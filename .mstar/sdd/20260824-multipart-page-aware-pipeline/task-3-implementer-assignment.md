Execute as: fullstack-dev
Delegation: forbidden
Task category: feature
Working branch: plan/20260824-multipart-page-aware-pipeline
---

# Assignment — Task 3 implementer

Execution mode: sdd
SDD implementer session: fresh
Model tier: standard
Findings cleanup: zero-residual

## Scene

Plan 001 Task 3: prove distinct artifacts and reruns. Tasks 1–2 are on this branch (identity + cid-aware harvest). `write_archive` still names files `{bvid}.*` and will collide across pages.

## Checkout (mandatory)

- Control harness root: `/root/workspace/bilibili-asr-archive/.mstar`
- Plan Path: `/root/workspace/bilibili-asr-archive/.mstar/plans/20260824-multipart-page-aware-pipeline.md`
- SDD dir: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260824-multipart-page-aware-pipeline`
- Worktree path: `/root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline`
- execution_lease holder: `dsh:goal-9443ff6c-a480-4433-915a-cf116c1a986b`
- Do not checkout another branch. Do not edit control-worktree product files.

## Requirements

Read first — this is your spec (verbatim values):
`/root/workspace/bilibili-asr-archive/.mstar/sdd/20260824-multipart-page-aware-pipeline/task-3-brief.md`

Architecture SSOT:
`/root/workspace/bilibili-asr-archive/.mstar/iterations/iter-2026-08-archive-foundations/specs/archive-foundations-architecture.md`

Use locked names: `PageIdentity`, `artifact_stem`, `work_id`. Do not invent aliases.

## Context not in the brief

- Product root: `<worktree>/bilibili-asr-archive/`
- Task 2 HEAD: `3b7064a` (parent `2e33653`; extra commit is tests-only for unresolved CLI skip)
- Harvest already writes subtitle raw/srt via `artifact_stem`. `write_archive` still uses `{bvid}.srt` / `{bvid}.txt` / `{bvid}.json` and md `{date}_{bvid}_{title}.md`. Change those stems to `artifact_stem` (md may include page_index). URL for page p>0 should use `?p=` via `page_query_index`.
- Tests: two-page raw/SRT/audio/transcript paths cannot collide; rerun is stable; completed or failed p0 does not suppress p1 (extend `tests/test_page_pipeline.py` / `tests/test_archive_md.py`).
- Document legacy migration + page-aware resume in a short operator-facing note under product docs if a matching file already exists; otherwise a concise module docstring / archive README fragment in the product tree — do not add `{KNOWLEDGE_DIR}` docs.
- L2 leftover (fix in this task): `download-audio --bvid` currently fabricates a `needs_audio` row when `_todo_for_bvid` returns `[]` (unresolved). STOP instead; never auto-assign unresolved to a page. Add a `main()` test.
- Tests via `uv` or existing `.venv-pm/bin/python -m pytest`. No live HTTP, no model download.

## Global Constraints

- Do not change the frozen API risk taxonomy or SESSDATA/signed-URL redaction boundaries.
- Do not add live-network tests, model downloads, or real media transfer.
- Preserve single-page compatibility adapters while making automatic multi-page enumeration page-aware.
- Every task must leave a reproducible test or static verification command.

## Report file

`/root/workspace/bilibili-asr-archive/.mstar/sdd/20260824-multipart-page-aware-pipeline/task-3-report.md`

## Before you begin

Load: `mstar-harness-core` → `mstar-host` → `references/dsh.md` → `mstar-roles` → `references/fullstack-dev.md` → `mstar-coding-behavior` → `mstar-sdd` (SUBAGENT-STOP).

## Your job

1. Implement exactly what the brief specifies, plus the unresolved `--bvid` STOP.
2. Tests from product root. No live HTTP.
3. Commit on Working branch only.
4. Self-review.
5. Write report file; return short summary only.

## When stuck

Report BLOCKED or NEEDS_CONTEXT — never guess.

## Report format (in file)

- Status: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED
- Implemented / attempted
- Tests: command, output
- Files changed
- Commits (SHAs)
- Self-review notes
