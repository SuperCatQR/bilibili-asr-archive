Execute as: fullstack-dev
Delegation: forbidden
Task category: bugfix
Working branch: plan/20260824-cursor-based-resume
---

# Assignment — Plan 002 F-005 fix (QC3 revalidation)

Execution mode: sdd
SDD implementer session: fresh
Model tier: standard
Findings cleanup: zero-residual

Worktree path: `/root/workspace/bilibili-asr-archive/.worktrees/20260824-cursor-based-resume`
SDD dir: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260824-cursor-based-resume`
execution_lease holder: `dsh:goal-9443ff6c-a480-4433-915a-cf116c1a986b`
HEAD: `9ab3507f06a32c23f4a42561dcf918071289326b` (R1–R4 already fixed; do NOT redo them)

<SUBAGENT-STOP> Skip PM orchestration. Leaf implementer. Fix F-005 only.</SUBAGENT-STOP>

QC3 revalidation: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260824-cursor-based-resume/review/qc3-revalidation.md`
Spec: `/root/workspace/bilibili-asr-archive/.mstar/iterations/iter-2026-08-archive-foundations/specs/meta-cursor.md`

## The bug (F-005)

`cli.py _cmd_fetch_meta` builds `known_bvids` from the existing JSONL **always**, and passes `known_bvids or None` into `BiliClient.fetch_pages` even without `--resume`. In `bili_client.fetch_pages`, the stop `if arcs and not added: enumeration_complete = True; break` then fires on the FIRST overlapping page of a full recrawl (every bvid already exists), so a plain `fetch-meta` recrawl from `pn=1` stops after one HTTP page instead of walking `ceil(total/ps)`.

## Fix

Seed `known_bvids` **only when `--resume`**. On a non-resume full recrawl, pass `known_bvids=None` so the no-new-bvid stop cannot fire; the run walks the whole catalog (`pn >= ceil(total/ps)` and other stops still apply) and last-write-wins refreshes the JSONL.

Keep `BiliClient` free of any `meta_cursor` import.

## Tests

Add a regression test in `tests/test_meta_cursor.py` (or `tests/test_fetch_meta.py` if the shape fits better): a non-resume `fetch-meta` with pre-existing JSONL whose bvids all overlap page 1 must still fetch through `ceil(total/ps)` and refresh (not stop after page 1). Keep the existing resume-seeding test green.

Run: `PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest -q` — full suite must pass.

## Report

Append to `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260824-cursor-based-resume/qc-fix-report.md` (or write `qc-fix-f005-report.md`): what changed, test command + count.

Commit on the working branch. No PR. No egg-info/uv.lock. Return a short summary.
