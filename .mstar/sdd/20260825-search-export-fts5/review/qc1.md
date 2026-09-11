# Plan QC Review Report (Reviewer 1)

- **Plan ID**: `20260825-search-export-fts5`
- **Reviewer Index**: 1 (`qc-specialist`)
- **Review Lens**: Architecture coherence and maintainability risk
- **Review cwd / Worktree Path**: `/root/workspace/bilibili-asr-archive/.worktrees/20260825-search-export-fts5`
- **Working Branch**: `plan/20260825-search-export-fts5`
- **Review Range / Diff Basis**: `cffe0f1de6ecc8a9d75060ebebb6db0b3a9fb2ce..2b8dd69`
- **Verdict**: **Approve**

---

## 1. Executive Summary

The branch diff `cffe0f1..2b8dd69` delivers the SQLite FTS5 full-text search index (`bili_asr.search_index.SearchIndex` and `bili-asr search`) and manifest metadata export engine (`bili_asr.export` and `bili-asr export`) as specified in plan `20260825-search-export-fts5`.

From the perspective of **architecture coherence and maintainability risk**, the implementation exhibits exceptional structural hygiene:
1. **Strict Layering & Module Isolation**: Neither `search_index` nor `export` imports `bili_client`, network utilities, or opens HTTP sockets. The CLI layer cleanly composes `ManifestStore.load()` into the read models.
2. **Manifest Remains Absolute SSOT**: Search and export are strictly read-only derivative models; neither module calls `upsert` or modifies `manifest/manifest.jsonl`.
3. **Locked Interfaces Honored**: All 6 FTS5 virtual table fields (`work_id`, `title`, `status`, `transcript_text`, `archive_paths`, `duration_s`) and CLI flags/behaviors precisely match the plan contract.
4. **Resilient Read Model Lifecycle**: Ephemeral SQLite index with atomic temp-db replacement (`os.replace`), comprehensive stale detection (`is_stale`), and safe query syntax fallback.
5. **Hygiene & Security**: Sensitive keys (credentials, session tokens, signed streaming URLs, raw stack traces) are strictly denied and stripped from exports.
6. **Vocabulary Compliance**: Strictly uses manifest `status` (never cursor `state`).

---

## 2. Lens Review & Architectural Analysis

### 2.1 Module Layering & Network Boundaries

- **Inspection Target**: `src/bili_asr/search_index.py`, `src/bili_asr/export.py`, `src/bili_asr/cli.py`.
- **Finding**:
  - `src/bili_asr/search_index.py` depends only on Python standard libraries (`sqlite3`, `json`, `os`, `dataclasses`, `typing`) and local formatting helpers (`bili_asr.archive.archive_stem`, `bili_asr.manifest.ManifestStore`). It contains zero imports from `bili_client`, `requests`, `httpx`, or socket-opening modules.
  - `src/bili_asr/export.py` depends only on standard libraries (`csv`, `io`, `json`, `os`, `typing`) and internal helpers (`bili_asr.manifest.ManifestStore`, `bili_asr.search_index.extract_transcript_text`).
  - `src/bili_asr/cli.py` composes `ManifestStore.load()` to feed both `SearchIndex` and `export_manifest`.
- **Maintainability Evaluation**: Excellent. High cohesion, low coupling, and zero architectural leakage into external networking or upstream API concerns.

### 2.2 Manifest as Single Source of Truth (SSOT)

- **Inspection Target**: `SearchIndex.build()`, `SearchIndex.search()`, `export_manifest()`, `export_rows()`.
- **Finding**:
  - `SearchIndex` only reads from `ManifestStore.load()`.
  - `export.py` reads from `ManifestStore.load()`.
  - No code path calls `store.upsert()`, `store.save()`, or writes to `manifest/manifest.jsonl`.
  - Verified by dedicated regression tests (`test_manifest_remains_unmodified_during_build_and_search` in `tests/test_search_index.py` and `test_export_manifest_immutability` in `tests/test_export.py`).
- **Maintainability Evaluation**: Zero risk of ledger corruption or state desynchronization.

### 2.3 Locked Interfaces & Schema Conformance

- **Inspection Target**: `src/bili_asr/search_index.py:719-722`, `src/bili_asr/export.py:14-30`, `src/bili_asr/cli.py:59-106`.
- **Finding**:
  - `SearchIndex` instantiates SQLite FTS5 table `transcripts_fts` over exactly the 6 locked columns:
    ```sql
    CREATE VIRTUAL TABLE transcripts_fts USING fts5(
        work_id, title, status, transcript_text, archive_paths, duration_s
    );
    ```
  - Indexing condition (`_is_indexable`): Filters strictly to completed transcript statuses `COMPLETED_STATUSES = frozenset({"archived", "subtitle_done"})` where transcript/archive files (`txt_path`, `srt_path`, `md_path`, `raw_path`) are present in manifest metadata or on disk. Non-completed records (`audio_ok`, `needs_audio`, `meta_ok`, `pending`, `gone`) and records missing transcript bodies are strictly excluded.
  - `bili-asr search <query>`: Implements `--limit`, `--rebuild`, `--archive-root`. Exits with code `1` on zero matching results with clear stderr notice; exits `0` and outputs ranked matches with score and primary path when hits exist.
  - `bili-asr export`: Implements `--format {json,csv}`, `--out <path>`, `--status <status>` (repeatable / comma-delimited), `--with-text`, and `--archive-root`.
  - Naming discipline: Manifest `status` is consistently used throughout schemas, dataclasses, CLI arguments, and error outputs (no `state` confusion).

### 2.4 Read-Model Cleanliness, Stale Detection & Idempotency

- **Inspection Target**: `SearchIndex.is_stale()`, `SearchIndex.build()`, `SearchIndex.search()`.
- **Finding**:
  - Stale check (`is_stale`) robustly evaluates three orthogonal conditions:
    1. Database file `{archive_root}/search.db` missing.
    2. Manifest mtime (`manifest/manifest.jsonl`) greater than database mtime (`search.db`).
    3. Index count mismatch: `completed_count != indexed_count`.
  - Atomic rebuild: `build()` builds a fresh database at `search.db.tmp` and replaces `search.db` via `os.replace`, ensuring read queries never encounter partial or corrupt index state.
  - Graceful FTS5 syntax fallback: `search()` catches SQLite syntax errors on raw user input (e.g., bare colons, unclosed quotes) and retries as an escaped exact phrase match (`"..."`), preventing unhandled crashes.
  - Clean text extraction: `extract_transcript_text()` handles TXT files, SRT files (stripping timecodes and line sequence counters), and raw subtitle/ASR JSON documents.

### 2.5 Security, Sanitization & Scope Discipline

- **Inspection Target**: `src/bili_asr/export.py:32-46, 49-78`.
- **Finding**:
  - `SENSITIVE_EXPORT_KEYS` denies `sessdata`, `cookie`, `cookies`, `bili_sessdata`, `url`, `signed_url`, `stream_url`, `audio_url`, `traceback`, `exception`, `error_trace`.
  - By default, `transcript_text` is omitted from exported rows; it is included only when `--with-text` is explicitly supplied.
  - No new third-party dependencies introduced (uses stdlib `sqlite3`, `csv`, `json`).
  - No scope creep (Meilisearch, web UIs, or external database servers avoided).

### 2.6 Documentation Accuracy (`README.md`)

- **Inspection Target**: `bilibili-asr-archive/README.md:9-11, 23-47`.
- **Finding**:
  - README clearly documents `search` and `export` command syntax, example invocations, SSOT boundaries, BM25 ranking, stale detection, rebuild mechanics, and output sanitization.

---

## 3. Findings by Severity

### Critical (Must fix before merge)
*None.*

### Important (Should fix before release)
*None.*

### Warning (Potential risk or friction)
*None.*

### Suggestion / Nit
- **Observation (Non-blocking)**: In `src/bili_asr/cli.py` lines 132-134 and 190-192, unexpected exceptions during `search` and `export` catch `Exception` and print generic error messages to stderr. This adheres well to the CLI requirement of avoiding raw stack trace leaks to users.

---

## 4. Unreviewed Scope & Boundaries

- **Static Diff Only**: As per QC specialist L3 constraints, test suites were not run in this review session; verification relies on static inspection of the branch diff and review package artifacts.
- **Runtime Environment Verification**: Verification of runtime test executions belongs to implementer reports (`task-1-report.md`, `task-2-report.md`) and QA evaluation.

---

## 5. Final Verdict

**Verdict**: **Approve**

The branch diff demonstrates high code quality, excellent module layering, strict manifest SSOT compliance, and zero maintainability risk.
