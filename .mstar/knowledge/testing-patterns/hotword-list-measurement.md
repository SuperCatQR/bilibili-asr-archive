---
module: bili-asr ASR hotword list (DEFAULT_HOTWORDS)
date: 2026-09-18
problem_type: testing_pattern
category: testing-patterns
severity: medium
plan_id: 20260918-transcript-text-precision; 20260924-qwen3-asr-transformers
applies_when:
  - deciding whether a DEFAULT_HOTWORDS entry earns its place
  - an A/B arm must subtract committed configuration rather than add it
  - a small transcript difference has to be separated from decoder jitter
  - bounding how far a prompt-list change reaches beyond its own terms
  - a measurement's engine changes and its older figures cannot carry over
  - a recovery must be told apart from an insertion rather than counted
  - a restore proof has to survive an uncommitted fix in the tree
tags:
  - hotword-ab
  - measurement-method
  - noise-floor
  - asr-prompt-list
  - sequence-matcher-basis
  - recovery-vs-insertion
  - uncommitted-fix-restore
  - prompt-induced-degeneration
related_components:
  - bilibili-asr-archive/src/bili_asr/asr.py (DEFAULT_HOTWORDS, _extra_hotwords)
  - BILI_ASR_HOTWORDS
  - asr_hotwords md frontmatter readback
  - bilibili-asr-archive/src/bili_asr/manifest.py (read-back surface)
---

# Measuring whether a hotword-list change earns its place

## Context

`DEFAULT_HOTWORDS` is a decoder prompt list: the words in it bias the ASR decode toward those spellings.
The six Chinese homophone entries added on 2026-09-17 (扬弃 自在 变易 此在 感性 实存) were justified by
**measured errors** — 118 mis-renderings across the season archive, every one the exact homophone of a
common word — but their **benefit was unverified**. An error census is a one-sided measurement: it says the
decoder gets these words wrong, not that adding them to the prompt list fixes the output. This is the
method for the other side, and the limits the one 2026-09-18 run of it established.

Sources for every figure below: `{ITERATION_DIR}/iter-2026-09-text-and-ledger-precision/guides/hotword-ab-20260918.md`
(the guide), `{SDD_DIR}/20260918-transcript-text-precision/task-2-report.md` (the implementer report), and
`{SDD_DIR}/20260918-transcript-text-precision/qc-inputs/driver-and-readbacks.md` (the arm readbacks).

**The engine changed on 2026-09-24, and that resets the evidence.** Everything in "Findings" below was
measured on the **retired** Fun-ASR-Nano-2512 checkpoint. The shipping engine reads the same list through a
different mechanism — the processor's free-form `prompt` rather than a decode-time bias — so those figures do
**not** carry over, and the 2026-09-26 re-measurement (bottom section) had to be run rather than inferred.
This is the general shape: a prompt-list result is a result *for an engine*, not for a list.

## Method — the two-arm removal design

**1. One affected lecture, chosen by the measured error census.** Not a corpus sample: re-transcribe one part
whose errors were already counted and whose term is actually spoken. The season register named
`BV1H69sB6EeF:p0` (《逻辑学》第二讲 存有论（2）扬弃-定在, cid `37953865549`, 6870 s ≈ 114.5 min) the worst
affected item — 扬弃 4 correct vs 57 wrong. The run identity is fixed with the arm: same audio, same model
(the FunAudioLLM/Fun-ASR-Nano-2512 checkpoint — **retired 2026-09-24**; the numbers below are that engine's, local model root nano/master), same device, one seeded row per
archive root, arms run sequentially.

**2. Build the "without" arm by temporary removal, not with the environment knob.** `_extra_hotwords`
(`bilibili-asr-archive/src/bili_asr/asr.py` L456-467) skips any term already in `DEFAULT_HOTWORDS`, so
`BILI_ASR_HOTWORDS` can only **add** — it cannot subtract a committed default entry. The Latin-acronym A/B
worked by re-adding removed acronyms through that knob; that trick is unavailable for a subtraction problem,
and the "without" arm exists only as a temporary, uncommitted edit that removes the six lines, restored
immediately after the run. (A guard bug was caught here before any arm ran: the six-term precondition counter
used `grep -c` with `\|` alternation, which under BRE returns 0 — the driver refused rather than removing
nothing. A precondition counter that can return 0 must abort, never proceed.)

**Prove the restore against BYTES, not against git** — corrected 2026-09-26, see the trap below. Snapshot
`bilibili-asr-archive/src/bili_asr/asr.py` to a temp file and record its sha256 **before** any edit; after the arm, require the file's sha256 to
equal that recorded value. A git-shaped proof (`git status --porcelain` empty **and** the working blob equal to
`HEAD`'s) is unsound whenever the fix under test is itself **uncommitted**, because reverting to `HEAD` is
exactly what makes both readings agree — the check passes while the run measures the wrong configuration.
Byte-anchoring restores what the run actually started from, whatever that was, and is independent of the host's
commit state. Print the git reading too, but as a *description* of the tree: on an uncommitted fix, "working
tree differs from HEAD" is the correct state, not a failure.

**3. Prove arm identity from the produced frontmatter, never from the invocation.** Read `asr_hotwords` back
out of each arm's produced md frontmatter: `with` 33 entries, `without` 27, and the diff is exactly the six
terms (`only in WITH: ['扬弃','自在','变易','此在','感性','实存']`, `only in WITHOUT: []`). The command line is
not evidence of which list ran; the artifact is.

**4. Fix the difference bar before the run.** The decision rule — correct forms rise, homophones fall, global
difference ≤5 %, and no new damage class — was fixed before the run (plan Task 2 Step 5). A bar chosen after
seeing the number measures nothing.

**4b. Fix the *clauses* before the run, not just the bar.** The 2026-09-26 round pre-declared nine
(thresholds P1–P9: recoveries, coverage, insertions, concentration, fabrications, global identity, noise
floor, damage classes, and an interpretive floor). Two paid for themselves immediately:

- The **interpretive floor** (`E < 8` exercised terms ⇒ the recovery and coverage clauses are
  uninformative) is what stopped a null being read as a refutation. Both substitute corpora and, in the end,
  the frozen corpus itself landed under it (`E = 7`). Without that clause written down in advance, "the list
  recovered nothing" reads like a verdict instead of an unanswerable question.
- The **damage-class clause** gives the engine's known degenerations numbers rather than adjectives, so a
  bad decode is a reported fact rather than a judgement call. See the trap it missed, below.

**4c. Fix the arm ORDER, and state it.** The corpus is the same in any order, but on a multi-hour run the
order decides what is banked if it stops. Seeding longest-first led with a 128-minute item; shortest-first
banks the cheapest items first. Either is defensible — what is not is leaving it unstated, because a reader
comparing two runs must be able to see that only the order differed. Without it, a few-percent difference is
indistinguishable from decoder jitter. A third arm re-ran the **identical** configuration as `with` and was
compared to it: ratio **1.0000** (floor **0.0000 %**), 0 of 1400 shared cues differing, identical
confidence, identical VAD counts. That is what makes the treatment difference interpretable — and it is a
floor *for the configuration that was repeated*: the repeat re-ran the 33-entry arm, so the 27-entry
`without` arm is a single sample.

## Findings — what the 2026-09-18 measurement established (FunASR era)

| Measurement | Result |
|---|---|
| `扬弃` correct forms | **4 → 38** |
| `扬弃` homophones | **59 → 26** (阳气 23 → 6, 洋气 36 → 20) |
| All six pairs, totals | correct 11 → 45 (**+34**); homophones 62 → 29 (**−33**) |
| The two transcripts | **97.52 % identical** (0.9752) — a 2.48 % global difference against the ≤5 % bar |
| Same-config repeat | **byte-identical**, floor 0.0000 % |
| `asr_mean_confidence` | 0.751 in both arms — unchanged |
| `asr_low_confidence_cues` | **48 with** the terms vs 51 without — **3 fewer** |
| Season baseline reproduced | the `without` arm lands at 4 correct vs 59 homophones, i.e. the pre-hotword condition |

Attribution of the 2.48 %: **209 of 1275** shared timing buckets differ — 38 扬弃/阳气/洋气-related (the
intended effect), 7 mentioning other hotwords, and **164 mentioning no hotword at all**. The 209 total is read
from the two arms' artifacts; the 38/7/164 sub-split is implementer-attested and carried as reported, not
independently re-derived.

## What it did not establish

- **The benefit is `扬弃`'s alone.** The other five terms (自在, 变易, 此在, 感性, 实存) were **unexercised on
  that lecture**: absent in both forms (自在, 此在), identical in both arms (感性 4, 实存 3), or touched only by
  a homophone-shaped word that does not move (变易's 变异 is 3 in both arms, unrelated to the term). Five of six
  showing no movement on a lecture
  that never speaks them is a **null, not a refutation** — and it is carried as an open residual
  (`20260918-transcript-text-precision · R1`), never as a verified fix. "Six terms confirmed" is the reading
  this measurement explicitly does not support.
- **One part, one model, one evidence channel.** This is not a corpus-wide claim; it answers the register entry
  that asked for exactly one affected lecture re-transcribed with and without the terms.
- **And, added 2026-09-26: a corpus can be too thin to answer at all.** The pre-declared interpretive floor
  (`E < 8`) fired on the frozen six too, at `E = 7`. A negative result under that floor is a statement about
  the corpus, not about the list — which is exactly why the clause exists. Attach it whenever a corpus is
  chosen for being *available* rather than for speaking the terms.

## Findings — what the 2026-09-26 measurement established (shipping Qwen3-ASR era)

Run on the **frozen six-item corpus** (7.3 h), the list as restored to its 33 documented entries, arms
identity-proven from frontmatter (33 / 0 / 33) and the restore proven. Full record:
`{ITERATION_DIR}/iter-2026-09-qwen3-asr-closeout/guides/t5-hotword-measurement-results.md`.

| Clause | Bar | Measured | Outcome |
|---|---|---|---|
| recoveries | `R ≥ 33` | **R = 0** | uninformative — `E = 7 < 8` |
| coverage | ≥ `0.6 × E` terms recover | 0 of 7 | uninformative — same clause |
| insertions | `I ≤ 8` | **I = 0** | pass |
| concentration | no term > 2 insertions | max 0 | pass |
| fabrications | `F = 0` | placeholder | not settled |
| global identity | ratio(A,B) ≥ 0.95 | **0.941523** | **fail** — one hand-read outlier |
| noise floor | ratio(A,R) ≥ 0.995 | **1.000000**, byte-identical | pass |
| damage classes | no known class | clean | pass (and blind — see traps) |
| throughput | ≤ 0.40× realtime | 0.1465× / 0.1379× / 0.1496× | pass |

**The result is negative and narrow.** Every one of the 7 exercised terms — `感性` 7, `辩证法` 8, `扬弃` 3,
`拉康`/`此在`/`自在`/`齐泽克` 1 each — carries an **identical count in both arms**. Not one term was recovered
by the prompt and not one was inserted by it. Four of the six homophone entries are exercised and all four are
flat, which matters directly: the 2026-09-18 result that justified them was *that engine's*, and on the
shipping engine the homophone failure it measured **does not reproduce on this corpus**.

**P3's own scale puts that in proportion.** The proofread wave counted **at least 25** insertion instances on
these same six items under the old engine (a floor, not a total, across eight shipped terms). Under the
shipping engine with the prompt on, this run counts **0**.

**And the P6 failure is a prompted-arm degeneration, not an insertion.** One item produced a **5 289-character
cue inside a 3.9-second window** (`blowing` ×99, `thatis` ×41, `is` ×401) plus a second of 2 439 characters.
An independent caption of the same audio shows a *short* `It's impossible` followed by Chinese, and contains
the looped phrase **zero** times. Arm R reproduces it byte-for-byte; the unprompted arm on identical audio has
**no cue above 500 characters** corpus-wide. Whether the prompt *causes* it is raised, not closed — one item
cannot settle that — but the correlation is arm-specific and reproducible, so it is reported.

## Promoted tooling

Two executable artifacts from this round are reusable as-is, in the iteration package:
the arm driver `{ITERATION_DIR}/iter-2026-09-qwen3-asr-closeout/guides/assets/ab-hotwords-qwen3.sh` (the arm driver: seeds arms, edits and byte-proves the restore, runs the arms, reads
the lists back) and the census classifier `{ITERATION_DIR}/iter-2026-09-qwen3-asr-closeout/guides/assets/census.py` (the per-term classifier: R/I/U per occurrence, per-item ratios, the noise
floor, damage classes, with the caption-vs-proofread basis labelled per span).

## When to Apply

- Before adding, removing or reordering a `DEFAULT_HOTWORDS` entry whose only justification is an error count:
  run the benefit side, on the audio where the errors were counted.
- Whenever the arm to be measured is *committed* configuration with no negative knob — the temporary-removal
  design plus its double restoration proof is the answer, and the readback is what makes it citable.
- Whenever a difference is small enough that decoder jitter is a live competing explanation: measure the floor
  first, or the difference is not yet a result.
- Not as a corpus-quality claim, and not as a substitute for the error census: the two halves are complementary,
  and this pattern supplies the second one.

## Traps that cost time
1. **State the ratio's basis.** 0.9752 is the standard library `SequenceMatcher` (`difflib`) over the **raw txt** with `autojunk=False`.
   The library default `autojunk=True` scores the *same pair* at 0.9731. Two "identical-char ratios" that
   differ in the third decimal are the same comparison under different bases, so the basis is part of the
   number and belongs beside it.
2. **A prompt-list change perturbs decoding beyond its own terms.** 164 of the 209 differing cues mention no
   hotword: filler and function-word slips (`呃`↔`嗯`, `Two`↔`To`, `施加`↔`实下`, `four`↔`your`, `form`↔`from`).
   None introduces a new damage class, confidence is flat and low-confidence cues *fall* — but the reach means
   "the diff is only about the term" is never a safe assumption, and it bounds any single-part result.

3. **A damage-class clause written as shapes will miss the same failure in another shape.** The clause said
   "no run of ≥3 consecutive identical cues" — repetition *across* cues. The actual degeneration was
   repetition *within* one cue, and a 5 289-character cue passed every clause: it was not empty, it was one
   cue not three, and the cue-count ratio stayed in band. What caught it was the **outlier rule** (an item
   outside the ratio envelope must be read by hand) plus a sanity check on **characters per second**: the
   affected item decoded at 6.1 chars/s against 5.0 for the unprompted arm, where every other item sat at
   4.9–5.3 for both. Express a damage clause over the *invariant you care about* (output length against
   elapsed audio) rather than over the shape the last failure took.
4. **A source path that is a network mount makes `rm -rf` a data-loss primitive.** A re-seed did
   `rm -rf <arms>` and then copied audio from a WebDAV mount, which had begun answering every **read** with
   `401` while directory *listings* still succeeded from cache — so it looked healthy. The copy failed and the
   previous arms' audio was already gone; the only other copy was behind the same failing auth. Order the
   guard the other way: **verify the source is readable for every item before removing anything**, reuse
   already-staged arms instead of rebuilding, and require an explicit force flag to rebuild. A corpus you
   cannot re-download is not reproducible, and no measurement script should be able to destroy one.
5. **A guard that checks the wrong list passes while the data it guards is absent.** The first version of the
   readability guard fell through to the *long* corpus's item list when asked about a short corpus, so it
   refused for the wrong reason and would have reported "source unreadable" for items that were never part of
   the corpus. Map the corpus to its bvids explicitly and **raise on an unknown corpus**; a wrong-list pass is
   worse than no guard.
6. **Counting entries by regex: strip comments first, and anchor the close.** Both the entry counter and the
   edit pattern must skip comment lines inside the literal (comment text quotes terms too — the count came out
   38 instead of 33), and the "did the edit land" check should match the one-line form the edit writes rather
   than re-scan the literal. A counter that can be satisfied by comment text silently approves the wrong list.
7. **Match the two arms by time OVERLAP, not by timestamp equality.** Arms segment independently: the same
   speech lands in buckets whose boundaries differ by a few hundred milliseconds. An exact-key lookup misses a
   span the other arm *does* carry, reads it as empty, and classifies every inherited occurrence as a
   recovery — the first census reported `R = 4` where the truth was `R = 0`, inflating precisely the number
   the measurement exists to produce. The `shared bucket` metric is still keyed by exact timestamps, because
   that number is *about* segmentation agreement; the word-level comparison is not.


## Evidence

- Guide (measurement record): `.mstar/iterations/iter-2026-09-text-and-ledger-precision/guides/hotword-ab-20260918.md`
- Implementer report: `.mstar/sdd/20260918-transcript-text-precision/task-2-report.md`
- Arm readbacks and driver capture: `.mstar/sdd/20260918-transcript-text-precision/qc-inputs/driver-and-readbacks.md`
- Plan: `20260918-transcript-text-precision` (iteration `iter-2026-09-text-and-ledger-precision`)
- Register: `e2e-23191782-season-7686105 · R3` closable on this evidence (the register write is the PM's); the
  other five terms carried on `20260918-transcript-text-precision · R1`.

**2026-09-26 round (shipping Qwen3-ASR era).**
- Verdict report: `{ITERATION_DIR}/iter-2026-09-qwen3-asr-closeout/guides/t5-hotword-measurement-results.md`
  (§1 records that the six items' audio was re-fetched after a mount loss, so read it before comparing with
  the 2026-09-18 figures).
- Pre-declared clauses P1–P9: `{ITERATION_DIR}/iter-2026-09-qwen3-asr-closeout/guides/t5-hotword-measurement-protocol.md` §5 (Amendments 1–3a record the
  entry-count correction, the attempt-ledger fact, and the second corpus).
- Substitute-corpus results and the artifact audit: `{ITERATION_DIR}/iter-2026-09-qwen3-asr-closeout/guides/t5-hotword-short-corpus-results.md`,
  `{ITERATION_DIR}/iter-2026-09-qwen3-asr-closeout/guides/t5-hotword-short2-corpus-results.md`, `{ITERATION_DIR}/iter-2026-09-qwen3-asr-closeout/guides/t5-artifact-audit.md`.
- Raw outputs on the target host: `/root/e2e-asr/ab-hotwords-qwen3/{CENSUS.md,census.json}`.
- Plan `20260924-qwen3-asr-transformers` (iteration `iter-2026-09-qwen3-asr-closeout`). The high residual
  `20260922-proofread-wave · R1` — "the hotword list is also an insertion source" — is **closed** on this
  measurement, with its uncovered part named in the closure note.
