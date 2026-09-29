# iter-2026-09-transcript-projections — iteration package

Charter: close the **projection half** of the medium residual `e2e-23191782-season-7686105 · R1` — a
stored transcript in `archive.db` must be publishable as a complete archive bundle, so the caption path
can produce products at all. The 2026-09-20 live E2E measured why it matters: both named items now
serve AI captions, the chain took its documented subtitles-first branch, and **no row could reach
`archived`** because nothing can project a stored transcript.

**Locked direction (user, 2026-09-20):** one new command projects stored transcripts into the archive
bundle (four artifact families + marker, products under the configured artifact root) and records the
row's state; the ASR/audio chain and its manifest contract are untouched. A small folded-in fix
(`check-asr-env`'s anchor, register row `e2e-23191782-longform-pair-webdav · R1`) rides along in the
same plan. See `delivery-compass.md` `## Decisions` (D1–D14) and `## Open Questions` for the two non-blocking
`PM`-owned items that may cross the lock (the frozen spec's owed revision, and the third documentation claim set
D14 names).

| Path | Purpose | Status |
|------|---------|--------|
| [`delivery-compass.md`](delivery-compass.md) | Steering compass — scope, decisions, open questions, plans, criteria, non-goals, roadmap, risks, branch policy | `status: active`; the PM sets `locked` when the §1.6 chain closes |
| [`specs/transcript-projection-contract.md`](specs/transcript-projection-contract.md) | Iteration-level contract written by the `architect` (candidates/membership, identity + winner rule, ms→s conversion, raw-sidecar and frontmatter key list, recorded state + idempotency, `asr-local`, operator surface, interfaces, risks, validation plan) | **landed** — sealed by the architect round 2026-09-20 (§1–§14); it is the plan's `primary_spec` |
| `guides/` | Operator-facing notes, if the plan produces any | none yet |

Plan: `{PLAN_DIR}/20260920-transcript-projections.md` — the iteration's only plan row
(`Execution: mstar-sdd`, `QA gate: mandatory`, `QA mode: targeted`).

## Promotion log (iteration-close)

Filled at iteration-close by `mstar-compound`; the package's `Promoted to:` trace lives here.
