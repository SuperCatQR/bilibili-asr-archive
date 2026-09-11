Execute as: fullstack-dev
Delegation: forbidden
Task category: bugfix
Working branch: plan/20260824-multipart-page-aware-pipeline
---

# Assignment — Task 3 L2 fix

Execution mode: sdd
SDD implementer session: fresh
Model tier: standard
Findings cleanup: zero-residual

## Scene

Task 3 L2 **Needs fixes**. Architecture requires markdown frontmatter identity fields. Everything else in Task 3 is accepted.

## Checkout (mandatory)

- Worktree: `/root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline`
- Plan Path: `/root/workspace/bilibili-asr-archive/.mstar/plans/20260824-multipart-page-aware-pipeline.md`
- SDD dir: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260824-multipart-page-aware-pipeline`
- execution_lease holder: `dsh:goal-9443ff6c-a480-4433-915a-cf116c1a986b`
- HEAD now: `817b5c89597ec2eda2a3ff729f440daa1a8c612a`
- Do not checkout another branch. Do not revert WBI cache `30a12d8`.

## Spec (verbatim)

Architecture (`archive-foundations-architecture.md` Harvest / audio / archive):

`write_archive(..., entry, ...)` filenames use `artifact_stem`; markdown frontmatter includes `work_id`, `bvid`, `page_index`, `cid`; `url` may append `?p={page_index+1}`.

Do **not** invent `work_id`, `page_index`, or `cid` on unresolved rows.

## Required change

1. `bili_asr/archive.py` `write_archive` frontmatter: include `work_id`, `page_index`, `cid` for page-aware rows (alongside existing `bvid`, `title`, `date`, `duration_s`, `source`, `url`).
2. Unresolved / missing-`work_id` rows: do not invent those fields. Keep legacy stem/url. You may omit the keys or write JSON `null` — pick one and test it.
3. Test: two-page markdown files contain distinct `work_id` / `page_index` / `cid`. Unresolved md must not grow a fabricated `work_id`.
4. Do not expand scope to L2 minors (asr mixed exit code, probe_subs WBI refresh, brittle `.p` assert) unless they fall out of the frontmatter edit.

## Tests

Product root: `.venv-pm/bin/python -m pytest -q` or `uv run --with pytest python -m pytest -q`. No live HTTP.

## Report

`/root/workspace/bilibili-asr-archive/.mstar/sdd/20260824-multipart-page-aware-pipeline/task-3-fix-report.md`

## Before you begin

Load: `mstar-harness-core` → `mstar-host` → `references/dsh.md` → `mstar-roles` → `references/fullstack-dev.md` → `mstar-coding-behavior` → `mstar-sdd` (SUBAGENT-STOP).

## Your job

1. Fix the Important finding only.
2. Tests green.
3. Commit on Working branch.
4. Write report (DONE / BLOCKED, SHA, test output).
5. Return short summary. No PR. No egg-info / uv.lock.

## When stuck

BLOCKED or NEEDS_CONTEXT — never guess.
