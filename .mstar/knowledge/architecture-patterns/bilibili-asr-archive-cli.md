---
module: bilibili-asr-archive CLI
date: 2026-08-23
last_updated: 2026-08-25
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
  - page-identity
  - meta-cursor
---

# Bilibili archive CLI architecture

## Context

A personal Bilibili archive has two very different workloads: metadata and
short-lived API/CDN requests, plus local transcript generation that may require
large model dependencies. The workflow must survive API risk control and be
safe to resume after a partial run. Multi-part videos need collision-free
per-part identity, and metadata enumeration must resume after risk stops
without misreading a deliberately bounded run as complete.

## Guidance

Keep `bili_client` as the only module that opens sockets. Expose transport
protocols and a binary-stream seam so API, CDN, and retry behavior can be
unit-tested without live media requests. Keep subtitle conversion, ASR
normalization, archive writers, and manifest updates pure or filesystem-only.
`BiliClient` never imports the cursor module; cursor I/O lives in the CLI /
`MetaCursorStore` seam.

Use a JSONL manifest keyed by `work_id` as the state machine SSOT. For
multi-part videos `work_id = bvid:p<zero-based-page-index>` and the
filesystem stem is `{bvid}.p{page_index}` (never put `:` in paths). State
machine: `pending -> meta_ok -> {subtitle_done | needs_audio -> audio_ok} ->
archived`, with `gone` as a per-video terminal state. Persist terminal state
atomically; write partial metadata after a risk ceiling so `--resume` can
continue.

### Resumable metadata enumeration (meta-cursor.json sidecar)

- Sidecar at archive root, keyed by `mid`: `next_page`, `total`, `state`,
  `last_api_error_code`, `updated_at`. Atomic same-directory temp file plus
  os.replace (matching ManifestStore.save).
- `state` enum: `risk_interrupted` (the only state `--resume` consumes,
  mid must match) | `limited` (deliberate cap; not full enumeration) |
  `complete` (visible archive fully enumerated) | `running` (in-memory only,
  never persisted).
- Advance rule: persist cursor after the corresponding manifest JSONL merge
  for each successful archive-list page; mid-run stays `risk_interrupted`
  with `next_page = last merged pn + 1`; terminal `complete`/`limited` only
  after the crawl returns. Risk exhaustion persists `next_page =
  last_failed_page` and exits 2.
- Without `--resume`, a new run replaces a stale cursor after the first
  successful page but never truncates the JSONL to a page-1 prefix (merge
  prior rows last-write-wins).
- `known_bvids` (seeding the no-new-bvid completion stop) is passed only on
  `--resume`; a full recrawl must walk to the last catalog page rather than
  stop on the first overlapping page.
- `--limit-pages N` counts pages fetched in the current call, not an absolute
  `pn` ceiling.
- Forbidden sidecar contents: cookies, SESSDATA, signed URLs, raw exception
  messages, request dumps.

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
keep credentials and signed URLs out of manifests and cursors, and turn
interrupted long runs into resumable work rather than a restart from zero.
Per-part identity prevents multi-part videos from overwriting each other's
subtitle/audio/transcript artifacts.

## When to Apply

Apply this pattern to archive or ingestion CLIs that combine rate-limited HTTP,
large binary downloads, optional local ML, and durable per-item progress with
multi-part sources and resumable enumeration.

## Evidence

- Iteration: `iter-2026-08-wmz-asr-mvp`, `iter-2026-08-archive-foundations`
- Source specs: `.mstar/specs/asr-archive-cli.md`,
  `.mstar/iterations/iter-2026-08-archive-foundations/specs/meta-cursor.md`
- Implementation: `bilibili-asr-archive/src/bili_asr/` (incl.
  `bilibili-asr-archive/src/bili_asr/meta_cursor.py`)
- Verification: 96 unit tests on Python 3.12 (MVP); 147 passed (plan 001);
  168 passed (plan 002), no live HTTP.
- Operational layer (ledger / FTS5 / coordinator) is documented in
  [operational-sidecars.md](operational-sidecars.md); 277 passed at
  `iter-2026-08-pilot-ops` close.
