# Implementer Task 2 Report — Add offline metadata E2E verification

- **Plan**: `20260909-metadata-cli-smoke` (batch 3, task 2 of 3)
- **Status**: **DONE**
- **Branch / commit**: `feature/20260909-metadata-cli-smoke` @ `cf490ff` (task base SHA: `849c046`)
- **Executor**: fullstack-dev (leaf executor; no subagents dispatched; no harness artifacts written except this report)
- **Worktree**: `/root/workspace/bilibili-asr-archive/.worktrees/20260909-metadata-cli-smoke` (verified: branch matches assignment, tree clean at start, HEAD = Task-1's `849c046`)

## Implemented

All five brief checklist items, as offline end-to-end evidence in
`bilibili-asr-archive/tests/test_metadata_e2e.py` (3 tests). Every test drives
the real user-facing command path — `bili_asr.cli.main` with plain argv — over
the fake `bilibili_api` package seam (`bilibili_api_seam` fixture), so the full
stack runs offline: CLI composition root → real `BilibiliApiGateway` adapter →
`MetadataIngestor` → Plan-1 `MetadataRepository` → temporary SQLite database.
No ingestor internals are called directly; no `bilibili_api` import; no
network.

1. **Single-part + multipart scripted (brief item 1)** — one page holds
   `BV1SINGLEPT1` (1 part) and `BV1MULTIPRT2` (2 parts, one-based pages 1/2
   normalized to zero-based indexes and ms).
2. **Normalized rows + `work_id` views (brief item 2)** — test 1 asserts exact
   rows for all seven families (`bilibili_users`, `videos`, `video_parts`,
   `ingestion_discoveries`, `ingestion_runs`, `ingestion_pages`,
   `ingestion_cursors`) plus the computed `work_id` values and joined user/video
   context of `v_video_parts` and `v_pending_metadata`. Run row pins
   `mid`, `source_package`, `source_version="17.4.2"`, `requested_start_page`,
   `requested_page_limit=DEFAULT_PAGE_LIMIT`, `outcome`, `finished_at`.
   `status` and `runs` read commands close the loop over the same database
   (counts, processing summary, pending work_ids, cursor line, run line with
   `pages=2 videos=2`).
3. **Re-run same page → no duplicates (brief item 3)** — test 2: full natural
   completion, then `--start-page 1` re-collect. Entities keep single identity
   rows (1 user / 2 videos / 3 parts, same keys); discovery evidence compared as
   a set: exactly one row per `(run_id, page_number, bvid)` per run, and the
   second run re-records page 1 once per video (see Decision 1).
4. **Failed page → cursor preserved + bounded error → resume (brief item 4)** —
   test 3: `--limit-pages 1` leaves the cursor at page 2 (`limited`); upstream
   `-412` mapped to `rate_limited` exits 2; the cursor row is preserved
   byte-for-byte (all six columns incl. `updated_at`); only bounded evidence is
   stored (`ingestion_pages` row `(2, risk_interrupted, rate_limited)`, run
   outcome `risk_interrupted`); entity/discovery counts unchanged; then the
   upstream recovers and the next run resumes implicitly from the preserved
   cursor (`requested_start_page=2`), completes (`outcome=complete`), and the
   cursor advances to the completing empty page 3. `runs` renders all three
   outcomes plus `error=rate_limited`.
5. **No legacy files (brief item 5)** — all three tests assert that
   `manifest/manifest.jsonl`, `meta-cursor.json`, `run-ledger.jsonl` do not exist
   in the temporary root after `fetch-meta`.

**No-leak evidence (assignment requirement)** — all three tests scan CLI output
(`assert_leaks_no_markers`) and all three scan the full persisted-row blob
(`persisted_row_text`) for every seam sentinel (SESSDATA value, signed URL, raw
JSON body, raw upstream exception text). The scans are non-vacuous by
construction: test 1 scripts payload-laden upstream items (sentinel notes ride
the raw responses the adapter must strip) and passes the sentinel SESSDATA via
`--sessdata` (CLI renders only `sessdata: present`); a positive control asserts
a normalized video row really persisted. Test 3's scripted upstream failure
carries the raw-exception sentinel end to end. The documented-call allowlist
(`assert_only_documented_metadata_calls`) plus an exact upstream call-trace
assertion pin the bounded page/parts fetch behavior (no speculative detail
calls; resume refetches only the cursor page).

## Tests (TDD triple)

- **Test files**: `tests/test_metadata_e2e.py` (new), `tests/fixtures/fake_bilibili_gateway.py` (extended).
- **Focused command** (worktree has no `.venv`; control checkout interpreter per assignment):
  `cd bilibili-asr-archive && /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_metadata_e2e.py -v`
  → `3 passed in 0.34s` (all green; test 1 also exercises `status` + `runs`).
- **Fixture-consumer regression check**: `.../python -m pytest tests/test_bilibili_api_gateway.py tests/test_metadata_ingest.py tests/test_metadata_cli.py tests/test_metadata_repository.py -q`
  → `183 passed, 1 skipped` — the fixture extension breaks nothing.
- **Full offline suite**:
  `.../python -m pytest` → `857 passed, 1 skipped in 42.90s`
  (Task-1 baseline was `854 passed, 1 skipped`; +3 new E2E tests, same single
  opt-in live-smoke skip. Zero regressions.)
- **Red/green note**: this task delivers verification tests, not a bug fix, so
  the meaningful red/green signal is the first run: the initial run failed on
  **two test-authoring defects of mine** (discovery-row expectation ordered by
  `run_id`, which is unordered uuid hex; a run-row tuple slice that included
  `finished_at`). Fixed inside the test file only — every failure root-caused to
  the test code, never worked around in product or fixture. Final state green as
  above.

## Files changed

- **Created**: `bilibili-asr-archive/tests/test_metadata_e2e.py` (576 lines: module contract doc, 3 E2E tests, corpus scripting helper, deterministic clock fixture, DB read helpers).
- **Modified**: `bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py` (+30/−2: `script_parts_by_bvid`, callable `parts_response(bvid)` on the fake `Video.get_pages`, docstring + `__all__` updates).
- **Not changed**: product source (requirement met), `tests/test_metadata_ingest.py` (see Decision 2), `tests/test_metadata_cli.py` (not in the brief's file list), any harness artifact besides this report.

## Decisions and deviations for PM disposition

1. **Re-run idempotency semantics (asked, unresolved by interaction — subagent cannot prompt; decided per the locked schema).** The assignment's alternative reading ("re-run adds zero new discovery rows") is structurally impossible under the locked Plan-1 schema: `ingestion_discoveries` PK is `(run_id, page_number, bvid)` and discovery rows are run-scoped evidence by design. The E2E therefore pins **run-scoped uniqueness**: entities do not duplicate or grow, and each re-run records exactly one discovery row per distinct video for that run (never duplicating another run's rows). If PM intends cross-run discovery dedup, that is a Plan-1 schema change outside this task's STOP-boundary and must be re-planned.
2. **`tests/test_metadata_ingest.py` left unchanged.** The brief lists it as "Modify", but the assignment scopes that to "only where the brief requires, e.g. promoting a shared double into the fixture". The E2E drives the CLI at the package seam (as Task-1's tests do), so no double from the ingest tests needed promotion; the checklist's five items are all covered by the new file + the fixture extension. Adding an ingestor-level duplicate of the new per-bvid scripting would be redundant coverage (YAGNI). Flagging so QC knows the listed file is intentionally untouched.
3. **Fixture extension scope** — exactly one capability the E2E lacked: per-bvid parts scripting (`script_parts_by_bvid`; callable `parts_response(bvid)` on fake `Video.get_pages`), needed because one page holds two distinct videos whose parts differ (the static single-list seam could not express a multipart video alongside a single-part one). Additive only: plain values keep previous behavior; all Plan-1/2 tests pass unchanged.
4. **Deliberate test-local duplication** — `LEGACY_SIDECAR_PATHS`, `_ingest_clock`, `_newest_run_id`, `_cursor_row` mirror Task-1's local helpers in `tests/test_metadata_cli.py` rather than being imported/refactored, because that file is outside this task's allowed file list. If QC prefers a shared home, that is a small follow-up refactor touching Task-1's file (PM disposition).

## Naming analysis (naming-analyzer, run before introducing names)

New names and their justification (project conventions: UPPER_SNAKE constants, snake_case functions, `_`-prefixed test-locals, descriptive behavior-statement test names):

- `script_parts_by_bvid` (fixture) — "script parts keyed by bvid"; mirrors the fixture's `script_*` vocabulary and the assignment's brief language (`bvid` is the project's established term). Unambiguous.
- `test_fetch_meta_normalizes_single_part_and_multipart_videos_end_to_end` / `test_fetch_meta_rerun_of_same_page_stores_no_duplicate_rows` / `test_fetch_meta_failed_page_preserves_cursor_and_resume_succeeds` — each names the command, the scenario, and the pinned property; no abbreviations beyond the established `bvid`/`p0` terms; consistent with the existing test-suite naming style.
- `LEGACY_SIDECAR_PATHS`, `SINGLE_PART_BVID`, `MULTI_PART_BVID`, `RESUMED_BVID`, `_script_upstream`, `_newest_run_id`, `_cursor_row`, `_discovery_rows`, `_ingest_clock` — 见名之意：each name states exactly what it holds/does; `_script_upstream` matches Task-1's helper name with the explicitly-named `parts_by_bvid` parameter replacing the ambiguous `parts` list.

## Self-review notes

- `git diff --check` clean (both before commit and for `849c046..cf490ff`); working tree clean after commit.
- Surgical scope: only the two brief-listed files changed; no product source, no CLI behavior change, no plan/snapshot/compass edits; zero-residual (no new findings opened).
- STOP conditions checked: no product change was needed (the E2E gap was a test-fixture scripting capability, explicitly allowed to extend); no legacy sidecar is read or written anywhere in the exercised path (asserted); the failure scenario stays bounded (one page, temporary DB, exit 2 with unchanged cursor); no credentials/signed URLs/raw JSON/traces in any output, fixture, or persisted row (asserted); single executable, single metadata source of truth (`archive.db` only).
- Exit taxonomy exercised end to end: 0 (complete, and limited in test 3's setup run) and 2 (terminal gateway failure with unchanged cursor); usage errors (exit 1) remain pinned by Task-1's parser/config tests.
- Determinism: no network, no sleeps, scripted upstream; multi-run tests patch the ingestor clock for strictly increasing `started_at` so newest-run resolution and `runs` ordering are deterministic; sentinels are fake non-real values by design.
- Environment note: tests ran with the control checkout interpreter (`/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python`) because the feature worktree has no `.venv`, exactly as the assignment prescribed; `bilibili-api-python` is installed there at the pinned 17.4.2, so the asserted `source_version` literal is stable.
