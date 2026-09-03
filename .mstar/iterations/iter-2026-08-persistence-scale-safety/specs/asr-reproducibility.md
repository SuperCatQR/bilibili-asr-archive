# Reproducible local ASR execution specification

> Promoted to: `.mstar/knowledge/architecture-patterns/run-scoped-asr-provenance.md` (2026-09-03)

## Problem

`bili_asr.asr.transcribe()` lazily imports FunASR but constructs `AutoModel` for every audio item, uses `trust_remote_code=True`, selects an environment/default model without a revision contract, and emits no stable provenance. This makes repeated local runs slow, difficult to compare, and difficult to diagnose without risking secrets or media in evidence.

## User outcome

A local operator can configure a SenseVoice model explicitly, reuse one model instance across a sequential run, compare normalized fixture output deterministically, and inspect redacted model/config/dependency provenance without a model download or live network requirement in tests.

## Contract

- Preserve the optional ASR boundary and existing `transcribe(audio_path, model_name=None)` compatibility wrapper.
- Add an injectable `ASRConfig` and `ASRRunner` boundary with explicit model identifier, offline/local-source intent, CPU settings, and optional revision metadata. Names must remain Python `snake_case`/PascalCase and describe behavior.
- `ASRRunner` constructs the model lazily once per coordinator/run scope and reuses it for subsequent items. Tests inject a fake model factory; no test imports a real FunASR installation.
- `normalize_result`, SRT/TXT conversion, rich-tag cleanup, timestamp conversion, dependency errors, and model errors retain their current observable contracts except for stable redaction-safe diagnostics.
- `provenance() -> dict[str, str]` returns only redacted identifiers/revisions/config values. It must not include `BILI_SESSDATA`, cookies, URLs, absolute local paths, raw exceptions, model bytes, or media bytes.
- `ASRRunner` constructs the model lazily on the first audio transcription, caches it only on that runner instance, and releases it when the coordinator's `run_batch` scope ends. The coordinator creates the runner after its persistence writer boundary is acquired and passes it only to audio-required rows; subtitle-first rows do not construct a runner. The runner never mutates manifest state.

## Phase 1 prepare decision

- **Specify and clarify:** complete. This plan is a code-first run-scoped lifecycle and provenance slice, not a model-quality, model-distribution, live-campaign, or process-only initiative.
- **Plan boundary:** implementation may begin only after the iteration registration, feature-worktree lease, and explicit plan lock; until then this specification defines scope and acceptance only.
- **Deferred roadmap:** measured sequential ASR evidence follows this iteration's Phase 5 and an operator-approved fresh denominator; model/dependency pinning and concurrency require separate approved plans.

## Required evidence

- Fake factory tests prove one model construction for multiple sequential transcriptions and deterministic generation arguments.
- Compatibility tests prove the wrapper still handles the existing result shapes and error classes.
- Provenance serialization tests reject forbidden markers and absolute-path leakage.
- Offline/local configuration tests never open a socket or trigger a model download.
- A fixture benchmark records construction count and normalized output shape, not wall-clock claims from unavailable hardware.

## Non-goals

No model-weight download, model replacement, semantic accuracy claim, diarization, LLM correction, live Bilibili traffic, credential acquisition, media persistence, or concurrency implementation.
