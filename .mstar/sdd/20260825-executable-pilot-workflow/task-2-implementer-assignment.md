Execute as: fullstack-dev
Delegation: forbidden
Task category: implement
Working branch: plan/20260825-executable-pilot-workflow
---

# Assignment — Plan A Task 2 (idempotent reruns + dependency errors)

Execution mode: sdd
SDD implementer session: fresh
Model tier: standard
Findings cleanup: zero-residual

Worktree path: `/root/workspace/bilibili-asr-archive/.worktrees/20260825-executable-pilot-workflow`
Plan Path: `/root/workspace/bilibili-asr-archive/.mstar/plans/20260825-executable-pilot-workflow.md`
SDD dir: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260825-executable-pilot-workflow`
execution_lease holder: `dsh:goal-9443ff6c-a480-4433-915a-cf116c1a986b`
BASE_SHA: `8de38460fc58294e12fc97c2ef318965d7875b67` (Task 1 L2 Approved)

<SUBAGENT-STOP> Skip PM orchestration. Leaf implementer for Task 2 only.</SUBAGENT-STOP>

Load: `mstar-harness-core` → `mstar-host` → `references/dsh.md` → `mstar-roles` → `references/fullstack-dev.md` → `mstar-coding-behavior` → `mstar-sdd`.

Brief: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260825-executable-pilot-workflow/task-2-brief.md`
Plan: `/root/workspace/bilibili-asr-archive/.mstar/plans/20260825-executable-pilot-workflow.md`
Prior review (context only): `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260825-executable-pilot-workflow/review/task-1-review.md` — minors (ASR-missing/risk-budget early returns skip branch summary; selected count vs `--n` after page expand; failure paths print without persisting status) are NOT required unless cheap; Task 2 scope is the three pins.

## Task 2 scope

1. Completed pilot rerun skips archived rows / no duplicate artifacts or manifest rows.
2. Missing optional ASR dependency → clear nonzero result + install hint (`pip install -e "bilibili-asr-archive/[asr]"`), row NOT archived.
3. Subtitle branch never calls ASR; audio branch calls it exactly once.

Use fake transport + stubbed `asr.transcribe`; no live HTTP. Do not change `VALID_STATUSES` / `classify_risk` / JSONL schema.

## Tests

`PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest tests/test_pilot_select.py tests/test_cli_pilot.py -q` then full suite.

## Report

`/root/workspace/bilibili-asr-archive/.mstar/sdd/20260825-executable-pilot-workflow/task-2-report.md`

Commit on working branch. No PR. No egg-info/uv.lock.
