---
plan_id: qc-w3-upsert-cross-process
project: _default
status: draft
created_at: 2026-10-02
execution_mode: inline
plan_parallelism: serial
---
# QC W3 — ManifestStore.upsert cross-process invalidation
## Status
- **Priority**: P2 · **Effort**: M · **Risk**: MED · **Depends on**: none · **Category**: bug · **Confidence**: HIGH
- **Evidence**: QC finding; `src/bili_asr/manifest.py:390-405` — lazy `_loaded` guard skips re-replay.
## Problem
`upsert()` caches `_entries` per process; another process's interleaved appends are missing from the cache and get overwritten on a later `save()`/`compact()`.
## Approach
Revalidate on each `upsert`: stat the journal/snapshot and re-`_replay_latest()` when changed since the last load (cheap — the journal is small). Alternatively version `_entries` and refuse cross-process staleness. Prefer revalidate-on-change.
## Files: `src/bili_asr/manifest.py`; test in `tests/test_manifest.py`.
## Verification: a test simulating a second writer's append between two upserts → the first store's `save()`/view includes the other row; `pytest tests/test_manifest.py -q` green. No perf regression (batch_cost still 1 re-read per batch, not per row).
## Done: cross-process staleness closed; tests green; batch_cost unchanged.
