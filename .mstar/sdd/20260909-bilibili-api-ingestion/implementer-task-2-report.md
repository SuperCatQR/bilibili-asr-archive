# Task 2 Implementation Report — Resumable Normalized Metadata Ingestion

- **Plan**: `20260909-bilibili-api-ingestion` (Batch 2, Task 2 of 3)
- **Executor**: fullstack-dev (leaf executor, no delegation)
- **Working branch**: `feature/20260909-bilibili-api-ingestion`
- **Commit**: `0c2c379` — `feat(services): add resumable normalized metadata ingestor`
- **Status**: **DONE**

## Implemented

`MetadataIngestor.collect_user_pages(mid, start_page=None, page_limit=None)` in
`bilibili-asr-archive/src/bili_asr/services/metadata_ingest.py`, plus the
`services` package (`__init__.py` re-exporting `MetadataIngestor` and
`IngestionRunResult`), and 17 offline contract tests in
`tests/test_metadata_ingest.py`.

Brief checklist, item by item:

- **Start an `ingestion_run` with requested bounds and package version** —
  the run row carries `source_version = gateway.get_package_version()`, the
  resolved `requested_start_page` (explicit argument, else stored cursor's
  `next_page`, else 1) and `requested_page_limit`. The user row is upserted
  first (its own transaction) because `ingestion_runs.mid` carries a foreign
  key into `bilibili_users` — same bootstrap order Plan 1's own tests use.
- **Per-page transaction in Plan 1's locked order** — each page is fetched
  through the typed `BilibiliGateway` protocol (summaries, then parts per
  distinct bvid) and persisted in exactly one committed transaction by the
  repository's canonical `record_page(page, user=, videos=, parts=,
  discoveries=, cursor=)`, which applies user → videos → parts → discoveries
  → cursor → page outcome → commit. The ingestor composes; it never opens a
  competing transaction.
- **Idempotent repeated pages** — entity upserts use the repository's
  `INSERT ... ON CONFLICT DO UPDATE` on primary/unique keys (users by mid,
  videos by bvid with first-non-None aid backfill, parts by (bvid,
  page_index)); discoveries upsert on (run_id, page_number, bvid). Each run
  writes its own run/page evidence rows (tested across two runs).
- **Outcomes `complete` / `limited` / `risk_interrupted` / `failed`** —
  `complete` only on an empty page; `limited` when the explicit page limit
  stops collection (cursor state `limited`, never claimed complete);
  `risk_interrupted` on `GatewayRateLimited` (bounded risk signal);
  `failed` on any other bounded gateway error. An empty page completes the
  run even when it happens to fall on the limit boundary, because nothing
  was cut short (pinned by a dedicated test).
- **Cursor preserved on gateway failure** — the failure occurs during the
  gateway fetches, before any page transaction opens, so no partial page
  write ever exists; the failure is then persisted as the no-payload
  `record_page(failed page record)` (scalar `error_code` only, run
  transitioned atomically by the repository's `_record_failed_page`), and
  the prior `CursorRecord` is untouched — asserted byte-for-byte via
  `CursorRecord` equality.
- **Required test cases** — one single-part video, one multipart video
  (zero-based indexes, millisecond durations preserved), duplicate page
  results (within-page duplicate summaries collapse to single entity rows
  and one discovery row, with one parts fetch per distinct video), empty
  page completion, explicit page limit, transaction rollback on failure,
  and cursor preservation/resume (a fresh run resumes from the stored
  cursor's `next_page` and completes).

## Adjudicated / design decisions (for reviewer attention)

1. **D3 invariant enforced ingestor-side** — `_completed_summary` rejects any
   summary whose `mid` differs from the requested user (`GatewayShapeError`,
   bounded code `shape_error`) *before* any parts request or detail fetch, so
   part requests only ever target videos whose ownership was proven against
   the requested user. Tests assert the negative shape: a foreign-owned
   summary fails the page with **zero** `get_video_parts` calls and **zero**
   completion calls.
2. **Missing `aid` is completed through the gateway** (spec: "The ingestion
   service decides when to call this method"): the ingestor calls
   `get_completed_video_summary` exactly when a summary lacks `aid` (D1:
   non-speculative by construction) and persists the completed value. Test
   asserts exactly one completion call for the aid-less summary and zero for
   summaries that already carry `aid`.
3. **`UserRecord.display_name = str(mid)`** — the Task-1 DTO contract
   (`UserVideoPage`/`VideoSummary`) carries no display-name field, so the
   ingestor's current label is the owner mid. The helper is one function; a
   future gateway method that exposes the name changes only it. The ingestor
   stays generic over mids (no hardcoded UP name).
4. **Failure outcome mapping** — `GatewayRateLimited` → page outcome
   `risk_interrupted` + run outcome `risk_interrupted`; every other bounded
   gateway error → page `failed` + run `failed`. The risk path persists page
   evidence via the no-payload `record_page` (page row only) and then finishes
   the run via `finish_run`; the `failed` path is fully atomic inside the
   repository's failure transaction. Non-gateway exceptions (e.g. a
   caller-argument `ValueError`) propagate unchanged — they are contract
   errors, not collection evidence.
5. **No cursor write on any gateway failure** — the brief says "preserve the
   previous cursor"; the cursor's position, state, `last_error_code` and
   `updated_at` are left exactly as the last successful page wrote them.
   Plan 1's `risk_interrupted` cursor state therefore remains unused by the
   ingestor (the run/page outcomes carry the bounded risk signal); flipping
   that is a one-branch change if PM wants the cursor to mark risk pauses.
6. **Count semantics** — `page_count` counts page-evidence rows written by
   the run (including interrupted/failed pages), matching
   `v_ingestion_run_stats.page_count`; `video_count` counts distinct bvids
   discovered, matching the view's `video_count`; `part_count` counts
   distinct `(bvid, page_index)` upserts (parts are not run-scoped, so no
   view equivalent exists).
7. **Sync facade over async gateway** — `collect_user_pages` is synchronous
   (matching the sync argparse CLI surface) and runs the async gateway page
   calls on one event loop per collection run; repository transactions
   execute inline between fetches. Nested-`asyncio.run` misuse fails loudly.

## Storage boundary (brief lists database.py as Modify)

**`src/bili_asr/storage/database.py` was NOT modified** (0-line diff against
Task-1 base). Every ingestor need composes existing canonical repository
methods: `transaction` + `upsert_user` (bootstrap), `start_run`,
`record_page` (payload, empty-with-cursor, and no-payload failure forms),
`finish_run`, `read_cursor`; `run_stats`/`list_pending_parts` for evidence.
No genuine gap exists, so per the assignment rule ("prefer composing
existing methods") the plan-1 transaction matrix, 3NF contract and bounded
codes stand unchanged.

## Tests

- **Focused command** (per brief):
  `cd bilibili-asr-archive && /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_metadata_ingest.py -v`
  → **17 passed** (16 functional + 8 validation params inside 2 test items).
- **Red/green evidence** — the first run with the initial implementation
  failed red: `11 failed, 5 passed` (missing `DiscoveryRecord` /
  `GatewayShapeError` imports, missing `_resume_page`/argument-validation
  helpers, plus two test bugs of mine: missing `mid` in validation kwargs,
  stale failure script). After fixing root causes: `16 passed`, then `17
  passed` after adding the empty-page-at-limit test.
- **Full offline suite before commit**:
  `/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest`
  → **840 passed in 41.62s** (823 baseline green + 17 new; includes Task 1's
  AST import-boundary tests, which scan the new `services` package too).
- **Neighbors** (`test_metadata_repository.py`, `test_bilibili_api_gateway.py`,
  `test_storage_schema.py`): 147 passed — plan-1 contract and gateway
  boundary unaffected.

## Files changed

- Create: `bilibili-asr-archive/src/bili_asr/services/__init__.py`
- Create: `bilibili-asr-archive/src/bili_asr/services/metadata_ingest.py`
- Test: `bilibili-asr-archive/tests/test_metadata_ingest.py`
- `bilibili-asr-archive/src/bili_asr/storage/database.py`: **unchanged**
  (deliberate; see storage boundary above)

## Self-review notes

- `git status` clean; `git diff --check` clean (no whitespace errors, no
  conflict markers).
- Import boundary holds: only `sources/bilibili_api_gateway.py` imports
  `bilibili_api`; `services` imports application-owned DTOs/protocol only
  (verified by grep and by Task 1's AST test in the green full suite).
- SESSDATA/credential boundary holds: no credential value enters the
  service, tests, records, or logs; failures persist bounded scalar codes
  only (`error.code` from the bounded taxonomy).
- No network, no `bilibili_api` import, no live call anywhere in the new
  tests; fake gateway doubles are local to `tests/test_metadata_ingest.py`
  (Task 3 owns the shared fixture file).
- Commit on the Working branch only; no push; no harness process artifacts
  touched except this report file.
- Known limits (documented, not blocking): a video deleted upstream between
  the page fetch and its parts/detail fetch fails its whole page (uniform
  bounded failure; the run stays resumable but would re-fail until upstream
  recovers or a later plan adds per-video degradation); two-transaction
  sequence for the `risk_interrupted` run finish (page row, then
  `finish_run`) — inherent to the plan-1 commit matrix, bounded window.
