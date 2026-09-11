# QC Review Report: qc-specialist-2 (Reviewer 2)

- **Plan ID**: `20260825-search-export-fts5`
- **Reviewer**: `qc-specialist-2` (reviewer_index 2)
- **Focus Lens**: **Security and correctness risk**
- **Review cwd / Worktree**: `/root/workspace/bilibili-asr-archive/.worktrees/20260825-search-export-fts5`
- **Working Branch**: `plan/20260825-search-export-fts5`
- **Review Range / Diff Basis**: `cffe0f1de6ecc8a9d75060ebebb6db0b3a9fb2ce..2b8dd69` (commits `cb7ff60` and `2b8dd69`)
- **Date**: 2026-08-25

---

## Verdict

**Approve**

---

## Findings Summary

| Severity | Count | Summary |
| :--- | :---: | :--- |
| **Critical** | 0 | None |
| **Important** | 0 | None |
| **Warning** | 0 | None |
| **Suggestion** | 0 | None |
| **Nit** | 0 | None |

---

## Security and Correctness Audit Details

### 1. Credential, Secret, Signed URL, and Exception Leakage Prevention
- **FTS5 Index Hygiene (`src/bili_asr/search_index.py`)**:
  - Virtual table `transcripts_fts` explicitly indexes only safe columns (`work_id`, `title`, `status`, `transcript_text`, `archive_paths`, `duration_s`).
  - `archive_paths` stores only structured local relative filesystem paths (`srt_path`, `txt_path`, `md_path`, `raw_path`). No streaming URLs or tokens are stored or indexed.
  - Exceptions during file reads (`OSError`, `JSONDecodeError`) are caught and handled gracefully without raw tracebacks leaking.
- **Export Sanitization (`src/bili_asr/export.py`)**:
  - `sanitize_export_entry()` denies sensitive keys case-insensitively using `SENSITIVE_EXPORT_KEYS` (`sessdata`, `cookie`, `cookies`, `bili_sessdata`, `url`, `signed_url`, `stream_url`, `audio_url`, `traceback`, `exception`, `error_trace`).
  - By default, transcript text bodies (`transcript_text`, `text`) are excluded from export, preventing unnecessary text exposure unless explicitly opted into via `--with-text`.
  - Sensitive parameters and tokens are stripped from exported JSON and CSV datasets.
- **CLI Exception Trapping (`src/bili_asr/cli.py`)**:
  - `_cmd_search` and `_cmd_export` trap unexpected exceptions and report concise error summaries (`search: unexpected error`, `export: unexpected error`) to `stderr` without dumping Python tracebacks to the terminal.

### 2. Index Coverage and State Filtering Correctness
- **Completed Transcripts Only (`src/bili_asr/search_index.py:650-682`)**:
  - `_is_indexable()` strictly requires `status` in `COMPLETED_STATUSES = frozenset({"archived", "subtitle_done"})`.
  - Non-completed statuses (`meta_ok`, `needs_audio`, `audio_ok`, `pending`, `gone`) are completely excluded from indexing.
  - Entries marked `archived` or `subtitle_done` are further verified to ensure transcript artifacts exist in entry metadata or on disk (`transcripts/txt`, `transcripts/srt`, `transcripts/md`, `transcripts/raw`, `subtitles/raw`).
  - Entries in `audio_ok` without transcripts cannot be indexed or searched.

### 3. FTS5 Query Safety, Injection Prevention, and Bounded Limits
- **SQL Parameterization (`src/bili_asr/search_index.py:816-842`)**:
  - FTS5 search query uses parameter binding (`WHERE transcripts_fts MATCH ?` with `params = [query]`).
  - SQLite syntax errors resulting from malformed query strings (e.g. unclosed double quotes, bare colons) are safely intercepted with an automatic phrase-escaping fallback (`'"' + query.replace('"', '""') + '"'`), followed by an empty result fallback on unrecoverable syntax. Statement injection is impossible.
- **Limit Bounding & Exit Taxonomy (`src/bili_asr/search_index.py:799-800`, `src/bili_asr/cli.py:1283-1288`)**:
  - Non-positive `--limit` values (`<= 0`) safely return empty results.
  - Zero search hits cleanly print `search: no matching transcripts found for ...` to `stderr` and exit with code 1.
  - Hits print formatted records to `stdout` and exit with code 0.
  - Absence of FTS5 extension in the SQLite build raises `FTS5UnavailableError` and reports an environment prerequisite failure exiting with code 1.

### 4. Manifest Immutability and Read-Only Guarantees
- **SSOT Invariant**:
  - Neither `search` nor `export` imports or invokes `ManifestStore.upsert()` or any mutating filesystem calls on `manifest/manifest.jsonl`.
  - `ManifestStore.load()` is exclusively used for read operations.
  - Verified by dedicated immutability tests `test_manifest_remains_unmodified_during_build_and_search` and `test_export_manifest_immutability`.

### 5. Stale Detection and Rebuild Idempotency
- **Stale Detection (`src/bili_asr/search_index.py:616-648`)**:
  - Verifies database file existence.
  - Compares filesystem modification timestamps (`manifest.jsonl` mtime vs `search.db` mtime).
  - Validates completed transcript row counts against indexed count (`completed_count != indexed_count`), detecting both record additions and status mutations.
- **Atomic Rebuild (`src/bili_asr/search_index.py:708-786`)**:
  - Builds index into an isolated temporary file `search.db.tmp` and replaces the active database atomically using `os.replace()`.
  - Avoids concurrency corruption or partial read anomalies.
  - Multiple rebuild invocations are completely idempotent.

### 6. CSV/JSON Escaping and Vocabulary Compliance
- **CSV/JSON Serialization (`src/bili_asr/export.py:123-174`)**:
  - Standard JSON serialization uses `json.dumps(..., indent=2, ensure_ascii=False)`.
  - CSV output is generated via `csv.DictWriter` with standard RFC 4180 escaping for commas, quotes, and newlines in multi-line transcript texts.
  - Nested dictionary and list fields in CSV are serialized as JSON strings.
- **Vocabulary Consistency**:
  - The codebase consistently uses manifest `status` across CLI arguments (`--status`), JSON keys, CSV column headers (`STANDARD_CSV_COLUMNS`), documentation, and test assertions. Cursor `state` is nowhere used in the search/export model.

---

## Unreviewed Areas

- Runtime execution of `pytest` in this session (read-only static analysis as instructed). Implementation test execution and verification evidence provided in `task-1-report.md` (23/23 passed) and `task-2-report.md` (35/35 focused, 253/253 full suite passed) was statically audited.

---

## Conclusion

The implementation across `src/bili_asr/search_index.py`, `src/bili_asr/export.py`, `src/bili_asr/cli.py`, and `README.md` exhibits outstanding security hygiene, strict manifest immutability, robust query escaping, and complete correctness against the Plan specifications. Approved without reservations.
