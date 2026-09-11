Execute as: fullstack-dev
Delegation: forbidden
Task category: bugfix
Working branch: plan/20260824-multipart-page-aware-pipeline
---

# Assignment — Plan 001 QC fix wave

Execution mode: sdd
SDD implementer session: fresh
Model tier: standard
Findings cleanup: zero-residual

## Checkout

- Worktree: `/root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline`
- Plan Path: `/root/workspace/bilibili-asr-archive/.mstar/plans/20260824-multipart-page-aware-pipeline.md`
- SDD dir: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260824-multipart-page-aware-pipeline`
- execution_lease holder: `dsh:goal-9443ff6c-a480-4433-915a-cf116c1a986b`
- HEAD: `fa20305bc85db07c7b2667b1d8bf6512705c35c8`
- Do not checkout another branch.

Consolidated findings:
`/root/workspace/bilibili-asr-archive/.mstar/sdd/20260824-multipart-page-aware-pipeline/review/qc-consolidated.md`

Also read `review/qc1.md`, `qc2.md`, `qc3.md`.

Architecture SSOT remains:
`/root/workspace/bilibili-asr-archive/.mstar/iterations/iter-2026-08-archive-foundations/specs/archive-foundations-architecture.md`

## Must fix (Warnings)

1. New automatic `upsert` rows require `work_id`. `_record_api_error` / unknown `--bvid` must not insert a bare-bvid processable row. Use `get_compatible` then STOP, or key by resolved `work_id`.
2. `--bvid` contract: STOP on unresolved. STOP on multi-part unless the argument is a `work_id` (`bvid:pN` via `parse_work_id`). Align harvest-subs, download-audio, and asr. Do not invent a new CLI flag name unless existing `parse_work_id` is enough.
3. `harvest-subs --bvid` on unresolved: exit 1 with the same STOP line as download-audio (not rc 0).
4. `_foreign_page_stems`: any `{bvid}.pN` including p0 is a migration collision.
5. `_merge_page_rows` / `_persist_partial`: never let per-bvid `list_pages` throw away already-fetched series pages. Persist series-level rows first; isolate pagelist failures per bvid.
6. Rate-limit or reuse pagelist during expansion (no unsleeped N-burst after series fetch). Do not call `list_pages` twice for the same bvid in one fetch-meta pass if identities are already in hand.

## Also fix (Suggestions in the consolidated in-scope list)

- `harvest_subtitle(str)`: if compatible row is unresolved/excluded, do not `resolve_page_identity`.
- Missing-cid STOP: do not print generic "unexpected error"; surface the STOP.
- `probe_subs`: refresh WBI on player `-403` like playurl.
- `download_audio`: skip-existing before network when the stem is already known (`PageIdentity`).
- `_foreign_page_stems`: walk known artifact dirs, not the entire archive root.

Do **not** add `duration` onto `PageIdentity` (QC1-S1) — locked struct.

## Tests

`.venv-pm/bin/python -m pytest -q` from product root. Add tests for: unresolved harvest `--bvid` rc 1; migrate collision on existing `{bvid}.p0`; upsert rejects new bare processable row; fetch-meta persist survives pagelist failure on one bvid.

No live HTTP. No egg-info / uv.lock. No PR.

## Report

`/root/workspace/bilibili-asr-archive/.mstar/sdd/20260824-multipart-page-aware-pipeline/qc-fix-report.md`

Load: `mstar-harness-core` → `mstar-host` → `references/dsh.md` → `mstar-roles` → `references/fullstack-dev.md` → `mstar-coding-behavior` → `mstar-sdd` (SUBAGENT-STOP).

Commit on the working branch. Return short summary.
