# Normalized Transcript Storage on the Reserved Tables

> Iteration: `iter-2026-09-subtitle-transcript-sqlite`.
> Execution mode: `sdd`.
> Findings cleanup: `zero-residual`.

## Status

- Priority: P0 (iteration-critical, serial 2/3: the CLI plan can store nothing until these
  tables and repository methods exist; this plan resolves carry F-010)
- Task category: backend / data persistence
- Status: Done
- Depends on: `20260911-subtitle-gateway` (segment DTOs)
- Primary spec: `.mstar/iterations/iter-2026-09-subtitle-transcript-sqlite/specs/transcript-storage.md`
- Owner: fullstack-dev
- QA gate: mandatory

## Goal

Turn the reserved `transcripts` / `transcript_segments` tables into the working, versioned,
idempotent store for acquired subtitles, and decide explicitly where subtitle/transcript
**process records** live instead of overloading the metadata-scoped `ingestion_runs`.

**What the operator gets from this plan.** A caption that has been acquired becomes a
queryable fact about a part — which source it came from (AI or CC), which language, which
version, when it was stored, and its millisecond timeline — and the store never destroys what
it already holds: re-running acquisition is a no-op when the content is unchanged, a changed
caption appends a new version, and every earlier version stays readable. The plan also makes
"no subtitle was visible" a recorded, timestamped per-part fact rather than an absence, so
neither the operator nor the next iteration has to guess whether a part was ever attempted.

## Architecture

Locked in `specs/transcript-storage.md` §2:

- `transcripts` gains `language TEXT NOT NULL` and
  `content_sha256 TEXT NOT NULL` (SHA-256 over the canonical JSON of
  `[start_ms, end_ms, text]` triples), the version key widens to
  `(video_part_id, source_kind, language, version)`, and a partial unique index
  `ux_transcripts_subtitle_content` enforces content identity for the two caption kinds.
- Process records get their own `kind`-keyed pair — `acquisition_runs` (one row per run,
  carrying selector, bound, credential presence, times, outcome) and `acquisition_attempts`
  (one row per attempted part, `PRIMARY KEY (run_id, video_part_id)`, outcome + bounded code +
  the transcript version it produced, append-only evidence that never becomes a terminal
  per-part state). `ingestion_runs` and its views are untouched (carry F-010 resolved). The
  next iteration reuses the same pair with `kind='audio'` / `'asr'`.
- One pending-work relation, `v_pending_subtitles`, carries the last-attempt evidence itself
  (no companion per-part query): `attempted`, `last_attempt_at`, `last_attempt_outcome`,
  `last_attempt_error_code`, `last_attempt_credential_present`, plus the `cid` the gateway call
  needs. Order is imposed by the repository:
  `attempted ASC, last_attempt_at ASC, bvid ASC, page_index ASC`.
- Rebuild stance, made executable: the schema splits into `schema.sql` (everything shipped
  before this iteration, minus the transcript block) and `schema-transcripts.sql` (the new
  contract). `initialize_schema` executes the second script only when `transcripts` is absent
  or already carries the new columns, so a pre-iteration database keeps working for the
  metadata commands instead of half-applying a schema it cannot accept;
  `require_subtitle_schema(connection)` then raises a bounded `SchemaContractError` for the
  subtitle commands, which report the rebuild procedure and exit `1`. No `ALTER TABLE`, no
  backfill, no compatibility reader.

A sibling repository class `TranscriptRepository` in `storage/database.py` (same connection,
same validation helpers and commit-boundary discipline as `MetadataRepository`) owns the
transcript and process-record writes; the metadata repository's documented commit matrix stays
exactly true. `storage` never imports `sources`: `storage/models.py` gains
`TranscriptSegmentRecord`, `TranscriptWriteResult`, `AcquisitionRunRecord` and the vocabulary
frozensets, and the service maps the gateway's `SubtitleSegment` into
`TranscriptSegmentRecord`.

## Tech Stack

Python 3.12 stdlib `sqlite3`, typed dataclasses, pytest, the shipped `schema.sql`
initialization path (now two resources) and its `resources.files` loader.

## Global Constraints

- The database stays 3NF: no derived duplicates in base tables (`work_id`, counts, and
  aggregates remain views/computed).
- `PRAGMA foreign_keys = ON` for every connection; `ON DELETE RESTRICT` on all new FKs.
- Versions are immutable: a new version is a new `transcripts` row + its segments; existing
  versions are never rewritten or deleted. This is operator-facing: nothing a later run does
  removes or alters a version the operator already holds. Enforced by code paths (no
  `UPDATE`/`DELETE`), by `ON DELETE RESTRICT`, and by tests — no triggers.
  There is also no trigger guard needed: a transcript is only ever written with a non-empty
  segment tuple, so FK RESTRICT makes deletion impossible.
- Idempotency is content-based: identical normalized content writes nothing new and is
  recorded as `unchanged`; the content hash covers the segment sequence only, never the part
  id, source kind, or language.
- Process records must not overload `ingestion_runs` (metadata-scoped); the locked shape is
  `acquisition_runs` + `acquisition_attempts`, pinned by schema and repository tests.
- Product honesty in the stored evidence: a part that exposed no usable caption is recorded
  as timestamped per-part attempt evidence, never as a transcript row and never as a terminal
  "unavailable" state — a later successful acquisition for the same part must still be able to
  store a transcript. The store therefore answers, for a part, whether it was ever attempted,
  when it was last attempted, with what bounded outcome, and with what credential presence.
- The `asr-local` source kind, `audio_objects`, and `asr_models` stay unused reservations;
  nothing in this plan writes an ASR or audio row. The version key stays model-agnostic, and
  the content-identity index is scoped to the caption kinds so the audio/ASR iteration can
  define its own model identity without inheriting a trap.
- Bounded scalar error codes only in persisted evidence; no raw JSON, URLs, or tracebacks.
- The archive database is rebuildable by policy: schema changes require a fresh database, and
  no migration reader is introduced. A pre-iteration database must keep working for the
  metadata commands and must fail the subtitle commands with the fixed rebuild message.
- All tests offline and deterministic (caller-supplied clocks).

## Interfaces

- Consumes: `SubtitleSegment` (gateway plan, converted by the service), the existing schema
  bootstrap and repository conventions, `validate_error_code`.
- Produces, for the CLI plan:
  - `schema-transcripts.sql` and the conditional `initialize_schema`,
  - `require_subtitle_schema(connection)` / `SchemaContractError`,
  - `TranscriptRepository` with `start_acquisition_run`, `finish_acquisition_run`,
    `record_acquired_transcript`, `record_subtitle_attempt`, `read_transcript`,
    `list_transcript_versions`, `list_pending_subtitle_parts`, `count_pending_subtitle_parts`,
    `list_selected_parts`,
  - `storage.models.TranscriptSegmentRecord`, `TranscriptWriteResult`, `AcquisitionRunRecord`,
    and the `AcquisitionKind` / `AcquisitionOutcome` / `AttemptOutcome` / `SourceKind`
    vocabularies.

## Tasks

### Task 1: Schema contract, bootstrap split, and structural guard

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/storage/schema.sql`
- Create: `bilibili-asr-archive/src/bili_asr/storage/schema-transcripts.sql`
- Modify: `bilibili-asr-archive/src/bili_asr/storage/database.py`
- Modify: `bilibili-asr-archive/src/bili_asr/storage/models.py`
- Test: `bilibili-asr-archive/tests/test_storage_schema.py`

**Interfaces:**
- Consumes: the reserved tables, the shipped `resources.files` loader, and the spec's DDL.
- Produces: the locked columns, widened uniqueness, partial content index,
  `transcript_segments`, `acquisition_runs`, `acquisition_attempts`,
  `ix_acquisition_attempts_part_time`, `v_pending_subtitles`, the conditional bootstrap, and
  `require_subtitle_schema` / `SchemaContractError`.

- [x] Move the `transcripts` / `transcript_segments` block out of `schema.sql` into
      `schema-transcripts.sql` and add the locked DDL (language, content hash, widened unique
      key, partial content index, the run/attempt pair with their CHECK matrices, the attempt
      index, the pending view) exactly as specified.
- [x] Make `initialize_schema` execute the transcript script only when `transcripts` is absent
      or already current, so a pre-iteration database is left untouched instead of
      half-applied; keep `PRAGMA foreign_keys = ON` enforcement unchanged.
- [x] Add `require_subtitle_schema(connection)` as a structural capability check
      (`pragma_table_info('transcripts')` plus the new tables and view) raising
      `SchemaContractError`, and export it.
- [x] Add the storage vocabulary (`AcquisitionKind`, `AcquisitionOutcome`, `AttemptOutcome`,
      `SourceKind` literals + `ALLOWED_*` frozensets) and the `TranscriptSegmentRecord`,
      `TranscriptWriteResult`, `AcquisitionRunRecord` dataclasses with validation.
- [x] Extend the schema inspection tests: exact column manifests for `transcripts`,
      `acquisition_runs`, `acquisition_attempts`; FK pairs; unique/PK/index set including the
      partial index's `WHERE` clause; CHECK enumerations; the pending view's columns; and a
      "no derived duplicates" check over the new tables.
- [x] Bootstrap matrix tests: fresh database (full contract), current database (idempotent
      re-open), pre-iteration database (metadata tables usable, transcript objects absent,
      `require_subtitle_schema` raising). No migration path is introduced.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_storage_schema.py -v`

### Task 2: TranscriptRepository writes with content-based idempotency

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/storage/database.py`
- Modify: `bilibili-asr-archive/src/bili_asr/storage/models.py`
- Create: `bilibili-asr-archive/tests/test_transcript_repository.py`

**Interfaces:**
- Consumes: Task-1 schema/vocabulary and the existing canonical repository forms and commit
  matrix.
- Produces: `TranscriptRepository` with `start_acquisition_run`, `finish_acquisition_run`,
  `record_acquired_transcript`, `record_subtitle_attempt`.

- [x] Bound the converted timeline (carried from plan `20260911-subtitle-gateway` QC S11 / QC3-008):
      reject a segment whose millisecond product exceeds a documented ceiling (e.g. `> 10**12`, ≈31 years)
      with the bounded validation error, so an upstream JSON integer cannot reach SQLite as an unbounded
      `OverflowError`. Record the chosen ceiling in the spec's normalization section and pin it with a test.
- [x] Implement `start_acquisition_run` / `finish_acquisition_run` with the shipped run
      discipline (own commit; terminal outcomes cannot be regressed; when no explicit outcome
      is given, derive `complete | partial | failed` from the attempt rows).
- [x] Implement `record_acquired_transcript` as **one** transaction: validate the part and the
      arguments, compute the content hash from the canonical segment JSON, write nothing when a
      version of `(video_part_id, source_kind, language)` already carries that hash (attempt
      outcome `unchanged`, referencing the existing version), otherwise append
      `version = MAX(version) + 1` with its segments (attempt outcome `stored`), write the
      attempt row, and commit — or roll back wholly. Reject an empty segment tuple, a
      non-positive `video_part_id`, and a `start_ms`/`end_ms` violation.
- [x] Implement `record_subtitle_attempt` for the `no-subtitle` / `failed` outcomes only, with
      the CHECK matrix enforced in code as well (bounded `error_code` required for `failed`,
      `NULL` or `not_found` for `no-subtitle`, no transcript reference for either).
- [x] Document the class's commit-boundary matrix in its docstring in the same style as
      `MetadataRepository`, including the "do not compose inside `transaction()`" rule.
- [x] Tests: first write; idempotent repeat (`unchanged`, no new row, no duplicate segments);
      changed content → version 2 with version 1 and its segments unchanged; revert-to-older
      content → `unchanged` referencing version 1; FK rejections (unknown part, unknown run,
      unknown transcript); RESTRICTed deletes; CHECK violations; transactional rollback when the
      attempt row cannot be written; run-outcome derivation for all three cases plus the
      abnormal `failed`.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_transcript_repository.py -v`

### Task 3: Reads, pending enumeration, and contract evidence

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/storage/database.py`
- Modify: `bilibili-asr-archive/tests/test_transcript_repository.py`
- Modify: `bilibili-asr-archive/tests/test_storage_schema.py`

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces: `read_transcript`, `list_transcript_versions`, `list_pending_subtitle_parts`,
  `count_pending_subtitle_parts`, `list_selected_parts`, and the deterministic E2E evidence the
  CLI plan builds on.

- [x] Implement the read paths (latest version by default, explicit version on request;
      `None` when absent) and `list_selected_parts(bvid, page_index=None)` over
      `v_video_parts`, returning zero rows for an unknown selector so the CLI can exit `1`
      without inventing an empty selection.
- [x] Implement `list_pending_subtitle_parts(limit=None)` over `v_pending_subtitles` with the
      locked order (`attempted ASC, last_attempt_at ASC, bvid ASC, page_index ASC`) and
      `count_pending_subtitle_parts()`, with the shipped argument-validation discipline.
- [x] E2E evidence: one part with two languages and two versions; a stored part excluded from
      the pending set; a part with metadata only present with `attempted = 0`; a part recorded
      `no-subtitle` still present with its last outcome, timestamp, and credential presence; the
      never-attempted part enumerated before the previously attempted one; a successful
      re-attempt after `no-subtitle` storing a transcript normally under a new run.
- [x] Assert the enumeration contract the CLI depends on and that `work_id` stays view-only;
      assert no legacy sidecar file is created or read by any storage path.
- [x] Re-inspect the final schema for the locked invariants (column manifests, indexes, checks)
      and pin the process-record shape chosen in the spec.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_storage_schema.py tests/test_transcript_repository.py -v`

**PM-authorized follow-ups (2026-09-11, from the Task-2 L2 review).** Both are small and recorded, not
silent relaxations:

- [x] **M3 (coverage gap, the important one):** pin spec §5's "order preserved verbatim, overlaps included"
  with a body whose intervals are non-monotonic and overlapping (today every test body is ascending and
  non-overlapping), so a future "sort or de-overlap on write" regression fails a named test.
- [x] **M2 (consistency):** validate `run_id` through the same path as the other identifiers (the class
  currently uses `_text` in two places and a hand-rolled check in another) and keep the messages byte-identical.

## STOP Conditions

- A single-transaction transcript write cannot satisfy the FK order or immutability rules →
  stop and update the spec rather than weakening constraints.
- The locked process-record shape cannot record bounded evidence without touching
  `ingestion_runs` semantics → stop and escalate the contract gap.
- Satisfying idempotency requires storing raw subtitle payloads → stop; content hashes only.
- The bootstrap split cannot keep a pre-iteration database usable for the metadata commands
  without a migration path → stop and report; do not add `ALTER TABLE`/backfill code.
- Existing metadata tests cannot stay green under the schema change → stop and report (the
  change must be additive and rebuild-safe).

## Durable Roadmap and Dependencies

- Consumed by `20260911-subtitle-cli-cutover`; the `asr-local` source kind and `asr_models`
  FK stay unused until the audio/ASR iteration.
- Resolves carry F-010: subtitle/transcript process records get their own explicit home
  (`acquisition_runs` + `acquisition_attempts`, keyed by `kind`), so the metadata-scoped
  `ingestion_runs` semantics stay untouched. The next iteration reuses the same pair with
  `kind='audio'` / `'asr'`, and inherits the transcript versioning rules, the enumeration of
  parts with no transcript, and one recorded handoff: activating `asr-local` with more than one
  model requires widening the model-agnostic version key, owned there.
- Deferred with a named owner (`project-manager`, trigger "this iteration delivered"):
  promoting this storage contract out of the iteration package at iteration-close
  (`mstar-compound` decides `{SPECS_DIR}` versus `{KNOWLEDGE_DIR}`); nothing is written into
  `{SPECS_DIR}` during Prepare.
- Deferred: audio objects (`audio_objects` / `part_audio_objects`) remain reservations, and
  rebuilding SRT/TXT/MD projections from stored transcripts is owned by the next iteration.

- **Closed by fix wave 2 (plan QC seat 3, QC3-001, Warning)**: the last ordering key `page_index ASC` was not
  falsifiable — the committed fixture inserted every part of a `bvid` in ascending page order, so rowid order
  coincided with page order and the `drop page_index ASC` mutation passed, while this plan's DoD claims the
  order is pinned by tests. The fix is test-only (insert a part whose `page_index` is higher than a sibling
  inserted after it, then extend the expected list), and the DoD claim now holds in both directions.
- Recorded (QC3-004, performance characteristic, no measurement taken): `v_pending_subtitles`'s
  `ROW_NUMBER()` CTE has no predicate pushdown and `acquisition_attempts` is append-only with no pruning, so
  every pending query and `count_pending_subtitle_parts()` is O(subtitle attempts). Fine at personal scale;
  recorded so the audio/ASR iteration inherits the growth characteristic rather than rediscovering it.

- Recorded (cross-iteration, QC1-001): `v_pending_subtitles` treats **any** `transcripts` row as "this part
  has a caption". When the audio/ASR iteration starts writing `asr-local` transcripts, those parts will drop
  out of the subtitle backlog — which is the locked behaviour, but the audio/ASR plan must decide explicitly
  whether it wants its own pending view (or a `source_kind`-scoped predicate) rather than inheriting this one.
- Recorded (nit, QC1-002): the structural guard `_SUBTITLE_SCHEMA_OBJECTS` omits `transcript_segments`
  (spec §3.3 lists the objects verbatim). It is unreachable through `open_database`, which heals the table, so
  this is hardening rather than a defect — harden it with the other recorded nit when a plan next owns the
  bootstrap.

- Recorded (QC2-S1, related to QC1-001): the write paths verify that the run exists but not its `kind`;
  an attempt recorded under an `audio`/`asr` run is invisible to `v_pending_subtitles` (which filters
  `kind='subtitle'`), so that part would never rotate out of the subtitle backlog. Today's only caller passes
  `kind='subtitle'`. The audio/ASR iteration must either add a precondition or scope its own pending view.
- Recorded (nit, QC2-S2): immutability has three mechanisms and only two are falsifiable — "no UPDATE/DELETE
  code path" is inspection-only (the source is clean today). One static source scan would make it a test.
  Harden alongside QC1-002 when a plan next owns the bootstrap/repository contract.
- Handoff to the next iteration's projection owner (QC2 finding, spec-locked behaviour, no action here): after
  a revert-to-older-content acquisition, `read_transcript(version=None)` returns `MAX(version)` while the
  newest attempt references the older matched version — both facts are stored, so a future projection/export
  step must choose deliberately which one it means.

## Drift Check

Before implementing, re-read the shipped `schema.sql` reservations and the metadata
repository's canonical forms and `docs/metadata-storage.md` (its "Fresh-start behavior" and
"Reserved media boundary" sections must be updated by the CLI plan, not silently left wrong);
confirm no other module depends on the reserved tables' current shape or on `schema.sql` being
the single schema resource.

## Acceptance / Done Criteria

- [x] Schema carries the locked transcript columns/tables/indexes/view with inspection tests
      pinning them, and the bootstrap handles fresh / current / pre-iteration databases.
- [x] Transcript writes are transactional, versioned, immutable, and content-idempotent.
- [x] A stored transcript answers, per part: source kind (AI/CC), language, version, creation
      time, and millisecond segments; the latest version is what a default read returns, and an
      explicit version stays readable after a newer one is written.
- [x] "No subtitle was visible" is recorded as timestamped per-part attempt evidence, is not a
      transcript row, and does not prevent a later successful acquisition of the same part.
- [x] Process records for subtitle acquisition are explicit and do not touch
      `ingestion_runs` semantics.
- [x] The pending view's order and last-attempt columns are pinned by tests, so successive
      bounded runs advance instead of re-attempting the same head.
- [x] Offline suites green with no metadata-path regressions.
- [x] No sidecar file is created or read by any new path.
- [x] `git diff --check` clean.

## Prepare → Execute Handoff

Execute Task 1 → Task 2 → Task 3 (serial). Then SDD review package, QC tri, QA gate, merge.

## Review Gate Summary

- Decision: **Approve** (plan QC tri N=3 → seat 1 Approve, seat 2 Approve, seat 3 Request Changes on one
  Warning; fix wave 2 closed it and the N=1 targeted re-review returned Approve)
- Review range / Diff basis: `6ee7c6a..4dcbf5d` (5 commits: `d4cae24` schema contract, `f3cd735` write path,
  `1019000` reads/enumeration, `5f93e05` ordering test strength, `4dcbf5d` QC fix wave 2)
- Review bundle: `.mstar/sdd/20260911-transcript-storage/review/` (`qc-consolidated.md` carries the gate)
- QC inputs: `qc1.md`, `qc2.md`, `qc3.md` (+ `## Revalidation`)
- Blocking result: none at the final gate — 0 Critical / 0 Warning / 0 open Suggestion
- Residual findings: **none registered by this plan**; the only open entry is `R1` from
  `20260911-subtitle-gateway` (`low`, `decision: defer`, executable target = the next plan whose file list
  includes `sources/bilibili_api_gateway.py`; this range touches no `sources/` file, so it stays correct)
- QA gate: **Approve** (`review/qa-gate.md`): fresh `1202 passed, 3 skipped` at HEAD; the legacy-database
  bootstrap guarantee reproduced 18/18 on the shipped `open_database` path; the ordering pin independently
  falsified (four mutations of the key list each fail the named test, with `attempted ASC` provably
  order-equivalent — QAF-1 informational); immutability/idempotency probed 13/13
- Merged into the iteration branch as `f490fd1` (2026-09-11)

## QA Gate Summary

- QA gate: mandatory
- QA mode: acceptance
- Evidence: **Approve (recommend merge)** — qa-engineer, 2026-09-11, at `HEAD 4dcbf5d`
  (`feature/20260911-transcript-storage`, worktree clean before/after; branch-diff + fix-2-diff replayed
  from the package onto `6ee7c6a` reproduce the HEAD tree, and both fenced diffs are byte-identical to the
  live ranges). Full offline suite re-run at HEAD: **1202 passed, 3 skipped** (the 3 skips are exactly the
  opt-in `BILI_LIVE_SMOKE` gates, none added by this plan); focused metadata/schema/repository set 275 passed;
  `git diff --check` clean. Legacy guarantee reproduced on the **shipped** `open_database` path from a
  pre-iteration database built with the old bootstrap (18/18): metadata readable/writable, no half-applied
  transcript objects, `require_subtitle_schema` **and** `TranscriptRepository.__init__` raise the bounded
  `SchemaContractError` where a raw query would raise `sqlite3.OperationalError`. QC3-001 confirmed closed:
  rowid order ≠ page order inside the affected `bvid` and dropping `page_index ASC` now fails the named test.
  Immutability/idempotency re-probed live (13/13: repeated identical acquisition writes nothing new and the
  stored bytes are unchanged; no UPDATE/DELETE against the transcript tables anywhere). Residual register
  holds only R1 (`low`, `defer`, untouched — this range changes no file under `sources/`), so the plan may
  proceed to Done with R1 open. CLI-plan readiness confirmed (F3, R1 carriage, QC3-002/003/005,
  `docs/metadata-storage.md` in its file list). Report:
  `.mstar/sdd/20260911-transcript-storage/review/qa-gate.md`; one non-blocking observation (QAF-1: the
  redundant, order-equivalent `attempted ASC` key is unfalsifiable — no behavioural consequence) and PM
  bookkeeping (QAF-2: `Review Gate Summary` still reads "pending"). Plan not marked Done — the merge
  precedes Done and the PM owns it.

## Sign-off

- Product intent: reviewed (product-manager, 2026-09-11)
- Architecture: reviewed (architect, 2026-09-11)
- Writing/corpus hygiene: reviewed (writing-specialist, 2026-09-11)
- PM lock: locked (project-manager, 2026-09-11)
- Implementation owner: fullstack-dev
- QA owner: qa-engineer
- Review cleanup: zero-residual

## Plan self-review

1. Every spec decision maps to a task and an assertion, including the exact DDL deltas.
2. No task stores raw payloads or derived duplicates.
3. Immutability and idempotency are both testable, and each has a named enforcement mechanism.
4. The process-record decision is explicit, keyed by `kind`, and does not overload metadata
   runs; the next iteration's reuse is stated.
5. Audio/ASR objects stay reservations, with the model-identity handoff recorded.
6. The stored state answers the operator's questions — source, language, version, time axis —
   and records "no caption visible" as bounded per-part evidence rather than as an absence or a
   terminal state.

## Evidence Index

- Primary spec: `.mstar/iterations/iter-2026-09-subtitle-transcript-sqlite/specs/transcript-storage.md`
- Tests: `tests/test_storage_schema.py`, `tests/test_transcript_repository.py`
- SDD runtime: `.mstar/sdd/20260911-transcript-storage/`

## Status Transition

Starts `Todo`; `InProgress` after the Phase 2 lease; `InReview` after implementation;
`Done` only after QC + the mandatory QA gate and the integration merge.

## End

Transcript storage is the durable contract for every future caption/ASR source; the
gateway plan only feeds it.
