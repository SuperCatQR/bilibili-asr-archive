# Full-visible-corpus Resumable Scheduler

> Iteration: `iter-2026-08-corpus-operations`.
> Execution mode: `sdd`.
> Findings cleanup: `zero-residual`.

## Status

- Priority: P1
- Category: product / operations
- Status: Todo
- Depends on: `20260826-mixed-outcome-contract`
- Primary spec: `.mstar/iterations/iter-2026-08-corpus-operations/specs/full-corpus-scheduler.md`

## Goal

Extend the proven bounded pilot and run-coordinator seams into a repeatable, resumable full-visible-corpus scheduler. Operators must be able to process the manifest in bounded batches, resume after risk interruption, include a deliberately selected multi-hour livestream proof, and inspect honest progress without turning the CLI into an unbounded daemon or concurrent worker system.

## Global Constraints

- `bili_client.py` remains the only module that opens Bilibili sockets; the scheduler composes existing `fetch-meta`, `pilot`, `run`, manifest, cursor, ledger, budget, and reclaim seams.
- The JSONL manifest schema and frozen risk taxonomy remain unchanged. Sidecar state is additive and redacted.
- Scheduling is sequential and bounded by an explicit batch limit; no distributed workers, implicit infinite loop, or automatic credential acquisition.
- Every successful page and every stage outcome remains resumable and inspectable. Risk-control exhaustion exits 2 and preserves the last stable state.
- Audio is transient: conservative pre-download budget checks run before every new download; successful archive writes trigger best-effort reclaim; failed rows retain retryable artifacts.
- No live HTTP, model download, or real media transfer in automated tests. Live acceptance is an explicit operator action on the Windows WSL PC using an environment/flag cookie value only.
- Long-live proof must use the same bounded policy and must not weaken the default short-video pilot filter.

## Interfaces

- CLI scheduler surface: `bili-asr schedule --scope pending|failed|<work_id>... --limit N [--resume] [--max-audio-gb G] [--archive-root ROOT]` (exact spelling/options to be confirmed by architect against current CLI conventions).
- Scheduler consumes `ManifestStore`, `MetaCursorStore`, `RunLedger`, and `RunCoordinator` rather than introducing a second manifest or HTTP client.
- A scheduler summary reports requested scope, processed/skipped/failed counts, cursor state, coverage by manifest status, and whether the batch is `complete`, `limited`, or `risk_interrupted`.
- A multi-hour acceptance fixture exposes duration, estimated bytes, local audio usage before/after, reclaim result, final manifest state, and no-secret scan evidence.
- `--resume` means resume only a matching, risk-interrupted cursor or scheduler sidecar state; deliberate limits never masquerade as completion.

## In scope

- Scheduler orchestration in `bilibili-asr-archive/src/bili_asr/` and the corresponding CLI parser/summary wiring.
- Bounded candidate selection, cursor/risk interruption handling, long-live selection override/fixture, audio budget and reclaim integration.
- Sidecar fields needed to distinguish a bounded batch from full-visible-corpus completion, without changing manifest row fields.
- Deterministic tests for repeated batches, risk stop/resume, mixed branch selection, long-live budget behavior, and idempotent terminal rows.
- README and iteration-scoped scheduler guide/spec updates.

## Out of scope

- Concurrent/distributed scheduling, daemonization, queue services, or a GUI.
- Claiming the visible corpus is fully archived when the source enumeration is `limited` or risk-interrupted.
- Manifest migration, changed `VALID_STATUSES`, changed gone-code taxonomy, or replacing `pilot`/`run`.
- Public media redistribution, diarization, LLM cleanup, or search UI.
- Storing SESSDATA, signed URLs, raw exception text, or model weights.

## Durable Roadmap and Dependencies

- Batch 1 (this plan): bounded sequential scheduler + resumability + one explicit long-live acceptance path. Depends on the mixed-outcome contract plan for exit semantics.
- Batch 2 (next iteration, owner: project-manager + fullstack-dev): controlled corpus execution and coverage reporting after this PR is merged to `main` and the scheduler has real operator telemetry.
- Deferred: concurrent workers and daemon/service operation until measured single-worker throughput, disk behavior, and API-risk telemetry justify a new plan. Final Done definition is an auditable visible-corpus ledger with no false completion claims.

## Tasks

### Task 1: Lock and implement bounded scheduler orchestration

**Files:** scheduler/CLI modules, focused tests, iteration spec.

- [ ] Define candidate ordering, scope selectors, explicit batch limit, terminal-row handling, and scheduler/cursor sidecar semantics against current `ManifestStore`, `RunLedger`, and `RunCoordinator`.
- [ ] Execute existing live/local stages sequentially, preserve per-row progress after each stage, and return the mixed-outcome exit code from the locked outcome contract.
- [ ] Distinguish `complete`, intentional `limited`, and `risk_interrupted` in summaries and persisted sidecars; never infer full coverage from a bounded call.
- [ ] Cover reruns, risk interruptions, resume, missing artifacts, and terminal-row idempotence with fake transports and stubbed ASR.

Run: focused scheduler/outcome tests pass without live HTTP or model downloads.

### Task 2: Integrate budgeted long-live campaign proof

**Files:** scheduler/budget/reclaim integration, tests, operator guide, evidence template.

- [ ] Add an explicit opt-in long-live campaign path/fixture that can process a multi-hour duration without silently disabling the audio cap or default short-video selection.
- [ ] Assert conservative pre-download estimation, observed `audio/` peak measurement, successful archive state, and post-archive audio reclaim; failure keeps retryable audio/state.
- [ ] Record operator steps for Windows WSL, including archive-root placement, cookie boundary, `du` measurement, and redacted evidence collection.

Run: long-live fake acceptance and documentation checks pass; live WSL execution is recorded by QA without echoing credentials.

## STOP Conditions

- Current cursor/ledger semantics cannot distinguish a bounded batch from complete enumeration without a manifest migration.
- Scheduler behavior would require concurrent writes, a new HTTP owner, or unbounded retries.
- The long-live path cannot prove pre-download budget safety and reclaim on a fake filesystem.
- Live acceptance would require printing, persisting, or checking in SESSDATA or signed URLs.
- A risk or API contract conflict cannot be reconciled with the frozen spec and current sidecar SSOT.

## Drift Check

Before execution compare the current checkout against the source revisions of the live-pc and pilot-ops compasses. Inspect `cli.py` command registration and dispatch, `meta_cursor.py`, `run_ledger.py`, `coordinator.py`, `audio_budget.py`, `audio_reclaim.py`, `manifest.py`, and current test counts. If the scheduler needs a new state or schema, update this plan/spec during Prepare before implementation.

## Acceptance / Done Criteria

- [ ] Bounded sequential scheduling processes only the requested scope and never claims full completion for `limited` or `risk_interrupted` runs.
- [ ] Risk interruption preserves progress and matching resume continues without duplicating manifest rows or artifacts.
- [ ] Existing terminal rows are idempotently skipped; per-item failures do not erase successful rows.
- [ ] A multi-hour fixture/live acceptance path uses the configured audio cap, records measured disk evidence, archives successfully, and reclaims local audio.
- [ ] Default short-video pilot behavior remains unchanged; no concurrent worker/daemon is introduced.
- [ ] Credentials, signed URLs, and raw exceptions are absent from outputs and committed artifacts.
- [ ] Full Python 3.12 test suite and the declared WSL operator acceptance gate pass.
- [ ] `git status --short` contains only in-scope changes.

## Prepare → Execute Handoff

Prepare must lock the scheduler command/options, sidecar fields, completion-state vocabulary, long-live opt-in, and dependency on the mixed-outcome plan. Execute Task 1 before Task 2; after all tasks, produce the branch review package, mandatory QC tri-review, and QA gate. Any deferred concurrency or telemetry work must remain in the roadmap above, not in narrative-only notes.
