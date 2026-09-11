# QA Gate Report (L4, mandatory, acceptance-only) — 20260909-structured-metadata-schema

- Iteration: `iter-2026-09-bilibili-api-sqlite` · Plan: `20260909-structured-metadata-schema` (SDD, Batch 1)
- QA mode: `acceptance-only` (evidence reuse first; targeted re-runs for the QC-routed gaps U1–U3)
- QA owner: `qa-engineer` (leaf executor; delegation: none used)
- **Verdict: Approve (recommend merge).** Plan NOT marked Done — integration merge precedes Done; PM owns the merge.

## Scope tested

The cumulative plan branch `c98f140..2063a1a` (6 commits) on
`feature/20260909-structured-metadata-schema`: normalized SQLite schema
(`schema.sql`), bootstrap/connection layer (`database.py`), typed records +
repository (`models.py`, `storage/__init__.py` re-exports), package-data
declaration (`pyproject.toml`), and the offline contract tests
(`tests/test_storage_schema.py`, `tests/test_metadata_repository.py`,
`tests/fixtures/metadata_records.py`). Acceptance mapping of all 10 plan
`Acceptance / Done Criteria` plus closure of the three QC-routed ⚪ evidence
items (U1 runtime pass counts, U2 built-artifact shipping of `schema.sql`, U3
interpreter/import-mode parity).

## Checkout alignment (validated)

| Item | Required | Verified |
|---|---|---|
| Review cwd | `/root/workspace/bilibili-asr-archive/.worktrees/20260909-structured-metadata-schema` | ✅ |
| Working branch | `feature/20260909-structured-metadata-schema` | ✅ (`git branch --show-current`) |
| HEAD | `2063a1a` | ✅ `2063a1a0b56b95c3dd290d1826096a187c855222` |
| Cumulative range | `c98f140..2063a1a` | ✅ merge-base `c98f140` verifies; 6 commits, +2576 lines across 9 files |
| Tree state | clean | ✅ `git status --porcelain` empty before and after all QA work |

## Evidence reuse (acceptance-first)

Read in full before any re-run:

- **L1 implementer reports**: `implementer-task-1-report.md` (7 passed; commit `14590a3`), `implementer-task-1-fix-report.md` (8 passed; package-data fix `5f22fc6`; disclosed build-tooling absence), `implementer-task-2-report.md` (8 / 16 / 709 passed; commit `bf602b8`), `implementer-task-3-report.md` (21 focused / 714 full; red→green test-authoring defects; commit `ff81140`), `implementer-qc-fix-1-report.md` (W1–W6 + S-fix-1…5; red 8 failed → focused 31 / full 724; commit `6d76ea4`), `implementer-qc-fix-2-report.md` (S-fix-6…9; red 2 failed → focused 33 / full 726; commit `2063a1a`).
- **L2 task reviews**: `review/task-1-review.md` (Important package-data finding → fixed, revalidated **Approved**), `review/task-2-review.md` (**Approved**, 7 Minor folded into QC), `review/task-3-review.md` (**Approved**, 0C/0I/4 Minor).
- **L3 QC tri**: `review/qc1.md`, `qc2.md`, `qc3.md` (Revalidation rounds 1–2 in place), consolidated `review/qc-consolidated.md` — final gate decision **Approve** (0 Critical / 0 Warning / 0 open Suggestion, zero-residual), with ⚪ U1–U3 explicitly routed to this gate as mandatory QA evidence.

Per L3 contract, QC reports were treated as review findings, not as the test log.

## U1 — targeted re-run (QA-executed, once, exact commands)

Both commands run from `/root/workspace/bilibili-asr-archive/.worktrees/20260909-structured-metadata-schema/bilibili-asr-archive`:

1. Focused:
   ```
   /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_storage_schema.py tests/test_metadata_repository.py -v
   → 33 passed in 0.78s   (12 schema + 21 repository, every test PASSED)
   ```
   Matches the assignment expectation (33) and the fix-wave-2 implementer claim.
2. Full offline suite:
   ```
   /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest
   → 726 passed in 40.84s, zero failures
   ```
   Matches the assignment expectation (726) and the fix-wave-2 implementer claim. Arithmetic is consistent with the QC-reported progression (714 → 724 → 726).

**U1 closed** — runtime pass counts are now QA-executed evidence, not implementer-reported.

## U2 — real build attempt (QA-executed, once)

The environment now provides build tooling (`uv 0.12.3` at `/root/.local/bin/uv`,
which bootstraps the declared `setuptools>=69` build backend):

- `uv build --wheel` → **SUCCESS** `dist/bili_asr-0.1.0-py3-none-any.whl`.
- Wheel inspection (zipfile listing): `bili_asr/storage/schema.sql` **present** among 36 entries; content readable, first line `PRAGMA foreign_keys = ON;`, 12 `CREATE TABLE` (7 metadata + 5 reserved) + 3 `CREATE VIEW` statements.
- `uv build --sdist` → **SUCCESS** `dist/bili_asr-0.1.0.tar.gz`; tar listing: `bili_asr-0.1.0/src/bili_asr/storage/schema.sql` present and readable (same first line).
- Cleanup: `dist/`, `build/`, `src/bili_asr.egg-info/` removed; `git status --porcelain` empty afterwards; HEAD unchanged `2063a1a`; nothing committed.

**U2 closed** — the built wheel *and* sdist both ship `schema.sql`; the Task 1
package-data/importlib.resources fix is verified against a real build artifact,
not just the in-diff contract test. The previously documented evidence gap is
resolved; no follow-up route remains.

## U3 — interpreter / import-mode parity (QA-verified)

- Control checkout interpreter used for all QA runs:
  `/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python` (Python 3.12.3, pytest 9.1.1).
- Feature worktree has **no** `.venv` (verified: `ls` fails, as the QC bundle stated).
- No `PYTEST_*` env vars, no `--import-mode` override in `pyproject.toml`, no `pytest.ini`/`setup.cfg` → pytest **default prepend import mode**; the 21 `test_metadata_repository.py` tests (which import `from fixtures.metadata_records import …`) collected and passed, proving the fixture import path resolves exactly as implementers ran it.

**U3 closed** — the QA re-run is interpreter- and import-mode-identical to the implementer runs.

## DoD mapping (plan `Acceptance / Done Criteria`, all 10 items)

| # | Done criterion | Evidence (path → test/command) | Freshness |
|---|---|---|---|
| 1 | `schema.sql` creates all declared tables, views, PKs, FKs, unique + check constraints in a fresh database | `test_fresh_database_initializes_archive_root_and_is_idempotent`, `test_schema_inspection_matches_the_declared_contract` (exact table/view set, ordered columns, FK pairs all `ON DELETE RESTRICT`, unique `origin='u'`, PK, CHECK enums) — both PASSED in QA focused re-run; corroborated by U2: shipped wheel/sdist file parses with `PRAGMA foreign_keys = ON;` header, 12 tables + 3 views | **Newly executed** (re-run) + U2 build |
| 2 | 3NF: no duplicate derived values (`work_id`, part counts, run aggregates in views only) | `test_views_compute_work_id_and_keep_derived_values_out_of_base_tables`, `test_schema_inspection…` (`work_id` absence per base table), `test_views_compute_derived_values_across_users_videos_and_runs` (`COUNT(DISTINCT)` dedup; user names joined via `videos.mid`, not stored on parts) — PASSED in QA focused re-run | **Newly executed** (re-run) |
| 3 | FK constraints reject orphaned records (video w/o user, part w/o video) | `test_foreign_keys_reject_orphans_and_use_restrict` (schema-level, incl. pages/discoveries orphans), `test_fk_rejection_and_delete_restriction_apply_to_repository_writes` (repo-level, incl. cursor w/o user), `test_start_run_requires_a_foreign_key_parent` — PASSED in QA focused re-run | **Newly executed** (re-run) |
| 4 | Unique constraints prevent duplicate entities (`(bvid, page_index)` etc.) | `test_duplicate_candidate_keys_are_rejected` — PASSED in QA focused re-run; uniqueness asserted exactly via `PRAGMA index_list` in the inspection test | **Newly executed** (re-run) |
| 5 | Idempotent upserts update labels without duplicates | `test_record_page_persists_single_and_multipart_entities_in_locked_order`, `test_repeated_page_is_idempotent_but_a_new_run_keeps_page_evidence`, `test_re_upsert_backfills_missing_aid_and_keeps_existing_aid` — PASSED in QA focused re-run | **Newly executed** (re-run) |
| 6 | Cursor advancement/page outcome atomic per page transaction; failed transaction leaves prior cursor unchanged | `test_ok_page_write_failure_rolls_back_and_caller_records_failure` (cursor byte-identical, first-write user-row rollback assertion restored in `2063a1a`), `test_transaction_order_parents_before_children`, `test_record_page_rejects_payloads_on_a_failed_page`, `test_failed_page_clock_before_running_run_start_is_rejected_and_nothing_persisted` — PASSED in QA focused re-run | **Newly executed** (re-run) |
| 7 | Failed pages persist only bounded scalar error codes | `test_error_fields_persist_only_bounded_scalar_codes` (5 forbidden inputs rejected at record boundary; DB sweep ≤64 chars, charset-bound), `test_schema_check_enumerations_match_model_validation_sets` (DDL ↔ model parity) — PASSED in QA focused re-run | **Newly executed** (re-run) |
| 8 | Offline schema + repository tests pass on Python 3.12 without network | QA full re-run: **726 passed in 40.84s** on Python 3.12.3; QA grep over `src/bili_asr/storage/`: no `bilibili_api`/`requests`/network imports; all imports stdlib-only | **Newly executed** (U1 re-run) |
| 9 | No legacy JSONL (`manifest.jsonl`, `meta-cursor.json`, `run-ledger.jsonl`) read/written by the new repository | QA grep over `src/bili_asr/storage/` for all four artifact names + `meta_cursor`/`manifest`: **no matches**; corroborates task-2-review static check ("no sidecar reads") and implementer self-reviews | **Newly executed** (fresh grep) + L2 reuse |
| 10 | `git diff --check` clean for the plan's implementation changes | QA fresh: `git diff --check c98f140 2063a1a` → exit 0, no output | **Newly executed** |

Coverage summary: **9/10 items carry QA-freshly-executed evidence** (focused+full re-runs, build-artifact check, two static checks); item 9 combines the fresh grep with L2 static reuse. No item rests on implementer-reported runtime counts anymore (U1 closed).

## Reproduction steps

```
cd /root/workspace/bilibili-asr-archive/.worktrees/20260909-structured-metadata-schema/bilibili-asr-archive
/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_storage_schema.py tests/test_metadata_repository.py -v   # → 33 passed
/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest                                                                      # → 726 passed
/root/.local/bin/uv build --wheel && /root/.local/bin/uv build --sdist                                                                                    # → dist/*.whl + *.tar.gz
python -c "import zipfile,glob; print('bili_asr/storage/schema.sql' in zipfile.ZipFile(glob.glob('dist/*.whl')[0]).namelist())"                           # → True
rm -rf dist build src/bili_asr.egg-info  # cleanup after verification
```

## Residual check (confirmed)

- No `residuals.json` exists anywhere in the repository (no `projects/` register dir) → the residual register is **empty: zero open items** for `20260909-structured-metadata-schema`.
- Engine status header concurs: `residuals: none open`.
- `zero-residual` cleanup requirement: satisfied (QC consolidated final decision already verified 0 open findings; QA re-confirmed the register side).

## Findings (QA-level)

- Critical: none. Important: none. Warning: none. Suggestions: none blocking.
- Note (informational, non-blocking): U2 verification was content-level (wheel/sdist listing + readable resource). A functional smoke of `open_database()` from an *installed* wheel in a clean interpreter was not performed (assignment scoped U2 to artifact inspection; the importlib.resources contract test plus shipped-file verification cover the risk). No residual is registered for this.
- Carry-over items remain correctly recorded in the plan's Durable Roadmap (record-level secret-prevention boundary + schema version stamp → Batch 2; typed read-model unification → Batch 3; FK-child indexes dropped) — they are roadmap items, not residuals of this plan.

## Not tested

- Non-storage suites were covered by the full re-run count (726 = 693 non-storage + 33 storage) but not individually re-inspected beyond the summary line.
- Live-network, credential, or media behaviors: out of scope by plan (STOP conditions; all tests offline by design).

## Recommended owners

- PM: proceed to spec-integration merge of `feature/20260909-structured-metadata-schema` per the review-gate chain; then plan Done. Batch 2 (`20260909-bilibili-api-ingestion`) inherits the Durable Roadmap carry-over items.

## Evidence index (paths)

- Plan: `.mstar/plans/20260909-structured-metadata-schema.md` (`## Acceptance / Done Criteria`, `## QA Gate Summary` filled by this gate)
- Primary spec: `.mstar/iterations/iter-2026-09-bilibili-api-sqlite/specs/structured-metadata-storage.md`
- SDD dir: `.mstar/sdd/20260909-structured-metadata-schema/` (implementer reports ×6, task briefs, `progress.md`)
- Review bundle: `.mstar/sdd/20260909-structured-metadata-schema/review/` (`task-1/2/3-review.md`, `qc1/2/3.md`, `qc-consolidated.md`, this file `qa-gate.md`)
- Source under review: `bilibili-asr-archive/src/bili_asr/storage/` (+ `pyproject.toml`, `tests/`) at HEAD `2063a1a`
