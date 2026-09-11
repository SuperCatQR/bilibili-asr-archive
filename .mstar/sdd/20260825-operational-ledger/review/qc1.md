# Plan QC Review Report (QC1): Operational Run Ledger

- **Plan ID:** `20260825-operational-ledger`
- **Reviewer Index:** 1 (`qc-specialist`)
- **Focus Lens:** Architecture coherence and maintainability risk
- **Review cwd / Worktree Path:** `/root/workspace/bilibili-asr-archive/.worktrees/20260825-operational-ledger`
- **Working Branch:** `plan/20260825-operational-ledger`
- **Review Range / Diff Basis:** `79652889e7e7b7a6c8419a4bf30badf6f73ee757..f65a19d97298064ccabfb3cf6e7b5a9080adf4a6`
- **Diff File:** `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260825-operational-ledger/review/branch-review.diff`

---

## Verdict

**Approve**

The branch implementation exhibits clean architectural coherence and low maintainability risk. Module boundaries are strictly respected, manifest row schema and last-write-wins semantics remain untouched, locked interfaces and state distinctness are fully honored, formatters are modularly decoupled, and operator-visible surfaces are accurately documented and tested.

---

## Findings by Severity

### Critical
None.

### Important
None.

### Warning
None.

### Suggestion
- **File**: `bilibili-asr-archive/src/bili_asr/run_ledger.py:399-405, 623-625`
  - **Context**: `VALID_COMMANDS = frozenset({"fetch-meta", "pilot", "run"})` is defined as a module constant, while `_validate_record()` validates `command` as `isinstance(command, str) and command` without asserting membership in `VALID_COMMANDS`.
  - **Impact**: Provides deliberate forward-compatibility for upcoming pipeline coordinator commands (e.g. Plan E `run`) without requiring schema validator adjustments.
  - **Suggestion**: Document in the docstring that `VALID_COMMANDS` represents the recognized core commands and `_validate_record` intentionally allows future subcommands to append records safely.

- **File**: `bilibili-asr-archive/src/bili_asr/run_ledger.py:716-735`
  - **Context**: `RunLedger.append()` reads existing bytes, writes existing + new record line to a `.tmp` file, executes `flush()` + `os.fsync()`, and completes with atomic `os.replace()`.
  - **Impact**: Guarantees crash-safety and eliminates partial or torn line corruption across CLI interruptions. The $O(N)$ write overhead is negligible for normal operational histories (hundreds of runs).
  - **Suggestion**: If long-term usage scales to tens of thousands of runs in high-frequency batch environments, consider evaluating append mode with advisory locking (`fcntl.flock`). For current single-user CLI operations, the atomic replace pattern is optimal.

### Nit
- **File**: `bilibili-asr-archive/src/bili_asr/run_ledger.py:748-753`
  - **Context**: In `RunLedger.load()`, `raw = json.loads(line)` is guarded by `if isinstance(raw, dict): records.append(_validate_record(raw))`.
  - **Impact**: If a line contains valid non-dict JSON (e.g., `"test"` or `[1, 2]`), it is silently skipped without logging the `"run-ledger: ignoring corrupt line"` diagnostic to stderr.
  - **Suggestion**: Pass `raw` directly to `_validate_record(raw)` (which already validates `isinstance(record, dict)` and raises `ValueError`), ensuring consistent stderr warnings for all invalid JSONL lines.

---

## Detailed Evaluation Matrix (Lens: Architecture Coherence & Maintainability)

| Dimension | Review Evaluation | Status |
|-----------|-------------------|:------:|
| **Module Layering & Seam Ownership** | `bili_client.py` retains exclusive HTTP ownership and does not import `run_ledger`. `run_ledger.py` contains filesystem sidecar logic only (zero HTTP, zero third-party dependencies). `run_ledger` is imported exclusively by `cli.py` and test modules. | **PASS** |
| **Sidecar Isolation & Schema Preservation** | Manifest JSONL row schema and last-write-wins semantics remain completely untouched. `run-ledger.jsonl` operates purely as an append-only sidecar. | **PASS** |
| **Locked Interfaces & Naming** | The 13 locked record fields (`run_id`, `command`, `started_at`, `finished_at`, `exit_code`, `mid`, `work_ids`, `pages_fetched`, `records_fetched`, `records_existing`, `last_api_error_code`, `coverage_summary`, `cursor_snapshot`) are strictly adhered to. | **PASS** |
| **State vs Status Distinctness** | Cursor crawl progress (`state` ∈ `{"complete", "limited", "risk_interrupted"}`) and manifest row state (`status` ∈ `VALID_STATUSES`) remain cleanly separated. `coverage_summary` is named explicitly and maps only manifest `status` counts. | **PASS** |
| **Honest Operator Reporting** | `format_cursor_summary()` renders `limited` cursors as `limited (next_page N, observed_total M)`, preventing misleading claims of full enumeration. | **PASS** |
| **Security & Redaction Boundaries** | `_validate_record()` inspects the full serialized record payload for forbidden credential, URL, and traceback markers (`_FORBIDDEN_MARKERS`). Error code scalar strings are bounded to 64 chars. | **PASS** |
| **Formatting & CLI Cohesion** | Presentation formatters (`format_cursor_summary`, `format_coverage_summary`, `format_run_summary`) are factored cleanly into `run_ledger.py`, allowing unified reuse across `status`, `runs`, and test fixtures. | **PASS** |
| **Documentation Accuracy** | `README.md` accurately documents the 13-field ledger schema, redaction guarantees, and operator inspection workflows for `bili-asr status` and `bili-asr runs`. | **PASS** |
| **Code Hygiene & Forward Compatibility** | No dead code, no circular imports, clear type annotations, and robust defensive handling (`try ... except Exception: pass` around CLI telemetry appends). | **PASS** |

---

## Scope & Unreviewed Notice

- **Reviewed**:
  - Branch diff `79652889e7e7b7a6c8419a4bf30badf6f73ee757..f65a19d97298064ccabfb3cf6e7b5a9080adf4a6` (`.mstar/sdd/20260825-operational-ledger/review/branch-review.diff`).
  - Source modules: `bili_asr/run_ledger.py`, `bili_asr/cli.py`, `bili_asr/manifest.py`, `bili_asr/meta_cursor.py`, and `README.md`.
  - Test suites: `tests/test_run_ledger.py` and `tests/test_cli_help.py`.
- **Unreviewed**:
  - Runtime execution of test suites (static diff review only; runtime execution verified via implementer and L2 review reports).

---

## Revalidation

- **Review Range / Diff Basis:** `79652889e7e7b7a6c8419a4bf30badf6f73ee757..cffe0f1de6ecc8a9d75060ebebb6db0b3a9fb2ce`
- **Fix Commit:** `cffe0f1de6ecc8a9d75060ebebb6db0b3a9fb2ce` (`fix(ledger): diagnose non-dict JSON lines in load and document VALID_COMMANDS`)
- **Fix Diff:** `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260825-operational-ledger/review/qc-fix.diff`

### Verdict
**Approve**

### Findings Resolution Status

1. **(Suggestion) `VALID_COMMANDS` forward-compat docstring** — ✅ **Resolved**
   - Added descriptive docstring comment above `VALID_COMMANDS` explaining that it defines recognized core commands for reference and documentation, while `_validate_record()` intentionally accepts any non-empty command string to support future pipeline coordinator subcommands without breaking validation.
2. **(Nit) `RunLedger.load()` silent skip of non-dict JSON lines** — ✅ **Resolved**
   - Removed conditional `if isinstance(raw, dict):` guard in `RunLedger.load()` and routed `raw` directly through `_validate_record(raw)`. Non-dict valid JSON records (such as lists or primitives) now properly raise `ValueError("run record must be a dict")` and consistently output `"run-ledger: ignoring corrupt line"` to stderr.
   - Verified that `tests/test_run_ledger.py` (`test_corrupt_lines_ignored`) was updated to test both non-dict JSON arrays and string literals, asserting exact counts of stderr diagnostic warnings.

### New Findings
None. The fix is surgical, robust, and introduces no maintainability or architectural regressions.
