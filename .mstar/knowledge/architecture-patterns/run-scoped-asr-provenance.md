---
module: local ASR execution
date: 2026-09-03
last_updated: 2026-09-13
problem_type: architecture_pattern
category: architecture-patterns
severity: medium
plan_id: "20260831-asr-reproducibility | 20260912-batch-model-reuse | 20260912-asr-provenance-identity"
applies_when:
  - running optional local ASR transcription for multiple archive items
  - comparing fixture-based ASR behavior across sequential runs
  - accepting local model selectors without exposing paths or credentials
  - integrating ASR into an existing subtitle-first coordinator
  - declaring which hub model produced a transcript, or debugging a refused declaration
  - adding or reading the ASR frontmatter's measurement keys, or recomputing them from a raw sidecar
  - deciding whether an ASR statistic belongs in a run's printed output or only on the runner
tags:
  - asr-runner
  - model-lifecycle
  - provenance
  - declared-identity
  - provenance-keys
  - vad-capture
  - reuse-line
  - fixture-testing
---

# Run-scoped ASR lifecycle and redacted provenance

## Context

Optional local ASR combines a heavyweight model dependency with a resumable archive coordinator. Constructing a model for every audio item wastes startup work, while a global cache would blur ownership and make cleanup or test isolation unpredictable. Runtime model selectors may also be local paths, and a path is never an identifier, so the producer's identity must be *declared* separately from the value the loader receives. The published row must additionally answer two questions a bare transcript cannot: how much audio the VAD actually captured, and where the doubtful cues are.

## Guidance

### One run scope, one runner, one stated cost

Use an explicit immutable configuration and a lazy runner owned by one sequential run scope. Construct the model on the first audio transcription, reuse that runner for later audio rows in the same scope, and release a coordinator-created runner when the batch exits. Keep injected runners caller-owned. Subtitle-first rows should return before runner construction, and the runner should never own manifest state or network behavior. One process is one run scope: `run`/`schedule`/`campaign` share the coordinator's shared batch entry (`run_batch`), and the in-process `asr`/`pilot` selections hold one runner per invocation, so `asr --pending --limit N` must not pay N constructions. `asr.transcribe()` stays the one-shot single-item wrapper — it is *loops* that must hold a runner, and a per-item `bili-asr asr --bvid …` loop is one process per item, which forfeits reuse.

Keep runtime selection separate from serialized provenance. Forward a configured local model path when the operator needs it, but retain only redaction-safe opaque identifiers and declared configuration intent in `provenance()`. Redact paths, URLs, credential-like values, raw exceptions, model bytes and media bytes. Keep the model factory injectable so deterministic fixtures can assert construction count and exact arguments without importing FunASR, downloading weights, or opening a network connection.

### Declared identity is not a load selector

`BILI_ASR_MODEL_ID` (`ASR_MODEL_ID_ENV_VAR`) is the operator's **declaration** of the hub-level identity behind the checkpoint; `BILI_ASR_MODEL` stays the value the loader receives. The declaration is read into the `model_id` field of `ASRConfig` — appended last, so existing positional construction does not shift — and **never reaches the loader**. It is not a new frontmatter key either: `provenance()` skips it while rendering and substitutes it into the `model_name` slot, so the nine-key configuration contract and its order (`model_name`, `model_revision`, `device`, `language`, `vad_model`, `vad_max_segment_s`, `hotwords`, `offline`, `local_source`) hold, and the declared value is re-scanned at that slot. Precedence is declared id → else the configured `model_name` when it is itself redaction-safe → else `[redacted]`; a configured local checkpoint directory therefore records `[redacted]`, because a path is not an identifier. Validation is loud, not silent: an invalid or credential-like declaration raises rather than quietly recording `[redacted]`, which would let the operator believe the archive names its producer.

The contradiction route — a declaration differing from an already-safe `model_name` — fires **only when that `model_name` is hub-level *and* does not resolve to a local directory** (`_is_hub_level_model_name`: `hub_level` plus `not os.path.isdir(value)`). A relative path-shaped selector such as models/Fun-ASR-Nano-2512 is a load *location*, not a competing identity; a shape-only rule cannot tell it from a hub id like Qwen/Qwen2.5-7B, and applying the route to it made the truthful declaration raise and archive nothing. Two different hub ids must still contradict. The revision companion is the existing `BILI_ASR_MODEL_REVISION`, which keeps its dual role (loader kwarg when set, recorded value) — no second variable.

### The published frontmatter: three runs, two gates

An ASR row publishes 24 keys, 15 of them `asr_*`, in this order: six row-identity keys (`bvid`, `title`, `date`, `duration_s`, `source`, `url`), then the measurement family (the three `asr_vad_*` capture keys, then `asr_mean_confidence` / `asr_low_confidence_cues` / `asr_low_confidence_at`), then the nine-key configuration family (`asr_model_name` … `asr_local_source`), then the trailing `work_id` / `page_index` / `cid` when the row resolves to a work item. The measurement family carries **two different presence rules**: the capture trio is **source**-gated (`source == "asr"` only — the subtitle path has no VAD), while the confidence trio is **score**-gated (emitted together whenever any cue carries a score, including `0` and `[]`; neither key when the transcript carries none). Do not restate one gate for both families. The capture keys are computed in `bilibili-asr-archive/src/bili_asr/archive.py` as a sibling of `_confidence_summary` and applied in `write_archive`; `CAPTURE_GAP_SECONDS` is declared locally with a focused test asserting it equals the shaper's own `_CUE_MAX_GAP_SECONDS`. The count and the location list are two renderings of **one** filtered list, so `len(asr_low_confidence_at) == asr_low_confidence_cues` holds by construction rather than by test.

### What "VAD captured" means without a boundary list

The model's result carries no VAD boundary list, so the capture span is the transcript's own cue intervals merged at `<= CAPTURE_GAP_SECONDS = 1.0` — the shaper's own pause threshold, one step wider than the shaper's split rule (which splits at `>=`). A gap of exactly 1.0 s is therefore two cues in the transcript and one span here, and that reading is deliberate and pinned in both directions; a naive "re-fuse the cues" recompute that drops the boundary case disagrees with the artefact. **Zero-length intervals (`end <= start`) are skipped**, which is what makes a recompute from the raw sidecar (`transcripts/raw/*.json`) exact: a zero-length cue describes no captured audio, its seconds are `0.0` so skipping leaves the duration sum identical, and merging it could bridge two real spans into one. Rounding is 3 decimals like `asr_mean_confidence`; `asr_vad_captured_s` stays unclamped so a duration/cue contradiction stays visible, the ratio is clamped to `[0, 1]`, and it divides the *published* (already-rounded) seconds so a reader holding only the artefact reproduces it — the ratio is omitted, not guessed, when `duration_s` is not a positive finite number. These keys answer *how much*, not *where*: they discriminate a speaker pause from a VAD miss (24 spans / 413.63 s / 0.921 straight-through; 25 / 413.63 / 0.767 with a 90 s pause injected; 19 / 334.76 / 0.621 with 90 s of cues deleted), but localising a doubtful stretch still requires the raw sidecar's `segments`.

### Counted is not printed

The runner's `model_load_attempts` counter records failed loads separately from `model_constructions` (successful constructions only), with `model_load_attempts >= model_constructions` and equality when every load succeeded. The printed per-batch reuse line carries constructions only, and its guard is "nothing was paid": it prints when `asr_items > 0` **or** `model_constructions > 0`, so a batch that built the model and then failed every transcription still states `… for 0 asr item(s)`. A batch whose **every load was rejected** paid no construction and transcribed nothing, so it prints nothing at all: its N retries are visible only to a caller holding the runner. The attempt count is therefore an attribute-level observable, not an operator-visible one — a known gap carried as a registered residual, not a feature to advertise, and the next plan touching the runner's lifetime must not silently reverse it.

### The reuse line's contract

One line per batch, on **stderr**: `<command>: model constructions=<n> for <m> asr item(s)`, produced by `model_constructions_line` in `bilibili-asr-archive/src/bili_asr/coordinator.py` and printed by all five labels — `run`, `schedule`, `campaign` through the coordinator's shared batch entry (`run_batch`), `asr` and `pilot` through the CLI's in-process helper. `<n>` is the constructions *this batch* paid (`after - before`, so a caller-injected runner reused across batches reports per-batch truth) and `<m>` counts rows whose `asr` stage produced a transcript. A subtitle-only batch prints nothing, so subtitle-only output is unchanged; a paid batch always states its cost. stdout stays untouched — `campaign`'s stdout is a single JSON document that downstream callers parse — and when fd 2 is closed the line is dropped rather than allowed to fold into stdout.

### The redaction rule is separator-aware

Credential markers must match with a letter-free separator boundary, not `\b`: an underscore is a word character, so a word-boundary rule let a value such as myorg/token_abc through and published it verbatim in `asr_model_name` and the raw sidecar, while `tokenizer` must still pass. Use the separator-aware form (`(?:^|[^A-Za-z])…(?![A-Za-z])`) that the file-name credential scan already applies, and keep it in **one** helper so validation and rendering cannot drift apart. The rule stays shape-based: it is not path-aware, so a relative path-shaped value satisfies it and would be recorded — declare the hub identity, not a relative path.

```python
config = ASRConfig(
    model_name="/srv/models/Fun-ASR-Nano-2512",  # what the loader receives
    model_id="FunAudioLLM/Fun-ASR-Nano-2512",    # what the archive records
    model_revision="approved-revision",
    device="cpu",
    offline=True,
    local_source="configured-local",
)
runner = ASRRunner(config, model_factory=fake_factory)
first = runner.transcribe(audio_path)
second = runner.transcribe(other_audio_path)  # same fake model, sequentially
provenance = runner.provenance()  # declared identity, never the path
runner.release()
```

## Why This Matters

Run-scoped ownership bounds the lifetime of heavyweight model state without introducing a process-global cache or concurrency promise. The subtitle-first short circuit preserves the lightweight no-model path. Separating a *declared* identity from the load value lets an operator use a populated local checkpoint directory while manifests, reports and comparison evidence stay safe, reproducible, and truthful about which model produced a transcript. The measurement keys make quality auditable from the artefact alone — how much audio was covered and where the doubtful cues are — without a human reference transcript. Stating the batch's construction count on stderr makes the reuse the run actually got visible to the operator without changing any command's stdout contract.

## When to Apply

- An optional local ML dependency is used repeatedly within one sequential batch or in-process loop.
- A coordinator must distinguish resources it creates from resources injected by its caller.
- Tests need reproducible model-construction and normalization evidence without model weights.
- Configuration can contain local paths, URLs, or values that must never enter serialized diagnostics.
- An archive must name its producer while the loader keeps receiving a local checkpoint directory.
- A reader recomputes capture or confidence facts from a raw sidecar, or adds a key to the published frontmatter.

## Examples

### Before

```python
for item in audio_items:
    segments = transcribe(item.audio_path)  # constructs AutoModel per item
```

### After

```python
runner = ASRRunner(config, model_factory=fake_factory)
try:
    for item in audio_items:
        segments = runner.transcribe(item.audio_path)
finally:
    runner.release()
# stderr: run: model constructions=1 for 3 asr item(s)
```

## Evidence

- Iteration specs: `.mstar/iterations/iter-2026-09-asr-ops-hardening/specs/02-batch-reuse.md` (D2.1–D2.7) and `.mstar/iterations/iter-2026-09-asr-ops-hardening/specs/04-provenance-observability.md` (D4.1–D4.10); earlier `.mstar/iterations/iter-2026-08-persistence-scale-safety/specs/asr-reproducibility.md`.
- Plan ids: `20260831-asr-reproducibility`, `20260912-batch-model-reuse`, `20260912-asr-provenance-identity` (plan files `{PLAN_DIR}/20260912-batch-model-reuse.md` and `{PLAN_DIR}/20260912-asr-provenance-identity.md`; `{PLAN_DIR}` is gitignored, so the files live in the control worktree).
- Implementation: `bilibili-asr-archive/src/bili_asr/asr.py` (`ASR_MODEL_ID_ENV_VAR`, the `model_id` field of `ASRConfig`, `_is_redaction_safe_model_identifier`, `_is_hub_level_model_name`, `_FORBIDDEN_PROVENANCE`, `provenance()`, `model_constructions`, `model_load_attempts`), `bilibili-asr-archive/src/bili_asr/archive.py` (`_capture_summary`, `_merged_cue_spans`, `_confidence_summary`, `CAPTURE_GAP_SECONDS`), `bilibili-asr-archive/src/bili_asr/coordinator.py`, and `bilibili-asr-archive/src/bili_asr/cli.py`; pinned by `bilibili-asr-archive/tests/test_asr_reproducibility.py`, `bilibili-asr-archive/tests/test_archive_md.py` and `bilibili-asr-archive/tests/test_cli_asr.py`.
- QA: `{SDD_DIR}/20260912-batch-model-reuse/review/qa-gate.md` (all five labels, one construction per batch, stderr-only, paid-but-empty line, `campaign` stdout still one JSON document) and `{SDD_DIR}/20260912-asr-provenance-identity/review/qa-gate.md` (declared identity reproduced from `bilibili-asr-archive/README.md` alone; A5 recomputed independently from the raw sidecar on the recorded fixture — 24 / 413.63 / 0.921 / `[3.72]`; 1565 passed / 4 skipped).
- QC: `{SDD_DIR}/20260912-asr-provenance-identity/review/qc-consolidated.md` (the to-fix table) and `{SDD_DIR}/20260912-asr-provenance-identity/review/qc1.md` (its "Knowledge at iteration-close" paragraph) — F-001 (the separator-aware credential rule), F-002 (the contradiction route amended to "hub-level **and** not a local directory"), and the four items this promotion must not drop.
- Not verified here: the real load with `BILI_ASR_MODEL_REVISION` declared beside a local checkpoint directory was run manually on the target WSL2 host via `bilibili-asr-archive/scripts/probe_target_host_load.py` and re-read, not re-executed on the QA host (no FunASR/torch); A5 was reproduced on the recorded 95-cue fixture, not on the 2026-09-12 output root (its sidecars are absent on that host). A real corpus run on the operator's host remains the operator's check.
