---
plan_id: qc-w4-pace-async
project: _default
status: draft
created_at: 2026-10-02
execution_mode: inline
plan_parallelism: serial
---
# QC W4 + S1 — metadata _pace asyncio + row-count gate
## Status
- **Priority**: P2 · **Effort**: S · **Risk**: MED · **Depends on**: none · **Category**: bug · **Confidence**: HIGH
- **Evidence**: QC W4 `src/bili_asr/sources/bilibili_api_gateway.py:766-778` (`time.sleep` in async getters); QC S1 `:793,811,867` (unconditional).
## Problem
(1) `_pace` blocks the event loop (~0.8–1.6s per upstream call). (2) Pacing is unconditional — single-bvid selections pay the full latency floor.
## Approach
Make the `_sleeper` seam return an awaitable (default `asyncio.sleep` awaited in `_pace`, or `time.sleep` via `asyncio.to_thread`), keeping the `_sleeper`/`_jitter` injection shape for tests. Gate pacing on the run's expected row count (pace only when the enumeration context exceeds a threshold; single-bvid keeps low latency), OR document the floor. Prefer gate-on-row-count with a small threshold.
## Files: `src/bili_asr/sources/bilibili_api_gateway.py`; test in `tests/test_bilibili_api_gateway.py`.
## Verification: pacing tests still pass with the async seam (no real sleeps); a small-selection path does not sleep; `pytest tests/test_bilibili_api_gateway.py -q` green.
## Done: _pace yields to the loop; small selections unpaced; tests green.
