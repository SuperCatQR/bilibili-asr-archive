### Task 3: Verify third-party API behavior at the package seam

**Files:**
- Modify: `bilibili-asr-archive/tests/test_bilibili_api_gateway.py`
- Modify: `bilibili-asr-archive/tests/test_metadata_ingest.py`
- Create: `bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py`

**Interfaces:**
- Consumes: gateway and ingestor from Tasks 1–2.
- Produces: offline contract evidence and a documented live-smoke entry point
  for Plan 3.

- [ ] Assert the adapter calls only the documented user/video metadata methods
  and never playback/subtitle methods.
- [ ] Assert no persisted row or test output contains SESSDATA, signed URL text,
  raw JSON, or raw exception text.
- [ ] Add a live smoke test that is opt-in, uses UID 23191782, requests one page,
  writes to a temporary database, and skips cleanly when live execution is not
  requested.
- [ ] Record the live smoke command and bounded expectations for the CLI plan.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_bilibili_api_gateway.py tests/test_metadata_ingest.py -v`

## STOP Conditions

- The pinned package cannot expose one-page metadata calls without importing
  playback/subtitle APIs.
- A package response field cannot be normalized without retaining raw JSON or
  changing the 3NF repository contract.
- The gateway needs to persist a signed URL or credential to resume a page.
- `get_videos` pagination semantics cannot be bounded and represented by the
  cursor contract; update the spec before implementation.
- Live smoke would require more than one page or would write outside a temporary
  archive root.

## Durable Roadmap and Dependencies

- Batch 1: Plan 1 establishes schema and repository contracts.
- Batch 2 (this plan): gateway and normalized ingestion.
- Batch 3: `20260909-metadata-cli-smoke` wires the fresh CLI and verification.
- Next iteration: subtitle gateway and structured transcript segments.
- Final Done definition: all external package details are isolated behind typed
  gateways and all collected facts enter normalized tables through transactions.

## Drift Check

Before implementation inspect current `bili_client.py`, `cli.py`,
`pyproject.toml`, package import paths, and the installed package API. Confirm
that no existing metadata caller must be silently left on JSONL. Check that
uncommitted exploratory prototypes are not imported by the new package.

## Acceptance / Done Criteria

- [ ] `bilibili-api-python==17.4.2` is pinned and `uv.lock` is reproducible.
- [ ] Only `sources/bilibili_api_gateway.py` imports `bilibili_api`; all other
  modules consume application-owned DTOs and protocols.
- [ ] DTOs validate required metadata fields (non-empty BVID/title, positive
  CID/duration) and reject malformed responses before returning.
- [ ] Ingestion service writes normalized entities (user/video/part) and discovery
  relationships with idempotency: repeated pages update display labels without
  creating duplicate rows.
- [ ] Cursor advances only after a successful page transaction commits; failed
  pages leave the prior cursor intact.
- [ ] Bounded failure records contain scalar error codes only; no credentials,
  signed URLs, raw JSON, or stack traces are persisted.
- [ ] Offline gateway and ingestor tests pass on Python 3.12 without network access.
- [ ] Opt-in live smoke is bounded to one public metadata page for UID 23191782,
  writes to a temporary SQLite database, and calls no subtitle/playback/audio/ASR
  endpoints.
- [ ] `git diff --check` is clean.

## Prepare → Execute Handoff

Prepare must lock the package version, gateway methods, DTO fields, error
mapping, page bound, credential boundary, and dependency on Plan 1. Execute
Task 1 before Task 2, then Task 3. After all tasks, produce the SDD review
package, mandatory QC tri-review, and QA gate before marking this plan Done.

## Review Gate Summary

- Decision: pending
- Review range / Diff basis: pending
- Review bundle: `.mstar/sdd/20260909-bilibili-api-ingestion/review/`
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

1. Every gateway behavior maps to a typed interface and a fake test.
2. Every persistence operation maps to a Plan 1 repository method.
3. Pagination and failure semantics are explicit and bounded.
4. No raw response or credential is required for resumption.
5. This plan does not expand into subtitle, playback, audio, or ASR work.

## Evidence Index

- Primary spec: `.mstar/iterations/iter-2026-09-bilibili-api-sqlite/specs/bilibili-api-gateway.md`
- Tests: `tests/test_bilibili_api_gateway.py`, `tests/test_metadata_ingest.py`
- SDD runtime: `.mstar/sdd/20260909-bilibili-api-ingestion/`
- Review bundle: `.mstar/sdd/20260909-bilibili-api-ingestion/review/`

## Status Transition

This plan starts as `Todo`, enters `InProgress` after the Plan 1 dependency and
Phase 2 lease are satisfied, enters `InReview` after implementation, and can be
marked `Done` only after QC and mandatory QA.

## End

The gateway is a replaceable boundary; the normalized DTO and repository
contracts are the durable application interface.

## Final Plan Statement

No migration is required. A fresh database and fresh metadata collection begin
from the new gateway and schema.
