---
plan_id: fix-006-attempt-ledger
project: _default
status: draft
created_at: 2026-10-02
execution_mode: inline
plan_parallelism: serial
---
# Fix 006 attempt-ledger regression
## Status
- **Priority**: P1 · **Effort**: M · **Risk**: MED · **Depends on**: none · **Category**: bug · **Confidence**: HIGH
- **Evidence**: high issue — commit 738b760 (006 in-memory attempt map) lost cross-process attempt numbering + the strict malformed-history check; 2 persistence_scale tests fail.
## Problem
`AttemptLedger.append()` numbers attempts from an in-memory map seeded at construction. Two fresh processes appending the same (work_id,stage) key both write attempt=1 (cross-process safety lost). Also the strict full-history malformed check at append was dropped.
## Approach (D4)
Restore cross-process safety WITHOUT reverting to a full scan: under the flock, re-read only the JOURNAL TAIL (last K lines, or stat-size compare) to detect a foreign append since our last load; on collision, re-replay (cheap — the journal is small) before numbering. Restore the strict malformed-history raise at append (validate the tail we read). Preserve the O(1) single-writer fast path (the common case: no foreign append → no re-read).
## Files: `src/bili_asr/coordinator.py` (AttemptLedger.append); test in `tests/test_persistence_scale.py`.
## Verification: the 2 failing tests go green — test_two_process_same_attempt_key_numbers_do_not_conflict (two processes, distinct attempt numbers) + test_malformed_attempt_history_fails_closed_for_authoritative_append (raises on malformed). The single-writer batch_cost invariant preserved (~1 re-read per batch, not per-row). Existing test_coordinator attempt tests green.
## STOP: if restoring cross-process safety under the flock cannot avoid re-reading growing state on EVERY append (not just on collision), STOP + report the cost tradeoff before proceeding.
## Done: cross-process + malformed-history restored; 2 tests green; batch perf preserved.
