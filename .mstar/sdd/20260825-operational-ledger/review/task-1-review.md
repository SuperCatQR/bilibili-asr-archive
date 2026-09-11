# Task 1 L2 review — Persist run records

Range: `79652889e7e7b7a6c8419a4bf30badf6f73ee757..6397e1c055e06c0e09b4aababa778b0ed0048804`
Diff: `.mstar/sdd/20260825-operational-ledger/review/task-1.diff`
Tests: not re-run (PM: 207 passed on `6397e1c`).

### Spec Compliance

- ✅ Spec compliant
- ⚠️ Cannot verify from diff:
  - PM pytest 207 passed on `6397e1c` (Assignment claim; not re-run).
  - Task 2 owns `bili-asr status` and `bili-asr runs` display commands and README documentation.

### Strengths

- **Atomic crash-safe writes**: `RunLedger.append` writes existing bytes plus the new record line to a `.tmp` file, performs `flush()` and `os.fsync()`, and atomically swaps via `os.replace()`, preventing truncated or corrupted lines during sudden process termination.
- **Robust schema & invariant validation**: `_validate_record` enforces locked field specifications (`run_id`, `command`, `started_at`, `finished_at`, `exit_code`, `mid`, `work_ids`, `pages_fetched`, `records_fetched`, `records_existing`, `last_api_error_code`, `coverage_summary`, `cursor_snapshot`), strict integer type checks (explicitly guarding against `bool` subclasses), and validates nested `cursor_snapshot` keys while prohibiting in-memory-only `state="running"`.
- **Comprehensive security & redaction**: Prohibits forbidden credential, URL, and stack trace markers (`_FORBIDDEN_MARKERS`: `SESSDATA`, `cookie`, `Cookie`, `http://`, `https://`, `Traceback`) across the entire serialized record payload, and caps `last_api_error_code` string lengths to 64 characters to block raw exception message leaks.
- **Fault-tolerant ledger loading**: `RunLedger.load()` skips malformed JSON lines or schema validation errors with diagnostic stderr messages without raising uncaught exceptions, maintaining ledger readability despite manual file tampering or corruption.
- **Non-interfering CLI exit recording**: `_record_exit` hooks in `_cmd_fetch_meta` and `_cmd_pilot` wrap ledger appends in defensive `try ... except Exception: pass` blocks, ensuring telemetry failures never alter command exit codes or abort execution.
- **Strict architectural boundaries**: `bili_client.py` maintains sole HTTP transport ownership and does not import `run_ledger`; verified via dedicated unit test `test_bili_client_does_not_import_run_ledger`.
- **Manifest preservation**: The JSONL manifest row schema and last-write-wins semantics remain completely untouched; `run-ledger.jsonl` acts strictly as an operational sidecar.
- **Targeted test coverage**: 18 unit tests in `tests/test_run_ledger.py` cover schema roundtrips, atomic append order, corruption recovery, redaction enforcement, and CLI exit code wiring (0, 1, 2) across both `fetch-meta` and `pilot`.

### Issues

#### Critical

None.

#### Important

None.

#### Minor

- `bilibili-asr-archive/src/bili_asr/run_ledger.py:406`: `_validate_record` validates `command` as a non-empty string rather than checking membership in `VALID_COMMANDS`. This provides forward compatibility for future commands (such as the upcoming `run` coordinator) without breaking existing checks, though `VALID_COMMANDS` remains as module-level documentation.

### Assessment

**Task quality:** Approved
