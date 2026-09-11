# Implementer Report — Task 3: Validate schema and repository against the contract

## Status

DONE

- Plan: `20260909-structured-metadata-schema` (Batch 1, final task)
- Working branch: `feature/20260909-structured-metadata-schema` (feature worktree `/root/workspace/bilibili-asr-archive/.worktrees/20260909-structured-metadata-schema`)
- BASE SHA: `bf602b8` → HEAD after commit: `ff81140`
- Commit: `ff81140 test(storage): validate schema and repository against contract`
- Delegation: none used (leaf executor; all work done in-session). No questions were needed — the brief and plan were verbatim-complete, so none were raised.

## Implemented

All five brief bullets, tests-only (no product source touched):

1. **Schema inspection test** (`tests/test_storage_schema.py::test_schema_inspection_matches_the_declared_contract`) — metadata-driven contract check on a fresh database:
   - exact table/view set equality (`BASE_TABLES | VIEWS` — no extra objects);
   - per-table exact ordered column manifests (`EXPECTED_TABLE_COLUMNS`) and explicit `work_id` absence per base table;
   - per-table FK pairs asserted exactly (`EXPECTED_FOREIGN_KEYS`) with every FK `on_delete == "RESTRICT"` (parent tables without FKs asserted empty);
   - unique constraints asserted exactly via `PRAGMA index_list`/`index_info` (`origin='u'`: `videos.aid`, `(bvid, page_index)`, `audio_objects.sha256`+`storage_key`, `(model_name, revision)`, `(video_part_id, source_kind, version)`);
   - composite primary keys asserted via `origin='pk'` indexes (videos, runs, pages, discoveries, part_audio_objects, transcript_segments);
   - status CHECK enumerations asserted in normalized DDL (`EXPECTED_CHECK_ENUMERATIONS`: processing_status, run outcome + source_package, cursor state, page outcome, transcript source_kind);
   - `work_id` expression `vp.bvid || ':p' || vp.page_index AS work_id` asserted present in `v_video_parts` and `v_pending_metadata` DDL.

2. **View derivation test** (`test_views_compute_derived_values_across_users_videos_and_runs`) — two users, three videos, parts in all three statuses, two runs (one empty):
   - `v_video_parts` computes `work_id` and joins the correct user/video per row (join through `videos.mid` proven by differing user names — owner name never stored on parts);
   - `v_ingestion_run_stats`: run-1 = 3 discovery rows → `(page_count=2, video_count=2)` proving `COUNT(DISTINCT)` dedup; run-2 = `(0, 0)` via LEFT JOIN;
   - `v_pending_metadata` returns only `discovered` parts (`metadata_collected` and `gone` excluded).

3. **Repository E2E test** (`test_repository_end_to_end_records_two_runs_with_cursor_transitions`) — one user, one single-part video, one multipart video (2 parts), two runs, three page records, cursor transitions `NULL → next_page=2 → 3 → complete`, both runs finished `complete`; asserts parent-before-child ordering via one `record_page` call with full payload (user → videos → parts → discoveries → cursor → page outcome), exact persisted page rows, pending order, derived run stats, and `PRAGMA foreign_key_check` empty.

4. **FK constraint tests** — repository-level: video without user, **part without video**, **cursor without user** (both added to `test_fk_rejection_and_delete_restriction_apply_to_repository_writes`); `ON DELETE RESTRICT` orphaning prevention for users/videos (pre-existing, kept); schema-level additions to the Task 1 orphan test: `ingestion_pages` row without its run, `ingestion_discoveries` row without its run, and discovery row with existing run but unknown `bvid`.

5. **No-secret persistence test** (`test_error_fields_persist_only_bounded_scalar_codes`) — bounded scalar codes (`rate_limited`, `http_412`) persist verbatim and round-trip through `read_cursor`/SQL; five forbidden fields (cookie string `SESSDATA=…; bili_jct=…`, signed URL `https://…?token`, raw JSON document, traceback text, 65-char over-length) are rejected with `ValueError` at the record boundary; database sweep proves error columns contain no `SESSDATA`/`bili_jct`/`https`/`{`/`Traceback`/whitespace markers and every persisted code is ≤ 64 chars matching `^[A-Za-z0-9_.:-]+$`.

6. **Single deterministic record factory** (`tests/fixtures/metadata_records.py`) — seven builders (`make_user_record`, `make_video_record`, `make_part_record`, `make_run_record`, `make_page_record`, `make_cursor_record`, `make_discovery_record`) returning validated frozen dataclasses from fixed literal timeline values; keyword overrides only, no wall-clock/random/network/credential input. `test_metadata_repository.py` now consumes it as its only record source (local `_user/_video/...` helpers removed); `test_storage_schema.py` keeps its raw-SQL seeding style (schema-level testing, no record factory needed).

7. Also asserted the 64-character error-code length bound at the schema level (cursor + page columns), and — per the Task 2 reviewer's plan-QC note — the previously untested `aid` COALESCE branch: `test_re_upsert_backfills_missing_aid_and_keeps_existing_aid` (None → backfilled to 1001; existing aid survives a later differing aid).

## Attempted / not done

- Nothing from the brief was skipped. No product source changes were needed — every contract point was evidenceable through tests alone, so no STOP/BLOCKED condition was hit.

## Tests

Focused command (worktree had no local `.venv`, so the control checkout's interpreter is used, as in Tasks 1–2):

```
cd bilibili-asr-archive && \
  /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest \
  tests/test_storage_schema.py tests/test_metadata_repository.py -v
```

- Baseline before changes: `16 passed in 0.70s` (Task 1: 8 schema tests, Task 2: 8 repository tests).
- After changes: `21 passed in 0.56s` (10 schema + 11 repository). Verbose run shows every test name PASSED; see "Red/green" below.
- Full offline suite from `bilibili-asr-archive/`: `714 passed in 40.23s` (previous 709 + 5 net-new tests), zero failures.

Red/green evidence (test-level TDD triple; no product bug fix was involved — this is a tests-only task, so there is no product red→green):

- Red: first run of the new tests → `2 failed, 16 passed`:
  1. `test_repository_end_to_end_records_two_runs_with_cursor_transitions` — `sqlite3.IntegrityError: FOREIGN KEY constraint failed`: E2E initially opened run-1's page without the run/user rows existing first. Fixed by using the file's `_start_run` helper (upsert user → start run) before `record_page`, matching the contract that runs are opened before pages and users before runs.
  2. `test_error_fields_persist_only_bounded_scalar_codes` — leak marker `http` also matched the legitimate bounded code `http_412`. Fixed by using URL-shaped markers (`https`) so the marker cannot flag a valid scalar code.
- Green: re-run → `21 passed`.
- Interim self-check that caught an implementation slip: the first full rewrite of `test_metadata_repository.py` collected only 18 tests (3 pre-existing Task 2 tests accidentally omitted). Detected by count comparison against expected 11 repository tests, restored verbatim, verified 21 collected. Final committed state contains all 16 pre-existing tests plus 5 new ones.

## Files changed

- `bilibili-asr-archive/tests/test_metadata_repository.py` — modified (factory imports replace local helpers; +E2E, +no-secret, +aid-backfill tests; FK test extended; all 8 pre-existing tests preserved)
- `bilibili-asr-archive/tests/test_storage_schema.py` — modified (additions only: contract-constant block, inspection test, view-derivation test, pages/discoveries FK cases, error-code length checks; all 8 pre-existing tests preserved)
- `bilibili-asr-archive/tests/fixtures/__init__.py` — created
- `bilibili-asr-archive/tests/fixtures/metadata_records.py` — created

Product source (`schema.sql`, `database.py`, `models.py`) untouched, as required.

## Self-review notes

- `git diff --check` clean (no whitespace/conflict markers), pre- and post-commit.
- Offline discipline: no network, no `bilibili_api`/`requests` imports, no credentials or cookie material in fixtures/assertions (cookie strings appear only as negative-case inputs rejected by the record boundary), no live HTTP, no model weights, no legacy JSONL artifacts read or written.
- Naming: all new names reviewed via `naming-analyzer` before introduction (builders `make_*_record`, `EXPECTED_*` contract constants; test names describe verified behavior).
- Contract clarifications recorded for Batch 2 (gateway) consumers:
  1. The schema enforces only the 64-character length bound on `error_code`/`last_error_code`; the bounded scalar-code *shape* (`^[A-Za-z0-9_.:-]+$`, no secrets/whitespace) is enforced at the record boundary (`models._error_code`), which is the repository's only accepted input type. Raw SQL bypassing records can persist arbitrary ≤64-char text — the contract boundary is the repository, not the column CHECK.
  2. `error_code=None` on a failed page is contract-conformant (spec declares `error_code` nullable); the Task 2 review's "looser than brief" note is resolved as spec-intended, not a gap.
  3. A no-payload `record_page` with `outcome='failed'` also marks the run failed/finished (Task 2 behavior); the E2E/no-secret tests observe this without asserting beyond the brief's scope.
- Red/green honesty: the two red failures above were test-authoring defects (missing run setup, marker collision), not product defects; both were fixed in the tests and re-verified. The dropped-tests slip was caught by collected-count comparison before commit.
- Zero-residual: only the four product test files above changed; worktree is clean; no stray artifacts (`.test-tmp` self-cleans via fixture, `.pytest_cache` is gitignored).
