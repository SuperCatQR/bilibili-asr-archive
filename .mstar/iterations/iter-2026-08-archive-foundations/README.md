# iter-2026-08-archive-foundations

Iteration package — `delivery-compass.md` plus specs/guides. Not `{KNOWLEDGE_DIR}/`. Promote at iteration-close via `mstar-compound`.

## Documents

| Document | Kind | Description | Status |
|----------|------|-------------|--------|
| [delivery-compass.md](delivery-compass.md) | compass | Scope, acceptance, roadmap, branch policy | locked |
| [specs/archive-foundations-architecture.md](specs/archive-foundations-architecture.md) | spec | PageIdentity, ledger, artifacts, client seams | draft |
| [specs/meta-cursor.md](specs/meta-cursor.md) | spec | `meta-cursor.json` schema and CLI/HTTP split | draft |
| [guides/review-edit-product-manager-assignment.md](guides/review-edit-product-manager-assignment.md) | guide | Phase 1 product-manager assignment | snapshot-only |
| [guides/review-edit-architect-assignment.md](guides/review-edit-architect-assignment.md) | guide | Phase 1 architect assignment | snapshot-only |
| [guides/review-edit-writing-specialist-assignment.md](guides/review-edit-writing-specialist-assignment.md) | guide | Phase 1 writing-specialist assignment | snapshot-only |

Spec status is `draft` until iteration-close promotion. Do not copy these files into `{SPECS_DIR}` or `{KNOWLEDGE_DIR}` during start/execute.

## Frozen spec delta

`.mstar/specs/asr-archive-cli.md` stays the frozen MVP: JSONL keyed by `bvid`, artifact stems `{bvid}.*`, no page identity. Do not rewrite that file as page-aware.

Intended change for this iteration (SSOT here until compound):

- Ledger key: `work_id` = `bvid:p<zero-based-page-index>`.
- Filesystem stem: `{bvid}.p{page_index}` (`artifact_stem`; never put `:` in paths).
- Unresolved legacy bare-bvid rows: preserve, report, exclude from automatic page processing.
- Metadata resume: archive-root `meta-cursor.json`; terminals `complete` / `limited` / `risk_interrupted`.

Shipped knowledge `architecture-patterns/bilibili-asr-archive-cli.md` still describes the bvid-keyed manifest; leave it until close.

## Delivery order

1. Plan `20260824-multipart-page-aware-pipeline` — identity, migration, page-aware harvest.
2. Plan `20260824-cursor-based-resume` — cursor sidecar (serial after 001).
3. Pilot remains a later iteration after these foundations and audit plan 005.

## Promotion log (filled at iteration-close)

| Source | Promoted to | Date | Notes |
|--------|-------------|------|-------|
| `specs/meta-cursor.md` + `specs/archive-foundations-architecture.md` (validated patterns) | `{KNOWLEDGE_DIR}/architecture-patterns/bilibili-asr-archive-cli.md` (updated) | 2026-08-24 | Page-aware `work_id`, `meta-cursor.json` resume, `--limit-pages` this-call semantics; verified by plans 001/002 QC/QA |
