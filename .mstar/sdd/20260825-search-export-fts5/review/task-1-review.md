# Task 1 Review: Index build + search

- **Plan**: `20260825-search-export-fts5` (SQLite FTS5 Search/Export Read Model)
- **Task**: Task 1: Index build + search
- **Review range**: `cffe0f1de6ecc8a9d75060ebebb6db0b3a9fb2ce..cb7ff6069c76b443e682bb2b64cfcd03daedad99` (commit `cb7ff60`)
- **Reviewer**: `code-reviewer` (SDD Task Reviewer, L2)
- **Verdict**: **Approved**

---

## Spec Compliance Checklist

| Item | Brief Requirement | Status | Review Notes |
| :--- | :--- | :---: | :--- |
| 1 | `SearchIndex.build(manifest)` indexes ONLY completed transcript rows (`archived` / `subtitle_done` with transcript/archive paths present); `audio_ok` without transcripts is NOT searchable. | ✅ | Correctly enforced via `COMPLETED_STATUSES = frozenset({"archived", "subtitle_done"})` and `_is_indexable(entry)`. Non-completed rows (`audio_ok`, `needs_audio`, `meta_ok`, `pending`, `gone`) and archived rows lacking on-disk/metadata transcript paths are strictly excluded. Tested in `test_build_indexes_only_completed_transcripts_with_paths`. |
| 2 | `bili-asr search <query> [--limit N] [--rebuild] [--archive-root]` queries FTS5 with ranking; bounded `--limit`; no results → exit 1 with clear message. | ✅ | Uses FTS5 `ORDER BY rank` (BM25). `--limit` argument is parsed, validated, and applied in SQL. Zero results correctly print `search: no matching transcripts found for ...` to `stderr` and exit with code 1. Matching hits print `{work_id}: {title} [{status}] (score: {score:.4f}, path: {path})` and exit 0. |
| 3 | Rebuild idempotent; stale detection documented. | ✅ | `SearchIndex.build()` builds into `search.db.tmp` and uses atomic `os.replace`. `is_stale()` verifies DB presence, mtime vs `manifest.jsonl`, and completed entry count vs indexed count. Idempotency and stale transitions are verified in unit tests. |
| 4 | FTS5 unavailable → environment prerequisite error (no silent skip). | ✅ | `FTS5UnavailableError` is explicitly raised if SQLite lacks FTS5 support during build or query, and CLI exits with code 1 and a descriptive error message on `stderr`. Explicitly tested with monkeypatched missing FTS5. |

---

## Global Constraints Compliance

- **Manifest remains SSOT**: ✅ Verified. `SearchIndex` only reads from `ManifestStore.load()`. No manifest modifications or JSONL writes occur during indexing or search (asserted in `test_manifest_remains_unmodified_during_build_and_search`).
- **No new runtime dependencies**: ✅ Verified. Uses stdlib `sqlite3` FTS5 virtual table. No external dependencies (no Meilisearch, no third-party indexers).
- **Network / Module isolation**: ✅ Verified. `bili_asr/search_index.py` does not import `bili_client`, `requests`, `urllib`, or open any network sockets.
- **Naming / Status convention**: ✅ Verified. Schema, dataclass, and CLI output strictly use `status` (never `state`).
- **Secret & exception hygiene**: ✅ Verified. Index stores only public metadata and local paths. Raw tracebacks are trapped with user-friendly error messages on CLI surfaces.
- **No live HTTP in tests**: ✅ Verified. All 23 tests run against synthetic local filesystem fixtures.
- **Scope discipline**: ✅ Verified. Surgical commit containing only Task 1 deliverables. `export` command and README updates are properly deferred to Task 2.

---

## Issues

### Critical
*None.*

### Important
*None.*

### Minor / Observational
- **Query syntax safety fallback**: `SearchIndex.search()` includes a fallback that wraps syntax-violating queries (e.g. unclosed quotes or bare colons) into exact phrase searches (`"..."`), preventing SQLite `OperationalError` aborts on raw user input.
- **SRT stripping**: `_extract_transcript_text()` filters out SRT sequence counters and timestamp lines (`00:00:00,000 --> ...`), ensuring clean text indexing in FTS5.

---

## Strengths

1. **Robust Stale Detection**: `is_stale()` combines filesystem timestamp comparison (`manifest.jsonl` mtime vs `search.db` mtime) with record count validation (`completed_count != indexed_count`), catching both file updates and row mutations.
2. **Atomic Index Replacement**: Index construction creates `search.db.tmp` and swaps it with `os.replace`, ensuring reader queries never observe half-built or corrupted databases.
3. **Comprehensive Test Suite**: 23 focused tests thoroughly validate edge cases including CJK/Chinese text search, legacy bare-bvid entries, raw JSON subtitle/ASR fallback parsing, limit bounds, and explicit FTS5 unavailability handling.

---

## Assessment Summary

The Task 1 implementation is clean, robust, and completely satisfies all Task Brief requirements and Plan Global Constraints with zero regressions. Approved to proceed to Task 2.
