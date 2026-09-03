---
module: local ASR execution
date: 2026-09-03
problem_type: architecture_pattern
category: architecture-patterns
severity: medium
plan_id: 20260831-asr-reproducibility
applies_when:
  - running optional local SenseVoice transcription for multiple archive items
  - comparing fixture-based ASR behavior across sequential runs
  - accepting local model selectors without exposing paths or credentials
  - integrating ASR into an existing subtitle-first coordinator
tags:
  - asr-runner
  - model-lifecycle
  - provenance
  - offline
  - sequential
  - fixture-testing
---

# Run-scoped ASR lifecycle and redacted provenance

## Context

Optional local ASR combines a heavyweight model dependency with a resumable archive coordinator. Constructing a model for every audio item wastes startup work, while a global cache would blur ownership and make cleanup or test isolation unpredictable. Runtime model selectors may also be local paths, so diagnostic provenance must not serialize them as if they were stable public identifiers.

## Guidance

Use an explicit immutable configuration and a lazy runner owned by one sequential coordinator/run scope. Construct the model on the first audio transcription, reuse that runner for later audio rows in the same scope, and release a coordinator-created runner when the batch exits. Keep injected runners caller-owned. Subtitle-first rows should return before runner construction, and the runner should never own manifest state or network behavior.

Keep runtime selection separate from serialized provenance. Forward a configured local model path when the operator needs it, but retain only redaction-safe opaque identifiers (for example, a slash-qualified model identifier) and declared configuration intent in `provenance()`. Redact paths, URLs, credential-like values, raw exceptions, model bytes, and media bytes. Keep the model factory injectable so deterministic fixtures can assert construction count and exact arguments without importing FunASR, downloading weights, or opening a network connection.

```python
config = ASRConfig(
    model_name="iic/SenseVoiceSmall",
    model_revision="approved-revision",
    device="cpu",
    offline=True,
    local_source="configured-local",
)
runner = ASRRunner(config, model_factory=fake_factory)
first = runner.transcribe(audio_path)
second = runner.transcribe(other_audio_path)  # same fake model, sequentially
provenance = runner.provenance()  # identifiers and intent, never local secrets
runner.release()
```

## Why This Matters

Run-scoped ownership bounds the lifetime of heavyweight model state without introducing a process-global cache or concurrency promise. The subtitle-first short circuit preserves the lightweight no-model path. Separating runtime selectors from provenance lets an operator use a populated local model directory while keeping manifests, reports, and comparison evidence safe and reproducible.

## When to Apply

- An optional local ML dependency is used repeatedly within one sequential batch.
- A coordinator must distinguish resources it creates from resources injected by its caller.
- Tests need reproducible model-construction and normalization evidence without model weights.
- Configuration can contain local paths, URLs, or values that must never enter serialized diagnostics.

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
```

## Evidence

- Iteration spec: `.mstar/iterations/iter-2026-08-persistence-scale-safety/specs/asr-reproducibility.md`
- Plan: `.mstar/plans/20260831-asr-reproducibility.md`
- Implementation: `bilibili-asr-archive/src/bili_asr/asr.py` and `bilibili-asr-archive/src/bili_asr/coordinator.py`
- Verification: `.mstar/sdd/20260831-asr-reproducibility/review/qa.md` records the mandatory L4 suite (`89 passed`) and fixture-only boundary.
