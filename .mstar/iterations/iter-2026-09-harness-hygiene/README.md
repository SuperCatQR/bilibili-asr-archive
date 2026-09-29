# iter-2026-09-harness-hygiene — iteration package

Package document index for `iter-2026-09-harness-hygiene`. The iteration state SSOT is
`delivery-compass.md` (frontmatter `status`); this file is an index, not a register —
document ownership lives in the `{HARNESS_DIR}/store.db` catalog, and
`{ITERATION_DIR}/README.md` is prose orientation only.

**Local process artifacts.** D11 keeps the iteration *process face* out of the published set:
a clone carries `specs/**` from this package and nothing else here. `delivery-compass.md`,
this README, and `guides/**` resolve locally, by design.

| Path | Contents | Editing roles |
|------|----------|---------------|
| `delivery-compass.md` | Iteration state SSOT: scope, plans table, decisions D1–D12, acceptance criteria, branch policy, close summaries | product-manager, architect |
| `guides/architect-phase-1-review-20260928.md` | The four Phase 1 gaps and how each was ruled (D9–D12): the gap text, the corrected premise, the establishing command | architect |
| `guides/` | Further iteration-level exploration and process notes that are not long-lived contracts | product-manager, architect |
| `specs/` | Iteration-scoped spec drafts. Empty today — both plans work from `{SPECS_DIR}/asr-archive-cli.md`. Long-lived specifications stay in `{SPECS_DIR}/` | product-manager, architect |
| `README.md` | This file — prose index. Not a register, and not a one-row-per-document table | writing-specialist |

## Phase 1 review chain

| Round | Seat | Outcome |
|-------|------|---------|
| 1 | product-manager | Compass + both plans drafted; Q1 ruled (field-complete the 23 pre-contract residual entries — compass **D7**) |
| 2 | architect | Four gaps ruled against the disk: **D9** register write path, **D10** worktree ownership metadata, **D11** published-vs-local boundary, **D12** deletion archive. Narrative in `guides/architect-phase-1-review-20260928.md` |
| 3 | writing-specialist | Corpus hygiene and prose pass over the compass, both plans, and `.mstar/AGENTS.md`; review narrative moved out of the compass into `guides/`; package README written |

No `TODO(owner: …)` marker survives any of the three rounds.

## Promotion

`mstar-compound` at iteration close (`mstar-iteration` §3.2) reads this package and promotes
what is worth keeping into `{KNOWLEDGE_DIR}/`, rewriting rather than copying. Source files are
kept as iteration history and gain a `Promoted to:` note when that happens.
