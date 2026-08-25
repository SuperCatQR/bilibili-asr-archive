---
module: bili-asr operational layer
date: 2026-08-25
last_updated: 2026-08-25
problem_type: architecture_pattern
category: architecture-patterns
severity: medium
plan_id: 20260825-run-coordinator-offline
applies_when:
  - adding operator-visible run history without changing JSONL rows
  - searching completed transcripts without a second SSOT
  - reprocessing on-disk artifacts without live HTTP
tags:
  - sidecar-jsonl
  - run-ledger
  - fts5
  - run-coordinator
  - offline-reprocess
---

# Operational sidecars (ledger, FTS5, coordinator)

## Context

The frozen MVP keeps `work_id`-keyed JSONL as the archive state machine and
`bili_client` as the only HTTP owner. Operators still need per-run progress,
search/export of completed transcripts, and a way to retry ASR/archive after
downloads already exist — without migrating the manifest schema or mixing
live-risk HTTP into deterministic local work.

## Guidance

Keep three sidecars / derived stores. Never rewrite `VALID_STATUSES` or
`classify_risk`.

1. **Run ledger** (`RunLedger`, command `runs` / `status` summary): append-only
   JSONL next to the archive. Record cursor snapshot, last API error *code*
   (never raw exception text), and per-status coverage. `command` is
   `fetch-meta` | `pilot` | `run`. Atomic tmp + fsync + same-directory replace; also
   fsync the parent directory after replace.

2. **FTS5 search/export**: SQLite read model over rows that already have
   transcript artifacts. Manifest remains SSOT; search never writes JSONL.
   Empty query → exit 1 with a clear message. Export writes metadata JSON/CSV;
   `--with-text` is optional.

3. **Run coordinator** (`bili-asr run`): stage-attempt ledger at
   `{archive_root}/coordinator/attempts.jsonl` with
   `harvest|download|asr|archive` × `ok|failed|skipped`. Compose existing
   seams (`harvest_subtitle`, `download_audio`, `transcribe`, `write_archive`);
   do not add a second HTTP client. **Every executed stage must persist an
   attempt**, including download/archive failures — otherwise `--scope failed`
   silently drops rows.

`--offline` never calls harvest or download. It only runs `asr` / `archive`
when `{stem}.m4a`/`.flac` or subtitle raw JSON already exist; missing input
is `skipped` with a reason. Batch continues on per-item failure. Explicit
rerun of an already-terminal `work_id` is idempotent (exit 0). `run`
complements frozen `pilot`; it does not replace it.

## Why This Matters

Sidecars keep the frozen risk taxonomy and JSONL contract intact while giving
operators inspectable runs, searchable archives, and network-free reprocessing.
Recording every stage failure is what makes `--scope failed` and crash recovery
honest.

## When to Apply

Apply when extending this CLI (or similar archive CLIs) with operator surfaces
that must not become a second state machine. Do not apply to live scheduling,
concurrency, or replacing `pilot` as the MVP proof command.

## Evidence

- Iteration: `iter-2026-08-pilot-ops`
- Plans: `20260825-operational-ledger`, `20260825-search-export-fts5`,
  `20260825-run-coordinator-offline`
- Implementation: `bilibili-asr-archive/src/bili_asr/run_ledger.py`,
  `bilibili-asr-archive/src/bili_asr/search_index.py`,
  `bilibili-asr-archive/src/bili_asr/coordinator.py`
- Verification: 277 passed on Python 3.12 (QA, no live HTTP)
