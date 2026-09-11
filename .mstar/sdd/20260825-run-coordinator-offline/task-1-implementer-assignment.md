Execute as: fullstack-dev
Delegation: forbidden
Task category: implement
Working branch: plan/20260825-run-coordinator-offline
---

# Assignment — Plan E Task 1 (stage-attempt ledger + coordinator core)

Execution mode: sdd
SDD implementer session: fresh
Model tier: standard
Findings cleanup: zero-residual

Worktree path: `/root/workspace/bilibili-asr-archive/.worktrees/20260825-run-coordinator-offline`
Plan Path: `/root/workspace/bilibili-asr-archive/.mstar/plans/20260825-run-coordinator-offline.md`
SDD dir: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260825-run-coordinator-offline`

<SUBAGENT-STOP> Skip PM orchestration. Leaf implementer for Task 1 only.</SUBAGENT-STOP>

Brief: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260825-run-coordinator-offline/task-1-brief.md`
Plan: `/root/workspace/bilibili-asr-archive/.mstar/plans/20260825-run-coordinator-offline.md`

## Scope (Task 1 only)

- `RunCoordinator` records per-stage attempts atomically (append-only, no partial lines).
- `run` command executes stages according to manifest `status`; per-item failures recorded and batch continues.
- Bounded `--limit`; rerun skips already-terminal rows.

## Tests

Focused + full suite:
```
cd /root/workspace/bilibili-asr-archive/.worktrees/20260825-run-coordinator-offline/bilibili-asr-archive
PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest tests/test_coordinator.py -q
PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest -q
```

## Report

`/root/workspace/bilibili-asr-archive/.mstar/sdd/20260825-run-coordinator-offline/task-1-report.md`

Commit on working branch. No PR. No egg-info/uv.lock.
