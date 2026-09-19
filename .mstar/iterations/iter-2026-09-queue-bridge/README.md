# iter-2026-09-queue-bridge — iteration package

Charter: close the medium residual `e2e-23191782-season-7686105 · R1` — the ASR/audio chain must be able
to take its work queue from `archive.db` instead of a hand-built `manifest/manifest.jsonl`. Two of the
three pieces the boundary section names are in scope; the SRT/TXT/MD projection rebuild is not.

**Locked direction (user, 2026-09-19):** the new command `bili-asr derive-manifest --archive-root
<archive-root>` derives manifest rows from the store; the ASR/audio chain keeps reading the manifest, and its
code is not restructured. See `delivery-compass.md` `## Decisions` D1/D2/D8/D9, and `## Open Questions` for
the one item the Phase-1 chain carries past the lock — Q6, owner `PM`, non-blocking.

| Path | Purpose | Status |
|------|---------|--------|
| [`delivery-compass.md`](delivery-compass.md) | Steering compass — scope, decisions, open questions, plans, criteria, non-goals, roadmap, risks, branch policy | `status: active`; the PM sets `locked` when the §1.6 chain closes |
| [`specs/sqlite-queue-bridge-contract.md`](specs/sqlite-queue-bridge-contract.md) | Iteration-level contract written by the `architect` (the bridge contract: queue predicate, row mapping, additive conflict policy, operator surface, validation plan) | architecture locked 2026-09-19; not written to `{SPECS_DIR}` (D6) |
| `guides/` | Operator-facing notes, if the plan produces any | empty |

Plan: `{PLAN_DIR}/20260919-sqlite-queue-bridge.md` — the iteration's only plan row (`Execution: mstar-sdd`,
`QA gate: mandatory`, `QA mode: targeted`), with Tasks 1–4.

## Promotion log (iteration-close, 2026-09-19)

| Source | Promoted to | Date | Notes |
|--------|-------------|------|-------|
| `specs/sqlite-queue-bridge-contract.md` | `.mstar/knowledge/architecture-patterns/queue-derivation-bridge.md` | 2026-09-19 | New architecture pattern, structured rewrite (not a file copy): the queue relation and its one owning call, the single derived status and the filesystem trap it dodges, the additive conflict policy, the effective-key limit (`R2`), the no-back-write rule kept structural. |
| plan `20260919-sqlite-queue-bridge` (Tasks 1–3 + both gate summaries) | `.mstar/knowledge/testing-patterns/absence-assertion-negative-control.md`, `.mstar/knowledge/testing-patterns/zone-independent-time-assertions.md`, `.mstar/knowledge/best-practices/claim-scope-discipline.md` | 2026-09-19 | Three new pattern docs: the negative-control requirement for absence assertions (Task 3), the zone-independent clock construction and its measured counter-example (the `pubdate_str` finding), and the claim-scope class the review round produced. |
| `specs/sqlite-queue-bridge-contract.md` §5/§9 + plan Task 4 | `.mstar/knowledge/architecture-patterns/bilibili-asr-archive-cli.md`, `.mstar/knowledge/architecture-patterns/normalized-transcript-storage.md` | 2026-09-19 | Existing docs updated rather than duplicated: the CLI pattern's projection/feeder bullet now states the shipped enumeration (`derive-manifest`) instead of the deferral it recorded, and the storage doc's known limit names the second consumer of the pending relation and its deliberate reading. |
| `guides/` | — | — | Empty by design (the plan produced no operator-facing guide); nothing to promote. |
| `delivery-compass.md`, `README.md` (this file) | — | — | Iteration steering and package index; kept as the iteration snapshot, excluded from promotion. |

Trace convention: this table is the package's `Promoted to:` record (per the compound skill's iteration
package promotion step 4); the promoted sources above are the ones this iteration's knowledge round drew
from, rewritten into the target docs rather than copied.
