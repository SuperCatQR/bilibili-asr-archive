# Bilibili ASR Archive

A local pipeline that collects Bilibili video metadata, acquires subtitle or audio evidence, runs local ASR when planned, and publishes transcript bundles. SQLite is the operational source of truth; transcript and audio files are derived products.

The explicit `universal-v2` archive adds single-video YouTube ingestion and
versioned source metadata without rewriting historical Bilibili editions.
See [Issues implementation and architecture](docs/issues-implementation.md),
[source adapters](docs/source-adapters.md), and [ASR workers](docs/asr-workers.md)
for migration, optional dependencies, worker roles and recovery checks.

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

AI revisions produce an immutable `ai-draft.md` and a verification reference
`review.md`. Editors create complete publication editions, review their exact
content hashes, and explicitly publish approved editions as `publish.md`.
The public reading-site projection includes only each part's current release.
Its source repository, `SuperCatQR/markdown-reading-site`, is an independent
delivery; the local `reading-site/` checkout is ignored by this repository.

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
- `archive.py` writes SRT, WebVTT, TXT, Markdown, raw JSON, and the five-product bundle marker.
- `coverage_report.py`, `integrity.py`, `export.py`, and search queries read projections over SQLite and published files; explicit index builds write FTS and recovery progress.

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
Before resuming past page 1, collection verifies the BVID order of every
previously collected page using list requests only. Changed or missing
prefix evidence returns `metadata_resume_requires_reenumeration` and leaves
the cursor untouched, even with `--skip-failed-page`. Use `--incremental`
to enumerate from page 1 and recover moved or newly uploaded videos.
Verification uses the shared request/deadline budget and does not refresh
previous pages' details, parts or tags. It cannot freeze Bilibili's list;
periodic homepage enumeration is still needed for changes during a run.
An upstream gateway failure returns exit 2. Rate control records the
page/run outcome `risk_interrupted` and preserves the existing cursor; a
first-page failure can leave no cursor at all. Re-run without `--resume` in
that case. Other failures record `failed`; `--skip-failed-page` can advance
past those failures but never skips rate control. `--start-page` explicitly
overrides the cursor and can move it backwards.

The summary distinguishes page evidence (`recorded`) from successfully
collected nonempty pages, videos and parts. Failure diagnostics report the
operation and available HTTP status, API code or `wbi_retry_exhausted`
reason, without raw upstream messages or credentials. `--page-retries 0`
stops on the first failed upload-list attempt; opt into at most five retries
with `--page-retries 1` through `5` (30/60/120/240/300 second cooldowns).
`--operation-retries 0` also defaults to one attempt. Set it to `1` through
`5` to retry necessary detail/parts transport failures with the same bounded
cooldowns, without repeating successful list or sibling requests. Each
attempt consumes the shared request budget; exhausted budgets, authentication,
malformed data, not-found and rate control stop these operation retries.
This option applies to paginated collection, not targeted `--bvid` or
`--refresh-failed` commands. Prefix verification failures are never skipped;
an explicitly skipped page leaves a gap requiring homepage re-enumeration
before a later implicit resume can establish coverage.
When `BILI_SESSDATA` is configured, the gateway verifies login once before
the first upload-list request. Rejected credentials stop with `auth_error`
and require refreshing the cookie; they are not retried as rate control.
Anonymous metadata collection does not add this login check.

Choose one or more stored video-part IDs and plan producer jobs. The database ID can be inspected with SQLite:

```sql
SELECT video_part_id, bvid, page_index, title FROM video_parts ORDER BY video_part_id;
```

```powershell
bili-asr workflow plan --part-id 42 --asr-policy all
bili-asr workflow plan --bvid BV_EXAMPLE --page-index 0 --proofread
bili-asr workflow run --limit 20
bili-asr workflow status --jobs
```

`workflow plan` is idempotent for the same input and policy. Repeat either `--part-id` or `--bvid`; the two selection forms are mutually exclusive. BVID selection uses stored metadata and optionally selects the same zero-based `--page-index` in each video (`0` is source P1). All targets are validated before profiles or jobs are created. See [workflow selection](docs/workflow-selection.md).

Subtitle acquisition is independent; ASR waits for its audio prerequisite. `--asr-policy` accepts `all`, `selected`, or `below-threshold`. The first two plan ASR for the explicit selection; `below-threshold` requires a stored quality assessment below `--quality-threshold`. ASR profiles freeze the full effective configuration, including independent model/aligner revisions, chunk size, timeout, hotwords, offline loading and generation budget. Explicit planning arguments override the environment; execution uses the stored snapshot.

Successful ASR runs retain per-chunk diagnostics independently of transcript content deduplication. Inspect them with `bili-asr workflow asr-evidence --run-id RUN_ID --part-id 42`. See [ASR configuration and diagnostics](docs/asr-configuration.md) for parameter defaults and quality flag meanings, and [public sample results](docs/asr-public-samples.md) for the evidence supporting the current baseline. Hotwords remain empty and are outside routine tuning.

Cancel selected jobs using IDs from `workflow status --jobs`:

```powershell
bili-asr workflow cancel --job-id JOB_ID --job-id ANOTHER_JOB_ID
```

Queued and running jobs become `cancelled`; running work stops cooperatively at safe boundaries. Cancellation and result commits share a SQLite write lock. Completed jobs are a no-op; dependants remain queued and are reported as blocked. Retry and repeated planning do not revive the same cancelled job. See [cancellation](docs/workflow-cancellation.md).

To rebuild a bundle from an existing preferred transcript, without reacquisition:

```powershell
bili-asr workflow publish --part-id 42
bili-asr workflow run
```

Bundles now require all five products and an `archive-bundle-v2` marker with SHA-256 digests. Existing four-product bundles require explicit republication; incompatible workflow databases require a backup and rebuild. See [WebVTT and bundle integrity](docs/webvtt.md).

Editorial work can be planned from stored transcripts and rendered deterministically:

```powershell
bili-asr workflow proofread --part-id 42 --no-reference
bili-asr workflow render --revision-id REVISION_ID
bili-asr workflow run --only-editorial
```

The editorial workflow stops after generating the AI draft and its reference.
It does not create editions, approve them, or publish articles. Create an
edition explicitly and inspect its complete content and hash:

```powershell
bili-asr publication create --archive-root archive --revision-id REVISION_ID --actor EDITOR
bili-asr publication show --archive-root archive --edition-id EDITION_ID --format json
bili-asr editorial export --archive-root archive --revision-id REVISION_ID --edition-id EDITION_ID --out review-output
```

After an explicit review decision for that edition and hash, record the
review, publish the approved edition, then export the public snapshot:

```powershell
bili-asr publication review --archive-root archive --edition-id EDITION_ID --status in-review --expected-status pending-review --content-sha256 CONTENT_SHA256 --actor REVIEWER --note "Review started"
bili-asr publication review --archive-root archive --edition-id EDITION_ID --status approved --expected-status in-review --content-sha256 CONTENT_SHA256 --actor REVIEWER --note "Approved this edition"
bili-asr publication publish --archive-root archive --edition-id EDITION_ID --actor PUBLISHER
bili-asr publication export --archive-root archive --out reading-site/content
```

Editor-confirmed cross-video reading order is maintained separately with
`publication series edit/validate/show`. Optional `--series-file` on both public
and draft exports binds those relations to the exact category catalog and adds
a hashed `series.json` to the existing manifest. No relation is inferred from
titles or AI output. See [series maintenance and export](docs/publication-series.md).

New drafts and pending reviews leave the existing release public. The new
release replaces it only after explicit publication. See
[publication.md](docs/publication.md) for editing, expected version checks,
withdrawal, output contracts and separate internal review exports. Transcript
bundle publication performed by workflow `publish` remains a separate operation.
Older manuscript databases, templates, commands and export manifests are
rejected without migration; use a separate fresh archive for the new contract.

To make current unpublished editions visible in the site's separate draft tab,
explicitly export the reader preview into a different directory:

```powershell
bili-asr publication export-drafts --archive-root archive --out reading-site/draft-content
```

This read-only preview carries exact edition identities and review labels, and
does not approve or publish content. Editions that already have release history
are excluded, so withdrawn releases do not reappear as drafts. The full private
review package remains separate from both website inputs.

Both reader catalogs use strict `schemaVersion: 2` and pair each article with
its exact AI revision's original `review.md`. The website can show the full
source comparison, replay links, issues and non-sensitive model parameters.
Required `reviewFile` and `reviewArtifactSha256` fields bind the copied bytes;
this reference does not approve an edition or assess later manual changes.
Private review records, actors, model requests/responses and `review.json`
remain outside the public snapshots. Generic export manifests still use
version 1. To upgrade existing version 1 catalogs, export into fresh output
directories and replace the site snapshots together after validation; old
catalogs are refused without fallback or automatic conversion.

## Query

```powershell
bili-asr status
bili-asr runs --limit 10
bili-asr coverage --format json
bili-asr verify --format text
bili-asr export --format csv --out archive/export.csv --with-text
bili-asr search-index
bili-asr search "transcript words" --format json
bili-asr search "标题关键词" --scope metadata --format json
bili-asr search "课程" --scope all --from 2026-01-01 --to 2026-12-31
bili-asr dedup report --archive-root archive --format text
```

`dedup report` is a read-only exact-reuse inventory. It reports audio objects
linked by multiple video parts and identical transcript content hashes seen
across parts; it never deletes, merges, or rewrites source records. Use
`--format json` for a machine-readable baseline and `--limit` to cap only the
example groups included in the output.

`status`, `runs`, and workflow inspection use read-only sessions over an existing compatible database. Queries never initialize a database or refresh views; missing or incompatible databases are refused. Coverage, verification, export, publication export, editorial export and dedup also use read-only projections. `fetch-meta` explicitly bootstraps the archive; `search-index` and `search --rebuild` explicitly write the derived index.

`workflow run --artifact-root PATH` and `BILI_ARTIFACT_ROOT` place audio, bundles and editorial Markdown in a separate existing directory while keeping `archive.db` at the archive root. Readers use the configured root first and the archive root as fallback. `workflow render` accepts the configuration when queuing; the subsequent run still needs the same flag or environment setting. See [docs/artifact-root.md](docs/artifact-root.md).

`bili-asr artifacts` provides read-only inventory, frozen offload plans, an explicit catalog upgrade, verified directory packages, manual audio offload and single-object restore. Production state stays in the archive database after audio moves. Offload uses an exclusive maintenance window and preserves queued, failed or held inputs; restore the retained SHA-256 before running a new consumer. See [artifact storage](docs/artifact-storage.md) for commands, target identity, crash recovery and snapshot limits.

Database table contracts must match the current shipped SQL. Incompatible old databases are refused before schema changes; there are no migrations. Stop workers, preserve any needed backup, delete the affected `archive.db`, and re-run metadata collection and workflow planning. **Rebuilding discards old database facts, including transcripts, revisions and review history.**

Search defaults to `transcripts`. `metadata` searches stored titles,
descriptions, and tags directly, without FTS or published artifacts. `all`
returns metadata first, followed by transcript hits under one total limit.
Dates use UTC video publication days; JSON includes `hit_type`. See
[metadata search](docs/metadata-search.md).

The current workflow writes audio, bundles, and documents under `--archive-root`.
Audio is retained; workflow has no automatic disk-budget or reclaim option.
See [artifact roots](docs/artifact-root.md) and [audio retention](docs/audio-retention-policy.md).

## Save and Restore an Archive

Stop archive writers before saving. A portable ZIP contains a consistent
`archive.db` snapshot, audio, transcript bundles, reading documents, and a
versioned SHA-256 file inventory. Save outside the archive directories:

```powershell
bili-asr snapshot save --archive-root archive --out D:\Backups\bili-archive.zip
bili-asr snapshot check --file D:\Backups\bili-archive.zip
bili-asr snapshot restore --file D:\Backups\bili-archive.zip --archive-root D:\BiliArchive
bili-asr workflow run --archive-root D:\BiliArchive
```

The restore target must be new or empty. Completed jobs, metadata cursors,
transcripts, and revisions survive; interrupted jobs are requeued in the
restored database while their attempt history is retained. Files recorded in
the database must be present and match their known hashes. Check works offline
without the original archive, credentials, a model, or GPU dependencies.

`snapshot save --artifact-root PATH` also includes an existing separate product
root (or `BILI_ARTIFACT_ROOT`); restore brings all products into the new archive
root so the workflow can use their relative paths directly. This version
supports the current database contract and whole-archive transfer. Configure
credentials and the compatible ASR runtime on the destination host separately.
See [archive-snapshots.md](docs/archive-snapshots.md) for consistency, recovery,
and format details.

## Tests

```powershell
uv run pytest tests/test_workflow_selection.py tests/test_workflow_cancellation.py tests/test_workflow_publication.py tests/test_workflow_audio_staging.py tests/test_webvtt.py tests/test_metadata_search.py tests/test_workflow_control_plane.py tests/test_workflow_lease_heartbeat.py tests/test_ai_editorial.py
```

This focused suite covers the supported SQLite workflow and metadata path. The full test tree also contains historical pre-cutover tests and host-dependent integration tests; run it separately when changing those areas. Live network tests require `BILI_LIVE_SMOKE=1`; scale tests require `BILI_SCALE=1`.

The [documentation index](docs/README.md) links the current architecture,
feature guides, storage contracts, and implementation assessment for #247–#250.
