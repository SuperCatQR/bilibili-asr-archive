---
title: "Journal ledger & projection replay: making per-row writes O(1) without breaking non-store readers"
problem_type: architecture_pattern
category: architecture-patterns
date: 2026-10-02
source_plans:
  - 003-batch-manifest-ledger-writes
  - iter-2026-10-audit-burndown
severity: medium
module: bili_asr.manifest + bili_asr.sidecar_projection
status: active
---

# Journal ledger & projection replay

## Context

The manifest is the resumable SSOT (`manifest/manifest.jsonl`). The original `ManifestStore.upsert()` re-read and rewrote the **whole** JSONL under a lock on every call — O(rows × manifest-bytes) per batch, dominating large-batch wall time. Plan 003 (iter-2026-10-audit-burndown) moved it to a **journal-append** model: per-row updates append to `manifest/manifest.journal.jsonl`, and a lazy compaction folds the journal into the deterministic byte-stable snapshot only when append history dominates (≥256 appends AND journal ≥2× snapshot bytes).

## Guidance

- **Replay once per process, then append.** `upsert()` replays snapshot+journal into memory once per store lifetime (`if not self._loaded`), then does O(1) journal appends under the existing lock. The in-memory map is authoritative between replays. This is what drops a K-row batch from K full re-reads to 1.
- **Every reader must be journal-aware.** The single most important lesson: changing the persistence strategy **without** updating the *non-store readers* that project the ledger silently breaks them. `coverage_report` / `cli/status_cmd` / `integrity` / `search_index` all read the manifest projection — and they read it through **one shared function**, `sidecar_projection.project_manifest_records()`. Fixing that one shared projection healed all four readers at once (no import cycle; `sidecar_projection` already imports from `.manifest`).
- **Replay semantics mirror the store.** Oldest-first, last-write-wins per `work_id`/`bvid` key; a torn trailing journal line stops replay (crash mid-append) and is dropped — only fully-appended records are exposed per key. Journal rows superseding a snapshot copy read as ordinary history, never a duplicate-defect signal.
- **Preserve both invariants.** Crash recovery (a torn tail replays to the last full record per key) and the deterministic snapshot (`save()` is byte-stable across runs: sorted keys, fixed separators). Compaction must never destroy data: do **not** unlink the journal when the snapshot is absent/empty (that loses the only durable copy).
- **`save()` must fold the journal first.** Otherwise a `save()` after journal-appended upserts resurrects pre-transition state and drops journaled rows.

## Why this matters

The naive journal change passed its own unit tests (crash-recovery, deterministic-snapshot, batch-cost) but **broke a cross-module reader** the tests didn't touch: `coverage --quality` began reporting `manifest_malformed` / denominator `unavailable` on a healthy archive because it read only the stale snapshot while the real row lived only in the journal. The defect was caught only by a post-merge integration smoke, not by any single-plan gate — evidence that **persistence-layer changes need a cross-reader integration check**, and that the "journal staleness for non-store readers" risk a reviewer flags must be fixed in the same round, not deferred.

## When to apply

- Any change to an append-only / snapshot ledger's persistence strategy (journal, log, segment files).
- When a store and its read projections live in different modules — audit **every** projection call site, not just the store's own tests.
- When you reach for "replay once then append" for performance: budget a same-round fix for all readers that project the ledger.

## Examples

- **The fix (plan 003, iter-2026-10-audit-burndown):** added `sidecar_projection.replay_journal_records()` and made `project_manifest_records()` fold the journal into the effective ledger after the snapshot. One file (`sidecar_projection.py`, +70/−7) healed coverage/quality, status, integrity, and search — versus patching each reader separately.
- **The residual:** `search_index.is_stale()` still keys off snapshot mtime only (journal-blind), so a same-count transition can be judged fresh and serve stale FTS rows. Registered as a residual for triage — the shared-projection fix did not reach the mtime-based staleness check.
- **Registered residual class (from the same QC round):** `ManifestStore.upsert`'s per-process cache has no cross-process invalidation (interleaved appends from another process can be overwritten on save/compact); `compact()` can delete the journal when the snapshot is absent; the projection reports snapshot-missing-with-empty-journal as a healthy "missing". These are the follow-on edges of a journal split that the happy path never exercises.

## Related

- `operational-sidecars.md` — the durable append/projection boundary this builds on.
- `row-merge-on-terminal-transition.md` — append-only ledger read semantics (last-record-wins) that the journal replay must preserve.
