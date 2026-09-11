# QA Report — Operational Run Ledger

- **Role**: `qa-engineer` (L4 acceptance gate)
- **plan_id**: `20260825-operational-ledger`
- **QA mode**: acceptance-only (evidence reuse first; verification executed)
- **Review cwd / Worktree path**: `/root/workspace/bilibili-asr-archive/.worktrees/20260825-operational-ledger`
- **Working branch**: `plan/20260825-operational-ledger`
- **Review range / Diff basis**: `79652889e7e7b7a6c8419a4bf30badf6f73ee757..cffe0f1de6ecc8a9d75060ebebb6db0b3a9fb2ce`
- **HEAD verified**: `cffe0f1de6ecc8a9d75060ebebb6db0b3a9fb2ce` (`fix(ledger): diagnose non-dict JSON lines in load and document VALID_COMMANDS`)
- **Findings cleanup**: zero-residual
- **QC input**: `review/qc-consolidated.md` verdict **Approve** (QC1, QC2, QC3 all Approved)

---

## Verdict

**Pass / Recommend Done**

All 5 Acceptance Criteria are fully satisfied with verifiable evidence. Tri-review QC approved the architecture, security/correctness, and performance/reliability aspects with 0 open findings. Test suites (28 focused run-ledger tests and 218 full regression tests) pass with 100% success and 0 failures under Python 3.12 without live HTTP dependencies.

---

## Validation: Acceptance Criteria to Evidence Mapping

| Acceptance Criterion | Status | Evidence Source & Verification |
|---|---|---|
| **AC1: Every `fetch-meta` run (exit 0 or 2) and every `pilot` run leaves an inspectable record (run_id, command, timestamps, exit_code, cursor snapshot, last_api_error_code, per-status coverage); crash leaves no partial record.** | ✅ PASS | **Reused L1/L2 & Newly Verified**: `RunLedger.append()` implements atomic `.tmp` + `flush` + `fsync` + `os.replace` guaranteeing crash-safe line records. `_cmd_fetch_meta` logs on exit 0 and 2; `_cmd_pilot` logs on exit 0, 1, and 2. Enforced schema fields validated via `_validate_record`. Tested via `test_cli_fetch_meta_exit_0_appends_ledger`, `test_cli_fetch_meta_exit_2_risk_appends_ledger`, `test_cli_fetch_meta_exit_2_gone_appends_ledger`, `test_cli_pilot_exit_0_appends_ledger`, `test_cli_pilot_exit_1_empty_manifest_appends_ledger`, `test_cli_pilot_exit_2_risk_appends_ledger`, and `test_ledger_schema_roundtrip`. |
| **AC2: `bili-asr status` and `bili-asr runs` expose coverage without claiming full enumeration for `limited`.** | ✅ PASS | **Reused L1/L2 & Newly Verified**: `format_cursor_summary()` renders `limited (next_page N, observed_total M)` using `observed_total`, never claiming full enumeration. `bili-asr status` and `bili-asr runs [--limit N]` display run records, cursor summaries, and per-status coverage without enumeration overclaims. Tested via `test_format_cursor_summary`, `test_cli_status_limited_cursor_does_not_claim_full_enumeration`, `test_cli_status_empty_archive`, `test_cli_status_with_manifest_and_runs`, `test_cli_runs_empty`, `test_cli_runs_listing_and_limit`, and `test_cli_runs_corrupt_lines_handled`. |
| **AC3: Ledger is a sidecar; JSONL manifest rows unchanged (last-write-wins per `work_id`).** | ✅ PASS | **Reused L1/L2/L3 & Newly Verified**: Manifest storage and schema in `bili_asr/manifest.py` remain completely untouched. Run records are stored in dedicated sidecar `{archive_root}/run-ledger.jsonl`. `bili_client.py` retains exclusive HTTP ownership and does not import `run_ledger`. Verified by `test_bili_client_does_not_import_run_ledger`. |
| **AC4: No credentials/signed URLs/raw exceptions in ledger or operator output.** | ✅ PASS | **Reused L1/L2/L3 & Newly Verified**: `_validate_record()` inspects serialized JSON payload against `_FORBIDDEN_MARKERS` (`SESSDATA`, `cookie`, `Cookie`, `http://`, `https://`, `Traceback`), and caps `last_api_error_code` string lengths to 64 chars to block raw exception leaks. Formatters and CLI handlers maintain strict sanitization. Tested via `test_ledger_forbidden_markers_redaction`, `test_ledger_error_code_max_len`, and `test_cli_status_and_runs_redaction_guarantees`. |
| **AC5: Full Python 3.12 suite passes; no live HTTP.** | ✅ PASS | **Newly Executed**: Ran full pytest suite in worktree: 218 passed in 4.18s. All HTTP interactions strictly mocked or isolated. |

---

## Verification Commands & Outputs

Environment:
- **Cwd**: `/root/workspace/bilibili-asr-archive/.worktrees/20260825-operational-ledger/bilibili-asr-archive`
- **Python**: `/root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python` (Python 3.12.3)

### 1. Focused Verification (28 tests)

```bash
PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest tests/test_run_ledger.py -v
```

Output:
```text
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-9.1.1, pluggy-1.6.0
collected 28 items

tests/test_run_ledger.py::test_ledger_initial_empty PASSED               [  3%]
tests/test_run_ledger.py::test_ledger_schema_roundtrip PASSED            [  7%]
tests/test_run_ledger.py::test_ledger_multiple_appends_chronological PASSED [ 10%]
tests/test_run_ledger.py::test_ledger_validation_required_fields PASSED  [ 14%]
tests/test_run_ledger.py::test_ledger_validation_types PASSED            [ 17%]
tests/test_run_ledger.py::test_ledger_validation_coverage_summary PASSED [ 21%]
tests/test_run_ledger.py::test_ledger_validation_cursor_snapshot PASSED  [ 25%]
tests/test_run_ledger.py::test_ledger_forbidden_markers_redaction PASSED [ 28%]
tests/test_run_ledger.py::test_ledger_error_code_max_len PASSED          [ 32%]
tests/test_run_ledger.py::test_compute_coverage_summary PASSED           [ 35%]
tests/test_run_ledger.py::test_corrupt_lines_ignored PASSED              [ 39%]
tests/test_run_ledger.py::test_bili_client_does_not_import_run_ledger PASSED [ 42%]
tests/test_run_ledger.py::test_cli_fetch_meta_exit_0_appends_ledger PASSED [ 46%]
tests/test_run_ledger.py::test_cli_fetch_meta_exit_2_risk_appends_ledger PASSED [ 50%]
tests/test_run_ledger.py::test_cli_fetch_meta_exit_2_gone_appends_ledger PASSED [ 53%]
tests/test_run_ledger.py::test_cli_pilot_exit_0_appends_ledger PASSED    [ 57%]
tests/test_run_ledger.py::test_cli_pilot_exit_1_empty_manifest_appends_ledger PASSED [ 60%]
tests/test_run_ledger.py::test_cli_pilot_exit_2_risk_appends_ledger PASSED [ 64%]
tests/test_run_ledger.py::test_format_cursor_summary PASSED              [ 67%]
tests/test_run_ledger.py::test_format_coverage_summary PASSED            [ 71%]
tests/test_run_ledger.py::test_format_run_summary PASSED                 [ 75%]
tests/test_run_ledger.py::test_cli_status_empty_archive PASSED           [ 78%]
tests/test_run_ledger.py::test_cli_status_with_manifest_and_runs PASSED  [ 82%]
tests/test_run_ledger.py::test_cli_status_limited_cursor_does_not_claim_full_enumeration PASSED [ 85%]
tests/test_run_ledger.py::test_cli_runs_empty PASSED                     [ 89%]
tests/test_run_ledger.py::test_cli_runs_listing_and_limit PASSED         [ 92%]
tests/test_run_ledger.py::test_cli_runs_corrupt_lines_handled PASSED     [ 96%]
tests/test_run_ledger.py::test_cli_status_and_runs_redaction_guarantees PASSED [100%]

============================== 28 passed in 0.13s ==============================
```

### 2. Full Suite Verification (218 tests)

```bash
PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest -q
```

Output:
```text
........................................................................ [ 33%]
........................................................................ [ 66%]
........................................................................ [ 99%]
..                                                                       [100%]
218 passed in 4.18s
```

---

## Checkout Alignment Confirmation

- **Worktree path**: `/root/workspace/bilibili-asr-archive/.worktrees/20260825-operational-ledger`
- **Branch**: `plan/20260825-operational-ledger`
- **HEAD commit**: `cffe0f1de6ecc8a9d75060ebebb6db0b3a9fb2ce`
- **Commits on branch**:
  - `cffe0f1` `fix(ledger): diagnose non-dict JSON lines in load and document VALID_COMMANDS`
  - `f65a19d` `feat(ledger): add status run summary, runs command, and ledger documentation`
  - `6397e1c` `feat(ledger): implement RunLedger and wire fetch-meta and pilot runs`
  - Base: `7965288`
- **Working tree status**: Clean (`git status -s` produces no output).
- **Checkout alignment**: **Confirmed ✅**

---

## Residuals Check

- **Open residuals**: 0 (no open residuals registered).
- **Residuals check**: **Zero residual ✅**

---

## Gaps / Notes

- None. Implementation, documentation in `README.md`, and test coverage completely satisfy the locked plan specification.
- Ready for plan closure and merge into iteration branch `iteration/iter-2026-08-pilot-ops`.
