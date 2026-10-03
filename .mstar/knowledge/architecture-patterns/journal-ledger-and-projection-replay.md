---
title: "Journal ledger & projection replay: making per-row writes O(1) without breaking non-store readers"
problem_type: architecture_pattern
category: architecture-patterns
date: 2026-10-02
source_plans:
  - 003-batch-manifest-ledger-writes
  - iter-2026-10-audit-burndown
  - journal-compaction-lifecycle
severity: medium
module: bili_asr.manifest + bili_asr.sidecar_projection
status: active
last_updated: 2026-10-03
---

# Journal ledger & projection replay

## Context

The manifest is the resumable SSOT (`manifest/manifest.jsonl`). The original `ManifestStore.upsert()` re-read and rewrote the **whole** JSONL under a lock on every call — O(rows × manifest-bytes) per batch, dominating large-batch wall time. Plan 003 (iter-2026-10-audit-burndown) moved it to a **journal-append** model: per-row updates append to `manifest/manifest.journal.jsonl`, and a lazy compaction folds the journal into the deterministic byte-stable snapshot. The trigger is a function of the ledger rather than of the folding instance: both sizes are stat'd from disk and a fold fires when `journal_bytes >= max(floor, 2 × snapshot_bytes)` (floor 512 B). The original per-instance counter (`>= 256` appends since *this* instance's last fold) was removed — it made the trigger depend on which handle happened to append, so a journal grown by other handles never folded from them.

## Guidance

- **Replay once per process, then append.** `upsert()` replays snapshot+journal into memory once per store lifetime (`if not self._loaded`), then does O(1) journal appends under the existing lock. The in-memory map is authoritative between replays. This is what drops a K-row batch from K full re-reads to 1.
- **Every reader must be journal-aware.** The single most important lesson: changing the persistence strategy **without** updating the *non-store readers* that project the ledger silently breaks them. `coverage_report` / `cli/status_cmd` / `integrity` / `search_index` all read the manifest projection — and they read it through **one shared function**, `sidecar_projection.project_manifest_records()`. Fixing that one shared projection healed all four readers at once (no import cycle; `sidecar_projection` already imports from `.manifest`).
- **Split the journal on the writer's own separator, never a line-separator-aware split.** This repo's writer emits one `"\n"` per record with `ensure_ascii=False`, so a legal Unicode line separator inside a JSON string (U+0085 / U+2028 / U+2029) is written **raw**. `str.splitlines()` breaks on exactly those three, turning one record into fragments that the torn-tail `break` then reads as the end of the journal: the row and everything after it vanish from every reader, and — worse — the next `save()`/`compact()` rewrites the snapshot from that truncated view, deleting the later rows durably while `\n`-based sibling readers still see them. Slice on `"\n"` (`sidecar_projection`'s journal replay and `coordinator.AttemptLedger` follow the same rule).
- **Replay semantics mirror the store.** Oldest-first, last-write-wins per `work_id`/`bvid` key; a torn trailing journal line stops replay (crash mid-append) and is dropped — only fully-appended records are exposed per key. Journal rows superseding a snapshot copy read as ordinary history, never a duplicate-defect signal.
- **Preserve both invariants.** Crash recovery (a torn tail replays to the last full record per key) and the deterministic snapshot (`save()` is byte-stable across runs: sorted keys, fixed separators). Compaction must never destroy data: do **not** unlink the journal when the snapshot is absent/empty (that loses the only durable copy).
- **`save()` must fold the journal first.** Otherwise a `save()` after journal-appended upserts resurrects pre-transition state and drops journaled rows.
- **Publish before discard, everywhere.** All three rewriting methods (`save()`, `compact()`, the legacy migration) write the snapshot and only then unlink the journal; an empty-`current` early return touches neither artifact. The window that order closes is a crash between "journal gone" and "snapshot written": the rows then exist nowhere.
- **Give the discard invariant one owner.** "Never unlink a journal whose rows were not folded" is enforced inside the single unlink helper (`ManifestStore._remove_journal`), not restated at each of its four call sites. Adding the rule to a duplicated call-site check makes every future caller a place to forget it; here the guarded condition is re-derived from the replay immediately before each discard, so a new caller inherits the guarantee instead of having to remember it (see the guard-ownership note in [reachability-delta-not-asserted.md](../best-practices/reachability-delta-not-asserted.md)).

## The torn fragment, the strand, and what a fold may publish

The replay stops at the first unparsable line: a torn tail (crash between `write` and a full line) drops
whatever follows it, because skipping mid-stream would publish a partial history as if it were complete. That
rule is correct for the *reader* and dangerous for the *writer that discards*: with a fragment in the middle
of the file — the cross-process shape, an old fragment before rows another handle appended later — complete
records after it are fsynced but unreachable to every reader, and a fold that unlinks the journal would delete
their only copy.

Three properties hold the repair together, each earned by a measured failure:

- **A complete record behind a fragment is a strand, and the journal holding it must not be discarded.** The
  detector scans past the fragment (without folding) purely to learn whether anything was stranded. The
  dangerous shape is not only a whole line: when the fragment's line was never terminated, the next append
  lands **on** it, so fragment and intact record share one physical line that no whole-line parse can read —
  detection must also look *inside* the unparsable line (walking its record anchors). An exhausted scan budget
  counts as *present*: retaining a fragment delays a fold, discarding a record loses it.
- **Refusing the discard is not the end state — the strand must be settled.** Retaining the journal forever
  means the fold can never complete, the residue grows (measured: 4120 B journal against a 43 B pinned
  snapshot after 40 appends, with a fresh reader seeing 1 of 41 rows) and the stranded records stay invisible.
  The settlement is to **publish the stranded records in the fold and only then discard**: the fold merges
  what the fragment stranded into the snapshot before the unlink, so the state is transient rather than
  permanent. An *incomplete* collection still refuses the fold — the safe direction.
- **The reader's contract and the writer's obligation differ.** "No record is discarded" and "the record is
  readable" are two halves of one honest sentence: while the fragment sits before them, stranded records are
  retained but unreadable to every reader. State both, and register the repair (or the report) a stranded tail
  needs as its own surface — the deletion class and the readability class are not the same fix.

## Why this matters

The naive journal change passed its own unit tests (crash-recovery, deterministic-snapshot, batch-cost) but **broke a cross-module reader** the tests didn't touch: `coverage --quality` began reporting `manifest_malformed` / denominator `unavailable` on a healthy archive because it read only the stale snapshot while the real row lived only in the journal. The defect was caught only by a post-merge integration smoke, not by any single-plan gate — evidence that **persistence-layer changes need a cross-reader integration check**, and that the "journal staleness for non-store readers" risk a reviewer flags must be fixed in the same round, not deferred.

## When to apply

- Any change to an append-only / snapshot ledger's persistence strategy (journal, log, segment files).
- When a store and its read projections live in different modules — audit **every** projection call site, not just the store's own tests.
- When you reach for "replay once then append" for performance: budget a same-round fix for all readers that project the ledger.

## Examples

- **The fix (plan 003, iter-2026-10-audit-burndown):** added `sidecar_projection.replay_journal_records()` and made `project_manifest_records()` fold the journal into the effective ledger after the snapshot. One file (`sidecar_projection.py`, +70/−7) healed coverage/quality, status, integrity, and search — versus patching each reader separately.
- **The residual:** `search_index.is_stale()` still keys off snapshot mtime only (journal-blind), so a same-count transition can be judged fresh and serve stale FTS rows. Registered as a residual for triage — the shared-projection fix did not reach the mtime-based staleness check.
- **Registered residual class (from the same QC round):** `ManifestStore.upsert`'s per-process cache has no cross-process invalidation (interleaved appends from another process can be overwritten on save/compact); ~~`compact()` can delete the journal when the snapshot is absent~~ — **closed**: every discard now routes through the one unlink helper, which refuses while the replay found unfolded records, and all three rewriting methods publish before discarding; the projection reports snapshot-missing-with-empty-journal as a healthy "missing". These are the follow-on edges of a journal split that the happy path never exercises.

## Related

- `operational-sidecars.md` — the durable append/projection boundary this builds on.
- `row-merge-on-terminal-transition.md` — append-only ledger read semantics (last-record-wins) that the journal replay must preserve.
- `../best-practices/reachability-delta-not-asserted.md` — why a trigger rewrite has to be reviewed for what it makes reachable, and why the discard guard is owned once.
- `../testing-patterns/absence-assertion-negative-control.md` — the recoverability-not-existence test shape this file's fold tests use.
