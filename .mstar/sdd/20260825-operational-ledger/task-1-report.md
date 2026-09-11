# Task 1 report — Persist run records

- Status: DONE
- Role: fullstack-dev (fresh SDD implementer)
- Working branch: `plan/20260825-operational-ledger`
- Worktree path: `/root/workspace/bilibili-asr-archive/.worktrees/20260825-operational-ledger`
- HEAD: `6397e1c055e06c0e09b4aababa778b0ed0048804`
- BASE_SHA: `79652889e7e7b7a6c8419a4bf30badf6f73ee757`

## Implemented

1. **`bili_asr/run_ledger.py`**:
   - `RunLedger(root)`: Manages `{archive_root}/run-ledger.jsonl`.
   - Atomic per-line append (`.tmp` + `fsync` + `os.replace`) ensuring crash-safe JSONL writes without leaving partial or truncated lines.
   - `load()`: Reads valid records in chronological order, safely ignoring corrupt lines with a stderr diagnostic.
   - `latest()`: Returns the most recent record or `None`.
   - Record validation: Enforces locked field schema (`run_id`, `command`, `started_at`, `finished_at`, `exit_code`, `mid`, `work_ids`, `pages_fetched`, `records_fetched`, `records_existing`, `last_api_error_code`, `coverage_summary`, `cursor_snapshot`).
   - Redaction: Prohibits credentials/URLs/traces (`_FORBIDDEN_MARKERS`: `SESSDATA`, `cookie`, `Cookie`, `http://`, `https://`, `Traceback`), and caps error codes to 64 chars.
   - `compute_coverage_summary()`: Generates manifest `status` counts restricted to `VALID_STATUSES`.

2. **`bili_asr/cli.py`**:
   - `_cmd_fetch_meta`: Appends a run record on exit code 0 and exit code 2 (with cursor snapshot, page/record counts, and manifest coverage summary).
   - `_cmd_pilot`: Appends a run record on all process exits (exit codes 0, 1, 2), recording selected work_ids, branch coverage summary, last API error codes without raw exceptions, and cursor snapshot.

3. **`tests/test_run_ledger.py`**:
   - 18 focused tests for `RunLedger` store operations, schema validation, redaction markers, corruption resilience, architectural boundaries (`bili_client` does not import `run_ledger`), and CLI integration for both `fetch-meta` and `pilot`.

## Tests

Focused test suite:
```bash
PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest tests/test_run_ledger.py -v
```
Output: `18 passed in 0.11s`

Full test suite:
```bash
PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest -v
```
Output: `207 passed in 4.14s`

## Files Changed

- `bilibili-asr-archive/src/bili_asr/run_ledger.py` (new)
- `bilibili-asr-archive/src/bili_asr/cli.py` (modified)
- `bilibili-asr-archive/tests/test_run_ledger.py` (new)

## Self-review

- Manifest JSONL row schema unchanged (last-write-wins per `work_id` preserved); run ledger is strictly a sidecar.
- `bili_client.py` does not import `run_ledger`.
- No credentials, signed URLs, or raw exception strings are written to the ledger.
- Clean git status and no extra untracked files.
- No PR created.
