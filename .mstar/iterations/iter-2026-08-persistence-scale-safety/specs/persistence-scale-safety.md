# Persistence scale and archive safety specification

## Problem

The sequential archive currently rewrites complete JSONL sidecars on many updates, uses stale in-memory manifest snapshots, caps coverage/integrity readers at 10,000 records, publishes transcript files independently, and accepts `audio_path` values without one shared confinement policy. A restart or overlapping command can therefore lose state, produce non-authoritative evidence, expose incomplete artifacts, or read/delete outside the archive audio root.

## User outcome

A local operator can run the existing sequential, no-daemon archive against larger synthetic fixtures and, only after separate operator authorization, a larger local corpus with durable restart behavior, authoritative trusted-local reports, bounded hostile-input inspection, atomic transcript publication, and confined audio reuse/reclaim.

## Contract

- `manifest/manifest.jsonl` remains the only item-state SSOT and keeps the current row schema, `work_id` identity, `VALID_STATUSES`, and risk taxonomy.
- Normal manifest updates are lock-protected JSONL revisions with last-write-wins projection. Legacy compact one-row-per-key files remain readable. `save()`/`compact()` produce deterministic compact snapshots.
- Attempt numbering is owned by the locked append operation: while holding the attempt-file lock it reads the latest `(work_id, stage)` number, assigns the next integer, appends durably, and releases the lock. Coordinator counters are non-authoritative hints. Attempt history is retained indefinitely; no compaction or rotation may drop prior records in this scope. Manifest history is append-only storage plus a deterministic latest-row snapshot/projection, never a second state machine or silently discarded history.
- A single archive-root writer boundary preserves `sequential-no-daemon`; overlapping production commands are rejected with a redacted stable diagnostic. The lock never authorizes worker or daemon execution.
- Shared reader policies distinguish `trusted_archive` streaming from `bounded_input` fail-closed inspection. Trusted mode has no hard total-record ceiling but retains per-record validation and path safety. Bounded mode preserves explicit record/byte limits and diagnostics.
- Coverage and integrity use the same latest-row/latest-attempt projection. Reports are read-only and never alter sidecars or artifacts.
- `write_archive(...)` retains its existing signature and return mapping while writing all required artifacts into a private staging directory, fsyncing them, replacing the four owned final files in deterministic order, and writing a final bundle-ready marker last. Readers require all outputs plus the marker before treating the bundle as complete; interrupted publication is retryable and does not alter statuses. Cleanup removes only the owned staging directory.
- `confined_audio_path(archive_root, declared_path, require_exists)` is the shared policy for coordinator lookup, audio persistence, and reclaim. Absolute paths, traversal, symlink escapes, directories, unsupported extensions, and non-regular files are rejected.

## Phase 1 prepare decision

- **Specify and clarify:** complete. This plan is a code-first reliability/security slice for the existing sequential archive, not a concurrency, campaign, or process-only initiative.
- **Plan boundary:** implementation may begin only after the iteration registration, feature-worktree lease, and explicit plan lock; until then this specification defines scope and acceptance only.
- **Deferred roadmap:** measured sequential production follows mandatory QC/QA plus Phase 5 and an operator-approved fresh denominator; concurrency remains separately gated by the existing evidence threshold and a new approved plan.

## Required evidence

- Two-process fixture writes show no lost disjoint rows/records or conflicting attempt numbers.
- 10,001 valid manifest rows and 40,001 valid attempts are authoritative in trusted mode; bounded mode fails closed at declared limits.
- Failure injection at write, fsync, replace, and parent-directory fsync leaves the previous valid state readable and never removes unrelated files.
- Read-only coverage/integrity runs preserve source bytes and mtimes.
- Path, symlink, malformed JSONL, redaction, truncated-final-line, and partial-publication fixtures remain deterministic and local-only.

## Non-goals

No SQLite migration, status/risk change, network or credential path, ASR model change, worker/daemon enablement, real campaign, or media redistribution.
