# ASR boundary: load Fun-ASR-Nano locally and keep its native punctuation

> Standalone fix (no iteration). Compressed hotfix path per `mstar-phase-gates` § Hotfix 例外:
> `specify(min) -> plan(min) -> implement`, with the clarify/RCA notes recorded after the fact.
> Execution mode: `inline`.
> Trigger: operator request 2026-09-11 — "用 Nano 原生标点,改好之后 e2e 一个视频".

## Status

- Priority: P0 (the shipped ASR path could not load its configured model, and long recordings
  collapsed even when it did)
- Task category: backend / defect-fix + live verification
- Status: Done (inline hotfix; branch `fix/20260911-asr-native-punctuation`)
- Depends on: none
- Primary spec: `.mstar/specs/asr-archive-cli.md` (frozen) + `{KNOWLEDGE_DIR}/architecture-patterns/run-scoped-asr-provenance.md`
- Owner: fullstack-dev (PM inline)
- QA gate: pm-acceptance (hotfix path)
- Findings cleanup: zero-residual

## Goal

One real video goes audio → local ASR → transcript archive on the shipped CLI, and the stored
text carries Fun-ASR-Nano's own punctuation with real per-cue timings.

## Specify (defects D1–D4, each reproduced)

- **D1 — the model cannot load.** `AutoModel(model="FunAudioLLM/Fun-ASR-Nano-2512",
  trust_remote_code=False)` raises `RuntimeError: model ... is not registered` (funasr 1.4.15,
  reproduced twice). The checkpoint is a remote-code model with no FunASR alias, but its own
  `config.yaml` declares `model: FunASRNano`, which **is** registered — so a **local snapshot
  directory** loads it with `trust_remote_code=False` (live: `<All keys matched successfully>`,
  12.9 s).
- **D2 — the call named behaviour it did not perform.** `transcribe()` sent `use_itn=True`
  (Nano reads `itn`), three VAD-only kwargs, and `language="auto"`, which becomes the literal
  prompt fragment `语音转写成auto：`.
- **D3 — the result shape was not understood.** `normalize_result()` handled `sentence_info`
  (ms) and `timestamp` pairs only; Nano returns `timestamps` as `{"token","start_time",
  "end_time"}` in **seconds**, punctuation included, so any Nano transcript collapsed.
- **D4 — no VAD, so long recordings collapsed.** Measured on the 448 s pilot recording: a
  single no-VAD decode returns `text` of **one character** (`。`) with the same checkpoint, in
  *both* the old and the new call shapes (the kwargs are irrelevant). The same audio behind
  `vad_model="fsmn-vad"` returns the full punctuated transcript — `text` 2227 chars,
  `timestamps` 2064 tokens — which normalizes to 124 punctuated cues. The pre-migration
  SenseVoice-era boundary had the VAD wired; the Nano migration dropped it.

## Clarify (decisions, each with its reason)

1. **Load route = local snapshot + registered class, `trust_remote_code=False` kept.** The
   documented hub route executes the checkpoint's own `model.py`, and `hub="hf"` cannot be
   revision-pinned at all (`funasr/download/download_model_from_hub.py:291`). The local path
   keeps the security posture and makes `BILI_ASR_MODEL_REVISION` meaningful, at the cost of
   requiring the snapshot to be materialized first (roadmap item 1).
2. **No `punc_model`.** Nano punctuates natively (`auto/auto_model.py:430-431`); a chained one
   is lossy and is skipped on the VAD path anyway (`auto_model.py:1072`).
3. **VAD is required, not deferred.** Decision revised by measurement: D4 shows the no-VAD
   long-audio path is unusable, so `vad_model="fsmn-vad"` is the default with FunASR's
   documented 30 s single-segment cap; `BILI_ASR_VAD_MODEL` with a blank value disables it.
4. **Cue segmentation comes from Nano's token timestamps.** The VAD result carries 2064 token
   entries including punctuation, so cues are cut at sentence punctuation, at pauses ≥ 1.0 s,
   and at a 60-character ceiling — no `sentence_timestamp=True` (which warns without a punc
   model and returns no `sentence_info`).
5. **`language` becomes explicit config, default `None`.** `None` leaves the model's generic
   `语音转写：` prompt; the bogus literal `"auto"` is gone.
6. **`BILI_ASR_DEVICE` env override added.** The coordinator built `ASRConfig(...)` with the
   `cuda` default, so a CPU-only host could not run ASR at all.

## Non-goals

- No `punc_model`, no hotword plumbing, no changes to the subtitle path, no SQLite-side audio
  stage, no punctuation post-processing of Bilibili AI captions.

## Architecture

`src/bili_asr/asr.py` keeps its boundary and changes four seams:

- `ASRConfig` gains `language` and `vad_model` (default `fsmn-vad`).
- `_get_model()` passes `vad_model` + `vad_kwargs={"max_single_segment_time": 30000}` when the
  VAD is configured, and keeps `trust_remote_code=False`.
- `transcribe()` sends only what the pinned model reads (`input`, `cache`, `itn`, and
  `language` when set), and materializes a descriptor path into a temporary file because the
  VAD pipeline reads its input more than once.
- `normalize_result()` gains the Nano branch: token dicts → cues grouped at `。！？` / pause /
  60-character ceiling, text preserved verbatim; `sentence_info` and legacy `timestamp` pairs
  keep working.
- `coordinator.py` builds its runner through the new `default_config()`.

## Global Constraints

- `trust_remote_code=False` stays; no remote code is executed.
- No credential, path, or raw payload enters provenance; a local checkpoint path renders as
  `[redacted]` (existing behaviour, re-asserted).
- Punctuation is preserved verbatim; the ASR path makes no quality claim and rewrites nothing.
- The legacy result shapes (`sentence_info`, `timestamp` pairs) may not regress.

## Tasks

1. Load route and call shape — `src/bili_asr/asr.py`, `src/bili_asr/coordinator.py`.
2. Nano result normalization — `src/bili_asr/asr.py`.
3. VAD wiring for long audio — `src/bili_asr/asr.py`.
4. Unit tests on the recorded contract — `tests/test_asr_format.py`,
   `tests/test_asr_reproducibility.py`.
5. Live E2E, one video, shipped CLI — evidence only.

## Verification

- `pytest -q`: **1326 passed, 4 skipped** at the final HEAD.
- Focused: `tests/test_asr_format.py` + `tests/test_asr_reproducibility.py` — 37 passed.
- Live E2E on the GPU box (`BV1wLTP6NE9h:p0`, 448 s): shipped `bili-asr asr`, local checkpoint,
  CPU, VAD on — `BV1wLTP6NE9h:p0: archived (asr)` in 3m40s (rtf 0.444), producing
  `transcripts/{srt,txt,md}/` plus raw JSON, **124 cues** (first 0.18 s, last 447.67 s, strictly
  increasing, non-overlapping, median gap 0.54 s), TXT 2251 chars with `。`×90 `，`×116 `？`×17,
  107/124 cues closed on a sentence mark, manifest `archived` with `srt_path`, and no
  credential or descriptor path in any artifact.

## Evidence log

- Reproduced D1 twice (funasr 1.4.15) and once on the GPU box (funasr 1.4.14).
- Local-path load without remote code: `<All keys matched successfully>`, 12.9 s; 60 s slice
  transcribed in 25.3 s (rtf 0.372) with `。，？` present.
- No-VAD full recording: `text` = 1 char (`。`), `ctc_timestamps` = 479/443 for both call
  shapes → D4.
- VAD full recording: `text` = 2227 chars, `timestamps` = 2064, normalized to 124 cues.
- **Corrigendum (process).** The first "E2E" ran the *old* checkout through a stale PEP 660
  editable install in the GPU box's venv; the live run therefore proved nothing about this
  change (and its single whole-file cue came from the old normalizer). Lesson: before trusting
  a live run, assert the module that actually loaded (`module.__file__`) and the branch it came
  from. The corrected run asserts both.

## Durable Roadmap and Dependencies

1. **Materialize the pinned checkpoint at the composition root.** Owner: next audio/ASR
   iteration. Trigger: operators must currently pre-download the snapshot and point
   `BILI_ASR_MODEL` at it. Done when a shipped command can resolve a hub id at a pinned
   revision and hand the runner a local directory (the boundary itself stays download-free).
2. **Hotwords.** Owner: next audio/ASR iteration. Trigger: recurring proper-noun errors
   (`黑格尔`, `海德格尔`, this corpus's vocabulary). Done when `hotwords` is configurable and
   recorded in provenance.
3. **SQLite audio stage.** Owner: next audio/ASR iteration; this E2E necessarily ran on the
   legacy manifest path because the SQLite archive has no audio acquisition stage yet.
4. `provenance()` records `model_name` / `model_revision` / `device` / `language` / `vad_model`;
   a local checkpoint path is redacted, so the pinned revision — not the filesystem path — is the
   recorded identity.

## Review Gate Summary

> Filled at close.

- PM self-review (hotfix path): scope stays inside the ASR boundary plus one coordinator line;
  every claim is reproduced by a command recorded above; two earlier conclusions (the "no-op"
  VAD kwargs, and the first E2E) are corrected in place rather than quietly dropped.
- Residuals at close: none open. Roadmap items 1–3 carry forward into the next audio/ASR
  iteration; the two operator-visible follow-ups are (a) pre-materialize the pinned checkpoint
  and (b) remove the GPU box's scratch copy (`.tmp`-style hygiene).
- Corrections made during the work, kept deliberately visible: the "VAD kwargs are no-ops"
  reading (true for the call, irrelevant to the failure), and the first E2E that ran the old
  checkout through a stale editable install.
