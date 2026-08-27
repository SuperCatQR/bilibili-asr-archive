---
module: bilibili-asr-archive CLI
date: 2026-08-23
last_updated: 2026-08-28
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
  - audio-budget
---

# Bilibili archive CLI architecture

## Context

A personal Bilibili archive has two very different workloads: metadata and
short-lived API/CDN requests, plus local transcript generation that may require
large model dependencies. The workflow must survive API risk control and be
safe to resume after a partial run. Multi-part videos need collision-free
per-part identity, and metadata enumeration must resume after risk stops
without misreading a deliberately bounded run as complete. Repeated full-visible-
corpus batches also need an explicit sequential scheduler whose progress is
separate from the manifest state machine.

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

### Sequential scheduler contract

Use `schedule` as a bounded orchestration layer over the existing client,
manifest, cursor, coordinator, budget, and reclaim seams. It owns neither HTTP
nor a second item state machine. Every call has an explicit finite limit and a
scope; **scheduler.json** records whether that batch is `complete`, `limited`,
or `risk_interrupted`. Resume only a matching-scope risk interruption. Keep
short-video selection as the default, and require `--allow-long-live` plus a
positive audio cap for multi-hour work. A bounded batch must never claim full
corpus completion merely because its local limit was reached.

Make heavy ASR dependencies optional and import them lazily. The base CLI must
still expose help/status/subtitle workflows, while `transcribe()` returns an
actionable install hint. Keep model weights outside the repository and support
a local model path for offline runs.

### Bounded transient-audio policy

Treat downloaded audio as a transient stage artifact rather than archive
content. Before downloading a `needs_audio` row, estimate its peak footprint as
`duration_s * 8_000` bytes (a conservative 64 kbps ceiling) plus current archive audio-directory usage. `pilot`, live `run`, and `schedule` skip the
item with `audio_budget` if that would exceed `--max-audio-gb`; the default is
10 GiB and `0` disables the cap except on `--allow-long-live`, which refuses a
disabled cap. The pilot's `--max-duration-min` default of 45 excludes long rows,
including pagelist siblings, from bounded selection. `schedule` pending/failed
uses the same 45-minute short-video policy unless the operator passes
`--allow-long-live`; an explicit multi-hour `work_id` without that flag is a
usage error. The long-live summary prints the conservative estimate, measured
audio-directory peak, and post-archive usage after reclaim.

When an archive write completes, call the filesystem-only reclaim helper to
remove the row's `.m4a` or `.flac` under `{archive_root}/audio/`. An
`audio_path` outside that directory is rejected. Reclaim must be best-effort:
the transcript and `archived` state remain valid if a local deletion fails.
Failed, `needs_audio`, and `audio_ok` rows retain audio for retry. For an
`audio_ok` row with a non-empty local file, ASR reuses that file directly and
must not apply the pre-download budget or make a second HTTP download.

Report `pilot batch branches` separately from `pilot coverage branches`.
Batch counts describe the invocation; coverage counts include earlier archived
rows and only decide whether the cumulative two-branch contract is satisfied.

### Installed Python baseline

Verify packaging through the installed `bili-asr` console script rather than
only importing checkout source. The repeatable baseline uses a fresh Python
3.12 environment, a complete locally reviewed wheel fixture, and `--no-index`
plus `--find-links` for both declared build requirements and `.[dev]`. Bootstrap
the declared build backend before a `--no-build-isolation` project install;
check the generated console launcher while the temporary environment still
exists. Record only command names and exit codes in the result, and keep local
advisory audit data separate from live lookups.

When staging tests for an installed distribution, copy only ordinary files
from explicitly required repository input trees. Reject symlinks before copy
to prevent checkout-local paths from escaping into the temporary test tree.
Keep the staged test tree's `src` path injection removed so product imports
resolve from the installed wheel. A missing interpreter prerequisite or
incomplete wheel closure must be a named failure, never a false green.

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
- Bounded PC pilot: `iter-2026-08-live-pc-pilot`, source revision `4e00fb3`;
  299 tests passed and staged Windows WSL N=5 / N=20 observed subtitle and
  ASR branches, named budget skipping, and post-archive reclaim.
- Corpus-operations update: `.mstar/iterations/iter-2026-08-corpus-operations/specs/full-corpus-scheduler.md` and `.mstar/iterations/iter-2026-08-corpus-operations/specs/verification-baseline.md`; integration revision `ad5253d` passed 392 tests, and the managed Python 3.12.13 no-index baseline passed with five zero-exit commands and 14 hash-validated fixture artifacts.
