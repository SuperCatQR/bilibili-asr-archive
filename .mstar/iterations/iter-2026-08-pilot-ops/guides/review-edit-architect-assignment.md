Execute as: architect
Delegation: forbidden
Task category: docs
Working branch: iteration/iter-2026-08-pilot-ops
---

# Assignment — Phase 1 Review & Edit: architect

Iteration: `iter-2026-08-pilot-ops` (autonomous loop, XL scale).
Control worktree: `/root/workspace/bilibili-asr-archive`.
Prior seat: product-manager completed (scope/AC verified).

<SUBAGENT-STOP> Skip PM orchestration. Review & Edit chain seat 2 of 3. Do NOT write to `{KNOWLEDGE_DIR}`.</SUBAGENT-STOP>

Load: `mstar-harness-core` → `mstar-host` → `references/dsh.md` → `mstar-roles` → `references/architect.md`.

## Scope

Review and edit the architecture/contracts on disk. Sources of truth:

- Compass: `/root/workspace/bilibili-asr-archive/.mstar/iterations/iter-2026-08-pilot-ops/delivery-compass.md`
- Plans (5) in `/root/workspace/bilibili-asr-archive/.mstar/plans/`:
  - `20260825-executable-pilot-workflow.md`
  - `20260825-state-machine-entrypoint-tests.md`
  - `20260825-operational-ledger.md`
  - `20260825-search-export-fts5.md`
  - `20260825-run-coordinator-offline.md`
- Frozen spec: `.mstar/specs/asr-archive-cli.md` (do NOT rewrite)
- Prior iteration architecture spec: `.mstar/iterations/iter-2026-08-archive-foundations/specs/archive-foundations-architecture.md`
- Product code: `bilibili-asr-archive/src/bili_asr/` (cli.py, manifest.py, bili_client.py, subtitles.py, audio.py, asr.py, archive.py, page_identity.py, meta_cursor.py)

## Mandate

1. Verify each plan's `## Interfaces` and `## Global Constraints` against live code (signatures, seams, lazy-import guarantees, HTTP ownership, JSONL compatibility, `work_id`/`artifact_stem` conventions).
2. Fix architecture/contract errors in plan Interfaces/Constraints; confirm no manifest schema migration, no risk-taxonomy change, no new dependencies, `bili_client` remains sole HTTP owner.
3. Check the pilot plan's orchestration seams (subtitles.harvest_subtitle / audio.download_audio / asr.transcribe / archive.write_archive signatures) and coordinator stage boundaries are implementable as written.
4. Make minimal targeted edits where architecture/contracts are wrong or missing. Do not redo product scope (seat 1) or prose (seat 3).

## Output

- Edited plan files on disk (architecture/contract edits only).
- Short summary: what changed, what you verified against code, open architecture questions (if any).

No worktree mutation beyond the files above. No PR.
