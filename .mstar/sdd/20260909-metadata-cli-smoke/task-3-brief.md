### Task 3: Add the bounded live API smoke test and operator notes

**Files:**
- Create: `bilibili-asr-archive/tests/test_live_metadata_smoke.py`
- Modify: `bilibili-asr-archive/README.md`
- Create: `bilibili-asr-archive/docs/metadata-storage.md`

**Interfaces:**
- Consumes: the real gateway and CLI from Tasks 1–2.
- Produces: opt-in one-page live evidence and user-facing setup instructions.

- [ ] Make live execution opt-in through `BILI_LIVE_SMOKE=1`; default test runs
  skip it without failure.
- [ ] Limit live fetch to one public page for UID 23191782 and a temporary DB;
  assert at least the expected normalized table relationships when successful.
- [ ] Document the fresh database layout, no-migration behavior, credential
  boundary, and exact bounded smoke command.
- [ ] Do not document or expose returned raw JSON, signed URLs, or credentials.

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

- [ ] Metadata CLI creates and reads only the fresh SQLite database at
  `{archive_root}/archive.db`.
- [ ] Offline fake-gateway E2E passes for: single-part video, multipart video,
  duplicate page (idempotency), failed page with cursor preservation, and
  successful resume from prior cursor.
- [ ] Opt-in live smoke is bounded to one public metadata page (UID 23191782,
  `--limit-pages 1`, temporary archive root) and calls no subtitle/playback/
  audio/ASR code.
- [ ] No legacy files (`manifest.jsonl`, `meta-cursor.json`, `run-ledger.jsonl`)
  are created or read by the new commands.
- [ ] Credentials, signed URLs, raw JSON responses, and raw exception text are
  absent from CLI output, logs, and persisted database rows.
- [ ] README and `docs/metadata-storage.md` describe the actual fresh-start
  workflow with accurate commands and exit code meanings.
- [ ] Existing test suite remains green or any intentional contract changes are
  updated in this plan before implementation.
- [ ] `git diff --check` is clean.

## Prepare → Execute Handoff

Prepare must lock the command names, exit behavior, no-migration boundary, live
smoke bound, and dependency on Plan 2. Execute Task 1 before Task 2, then Task 3.
After all tasks, produce the SDD review package, mandatory QC tri-review, and QA
gate before marking this plan Done.

## Review Gate Summary

- Decision: pending
- Review range / Diff basis: pending
- Review bundle: `.mstar/sdd/20260909-metadata-cli-smoke/review/`
- QC inputs: `qc1.md`, `qc2.md`, `qc3.md`
- Blocking result: pending
- Residual findings: pending

## QA Gate Summary

- QA gate: mandatory
- QA mode: acceptance
- Evidence: pending

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
