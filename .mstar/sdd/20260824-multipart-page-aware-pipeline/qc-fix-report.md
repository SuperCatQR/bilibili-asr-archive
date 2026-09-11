# QC fix report — Plan 001

Working branch: `plan/20260824-multipart-page-aware-pipeline`
Worktree path used: `/root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline`
Role: fullstack-dev (fresh SDD implementer)

## Warnings

| ID | Disposition |
|----|-------------|
| QC1-W1 | `upsert` rejects new processable rows without `work_id`. `_record_api_error` only patches `get` / `get_compatible`. Unknown `--bvid` no longer inserts a bare processable row. |
| QC1-W2 | harvest-subs, download-audio, and asr share `_todo_for_bvid`: STOP on unresolved / unknown / multi-part; `bvid:pN` via `parse_work_id` selects one page. |
| QC2-W1 | `harvest-subs --bvid` on unresolved now exits 1 with the same STOP line as download-audio. |
| QC2-W2 | `_foreign_page_stems` treats any `{bvid}.pN` including p0 as a migration collision. |
| QC3-W1 | `_merge_page_rows` isolates pagelist failures per bvid so other series rows still `store.save`. |
| QC3-W2 | One `_cached_page_lister` per fetch-meta pass; sleeper between distinct pagelist calls; migrate reuses the cache. |

## In-scope suggestions

| ID | Disposition |
|----|-------------|
| QC1-S2 | `download_audio(PageIdentity)` skip-existing before any HTTP. |
| QC2-S1 | `harvest_subtitle(str)` STOP on unresolved/excluded without `resolve_page_identity`. |
| QC2-S2 / QC3-S3 | Missing-cid / unresolved `ValueError` printed as STOP, not "unexpected error". |
| QC3-S2 | `probe_subs` refreshes WBI on player `-403`. |
| QC3-S4 | `_foreign_page_stems` walks known artifact dirs only. |

QC1-S1 (`duration` on `PageIdentity`) not implemented (locked struct).

## Tests

Command: `.venv-pm/bin/python -m pytest -q`  
Cwd: `bilibili-asr-archive/` in the feature worktree  
Result: **147 passed**

Added/updated coverage: unresolved harvest `--bvid` rc 1; migrate collision on `{bvid}.p0`; upsert rejects new bare processable row; fetch-meta persists other bvids when one pagelist fails.

No live HTTP. egg-info / uv.lock not committed. No PR.
