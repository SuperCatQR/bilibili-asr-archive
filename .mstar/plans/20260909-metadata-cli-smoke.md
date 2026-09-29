# SQLite-backed Metadata CLI and Bounded Verification

> Iteration: `iter-2026-09-bilibili-api-sqlite`.
> Execution mode: `sdd`.
> Findings cleanup: `zero-residual`.

## Status

- Priority: P0
- Task category: backend / CLI verification
- Status: Todo
- Depends on: `20260909-bilibili-api-ingestion`
- Primary spec: `.mstar/iterations/iter-2026-09-bilibili-api-sqlite/specs/metadata-cli-contract.md`
- Owner: fullstack-dev
- QA gate: mandatory

## Goal

Wire the existing `bili-asr` executable to use the fresh SQLite repository and
typed gateway for metadata commands (`fetch-meta`, `status`, `runs`). Prove the
replacement works with offline fake-gateway E2E tests and one bounded opt-in
live smoke test.

## Architecture

The CLI constructs configuration, database, gateway, and ingestion services; it
never parses third-party dictionaries and never opens the old JSONL manifest.
The command surface remains intentionally small for this iteration: metadata
fetch, status, and runs. The smoke test writes only to a temporary archive root.

## Tech Stack

Python 3.12, argparse-compatible CLI, `bilibili-api-python==17.4.2`, SQLite,
asyncio bridge for the synchronous console entrypoint, pytest, and optional live
network execution.

## Global Constraints

- Replace the metadata behavior in the existing `bili-asr` entrypoint; do not
  add a parallel `bili-asr-v2` executable.
- `fetch-meta` writes `{archive_root}/archive.db` through the repository and
  never writes `manifest.jsonl`, `meta-cursor.json`, or `run-ledger.jsonl`.
- `status` and `runs` read the same SQLite database and expose derived counts;
  they do not read old sidecars.
- The live smoke is opt-in, limited to one public page for UID 23191782, uses a
  temporary archive root, and does not call subtitle/playback/audio/ASR code.
- No migration, deletion, or rewriting of old archive data is performed.
- CLI output and persisted records must not contain SESSDATA, signed URLs, raw
  response bodies, or raw exception text.
- Preserve the project's exit taxonomy for usage/configuration and terminal
  gateway errors, with bounded page limits and no unbounded retries.

## Interfaces

- Consumes: `MetadataIngestor`, `MetadataRepository`, `BilibiliGateway`, and
  configuration from Plans 1–2.
- Produces: SQLite-backed `fetch-meta`, `status`, and `runs` commands plus
  deterministic fake-gateway E2E and opt-in live-smoke tests.

## Tasks

### Task 1: Replace metadata CLI construction and commands

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/cli.py`
- Create: `bilibili-asr-archive/src/bili_asr/config.py`
- Modify: `bilibili-asr-archive/pyproject.toml`
- Test: `bilibili-asr-archive/tests/test_metadata_cli.py`

**Interfaces:**
- Consumes: CLI arguments, environment configuration, and service constructors.
- Produces: SQLite-backed command handlers with documented exit behavior.

- [x] Add configuration loading for archive root, optional SESSDATA, and bounded
  metadata page parameters; redact credentials from any display path.
- [x] Wire `fetch-meta` to the new ingestor and expose `--mid`, `--start-page`,
  `--limit-pages`, `--archive-root`, and optional `--sessdata`.
- [x] Wire `status` to `v_pending_metadata` and `runs` to normalized run/page
  queries; fail clearly when the fresh database is missing for read commands.
- [x] Remove metadata command reads/writes of old JSONL and cursor sidecars from
  the new path without changing unrelated future processing modules.
- [x] Test parser behavior, fresh database creation, status/run output, exit codes,
  and no-old-file assertions.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_metadata_cli.py -v`

### Task 2: Add offline metadata E2E verification

**Files:**
- Create: `bilibili-asr-archive/tests/test_metadata_e2e.py`
- Modify: `bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py`
- Modify: `bilibili-asr-archive/tests/test_metadata_ingest.py`

**Interfaces:**
- Consumes: CLI, ingestor, repository, and fake gateway.
- Produces: deterministic end-to-end evidence for the iteration acceptance gate.

- [x] Script a single-part video and a multipart video returned by the fake gateway.
- [x] Verify normalized user/video/part/discovery/run/page/cursor rows and the
  computed `work_id` view values.
- [x] Re-run the same page and assert no duplicate entity or discovery rows.
- [x] Script a failed page, assert cursor preservation and bounded error storage,
  then resume successfully from the prior cursor.
- [x] Assert no old JSONL/cursor/ledger files are created in the temporary root.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_metadata_e2e.py -v`

### Task 3: Add the bounded live API smoke test and operator notes

**Files:**
- Create: `bilibili-asr-archive/tests/test_live_metadata_smoke.py`
- Modify: `bilibili-asr-archive/README.md`
- Create: `bilibili-asr-archive/docs/metadata-storage.md`

**Interfaces:**
- Consumes: the real gateway and CLI from Tasks 1–2.
- Produces: opt-in one-page live evidence and user-facing setup instructions.

- [x] Make live execution opt-in through `BILI_LIVE_SMOKE=1`; default test runs
  skip it without failure.
- [x] Limit live fetch to one public page for UID 23191782 and a temporary DB;
  assert at least the expected normalized table relationships when successful.
- [x] Document the fresh database layout, no-migration behavior, credential
  boundary, and exact bounded smoke command.
- [x] Do not document or expose returned raw JSON, signed URLs, or credentials.

Run: `cd bilibili-asr-archive && BILI_LIVE_SMOKE=1 .venv/bin/python -m pytest tests/test_live_metadata_smoke.py -v`

## STOP Conditions

- The existing CLI cannot replace metadata persistence without changing the
  future subtitle/audio/ASR contract; update the roadmap/spec before expanding.
- A command still reads a legacy metadata sidecar after the replacement wiring.
- Live smoke cannot be bounded to one page and a temporary database.
- Any output or fixture contains credentials, signed URLs, raw JSON, or traces.
- The new CLI requires a second executable or a second metadata source of truth.

## Durable Roadmap and Dependencies

- Batch 1: Plan 1 schema/repository.
- Batch 2: Plan 2 gateway/ingestion.
- Batch 3 (this plan): CLI replacement and verification.
- Next iteration: add subtitle acquisition and normalized transcript segments,
  then audio objects and ASR version records; owner: project-manager.
- Final Done definition: a single SQLite-backed metadata entrypoint feeds the
  future complete speech-to-text archive without JSONL metadata state.

## Drift Check

Before implementation inspect all existing CLI registrations for `fetch-meta`,
`status`, and `runs`, plus package entrypoints and tests. Confirm the new command
is the only metadata writer and that old uncommitted prototypes are not imported.

## Acceptance / Done Criteria

- [x] Metadata CLI creates and reads only the fresh SQLite database at
  `{archive_root}/archive.db`.
- [x] Offline fake-gateway E2E passes for: single-part video, multipart video,
  duplicate page (idempotency), failed page with cursor preservation, and
  successful resume from prior cursor.
- [x] Opt-in live smoke is bounded to one public metadata page (UID 23191782,
  `--limit-pages 1`, temporary archive root) and calls no subtitle/playback/
  audio/ASR code.
- [x] No legacy files (`manifest.jsonl`, `meta-cursor.json`, `run-ledger.jsonl`)
  are created or read by the new commands.
- [x] Credentials, signed URLs, raw JSON responses, and raw exception text are
  absent from CLI output, logs, and persisted database rows.
- [x] README and `docs/metadata-storage.md` describe the actual fresh-start
  workflow with accurate commands and exit code meanings.
- [x] Existing test suite remains green or any intentional contract changes are
  updated in this plan before implementation.
- [x] `git diff --check` is clean.

## Prepare → Execute Handoff

Prepare must lock the command names, exit behavior, no-migration boundary, live
smoke bound, and dependency on Plan 2. Execute Task 1 before Task 2, then Task 3.
After all tasks, produce the SDD review package, mandatory QC tri-review, and QA
gate before marking this plan Done.

## Review Gate Summary

- Decision: QC converged — Approve conditional on the mandatory QA gate closing the routed runtime evidence U1–U4 (initial tri 3×Request Changes → docs fix wave `1a99751` + PM spec edit → targeted re-review N=3: seats 2/3 Approve, seat 1 no open defects with stated resolution path)
- Review range / Diff basis: `18b6353..1a99751` (merge-base 18b6353 with spec integration branch; final reviewed head `1a99751`)
- Review bundle: `.mstar/sdd/20260909-metadata-cli-smoke/review/`
- QC inputs: `qc1.md`, `qc2.md`, `qc3.md` (Revalidation in place), consolidated: `qc-consolidated.md`
- Blocking result: none unresolved in QC scope (W1 exit-2 contract drift + W2 default page bound resolved and seat-verified; routed runtime evidence U1–U4 → QA gate)
- Residual findings: none open (zero-residual; accepted-with-rationale polish notes + next-iteration carries in Durable Roadmap)

## QA Gate Summary

- QA gate: mandatory
- QA mode: acceptance
- Evidence: **QA gate Approve (recommend merge)** — qa-engineer L4, 2026-09-10, at `1a99751` (checkout alignment verified; worktree clean). U1 fresh re-runs: full suite `861 passed, 2 skipped`, focused trio `38 passed, 1 skipped` — exact post-fix baselines. U2 opted-in live smoke: anonymous bounded-failure path executed and evidenced (designed `response_error` → exit 2 → reasoned skip after bounded-failure + leak assertions ran); happy path = explicit live-network blocker (`BILI_SESSDATA` unset on this machine; presence-checked only, nothing fabricated). U3 isolated-install verified: `uv build --wheel` → offline scratch-venv install → `bili_asr.cli` imports from site-packages → `bili-asr --help` exit 0 → `schema.sql` package-data present → scratch cleaned. U4: no third-party writes outside the temporary root observed (package write surfaces all in non-metadata modules; temp root torn down). All 9 acceptance items mapped (8 reuse + routed gaps closed fresh); zero open residuals. Full report: `.mstar/sdd/20260909-metadata-cli-smoke/review/qa-gate.md`

## Sign-off

- Product intent: pending product-manager review
- Architecture: pending architect review
- Writing/corpus hygiene: pending writing-specialist review
- PM lock: pending
- Implementation owner: fullstack-dev
- QA owner: qa-engineer
- Review cleanup: zero-residual

## Plan self-review

1. CLI wiring, offline E2E, and live smoke each have an explicit task.
2. The plan depends on typed service/repository contracts rather than raw API data.
3. The live test has a strict page and filesystem bound.
4. No migration or deferred media pipeline is hidden in this plan.
5. All acceptance claims have named commands or database assertions.

## Evidence Index

- Primary spec: `.mstar/iterations/iter-2026-09-bilibili-api-sqlite/specs/metadata-cli-contract.md`
- Tests: `tests/test_metadata_cli.py`, `tests/test_metadata_e2e.py`,
  `tests/test_live_metadata_smoke.py`
- SDD runtime: `.mstar/sdd/20260909-metadata-cli-smoke/`
- Review bundle: `.mstar/sdd/20260909-metadata-cli-smoke/review/`

## Status Transition

This plan starts as `Todo`, enters `InProgress` after Plan 2 and the Phase 2
lease are satisfied, enters `InReview` after implementation, and can be marked
`Done` only after QC and mandatory QA.

## End

The CLI is a thin composition root; repository and gateway contracts carry the
long-term design.

## Final Plan Statement

No old data is migrated. The new command starts from a fresh SQLite database and
writes only normalized metadata and ingestion process records.

## Verification Boundary

The bounded live test validates package integration only; it is not a corpus
coverage claim and must not be expanded without a new scope decision.

## Future Compatibility

Later media and transcript plans must use the foreign-key boundaries established
by the schema plan rather than reintroducing sidecars.

## Review Boundary

Specialist review may edit this plan and its iteration package during Phase 1;
raw QC/QA reports belong under the plan's SDD review directory during Phase 2.

## Completion Evidence

Plan completion requires offline tests, live-smoke evidence or an explicit live
network blocker, and a clean metadata command path.

## End of Plan

The plan is intentionally serial with the schema and gateway plans.
