# 2026-09-12 ten-video GPU run — audit evidence

Evidence base for `iter-2026-09-asr-ops-hardening`. Every number below was measured on
2026-09-12 on the WSL2 target (192.168.3.21, Ubuntu 24.04, 12 cores, RX 7800 XT via
ROCDXG); nothing here is estimated.

## 1. What was run

Ten archived parts of the visible corpus (the ten shortest, 449 s–1115 s, 125 minutes of
audio), transcribed end to end through the shipped CLI with the pinned
`FunAudioLLM/Fun-ASR-Nano-2512` checkpoint, `fsmn-vad`, the corpus hotword list, and
`BILI_ASR_DEVICE=cuda`.

| bvid | audio | cues | chars | chars/min | mean conf | cues ≤ 0.4 |
|---|---|---|---|---|---|---|
| BV132XgBjER4 | 499 s | 84 | 1563 | 188 | 0.852 | 0 |
| BV1aRTA6mEGF | 570 s | 125 | 2572 | 271 | 0.819 | 1 |
| BV1eGJ46mEHQ | 663 s | 118 | 2370 | 214 | 0.772 | 5 |
| BV1CiN46cEzm | 697 s | 148 | 3472 | 299 | 0.827 | 1 |
| BV1u1f1BxEaV | 702 s | 139 | 2598 | 222 | 0.791 | 1 |
| BV19h7168EMr | 730 s | 135 | 2759 | 227 | 0.842 | 0 |
| BV1UNPczkEkE | 746 s | 164 | 3147 | 253 | 0.815 | 1 |
| BV1147c6sEKs | 891 s | 162 | 3469 | 234 | 0.789 | 1 |
| BV1yt7c69EAx | 903 s | 165 | 3788 | 252 | 0.838 | 0 |
| BV1eiPczHEqg | 1114 s | 225 | 4252 | 229 | 0.815 | 0 |
| **total** | **125 min** | **1465** | **29 990** | — | **0.816** | **11** |

Decode `rtf_avg` per video: 0.097–0.150. Wall time for all ten: 21.8 min
(19:23:22 → 19:45:11), which decomposes as ≈ 16.3 min decode plus ≈ 5.6 min of
per-item work — of which the model reconstruction is the dominant term (§4.2).

Hard invariants held on all ten: zero zero-length cues, zero fragment cues, zero cues
opening with a closing mark, monotonic timelines, and per-file
`asr_mean_confidence` matching the recomputed per-cue mean.

## 2. Content defects found (recorded as evidence, not scheduled work)

**English terms fragment and lose case.** In `BV1eGJ46mEHQ` (the same video that carries
the lowest mean confidence, 0.772) the speaker spells the English name of the labour
court:

| produced | token confidence |
|---|---|
| `FOR EMP` | 0.00 |
| `LOYMENT MAT` | 0.00 |
| `tryBUNAL` | 0.19 |
| `employ没得事` | 0.00 |
| `programmizationprogrammatizationprogrammatisation` | 0.35 |

One English word is split across two cues; the last row is three spellings of the same
word emitted back to back — the loop signature.

**Number formatting is inconsistent inside one passage.** `BV1UNPczkEkE` @580.6 s
(confidence 0.25) contains `六万，六万，六万，六万` and `投60000` in the same breath:
`itn` behaves differently per segment.

**Repetition.** 4-grams occurring ≥ 3 times: 12–76 per video. Part is the speaker's
rhetorical repetition, part is decoder jitter; the two are not separable with today's
artefacts.

**Low-confidence cues (11, conf ≤ 0.4) decompose as** English/foreign 4, numbers 1,
disfluent fillers 3, garbled 2 — i.e. English and numbers carry half of them, and the
model's own confidence localises them without listening.

**Metric caveat.** An earlier ad-hoc "rare character" count in this audit was wrong (it
counted CJK punctuation); the numbers in the table above are the reliable ones.

## 3. Two questions the artefacts cannot answer

1. **VAD capture.** Gaps longer than 3 s between cues occur 1–15 times per video
   (`BV1147c6sEKs` 15, `BV1eiPczHEqg` 15). Nothing records how much audio the VAD
   captured, so a speaker pause and a VAD miss are indistinguishable.
2. **Where the doubt is.** `asr_low_confidence_cues: 5` names a count, not a location; the
   per-cue confidence exists only in `raw.json`.

## 4. Engineering defects reversed out of the run

### 4.1 The published GPU path does not produce a working device

`README.md` says "AMD 7800XT GPU with ROCm 5.7+ drivers" and
`pip install torch --index-url https://download.pytorch.org/whl/rocm6.0`; `asr.py`'s
runtime hint repeats the same command. Measured reality on the target:

- ROCm 5.7 has no `gfx1101` support at all.
- The PyTorch.org ROCm wheel imports but `torch.cuda.is_available()` is `False`; forcing
  `HSA_ENABLE_DXG_DETECTION=1` aborts: `Found 0 rocprofiler agents and 2 HSA agents …`,
  inside torch's bundled `librocprofiler-sdk`, which AMD documents as unsupported on WSL.
- The verified path (device visible, `gfx1101`, 15.8 GB, matmul on device):
  ROCm 7.2.1 runtime + `rocdxg-roct` 1.2.2 (ROCDXG) + **repo.radeon.com** wheel
  `torch 2.9.1+rocm7.2.0.lw` (installed together with its matching `triton` wheel) +
  `rocm-hip-libraries`/`miopen-hip`/`roctracer`/`rocprofiler-register` +
  `/opt/rocm-7.2.1/lib` on the loader path + the WSL-compatible `libhsa-runtime64.so` in
  the venv's `torch/lib` + `HSA_ENABLE_DXG_DETECTION=1`.

### 4.2 The obvious batch loop forfeits the designed model reuse

`coordinator.py` constructs one `ASRRunner` per run scope and reuses it
(`if self.asr_runner is None: …`), which is exactly the designed contract in
`{KNOWLEDGE_DIR}/architecture-patterns/run-scoped-asr-provenance.md`. Invoking
`bili-asr asr --bvid …` once per item — the form the run used — reconstructs the model
every time: 21.8 min total, ≈ 16.3 min decode, ≈ 5.6 min per-item overhead (26 %).

### 4.3 Quality has two entry points

`src/bili_asr/quality.py` (+ `coverage --quality`) owns the shape layer with reason codes
`empty`, `malformed`, `non_monotonic`, `overlap`, `out_of_range`, `identity_mismatch`,
`artifact_missing`. The content layer added on 2026-09-12 (confidence, fragments,
over-long cues, repeated n-grams, cross-system agreement) lives in a parallel
`scripts/asr_quality.py` that the coverage surface knows nothing about.

### 4.4 Provenance cannot name the producer

All ten archived files record `asr_model_name: "[redacted]"`: the operator loaded the
checkpoint from a local path, which by design is not a redaction-safe identifier, and no
declared hub-level identity was available to fall back on.

## 5. Checked and *not* defects

- **Audio reclaim after `archived`** is deliberate (`coordinator.py` "Best-effort audio
  reclaim once a row is archived"), documented in `docs/audio-retention-policy.md`, and
  configurable via `BILI_KEEP_AUDIO=1`. The run's re-download need was self-inflicted.
- **Append-oriented manifest revisions** (20 rows / 10 work ids: `audio_ok` + `archived`)
  are decided design: `operational-sidecars.md` guidance 10 requires durable append and
  derived latest-valid state, and the readers already implement last-valid-wins.
- **`verify`/integrity** does not expect reclaimed audio for `archived` rows
  (`RETRYABLE_INCOMPLETE` covers only pre-archive statuses).
