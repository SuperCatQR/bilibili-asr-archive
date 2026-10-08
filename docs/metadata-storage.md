# SQLite 数据与工作流

本文描述当前源码的持久化契约、执行入口与恢复方式。系统使用归档根目录下的
`archive.db` 保存元数据、转录版本、工作流、校对修订和审核记录；音频及 Markdown 等
文件保存产品字节。SQLite 中的事实决定计划和执行，文件用于发布、验证和阅读。

整体关系见 [architecture.md](architecture.md)，文件位置见 [artifact-root.md](artifact-root.md)，
阅读审核见 [ai-proofreading.md](ai-proofreading.md#阅读导出与人工审核)。

## 1. 唯一执行控制面

当前执行入口是 `fetch-meta` 和 `workflow`。元数据独立采集；字幕、音频、ASR、发布、
AI 校对与阅读文档渲染由 SQLite workflow 调度。旧 manifest 队列和旧阶段命令不再是
受支持的执行入口；数据库缺失时不会自动恢复 JSONL 队列。

```text
fetch-meta -> metadata tables -> workflow plan
                                     |
                           +---------+----------+
                           v                    v
                       subtitle               audio
                           |                    |
                           |                    v
                           |                   asr
                           |                    |
                           +------> publish <---+
                                                |
                                  optional proofread
                                                |
                                         render_document
```

发布箭头表示成功获得转录后请求发布。ASR 的调度 prerequisite 是 audio；字幕结果不决定
ASR 是否能被领取。带 `--proofread` 的计划中，校对依赖 ASR，文档渲染依赖校对。
已有 transcript 也可以通过 `workflow proofread` 单独进入校对分支。

## 2. Schema 与数据所有权

`storage/database.py` 的 `open_database()` 支持归档目录、显式数据库文件和 `:memory:`。
正常 CLI 使用 `<archive-root>/archive.db`。新数据库按四份包内 SQL 建立完整 schema：

| Schema 文件 | 主要表 | 保存的事实 |
|---|---|---|
| `schema.sql` | `bilibili_users`、`videos`、`video_parts`、`video_tags`、`video_details` | 用户、视频、分 P、标签和详情 |
| `schema.sql` | `ingestion_runs`、`ingestion_cursors`、`ingestion_pages`、`ingestion_discoveries` | 元数据运行、分页、游标与发现证据 |
| `schema.sql` | `audio_objects`、`part_audio_objects`、`asr_models` | 音频身份、分 P 关联、模型身份 |
| `schema-transcripts.sql` | `transcripts`、`transcript_segments` | 转录版本与按序片段 |
| `schema-transcripts.sql` | `acquisition_runs`、`acquisition_attempts`、`transcript_coverage_attestations` | 采集结果、字幕证据、ASR 时长覆盖 |
| `schema-workflow.sql` | `workflow_asr_profiles`、`workflow_jobs`、`workflow_job_dependencies`、`workflow_attempts` | 配置快照、任务、依赖、租约与执行历史 |
| `schema-workflow.sql` | `workflow_quality_assessments`、`workflow_publications` | 质量评估、发布版本和相对文件路径 |
| `schema-editorial.sql` | `editorial_inputs`、`editorial_job_inputs`、`editorial_model_calls`、`editorial_chunk_results`、`editorial_revisions` | 冻结输入、模型响应、分块检查点与修订 |
| `schema-editorial.sql` | `document_artifacts`、`reading_document_editions`、`reading_publications`、`reading_publication_events` | 文档哈希、人工 edition、审核状态与事件 |

Repository 拥有对应事实的写入契约；CLI 组装 repository、配置和 handler。执行器负责
领取、续租和终态，handler 负责处理。查询投影不维护第二套任务状态。

### 身份、单位与版本

- API 分 P 页码从 1 开始，数据库 `page_index` 从 0 开始。工作流使用 `video_part_id`；
  展示层 `BV...:p0` 是 work ID，不能直接代替 `--part-id`。
- 视频时长与转录位置使用毫秒；运行和租约时间使用整数 Unix 秒。
- transcript 身份是 `(video_part_id, source_kind, language, version)`，来源为
  `subtitle-cc`、`subtitle-ai`、`asr-local`。正文哈希与有序 segments 保存不可变转录事实。
- 相同字幕内容避免重复版本；ASR 保留模型与运行证据。空响应和失败是采集证据，不能
  覆盖已有 transcript。`credential_verified`、`absence_verified` 区分验证与观察结果。
- ASR profile 固定模型、revision、aligner、device、language 和配置 digest；配置变化产生
  新身份，不修改旧 job 引用。计划冻结当时的参考字幕 ID，执行读取成功的 audio result。
- 文件 key 是根目录相对路径。音频登记 SHA-256、大小、格式、时长；阅读文档登记
  SHA-256，导出时验证实际字节。目录配置不保存在数据库中。

凭据在运行时解析；数据库记录凭据存在和验证证据，不保存 `SESSDATA` 的值。

`v_pending_subtitles`、`v_missing_subtitle`、`v_missing_audio`、`v_missing_transcript` 和
`v_part_pipeline` 是缺口查询视图。实际领取条件属于 workflow jobs 和 dependencies；
这些视图不承担第二条队列或 manifest 回退。

## 3. 采集、计划与执行

以下示例适用于 WSL 的 POSIX shell。先有界采集：

```sh
bili-asr fetch-meta --archive-root ./archive --mid 123456 --limit-pages 2
```

成功页推进持久游标，再次运行继续；`--resume` 要求已有游标，`--start-page` 显式覆盖
起始页。上游 gateway 失败返回退出码 2 并保存中断证据；未指定 `--skip-failed-page`
时不会跳过失败页。

查询数据库中的分 P ID，再计划执行：

```sh
sqlite3 ./archive/archive.db \
  'SELECT video_part_id, bvid, page_index, title FROM video_parts ORDER BY video_part_id;'
bili-asr workflow plan --archive-root ./archive --part-id 42 --asr-policy all
bili-asr workflow run --archive-root ./archive --limit 20
bili-asr workflow status --archive-root ./archive --details
```

计划按输入身份去重，可重复执行；`--part-id` 可重复传入。ASR 策略只有以下三种：

| 策略 | 语义 |
|---|---|
| `all` | 为传入的分 P 计划音频和 ASR |
| `selected` | 为明确选择的分 P 计划音频和 ASR；当前实现的选择结果与 `all` 相同 |
| `below-threshold` | 按最新质量评估筛选；需要 0 到 1 的 `--quality-threshold`，缺少评估也进入处理集合 |

所有选择的分 P 都有独立字幕 job。字幕获取由 subtitle handler 与 `BilibiliApiGateway`
完成，一个分 P 可保留字幕和 ASR 两种来源。`workflow run` 处理当前可领取任务，
没有就绪任务时返回，不持续轮询等待。

```sh
# 从最新 ASR 版本冻结校对输入，明确不使用参考字幕
bili-asr workflow proofread --archive-root ./archive --part-id 42 --no-reference
bili-asr workflow run --archive-root ./archive --only-editorial
# 请求已有 revision 的确定性重渲染，不调用 AI
bili-asr workflow render --archive-root ./archive --revision-id REVISION_ID
bili-asr workflow run --archive-root ./archive --only-editorial
```

冻结快照和已完成 chunk 是重试检查点；渲染读取 revision 与模板。人工审核与 edition
追加记录，不覆盖原 AI revision。

## 4. 任务状态、阻塞解释与定向恢复

持久状态为 `queued`、`running`、`succeeded`、`failed`、`cancelled`。
`blocked` 是派生值：queued 且有 prerequisite 未 succeeded。等待 `available_at`
的任务也可能尚未 ready，但不因此被标记为依赖阻塞。

```sh
bili-asr workflow explain --archive-root ./archive --job-id JOB_ID
bili-asr workflow status --archive-root ./archive --details
```

`explain` 输出一个 JSON 对象；`status --details` 先输出状态计数，再逐行输出任务 JSON。
解释包含 kind、状态、attempt_count、最近 attempt、available_at、ready、blocked，
以及 prerequisites、blockers 中各任务的 ID、kind、状态和有界错误码。错误码至多
64 字符，不保存任意异常全文。

audio 失败后 ASR 保持 queued，blockers 指向 audio。修复下载配置后重试 audio，
其成功后 ASR 自然满足依赖：

```sh
bili-asr workflow retry --archive-root ./archive --job-id AUDIO_JOB_ID
bili-asr workflow run --archive-root ./archive
```

`retry` 只重排 failed 任务，保留 job 身份、attempt_count 与历史 attempts。
`--job-id`、`--kind`、`--part-id` 均可重复：同一参数内是并集，不同参数之间取交集。
不带筛选重排全部 failed；queued 的下游任务不需要 retry。

```sh
bili-asr workflow retry --archive-root ./archive --kind audio --part-id 42
bili-asr workflow retry --archive-root ./archive --job-id JOB_ID --kind asr --part-id 42
```

过期租约在下一次领取时回收，旧 attempt 记录 `lease_expired`。终态与续租验证
`job_id + lease_owner + attempt_count`，旧 worker 不能覆盖新 attempt。运行时注册
subtitle、audio、asr、publish、proofread、render_document handler；schema 中的 `index`
kind 当前没有运行 handler，全文索引通过 `search-index` 建立。

## 5. 本机多进程 SQLite 运行范围

支持同一主机、共享本地文件系统上的同一数据库由多个 worker 进程使用。每个进程拥有
自己的连接与 worker ID。领取使用短 `BEGIN IMMEDIATE` 事务；请求、下载、推理和
渲染在事务外执行。SQLite 串行化写事务，不提供多个同时写入的事务。

建议从 1–4 个 worker 开始；回归测试验证 4 个进程同时领取时没有重复 claim。
这不是代码强制的进程上限，也不是吞吐保证。更多 worker 应先测量写入等待与资源占用，
让 busy timeout 和租约留出调度余量；默认生产租约是 900 秒，heartbeat 间隔为租约的三分之一。

heartbeat 在自己的 daemon 线程中打开独立连接。它与主连接使用相同 `busy_timeout`：
默认 30000 毫秒，`BILI_SQLITE_BUSY_TIMEOUT_MS` 接受 1 到 300000 的整数。
heartbeat 继承 repository 创建时的策略，不重新读取后续环境变化。

```sh
export BILI_SQLITE_BUSY_TIMEOUT_MS=30000
# 在两个 WSL 终端分别运行，使用不同 worker ID
bili-asr workflow run --archive-root ./archive --worker-id worker-a --limit 20
bili-asr workflow run --archive-root ./archive --worker-id worker-b --limit 20
```

超出等待上限的锁冲突返回退出码 1，CLI 提示 SQLite 竞争超时、超时变量和重试方式。
等待占锁事务结束再运行；不要删除使用中的数据库或手动清除租约。等待超时不是整个
命令的时限。多 worker 不协调 GPU 显存；GPU worker 数量由操作者控制。租约不能撤销
已发出的外部请求，但会阻止过期 worker 写入权威终态和关键发布点。

该范围不包含跨主机共享数据库、网络文件系统 SQLite，或 Windows 与 WSL 同时写同一
挂载数据库。本机 WSL 多进程测试可以验证当前文件系统上的竞争行为，不能推导跨系统保证。

## 6. Schema 不兼容时重建

本项目不维护旧数据库迁移。打开非空库前从四份当前 SQL 推导表定义，核对所有产品表。
缺表、旧字段或约束不符会在执行 schema 修改前失败，提示
`delete archive.db and re-run fetch-meta`。不存在自动 `ALTER TABLE` 补字段路径。
新库建立完整 schema；已有兼容库可继续用，当前包内派生视图仍可刷新。
额外索引表不能代替产品表契约。

重建步骤：

1. 停止该归档的 worker 与写入命令。
2. 如需留存，在关闭连接后保存旧数据库与文件。
3. 操作者删除该归档的 `archive.db`，重新运行 `fetch-meta`。
4. 重新计划采集、ASR、校对和发布，重建搜索及阅读站快照。

**删除数据库会丢失元数据、转录版本、运行历史、修订和审核状态，需要重新采集或生成。**
保留文件不能自动恢复这些事实，也没有受支持的 manifest 导入路径。

## 7. 查询、导出与完整性

- `status`、`runs` 不创建缺失数据库；打开已有库仍可能初始化兼容 schema、刷新视图。
- `workflow status`、`workflow explain` 使用 schema 初始化入口，缺失数据库会初始化；
  因此不能通过它们证明数据库此前存在。
- `coverage`、`verify`、`export` 使用只读 workflow projection，合并 transcript、publication
  与文件校验；独立目录的 bundle 按 artifact root、archive root 检查。
- `search-index` 写可重建 FTS 派生索引；`search` 查询索引。
- `dedup report` 只读内容身份清单，不删除音频、不合并版本、不选 canonical。
- `reading-export` 以只读数据库连接验证文档 SHA-256，再生成静态输入；
  `reading-review`、`reading-edit` 写审核决定与人工 edition。

publication 行不能替代完整 marker 和实际字节校验。目录配置不迁移数据库，后续读取
必须提供一致的 artifact root。路径规则见 [artifact-root.md](artifact-root.md)。

## 8. 验证入口

离线专项测试适用于 WSL 独立开发环境，不要求加载 GPU 模型：

```sh
python -m pytest -q tests/test_workflow_issue_regressions.py \
  tests/test_workflow_control_plane.py tests/test_workflow_lease_heartbeat.py \
  tests/test_storage_schema.py tests/test_ai_editorial.py
```

覆盖相对路径、符号链接拒绝、独立产物目录、审核导出哈希、阻塞解释、定向重试、旧库拒绝，
以及真实多进程领取与 heartbeat 锁竞争。完整测试用 `python -m pytest -q`；live API
与 GPU 集成测试要求各自环境，不能将离线 adapter 测试视为真实模型推理验证。
