# iter-2026-09-text-and-ledger-precision — iteration package

Charter: close the four residuals `iter-2026-09-residual-closeout` deferred when its scope was reduced
to one plan on 2026-09-18. Both plans were written, reviewed and locked in that iteration and are
**adopted here unchanged in substance** — only their package references were re-pointed.

**Adoption boundary (what this iteration did and did not do at Phase 1):** the plans' `**Goal:**`,
`**Architecture:**`, Global Constraints, task steps and run commands are the previous iteration's locked
and reviewed text, untouched. This iteration's own Phase-1 chain added only: the re-pointed package
references, acceptance **criteria 1–4** on this compass's own numbering (the previous compass's 6–9 is
retired and is cited nowhere in this package), the corrected serial-scheduling basis, and the re-pointed
deferral records for `R1` plus the three low entries. No technical content was re-derived.

| Path | Purpose | Status |
|------|---------|--------|
| [`delivery-compass.md`](delivery-compass.md) | Steering compass — scope, plans, criteria 1–4, non-goals, roadmap, risk register, branch policy | locking at Phase 1 (chain in progress) |
| `guides/hotword-ab-20260918.md` | The two-arm A/B comparison for the six Chinese homophone hotwords (plan `20260918-transcript-text-precision`, Task 2) | written when that task closes |
| `guides/pilot-attempt-ledger-boundary.md` | The pilot attempt-ledger boundary text destined for `{KNOWLEDGE_DIR}` (plan `20260918-operational-record-coverage`, Task 1) | written when that task closes |
| `specs/` | Empty by design: this iteration writes no iteration-level spec (the cue rule lives in the pinned fixture and the task brief) | n/a |

## Register entries in scope

| Residual | severity | 收口判据 | Plan |
|----------|----------|----------|------|
| `e2e-23191782-season-7686105 · R6` | low | 1 | `20260918-transcript-text-precision` |
| `e2e-23191782-season-7686105 · R3` | low | 2 | `20260918-transcript-text-precision` |
| `e2e-23191782-season-7686105 · R4` | low | 3 | `20260918-operational-record-coverage` |
| `e2e-23191782-season-7686105 · R5` | low | 4 | `20260918-operational-record-coverage` |
| `e2e-23191782-season-7686105 · R1` | medium | — | **out of scope** — next iteration (roadmap, with trigger / owner / done definition) |
| `20260918-verification-surface-truth · R1/R2/R3` | low | — | **out of scope** — latent debt, each with its own trigger / owner / done definition in the compass roadmap |

Register writes are the PM's domain operation: this iteration neither edits
`{PROJECT_DIR}/_default/residuals.json` nor closes anything in it from a leaf task. The four in-scope
entries stay `open` until their own criteria pass.

## Boundaries observed while drafting

- `{KNOWLEDGE_DIR}` is not written during start/execute; plan 2 Task 1 puts its knowledge-destined text
  in `guides/` for `mstar-compound` to promote at iteration-close.
- No iteration-level spec is written; iteration-scoped drafts stay in this package.
- The previous iteration's package (`{ITERATION_DIR}/iter-2026-09-residual-closeout/**`) is a closed
  record: it is cited as the authority for what was deferred and on what terms, and is never edited.
