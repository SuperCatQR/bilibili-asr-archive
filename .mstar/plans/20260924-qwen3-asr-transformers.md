---
plan_id: 20260924-qwen3-asr-transformers
iteration: iter-2026-09-qwen3-asr-closeout
iteration_compass: .mstar/iterations/iter-2026-09-qwen3-asr-closeout/delivery-compass.md
iteration_refs:
  - .mstar/iterations/iter-2026-09-qwen3-asr-closeout/delivery-compass.md
primary_spec: .mstar/specs/asr-archive-cli.md
blocked_by: []
qa_gate: mandatory
qa_mode: targeted
execution_mode: sdd
---

# 20260924-qwen3-asr-transformers — switch the ASR model and inference engine to Qwen3-ASR on transformers

**Status: `Done` 2026-09-26.** Registered 2026-09-25 as the single `Todo` plan row of iteration
`iter-2026-09-qwen3-asr-closeout` (compass `.mstar/iterations/iter-2026-09-qwen3-asr-closeout/delivery-compass.md`).
T1–T4 merged on `main` as `3b561ea`; T5 and T6 completed 2026-09-26 and merged into
`iteration/iter-2026-09-qwen3-asr-closeout` as `d273242`. All seven §7 Done criteria carry evidence (§14).

**T5's verdict is `PARTIAL`, and that is a completed measurement, not an unfinished one**: the frozen six
ran end to end and returned `R = 0, I = 0, U = 0`, with P6 failing on a hand-read prompted-arm degeneration
and `E = 7` leaving P1/P2 uninformative by the protocol's own P9. A negative result the protocol explicitly
requires to be recordable closed the high residual `20260922-proofread-wave · R1`. Report:
`guides/t5-hotword-measurement-results.md` — read its §1 before comparing with the §13 figures below,
because the six items' audio was re-fetched after the 123pan loss (register `R3`).

§14 item 4, the real-machine CLI E2E, **stays deferred by the operator** and is carried by the compass
`## Roadmap Position` as the next iteration's first work — it does not block this plan, which is why the
plan is Done while the item is open. Measurements in §13 are from 2026-09-24, `main` @ `6e7f427`; the
T5 run above is the later, engine-shipping measurement.

---

## 1. Goal

| | today | after |
|---|---|---|
| Model | `FunAudioLLM/Fun-ASR-Nano-2512` (remote-code checkpoint, local snapshot) | **`Qwen/Qwen3-ASR-1.7B-hf`** (settled) |
| Engine | `funasr.AutoModel` (`src/bili_asr/asr.py:27`) | **transformers-native**: `AutoProcessor` + `AutoModelForMultimodalLM` / `Qwen3ASRForConditionalGeneration` |
| Timestamps | FunASR VAD + the checkpoint's token timings | **`Qwen/Qwen3-ForcedAligner-0.6B-hf`** (`Qwen3ASRForTokenClassification`) + our own chunker |
| Weights | ModelScope cache under `~/.cache` | **`bilibili-asr-archive/models/`** — in-project, gitignored (settled) |
| Precision | fp16/bf16 | **bf16 only; no quantisation** (settled) |
| Existing transcripts | — | **not re-transcribed** (settled) |

The product shape does not change: one part in, millisecond segments out, `srt`/`txt`/`md`/`raw` under
the artifact root, provenance in the frontmatter, `bili-asr asr` as the entry point.

## 2. Why — the measured case

**The engine is already on the host; this migration is mostly code, not environment.**

| Measurement (2026-09-24) | Result |
|---|---|
| `transformers` in both target-host venvs | **5.16.1** — the model card requires ≥ 5.13.0 |
| Qwen3-ASR API present | `Qwen3ASRForConditionalGeneration`, `Qwen3ASRForTokenClassification`, `Qwen3ASRProcessor` with `apply_transcription_request`, `prepare_forced_aligner_inputs`, `decode_forced_alignment`, `split_words_for_alignment` |
| Quantiser configs present | `BitsAndBytesConfig` ✓ `QuantoConfig` ✓ `TorchAoConfig` ✓ `FbgemmFp8Config` ✓ `FineGrainedFP8Config` ✓ `CompressedTensorsConfig` ✓ `GPTQConfig` ✓ `AwqConfig` ✓ |
| Weight channel | `huggingface.co` / `github.com` / `pypi.org` direct = **timeout**; **`hf-mirror.com` = 7.58 MB/s from the target host**, ModelScope reachable but throttles large files to ~300 kB/s |
| GPU baseline | `/root/gpu-venv` reaches the device (RX 7800 XT, `gfx1101`, 15.8 GB); the repo `.venv` (torch 2.14.0+rocm7.2) **dumps core** with `HSA_ENABLE_DXG_DETECTION=1` — the recipe's step-7 HSA swap has not been re-applied there |
| Weights, in-project | `Qwen3-ASR-1.7B-hf/model.safetensors` 4,076,193,080 B `sha256 2db53c7d…042dfee1`; `Qwen3-ForcedAligner-0.6B-hf/model.safetensors` 1,835,545,960 B `sha256 00568245…5c47fb86` (identical on the HF and ModelScope records) |
| Published quality | Qwen3-ASR-1.7B vs **Fun-ASR-MLT-Nano** (closest published relative of the pinned checkpoint): Dialog-Chinese-Dialects WER 15.94 vs 19.41, TongueTwister 2.44 vs 9.02, ExtremeNoise 16.17 vs 36.55 |
| Licence | Apache-2.0 |

Registered residuals this migration touches: `20260922-proofread-wave · R1` (high — the ASR hotword list
is itself an **insertion source**), `20260917-hotword-acronym-precision · R1`,
`20260918-transcript-text-precision · R1`.

Registered residuals this migration **produced**, both found and fixed on 2026-09-26 while running T5 (the
merge introduced them; nothing in this plan authorised or recorded either):

- `20260924-qwen3-asr-transformers · R1` (high) — the merged boundary could not read the audio the archive's
  own downloader writes: `soundfile`/libsndfile cannot decode the **AAC** inside the `.m4a` that
  `cli.py:1574` / `audio.py` produce, so `bili-asr asr` failed on its own product's audio. Fixed by
  `_read_audio()`'s `librosa` fallback (commit `0a95035`). The 2026-09-24 measurement was green only
  because it ran on a PCM `.wav`.
- `20260924-qwen3-asr-transformers · R2` (high) — the same merge silently rewrote `DEFAULT_HOTWORDS`,
  33 entries → 26: it deleted the six 2026-09-17 homophone entries including `扬弃` with their measured
  rationale, re-added `ITEM`/`AITEM` after `ef5e1e8` deliberately removed them, and dropped the three
  Latin shards. No test pinned the list, so every gate stayed green while the prompt changed. Restored in
  commit `83ba8d0` to the pre-rewrite set and order, and T5's thresholds restated for 33 via the
  protocol's Amendment 1.

- `20260924-qwen3-asr-transformers · R3` (high) — the 123pan mount failed auth and a re-seed destroyed the
  frozen six's staged audio. **Re-staged the same day** from Bilibili into `/mnt/e/asr-archive-c6/audio`,
  identity cross-checked before downloading, all durations within 2 s of the frozen record; the driver is
  hardened so the destructive sequence cannot recur.
- `20260924-qwen3-asr-transformers · R4` (low) — the archive's two-engine state, recorded in the README's
  provenance material (T6, commit `7b86882`).

**T5's verdict on the high residual this migration was to move.** `20260922-proofread-wave · R1` (high) said
the hotword list is itself an insertion source and that the measurement family could not tell an injected
term from a spoken one. T5 closes it: the census classifies every occurrence as recovery / insertion /
undecided, so presence no longer counts the same whichever way it arose, and on the frozen six the result is
**R = 0, I = 0, U = 0** — against the proofread wave's floor of **at least 25** insertions on the same six
items under the old engine. The negative result R1's own text asked to be recordable is recorded. What the
closure does **not** cover, stated here rather than left to be inferred: the verdict is `PARTIAL` (`E = 7`
is below P9's floor, so the corpus cannot settle whether the list earns its place), `F = 0` is a declared
placeholder rather than a measurement, and the product still does not mark per-token provenance in a
transcript — leg (a) of R1 is only partly addressed. Register row: `20260922-proofread-wave · R1`,
`lifecycle: resolved`, closed 2026-09-26.

## 3. Surface map — what changes

| Surface | Anchor | Change |
|---|---|---|
| Engine boundary | `asr.py:27` `_load_default_model`, `DEFAULT_MODEL:22` | funasr `AutoModel` → transformers processor+model; `DEFAULT_MODEL` → `Qwen/Qwen3-ASR-1.7B-hf` |
| Configuration | `ASRConfig` (`asr.py:293`), `default_config()` | `vad_model` (a FunASR alias, `asr.py:129`) loses its meaning; a chunking knob replaces it; a new aligner-model knob |
| Input materialisation | `_materialize_input` (`asr.py:374`) | exists only because FunASR's VAD shells out to `ffmpeg`; a transformers decode is in-process — **verify before removing** |
| Cue shaping | `_normalize_nano_tokens` family, `tests/test_asr_format.py` | token-timing shaping is FunASR's shape; the aligner's word/char timings need their own, equally tested, shaping |
| Provenance | `archive.py:312-448` | see §4/G2; `asr_vad_*` **already describe the merged cues, not the VAD component** (`archive.py:415`), so they survive semantically |
| Optional deps | `pyproject.toml` `[asr] = ["funasr>=1.2"]` | → `transformers>=5.13`; modelscope/librosa/soundfile already present |
| Host check | `scripts/check_asr_env.py` | **survives unchanged** — torch/ROCm invariants only |
| Tests | `tests/test_asr_reproducibility.py` (**1843 lines**, `fake_funasr`), `test_asr_format.py`, `test_asr_cues.py`, `test_derived_queue_chain.py` | the real cost; engine-agnostic parts stay |
| Docs | `README.md` (9 mentions), `.mstar/specs/asr-archive-cli.md` (3) | one contract, updated in place |

## 4. The four real gaps

**G1 — timestamps.** `generate()` returns text with no timings; the archive's product is millisecond
segments. Timings come from the aligner, whose documented bound is 5 minutes per call — and the
reference implementation is stricter: `MAX_FORCE_ALIGN_INPUT_SECONDS = 180` (3 min) with timestamps,
`MAX_ASR_INPUT_SECONDS = 1200` (20 min) without. Its `split_audio_into_chunks` cuts at a **low-energy
boundary** (±5 s search, 100 ms windows), **guarantees no overlap and no gaps** (chunks concatenate to
the original exactly), and zero-pads chunks below `MIN_ASR_INPUT_SECONDS = 0.5`. `parse_asr_output`
handles `language X<asr_text>…` and applies a repetition guard (`detect_and_fix_repetitions`, threshold
20). **The package already owns this logic**; see D2 for why we port it rather than depend on it.

**G2 — confidence (OPEN).** Each cue carries `confidence` = mean token score, published as
`asr_low_confidence_cues` / `asr_low_confidence_at` (`archive.py:312-361`). An autoregressive decode has
no per-cue score. Options: (a) derive from generation logprobs over that cue's tokens; (b) publish the
keys as explicitly unavailable for the new engine, with a version marker; (c) drop them. **Nothing may
silently disappear from the frontmatter contract.**

**G3 — segmentation.** `fsmn-vad` leaves with funasr (measured comment, `asr.py:123-142`: without a VAD a
448 s recording collapsed to a single `。`). Segmentation returns as our chunker (G1's algorithm), and the
recorded lesson — that content-moving VAD knobs silently drop speech — must be re-measured the same way
(captured seconds vs duration), not assumed.

**G4 — hotwords.** The surface moves from a decode-time bias (`hotwords=`) to a **prompt / system
message** (`prompt="Vocabulary: …"`, verified in the model card). The register already says the current
list *injects* terms (13× `国际劳工仲裁` on ASR sides vs 0× on any caption side; two cases where a
character appears in neither source). The migration therefore carries a **two-arm measurement**, not an
assumption.

## 5. Decisions

| # | Decision | State |
|---|---|---|
| D1 | Model: **`Qwen/Qwen3-ASR-1.7B-hf`** | **settled** (operator, 2026-09-24) |
| D2 | Route: **transformers-native**, chunker ported from the `qwen-asr` package; **hard switch — no dual-engine flag, no compatibility path** | **settled** (operator, 2026-09-24) — see the box below |
| D3 | Timestamps: **`Qwen/Qwen3-ForcedAligner-0.6B-hf`** + our chunker | settled by D1/D2 |
| D4 | Confidence: **no confidence keys are emitted** — the code's existing no-score path (`_confidence_summary` returns `{}` when no segment carries a score), not a redefinition | **settled** (operator, 2026-09-24) — see the box below |
| D5 | Chunking: **180 s windows carrying timestamps**, boundary at the lowest-energy point, **exact tiling** (no overlap, no gap, no lost tail), 0.5 s zero-padding floor. Adopted as the package's measured constants, except that the **`1200 s` untimed variant is not adopted and does not exist in this implementation** — a chunk here is a caller-supplied cap on one aligned window | **settled** (architect, 2026-09-25) — named in the compass `## Decisions` row D5; shipped constants `bilibili-asr-archive/src/bili_asr/asr.py:52-56`, env override `:93`/`:241-253` |
| D6 | Hotwords: the shipped surface is the processor's free-form `prompt`, built as `"Vocabulary: " + ", ".join(hotwords)`; an empty tuple sends no prompt. Whether the list **pays for itself** is settled by T5's two-arm measurement, not assumed | **settled** (architect, 2026-09-25) — named in the compass `## Decisions` row D6; shipped expression `bilibili-asr-archive/src/bili_asr/asr.py:697`; protocol `{ITERATION_DIR}/iter-2026-09-qwen3-asr-closeout/guides/t5-hotword-measurement-protocol.md` |
| D7 | Environment: the AMD/WSL ROCm recipe; on the target host the repo `.venv` and `/root/gpu-venv` are interchangeable, and the conda env stays out of the ASR path | **settled and re-verified** (2026-09-25) — named in the compass `## Decisions` row D7: with `HSA_ENABLE_DXG_DETECTION=1` both venvs reach the RX 7800 XT (gfx1101, 15.8 GB) and `scripts/check_asr_env.py` passes all five invariants with exit 0. The `high` risk "repo `.venv` core-dumps under the DXG flag" did **not** reproduce |
| D8 | Provenance naming for new keys (engine/aligner/chunker) through the `naming-analyzer` discipline, recorded in one contract | procedure |
| D9 | Offline determinism: local snapshot dirs only, `HF_HUB_OFFLINE=1`, the "no download helpers" test stays green | procedure |
| D10 | Weights: **in-project at `bilibili-asr-archive/models/`** (gitignored), fetched from `hf-mirror.com` on the faster host, integrity-checked against the published LFS sha256 | **settled** (operator, 2026-09-24) |
| D11 | Precision: **bf16 only, no quantisation** | **settled** (operator, 2026-09-24) — evidence in the box below |
| D12 | Existing transcripts: **not re-transcribed**; the three archived parts keep their FunASR provenance and the archive will hold two engines' text, recorded as accepted | **settled** (operator, 2026-09-24) |

### D2 in detail — why the `qwen-asr` package is not the dependency
The package is viable on this hardware (its inference module has **no cuda/hip/rocm literal**; it reads
`self.model.device`, dispatches attention through the model's own `ALL_ATTENTION_FUNCTIONS`, keeps vLLM
behind an optional `try/except`, and `wheels.vllm.ai/rocm/` answers 200 from the host). It is rejected as
a **dependency**, not as an implementation:

```
qwen-asr 0.0.6 requires: transformers==4.57.6, nagisa==0.2.11, soynlp==0.0.493, accelerate==1.12.0,
                         qwen-omni-utils, librosa, soundfile, sox, gradio, flask, pytz,
                         vllm==0.14.0; extra == "vllm"
```

It **pins transformers to 4.57.6** and vendors its own `Qwen3ASRConfig` / `Qwen3ASRForConditionalGeneration`
/ `Qwen3ASRProcessor` (`qwen_asr.core.transformers_backend`) — it predates the upstream integration
(2026-06-26). The host runs **5.16.1**, which `funasr` depends on; installing the package would downgrade
it silently (funasr's requirement is unpinned, so pip would accept it). The cached `Qwen3-ASR-0.6B` on the
host is a `transformers_version: 4.57.6` artifact of that same era, and the `-hf` checkpoints we are
downloading are the upstream ones. **So: read the package's chunker/stitcher as a reference (Apache-2.0)
and re-implement it inside our boundary, keeping transformers 5.16.1.**

**Consequences of the hard switch (operator, 2026-09-24 — "引擎直接硬切，不考虑兼容").** No
`BILI_ASR_ENGINE`-style flag and no FunASR code path survive in the product:

- **Rollback is `git revert` / checking out the previous commit**, not a runtime switch. The old engine
  stays reachable only in the old revision and in `/root/gpu-venv` (which still has `funasr`).
- **T5's two-arm measurement can no longer run *through the product*** — it becomes a one-off script
  executed against the old revision (or against `gpu-venv`'s funasr) comparing transcripts on the same
  audio. The measurement itself is unchanged; only its home moves out of the shipped surface.
- `funasr` leaves the `[asr]` extra in the same commit that removes the code path, so no shipped
  dependency can load the old engine by accident.

### D4 in detail — cues stay, confidence goes (and why that is not a contract break)

A **cue** is the archive's atomic transcript unit: `{start, end, text}` shaped from the model's own token
timings (`asr.py:721-783` `_token_cues`), closed on sentence-ending punctuation, on a pause at or above
`CAPTURE_GAP_SECONDS = 1.0`, or on a character ceiling, with fragments absorbed into the cue before them.
It is not decoration — it **is** the product at every layer:

| Layer | The cue's role |
|---|---|
| `srt` / `txt` / `md` products | one cue = one subtitle line (`archive.py` → `_fmt_srt_time`) |
| store | `transcript_segments(start_ms, end_ms, text)` — literally the cue, **and the table has no confidence column** (`schema-transcripts.sql:40-42`) |
| coverage / provenance | `asr_vad_segments` and `asr_vad_captured_s` are computed from the merged cue spans ("as the cues testify", `archive.py:413`) |
| downstream editorial stages | the alignment builder and the proofread merge both aggregate ASR cues into their comparison blocks |

So the cue is never in question. What is optional is the **`confidence` field hanging off it**, and there
the existing code already defines the answer: `_confidence_summary` (`archive.py:306-361`) emits
`asr_mean_confidence` / `asr_low_confidence_cues` / `asr_low_confidence_at` **only when at least one cue
carries a numeric score, and emits nothing at all otherwise** — a documented, tested rule ("when it
carries no score neither is emitted"). Nothing reads those keys back: the store does not hold them, and
the only consumer of low-confidence locations is the in-memory result object that `coverage --quality`
prints (`cli.py:1788-1935`). The new engine simply reports no per-cue score, the summary returns `{}`, and
the frontmatter is honest by omission.

Reusing the old key names for a new quantity was rejected: FunASR's mean token score and an
autoregressive decoder's log-probability mean are **different quantities**, and publishing the second
under the first's name is exactly the silent contract redefinition this repository refuses. If a quality
signal is wanted later it arrives with a **new name and a new definition** (naming-analyzer discipline),
introduced deliberately rather than inherited.

### D11 in detail — the quantisation menu, and why bf16

**No quantised Qwen3-ASR-1.7B artifact is loadable by transformers.** Every quantised variant belongs to
another engine:

| Family | Representative repos (downloads) | Engine | Verdict for gfx1101 |
|---|---|---|---|
| GGUF | `handy-computer/Qwen3-ASR-1.7B-gguf` (191,744; BF16…Q4_K_M), `ggml-org` (20,604), `cstr` (6,219), `mradermacher` i1-IQ1…Q6, `FlippyDora`, `foryoung365`, `dseditor` | llama.cpp / transcribe.cpp | llama.cpp has HIP, but Qwen3-ASR audio support is a fork (`shershah1024/qwen3-asr-llamacpp`), not upstream → source build **and a different engine** |
| FP8 | `vrfai/Qwen3-ASR-1.7B-fp8` (6,314) | vLLM | no FP8 matrix hardware on RDNA3 |
| NVFP4 | `vrfai/…-nvfp4` (1,555; LLM only, audio tower + lm_head stay BF16) | vLLM | Blackwell fp4 kernels |
| TensorRT int8/int4 | `vrfai/…-int8`, `…-int4` (0) | TensorRT | NVIDIA |
| AWQ INT4 | `vrfai/Qwen3-ASR-0.6B-int4[-QAD]` (0.6B only) | vLLM/AWQ | CUDA-first kernels; no 1.7B |
| GPTQ | only `ReopenAI/Qwen3-omni-ASR-GPTQ-Int4` (omni, 9 downloads) | — | effectively absent |
| OpenVINO INT8 | `dseditor/Qwen3-ASR-1.7B-INT8_OpenVINO` (141) | OpenVINO | Intel |
| ONNX | `andrewleech/qwen3-asr-1.7b-onnx` (141) | ONNX Runtime | possible via MIGraphX EP, again a different engine |
| MLX / CoreML | mlx-community 8/6/5/4-bit, `illitan` Q8, `schroneko`, `Alkd`, `weiren119`, `UniMocha` INT8/INT4 | MLX / CoreML | Apple only |

Qwen publishes **no** quantised release of this family. Inside the transformers engine, quantisation is a
**load-time config over the same bf16 weights** (`BitsAndBytesConfig` int8/int4, `QuantoConfig`
int8/int4/float8/int2 with device-agnostic eager kernels, `TorchAoConfig`) — all three installable from
the tuna mirror (bnb 0.50.2, quanto 0.2.7, torchao 0.18.0), none installed. bitsandbytes' own install
docs list **gfx1101** among the PyPI ROCm wheel targets (ROCm 6.4.4 build; AMD's own ROCm page is
Instinct-only and lags), and quanto is device-agnostic. **Decision: none of them, for now** — a 1.7B bf16
checkpoint is 4.08 GB of a 15.8 GB card, so there is no fit problem to solve, and every quantised kernel
with a real ROCm story costs the transformers engine. Revisit only against a measured throughput trigger,
with the acceptance gate: identical transcript on a fixture + no crash + end-to-end timing.

## 6. Tasks

> **Refactor scope (operator directive, 2026-09-24): this is a rewrite of the ASR boundary, not a swap at
> the engine seam.** The old boundary conflates three things a single FunASR call happened to return —
> text, per-token timings and per-token scores. Qwen3-ASR returns only text; timings come from a second
> model; scores do not exist. So the cue builder, the segmentation and the confidence path are rewritten
> rather than adapted. What dies, what lives, and the new invariants: **§13**.

**T1 — engine seam.** Introduce the transformers boundary behind the existing `ASRRunner`/`ASRConfig`
surface with an injectable factory (the `fake_funasr` fixture becomes a fake processor/model).
*Verification:* engine-agnostic suite green with the new fake; the missing-dependency run still prints the
install hint.

**T2 — chunking + alignment (G1/G3).** Port the package's measured algorithm: 180 s windows with
timestamps, low-energy boundary search, no overlap/gap, short-chunk padding; per-window ASR → per-window
alignment → stitched monotonic millisecond segments.
*Verification:* synthetic fixture with known boundaries; a real 43-minute item and a multi-hour item
measured for captured-seconds ratio, seam duplicates and boundary loss; content-moving knobs re-measured,
not assumed.

**T3 — confidence + provenance (G2).** Implement D4's decision, update the frontmatter contract in one
place, re-read the affected residual.
*Verification:* keys asserted for both the available and unavailable cases; no key vanishes undocumented.

**T4 — CLI, knobs and docs.** `BILI_ASR_MODEL`/`_MODEL_ID`/`_DEVICE`/`_LANGUAGE` semantics preserved; a new
aligner knob; FunASR-only knobs retired loudly; `README.md` and `{SPECS_DIR}/asr-archive-cli.md` updated
in place; the weights path documented with the LFS digests.
*Verification:* `--help` and the README agree with the code; `bili-asr asr` runs with no Hub access.

**T5 — the corpus measurement (G4) and the host check.** Six-item corpus re-run under both engines with
insertions counted separately from recoveries; `check_asr_env.py` re-run; a Qwen smoke (load, transcribe
one short file, one alignment returns monotonic timings).
*Verification:* the two-arm numbers recorded with inputs; `check-asr-env` exits 0; residual rows updated.

**T6 — the archive's two-engine state (D12).** Record the accepted decision (no re-transcription) in the
docs and in the residual register so a later reader does not read it as a defect.
*Verification:* the decision is written where a reader of the frontmatter would look.

## 7. Done criteria

1. `bili-asr asr` transcribes through Qwen3-ASR on the target host with **no network** at run time.
2. Segments carry monotonic millisecond timings from the aligner, chunk boundaries recorded; a 43-minute
   and a multi-hour item both survive with their captured-seconds ratio measured against today's engine.
3. The frontmatter contract is complete and explicit for the new engine (whatever D4 decides).
4. The six-item corpus has a recorded two-arm comparison with insertions separated from recoveries.
5. `scripts/check_asr_env.py` exits 0 in the environment that runs ASR, and that environment is named in
   `README.md`; the weights live in-project and match the published digests.
6. No test asserts FunASR; the engine-agnostic suite is green; the "no download helpers" guard is green.
7. The docs and the frozen spec describe one engine, in one place.

## 8. STOP conditions

- A new dependency that reaches the network at import or run time → stop.
- A dependency that **downgrades transformers** (the `qwen-asr` pin) → stop.
- A timestamp that cannot be traced to an aligner call over the same audio → stop (no silent interpolation).
- A frontmatter key that changes meaning without a recorded decision → stop.
- A chunk seam that duplicates or drops speech with no named test → stop.
- vLLM or FlashAttention-2 entering the dependency set → stop.

## 9. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Long-audio behaviour of a 1.7B audio-LLM on 43-minute lectures is unmeasured | high | T2 measures it first on real items |
| The repo `.venv` cannot reach the device today (core dump with the DXG flag) | high | D7 makes it an explicit verified step; `/root/gpu-venv` is the measured-good fallback |
| The characterization suite (1843 lines) encodes FunASR's shapes | medium | T1 replaces the fake, not the assertions; FunASR-specific shape tests retired by name |
| Prompt-based hotword biasing may inject worse than decode-time biasing | medium | T5's two-arm design measures insertions directly |
| Two engines' text in one archive | low (accepted, D12) | T6 records the decision |
| `transformers` 5.16.1 is new enough that the API may still move | low | pin in `pyproject.toml`; the seam is one module |

## 10. Open questions

Both entries this section carried at draft time are settled, and neither is settled here: this plan's own §5
fixed **D4 (confidence)** as the no-confidence-keys option, and the still-open items of §6 T5/T6 —
**D5 (chunking constants)**, **D6 (the hotword prompt surface)**, the `BILI_ASR_MODEL` default expression and
the throughput target — are settled as named decisions in the compass `## Decisions` table of
`iter-2026-09-qwen3-asr-closeout` (rows D5 and D6), with the evidence the closeout produces. This section
therefore records no open question of its own; §14 lists what remains to be delivered.

## 11. Not in scope

- No quantisation (D11), no vLLM, no FlashAttention-2, no streaming, no fine-tuning.
- No change to the editorial stages, the manifest, the store or the publication boundary.
- No ASR-stack install into the conda env.
- No re-transcription of existing archive items (D12).
- No change to `iter-2026-09-transcript-editorial-stages`, which stays parked (its harness package
  was deleted from disk on 2026-09-25 by a separate operator decision — `HANDOFF.md` §9).

## 12. Appendix — the evidence behind §2

```bash
# target host, 2026-09-24
.venv/bin/python -c "import transformers; print(transformers.__version__)"        # 5.16.1
.venv/bin/python -c "import transformers as t; print(hasattr(t,'BitsAndBytesConfig'))"  # True
HSA_ENABLE_DXG_DETECTION=1 /root/gpu-venv/bin/python -c "import torch;print(torch.cuda.get_device_name(0))"  # RX 7800 XT
HSA_ENABLE_DXG_DETECTION=1 <repo>/.venv/bin/python -c "import torch;print(torch.cuda.is_available())"        # core dump
curl -sI https://hf-mirror.com/...            # 200, 7.58 MB/s
curl -sI https://huggingface.co/...           # timeout
# weights, in-project
hf download Qwen/Qwen3-ASR-1.7B-hf --local-dir <repo>/models/Qwen3-ASR-1.7B-hf          # HF_ENDPOINT=hf-mirror
hf download Qwen/Qwen3-ForcedAligner-0.6B-hf --local-dir <repo>/models/Qwen3-ForcedAligner-0.6B-hf# expected digests (HF and ModelScope records agree)
#   1.7B-hf/model.safetensors            4,076,193,080  2db53c7d81bd9b8cbc6a074e89be2c968a0d373fb4ee68bb1b1e14f7042dfee1
#   ForcedAligner-0.6B-hf/model.safetensors 1,835,545,960  00568245ceca5af1991d28562a75fe1ddc9bfeb041c27fda66947ea05c47fb86
```

### Operational note — how the weights were actually fetched (2026-09-24)

`hf download --local-dir` **fails against the mirror**: huggingface_hub 1.x uses Xet storage, and the Xet
CAS endpoint (`cas-server.xethub.hf.co`) rejects the mirror's authentication with
`HTTP 401 Unauthorized` after the small files succeed, so the download dies before the weights. The
working route is plain HTTP against the mirror's resolve endpoint:

```bash
export BASE=https://hf-mirror.com
curl -L -C - --retry 5 --retry-all-errors -o "<dest>/<file>" "$BASE/Qwen/Qwen3-ASR-1.7B-hf/resolve/main/<file>"
# then verify against the LFS sha256 above — the checkpoint is only trusted after that comparison passes
```

`HF_HUB_DISABLE_XET=1` is the equivalent switch if the CLI is preferred. ModelScope is an alternative
channel (its API reports the same sha256), but it throttles large files to ~300 kB/s on this host.

---

## 13. Refactor scope — what dies, what lives, what is new

`src/bili_asr/asr.py` is 895 lines. Roughly **700 of them are engine-shaped** and are rewritten; the rest
is product logic that survives. The split matters because the product rules were *measured on this
corpus*, and losing them silently would change the archive's output for reasons no one chose.

### 13.1 Dies (FunASR-shaped)

| What | Where | Why |
|---|---|---|
| `_load_default_model` / `funasr.AutoModel` | `asr.py:25-32` | engine |
| `DEFAULT_VAD_MODEL`, `DEFAULT_VAD_MAX_SEGMENT_S`, `VAD_MAX_SEGMENT_ENV_VAR`, `_resolve_vad_model`, `_resolve_vad_max_segment`, `BILI_ASR_VAD_*` | `asr.py:228-258`, `433-475` | `fsmn-vad` is a FunASR component; segmentation becomes our chunker |
| `_materialize_input` | `asr.py:370-393` | exists only because FunASR's VAD shells out to `ffmpeg` and a descriptor path is closed on `exec`; a transformers decode is in-process (**verify before deleting**) |
| `_token_cues` | `asr.py:721-822` | consumes FunASR's token stream; replaced by §13.3 |
| the `confidence` path: `ASRConfig` → segment field → `_confidence_summary` keys | `asr.py:734-783`, `archive.py:306-361` | no per-cue score exists (D4) |
| `funasr` in the `[asr]` extra | `pyproject.toml` | removed in the same commit as the code path (D2 hard switch) |

### 13.2 Lives (product rules, measured on this corpus)

| What | Where | Why it survives |
|---|---|---|
| Redaction / identity guards (`_FORBIDDEN_*`, `_is_redaction_safe_model_identifier`, `_is_hub_level_model_name`) | `asr.py:42-95` | engine-agnostic, and `quality.py:16` imports one of them |
| Error taxonomy (`ASRDependencyError`, `ASRModelError`), `MAX_MODEL_LOAD_ATTEMPTS` | `asr.py:96-104`, `260` | the retry/loudness contract |
| **The cue rules**: `_SENTENCE_ENDINGS`, `_CUE_CLOSING_MARKS`, `_CUE_MAX_CHARS = 60`, `_CUE_MAX_GAP_SECONDS = 1.0`, `_CUE_MIN_CHARS = 6`, `_CUE_MIN_SECONDS = 1.0` | `asr.py:268-279` | product decisions (when is a line readable), independent of which engine produced the timings |
| `segments_to_srt` / `segments_to_txt` / `_fmt_srt_time` | `asr.py:850-868` | the products; `archive.py:14` imports them |
| The runner contract: lazy construction, run-scoped reuse, `model_constructions` / `model_load_attempts` | `asr.py:477-689`, `coordinator.py:578/817-888`, `cli.py:2150-2160` | observable behaviour other suites assert |
| `_merged_cue_spans` and the `asr_vad_*` semantics (they describe the **merged cues**, not the VAD) | `archive.py:415-448` | the coverage numbers stay comparable |
| `DEFAULT_HOTWORDS` (the list itself) | `asr.py:125-227` | corpus vocabulary; only its *delivery* changes (prompt, D6) |

### 13.3 New logic — the pipeline Qwen3-ASR actually requires

```
audio (any length, from the archive root)
 └─ chunker: cut at a low-energy boundary (±5 s search, 100 ms windows)
      └─ 180 s chunks (aligner's practical bound) — the only branch: every path here carries timestamps, and the reference package's untimed 1200 s branch is NOT adopted (compass row D5)
 ├─ per chunk: Qwen3-ASR (transformers) → text + detected language
 ├─ per chunk: ForcedAligner(chunk audio, that text) → word/char timings
 └─ stitch: offset each chunk's timings by the chunk start, join the text
      └─ ALIGNED CUE BUILDER — the §13.2 cue rules, now driven by aligned words
           └─ cues {start, end, text} → srt / txt / md / raw → store → frontmatter
```

Two things this structure buys that the old one could not: **language becomes an output** (Qwen3-ASR
detects it; today `asr_language` is only the operator's hint echoed back — a decision is needed on
whether to record the detected value, see §10), and **chunking becomes explicit and inspectable**
instead of hidden inside a VAD component whose content-moving knobs once silently dropped speech.

### 13.4 Four invariants the new boundary must test (they did not exist before)

1. **Chunks tile the audio exactly** — concatenating them reproduces the input samples, no overlap, no
   gap, no dropped tail (the reference implementation guarantees this; our port must prove it).
2. **The aligned text is the archived text** — the string handed to the aligner is the string that lands
   in the product, so no cue can describe words that were never transcribed.
3. **Every timing traces to an aligner call over that chunk**, offset by its start — no interpolation, no
   invented boundaries.
4. **Cue rules are engine-independent** — the §13.2 thresholds produce the same *shape* decisions
   (close on sentence end / pause / ceiling; absorb fragments) whatever engine fed them.

### 13.5 The measured output structures (real run, 60 s of the archive's own audio)

Run on the target host, 2026-09-24, repo `.venv`, `Qwen3-ASR-1.7B-hf` + `Qwen3-ForcedAligner-0.6B-hf`,
audio = the first 60 s of `/mnt/e/asr-archive-20/audio/BV1147c6sEKs.p0.m4a`.

```text
REQUEST  (processor.apply_transcription_request(audio=...))
  keys: input_ids (1,795) int64 | attention_mask (1,795) | input_features (1,128,6000) float32
        | input_features_mask (1,6000) int32          # 6000 mel frames = 100/s × 60 s
  audio_token_ids: [151676, 151669, 151670]

ASR OUTPUT  (slice off the prompt: out[:, inputs["input_ids"].shape[1]:])
  RAW   (decode(gen))                        -> 'language Chinese<asr_text>拟象论啊，……政治隐喻啊。<|im_end|>'
  PARSED (return_format="parsed")            -> {'language': 'Chinese', 'transcription': '拟象论啊，……'}
  TEXT   (return_format="transcription_only")-> '拟象论啊，……政治隐喻啊。'
  ⚠ decode(..., return_format=...) hard-sets skip_special_tokens=True; feeding the RAW string to
    parse_output()/extract_transcription() instead leaves a visible '<|im_end|>' in the text.

ALIGNER  (processor.prepare_forced_aligner_inputs(audio, transcript=that text, language=...))
  input_ids (1,1235) int64 | attention_mask | input_features (1,128,6000) | input_features_mask
  word_lists: list[list[str]] -> per-character units for Chinese: ['拟','象','论','啊', …]  (151 units)
  config.timestamp_token_id: 151705
  forward: 0.1 s, single pass (NAR) -> logits (1, 1235, 5000)
  decode_forced_alignment(...) -> list[dict] with EXACTLY these keys:
      {'text': '拟', 'start_time': 0.0,  'end_time': 0.08}
      {'text': '象', 'start_time': 0.08, 'end_time': 0.32}
      … monotonic, float seconds, covering 0.0 → 59.04 for the sample

COST (60 s of audio, both models resident)
  ASR generate: 24.7 s  (~0.41× real-time)      ALIGNER forward: 0.1 s   (≈250× cheaper)
  peak GPU allocated: 6.02 GB of 15.8 GB
```

**What this settles for the design.** (1) The two-model split is right: the decoder yields text only. (2)
**The alignment is nearly free** — 0.1 s against 24.7 s — so the chunk size should be tuned around the
*decode*, and the 180 s alignment chunk costs nothing in aligner terms. (3) **Units are per character for
Chinese**, which maps one-to-one onto the surviving cue rules (they only ever needed per-unit
start/end times). (4) The decode rate is the migration's real cost: at 0.41× real-time a 43-minute
lecture needs ≈18 minutes of decoding — a number the old engine's single-pass VAD+decode did not pay.
(5) Still to measure at the real chunk size: the 180 s and 1200 s windows' VRAM and mel-frame counts
(18 000 and 120 000 frames), and one full-length item end to end.

### 13.6 The full-item measurement, and the three defects it found (2026-09-24)

One real item — `BV13hEB63En5.p0`, **47.4 min**, the archive's own audio — through the rewritten
boundary (16 chunks at the 180 s cap, chunk lengths 146–185 s, **tiling exact**):

| | prototype (before the mark fix) | module (after) |
|---|---|---|
| cues | 287 | **386** |
| cue seconds | mean 8.05 / max 21.76 | mean **6.11** / max 22.80 |
| characters in cues | 11 187 (**zero marks**) | **12 383** (243 sentence marks, 926 other marks) |
| captured | 0.814 (209 spans) | **0.850** (174 spans) |
| monotonic timings | — | **true** |
| wall clock | 844 s (0.297× real-time) | **428 s (0.151×)** |
| peak GPU | 9.65 GB | **9.60 GB** |
| runner counters | — | constructions=1, attempts=1 for 16 chunks |

**Defect 1 — the aligner does not return punctuation.** Its units are the characters it can time, so
marks never come back; the "close on a sentence-ending mark" rule therefore never fired and the marks
were lost from the product (11 187 vs 12 383 characters). Fixed by `_thread_text`, which threads every
character of the recognised text back onto the timed units in order. This is the migration's single
most important structural difference: FunASR returned marks as their own timed tokens.

**Defect 2 — the chunker degenerated when the search window could not be centred.** With the boundary
search reaching back past the current start, the quietest point landed on the window's edge and the
one-sample floor walked the audio: a 3.01 s recording came back as **161 chunks of ~4 samples**.
Fixing it by flooring progress at one window produced a second degeneration (a run of 100 ms chunks) —
caught by the suite, not by luck — so the rule is now: search only where the window is centred *and*
clear of the start, and otherwise cut. Real 180 s chunks were never affected (`expand ≪ max_len`),
which is exactly why only a small-cap test could find it.

**Defect 3 — padding inside the splitter broke its own promise.** A degenerate tail was zero-padded by
`_split_audio`, so the chunks no longer summed to the input (165 502 vs 160 000 samples). The pad now
happens in the runner, where the aligner's minimum-length requirement belongs; the splitter's tiling
promise is exact and checkable again.

**Two alarms that were the test's fault, not the code's**, kept here because both were resolved by
reading the old implementation rather than by changing a rule: the character ceiling absorbs an
undersized tail instead of publishing a one-character cue (deliberate), and the redaction pattern
passes a *relative* checkpoint path through while catching Windows paths, URLs and credential-marked
values (also deliberate — `README.md` documents the relative form). The same reading restored two
identity rules the first port had simplified away: `hub_level` is `"/" in value`, and
`_is_hub_level_model_name` **probes the filesystem** — a checkpoint directory that exists is not a
competing hub identity.

**First suite over the new boundary** (`tests/test_asr_qwen.py`, 32 tests): all pass on the host that
has numpy/soundfile; the 11 that need them skip where they are absent. The FunASR-shaped suites
(`test_asr_reproducibility.py` 1843 lines and friends) are the next work item and are expected red
until they are retired or rewritten.

### 13.7 The test-suite transition (2026-09-24)

**Retired by name** (deleted on `feat/20260924-qwen3-asr-transformers`, each survivor carried into
`tests/test_asr_qwen.py` first, and the retirement recorded in that file's docstring so a reader of the
diff knows where the assertions went):

| Retired | Lines | Why | Carried across |
|---|---|---|---|
| `tests/test_asr_reproducibility.py` | 1843 | FunASR `AutoModel` kwargs, token-timestamp normalization, `normalize_result`, VAD configuration, and a `fake_funasr` fixture; its `fail_torch_import` monkeypatch now recurses infinitely against the new loader | construction/attempt counters and their bounds, the dependency/model error taxonomy, provenance stability and redaction, **the offline guard** |
| `tests/test_asr_format.py` | 200 | `_RICH_TAG` cleanup and token-shaped cue shaping | the SRT/TXT writers and the SRT clock |
| `tests/test_asr_cues.py` | 77 | cue shaping from token timings, including the per-cue confidence the engine no longer has | the cue rules, now driven by aligned pieces |

`tests/test_check_asr_env.py` is untouched — it asserts torch/ROCm invariants only.

**Adaptation wave — 14 suites, 35 call sites.** Every suite that drives the ASR path through the CLI
stubs the module-level factory, and the seam changed shape: the factory now returns a **model set**
(four objects) instead of one model. Measured after the retirements: **1569 passed / 121 failed / 17
skipped / 2 errors**, with every failure coming from that one seam. The call sites carry bespoke intent
— a per-row failure, recorded construction kwargs, a factory that must never be called — so this is a
wave of careful conversions rather than a rename.

The shared double is now in place: `tests/_asr_fakes.py` exports `install(monkeypatch)` (factory +
audio reader patched, returns the set so a test can assert what the processor was asked to transcribe),
`raising(monkeypatch, exc)` and `forbidden(monkeypatch)` for the two special intents. Each converted
site loses its local `FakeModel` class and gains the call, which is also the point: one definition of
the seam instead of fourteen.

### 13.8 The wave is done (2026-09-24) — and what it found

**All 14 suites and 35 call sites are converted**, in three batches, every batch verified on the host
that owns the `[asr]` extra:

| | control host | target host |
|---|---|---|
| suite, at the wave's start | 1569 passed / **121 failed** / 23 skipped / 2 errors | — |
| suite, at the wave's end | **1576 passed / 0 failed / 0 errors / 135 skipped** | **1700 passed / 0 failed / 6 skipped / 5 errors** |

The target host's 5 errors are the pre-existing `test_cli_help.py` `installed_*` cases, which need `uv`
to provision an isolated venv — the same environment-limited five this repository has carried since
before the migration. The control host's 135 skips are the ASR-path cases: it has neither numpy nor
soundfile (and no installer at all), so they are verified where the extra lives.

Four things the wave taught, in order of how much they cost:

1. **A production defect, found by the suite rather than by a reviewer.** `transcribe()` imported
   numpy and soundfile *before* loading the model pair, so a host without the extra failed with a bare
   `ModuleNotFoundError: No module named 'numpy'` instead of the documented `ASRDependencyError` that
   names the `[asr]` install — the very error taxonomy `test_derived_queue_chain` asserts. The model
   pair now loads first and the readers' absence is reported the same way.
2. **The autouse torch stand-in in `tests/conftest.py` had to grow.** It replaced `sys.modules["torch"]`
   with a namespace carrying only `cuda.is_available`; the rebuilt boundary also runs inside
   `torch.inference_mode()`, so every ASR row died at its first decode with an `AttributeError` that the
   coordinator records as a **per-row failure in the run ledger** — visible only as `0 asr item(s)` with
   the row still `audio_ok`. The diagnostic path that found it: call the runner directly (works) →
   call the coordinator directly (works) → only pytest fails → read conftest.
3. **A row is identified at the read now, not at the model.** The boundary hands the model a chunk file
   — one scratch path for every row — so the old `generate(kwargs["input"])` doubles can no longer tell
   rows apart. `install(reads=…)` records the path of every recording the boundary opened (resolving a
   confined descriptor while it is still open) and `fail_when=` turns that into a per-row failure.
4. **Two consumers of the retired shaper were not stubs at all.** `test_quality`'s `recorded_cues` and
   `test_archive_md`'s threshold case fed real recorded FunASR data through `_token_cues`. The first now
   loads the 95 cues frozen beside its token dump — which keeps it a test of the quality surface *and*
   of reading a transcript the current engine no longer produces; the second drives the surviving
   builder through pieces, so it still pins the cue/pause threshold against `CAPTURE_GAP_SECONDS`.

---

## 14. 落地（2026-09-25）

`feat/20260924-qwen3-asr-transformers` 已 `--no-ff` 合并进 `main`：合并提交 **`3b561ea`**，已推送。

- **合并后 main 全量测试：1576 passed / 135 skipped / 0 failed**（控制端）；分支在拥有 `[asr]` 的目标端为 **1700 passed / 0 failed**（另有 5 个既有的 `uv` 缺失 error，与本次无关）。
- 合并前 main 上另有两个 chore 提交（`d3c515b` 丢弃 63,012 行渲染出的评审 diff、`18e8119` 让 `.mstar` 按自身规则本地化）。**两者都经受住了合并**：`--no-ff` 合并后 `.mstar` 追踪文件仍是 23 个，`git rm --cached` 的移除没有被分支带回来。
- 合并把这次迁移作为**一个单元**记录（11 个提交 + 1 个合并提交），而不是压成一条。

**仍然开着的（本计划的未完成项，非合并阻塞）**：
1. ~~T5 两臂热词测量~~ —— **已在冻结六件上跑完，2026-09-26**，结论 **`PARTIAL`**：`R=0 I=0 U=0`、
   P6 FAIL（0.941523，手读定位到 prompted arm 的一段英文退化循环）、P3/P4/P7/P8/C4 PASS、
   P9 的 `E=7 < 8` 使 P1/P2 uninformative。报告 `guides/t5-hotword-measurement-results.md`。
   该结论同时关闭 high 残留 `20260922-proofread-wave · R1`（见上方段落，含未覆盖部分）。
   六件音频先经 `R3` 丢失后重新下载（`/mnt/e/asr-archive-c6/audio`），报告 §1 记录了这点。
2. ~~T6 存量三件"旧引擎产物"的留痕~~ —— **已完成 2026-09-26**（commit `7b86882`）：README provenance
   段落新增 `### An archive can hold two engines' text, and that is decided, not broken`，登记为 `R4`（low）。
3. §13.6 与 §12 里尚未拍板的决定（D5 分块常数、D6 热词提示面、`BILI_ASR_MODEL` 默认表达、吞吐目标）—— 见 §5 与闭集 compass `## Decisions`：D5/D6 已具名（`settled`），默认表达为 **D13**，T5 协议为 **D14**，吞吐目标为 **C4**（≤0.4× 实时）
4. 真机 CLI E2E（操作者已明确暂缓）
