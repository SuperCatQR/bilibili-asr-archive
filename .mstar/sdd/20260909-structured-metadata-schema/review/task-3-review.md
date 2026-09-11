# Task 3 Review — Validate schema and repository against the contract

- **Reviewer**: code-reviewer (Mode A, L2, diff-first; read-only)
- **Base** `bf602b8620e8dc4cc630ababf17bfb10e0ade1b0` → **Head** `ff81140`; diff: `.mstar/sdd/20260909-structured-metadata-schema/review/task-3-diff.md`
- **Inputs checked**: `task-3-brief.md`, `implementer-task-3-report.md` (claims treated as unverified until checked), `task-3-diff.md`; final state cross-checked read-only in the feature worktree (`tests/test_storage_schema.py`, `tests/test_metadata_repository.py`, `tests/fixtures/metadata_records.py` via diff, `src/bili_asr/storage/schema.sql`).
- **Tally**: 0 Critical / 0 Important / 4 Minor. **Verdict: Approved.**

## Spec Compliance

- ✅ **Spec compliant** — all five brief bullets delivered; diff is tests + fixture only (zero product-source change).

Bullet-by-bullet against the brief and the plan's task-3 checks:

1. **Schema inspection test** — `test_schema_inspection_matches_the_declared_contract` (`tests/test_storage_schema.py:442-498`, worktree final state):
   - exact table/view set equality vs `BASE_TABLES | VIEWS` (line 445 — no extra objects);
   - exact ordered column manifests per base table + explicit `work_id` absence (447-452);
   - FK pair-set equality per table and every FK `on_delete == "RESTRICT"` (454-460; parent tables without FKs asserted empty via `.get(table, ())`);
   - unique constraints asserted exactly via `PRAGMA index_list`/`index_info` `origin='u'` (462-475): `videos.aid`, `(bvid, page_index)`, `audio_objects.sha256` + `storage_key`, `(model_name, revision)`, `(video_part_id, source_kind, version)`;
   - composite PK indexes via `origin='pk'` (470-478);
   - status CHECK enumerations asserted in normalized DDL (480-487): processing_status, run outcome + source_package, cursor state, page outcome, transcript source_kind;
   - `work_id` expression `vp.bvid || ':p' || vp.page_index AS work_id` asserted present in `v_video_parts` and `v_pending_metadata` DDL (489-496).
2. **Three views compute derived values correctly** — `test_views_compute_derived_values_across_users_videos_and_runs` (`tests/test_storage_schema.py:501-576`): two users, three videos, parts in all three statuses, two runs (one empty). `v_video_parts`: `work_id` computed and correct user/video joined per row — `user_name` proven to route through `videos.mid` (two differing user names), i.e. owner name is not stored on parts (3NF evidence). `v_ingestion_run_stats`: run-1 has 3 discovery rows over 2 distinct videos → `(2, 2)` proving `COUNT(DISTINCT)` dedup; run-2 → `(0, 0)` proving LEFT-JOIN zeros. `v_pending_metadata`: only `discovered` parts returned (`metadata_collected` and `gone` excluded).
3. **Repository E2E** — `test_repository_end_to_end_records_two_runs_with_cursor_transitions` (`tests/test_metadata_repository.py:208-303`): one user, one single-part video, one multipart video (2 parts), two runs, three page records; cursor transitions `None → next_page=2 → 3 → complete` (213, 227, 252, 264-267, 284-286) with both runs finished `complete` (269-270). Locked order exercised via one `record_page` call per page with the full payload (user → videos → parts → discoveries → cursor → page outcome; documented at 217-218); asserts exact persisted page rows (279-283), pending order, derived run stats (`(1,1)` / `(2,1)`), and `PRAGMA foreign_key_check` empty (301).
4. **FK constraint tests** — repository-level (`tests/test_metadata_repository.py:181-205`): video-without-user (pre-existing, kept), **part-without-video** (188-190), cursor-without-user (191-193); `ON DELETE RESTRICT` blocks deleting the referenced user and video (200-203). Schema-level additions to the Task 1 orphan test (`tests/test_storage_schema.py:242-289`): `ingestion_pages` row without its run (260-263), `ingestion_discoveries` row without its run (264-268), discovery with existing run but unknown `bvid` (275-279); RESTRICT asserted over every base-table FK (285-287).
5. **No-secret persistence** — `test_error_fields_persist_only_bounded_scalar_codes` (`tests/test_metadata_repository.py:306-366`): bounded scalar codes (`rate_limited`, `http_412`) persist verbatim and round-trip through `read_cursor`/SQL (313-331); five forbidden fields — cookie material (`SESSDATA=…; bili_jct=…`), signed URL, raw JSON document, traceback text, 65-char over-length — rejected with `ValueError` at the record boundary (332-343); DB sweep proves error columns contain no secret/URL/JSON/traceback/whitespace markers and every persisted value is ≤ 64 chars matching `^[A-Za-z0-9_.:-]+$` (349-364).
6. **Offline / independent of `bilibili_api`** — final imports are `sqlite3`, `re`, `pytest`, `bili_asr.storage.*`, `fixtures.metadata_records` only; no network, no wall-clock/random input, no credentials in fixtures (cookie strings exist only as rejected negative-case inputs, never persisted).

Global-constraint spot checks:

- `PRAGMA foreign_keys = ON` asserted: `test_fresh_database_initializes_archive_root_and_is_idempotent` asserts it on the fresh connection and after reopen (`tests/test_storage_schema.py:214`, `226`) — Task 1 pre-existing test, preserved intact by this diff.
- 3NF: `work_id` absence asserted per base table (452); pre-existing test also asserts `part_count`/`video_count`/`run_count` absence and that derived values live in views; idempotent display-label overwrite preserved (`tests/test_metadata_repository.py:88-131`).
- Audio/transcript tables remain schema reservations only — column manifests asserted, no media/ASR behavior added.
- Task scope: diff touches only `tests/test_metadata_repository.py`, `tests/test_storage_schema.py`, `tests/fixtures/metadata_records.py` (new), `tests/fixtures/__init__.py` (new). **No product source changed** ✓.

Pre-existing-test preservation verified: final files contain all 8 Task 1 schema tests and all 8 Task 2 repository tests verbatim; totals 10 schema + 11 repository match the report's "21 passed" claim. The implementer's interim "dropped-tests" slip was caught and fixed before commit; the committed state is complete.

- ⚠️ **Cannot verify from diff** (for PM/QA to resolve):
  1. Runtime pass counts (focused `21 passed in 0.56s`, full offline suite `714 passed in 40.23s`) are implementer-reported evidence, not re-executed by this review (L2 contract: trust implementer evidence; no full-suite re-run). QA gate should confirm.
  2. **Contract boundary for Batch 2**: the schema enforces only the 64-char length bound on `error_code`/`last_error_code` (`src/bili_asr/storage/schema.sql:61`, `72` — `CHECK (… IS NULL OR length(…) <= 64)`, no shape CHECK). The bounded scalar-code *shape* (`^[A-Za-z0-9_.:-]+$`, no secrets/whitespace) is enforced at the record boundary (`models._error_code`) — i.e. **the repository, not the column CHECK, is the secret-prevention boundary**; raw SQL bypassing records can persist arbitrary ≤ 64-char text. The implementer documented this as a Batch 2 clarification and it matches the plan's contract (repository is the only accepted input path); plan QC should carry it to the gateway/CLI plans.
  3. Environment note: the feature worktree has no local `.venv` (verified), so the brief's run command as written cannot execute there; the implementer used the control checkout's `.venv` interpreter (disclosed in the report). QA re-runs should use the same interpreter pattern.
  4. `from fixtures.metadata_records import …` relies on pytest's default prepend import mode inserting `tests/` into `sys.path`. Works under the documented run command; revisit if the project ever changes `--import-mode`.

## Strengths

- **Metadata-driven contract test**: exact-set assertions for tables, ordered columns, FK pairs, unique/PK indexes, and CHECK fragments make every schema deviation a named, self-explanatory failure — precisely the "deterministic contract evidence for the gateway and CLI plans" the brief demands.
- **Honest red/green**: the two red failures were test-authoring defects (missing run/user setup; an `http` leak marker that collided with the valid code `http_412`) — fixed in the tests, not papered over. The `https` marker fix shows the forbidden-marker set was chosen so it cannot flag a legitimate scalar code.
- **Deterministic single record factory**: keyword-only overrides over fixed literal timeline values, no wall-clock/random/network/credential input; adopted as the only record source by the repository tests, deleting ~120 lines of duplicated builders while preserving every pre-existing assertion verbatim.
- **The extra `aid` COALESCE test** (`tests/test_metadata_repository.py:369-383`) closes the exact gap the Task 2 reviewer noted (None → backfill to 1001; existing aid survives a later differing aid) — small, disclosed, tests-only.
- **Self-review notes are candid and useful**: the schema-length-vs-record-shape boundary clarification and the `error_code=None`-on-failed-page resolution are exactly what the gateway plan needs next; the collected-count check (18 → 21) is a good anti-regression habit worth repeating.
- View-derivation test asserts owner names arrive via the join (two distinct users), directly evidencing the "no owner names in video/part rows" 3NF constraint.

## Issues

### Critical

None.

### Important

None.

### Minor

1. `tests/fixtures/__init__.py` is an extra file beyond the brief's explicit file list (brief lists only `metadata_records.py`). Justified: the pre-existing `tests/fixtures/` directory (already holding `advisories-empty.json`) is turned into a regular importable package so `from fixtures.metadata_records import …` resolves deterministically. Tests-only; no impact on existing data usage. PM: accept as-is (or note for future brief precision).
2. Redundant defense layer in the no-secret test (`tests/test_metadata_repository.py:349-364`): the LIKE-marker sweep over error columns duplicates what the exact non-null value-equality assertions directly below (361) already prove. Harmless defense-in-depth; trim if the test grows.
3. `make_part_record(status=…)` parameter name diverges from the field name `processing_status` (inherited from the removed `_part` helper). Cosmetic; call sites remain readable.
4. The CHECK-enumeration assertions match normalized DDL text (`tests/test_storage_schema.py:480-487`), so they are formatting/wording-sensitive by design: a schema reformat or reworded CHECK requires updating `EXPECTED_CHECK_ENUMERATIONS`. Acceptable for a contract test — a known maintenance trade-off, not a defect.

## Assessment

**Task quality:** Approved

All five brief bullets and the plan's task-3 checks are evidenced in the diff; scope is exactly tests + fixture with zero product-source change; all 16 pre-existing tests preserved; offline discipline holds. Runtime pass counts remain implementer-reported (⚠️ 1), and the record-boundary-vs-column-CHECK nuance (⚠️ item 2) should ride to plan QC and the Batch 2 gateway plan.
