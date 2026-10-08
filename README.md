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

`workflow plan` is idempotent for the same input and policy. Subtitle acquisition is independent; audio is queued only when needed; ASR waits for its audio prerequisite. `--asr-policy` accepts `all`, `missing-only`, or `quality-gated`. ASR profile configuration includes model, revision, aligner, device, and language.

Editorial work can be planned from stored transcripts and rendered deterministically:

```powershell
bili-asr workflow proofread --part-id 42 --no-reference
bili-asr workflow render --revision-id REVISION_ID
bili-asr workflow run --only-editorial
```

The read-only Markdown site importer copies rendered `reading.md` and
`review.md` documents from SQLite and their recorded artifact roots. The public
site exposes both views; unreviewed revisions are visibly marked for
Issue-based review:

```powershell
bili-asr reading-export --archive-root archive --out reading-site/content
cd reading-site
pnpm install
pnpm dev
```

Record an Issue and review status with `bili-asr reading-review`. Accepted
changes are stored as immutable human editions using `bili-asr reading-edit`;
the original AI revision remains unchanged. See [reading-site/README.md](reading-site/README.md)
for the full review and static publishing flow.

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

Read commands do not bootstrap or create a missing database. `--artifact-root` can point read projections at a separate existing directory containing the published bundles. The default is the archive root.

## Tests

```powershell
uv run pytest tests/test_workflow_control_plane.py tests/test_transcript_projection.py tests/test_metadata_repository.py tests/test_metadata_ingest.py tests/test_metadata_page_retries.py tests/test_metadata_cli.py
```

This focused suite covers the supported SQLite workflow and metadata path. The full test tree also contains historical pre-cutover tests and host-dependent integration tests; run it separately when changing those areas. Live network tests require `BILI_LIVE_SMOKE=1`; scale tests require `BILI_SCALE=1`.
