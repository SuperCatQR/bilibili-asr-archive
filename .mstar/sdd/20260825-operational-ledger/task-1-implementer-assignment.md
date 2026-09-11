Execute as: fullstack-dev
Delegation: forbidden
Task category: implement
Working branch: plan/20260825-operational-ledger
---

# Assignment — Plan C Task 1 (persist run records)

Execution mode: sdd
SDD implementer session: fresh
Model tier: standard
Findings cleanup: zero-residual

Worktree path: `/root/workspace/bilibili-asr-archive/.worktrees/20260825-operational-ledger`
Plan Path: `/root/workspace/bilibili-asr-archive/.mstar/plans/20260825-operational-ledger.md`
SDD dir: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260825-operational-ledger`
execution_lease holder: `dsh:goal-9443ff6c-a480-4433-915a-cf116c1a986b`
BASE_SHA: `79652889e7e7b7a6c8419a4bf30badf6f73ee757` (plan B merged)

<SUBAGENT-STOP> Skip PM orchestration. Leaf implementer for Task 1 only.</SUBAGENT-STOP>

Load: `mstar-harness-core` → `mstar-host` → `references/dsh.md` → `mstar-roles` → `references/fullstack-dev.md` → `mstar-coding-behavior` → `mstar-sdd`. New public name `RunLedger` is pre-locked in the plan; do not rename.

Brief: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260825-operational-ledger/task-1-brief.md`
Plan: `/root/workspace/bilibili-asr-archive/.mstar/plans/20260825-operational-ledger.md`

## Scope (Task 1 only)

- New module `bili_asr/run_ledger.py`: `RunLedger(root)` → `{archive_root}/run-ledger.jsonl`, append-only, atomic per-line writes (write temp + os.replace or single write with fsync — never leave a truncated line).
- Record fields (locked, from plan Interfaces): `run_id`, `command` (`fetch-meta` | `pilot`), optional `mid` / `work_ids`, `started_at` / `finished_at` ISO-8601 Z, `exit_code` int, `pages_fetched` / `records_fetched` / `records_existing` int|null, `last_api_error_code` int|short str|null (never exception text), `coverage_summary` dict of manifest `status` → count (keys from `VALID_STATUSES` only), `cursor_snapshot` (copy of the six `MetaCursorStore` keys or null).
- Wire into `cli`:
  - `fetch-meta` appends a record on exit 0 and exit 2 (with cursor snapshot).
  - `pilot` appends a run record on process exit (any code); branch counts live in `coverage_summary`; no raw exceptions.
- Redaction: no cookies/SESSDATA/signed URLs/raw exception text (same `_FORBIDDEN_MARKERS` discipline as `meta_cursor`).
- No manifest row schema change; ledger is a sidecar. `bili_client.py` must not import `run_ledger`.

## Tests

New `tests/test_run_ledger.py` (focused), then full suite:
`PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest -q`

## Report

`/root/workspace/bilibili-asr-archive/.mstar/sdd/20260825-operational-ledger/task-1-report.md`

Commit on working branch. No PR. No egg-info/uv.lock.
