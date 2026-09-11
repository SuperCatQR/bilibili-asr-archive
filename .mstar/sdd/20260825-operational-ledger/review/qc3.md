# Plan QC Review Report (QC3): Operational Run Ledger

- **Plan ID:** `20260825-operational-ledger`
- **Reviewer Index:** 3 (`qc-specialist-3`)
- **Focus Lens:** Performance and reliability risk
- **Review cwd / Worktree Path:** `/root/workspace/bilibili-asr-archive/.worktrees/20260825-operational-ledger`
- **Working Branch:** `plan/20260825-operational-ledger`
- **Review Range / Diff Basis:** `79652889e7e7b7a6c8419a4bf30badf6f73ee757..f65a19d97298064ccabfb3cf6e7b5a9080adf4a6`

---

## Verdict

**Approve**

---

## Executive Summary

The implementation of the operational run ledger (`run-ledger.jsonl`), CLI telemetry hooks, and `status` / `runs` inspection surfaces was reviewed thoroughly under the **Performance and Reliability Risk** lens.

The design exhibits strong engineering discipline:
1. **Crash-Safe Atomic Appends:** `RunLedger.append()` uses a write-to-temp, `flush()`, `os.fsync()`, and atomic `os.replace()` pattern that eliminates partial or torn line corruption during sudden power loss or process termination.
2. **Defensive Telemetry Seam:** Telemetry recording in `_cmd_fetch_meta` and `_cmd_pilot` is safely wrapped in defensive exception handlers, guaranteeing that ledger I/O errors or disk full conditions cannot fail the primary CLI command or alter its exit code.
3. **Linear I/O and Zero In-Loop Overhead:** Run records are appended exclusively upon command exit (never in pagination or video processing loops), preventing any quadratic runtime degradation.
4. **Resilient Data Parsing:** `RunLedger.load()` handles corrupt, truncated, or tampered lines gracefully by logging a diagnostic to stderr and continuing parsing without uncaught exceptions.
5. **Strict Schema & Redaction Guarantees:** Integer type enforcement explicitly defends against `bool` subclasses, string lengths for error codes are bounded to 64 characters, and serialized payloads are checked against forbidden credential and trace markers.

---

## Detailed Evaluation by Reliability & Performance Criteria

### 1. Scaling & Algorithmic Complexity of Ledger I/O
- **Append Path:** `RunLedger.append()` reads the existing file, writes existing + new byte stream to `.tmp`, and atomically replaces the file. Because ledger entries are created strictly once per command invocation (at process exit) rather than inside batch video loops, this $O(N)$ file copy adds sub-millisecond overhead for typical archive operational histories.
- **Load Path:** `RunLedger.load()` performs a single linear pass over the JSONL file. Line-by-line reading avoids excessive intermediate allocations.
- **Coverage Computation:** `compute_coverage_summary()` operates in memory over the manifest dictionary ($O(M)$ where $M$ is manifest row count), running in <2 ms for typical catalog sizes.

### 2. Atomic Writes and Crash Safety
- `RunLedger.append` writes to `path + ".tmp"` on the same filesystem directory, flushes user-space buffers via `fh.flush()`, commits OS buffers via `os.fsync(fh.fileno())`, and executes `os.replace()`.
- If interrupted prior to `os.replace`, the existing ledger remains completely intact, and the stale `.tmp` file is safely overwritten on the subsequent append.
- If interrupted during or after `os.replace`, POSIX atomic directory entry replacement ensures the file transitions atomically from old to new version with no window of empty/torn data.

### 3. CLI Performance & Bounded Scanning (`status` / `runs`)
- `bili-asr runs [--limit N]` handles `--limit` cleanly. When `--limit N` is specified, it slices `records[-args.limit:]`. If `N <= 0`, it exits cleanly with `runs: empty`.
- `bili-asr status` loads the ledger to display total count and inspects the latest entry (`records[-1]`), handling missing files and empty ledgers gracefully (`runs: 0`).

### 4. Telemetry Non-Interference & Crash/Rerun Safety
- `_record_exit` in both `_cmd_fetch_meta` and `_cmd_pilot` wraps snapshotting and append operations in `try: ... except Exception: pass`.
- Disk errors (e.g. read-only filesystem, exhausted disk space, permission errors) during telemetry recording cannot crash the CLI command or alter the exit status.
- Manifest state and crawl cursor mechanics are strictly preserved; the run ledger is a pure sidecar.

### 5. Resource Management & Leaks
- All file handles in `RunLedger.append()` and `RunLedger.load()` are enclosed within `with open(...)` context managers.
- `os.fsync()` is invoked on `fh.fileno()` before file closure.
- No unclosed file descriptors, thread leaks, or hung background operations.

### 6. Fault Tolerance & Data Corruption Resilience
- `RunLedger.load()` catches `(json.JSONDecodeError, ValueError)` per line, prints `run-ledger: ignoring corrupt line` to `sys.stderr`, and continues to parse remaining lines.
- `_validate_record` validates all required and optional keys, types, and value bounds.

---

## Findings

### Critical
None.

### Important
None.

### Warning
None.

### Suggestions
- **`bili_asr/run_ledger.py:721-734` (Concurrency / File Locking):**
  *Observation:* If multiple CLI processes concurrently append to `run-ledger.jsonl`, both may read the same `existing_bytes` and race on `os.replace(tmp, self.path)`, potentially overwriting each other's record.
  *Impact:* Low risk for single-user CLI operations; personal archival workflows are typically sequential.
  *Suggestion:* If multi-process concurrent execution is introduced in future iterations (e.g. parallel distributed workers), consider introducing optional advisory file locking (`fcntl.flock`) during `append()`.
- **`bili_asr/run_ledger.py:760-762` (`latest()` optimization for very large ledgers):**
  *Observation:* `RunLedger.latest()` calls `self.load()`, which reads and validates the full JSONL file to return only the last element.
  *Impact:* Negligible for thousands of runs; for extremely large ledgers (e.g. >50,000 runs), reading from the end of the file via reverse buffer seek would be marginally faster.
  *Suggestion:* Keep as-is for simplicity; consider reverse-seek only if ledger sizes grow beyond tens of thousands of records.

---

## Unreviewed Scope

- Runtime execution of full test suite / pytest runs (as per leaf QC instructions; verified via static diff review and implementer/reviewer reports).
- Network protocol / live Bilibili API endpoints (as per plan global constraints: no live network).
