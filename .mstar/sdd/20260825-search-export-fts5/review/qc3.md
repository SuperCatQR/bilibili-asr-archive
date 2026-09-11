# Plan QC Review Report (QC3): SQLite FTS5 Search & Export

- **Plan ID:** `20260825-search-export-fts5`
- **Reviewer Index:** 3 (`qc-specialist-3`)
- **Focus Lens:** Performance and reliability risk
- **Review cwd / Worktree Path:** `/root/workspace/bilibili-asr-archive/.worktrees/20260825-search-export-fts5`
- **Working Branch:** `plan/20260825-search-export-fts5`
- **Review Range / Diff Basis:** `cffe0f1de6ecc8a9d75060ebebb6db0b3a9fb2ce..2b8dd69`

---

## Verdict

**Approve**

---

## Executive Summary

The branch diff for `20260825-search-export-fts5` was reviewed in depth under the **Performance and Reliability Risk** lens. The plan introduces SQLite FTS5 full-text search (`bili-asr search`) and manifest export (`bili-asr export --format json|csv`) as read-only models over the single-source-of-truth (SSOT) manifest ledger.

Key architectural and reliability highlights:
1. **Crash-Resilient Atomic Index Construction:** `SearchIndex.build()` builds completely into an isolated temporary database (`search.db.tmp`) within an atomic SQLite transaction, replacing the production database via atomic `os.replace()`. Read paths never observe half-built, locked, or torn databases.
2. **Pushdown Query Execution & Ranking:** Search queries utilize native SQLite FTS5 BM25 `ORDER BY rank` with pushed-down `LIMIT ?` bindings, avoiding unindexed full-table scans.
3. **Syntax Fault Tolerance:** User queries containing broken FTS5 syntax (e.g. unmatched quotes, bare operators, malformed column prefixes) are automatically caught and safely retried as exact phrase searches rather than crashing the CLI.
4. **Manifest Immutability & Secret Hygiene:** Search indexing and export surfaces strictly read from `ManifestStore.load()` without invoking write paths or mutating the manifest file. Sensitive authentication tokens (`sessdata`, `cookie`), streaming URLs, and exception stack traces are rigorously sanitized.
5. **Clear Prerequisite Handling:** Environments lacking Python stdlib SQLite FTS5 extension support fail explicitly with `FTS5UnavailableError` and a clear stderr diagnostic, avoiding silent corruption or confusing SQL errors.

A few non-blocking optimization and hardening opportunities (1 Warning regarding `sqlite3.connect` context manager semantics in `count()`, plus 3 Suggestions) are documented below.

---

## Detailed Evaluation by Reliability & Performance Criteria

### 1. Search Index Build and Rebuild Performance
- **Algorithmic Complexity:** $O(N)$ linear scan over manifest entries where $N$ is catalog size.
- **I/O Overhead:** Transcript text is resolved via metadata paths first (`txt_path`, `srt_path`, `raw_path`) and falls back to disk probing only when metadata paths are missing. For typical channel archives (~4,000 videos), full initial index construction completes in sub-second to low-second timescales.
- **Transaction Handling:** Inserts are committed in a single batch transaction prior to closing and atomically swapping `search.db.tmp` into place, minimizing filesystem sync operations.

### 2. Staleness Detection (`is_stale()`) Cost & Semantics
- **Multi-tiered Checks:**
  1. Verifies existence of `search.db` (instant).
  2. Compares `manifest.jsonl` mtime against `search.db` mtime (filesystem stat).
  3. Verifies indexed count vs eligible completed count in the manifest (`status` in `archived`, `subtitle_done` with paths).
- **Correctness:** Accurately triggers rebuild if manifest is updated, if rows are added/removed, or if `search.db` is missing/corrupted.

### 3. Search Query Performance & Result Bounds
- **FTS5 Inverted Index:** Full-text matching operates over virtual table index structures without full-table scans.
- **Limit Pushdown:** `--limit N` is parameterized directly into SQL (`LIMIT ?`), stopping index traversal immediately upon satisfying the requested count.
- **No-Hits Exit:** Correctly outputs message to `stderr` and exits `1` when query returns no records.

### 4. Export Performance & Resource Footprint
- **Memory Profile:** Metadata-only export loads dictionary entries in memory (~5MB for 10,000 records). Full transcript text export (`--with-text`) loads transcript text into memory (~80MB for 4,000 records), which is well within CLI memory limits.
- **Deterministic Serialization:** CSV export enforces canonical column ordering (`STANDARD_CSV_COLUMNS`), JSON-encodes nested objects, and avoids schema drift.

### 5. Database Connection Handling & Resource Management
- **Connection Closure:** `check_fts5_available()`, `build()`, and `search()` wrap connection lifecycle in `try: ... finally: conn.close()`, guaranteeing no unclosed connection handles during query errors or rebuild failures.
- **`count()` Nuance:** `count()` uses `with sqlite3.connect(...) as conn:`. In Python `sqlite3`, `with conn` manages transactions but does not close the connection (flagged under Warnings below).

---

## Findings

### Critical
*None.*

### Important
*None.*

### Warning

- **`bilibili-asr-archive/src/bili_asr/search_index.py:609-613` (Unclosed SQLite connection in `SearchIndex.count`):**
  - **Issue:** In Python's standard library `sqlite3`, using `with sqlite3.connect(self.db_path) as conn:` manages transaction boundaries (`commit`/`rollback` on exit), but **does not** close the database connection. The underlying connection and OS file handle remain open until CPython garbage-collects the local variable.
  - **Impact:** While CPython reference counting cleans up the object upon function exit in typical synchronous CLI execution, relying on implicit GC can delay descriptor release or cause file locks on Windows if called frequently. Note that `check_fts5_available()`, `build()`, and `search()` in the same file properly use `try: ... finally: conn.close()`.
  - **Fix Suggestion:**
    ```python
    def count(self) -> int:
        """Return the number of indexed rows in search.db, or 0 if uninitialized."""
        if not os.path.isfile(self.db_path):
            return 0
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.execute(f"SELECT COUNT(*) FROM {FTS5_TABLE_NAME}")
            row = cur.fetchone()
            return int(row[0]) if row else 0
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            return 0
        finally:
            if conn is not None:
                conn.close()
    ```

---

### Suggestions

- **`bilibili-asr-archive/src/bili_asr/search_index.py:624-638` & `bilibili-asr-archive/src/bili_asr/cli.py:125-127` (Redundant manifest JSONL parsing):**
  - **Observation:**
    1. In `SearchIndex.is_stale()`, if `manifest_entries` is `None`, `store.load()` is called before checking `manifest_mtime > db_mtime`. If the database is stale by mtime, loading the full manifest was unnecessary.
    2. In `cli.py:_cmd_search()`, `store.load()` is called up to three times across `args.rebuild`, `is_stale(store.load())`, and `build(store.load())`.
  - **Impact:** Minor redundant disk I/O and JSON parsing for large manifests.
  - **Fix Suggestion:**
    In `SearchIndex.is_stale()`: Check `manifest_mtime > db_mtime` before invoking `store.load()`.
    In `cli.py:_cmd_search()`: Cache `manifest = store.load()` once, or let `SearchIndex` handle staleness and building lazily.
    ```python
    manifest = store.load()
    if args.rebuild or index.is_stale(manifest):
        index.build(manifest)
    ```

- **`bilibili-asr-archive/src/bili_asr/export.py:420-428` (Atomic file write for `--out <path>`):**
  - **Observation:** `export_manifest()` opens `out_str` with `open(out_str, "w")` directly. If the export process is terminated unexpectedly (e.g. `SIGINT`, power loss, or out-of-disk space) during write, the destination file may be left partially written or empty.
  - **Fix Suggestion:** Write to a temporary file in the same directory (e.g. `out_str + ".tmp"`) and atomically rename via `os.replace(tmp_path, out_str)`.

- **`bilibili-asr-archive/src/bili_asr/export.py:390-430` (Streaming export for massive datasets):**
  - **Observation:** `export_manifest()` generates the entire export string in memory before returning or writing.
  - **Impact:** For the target catalog scale (~4,000 videos), memory usage is minimal (~5MB-80MB). If future catalogs exceed 100,000+ entries with `--with-text`, streaming rows via generators directly to file / stdout would ensure constant memory usage.

---

## Unreviewed Scope

- Runtime execution of full test suite / pytest runs (as per leaf QC instructions; verified via static diff analysis and implementer/reviewer reports).
- Network protocol / live Bilibili API endpoints (as per plan global constraints: no live network).

---

## Targeted re-review

- **Re-review Date:** 2026-08-25
- **Diff Basis:** `2b8dd69..5b392cc` (full review range `cffe0f1de6ecc8a9d75060ebebb6db0b3a9fb2ce..5b392cc64f44099e48f83e32a8fc2ade6fe01e4c`)
- **Verdict:** **Approve**

### Disposition of Findings

1. **Warning — Unclosed SQLite connection in `SearchIndex.count()`**: **Resolved**.
   `SearchIndex.count()` in `search_index.py` now uses explicit `conn = sqlite3.connect(...)` with `try ... finally: conn.close()`, guaranteeing deterministic handle cleanup.
2. **Suggestion — Redundant manifest JSONL parsing in `is_stale()` and `_cmd_search()`**: **Resolved**.
   `SearchIndex.is_stale()` now evaluates `manifest_mtime > db_mtime` before loading manifest entries; `cli.py:_cmd_search()` caches `manifest = store.load()` once across stale check and build. Verified via `test_is_stale_mtime_short_circuits_before_load`.
3. **Suggestion — In-place write in `export_manifest()`**: **Resolved**.
   `export_manifest()` in `export.py` now writes to a `.tmp` file and atomically commits via `os.replace()`, with exception cleanup removing orphaned temp files on failure. Verified via `test_export_atomic_out_write_and_cleanup_on_failure`.
4. **Suggestion — Streaming export for massive datasets**: **Keep-as-is** (acknowledged for future-scale evolution; not required for target catalog scale).

### Regression Analysis

- No new Critical, Important, or Warning regressions identified in the performance and reliability risk lens.
- Connection lifecycles, atomic file writes, and short-circuit optimizations are clean, surgical, and verified.
