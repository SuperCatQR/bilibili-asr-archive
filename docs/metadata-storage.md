# SQLite 元数据、字幕与转录存储

`{archive_root}/archive.db` 是当前归档的持久状态来源：保存视频元数据、采集游标、字幕观察、不可变转录版本、音频对象引用、工作流任务和发布登记。音频及发布产物保存为文件，数据库记录它们的身份与路径。默认归档根目录为 `archive`。

本文按当前源码说明存储与公共 CLI 契约。系统全貌见 [架构文档](architecture.md)；操作细节见 [BVID 选择](workflow-selection.md)、[任务取消](workflow-cancellation.md)、[WebVTT 与五产物归档包](webvtt.md)、[AI 校对](ai-proofreading.md)、[元数据搜索](metadata-search.md)。

## 从采集到发布

先采集元数据，再为已存储的分 P 规划任务。以下 BVID 仅表示待替换的示例值：

```sh
bili-asr fetch-meta --mid 23191782 --archive-root archive --limit-pages 2
bili-asr status --archive-root archive
bili-asr runs --archive-root archive --limit 5

bili-asr workflow plan --archive-root archive --bvid BV_EXAMPLE --page-index 0
bili-asr workflow run --archive-root archive --limit 10
bili-asr workflow status --archive-root archive --jobs
bili-asr verify --archive-root archive --format json
```

`workflow plan` 创建任务；`workflow run` 领取满足依赖的任务，执行字幕获取、下载、ASR 和发布。字幕或 ASR 成功写入转录后请求 publish job。一次 `--limit` 限制的是执行的任务数，包含 succeeded、failed、cancelled；它不是视频数或分 P 数。未指定 limit 时运行到没有可领取的任务。

| 公共入口 | 数据来源与结果 |
|---|---|
| `fetch-meta` | 通过网关获取视频列表、分 P、描述与标签，写入元数据及逐页恢复证据。 |
| `workflow plan` | 解析数据库中的 BVID/part ID，注册 ASR profile，创建幂等任务及依赖。不会补抓缺失元数据。 |
| `workflow run` | 领取 SQLite jobs，持久化 attempt、转录、音频事实和发布结果；网络与模型调用发生在此阶段。 |
| `workflow publish --part-id ID` | 为已有转录请求重新发布；可重复 part ID。请求后仍需 `workflow run` 执行。 |
| `workflow status --jobs` | 查看任务状态、内部 ID、分 P 身份及取消造成的依赖阻塞。 |
| `workflow cancel --job-id ID` | 原子取消指定 queued/running 任务；可重复 job ID，详细语义见取消指南。 |
| `workflow asr-evidence --run-id ID --part-id ID` | 查询某次成功 ASR 的配置身份、输入来源与逐块运行诊断。 |
| `workflow retry [--part-id ID]` | 仅重新排队 failed jobs，保留历史 attempts。 |
| `status` / `runs` | 查看元数据数量、工作流计数、元数据待办、游标及 ingestion runs。 |
| `search` / `export` / `coverage` / `verify` | 从 SQLite 与产物读取搜索、导出、覆盖率和完整性投影；搜索索引更新是显式操作。 |

`probe-subs`、`harvest-subs`、`publish-transcripts`、`derive-manifest`、`adopt-transcripts` 等旧入口不在当前公共 parser 中。源码保留的服务或兼容函数不代表仍有同名 CLI。当前工作流不使用 `manifest.jsonl`、`meta-cursor.json` 或 `run-ledger.jsonl` 作为队列、游标或发布状态，也没有公共命令自动导入这些历史文件。

## 数据库打开与 schema 边界

`storage.database.open_database()` 接受归档目录、显式 `.db`/`.sqlite`/`.sqlite3` 文件或 `:memory:`。目录不存在时创建目录和数据库；显式路径按文件解释。连接使用 `sqlite3.Row`、`isolation_level="DEFERRED"`，并启用及验证 `PRAGMA foreign_keys = ON`。URI 字符串不会被该函数当作 SQLite URI 解释。

初始化资源分为四份：

| 资源 | 负责的对象 |
|---|---|
| [`schema.sql`](../src/bili_asr/storage/schema.sql) | 用户、视频、分 P、标签、描述、元数据 runs/pages/cursors/discoveries，以及音频与模型身份。 |
| [`schema-transcripts.sql`](../src/bili_asr/storage/schema-transcripts.sql) | acquisition runs/attempts、转录、segments、coverage attestations 与缺口视图。 |
| `schema-transcripts.sql` 的 `transcript_asr_evidence` | 每次成功 ASR 的 profile、音频、provenance 与诊断，不随正文去重丢失。 |
| [`schema-workflow.sql`](../src/bili_asr/storage/schema-workflow.sql) | ASR profiles、jobs、依赖、attempts、质量评估与 publication 登记。 |
| `schema-workflow.sql` 的 `workflow_asr_profile_configs` | 完整有效 ASR 配置的不可变快照与 schema version。 |
| [`schema-editorial.sql`](../src/bili_asr/storage/schema-editorial.sql) | 校对输入快照、API 调用、chunks、revision 和渲染产物等独立编辑数据；见 AI 校对指南。 |

新数据库按四份 SQL 建立完整 schema。打开非空数据库前，从当前 SQL 推导表契约并核对所有产品表；旧字段或约束不符在修改 schema 前失败。当前有明确的新增观察表例外：缺少 `video_tag_observations` 可补建，不改写 tags 或稿件；其他必需表缺失仍按现有契约拒绝。兼容数据库中的派生视图仍可刷新。

main 9b28957 的四份 schema 共 38 张持久表、8 个视图；完整字段、外键及按需创建的 FTS 虚拟表/水位表见[架构源码与覆盖清单](architecture-sources.md)。
原始标签观察的 success_nonempty/success_empty/unavailable 与已存集合分别保存；不可用观察保留旧集合。

当前不支持旧数据库迁移或自动 `ALTER TABLE` 补列。不兼容时提示 `delete archive.db and re-run fetch-meta`；应先停止 worker、备份数据库和必要文件，再由操作者重建。重建会丢失原数据库中的转录、任务、校对与审核历史；备份与重建步骤见 [取消指南](workflow-cancellation.md)。

`status`、`runs` 先检查数据库是否存在，缺失时退出 `1`，不创建新库。打开兼容库仍可能刷新派生视图。`workflow status` 和 `workflow explain` 使用 `open_database()`，可以初始化新库。需要结构性只读时，应使用下文的 `mode=ro` 投影或自行建立只读 SQLite 连接。

### Manuscript Contract

Fresh archives also carry `schema-editorial.sql` and its explicit manuscript
contract marker. Opening an existing archive validates this contract before
any schema initialization, view refresh or commit. Legacy editorial tables,
missing required entities, changed constraints, and unsupported artifact
templates fail with a schema-contract error; the program does not add tables
to make an old manuscript archive appear current. Read commands and repository
boundaries use the same read-only guard. Existing data is retained; create a
separate fresh archive to use the new manuscript contract.

The AI layer freezes inputs and model evidence in `editorial_inputs`,
`editorial_job_inputs`, `editorial_model_calls`, `editorial_chunk_results`, and
`editorial_revisions`. `document_artifacts` records the exact revision/template
pair, `ai-draft` / `review-reference` role, controlled path and byte hash for
`ai-draft.md` and `review.md` under `ai-draft-v1`.

The publication layer stores immutable complete reader content in
`publication_editions`, exact edition/hash reviews in
`publication_edition_reviews`, versioned release artifacts in
`publication_releases`, and append-only operator facts in
`publication_events`. `publication_heads` has independent current edition and
current release pointers for each video part. Creating or reviewing edition B
leaves release A public until approved B is explicitly published. Withdrawing
the current release clears only the public pointer and keeps its history.

Complete reader content has its own canonical JSON SHA-256. The separately
rendered `publish.md` byte hash is also registered. The reviewer must submit
the exact content hash, and publication revalidates the edition, approval,
relationship and artifact. AI quality states are not publication approval.
See [publication.md](publication.md) for commands and export schemas; workflow
`publish` still means publication of transcript bundles.

### Normalized entity tables

| Table | Key | Contents |
|-------|-----|----------|
| `bilibili_users` | `mid` | The collected user and its current display label. |
| `videos` | `bvid` | One row per video: `aid`, owner `mid` (FK to `bilibili_users`), `title`, `pubdate`. |
| `video_parts` | `(bvid, page_index)` | One row per part: `cid`, part `title`, `duration_ms`, zero-based `page_index` (`{bvid}:p{page_index}` is the derived `work_id`, computed, never stored), `processing_status` (`discovered`, `metadata_collected`, `gone`), FK to `videos`. |

### Ingestion process tables

| Table | Key | Contents |
|-------|-----|----------|
| `ingestion_runs` | `run_id` | One row per collection run: target `mid`, source package and version, requested start page and page limit, `started_at` / `finished_at`, terminal `outcome` (`complete`, `limited`, `risk_interrupted`, `failed`). |
| `ingestion_pages` | `(run_id, page_number)` | One evidence row per requested page: `outcome` (`ok`, `empty`, `risk_interrupted`, `failed`) and a bounded scalar `error_code` on failure. |
| `ingestion_cursors` | `mid` | The resumable one-based cursor: `next_page`, `state` (`ready`, `complete`, `limited`, `risk_interrupted`), `observed_total`. |
| `ingestion_discoveries` | `(run_id, page_number, bvid)` | Run-scoped discovery evidence linking a run page to a discovered video. |

### Media and transcript tables

`transcripts` and `transcript_segments` store acquired captions and local ASR
results with their ordered segments. `harvest-subs` records caption acquisition;
the store-backed ASR path records local transcripts and their `asr_models`
identity. `adopt-transcripts` imports verified legacy bundles without ASR.

`derive-audio-inventory` records confined, hashed files in `audio_objects` and
`part_audio_objects`. The download and ASR store routes also record their
acquisition attempts and close their run rows. The execution manifest retains
per-stage state and published artifact paths alongside this store evidence.

### Views

| View | Contents |
|------|----------|
| `v_video_parts` | Every part with its derived `work_id` and the joined user/video context. |
| `v_ingestion_run_stats` | Per-run page and video counts (the `runs` command's source). |
| `v_pending_metadata` | Parts with `processing_status = 'discovered'` (the `status` command's pending work). |
| `v_pending_subtitles` | Every part that is not `gone` and has no stored transcript, ordered never-attempted first — the subtitle commands' work list, carrying the newest attempt's outcome, timestamp, and credential presence. |

### Manuscript Contract

Fresh archives also carry `schema-editorial.sql` and its explicit manuscript
contract marker. Opening an existing archive validates this contract before
any schema initialization, view refresh or commit. Legacy editorial tables,
missing required entities, changed constraints, and unsupported artifact
templates fail with a schema-contract error; the program does not add tables
to make an old manuscript archive appear current. Read commands and repository
boundaries use the same read-only guard. Existing data is retained; create a
separate fresh archive to use the new manuscript contract.

The AI layer freezes inputs and model evidence in `editorial_inputs`,
`editorial_job_inputs`, `editorial_model_calls`, `editorial_chunk_results`, and
`editorial_revisions`. `document_artifacts` records the exact revision/template
pair, `ai-draft` / `review-reference` role, controlled path and byte hash for
`ai-draft.md` and `review.md` under `ai-draft-v1`.

The publication layer stores immutable complete reader content in
`publication_editions`, exact edition/hash reviews in
`publication_edition_reviews`, versioned release artifacts in
`publication_releases`, and append-only operator facts in
`publication_events`. `publication_heads` has independent current edition and
current release pointers for each video part. Creating or reviewing edition B
leaves release A public until approved B is explicitly published. Withdrawing
the current release clears only the public pointer and keeps its history.

Complete reader content has its own canonical JSON SHA-256. The separately
rendered `publish.md` byte hash is also registered. The reviewer must submit
the exact content hash, and publication revalidates the edition, approval,
relationship and artifact. AI quality states are not publication approval.
See [publication.md](publication.md) for commands and export schemas; workflow
`publish` still means publication of transcript bundles.

### Normalized entity tables

| Table | Key | Contents |
|-------|-----|----------|
| `bilibili_users` | `mid` | The collected user and its current display label. |
| `videos` | `bvid` | One row per video: `aid`, owner `mid` (FK to `bilibili_users`), `title`, `pubdate`. |
| `video_parts` | `(bvid, page_index)` | One row per part: `cid`, part `title`, `duration_ms`, zero-based `page_index` (`{bvid}:p{page_index}` is the derived `work_id`, computed, never stored), `processing_status` (`discovered`, `metadata_collected`, `gone`), FK to `videos`. |

### Ingestion process tables

| Table | Key | Contents |
|-------|-----|----------|
| `ingestion_runs` | `run_id` | One row per collection run: target `mid`, source package and version, requested start page and page limit, `started_at` / `finished_at`, terminal `outcome` (`complete`, `limited`, `risk_interrupted`, `failed`). |
| `ingestion_pages` | `(run_id, page_number)` | One evidence row per requested page: `outcome` (`ok`, `empty`, `risk_interrupted`, `failed`) and a bounded scalar `error_code` on failure. |
| `ingestion_cursors` | `mid` | The resumable one-based cursor: `next_page`, `state` (`ready`, `complete`, `limited`, `risk_interrupted`), `observed_total`. |
| `ingestion_discoveries` | `(run_id, page_number, bvid)` | Run-scoped discovery evidence linking a run page to a discovered video. |

### Media and transcript tables

`transcripts` and `transcript_segments` store acquired captions and local ASR
results with their ordered segments. `harvest-subs` records caption acquisition;
the store-backed ASR path records local transcripts and their `asr_models`
identity. `adopt-transcripts` imports verified legacy bundles without ASR.

`derive-audio-inventory` records confined, hashed files in `audio_objects` and
`part_audio_objects`. The download and ASR store routes also record their
acquisition attempts and close their run rows. The execution manifest retains
per-stage state and published artifact paths alongside this store evidence.

### Views

| View | Contents |
|------|----------|
| `v_video_parts` | Every part with its derived `work_id` and the joined user/video context. |
| `v_ingestion_run_stats` | Per-run page and video counts (the `runs` command's source). |
| `v_pending_metadata` | Parts with `processing_status = 'discovered'` (the `status` command's pending work). |
| `v_pending_subtitles` | Every part that is not `gone` and has no stored transcript, ordered never-attempted first — the subtitle commands' work list, carrying the newest attempt's outcome, timestamp, and credential presence. |

## 数据身份与核心表

源站 P1 对应数据库 `page_index=0`。分 P 的稳定身份为 `(bvid, page_index)`；`video_part_id` 是该数据库分配的内部主键，适合 CLI 精确选择与外键关联。`work_id` 派生为 `BV…:p0`，不存储在实体表；文件目录使用 `BV….p0`，避免将冒号放进路径。公开播放链接的 `?p=` 值为 `page_index + 1`。

时间戳为 Unix 整数秒，视频时长和转录时间轴为整数毫秒。外键默认 `ON DELETE RESTRICT`，存储 API 不通过删除旧版本来覆盖历史结果。

### 元数据实体

| 表 | 主键 / 唯一身份 | 主要字段与约束 |
|---|---|---|
| `bilibili_users` | `mid` | `display_name`、`created_at`、`updated_at`。 |
| `videos` | `bvid`；`aid` 唯一 | `mid` 外键、`title`、`pubdate`、创建/更新时间。`aid` 可以为空。 |
| `video_parts` | `video_part_id`；`(bvid, page_index)` 唯一 | `cid > 0`、`duration_ms > 0`、`title`、`processing_status`、时间戳；索引零基且非负。 |
| `video_tags` | `(bvid, tag_id)` | `tag_name`、`tag_type`，`tag_id > 0`；保存当前标签集合。 |
| `video_details` | `bvid` | 可空的 `pic`、`"desc"`、`tid` 和 `observed_at`；非空 `tid > 0`。 |

`processing_status` 仅允许 `discovered`、`metadata_collected`、`gone`，表示元数据/可处理状态。`fetch-meta` 成功获取并校验分 P 后写入 `metadata_collected`。字幕和 ASR 结果存在独立表中，不将这个字段当作任务生命周期。

重采集遵循实际 upsert 范围：视频更新标题及更新时间，首次非空 `aid` 会被保留；已有 `mid`、`pubdate` 不因后续 upsert 改写。分 P 更新标题、时长、processing status 及更新时间，保留已有身份与 `cid`。上游列表中某个视频或分 P 消失，不会仅因本次未看到它就自动删除或标记 `gone`。

### 元数据采集过程

| 表 | 主键 | 主要证据 |
|---|---|---|
| `ingestion_runs` | `run_id` | `mid`、固定 source package `bilibili-api-python` 及实际版本、请求起始页、页数上限、开始/结束时间、outcome。 |
| `ingestion_pages` | `(run_id, page_number)` | 请求的一基页码、outcome、最多 64 字符的 `error_code`、开始/结束时间。 |
| `ingestion_cursors` | `mid` | 一基 `next_page`、可空 `observed_total`、state、last error、更新时间。 |
| `ingestion_discoveries` | `(run_id, page_number, bvid)` | 该 run/page 观察到视频的证据、可空 `source_position`、发现时间。 |

run outcomes 为 `running`、`complete`、`limited`、`risk_interrupted`、`failed`；page outcomes 为 `ok`、`empty`、`risk_interrupted`、`failed`。cursor state 为 `ready`、`complete`、`limited`、`risk_interrupted`。三者分别描述运行、一次页请求和下次恢复位置，不能互相替代。

### 音频、转录与获取证据

| 表 | 主键 / 唯一身份 | 主要字段与含义 |
|---|---|---|
| `audio_objects` | `audio_id`；`sha256`、`storage_key` 分别唯一 | 内容摘要、byte size、format、duration、外部文件相对路径与创建时间。 |
| `part_audio_objects` | `(video_part_id, audio_id)` | 分 P 到音频对象的多对多引用、获取时间与 acquisition source。 |
| `asr_models` | `model_id`；`(model_name, revision)` 唯一 | 本地 ASR 模型身份，未提供 revision 时使用空字符串。 |
| `transcripts` | `transcript_id`；`(video_part_id, source_kind, language, version)` 唯一 | `model_id`、正整数 version、64 字符小写 `content_sha256`、创建时间。 |
| `transcript_segments` | `(transcript_id, ordinal)` | 零基顺序、`start_ms`、`end_ms`、text；start 非负且 end 大于 start。 |
| `acquisition_runs` | `run_id` | kind、selector、requested limit、credential presence、时间与 outcome。 |
| `acquisition_attempts` | `(run_id, video_part_id)` | 每次尝试的 outcome、bounded error、可空 transcript ID、时间、credential/absence verified。 |
| `transcript_coverage_attestations` | `(run_id, video_part_id)` | transcript ID、decoded/produced seconds、coverage、coverage minimum 与 short 标志；外键关联对应 acquisition attempt。 |

`source_kind` 为 `subtitle-cc`、`subtitle-ai`、`asr-local`。caption 新版本的 `model_id` 为空，本地 ASR 新版本引用模型身份。caption 另有部分唯一索引 `(video_part_id, source_kind, language, content_sha256)`，避免同源同语言重复存相同内容。

acquisition kind 支持 `subtitle`、`audio`、`asr`；selector 为 `pending`（target 为空）或 `bvid`（target 必须非空，可保存 `BVID:pN`）。当前 workflow 的 subtitle 和 ASR handlers 使用 acquisition runs；audio handler 将下载事实写到音频对象与工作流 attempt，不创建同样的 acquisition run/attempt。表支持某种 kind，不代表每条当前执行路径都会写它。

acquisition run 的 outcome 为 `running`、`complete`、`partial`、`failed`；attempt 为 `stored`、`unchanged`、`no-subtitle`、`failed`。stored/unchanged 必须有 transcript ID 且无 error；failed 必须有 error 且无 transcript ID；no-subtitle 没有 transcript ID，只允许空 error 或 `not_found`。同一 run 对一个分 P 最多记录一行 attempt，重新尝试使用新 run。

coverage 是某次 ASR run 的事实，不是转录内容身份。同一 cue 内容可复用版本，但不同录音时长仍可产生独立 coverage attestation。当前工作流将测量写入该表；不应仅因有存储 attestation 就假定所有发布 sidecar 都携带同样测量。

### 工作流控制与发布登记

| 表 | 身份 | 作用 |
|---|---|---|
| `workflow_asr_profiles` | `profile_id`；`(profile_key, config_sha256)` 唯一 | 配置身份；关联完整快照，冻结独立模型版本、分块、语言、离线与生成策略等。 |
| `workflow_jobs` | `job_id`；`dedupe_key` 唯一 | kind、part/profile/policy、payload、status、priority、available time、lease、attempt count 与 last error。 |
| `workflow_job_dependencies` | `(job_id, prerequisite_job_id)` | 显式执行依赖；只在 prerequisite succeeded 后允许领取。 |
| `workflow_attempts` | `attempt_id` | job、worker、时间、outcome、error 与 result JSON；保存每次领取后的执行证据。 |
| `workflow_quality_assessments` | `assessment_id` | 分 P/source 的 0–1 score、assessor、details 与评估时间。 |
| `workflow_publications` | `publication_id`；`(video_part_id, transcript_id)` 唯一 | 发布时间与五项产物的 `artifact_json` 路径映射。 |

job statuses 为 `queued`、`running`、`succeeded`、`failed`、`cancelled`；attempt outcomes 为 `running`、`succeeded`、`failed`、`cancelled`。queued 尚未被领取时没有 attempt。acquisition run/attempt 是内容获取证据，workflow attempt 是领取与执行证据，两种 lifecycle 允许有不同的终态。

## 元数据分页与恢复

`fetch-meta` 默认 `mid=23191782`，每页请求 `PAGE_SIZE=30`，没有页大小 CLI 参数。省略 `--limit-pages` 使用 `10`，不会无限扫描。起始页优先级为显式 `--start-page`、已存游标的 `next_page`、第一页。`--resume` 与 `--start-page` 互斥；前者要求现有数据库且目标 mid 有游标。即使没有显式 `--resume`，省略 start page 仍会使用已有游标。

每个 run 先独立提交父用户与 run 起点。所有当前页的网络读取完成后，`MetadataRepository.record_page()` 在一个写组内按顺序提交用户观察、videos、parts、标签集合、details、discoveries、cursor 和 page outcome。任一写入失败会回滚整个页，前面已成功提交的页保留。同页重复 BVID 共用 detail/parts 获取，discovery 主键去重；重复行最终保留后一次 source position。

| 页结果 | 持久化与恢复位置 |
|---|---|
| 非空成功页，未到上限 | page=`ok`，cursor 指向下一页，state=`ready`。 |
| 非空成功页，达到上限 | page=`ok`，run/cursor=`limited`，cursor 指向下一页；退出 `0`。 |
| 空页 | page=`empty`，run/cursor=`complete`，cursor 留在该空页，后续恢复可再次验证；退出 `0`。 |
| rate control | page/run=`risk_interrupted`，只记录有界错误，已有 cursor 不变；退出 `2`。 |
| 其他 gateway failure | page/run=`failed`，失败页无实体载荷，已有 cursor 不变；退出 `2`。 |

`observed_total` 是该页响应报告的上游总数，可为空；它不是已抓取数量或完成证明。完成只由空列表决定，即使空页恰好落在页数上限，也记录 complete。run page count 包含空页和失败页请求，video count 来自该 run 的 distinct discoveries。

`--page-retries N` 允许 `0` 到 `3` 次额外的视频列表页请求，默认 `0`。只重试 `GatewayRateLimited`、`GatewayTransportError`，等待依次为 30、60、120 秒；不重试 shape/authentication/其他 response failure，不为整个 detail/parts fan-out 增加通用重试。等待期间不写当前页载荷；最终失败仍进入上述证据路径。

`--skip-failed-page` 在非 rate-limit failure 后额外提交 cursor=`page+1`、state=`ready`，保留 failed page 的 error 和 failed run 的终态，然后退出 `2`。它也会跳过可能恢复的 transport failure；rate control 不能跳过。显式 `--start-page` 可回到跳过页，亦可向后移动已有游标。此选项不会把失败页认定为成功。

```sh
bili-asr fetch-meta --archive-root archive --resume --limit-pages 10 --page-retries 2
bili-asr fetch-meta --archive-root archive --start-page 3 --limit-pages 1
```

内部异常打印固定 `fetch-meta: unexpected error` 并退出 `2`。最后一次已提交页保留，run 可能停在 running；先用 `runs` 和 `status` 检查现有证据。`runs` 包含 running rows，按 started_at 降序、run_id 降序稳定列出，默认不限行数，`--limit` 必须为正整数。

### 刷新事实与保留事实

每页使用第一个非空 author 刷新上传者名称；未观察到名称的页保留旧值与时间戳。只要观察到名称，该页就执行 user upsert，即使名称相同也刷新 `updated_at`；它表示最近一次名称观察，不保证名称发生变化。run 开始时的 `ensure_user()` 只建立缺失的父记录，不改写既有名称。新建用户在还未观察到名称时可先保存 mid 占位值。

标签是当前集合，成功空集合会清空旧标签；网关降级返回 `None` 或不可用 shape 时不提交该视频的标签变化。tag cache 每次 run 从空开始，至多保留 256 个近期 BVID 观察，包括降级答案；缓存驱逐后会再请求，当前页有独立答案集合以免驱逐影响该页持久化。因此跨 run/resume 可以重新读取同一视频标签，既有标签不充当当前新鲜度证明。

`video_details` 保存最后一次可用观察，三项全为空时不写入，也不刷新 observed_at；至少一项可用时整行替换，未观察到的其他项写为 NULL。它既不是历史表，也不是逐字段 last-known-good 合并。`pic` 为库内封面 URL；当前通用 workflow export 不包含该字段。

## 字幕观察、选择与凭据证据

[`SubtitleIngestor`](../src/bili_asr/services/subtitle_ingest.py) 仍提供 `probe()` 和 `harvest()` 服务方法。probe 只列轨道，不创建 run/attempt/transcript 或文件；它没有当前同名公共 CLI。harvest 接受 `SubtitleSelection`，列表与正文经 typed gateway 校验后写入 `TranscriptRepository`。workflow subtitle handler 以已存 BVID、零基 index 和 `limit=1` 获取一个分 P；`cid` 来自 `video_parts`，不重新请求 pagelist 来猜身份。

服务的显式 BVID selection 可包含已存转录，用于重新观察；pending selection 从 `v_pending_subtitles` 取工作，按 never-attempted、最早 last attempt、BVID、index 排序。公共 `workflow plan` 使用独立 jobs，不直接消费这条 pending enumeration。

### 轨道选择

每次获取至多选择一条轨道。默认排序键为 `(language family rank, is_ai, upstream index)`：family 依次为 `zh`、`en`、其他；同 family rank 下 CC 优先 AI，最后保持上游顺序。其他语言共享同一 rank，所以不同的非中英文 family 之间，CC 也可优先于较早出现的 AI。

family 由语言代码小写 primary subtag 派生；机器轨道先去掉 `ai-`。因此 `zh-CN`、`zh-Hans`、`zh-Hant`、`ai-zh` 都归为 `zh`。存储 language 仍保留 trimmed 原代码，family 不替代版本身份。

服务 API 的 `SubtitleSelection.languages` 可提供精确代码偏好：首个有匹配的代码获选，同代码下 CC 优先 AI，再按上游顺序。有效偏好无匹配时返回 no-subtitle。当前 workflow subtitle handler 使用默认选择；`workflow plan --language` 配置的是 ASR profile，不是字幕语言过滤参数。

| 实际观察 | acquisition attempt | 含义 |
|---|---|---|
| 列表非空、选中正文成功 | `stored` 或 `unchanged`，关联 transcript | 新 cue 内容追加版本；已存相同内容只记录新的 attempt。 |
| 列表为空或服务语言偏好无匹配 | `no-subtitle`，error 为空 | 本次没有可用轨道；不是永久无字幕结论。存在凭据时还须验证登录。 |
| 列表请求明确 `GatewayNotFound` | `no-subtitle` + `not_found`，`absence_verified=1` | 本次列表缺失证据，与正文不可获取不同。 |
| 选中轨道的正文 `not_found`/空正文 | `failed` + `subtitle_body_unavailable` | 已知轨道正文暂不可用，不证明列表缺失。 |
| authentication/rate/transport/response/shape failure | `failed` + bounded error | 失败证据；不会把失败解释成字幕耗尽。 |

服务 probe 的 listing not_found 为带 error 的失败观察；harvest 则按上表记录列表缺失。probe 结果不写入持久缺失证据。

正常 acquisition run 在所有尝试无 failed 时结束 complete（空选择也 complete）；部分失败为 partial；非空选择全部失败为 failed。unexpected exception 或取消会尝试把已经打开的 run 收尾为 failed 后向上抛出；清理失败不会替换原异常，因此进程崩溃或数据库不可写时仍可能留下 running，不能将 best-effort cleanup 理解为崩溃恢复保证。

### 凭据与网络边界

SESSDATA 从 `--sessdata` 优先读取，否则使用 `BILI_SESSDATA`；显式空 flag 强制匿名，不回落环境。输出及持久证据只包含 presence；`acquisition_runs.credential_present` 只表示配置存在，不能证明登录成功。服务对每次带凭据的空观察调用 `validate_subtitle_credentials()`，成功才将该 attempt 的 `credential_verified` 设为 1。失效登录或不可读验证结果记录 failed，不能累计为已认证空列表。

网关仅向应用返回验证过的 DTO 和有界 error code，不向数据库输出凭据、带签名字幕 URL、原始响应或上游异常文本。正文获取会重新列轨道以解析临时 URL，规范为 HTTPS，并向 CDN 使用空 Credential。正文 transport failure 允许一次额外的“重新列表 + 正文获取”；这不等同于 `fetch-meta --page-retries`，rate control 等其他错误仍直接上抛。

当前依赖声明为 `bilibili-api-python==17.4.2` 与 `curl_cffi>=0.16`。metadata user-list 使用该版本的 WBI Api，关闭 dm，始终提供字符串 w_webid；网关对部分逐视频 metadata 调用施加顺序 pacing。HTTP 412/429、API risk codes 映射 rate_limited，gone codes 映射 not_found，登录拒绝映射 authentication error，形状/传输/其他响应问题保留各自分类。

网关代理按首个非空值解析：构造器 `proxy=`、`BILI_HTTP_PROXY`、`HTTPS_PROXY`、`https_proxy`、`ALL_PROXY`、`all_proxy`。空白值视为未设置，解析结果写入上游 package 的进程全局 request settings；空 `BILI_HTTP_PROXY` 不屏蔽更低优先级环境变量。未解析到代理时保持 package 默认。该事实来自代码，不表示某个代理、凭据或上游 endpoint 当前可用。

## 不可变转录与写入事务

[`TranscriptRepository`](../src/bili_asr/storage/transcripts.py) 要求符合 schema 的连接。一个转录至少含一个 segment；每段校验整数时间、`0 <= start_ms < end_ms <= 10**12`、trim 后非空文本。保留传入 ordinal 顺序和允许的时间重叠，不自动排序。WebVTT 的额外可表示性约束发生在发布阶段，见 WebVTT 指南。

content hash 是以下 canonical 数据的 SHA-256：按 ordinal 排列的 `[start_ms, end_ms, trimmed_text]` 列表，使用 `json.dumps(..., ensure_ascii=False, separators=(",", ":"))` 编码为 UTF-8。时间或文本变化会改变身份；语言只 trim，不将不同代码折叠。

`record_acquired_transcript()` 在一个事务中验证 part/run、按 part/source/language/hash 查找既有内容、必要时追加 `max(version)+1` 及全部 segments，最后记录 stored/unchanged attempt。内容恢复到历史版本时复用那个版本，不新建一个相同版本。旧版本、segments 与 attempt 不被覆盖。subtitle 写入只接受 caption kinds。

`record_local_transcript()` 是单独的 ASR 写入入口，在同一事务内登记模型、新转录与 segments、attempt 和可选 coverage。其内容复用查询同样按 part/source/language/hash，model ID 不是版本唯一身份；重用既有 cue 内容时保留已有 transcript/model 关联。`read_transcript()` 默认取身份的最新 version，显式 version 仍可读取历史内容。

提供 `asr_evidence` 时，它也在同一结果事务写入 `transcript_asr_evidence`；cue 内容复用不跳过本次证据。完整快照与查询合同见 [ASR 参数与诊断](asr-configuration.md)。取消与过期租约的 write guard 同时保护诊断和转录写入。

acquisition run 的开始和结束分别独立提交；每个成功/无字幕/失败的 part attempt 是单独写组。不要将这些会自行提交的方法嵌套到包含其他待提交内容的 `MetadataRepository.transaction()` 中。纯 repository read 方法只执行 SELECT，不 commit，也不改写 caller 已持有的事务。

工作流向 transcript repository 注入 `write_guard`。结果事务先 `BEGIN IMMEDIATE`，在取得 SQLite 写锁后检查当前 job 的状态、owner、attempt count 和 lease，再允许写入。它拒绝嵌套事务，防止独立 repository 提前提交外层写组。API/模型返回之后及后续 publication 请求也会检查 ownership；取消已经提交时，迟到结果不能追加 transcript、segments、模型或成功 run 终态。

失败收尾是受控例外：`finish_acquisition_run(..., outcome="failed")` 不要求已撤销的 lease，允许将已打开 run 关闭为 failed。这条路径只收尾获取证据，不授权继续提交内容。workflow attempt 可为 cancelled，同时 acquisition run 为 failed，二者描述不同层次的事实。

## 视图、缺口与只读投影

| 视图 | 实际关系 |
|---|---|
| `v_video_parts` | 所有分 P，派生 work ID，连接用户名称和视频标题。 |
| `v_ingestion_run_stats` | 每 run 的 distinct page count、distinct discovered video count。 |
| `v_pending_metadata` | 仅 processing status=`discovered` 的 parts；是顶层 `status` 中 pending 的来源。 |
| `v_pending_subtitles` | 非 gone 且无任何 transcript 的 parts，携带最新 subtitle attempt 的 outcome/time/error/credential presence。 |
| `v_missing_subtitle` | 同一“非 gone 且无转录”缺口，附视频上下文，不含全部最新 attempt 字段。 |
| `v_missing_audio` | 非 gone、无 transcript、无 part_audio_objects 引用，且具有已确认字幕缺失证据的 parts。 |
| `v_missing_transcript` | 已有关联音频且无 transcript；允许 gone part，保留字节仍可本地转录。 |
| `v_part_pipeline` | 每 part 的事实状态：依次为 transcribed、audio_ok、audio_pending、no_subtitle、discovered。 |

subtitle 观察的“最新”按 attempt finished_at、run started_at、run rowid 降序确定，避免秒级同时间下随机 UUID 覆盖真实后一次观察。pending enumeration 优先从尚无 transcript 的 eligible parts 查询相关历史，避免将已完成 corpus 的全部 subtitle attempts 再窗口排序。

`v_missing_audio` 只有在最新 subtitle attempt 为 no-subtitle 且满足其一时成立：列表 not_found 并有 `absence_verified=1`；或无 error 的空观察带有效 credential proof，且历史已有至少两个 distinct credentialed、verified run 的同类空观察。匿名空列表、认证失败、正文失败与旧版未验证 not_found 都不证明耗尽。之后最新失败观察也不会被历史正当缺失覆盖。

这些视图描述数据缺口与历史证据，当前工作流依赖图不依赖它们决定“有字幕就不用 ASR”。`workflow plan` 总为有效选中 part 确保 subtitle job；`all`、`selected` 为选中 parts 确保 audio→ASR；`below-threshold` 只在该 part 最新质量评估存在且 score 低于阈值时创建 audio/ASR。没有质量评估不自动视为低分。可选 proofread→render_document 依赖 ASR；字幕结果不作为这条依赖链的 prerequisite。

BVID/part ID 选择先一次性验证全部目标与策略参数，再创建 profile/jobs；重复目标去重，稳定按 BVID/index/internal ID 排序。BVID 未指定 index 时选择所有非 gone parts 并打印 gone 排除项；显式 ID/index 指向 gone、缺失分 P、未知 BVID 或全部 gone 的视频则整次请求失败。重复 plan 通过 dedupe key 保留已有任务状态，不复活 cancelled。完整规则见 [BVID 选择指南](workflow-selection.md)。

[`services.workflow_projection.workflow_records()`](../src/bili_asr/services/workflow_projection.py) 使用独立 `mode=ro` 连接，从 active parts、transcripts、workflow_publications 生成每分 P 一条当前记录。数据库不存在时返回空集合，不创建数据库。状态为 meta_ok、subtitle_done、asr_done、archived，分别表示无转录、已存字幕、已存 ASR 和已登记且按默认读取规则确认完整的产物包；这些状态不同于 job status，也不同于 `v_part_pipeline`。

普通投影默认检查发布登记对应的完整包；`with_text=True` 从有序 segments 构建文本，不要求重读 TXT。integrity/coverage 读取时可保留数据库声明的 archived，再由自己的验证器判断产物缺陷，避免将损坏包误判为普通 backlog。该投影的来源优先为 CC、AI、ASR，语言偏向中文、再按 version/created_at/internal ID；发布候选的严格语言排序见下节，两种读者当前并非同一函数，应按实际用途解释。

元数据搜索也使用 `mode=ro`，直接查当前 title/description/tags，不建立 FTS；转录搜索 FTS 由 `search-index` 或显式 `search --rebuild` 更新。查询、export、publication export 消费 SQLite 投影，不通过 JSONL 补回缺失状态。publication export 只输出准确获批、已发布且有效 release 的 catalog/Markdown 快照；publication export-drafts 另行输出当前且从未发布的 edition 预览。两个 catalog v2 都登记正文和配对 AI 校验参照 review.md 的路径与字节哈希；editorial export 单独输出含审核事件和请求配置的完整私有审阅包。这些导出不是数据库或队列，也不代表仓库附带前端源码。

## 五产物发布与取消保护

publish job 以 `publish:{video_part_id}` 去重，一个分 P 共用一个发布任务。请求的 transcript ID 是触发证据；handler 执行时重新选择当前优先存储版本，按以下键排序：source kind `subtitle-cc`、`subtitle-ai`、`asr-local`；语言 family `zh`、`en`、其他；完整 language code 升序；version 降序。这个优先级先比较 kind，区别于获取轨道时先比较 family，因此较晚完成的 ASR 不会仅因完成时间覆盖已有优先字幕。

`services.transcript_projection` 本身是纯函数层，不开连接、不写文件；workflow handler 读取候选与 ordinal segments，将整数毫秒转换为秒交给 archive writer。发布的路径字段为 `srt_path`、`vtt_path`、`txt_path`、`md_path`、`raw_path`，相对该次写入根目录。

```text
archive/
  archive.db
  audio/BV_EXAMPLE.p0.m4a
  transcripts/BV_EXAMPLE.p0/
    bundle.srt
    bundle.vtt
    bundle.txt
    bundle.md
    bundle.raw.json
    .bundle-ready
```

`.bundle-ready` schema 为 `archive-bundle-v2`，声明五项路径与各自 SHA-256。文件存在、大小或 mtime 相同都不能证明完整；读者逐块哈希核对 marker、路径和全部内容。旧四产物包没有当前完整性契约，需从存储版本重发，不能通过补一个空 VTT 或伪造 marker 认定完成。

当前 workflow writer 先在 guard 外准备编码、摘要及暂存文件，然后进入 `WorkflowRepository.owned_transaction(job)`：取得 SQLite 写锁、检查精确 attempt ownership、使旧 marker 失效、依次替换五项产物、最后替换 marker，并在同一 guard 内 upsert `workflow_publications`。每次最终替换前仍执行 lease checkpoint；guard 成功退出才提交数据库。失败清理回调在数据库回滚和写锁释放前失效已开始发布的 marker，避免部分包被读者认可，也防止旧 attempt 退出时误删新 worker 的有效 marker。暂存文件按 writer 清理路径释放。

SQLite 与文件系统不是一个可回滚事务。若文件阶段在取消前已经取得写锁，取消要等该短事务完成，已提交的内容保留；之后取消尚为 running 的 job 仍可成功。若 job 的终态已经提交，取消为 noop。若取消先提交，后续 guard 拒绝最终替换和发布登记。中途文件写入、目录创建、暂存或已提交的早期 acquisition 证据不承诺因取消消失；有效 marker 和数据库状态决定可见结果。

取消不使用旧的 `coordinator/archive-writer.lock` 整次运行锁。claim、短结果提交和 cancel 通过 SQLite 写事务串行化，长时间网络/模型调用在锁外；文件写入还有 writer 自身的进程内互斥。lease 绑定 job ID、owner、attempt count 与截止时间，独立连接续租防止长推理被误回收。取消 queued job 没有伪 attempt，取消 running job 会关闭当前 attempt、清空 lease；依赖不自动级联取消，queued 后继通过 `blocked_by_cancelled` 显示阻塞。详见 [取消指南](workflow-cancellation.md)。

显式重建已有包只需要存储转录：

```sh
bili-asr workflow publish --archive-root archive --part-id 12 --part-id 13
bili-asr workflow run --archive-root archive --limit 10
bili-asr workflow status --archive-root archive --jobs
bili-asr verify --archive-root archive --format json
```

publish CLI 会在请求前解析完整 ID 集合并确认每个 part 有候选，报告各 job 的 status。force 请求可重新排队非 cancelled 的已完成发布；若原 job 为 cancelled，它保留取消状态，不更新请求内容。普通重复 plan 不保证重新执行已成功的发布。当前 workflow 发布同步执行，没有旧 `publish-transcripts` 的 pending scan、256 MiB verification budget、独立 publication supervisor 或对应 timeout flags；不要套用旧入口的读预算与整库锁说明。

`workflow run --artifact-root` / `BILI_ARTIFACT_ROOT` 指定音频、转录及阅读文档的产物写根，数据库保留在 archive root；读取按产物根、归档根的顺序探测，登记路径始终是相对路径。具体边界见 [产物根目录](artifact-root.md)。可选 AI 校对的 revision/rendered Markdown 有独立 schema 与渲染路径，不改变已存 transcript 或上述原始归档包的来源身份。

## 诊断与离线契约验证

`fetch-meta` 的 `0` 表示 complete 或 limited，`1` 表示参数/根目录/恢复配置错误，`2` 表示 gateway failure 或内部异常。`workflow plan/publish/cancel/retry` 的可识别选择或 schema 错误为 `1`；`workflow run` 在 failed 非零时为 `1`，仅取消不作为 failure。输出 `succeeded/failed/cancelled/idle` 表达本次执行结果，不表示整个 corpus 已归档。`workflow run` 的未被转换的内部异常和底层 SQLite/I/O 错误没有统一的额外退出码保证。

顶层 `status`、`runs` 对不存在或无法打开的数据库给出 bounded 诊断。它们不修复损坏库；更早 schema 的后续查询兼容性仍取决于实际对象，打开成功不等于所有读取入口可用。`verify` 默认将声明发布后的产物缺失/损坏作为 defect 并退出 `1`，未发布内容作为 backlog；strict 模式也将 backlog 计为失败。coverage 只有通过完整性检查的五产物才计为 complete。

以下当前测试覆盖主要离线契约，可作为进一步追踪入口：

- [`test_metadata_repository.py`](../tests/test_metadata_repository.py)、[`test_metadata_ingest.py`](../tests/test_metadata_ingest.py)、[`test_metadata_page_retries.py`](../tests/test_metadata_page_retries.py)：页事务、游标、刷新与有界重试。
- [`test_transcript_repository.py`](../tests/test_transcript_repository.py)、[`test_subtitles.py`](../tests/test_subtitles.py)、[`test_pending_subtitles_cost.py`](../tests/test_pending_subtitles_cost.py)：版本身份、观察/凭据和 pending 查询成本。
- [`test_workflow_control_plane.py`](../tests/test_workflow_control_plane.py)、[`test_workflow_selection.py`](../tests/test_workflow_selection.py)、[`test_workflow_lease_heartbeat.py`](../tests/test_workflow_lease_heartbeat.py)、[`test_workflow_cancellation.py`](../tests/test_workflow_cancellation.py)：独立规划、租约、精确选择、取消及真实 SQLite 连接竞态。
- [`test_webvtt.py`](../tests/test_webvtt.py)、[`test_ai_editorial.py`](../tests/test_ai_editorial.py)：五产物完整性、发布 guard 与独立校对/渲染。

本文依据当前代码与离线契约更新，不将旧入口的历史 live smoke 结果视为当前 CLI 的实网验证，也不声明这次文档更新验证了上游网络、账号权限或模型服务可用性。
## 任务状态、阻塞解释与定向恢复

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

## 本机多进程 SQLite 运行范围

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


### 可选标签观察与补采

`fetch-meta` 继续把标签作为 best-effort 元数据，但会展示标签调用的尝试、成功、失败计数，
在列表采集 complete 而标签仍缺失时提醒覆盖不完整。成功非空、成功空、不可用分别记录为
`video_tag_observations.state` 的 `success_nonempty`、`success_empty`、`unavailable`；
没有观察行表示未尝试。观察包含时间、受控错误类别和所属 run_id，不保存原始响应、Cookie 或签名 URL。

`bili-asr fetch-tags --archive-root ROOT --bvid BV...` 专门补采已归档视频；可重复 --bvid，
省略时补采归档中的全部视频。失败保留上次成功标签，只有成功空集合才清空源集合；存在失败时退出 2。

这个观察表是严格限定的可加扩展：原有兼容数据库缺少该表时，open_database 可以仅建立该表，
不改写已有表、源标签、转录、任务或人工审核历史。若该表已存在但契约不符仍拒绝。
其他原有缺表、旧字段、约束不匹配，以及旧 manuscript schema 的拒绝规则继续适用。
publication 只读操作把缺少观察表视为未知覆盖，不自动初始化。
