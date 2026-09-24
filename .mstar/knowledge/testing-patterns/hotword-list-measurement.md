---
module: bili-asr ASR hotword list (DEFAULT_HOTWORDS)
date: 2026-09-18
problem_type: testing_pattern
category: testing-patterns
severity: medium
plan_id: 20260918-transcript-text-precision
applies_when:
  - deciding whether a DEFAULT_HOTWORDS entry earns its place
  - an A/B arm must subtract committed configuration rather than add it
  - a small transcript difference has to be separated from decoder jitter
  - bounding how far a prompt-list change reaches beyond its own terms
tags:
  - hotword-ab
  - measurement-method
  - noise-floor
  - asr-prompt-list
  - sequence-matcher-basis
related_components:
  - bilibili-asr-archive/src/bili_asr/asr.py (DEFAULT_HOTWORDS, _extra_hotwords)
  - BILI_ASR_HOTWORDS
  - asr_hotwords md frontmatter readback
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
immediately after the run. Restoration is proved twice, not asserted: `git status --porcelain` empty for
`bilibili-asr-archive/src/bili_asr/asr.py` **and** the working file's blob hash equal to `HEAD`'s. (A guard bug
was caught here before any arm ran: the six-term precondition counter used `grep -c` with `\|` alternation,
which under BRE returns 0 — the driver refused rather than removing nothing. A precondition counter that can
return 0 must abort, never proceed.)

**3. Prove arm identity from the produced frontmatter, never from the invocation.** Read `asr_hotwords` back
out of each arm's produced md frontmatter: `with` 33 entries, `without` 27, and the diff is exactly the six
terms (`only in WITH: ['扬弃','自在','变易','此在','感性','实存']`, `only in WITHOUT: []`). The command line is
not evidence of which list ran; the artifact is.

**4. Fix the difference bar before the run.** The decision rule — correct forms rise, homophones fall, global
difference ≤5 %, and no new damage class — was fixed before the run (plan Task 2 Step 5). A bar chosen after
seeing the number measures nothing.

**5. Measure the noise floor with a same-config repeat run.** Without it, a few-percent difference is
indistinguishable from decoder jitter. A third arm re-ran the **identical** configuration as `with` and was
compared to it: ratio **1.0000** (floor **0.0000 %**), 0 of 1400 shared cues differing, identical
confidence, identical VAD counts. That is what makes the treatment difference interpretable — and it is a
floor *for the configuration that was repeated*: the repeat re-ran the 33-entry arm, so the 27-entry
`without` arm is a single sample.

## Findings — what the 2026-09-18 measurement established

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

## Evidence

- Guide (measurement record): `.mstar/iterations/iter-2026-09-text-and-ledger-precision/guides/hotword-ab-20260918.md`
- Implementer report: `.mstar/sdd/20260918-transcript-text-precision/task-2-report.md`
- Arm readbacks and driver capture: `.mstar/sdd/20260918-transcript-text-precision/qc-inputs/driver-and-readbacks.md`
- Plan: `20260918-transcript-text-precision` (iteration `iter-2026-09-text-and-ledger-precision`)
- Register: `e2e-23191782-season-7686105 · R3` closable on this evidence (the register write is the PM's); the
  other five terms carried on `20260918-transcript-text-precision · R1`.
