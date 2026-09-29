# iter-2026-09-qwen3-asr-closeout — iteration package

Charter: close out the already-merged Qwen3-ASR-on-transformers engine switch — re-measure the corpus
hotword list under the engine that ships (T5), record the archive's accepted two-engine state where a
frontmatter reader will look (T6), and turn the migration plan's unlocked items into named decisions.

**This is the iteration package.** It is the working set an iteration produces on its way to a permanent
home; it is **not** `{KNOWLEDGE_DIR}` (`.mstar/knowledge/`). Work here earns its place by being
**promoted** at iteration-close, which `mstar-compound` performs into `{KNOWLEDGE_DIR}` — the
`## Promotion log` below records where each promoted piece went. Nothing in this package is a shipped
contract until that promotion happens.

## Orientation

1. [`delivery-compass.md`](delivery-compass.md) — the iteration's steering record: scope, the settled
   decisions (D1–D14, C1–C15), acceptance criteria, non-goals, branch policy and risk register. Read this
   first.
2. [`guides/t5-hotword-measurement-protocol.md`](guides/t5-hotword-measurement-protocol.md) — the
   pre-declared two-arm protocol that fixes T5's arms, command, thresholds and noise floor before any
   arm runs, so a reader can run the measurement and judge it without asking.
3. [`guides/t5-hotword-short-item-dry-run.md`](guides/t5-hotword-short-item-dry-run.md) — a 448 s
   seventh item run outside the frozen corpus to prove the apparatus works on the shipped
   configuration, and what that run did and did not establish (supplementary; not the T5 verdict).
4. [`guides/assets/`](guides/assets/) — the two executable artifacts: `ab-hotwords-qwen3.sh` (the arm
   driver, with the restore encoded in a `trap`) and `census.py` (the `R`/`I`/`U` classifier).
5. [`guides/t5-artifact-audit.md`](guides/t5-artifact-audit.md) — the contract audit of the short-item
   arms: the product's own `verify` (0 defects), 12/12 independently recomputed hashes, four-surface
   agreement, and two observations that are not defects.
6. [`guides/t5-hotword-short-corpus-results.md`](guides/t5-hotword-short-corpus-results.md) — the
   three-item ≤10 min corpus result under the protocol's Amendments 3 / 3a, with the limits that keep a
   PASS from being read as a verdict (written; the run completed).
7. [`guides/t5-hotword-short2-corpus-results.md`](guides/t5-hotword-short2-corpus-results.md) — the
   nine-item ≤10 min corpus result, staged on a local disk after the 123pan mount failed; same limits,
   `E = 3`, and the recorded reason the frozen six cannot run (register row `R3`).
8. [`guides/t5-hotword-measurement-results.md`](guides/t5-hotword-measurement-results.md) — **the T5
   verdict.** The frozen six-item corpus, `PARTIAL`: `R = 0`, `I = 0`, P6 fails on one hand-read outlier
   (a prompted-arm degeneration loop), P3/P4/P7/P8/C4 pass. Read §1 first — the audio is a re-fetch.

`specs/` is empty in this iteration: the closeout owed no iteration-level spec, and the frozen warehouse
spec `.mstar/specs/asr-archive-cli.md` is left as written — the compass's row C9 records why. What each
package directory is for is defined once in the compass's `## Iteration package`.

The plan this package serves is `.mstar/plans/20260924-qwen3-asr-transformers.md`; the package's index
entry is the `iter-2026-09-qwen3-asr-closeout` row in `.mstar/iterations/README.md`.

## Promotion log (iteration-close)

Filled at iteration-close by `mstar-compound`; each promoted piece's `Promoted to:` trace lives here.

The first four rows are that round (**2026-09-26**, described in the compass's
`## Compound Round Summary`). The last two come from a **later, separate** round: the plan
`20260927-aac-decode-contract` and PR #20's review findings (2026-09-27), which touched two docs this
package's work is connected to but which the iteration close predates. They are listed here rather than
only on the plan's workflow because this table is where a reader looks for "what did this iteration's
work turn into"; the dating column keeps the two rounds distinguishable, and the compass deliberately
still describes only the first.

| Source | Promoted to | Date | Notes |
|---|---|---|---|
| `guides/t5-hotword-measurement-results.md` | `.mstar/knowledge/testing-patterns/hotword-list-measurement.md` | 2026-09-26 | The verdict's method content: the negative result on the frozen six (`R=0`, `I=0`), the `E=7` interpretive floor, the prompted-arm degeneration, the byte-anchored restore correction, and five further traps. Source carries its own `Promoted to:` marker. |
| (the codec defect and the hotword-list restoration, carried by this package's plan and compass) | `.mstar/knowledge/best-practices/premise-freshness-before-lock.md` | 2026-09-26 | The same premise principle's **irreversible** case: probe before you delete, prefer reuse over rebuild, and why a cached listing is not evidence of a readable source. |
| `guides/assets/ab-hotwords-qwen3.sh`, `guides/assets/census.py` | named as referenced tooling in `.mstar/knowledge/testing-patterns/hotword-list-measurement.md` | 2026-09-26 | **Promoted as references, not as copies** — the knowledge doc names them as the reusable arm driver and classifier; the files stay in this package. |
| `guides/t5-hotword-measurement-protocol.md`, `…-short-corpus-results.md`, `…-short2-corpus-results.md`, `…-short-item-dry-run.md`, `…t5-artifact-audit.md`, this `README.md` | — (kept) | 2026-09-26 | Keep snapshot. The protocol's pre-declared clauses P1–P9 and the substitute-corpus records belong to this measurement; their shared lesson is the promoted row above. |
| PR #20's review rounds — the plan `20260927-aac-decode-contract`, **not** this iteration's plan | `.mstar/knowledge/architecture-patterns/wsl-rocm-gpu-asr.md` | 2026-09-27 | Guidance item 2b: `accelerate` requires `torch` with no marker, and a lock file is a second declaration that `uv sync` reconciles *to* — so a lock naming the default-index CUDA wheel overrides the deliberate omission rather than lagging it. |
| PR #20's review rounds | `.mstar/knowledge/testing-patterns/absence-assertion-negative-control.md` | 2026-09-27 | Four instances of the doc's own failure wearing the **opposite sign**: presence assertions whose fixture cannot see the value change (a skip that went green on the surface under repair; a `*args, **kwargs` double; set-membership on an ordered argv; a new exception class with no test). |
