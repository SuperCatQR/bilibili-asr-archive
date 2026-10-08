# 当前架构

交互式组件图：[architecture.html](architecture.html)（规格源：[architecture.json](architecture.json)）。
交互图的源码证据固定于 `architecture.json` 中登记的提交；本文反映已提交的
目录配置、失败恢复、schema 与并发策略，覆盖 CLI、SQLite workflow、
元数据和字幕采集、音频与 ASR、AI 校对、归档发布、全文检索、完整性检查和阅读站导出。

源 JSON 与生成 HTML 必须一起维护；刷新流程、证据要求和验证命令见
[architecture-maintenance.md](architecture-maintenance.md)。

## 核心执行模型

产品只有一个执行控制面：SQLite-backed workflow。CLI 负责组装配置和 handler，
`WorkflowRepository` 负责计划、依赖、领取、租约、attempt、重试和终态；
`WorkflowExecutor` 每次领取一个 job，在事务外执行 handler，再以精确的
`job_id + lease_owner + attempt_count` 写回结果。SQLite 是元数据、转录版本、
工作流状态、编辑修订和阅读审核状态的事实源；音频、转录 bundle、`reading.md`
与 `review.md` 是文件产物，只能通过受约束的写入边界发布。

```text
CLI / composition
        |
        v
Workflow planner -> SQLite jobs, dependencies, leases, attempts
        |
        +--> Acquire: metadata, captions, audio
        |
        +--> Process: ASR, editorial proofread, deterministic rendering
        |
        +--> Publish: transcript bundles and reading documents
                         |
                         v
               Query projections: status, coverage, export, verify, search, dedup
```

长任务由 daemon heartbeat 使用独立的 file-backed SQLite 连接续租；续租和终态写入都校验精确
attempt，旧 worker 不能覆盖新 attempt。CUDA/ROCm ASR 的强制对齐运行在可杀死的子进程中，
超时会终止子进程并记录可重试的 `inference_timeout`，避免卡住的 aligner 永久占住租约。
发布前、文件替换前后也会执行 lease fence。

## 运行边界与数据流

### 采集与规划

`fetch-meta` 通过 `BilibiliApiGateway` 有界分页采集用户、视频、分 P、标签和分页证据，写入
`archive.db` 的 metadata 表组；游标、run、page 和 discovery 都是可恢复的事实。
workflow 的 subtitle handler 使用同一 gateway 获取字幕轨道，字幕没有可见结果时保留可重试
证据，不把一次空响应误认为永久缺失。

`workflow plan` 按 part 生成去重 job：字幕、音频、ASR，以及可选的 `proofread` /
`render_document`。ASR 只依赖成功的 audio prerequisite，不依赖字幕 job 是否成功。
`claim` 会先回收过期 lease 并把对应 attempt 标记为 `lease_expired`，然后以优先级、创建时间
和 job ID 的稳定顺序领取一个就绪任务。

### 处理与发布

音频下载写入 `audio/` 并在 `audio_objects` / `part_audio_objects` 中登记 key、哈希和来源。
当前 workflow 不提供音频预算或自动回收选项。`workflow run --artifact-root` /
`BILI_ARTIFACT_ROOT` 可把音频、bundle
和阅读文档放在独立产品根；`archive.db` 始终留在 archive root，读取时按 artifact root、
archive root 的顺序探测，写入只使用配置的 write base。
根目录统一通过 `ArtifactRoots.of` 保存词法绝对路径，保留符号链接身份供写入边界拒绝。
`workflow render` 接受目录配置但只排队，随后 run 需要相同 flag/env；目录不保存到 job 中。

ASR handler 固定 profile digest、参考 transcript ID 和 audio prerequisite result，由
`ASRRunner` 完成解码、对齐、分块、hotword、provenance 与 coverage attestation，再追加
transcript version 和 segments。发布 handler 选择优选版本，`archive.write_archive` 一次性
写入 SRT、TXT、Markdown、raw JSON、characters/coverage 等 bundle，并用完成 marker 与
`workflow_publications` 共同证明发布完整。

AI 校对是独立的可选分支：它把输入快照、模型调用 envelope、chunk 结果和 immutable revision
写入 editorial 表组。`DeepSeekClient` 只在 `proofread` job 中发起 HTTPS JSON 请求；
`render_document` 读取已保存 revision，确定性地生成 `reading.md` / `review.md`，因此重渲染
不重复调用模型。

### 查询与阅读站

`status` / `runs` 读取 SQLite，已有库的打开路径可能刷新派生视图；`coverage`、`export`、`verify` 通过只读 `workflow_projection`
合并数据库事实和文件存在性。`search-index` 建立可重建的 SQLite FTS5 派生表，`search` 读取
转录文本并可用已发布 Markdown 补全；FTS 不是事实源。`dedup` 只计算音频与跨分片转录内容哈希，
不选择 canonical，也不改写 provenance。

`reading-export` 以只读连接打开 `archive.db`，校验登记的 `reading.md` / `review.md` SHA-256，
按审核状态生成静态 `reading-site/content` 快照。浏览器只接触 Markdown、catalog 和 Issue 链接，
不接触 SQLite、原始转录、模型请求或凭据。`reading-review` 和 `reading-edit` 通过状态转换与
append-only event 写回审核决定；人工 edition 以 parent 链保留，AI revision 不被覆盖。

## 模块职责与边界

- `bili_asr.cli` 解析参数、注册命令，在命令边界解析 artifact root、凭据和代理；它不实现阶段状态机。
- `bili_asr.storage.workflow` 拥有 job planning、dependency eligibility、leases、attempt、retry、immutable ASR profile 和终态 outcome。profile 由配置 digest 版本化，变更配置不会修改已有 job 引用的 profile。
- `storage.metadata`、`storage.transcripts` 与 acquisition services 拥有外部观察、字幕尝试、音频身份和持久转录事实。transcript version append-only；plan 时冻结 reference transcript，执行时读取精确的成功 audio prerequisite。
- `bili_asr.asr` 拥有模型生命周期、解码、对齐、coverage、provenance 和有界的 CUDA/ROCm 子进程，但不直接写 workflow state 或发布文件。editorial handlers 同样只通过 repository 保存 snapshot、model-call、chunk、revision 和 document artifact。
- `bili_asr.archive` 是对象发布边界：在 confined root 下写完整 bundle，在每次不可逆 replace 前接受 lease fence callback。`artifact_root` 与 `path_policy` 约束文件位置；保留的 `audio_reclaim` 模块未接入当前 workflow。
- `bili_asr.services.workflow_projection` 是 workflow 的只读投影；`coverage`、`export`、`verify` 读取 parts、transcript、publication 和 bundle layout，但不维护第二套执行状态机。

## 状态所有权

| 事实 | 权威所有者 | 派生读取者 |
|---|---|---|
| 视频、分 P、标签、分页证据 | `storage.metadata` | planner、status、export、projection |
| 字幕尝试、转录版本、segments、coverage | `storage.transcripts` + ASR services | publisher、search、editorial、verify |
| job、dependency、lease、attempt、profile | `storage.workflow` | executor、status、retry、handlers |
| 音频对象身份与文件 key | `audio_objects` / `part_audio_objects` + `audio/` | ASR、dedup |
| bundle 发布身份 | `workflow_publications` + completion marker | coverage、export、verify |
| 校对输入、调用、修订、文档 | `schema-editorial.sql` 表组 + Markdown 文件 | render、reading-export |
| 搜索索引 | `search_index.store` 的 FTS5 表 | search |

SQLite workflow jobs 和 attempts 拥有调度与 outcome；任何 JSONL/manifest 只作为发布或审计产物，
不能替代控制平面。`status` / `runs` 拒绝缺失数据库，但会通过 schema 初始化入口打开已有库；
`workflow status` / `explain` 也使用初始化入口，可以创建新库。`coverage`、`verify`、
`export`、`reading-export` 和 `dedup report` 的事实查询使用只读连接；`search-index` 明确
写入派生索引。不要将所有查询入口概括为绝对零写入。

## 失败恢复与并发范围

`workflow explain --job-id` 和 `workflow status --details` 输出 prerequisites、blockers、
最近 attempt 与有界错误码。blocked 从 queued 状态和未成功依赖推导，不增加持久状态。
`workflow retry` 支持重复的 `--job-id`、`--kind`、`--part-id`，不同筛选维度取交集；
只重排 failed job，保留历史 attempts。修复前置任务后，下游自然变得可领取。

支持同一主机、共享本地 SQLite 文件的多 worker；领取使用短 `BEGIN IMMEDIATE` 事务，
外部工作在事务外执行。主连接与独立 heartbeat 连接共享 `BILI_SQLITE_BUSY_TIMEOUT_MS`
策略，默认 30000 毫秒，允许 1 到 300000。超过上限的 SQLite 锁冲突返回明确的 CLI
错误。此范围不包含网络文件系统、跨主机数据库或 Windows/WSL 同时写入保证。

schema 采用重建策略：新库执行四份完整 SQL，非空旧库在修改前检查所有产品表定义。
不兼容时拒绝，要求操作者删除数据库并重新采集，不自动补字段。删除数据库会丢失
转录、修订、审核和运行事实；保留文件不能恢复这些数据。兼容库的派生视图仍可刷新。
表所有权、命令例子和完整恢复步骤见 [metadata-storage.md](metadata-storage.md)；
产品目录与导出约束见 [artifact-root.md](artifact-root.md)。
