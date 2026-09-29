# Hotword acronym precision: drop `ITEM`/`AITEM`, keep the phrase, verify by A/B

> Follow-on to the season E2E (`e2e-23191782-season-7686105`) and to `757baa1`.
> Evidence base: `{WORKFLOW_DIR}/e2e-23191782-season-7686105/reports/e2e.md` → "Text-quality pass".
> Primary knowledge: `{KNOWLEDGE_DIR}/architecture-patterns/run-scoped-asr-provenance.md` (the nine-key
> provenance contract; `asr_hotwords` records the list actually used, which is what makes the A/B legible).
> Execution mode: `inline` — one constant edit, one documentation edit, one bounded A/B.

## Status

- Priority: P2 (quality precision on the corpus's most valuable content — the English quotes)
- Task category: `logic` / ASR decoding configuration + verification
- Status: Done
- Owner: fullstack-dev · QA gate: pm-acceptance (the A/B **is** the acceptance evidence)
- Findings cleanup: allow-residual (N-4 and R3 are expected to survive in modified form)
- Depends on: `757baa1` (the Chinese homophone block, which shares this constant)

## Goal

Stop the two bare acronyms from hijacking English words in the Hegel quotes, keep the spelled-out
phrase that shows no measured harm, rely on the existing confidence signal rather than a new mechanism
for whatever interference remains, and settle the question with an A/B on the lecture that carries most
of the damage.

## Specify (measured defects)

- **D1 — the acronyms corrupt English quotes.** Across the 14 archived lectures, `ITEM`/`AITEM` appear
  **9 times inside passages where Hegel's English is being read aloud**, where the original was almost
  certainly another English word: `THE ITEMthat's the question is anITEM ONE` (conf 0.404),
  `This is expressed in the finite on the AITEM` (0.470), `EMERGE IN THE ABSTRACT SIGNIFICANCE OF ITEM
  NOTHING` (0.275), `S呃，AITEM determined B啊。` (0.033), `就是WHAT IS POSITIVE ITEM` (0.040),
  `In accessible AITEM distance outside` (0.239), `AS A PREDEAL ITEM` (0.257),
  `IT REMAINSTHE OTHER ITEM REMAINS` (0.375). Item `BV19hG56hEfV.p2` carries **5 of the 9**.
- **D2 — the phrase is not implicated.** `International Employment Matters Tribunal` appears 3 times,
  genuine each time (he is explaining the name), and the 5 Chinese-narration occurrences are mostly
  genuine (he discusses his own project). The damage tracks the **bare acronyms**, not the phrase.
- **D3 — the benefit side is unreproducible.** The entries exist because `BV1eGJ46mEHQ` mangled the
  acronyms into `TEM`/`AITM`/`ITM` (measured 2026-09-14) — and that video no longer has audio, so the
  benefit cannot be re-measured on this host. The harm can (D1), on a lecture whose audio is one
  re-download away.
- **D4 — removal creates no blind spot.** 8 of the 9 D1 cues carry confidence **below**
  `LOW_CONFIDENCE` (0.033–0.375), so `asr_low_confidence_at` and the CSV stderr surface already reach
  this class. Contrast the Chinese homophone class (R3), which is *confidently* wrong (1 of 78 flagged).
- **D5 — no test pins the entries.** `grep '"ITEM"\|"AITEM"' tests/` returns nothing; the hotword tests
  compare dynamic slices against `DEFAULT_HOTWORDS`, so the edit is test-neutral by construction.

## Clarify (decisions)

1. **Remove exactly `ITEM` and `AITEM`.** Keep `International Employment Matters Tribunal`,
   `International`, `Employment`, `Tribunal` — three of three genuine, no measured harm. The list goes
   from 35 entries to 33 (29 Chinese + 4 Latin).
2. **Keep the confidence fallback as it is; do not add a mechanism.** "Rely on confidence" is a
   *documented contract*, not new code: the positions are already in `asr_low_confidence_at` and on
   stderr in the CSV quality path (`9c385cc`). T2 writes that down where a reader will look.
3. **The A/B re-adds the acronyms through the existing environment knob.** `_extra_hotwords` skips terms
   already in `DEFAULT_HOTWORDS`, so after T1 sets `BILI_ASR_HOTWORDS=ITEM,AITEM` reproduces the
   pre-change list. No test-only code path, and the `asr_hotwords` frontmatter field proves which list
   each root actually used.
   - **Fidelity caveat, stated up front:** the env path appends after the defaults, so the A/B
     reproduces the pre-change *set* but not its *order* (the acronyms were originally first among the
     Latin block). The measured harm is about an entry's **presence** pulling a shard to itself, not
     about its position, so the comparison remains valid for the claim being tested; if the A/B comes
     out ambiguous, order becomes the next hypothesis rather than an assumption.
4. **Two fresh archive roots, one row each.** The archived part's audio was reclaimed by design, so the
   A/B re-downloads `BV19hG56hEfV.p2` (71.4 min, ≈35 MB) — once per root, because a single root cannot
   hold two transcripts at the same stem. The row's `cid`/`duration_s`/`page_label` are copied from the
   season manifest rather than re-derived (they are already verified against Bilibili).
5. **Residual bookkeeping at close.** N-4 is updated with the A/B result; whether it closes depends on
   the result (see Verification). R3 (the Chinese homophones) stays open — `BV19hG56hEfV.p2` contains
   neither `扬弃` nor `阳气`, so this A/B says nothing about it; its target remains `BV1H69sB6EeF` (57
   mis-renderings).

## Tasks

### Task 1: Drop the two bare acronyms

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/asr.py` (`DEFAULT_HOTWORDS` + its evidence comment)
- Modify: `bilibili-asr-archive/README.md` (the hotword paragraph)

**Interfaces:**
- Consumes: nothing; the list is a module constant read by `default_config()`.
- Produces: a 33-entry `DEFAULT_HOTWORDS` whose Latin block is the four phrase words only.

- [x] Remove the `"ITEM"` and `"AITEM"` entries.
- [x] Rewrite the Latin block's comment: keep the 2026-09-14 measurement that motivated the entries,
      then record why the acronyms left (D1's counts, the 8-of-9 low-confidence fact), and state that
      the phrase stays because it shows no harm. Do not delete the history — a future reader must see
      both the benefit claim and the harm measurement.
- [x] Update the README paragraph the same way, keeping the "unverified benefit" honesty for whatever
      remains (the phrase).
- [x] Confirm no test, fixture, or other source file references the two entries.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest -q tests/test_asr_reproducibility.py`

### Task 2: Write down the confidence fallback (no code change)

**Files:**
- Modify: `bilibili-asr-archive/README.md`

**Interfaces:**
- Consumes: the existing `asr_low_confidence_at` / `asr_low_confidence_cues` keys and the CSV stderr
  surface shipped in `9c385cc`.
- Produces: a stated division of labour between the two instruments.

- [x] State the division: **confidence catches what the model doubts** (unclear audio, English
      passages, and hotword interference — 8 of 9 measured), **the hotword list is the only lever for
      what it does not doubt** (Chinese homophones — 1 of 78 flagged).
- [x] Name the operator path explicitly: `bilibili-asr coverage --quality --format csv` prints every
      low-confidence position on stderr, so residual interference after T1 is findable without new
      tooling. Point at the archived keys (`asr_low_confidence_at`) for the same facts per row.
- [x] No new flag, key, or endpoint. If a reviewer proposes one, that is a separate plan.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest -q` (documentation-only change; suite must
stay green at 1576 passed / 4 skipped)

### Task 3: A/B on `BV19hG56hEfV.p2` (the verification)

**Files:**
- Create (target host, scaffolding — not the repository): `/root/e2e-asr/ab-hotwords/{new,old}/`
  archive roots with a one-row manifest each, plus an `ab.sh` driver beside the existing
  `run_e2e.sh`.

**Interfaces:**
- Consumes: the same row (`BV19hG56hEfV:p2`, cid 38991823624, 4284 s) copied from the season manifest;
  the GPU venv and `HSA_ENABLE_DXG_DETECTION=1`; the pre-change list via `BILI_ASR_HOTWORDS=ITEM,AITEM`.
- Produces: two transcript bundles for the same audio, differing only in the hotword list, plus a
  written comparison.

- [x] Root **new**: run with no `BILI_ASR_HOTWORDS` (T1's list). Root **old**: run with
      `BILI_ASR_HOTWORDS=ITEM,AITEM` (the pre-change list). Same part, same model, same device.
- [x] Prove the lists differ as intended from the artefacts, not from the invocation: read
      `asr_hotwords` out of each root's md frontmatter and diff the two strings.
- [x] Measure the primary question: occurrences of `ITEM`/`AITEM` in each root's txt, and specifically
      what happens to the **5 known suspect cues** (611 s, 1329 s, 3093 s, 4060 s, 4126 s) — resolved,
      changed to another word, or unchanged.
- [x] Measure the harmlessness side, which the removal must not destroy: the global diff between the two
      transcripts (identical-character ratio, and the tail-identity check the Latin block's original
      evidence used), plus cue count, mean confidence and the capture ratio for both roots.
- [x] Measure the residual interference on the **old** root only: do the 9 D1 occurrences still carry
      confidence below 0.4 there (i.e. is D4 true in this controlled pair, not just in the season run)?
- [x] Write the comparison into the E2E report as a new section, with the raw counts and cue lists.

Run (sketch — the exact argv is written when the roots are built):
`cd /root/e2e-asr/tools && ./ab.sh new` then `./ab.sh old`

## Verification

- **Suite:** 1576 passed / 4 skipped / 0 failed unchanged (T1 is a constant edit, T2 is prose).
- **A/B decision rules** (written before the run, so the outcome cannot be read backwards):
  - **Confirms removal** if the **old** root contains `ITEM`/`AITEM` inside the English quotes and the
    **new** root does not, the 5 suspect cues resolve to non-acronym text (or change to something that
    is not an acronym), and the two transcripts are ≥95 % identical in the tail check that the Latin
    block's original harmlessness evidence used. → N-4 closes, citing both halves.
  - **Refutes removal** if the new root shows the same 9 occurrences (removal did not help) or the
    global diff shows the acronym entries were doing measurable work elsewhere. → revert T1, keep N-4
    open with the counter-evidence.
  - **Ambiguous** (e.g. the quotes change but the acronyms persist elsewhere): keep T1 (its harm
    evidence already stands on 9 measured cues), keep N-4 open, and state the open question — including
    the order caveat from Clarify §3 — as the next measurement.
- **No E2E beyond this**: the A/B is the bounded verification this plan asked for; no device, browser
  or installed-deployment scenario is added.

## Scope

- **In:** `DEFAULT_HOTWORDS` (two entries), the README hotword paragraph, the A/B scaffolding on the
  target, the residual register (N-4), the E2E report's new section.
- **Out, deliberately:** an A/B for the six Chinese homophones (R3 — needs `BV1H69sB6EeF`, ~114 min of
  audio, a separate run); any change to `asr_low_confidence_at` or the quality surface (T2 is
  documentation); the `_join_text` gluing defect (R6) and the `verify` exit contract (R2) — registered,
  not touched here.

## Evidence log

| Date | Evidence |
|------|----------|
| 2026-09-17 | Season E2E text-quality pass measured D1–D5 (9 English-quote occurrences, 8 below `LOW_CONFIDENCE`, phrase 3/3 genuine, no test coupling). |
| 2026-09-17 | Prerequisites checked: `BV19hG56hEfV.p2` audio reclaimed (re-download required); model `/root/e2e-asr/nano/master` present (2.0 GB); GPU verified by `check-asr-env` exit 0; season manifest still holds the row's real `cid`/`duration_s`. |

## Review Gate Summary

| Gate | Decision | Notes |
|------|----------|-------|
| Task reviews | — | single-plan inline execution |
| Plan QC | — | not required for `inline`; the change is a constant plus prose |
| QA gate | pm-acceptance | the A/B comparison **is** the acceptance evidence, with the decision rules fixed above |

## Completion Report (2026-09-17)

**Result.** All three actions landed. `ITEM` and `AITEM` are gone from `DEFAULT_HOTWORDS` (35 → 33
entries), the confidence fallback is written down as the net for what remains, and the A/B **confirms**
the removal on the part that carried 5 of the 9 season-run occurrences.

**Commit:** `ef5e1e8` (T1 + T2, one constant and one README paragraph; no code change for T2).

**A/B (`BV19hG56hEfV.p2`, 71.4 min, two roots on the target):** lists differed by exactly the two
entries as read from each bundle's `asr_hotwords`; occurrences **0 vs 10**; all five suspect cues
resolved; **96.06 %** identical text (bar ≥95 %); low-confidence cues **39 → 33**; mean confidence
0.747 → 0.751. Two cues improved substantively — `AITEMond` → **`on the other hand`** (1329 s),
`ITEM MOVEMENTS` → **`Idea Moments`** (4060 s) — and none regressed.

**Verification:** suite 1576 passed / 4 skipped at the change. `verify --trusted-local` is not used here
(its exit contract is broken on any normally-produced archive — R2).

**Register:** **N-4 closed** with the A/B as closure evidence, including the qualification that its
original 8-of-9 low-confidence ratio did not reproduce in this narrower run (2 of 5), and a note stating
where the phrase's remaining unverified benefit is documented. `R3` (Chinese homophones) stays open —
this lecture exercises neither `扬弃` nor `阳气`.

**Observed, then registered:** the full suite is intermittently red for no product reason — ~200–260
tests error at setup across many files in some runs, while the same working tree is green in others
(261 / 0 / 196 / 0 errors over four consecutive runs; `tests/test_verify_baseline.py` owns the visible
tail and is 100 % green standalone). Registered as **`20260917-hotword-acronym-precision · R1`** (low).
The entry records what measurement ruled out — `/tmp` space: a full green run moved the 3.7 GiB tmpfs by
only +31.4 MiB against ~1.7 GiB free — and states plainly that the trigger is still unknown, so the next
red suite is not misread as a regression from whatever change is in flight.
