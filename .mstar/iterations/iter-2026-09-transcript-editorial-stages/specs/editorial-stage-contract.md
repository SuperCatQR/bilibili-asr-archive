# Stage contract: 校对 (proofread) + 精校 (reading edition)

> **Status: draft** — the iteration-scoped spec under Phase-1 chain review (product-manager →
> architect → writing-specialist). Section-owned gaps carry `TODO(owner: …)`; the marker syntax is
> defined in `mstar-iteration/references/phase-1-prepare.md` §1.3(iii).
>
> **Scope**: what the two stages *are*, what the mechanical half must prove, what the agent half must
> do, and the line between them. Command names/flags/summary live in the plans' operator-surface sections
> and are fixed by compass **D11**.

## §C. Shared: the two routes and the base

- The **proofread base** is produced by reading both machine transcripts route-by-route and adjudicating
  every divergence on record.
- **Both routes are machine transcripts; neither is ground truth.** The caption route is *not* a
  reference: no measurement makes either route one — they are two independent machine transcripts of the
  same audio, and the repo's own cross-system comparison is a *floored, capped agreement* measure rather
  than a verdict on which side is correct (`REFERENCE_AGREEMENT_FLOOR = 0.95`, `quality.py:58`;
  `coverage --reference` refuses any pair whose flattened transcript exceeds
  `_MAX_COMPARE_CHARS = 20 000` instead of comparing it, `quality.py:104`/`:549`). The wave adjudicated
  divergences item by item (`README-reading-edition.md`, the `此在` case D4 rests on), never by trusting
  one side: the contract must never imply one route is truth, and never cite a route as the other's
  yardstick.
- **The store is the SSOT for transcript text** where one exists; loose JSON is not.

## §A. Proofread stage (校对)

- **Inputs**: one stored part's ASR transcript + its caption transcript (both routes), read read-only.
- **Product**: a candidate markdown carrying — frontmatter with the measured counts; an H1; one `>`
  legend; body paragraphs; a `## 校对记录` table (**one row per change, deletions included**); and the
  per-item disposition table for cues the builder could not attach.
- **Mechanical half (shipped, tested)**:
  1. **Alignment accounting** — every ASR segment and every caption cue appears in exactly one bucket
     (attached / unattached) and the counts are printed. *The failure this closes is recorded: a midpoint
     scheme dropped 251/9607 cues silently (`20260922-proofread-wave · R2`).*
  2. **Marker vocabulary + parity** — one normalised rejection mark; body marks equal record rows.
  3. **Containment** — candidate body characters ⊆ (ASR ∪ caption ∪ explicit annotation); a character in
     neither route is either an inference (must be annotated) or a defect.
  4. **Hotword screen** — no `provenance.hotwords` token may appear where the routes disagree unless the
     record names it as an inference (`20260922-proofread-wave · R1`'s signature).
- **Agent half (protocol, not code)**: adjudicate each divergence; record evidence per change; never
  complete a hotword phrase to make a sentence read; `claim-scope-discipline.md` applies to the record.

## §B. Edition stage (精校)

- **Input**: a proofread base (single file or parts) + both routes.
- **Product**: a reading edition — no timestamps; filler/stutter/repeat/noise deleted; clause order and
  paragraphing repaired; **laughter, mood vocalisations, `哎/唉`, and coarse register retained**; nothing
  added; every inference in appendix A, every undecidable spot as `〔?〕` + appendix B.
- **Mechanical half (shipped, tested)**:
  1. **No timestamps** in the body.
  2. **Containment** against base **and** routes (a character absent from all three is a defect).
  3. **Zero unexplained insertions** (per-character).
  4. **Every deletion classified** — filler·noise / adjacent-repeat-with-retained-twin / fragment — with
     the **term guard**: a deletion whose core is a term the base uses is a **refusal**, never a repeat.
     *This is the `此在` blind spot, measured 2026-09-23.*
  5. **Marker parity**; **seam checks** and **byte-exact concatenation** for multi-part candidates.
- **Agent half (protocol, not code)**: the polish level is judgement (what reads as filler); the
  protocol states the boundary (vocabulary unchanged, propositions not merged, register not raised) and
  the inference rule (only when the context forces exactly one reading).

## §D. What neither half proves

- No audio was listened to; the routes are both machine output.
- A `〔?〕`/`‹?›` site remains undecided by construction; the verifiers prove it is *marked*, not resolved.
- The verifiers check **bytes and record**, never the interpretation.

## §E. Refusal taxonomy (what a verifier may refuse, and how)

The rule vocabulary D11(c) leaves open is fixed here. Each row is a rule the mechanical half can decide
from **bytes + the record** alone; the print forms (`refused (<rule>) at <location>` /
`warning (<rule>) at <location>`) and the exit values are D11(c)(d) and are not re-opened.

| rule id | what it proves | class | message carries |
|---|---|---|---|
| `accounting_invalid` | the builder's own identity holds — `segments_in == segments_attached + segments_unattached` and the same for cues (proofread builder + proofread verifier) | error | the counts row `<path>:<line>`, else the `[hh:mm:ss]` / cue index that fell out of every bucket |
| `marker_parity` | every body rejection mark is in the one normalised vocabulary, and body marks == `## 校对记录` rows | error | the offending mark at `<path>:<line>`, or the two counts |
| `evidence_missing` | a record row that asserts a change names its evidence (a route location/span, or an explicit inference annotation) | error | the row `<path>:<line>` |
| `char_outside_routes` | every body character is in ASR ∪ caption ∪ explicit annotation | error | the first offending character, `<path>:<line>` |
| `hotword_disagreement` | no `provenance.hotwords` token sits where the two routes disagree unless the record names it as an inference (`20260922-proofread-wave · R1`'s signature) | error | the token + the `[hh:mm:ss]` / cue index |
| `timestamp_in_body` | the edition body carries no cue timestamp | error | the timestamp at `<path>:<line>` |
| `insertion_unexplained` | every body character absent from base ∪ routes has an annotation or a record row (checked **per character**) | error | the first unexplained character, `<path>:<line>` |
| `deletion_unclassified` | every deletion carries exactly one of filler·noise / adjacent-repeat-with-retained-twin / fragment | error | the deletion's `<path>:<line>` in the base |
| `term_guard_tripped` | a deletion's core is **not** a term the base uses — the `此在` blind spot: this is an **error, never a repeat** | error | the term + the base location that uses it |
| `twin_not_retained` | a deletion classified adjacent-repeat-with-retained-twin has that twin locatable in the body | error | `<path>:<line>` where the twin should be |
| `seam_break` | parts join at the declared seam — the last block of part *i* and the first block of part *i+1* join, with no block dropped at the join | error | `<part_i> → <part_i+1>` and the `<path>:<line>` of the break |
| `concat_mismatch` | the candidate body is the byte-exact concatenation of its declared parts | error | the first differing offset, `<path>:<line>` |
| `identity_mismatch` | the candidate's own frontmatter `work_id`/`bvid` equals the selector (D11(b)'s shipped `coverage --quality` discipline) | error | the two values + `<path>:<line>` |
| `part_missing` | every `--base`/`--part` the candidate declares exists and is readable | error | the missing path |
| `route_absent_for_part` | builder only: a part inside the range holds **both** routes — a part holding one is skipped, never silently aligned | advisory | the part + which route is absent |
| `hotword_screen_vacuous` | proofread only: the sidecar's `provenance.hotwords` was non-empty and its tokens occur in the routes, so `hotword_disagreement` could actually bite | advisory | the part + `hotwords=0`, or the token seen in neither route |

**Errors vs advisories** — an **error** is a rule whose violation makes the candidate an untrue statement
about its own inputs (the arithmetic, the containment, the parity, the guard or the identity is broken, so
its bytes cannot be trusted); an **advisory** leaves every byte accounted for — a range member was skipped,
or a screen could not bite — so refusing on it would fake a defect and hide that the check was vacuous.
Errors exit `1`; advisories print `warning (<rule>) at <location>` and change neither the per-candidate
verdict nor the exit (the shipped defect-vs-advisory split of `coverage --quality`, `README.md:672-679`).

**Exit stance (restated, unchanged)** — `0` when every candidate is aligned/ok, **including zero
candidates**; `1` for a configuration error and for any candidate the command refused; **`2` is never
produced** — no socket is opened and `_UsageErrorArgumentParser` maps argparse's own usage exit to 1
(`cli.py:83-92`). No new exit code is introduced for `align-transcripts` / `verify-proofread` /
`verify-reading-edition`; D8's taxonomy stands.

**Not in this taxonomy** — `unknown --bvid <value>` and an unreadable `--candidate` are *configuration*
errors: they print in the shipped `<command>: …` usage form, carry no rule id, and are never a
`refused (<rule>)` line (D11(b)(d)). A rule id is reserved for a finding about a candidate, so no rule
here is invented that the mechanical half could not decide from bytes and the record.

## §F. Behaviour or protocol?

The boundary D2 rests on. Left column is what a shipped command proves deterministically and the test
suite covers; right column is contract text an agent must follow and **no command may enforce**.

**Command behaviour (deterministic, tested)**

1. The alignment accounting identity and the printed accounting line (`accounting_invalid`).
2. Containment — proofread against ASR ∪ caption (`char_outside_routes`); edition against base ∪ routes
   (the `insertion_unexplained` half).
3. Insert / delete classification counts, and the per-character insertion check.
4. The term guard and the retained-twin locatability check (`term_guard_tripped`, `twin_not_retained`) —
   the two mechanical halves of the `此在` blind spot.
5. Marker vocabulary + parity between body marks and record rows (`marker_parity`).
6. Seam checks and byte-exact concatenation for multi-part candidates (`seam_break`, `concat_mismatch`).
7. Timestamp absence in the edition body (`timestamp_in_body`).
8. Identity match between the candidate's frontmatter and the selector (`identity_mismatch`).
9. Presence and readability of the base and part files (`part_missing`).
10. The **mechanical half** of the hotword screen: the token set read from `provenance.hotwords`, the two
    route token sets, the disagreeing span, and the vacuity advisory (`hotword_disagreement`,
    `hotword_screen_vacuous`).
11. The print forms themselves — verdict / refusal / advisory lines, the counts line, the exit stance.

**Agent protocol (contract text only)**

1. Reading the two machine routes and **adjudicating every divergence on record**: the builder attaches
   and accounts; it never decides which route is right (§C — neither route is ground truth).
2. The polish-level judgement — what reads as filler, stutter, repeat or noise at this register.
3. What counts as an inference, and the inference rule: **only when the context forces exactly one
   reading**.
4. Never completing a hotword phrase to make a sentence read (`20260922-proofread-wave · R1`'s signature) —
   the command checks that such a token is *recorded*, not that the phrase reads well.
5. The edition's boundary statement — vocabulary unchanged, propositions not merged, register not raised;
   laughter, mood vocalisations, `哎/唉` and coarse register retained.
6. What a `## 校对记录` row's **prose may claim** (`claim-scope-discipline.md` applied to the record): the
   command proves evidence is *named* (`evidence_missing`), never that it *supports* the claim.
7. Whether a site is undecidable and therefore marked (`〔?〕` + appendix B, `‹?›`): the commands prove the
   mark is **present**, never that it is warranted (§D).

**The one-line rule that keeps D2 honest:** *a command may refuse only what it can show from the bytes and
the record; anything requiring a reading of the speech stays in the protocol.*

### §F.1 Alignment persistence (Q4 → D16)

**Ruling: the builder persists its artifact — JSONL, one file per selected part, at
`<artifact-root>/alignments/<work_id>.jsonl`.** `<artifact-root>` is the configured artifact root
(D11(e)); the file sits **below the archive root's sidecar surface and never under
`transcripts/{srt,txt,md,raw}`** — those four are the product families, and the bundle marker is what
proves them complete, so adding a fifth family there would make `archive_bundle_complete` lie (it would
report the bundle complete while every alignment file could be absent). Keeping alignments under the
artifact root puts the record beside the archive without joining the product families. Line 1 is a header
record — `{"kind":"header","work_id":…,"bvid":…,"part":…,"blocks":…,"segments_in":…,"segments_attached":…,
"segments_unattached":…,"cues_in":…,"cues_attached":…,"cues_unattached":…}` — and every following line is
one input unit: `{"kind":"segment"|"cue","at":<[hh:mm:ss]|cue index>,"attached":<block index|null>,
"evidence":"<route span>"}`. **JSONL, not one JSON document, because the unit of recovery is a line:** the
251/9607 cue loss was found by re-counting, not by trusting a summary, so a truncated tail must surface as
a parse failure on the last line plus a header-vs-line count mismatch — i.e. a visible `accounting_invalid`
— rather than as a document that merely looks shorter. Because persistence is **on**, D11(e)'s
`--artifact-root` is live on the builder (persistence off would leave it an accepted-but-ignored flag,
which `README.md:373-381` forbids); it is the only flag this ruling adds, and the printed accounting line
and the exit stance above are unchanged — a failed write under the artifact root is a configuration error
in the usage form (exit `1`), never a candidate refusal. **Why this suffices for criterion 1**: the
accounting must be re-checkable *after* the run; with the artifact persisted, the replay re-derives
`in == attached + unattached` from the sidecar record without re-reading either route, so the wave's
scratch tool disappearing cannot take criterion 1's evidence with it.

## §G. Knowledge surface (Q5 — attachment plan, **executed at iteration-close**, not now)

**No `{KNOWLEDGE_DIR}` write happens in Phase 1 or 2** (D7). What follows is the plan `mstar-compound`
executes at iteration-close (`mstar-iteration` §3.2); this round records it instead of creating docs by
hand. Every surface named below already exists unless the row says *new*.

| Surface | Action at close | The lesson to attach | Why here |
|---|---|---|---|
| `architecture-patterns/transcript-projection-publication.md` | **extend** (one section) | The two stages are a second instance of D2's split: a **pure** rule module carries the decision, `cli.py` composes the reads, and no judgement enters the deterministic half — the same split applied to a *checker* instead of a writer | **D2** names this doc as the repo precedent, and `§F` is the boundary that decision rests on; an instance belongs beside the pattern it instances |
| `best-practices/claim-scope-discipline.md` | **extend** (two entries) | (a) **This round's own catch**: `§C` asserted a measured caption-route CER that has no source on disk — a measured-looking number is the same defect class as unscoped prose, and the fix is a categorical statement plus the discipline that does exist (`quality.py`'s floor/cap, above). (b) the `§A` agent half and `§F`'s protocol item 6: a verifier proves a record row **names** its evidence, never that the evidence **supports** the claim | The contract already names this doc twice (`§A` agent half, `§F.6`), and the round produced a fresh dated instance of the failure it describes |
| `testing-patterns/hotword-list-measurement.md` | **reference only — no write** | A pointer: the `provenance.hotwords` screen (`hotword_disagreement` / `hotword_screen_vacuous`) is the *detector* that doc's measurement can reuse; whether the hotword list *helps* stays that doc's question | D5 keeps the ASR hotword-configuration question out of this iteration; writing this screen into the measurement doc would mix directions |
| `architecture-patterns/editorial-stage-contract.md` | **new doc owed** | The transferable core of this package: a file-transform stage ships as a **byte-provable mechanical half** (rules decidable from bytes + the record, split error vs advisory, where an advisory means *the check could not bite*) plus a **written judgement protocol** for the items no command may enforce, with persistence chosen so the recovery unit is a **line** | No existing doc covers verifier refusal-class design: `transcript-projection-publication.md` covers the decision/write split, `absence-assertion-negative-control.md` covers vacuous assertions as a *test* concern. Without it the stage shape would survive only inside an iteration-scoped spec |

**What does not move**: the 16 rule ids and their print forms stay in the frozen CLI spec
(`{SPECS_DIR}/asr-archive-cli.md`) and in this contract — the knowledge doc carries the pattern, not the
vocabulary.
