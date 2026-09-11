# Task 2 Implementation Report: Inspectable status / runs surfaces + README

- Status: DONE
- Working branch: `plan/20260825-operational-ledger`
- Base commit: `6397e1c055e06c0e09b4aababa778b0ed0048804`
- Commit: `f65a19d97298064ccabfb3cf6e7b5a9080adf4a6` (`feat(ledger): add status run summary, runs command, and ledger documentation`)

## Implemented

1. **`bili-asr status` enhancements**:
   - Preserves existing per-status manifest row counts (`archived`, `meta_ok`, etc.) and unresolved identifiers.
   - Adds ledger run history count and latest run details (`run_id`, command, exit code, timestamp, cursor snapshot summary, and per-status coverage summary).
   - Honestly reflects cursor state for `limited` enumeration runs (e.g. `limited (next_page N, observed_total M)`), never claiming full enumeration.
   - Handles empty archives and missing ledger files gracefully (`manifest: empty`, `runs: 0`).

2. **Dedicated `bili-asr runs` verb**:
   - Added `bili-asr runs [--limit N] [--archive-root <root>]` subcommand to parser and CLI dispatcher.
   - Lists recent operational runs in chronological order with run IDs, command names, exit codes, cursor states, coverage summaries, and completion timestamps.
   - Supports `--limit N` (e.g. displaying only the latest N runs; non-positive values cleanly display `runs: empty`).
   - Gracefully handles empty ledgers (`runs: empty`) and corrupt lines in `run-ledger.jsonl` (warns to stderr and parses valid lines).
   - Reuses formatters from `bili_asr.run_ledger` with zero credential or trace leakage.

3. **Formatters in `bili_asr.run_ledger`**:
   - `format_cursor_summary(cursor_snapshot)`: Formats cursor state without claiming full enumeration for `limited`.
   - `format_coverage_summary(coverage_summary)`: Formats manifest per-status counts sorted by key.
   - `format_run_summary(record)`: Formats a complete single-line run record for operator inspection.

4. **Documentation in `README.md`**:
   - Added `bili-asr runs` to CLI workflow section.
   - Added comprehensive section on the operational run ledger (`run-ledger.jsonl`), detailing record schema fields, redaction guarantees, and operator inspection via `bili-asr status` and `bili-asr runs`.

5. **Test coverage**:
   - Unit tests for formatter functions (`format_cursor_summary`, `format_coverage_summary`, `format_run_summary`).
   - CLI integration tests for `status` with empty, populated, limited-cursor, and risk-interrupted archives.
   - CLI integration tests for `runs` with empty, multiple runs, `--limit`, corrupt line handling, and forbidden marker redaction guarantees.
   - Module entrypoint and help test assertions updated.

## Tests

### Focused tests
```bash
PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest tests/test_run_ledger.py -v
```
Output:
```
============================== 28 passed in 0.18s ==============================
```

### Full test suite
```bash
PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest -q
```
Output:
```
........................................................................ [ 33%]
........................................................................ [ 66%]
........................................................................ [ 99%]
..                                                                       [100%]
218 passed in 4.10s
```

## Files Changed

- `src/bili_asr/run_ledger.py`: Added `format_cursor_summary`, `format_coverage_summary`, and `format_run_summary`.
- `src/bili_asr/cli.py`: Added `runs` subcommand to `build_parser`, updated `_cmd_status`, implemented `_cmd_runs`, and wired `main()` dispatch.
- `README.md`: Documented ledger schema, redaction guarantees, and `status` / `runs` usage.
- `tests/test_run_ledger.py`: Added 10 tests covering formatters, `status` integration, `runs` listing, `--limit`, corruption tolerance, and redaction verification.
- `tests/test_cli_help.py`: Added `runs` assertions for direct and module entrypoints.

## Self-Review Notes

- Changes are strictly bounded to Task 2 requirements.
- No changes to manifest row schemas or HTTP ownership in `bili_client.py`.
- No credentials, signed URLs, or raw tracebacks are logged or displayed in operator outputs.
- All 218 tests in the full test suite pass cleanly with 0 failures.

## QC fix round

### Addressed Findings

1. **Nit (QC1 + QC2)** — `src/bili_asr/run_ledger.py` `RunLedger.load()`: Passed `raw` directly to `_validate_record(raw)` so non-dict JSON lines (e.g. `[1, 2]` or `"string"`) raise `ValueError` and produce the consistent `"run-ledger: ignoring corrupt line"` stderr diagnostic instead of being silently skipped.
2. **Suggestion (QC1)** — `src/bili_asr/run_ledger.py`: Added docstring comment to `VALID_COMMANDS` explaining that it serves as reference documentation for recognized core commands and `_validate_record` intentionally accepts any non-empty command string for forward compatibility with future subcommands.

### Commit
`cffe0f1de6ecc8a9d75060ebebb6db0b3a9fb2ce` (`fix(ledger): diagnose non-dict JSON lines in load and document VALID_COMMANDS`)

### Files Changed
- `src/bili_asr/run_ledger.py`: Updated `VALID_COMMANDS` documentation docstring and `RunLedger.load()` validation invocation.
- `tests/test_run_ledger.py`: Extended `test_corrupt_lines_ignored` to assert stderr diagnostic output on non-dict JSON lines.

### Test Execution & Output

```bash
cd /root/workspace/bilibili-asr-archive/.worktrees/20260825-operational-ledger/bilibili-asr-archive
PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest tests/test_run_ledger.py -q
```
Output:
```
............................                                             [100%]
28 passed in 0.13s
```

```bash
cd /root/workspace/bilibili-asr-archive/.worktrees/20260825-operational-ledger/bilibili-asr-archive
PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest -q
```
Output:
```
........................................................................ [ 33%]
........................................................................ [ 66%]
........................................................................ [ 99%]
..                                                                       [100%]
218 passed in 4.10s
```

