# QC Specialist Review (L3): Security and Correctness Risk

- **Plan ID**: `20260825-operational-ledger`
- **Reviewer**: `qc-specialist-2` (reviewer_index 2)
- **Task Category**: review
- **Focus Lens**: **Security and correctness risk**
- **Review cwd / Worktree Path**: `/root/workspace/bilibili-asr-archive/.worktrees/20260825-operational-ledger`
- **Working Branch**: `plan/20260825-operational-ledger`
- **Review Range / Diff Basis**: `79652889e7e7b7a6c8419a4bf30badf6f73ee757..cffe0f1de6ecc8a9d75060ebebb6db0b3a9fb2ce`
- **Diff File**: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260825-operational-ledger/review/branch-review.diff`

---

## Verdict

**Approve**

The branch diff cleanly satisfies all security and correctness constraints for the operational run ledger and operator inspection surfaces. Record validation is comprehensive, crash-safety guarantees are sound, exit-code propagation is non-interfering, and credential/traceback redaction mechanisms leave no observable bypass paths.

---

## Findings by Severity

### Critical
None.

### Important
None.

### Warning
None.

### Suggestion
- **File**: `bilibili-asr-archive/src/bili_asr/run_ledger.py:350`
  - **Context**: In `RunLedger.append()`, the full content of `run-ledger.jsonl` is re-read and rewritten via temporary file replacement (`.tmp` + `os.replace`).
  - **Impact**: Provides strong crash safety and eliminates partial-line corruption on crash. For very large ledgers (thousands of runs), this is $O(N)$ write overhead per run.
  - **Suggestion**: For future scale, if the ledger grows significantly, consider a standard file-append with direct atomic line writes and explicit trailing newline recovery, or keep the existing atomic replace pattern given that operator runs typically number in the hundreds.

### Nit
- **File**: `bilibili-asr-archive/src/bili_asr/run_ledger.py:748-753`
  - **Context**: In `RunLedger.load()`, `raw = json.loads(line)` is followed by `if isinstance(raw, dict): records.append(_validate_record(raw))`.
  - **Impact**: If a line contains valid JSON that is not a dictionary (e.g. `[1, 2, 3]` or `"string"`), it silently skips without raising a `ValueError` or printing the stderr warning `"run-ledger: ignoring corrupt line"`.
  - **Suggestion**: Consider passing `raw` directly to `_validate_record(raw)` (which already checks `isinstance(record, dict)` and raises `ValueError("run record must be a dict")`), ensuring consistent stderr warnings for all non-record lines.

---

## Detailed Evaluation Matrix (Lens: Security & Correctness)

| Dimension | Review Evaluation | Status |
|-----------|-------------------|:------:|
| **Credential & Trace Redaction** | `_validate_record` dumps the entire serialized record to lower-case JSON and scans against `_FORBIDDEN_MARKERS` (`SESSDATA`, `cookie`, `Cookie`, `http://`, `https://`, `Traceback`). `last_api_error_code` enforces length $\le 64$ to prevent raw exception string leakage. CLI catch blocks sanitize exceptions to scalar error codes or class names. | **PASS** |
| **Record Validation & Types** | `_validate_record` and `_validate_cursor_snapshot` enforce the locked 13-field schema. Explicit `not isinstance(v, bool)` checks prevent Python boolean-as-int loopholes across all integer fields (`exit_code`, `mid`, `pages_fetched`, `records_fetched`, `records_existing`, `next_page`, `total`). | **PASS** |
| **Cursor Invariants** | `_validate_cursor_snapshot` explicitly checks `state in VALID_STATES` and rejects `state == "running"`. Mid-run cursor writes keep `state="risk_interrupted"` until clean completion writes `complete` or `limited`. | **PASS** |
| **Atomic Append Crash-Safety** | `RunLedger.append()` reads existing bytes, writes to `{path}.tmp`, ensures trailing newline, performs `flush()` and `os.fsync()`, and completes with atomic `os.replace()`. Prevents truncated or partial lines on sudden crash. | **PASS** |
| **Exit-Code Wiring** | `fetch-meta` records runs on exit 0 and exit 2; `pilot` records runs across all exit codes (0, 1, 2). All ledger operations in `_record_exit` are guarded in `try ... except Exception: pass` to ensure telemetry failures never alter command return codes. | **PASS** |
| **Edge Cases & Error Handling** | Corrupt JSONL lines are safely skipped with diagnostic stderr warnings. Empty ledgers produce standard empty outputs (`runs: 0` for `status`, `runs: empty` for `runs`). `format_cursor_summary` uses `observed_total` for `limited` cursor state to prevent claiming full enumeration. | **PASS** |
| **Coverage Summary Derivation** | `compute_coverage_summary()` counts manifest statuses restricted strictly to `VALID_STATUSES`, sorts output keys deterministically, and handles empty archives safely. | **PASS** |
| **Architectural Boundaries** | `bili_client.py` retains sole HTTP transport ownership and does not import `run_ledger`. Manifest row schema remains untouched (last-write-wins JSONL sidecar). | **PASS** |

---

## Revalidation

- **Verdict**: **Approve**
- **Review Range**: `79652889e7e7b7a6c8419a4bf30badf6f73ee757..cffe0f1de6ecc8a9d75060ebebb6db0b3a9fb2ce`
- **Fix Verification**:
  - ✅ **Nit Resolved**: `RunLedger.load()` now directly invokes `_validate_record(raw)` on parsed JSON objects. Non-dict JSON records (e.g. lists, strings, numbers) trigger `ValueError("run record must be a dict")` and are routed to the `except (json.JSONDecodeError, ValueError):` branch, printing `"run-ledger: ignoring corrupt line"` to stderr consistently with other malformed lines.
  - ✅ **Surgical Implementation**: Fix in commit `cffe0f1` is minimal and surgical (2 lines changed in `src/bili_asr/run_ledger.py`). It does not loosen any validation rules or introduce regression vectors.
  - ✅ **Test Verification**: `test_corrupt_lines_ignored` in `tests/test_run_ledger.py` explicitly tests both list `[1, 2, 3]` and string `"standalone string"` corrupt lines, asserting exact stderr count matching.
- **New Findings**: None.

---

## Scope & Unreviewed Notice

- **Reviewed**: Static diff `79652889e7e7b7a6c8419a4bf30badf6f73ee757..cffe0f1de6ecc8a9d75060ebebb6db0b3a9fb2ce`, `bili_asr/run_ledger.py`, `bili_asr/cli.py`, `bili_asr/meta_cursor.py`, `bili_asr/manifest.py`, `README.md`, and test suites `tests/test_run_ledger.py` and `tests/test_cli_help.py`.
- **Unreviewed**: Runtime execution of test suites (per QC static review policy, runtime test execution is owned by implementer evidence and QA engineering).
