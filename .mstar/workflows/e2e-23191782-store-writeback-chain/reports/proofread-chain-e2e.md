# E2E report — the proofread chain (校对环节), 2026-10-03

**Scope.** An explicitly requested end-to-end verification of the proofread pipeline:
`bili-asr proofread` (machine alignment) → operator-marked 定稿 → `bili-asr proofread-merge`.
Run on the compute host `chosenecho@192.168.3.21` (WSL2, RX 7800 XT, `gfx1101`) against the
real product checkout.

**Outcome: the chain itself works and is honestly guarded. It also surfaced a high-severity
product defect (I-000188) which is the most important result of this run.**

## 1. A correction to the previous session's framing (important)

This run was requested on the premise that the proofread chain had never been exercised past
its first stage. That premise was **only partly right, and the part that was wrong is my error**:

- A full `proofread` **build** had in fact been delivered once before, on part `BV1acKfzEEWS:p0`
  (29 blocks, 195/195 caption entries assigned, 0 unassigned) during the prior E2E.
- What had genuinely never been verified — by any run — was the **status of its Guard B**, the
  **marker→column contract**, the **merge stage**, the **corrections accounting**, and the
  **write boundary**.

So this run's real contribution is the merge half of the chain plus the discovery below — not
"the first proofread ever". Stated because the earlier framing shaped what I went looking for.

## 2. The chain verified end to end on part `BV1qR7az2EzY:p0`

Both routes genuinely existed (store `subtitle-ai ai-zh v1`, disk `bundle.raw.json` with
`source: asr`), which is the precondition the chain needs.

| Assertion | Result |
|---|---|
| `proofread` writes both artifacts and exits 0 | **passed** — `inputs/…sidebyside.md` 11,954 B, `align/…alignment.jsonl` 5,098 B |
| **Guard C** — same inputs → byte-identical outputs | **passed** — re-run identical for both files (`dd74faf9…`, `82b68e95…`) |
| `proofread-merge` refuses with no 定稿 | **passed** — exit 1, names the expected path |
| `proofread-merge` refuses non-contiguous block indexes | **passed** — exit 1, `block indexes are not the contiguous 1..N` |
| `proofread-merge` refuses an unparseable heading | **passed** — exit 1, echoes the line |
| `proofread-merge` refuses an empty `custom:` payload | **passed** — exit 1, `custom decision carries no text` |
| **All four marker kinds → the right column** | **passed** — see §3 |
| Corrections accounting formulas | **passed** — see §3 |
| **Write boundary** — canonical families untouched | **passed** — byte-identical before/after the merge |
| Route check: a caption-derived sidecar offered as the ASR route | **passed** — refuses, exit 1, names the source it found instead |

The `.proofread` family is a **separate output**, not a canonical bundle: it holds
`bundle.txt`, `bundle.srt`, `bundle.raw.json` and **neither `bundle.md` nor `.bundle-ready`**,
so it is not "complete" by the archive's own completeness rule, and `publish-transcripts` still
owns the canonical four. That matches the spec's write-boundary claim.

## 3. The marker contract, measured (23 blocks, all four kinds)

| Block | Marker | Recorded | Body taken from |
|---|---|---|---|
| 1 | `use-asr` | `use-asr` | ASR column |
| 2 | `custom: 【人工判定】…` | `custom` | the payload |
| 3 | `use-sub` | `use-sub` | 字幕 column |
| 4 | `keep` | `keep` | 字幕 column |
| 5–23 | unmarked | `keep` | 字幕 column (default confirmed) |

`bundle.raw.json` carried `source=proofread`, 23 segments, 23 decision records; **0 mapping
mismatches**; **no non-empty block body was missing from `bundle.txt`**.

Accounting matched its stated formulas exactly:
`{"blocks": 23, "decisions": {"custom": 1, "keep": 20, "use-asr": 1, "use-sub": 1},
"subtitles_asr": 1, "subtitles_sub": 22}` — `subtitles_sub` counting
`keep + use-sub + custom` (= 22, i.e. **`custom` counts as 字幕-side**, never asr).

## 4. The headline finding: Guard A fired, and it was right (I-000188)

On the first part tried, `BV1YFEUzpEsT:p0`, `proofread` **refused to run**:

```
proofread: Guard A: work_id=BV1YFEUzpEsT:p0 block 1: 6 subtitle entr(ies) —
first is entry 26 — appear in no block
```

Guard A runs **before any artifact is written**, so nothing was produced — which is the guard
behaving as specified. I first had to decide whether this was a true positive or a bug in the
aligner. It is a **true positive, and it points at the ASR stage**:

| Measurement | Value |
|---|---|
| ASR bundle span | **0.0 – 59.0 s** (13 segments) |
| Decoded audio length | **73.561 s** (3,244,032 samples @ 44.1 kHz) |
| `video_parts.duration_ms` | 74,000 |
| **Speech never reached by ASR** | **14.6 s (20 % of the recording)** |
| Caption entries in that span | 7, at 58.0 – 67.5 s |
| The other part (`BV1qR7az2EzY`) | ASR end 467.3 s of 469.0 s → **0 unassigned, guard passes** |

So Guard A failed on exactly one part — the one whose ASR had dropped a fifth of the audio.

**Attribution, each step measured rather than argued:**

1. **Not the download.** A fresh download of the same part is 303,078 bytes and measures
   **73.561 s** by both `ffprobe` and the product's own `_read_audio`.
2. **Not the token budget.** Raising `_MAX_NEW_TOKENS_PER_AUDIO_SECOND` from 8 to 32 (budget
   588 → 2,352 tokens) produced **byte-identical** output: 13 segments, 307 characters, span
   0.0–59.0 s.
3. **Not silence.** The skipped span measures **−27.0 dB mean / −4.0 dB max**, against
   **−26.0 / −4.0 dB** for the covered region, with only 0.4–0.6 s pauses.
4. **The model does not hear speech there at its level.** Fed only the gap it returns **0
   characters**. At **+20 dB** it returns text (`我每天呢，你看，中央都给它发下去，都给它都给它压。`).
   Controls: the verifiably silent 67–73.5 s returns **0 characters at any gain**, and a covered
   region (50–58 s) returns 4 segments at its own level.
5. **Therefore the recovered text is unreliable** — the two gain variants disagree with each
   other and neither matches the captions. This is *hard audio*, not a fixable gain setting.

The defect is therefore not "the model is bad at this region". It is that **the archive recorded
a 20 % short transcript as an unqualified success** — `outcome=stored`, an `archived` bundle,
four published families, no `error_code`, no warning. Nothing in the write path compares the
produced span with the decoded duration. Registered as **`I-000188` (high)**.

Two caveats I hold about my own finding: the "hard audio" conclusion rests on one 8-second
region of one video, and my gain experiment used a module constant rather than a product knob.

## 5. An independent source derivation, and what it caught

A read-only seat (`code-reviewer`) independently derived the merge contract from source. It
matched the live run on every point it covered — marker→column, the unmarked default, the exit
taxonomy, the output paths, the accounting formulas, Guard A's two counts and the fact that it
is unreachable from the merge path, and **Guard B** (confirmed present:
`tests/test_proofread.py:254-261` asserts the banned tokens `midpoint` / `中点` / `outside` are
absent from `proofread.py`).

It also caught a real defect I had not: **a block whose table row is missing yields an empty
body, is dropped from the transcript, still counts in the accounting, and exits 0** —
registered as **`I-000189` (medium)**. And it flagged a spec-vs-code gap (the spec at
`proofread.md:27` says "the final `.proofread` transcript artifact", singular; the code writes
three families and no `.bundle-ready`) — **`T4-F1` (low)**, spec wording loose, code intended.

## 6. A reporting correction I have to make

Earlier in this run I reported that all four marker kinds had been exercised, then realised on
re-reading the raw output that **several verification blocks never executed**: a heredoc had
bound to `tee` instead of to `python3`, so the script text was printed as if it were output. In
consequence the first "all four markers" merge actually ran with **zero** markers — a valid
default-`keep` path, but not the marker test I claimed. §3 above is the corrected run, with the
marker block verified to have executed. One guess in that same batch was also wrong and is now
fixed: the merged bundle's sidecar is **`bundle.raw.json`**, not `raw.json`.

## 7. Artifacts

All on the compute host under `/root/e2e-asr/asr-two-video-batch/`:

| Path | Content |
|---|---|
| `evidence/proofread/b-align.txt` | the Guard A refusal and the missing artifacts |
| `evidence/proofread/v-tail-audio.txt` | per-second RMS and the silence map |
| `evidence/proofread/x-gain.txt` | as-is vs +20 dB vs silent control vs covered control |
| `evidence/proofread/u-budget.txt` | the token-budget experiment |
| `evidence/proofread/t-tail.txt` | what the skipped span carries per the caption route |
| `evidence/proofread/t-markers.txt` | the corrected marker/accounting/boundary run |
| `evidence/proofread/n-chain.txt`, `o-merge.txt`, `p-failures.txt` | the passing chain and its failure modes |
| `transcripts/BV1qR7az2EzY.p0.proofread/` | the merged artifact (3 families) |
| `artifacts-fresh/` | the full-length re-download used for attribution |

## 8. Issues

| Issue | Severity | Substance |
|---|---|---|
| `I-000188` | **high** | ASR can store a transcript covering part of the audio's speech, recorded as success with no coverage signal |
| `I-000189` | medium | `proofread-merge` silently drops a rowless block, exits 0, still counts it |
| `I-000187` | high | (earlier this session) an empty caption inventory recorded as durable `no-subtitle` |
| `I-000186` | medium | (earlier this session) the issue-close channel is unreachable |
| `T4-F1` | low | spec `proofread.md:27` singular/loose about what merge writes — not registered as an issue, recorded here |

## 9. Standing

- The **chain** verifies: guard, merge, markers, accounting, boundary, failure modes.
- The **only product defect the chain itself detected** is `I-000188` — and it detected it by
  refusing to run, which is the guard doing its job.
- `I-000188` and `I-000187` are the two candidates for the next iteration; both are ASR-stage
  defects that make a **successful-looking archive entry wrong**, which is the same failure
  class as `I-000166`.
