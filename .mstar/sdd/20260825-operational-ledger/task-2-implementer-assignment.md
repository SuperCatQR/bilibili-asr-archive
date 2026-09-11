Execute as: fullstack-dev
Delegation: forbidden
Task category: implement
Working branch: plan/20260825-operational-ledger
---

# Assignment — Plan C Task 2 (inspectable status/runs)

Execution mode: sdd
SDD implementer session: fresh
Model tier: standard
Findings cleanup: zero-residual

Worktree path: `/root/workspace/bilibili-asr-archive/.worktrees/20260825-operational-ledger`
Plan Path: `/root/workspace/bilibili-asr-archive/.mstar/plans/20260825-operational-ledger.md`
SDD dir: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260825-operational-ledger`
execution_lease holder: `dsh:goal-9443ff6c-a480-4433-915a-cf116c1a986b`
BASE_SHA: `6397e1c055e06c0e09b4aababa778b0ed0048804` (Task 1 L2 Approved)

<SUBAGENT-STOP> Skip PM orchestration. Leaf implementer for Task 2 only.</SUBAGENT-STOP>

Brief: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260825-operational-ledger/task-2-brief.md`
Plan: `/root/workspace/bilibili-asr-archive/.mstar/plans/20260825-operational-ledger.md`

## Scope (Task 2 only)

- `bili-asr status --archive-root <root>` keeps current per-`status` counts and adds run-history + coverage from the ledger.
- `bili-asr runs [--limit N] [--archive-root]` is a dedicated verb (not only `status --runs`): lists recent runs with exit codes and cursor `state`.
- README documents ledger schema and status/runs output.
- Ledger is a sidecar; JSONL manifest rows unchanged. `status`/`runs` must not claim full enumeration for `limited` cursor state.
- No credentials/signed URLs/raw exceptions in operator output.

## Tests

Focused tests + full suite:
`PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest -q`

## Report

`/root/workspace/bilibili-asr-archive/.mstar/sdd/20260825-operational-ledger/task-2-report.md`

Commit on working branch. No PR. No egg-info/uv.lock.
