# T5 — artifact audit of the short-item arms

**Status: an audit record, not a measurement.** It establishes that the three arms' products conform to
the archive's own contract before ~hours of corpus time is spent on them, and it records two observations
that are *not* defects. Written 2026-09-26 against the arms of
`guides/t5-hotword-short-item-dry-run.md`.

## What was audited

| arm | root | configuration read back |
|---|---|---|
| A | `/root/e2e-asr/ab-short/with` | `asr_hotwords` = 33 |
| B | `/root/e2e-asr/ab-short/without` | `asr_hotwords` = 0 |
| R | `/root/e2e-asr/ab-short/repeat` | `asr_hotwords` = 33 |

Item `BV1wLTP6NE9h:p0`, 448 s. Host `chosenecho@192.168.3.21` (WSL, RX 7800 XT gfx1101), repo
`d41c257`, venv `.venv` (Python 3.12.3, transformers 5.16.1, torch 2.9.1+rocm7.2.0), command
`python -m bili_asr asr --pending --archive-root <arm>` with `HSA_ENABLE_DXG_DETECTION=1`,
`HF_HUB_OFFLINE=1`, and `BILI_ASR_HOTWORDS` unset.

## Layer 1 — the product's own verifier

```
$ python -m bili_asr verify --archive-root <arm>
{"authoritative": false, "checked": 1, "defect_count": 0, "defects": [], "diagnostics": ["missing_attempts_sidecar"]}
exit 0
```

All three arms: **1 checked, 0 defects, exit 0**. `--format text` and `--trusted-local` return the same
verdict.

## Layer 2 — independent hash verification

Each arm's `.bundle-ready` marker carries a sha256 per artifact (`schema: archive-bundle-v1`). Every one
was recomputed from the bytes on disk:

| arm | md | raw | srt | txt | manifest paths == marker paths |
|---|---|---|---|---|---|
| A / B / R | OK | OK | OK | OK | yes |

12 of 12 hashes verify. The manifest's recorded `{md,raw,srt,txt}_path` values equal the marker's, so the
row and the marker cannot disagree about where the bundle lives.

## Layer 3 — contract compliance

**Frontmatter.** 21 keys on every arm. The nine `asr_*` provenance keys that `ASRRunner.provenance()`
(`asr.py:899-913`) produces are present **complete and unabridged**: `asr_model_name`,
`asr_aligner_model`, `asr_model_revision`, `asr_device`, `asr_language`, `asr_hotwords`,
`asr_chunk_seconds`, `asr_offline`, `asr_local_source`. The base keys
(`bvid`/`title`/`date`/`duration_s`/`source`/`url`/`work_id`/`page_index`/`cid`) are present.
`asr_model_name` reads `Qwen/Qwen3-ASR-1.7B-hf` and `asr_chunk_seconds` `180` on all three.

**Four-surface agreement.** For each arm: `txt` equals the newline-joined `raw.segments` text; the `srt`
cue count equals the `raw` segment count (60/60, 57/57, 60/60); the `md` body equals the `txt`.

**Timings.** Monotonic non-decreasing starts, strictly positive durations, **0 empty-text segments** —
i.e. no P8 damage class. Cue character lengths are sane (min/median/max 6/29/67 for A and R; 10/33/64 for
B).

**Manifest.** Each arm holds the seeded `audio_ok` row and one `archived` row carrying the four path keys.
No `archive.db` is written by the `asr` path.

**Capture family.** `asr_vad_segments` / `asr_vad_captured_s` / `asr_vad_captured_ratio` reproduce exactly
when recomputed with the product's own `archive._merged_cue_spans` (A 20 spans / 418.701 s / 0.933;
B 19 / 420.061 s / 0.936; R identical to A). See observation 1.

## Observation 1 — `asr_vad_*` is a legacy *name*, and its values are correct

The three capture keys are named for a VAD, and the engine that ships has **no VAD component at all**
(`grep -n vad bilibili-asr-archive/src/bili_asr/asr.py` returns nothing). The values are computed from the
merged cue spans (`archive.py:412-448`, `CAPTURE_GAP_SECONDS = 1.0` at `:303`).

This is **not** a contradiction, and the reader-facing documentation is already accurate: `README.md:245-258`
describes the keys as "the stretches of audio the transcript actually covers", states the 1.0 s fusion
rule, and gives the exact recomputation — a reader is not misled about what the numbers mean. The *names*
are what remain FunASR-era, and they were already cue-derived before the engine change (`2548ca9^`'s
`_capture_summary` carries the same docstring), so the engine switch did not introduce the mismatch.

Not fixed here: renaming a frontmatter key changes a published contract and belongs to a round that owns
that decision, not to a measurement round. Recorded so the next reader does not re-derive it.

**A correction this audit had to make to itself.** The first recomputation attempt reported a mismatch
(20 published spans vs 49 recomputed). The error was in the audit, not the product: the replication had
omitted the 1.0 s fusion and the zero-length-skip. Re-run through the product's own
`_merged_cue_spans`, all three arms reproduce exactly. Recorded because a "defect" that turns out to be
the checker's arithmetic is exactly the kind of finding that should not reach the register.

## Observation 2 — the missing attempt sidecar, independently confirmed

`verify` reports `missing_attempts_sidecar`, and `coverage` reports `evidence_missing` for
`attempts`, `cursor`, `run_ledger` and `scheduler`. This is the same fact the protocol carries as
**Amendment 2**: `bili-asr asr` writes no `coordinator/attempts.jsonl` — only the coordinator path does
(`RunCoordinator` builds the `AttemptLedger`, `coordinator.py:357`). The product's own tools agree with
the amendment, which is the strongest confirmation available that the amendment is right.

Consequence for T5: none. No clause in P1–P9 reads an attempt count; a failed row surfaces as a missing
transcript for that item, which the census reports per item as `A absent` / `B absent`.

## What this audit does and does not establish

It establishes that the arm products are contract-conformant, internally consistent across all four
surfaces, hash-verified, and free of the P8 damage classes — so a corpus run built the same way produces
comparable artifacts, and a later difference between arms is a difference in transcription rather than in
bookkeeping.

It does **not** establish anything about transcription quality, hotword benefit, or the six restored
terms. Those are the measurement's job.
