---
module: bilibili-asr-archive CLI
date: 2026-08-23
problem_type: architecture_pattern
category: architecture-patterns
severity: medium
plan_id: iter-2026-08-wmz-asr-mvp
tags:
  - bilibili-api
  - resumable-cli
  - optional-asr
  - risk-control
  - transport-seam
---

# Bilibili archive CLI architecture

## Context

A personal Bilibili archive has two very different workloads: metadata and
short-lived API/CDN requests, plus local transcript generation that may require
large model dependencies. The workflow must survive API risk control and be
safe to resume after a partial run.

## Guidance

Keep `bili_client` as the only module that opens sockets. Expose transport
protocols and a binary-stream seam so API, CDN, and retry behavior can be
unit-tested without live media requests. Keep subtitle conversion, ASR
normalization, archive writers, and manifest updates pure or filesystem-only.

Use a JSONL manifest keyed by `bvid` as the state machine SSOT:
`pending -> meta_ok -> {subtitle_done | needs_audio -> audio_ok} -> archived`,
with `gone` as a per-video terminal state. Persist terminal state atomically;
write partial metadata after a risk ceiling so `--resume` can continue.

Treat API risk ceilings as batch-stop conditions (exit 2), but treat CDN stream
failures as per-video failures so one flaky media request does not discard the
whole batch. Check non-empty `.m4a`/`.flac` artifacts before API probes, and
pace sequential video work between requests.

Make heavy ASR dependencies optional and import them lazily. The base CLI must
still expose help/status/subtitle workflows, while `transcribe()` returns an
actionable install hint. Keep model weights outside the repository and support
a local model path for offline runs.

## Why This Matters

These boundaries make the no-login subtitle-first path useful without a model,
keep credentials and signed URLs out of manifests, and turn interrupted long
runs into resumable work rather than a restart from zero.

## When to Apply

Apply this pattern to archive or ingestion CLIs that combine rate-limited HTTP,
large binary downloads, optional local ML, and durable per-item progress.

## Evidence

- Iteration: `iter-2026-08-wmz-asr-mvp`
- Source spec: `.mstar/specs/asr-archive-cli.md`
- Implementation: `bilibili-asr-archive/src/bili_asr/`
- Verification: 96 unit tests passed on Python 3.12.
