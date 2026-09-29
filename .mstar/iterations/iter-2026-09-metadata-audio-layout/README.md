# iter-2026-09-metadata-audio-layout

Iteration package — `delivery-compass.md` + `specs/`. Not `{KNOWLEDGE_DIR}/`. Worthy content is **promoted**
at iteration-close via `mstar-compound`.

Three operator complaints from 2026-09-26: the metadata the pipeline already fetches and discards, the
downloaded audio's persistence and discoverability, and an output tree that reads as "too scattered".
The first two became plans; the third is a measured survey whose target shape is deliberately left open (D8).

## Orientation

- `delivery-compass.md` — the entry point: scope, decisions D1–D15, acceptance criteria, non-goals,
  milestones, branch policy, and the concurrency rule that governs Phase 2. **Read this first.**
- `specs/metadata-coverage-contract.md` — what metadata is admitted and at what grain; the five-hop rule and
  the schema-evolution constraint (`CREATE ... IF NOT EXISTS` only, no migration path) that forces child
  tables instead of widened columns.
- `specs/audio-retention-contract.md` — the retention chain **as shipped** (retention is already the default;
  this iteration does not change it), the inventory gap, and the two coverage holes actually being closed.
- `specs/output-layout-options.md` — the measured survey: what is written today, the two-naming-rules defect,
  what constrains any new shape, three candidate targets with measured cost, and the open decision.

## Status at 2026-09-26

- Compass is **`locked`**; the Phase-1 review-and-edit chain ran all three seats and cleared every marker.
- Two plans are registered — `20260926-video-metadata-enrichment` (first in the capacity order, D13) and
  `20260926-audio-inventory`. Neither is dispatched.
- **Phase-2 write dispatch is serial behind `iter-2026-09-qwen3-asr-closeout`** — see the compass
  `## Blocked By`. That rule is a scheduling constraint, not a technical blocker.
- **Still owed by the operator:** the layout shape decision (compass Q4–Q6). It blocks only a third plan,
  which was never written; see `specs/output-layout-options.md` §5.

## Promotion log (annotated at iteration-close)

| Source | Promoted to | Date | Notes |
|--------|-------------|------|-------|
| compass D16 + SDD Task 3 evidence | `.mstar/knowledge/best-practices/degradation-vs-observation-third-state.md` | 2026-09-27 | The `None` vs `()` third-state ruling and the two-run seeded-store degradation test |
| `specs/audio-retention-contract.md` §3 (field semantics) | `.mstar/knowledge/architecture-patterns/audio-evidence-queue-contract.md` | 2026-09-27 | The both-UNIQUE constraint and in-place UPDATE rule are the substrate the queue-cutover §4c ruling builds on (cross-iteration reference, not a rewrite) |
| `specs/output-layout-options.md` | — | 2026-09-27 | Keep snapshot: the survey is the deliverable but the target shape is undecided (D8, Q4–Q6 open); a layout decision followed by a migration plan is the promotion trigger |
| `specs/metadata-coverage-contract.md` | — | 2026-09-27 | Keep snapshot: the five-hop rule and schema-evolution contract are iteration-scoped; a future metadata addition plan is the promotion trigger |
