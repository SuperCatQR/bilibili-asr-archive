Execute as: fullstack-dev
Delegation: forbidden
Task category: implement
Working branch: plan/20260825-state-machine-entrypoint-tests
---

# Assignment — Plan B Task 2 (installed entrypoint)

Execution mode: sdd
SDD implementer session: fresh
Model tier: standard
Findings cleanup: zero-residual

Worktree path: `/root/workspace/bilibili-asr-archive/.worktrees/20260825-state-machine-entrypoint-tests`
Plan Path: `/root/workspace/bilibili-asr-archive/.mstar/plans/20260825-state-machine-entrypoint-tests.md`
SDD dir: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260825-state-machine-entrypoint-tests`
execution_lease holder: `dsh:goal-9443ff6c-a480-4433-915a-cf116c1a986b`
BASE_SHA: `10ebd0238e73efe35e0d7a4adaaabfc58a37d470` (Task 1 L2 Approved)

<SUBAGENT-STOP> Skip PM orchestration. Leaf implementer for Task 2 only.</SUBAGENT-STOP>

Brief: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260825-state-machine-entrypoint-tests/task-2-brief.md`
Plan: `/root/workspace/bilibili-asr-archive/.mstar/plans/20260825-state-machine-entrypoint-tests.md`

## Scope

- New `tests/test_cli_help.py`: packaging/integration fixture invokes `bili-asr --help` and `bili-asr status --archive-root <temp>` as installed-console-script subprocesses.
- `python -m bili_asr --help` is a separate test and is NOT install proof.
- Document the exact environment-prep command (how the package gets installed into the test venv) in the plan's Prepare→Execute Handoff / report. If the console script is not available in the supported env, the test must `skip` with a clear environment-prerequisite message — never mutate the repo or global env during normal test runs (STOP condition).
- Do not change product source; do not change exit-code contracts; mixed per-video exit-code stays out of contract.

## Notes

- Check whether `bili-asr` console script exists in the PM venv first: `/root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/bili-asr --help`. If absent, prefer an editable/installable-env fixture guarded by availability; document the prep command (e.g. `pip install -e ".[asr]"` or `pip install .`) rather than mutating at test time.

## Tests

`PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest tests/test_cli_help.py -q` then full suite.

## Report

`/root/workspace/bilibili-asr-archive/.mstar/sdd/20260825-state-machine-entrypoint-tests/task-2-report.md`

Commit on working branch. No PR. No egg-info/uv.lock.
