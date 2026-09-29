# iter-2026-08-corpus-coverage

Iteration package for the XL autonomous corpus-coverage and production-safety iteration.

## Documents

| Document | Kind | Description | Status |
|----------|------|-------------|--------|
| [delivery-compass.md](delivery-compass.md) | compass | Autonomous XL scope, six business plans, branch policy, and iteration gates | completed |
| [specs/](specs/) | spec | Six implemented product contracts: campaign, telemetry, quality, explorer, integrity, and concurrency gate | completed |

The package is the retained iteration snapshot. Reusable architecture guidance was promoted by updating these active knowledge documents at Phase 3 close:

- `specs/controlled-corpus-campaign.md`, `specs/coverage-telemetry-reconciliation.md`, `specs/subtitle-quality-campaign.md`, `specs/transcript-explorer.md`, and `specs/archive-integrity-recovery.md` → `.mstar/knowledge/architecture-patterns/operational-sidecars.md`
- all six implemented specs, including `specs/concurrency-safety-gate.md` → `.mstar/knowledge/architecture-patterns/bilibili-asr-archive-cli.md`

The three `guides/review-edit-*-assignment.md` files remain Phase 1 process snapshots and were not promoted as reusable product guidance.

## Product boundary

This iteration turns the shipped sequential CLI into an auditable corpus-production workflow. It does not promise that a bounded batch equals the whole visible corpus, and it does not claim semantic transcript correctness. The manifest JSONL remains the source of truth; operational sidecars and reports are derived evidence.

## Slice sequence

1. **Campaign** establishes bounded, restartable production runs.
2. **Telemetry** reconciles cumulative coverage and batch evidence.
3. **Subtitle quality** measures source coverage and deterministic artifact defects.
4. **Explorer** makes eligible completed transcripts searchable/exportable.
5. **Integrity** verifies required artifacts and records explicit bounded audit-only recovery candidates without requeueing or mutating archive state.
6. **Concurrency gate** evaluates evidence and normally returns no-go; it does not enable workers or a daemon by default.

Slices 1–2 are the production evidence spine. Slice 3 depends on reconciled denominators. Slice 4 depends on stable coverage and quality vocabulary. Slice 5 depends on the same artifact/status contracts. Slice 6 consumes evidence from campaign, telemetry, and integrity and is not an implementation bypass.

## Completion evidence

All six plans completed SDD implementation, L2 review, mandatory QC tri-review, mandatory QA, and serial merge into `iteration/iter-2026-08-corpus-coverage`. The final integration revision includes the deterministic concurrency gate while retaining `sequential-no-daemon`; the merged full suite passes 612 tests without live traffic. The delivery compass records plan-level gate evidence, roadmap disposition, compound promotion, and the iteration retrospective.
