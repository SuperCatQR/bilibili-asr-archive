Execute as: product-manager
Delegation: forbidden
Task category: docs
Working branch: iteration/iter-2026-08-pilot-ops
---

# Assignment — Phase 1 Review & Edit: product-manager

Iteration: `iter-2026-08-pilot-ops` (autonomous loop, XL scale, direction "继续迭代").
Control worktree: `/root/workspace/bilibili-asr-archive`.

<SUBAGENT-STOP> Skip PM orchestration. Review & Edit chain seat 1 of 3. Do NOT write to `{KNOWLEDGE_DIR}`.</SUBAGENT-STOP>

Load: `mstar-harness-core` → `mstar-host` → `references/dsh.md` → `mstar-roles` → `references/product-manager.md`.

## Scope

Review and edit the iteration direction, scope, and acceptance criteria on disk. Sources of truth:

- Compass: `/root/workspace/bilibili-asr-archive/.mstar/iterations/iter-2026-08-pilot-ops/delivery-compass.md`
- Plans (5, in `/root/workspace/bilibili-asr-archive/.mstar/plans/`):
  - `20260825-executable-pilot-workflow.md`
  - `20260825-state-machine-entrypoint-tests.md`
  - `20260825-operational-ledger.md`
  - `20260825-search-export-fts5.md`
  - `20260825-run-coordinator-offline.md`
- Candidate sources: `.mstar/plans/audit-2026-08-24/` (003/004 + DIR-01/02/03), `.mstar/specs/asr-archive-cli.md` (frozen MVP)
- Prior iteration context: `.mstar/iterations/iter-2026-08-archive-foundations/` (delivered 001/002/005)

## Mandate

1. Verify the locked direction ("executable two-branch pilot + operational layer: run ledger, FTS5 search/export, run coordinator + offline reprocessing") matches roadmap evidence (audit 003/004, DIR-01/02/03, PLAN.md M4).
2. Verify iteration-level acceptance criteria are measurable and complete; fix gaps in compass `## Scope` / `## Acceptance Criteria` / `## Non-Goals`.
3. Check each plan's Goal/Status/ACs are product-coherent (pilot proves the frozen MVP proof bar; ledger/search/coordinator are operator-visible).
4. Make minimal targeted edits only where product scope/acceptance is wrong or missing. Do not rewrite architecture (architect seat) or prose (writing-specialist seat).

## Output

- Edited compass/plan files on disk (product-scope edits only).
- Short summary: what changed, what you verified, open product questions (if any).

No worktree mutation beyond the files above. No PR.
