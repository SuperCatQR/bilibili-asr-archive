# Persistence scale and archive safety specification

> Promoted to: `.mstar/knowledge/architecture-patterns/operational-sidecars.md` (2026-09-03; updated existing high-overlap guidance)

## Problem

The sequential archive currently rewrites complete JSONL sidecars on many updates, uses stale in-memory manifest snapshots, caps coverage/integrity readers at 10,000 records, publishes transcript files independently, and accepts `audio_path` values without one shared confinement policy. A restart or overlapping command can therefore lose state, produce non-authoritative evidence, expose incomplete artifacts, or read/delete outside the archive audio root.

## User outcome

A local operator can run the existing sequential, no-daemon archive against larger synthetic fixtures and, only after separate operator authorization, a larger local corpus with durable restart behavior, authoritative trusted-local reports, bounded hostile-input inspection, atomic transcript publication, and confined audio reuse/reclaim.

## Contract

- `manifest/manifest.jsonl` remains the only item-state SSOT and keeps the current row schema, `work_id` identity, `VALID_STATUSES`, and risk taxonomy. Bare-`bvid` legacy rows remain readable; automatic new writes remain page-qualified. After successful metadata enumeration only, an exact page-0 identity match may coalesce a stale bare row with the newly fetched page-qualified row while preserving legacy-only fields; interrupted enumeration does not migrate the legacy key.
- Normal manifest updates are lock-protected JSONL revisions with last-write-wins projection. Legacy compact one-row-per-key files remain readable. `save()`/`compact()` produce deterministic compact snapshots. A semantically invalid later revision is never authoritative or promoted, while prior valid evidence remains inspectable with named diagnostics across store, coverage, and integrity.
- Attempt numbering is owned by the locked append operation: while holding the attempt-file lock it reads the latest `(work_id, stage)` number, assigns the next integer, appends durably, and releases the lock. Coordinator counters are non-authoritative hints. Attempt history is retained indefinitely; no compaction or rotation may drop prior records in this scope. Manifest history is append-only storage plus a deterministic latest-row snapshot/projection, never a second state machine or silently discarded history.
- `RunLedger.load()` remains a compatibility list reader. `RunLedger.latest()` and report paths stream and retain only the latest validated run record, so run history is not materialized by normal coverage/status projections.
- A single archive-root writer boundary spans each complete real CLI/coordinator/campaign mutation window and preserves `sequential-no-daemon`; overlapping production commands are rejected with a redacted stable diagnostic. Lock-acquisition failures use stable persistence diagnostics, while exceptions raised by work inside the lock retain their own redacted business-error mapping. The lock never authorizes worker or daemon execution.
- Shared reader policies distinguish explicit operator-owned `trusted_archive` streaming from `bounded_input` fail-closed inspection. Trusted mode has no hard total-record ceiling but retains per-record/line/object validation and path safety. CLI `coverage` and `verify` are bounded by default and expose additive `--trusted-local`; `coverage --quality` uses the same selected policy.
- Coverage and integrity use the same latest-row/latest-attempt/latest-run projection and authority rules. Reports are read-only and never alter sidecars or artifacts.
- `write_archive(...)` retains its existing signature and return mapping while publishing exactly `srt`, `txt`, `md`, and raw JSON through owned descriptor-anchored staging, fsyncing them, replacing the four owned final files in deterministic order, and writing `<srt>.bundle-ready` last with exact paths and SHA-256 digests. Readers require one complete marker-matched generation. Interrupted publication and complete-publication-before-manifest failures are retryable and do not alter statuses; the next sequential run may republish and commit. Pre-marker archived rows lacking `raw_path` or the marker are incomplete and require re-archive.
- `confined_audio_path(archive_root, declared_path, require_exists)` is the shared lexical policy for coordinator lookup, audio persistence, and reclaim. Absolute paths, traversal, symlink escapes, directories, unsupported extensions, and non-regular files are rejected. Descriptor-backed consumers revalidate the opened inode before use.
- Audio download publication and reclaim mutate only private random stage/quarantine entries and final names through an opened trusted `audio` directory fd. Reclaim moves the selected entry before validating/deleting it, preventing a name swap from redirecting deletion. The hardened mutation path supports POSIX/WSL and fails closed on unsupported descriptor primitives; native Windows support is not claimed.

## Phase 1 prepare decision

- **Specify and clarify:** complete. This plan is a code-first reliability/security slice for the existing sequential archive, not a concurrency, campaign, or process-only initiative.
- **Plan boundary:** implementation may begin only after the iteration registration, feature-worktree lease, and explicit plan lock; until then this specification defines scope and acceptance only.
- **Deferred roadmap:** measured sequential production follows mandatory QC/QA plus Phase 5 and an operator-approved fresh denominator; concurrency remains separately gated by the existing evidence threshold and a new approved plan.

## Required evidence

- Two-process fixture writes show no lost disjoint rows/records or conflicting attempt numbers. The CLI dispatch classifies `fetch-meta`, `recover`, `asr`, `pilot`, `probe-subs`, `harvest-subs`, `download-audio`, `run`, `campaign`, and `schedule` as archive mutations; each complete window rejects an overlapping writer with `<command>: archive_busy`, while read-only commands do not claim the writer lock.
- 10,001 valid manifest rows and 40,001 valid attempts are authoritative through explicit trusted API/CLI mode; bounded defaults fail closed at declared limits. Large run-ledger latest projections stream without materializing all history.
- Invalid middle/final manifest revisions never replace prior valid state and make store/coverage/integrity projections consistently non-authoritative with named diagnostics.
- Failure injection at write, fsync, replace, and parent-directory fsync leaves the previous valid state readable and never removes unrelated files.
- Read-only coverage/integrity runs preserve source bytes and mtimes.
- Path, symlink, malformed JSONL, redaction, truncated-final-line, and partial-publication fixtures remain deterministic and local-only.
- Failure after complete bundle publication but before manifest upsert leaves the bundle complete/readable, does not create a false `archived` row, and succeeds on the next sequential retry.
- Audio destination/reclaim swap fixtures preserve outside victims and prove descriptor-anchored mutation; unsupported native descriptor platforms fail closed and product documentation states POSIX/WSL support.

## Non-goals

No SQLite migration, status/risk change, network or credential path, ASR model change, worker/daemon enablement, real campaign, or media redistribution.
