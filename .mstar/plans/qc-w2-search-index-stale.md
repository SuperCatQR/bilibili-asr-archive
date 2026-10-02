---
plan_id: qc-w2-search-index-stale
project: _default
status: draft
created_at: 2026-10-02
execution_mode: inline
plan_parallelism: serial
---
# QC W2 — search_index.is_stale journal-aware
## Status
- **Priority**: P2 · **Effort**: S · **Risk**: LOW · **Depends on**: none · **Category**: bug · **Confidence**: HIGH
- **Evidence**: QC finding; `src/bili_asr/search_index.py:511-513` — `is_stale()` uses snapshot mtime only.
## Problem
A journal-appended same-count manifest change does not bump the snapshot mtime, so `is_stale()` judges the index fresh and serves stale FTS rows.
## Approach
Make `is_stale()` incorporate the journal mtime (max of snapshot + `manifest.journal.jsonl` mtimes) so any journaled write invalidates the index.
## Files: `src/bili_asr/search_index.py`; test in `tests/test_search_index.py`.
## Verification: a test where a journal append without a snapshot change → `is_stale()` becomes True; `pytest tests/test_search_index.py -q` green.
## Done: is_stale journal-aware; new test passes; full test_search_index.py green.
