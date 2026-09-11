# Task 2 Review — Repository Transactions and Idempotent Upserts

- Reviewer: code-reviewer (L2, Mode A, diff-first, read-only)
- Plan: `20260909-structured-metadata-schema`
- Diff: `5f22fc6..bf602b8` (review package: `review/task-2-diff.md`)
- Files in diff: `src/bili_asr/storage/database.py` (modify), `src/bili_asr/storage/models.py` (create), `tests/test_metadata_repository.py` (create) — exactly the three briefed files, no piggyback changes.
- Inputs verified against: task-2 brief, plan Global Constraints, primary spec `structured-metadata-storage.md` (transaction order §"Transaction and integrity rules"), Task 1 schema (`schema.sql`), `open_database` config, existing `tests/conftest.py` (`tmp_root` fixture pre-exists and is reused).

## Spec Compliance

✅ **Spec compliant.**

- **Dataclasses with explicit fields and validation** — `models.py` defines frozen/slots dataclasses for `UserRecord`, `VideoRecord`, `VideoPartRecord`, `IngestionRunRecord`, `IngestionPageRecord`, `CursorRecord` (+ `DiscoveryRecord` for the relationship table, justified by `record_discovery` in the plan's Interfaces). Every record has `__post_init__` validation aligned with the schema CHECK constraints (mid ≥ 1, page_index ≥ 0, cid ≥ 1, duration_ms ≥ 1, enum membership for statuses/outcomes/states, timestamp ordering). `work_id` is a computed `@property` on `VideoPartRecord` (models.py:141-146) and is never written by any upsert; the test asserts it is absent from persisted fields (`test_models_validate_scalars_and_compute_work_id_without_persisting_it`).
- **Locked transaction order** — `record_page` payload path (database.py:379-391) executes exactly user → videos → parts → discoveries → cursor → page outcome → commit, matching spec §Transaction and integrity rules steps 1–7. FK parents are guaranteed before children; the cursor write sits inside the transaction so it survives only on success (verified behaviorally by the rollback test).
- **Idempotency** — entities upsert via `ON CONFLICT` on stable keys (`mid`, `bvid`, `(bvid, page_index)`); discoveries upsert via `ON CONFLICT(run_id, page_number, bvid)`; pages key on `(run_id, page_number)`, so a new run retains its own page/discovery evidence while repeating a page is idempotent. Tested in `test_repeated_page_is_idempotent_but_a_new_run_keeps_page_evidence` (row counts stay 1/1/1/1 in run-1, become 2 pages + 2 discoveries under run-2).
- **Bounded failure handling** — payload failure rolls back the whole transaction; when the page outcome is `failed`, `_record_failed_page` (database.py:402-413) writes the page row (error_code validated to a bounded scalar by the model, ≤64 chars, charset `^[A-Za-z0-9_.:-]+$`) plus run outcome/finished_at in a separate transaction. No exception text, JSON, URLs, or cookies can be persisted (charset rejects `=`, `{`, `/`, whitespace; the test asserts no `traceback` substring). Prior cursor preserved — confirmed by the ordering-sensitive rollback test.
- **Required tests all present** — single+multipart pages, repeated pages, cursor resume, failed-page rollback, missing FKs (orphan video, orphan part, missing run parent), FK delete restriction (`ON DELETE RESTRICT` via `schema.sql:18/34/51/63/76/86-87`), pending-part queries (with/without limit, status transition). 8 test functions in the new file; implementer reports `8 passed`, plus `16 passed` for Task 1+2 files and `709 passed` full suite.
- **Plan Interfaces honored** — all 11 required `MetadataRepository` methods exist; inputs are validated internal dataclasses/scalars only (no response dicts, no `bilibili_api` import, no network, no sidecar reads, no writes to reserved media tables).
- **Global constraints** — 3NF preserved (aggregates read from `v_ingestion_run_stats`/`v_pending_metadata`, never stored); display labels overwritten with no history (`upsert_user`, `upsert_video`, `upsert_part` update only label/operational fields, `created_at` never overwritten); writes are deterministic (all timestamps caller-supplied — no `datetime.now()` anywhere); surgical scope (only the three briefed files).

⚠️ **Cannot verify from diff (for PM to resolve, non-blocking):**
- Implementer test outputs (`8 passed`, `16 passed`, `709 passed`) and `git diff --check` cleanliness are implementer-reported evidence (TDD triple present in the report); not independently re-run per the diff-first/trust protocol. Static trace of all 8 tests against the schema found no doubt warranting a focused run.
- Parity of diff file ↔ worktree head `bf602b8` is taken from the review-package header (bound `mstar sdd review-package` flow).
- Plan-file Task 2 checkboxes remain unchecked — PM ledger action, not an implementer defect.

## Strengths

- The transaction ordering is not merely implemented but *proven* by a test where the FK failure occurs mid-order (parts after videos, before cursor), which is exactly the case that exercises both rollback and cursor preservation.
- Validation is defense-in-depth: model-level checks mirror schema CHECK constraints, and the bounded error-code policy is enforced twice (model charset/length + DB `length(...) <= 64`).
- Deterministic by design: caller-supplied timestamps mean every test is offline and repeatable, matching "All database writes are transactionally testable and deterministic."
- Reused the existing `tmp_root` fixture (conftest.py) instead of inventing a new fixture — correct Ladder discipline.
- `start_run`'s independent commit is a deliberate, inline-commented decision that keeps the run FK parent alive for post-rollback failure evidence (a naive "commit everything at the end" design would lose the failed-page record).

## Issues

### Critical

None.

### Important

None.

### Minor

1. **Class docstring over-claims commit behavior** — `database.py:98-107` states "The low-level methods execute SQL without committing so a caller can group them in one transaction," but `start_run` (database.py:255-257) and `finish_run` (database.py:312) commit unconditionally. Composing them inside `transaction()` (which the docstring invites) silently commits the enclosing transaction's earlier writes. Behavior is intentional and commented at the `start_run` site, but the class-level contract should name the two committing methods explicitly so the Batch 2 gateway doesn't compose them inside a page transaction.
2. **Speculative dual-form APIs (YAGNI / no-compat-layer rule)** — `finish_run` offers a "scalar compatibility form" (database.py:267-269) although no prior API exists to be compatible with; the docstring's "preferred form" (`finish_run(IngestionRunRecord(...))`) is the one *not* covered by tests (the scalar form is what `test_finish_run...` exercises). Similarly `record_page` accepts both `video=` and keyword-only `videos=` (database.py:340,345), and `upsert_part` carries an explicit-`video_part_id` insert branch (database.py:169-217, models.py:125) that no caller or test currently exercises. Harmless today, but the gateway plan will lock against this contract — pick one canonical form per method before Batch 2, or add a test if the extra form is intentionally kept.
3. **`_record_failed_page` can regress a terminal run outcome** — the failure-path `UPDATE ingestion_runs SET outcome='failed', finished_at=?` (database.py:406-412) is unguarded: a stale/late failed-page record can flip a `complete` run back to `failed` and move `finished_at` backwards, and it bypasses the `finished_at >= started_at` check that `finish_run` enforces (schema has no such CHECK). Unreachable in the designed gateway flow, but a one-line guard (`WHERE outcome = 'running'` or an outcome check) would make the failure path as disciplined as the success path.
4. **Constructor accepts connections the read paths can't serve** — `MetadataRepository.__init__` (database.py:109-112) accepts any `sqlite3.Connection`, but `read_cursor`/`run_stats`/`list_pending_parts` column-name indexing (`row["mid"]`, database.py:451-461) requires `row_factory = sqlite3.Row`, which only `open_database` sets. A bare `sqlite3.connect()` connection fails at read time with an opaque `TypeError`. Either set/assert the Row factory in `__init__` or document the requirement.
5. **models.py export/comment contradiction** — models.py:255 comments that validation helpers are "intentionally not part of the public model API," then immediately exports `validate_error_code` and `ALLOWED_*` sets in `__all__` (models.py:256-268). They are public by that export; reword the comment (or keep the helpers private and let Task 3 derive allowed sets from the `Literal` types).
6. **Untested subtle upsert branch** — `upsert_video`'s `aid = COALESCE(videos.aid, excluded.aid)` backfill (database.py:150) is only exercised with an identical aid; the preserve-existing-aid-when-new-differs case is unasserted. Suggested for the Task 3 contract tests (one re-ingest with `aid=None` after an aid-bearing insert).
7. **Failed page permits `error_code=None`** — the brief says "a failed page records a scalar error code," but `IngestionPageRecord` (models.py:190-198) accepts `outcome='failed'` with `error_code=None` (as do the DB CHECKs). Tightening the model (failed ⇒ non-null bounded code) or documenting that the gateway owns this invariant would close the small gap between brief text and contract.

## Assessment

**Task quality:** Approved

All five brief checkboxes and the applicable Global Constraints are satisfied with static-verifiable evidence; the seven Minor findings are non-blocking quality notes for PM disposition (zero-residual cleanup: report only — PM owns close/defer; items 1, 2, 5 are cheap pre-gateway contract polish, item 6 maps naturally to Task 3's contract tests).
