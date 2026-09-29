# SQLite FTS5 Search/Export Read Model

> Source: audit DIR-02 (`.mstar/plans/audit-2026-08-24/README.md`) + `PLAN.md` M4 (SQLite FTS5 检索).
> Iteration: `iter-2026-08-pilot-ops`.
> Execution mode: `sdd`.

## Status

- Priority: P2
- Category: product / feature
- Status: Done
- Depends on: none (reads manifest; pilot/ledger not required)
- Findings cleanup: zero-residual

## Goal

Add a **CLI** read-only SQLite FTS5 search/export model over completed transcript metadata (`bili-asr search <query>` / `bili-asr export --format csv|json`) — DIR-02 / PLAN.md M4 — treating the manifest as SSOT and never rewriting it. This is not a search UI.

## Global Constraints

- Manifest remains SSOT; index is a derived read model rebuilt on demand (`bili-asr search --rebuild` or auto-stale check). Search/export never call `upsert` / rewrite JSONL.
- No new runtime dependencies (stdlib `sqlite3` FTS5 only); no manifest schema migration; no Meilisearch.
- `search_index` must not import `bili_client` or open HTTP. CLI composes `ManifestStore.load()` → index.
- No credentials/signed URLs/raw exceptions in index or output.
- No live HTTP in tests; fixtures from existing test archives.
- Column/flag name is manifest **`status`**, never `state` (cursor vocabulary).

## Interfaces (locked)

- New `bili_asr.search_index.SearchIndex(root)`: `{archive_root}/search.db` (FTS5 virtual table over `work_id`, `title`, `status`, `transcript_text`, `archive_paths`, `duration_s`). `work_id` / `artifact_stem` conventions unchanged (`:` never in paths; text loaded from `{archive_root}/transcripts/txt/{stem}.txt` when present).
- Index only **completed transcript** rows: `status` in {`archived`, `subtitle_done`} **and** transcript/archive paths present (`srt_path` / archive writer outputs). `audio_ok` without transcripts is not searchable.
- `bili-asr search <query> [--limit N] [--rebuild] [--archive-root]` → rows with `work_id`, `title`, `status`, score, path. No hits → exit 1.
- `bili-asr export --format json|csv [--out <path>] [--status ...] [--with-text] [--archive-root]` → manifest-derived metadata; transcript bodies only with `--with-text`.
- Stale detection: compare index mtime/row count vs `manifest/manifest.jsonl`; `--rebuild` forces refresh. Idempotent rebuild.

## Tasks

### Task 1: Index build + search

- [x] `SearchIndex.build(manifest)` indexes only **completed transcript** rows: `archived` or `subtitle_done` **with transcript/archive paths present**. `audio_ok` without transcripts is not searchable as complete.
- [x] `bili-asr search` queries FTS5 with ranking; bounded `--limit`; no results → exit 1 with clear message.
- [x] Rebuild idempotent; stale detection documented.

Run: focused `tests/test_search_index.py` passes (stdlib sqlite3 FTS5 available; skip-if-unavailable handled explicitly, not silently).

### Task 2: Export + integration

- [x] `bili-asr export --format json|csv` writes manifest-derived rows (no transcript bodies by default).
- [x] `--with-text` includes transcript text; never includes credentials/signed URLs.
- [x] README documents search/export, rebuild, and manifest-as-SSOT boundary.

Run: focused tests + full suite exit 0.

## Acceptance Criteria

- `bili-asr search <query>` returns ranked matches from completed transcript metadata only; no hits → exit 1 with a clear message.
- `bili-asr export --format json|csv` writes manifest-derived metadata; `--with-text` is opt-in for transcript bodies.
- Rebuild is idempotent; stale detection is documented; search/export never modify the manifest.
- No credentials/signed URLs/raw exceptions in index or output. Meilisearch is out of scope.
- Full Python 3.12 suite passes; no live HTTP. If FTS5 is missing in stdlib, fail with an environment prerequisite (no silent skip of core behavior).

## STOP Conditions

- FTS5 unavailable in target stdlib build → STOP and document environment prerequisite (no silent skip of core behavior).
- Search requires manifest changes to be useful → STOP, keep manifest SSOT.

## Prepare → Execute Handoff

Index coverage is locked to completed transcript rows (`archived` / `subtitle_done` with archive paths). Execute index build first, then search/export surfaces (`--with-text` opt-in; stale detection as specified).

## Durable Review Summary

- **QC (tri, sdd)**: Approve — 3/3 seats (qc1 architecture, qc2 security/correctness, qc3 perf/reliability). 0 Critical/Important. 1 Warning + 2 Suggestions fixed in `5b392cc` (count() close; is_stale mtime-first + _cmd_search cache; atomic --out); QC3 targeted re-review Approve. Streaming-export suggestion documented keep-as-is. Reports: `.mstar/sdd/20260825-search-export-fts5/review/qc1-3.md` + `qc-consolidated.md`.
- **QA (mandatory, acceptance-only)**: **Pass / Recommend Done** — AC1–AC5 all verified (L1 reuse + 37 focused + 255 full tests; checkout aligned at `5b392cc`; 0 open residuals). Report: `.mstar/sdd/20260825-search-export-fts5/review/qa.md`.
- **Residuals**: none open (zero-residual).
