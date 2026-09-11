Execute as: fullstack-dev
Delegation: forbidden
Task category: bugfix
Working branch: plan/20260824-cursor-based-resume
---

# Assignment — Plan 002 Task 1 L2 fix

Execution mode: sdd
SDD implementer session: fresh
Model tier: standard

Worktree path: `/root/workspace/bilibili-asr-archive/.worktrees/20260824-cursor-based-resume`
Plan Path: `/root/workspace/bilibili-asr-archive/.mstar/plans/20260824-cursor-based-resume.md`
SDD dir: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260824-cursor-based-resume`
execution_lease holder: `dsh:goal-9443ff6c-a480-4433-915a-cf116c1a986b`
HEAD: `be4623ac682906735e24b4403c3719b4a4aa42d3`

<SUBAGENT-STOP> Skip PM orchestration. Leaf implementer. Fix the L2 Important only.</SUBAGENT-STOP>

Prior review: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260824-cursor-based-resume/review/task-1-review.md`
Spec: `/root/workspace/bilibili-asr-archive/.mstar/iterations/iter-2026-08-archive-foundations/specs/meta-cursor.md`

## Fix

Without `--resume`, replace leftover `risk_interrupted` **after the first successful archive-list page** of the new run (after that page's JSONL merge), not only after the whole `fetch_pages` return.

Do not persist `state=running`. HTTP stays in `bili_client` (optional per-page callback / generator is OK; no cursor import in the client).

Add a test: leftover `risk_interrupted` next_page=2; no `--resume`; first page succeeds then the crawl aborts before the terminal persist; later `--resume` must **not** consume the old next_page=2.

Minors (bool mid, generic Exception path) out of this fix unless trivial.

Tests: `PYTHONPATH=src` + `/root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest -q`

Report: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260824-cursor-based-resume/task-1-fix-report.md`

Commit. No PR. No egg-info/uv.lock.
