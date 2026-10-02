---
plan_id: search-n1-batching
project: _default
status: draft
created_at: 2026-10-02
execution_mode: inline
plan_parallelism: serial
---
# Search N+1 batching (O-R3)
## Status
- **Priority**: P2 · **Effort**: S · **Risk**: LOW · **Depends on**: none · **Category**: perf · **Confidence**: HIGH
- **Evidence**: residual O-R3 — search_blocks issues one MATCH snippet query per hit and eagerly scans videos titles.
## Problem
`search_blocks` (search_index.py) issues one snippet query PER HIT (N+1) and eagerly scans video titles — unbounded queries on a result set.
## Approach
Batch the snippet reads: one query fetching the snippets for ALL hit block_keys (a single WHERE block_key IN (...)), not one-per-hit. Bound the eager title scan (only fetch titles for the hits returned, in the same batched query). Keep deterministic result ordering. Add a query-count test (a counting connection wrapper asserts a bounded number of queries for K hits).
## Files: `src/bili_asr/search_index.py` (search_blocks); test in `tests/test_search.py`.
## Verification: a query-count test asserts search_blocks over K hits issues a bounded (constant) number of queries, not K; existing test_search green; deterministic ordering preserved.
## STOP: if batching the snippet read requires changing the FTS result schema or breaking deterministic order, STOP + report.
## Done: bounded queries; test green; no order regression.
