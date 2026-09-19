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
