---
plan_id: 006-attempt-ledger-inmemory
project: _default
status: draft
created_at: 2026-10-02
execution_mode: inline
plan_parallelism: serial
---
# Plan 006 — Trust the in-memory attempt-count map instead of re-scanning attempts.jsonl

## Status
- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: perf
- **Confidence**: HIGH
- **Evidence**: `src/bili_asr/coordinator.py:209-225` — `AttemptLedger.append` re-reads/parses the whole sidecar to compute the next attempt number; `_attempt_counts` at `:354-361` is already maintained but never consulted
- **Planned at**: commit `ff39fd0`, 2026-10-02

## Problem

`AttemptLedger.append` holds the file lock, then calls `_iter_valid(strict=True)` to stream and parse
**every prior line** of the append-only `attempts.jsonl` just to find the max attempt number for
`(work_id, stage)`. The in-memory `self._attempt_counts` dict is initialized once in
`RunCoordinator.__init__` (`coordinator.py:354-361`) and updated at `:391`, but `append` never consults
it — it re-scans the file instead.

The sidecar is append-only and unbounded (residual C-R7 tracks the unbounded growth separately). After N
attempts the run has done **O(N²)** line parses; with ~5 stage records per processed row, a 1000-row
campaign produces thousands of full-file scans.

## Current state (excerpt)

`src/bili_asr/coordinator.py:213-224`:
```python
with file_lock(lock_path):
    key = (stored["work_id"], stored["stage"])
    latest = 0
    for prior in self._iter_valid(strict=True):     # full-file re-scan, every append
        if (prior["work_id"], prior["stage"]) == key:
            latest = max(latest, prior["attempt"])
    if record.get("_preserve_attempt"):
        next_attempt = stored["attempt"]
    else:
        next_attempt = max(stored["attempt"], latest + 1)
    stored["attempt"] = next_attempt
    append_jsonl_record(self.path, stored, lock_path=lock_path)
```

## Approach

Trust the in-memory `self._attempt_counts` map inside the lock instead of re-scanning:
`next_attempt = max(stored["attempt"], counts.get(key, 0) + 1)`, and update `counts[key]` after the append.
This removes the O(N) scan per append, dropping the batch to O(N) total.

**Cross-process caveat**: the full-file scan exists to number attempts correctly if a second process
appends concurrently. Under the project's `sequential-no-daemon` single-writer design (decision D12), a
concurrent writer is out of contract. To stay safe without the full scan, keep a **bounded fallback**:
read only the last K lines (a torn-tail window) to catch a recently-appended higher attempt number, rather
than the whole file. If you judge the single-writer guarantee sufficient, document that and drop the
fallback — but say so explicitly in the commit.

## Files

- **Modify**: `src/bili_asr/coordinator.py` — `AttemptLedger.append`: consult `_attempt_counts` instead of
  `_iter_valid`; update the count after append; optional bounded last-K-lines fallback.
- **Test**: `tests/test_coordinator.py` — add the attempt-numbering regression below.

## Out of scope

- Compacting/truncating the unbounded `attempts.jsonl` (that is residual C-R7, a separate concern).
- Changing the attempt record schema or the ledger's append-only property.
- Concurrency model (single-writer is by-design).

## Verification gates

- **Attempt-numbering regression** in `tests/test_coordinator.py`: append several attempts for the same
  `(work_id, stage)` and across multiple keys; assert the attempt numbers are strictly increasing per key
  and match the pre-change behaviour (the sequence is identical to the full-scan version). Assert the
  per-append cost does not re-read the whole file (e.g. instrument `_iter_valid` call count → 0, or the
  bounded fallback count).
  - Run: `python3.12 -m pytest tests/test_coordinator.py -k attempt_numbering -v` → passes.
- Existing coordinator/ledger behaviour unchanged:
  - Run: `python3.12 -m pytest tests/test_coordinator.py -q` → the attempt-ledger and run_batch tests pass.

## STOP conditions

- If `append` can be called on an `AttemptLedger` whose in-memory `_attempt_counts` was **not** seeded from
  the existing file (e.g. a fresh `AttemptLedger` opened on a non-empty sidecar), then trusting the map
  alone would under-count. STOP — in that case seed the map once at construction (a single initial scan),
  then keep it in memory thereafter; do not per-append scan.

## Done criteria

- [ ] `python3.12 -m pytest tests/test_coordinator.py -k attempt_numbering -v` passes.
- [ ] `python3.12 -m pytest tests/test_coordinator.py -q` passes.
- [ ] The per-append full-file re-scan is removed (evidenced by the test asserting no `_iter_valid` call per
      append), or replaced by a documented bounded fallback.
- [ ] `git diff --check -- src/bili_asr/coordinator.py tests/test_coordinator.py` exits 0.
- [ ] No files outside the Files list are modified.

## Drift check

`git diff --stat ff39fd0..HEAD -- src/bili_asr/coordinator.py tests/test_coordinator.py` — if either file changed, re-open the excerpt and confirm `append` still re-scans before editing.
