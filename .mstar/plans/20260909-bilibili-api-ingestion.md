# Bilibili API Gateway and Normalized Metadata Ingestion

> Iteration: `iter-2026-09-bilibili-api-sqlite`.
> Execution mode: `sdd`.
> Findings cleanup: `zero-residual`.

## Status

- Priority: P0
- Task category: backend / external integration
- Status: Todo
- Depends on: `20260909-structured-metadata-schema`
- Primary spec: `.mstar/iterations/iter-2026-09-bilibili-api-sqlite/specs/bilibili-api-gateway.md`
- Owner: fullstack-dev
- QA gate: mandatory

## Goal

Wrap the pinned `bilibili-api-python` package in a typed gateway that prevents
third-party response dictionaries from leaking into application code. Use the
gateway to collect one-page user-video results and persist normalized metadata
through the SQLite repository from Plan 1.

## Architecture

`BilibiliGateway` is the only application module that imports `bilibili_api`.
It converts package responses into validated internal DTOs. `MetadataIngestor`
owns pagination, cursor/run/page transactions, and repository calls; it never
stores the third-party response dictionary.

## Tech Stack

Python 3.12, `bilibili-api-python==17.4.2`, `uv.lock`, standard-library
`asyncio` and dataclasses, repository interfaces from
`20260909-structured-metadata-schema`, pytest and fake gateway fixtures.

## Global Constraints

- Use the user-supplied API documentation as the API reference:
  `https://nemo2011.github.io/bilibili-api/#/modules/user`.
- Pin `bilibili-api-python==17.4.2`; the gateway must expose the package version
  in run metadata without persisting credentials or raw response bodies.
- Only `sources/bilibili_api_gateway.py` imports `bilibili_api`; services import
  the application-owned protocol and DTOs.
- Use one bounded page per gateway call. The ingestor advances the SQLite cursor
  only after the page transaction commits.
- Map one-based upstream page values to zero-based `page_index`; compute
  `work_id` only at the application/view boundary.
- Do not call subtitle, playback, audio, ASR, or export APIs in this plan.
- Translate upstream failures into bounded scalar error codes; raw exception
  text, URLs, cookies, and response JSON remain process-local.
- Optional SESSDATA comes from `BILI_SESSDATA` or a CLI value and is never
  serialized, logged, or returned by the gateway.
- The gateway/ingestor updates current display labels only; it does not persist
  mutable metadata history or complete upstream response documents.
- No network calls occur in fake-gateway tests.

## Interfaces

- Consumes: `MetadataRepository` from Plan 1 and the package APIs
  `user.User.get_videos`, `video.Video.get_info`, and `video.Video.get_pages`.
- Produces: DTO protocol `BilibiliGateway`, concrete package adapter, and
  `MetadataIngestor.collect_user_pages(mid, start_page, page_limit)`.
- Produces: normalized user/video/part/discovery/run/page/cursor records for Plan 3.

## Tasks

### Task 1: Add the pinned dependency and typed gateway boundary

**Files:**
- Modify: `bilibili-asr-archive/pyproject.toml`
- Create: `bilibili-asr-archive/src/bili_asr/sources/__init__.py`
- Create: `bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py`
- Create: `bilibili-asr-archive/src/bili_asr/sources/models.py`
- Test: `bilibili-asr-archive/tests/test_bilibili_api_gateway.py`

**Interfaces:**
- Consumes: package objects and optional credential configuration.
- Produces: `UserVideoPage`, `VideoSummary`, `VideoPart`, `BilibiliGateway`,
  and bounded gateway exception classes.

- [x] Pin `bilibili-api-python==17.4.2` and generate/update `uv.lock` without
  changing unrelated runtime dependencies.
- [x] Implement credential construction without exposing SESSDATA to DTOs,
  logs, exception messages, or persistent records.
- [x] Implement `get_package_version()` returning the pinned package version string
  for run metadata.
- [x] Implement `get_user_video_page` using the documented `User.get_videos`
  page parameters and normalize required scalar fields. Return `observed_total`
  from the API response when present. Validate that all returned video `mid`
  values match the requested `mid`; reject with `GatewayShapeError` on mismatch.
- [x] Implement `get_video_parts` using `Video.get_pages`; convert one-based
  `page` to zero-based `page_index` using `page - 1`, and convert `duration`
  seconds to `duration_ms` using `floor(seconds * 1000)`. Use `get_info` only
  when the video summary lacks `aid`; do not call it speculatively.
- [x] Validate non-empty BVID/title, non-negative page index, positive CID and
  duration before returning DTOs.
- [x] Test DTO normalization, duration/page-index conversion, owner-MID validation,
  malformed responses, bounded error mapping, and import-boundary inspection with
  a fake package seam.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_bilibili_api_gateway.py -v`

### Task 2: Implement resumable normalized metadata ingestion

**Files:**
- Create: `bilibili-asr-archive/src/bili_asr/services/__init__.py`
- Create: `bilibili-asr-archive/src/bili_asr/services/metadata_ingest.py`
- Modify: `bilibili-asr-archive/src/bili_asr/storage/database.py`
- Test: `bilibili-asr-archive/tests/test_metadata_ingest.py`

**Interfaces:**
- Consumes: the gateway protocol and Plan 1 repository.
- Produces: run result with outcome, next cursor, and derived counts; all
  persisted data is normalized repository data.

- [x] Start an `ingestion_run` with requested bounds and package version.
- [x] For each page, fetch summaries, fetch parts, and persist user/video/part
  records plus discovery relationships in one transaction using the explicit
  ordering from Plan 1: (1) upsert user, (2) upsert video, (3) upsert parts,
  (4) insert discoveries, (5) update cursor on success only, (6) record page
  outcome, (7) commit atomically.
- [x] Make repeated pages idempotent for entity and discovery keys while keeping
  separate run/page evidence for each collection run. Entity upserts use
  `INSERT ... ON CONFLICT DO UPDATE` on primary/unique keys.
- [x] Persist `complete`, `limited`, `risk_interrupted`, or `failed` outcomes;
  never claim completion when an explicit page limit stops collection.
- [x] Preserve the previous cursor on gateway failure: rollback the entire page
  transaction and store only the scalar error code in a separate page/run
  outcome transaction.
- [x] Test one single-part video, one multipart video, duplicate page results,
  empty page completion, explicit page limit, transaction rollback on failure,
  and cursor preservation/resume behavior.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_metadata_ingest.py -v`

### Task 3: Verify third-party API behavior at the package seam

**Files:**
- Modify: `bilibili-asr-archive/tests/test_bilibili_api_gateway.py`
- Modify: `bilibili-asr-archive/tests/test_metadata_ingest.py`
- Create: `bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py`

**Interfaces:**
- Consumes: gateway and ingestor from Tasks 1–2.
- Produces: offline contract evidence and a documented live-smoke entry point
  for Plan 3.

- [x] Assert the adapter calls only the documented user/video metadata methods
  and never playback/subtitle methods.
- [x] Assert no persisted row or test output contains SESSDATA, signed URL text,
  raw JSON, or raw exception text.
- [x] Add a live smoke test that is opt-in, uses UID 23191782, requests one page,
  writes to a temporary database, and skips cleanly when live execution is not
  requested.
- [x] Record the live smoke command and bounded expectations for the CLI plan.

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

- [x] `bilibili-api-python==17.4.2` is pinned and `uv.lock` is reproducible.
- [x] Only `sources/bilibili_api_gateway.py` imports `bilibili_api`; all other
  modules consume application-owned DTOs and protocols.
- [x] DTOs validate required metadata fields (non-empty BVID/title, positive
  CID/duration) and reject malformed responses before returning.
- [x] Ingestion service writes normalized entities (user/video/part) and discovery
  relationships with idempotency: repeated pages update display labels without
  creating duplicate rows.
- [x] Cursor advances only after a successful page transaction commits; failed
  pages leave the prior cursor intact.
- [x] Bounded failure records contain scalar error codes only; no credentials,
  signed URLs, raw JSON, or stack traces are persisted.
- [x] Offline gateway and ingestor tests pass on Python 3.12 without network access.
- [x] Opt-in live smoke is bounded to one public metadata page for UID 23191782,
  writes to a temporary SQLite database, and calls no subtitle/playback/audio/ASR
  endpoints.
- [x] `git diff --check` is clean.

## Prepare → Execute Handoff

Prepare must lock the package version, gateway methods, DTO fields, error
mapping, page bound, credential boundary, and dependency on Plan 1. Execute
Task 1 before Task 2, then Task 3. After all tasks, produce the SDD review
package, mandatory QC tri-review, and QA gate before marking this plan Done.

## Review Gate Summary

- Decision: QC converged — Approve conditional on the mandatory QA gate closing the routed runtime evidence U1–U4 (initial tri: Unconfirmed/Request Changes/Approve → fix wave `3dcc51b` → targeted re-review N=2: seat 2 Approve with W resolved, seat 1 no open defects with stated no-objection)
- Review range / Diff basis: `e62280a..3dcc51b` (merge-base e62280a with spec integration branch; final reviewed head `3dcc51b`)
- Review bundle: `.mstar/sdd/20260909-bilibili-api-ingestion/review/`
- QC inputs: `qc1.md`, `qc2.md`, `qc3.md` (Revalidation in place), consolidated: `qc-consolidated.md`
- Blocking result: none unresolved in QC scope (W1 bvid boundary asymmetry fixed + seat-verified; routed runtime evidence U1–U4 → QA gate)
- Residual findings: none open (zero-residual; dangling-running windows accepted as bounded design limits; Batch-3 carries C1–C6 recorded in Durable Roadmap)

## QA Gate Summary

- QA gate: mandatory
- QA mode: acceptance
- Evidence: qa-engineer L4 gate **Approve (recommend merge)** at HEAD `3dcc51b`, range `e62280a..3dcc51b` — full report `.mstar/sdd/20260909-bilibili-api-ingestion/review/qa-gate.md`. U1 fresh re-runs match the post-fix baseline exactly (focused pair 131 passed + 1 skipped in 0.95s, skip = the opt-in live smoke; full suite 857 passed + 1 skipped in 41.64s; CPython 3.12.13; `git diff --check` clean). U2 fresh `uv lock --check` no-op (exit 0, resolved 98 packages; pin from PyPI per `uv.lock`). U3 live smoke executed opt-in (no credential, one page, UID 23191782, temporary SQLite): attempt + single mandated retry both ended in the designed bounded failure `response_error` — upstream reachable but rejects the anonymous metadata chain; bounded failure path verified live (atomic terminal run, one page-evidence row, scalar-only persistence, temp-root-only writes); happy-path collection not demonstrable from this environment, recorded as a Plan-3 operational note (SESSDATA support is Plan-3 CLI scope, C6). U4 wheel inspection confirms all fake-seam assumptions (inner-`data` return shape via `Api._check_response`, `get_pages`→`x/player/pagelist` with local `bvid2aid` and no internal `get_info`, `get_info`→`x/web-interface/view` with the S-fix-4 top-level-`bvid` anchor bounded as `shape_error` either way, exception/`Credential` signatures). Zero open residuals (zero-residual confirmed); plan-level Approve unblocked — PM owns the integration merge and the `Done` transition (plan not marked Done here).

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
