Execute as: qa-engineer
Delegation: forbidden
Task category: review
Working branch: plan/20260825-state-machine-entrypoint-tests
---

# Assignment — Plan B mandatory full QA

QA mode: mandatory/full
Findings cleanup: zero-residual
Model tier: standard

Review cwd: `/root/workspace/bilibili-asr-archive/.worktrees/20260825-state-machine-entrypoint-tests`
plan_id: `20260825-state-machine-entrypoint-tests`
Review range: `c4ce9bbb8b6c0709699df68489619ac3e6ef5ff3..79652889e7e7b7a6c8419a4bf30badf6f73ee757`
Diff basis: plan B start (plan A merge) vs final HEAD

<SUBAGENT-STOP> Skip PM orchestration. Full QA gate. No PR.</SUBAGENT-STOP>

Plan: `/root/workspace/bilibili-asr-archive/.mstar/plans/20260825-state-machine-entrypoint-tests.md`
Spec: `/root/workspace/bilibili-asr-archive/.mstar/specs/asr-archive-cli.md`
Prior QC: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260825-state-machine-entrypoint-tests/review/qc-consolidated.md`

Acceptance: both terminal paths covered through `cli.main`; risk exhaustion → exit 2 with last stable status preserved; missing ASR → exit 1 non-archived; rerun idempotent; installed console script (`bili-asr --help`, `bili-asr status --archive-root <temp>`) exercised as subprocess with PYTHONPATH stripped, or documented env-prerequisite skip; `python -m` separate and not install proof; mixed per-video exit-code NOT changed; no live HTTP or model downloads; `git status --short` only in-scope files.

Run on product root `bilibili-asr-archive/`:
`PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest -q`

Write `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260825-state-machine-entrypoint-tests/review/qa.md` (include actual test output).

Return short summary. No worktree mutation.
