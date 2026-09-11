Execute as: fullstack-dev
Delegation: forbidden
Task category: implement
Working branch: plan/20260824-cursor-based-resume
---

# Assignment — Plan 002 Task 2

Execution mode: sdd
SDD implementer session: fresh
Model tier: standard
Findings cleanup: zero-residual

Worktree path: `/root/workspace/bilibili-asr-archive/.worktrees/20260824-cursor-based-resume`
Plan Path: `/root/workspace/bilibili-asr-archive/.mstar/plans/20260824-cursor-based-resume.md`
SDD dir: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260824-cursor-based-resume`
execution_lease holder: `dsh:goal-9443ff6c-a480-4433-915a-cf116c1a986b`
BASE_SHA: `7d4161f9d73c5dbfa97ac5c4c1d5406b48c8cd66`

<SUBAGENT-STOP> Skip PM orchestration. Leaf implementer for Task 2 only.</SUBAGENT-STOP>

Load: `mstar-harness-core` → `mstar-host` → `references/dsh.md` → `mstar-roles` → `references/fullstack-dev.md` → `mstar-coding-behavior` → `mstar-sdd`.

Brief: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260824-cursor-based-resume/task-2-brief.md`
Spec: `/root/workspace/bilibili-asr-archive/.mstar/iterations/iter-2026-08-archive-foundations/specs/meta-cursor.md`

Task 1 is L2 Approved at BASE. Do not reopen cursor schema. Prove:

1. Risk stop on page 2 → `next_page=2`, later `--resume` starts at page 2.
2. No duplicate JSONL `work_id`/bvid rows; failed page is not claimed complete.
3. Sidecar has no cookies, SESSDATA, signed URL, or raw exception text.
4. README documents `--resume` and exit 2.

T1 minor (JSONL truncate on first no-resume page) is context only — do not invent a preserve-until-complete policy unless required to meet "no duplicate rows".

HTTP stays in `bili_client`. No live HTTP. No PR. No egg-info/uv.lock.

Tests: `PYTHONPATH=src` + `/root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest -q`

Report: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260824-cursor-based-resume/task-2-report.md`

Commit. Return short summary.
