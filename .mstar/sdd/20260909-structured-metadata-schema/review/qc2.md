---
report_kind: qc
reviewer: qc-specialist-2
reviewer_index: 2
plan_id: "20260909-structured-metadata-schema"
verdict: "Approve"
generated_at: "2026-09-10"
---

# Code Review Report

## Reviewer Metadata

- Reviewer: @qc-specialist-2
- Runtime Agent ID: qc-specialist-2
- Runtime Model: DeepSeek Harness, standard tier (exact provider/model id not exposed in this session)
- Review Perspective: security / correctness (QC seat 2 of 3), plan-level L3 whole-branch
- Report Timestamp: 2026-09-10

## Scope

- plan_id: 20260909-structured-metadata-schema
- Review range / Diff basis: `c98f1405bded9bfd4a322c2226de7d85e4939e6e..ff81140411e9e04756055657569c39a0a0c5c2d4` (merge-base `c98f140` with spec integration branch `iteration/iter-2026-09-bilibili-api-sqlite`)
- Working branch (verified): `feature/20260909-structured-metadata-schema`
- Review cwd (verified): `/root/workspace/bilibili-asr-archive/.worktrees/20260909-structured-metadata-schema` (HEAD `ff81140` contains all 4 range commits: `14590a3`, `5f22fc6`, `bf602b8`, `ff81140`; merge-base re-verified = `c98f140`; worktree clean)
- Files reviewed: 9 diff files (+2181/-0; reproduced via `git diff --stat` — matches the branch review package exactly) plus supporting reads: `tests/conftest.py` (pre-existing `tmp_root` fixture), plan, primary spec, 3 L2 task reviews, 4 implementer reports, SDD progress ledger
- Commit range (identical to Review range — no discrepancy): `c98f140..ff81140`
- Analysis methods: git-diff (review package `branch-diff.md`, spot-reproduced read-only), read, grep — no test/build/lint runs (L3 read-only boundary)
- Deep review: triggered (S1: +2181 lines / 9 files; S2: `schema.sql` DDL under `storage/`; S3: new `bili_asr.storage` domain absent from `{KNOWLEDGE_DIR}` index; S4: `CREATE TABLE` DDL; S6: storage / tests / fixtures module boundaries)
- Lenses applied: Security Lens, Correctness Lens, Bounds Lens, Real-Entry-Path Lens, Input Validation Lens, Data Migration Lens, Testing Lens

## Findings

### 🔴 Critical

- None.

### 🟡 Warning

- None.

### 🟢 Suggestion

- [QC2-001] Terminal-outcome transitions are unguarded: `_record_failed_page`'s `UPDATE ingestion_runs SET outcome='failed', finished_at=?` has no `outcome='running'` predicate and no `finished_at >= started_at` guard, so a late/stale failed-page record can regress a `complete` run to `failed` and move `finished_at` backwards; `finish_run` symmetrically allows re-finishing (e.g., `complete` → `failed`) with the same effect. -> Add `WHERE run_id = ? AND outcome = 'running'` (+ `changes()` check raising `IntegrityError`) to `_record_failed_page`, and a terminal-state guard to `finish_run`, before the Batch 2 gateway locks this contract. Unreachable in the designed sequential gateway flow, hence non-blocking.
  - Source Type: deep-lens: Correctness Lens (re-adjudicated from L2 Task-2 Minor #3, extended to `finish_run`)
  - Verification: diff/read anchor — `src/bili_asr/storage/database.py:402-413` (`_record_failed_page` unguarded UPDATE), `database.py:306-312` (`finish_run` UPDATE, no prior-state check; schema has no CHECK binding `finished_at`/`outcome` transitions), vs `finish_run`'s own `finished_at >= started_at` validation at `database.py:303-304`
  - Expected vs observed: expected a run's terminal outcome to be monotonic (failed/complete cannot be overwritten by a later page record) vs observed any `record_page(failed)` or repeated `finish_run` overwrites outcome/finished_at unconditionally

- [QC2-002] Secret-prevention boundary is record-level only — verified as documented (PM disposition confirmed from the diff): `schema.sql` enforces only `length(...) <= 64` on `error_code`/`last_error_code`; the scalar-code *shape* (`^[A-Za-z0-9_.:-]+$`, no cookies/URLs/JSON/tracebacks/whitespace) lives exclusively in `models._error_code`. Raw SQL bypassing the record types can persist arbitrary ≤64-char text. -> Carry to Batch 2 as a hard gateway rule (all error-field writes must go through the record types); optionally add a comment in `schema.sql` stating the column CHECK is a length backstop, not the secret boundary.
  - Source Type: deep-lens: Input Validation Lens (PM disposition verified, carried per assignment focus 4)
  - Verification: diff/read anchor — `src/bili_asr/storage/schema.sql:62,73` (length-only CHECKs) vs `src/bili_asr/storage/models.py:48-55` (`_error_code` charset + length); test evidence `tests/test_metadata_repository.py:306-364` (forbidden materials rejected at record boundary; DB sweep proves repository path clean)
  - Expected vs observed: expected the plan's "persisted errors are bounded scalar codes only" to hold on the repository path (it does — verified) vs observed the column layer alone cannot enforce it (documented, dispositioned; not a compliance defect of this branch)

- [QC2-003] `_resolve_database_path` special-cases `file:`-prefixed strings, but `sqlite3.connect(...)` is called without `uri=True`, so a `file:` value cannot work as a URI — it would be treated as a literal filename (a stray file named `file:...` is created; URI params like `mode=memory&cache=shared` are silently ignored). -> Either pass `uri=True` for `file:` values or drop the branch; add a focused test if kept.
  - Source Type: deep-lens: Input Validation Lens (new seat-2 finding; not in L2 reports)
  - Verification: diff/read anchor — `src/bili_asr/storage/database.py:55-56` (accepts `":memory:"` and `file:` prefixes) vs `database.py:88` (`sqlite3.connect(database_path, isolation_level="DEFERRED")` — no `uri` argument; no test exercises the `file:` branch)
  - Expected vs observed: expected an explicitly special-cased input form to behave as that form (`file:` URI semantics) vs observed the branch routes the string to `connect` with URI interpretation disabled (Python default `uri=False`)

- [QC2-004] Class docstring over-claims: "The low-level methods execute SQL without committing so a caller can group them in one transaction", while `start_run` (`database.py:256-257`) and `finish_run` (`database.py:312`) commit unconditionally — composing them inside `transaction()` / `with connection:` prematurely commits the enclosing transaction's earlier writes. -> Name the two committing methods explicitly in the class docstring before Batch 2 composes against this API. (The `start_run` independent commit itself is correct plan design: it keeps the run FK parent alive for bounded failure evidence after a page rollback.)
  - Source Type: deep-lens: Correctness Lens / Contract clarity (L2 Task-2 Minor #1, re-adjudicated: agree, non-blocking)
  - Verification: diff/read anchor — `database.py:99-107` (docstring) vs `database.py:256-257` (`self.connection.commit()` in `start_run`) and `database.py:312` (commit in `finish_run`)
  - Expected vs observed: expected the docstring's commit contract to match method behavior vs observed two undocumented committing methods inside a "no-commit" API group

- [QC2-005] Speculative dual-form APIs in brand-new code (no prior API to be compatible with): scalar `finish_run(run_id, outcome, finished_at)` whose "preferred" record form is never exercised by any test (both test call sites use the scalar form), `record_page(video=...)` plus keyword-only `videos=...`, and the untested explicit-`video_part_id` upsert branch in `upsert_part` (`database.py:193-217`). -> Pick one canonical form per method (or add tests for the forms intentionally kept) before Batch 2 locks against this contract.
  - Source Type: deep-lens: Correctness Lens / Standards (L2 Task-2 Minor #2, re-adjudicated: agree, non-blocking)
  - Verification: diff/read anchor — `database.py:259-293` (dual-form `finish_run`), `database.py:336-345` (`video` + `videos` params), `database.py:193-217` (explicit-id branch); grep — the only `finish_run` call sites (`tests/test_metadata_repository.py:270-271,321`) use the scalar form; no caller/test uses the record form, `videos=` or the explicit-id branch
  - Expected vs observed: expected the documented "preferred form" to be the tested one vs observed the untested compatibility form is what tests exercise

- [QC2-006] `MetadataRepository.__init__` accepts any `sqlite3.Connection`, but `read_cursor`/`run_stats` use column-name indexing (`row["mid"]`, `row["next_page"]`, …) which requires `row_factory = sqlite3.Row` — only `open_database` sets it; a bare `sqlite3.connect()` connection fails at read time with an opaque `TypeError`. -> Assert/set the Row factory in `__init__` or document the requirement.
  - Source Type: deep-lens: Correctness Lens (L2 Task-2 Minor #4, re-adjudicated: agree, non-blocking)
  - Verification: diff/read anchor — `database.py:109-112` (`__init__` type check only) vs `database.py:451-462` (column-name indexing) and `database.py:87-88` (row factory set only in `open_database`)
  - Expected vs observed: expected the constructor's accepted inputs to be serviceable by all public methods vs observed a constructible-but-undocumented-broken connection variant

- [QC2-007] `models.py:255-269` comments that validation helpers are "intentionally not part of the public model API", then exports `validate_error_code` and `ALLOWED_*` sets in `__all__` — and repo-wide grep confirms **no caller or test uses any of them**. -> Drop the exports (or reword the comment if they are deliberately public); also note `__all__` is built with two statements (list + `+=`), trivially foldable.
  - Source Type: deep-lens: Standards Lens / Contract clarity (L2 Task-2 Minor #5, re-adjudicated and strengthened with a usage grep: agree, non-blocking)
  - Verification: diff/read anchor — `src/bili_asr/storage/models.py:255-269`; grep across `src/` and `tests/` — `validate_error_code|ALLOWED_` has zero usages outside `models.py`
  - Expected vs observed: expected comment and export list to agree vs observed exported-but-unused "private" helpers (dead speculative surface)

- [QC2-008] Package export asymmetry: `bili_asr/storage/__init__.py` re-exports `DatabaseConnection` and helpers but omits `MetadataRepository` (the primary product of this plan), so consumers must import from `bili_asr.storage.database` — inconsistent public surface for the Batch 2 gateway/CLI plans. -> Export `MetadataRepository` from the package root (it is already imported transitively, so this costs nothing) or document the intended import path.
  - Source Type: deep-lens: Contract Lens focus by seat-2 mandate / Standards (new seat-2 finding)
  - Verification: diff/read anchor — `src/bili_asr/storage/__init__.py:6-17` (`__all__` without `MetadataRepository`) vs `src/bili_asr/storage/database.py:572-579` (module `__all__` includes it); `tests/test_metadata_repository.py:11` imports it from `.database`
  - Expected vs observed: expected the package root to expose the repository it advertises in the plan Interfaces vs observed the central class missing from the public surface

- [QC2-009] Failed-page contract asymmetry: a no-payload `record_page(page, outcome='failed')` marks the run failed/finished (`_record_failed_page`), but a `failed` page recorded **with** a successful payload persists the payload plus the failed page row and does **not** mark the run failed (the run-failure update only runs on the exception path). Both are currently legal. -> Pin the gateway rule (failed pages carry no payload, or payload+failed implies run-failure) in the Batch 2 contract.
  - Source Type: deep-lens: Correctness Lens / Contract clarity (new seat-2 finding; the no-payload behavior itself was disclosed in the Task 3 implementer self-review)
  - Verification: diff/read anchor — `database.py:385-399` (no-payload failed path → `_record_failed_page`), `database.py:400-451` (payload path: page row written inside the success transaction; run-failure update only under `except BaseException`)
  - Expected vs observed: expected a uniform run-failure rule for `outcome='failed'` vs observed divergent behavior depending on whether payload arguments are supplied

- [QC2-010] Schema has no version stamp and `CREATE TABLE IF NOT EXISTS` initialization silently keeps divergent legacy shapes on reopen (no migration is in scope this iteration — fine for a greenfield path). Before any long-lived `archive.db` exists, record a schema version (e.g., `PRAGMA user_version`) or a documented "fresh-database only" policy. Mitigation exists today: the exact-set inspection test fails loudly on a divergent DB, but only in the test suite.
  - Source Type: deep-lens: Data Migration Lens (new seat-2 finding; no-migration is spec/plan-sanctioned for this iteration, hence Suggestion)
  - Verification: diff/read anchor — `src/bili_asr/storage/schema.sql` (all objects `IF NOT EXISTS`; no `user_version`), `database.py:66-75` (`initialize_schema` executes idempotently, no shape/version verification), plan Global Constraint "a fresh database is initialized from a checked-in schema file"
  - Expected vs observed: expected reopening an existing database to verify it matches the checked-in contract vs observed silent acceptance of any pre-existing object set

- [QC2-011] Display labels (`title`, `display_name`, part `title`) are unbounded at both layers: `models._text` rejects empty/control characters but has no length limit, and the schema columns are bare `TEXT NOT NULL` — a multi-megabyte upstream label would be persisted verbatim. The plan's bounded-fields constraint covers error codes only. -> Bound label length at the gateway boundary (Batch 2) or add a generous column CHECK; not required by this plan's contract.
  - Source Type: deep-lens: Bounds Lens (new seat-2 finding)
  - Verification: diff/read anchor — `models.py:38-45` (`_text`, no length check) vs `models.py:48-55` (`_error_code`, ≤64); `schema.sql` (`videos.title`, `bilibili_users.display_name`, `video_parts.title` have no CHECK)
  - Expected vs observed: expected persisted external-facing text to have a documented size bound like error codes do vs observed unbounded label persistence

- [QC2-012] `v_ingestion_run_stats` LEFT-JOINs `ingestion_pages` × `ingestion_discoveries` per run before `COUNT(DISTINCT)`, producing an O(pages × discoveries) intermediate per run — correct results (the view test proves COUNT(DISTINCT) dedup and LEFT-JOIN zeros), and the SQL is spec-verbatim, so this is not a compliance defect. -> If Batch 3 CLI consumers aggregate over many large runs, prefer subquery counts; no change required now.
  - Source Type: manual-reasoning (cross-cutting performance note, verified against the spec's locked view SQL)
  - Verification: diff/read anchor — `src/bili_asr/storage/schema.sql:162-174` (view SQL identical to spec §`v_ingestion_run_stats`), `tests/test_storage_schema.py:460-465` (derivation test: 3 discovery rows over 2 pages → `(2, 2)`)
  - Expected vs observed: expected per-run aggregation cost linear in rows vs observed quadratic cross-product per run (correctness unaffected; spec-mandated SQL)

### ⚪ Unconfirmed

- None — every finding above is anchored in the diff/worktree via read/grep; no evidence channel failed.

## Plan-Level Compliance Verification (whole branch vs primary spec + plan Global Constraints)

Verified from diff/read/grep (not runtime):

1. **3NF / no derived duplicates in base tables** — ✅. No `work_id`, `part_count`, `video_count`, `run_count` columns in any base table (`tests/test_storage_schema.py` inspection test asserts their absence per table and per-column manifests); `work_id` computed only in `v_video_parts`/`v_pending_metadata` and as the `VideoPartRecord.work_id` property (never persisted); run aggregates only in `v_ingestion_run_stats`; owner name reached via `videos.mid` (view test proves the join routes through two distinct users). `videos.aid` is a stable identifier with COALESCE backfill — no derived duplicate.
2. **FK `ON DELETE RESTRICT` everywhere** — ✅. All 11 declared FKs use RESTRICT; asserted both behaviorally (delete tests raise `IntegrityError`) and by `PRAGMA foreign_key_list` (`on_delete == "RESTRICT"` per FK) in the schema inspection test. Deliberate absence of a discovery→page FK is a disclosed design choice compatible with the locked order (discoveries are inserted before the page outcome row) — agreed.
3. **Bounded scalar error codes only** — ✅ on the repository path. `models._error_code` enforces ≤64 chars and charset `^[A-Za-z0-9_.:-]+$`, structurally rejecting cookies (`=`/`;`/space), signed URLs (`/`/`?`/`:`-excepted but `https` with `/` fails), raw JSON (`{`/quotes/space), and tracebacks (space/newline). Schema is a length backstop only (see QC2-002). No cookie/signed-URL/JSON/traceback field exists anywhere in the models or SQL.
4. **Offline-only (no `bilibili_api`/network imports)** — ✅. Grep over `src/bili_asr/storage/*` and the three new test files: zero matches for `bilibili_api|requests|urllib|httpx|aiohttp|socket`. Stdlib-only imports (`sqlite3`, `dataclasses`, `re`, `contextlib`, `importlib.resources`, `math`, `os`, `pathlib`, `typing`, `tomllib`, `pytest`).
5. **No legacy JSONL reads/writes** — ✅. Grep over the new module, `schema.sql`, and new tests: zero matches for `manifest|meta_cursor|meta-cursor|run_ledger|run-ledger|jsonl`. The repository consumes only internal dataclasses/scalars.
6. **Audio/transcript tables as schema reservations only** — ✅. The five reservation tables exist with spec-shaped columns/FKs/uniques/CHECKs; no repository method writes them; the only test touching `audio_objects` is a schema-level duplicate-key test. No media/ASR behavior added.
7. **Locked page transaction order** (user → videos → parts → discoveries → cursor → page outcome → commit) — ✅. `record_page` payload path implements exactly this order; proven by the rollback test where the FK failure occurs mid-order (parts after videos, before cursor), demonstrating both rollback and cursor preservation. `start_run`'s independent commit is correct plan design (run parent survives page rollback for bounded failure evidence) — see QC2-004 for the docstring caveat.
8. **Idempotency vs per-run page evidence** — ✅. Entities upsert on stable keys (`mid`, `bvid`, `(bvid, page_index)`); pages key `(run_id, page_number)`, discoveries key `(run_id, page_number, bvid)`, so repeated pages are idempotent while each run keeps its own evidence (tested: counts stay 1 under run-1 replay, become 2 pages + 2 discoveries under run-2).
9. **Cursor preservation on failure** — ✅. Cursor write sits inside the page transaction; the rollback test asserts the prior cursor row is byte-identical after a failed page.
10. **Determinism** — ✅. Grep: no `datetime|time.time|random|uuid|secrets` in the storage module; every persisted timestamp is caller-supplied; fixtures use a fixed literal timeline.
11. **Packaging** — ✅ diff-level. `pyproject.toml` declares `[tool.setuptools.package-data] "bili_asr.storage" = ["schema.sql"]` (quoted literal package key — correct) and `database.py` reads the schema through `importlib.resources.files(__package__)` with an offline contract test asserting both. Actual wheel/sdist content remains runtime-unverified (⚠️ below).

## Acceptance / Done Criteria — diff-evidenced vs QA-open

| Criterion (plan) | Status |
|---|---|
| `schema.sql` creates all tables/views/PKs/FKs/uniques/CHECKs in a fresh DB | Diff-evidenced (exact-set inspection test) |
| 3NF: `work_id`, part counts, run aggregates computed in views/app code, not stored | Diff-evidenced |
| FK constraints reject orphans (video w/o user, part w/o video) | Diff-evidenced (schema + repository tests) |
| Unique constraints prevent duplicate entities (`(bvid, page_index)`, `aid`, `sha256`, `storage_key`) | Diff-evidenced (behavioral + index-asserted) |
| Idempotent upserts update labels without duplicate rows | Diff-evidenced |
| Cursor advancement + page outcome atomic per page; failed txn leaves prior cursor unchanged | Diff-evidenced |
| Failed pages persist only bounded scalar codes; no credentials/signed URLs/raw JSON/tracebacks | Diff-evidenced **on the repository path** (boundary documented — QC2-002) |
| Offline schema + repository tests pass on Python 3.12 without network | Diff-evidenced for *offline* (imports); **pass counts implementer-reported → QA gate** ⚠️ |
| No legacy JSONL (`manifest.jsonl`, `meta-cursor.json`, `run-ledger.jsonl`) read/written | Diff-evidenced (grep: zero references) |
| `git diff --check` clean | Implementer-reported; not re-run per read-only boundary ⚠️ |

No acceptance criterion is unevidenceable in principle; two require the mandatory QA gate re-run (⚠️ items 1–2).

## L2 Finding Re-Adjudication (assignment focus 2 — severities judged independently)

- Task 1 Important (schema resource packaging) — **fixed in `5f22fc6`**, verified in the final diff (package-data entry + `importlib.resources` + offline contract test). Closed.
- Task 2 Minors #1 (docstring), #2 (dual forms), #4 (row_factory), #5 (models exports) — **confirmed as non-blocking**; re-reported as QC2-004/005/006/007 (with the usage grep strengthening #5). Not escalated: none is reachable as a defect in the designed gateway flow; all are pre-Batch-2 contract polish.
- Task 2 Minor #3 (`_record_failed_page` terminal regression) — **confirmed, extended** to the symmetric `finish_run` re-finish case → QC2-001. Not escalated: no designed path triggers it; fix is one guard line before Batch 2.
- Task 2 Minor #6 (aid COALESCE untested) — **closed by Task 3**: `test_re_upsert_backfills_missing_aid_and_keeps_existing_aid` covers None→backfill and preserve-on-differing-aid. Verified in diff.
- Task 2 Minor #7 (failed page permits `error_code=None`) — **agree with implementer resolution: spec-intended** (spec declares `error_code` nullable; the plan brief sentence is looser than the spec it derives from). Not carried as a finding.
- Task 3 Minors (extra `tests/fixtures/__init__.py`, redundant LIKE sweep, `status=` naming nit, DDL-substring sensitivity) — **accepted as cosmetic**; none re-reported. The `fixtures/__init__.py` is justified: it makes `from fixtures.metadata_records import …` resolve under pytest's prepend import mode (verified `tests/` has no `__init__.py`, `tests/fixtures/` does, and the pre-existing `tests/conftest.py` provides `tmp_root`).
- Cross-task boundary risks from the assignment (locked order / idempotency-vs-per-run evidence / separate `start_run` commit / cursor preservation) — all verified compliant; see Plan-Level Compliance items 7–9. **No plan-level blocker found.**

## ⚠️ Items for PM/QA (cannot verify from diff)

1. **Runtime pass counts are implementer-reported**: focused `21 passed` (10 schema + 11 repository — test-function census independently matches) and full offline suite `714 passed`; plus red→green (`2 failed` → `21 passed`) with both reds disclosed as test-authoring defects. QA gate must re-run with the **control-checkout interpreter** (`/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python` — the feature worktree has no local `.venv`) and the **exact documented command** (`from fixtures.metadata_records import …` relies on pytest prepend import mode inserting `tests/` into `sys.path`).
2. **`git diff --check` cleanliness is implementer-reported** (both pre- and post-commit); not re-run per the read-only review boundary.
3. **Built-wheel content unverified**: the implementer disclosed that no `pip`/`setuptools`/`wheel`/`build` tooling exists in the environment, so the wheel/sdist was never actually built; the offline package-data + `importlib.resources` contract test is the only artifact evidence. When tooling is available, QA/PM should verify `schema.sql` lands inside a built wheel (residual risk is low: the declaration is present and the resource API is used).
4. **Record-level secret-prevention boundary** (QC2-002) must ride to the Batch 2 gateway plan as a contract rule; the schema alone cannot enforce the code shape.

## Source Trace

- QC2-001 — Source Type: deep-lens: Correctness Lens — Source Reference: `src/bili_asr/storage/database.py:402-413, 306-312` — Confidence: High
- QC2-002 — Source Type: deep-lens: Input Validation Lens — Source Reference: `src/bili_asr/storage/schema.sql:62,73` vs `src/bili_asr/storage/models.py:48-55` — Confidence: High
- QC2-003 — Source Type: deep-lens: Input Validation Lens — Source Reference: `src/bili_asr/storage/database.py:55-56, 88` — Confidence: High
- QC2-004 — Source Type: deep-lens: Correctness Lens — Source Reference: `src/bili_asr/storage/database.py:99-107 vs 256-257, 312` — Confidence: High
- QC2-005 — Source Type: deep-lens: Standards Lens — Source Reference: `src/bili_asr/storage/database.py:259-293, 336-345, 193-217`; grep of call sites — Confidence: High
- QC2-006 — Source Type: deep-lens: Correctness Lens — Source Reference: `src/bili_asr/storage/database.py:109-112, 451-462` — Confidence: High
- QC2-007 — Source Type: deep-lens: Standards Lens — Source Reference: `src/bili_asr/storage/models.py:255-269`; repo-wide grep (zero external usages) — Confidence: High
- QC2-008 — Source Type: manual-reasoning (contract surface) — Source Reference: `src/bili_asr/storage/__init__.py:6-17` vs `database.py:572-579` — Confidence: High
- QC2-009 — Source Type: deep-lens: Correctness Lens — Source Reference: `src/bili_asr/storage/database.py:385-399 vs 400-451` — Confidence: High
- QC2-010 — Source Type: deep-lens: Data Migration Lens — Source Reference: `src/bili_asr/storage/schema.sql` (IF NOT EXISTS only), `database.py:66-75` — Confidence: High (risk deferred by greenfield scope)
- QC2-011 — Source Type: deep-lens: Bounds Lens — Source Reference: `src/bili_asr/storage/models.py:38-45`, `schema.sql` label columns — Confidence: High
- QC2-012 — Source Type: manual-reasoning (performance note) — Source Reference: `src/bili_asr/storage/schema.sql:162-174`; spec §`v_ingestion_run_stats` — Confidence: Medium (impact depends on future run sizes)

Note: every finding carries `Verification` + `Expected vs observed` in its entry above.

## Summary

| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟡 Warning | 0 |
| 🟢 Suggestion | 12 |
| ⚪ Unconfirmed | 0 |

**Verdict**: Approve

Rationale: the whole-branch diff satisfies the primary spec and every plan Global Constraint I can verify statically (3NF, RESTRICT FKs, locked page order, idempotency with per-run page evidence, cursor preservation on failure, bounded scalar error codes on the repository path, offline-only, no legacy JSONL, reservation-only media tables, deterministic writes). All L2 Important findings were fixed and verified in the final diff; L2 Minors re-adjudicated as non-blocking; no new Critical/Warning found. The 12 Suggestions are pre-Batch-2 contract polish and robustness notes (trigger conditions all lie outside this plan's designed flows), and the four ⚠️ items are runtime claims that belong to the mandatory QA gate, not to this diff review. Approve per template rules: Critical = 0, Warning = 0, every finding's evidence channel intact.
