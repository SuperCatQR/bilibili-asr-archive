# iter-2026-08-pilot-ops

Iteration package — `delivery-compass.md` plus specs/guides. Not `{KNOWLEDGE_DIR}/`. Promote at iteration-close via `mstar-compound`.

## Documents

| Document | Kind | Description | Status |
|----------|------|-------------|--------|
| [delivery-compass.md](delivery-compass.md) | compass | Scope, acceptance, roadmap, branch policy | completed |
| [guides/](guides/) | guide | Phase 1 review-chain assignments (snapshot-only) | snapshot-only |

## Delivery order

1. Plan `20260825-executable-pilot-workflow` — two-branch pilot execution (audit 003).
2. Plan `20260825-state-machine-entrypoint-tests` — integration + installed entrypoint (audit 004; serial after 1).
3. Plan `20260825-operational-ledger` — run metadata/coverage (DIR-01).
4. Plan `20260825-search-export-fts5` — SQLite FTS5 read model (DIR-02 / PLAN.md M4).
5. Plan `20260825-run-coordinator-offline` — stage-attempt coordinator + offline reprocessing (DIR-03; last, depends on 1/3 contracts).

## Frozen spec delta

`.mstar/specs/asr-archive-cli.md` stays the frozen MVP. This iteration adds operator-visible layers (pilot execution, run ledger, FTS5 search/export, run coordinator) without changing the frozen risk taxonomy, manifest schema, or HTTP ownership.

## Promotion log (filled at iteration-close)

| Source | Promoted to | Date | Notes |
|--------|-------------|------|-------|
| plan C/D/E (ledger, FTS5, coordinator) | `.mstar/knowledge/architecture-patterns/operational-sidecars.md` | 2026-08-25 | Structured rewrite, not a file copy |
| `guides/` review-edit assignments | — | 2026-08-25 | Keep snapshot; process-only |
