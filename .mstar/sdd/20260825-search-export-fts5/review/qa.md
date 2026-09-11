# QA Acceptance Report — 20260825-search-export-fts5

- **Plan ID**: `20260825-search-export-fts5`
- **QA Gate**: Mandatory (acceptance-only)
- **Role**: `qa-engineer` (L4)
- **Verdict**: **Pass**
- **Working branch**: `plan/20260825-search-export-fts5`
- **Review cwd / Worktree path**: `/root/workspace/bilibili-asr-archive/.worktrees/20260825-search-export-fts5`
- **Review range / Diff basis**: `cffe0f1de6ecc8a9d75060ebebb6db0b3a9fb2ce..5b392cc64f44099e48f83e32a8fc2ade6fe01e4c`
- **Date**: 2026-08-25

---

## Verdict

**Pass** — All 5 Acceptance Criteria verified with full reproducible test suite coverage, zero residuals, and clean checkout alignment.

---

## Checkout Alignment Confirmation

- **Worktree path**: `/root/workspace/bilibili-asr-archive/.worktrees/20260825-search-export-fts5/bilibili-asr-archive`
- **Branch**: `plan/20260825-search-export-fts5`
- **HEAD Commit**: `5b392cc64f44099e48f83e32a8fc2ade6fe01e4c` (`fix(search,export): address QC3 findings for connection lifecycle, caching, and atomic writes`)
- **Diff basis**: `cffe0f1..5b392cc` (includes `cb7ff60`, `2b8dd69`, `5b392cc`)
- **Working tree**: Clean (`git status` reports nothing to commit).

---

## Validation: Acceptance Criteria to Evidence Mapping

### AC 1: `bili-asr search <query>` returns ranked matches from completed transcript metadata only; no hits → exit 1 with a clear message.
- **Status**: **PASS**
- **Evidence Mapping**:
  - `SearchIndex.build()` filters strictly on `status in {"archived", "subtitle_done"}` with non-empty transcript text extracted; non-completed stages (`audio_ok`, `needs_audio`, `meta_ok`, `pending`, `gone`) are skipped.
  - Queries use SQLite FTS5 BM25 `ORDER BY rank` with bounded `--limit`.
  - CLI `_cmd_search` outputs matches to stdout (exit 0) or outputs `search: no matching transcripts found for ...` to stderr and returns exit code 1.
  - Tests: `test_build_indexes_only_completed_transcripts`, `test_search_ranking_and_limit`, `test_cli_search_hits_and_no_hits_exit_codes`, `test_cli_search_cjk_query` in `tests/test_search_index.py`.
- **Reused / Executed**: Reused L1/L2/L3 reports + Newly executed in QA suite pass.

### AC 2: `bili-asr export --format json|csv` writes manifest-derived metadata; `--with-text` is opt-in for transcript bodies.
- **Status**: **PASS**
- **Evidence Mapping**:
  - `export_manifest()` generates JSON/CSV metadata from manifest entries.
  - `transcript_text` is omitted by default; included only when `--with-text` is passed.
  - Supports `--out <path>`, `--status <status>` (single, multiple, comma-separated), and atomic file writes via `.tmp` + `os.replace`.
  - Tests: `test_export_json_default_without_text`, `test_export_csv_default_without_text`, `test_export_json_and_csv_with_text`, `test_export_out_file_writing`, `test_export_status_filtering`, `test_export_atomic_out_write_and_cleanup_on_failure` in `tests/test_export.py`.
- **Reused / Executed**: Reused L1/L2/L3 reports + Newly executed in QA suite pass.

### AC 3: Rebuild is idempotent; stale detection is documented; search/export never modify the manifest.
- **Status**: **PASS**
- **Evidence Mapping**:
  - `SearchIndex.build(force=...)` uses atomic temp database replacement, ensuring deterministic idempotent content across multiple runs.
  - Stale detection checks database existence, `manifest.jsonl` mtime vs `search.db` mtime, and completed transcript count vs indexed count.
  - Search and export commands perform read-only operations (`ManifestStore.load()`); manifest is never rewritten or mutated.
  - Documented in `README.md` under `SQLite FTS5 full-text search and metadata export`.
  - Tests: `test_build_idempotency`, `test_manifest_not_modified_during_search_or_build`, `test_stale_detection_and_rebuild`, `test_is_stale_mtime_short_circuits_before_load` in `tests/test_search_index.py`; `test_export_does_not_modify_manifest` in `tests/test_export.py`.
- **Reused / Executed**: Reused L1/L2/L3 reports + Newly executed in QA suite pass.

### AC 4: No credentials/signed URLs/raw exceptions in index or output. Meilisearch is out of scope.
- **Status**: **PASS**
- **Evidence Mapping**:
  - Indexing restricted to `work_id`, `title`, `status`, `transcript_text`, `archive_paths`, `duration_s`.
  - `sanitize_export_entry()` explicitly strips `sessdata`, `cookie`, `cookies`, `bili_sessdata`, `url`, `signed_url`, `stream_url`, `audio_url`, `traceback`, `exception`, `error_trace`.
  - Zero Meilisearch runtime dependencies; stdlib `sqlite3` only.
  - Tests: `test_export_sanitizes_credentials_and_signed_urls` in `tests/test_export.py`; `test_search_safe_exceptions_and_no_credentials` in `tests/test_search_index.py`.
- **Reused / Executed**: Reused L1/L2/L3 reports + Newly executed in QA suite pass.

### AC 5: Full Python 3.12 suite passes; no live HTTP. If FTS5 is missing in stdlib, fail with an environment prerequisite (no silent skip of core behavior).
- **Status**: **PASS**
- **Evidence Mapping**:
  - `check_fts5_available()` explicitly tests FTS5 virtual table support in SQLite; `FTS5UnavailableError` is raised and reported to stderr with exit code 1 if unavailable (no silent skips).
  - No live network requests; tests use synthetic in-memory/tempfile fixtures.
  - Full test suite passes: 255 tests passed in 4.61s.
  - Tests: `test_fts5_availability_check`, `test_fts5_unavailable_error_raises`, `test_cli_search_fts5_unavailable_exit_code` in `tests/test_search_index.py`.
- **Reused / Executed**: Newly executed and verified.

---

## Verification Execution Output

### 1. Focused Verification
```bash
cd /root/workspace/bilibili-asr-archive/.worktrees/20260825-search-export-fts5/bilibili-asr-archive
PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest tests/test_search_index.py tests/test_export.py -q
```
**Output**:
```
.....................................                                    [100%]
37 passed in 0.41s
```

### 2. Full Test Suite Verification
```bash
cd /root/workspace/bilibili-asr-archive/.worktrees/20260825-search-export-fts5/bilibili-asr-archive
PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest -q
```
**Output**:
```
........................................................................ [ 28%]
........................................................................ [ 56%]
........................................................................ [ 84%]
.......................................                                  [100%]
255 passed in 4.61s
```

---

## Residuals Check

- **Open Residuals**: 0 (zero-residual verified)
- **QC3 Re-review**: All QC findings (1 warning, 2 suggestions) were fixed in `5b392cc` and re-verified. Streaming export suggestion documented as future-scale backlog item (not a blocker for current ~4k catalog size).

---

## Gaps / Notes

- None. All deliverables are complete, documented, tested, and conform to project constraints.
