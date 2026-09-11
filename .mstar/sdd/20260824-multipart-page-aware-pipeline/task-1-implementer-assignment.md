# Assignment — Task 1 implementer

Execute as: fullstack-dev
Delegation: forbidden
Execution mode: sdd
SDD implementer session: fresh
Model tier: standard
Findings cleanup: zero-residual

## Scene

Plan 001 Task 1: lock page identity and migrate unambiguous legacy bare-bvid rows before any harvest/playurl change.

## Checkout (mandatory)

- Control harness root: `/root/workspace/bilibili-asr-archive/.mstar`
- Plan Path: `/root/workspace/bilibili-asr-archive/.mstar/plans/20260824-multipart-page-aware-pipeline.md`
- SDD dir: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260824-multipart-page-aware-pipeline`
- Worktree path: `/root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline`
- Working branch: `plan/20260824-multipart-page-aware-pipeline`
- execution_lease holder: `dsh:goal-9443ff6c-a480-4433-915a-cf116c1a986b`
- Do not checkout another branch. Do not edit files in the control worktree product tree.

## Requirements

Read first — this is your spec (verbatim values):
`/root/workspace/bilibili-asr-archive/.mstar/sdd/20260824-multipart-page-aware-pipeline/task-1-brief.md`

Architecture SSOT (control paths; not present in the feature worktree):
- `/root/workspace/bilibili-asr-archive/.mstar/iterations/iter-2026-08-archive-foundations/specs/archive-foundations-architecture.md`
- Frozen MVP still bvid-keyed: `/root/workspace/bilibili-asr-archive/.mstar/specs/asr-archive-cli.md`

Use the locked names from the architecture spec. Do not invent alternate identifiers.

## Context not in the brief

- Product root: `<worktree>/bilibili-asr-archive/`
- Current `ManifestStore` keys JSONL by `bvid` in `src/bili_asr/manifest.py`.
- `harvest_subtitle` / `download_audio` / `write_archive` still take bare `bvid` and write `{bvid}.*`. Task 1 may add identity + manifest migration; do not expand into full harvest/playurl rewiring unless required for tests.
- Unresolved operator rewrite CLI is **out of scope**; report + exclude only.
- `cid` is a field, never the primary key.
- `artifact_stem` = `{bvid}.p{page_index}` — never put `work_id` (`:`) on disk.

## Global Constraints

- Do not change the frozen API risk taxonomy or SESSDATA/signed-URL redaction boundaries.
- Do not add live-network tests, model downloads, or real media transfer.
- Preserve single-page compatibility adapters while making automatic multi-page enumeration page-aware.
- Every task must leave a reproducible test or static verification command.

## Report file

Write your full report to:
`/root/workspace/bilibili-asr-archive/.mstar/sdd/20260824-multipart-page-aware-pipeline/task-1-report.md`

## Before you begin

Load: `mstar-harness-core` → `mstar-host` → `references/dsh.md` → `mstar-roles` → `references/fullstack-dev.md` → `mstar-coding-behavior` → `mstar-sdd` (SUBAGENT-STOP).

## Your job

1. Implement exactly what the brief specifies.
2. Tests: from product root, `python3 -m pytest` (create/use a local 3.12 venv if needed). No live HTTP, no model download, no real media.
3. Commit on Working branch only.
4. Self-review.
5. Write report file; return short summary only.

## When stuck

Report BLOCKED or NEEDS_CONTEXT — never guess.

## Report format (in file)

- Status: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED
- Implemented / attempted
- Tests: command, output, red/green evidence if TDD
- Files changed
- Commits (SHAs)
- Self-review notes
