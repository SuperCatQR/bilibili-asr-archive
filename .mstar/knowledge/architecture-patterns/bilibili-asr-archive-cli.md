---
module: bilibili-asr-archive CLI
date: 2026-08-31
problem_type: architecture_pattern
category: architecture-patterns
severity: medium
plan_id: iter-2026-08-archive-foundations
tags:
  - bilibili-api
  - page-aware-ledger
  - resumable-cli
  - metadata-cursor
  - optional-asr
  - risk-control
  - transport-seam
---

# Bilibili archive CLI architecture

## Context

A personal Bilibili archive combines rate-limited metadata/API requests, large CDN streams, optional local ASR, and durable local progress. A bvid may contain several pagelist pages, so a bvid-only ledger cannot identify the media unit or resume work safely. Risk interruption must preserve the first unmerged metadata page without claiming corpus completion.

## Guidance

Keep `bili_client` as the only module that opens sockets. Expose transport protocols and binary-stream seams so API, CDN, WBI, cookie, and retry behavior can be tested without live media requests. Keep subtitle conversion, ASR normalization, archive writers, identity transforms, and cursor persistence separate from HTTP ownership.

Use a JSONL manifest as the state-machine SSOT, keyed by canonical `work_id`: `bvid:p<zero-based-page-index>` for multipart pages, with an explicit p0 adapter for unambiguous single-page rows. Use a colon-free `artifact_stem` such as `bvid.p0` for filesystem paths. Carry each page cid through subtitle/audio/archive operations. Migrate legacy bare-bvid rows only when ownership is unambiguous; preserve ambiguous rows as visible unresolved data instead of guessing.

Persist metadata enumeration progress in an archive-root `meta-cursor.json` with a bounded exact schema. Persist `risk_interrupted` after a risk ceiling and set `next_page` to the first unmerged 1-based page. Consume the cursor only when `--resume` has a matching mid and the state is `risk_interrupted`; `limited` and `complete` are terminal evidence, not automatic resume inputs. Atomic replacement and forbidden-marker validation keep credentials, signed URLs, raw exceptions, and response bodies out of evidence.

Treat API risk ceilings as batch-stop conditions (exit 2), but treat per-page or CDN stream failures as retryable item outcomes so successful rows and artifacts remain durable. Pace sequential work and keep concurrency/daemonization outside the default runtime until separately approved by evidence.

Keep heavy ASR dependencies optional and imported lazily. The base CLI must expose help/status and metadata/subtitle workflows without a model. Keep model weights outside the repository and support local offline runs.

## Why This Matters

Page identity prevents wrong-page archives and artifact collisions. The cursor turns a risk interruption into a bounded continuation rather than a restart from page one. Together with a single HTTP owner and redacted sidecars, these boundaries make subtitle-first archival and later measured production auditable without changing the manifest status taxonomy.

## When to Apply

Apply this pattern to archive or ingestion CLIs that combine rate-limited HTTP, multipart resources, large binary downloads, optional local ML, and durable per-item progress.

## Evidence

- Iteration: `iter-2026-08-archive-foundations`
- Source specs: `.mstar/iterations/iter-2026-08-archive-foundations/specs/multipart-page-aware-pipeline.md`, `.mstar/iterations/iter-2026-08-archive-foundations/specs/cursor-based-resume.md`
- Implementation: `bilibili-asr-archive/src/bili_asr/page_identity.py`, `meta_cursor.py`, `manifest.py`, `bili_client.py`, and `cli.py`
- Verification: foundation focused suite 109 passed; full Python 3.12 suite 168 passed on PC WSL.
