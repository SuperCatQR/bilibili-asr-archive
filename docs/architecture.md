# 当前架构

本分支新增实现见 [Issues 实现与架构边界](issues-implementation.md)：显式 `universal-v2` 与 YouTube 来源、输入/内容版本 2、候选字幕、观察驱动元数据刷新、恢复检查/模型绑定，以及持久 GPU 会话与 worker supervision。以下 19 张既有图仍描述原固定代码提交，不自动随本分支代码更新。

新增能力的交互视图见 [多平台归档的控制与持久化边界](issues-architecture.html)、
[新增七张时序图](architecture-sequences.md#本轮新增流程)。固定源码和自动检查的实际范围见
[本轮图表凭据](issue-diagram-validation/README.md)，代码验证见 [WSL 验证记录](issues-validation.md)。

本页、[全景架构图](architecture.html)、[AI 与出版专题图](ai-proofreading-architecture.html)和 [17 个完整时序流程](architecture-sequences.md)统一描述本次架构边界修复的固定代码提交 `5d7a57e201564a10dec7a360b2ef8f7874dc51a7`，共 19 张图，核对日期为 2026-10-09（Asia/Hong_Kong）。各 JSON 的 `meta.repository.revision` 绑定同一源码身份；这是从 main 开始的本地修复提交，不代表远端 main 已包含修复。全部命令、源码模块、SQL 表/视图见 [源码与覆盖清单](architecture-sources.md)，图的源码证据、自动检查与文件身份见 [验证记录](architecture-validation.md)。

图中 SQLite 节点表示同一个 archive.db 内的逻辑表组。后续变化需按 [维护指南](architecture-maintenance.md)重新核对；固定提交身份不自动代表未来版本。在该历史提交中，其他平台落库与迁移转换仍为后续范围；本分支的实现见本页开头所链接的新说明与图表。

## 系统边界与模块责任

项目是 Python 3.12+ CLI，安装入口为 `bili-asr = bili_asr.cli:main`。SQLite 保存来源事实、不可变转录、任务/尝试、AI 修订、完整出版版本与事件；音频、bundle 和稿件保存为受限文件。没有 HTTP 应用服务、Redis、外部消息队列或另一套 JSON 调度器。

CLI 解析命令，声明文件与数据库访问模式并调用应用用例；WorkflowApplication 组装 repository、source adapter 与 handler；纯规划器生成依赖描述，repository 保存持久身份和状态转换，JobCommitGuard 在同一连接上保护权威提交；service/handler 执行网络、推理与文件操作。WorkflowExecutor 依赖控制协议，每次顺序处理一个 job，多 worker 可连接同一数据库。短期客户端和 CPU 模型缓存可以留在进程内，恢复进度始终来自 SQLite。

| 层 | 代码入口 | 责任 |
| --- | --- | --- |
| 命令与组合根 | cli/parser.py、registry.py、main.py、命令模块 | 参数、产物访问策略、维护锁、分派、输出和退出码 |
| 应用用例与访问生命周期 | services/workflow_application.py、archive_session.py | 每次调用的依赖组装、READ/WRITE/BOOTSTRAP/MAINTENANCE、schema 契约、连接和维护锁生命周期 |
| 外部访问 | platform_identity.py、sources/protocols.py、sources/bilibili_source.py、bili_client.py、deepseek.py | ContentRef、采集端口、Bilibili ID/凭据适配、SDK/HTTP、pacing、CDN 下载、有界错误 |
| 采集服务 | services/metadata_ingest.py、video_tags.py、subtitle_ingest.py | 分页、详情、parts、标签、轨道选择和获取证据 |
| 工作流控制 | workflow_models.py、workflow_planning.py、workflow_payloads.py、storage/workflow.py、storage/workflow_selection.py、workflow.py | 中立任务模型、纯 JobSpec 规划、payload 校验、持久化、幂等 job、claim、lease/heartbeat、attempt、cancel/retry |
| 提交与共享纯策略 | storage/job_commit.py、transcript_selection.py、cue_models.py、publication_content.py、publication_identity.py | 租约提交保护、转录总排序、字幕 cue 和稿件身份/内容契约，避免底层反向导入业务服务 |
| 原始生产 | workflow_runtime.py、asr/、archive.py | 音频、ASR、不可变转录、择优 bundle 与 lease 保护提交 |
| AI 派生 | editorial.py、editorial_runtime.py、storage/editorial.py | 冻结输入、分块、调用审计、校验、检查点、revision、双稿 |
| 人工出版 | publication.py、publication_tags.py、storage/publication.py | 完整 edition、精确审核、双 head CAS、release、替换/撤回 |
| 消费与检索 | workflow_projection.py、search_index/、publication_export.py | 只读投影、派生 FTS、公开/预览/私有快照 |
| 维护迁移 | archive_maintenance.py、artifact_inventory.py、services/archive_snapshot.py、services/migration_preflight.py、storage/snapshots.py、storage/migration_source.py、storage/migration_artifacts.py | 维护协调、公共文件盘点与路径规则、ZIP 保存/恢复、固定旧源预检 |

外部依赖是 Bilibili SDK/API/CDN、可选 DeepSeek HTTPS API，以及本机 Qwen3-ASR/ForcedAligner 权重和 CPU/CUDA/ROCm。阅读站属于独立仓库，本仓库提供静态内容契约；页面、路由、远端部署和缓存刷新不由本仓库执行。

## 命令、启动、schema 与访问锁

当前注册 16 个顶层命令：fetch-meta、fetch-tags、workflow、snapshot、archive、status、runs、coverage、verify、search、search-index、check-asr-env、export、publication、editorial、dedup。子命令和对应流程见 [命令覆盖](architecture-sources.md#命令覆盖)。旧 docstring 中的 reading-*、独立 proofread、publish-transcripts 名字不能当作当前 CLI。

CommandSpec 分别声明 ArtifactPolicy.NONE/READ/WRITE 和 ArchiveAccessMode，子命令可覆盖两者；search --rebuild 切换数据库写模式，metadata search 跳过产物根探测。ArchiveSession 的 READ 使用 SQLite mode=ro 与 query_only；WRITE 打开已存在库，两者校验契约且不运行初始化或刷新视图。status/runs 和 workflow 的查询操作使用 READ，缺失库按命令契约报告，不因查询创建 archive.db。

READ/WRITE/BOOTSTRAP 持有共享 archive_access OS 锁，MAINTENANCE 持有独占锁；共享访问允许多个 worker，排除 snapshot/预检。CLI 在整个调用边界协调访问，程序化连接持有自己的 session，直到 close 释放；同线程嵌套连接通过引用计数支持任意关闭顺序。维护锁位于 archive root 旁，目录恢复不搬动锁身份；SQLite 决定事务写入顺序。BUSY/LOCKED 超时给出诊断，数据保留以便重试。合作协议不能约束绕开它的外部写入。

只有 BOOTSTRAP 调用 initialize_schema，在 DDL 前检查 manuscript 和持久表契约，再初始化和刷新已交付视图；兼容的 metadata 库可补 video_tag_observations，旧表/CHECK 不自动 ALTER 或删除。ArchiveContract.RUNTIME 与 MANUSCRIPT 分别约束运行库和稿件契约，NONE 交由专用消费者验证；历史索引、冻结迁移源不能借此隐式升级。缺失 FTS 的显式构建只新增索引表；新空归档才走 BOOTSTRAP。不兼容旧库须另建兼容 archive。见 [01 启动](sequences/01-cli-bootstrap.md)。

## 元数据、游标与原始标签

fetch-meta 获取用户视频页、必要详情、零基分 P 和 tags。页内按 BVID 去重请求，页事务保存 users/videos/parts/details、成功标签及观察、page/discoveries 和 cursor。显式 start-page 是一基页号，可回退；resume 必须已有游标。空页完成，页上限 limited；失败/风控/空页各自有证据。

页面传输/限流最多 5 次重试，退避 30/60/120/240/300 秒；不代表所有 API 调用统一重试。skip-failed-page 仅推进未来游标，本 run 仍失败，risk_interrupted 不跳过。可选 tags unavailable 不丢失其他成功元数据。

标签观察区分 success_nonempty、success_empty、unavailable：非空成功替换，成功空清空，不可用保留旧集合并记录失败。每个 run 重新观察，有界 LRU 只减少本次重复请求；fetch-tags 先验证完整已存 BVID 选择再刷新。

publication create 从当前原始集合冻结 edition tags；sync-source-tags 要求观察覆盖完整，显式生成新的 pending-review edition。抓取更新不修改既有 edition/release。见 [02](sequences/02-metadata-tags.md)、[11](sequences/11-publication-lifecycle.md)。

## 规划、依赖、状态与恢复

workflow plan 支持 part ID，或多个 BVID 全部/指定零基 page-index。WorkflowApplication 解析完整目标，纯规划器验证策略与 editorial 配置，repository 在一次写事务内冻结 profile 并应用 JobSpec；无效选择、配置或 job 写入失败不会留下部分 profile/jobs。BVID 全量选择报告排除 gone，显式 unknown/gone 拒绝。兼容的 repository.plan 接口继续接受已有 profile，CLI 用例使用原子的 plan_with_profile。

每个 part 建 subtitle；策略为 all/selected/below-threshold；selected 与 all 在已选 part 上同样规划，需要 ASR 时建 audio，ASR 只依赖 audio succeeded，与 subtitle 无依赖。below-threshold 读取已存 workflow_quality_assessments 和用户阈值，不即时测量准确率。当前没有按时长/直播过滤的 plan 参数。

```mermaid
flowchart LR
  selection[完整目标与配置验证] --> subtitle[subtitle]
  selection --> audio[audio]
  audio --> asr[asr]
  subtitle -->|成功转录请求| publish[publish 原始 bundle]
  asr -->|成功转录请求| publish
  asr -->|可选依赖| proofread[proofread]
  proofread --> render[render_document]
```

逻辑 key 去重；ASR key 含 profile digest，冻结 model/aligner 各自 revision、device、language、chunk、timeout、hotwords、生成预算/cache/offline 参数。执行从数据库重建，不读取后来的 ASR 环境配置。index kind 在 schema/enum 允许，但当前 planner/handler 没有注册；FTS 由 search-index 执行。见 [03](sequences/03-workflow-plan.md)。

| job 状态 | 条件 | 后续 |
| --- | --- | --- |
| queued | 新计划、failed retry、lease 回收、publish 新请求 | available_at 到期且依赖全部 succeeded 才可 claim |
| running | 写锁下建立 lease、attempt_count+1 和新 attempt | 独立 file-backed 连接 heartbeat；检查精确 attempt |
| succeeded | 结果后再次校验 owner/attempt/未过期 lease | 满足依赖；publish 在途新请求可使成功 attempt 后 job 回 queued |
| failed | handler/no_handler/超时失败，或旧 attempt lease_expired | 显式 retry 仅重排 failed，保留历史证据 |
| cancelled | 全集验证后取消 queued/running；running attempt 同步 cancelled | plan/retry/publish 不复活；保留已提交事实，不级联删除 |

claim 在取得写锁后采样当前时间，先收尾过期 attempt，再回收 job，并在提交前复验新租约。旧 worker 即使重用 worker ID，也不能越过 attempt_count 校验。renew 进入时检查准确 owner、attempt 与旧期限，退出前同时检查旧期限和新期限；不能通过等待或慢写续活已到期的任务。finish/fail 清空 lease 后仍以捕获的期限作提交前复验。取消依赖导致 queued 下游 blocked 是 status/explain 的派生事实。JobCommitGuard 的 owned_transaction 先 BEGIN IMMEDIATE，在事务进入和提交前检查 job/owner/attempt/有效 lease；editorial repository 注入相同 guard，底层持久化无需导入整个 workflow 业务。耗时网络/推理在锁外，业务结果与 executor 终态是独立事务，崩溃后可能需幂等再执行。payload 边界在写入、读取和 handler 副作用前校验，缺省 schema_version 是已有 v1，不改历史 JSON/摘要/去重身份。手动取消是协作式，不立即撤销在途外部调用。见 [04](sequences/04-lease-cancel-retry.md)。

## 字幕、音频与 ASR

采集端口以 ContentRef(platform/external_video_id/零基 part_index) 标识工作单元；Bilibili adapter 解析真实 cid/bvid、验证凭据并调用既有 gateway/client。当前 schema、artifact stem 和 CLI 仍为 Bilibili，端口可替换不表示已支持其他平台。subtitle handler 精确选 part，列轨道、按语言 family 后 CC/AI 选轨、获取正文；存储后发布选择另以来源优先的总排序执行。cookie 存在不等于认证成功；认证、not_found、未认证空清单区别保存，adapter 只返回观察，应用仍决定 absence/ASR 策略。已列轨道正文消失是失败，不能变成永久无字幕证据。来源/语言/content/version 不可变，转录/segments 和 stored/unchanged attempt 同保护事务保存，run 异常仍收尾。见 [05](sequences/05-subtitle-ingest.md)、[采集端口](source-adapters.md)。

audio handler 在受限 audio/ 下按配置根再旧 archive 根探测非空 M4A/FLAC。下载使用本次 .workflow-audio-* 内的 audio/ 子目录，网络、ffprobe（30 秒）、duration 与 SHA-256 在事务外；无 ffmpeg 的真实 FLAC 保留后缀。最终替换和 audio_objects/part_audio_objects 登记共享 lease 保护锁，清理本次暂存。复用仍 probe/hash；成功后不自动回收。见 [06](sequences/06-audio-download.md)。

ASR 读取精确成功 audio prerequisite storage key、冻结 profile/reference ID。soundfile 优先解码，容器由 ffmpeg RF64 回退；mono 16 kHz float32，经 soxr 重采样，完整分块，processor 接收数组。每块真实 ForcedAligner 对同一波形/文本取得字符时间，校验后回全局时间轴，不插值。第一遍证据筛选热词，保留候选才第二遍新调用，不共享跨遍 prefix KV cache。

CPU runner 按 profile 复用；CUDA/ROCm 使用 spawn 子进程，父进程先持续排空队列，硬超时 terminate/kill，报告 inference_timeout；CPU 无同等硬超时。成功非空转录、segments、coverage、transcript_asr_evidence 同保护事务保存；内容去重复用旧 transcript 时仍保存本次配置、音频、参考、每遍每块诊断/EOS/对齐/耗时。workflow asr-evidence 查询证据；失败/取消全部中间块尚未持久化，质量 flags 不是 CER，不自动阻止发布。见 [07](sequences/07-asr-runtime.md)、[ASR 参数](asr-configuration.md)。

## 原始 bundle 与保护提交

成功 subtitle/ASR 请求同 part 唯一 publish job；运行时重新择优当前版本，CC > AI 字幕 > ASR，再按语言 family zh/en/其余、精确语言代码升序、同来源同语言 version 降序，不盲用 requested ID。transcript_selection 的 transcript_preference_key/choose_transcript 是公共策略，producer、projection、规划参考选择和 editorial 复用；不同语言代码先比较代码，不能把另一中文变体较新的版本误当作同语言升级。workflow publish 只请求，workflow run 可同时执行其他就绪任务。

输出 transcripts/<stem>/bundle.srt、bundle.vtt、bundle.txt、bundle.md、bundle.raw.json 及 archive-bundle-v2 marker。编码/hash/暂存/fsync 在 SQLite 锁外；旧 marker 失效、五文件替换、目录同步、新 marker、workflow_publications 登记共享 lease 写锁。失败回调在释放锁前失效 marker，避免旧 attempt 清理新 owner 结果。

当前 workflow publish 仅传 ASR 模型名称/revision provenance 子集，未读取并传入全部 transcript_asr_evidence、coverage 或 characters；writer 支持字段不等于当前调用已携带它们，完整逐次证据以 DB 为准。marker 校验精确五文件集合、受限路径和 hash，旧四文件/缺失/不符不算完整。SQLite 与文件系统无跨介质原子事务；掉电/磁盘/commit 故障由 verify、marker 和显式重新发布识别恢复。见 [08](sequences/08-transcript-bundle.md)、[WebVTT](webvtt.md)。

## AI 冻结、检查点、双稿与模板

显式 proofread 在请求时固定 base/reference，输入与 proofread/render 两个任务及依赖边同事务保存；自动链首次执行读取精确 ASR prerequisite result，并固定当时同语言参考，输入保存与 job-input 绑定共用一次保护事务。input digest 含转录、元数据、完整配置、提示词和块；retry 不读最新 ASR/文件。任一持久化失败回滚对应完整用例，不留下部分输入或任务。

未完成块先续 lease、记绑定准确 attempt 的请求，锁外调用 DeepSeek；无隐式 HTTP retry。实际 envelope/usage/model/返回思考先审计，再检查 lease 和严格结构：连续有序、来源恰好一次、无未知/只读引用。块/revision 分别受保护提交，完成块重试复用。外部请求可能重复计费；结构覆盖不证明语义保真。见 [09](sequences/09-ai-proofread.md)。

render_document 锁外确定性生成双稿，预检完整 path/hash/role 及既有字节，再通过 stage_artifact 在锁外完成临时文件写入和文件 fsync；lease 保护事务内安装不可变字节、同步 POSIX 目录并登记完整双稿。两文件不构成 FS 事务，第二份失败可留第一份，消费仍验证完整登记和字节。

固定 AI_RENDERERS/PUBLISH_RENDERERS 按记录版本校验历史产物，当前 writer 为 ai-draft-v1/publish-v1；未知 renderer 拒绝，排版变化需要新版本/路径/身份。ai-draft.md 纯正文；review.md 为 AI 原文、整理稿、来源/时间/回看、疑点和模型参数参照，非人工批准。重渲染不调用模型。见 [10](sequences/10-document-render.md)、[AI 专题](ai-proofreading-architecture.md)。

## 完整 edition、审核、release 与三类导出

create 验证明确 AI 基线，冻结 title/markdown/summary/tags/source/attribution/editorNote，全对象 SHA-256；edit/tags sync 按精确父版与 draft head CAS 生成新 edition/new pending-review。旧内容不修改。

review 指定 edition/hash/expected status/actor：pending-review → in-review → approved/changes-requested/rejected，changes-requested → in-review。approved/rejected 终态，改内容新建版。publication_edition_reviews 保存当前状态行，publication_events 追加变更；不是每次审核插新 review。

draft/release head 独立，新建/审核/批准 B 保持公开 A；显式 publish B 才验证批准/expected release，锁外写 publish.md，再写事务重验 hash/批准/安装字节/CAS，登记 release，旧 A superseded，新有效 head。重复 publish 返回该 edition 历史 release，不恢复 withdrawn/superseded；withdraw 清有效 head、保留历史。文件先于 DB 登记，失败可留未登记字节。见 [11](sequences/11-publication-lifecycle.md)。

| 出口 | 精确选择 | 产物 |
| --- | --- | --- |
| publication export | 有效 current_release_id，准确批准/来源/模板/事件/字节 | catalog v2、publish.md、对应 AI 原始 review.md、manifest |
| publication export-drafts | 当前 edition 且从未产生任何状态 release | draft catalog、preview.md、原始 review.md、状态与 manifest |
| editorial export | 明确配对 revision/edition | 双稿、edition.md/json、review.json、AI/父版全内容 patches、events/配置 |

先读 head 再验证，坏关系不得被 JOIN 隐藏成空结果；有效 release 或配对 AI 稿损坏整次失败。公开/预览 reviewFile 与 reviewArtifactSha256 独立；参照针对 AI 初稿，人工正文可不同，actor/events/请求配置和私有差异另行导出。

export_snapshot 使用输出独占锁、旧目录归属校验、完整 staging/manifest、恢复日志和目录切换，拒绝 unknown 文件、链接/junction、源目标重叠。成功快照完整，切换可短暂不可用；父目录是私有恢复空间，只部署输出目录。withdraw 不自动刷新已导出/部署副本。见 [12](sequences/12-reader-private-export.md)、[出版](publication.md)、[JSON 契约](contracts/README.md)。

## 投影、覆盖、完整性、去重与检索

workflow_records 在 READ/RUNTIME session 的一次 SQLite 读快照内，按 part ID 每批 256 读取 active parts，以集合查询选转录、取最新 publication，按需批量取 segments；输出恢复原 pubdate 降序、BVID/page 顺序，保留 dict API。meta_ok/subtitle_done/asr_done/archived 是投影状态，非 job 状态。

preferred_* 描述按公共总排序选择的当前版本；published_* 描述最后成功 publication 的身份。已有 publication 时，兼容字段 transcript_id/source/language/version 和 with-text 描述已发布内容；尚未发布时描述 preferred。publication_current 表示两者是否同一 transcript。新版本或更优语言进入库，旧完好 bundle 仍 archived、coverage complete、export 仍对应其发布正文，重新发布后才切换。

最新声明按 published_at、publication_id 选取；producer 在同一个 part 的保护事务内用 max(墙钟秒, 已有 published_at 最大值 + 1) 生成单调提交时间。同秒重新发布旧 transcript 的 upsert 因而成为最新声明；密集发布时该值可短暂领先墙钟秒，表示顺序，不能当精确物理时钟。同 part 的历史 publication 可能共用可变 bundle slot，不能因最新损坏回退旧声明。artifact_json 必须含完整路径集合，JSON 损坏或缺键不会由默认路径掩盖。正常投影验证五文件与 marker 后才 archived；verify/coverage 使用 verify_artifacts=False 保留 declared publication，再自行查字节，使 terminal_missing_artifact/defect 不被静默降为 backlog。

publication 与 transcript 用 LEFT JOIN 保留损坏关系：引用悬空或引用另一 part 的转录时，publication_error 分别为 published_transcript_missing/published_transcript_part_mismatch，保留声明 transcript ID 并将正文置空，不能借 preferred 或另一 part 的正文补齐。coverage 和 IntegrityVerifier 明确报告数据库关系 defect，即使 bundle 字节仍完整也不能计 complete。

IntegrityVerifier 当前检查 projected bundle 完整性及相关缺陷，不等于自动验证全部音频/AI/release；稿件和快照各有专门验证。coverage strict 将 diagnostics 变成非零；verify 区分 backlog/defect；export 输出普通 JSON/CSV，可按 status/with-text；dedup 仅报告精确音频及跨 segment 文本复用，不选 canonical/改来源。见 [13](sequences/13-projection-verify.md)。

FTS 在 archive.db 内，search-index/--rebuild 显式写。构建入口现有库用 WRITE/NONE 加原 store 检查，新库用 BOOTSTRAP；查询用 READ/NONE 加索引形状检查，持续持有维护访问锁。transcript_segments 为主，构建开始捕获 transcript ID 上界，以 (transcript_id,ordinal) keyset 每页最多 500 行读取；单行前瞻识别整份转录结束。FTS 行与精确 segment cursor 同批提交，整份转录水位只在最后 segment 提交后前进；崩溃/失败继续已提交位置，构建期间新采集留下一轮。

无已存 transcript 的 part 可兼容发布 MD，同样按 part ID/上界分页。已经 MD 索引的 part 在连接临时主键表中排除，避免全量 Python 集合、巨型 NOT IN 或逐 part 扫描 FTS；只读查询不建临时表。旧无 cursor 索引把已索引 block_key 保存于 SQLite 连接临时主键表，有界 keyset 核对连续前缀、批量 JOIN 标记后续既有 block，不保留 O(index) Python 集合。只读查询旧 stamp 时使用一次 materialized 只读 CTE 后流式核对，无 DDL。已有行不默认重写。脱敏与 CJK bigram/tokenizer 支持检索。

search 默认 transcripts；metadata 只读当前 title/description/source tags 字面子串，无需文件/FTS。all 元数据在前，共用总 limit；填满 limit 仍校验转录源健康。missing index 正常 backlog，all 缺 FTS 可保留元数据；损坏明确失败。UTC 日期 [from,to+1day)，metadata 当前 pubdate、FTS 构建快照；JSON stdout 为数组，诊断分离。见 [14](sequences/14-search-index.md)。

## 私有归档快照与恢复

snapshot save 独占维护，拒绝有效 running lease；检查 schema/FK 后 SQLite backup，busy 等待有界。产物根优先旧根回退，排除 staging，检查可移植路径和文件读前后身份；ZIP64 流式 size/hash/manifest，不覆盖目标。包括音频、bundle/marker、AI 双稿和全部历史 release（含 superseded/withdrawn），验证 DB references，是完整私有包。

check 流式校验所有成员/hash/marker/DB contract/FK/references，仅落临时 DB；restore 目标必须不存在/空，独占锁下完整解压校验后收尾 running attempts/runs/model calls，running job 回 queued 清 lease，记录 snapshot_restored，cancelled 保留。再次校验/fsync/rename 完整安装。过期 running 可随 save 保留供 restore 恢复，当前有效 lease 不可保存。见 [15](sequences/15-archive-snapshot.md)、[快照指南](archive-snapshots.md)。

## 数据所有权、布局与保留库能力

| 事实/产物 | 所有者 | 消费 |
| --- | --- | --- |
| archive.db 元数据、转录、控制、AI、出版表组 | 各 storage repository | planner/worker/投影/导出/快照 |
| audio/<stem>.m4a 或 .flac | audio handler 与音频表 | 精确 ASR prerequisite、快照、显式 inventory |
| transcripts/<stem>/bundle.* 与 marker | archive writer + workflow_publications | 验证、投影、普通导出、兼容检索 |
| documents/part-ID/revision/ai-draft-v1/ | render + document_artifacts | edition 基线、配对 review、私有包/快照 |
| publications/part-ID/release/publish-v1/publish.md | publication service + release/head/events | 公开出口、全部历史快照 |
| archive.db FTS | search-index | transcripts/all search |
| 三类静态目录 | publication_export + export_snapshot | 外部阅读站/审核者 |
| 完整 ZIP | archive_snapshot + storage.snapshots | check/restore |

artifact root 可由 flag/BILI_ARTIFACT_ROOT 与 archive root 分离，写 write_base，读配置根优先旧根回退，DB 始终 archive root。ZIP restore 可把产物合并进新根；受限音频路径、固定稿件路径和 portable key 共同限制访问。

库中保留 audio_budget/audio_reclaim/long_live/audio_inventory、旧双路人工 proofread、publication_supervisor、bundle_verification、concurrency_gate、persistence/run-ledger 等。显式调用的路径/预算/超时能力存在，当前注册 CLI/workflow 不自动启用成功回收、旧 merge 或发布进程监督。scripts/production.py 解析受限 env-file 并调用已安装 CLI；评测/验证脚本是工程支持。见 [16](sequences/16-library-and-operations.md)和 [产品模块清单](architecture-sources.md)。

## 固定旧源迁移预检

`archive migration-preflight` 是当前 main 已交付的离线运维入口。CLI 不打开当前运行库，由 `services/migration_preflight.py` 持有源归档维护独占锁，交给 `storage/migration_source.py` 按冻结的 Bilibili v1 契约读取停止写入且已 checkpoint 的旧库；不调用当前 initializer，不创建目标、不恢复任务、不转换 schema。

逐表指纹保留 SQLite 类型、精确值和 rowid；文件扫描按显式产物根优先、归档根回退，记录遮蔽文件及排除项。`storage/migration_artifacts.py` 独立核对全部冻结输入/revision 身份、已登记 AI 双稿、完整审核事件链、独立 draft/release head 和全部历史 release；无产物 revision 可以保留，但冻结身份仍须有效。非空 WAL/journal、有效或缺失 lease 的 running job、不支持的结构、缺失或损坏产物及扫描期间变化均拒绝。更多操作边界见 [预检指南](archive-migration-preflight.md)。

预检覆盖全部 38 张权威表和五类受管理产物目录；已知完整 FTS 缓存标为可重建派生数据。显式产物根优先、旧根回退，遮蔽副本也计算哈希并检测变化；根目录未知条目、暂存文件、链接/junction、不可移植路径和不允许的根重叠均失败。凭据、模型、日志、缓存等仅记录排除名称，不递归读取。

完整性包括所有冻结 input/revision（含未登记产物 revision）的身份、job/input/part 关系；已登记双稿必须完整并按固定 ai-draft-v1 渲染复算。edition 内容、父版、准确审核历史链及终态、独立 draft/release head、全部历史 release（含 superseded/withdrawn）和固定 publish-v1 字节必须相符。成功音频 attempt、bundle 五文件和 marker、AI 双稿、历史 release 引用均须存在且满足大小/哈希。

扫描后再次核对文件集合、全部物理文件身份、DB 身份与 sidecar、排除项。通过后输出表行数/摘要、文件摘要、源 fingerprint、遮蔽与排除项，以及过期 running/未完成 run/调用的恢复候选计数；候选只报告。JSON/text 成功退出 0，受控诊断失败退出 1；仅锁协调可能写入根旁的稳定锁文件。报告包含私有路径，应按私有归档信息处理。文件哈希流式执行，清单与部分内容校验仍在内存中，预检不提供全链路内存上限。完整时序见 [17](sequences/17-migration-preflight.md)。

本轮保留 16 顶层命令和既有持久 schema，新增应用用例、纯任务模型/规划/payload、提交保护、共享选择策略、session 与来源端口等模块。ContentRef 与 Bilibili 适配边界已交付；[多平台实施方案](multi-platform-architecture-plan.md)中的其他平台 schema、转换和运行生产链仍需另行实现。

## 验证边界

本次包含实现修复及对应文档、JSON 和生成 HTML，逐项对应关系见 [边界修复与验收](architecture-refactoring.md)。测试在独立工作树的本地 WSL Ubuntu-24.04 运行；发布/投影/coverage/export/损坏归档、索引有界分页/恢复/并发上界/历史 MD、只读连接与维护锁均有生产和消费者回归。完整业务验收以本轮实际测试记录为准，历史被 collect_ignore 明确排除的测试不代表当前 CLI 能力。

Archify 的 validate/deliver/strict check/browser-check 绑定 commit 与 specification/artifact SHA-256；截图和实际目视检查分别记录。图表检查不能替代行为回归、真实 B站访问、GPU/付费模型或逐句语义审核。本次验收结果见 [验证记录](architecture-validation.md)。
