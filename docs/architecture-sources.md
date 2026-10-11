# 当前源码、命令与契约覆盖

固定源码 `4f073318c944add37417416155845e55247f9bc1`；2026-10-11（Asia/Hong_Kong）。本清单重新从实际 parser/registry、提交文件树和契约资源核对；[机器清单](architecture-coverage.json)。当前有 20 个顶层命令、86 条实际叶命令、203 个 Python 模块、11 份 SQL 资源、47 项稳定契约和 23 份 JSON Schema。

## 全部实际命令路径

| 命令 | 登记入口 |
| --- | --- |
| `workflow plan` | _cmd_workflow；registry 的默认数据库模式为 write，子命令/flag 可覆盖 |
| `workflow proofread` | _cmd_workflow；registry 的默认数据库模式为 write，子命令/flag 可覆盖 |
| `workflow repair-proofread` | _cmd_workflow；registry 的默认数据库模式为 write，子命令/flag 可覆盖 |
| `workflow render` | _cmd_workflow；registry 的默认数据库模式为 write，子命令/flag 可覆盖 |
| `workflow run` | _cmd_workflow；registry 的默认数据库模式为 write，子命令/flag 可覆盖 |
| `workflow supervise` | _cmd_workflow；registry 的默认数据库模式为 write，子命令/flag 可覆盖 |
| `workflow status` | _cmd_workflow；registry 的默认数据库模式为 write，子命令/flag 可覆盖 |
| `workflow cancel` | _cmd_workflow；registry 的默认数据库模式为 write，子命令/flag 可覆盖 |
| `workflow publish` | _cmd_workflow；registry 的默认数据库模式为 write，子命令/flag 可覆盖 |
| `workflow explain` | _cmd_workflow；registry 的默认数据库模式为 write，子命令/flag 可覆盖 |
| `workflow asr-evidence` | _cmd_workflow；registry 的默认数据库模式为 write，子命令/flag 可覆盖 |
| `workflow asr-performance` | _cmd_workflow；registry 的默认数据库模式为 write，子命令/flag 可覆盖 |
| `workflow retry` | _cmd_workflow；registry 的默认数据库模式为 write，子命令/flag 可覆盖 |
| `workflow repair-dependencies` | _cmd_workflow；registry 的默认数据库模式为 write，子命令/flag 可覆盖 |
| `publication create` | _cmd_publication；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `publication edit` | _cmd_publication；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `publication sync-source-tags` | _cmd_publication；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `publication review` | _cmd_publication；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `publication publish` | _cmd_publication；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `publication withdraw` | _cmd_publication；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `publication show` | _cmd_publication；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `publication export` | _cmd_publication；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `publication export-drafts` | _cmd_publication；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `publication import-preserved install` | _cmd_publication；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `publication import-preserved plan` | _cmd_publication；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `publication import-preserved apply` | _cmd_publication；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `publication import-preserved check` | _cmd_publication；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `publication supplement-source install` | _cmd_publication；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `publication supplement-source plan` | _cmd_publication；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `publication supplement-source apply` | _cmd_publication；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `publication supplement-source check` | _cmd_publication；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `publication series validate` | _cmd_publication；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `publication series show` | _cmd_publication；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `publication series edit` | _cmd_publication；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `editorial export` | _cmd_editorial；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `snapshot save` | _cmd_snapshot；registry 的默认数据库模式为 maintenance，子命令/flag 可覆盖 |
| `snapshot check` | _cmd_snapshot；registry 的默认数据库模式为 maintenance，子命令/flag 可覆盖 |
| `snapshot inspect` | _cmd_snapshot；registry 的默认数据库模式为 maintenance，子命令/flag 可覆盖 |
| `snapshot plan` | _cmd_snapshot；registry 的默认数据库模式为 maintenance，子命令/flag 可覆盖 |
| `snapshot doctor` | _cmd_snapshot；registry 的默认数据库模式为 maintenance，子命令/flag 可覆盖 |
| `snapshot restore` | _cmd_snapshot；registry 的默认数据库模式为 maintenance，子命令/flag 可覆盖 |
| `archive migration-preflight` | _cmd_archive；registry 的默认数据库模式为 maintenance，子命令/flag 可覆盖 |
| `archive init` | _cmd_archive；registry 的默认数据库模式为 maintenance，子命令/flag 可覆盖 |
| `archive migrate` | _cmd_archive；registry 的默认数据库模式为 maintenance，子命令/flag 可覆盖 |
| `archive migration-check` | _cmd_archive；registry 的默认数据库模式为 maintenance，子命令/flag 可覆盖 |
| `archive upgrade-paths` | _cmd_archive；registry 的默认数据库模式为 maintenance，子命令/flag 可覆盖 |
| `archive derive-vtt` | _cmd_archive；registry 的默认数据库模式为 maintenance，子命令/flag 可覆盖 |
| `archive upgrade-plan` | _cmd_archive；registry 的默认数据库模式为 maintenance，子命令/flag 可覆盖 |
| `archive upgrade-apply` | _cmd_archive；registry 的默认数据库模式为 maintenance，子命令/flag 可覆盖 |
| `archive upgrade-check` | _cmd_archive；registry 的默认数据库模式为 maintenance，子命令/flag 可覆盖 |
| `artifacts inventory` | _cmd_artifacts；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `artifacts plan` | _cmd_artifacts；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `artifacts upgrade` | _cmd_artifacts；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `artifacts capture-groups` | _cmd_artifacts；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `artifacts restore-group` | _cmd_artifacts；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `artifacts status` | _cmd_artifacts；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `artifacts policy-show` | _cmd_artifacts；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `artifacts policy-set` | _cmd_artifacts；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `artifacts policy-run` | _cmd_artifacts；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `artifacts bind-target` | _cmd_artifacts；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `artifacts transfer` | _cmd_artifacts；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `artifacts restore` | _cmd_artifacts；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `artifacts reconcile` | _cmd_artifacts；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `artifacts check` | _cmd_artifacts；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `remote prepare` | _cmd_remote；registry 的默认数据库模式为 无，子命令/flag 可覆盖 |
| `remote probe` | _cmd_remote；registry 的默认数据库模式为 无，子命令/flag 可覆盖 |
| `remote push` | _cmd_remote；registry 的默认数据库模式为 无，子命令/flag 可覆盖 |
| `remote restore` | _cmd_remote；registry 的默认数据库模式为 无，子命令/flag 可覆盖 |
| `reference save` | _cmd_reference；registry 的默认数据库模式为 无，子命令/flag 可覆盖 |
| `reference inspect` | _cmd_reference；registry 的默认数据库模式为 无，子命令/flag 可覆盖 |
| `reference check` | _cmd_reference；registry 的默认数据库模式为 无，子命令/flag 可覆盖 |
| `reference plan` | _cmd_reference；registry 的默认数据库模式为 无，子命令/flag 可覆盖 |
| `reference restore` | _cmd_reference；registry 的默认数据库模式为 无，子命令/flag 可覆盖 |
| `source doctor` | _cmd_source；registry 的默认数据库模式为 write，子命令/flag 可覆盖 |
| `source import` | _cmd_source；registry 的默认数据库模式为 write，子命令/flag 可覆盖 |
| `dedup report` | _cmd_dedup；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `fetch-meta` | _cmd_fetch_meta；registry 的默认数据库模式为 bootstrap，子命令/flag 可覆盖 |
| `fetch-tags` | _cmd_fetch_tags；registry 的默认数据库模式为 bootstrap，子命令/flag 可覆盖 |
| `status` | _cmd_status；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `runs` | _cmd_runs；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `search` | _cmd_search；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `search-index` | _cmd_search_index；registry 的默认数据库模式为 write，子命令/flag 可覆盖 |
| `coverage` | _cmd_coverage；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `verify` | _cmd_verify；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `export` | _cmd_export；registry 的默认数据库模式为 read，子命令/flag 可覆盖 |
| `check-asr-env` | _cmd_check_asr_env；registry 的默认数据库模式为 无，子命令/flag 可覆盖 |

## 完整 Python 模块

| 模块 | 所属目录 |
| --- | --- |
| [src/bili_asr/__init__.py](../src/bili_asr/__init__.py) | src/bili_asr |
| [src/bili_asr/__main__.py](../src/bili_asr/__main__.py) | src/bili_asr |
| [src/bili_asr/archive.py](../src/bili_asr/archive.py) | src/bili_asr |
| [src/bili_asr/archive_maintenance.py](../src/bili_asr/archive_maintenance.py) | src/bili_asr |
| [src/bili_asr/archive_session.py](../src/bili_asr/archive_session.py) | src/bili_asr |
| [src/bili_asr/artifact_inventory.py](../src/bili_asr/artifact_inventory.py) | src/bili_asr |
| [src/bili_asr/artifact_packages.py](../src/bili_asr/artifact_packages.py) | src/bili_asr |
| [src/bili_asr/artifact_root.py](../src/bili_asr/artifact_root.py) | src/bili_asr |
| [src/bili_asr/artifacts.py](../src/bili_asr/artifacts.py) | src/bili_asr |
| [src/bili_asr/asr/__init__.py](../src/bili_asr/asr/__init__.py) | src/bili_asr/asr |
| [src/bili_asr/asr/alignment.py](../src/bili_asr/asr/alignment.py) | src/bili_asr/asr |
| [src/bili_asr/asr/audio.py](../src/bili_asr/asr/audio.py) | src/bili_asr/asr |
| [src/bili_asr/asr/backend.py](../src/bili_asr/asr/backend.py) | src/bili_asr/asr |
| [src/bili_asr/asr/batching.py](../src/bili_asr/asr/batching.py) | src/bili_asr/asr |
| [src/bili_asr/asr/config.py](../src/bili_asr/asr/config.py) | src/bili_asr/asr |
| [src/bili_asr/asr/constants.py](../src/bili_asr/asr/constants.py) | src/bili_asr/asr |
| [src/bili_asr/asr/coverage.py](../src/bili_asr/asr/coverage.py) | src/bili_asr/asr |
| [src/bili_asr/asr/deployment.py](../src/bili_asr/asr/deployment.py) | src/bili_asr/asr |
| [src/bili_asr/asr/device_probe.py](../src/bili_asr/asr/device_probe.py) | src/bili_asr/asr |
| [src/bili_asr/asr/diagnostics.py](../src/bili_asr/asr/diagnostics.py) | src/bili_asr/asr |
| [src/bili_asr/asr/errors.py](../src/bili_asr/asr/errors.py) | src/bili_asr/asr |
| [src/bili_asr/asr/execution.py](../src/bili_asr/asr/execution.py) | src/bili_asr/asr |
| [src/bili_asr/asr/hotwords.py](../src/bili_asr/asr/hotwords.py) | src/bili_asr/asr |
| [src/bili_asr/asr/preparation.py](../src/bili_asr/asr/preparation.py) | src/bili_asr/asr |
| [src/bili_asr/asr/provenance.py](../src/bili_asr/asr/provenance.py) | src/bili_asr/asr |
| [src/bili_asr/asr/runner.py](../src/bili_asr/asr/runner.py) | src/bili_asr/asr |
| [src/bili_asr/asr/runtime_cache.py](../src/bili_asr/asr/runtime_cache.py) | src/bili_asr/asr |
| [src/bili_asr/asr/session.py](../src/bili_asr/asr/session.py) | src/bili_asr/asr |
| [src/bili_asr/asr/strategies.py](../src/bili_asr/asr/strategies.py) | src/bili_asr/asr |
| [src/bili_asr/audio.py](../src/bili_asr/audio.py) | src/bili_asr |
| [src/bili_asr/audio_budget.py](../src/bili_asr/audio_budget.py) | src/bili_asr |
| [src/bili_asr/audio_reclaim.py](../src/bili_asr/audio_reclaim.py) | src/bili_asr |
| [src/bili_asr/bili_client.py](../src/bili_asr/bili_client.py) | src/bili_asr |
| [src/bili_asr/bilibili_identity.py](../src/bili_asr/bilibili_identity.py) | src/bili_asr |
| [src/bili_asr/canonical_json.py](../src/bili_asr/canonical_json.py) | src/bili_asr |
| [src/bili_asr/check_asr_env.py](../src/bili_asr/check_asr_env.py) | src/bili_asr |
| [src/bili_asr/cli/__init__.py](../src/bili_asr/cli/__init__.py) | src/bili_asr/cli |
| [src/bili_asr/cli/_shared.py](../src/bili_asr/cli/_shared.py) | src/bili_asr/cli |
| [src/bili_asr/cli/archive.py](../src/bili_asr/cli/archive.py) | src/bili_asr/cli |
| [src/bili_asr/cli/artifacts.py](../src/bili_asr/cli/artifacts.py) | src/bili_asr/cli |
| [src/bili_asr/cli/dedup.py](../src/bili_asr/cli/dedup.py) | src/bili_asr/cli |
| [src/bili_asr/cli/editorial.py](../src/bili_asr/cli/editorial.py) | src/bili_asr/cli |
| [src/bili_asr/cli/main.py](../src/bili_asr/cli/main.py) | src/bili_asr/cli |
| [src/bili_asr/cli/meta.py](../src/bili_asr/cli/meta.py) | src/bili_asr/cli |
| [src/bili_asr/cli/ops.py](../src/bili_asr/cli/ops.py) | src/bili_asr/cli |
| [src/bili_asr/cli/parser.py](../src/bili_asr/cli/parser.py) | src/bili_asr/cli |
| [src/bili_asr/cli/publication.py](../src/bili_asr/cli/publication.py) | src/bili_asr/cli |
| [src/bili_asr/cli/registry.py](../src/bili_asr/cli/registry.py) | src/bili_asr/cli |
| [src/bili_asr/cli/remote_storage.py](../src/bili_asr/cli/remote_storage.py) | src/bili_asr/cli |
| [src/bili_asr/cli/search.py](../src/bili_asr/cli/search.py) | src/bili_asr/cli |
| [src/bili_asr/cli/snapshot.py](../src/bili_asr/cli/snapshot.py) | src/bili_asr/cli |
| [src/bili_asr/cli/source.py](../src/bili_asr/cli/source.py) | src/bili_asr/cli |
| [src/bili_asr/cli/status_cmd.py](../src/bili_asr/cli/status_cmd.py) | src/bili_asr/cli |
| [src/bili_asr/cli/workflow.py](../src/bili_asr/cli/workflow.py) | src/bili_asr/cli |
| [src/bili_asr/concurrency_gate.py](../src/bili_asr/concurrency_gate.py) | src/bili_asr |
| [src/bili_asr/config.py](../src/bili_asr/config.py) | src/bili_asr |
| [src/bili_asr/contracts/__init__.py](../src/bili_asr/contracts/__init__.py) | src/bili_asr/contracts |
| [src/bili_asr/contracts/__main__.py](../src/bili_asr/contracts/__main__.py) | src/bili_asr/contracts |
| [src/bili_asr/contracts/content_policies.py](../src/bili_asr/contracts/content_policies.py) | src/bili_asr/contracts |
| [src/bili_asr/contracts/fingerprints.py](../src/bili_asr/contracts/fingerprints.py) | src/bili_asr/contracts |
| [src/bili_asr/contracts/json_schema.py](../src/bili_asr/contracts/json_schema.py) | src/bili_asr/contracts |
| [src/bili_asr/contracts/registry.py](../src/bili_asr/contracts/registry.py) | src/bili_asr/contracts |
| [src/bili_asr/contracts/release_gate.py](../src/bili_asr/contracts/release_gate.py) | src/bili_asr/contracts |
| [src/bili_asr/contracts/values.py](../src/bili_asr/contracts/values.py) | src/bili_asr/contracts |
| [src/bili_asr/coverage_report.py](../src/bili_asr/coverage_report.py) | src/bili_asr |
| [src/bili_asr/cue_models.py](../src/bili_asr/cue_models.py) | src/bili_asr |
| [src/bili_asr/cues.py](../src/bili_asr/cues.py) | src/bili_asr |
| [src/bili_asr/dedup.py](../src/bili_asr/dedup.py) | src/bili_asr |
| [src/bili_asr/deepseek.py](../src/bili_asr/deepseek.py) | src/bili_asr |
| [src/bili_asr/diagnostics.py](../src/bili_asr/diagnostics.py) | src/bili_asr |
| [src/bili_asr/editorial.py](../src/bili_asr/editorial.py) | src/bili_asr |
| [src/bili_asr/editorial_quality.py](../src/bili_asr/editorial_quality.py) | src/bili_asr |
| [src/bili_asr/editorial_runtime.py](../src/bili_asr/editorial_runtime.py) | src/bili_asr |
| [src/bili_asr/error_codes.py](../src/bili_asr/error_codes.py) | src/bili_asr |
| [src/bili_asr/export.py](../src/bili_asr/export.py) | src/bili_asr |
| [src/bili_asr/export_snapshot.py](../src/bili_asr/export_snapshot.py) | src/bili_asr |
| [src/bili_asr/formatting.py](../src/bili_asr/formatting.py) | src/bili_asr |
| [src/bili_asr/integrity.py](../src/bili_asr/integrity.py) | src/bili_asr |
| [src/bili_asr/long_live.py](../src/bili_asr/long_live.py) | src/bili_asr |
| [src/bili_asr/manuscript_artifacts.py](../src/bili_asr/manuscript_artifacts.py) | src/bili_asr |
| [src/bili_asr/manuscript_files.py](../src/bili_asr/manuscript_files.py) | src/bili_asr |
| [src/bili_asr/manuscript_templates.py](../src/bili_asr/manuscript_templates.py) | src/bili_asr |
| [src/bili_asr/meta_cursor.py](../src/bili_asr/meta_cursor.py) | src/bili_asr |
| [src/bili_asr/metadata_policy.py](../src/bili_asr/metadata_policy.py) | src/bili_asr |
| [src/bili_asr/page_identity.py](../src/bili_asr/page_identity.py) | src/bili_asr |
| [src/bili_asr/path_policy.py](../src/bili_asr/path_policy.py) | src/bili_asr |
| [src/bili_asr/persistence.py](../src/bili_asr/persistence.py) | src/bili_asr |
| [src/bili_asr/platform_identity.py](../src/bili_asr/platform_identity.py) | src/bili_asr |
| [src/bili_asr/process_environment.py](../src/bili_asr/process_environment.py) | src/bili_asr |
| [src/bili_asr/proofread.py](../src/bili_asr/proofread.py) | src/bili_asr |
| [src/bili_asr/publication.py](../src/bili_asr/publication.py) | src/bili_asr |
| [src/bili_asr/publication_content.py](../src/bili_asr/publication_content.py) | src/bili_asr |
| [src/bili_asr/publication_content_v2.py](../src/bili_asr/publication_content_v2.py) | src/bili_asr |
| [src/bili_asr/publication_export.py](../src/bili_asr/publication_export.py) | src/bili_asr |
| [src/bili_asr/publication_identity.py](../src/bili_asr/publication_identity.py) | src/bili_asr |
| [src/bili_asr/publication_origins.py](../src/bili_asr/publication_origins.py) | src/bili_asr |
| [src/bili_asr/publication_series.py](../src/bili_asr/publication_series.py) | src/bili_asr |
| [src/bili_asr/publication_tags.py](../src/bili_asr/publication_tags.py) | src/bili_asr |
| [src/bili_asr/publication_worker.py](../src/bili_asr/publication_worker.py) | src/bili_asr |
| [src/bili_asr/quality.py](../src/bili_asr/quality.py) | src/bili_asr |
| [src/bili_asr/remote_storage.py](../src/bili_asr/remote_storage.py) | src/bili_asr |
| [src/bili_asr/request_budget.py](../src/bili_asr/request_budget.py) | src/bili_asr |
| [src/bili_asr/runtime_bindings.py](../src/bili_asr/runtime_bindings.py) | src/bili_asr |
| [src/bili_asr/search_index/__init__.py](../src/bili_asr/search_index/__init__.py) | src/bili_asr/search_index |
| [src/bili_asr/search_index/common.py](../src/bili_asr/search_index/common.py) | src/bili_asr/search_index |
| [src/bili_asr/search_index/constants.py](../src/bili_asr/search_index/constants.py) | src/bili_asr/search_index |
| [src/bili_asr/search_index/errors.py](../src/bili_asr/search_index/errors.py) | src/bili_asr/search_index |
| [src/bili_asr/search_index/metadata.py](../src/bili_asr/search_index/metadata.py) | src/bili_asr/search_index |
| [src/bili_asr/search_index/models.py](../src/bili_asr/search_index/models.py) | src/bili_asr/search_index |
| [src/bili_asr/search_index/query.py](../src/bili_asr/search_index/query.py) | src/bili_asr/search_index |
| [src/bili_asr/search_index/readers.py](../src/bili_asr/search_index/readers.py) | src/bili_asr/search_index |
| [src/bili_asr/search_index/source_store.py](../src/bili_asr/search_index/source_store.py) | src/bili_asr/search_index |
| [src/bili_asr/search_index/store.py](../src/bili_asr/search_index/store.py) | src/bili_asr/search_index |
| [src/bili_asr/services/__init__.py](../src/bili_asr/services/__init__.py) | src/bili_asr/services |
| [src/bili_asr/services/_common.py](../src/bili_asr/services/_common.py) | src/bili_asr/services |
| [src/bili_asr/services/archive_migration.py](../src/bili_asr/services/archive_migration.py) | src/bili_asr/services |
| [src/bili_asr/services/archive_recovery.py](../src/bili_asr/services/archive_recovery.py) | src/bili_asr/services |
| [src/bili_asr/services/archive_snapshot.py](../src/bili_asr/services/archive_snapshot.py) | src/bili_asr/services |
| [src/bili_asr/services/archive_upgrade.py](../src/bili_asr/services/archive_upgrade.py) | src/bili_asr/services |
| [src/bili_asr/services/artifact_access.py](../src/bili_asr/services/artifact_access.py) | src/bili_asr/services |
| [src/bili_asr/services/artifact_catalog_upgrade.py](../src/bili_asr/services/artifact_catalog_upgrade.py) | src/bili_asr/services |
| [src/bili_asr/services/artifact_child.py](../src/bili_asr/services/artifact_child.py) | src/bili_asr/services |
| [src/bili_asr/services/artifact_consumer.py](../src/bili_asr/services/artifact_consumer.py) | src/bili_asr/services |
| [src/bili_asr/services/artifact_coordination.py](../src/bili_asr/services/artifact_coordination.py) | src/bili_asr/services |
| [src/bili_asr/services/artifact_groups.py](../src/bili_asr/services/artifact_groups.py) | src/bili_asr/services |
| [src/bili_asr/services/artifact_inventory_service.py](../src/bili_asr/services/artifact_inventory_service.py) | src/bili_asr/services |
| [src/bili_asr/services/artifact_io.py](../src/bili_asr/services/artifact_io.py) | src/bili_asr/services |
| [src/bili_asr/services/artifact_policy.py](../src/bili_asr/services/artifact_policy.py) | src/bili_asr/services |
| [src/bili_asr/services/artifact_readers.py](../src/bili_asr/services/artifact_readers.py) | src/bili_asr/services |
| [src/bili_asr/services/artifact_release.py](../src/bili_asr/services/artifact_release.py) | src/bili_asr/services |
| [src/bili_asr/services/artifact_restore.py](../src/bili_asr/services/artifact_restore.py) | src/bili_asr/services |
| [src/bili_asr/services/artifact_state.py](../src/bili_asr/services/artifact_state.py) | src/bili_asr/services |
| [src/bili_asr/services/artifact_transfer.py](../src/bili_asr/services/artifact_transfer.py) | src/bili_asr/services |
| [src/bili_asr/services/asr_performance.py](../src/bili_asr/services/asr_performance.py) | src/bili_asr/services |
| [src/bili_asr/services/audio_inventory.py](../src/bili_asr/services/audio_inventory.py) | src/bili_asr/services |
| [src/bili_asr/services/bundle_verification.py](../src/bili_asr/services/bundle_verification.py) | src/bili_asr/services |
| [src/bili_asr/services/editorial_repair.py](../src/bili_asr/services/editorial_repair.py) | src/bili_asr/services |
| [src/bili_asr/services/import_staging.py](../src/bili_asr/services/import_staging.py) | src/bili_asr/services |
| [src/bili_asr/services/metadata_ingest.py](../src/bili_asr/services/metadata_ingest.py) | src/bili_asr/services |
| [src/bili_asr/services/metadata_refresh.py](../src/bili_asr/services/metadata_refresh.py) | src/bili_asr/services |
| [src/bili_asr/services/migration_preflight.py](../src/bili_asr/services/migration_preflight.py) | src/bili_asr/services |
| [src/bili_asr/services/preserved_body_import.py](../src/bili_asr/services/preserved_body_import.py) | src/bili_asr/services |
| [src/bili_asr/services/publication_supervisor.py](../src/bili_asr/services/publication_supervisor.py) | src/bili_asr/services |
| [src/bili_asr/services/reference_backup.py](../src/bili_asr/services/reference_backup.py) | src/bili_asr/services |
| [src/bili_asr/services/remote_artifacts.py](../src/bili_asr/services/remote_artifacts.py) | src/bili_asr/services |
| [src/bili_asr/services/source_supplement.py](../src/bili_asr/services/source_supplement.py) | src/bili_asr/services |
| [src/bili_asr/services/source_workflow.py](../src/bili_asr/services/source_workflow.py) | src/bili_asr/services |
| [src/bili_asr/services/subtitle_ingest.py](../src/bili_asr/services/subtitle_ingest.py) | src/bili_asr/services |
| [src/bili_asr/services/transcript_adoption.py](../src/bili_asr/services/transcript_adoption.py) | src/bili_asr/services |
| [src/bili_asr/services/transcript_derivatives.py](../src/bili_asr/services/transcript_derivatives.py) | src/bili_asr/services |
| [src/bili_asr/services/transcript_projection.py](../src/bili_asr/services/transcript_projection.py) | src/bili_asr/services |
| [src/bili_asr/services/video_tags.py](../src/bili_asr/services/video_tags.py) | src/bili_asr/services |
| [src/bili_asr/services/workflow_application.py](../src/bili_asr/services/workflow_application.py) | src/bili_asr/services |
| [src/bili_asr/services/workflow_audio_access.py](../src/bili_asr/services/workflow_audio_access.py) | src/bili_asr/services |
| [src/bili_asr/services/workflow_projection.py](../src/bili_asr/services/workflow_projection.py) | src/bili_asr/services |
| [src/bili_asr/source_identity.py](../src/bili_asr/source_identity.py) | src/bili_asr |
| [src/bili_asr/source_metadata.py](../src/bili_asr/source_metadata.py) | src/bili_asr |
| [src/bili_asr/source_supplements.py](../src/bili_asr/source_supplements.py) | src/bili_asr |
| [src/bili_asr/source_video.py](../src/bili_asr/source_video.py) | src/bili_asr |
| [src/bili_asr/sources/__init__.py](../src/bili_asr/sources/__init__.py) | src/bili_asr/sources |
| [src/bili_asr/sources/bilibili_api_gateway.py](../src/bili_asr/sources/bilibili_api_gateway.py) | src/bili_asr/sources |
| [src/bili_asr/sources/bilibili_identity.py](../src/bili_asr/sources/bilibili_identity.py) | src/bili_asr/sources |
| [src/bili_asr/sources/bilibili_source.py](../src/bili_asr/sources/bilibili_source.py) | src/bili_asr/sources |
| [src/bili_asr/sources/models.py](../src/bili_asr/sources/models.py) | src/bili_asr/sources |
| [src/bili_asr/sources/protocols.py](../src/bili_asr/sources/protocols.py) | src/bili_asr/sources |
| [src/bili_asr/sources/registry.py](../src/bili_asr/sources/registry.py) | src/bili_asr/sources |
| [src/bili_asr/sources/request_scope.py](../src/bili_asr/sources/request_scope.py) | src/bili_asr/sources |
| [src/bili_asr/sources/youtube_source.py](../src/bili_asr/sources/youtube_source.py) | src/bili_asr/sources |
| [src/bili_asr/ssh_storage_agent.py](../src/bili_asr/ssh_storage_agent.py) | src/bili_asr |
| [src/bili_asr/storage/__init__.py](../src/bili_asr/storage/__init__.py) | src/bili_asr/storage |
| [src/bili_asr/storage/archive_contracts.py](../src/bili_asr/storage/archive_contracts.py) | src/bili_asr/storage |
| [src/bili_asr/storage/artifact_catalog.py](../src/bili_asr/storage/artifact_catalog.py) | src/bili_asr/storage |
| [src/bili_asr/storage/artifact_online.py](../src/bili_asr/storage/artifact_online.py) | src/bili_asr/storage |
| [src/bili_asr/storage/asr_performance.py](../src/bili_asr/storage/asr_performance.py) | src/bili_asr/storage |
| [src/bili_asr/storage/database.py](../src/bili_asr/storage/database.py) | src/bili_asr/storage |
| [src/bili_asr/storage/editorial.py](../src/bili_asr/storage/editorial.py) | src/bili_asr/storage |
| [src/bili_asr/storage/import_origins.py](../src/bili_asr/storage/import_origins.py) | src/bili_asr/storage |
| [src/bili_asr/storage/job_commit.py](../src/bili_asr/storage/job_commit.py) | src/bili_asr/storage |
| [src/bili_asr/storage/metadata.py](../src/bili_asr/storage/metadata.py) | src/bili_asr/storage |
| [src/bili_asr/storage/migration_artifacts.py](../src/bili_asr/storage/migration_artifacts.py) | src/bili_asr/storage |
| [src/bili_asr/storage/migration_source.py](../src/bili_asr/storage/migration_source.py) | src/bili_asr/storage |
| [src/bili_asr/storage/models.py](../src/bili_asr/storage/models.py) | src/bili_asr/storage |
| [src/bili_asr/storage/publication.py](../src/bili_asr/storage/publication.py) | src/bili_asr/storage |
| [src/bili_asr/storage/snapshots.py](../src/bili_asr/storage/snapshots.py) | src/bili_asr/storage |
| [src/bili_asr/storage/source_supplements.py](../src/bili_asr/storage/source_supplements.py) | src/bili_asr/storage |
| [src/bili_asr/storage/sources.py](../src/bili_asr/storage/sources.py) | src/bili_asr/storage |
| [src/bili_asr/storage/transcripts.py](../src/bili_asr/storage/transcripts.py) | src/bili_asr/storage |
| [src/bili_asr/storage/upgrade_evidence.py](../src/bili_asr/storage/upgrade_evidence.py) | src/bili_asr/storage |
| [src/bili_asr/storage/workflow.py](../src/bili_asr/storage/workflow.py) | src/bili_asr/storage |
| [src/bili_asr/storage/workflow_dependency_repair.py](../src/bili_asr/storage/workflow_dependency_repair.py) | src/bili_asr/storage |
| [src/bili_asr/storage/workflow_selection.py](../src/bili_asr/storage/workflow_selection.py) | src/bili_asr/storage |
| [src/bili_asr/storage_targets.py](../src/bili_asr/storage_targets.py) | src/bili_asr |
| [src/bili_asr/subtitle_policy.py](../src/bili_asr/subtitle_policy.py) | src/bili_asr |
| [src/bili_asr/transcript_selection.py](../src/bili_asr/transcript_selection.py) | src/bili_asr |
| [src/bili_asr/workflow.py](../src/bili_asr/workflow.py) | src/bili_asr |
| [src/bili_asr/workflow_errors.py](../src/bili_asr/workflow_errors.py) | src/bili_asr |
| [src/bili_asr/workflow_models.py](../src/bili_asr/workflow_models.py) | src/bili_asr |
| [src/bili_asr/workflow_payloads.py](../src/bili_asr/workflow_payloads.py) | src/bili_asr |
| [src/bili_asr/workflow_planning.py](../src/bili_asr/workflow_planning.py) | src/bili_asr |
| [src/bili_asr/workflow_runtime.py](../src/bili_asr/workflow_runtime.py) | src/bili_asr |
| [src/bili_asr/workflow_runtime_ports.py](../src/bili_asr/workflow_runtime_ports.py) | src/bili_asr |
| [src/bili_asr/workflow_shutdown.py](../src/bili_asr/workflow_shutdown.py) | src/bili_asr |
| [src/bili_asr/workflow_supervisor.py](../src/bili_asr/workflow_supervisor.py) | src/bili_asr |

## 基础库与可选扩展

基础库 SQL 经 contract_scripts 实际组装后在内存 SQLite 提取表和视图；universal-v2 对旧兼容表作受版本约束的重建，不应仅按原 SQL 文本数表。下表不含可选扩展或按需 FTS/shadow objects。

### bilibili-v1：38 张表 / 8 个视图

| 对象 | 类型 | 全部字段 |
| --- | --- | --- |
| acquisition_attempts | table | run_id、video_part_id、outcome、error_code、transcript_id、started_at、finished_at、credential_verified、absence_verified |
| acquisition_runs | table | run_id、kind、selector_kind、selector_target、requested_limit、credential_present、started_at、finished_at、outcome |
| asr_models | table | model_id、model_name、revision、created_at |
| audio_objects | table | audio_id、sha256、byte_size、format、duration_ms、storage_key、created_at |
| bilibili_users | table | mid、display_name、created_at、updated_at |
| document_artifacts | table | revision_id、template_version、artifact_name、manuscript_role、relative_path、content_sha256 |
| editorial_chunk_results | table | input_id、chunk_id、call_id、blocks_json |
| editorial_inputs | table | input_id、video_part_id、base_transcript_id、reference_transcript_id、prepared_json、created_at |
| editorial_job_inputs | table | job_id、input_id |
| editorial_model_calls | table | call_id、attempt_id、input_id、chunk_id、request_json、response_json、error_code、started_at、finished_at |
| editorial_revisions | table | revision_id、input_id、job_id、blocks_json、quality_status、created_at |
| ingestion_cursors | table | mid、next_page、observed_total、state、last_error_code、updated_at |
| ingestion_discoveries | table | run_id、page_number、bvid、source_position、discovered_at |
| ingestion_pages | table | run_id、page_number、outcome、error_code、started_at、finished_at |
| ingestion_runs | table | run_id、mid、source_package、source_version、requested_start_page、requested_page_limit、started_at、finished_at、outcome |
| manuscript_contract | table | version |
| part_audio_objects | table | video_part_id、audio_id、acquired_at、acquisition_source |
| publication_edition_reviews | table | edition_id、review_id、content_sha256、status、actor、note、issue_url、updated_at |
| publication_editions | table | edition_id、video_part_id、revision_id、parent_edition_id、content_json、content_sha256、created_at、created_by、note |
| publication_events | table | event_id、video_part_id、edition_id、release_id、review_id、content_sha256、event_type、from_status、to_status、actor、issue_url、note、changed_at |
| publication_heads | table | video_part_id、current_edition_id、current_release_id |
| publication_releases | table | release_id、video_part_id、edition_id、review_id、content_sha256、template_version、relative_path、artifact_sha256、published_at、published_by、status |
| transcript_asr_evidence | table | run_id、video_part_id、transcript_id、schema_version、evidence_json |
| transcript_coverage_attestations | table | run_id、video_part_id、transcript_id、decoded_s、produced_s、coverage、coverage_min、coverage_short |
| transcript_segments | table | transcript_id、ordinal、start_ms、end_ms、text |
| transcripts | table | transcript_id、video_part_id、source_kind、language、model_id、version、content_sha256、created_at |
| video_details | table | bvid、pic、desc、tid、observed_at |
| video_parts | table | video_part_id、bvid、page_index、cid、title、duration_ms、processing_status、created_at、updated_at |
| video_tag_observations | table | bvid、state、observed_at、error_code、run_id |
| video_tags | table | bvid、tag_id、tag_name、tag_type |
| videos | table | bvid、aid、mid、title、pubdate、created_at、updated_at |
| workflow_asr_profile_configs | table | profile_id、schema_version、config_json |
| workflow_asr_profiles | table | profile_id、profile_key、model_name、model_revision、aligner_name、device、language、config_sha256、created_at |
| workflow_attempts | table | attempt_id、job_id、worker_id、started_at、finished_at、outcome、error_code、result_json |
| workflow_job_dependencies | table | job_id、prerequisite_job_id |
| workflow_jobs | table | job_id、kind、video_part_id、profile_id、policy_key、dedupe_key、payload_json、status、priority、available_at、lease_owner、lease_expires_at、attempt_count、last_error_code、created_at、updated_at |
| workflow_publications | table | publication_id、video_part_id、transcript_id、published_at、artifact_json |
| workflow_quality_assessments | table | assessment_id、video_part_id、source_kind、score、assessor、details_json、assessed_at |
| v_ingestion_run_stats | view | run_id、mid、started_at、finished_at、outcome、page_count、video_count |
| v_missing_audio | view | video_part_id、work_id、bvid、page_index、cid、part_title、duration_ms、video_title、pubdate、newest_outcome、newest_error_code |
| v_missing_subtitle | view | video_part_id、work_id、bvid、page_index、cid、part_title、duration_ms、video_title、pubdate |
| v_missing_transcript | view | video_part_id、work_id、bvid、page_index、cid、part_title、duration_ms、video_title、pubdate |
| v_part_pipeline | view | video_part_id、work_id、bvid、page_index、processing_status、pipeline_state |
| v_pending_metadata | view | video_part_id、work_id、bvid、page_index、processing_status |
| v_pending_subtitles | view | video_part_id、work_id、bvid、page_index、cid、part_title、duration_ms、attempted、last_attempt_at、last_attempt_outcome、last_attempt_error_code、last_attempt_credential_present |
| v_video_parts | view | video_part_id、work_id、user_name、video_title、page_index、cid、part_title、duration_ms、processing_status、created_at、updated_at |
### universal-v2：47 张表 / 11 个视图

| 对象 | 类型 | 全部字段 |
| --- | --- | --- |
| acquisition_attempts | table | run_id、video_part_id、outcome、error_code、transcript_id、started_at、finished_at、credential_verified、absence_verified |
| acquisition_runs | table | run_id、kind、selector_kind、selector_target、requested_limit、credential_present、started_at、finished_at、outcome |
| archive_contract | table | singleton、contract |
| asr_models | table | model_id、model_name、revision、created_at |
| audio_objects | table | audio_id、sha256、byte_size、format、duration_ms、storage_key、created_at |
| bilibili_users | table | mid、display_name、created_at、updated_at |
| document_artifacts | table | revision_id、template_version、artifact_name、manuscript_role、relative_path、content_sha256 |
| editorial_chunk_results | table | input_id、chunk_id、call_id、blocks_json |
| editorial_input_versions | table | input_id、version |
| editorial_inputs | table | input_id、video_part_id、base_transcript_id、reference_transcript_id、prepared_json、created_at |
| editorial_job_inputs | table | job_id、input_id |
| editorial_model_calls | table | call_id、attempt_id、input_id、chunk_id、request_json、response_json、error_code、started_at、finished_at |
| editorial_revisions | table | revision_id、input_id、job_id、blocks_json、quality_status、created_at |
| ingestion_cursors | table | mid、next_page、observed_total、state、last_error_code、updated_at |
| ingestion_discoveries | table | run_id、page_number、bvid、source_position、discovered_at |
| ingestion_pages | table | run_id、page_number、outcome、error_code、started_at、finished_at |
| ingestion_runs | table | run_id、mid、source_package、source_version、requested_start_page、requested_page_limit、started_at、finished_at、outcome |
| manuscript_contract | table | version |
| metadata_refresh_attempts | table | id、bvid、operation、state、error_code、started_at、finished_at、details_json |
| migration_records | table | migration_id、source_fingerprint、source_contract、target_contract、report_json、completed_at |
| part_audio_objects | table | video_part_id、audio_id、acquired_at、acquisition_source |
| publication_content_versions | table | edition_id、version |
| publication_edition_reviews | table | edition_id、review_id、content_sha256、status、actor、note、issue_url、updated_at |
| publication_editions | table | edition_id、video_part_id、revision_id、parent_edition_id、content_json、content_sha256、created_at、created_by、note |
| publication_events | table | event_id、video_part_id、edition_id、release_id、review_id、content_sha256、event_type、from_status、to_status、actor、issue_url、note、changed_at |
| publication_heads | table | video_part_id、current_edition_id、current_release_id |
| publication_releases | table | release_id、video_part_id、edition_id、review_id、content_sha256、template_version、relative_path、artifact_sha256、published_at、published_by、status |
| source_caption_observations | table | observation_id、video_part_id、run_id、policy_version、state、access_context、error_code、observed_at、provenance_json |
| source_creators | table | creator_id、platform、external_id、display_name、created_at、updated_at |
| source_metadata_observations | table | platform、external_id、operation、field、state、observed_at、last_success_at、error_code、value_json |
| source_videos | table | source_video_id、platform、external_id、creator_id、title、published_at、original_language、canonical_url、observed_at、created_at、updated_at |
| transcript_asr_evidence | table | run_id、video_part_id、transcript_id、schema_version、evidence_json |
| transcript_coverage_attestations | table | run_id、video_part_id、transcript_id、decoded_s、produced_s、coverage、coverage_min、coverage_short |
| transcript_segments | table | transcript_id、ordinal、start_ms、end_ms、text |
| transcripts | table | transcript_id、video_part_id、source_kind、language、model_id、version、content_sha256、created_at |
| video_details | table | bvid、pic、desc、tid、observed_at |
| video_parts | table | video_part_id、bvid、page_index、cid、title、duration_ms、processing_status、created_at、updated_at、source_video_id |
| video_tag_observations | table | bvid、state、observed_at、error_code、run_id |
| video_tags | table | bvid、tag_id、tag_name、tag_type |
| videos | table | bvid、aid、mid、title、pubdate、created_at、updated_at |
| workflow_asr_profile_configs | table | profile_id、schema_version、config_json |
| workflow_asr_profiles | table | profile_id、profile_key、model_name、model_revision、aligner_name、device、language、config_sha256、created_at |
| workflow_attempts | table | attempt_id、job_id、worker_id、started_at、finished_at、outcome、error_code、result_json |
| workflow_job_dependencies | table | job_id、prerequisite_job_id |
| workflow_jobs | table | job_id、kind、video_part_id、profile_id、policy_key、dedupe_key、payload_json、status、priority、available_at、lease_owner、lease_expires_at、attempt_count、last_error_code、created_at、updated_at |
| workflow_publications | table | publication_id、video_part_id、transcript_id、published_at、artifact_json |
| workflow_quality_assessments | table | assessment_id、video_part_id、source_kind、score、assessor、details_json、assessed_at |
| v_bilibili_missing_audio | view | video_part_id、work_id、bvid、page_index、cid、part_title、duration_ms、video_title、pubdate、newest_outcome、newest_error_code |
| v_bilibili_part_pipeline | view | video_part_id、work_id、bvid、page_index、processing_status、pipeline_state |
| v_ingestion_run_stats | view | run_id、mid、started_at、finished_at、outcome、page_count、video_count |
| v_missing_audio | view | video_part_id、work_id、bvid、page_index、cid、part_title、duration_ms、video_title、pubdate、newest_outcome、newest_error_code |
| v_missing_subtitle | view | video_part_id、work_id、bvid、page_index、cid、part_title、duration_ms、video_title、pubdate |
| v_missing_transcript | view | video_part_id、work_id、bvid、page_index、cid、part_title、duration_ms、video_title、pubdate |
| v_part_pipeline | view | video_part_id、work_id、bvid、page_index、processing_status、pipeline_state |
| v_pending_metadata | view | video_part_id、work_id、bvid、page_index、processing_status |
| v_pending_subtitles | view | video_part_id、work_id、bvid、page_index、cid、part_title、duration_ms、attempted、last_attempt_at、last_attempt_outcome、last_attempt_error_code、last_attempt_credential_present |
| v_source_parts | view | video_part_id、source_video_id、bvid、cid、page_index、title、duration_ms、processing_status、platform、external_video_id、video_title、pubdate、original_language、canonical_url、observed_at、creator_external_id、creator_name |
| v_video_parts | view | video_part_id、work_id、user_name、video_title、page_index、cid、part_title、duration_ms、processing_status、created_at、updated_at |

### 全部 SQL 资源

- [src/bili_asr/storage/schema-artifact-online.sql](../src/bili_asr/storage/schema-artifact-online.sql)
- [src/bili_asr/storage/schema-artifact-storage.sql](../src/bili_asr/storage/schema-artifact-storage.sql)
- [src/bili_asr/storage/schema-content-v2.sql](../src/bili_asr/storage/schema-content-v2.sql)
- [src/bili_asr/storage/schema-editorial.sql](../src/bili_asr/storage/schema-editorial.sql)
- [src/bili_asr/storage/schema-observations.sql](../src/bili_asr/storage/schema-observations.sql)
- [src/bili_asr/storage/schema-preserved-body-import.sql](../src/bili_asr/storage/schema-preserved-body-import.sql)
- [src/bili_asr/storage/schema-source-supplements.sql](../src/bili_asr/storage/schema-source-supplements.sql)
- [src/bili_asr/storage/schema-source-sync.sql](../src/bili_asr/storage/schema-source-sync.sql)
- [src/bili_asr/storage/schema-transcripts.sql](../src/bili_asr/storage/schema-transcripts.sql)
- [src/bili_asr/storage/schema-workflow.sql](../src/bili_asr/storage/schema-workflow.sql)
- [src/bili_asr/storage/schema.sql](../src/bili_asr/storage/schema.sql)

可选 preserved-body、来源补充、artifact-storage 和 artifact-online 必须按已登记精确组合显式安装；不代表所有归档都有全部表。动态 FTS transcript_fts 与 metadata 表是可重建消费对象。完整 PK/FK/CHECK、版本指纹及升级边以安装包 contracts 与 storage/archive_contracts 为准。
