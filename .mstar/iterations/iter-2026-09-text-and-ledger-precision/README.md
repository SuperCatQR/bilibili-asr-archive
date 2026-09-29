# iter-2026-09-text-and-ledger-precision — iteration package

Charter: close the residuals `iter-2026-09-residual-closeout` deferred when its scope was reduced
to one plan on 2026-09-18. Both plans were written, reviewed and locked in that iteration and are
**adopted here unchanged in substance** — only their package references were re-pointed.
**Amended 2026-09-18, mid-Execute:** the cue-writer criterion was **retired on evidence** (plan 1
Task 1 returned `NEEDS_CONTEXT` at its own Step-1 exit; `R6` stays open) and the live criteria were
renumbered **1–3**. Plan 1's remaining criterion (`R3`) was discharged the same day.

**Adoption boundary (what this iteration did and did not do at Phase 1):** the plans' `**Goal:**`,
`**Architecture:**`, Global Constraints, task steps and run commands are the previous iteration's locked
and reviewed text, untouched. This iteration's own Phase-1 chain added only: the re-pointed package
references, acceptance **criteria 1–3** on this compass's own numbering (the previous compass's 6–9 is
retired and is cited nowhere in this package; the live set lost one number again when the cue criterion
was retired), the corrected serial-scheduling basis, and the re-pointed deferral records for `R1` plus
the three low entries. No technical content was re-derived.

| Path | Purpose | Status |
|------|---------|--------|
| [`delivery-compass.md`](delivery-compass.md) | Steering compass — scope, plans, criteria 1–3, non-goals, roadmap, risk register, branch policy | locked at Phase 1; amended mid-Execute (see `### Scope changes`); **Keep snapshot** (iteration steering record, excluded from promotion by default) |
| `guides/hotword-ab-20260918.md` | The two-arm A/B comparison for the six Chinese homophone hotwords (plan `20260918-transcript-text-precision`, Task 2) | **written** (2026-09-18, 505 lines, incl. the host-evidence appendix); **Promoted to:** `.mstar/knowledge/testing-patterns/hotword-list-measurement.md` (structured rewrite: method, findings, limits, traps) |
| `guides/pilot-attempt-ledger-boundary.md` | The pilot attempt-ledger boundary text destined for `{KNOWLEDGE_DIR}` (plan `20260918-operational-record-coverage`, Task 1) | **written** (2026-09-18, 189 lines; carries the shipped text, its contract target and the three plan checks before/after); **Promoted to:** `.mstar/knowledge/architecture-patterns/operational-sidecars.md` (two new sections: the attempt-ledger writer boundary; a run that records its own interruption) |
| `specs/` | Empty by design: this iteration writes no iteration-level spec. The cue rule that would have been the one durable contract here was **retired on 2026-09-18** (evidence base absent), so nothing is owed | n/a |
| `README.md` (this file) | Iteration package index — charter, adoption boundary, package contents, register entries in scope, boundaries observed | **Keep snapshot** (package index, not promoted) |

**Promotion disposition (iteration-close, 2026-09-18):** both `guides/` entries were **Promoted** (the
hotword A/B guide rewritten as the new `testing-patterns/` doc; the pilot boundary guide's material
rewritten into two sections of the existing operational-sidecars doc) — nothing in this package was
**Skipped**, and the two snapshot-only files stay iteration history (marked in the table above).

## Register entries in scope

| Residual | severity | 收口判据 | Plan |
|----------|----------|----------|------|
| `e2e-23191782-season-7686105 · R6` | low | —（判据已退役；条目保持 open） | `20260918-transcript-text-precision`（Task 1 因证据不足退役） |
| `e2e-23191782-season-7686105 · R3` | low | 1（2026-09-18 已闭环） | `20260918-transcript-text-precision` |
| `e2e-23191782-season-7686105 · R4` | low | 2（2026-09-18 已闭环，**操作员面结案**；知识半部交 compound） | `20260918-operational-record-coverage` |
| `e2e-23191782-season-7686105 · R5` | low | 3（2026-09-18 已闭环，范围限定 `run` 入口） | `20260918-operational-record-coverage` |
| `20260918-transcript-text-precision · R1` | low | —（本迭代新登记：A/B 未触发的那五个中文热词） | 本迭代 plan 1 闭环时登记，见 compass `## Roadmap Position` ⑤ |
| `20260918-transcript-text-precision · R2` | low | —（`waived`：冻结实现者报告的占位符，理由 + 重开条件齐备） | 同上 |
| `20260918-operational-record-coverage · R1`–`R4` | low | —（QC 波次新登记，均 `defer`） | `20260918-operational-record-coverage` QC 门禁；逐条见 compass `## Quality Gate Summary` |
| `e2e-23191782-season-7686105 · R1` | medium | — | **out of scope** — next iteration (roadmap, with trigger / owner / done definition) |
| `20260918-verification-surface-truth · R1/R2/R3` | low | — | **out of scope** — latent debt, each with its own trigger / owner / done definition in the compass roadmap |

Register writes are the PM's domain operation: this iteration neither edits
`{PROJECT_DIR}/_default/residuals.json` nor closes anything in it from a leaf task. Final status
(2026-09-18): `R3`, `R4` and `R5` **closed** (all three verified closes — `R4` as an operator-surface
close whose knowledge half is handed to `mstar-compound` at iteration-close, `R5` scoped to the `run`
entry point); `R6` **open** (criterion retired, entry deferred with its unblock recorded); and five
new `defer` rows registered by this iteration's own gates — plan 1's successor `R1` (the five terms the
A/B did not exercise) plus plan 2's `R1`–`R4` (the writer set, the pre-guard window, the timestamp
comparison, and the SIGINT clause window) — with plan 1's `R2` **waived** (the frozen report's
placeholders, reason and re-open trigger recorded). Open set at close: **medium 1 / low 9**.

## Boundaries observed while drafting

- `{KNOWLEDGE_DIR}` is not written during start/execute; plan 2 Task 1 puts its knowledge-destined text
  in `guides/` for `mstar-compound` to promote at iteration-close.
- No iteration-level spec is written; iteration-scoped drafts stay in this package.
- The previous iteration's package (`{ITERATION_DIR}/iter-2026-09-residual-closeout/**`) is a closed
  record: it is cited as the authority for what was deferred and on what terms, and is never edited.
