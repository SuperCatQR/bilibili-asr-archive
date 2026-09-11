# Task 2 Review Report: Export Command + Integration & Documentation

- **Plan**: `20260825-search-export-fts5` (SQLite FTS5 Search/Export Read Model)
- **Task**: Task 2: Export + integration + README
- **Review Range**: `cb7ff6069c76b443e682bb2b64cfcd03daedad99..2b8dd69`
- **Working Branch**: `plan/20260825-search-export-fts5`
- **Reviewer**: `code-reviewer` (SDD task reviewer, fresh)

---

## Verdict

**Approved** (Severity: None / Clean pass)

---

## Spec Compliance Checklist

| Brief Item | Status | Notes |
|---|:---:|---|
| `bili-asr export --format json\|csv` writes manifest-derived rows (no transcript bodies by default) | ✅ | Implemented in `src/bili_asr/export.py` (`export_manifest`, `format_json_export`, `format_csv_export`) and CLI `src/bili_asr/cli.py` (`_cmd_export`). Without `--with-text`, transcript bodies are strictly excluded. |
| `--with-text` includes transcript text; never includes credentials/signed URLs | ✅ | `sanitize_export_entry` loads transcript text on opt-in via `extract_transcript_text`, while stripping sensitive keys (`sessdata`, `cookie`, `cookies`, `bili_sessdata`, `url`, `signed_url`, `stream_url`, `audio_url`, `traceback`, `exception`, `error_trace`). |
| README documents search/export, rebuild, and manifest-as-SSOT boundary | ✅ | `README.md` updated with comprehensive section detailing `search` and `export` CLI options, SSOT boundary, BM25 ranking, automated stale detection, rebuild semantics, and credential security. |
| Manifest stays SSOT; export never rewrites it | ✅ | `export.py` and `cli.py` only perform read operations (`store.load()`); tested and verified with `test_export_manifest_immutability`. |

---

## Global Constraints Compliance

- **Manifest SSOT**: `export_manifest` reads manifest entries via `ManifestStore.load()` and never calls `upsert` or modifies `manifest/manifest.jsonl`.
- **Zero New Dependencies / Stdlib Only**: Uses only Python stdlib modules (`csv`, `io`, `json`, `os`, `sqlite3`). No Meilisearch, no external database or parsing packages added.
- **Zero Network / API Boundaries**: `export.py` and `search_index.py` do not import `bili_client` or invoke network calls.
- **Credential & URL Hygiene**: Sensitive keys are stripped during sanitization. Raw exception stack traces are denied from output.
- **Vocabulary Consistency**: Manifest column and CLI flag strictly use `status` (never cursor `state`).
- **Offline Tests**: All 12 new tests in `tests/test_export.py` use local fixture stores and temp directories with zero network calls.

---

## Issues

*No Critical, Important, or Minor issues identified.*

---

## Strengths

1. **Clean Code Reuse**: Factored `extract_transcript_text` out of `SearchIndex` into a shared public function, providing a single source of transcript text resolution across both search indexing and export formatting.
2. **Robust Export Formatting**: `format_csv_export` standardizes canonical column order (`STANDARD_CSV_COLUMNS`), deterministically appends additional columns, safely serializes nested structures (dicts/lists to JSON strings), and handles empty datasets cleanly.
3. **Flexible Status Filtering**: `_parse_status_filter` supports both repeated flags (`--status archived --status subtitle_done`) and comma-delimited values (`--status archived,subtitle_done`), with strict validation against `VALID_STATUSES` failing fast with exit code 1.
4. **Thorough Test Suite**: `tests/test_export.py` includes 12 targeted test cases verifying default text omission, opt-in `--with-text`, CSV/JSON serialization, `--out` file writing, status filtering, invalid status rejection, sanitization of credentials and signed URLs, bare-bvid legacy rows, and manifest immutability.

---

## Assessment Summary

The Task 2 implementation fully satisfies all requirements and acceptance criteria in `task-2-brief.md` and aligns cleanly with the global constraints in `20260825-search-export-fts5.md`. The code is clean, robust, well-documented, and ready to merge.
