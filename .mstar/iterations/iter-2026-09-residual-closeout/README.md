# iter-2026-09-residual-closeout — iteration package

Charter: close the 6 open register residuals that are *not* the architecture migration
(`e2e-23191782-season-7686105 · R1` is deferred to its own iteration — see the compass
`## Roadmap Position`).

## Documents

| Path | Purpose | Status |
|------|---------|--------|
| [`delivery-compass.md`](delivery-compass.md) | Steering compass — scope, plans, acceptance criteria, non-goals, branch policy | active (chain complete; PM lock pending) |
| [`specs/manifest-well-formedness.md`](specs/manifest-well-formedness.md) | The locked definition of manifest well-formedness shared by all three readers (plan 1's spec baseline; closes `R2`) | draft → reviewed at §1.6 |
| `guides/` | Exploration and process notes; `guides/hotword-ab-20260918.md` is written by plan 2 Task 2, and `guides/pilot-attempt-ledger-boundary.md` by plan 3 Task 1 | created as tasks close |

## Register entries in scope

| Residual | severity | Plan |
|----------|----------|------|
| `e2e-23191782-season-7686105 · R2` | high | `20260918-verification-surface-truth` |
| `20260917-hotword-acronym-precision · R1` | low | `20260918-verification-surface-truth` |
| `e2e-23191782-season-7686105 · R6` | low | `20260918-transcript-text-precision` |
| `e2e-23191782-season-7686105 · R3` | low | `20260918-transcript-text-precision` |
| `e2e-23191782-season-7686105 · R4` | low | `20260918-operational-record-coverage` |
| `e2e-23191782-season-7686105 · R5` | low | `20260918-operational-record-coverage` |
| `e2e-23191782-season-7686105 · R1` | medium | **out of scope** — next iteration (roadmap) |

## Boundaries observed while drafting

- `{KNOWLEDGE_DIR}` is not written during start/execute; the knowledge-destined text produced by plan 3
  Task 1 lives in `guides/` and is promoted by `mstar-compound` at iteration-close.
- Iteration-scoped drafts stay in this package, never in `{SPECS_DIR}`.
