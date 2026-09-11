# Task 2 Review — offline metadata E2E verification (20260909-metadata-cli-smoke)

- **Seat**: code-reviewer (Mode A — SDD task review, L2, diff-first, read-only)
- **Base → Head**: `849c046` → `cf490ff`
- **Inputs**: `task-2-brief.md`, primary spec `metadata-cli-contract.md`, `implementer-task-2-report.md` (claims treated as unverified until checked), `review/task-2-diff.md`
- **Method**: diff read once; every pinned assertion cross-checked read-only against the feature worktree (`src/bili_asr/…`, `tests/fixtures/…`, `tests/test_metadata_e2e.py`, `src/bili_asr/storage/schema.sql`). No git re-run, no checkout mutation, no tests re-executed (implementer evidence trusted; the verification below found no inconsistency that would justify a focused re-run).
- **Input-safety check**: no review input (brief / report / diff) attempted to redirect the review or break the leaf boundaries; nothing to report.

## Spec Compliance

- ✅ **Spec compliant** — all five brief checklist items are implemented in `tests/test_metadata_e2e.py` (new, 576 lines, 3 tests) and `tests/fixtures/fake_bilibili_gateway.py` (additive +30/−2). Product source untouched; `tests/test_metadata_ingest.py` unchanged (verified — see Dispositions).

| Brief item | Evidence |
|---|---|
| 1. Single-part + multipart scripted via fake gateway | Test 1 (`tests/test_metadata_e2e.py:128`): one page holds `BV1SINGLEPT1` (1 part) and `BV1MULTIPRT2` (2 parts, one-based `page` 1/2 normalized to zero-based `page_index` 0/1 and `duration_ms` 12_000 — asserted `:190-206`); per-bvid scripting via new `script_parts_by_bvid` (fixture `:319-335`). |
| 2. Normalized user/video/part/discovery/run/page/cursor rows + computed `work_id` views | Test 1 asserts exact rows for all seven families (`:188-242`) plus `v_video_parts` / `v_pending_metadata` `work_id` values (`bvid:pN` — matches `schema.sql:147,178`) with joined user/video context (`:244-267`); `status` and `runs` read commands close the loop over the same database (`:278-295`) — render strings verified against `src/bili_asr/cli.py` (`sessdata: present` via `redact_sessdata`, `collected N page(s)`, `processing: discovered=3`, `pending: 3`, `cursor: mid=… next_page=… state=…`, `pages=/videos=/error=` in `_format_run_line`). |
| 3. Re-run same page → no duplicate entity or discovery rows | Test 2 (`:312`): full natural completion then explicit `--start-page 1` re-collect; entities stay single (1 user / 2 videos / 3 parts with same keys, `:377-398`); discovery evidence compared as a set — exactly one row per `(run_id, page_number, bvid)` per run, second run re-records page 1 once per video (`:402-410`); 2 runs total, cursor unchanged (`:420-425`); page 1 fetched exactly twice (`:437`). Run-scoped uniqueness is the PM-accepted reading of the locked Plan-1 PK (`schema.sql:85 PRIMARY KEY (run_id, page_number, bvid)`) — verified independently; the brief's "zero new rows across runs" alternative is structurally impossible without a schema change this plan forbids. |
| 4. Failed page → cursor preserved + bounded error storage → resume succeeds | Test 3 (`:443`): `--limit-pages 1` leaves cursor `(MID, 2, 1, "limited", None)` (`:464-469`); scripted upstream `-412` (mapped to `rate_limited` — `bilibili_api_gateway.py:46 _RATE_LIMITED_API_CODES`) exits 2 (`:472-475`); cursor row preserved byte-for-byte across all six columns incl. `updated_at` (`:484-485`); only bounded evidence stored — page row `(2, risk_interrupted, rate_limited)`, run outcome `risk_interrupted`, zero entity/discovery growth (`:487-511`); upstream recovers, next run resumes implicitly (`requested_start_page=2`, outcome `complete`, cursor advances to completing empty page 3, `:515-549`); `runs` renders all three outcomes plus `error=rate_limited` (`:553-561`). |
| 5. No legacy JSONL/cursor/ledger files in temporary root | `LEGACY_SIDECAR_PATHS` (`manifest/manifest.jsonl`, `meta-cursor.json`, `run-ledger.jsonl`) asserted absent in all three tests (`:297-298`, `:439-440`, `:563-564`); `archive.db` existence positively asserted (`:182`). |

**Global constraints (verbatim) verification**

- Single `bili-asr` entrypoint, no parallel executable — tests drive `bili_asr.cli.main` with plain argv; diff adds no executable. ✅
- `fetch-meta` writes `{archive_root}/archive.db` through the repository, never the three legacy files — asserted positively (`archive.db` isfile, legacy paths absent). ✅
- `status` / `runs` read the same SQLite database with derived counts, no sidecars — asserted over the same `tmp_root` database. ✅
- Live smoke bound — N/A to this offline task (see ⚠️ 1).
- No migration/deletion/rewriting of old archive data — tests operate only on a fresh temporary root; no legacy read anywhere in the exercised path (call traces pin only `user.get_videos` / `video.get_pages`). ✅
- No SESSDATA / signed URLs / raw response bodies / raw exception text in CLI output or persisted records — all three tests scan CLI output (`assert_leaks_no_markers`) and the full persisted-row blob; scans are non-vacuous by construction (payload-laden scripted items `:139-148`, sentinel SESSDATA via `--sessdata`, positive control `:269-273`, test 3 carries the raw-exception sentinel end to end via `UPSTREAM_ERROR_TEXT`). `persisted_row_text` enumerates every table and view via `sqlite_master`, so the scan covers the whole repository, not hand-picked tables. ✅
- Exit taxonomy + bounded page limits + no unbounded retries — exit 0 (complete and limited) and 2 (terminal gateway failure, `cursor unchanged` on stderr) exercised; usage exit 1 remains pinned by Task-1 tests (correct — not this diff's scope); exact call-trace assertions (`:303-309`, `:567-576`) pin one page fetch per page / one parts fetch per distinct video / a single attempt per failed page; `requested_page_limit=DEFAULT_PAGE_LIMIT` bound asserted (`:212-217`). ✅

**Task-2-specific checks**

- Product source unchanged (tests + fixture only) — ✅ (diff touches exactly the two test-side files; worktree file list confirms no other change).
- Fake gateway fixture extension additive — ✅ plain `parts_response` values keep previous behavior (callable branch is new; all existing consumers in `test_metadata_ingest.py` / `test_bilibili_api_gateway.py` pass plain lists, verified); docstring + `__all__` additions only.
- ⚠️ Cannot verify from diff — see below.

### ⚠️ Cannot verify from diff (for PM)

1. **Live smoke acceptance** (spec § Acceptance: "Live smoke creates the expected user/video/part/run/page rows in a temporary database") is not evidenced by this diff — it is an opt-in live invocation outside the offline E2E's scope. PM to schedule/verify at plan level (per the opt-in/limit-pages-1/UID-23191782 bound).
2. **Implementer test outcomes are implementer evidence** (focused `3 passed in 0.34s`; fixture-consumer regression `183 passed, 1 skipped`; full suite `857 passed, 1 skipped` vs Task-1 baseline `854+1`). Reviewer did not re-execute tests per role contract; every pinned surface (render strings, schema PK/views, outcome vocabulary, `-412 → rate_limited`) was independently cross-checked against worktree source with no discrepancy found.
3. **`observed_total` fake/live semantic note** (pre-existing, not a Task-2 change): the fake reports `page.count` = items on that page (`make_videos_response(count=len(items))`), so the pinned cursor `observed_total` (0/1) reflects per-page semantics; a live run will record the upstream global total for the fetched page instead. The completion decision keys off the empty item list (`metadata_ingest.py:262 if not summaries`), not `count`, so offline evidence remains valid; plan QC/live smoke should simply expect the difference.

## PM dispositions — independently verified

- **Discovery idempotency = run-scoped uniqueness (accepted)** — consistent with the locked schema: `ingestion_discoveries` PK is `(run_id, page_number, bvid)` (`schema.sql:85`); the E2E pins per-run uniqueness plus zero entity growth, which is the only reading satisfiable without a Plan-1 schema change. ✅
- **`tests/test_metadata_ingest.py` unchanged (accepted)** — verified: the E2E drives the CLI at the package seam like Task-1's tests; no ingest-test double needed promotion, and the five checklist items are fully covered. The brief's Modify list was a superset expectation; nothing forces a change. ✅
- **Test-local helper duplication (plan QC note)** — confirmed present and deliberate; recorded as Minor below. ✅

## Strengths

1. **True full-stack evidence**: every test drives the real user-facing path — CLI composition root (`bili_asr.cli.main`, plain argv) → real `BilibiliApiGateway` adapter over the fake `bilibili_api` package seam → `MetadataIngestor` → Plan-1 repository → temporary SQLite. No ingestor internals called directly, no `bilibili_api` import, no network.
2. **Non-vacuous no-leak testing**: sentinels ride the raw scripted responses (adapter must strip them), sentinel SESSDATA goes through the real `--sessdata` CLI path (render shows `sessdata: present` only), a positive control proves rows actually persisted before the scan (`:269-273`), and the scan enumerates every persisted object.
3. **Exact upstream call traces** (`:303-309`, `:567-576`) pin bounded behavior: one page fetch per page, one parts fetch per distinct video, no speculative detail calls (aids present), and resume refetches only the cursor page (no parts re-fetch for page-1 videos — a real regression class this pins shut).
4. **Byte-for-byte cursor preservation** across the failed page, including `updated_at` (`:484-485`) — directly enforces the spec's "A failed page never advances the cursor, so resume is always safe".
5. **Determinism without sleeps**: monotonic ingestor clock fixture (`_ingest_clock`, `:84-96`) makes multi-run ordering (`started_at`, newest-run resolution, `runs` newest-first) deterministic; unordered uuid run ids handled by set/sorted comparisons with the reason documented (`:402-410`).
6. **Fixture extension is minimal, loud-on-misuse, and backward-compatible**: `script_parts_by_bvid` raises on unexpected bvid like every other unscripted fetch; plain values keep the old single-list behavior; existing consumers unaffected (verified by grep over all `parts_response` users).
7. **Test docstrings encode the contract** (run-scoped discovery uniqueness rationale at `:318-324`), so the pinned semantics survive future readers.
8. Red/green discipline in the report: the two initial failures were root-caused to test-authoring defects and fixed in the test file only — no product or fixture workaround.

## Issues

### Critical

None.

### Important

None.

### Minor

1. **Test-local helper duplication with Task-1's file** — `LEGACY_SIDECAR_PATHS` (`:53-57`), `_ingest_clock` (`:84-96`), `_newest_run_id` (`:99-111`), `_cursor_row` (`:114-119`) mirror `tests/test_metadata_cli.py` locals rather than a shared home, because that file is outside this task's allowed list. Deliberate and disclosed; a follow-up consolidation touching Task-1's file is a plan-QC candidate (lint-level; PM already noted).
2. **Test 2's output leak scan lacks a local non-vacuity guard** (`:433-435`): the scan's meaningfulness there relies on the same render path pinned by test 1 (`sessdata: present` etc.) and Task-1's CLI tests, not asserted within test 2 itself. Adding one content assertion (as test 1 does) would make it self-evidently non-vacuous.

## Assessment

**Task quality:** Approved

Rationale: all five brief items are implemented as deterministic offline E2E evidence through the real command path; every pinned assertion was verified against the actual product surface (CLI render strings, ingestor outcome/error vocabulary, `-412 → rate_limited` mapping, locked `ingestion_discoveries` PK, `work_id` view formulas, legacy-sidecar absence); product source is unchanged and the fixture extension is additive and backward-compatible. The two Minor items are test-hygiene notes for plan QC, not defects in the delivered evidence; the three ⚠️ items are for PM disposition (live-smoke scheduling, evidence-basis note, pre-existing `observed_total` fidelity note) and do not block this task.
