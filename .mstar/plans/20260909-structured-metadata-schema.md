# Structured Metadata Schema and SQLite Repository

> Iteration: `iter-2026-09-bilibili-api-sqlite`.
> Execution mode: `sdd`.
> Findings cleanup: `zero-residual`.

## Status

- Priority: P0
- Task category: backend / data persistence
- Status: Done
- Depends on: none
- Primary spec: `.mstar/iterations/iter-2026-09-bilibili-api-sqlite/specs/structured-metadata-storage.md`
- Owner: fullstack-dev
- QA gate: mandatory

## Goal

Create a normalized SQLite schema and repository layer that serves as the single
source of truth for Bilibili metadata (users, videos, parts) and ingestion state
(runs, cursors, pages). The schema satisfies 3NF: no duplicate derived values,
all facts are normalized. No migration of existing JSONL archives is performed.

## Architecture

The database layer owns schema initialization, foreign-key enforcement,
transaction boundaries, idempotent upserts, cursor state, and normalized query
views. It does not import `bilibili_api`, open network connections, store full
API responses, or write audio/transcript bytes. Future media and transcript
references are represented only by explicit normalized tables and foreign keys.

## Tech Stack

Python 3.12 standard library `sqlite3`, typed dataclasses/protocols, pytest,
SQLite constraints/views/triggers only where they preserve 3NF and do not hide
business transitions.

## Global Constraints

- The new database path is `{archive_root}/archive.db`; a fresh database is
  initialized from a checked-in schema file.
- `PRAGMA foreign_keys = ON` is required for every connection; tests must assert
  that it is enabled.
- The schema must satisfy 3NF: do not store `work_id`, part counts, aggregate
  run counts, owner names in video rows, or other derivable duplicates.
- Current title/name fields are operational display labels and may be overwritten
  by idempotent upsert; no historical title/name, description, or statistics
  snapshots are stored in this iteration.
- Ingestion state is normalized into runs, cursors, pages, and discovery
  relationships; sidecar files are not read by this repository.
- Persisted errors are bounded scalar codes only. Never persist cookies, signed
  URLs, complete JSON responses, raw exception text, or tracebacks.
- Audio/transcript object tables are schema reservations only in this plan; no
  media or ASR implementation is added.
- All database writes are transactionally testable and deterministic.

## Interfaces

- Produces `DatabaseConnection`, repository methods for users/videos/parts,
  ingestion runs/pages/discoveries, and cursor reads/writes.
- Produces views `v_video_parts`, `v_ingestion_run_stats`, and
  `v_pending_metadata` consumed by the gateway/CLI plans.
- Consumes only validated internal dataclasses or scalar arguments; it never
  accepts third-party response dictionaries.

## Tasks

### Task 1: Implement the normalized schema bootstrap

**Files:**
- Create: `bilibili-asr-archive/src/bili_asr/storage/__init__.py`
- Create: `bilibili-asr-archive/src/bili_asr/storage/schema.sql`
- Create: `bilibili-asr-archive/src/bili_asr/storage/database.py`
- Test: `bilibili-asr-archive/tests/test_storage_schema.py`

**Interfaces:**
- Consumes: archive root path and schema SQL.
- Produces: `open_database(path)`, foreign-key-enabled connection, schema tables,
  constraints, and views.

- [x] Define tables `bilibili_users`, `videos`, `video_parts`,
  `ingestion_runs`, `ingestion_cursors`, `ingestion_pages`,
  `ingestion_discoveries`, plus the reserved audio/transcript tables from the
  primary spec with explicit FK constraints using `ON DELETE RESTRICT`.
- [x] Define primary keys, candidate-key unique constraints, foreign keys,
  status checks, non-negative checks, and the three required views.
- [x] Implement duration conversion as `floor(seconds * 1000)` and page-index
  normalization as `page - 1` per the spec's normalization rules.
- [x] Configure SQLite with foreign keys enabled and a transaction-safe default;
  do not add an ORM or a second database library.
- [x] Test a fresh database, foreign-key rejection, duplicate-key rejection,
  derived work ID view, the absence of duplicate aggregate columns, and the
  explicit transaction ordering that prevents FK violations.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_storage_schema.py -v`

### Task 2: Implement repository transactions and idempotent upserts

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/storage/database.py`
- Create: `bilibili-asr-archive/src/bili_asr/storage/models.py`
- Test: `bilibili-asr-archive/tests/test_metadata_repository.py`

**Interfaces:**
- Consumes: internal models `UserRecord`, `VideoRecord`, `VideoPartRecord`,
  `IngestionRunRecord`, `IngestionPageRecord`, and `CursorRecord`.
- Produces: `MetadataRepository.upsert_user`, `upsert_video`, `upsert_part`,
  `start_run`, `finish_run`, `record_page`, `record_discovery`,
  `read_cursor`, `write_cursor`, `list_pending_parts`, and `run_stats`.

- [x] Add dataclasses with explicit fields and validation for the schema types;
  keep `work_id` as a computed property rather than a persisted field.
- [x] Implement one-page transaction support using the explicit ordering from the
  primary spec: (1) upsert user, (2) upsert video, (3) upsert parts, (4) insert
  discoveries, (5) update cursor, (6) record page outcome, (7) commit. This order
  guarantees FK parents exist before FK children are inserted.
- [x] Make repeated ingestion of the same page idempotent for entities and
  discovery relationships while allowing a new run to retain its own page
  record.
- [x] Keep failure handling bounded: a failed page records a scalar error code,
  rolls back the entire transaction, leaves the previous cursor unchanged, and
  marks the run/page outcome in a separate transaction.
- [x] Test single-part and multipart videos, repeated pages, cursor resume,
  failed-page rollback, missing foreign keys, FK delete restriction, and
  pending-part queries.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_metadata_repository.py -v`

### Task 3: Validate schema and repository against the contract

**Files:**
- Modify: `bilibili-asr-archive/tests/test_storage_schema.py`
- Modify: `bilibili-asr-archive/tests/test_metadata_repository.py`
- Create: `bilibili-asr-archive/tests/fixtures/metadata_records.py`

**Interfaces:**
- Consumes: repository and schema from Tasks 1–2.
- Produces: deterministic contract evidence for the gateway and CLI plans.

- [x] Add a schema inspection test that checks required tables, views, foreign
  keys with `ON DELETE RESTRICT`, unique constraints, status checks, and the
  absence of `work_id` as a base-table column. Verify the three views compute
  derived values correctly.
- [x] Add a repository E2E test that inserts one user, one single-part video,
  one multipart video, two runs, page records, and cursor transitions using the
  explicit transaction ordering (user → video → parts → discoveries → cursor →
  page outcome).
- [x] Add FK constraint tests: attempt to insert a video without its user,
  attempt to insert a part without its video, and verify `ON DELETE RESTRICT`
  prevents orphaning.
- [x] Add a no-secret persistence test that attempts forbidden fields and proves
  the repository accepts only bounded scalar error codes.
- [x] Keep all tests offline and independent of `bilibili_api`.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_storage_schema.py tests/test_metadata_repository.py -v`

## STOP Conditions

- A required table needs a duplicated derived attribute to satisfy a current
  consumer; stop and update the spec rather than denormalizing silently.
- SQLite cannot enforce a stated relationship or transaction boundary without
  storing raw API payloads; stop and escalate the contract gap.
- Existing old archive files are read or modified by the new repository.
- The repository begins importing `bilibili_api`, `requests`, or any network
  transport.
- A test requires live HTTP, credentials, or model weights.

## Durable Roadmap and Dependencies

- Batch 1 (this plan): schema, typed repository, and offline contract tests.
- Batch 2 (`20260909-bilibili-api-ingestion`): gateway DTOs and page ingestion;
  blocked until this plan's repository contract is accepted.
- Batch 3 (`20260909-metadata-cli-smoke`): CLI replacement and live smoke;
  blocked until Batch 2 is accepted.
- Next iteration: populate subtitle/audio/transcript tables and implement
  versioned transcript segments after metadata contracts are stable.
- Final Done definition: the database can be rebuilt from a future fresh ingest,
  supports normalized future media/transcript references, and has no second
  metadata source of truth.
- QC carry-over contract rules inherited by Batch 2 (gateway) and Batch 3 (CLI):
  (1) record-level bounded-error validation is the secret-prevention SSOT — the
  schema enforces only the 64-char length bound, so the gateway must keep
  record-level charset/forbidden-class validation and never persist raw payloads,
  cookies, signed URLs, or tracebacks; (2) a schema version stamp decision
  (`IF NOT EXISTS` currently accepts a divergent legacy DB) belongs to the Batch 2
  contract acceptance; no legacy DB can exist today (fresh rebuild only);
  (3) FK-child indexes (`videos.mid`, `ingestion_runs.mid`) are deliberately
  deferred until ingest volume justifies them.

## Drift Check

Before implementation, compare the current `pyproject.toml`, `cli.py`,
`manifest.py`, `meta_cursor.py`, and existing untracked schema prototypes. Do not
copy the prototypes as-is. Confirm the new paths are the only intended product
files and that the package root remains `bilibili-asr-archive/`.

## Acceptance / Done Criteria

- [x] `schema.sql` creates all declared tables, views, primary keys, foreign keys,
  unique constraints, and check constraints in a fresh database.
- [x] Schema satisfies 3NF: no duplicate derived values in base tables. Specifically,
  `work_id`, part counts, and run aggregates are computed in views or application
  code, not stored as columns.
- [x] Foreign key constraints reject orphaned records (e.g., video without user,
  part without video).
- [x] Unique constraints prevent duplicate entities (e.g., duplicate `(bvid, page_index)`
  for video parts).
- [x] Repository performs idempotent upserts: re-inserting the same user/video/part
  updates display labels without creating duplicate rows or failing on constraint
  violations.
- [x] Cursor advancement and page outcome recording are atomic per successful page
  transaction. A failed transaction leaves the prior cursor unchanged.
- [x] Failed pages persist only bounded scalar error codes; no credentials, signed
  URLs, raw JSON, or stack traces are stored.
- [x] Offline schema and repository tests pass on Python 3.12 without network access.
- [x] No legacy JSONL file (`manifest.jsonl`, `meta-cursor.json`, `run-ledger.jsonl`)
  is read or written by the new repository.
- [x] `git diff --check` is clean for the plan's implementation changes.

## Prepare → Execute Handoff

Prepare must lock the table list, functional-dependency decisions, repository
interfaces, and sequential dependency on the gateway plan. Execute Task 1 before
Task 2, then Task 3. After all tasks, produce the SDD review package, mandatory
QC tri-review, and QA gate before marking this plan Done.

## Review Gate Summary

- Decision: Approve (QC tri N=3 converged after fix waves: initial 2×Request Changes + 1×Approve → fix wave 1 `6d76ea4` → targeted re-review N=2 Approve → round-2 micro-fix `2063a1a` → targeted re-review round 2 N=2 Approve; 0 Critical / 0 Warning / 0 open Suggestion)
- Review range / Diff basis: `c98f140..2063a1a` (merge-base c98f140 with spec integration branch; final reviewed head `2063a1a`)
- Review bundle: `.mstar/sdd/20260909-structured-metadata-schema/review/`
- QC inputs: `qc1.md`, `qc2.md`, `qc3.md` (Revalidation rounds 1–2 in place), consolidated: `qc-consolidated.md`
- Blocking result: none (W1–W6 resolved and seat-verified; no open residual)
- Residual findings: none open (zero-residual; carried contract items in Durable Roadmap; ⚪ U1–U3 evidence items routed to the mandatory QA gate)

## QA Gate Summary

- QA gate: mandatory
- QA mode: acceptance
- Evidence: **Approve (recommend merge)** — L4 acceptance gate executed by `qa-engineer`; report: `.mstar/sdd/20260909-structured-metadata-schema/review/qa-gate.md`.
  - Checkout aligned: Review cwd `.worktrees/20260909-structured-metadata-schema`, branch `feature/20260909-structured-metadata-schema`, HEAD `2063a1a`, cumulative range `c98f140..2063a1a`, clean tree (QA-verified).
  - U1 closed (fresh re-run): focused `pytest tests/test_storage_schema.py tests/test_metadata_repository.py -v` → **33 passed in 0.78s**; full `pytest` → **726 passed in 40.84s** (Python 3.12.3 / pytest 9.1.1, offline) — pass counts are now QA-executed, not implementer-reported.
  - U2 closed (fresh build): `uv build --wheel` → `bili_asr-0.1.0-py3-none-any.whl` ships `bili_asr/storage/schema.sql` (12 CREATE TABLE + 3 CREATE VIEW, first line `PRAGMA foreign_keys = ON;`); `uv build --sdist` ships the same file; scratch artifacts removed, tree clean, nothing committed — the previously documented build-tooling gap is resolved with a real build.
  - U3 closed (verified): all QA runs used the control-checkout interpreter `bilibili-asr-archive/.venv/bin/python`; feature worktree has no `.venv`; no `PYTEST_*`/import-mode override → pytest default prepend import mode (`from fixtures.metadata_records import …` resolved).
  - DoD mapping: all 10 `Acceptance / Done Criteria` covered with evidence paths + commands (9 items QA-freshly-executed; legacy-JSONL absence = fresh grep + L2 reuse) — see report table.
  - Residuals: zero open (register empty repo-wide; engine status `residuals: none open`); `zero-residual` satisfied.
  - Plan NOT marked Done: integration merge precedes Done; PM owns the merge.

## Sign-off

- Product intent: pending product-manager review
- Architecture: pending architect review
- Writing/corpus hygiene: pending writing-specialist review
- PM lock: pending
- Implementation owner: fullstack-dev
- QA owner: qa-engineer
- Review cleanup: zero-residual

## Plan self-review

1. Every schema requirement maps to a task and an offline assertion.
2. No task depends on an unspecified response dictionary or raw JSON payload.
3. Dependencies are serial and visible in the compass and workflow snapshot.
4. No placeholder implementation is required to pass the acceptance gate.
5. The plan deliberately excludes migration and media processing.

## Evidence Index

- Primary spec: `.mstar/iterations/iter-2026-09-bilibili-api-sqlite/specs/structured-metadata-storage.md`
- Tests: `tests/test_storage_schema.py`, `tests/test_metadata_repository.py`
- SDD runtime: `.mstar/sdd/20260909-structured-metadata-schema/`
- Review bundle: `.mstar/sdd/20260909-structured-metadata-schema/review/`

## Status Transition

This plan starts as `Todo`, enters `InProgress` only after the Phase 2 lease is
claimed, enters `InReview` after implementation, and can be marked `Done` only by
project-manager or qa-engineer after QC and the mandatory QA gate.

## End

The schema is the durable contract; implementation must update this plan first
if a new constraint changes the design.
