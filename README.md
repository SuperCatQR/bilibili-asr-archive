# Bilibili ASR Archive

A local pipeline that collects Bilibili video metadata, acquires subtitle or audio evidence, runs local ASR when planned, and publishes transcript bundles. SQLite is the operational source of truth; transcript and audio files are derived products.

## Architecture

```text
CLI
 ├─ fetch-meta ──> Bilibili gateway ──> MetadataIngestor ──> MetadataRepository
 ├─ workflow ────> WorkflowRepository <── WorkflowExecutor ── Workflow handlers
 │                                                        ├─ subtitle gateway
 │                                                        ├─ audio downloader
 │                                                        ├─ local ASR
 │                                                        └─ archive writer
 └─ status / runs / coverage / verify / search / export
                   └─ SQLite repositories and read-only projections

archive.db: metadata, transcripts, audio references, workflow jobs, leases, attempts,
            immutable ASR profiles, editorial revisions, and publication records
archive/:   audio files and published transcript bundles
```

The reading-site projection is built separately: SQLite editorial revisions
and hash-verified `reading.md` artifacts are exported read-only to
`reading-site/content/`. Issue review decisions and accepted human editions
return through `reading-review` and `reading-edit`.

## License

This project is licensed under the GNU General Public License, version 3
(GPL-3.0-only). See [LICENSE](LICENSE) for the full license text.

Third-party components retain their original licenses. This software license
does not grant rights to downloaded videos, audio, subtitles, or other archived
content.

The workflow tables are the only job scheduler. `workflow_jobs` stores producer jobs and prerequisite links; `workflow_attempts` stores attempt outcomes and lease ownership. Each ASR job references an immutable profile snapshot and a fixed input transcript when one exists. Publication records identify the transcript version and bundle paths that were written.

Package boundaries:

- `sources/` contains typed network adapters.
- `services/` coordinates acquisition and pure transcript projections.
- `storage/` owns SQLite schema, records, repositories, and workflow scheduling.
- `workflow.py` runs claimed jobs; `workflow_runtime.py` supplies the media handlers.
- `archive.py` writes the SRT, TXT, Markdown, raw JSON, and bundle marker.
- `coverage_report.py`, `integrity.py`, `export.py`, and `search_index/` are read projections over SQLite and published files.

## Install

Python 3.12 or later is required.

For production, use the [Miniconda deployment guide](docs/miniconda-deployment.md).
It covers isolated Python 3.12 environments, pinned application dependencies,
AMD WSL and NVIDIA preflight, non-interactive startup, and deployment evidence.
`check-asr-env` is an AMD WSL check, not a general CUDA support check.

```powershell
uv sync --extra dev
```

Local ASR requires the host's compatible PyTorch/ROCm or CUDA runtime, plus the ASR extra and `ffmpeg`. Install host-specific PyTorch first, then:

```powershell
uv sync --extra asr --inexact
```

Set `BILI_SESSDATA` for authenticated subtitle and audio acquisition. Credentials are resolved at runtime and are not stored in SQLite or exported records.

`bili-asr check-asr-env` reports the five host checks in order: `dxg-detection`, `rocm-loader-path`, `torch-present`, `hsa-runtime`, and `device-probe`.

## Workflow

Collect metadata into `archive/archive.db`:

```powershell
bili-asr fetch-meta --mid 123456 --limit-pages 2
```

Each successful page advances a persisted cursor. Re-run `fetch-meta` to
continue from that cursor, or pass `--resume` to require an existing cursor.
An upstream gateway failure exits with code `2` (exit 2) and records the
`risk_interrupted` cursor state without advancing past the failed page, unless
`--skip-failed-page` was requested. `--start-page` explicitly overrides the
cursor and can move it backwards.

Choose one or more stored video-part IDs and plan producer jobs. The database ID can be inspected with SQLite:

```sql
SELECT video_part_id, bvid, page_index, title FROM video_parts ORDER BY video_part_id;
```

```powershell
bili-asr workflow plan --part-id 42 --asr-policy all
bili-asr workflow run --limit 20
bili-asr workflow status
```

`workflow plan` is idempotent for the same input and policy. Subtitle acquisition is independent; each selected ASR job gets an audio prerequisite. `--asr-policy` accepts `all`, `selected`, or `below-threshold` (with `--quality-threshold`). The current `selected` policy plans ASR for the explicitly supplied parts, as does `all`; `below-threshold` uses the latest stored quality assessment and includes unassessed parts. ASR profiles snapshot model, revision, aligner, device, and language.

Inspect unsatisfied prerequisites and retry a specific failure without discarding its attempt history:

```powershell
bili-asr workflow status --details
bili-asr workflow explain --job-id JOB_ID
bili-asr workflow retry --job-id JOB_ID --kind audio
```

Repeated `--job-id`, `--kind`, and `--part-id` filters combine by intersection across filter types. A queued downstream job becomes ready when its prerequisites succeed. Local processes may share one SQLite database; application and heartbeat connections use the same bounded wait, configured by `BILI_SQLITE_BUSY_TIMEOUT_MS` (default `30000`). See [docs/metadata-storage.md](docs/metadata-storage.md) for the concurrency scope and recovery procedure.

Editorial work can be planned from stored transcripts and rendered deterministically:

```powershell
bili-asr workflow proofread --part-id 42 --no-reference
bili-asr workflow render --revision-id REVISION_ID
bili-asr workflow run --only-editorial
```

The read-only Markdown site importer copies rendered `reading.md` and
`review.md` documents registered in SQLite, resolving their relative paths through the configured artifact roots. The public
site can consume both views and their review status. Export the content snapshot:

```powershell
bili-asr reading-export --archive-root archive --out reading-site/content
```

Record an Issue and review status with `bili-asr reading-review`. Accepted
changes are stored as immutable human editions using `bili-asr reading-edit`;
the original AI revision remains unchanged. This checkout provides the content exporter;
the separately maintained reading-site frontend must be provisioned separately.
See [docs/ai-proofreading.md](docs/ai-proofreading.md#阅读导出与人工审核)
for the export and review commands.

## Query

```powershell
bili-asr status
bili-asr runs --limit 10
bili-asr coverage --format json
bili-asr verify --format text
bili-asr export --format csv --out archive/export.csv --with-text
bili-asr search-index
bili-asr search "transcript words" --format json
bili-asr dedup report --archive-root archive --format text
```

`dedup report` is a read-only exact-reuse inventory. It reports audio objects
linked by multiple video parts and identical transcript content hashes seen
across parts; it never deletes, merges, or rewrites source records. Use
`--format json` for a machine-readable baseline and `--limit` to cap only the
example groups included in the output.

`status` and `runs` refuse a missing database, although opening a compatible existing database may refresh derived views. Workflow inspection uses the initializing database entrypoint. Coverage, verification, export, reading export and dedup use read-only projections; `search-index` writes a derived index.

`workflow run --artifact-root PATH` and `BILI_ARTIFACT_ROOT` place audio, bundles and editorial Markdown in a separate existing directory while keeping `archive.db` at the archive root. Readers use the configured root first and the archive root as fallback. `workflow render` accepts the configuration when queuing; the subsequent run still needs the same flag or environment setting. See [docs/artifact-root.md](docs/artifact-root.md).

Database table contracts must match the current shipped SQL. Incompatible old databases are refused before schema changes; there are no migrations. Stop workers, preserve any needed backup, delete the affected `archive.db`, and re-run metadata collection and workflow planning. **Rebuilding discards old database facts, including transcripts, revisions and review history.**

## Tests

```powershell
uv run pytest tests/test_workflow_control_plane.py tests/test_transcript_projection.py tests/test_metadata_repository.py tests/test_metadata_ingest.py tests/test_metadata_page_retries.py tests/test_metadata_cli.py
```

This focused suite covers the supported SQLite workflow and metadata path. The full test tree also contains historical pre-cutover tests and host-dependent integration tests; run it separately when changing those areas. Live network tests require `BILI_LIVE_SMOKE=1`; scale tests require `BILI_SCALE=1`.
