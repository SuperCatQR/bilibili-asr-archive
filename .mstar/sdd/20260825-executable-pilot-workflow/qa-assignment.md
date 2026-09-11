Execute as: qa-engineer
Delegation: forbidden
Task category: review
Working branch: plan/20260825-executable-pilot-workflow
---

# Assignment — Plan A mandatory full QA

QA mode: mandatory/full
Findings cleanup: zero-residual
Model tier: standard

Review cwd: `/root/workspace/bilibili-asr-archive/.worktrees/20260825-executable-pilot-workflow`
plan_id: `20260825-executable-pilot-workflow`
Review range: `559dfcb54816a8e275e5d162ab27f86cde187476..c4ce9bbb8b6c0709699df68489619ac3e6ef5ff3`
Diff basis: plan A start vs final HEAD

<SUBAGENT-STOP> Skip PM orchestration. Full QA gate. No PR.</SUBAGENT-STOP>

Plan: `/root/workspace/bilibili-asr-archive/.mstar/plans/20260825-executable-pilot-workflow.md`
Spec: `/root/workspace/bilibili-asr-archive/.mstar/specs/asr-archive-cli.md`
Prior QC: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260825-executable-pilot-workflow/review/qc-consolidated.md`

Acceptance: fresh `meta_ok` fixture drives bounded `pilot --n N` to both branch outcomes under fakes; subtitle rows archived without ASR; audio rows archived only after successful transcript writing; missing ASR → nonzero + install hint, row not archived; unavailable branch coverage → nonzero naming what's missing; completed rerun idempotent; multi-part bvid every `work_id` processed or failed; focused + full suite pass; no live HTTP.

Run on product root `bilibili-asr-archive/`:
`PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest -q`

Write `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260825-executable-pilot-workflow/review/qa.md` (include actual test output).

Return short summary. No worktree mutation.
