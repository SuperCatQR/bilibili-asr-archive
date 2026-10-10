# Issues 实现与架构边界

本次实现位于独立分支 `codex/open-issues-implementation`，从 main 的 `effd9df473fca382133067eb1b7e04143ccbb849` 开始。范围为 #278、#279、#282、#285、#286、#287、#288；BW1000 部署测试 #289 不在本次范围。旧 [架构图](architecture.html) 及其 17 张时序图仍绑定原始固定提交，不能作为本分支新增功能的证据。

## 责任与依赖

SQLite 继续拥有任务、租约、尝试、来源事实、不可变转录、稿件、审核和发布事件。GPU 子进程、SDK、yt-dlp、模型绑定和文件产物都不能成为第二个进度来源。新的职责如下：

| 边界 | 模块 | 行为与约束 |
| --- | --- | --- |
| 平台身份与领域值 | `platform_identity`、`source_identity`、`source_metadata`、`source_video` | 平台、外部视频 ID、零基处理单元；平台适配器只交换类型化值 |
| 外部来源 | `sources/registry`、`sources/bilibili_source`、`sources/youtube_source` | SDK/yt-dlp 私有响应、URL、cookie 和异常文本留在适配器内部 |
| 采集用例 | `subtitle_ingest`、`metadata_ingest`、`metadata_refresh`、`source_workflow` | 候选字幕、观察字段、页事务、刷新和失败修复；写入沿用租约保护 |
| 数据契约 | `storage/archive_contracts`、`storage/sources` | 默认旧 `bilibili-v1` 不自动改表；`universal-v2` 只向显式空目标初始化或迁移 |
| 调度与执行 | `workflow_application`、`workflow`、`workflow_supervisor` | 按角色领取任务、heartbeat、drain、持有固定数量的子进程句柄并退避重启 |
| GPU 运行 | `asr/session`、`asr/runner` | 一个会话同一时刻一个请求；模型复用，任务证据、热词与输出隔离；超时/取消/崩溃销毁会话 |
| 模型位置绑定 | `runtime_bindings` | 只改变运行位置，冻结 profile 不变；匹配精确 revision、逻辑身份和文件清单 SHA-256 |
| 恢复 | `archive_snapshot`、`archive_recovery`、`storage/snapshots` | 完整字节校验、只读检查/计划、暂存库中断恢复、独立行级审计、安装后状态如实报告 |
| 稿件与发布 | `publication_content_v2`、`storage/editorial`、`storage/publication`、`publication_export` | 输入和内容显式登记版本；历史版本用旧 codec/template，新内容冻结来源元数据和语言规则 |

控制层不导入具体来源响应。来源模块不写数据库。推理子进程不持有数据库连接。父 worker 在提交转录、音频、稿件或发布事实前，仍需核对相同 job、owner、attempt 和未过期租约。动态 FTS 只是可重建缓存。

## #285：字幕为空与旧依赖

字幕选择对符合语言要求的候选稳定排序，并在候选数、整体时长及请求时长预算内逐个尝试。合法空 body/空文本与结构错误、传输失败、认证失败、限流分别记录。某候选为空可以尝试下一候选；认证和风控错误停止相应请求。全部合法候选为空属于“已观察到空内容”，不赋予“凭据已验证且来源没有字幕”的权威证明。未知错误不会被转换成没有字幕。

`JobExecutionError` 仅携带已审阅的错误码及有界标识/计数，executor 将其保存到失败 attempt 的 `result_json.diagnostic`。任意异常文本、cookie、签名 URL 和正文不能进入这个通道。

新的 `ALL` 规划中，subtitle 独立，ASR 仅依赖 audio。`BELOW_THRESHOLD` 保留显式质量策略：未知 score 不自动创造 ASR 任务。需要独立 ASR 时须显式选择 `ALL` 并提供冻结 profile。

历史数据库可先生成精确计划，再应用同一个计划 ID：

```bash
bili-asr workflow repair-dependencies --archive-root /data/archive --part-id 123
bili-asr workflow repair-dependencies --archive-root /data/archive --part-id 123 \
  --apply --expected-plan-id <上一条返回的plan_id>
```

这里只修复选定 part 上 queued/failed audio、ASR 的旧 subtitle 依赖；ASR 的 audio 依赖保留或补齐。运行中任务拒绝修复，成功/取消任务的边和历史 attempts 保留；`--retry-failed` 只重排失败的 audio/ASR。失败字幕可另用现有 `workflow retry --job-id ...` 精确重试。事务中重新计算计划身份，过期计划不应用。

## #286/#287：当前元数据与冻结来源

元数据刷新与首次发现分开。增量从第一页发现新视频；resume 沿用持久分页游标；针对 BVID/字段的刷新不回退正常游标。缺失、陈旧、强制模式和失败操作补抓使用同一预算与风控冷却。调度器是本进程、单采集协调器共享的限额，不宣称跨进程总限流。

字段的 present/empty/unavailable 语义区分“确实观察到空”与“本次没有获取成功”。失败不能抹去上次成功数据或推进成功观察时间。CID 冲突拒绝覆盖原处理单元。v2 保存字段观察与操作尝试，v1 继续已有 schema；v1 无持久操作账本时不能承诺跨进程 `refresh-failed`。

原始发布时间保存 Unix 秒，完整 UTC 时间为 `sourcePublishedAt`，未知值为 `null`；旧日期展示保留。旧 0 值可由有效观察补齐，已知发布时间只有显式刷新才能纠正。来源 metadata 的 observed time、creator、description、cover、category、tags 与稿件编辑字段各有所有者。安全 cover 只能是无凭据、无查询能力值的允许来源地址。

`SourceMetadataSnapshot` 冻结到 v2 editorial input 和 reader content。刷新当前视频标题或发布时间不会改动历史 input、edition、审核哈希或 release 文件。来源 tags 与稿件 tags 分开；人工编辑生成新完整 edition 并重新审核。

## #278：显式多平台目标与内容版本

`universal-v2` 增加 `source_creators`/`source_videos` 和处理单元外键。Bilibili 兼容表继续保存真实 Bilibili 事实，通过目标契约内的同步逻辑映射到中立核心。YouTube 使用真实 platform/external ID；其旧 BVID/CID 字段为空，不制造假 Bilibili 身份。处理单元 ID、零基 part index 与现有转录/任务外键继续有效。

```bash
bili-asr archive init --target-root /data/new-archive
bili-asr archive migrate --source-root /data/stopped-archive \
  --target-root /data/universal-archive --dry-run
bili-asr archive migrate --source-root /data/stopped-archive \
  --target-root /data/universal-archive --expected-fingerprint <已核对的fingerprint>
bili-asr archive migration-check --target-root /data/universal-archive
```

迁移源必须停写并 checkpoint；转换在独立暂存目标进行。迁移核对旧表的类型化单元格、原始 ID/rowid、冻结 JSON 和产物字节，而非比较新旧整库文件 SHA。固定旧源契约文件保持原提交身份；当前运行契约与迁移源验证分开。真实部署旧 archive 的正式切换仍需在该数据集上执行预检、备份、转换和核对。

历史 editorial input/content 在目标中显式登记版本 1，继续使用 `ai-draft-v1`/`publish-v1`。新输入/content 登记版本 2，使用多语言原语编辑规则、`ai-draft-v2`/`publish-v2`。稿件内容仍有七个顶层字段；v2 `source` 包含 platform、externalVideoId、partIndex、videoPartId、canonical URL 和完整冻结 metadata。包含 v2 内容的公开/草稿 catalog 使用 `schemaVersion: 3`；全旧内容仍输出版本 2。外部阅读站需支持版本 3 才能消费新增来源。

YouTube 依赖独立可选 extra 和匹配的 EJS、Deno 运行时；安装与版本检查见来源使用说明。访问上下文、caption 语言、原始语言、自动/人工、翻译属性及归一化算法写入来源证据。访问限制归为 `auth_failed`，下架或不可访问归为 `youtube_unavailable`，其他字幕与传输故障有有界分类；匿名和 credentialed 上下文分开记录。实时流和播放列表不进入单视频路径。

`BILI_YOUTUBE_COOKIES` 在每次适配器构造时解析为私有 cookie 文件位置，显式 import 参数优先；凭据重新配置由操作者负责，不保存在数据库中。YouTube 只有日期而没有精确时间戳时，发布时间保持未知，避免把 UTC 午夜冒充原发布时间。

## #279/#288：角色、持久会话与有界准备

部署角色可用 `workflow run --role asr|acquisition|editorial|cpu`，或用 `workflow supervise` 持有固定 slot。`cpu` 负责 subtitle/audio/publish；未实现的 index handler 不能被静默领取。drain 后停止新 claim，活跃任务在宽限内继续 heartbeat 和完成提交；超出宽限则终止推理，保留可重试任务证据。

每个 GPU 请求携带 protocol、session generation、request ID、job ID、owner、attempt、profile digest 和绑定身份。响应必须完全匹配。配置或绑定改变后重建会话；超时、取消、租约丢失和子进程故障会终止并回收，后续请求重新加载。父进程死亡保护负责回收模型进程及其进程组，Linux 另有内核父死亡信号。`--gpu-session oneshot` 保留故障定位和部署回退路径。

runner 的 trace 记录准备、解码、对齐、空档和总体 wall time；这些不是 GPU kernel 时间，也不证明设备持续满载。双遍只在同一任务内复用经内容身份核对的 waveform。可选 `--asr-prefetch` 最多提前准备下一块，使用独立 processor 与显式内存预算，无法安全复制或预算不足则串行；没有提前领取其他音频任务。

详见 [ASR worker 使用与限制](asr-workers.md)。真实 ROCm/CUDA 吞吐、显存峰值及生产四类角色切换需要设备上的对照测量，不能从离线故障测试推断。

## #282：快照、恢复计划与模型位置

```bash
bili-asr snapshot inspect --file /backup/archive.zip
bili-asr snapshot plan --file /backup/archive.zip --archive-root /data/restored
bili-asr snapshot restore --file /backup/archive.zip --archive-root /data/restored \
  --report /backup/recovery.ndjson
bili-asr snapshot doctor --archive-root /data/restored
```

v1 ZIP manifest 字段不变，所有文件、数据库契约、引用和 bundle 标记均验证。inspect/plan 只创建临时读取副本；plan 不创建目标，核对目标空目录/链接、整包身份、空间及本机要求。restore 再验证实际包和目标，暂存库中 running job 回到 queued，旧 running attempt 失败结束；attempt_count、已完成历史和 cancelled 终态保留。NDJSON 审计逐行记录 entity/identity/before/after/snapshot/reason，另记录恢复事务和目录安装。安装后的审计或目录同步失败返回 `installed: true` 与 warning，避免误报为未恢复。

doctor 使用 READ/query_only，不执行 DDL、不改 profile、不重排任务。`data_complete` 与 `runtime_ready` 分开；queued/running/failed 的派生状态包括可领取、依赖等待、定时等待、环境阻塞、坏 payload、需要人工重试及过期租约。该状态仅是报告，不新增持久调度枚举。检查 CPU/CUDA/ROCm、工具、所需依赖、模型可用性和凭据变量名称；不输出凭据内容，不承诺已在线验证授权或已成功加载模型。

`--runtime-bindings` 可用于 inspect/plan/doctor 和 worker。JSON schema version 1 的每一项分别声明 model/aligner 的 original、path、model_id、revision、manifest_sha256。checkpoint 的 `model-manifest.json` 声明 schema_version、model_id、revision 和 files（相对路径 → SHA-256）。必须包含 config 与权重，清单与实际文件一致，链接拒绝，缓存因文件状态变化失效。旧 profile 的精确 revision 和逻辑身份不足时拒绝绑定；改变 device、精度或推理配置需要新 profile。

## 验证范围

本地 WSL 的验证包括真实 SQLite 新旧契约、冻结旧 archive、typed row/rowid 与产物字节核对、完整恢复、双平台稿件到发布/导出的闭环、字幕异常分类、刷新账本、实际 spawn 子进程的超时/取消/崩溃/大 IPC/父死亡和并发准备。最终完整回归、覆盖门禁、构建安装和依赖审计结果另见交付记录。

可审阅的 [新增架构图](issues-architecture.html) 和 [七张时序图](architecture-sequences.md#本轮新增流程)
分别覆盖职责边界及全部新增条件路径；[图表凭据](issue-diagram-validation/README.md) 与
[WSL 验证记录](issues-validation.md) 记录固定源码、文件身份和实际执行结果。

离线 fixture 不等于真实账号、真实旧生产数据集或真实 GPU 吞吐验收。BW1000 部署测试按约定推迟；本次不执行生产进程替换或生产数据迁移。
