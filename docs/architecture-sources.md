# 源码与覆盖清单

固定基线：main `9b289570494b5e8f7cc564a7eaa5b2eb2c28c3ad`；2026-10-09。

清单包含 15 个顶层命令及 34 个实际命令路径、97 个 Python 产品模块、4 个 SQL schema 的全部表/视图，以及部署/评测脚本。源码中的函数能力与当前已注册运行路径分别说明；历史 docstring 不作为命令存在证据。

[架构总览](architecture.md) · [完整时序](architecture-sequences.md) · [验证记录](architecture-validation.md)

## 命令覆盖

| 命令 | 写入面或读取契约 | 时序 |
| --- | --- | --- |
| `fetch-meta` | 元数据、页/cursor/run/tag 观察写入 | 02 |
| `fetch-tags` | 原始 tags 与观察写入 | 02 |
| `workflow plan` | profile 与 job/dependency 写入 | 03 |
| `workflow proofread` | 冻结 input 与 proofread/render job | 09 |
| `workflow render` | 显式 revision render job | 10 |
| `workflow run` | claim/attempt/lease 与业务产物写入 | 04–10 |
| `workflow status` | 可初始化连接，读取 counts/jobs/details/blockers | 01、04 |
| `workflow explain` | 可初始化连接，读取精确 job/dependency/attempt | 04 |
| `workflow asr-evidence` | 可初始化连接，读取指定 run/part ASR evidence | 07 |
| `workflow cancel` | queued/running 与 running attempt 原子取消 | 04 |
| `workflow retry` | 仅 failed 重排，保留 attempts | 04 |
| `workflow publish` | 从已存转录 force 请求单 part bundle job | 08 |
| `snapshot save` | 只读源 DB backup；完整私有 ZIP；独占维护锁 | 15 |
| `snapshot check` | ZIP 全文件/DB/引用校验；临时 DB | 15 |
| `snapshot restore` | 暂存验证/中断恢复，安装新完整 archive | 15 |
| `status` | 已有库初始化/派生视图刷新及汇总；不创建缺失库 | 01、13 |
| `runs` | 已有库初始化/派生视图刷新及 run 汇总；不创建缺失库 | 01、02 |
| `coverage` | 只读投影/质量/产物 diagnostics；strict 判定 | 13 |
| `verify` | 只读 declared bundle 完整性与缺陷 | 13 |
| `export` | 只读普通 JSON/CSV，可带文本；非出版快照 | 13 |
| `search` | 只读 metadata/transcripts/all；--rebuild 另行写 FTS | 14 |
| `search-index` | 显式 FTS schema/build/progress 写入 | 14 |
| `dedup report` | 只读 SQLite hash/part 复用，不读取产物字节 | 13 |
| `check-asr-env` | 环境/模型/device 诊断 | 16 |
| `publication create` | AI 基线验证、新 edition/review/events、draft CAS | 11 |
| `publication edit` | 正文/允许元数据生成新 edition/review/events | 11 |
| `publication sync-source-tags` | 成功原始标签观察冻结到新 edition | 02、11 |
| `publication review` | 精确 edition/hash/状态 CAS 与审核 events | 11 |
| `publication publish` | 固定稿、批准重验、release/head/events 写入 | 11 |
| `publication withdraw` | release 状态/head/events 写入，历史保留 | 11 |
| `publication show` | 只读指定 edition 与 review/head | 11 |
| `publication export` | 只读有效 release，完整公开快照替换 | 12 |
| `publication export-drafts` | 只读当前且从未发布 edition，预览快照替换 | 12 |
| `editorial export` | 只读精确 revision/edition，完整私有快照替换 | 12 |

## 全部产品模块

以下路径以 src/bili_asr 为根，全部模块恰好出现一次。每个子系统的交互证据另列在相应时序页；包导出与纯 helper 不额外虚构进程。

| 源码模块 | 责任与调用边界 | 时序 |
| --- | --- | --- |
| [__init__.py](../src/bili_asr/__init__.py) | 包版本与稳定导出 | 01 |
| [__main__.py](../src/bili_asr/__main__.py) | python -m bili_asr 入口 | 01 |
| [archive.py](../src/bili_asr/archive.py) | 五文件布局、格式编码、安全替换、完成 marker、bundle hash 校验 | 08、13 |
| [archive_maintenance.py](../src/bili_asr/archive_maintenance.py) | 合作 writer 共享访问及 snapshot 独占 OS 锁 | 01、15 |
| [artifact_root.py](../src/bili_asr/artifact_root.py) | flag/env/root 解析、读根优先与音频复用 | 01、06 |
| [artifacts.py](../src/bili_asr/artifacts.py) | 必需 artifact keys 与发布产品身份 | 08、13 |
| [asr/__init__.py](../src/bili_asr/asr/__init__.py) | ASR 包导出与兼容接口 | 07 |
| [asr/alignment.py](../src/bili_asr/asr/alignment.py) | 真实字符对齐、时间校验、cue 归并 | 07 |
| [asr/audio.py](../src/bili_asr/asr/audio.py) | 音频输入物化、soundfile/ffmpeg RF64、完整切块 | 07 |
| [asr/config.py](../src/bili_asr/asr/config.py) | 完整 ASRConfig 校验与环境默认解析 | 03、07 |
| [asr/constants.py](../src/bili_asr/asr/constants.py) | 模型、语言、分块和生成预算常量 | 03、07 |
| [asr/coverage.py](../src/bili_asr/asr/coverage.py) | 解码/输出跨度覆盖 attestation | 07 |
| [asr/diagnostics.py](../src/bili_asr/asr/diagnostics.py) | 运行环境、逐块/逐遍诊断与质量告警 | 07 |
| [asr/errors.py](../src/bili_asr/asr/errors.py) | 依赖、音频、模型、覆盖异常分类 | 07 |
| [asr/hotwords.py](../src/bili_asr/asr/hotwords.py) | 第一遍与字幕证据的候选热词 guard | 07 |
| [asr/provenance.py](../src/bili_asr/asr/provenance.py) | 模型身份、语言与脱敏配置来源 | 07 |
| [asr/runner.py](../src/bili_asr/asr/runner.py) | 模型懒加载、两遍生成、真实对齐、GPU spawn watchdog | 07 |
| [audio.py](../src/bili_asr/audio.py) | DASH 音频暂存下载、格式与受限路径 | 06 |
| [audio_budget.py](../src/bili_asr/audio_budget.py) | 保留库：音频目录预算与预测下载尺寸 | 16 |
| [audio_reclaim.py](../src/bili_asr/audio_reclaim.py) | 保留库：受限音频候选与显式回收 | 16 |
| [bili_client.py](../src/bili_asr/bili_client.py) | 同步 HTTP、风控/退避、DASH 音频及流式 CDN | 06 |
| [check_asr_env.py](../src/bili_asr/check_asr_env.py) | 模型/aligner/torch/ffmpeg/device 环境诊断 | 16 |
| [cli/__init__.py](../src/bili_asr/cli/__init__.py) | 公共 CLI 导出、入口及兼容测试接口 | 01 |
| [cli/_shared.py](../src/bili_asr/cli/_shared.py) | 参数、错误、roots 和 SQLite 读取共享入口 | 01 |
| [cli/dedup.py](../src/bili_asr/cli/dedup.py) | dedup report 只读命令 | 13 |
| [cli/editorial.py](../src/bili_asr/cli/editorial.py) | 精确 revision/edition 私有 export 命令 | 12 |
| [cli/main.py](../src/bili_asr/cli/main.py) | 注册分派、artifact 策略、archive access、SQLite 争用诊断 | 01 |
| [cli/meta.py](../src/bili_asr/cli/meta.py) | fetch-meta/fetch-tags 组合与 run 结果 | 02 |
| [cli/ops.py](../src/bili_asr/cli/ops.py) | check-asr-env、普通 export、verify | 13、16 |
| [cli/parser.py](../src/bili_asr/cli/parser.py) | 完整顶层命令参数及 registration 一致性 | 01 |
| [cli/publication.py](../src/bili_asr/cli/publication.py) | 出版子命令、严格输入 JSON、读/写连接与策略 | 11、12 |
| [cli/registry.py](../src/bili_asr/cli/registry.py) | 15 顶层命令和 ArtifactPolicy 登记 | 01 |
| [cli/search.py](../src/bili_asr/cli/search.py) | FTS build、scope/UTC/limit 与结果诊断 | 14 |
| [cli/snapshot.py](../src/bili_asr/cli/snapshot.py) | save/check/restore 参数和服务分派 | 15 |
| [cli/status_cmd.py](../src/bili_asr/cli/status_cmd.py) | status/runs SQLite 汇总与 coverage | 01、13 |
| [cli/workflow.py](../src/bili_asr/cli/workflow.py) | 所有 workflow 子命令及完整配置冻结/handler 组合 | 03、04 |
| [concurrency_gate.py](../src/bili_asr/concurrency_gate.py) | 保留库：worker 容量门禁及进程边界 | 16 |
| [config.py](../src/bili_asr/config.py) | 归档/采集默认配置与 SESSDATA 解析 | 01、02 |
| [coverage_report.py](../src/bili_asr/coverage_report.py) | 投影覆盖汇总、质量数据与 diagnostics | 13 |
| [cues.py](../src/bili_asr/cues.py) | 时间轴解析、route 与字符/segment 规范 | 07、08、16 |
| [dedup.py](../src/bili_asr/dedup.py) | 数据库内 hash/source/language 与音频关联复用报告 | 13 |
| [deepseek.py](../src/bili_asr/deepseek.py) | HTTPS JSON 适配、请求/响应结构与无隐式 retry | 09 |
| [diagnostics.py](../src/bili_asr/diagnostics.py) | 诊断流与敏感信息边界 | 01、16 |
| [editorial.py](../src/bili_asr/editorial.py) | 冻结输入、预算分块、引用/段落校验和渲染分派 | 09、10 |
| [editorial_runtime.py](../src/bili_asr/editorial_runtime.py) | proofread/render handler、审计与 lease 保护提交 | 09、10 |
| [export.py](../src/bili_asr/export.py) | 普通 JSON/CSV 数据投影与文本导出 | 13 |
| [export_snapshot.py](../src/bili_asr/export_snapshot.py) | 三类稿件快照归属校验、锁、manifest、日志/目录恢复 | 12 |
| [formatting.py](../src/bili_asr/formatting.py) | UTC 日期、时长、正文、SRT/VTT 共享纯格式化 | 08、14 |
| [integrity.py](../src/bili_asr/integrity.py) | 声明 bundle 完整性、terminal 缺陷和可重试 backlog 分类 | 13 |
| [long_live.py](../src/bili_asr/long_live.py) | 保留库：长直播识别与显式过滤策略 | 16 |
| [manuscript_files.py](../src/bili_asr/manuscript_files.py) | 固定稿件安全路径、原子文件写入及摘要读取 | 10、11、12 |
| [manuscript_templates.py](../src/bili_asr/manuscript_templates.py) | 不可变 v1 renderer 与按保存版本验证的注册表 | 10、11 |
| [meta_cursor.py](../src/bili_asr/meta_cursor.py) | 保留库：历史文件 cursor 契约；当前 metadata 用 SQLite | 16 |
| [page_identity.py](../src/bili_asr/page_identity.py) | BVID/零基页/cid/work_id 与 artifact stem 身份 | 03、06、08 |
| [path_policy.py](../src/bili_asr/path_policy.py) | 可移植 key、confined 音频和文件访问 | 01、06、15 |
| [persistence.py](../src/bili_asr/persistence.py) | 保留库：历史 run/manifest 文件契约及原子写支持 | 16 |
| [proofread.py](../src/bili_asr/proofread.py) | 保留库：ASR/字幕双路对照、coverage guards 与人工 merge | 16 |
| [publication.py](../src/bili_asr/publication.py) | 完整内容、AI/release 校验、create/edit/review/publish/withdraw | 11、12 |
| [publication_export.py](../src/bili_asr/publication_export.py) | 有效公开、从未发布预览及精确私有审阅出口 | 12 |
| [publication_tags.py](../src/bili_asr/publication_tags.py) | 原始 tags/观察覆盖、显式 CAS 新版 tags 同步 | 02、11 |
| [quality.py](../src/bili_asr/quality.py) | 原始产物质量与字符/覆盖安全诊断；库能力 | 07、13、16 |
| [search_index/__init__.py](../src/bili_asr/search_index/__init__.py) | 检索包导出 | 14 |
| [search_index/common.py](../src/bili_asr/search_index/common.py) | FTS DDL、block key、脱敏和 CJK bigram | 14 |
| [search_index/constants.py](../src/bili_asr/search_index/constants.py) | FTS 表、来源、tokenizer 与批量常量 | 14 |
| [search_index/errors.py](../src/bili_asr/search_index/errors.py) | missing/backlog、坏 store 与 FTS 不可用分类 | 14 |
| [search_index/metadata.py](../src/bili_asr/search_index/metadata.py) | 当前元数据只读字面检索 | 14 |
| [search_index/models.py](../src/bili_asr/search_index/models.py) | metadata/transcript hit 类型 | 14 |
| [search_index/query.py](../src/bili_asr/search_index/query.py) | metadata 在前、共享 limit、源健康与 diagnostics | 14 |
| [search_index/readers.py](../src/bili_asr/search_index/readers.py) | 受限根回退、bundle/MD 文本读取 | 13、14 |
| [search_index/store.py](../src/bili_asr/search_index/store.py) | FTS5 schema/tokenizer、批次水位恢复、增量与查询 | 14 |
| [services/__init__.py](../src/bili_asr/services/__init__.py) | 服务包边界 | 01 |
| [services/_common.py](../src/bili_asr/services/_common.py) | 服务共享的有界来源/存储转换 | 02、05 |
| [services/archive_snapshot.py](../src/bili_asr/services/archive_snapshot.py) | 完整 ZIP 流式 save/check/restore 和安全引用校验 | 15 |
| [services/audio_inventory.py](../src/bili_asr/services/audio_inventory.py) | 保留库：既有音频与 SQLite 对账/登记 | 16 |
| [services/bundle_verification.py](../src/bili_asr/services/bundle_verification.py) | 保留独立服务：子进程 deadline 与真实读预算 | 13、16 |
| [services/metadata_ingest.py](../src/bili_asr/services/metadata_ingest.py) | 分页、retry/skip、实体与游标事务、标签观察 | 02 |
| [services/publication_supervisor.py](../src/bili_asr/services/publication_supervisor.py) | 保留独立服务：loopback phase、进程 deadline/容量 | 16 |
| [services/subtitle_ingest.py](../src/bili_asr/services/subtitle_ingest.py) | 轨道选择、凭据/缺失证明、获取与失败收尾 | 05 |
| [services/transcript_adoption.py](../src/bili_asr/services/transcript_adoption.py) | 保留库：严格受限历史 bundle 转录读取 | 16 |
| [services/transcript_projection.py](../src/bili_asr/services/transcript_projection.py) | 纯版本总排序、候选与 writer segments 转换 | 08 |
| [services/video_tags.py](../src/bili_asr/services/video_tags.py) | 完整 BVID 验证与 best-effort 标签观察事务 | 02 |
| [services/workflow_projection.py](../src/bili_asr/services/workflow_projection.py) | 只读当前 facts、bundle 声明与派生状态 | 13 |
| [sources/__init__.py](../src/bili_asr/sources/__init__.py) | 来源适配包导出 | 02、05 |
| [sources/bilibili_api_gateway.py](../src/bili_asr/sources/bilibili_api_gateway.py) | 固定 SDK gateway、DTO、凭据/proxy/pacing 和来源请求 | 02、05 |
| [sources/models.py](../src/bili_asr/sources/models.py) | Gateway protocol、DTO 和有界外部错误 | 02、05 |
| [storage/__init__.py](../src/bili_asr/storage/__init__.py) | repository/records 的稳定存储导出 | 01 |
| [storage/database.py](../src/bili_asr/storage/database.py) | 连接、busy timeout、schema/模板契约、派生视图刷新 | 01、15 |
| [storage/editorial.py](../src/bili_asr/storage/editorial.py) | 固定 input/job/call/chunk/revision 与双稿登记 | 09、10 |
| [storage/metadata.py](../src/bili_asr/storage/metadata.py) | 元数据实体、页/cursor/run 和标签观察仓库 | 02 |
| [storage/models.py](../src/bili_asr/storage/models.py) | 元数据/获取/转录/音频不可变记录类型 | 02、05、07 |
| [storage/publication.py](../src/bili_asr/storage/publication.py) | edition/review/head CAS、release/events、withdraw | 11 |
| [storage/snapshots.py](../src/bili_asr/storage/snapshots.py) | 完整 schema/FK、backup、引用与中断状态恢复 | 15 |
| [storage/transcripts.py](../src/bili_asr/storage/transcripts.py) | 不可变 versions/segments、acquisition、coverage/ASR evidence | 05、07 |
| [storage/workflow.py](../src/bili_asr/storage/workflow.py) | profiles/jobs/dependencies/claim/lease/cancel/retry/terminal | 03、04 |
| [storage/workflow_selection.py](../src/bili_asr/storage/workflow_selection.py) | 完整 BVID/part 选择验证和 gone 处理 | 03 |
| [workflow.py](../src/bili_asr/workflow.py) | 单 job executor、独立连接 heartbeat、精确 attempt 终态 | 04 |
| [workflow_runtime.py](../src/bili_asr/workflow_runtime.py) | subtitle/audio/ASR/publish 具体任务及各提交边界 | 05、06、07、08 |

## SQLite 全部持久表

列清单来自本次四份 SQL 在临时内存库的 PRAGMA table_info；PK/UNIQUE/CHECK/索引精确定义保留在源 SQL。表组均位于一个 archive.db。FTS 派生表由显式索引路径另建。

| 表与定义 | 全部字段 | 外键关系 |
| --- | --- | --- |
| [acquisition_attempts](../src/bili_asr/storage/schema-transcripts.sql#L71) | `run_id`、`video_part_id`、`outcome`、`error_code`、`transcript_id`、`started_at`、`finished_at`、`credential_verified`、`absence_verified` | transcript_id → transcripts.transcript_id (RESTRICT)；video_part_id → video_parts.video_part_id (RESTRICT)；run_id → acquisition_runs.run_id (RESTRICT) |
| [acquisition_runs](../src/bili_asr/storage/schema-transcripts.sql#L49) | `run_id`、`kind`、`selector_kind`、`selector_target`、`requested_limit`、`credential_present`、`started_at`、`finished_at`、`outcome` | 无 |
| [asr_models](../src/bili_asr/storage/schema.sql#L150) | `model_id`、`model_name`、`revision`、`created_at` | 无 |
| [audio_objects](../src/bili_asr/storage/schema.sql#L130) | `audio_id`、`sha256`、`byte_size`、`format`、`duration_ms`、`storage_key`、`created_at` | 无 |
| [bilibili_users](../src/bili_asr/storage/schema.sql#L3) | `mid`、`display_name`、`created_at`、`updated_at` | 无 |
| [document_artifacts](../src/bili_asr/storage/schema-editorial.sql#L51) | `revision_id`、`template_version`、`artifact_name`、`manuscript_role`、`relative_path`、`content_sha256` | revision_id → editorial_revisions.revision_id (NO ACTION) |
| [editorial_chunk_results](../src/bili_asr/storage/schema-editorial.sql#L34) | `input_id`、`chunk_id`、`call_id`、`blocks_json` | call_id → editorial_model_calls.call_id (NO ACTION)；input_id → editorial_inputs.input_id (NO ACTION) |
| [editorial_inputs](../src/bili_asr/storage/schema-editorial.sql#L7) | `input_id`、`video_part_id`、`base_transcript_id`、`reference_transcript_id`、`prepared_json`、`created_at` | reference_transcript_id → transcripts.transcript_id (NO ACTION)；base_transcript_id → transcripts.transcript_id (NO ACTION)；video_part_id → video_parts.video_part_id (NO ACTION) |
| [editorial_job_inputs](../src/bili_asr/storage/schema-editorial.sql#L16) | `job_id`、`input_id` | input_id → editorial_inputs.input_id (NO ACTION)；job_id → workflow_jobs.job_id (NO ACTION) |
| [editorial_model_calls](../src/bili_asr/storage/schema-editorial.sql#L21) | `call_id`、`attempt_id`、`input_id`、`chunk_id`、`request_json`、`response_json`、`error_code`、`started_at`、`finished_at` | input_id → editorial_inputs.input_id (NO ACTION)；attempt_id → workflow_attempts.attempt_id (NO ACTION) |
| [editorial_revisions](../src/bili_asr/storage/schema-editorial.sql#L42) | `revision_id`、`input_id`、`job_id`、`blocks_json`、`quality_status`、`created_at` | job_id → workflow_jobs.job_id (NO ACTION)；input_id → editorial_inputs.input_id (NO ACTION) |
| [ingestion_cursors](../src/bili_asr/storage/schema.sql#L92) | `mid`、`next_page`、`observed_total`、`state`、`last_error_code`、`updated_at` | mid → bilibili_users.mid (RESTRICT) |
| [ingestion_discoveries](../src/bili_asr/storage/schema.sql#L117) | `run_id`、`page_number`、`bvid`、`source_position`、`discovered_at` | bvid → videos.bvid (RESTRICT)；run_id → ingestion_runs.run_id (RESTRICT) |
| [ingestion_pages](../src/bili_asr/storage/schema.sql#L104) | `run_id`、`page_number`、`outcome`、`error_code`、`started_at`、`finished_at` | run_id → ingestion_runs.run_id (RESTRICT) |
| [ingestion_runs](../src/bili_asr/storage/schema.sql#L75) | `run_id`、`mid`、`source_package`、`source_version`、`requested_start_page`、`requested_page_limit`、`started_at`、`finished_at`、`outcome` | mid → bilibili_users.mid (RESTRICT) |
| [manuscript_contract](../src/bili_asr/storage/schema-editorial.sql#L2) | `version` | 无 |
| [part_audio_objects](../src/bili_asr/storage/schema.sql#L140) | `video_part_id`、`audio_id`、`acquired_at`、`acquisition_source` | audio_id → audio_objects.audio_id (RESTRICT)；video_part_id → video_parts.video_part_id (RESTRICT) |
| [publication_edition_reviews](../src/bili_asr/storage/schema-editorial.sql#L79) | `edition_id`、`review_id`、`content_sha256`、`status`、`actor`、`note`、`issue_url`、`updated_at` | edition_id → publication_editions.edition_id (NO ACTION) |
| [publication_editions](../src/bili_asr/storage/schema-editorial.sql#L65) | `edition_id`、`video_part_id`、`revision_id`、`parent_edition_id`、`content_json`、`content_sha256`、`created_at`、`created_by`、`note` | parent_edition_id → publication_editions.edition_id (NO ACTION)；revision_id → editorial_revisions.revision_id (NO ACTION)；video_part_id → video_parts.video_part_id (NO ACTION) |
| [publication_events](../src/bili_asr/storage/schema-editorial.sql#L119) | `event_id`、`video_part_id`、`edition_id`、`release_id`、`review_id`、`content_sha256`、`event_type`、`from_status`、`to_status`、`actor`、`issue_url`、`note`、`changed_at` | review_id → publication_edition_reviews.review_id (NO ACTION)；release_id → publication_releases.release_id (NO ACTION)；edition_id → publication_editions.edition_id (NO ACTION)；video_part_id → video_parts.video_part_id (NO ACTION) |
| [publication_heads](../src/bili_asr/storage/schema-editorial.sql#L113) | `video_part_id`、`current_edition_id`、`current_release_id` | current_release_id → publication_releases.release_id (NO ACTION)；current_edition_id → publication_editions.edition_id (NO ACTION)；video_part_id → video_parts.video_part_id (NO ACTION) |
| [publication_releases](../src/bili_asr/storage/schema-editorial.sql#L95) | `release_id`、`video_part_id`、`edition_id`、`review_id`、`content_sha256`、`template_version`、`relative_path`、`artifact_sha256`、`published_at`、`published_by`、`status` | review_id → publication_edition_reviews.review_id (NO ACTION)；edition_id → publication_editions.edition_id (NO ACTION)；video_part_id → video_parts.video_part_id (NO ACTION) |
| [transcript_asr_evidence](../src/bili_asr/storage/schema-transcripts.sql#L129) | `run_id`、`video_part_id`、`transcript_id`、`schema_version`、`evidence_json` | transcript_id → transcripts.transcript_id (RESTRICT)；(run_id, video_part_id) → acquisition_attempts.(run_id, video_part_id) (RESTRICT) |
| [transcript_coverage_attestations](../src/bili_asr/storage/schema-transcripts.sql#L109) | `run_id`、`video_part_id`、`transcript_id`、`decoded_s`、`produced_s`、`coverage`、`coverage_min`、`coverage_short` | transcript_id → transcripts.transcript_id (RESTRICT)；(run_id, video_part_id) → acquisition_attempts.(run_id, video_part_id) (RESTRICT) |
| [transcript_segments](../src/bili_asr/storage/schema-transcripts.sql#L36) | `transcript_id`、`ordinal`、`start_ms`、`end_ms`、`text` | transcript_id → transcripts.transcript_id (RESTRICT) |
| [transcripts](../src/bili_asr/storage/schema-transcripts.sql#L11) | `transcript_id`、`video_part_id`、`source_kind`、`language`、`model_id`、`version`、`content_sha256`、`created_at` | model_id → asr_models.model_id (RESTRICT)；video_part_id → video_parts.video_part_id (RESTRICT) |
| [video_details](../src/bili_asr/storage/schema.sql#L66) | `bvid`、`pic`、`desc`、`tid`、`observed_at` | bvid → videos.bvid (RESTRICT) |
| [video_parts](../src/bili_asr/storage/schema.sql#L21) | `video_part_id`、`bvid`、`page_index`、`cid`、`title`、`duration_ms`、`processing_status`、`created_at`、`updated_at` | bvid → videos.bvid (RESTRICT) |
| [video_tag_observations](../src/bili_asr/storage/schema.sql#L47) | `bvid`、`state`、`observed_at`、`error_code`、`run_id` | bvid → videos.bvid (RESTRICT) |
| [video_tags](../src/bili_asr/storage/schema.sql#L37) | `bvid`、`tag_id`、`tag_name`、`tag_type` | bvid → videos.bvid (RESTRICT) |
| [videos](../src/bili_asr/storage/schema.sql#L10) | `bvid`、`aid`、`mid`、`title`、`pubdate`、`created_at`、`updated_at` | mid → bilibili_users.mid (RESTRICT) |
| [workflow_asr_profile_configs](../src/bili_asr/storage/schema-workflow.sql#L23) | `profile_id`、`schema_version`、`config_json` | profile_id → workflow_asr_profiles.profile_id (RESTRICT) |
| [workflow_asr_profiles](../src/bili_asr/storage/schema-workflow.sql#L7) | `profile_id`、`profile_key`、`model_name`、`model_revision`、`aligner_name`、`device`、`language`、`config_sha256`、`created_at` | 无 |
| [workflow_attempts](../src/bili_asr/storage/schema-workflow.sql#L67) | `attempt_id`、`job_id`、`worker_id`、`started_at`、`finished_at`、`outcome`、`error_code`、`result_json` | job_id → workflow_jobs.job_id (RESTRICT) |
| [workflow_job_dependencies](../src/bili_asr/storage/schema-workflow.sql#L58) | `job_id`、`prerequisite_job_id` | prerequisite_job_id → workflow_jobs.job_id (RESTRICT)；job_id → workflow_jobs.job_id (CASCADE) |
| [workflow_jobs](../src/bili_asr/storage/schema-workflow.sql#L30) | `job_id`、`kind`、`video_part_id`、`profile_id`、`policy_key`、`dedupe_key`、`payload_json`、`status`、`priority`、`available_at`、`lease_owner`、`lease_expires_at`、`attempt_count`、`last_error_code`、`created_at`、`updated_at` | profile_id → workflow_asr_profiles.profile_id (RESTRICT)；video_part_id → video_parts.video_part_id (RESTRICT) |
| [workflow_publications](../src/bili_asr/storage/schema-workflow.sql#L98) | `publication_id`、`video_part_id`、`transcript_id`、`published_at`、`artifact_json` | transcript_id → transcripts.transcript_id (RESTRICT)；video_part_id → video_parts.video_part_id (RESTRICT) |
| [workflow_quality_assessments](../src/bili_asr/storage/schema-workflow.sql#L84) | `assessment_id`、`video_part_id`、`source_kind`、`score`、`assessor`、`details_json`、`assessed_at` | video_part_id → video_parts.video_part_id (RESTRICT) |

## SQLite 全部派生视图

| 视图与定义 | 输出字段 | FROM/JOIN 引用（含局部 CTE） |
| --- | --- | --- |
| [v_ingestion_run_stats](../src/bili_asr/storage/schema.sql#L186) | `run_id`、`mid`、`started_at`、`finished_at`、`outcome`、`page_count`、`video_count` | ingestion_discoveries、ingestion_pages、ingestion_runs |
| [v_missing_audio](../src/bili_asr/storage/schema-transcripts.sql#L262) | `video_part_id`、`work_id`、`bvid`、`page_index`、`cid`、`part_title`、`duration_ms`、`video_title`、`pubdate`、`newest_outcome`、`newest_error_code` | acquisition_attempts、acquisition_runs、eligible_parts、empty_inventory_confirmations、part_audio_objects、subtitle_attempts、transcripts、video_parts、videos |
| [v_missing_subtitle](../src/bili_asr/storage/schema-transcripts.sql#L210) | `video_part_id`、`work_id`、`bvid`、`page_index`、`cid`、`part_title`、`duration_ms`、`video_title`、`pubdate` | transcripts、video_parts、videos |
| [v_missing_transcript](../src/bili_asr/storage/schema-transcripts.sql#L332) | `video_part_id`、`work_id`、`bvid`、`page_index`、`cid`、`part_title`、`duration_ms`、`video_title`、`pubdate` | part_audio_objects、transcripts、video_parts、videos |
| [v_part_pipeline](../src/bili_asr/storage/schema-transcripts.sql#L362) | `video_part_id`、`work_id`、`bvid`、`page_index`、`processing_status`、`pipeline_state` | acquisition_attempts、acquisition_runs、empty_inventory_confirmations、part_audio_objects、subtitle_attempts、transcripts、video_parts |
| [v_pending_metadata](../src/bili_asr/storage/schema.sql#L200) | `video_part_id`、`work_id`、`bvid`、`page_index`、`processing_status` | video_parts |
| [v_pending_subtitles](../src/bili_asr/storage/schema-transcripts.sql#L149) | `video_part_id`、`work_id`、`bvid`、`page_index`、`cid`、`part_title`、`duration_ms`、`attempted`、`last_attempt_at`、`last_attempt_outcome`、`last_attempt_error_code`、`last_attempt_credential_present` | acquisition_attempts、acquisition_runs、eligible、eligible_parts、fixes、subtitle_attempts、transcripts、video_parts |
| [v_video_parts](../src/bili_asr/storage/schema.sql#L169) | `video_part_id`、`work_id`、`user_name`、`video_title`、`page_index`、`cid`、`part_title`、`duration_ms`、`processing_status`、`created_at`、`updated_at` | bilibili_users、video_parts、videos |

## 索引与身份约束

四份 schema 中的 38 张持久表与 8 个视图不包括按需创建的 FTS 对象。当前 search-index 在同一 archive.db 中另外创建两个逻辑对象：

| 对象与代码定义 | 全部字段 | 创建、更新与读取 |
| --- | --- | --- |
| [transcript_fts](../src/bili_asr/search_index/common.py#L88)（FTS5 虚拟表） | `block_key`、`bvid`、`page_index`、`start_ms`、`end_ms`、`pubdate`、`text`、`bigram`、`source` | build 显式创建；仅 text/bigram 索引，其他列 UNINDEXED；query 只读 |
| [transcript_fts_index_meta](../src/bili_asr/search_index/store.py#L122) | `key`（主键）、`value` | 保存 completed_transcript_id/cursor_transcript_id/cursor_ordinal 水位、indexed_count 和 built_at 等派生构建信息；水位与批次共同提交 |

tokenizer 探测顺序为 trigram/simple/unicode61；已有 FTS 的 tokenizer 声明保持权威，不自动重建。SQLite 自动管理 FTS5 的 shadow tables，它们不作为业务实体/独立状态所有者；探测用 `_test_fts5` / `_fts_tok_probe` 是临时创建后删除的对象。constants 中保留的 `transcripts_fts` / `_index_meta` 不代表当前 store build 会创建另一个检索数据库。

视图清单的 FROM/JOIN 引用包括 eligible、fixes、subtitle_attempts 等局部 CTE 名字，CTE 不是额外持久表。完整 SQL 同时描述间接依赖与筛选条件。

- 转录版本：part/source/language/version 唯一；内容 digest 去重不删除本次 acquisition/evidence。
- Job：dedupe_key 唯一；依赖关系单独保存；owner + attempt_count + expires 隔离旧 worker。
- AI：input/revision 内容寻址；chunk 对 input/chunk 唯一；artifact 对 revision/template/role/path/hash 验证。
- 出版：edition 全内容 SHA；当前 review 状态与完整追加 events；release 精确 edition/review/template 身份；双 head 独立。
- 派生 FTS：transcript_fts 与 search_index/store.py 配套 metadata 表、tokenizer 和进度。query 不创建索引；DDL 和表名以 constants/common 为准。
- 全部 PK/UNIQUE/CHECK、ON DELETE 策略和普通索引以四份 SQL 源文件为精确契约，不由文档简写替代。

## 工程脚本与支持目录

| 文件 | 用途 |
| --- | --- |
| [benchmark_public_asr.py](../scripts/benchmark_public_asr.py) | 公开 ASR 样本基准，CPU/GPU 实验入口 |
| [check_asr_env.py](../scripts/check_asr_env.py) | 环境诊断脚本入口 |
| [check_test_coverage.py](../scripts/check_test_coverage.py) | 产品行/分支覆盖率门禁 |
| [fetch_meta.py](../scripts/fetch_meta.py) | 采集调用/验证脚本；公共 CLI 以 registry 为准 |
| [forensic_log.py](../scripts/forensic_log.py) | 验证与运行取证日志 |
| [measure_hotwords.py](../scripts/measure_hotwords.py) | 热词证据测量 |
| [prepare_offline_baseline_fixture.py](../scripts/prepare_offline_baseline_fixture.py) | 离线基线 fixture 准备 |
| [probe_target_host_load.py](../scripts/probe_target_host_load.py) | 目标机器负载探测 |
| [production.py](../scripts/production.py) | 受限 env-file，启动已安装 CLI |
| [project_staging.py](../scripts/project_staging.py) | 项目安装/验证 staging |
| [pytest_shard.py](../scripts/pytest_shard.py) | 测试分片 |
| [verify_baseline.py](../scripts/verify_baseline.py) | 安装基线验证 |
| [verify_gpu.py](../scripts/verify_gpu.py) | GPU 可用性与真实样本验证 |

- [.github/workflows/ci.yml](../.github/workflows/ci.yml)：安装、lint、离线测试、覆盖门禁与审计配置。
- [pyproject.toml](../pyproject.toml) 与 [uv.lock](../uv.lock)：依赖、安装入口、ASR extra 和 externally provisioned torch 约束。
- [tests](../tests)：行为、竞争/取消、路径、schema、模板、标签、公开/预览导出和恢复测试；live/scale 需显式选择。
- [references](../references/README.md)：历史决策/工程证据，阅读时保留原时间上下文。
- [docs/contracts](contracts/README.md)：稿件公开/预览/私有 JSON schema 与例子。

## 完整性核对规则

新增命令、job kind、模块、SQL 表/视图、持久 artifact 或副作用必须更新本清单与对应时序。库能力新增时先确认正常路径是否调用，未调用的能力仍标为显式库工具。源码身份、引用范围和图中关系不得用未来计划补齐。
