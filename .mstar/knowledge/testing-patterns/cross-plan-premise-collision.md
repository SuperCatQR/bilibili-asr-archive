---
title: "Cross-plan premise collision: two green lanes can contradict each other at integration"
module: bili-asr iteration integration tests
date: 2026-10-03
problem_type: testing_pattern
category: testing-patterns
severity: high
plan_id: caption-writeback-guard
applies_when:
  - several plans in one iteration change one module or one artifact lifecycle
  - an iteration is closing and every per-plan gate is green
  - a test reads a file, sidecar, ordering or fold state whose lifecycle another change controls
  - part of the suite cannot execute in the current container
tags:
  - integration-check
  - failure-set-diff
  - test-premises
  - iteration-close
  - false-green
---

# Cross-plan premise collision

## Context

Iteration `iter-2026-10-ledger-integrity` merged four plans whose behaviour lands in
`bilibili-asr-archive/src/bili_asr/manifest.py` and `coordinator.py`. Each plan's regression test was red
before its fix and green after; each plan's QA recorded every Done criterion; the four lanes were green in
isolation. On the integration branch one test from the caption-writeback plan failed: its observable read the
run's manifest write from `manifest/manifest.journal.jsonl`, and the compaction plan's new file-based fold had
made the journal foldable at that fixture's size — the file was already gone by the time the test read it. The
test's premise ("this run writes a journal that survives the call") was owned by a **sibling plan's** change,
and no per-plan gate could see it: each QA read only its own diff.

The repair (`c50c897`, tests only) made the read state-independent: read the run's write from whichever
artifact holds it — the journal when present (append-only, so the write is the last record), the snapshot when
folded (last-wins per work id) — while still failing when the caption fix is reverted.

## Guidance

1. **At iteration close, diff the failure set, not the pass count.** Run the tests of every module the
   iteration touched on the pinned base and on the integration head, and compare the *sets of failing test ids*;
   classify each difference as NEW or FIXED. Pin the base to the iteration's declared base commit so "NEW"
   means "this iteration did it".
2. **Where several plans share a module, expect premise collisions.** A test that reads a file, sidecar,
   ordering, count or fold state whose lifecycle a sibling change controls is the collision site. Enumerate
   those reads across the plans' test files before the merge: it is a short list, and cheaper than the failure.
3. **Prefer state-independent reads and property assertions.** Read the value from whichever artifact holds it
   under either lifecycle state, and assert the property rather than the artifact's incidental existence (see
   [absence-assertion-negative-control.md](absence-assertion-negative-control.md)). A test whose precondition is
   another module's compaction policy will break whenever that policy is reworked.
4. **A premise that was already de-narrated once is a warning, not a licence.** The caption plan's comment had
   already stopped restating the fold trigger so it could not go stale — while the *assertion* beside it still
   assumed no fold had happened. De-narrating a premise does not remove the dependence on it.
5. **In a container that cannot run part of the suite, the diff still works.** Run both bases and compare the
   FAILED sets: identical sets (e.g. every test needing an absent optional dependency) are an environment gap,
   not a regression — record the equality explicitly. Report the failures the iteration incidentally *fixed*
   as incidental, not as scope: the same check found two of those beside the new one.

## Why This Matters

Per-plan gates are scoped to a diff, and a premise that migrates between plans is exactly what that scoping
cannot see. Each lane's green is true and the iteration's green is false. The failure-set diff is the cheapest
moment to catch it: the base is pinned, the environment is unchanged, and the output is a set difference rather
than a judgement call. Done at close, one collision costs one small test fix; done after the merge, it arrives
as a red suite on the integration branch, with the iteration's change history to re-read first.

## When to Apply

- Iteration close (or a PR head) when two or more plans touched one module, one test file, or one artifact lifecycle.
- Any review asking "which test reads another change's output artifact?".
- A previously green test fails after merging a plan whose own suite is green.

## Examples

Before — plan A's test, plan B's lifecycle:

```python
# The run's write is read from the journal, unconditionally.
with open(os.path.join(tmp_root, "manifest", "manifest.journal.jsonl"), encoding="utf-8") as fh:
    rows = [json.loads(line) for line in fh if line.strip()]
assert rows[-1]["status"] == "archived"
```

After — state-independent:

```python
journal_path = os.path.join(tmp_root, "manifest", "manifest.journal.jsonl")
snapshot_path = os.path.join(tmp_root, "manifest", "manifest.jsonl")
if os.path.exists(journal_path):
    ...   # append-only: the run's write is the last record
else:
    ...   # folded: last-wins per work id in the snapshot
```

The diff shape (both bases, same selector, compare failing ids):

```bash
PYTHONPATH=$PWD/src python3 -m pytest -q tests/test_manifest.py tests/test_coordinator.py tests/test_queue.py
```

## Evidence

- Iteration `iter-2026-10-ledger-integrity`, compass decision D12 (the cross-plan check was adopted as a
  decision after the fact); the captured issue `I-000206`; the iteration's failure-set diff found the new
  failure and two pre-existing ones the iteration had incidentally repaired.
- Repair commit `c50c897` (tests only) on the iteration branch; the affected test is the caption plan's
  `test_run_batch_subtitle_archive_records_published_bundle_when_writeback_fails` in
  `bilibili-asr-archive/tests/test_coordinator.py`.
- Degraded-container instance of the same method: the ASR run-id plan's QA record — both bases report identical
  FAILED sets because the container's interpreter lacks a dependency the caller tests import.
