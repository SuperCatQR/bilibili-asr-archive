Execute as: fullstack-dev
Delegation: forbidden
Task category: feature
Working branch: plan/20260824-multipart-page-aware-pipeline
---

# Assignment — Task 2 implementer

Execution mode: sdd
SDD implementer session: fresh
Model tier: standard
Findings cleanup: zero-residual

## Scene

Plan 001 Task 2: enumerate every pagelist part, thread cid into subtitle/playurl, keep p0/p1 independent. Task 1 identity/migration is already on this branch.

## Checkout (mandatory)

- Control harness root: `/root/workspace/bilibili-asr-archive/.mstar`
- Plan Path: `/root/workspace/bilibili-asr-archive/.mstar/plans/20260824-multipart-page-aware-pipeline.md`
- SDD dir: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260824-multipart-page-aware-pipeline`
- Worktree path: `/root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline`
- execution_lease holder: `dsh:goal-9443ff6c-a480-4433-915a-cf116c1a986b`
- Do not checkout another branch. Do not edit control-worktree product files.

## Requirements

Read first — this is your spec (verbatim values):
`/root/workspace/bilibili-asr-archive/.mstar/sdd/20260824-multipart-page-aware-pipeline/task-2-brief.md`

Architecture SSOT:
`/root/workspace/bilibili-asr-archive/.mstar/iterations/iter-2026-08-archive-foundations/specs/archive-foundations-architecture.md`

Use locked names: `list_pages`, `AmbiguousPageError`, `PageIdentity`. Do not invent aliases.

## Context not in the brief

- Product root: `<worktree>/bilibili-asr-archive/`
- Task 1 landed: `page_identity.py`, `ManifestStore` keyed by `work_id`, `migrate_legacy_rows`, `get_compatible`.
- Current `probe_subs(bvid)` / `fetch_playurl_audio(bvid)` still use `pages[0]`. Change to `cid: int | None = None`; `cid is None` only when pagelist length is 1; otherwise raise `AmbiguousPageError`. Never silent `pages[0]` on multi-part.
- `harvest_subtitle` / `download_audio` must take `PageIdentity` (or derive paths from `artifact_stem`) and pass that page's cid.
- Create one ledger row per `PageIdentity`. Skip unresolved legacy rows.
- Call `migrate_legacy_rows` from the meta/harvest path so Task 1's library is not dead code.
- `upsert` may keep accepting bare-bvid until callers emit `work_id`; new automatic page rows must include `work_id`.
- Two-page fixtures only; no live HTTP, no model download, no real media.

## Global Constraints

- Do not change the frozen API risk taxonomy or SESSDATA/signed-URL redaction boundaries.
- Do not add live-network tests, model downloads, or real media transfer.
- Preserve single-page compatibility adapters while making automatic multi-page enumeration page-aware.
- Every task must leave a reproducible test or static verification command.

## Report file

`/root/workspace/bilibili-asr-archive/.mstar/sdd/20260824-multipart-page-aware-pipeline/task-2-report.md`

## Before you begin

Load: `mstar-harness-core` → `mstar-host` → `references/dsh.md` → `mstar-roles` → `references/fullstack-dev.md` → `mstar-coding-behavior` → `mstar-sdd` (SUBAGENT-STOP).

## Your job

1. Implement exactly what the brief specifies.
2. Tests from product root with `uv` (`uv venv` + `uv pip install -e '.[dev]'` + `python -m pytest`). No live HTTP.
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
