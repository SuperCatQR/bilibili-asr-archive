---
plan_id: test-drift-repair
project: _default
status: draft
created_at: 2026-10-02
execution_mode: sdd
plan_parallelism: serial
---
# Test drift — fix the 18 pre-existing failures
## Status
- **Priority**: P1 · **Effort**: M · **Risk**: MED · **Depends on**: none · **Category**: bug · **Confidence**: HIGH
- **Evidence**: registered medium issue — 18 failures in test_scheduler/test_coordinator/test_metadata_cli, byte-identical FAILED set base vs head (pre-existing, mask real regressions).
## Problem
18 pre-existing failures (recovery-contract drift in integrity.py, rerun manifest path, processed_work_ids/subtitle_done fixture gap, + persistence_scale/search_index immutability fixture gaps) keep the coordinator/scheduler/metadata lanes red, masking real regressions.
## Approach
Diagnose each cluster's ROOT cause (not per-test patches): (1) recovery-contract drift — reconcile integrity.py's recovery behaviour with the test's contract expectation (or fix the test if the code is correct); (2) rerun manifest path; (3) processed_work_ids/subtitle_done fixture gap — the fixture must seed the state the assertion reads; (4) the immutability tests' fixture never writes the snapshot (journal-only upsert) → add store.save() to the fixture.
## Files: the failing test files + the src under test (integrity.py, coordinator.py, scheduler.py, and the fixtures).
## Verification: `pytest tests/test_scheduler.py tests/test_coordinator.py tests/test_metadata_cli.py -q` green (0 failures); the persistence_scale/search_index immutability tests green after the fixture fix.
## STOP: if a failure is a genuine CODE bug (not drift), STOP + report it as a finding rather than patching the test to match buggy code.
## Done: the 18 (and the immutability/persistence_scale set) go green; suites reliable.
