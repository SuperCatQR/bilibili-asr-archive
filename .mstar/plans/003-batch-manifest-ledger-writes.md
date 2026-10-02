---
plan_id: 003-batch-manifest-ledger-writes
project: _default
primary_spec: .mstar/plans/audit-2026-10-02/001-second-pass-asr-cache-bust.md
status: draft
created_at: 2026-10-02
execution_mode: sdd
plan_parallelism: serial
---
# Plan 003 — Batch manifest ledger writes (stop re-reading the whole JSONL per row)

## Status
- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: perf
- **Confidence**: HIGH
- **Evidence**: `src/bili_asr/manifest.py:265-296` — `upsert()` re-reads the entire manifest under the lock on every call; ~14 production call sites
- **Planned at**: commit `ff39fd0`, 2026-10-02

## Problem

`ManifestStore.upsert()` re-reads and rewrites the whole `manifest.jsonl` under the lock on **every**
call. With the documented ~1730-video corpus, every archived row costs a full JSONL parse of ~1700 records
plus an `flock` round-trip and an fsync-heavy append — and a single ASR row performs ~3 upserts
(`mark_audio_ok`, `archived`, `gone`-path). Batch shape is therefore **O(rows × manifest bytes)**, and the
cost dominates large-batch wall time while serializing all row completions on one file lock.

`upsert()` has ~14 production call sites: `coordinator.py:526,952,960`, `cli/asr.py:242`,
`cli/pilot.py:198,309,568`, `cli/publish.py:190`, `cli/queue.py:107,375`, `cli/_shared.py:105`.

## Current state (excerpt)

`src/bili_asr/manifest.py:279-296`:
```python
with self._manifest_lock(create=True):
    self._entries = self._read_latest()      # full JSONL re-read, every call
    self._loaded = True
    ...
    self._append_record(stored)
    self._entries[key] = stored
    return stored
```

`save()` / `_replace_snapshot()` (`manifest.py:194-231`) rewrite the entire deterministic snapshot on
every call path that passes entries.

## Approach

Make per-row ledger updates cheap while preserving the two invariants the manifest exists for:

1. **Crash recovery** — `manifest.jsonl` is the resumable SSOT; a crash mid-batch must leave a readable,
   replayable ledger.
2. **Deterministic snapshot** — `save()` documents a deterministic byte-stable snapshot property.

Recommended shape (pick one; the first is simpler and preferred):

- **(A) Journal-append for per-row updates, compact lazily.** Split the write path: per-row status
  transitions during a batch go through an **append-only journal** (cheap O(1) append + fsync, no full
  re-read); the in-memory `_entries` map stays authoritative within the process. `save()`/`load()` replay
  journal + snapshot and **compact** (rewrite the snapshot, truncate the journal) only when the
  journal-to-entry ratio crosses a threshold. This keeps crash recovery intact (replay is idempotent and
  order-preserving) and keeps the deterministic snapshot for the compacted form.
- **(B) Batch-then-persist at the coordinator.** `RunCoordinator.run_batch` already owns the batch; hold
  per-row state in memory and persist once at run end. This is a smaller change but only helps the
  coordinator path, leaving the per-row CLI commands (`asr`/`download-audio` loops) still paying the
  per-row cost — so it is a partial fix.

Prefer (A) because it fixes all ~14 call sites uniformly. The key design constraint: **do not** change the
public `upsert()`/`load()`/`save()` semantics observed by callers — only the persistence strategy underneath.

## Files

- **Modify**: `src/bili_asr/manifest.py` — introduce the journal-append path for per-row updates + lazy
  compaction in `save()`.
- **Test**: `tests/test_manifest.py` — add the crash-recovery and compaction-threshold tests below.

## Out of scope

- The call sites themselves — they keep calling `upsert()`; this plan changes the store's internals, not
  the ~14 callers.
- Changing the manifest schema or the SSOT role of `manifest.jsonl`.
- Concurrency model (single-writer `sequential-no-daemon` is by-design; do not add a concurrent writer).

## Verification gates

- **Crash-recovery test**: simulate a batch of N upserts interrupted mid-journal (truncate the journal
  partway), then `load()` and assert the replayed effective state equals the last fully-appended record
  per key (no torn/partial row is exposed).
  - Run: `python3.12 -m pytest tests/test_manifest.py -k journal_crash -v` → passes.
- **Deterministic-snapshot test**: after compaction, `save()` twice and assert byte-identical output (the
  existing deterministic-snapshot property is preserved).
  - Run: `python3.12 -m pytest tests/test_manifest.py -k snapshot_deterministic -v` → passes.
- **Per-row cost test (bounded)**: a batch of K upserts over an L-line manifest issues **fewer than K full
  re-reads** (assert the journal path is taken; e.g. instrument or assert the read count stays ~1, not ~K).
  - Run: `python3.12 -m pytest tests/test_manifest.py -k batch_cost -v` → passes.
- Existing manifest contract intact:
  - Run: `python3.12 -m pytest tests/test_manifest.py -q` → all existing load/save/upsert/lock tests pass.

## STOP conditions

- If the deterministic-snapshot property cannot be preserved across the journal + compaction design (e.g.
  the snapshot's byte-stability depends on rewriting every row in a fixed order that the journal breaks),
  STOP — report the exact property and where it conflicts; do not silently drop the snapshot guarantee.
- If `load()` has a caller that depends on reading only the compacted snapshot file and would break on a
  non-empty journal, STOP and list that caller before proceeding.

## Done criteria

- [ ] The three new tests (`journal_crash`, `snapshot_deterministic`, `batch_cost`) pass.
- [ ] `python3.12 -m pytest tests/test_manifest.py -q` passes (no regression to the existing contract).
- [ ] A batch of K upserts no longer performs K full manifest re-reads (evidenced by the `batch_cost` test).
- [ ] `git diff --check -- src/bili_asr/manifest.py tests/test_manifest.py` exits 0.
- [ ] No files outside the Files list are modified.

## Drift check

`git diff --stat ff39fd0..HEAD -- src/bili_asr/manifest.py tests/test_manifest.py` — if either file changed, re-open the excerpt and confirm `upsert()` still re-reads the whole manifest per call before editing.
