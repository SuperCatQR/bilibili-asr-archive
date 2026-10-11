# 未关闭 Issue 与架构调整评估

> 本文保留实施前的评估基线和验收建议。下文“当前”“尚未实现”均指 `effd9df473fca382133067eb1b7e04143ccbb849` 的状态；本分支的实现、命令和限制见 [Issues 实现与架构边界](issues-implementation.md)。

核对基线：`main` 本地提交 `effd9df473fca382133067eb1b7e04143ccbb849`，日期：2026-10-09（Asia/Hong_Kong）。本评估读取了当前未关闭的 #278、#279、#282、#285、#286、#287、#288、#289 及其正文/评论；按要求暂不评估 #289（海光 BW1000 部署验证）。#280、#281 已在 2026-10-09 合并，不能再按 issue #278 的旧评论判断为未合并。

当前 main 可以沿既有 CLI、应用用例、SQLite 与文件产物架构继续实现。最先应处理 #285 的字幕结果分类和生产诊断，再修 #286 的元数据传递和补抓更新，随后按测量结果推进 #287。#279 在既有执行器和 GPU 推理端口上增加 worker 角色与可终止会话；#288 的 trace 可先做，其常驻模型条件下的性能验收依赖 #279。#282 先复用快照实现交付只读 inspect/doctor/恢复计划。#278 需要真实旧归档 P0 验收、新目标 schema、显式迁移和 YouTube 单视频闭环，涉及范围最大。

下文 P0/P1/P2/P3 表示建议优先级，不是修改 GitHub label，也不等同于 #278 自己的 P0–P5 交付阶段。现状为源码证据，新增类型、模块、命令和版本均为提案，尚未实现。

| Issue | 建议范围 | 数据契约影响 |
| --- | --- | --- |
| #285 | 先修 typed 字幕结果、候选策略和错误传递，再审生产旧依赖 | 当前 workflow 首期可不改 schema；历史 gap 消费新空正文证据需新版观察契约 |
| #286 | 有效发布时间补抓/展示；再做冻结稿件元数据 | 首期有效值更新可沿旧库；nullable/观察历史/公开冻结字段和模板需版本化 |
| #287 | 先测量、运行内复用、刷新入口与 typed observations | 持久 freshness/failure ledger 需新版契约；并发是后续可选优化 |
| #279 | 任务筛选、drain、GPU session 协议/生命周期 | 可沿当前 jobs/attempts，不新增队列；诊断版本向后兼容 |
| #288 | trace、同任务 waveform 复用、深度 1 的 CPU 准备 | 不需改业务 schema；跨任务预取另有 ownership/预算协议 |
| #282 | inspect/plan/doctor 与恢复差异；再做模型绑定 | 只读阶段保留 snapshot v1；binding 与实际执行审计独立版本化 |
| #278 | 通用身份、显式新库迁移、版本分派与 YouTube | 必须新 schema/兼容 reader/converter/公共消费契约，是最大范围变化 |

## 当前边界

已经交付的能力包括：SQLite 是任务和业务事实的唯一来源；`workflow_planning.plan_producers` 生成 subtitle、audio、ASR 的依赖图；ASR 只依赖 audio（`src/bili_asr/workflow_planning.py:60`）；`WorkflowRepository.claim` 支持按 `JobKind` 领取并用 lease/attempt fence 保护结果（`src/bili_asr/storage/workflow.py:195`）；CUDA/ROCm 有一次性 spawn 子进程和硬超时（`src/bili_asr/asr/runner.py:57`）；CPU runner 按 profile 在一个应用进程内复用；快照 restore 会在目标内收尾 running attempt、清理租约并重新排队（`src/bili_asr/storage/snapshots.py:297`、`src/bili_asr/services/archive_snapshot.py:335`）；`ContentRef`、`MetadataSource`、`SubtitleSource`、`AudioSource` 已建立来源端口，但当前持久化 schema、文件 key、出版内容契约仍是 Bilibili 专用。

生产 issue 中的专用 worker、常驻 GPU 子进程等观察来自仓库外脚本，不能算作 main 已交付功能。main 的 `WorkflowApplication.run` 仍只提供通用 worker 或 `--only-editorial`（`src/bili_asr/services/workflow_application.py:92`），GPU 默认路径仍调用一次性的 `transcribe_with_timeout`，而不是跨任务复用模型。文档中的验证数字是离线 WSL/fixture 证据，不能替代真实 Bilibili、GPU、付费模型或完整旧归档验收。

## Issue 评估

### #285：字幕正文为空时回退 ASR（P0）

**事实和缺口。** gateway 模块的顶层函数 `_normalize_subtitle_segment` 同时丢弃空文字行和非正/倒序时间区间，`BilibiliApiGateway.fetch_subtitle_segments` 在规范化结果为空时抛 `GatewayNotFound`（[行转换](../src/bili_asr/sources/bilibili_api_gateway.py#L616)、[正文获取](../src/bili_asr/sources/bilibili_api_gateway.py#L1014)）；`SubtitleIngestor._acquire_part` 只读取一个候选，把已列轨道的正文不可用记为 `subtitle_body_unavailable`（[采集服务](../src/bili_asr/services/subtitle_ingest.py#L494)），随后 `workflow_runtime.subtitle` 抛普通 `RuntimeError`。执行器保存异常类型，因此具体错误码丢失。不能仅凭 `len(segments) == 0` 判断确定空正文：原文全空、时间损坏和轨道消失需要不同结论。

Issue 中“字幕成功后才允许 audio/ASR”与当前 main 不符：规划器明确只给 ASR 加 audio prerequisite，且已有回归测试 `tests/test_workflow_control_plane.py:81` 证明字幕失败不阻塞 ASR。仍需只读核对生产库的 `workflow_job_dependencies`，因为 `storage/workflow.py` 的幂等规划只插入缺失依赖，不会删除历史错误依赖。

独立执行不等于所有 policy 都创建 ASR：`below-threshold` 在无质量分数或已达阈值时只建 subtitle。真实回退先确认目标已有 audio/ASR 及冻结 profile；否则由应用显式对该 part 规划 `all/selected`，或新增有明确身份和验收的 `on-unavailable` 策略。不能把字幕成功结果本身说成自动触发了不存在的 ASR job。

**实现。** 第一阶段不改旧 `acquisition_attempts` CHECK 和 `v_missing_audio`。在 gateway/adapter 返回结构化 `SubtitleBodyRead`，区分有效正文、合法空文字/空 body、时间或结构异常、传输/轨道不可用；单独的纯 `rank_candidates` 保持当前语言偏好、CC/AI 和稳定轨道次序，不能直接使用已存 transcript 的另一套排序。限制候选数和总耗时。认证和风控停止；其他候选失败可以继续寻找有效正文，但有任一不确定或未检查候选时不能声明“全部为空”。

所有合规候选确实读取为合法空正文时，用已有 `no-subtitle/error_code=NULL` 表达本次观察，同时保持 `credential_verified=0`、`absence_verified=0`；workflow result 另存 `availability=visible_candidates_exhausted` 及有界每轨证据。一个 acquisition `(run_id, part_id)` 只写一条汇总，不能为每轨重复写同一主键。这个结果不进入旧的认证空清单 gap 视图，当前独立 audio→ASR 工作流仍可继续。失败改用 `JobExecutionError(error_code, safe_details)`，由执行器和 fail port 显式写入白名单诊断；不存异常字符串、签名 URL 或秘密。

第二阶段若产品要让“正文全空”参与历史 `v_missing_audio`，再设计版本化 subtitle observation 表和新 schema/view；不能把 `empty body` 映射成 `not_found` 或修改旧冻结视图来绕过证明条件。

**生产修复。** 先读取该 part 的真实 job/attempt/依赖、部署构建版本和外部重试策略。main 执行器没有 issue 所述的“三次自动退避”策略，不能假定部署与 main 相同。若存在旧字幕→audio/ASR 边，停相关 writer 后生成修复计划，只处理确认属于旧规划且尚未运行的边，重新校验 audio prerequisite，并在事务内记录差异；保留四次失败，精确 retry 失败的字幕 job。不要全局删除 subtitle dependency 或复活 cancelled。

**验收。** 覆盖首轨空、第二轨有效；唯一轨道合法空；所有候选合法空；非正时间、NaN、shape error、认证/限流/网络/签名/轨道消失；候选预算截断；安全诊断；保留旧四次 attempts；新音频和 ASR 可领取。若做历史依赖修复，验证 dry-run、活动任务拒绝、旧边精确变更、恢复后可 claim。空字幕不得产生 transcript 或“无声”结论。

### #286：B 站源视频元数据补全（P1）

**事实和缺口。** gateway 已读取 `created`，回退 `pubdate`（`src/bili_asr/sources/bilibili_api_gateway.py:187`），`VideoRecord` 也有 Unix 秒级 `pubdate`。但 `MetadataRepository.upsert_video` 的冲突更新只更新 `aid/title/updated_at`，没有更新 `pubdate`（`src/bili_asr/storage/metadata.py:102`），所以历史缺失或错误发布时间无法通过重抓修复。展示层 `formatting.pubdate_utc` 只输出 UTC 日期，`render_publish_v1` 也没有发布时间。

**实现。** 先沿当前契约修 `pubdate` 的更新：保留已有正值；在显式补抓确认来源后补首次无效值/纠正旧值；失败、缺字段、0 不能覆盖已知有效值。gateway 当前缺 `created` 和 `pubdate` 会报 shape error、DTO 必填整数、SQLite `pubdate NOT NULL`，因此真正 nullable 的未知时间、持久化来源/新鲜度需要单独的新契约与迁移，不能悄悄用 0 冒充缺失。读取端可以将历史 0 显示为 unknown，同时保留原始事实。

新增纯 `SourceMetadataSnapshot` 和 ISO formatter，区分原始 Unix 秒、观测来源（list.created/list.pubdate/detail.pubdate）、源发布时间、采集时间和本项目 release 发布时间。保留旧日期 formatter，新的字段提供 RFC3339 UTC `Z` 或显式 `+08:00`，不能依赖主机时区。现有冻结 editorial metadata 只有 BVID/index/title；publication content/source 的字段集合也严格固定。公开稿件要带时间时必须新增版本化冻结 source metadata、content codec 和 renderer，再创建新 edition、审核及 release；仅改 `publish-v1` 或在渲染时读实时数据库会破坏旧字节/身份。

标题、UP 主/UID、BVID/AVID、链接、简介、P 信息、时长、封面、分区和原始 tags 先进入只读 metadata projection；人工 edition tags 保持独立。公开封面 URL 需受限来源/协议策略；公开/预览 catalog 的严格 schema 也必须明确新版本与消费方兼容。原始时间正确的历史 bundle 可显式重新导出/发布，缺失或错误的时间需定向补抓，不靠 resume 自动回扫旧视频。

**验收。** 普通视频、多 P 视频、缺失发布时间、UTC/北京时间跨日、重复抓取覆盖缺失值；比较 gateway→SQLite→metadata search→bundle/frontmatter→publication 的每一跳。发布历史、content hash、旧导出字节和原始 source JSON 保持不变。补抓失败必须保留旧值并记录观察失败。

### #287：增量抓取、请求复用和失败补抓（P1/P2）

**事实和缺口。** 当前 `_collect` 仅在缺 aid 时补详情，再逐视频获取分 P 和 tags（`src/bili_asr/services/metadata_ingest.py:305`），已做页内 summary/parts 去重、运行内 tags LRU（256）、页级事务、游标、有限重试、节流和 `fetch-tags` 定向补抓；不是每个视频固定重复取完整详情。缺少跨运行字段级新鲜度、一般操作级失败记录和统一预算。

必须先修清楚四个前提。第一，resume 使用 `cursor.next_page`，完成扫描的游标停在末尾空页；resume 与发现头部新投稿是不同操作，增量入口应重新扫描前部、保留重叠窗口并周期全量核对。第二，tags 的 `None + gateway.tag_error_code` 是共享可变旁路，SDK proxy 设置也是包全局；在并发前改为 `TagRead` typed result 并明确代理/凭据隔离。第三，`upsert_video_details` 将部分观测作为整行快照，会清空未提供字段；按字段刷新需要区分 missing、explicit_empty、unavailable、denied 和 present，不能只 `COALESCE` 而永久保留已撤回值。第四，part 冲突更新 title/duration 却保留 cid；重新获取时若 `(bvid, index, cid)` 不一致，应报告身份冲突并显式处理，不能把旧音频/转录/稿件绑到新的分 P 内容。

**实现。** 先记录每 operation 请求数/耗时/重试、复用命中、新增/更新/缺失，再建立 `MetadataRefreshPolicy` 纯策略，按字段声明 TTL、缺失补齐和 force。列表已有值优先复用；gateway 的 video detail 响应可在同一视频/运行内复用，向上只交付自有 DTO。请求缓存 key 使用 platform、external id、operation、凭据作用域和参数；response digest 是缓存结果身份，不能当作发请求前才能知道的查询 key。失败不缓存为成功，跨运行复用明确 TTL、来源和 observed_at。

共享 `RequestScheduler` 在 adapter 下处理限速、单请求超时、重试和总预算；credential scope 是脱敏内部身份，不能存凭据内容。每进程限速不能宣称覆盖所有 worker；初期限定一个采集协调进程，有多进程需求时明确跨进程协调范围。412/风控应中止或长冷却；429 采用有界退避。先有界串行，再依据基准试少量并发；事务连接继续单线程使用，网络在事务外。分页完成仍按 API/page/cursor 证据，服务端总数变化和置顶/重排都要复核，不能仅靠已见 BVID 提前终止。

操作级观察和定向补抓由 storage+应用层负责，区分 success_nonempty、success_empty、unavailable、auth_failed；保留现有 tags 的降级保护。仅需要单次运行复用的首期可不改 schema；持久化跨运行新鲜度/失败 ledger 需要明确新契约。列表页重抓仍原子提交该页和游标；独立补抓不能借失败请求推进 page cursor。不要为整个采集另建 workflow 调度器或无界全页 JSON 缓存。

**验收。** 首次全量、无变化重跑、末尾空页后头部新增、置顶/重排/重复、缺字段补抓、中断续跑、详情超时/限流/tags 失败；partial/missing 不误清旧值，explicit empty 能清除，cid 变化不串绑。比较请求数、命中率、耗时、覆盖率和失败项。并发仅在 typed result、代理作用域和共享 scheduler 有界时引入；总预算限制 SDK 重试与应用重试叠加，验证取消、页游标原子性和失败请求不被记为新鲜成功。

### #279：专用 ASR worker 与可终止常驻会话（P1）

**事实和缺口。** `WorkflowExecutor` 已支持 `kinds` 过滤和独立 heartbeat（`src/bili_asr/workflow.py:46`），所以可以先实现 worker 角色；但 GPU `transcribe_with_timeout` 每次任务都 spawn 新进程、构造新 `ASRRunner`，没有跨任务会话。现有 `RunnerFactory`/`TimeoutTranscriber` 端口分别表达 CPU runner 与一次性 GPU 调用，无法表达会话重建、配置切换或父子进程归属。

**实现。** CLI/应用组合根先提供重复 `--kind` 或映射到固定 kind 集合的 `--role asr|acquisition|editorial`；保留 `--only-editorial` 兼容，筛选进入现有 claim，启动时拒绝未注册 handler 的 INDEX。单机角色配置持有槽位上限；部署配置决定 GPU 数量，不能在库里硬编码生产的“两路”。`WorkflowExecutor` 在任务边界读取 drain token，停止新 claim 并让当前 job/heartbeat 正常完成；新增 drain 等待期限和超时处置，不借数据库触发器实现。

新增 `AsrInferenceSession` 端口表达 `transcribe(request, deadline, cancellation)` 和 `close/terminate`。请求/响应包含协议版本、session generation、request id、job id、owner、attempt_count、profile digest，初期输入仍为精确校验的音频路径和 reference text，不依赖 #288 的 prepared waveform。每路只持有一组活动 GPU 模型；完整配置摘要或后续 runtime binding 身份变化就重建。模型可复用，热词、字符、coverage、diagnostics 和输出必须每请求重置。子进程只做推理并返回结果，父进程负责 heartbeat、权威终态和 `JobCommitGuard` 提交。

当前 heartbeat 失去 lease 后只停止续期，GPU 会一直执行到返回或 timeout；会话实现须把取消/失权通过父进程 token 送达，销毁在途子进程并丢弃迟到响应。持续排空 IPC 后再等待退出，避免大 segments 堵塞；异常/超时/崩溃清理并下次重建。正常 close、drain、父进程异常退出及强制退出的子进程归属需要显式机制和平台验收，不能仅凭 `finally` 保证无孤儿。一次性路径保留为可配置回退。

进程补槽、启动退避、drain 和进程归属放在部署/组合根；优先由既有进程管理能力按拥有的槽位处理，确需仓库 supervisor 再单独交付，不用宽泛 argv/PID 扫描误计 multiprocessing 子进程。SQLite 不承担 GPU 会话恢复状态。现有 diagnostics 已有 `model_reused` 和阶段 timings，应扩展 session 重建原因、任务间等待和音频秒/墙钟；新增版本保持旧 evidence 可读。

**验收。** 两个 ASR worker 只领取 ASR，CPU worker 不领取 ASR；同一 profile 连续两任务第二次复用，配置变更/超时/取消/崩溃/父进程退出均重建且无孤儿/迟到提交；任务输出、coverage、双遍诊断和 attempts 独立；长窗口以音频秒/墙钟、P95、失败率和显存峰值对照，不能只看 GPU 利用率。

### #288：ASR 任务内 CPU/GPU 重叠（P2，依赖 #279）

**事实和缺口。** 当前 `ASRRunner.transcribe` 先整段解码/重采样/切块，再逐块同步 processor、decode、align；`two_pass_transcribe` 会再次调用 `transcribe`（`src/bili_asr/asr/runner.py:700`）。已有 diagnostics 记录 `audio_prepare/split/decode/align/total`，但没有每阶段起止和输入等待事件，因此 issue 的生产低点只能是待验证解释。

**实现。** 先增加单调 trace：任务/块/阶段起止、CPU 输入准备、数据传输、decode/align、后处理、等待和资源峰值。现有阶段为墙钟时间，不能直接当 GPU kernel 时间；不能在两个进程间直接比较未校准的 monotonic timestamp，profiling 也不能每块强制同步而显著改变吞吐。采样与 trace 对齐后再选择优化。

先在同一 runner 内提取“CPU 输入准备→GPU 调用→CPU 后处理”，试深度 1 的 next-chunk prefetch，验证 processor 并发安全；只重叠 CPU 工作，不并发使用同一组 GPU 模型。可另做同一双遍任务的 prepared waveform 复用，以源文件身份、采样率/重采样参数、分块策略校验，两个 pass 的热词和结果仍独立。

跨任务预解码最后做：它涉及下一任务 ownership、取消/失权、运行期限及额外 heartbeat，不能只 peek 一个 queued job 就开始执行。先决定由现有 executor 显式预约下一任务并续期，还是仅以只读文件身份缓存且 claim 后再次验证；在协议与资源预算未定前不启用。每路最多一份，预算包含解码前原始声道/采样率数组、16 kHz waveform、processor 输入和 RF64 临时盘，不仅是最终 mono 数组。长音频超过预算回退串行。开关默认串行，收益不足立即回退。

**验收。** 短/长/多块、单遍/双遍前后对照处理音频秒/墙钟、P50/P95、输入等待、峰值 RAM/VRAM/临时盘、失败率和覆盖区间；验证取消、超时、lease、进程退出和 RF64 清理。用 feature flag 可回退串行。

### #282：状态保存、恢复和换机续跑（P1/P2）

**事实和缺口。** `snapshot save/check/restore` 已保存数据库、音频、bundle、AI 稿件和所有历史 release，并在恢复时处理 running 记录；但包不含模型/环境/凭据，恢复后没有统一的“数据完整”和“运行环境就绪”结论，也不能安全修改冻结 profile 路径。

**实现。** 第一阶段在 `services/archive_recovery.py` 编排 `snapshot inspect/plan` 和离线 `snapshot doctor`，使用快照模块公开的 verified snapshot reader，而不是导入 `_validate_into` 私有函数。`RuntimeRequirements` 从实际未完成 DAG、冻结 profile 和包构建元数据按白名单派生；Git SHA 在安装包内可缺省，兼容判断仍以契约和能力为准。report 区分 `data_complete`、`ready_now`、`waiting_dependency`、`blocked_environment`、`manual_retry`、`cancelled_terminal`；可执行计数须遵循 available_at 和 prerequisite 条件，不能把全部 queued 算 ready。

新增后端相关探测：CPU、CUDA、ROCm 的检查不同；当前 `check_asr_env.py` 专用于 AMD WSL，不能套给所有平台。凭据按实际操作需求检查，Bilibili 公共 metadata/audio 不必一律要求 Cookie，editorial 才要求对应 API key；离线只报已配置/未验证，不宣称认证有效。检查不安装依赖、不下载模型、不输出秘密、不启动 worker。第一阶段保持 snapshot v1 严格字段集合，需求在检查时派生；新增 manifest 字段另走新版本。恢复差异报告在 staging 中记录每个 job/attempt/run/model call 前后状态，最终整体安装仍由 snapshot 服务负责；报告放显式私有输出位置，不能塞入不支持的新产物目录。

第二阶段新增执行层 `RuntimeBinding`，将 profile/model 的可验证逻辑身份映射到本机模型/aligner 路径；模型名称相同或目录名相同不能证明权重一致。旧记录缺 identity/revision/摘要证据时返回 `model_identity_unverified`，不能自动绑定。运行时分离历史 profile 与实际加载路径，保留原 digest，同时审计 resolved model、binding 身份、加载环境；同一 binding 身份进入 #279 的会话缓存 key。变更模型、精度、设备或推理参数使用新 profile 和显式规划，不能在 binding 中偷改参数。

恢复/运行前重检包、目标、profile 和 binding，处理检查后的环境变化。已失败任务可显式 `workflow retry`；已取消任务是终态，当前 retry/plan 都不复活（[实现](../src/bili_asr/storage/workflow.py#L507)、[回归](../tests/test_workflow_cancellation.py#L160)），不能把 #282 原文“失败/取消均可 retry”当作现有能力。换机明确停止旧 writer 再启动新 writer；两个独立 SQLite 副本的 lease 无法互相排斥。初版保持停写保存，不承诺 GPU 中间态/未提交 API 响应续接。

**验收。** 同一快照原机/缺模型机/缺凭据机/不同 GPU/坏文件/非空目标/恢复中断；成功任务不重复，失败/取消不自动重试，running 差异可解释，报告不含 secrets，源归档不被修改。

### #278：YouTube 接入与旧 Bilibili 保真迁移（P3，前置事实未完成）

**当前进度。** #280/#281 已合并：固定旧 Bilibili 源契约、只读 `migration-preflight`、逐表 rowid/类型摘要和受管产物检查已存在；`ContentRef` 与三类来源 port/Bilibili wrapper 也已进入 main。#278 的评论仍写着“PR 未合并”，那是历史状态。方案文档仍 pin 在 `9b28957`，只能作为计划，不能当作当前代码身份；真实完整旧归档、目标 schema、转换器、版本分派、YouTube adapter 和阅读站兼容仍未实现。

现有 `renderer_for` 已按 template version 分派旧 renderer，本评估所指缺口是新增通用 input/content/catalog 的版本以及新目标 schema 分派，不能将已有历史模板验证说成不存在。

“更新计划状态”不等于重定冻结源：`migration-source-bilibili-v1.json` 的 `9b28957` 是刻意固定的旧契约，必须原样保留。`migration_preflight` 明确返回 `conversion_performed=false`、`target_created=false`，预检通过不表示数据已经迁移。

**实现顺序。** P0 先用真实归档只读盘点固定源版本、双 artifact root、规模、WAL/lease、历史文件和代表性 fixture；fixture 不能只由当前 writer 重新生成，否则可能掩盖旧 hash/rowid/字节差异。P1 新增 `platform + external_id` 通用核心身份和平台扩展表，保留旧 Bilibili `bvid/cid/mid` 及 `video_part_id/job/profile/transcript/revision/edition/release` 身份；所有新 schema/codec/template/catalog 版本显式分派。P2 新增离线 converter：独立空目标、按外键顺序导入、保留必要 rowid、复制原始字节、完整文件/数据库/冻结 JSON/hash/审核/release 校验，生成 id mapping、恢复差异和不可变 migration report；普通命令拒绝跨 schema 自动升级。P3 先做 Bilibili 新目标演练和旧出口兼容，再做 P4 YouTube 单视频：静态 adapter registry、URL→ContentRef、metadata/subtitle/audio、匿名/认证/自动翻译/无字幕状态分离、WebM/Opus 实际后缀和 ASR 多语言；P5 才做显式切换、观察、回滚和频道/播放列表。

迁移不能把 YouTube ID 塞进 bvid/cid/mid，不能向旧 raw JSON、marker、prepared_json、publication content 或旧 hash 添加 `platform` 后覆盖原数据，不能重新渲染已发布 `publish-v1`/`ai-draft-v1` 以“完成迁移”。旧库与新库独立保留；新库写入后的回滚只能切回旧服务并保留新库快照，不承诺双向合并。

迁移 reader 的 `text_factory=bytes` 用于指纹保真；converter 绑定时仍须保留 SQLite TEXT/BLOB 类型，不能把所有 bytes 当 BLOB 写入。已有 part/其他内部 ID 与必要 rowid 保留，新增 creator/video 映射显式审计，校验新 ID 分配不重用。Bilibili 旧 key 原样保留；YouTube 大小写敏感 ID 用平台前缀和完整摘要生成可移植 key，避免 Windows 大小写碰撞。新版 sources DTO、选择器、gap view、搜索、冻结稿件与 catalog 消费都必须改为通用身份；现有 `MetadataSource` 只抽象 get_parts，还需单视频信息导入和独立批量发现端口。播放列表不当作分 P，章节不当作独立视频。

代码扫描必须覆盖通用核心之外的隐式平台假设：`search_index/store.py` 按 `bilibili_users` 识别归档；字幕 work item 仍构造 Bilibili 身份；历史 `read_revision/read_edition` 仍对实时 bvid 做归属校验。新目标通过映射读取旧 Bilibili 字段，不能改冻结 JSON。provider registry 放在组合根，storage 只依赖应用 DTO；源状态需包括可访问性、原语言/自动翻译、提取器版本和确定空/不确定失败，既有两个 access 字段不足以表达所有新平台观察。

迁移恢复复用 snapshot 的事务与校验机制，另用明确的 migration recovery reason 和对象级审计；不能直接调用当前恢复函数后把 `snapshot_restored` 当作迁移报告。运行库、旧/新 snapshot 的结构校验需要有界 contract registry 分派，不能只依赖当前 SQL resources 推导所有历史契约。新库稿件 template CHECK、frozen content/input codec 和读取站 catalog 分别增加版本，并保持旧 reader/renderer 的原字节行为。

yt-dlp 是 #278 已选择的适配器依赖。[官方 EJS 指南](https://github.com/yt-dlp/yt-dlp/wiki/EJS)要求 YouTube 提取准备支持的 JS runtime 和匹配的 EJS 依赖；应随 optional extra/lockfile 固定组合，doctor 检查，程序启动不升级。具体版本、字幕转换和部署环境仍待小样本验收。[YouTube 官方 captions.download](https://developers.google.com/youtube/v3/docs/captions/download)要求相应授权与视频编辑权限，不能作为任意公开视频的通用替代字幕通道。阅读站是独立仓库，公共/预览新 catalog 的兼容属于外部交付依赖。未知旧 schema/历史格式单独加 reader，不能让新 initializer 猜测；旧库拒绝提示也应改为显式迁移指引，而非重采暗示。

**验收。** 代表性旧归档逐表/逐文件/逐 hash/逐历史状态保真；未知 schema、WAL、活动 lease、链接、路径碰撞、缺文件、坏 marker、非空目标、磁盘不足和复制中断均拒绝且不改源。迁移后重复 plan 不复制 job、不重跑 ASR/AI、不复活 cancelled；YouTube 人工字幕、自动字幕、无字幕 ASR、多语言、WebM/Opus、限流、取消、混合搜索与导出分别通过。

## 依赖顺序和架构决策

| 工作 | 必需前置 | 可并行或可复用的工作 |
| --- | --- | --- |
| #285 修复 | 来源结果分类与真实生产依赖审计 | 与元数据、GPU、doctor 无代码先后依赖 |
| #286 存储/展示 | 字段语义；公开新字段需冻结内容和 renderer/catalog 新版本 | 首期当前库有效时间补抓可独立修；新元数据观测契约与 #278 统一 |
| #287 请求复用 | 请求基准和明确 freshness/失败策略 | 运行内复用可先做；持久 ledger 与 #286 观察事实共用 |
| #279 角色/会话 | 现有 kind-filter 与精确 attempt fence | 不依赖新平台、doctor 或元数据刷新 |
| #288 trace/预取 | trace 可独立做；常驻会话基准依赖 #279；跨任务预取须完成 ownership 协议 | 同任务双遍准备复用可单独交付 |
| #282 inspect/doctor | 公开快照验证入口、只读 runtime requirements | 不依赖 #278；binding 与 #279 共用实际执行身份 |
| #278 新平台 | 真实旧源/冻结 fixture、新 schema 与 codec、converter、出口消费兼容 | 不强制依赖 #279/#287；可复用字幕分类、元数据观察和 doctor |

保持四条稳定边界：纯策略（轨道选择、刷新策略、身份/版本）不导入 SQLite；应用服务负责编排和外部副作用；repository 负责事实、lease 和提交 fence；组合根负责平台/worker/runtime 装配。不要引入第二个调度器、Redis 或“守护器数据库”；跨平台迁移是离线工具，不是普通启动时的隐式 ALTER。新的运行时会话、环境 binding 和 metadata observation 都应有版本化端口/DTO，不能用可变全局配置或宽泛 JSON 分支侵入已有提交守卫。

建议工作分为四组并行推进：生产正确性组 #285；来源数据组 #286→#287；推理运行时组 #279→#288；恢复与演进组 #282 只读阶段及 #278 P0 事实盘点。新 schema 设计、持久 observations/ledger、冻结内容 v2 和 converter 由同一数据契约责任人整合，不能多条分支各改一次互不兼容的契约。#278 内按 P0→通用核心/历史分派→converter/快照→Bilibili 出口演练→YouTube 单视频→切换/批量发现推进，每阶段都有独立验收门槛。

运行 session 检查必需契约并容许明确支持的历史布局；snapshot 校验当前必需结构并拒绝未知 trigger；固定源 preflight 拒绝不受支持的权威对象，只容许明确登记的 FTS 派生组。这三者不是同一宽松程度的结构检查。添加“可选”表也可能使固定旧源 reader 拒绝，改变必需结构可能使旧 snapshot 不兼容，因此 schema、snapshot 格式、frozen content、renderer 和 catalog 分别设计版本，不能以一个总版本号覆盖所有变化。回归保留旧读库不做 DDL、历史摘要/字节、取消/租约边界、staging/marker、检索和导出。

真实源盘点是承诺迁移支持范围、全量演练与正式切换的门槛，不妨碍先开发协议、目标 schema 或代表性测试。新旧整体 DB SHA 不应相等：结构变换和有审计的中断恢复会改变数据库字节，保真验证针对原业务对象、冻结 JSON/摘要、类型和值、ID 映射、状态允许差异和原文件字节。大归档还须测 RSS、扫描耗时和峰值磁盘；当前预检逐文件流式哈希，但清单及部分校验仍在内存，不能称全链路常量内存。

## 证据和限制

本评估通过 `gh` 实时读取 issue、评论、PR 合并状态和 main SHA；本地 main 与 GitHub API 均为 `effd9df`。#285 的真实四次失败与 #279/#288 的生产吞吐/显存是 issue 提供的现场证据，本轮没有连接生产实例复测。所有新增命令和行为仅为设计提案，本轮只写评估文档和索引。

本次未修改产品源码，也未重新运行产品测试。此前本地 WSL 验证见 [架构验证记录](architecture-validation.md)，证据目录 `/home/chosenecho/architecture-boundaries-validation-20261009` 存在；当前 main 的 GitHub CI run `37935292477` 为 success。这些证据支持当前基线，不验证本文待实现功能。后续小改动在本地 WSL 运行对应真实应用链回归；协议/schema/迁移改动补进程故障、历史 fixture、安装包和完整回归；GPU 收益和真实旧归档保真另需专项实测。

## Issue 链接

- [#285 字幕空正文](https://github.com/SuperCatQR/bilibili-asr-archive/issues/285)
- [#286 源元数据与发布时间](https://github.com/SuperCatQR/bilibili-asr-archive/issues/286)
- [#287 抓取优化](https://github.com/SuperCatQR/bilibili-asr-archive/issues/287)
- [#279 ASR worker 和常驻推理](https://github.com/SuperCatQR/bilibili-asr-archive/issues/279)
- [#288 CPU/GPU 重叠](https://github.com/SuperCatQR/bilibili-asr-archive/issues/288)
- [#282 保存、恢复、换机](https://github.com/SuperCatQR/bilibili-asr-archive/issues/282)
- [#278 多平台与迁移](https://github.com/SuperCatQR/bilibili-asr-archive/issues/278)
- [#289 BW1000 部署验证，本轮排除](https://github.com/SuperCatQR/bilibili-asr-archive/issues/289)
