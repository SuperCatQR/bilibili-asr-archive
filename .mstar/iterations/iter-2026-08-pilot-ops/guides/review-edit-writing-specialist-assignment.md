Execute as: writing-specialist
Delegation: forbidden
Task category: docs
Working branch: iteration/iter-2026-08-pilot-ops
---

# Assignment — Phase 1 Review & Edit: writing-specialist (corpus hygiene)

Iteration: `iter-2026-08-pilot-ops` (autonomous loop, XL scale).
Control worktree: `/root/workspace/bilibili-asr-archive`.
Prior seats: product-manager (scope/AC), architect (contracts/Interfaces) completed.

<SUBAGENT-STOP> Skip PM orchestration. Review & Edit chain seat 3 of 3. Do NOT write to `{KNOWLEDGE_DIR}`.</SUBAGENT-STOP>

Load: `mstar-harness-core` → `mstar-host` → `references/dsh.md` → `mstar-roles` → `references/writing-specialist.md` → `mstar-iteration/references/iteration-corpus-hygiene.md` (as needed).

## Scope

Corpus hygiene + prose quality on disk. Sources of truth:

- Compass: `/root/workspace/bilibili-asr-archive/.mstar/iterations/iter-2026-08-pilot-ops/delivery-compass.md`
- Plans (5) in `/root/workspace/bilibili-asr-archive/.mstar/plans/`: `20260825-executable-pilot-workflow.md`, `20260825-state-machine-entrypoint-tests.md`, `20260825-operational-ledger.md`, `20260825-search-export-fts5.md`, `20260825-run-coordinator-offline.md`
- Iteration package: `/root/workspace/bilibili-asr-archive/.mstar/iterations/iter-2026-08-pilot-ops/` (README.md, guides/, delivery-compass.md)
- Specs corpus: `/root/workspace/bilibili-asr-archive/.mstar/specs/` (asr-archive-cli.md frozen — do NOT rewrite)
- Iterations index: `/root/workspace/bilibili-asr-archive/.mstar/iterations/README.md`

## Mandate

1. Prose/consistency pass over compass + 5 plans: terminology (`work_id`/`artifact_stem`, `status` vs `state`, `pilot` vs `run`), headings, checkboxes, acceptance criteria measurable.
2. Corpus hygiene: verify nothing was misrouted — iteration-scoped drafts live under `{ITERATION_DIR}/iter-2026-08-pilot-ops/`, plans under `{PLAN_DIR}`, no new files under `{KNOWLEDGE_DIR}` or `{SPECS_DIR}` (except frozen spec untouched).
3. Fix any doc that misstates the frozen spec or prior iteration outcomes (001/002/005 merged to main at `559dfcb`).
4. Ensure every plan has the `## Durable Review Summary` placeholder and consistent Status/Depends-on fields.

## Output

- Edited files on disk (prose/hygiene only).
- Short summary: what changed, hygiene findings.

No worktree mutation beyond the files above. No PR.
