---
report_kind: qc
reviewer: qc-specialist
reviewer_index: 1
plan_id: "20260909-structured-metadata-schema"
verdict: "Approve"
generated_at: "2026-09-10"
---

# Code Review Report

## Reviewer Metadata

- Reviewer: @qc-specialist
- Runtime Agent ID: qc-specialist
- Runtime Model: DeepSeek (harness-configured session route; exact route id not surfaced to this seat)
- Review Perspective: QC seat 1 — whole-branch spec compliance, cross-task contract boundaries, logic/data-consistency risk, maintainability (diff / logic / maintainability reviewer; not a test runner)
- Report Timestamp: 2026-09-10T18:20Z (approx., session clock)

## Scope

- plan_id: `20260909-structured-metadata-schema` (Batch 1 of `iter-2026-09-bilibili-api-sqlite`, Execution mode: sdd)
- Review range / Diff basis: `c98f1405bded9bfd4a322c2226de7d85e4939e6e..ff81140411e9e04756055657569c39a0a0c5c2d4` (merge-base `c98f140` with spec integration branch `iteration/iter-2026-09-bilibili-api-sqlite`)
- Working branch (verified): `feature/20260909-structured-metadata-schema`
- Review cwd (verified): `/root/workspace/bilibili-asr-archive/.worktrees/20260909-structured-metadata-schema` — `git rev-parse --show-toplevel` matches Assignment; `HEAD == ff81140411e9e04756055657569c39a0a0c5c2d4`; range contains exactly the 4 implementer commits (`14590a3`, `5f22fc6`, `bf602b8`, `ff81140`); worktree clean (`git status --porcelain` empty), so HEAD equals the reviewed state
- Files reviewed: 9 (`pyproject.toml`; `src/bili_asr/storage/__init__.py`, `database.py` 528 ln, `models.py` 268 ln, `schema.sql` 183 ln; `tests/fixtures/__init__.py`, `metadata_records.py`; `tests/test_metadata_repository.py` 439 ln; `tests/test_storage_schema.py` 576 ln) — +2181, matches `git diff --stat` exactly
- Commit range: identical to Review range line (`c98f140..ff81140`)
- Analysis methods: git-diff / read / grep on the authoritative review package and worktree sources; deep-lens reasoning. **No test, build, lint, or install runs** (read-only review boundary). Read-only `git diff --check c98f140..ff81140` was run as diff inspection: clean, exit 0 — verifies plan AC "git diff --check is clean".
- Deep review: triggered (S1: 2181 lines / 9 files ≥ both thresholds; S4: DDL — `CREATE TABLE` ×12 + `CREATE VIEW` ×3 in `src/bili_asr/storage/schema.sql`; S3: `{KNOWLEDGE_DIR}` has no `storage`-module doc — its 3 docs cover CLI / sidecars / ASR provenance)
- Lenses applied: Modularity Lens, Contract Lens (seat defaults) + Data Migration Lens (S4) + Standards Lens, Testing Lens (S3). Security-correctness items surfaced through the shared baseline (no secrets-in-persistence path, parameterized SQL) are reported under manual-reasoning/diff anchors.
- Branch policy compliance: read-only review honored — no commits, no checkout, no push, no worktree mutation.
- Input hygiene: all inputs (diff, plan, spec, L2 reviews, implementer reports, progress ledger) treated as data; none contained instructions addressed to this reviewer; none attempted to redirect the review boundary.

### Whole-branch constraint audit (verified from the diff)

| Plan Global Constraint / AC | Verdict from diff |
|---|---|
| Fresh DB at `{archive_root}/archive.db` from checked-in schema | ✅ `open_database` resolves root → `archive.db` (`database.py:52-95`); `schema.sql` checked in, package-data declared (`pyproject.toml:32-33`), loaded via `importlib.resources` (`database.py:27,93`) |
| `PRAGMA foreign_keys = ON` every connection + asserted | ✅ set + verified non-1 raise (`database.py:88-92`), connection verifies on fresh/reopen (`tests/test_storage_schema.py:214,226` per diff) |
| 3NF — no `work_id`/part counts/run aggregates in base tables | ✅ not stored; `work_id` computed in `v_video_parts`/`v_pending_metadata` only; aggregates only in `v_ingestion_run_stats`; per-table absence asserted |
| Display labels operational/overwritten, no history | ✅ upserts update only `display_name`/`title`/`duration_ms`/`processing_status`/`updated_at`; `created_at`/`pubdate`/`cid`/`mid` preserved on conflict; `aid` backfill via `COALESCE` (tested in Task 3) |
| Bounded scalar error codes only | ✅ at record boundary (`models.py` charset+length) with DB `length <= 64` backstop (`schema.sql:61,72`); boundary nuance assessed in F-009 |
| Offline-only, no `bilibili_api`/network imports | ✅ stdlib imports only across all 4 product/test modules; no network/wall-clock/random input |
| No legacy JSONL reads/writes | ✅ zero references to `manifest.jsonl` / `meta-cursor.json` / `run-ledger.jsonl` in the diff |
| Audio/transcript tables = schema reservations only | ✅ 5 reservation tables column-exact per spec; repository writes none of them; no media/ASR behavior added |
| All writes transactionally testable + deterministic | ✅ caller-supplied timestamps everywhere; explicit `transaction()`; locked page order implemented and tested incl. mid-order FK rollback preserving cursor |
| Spec transaction order steps 1–7 | ✅ implemented in `record_page` payload path and exercised by E2E |
| Stop conditions | ✅ none triggered (no denormalization, no raw payloads, no legacy access, no network) |

## Findings

### 🔴 Critical

None. No spec violation, no security exposure, and no data-corruption path reachable in the flows implemented and tested by this branch was found.

### 🟡 Warning

- **[F-001]** `_record_failed_page` overwrites a run's terminal outcome without any guard — a late/stale failed-page record can regress a finished run (`complete`/`limited`/`risk_interrupted` → `failed`) and move `finished_at` backwards (the schema has no CHECK binding `ingestion_runs.finished_at`), bypassing the `finished_at >= started_at` discipline that `finish_run` enforces. -> Guard the failure-path update to running runs only: `SET outcome='failed', finished_at=? WHERE run_id=? AND outcome='running'` (the page row is still persisted as failure evidence); give `finish_run` an explicit re-finish/idempotency rule so outcome transitions are disciplined in both directions. Do this before the contract is accepted by Batch 2.
  - Verification: diff/read anchor — `src/bili_asr/storage/database.py:402-413` (`UPDATE ingestion_runs SET outcome='failed', finished_at=? WHERE run_id=?`, unguarded; no `changes()` check) vs `database.py:295-311` (`finish_run` validates terminal outcome + ordering); both are reachable from public API surface via the no-payload failed-page path (`database.py:371-373`) and the payload-failure handler (`database.py:388-400`); no outcome-transition CHECK exists in `src/bili_asr/storage/schema.sql:37-52`.
  - Expected vs observed: expected — a terminal run outcome is immutable under every repository write path (failure evidence appended, not rewritten) vs observed — any later `record_page` with a `failed` page for the same `run_id` unconditionally rewrites `outcome` and `finished_at`.
  - Note: re-judged from L2 Task 2 Minor #3 to plan-level Warning. Trigger condition: any failed-page record arriving for a run already in a terminal outcome (stale/queued page result, retry reusing a `run_id`, or a Batch 2 consumer recording pages after `finish_run`). Impact: silent corruption of run terminal state on the SSOT layer (run outcome is a fact, not an overwritable display label); `v_ingestion_run_stats` consumers see a regressed history. Not a functional break in this plan's own tested flows — Severity Warning, not Critical.
  - Confidence: High

- **[F-002]** `finish_run`'s documented "preferred" record form (`finish_run(IngestionRunRecord(...))`) has zero test coverage on the whole branch, and it validates `finished_at >= started_at` against the caller-supplied record's `started_at` instead of the database's actual `started_at` — only the scalar form is exercised, and it is the form that fetches `started_at` from the DB. -> Add a contract test for the record form and source `started_at` from the DB in both forms (or document the record form's weaker baseline), before Batch 2 consumers adopt the "preferred" form.
  - Verification: grep anchor — every `finish_run` call in the branch is the scalar form: `tests/test_metadata_repository.py:269-270, 422`; the record form appears only in the docstring (`src/bili_asr/storage/database.py:267-269`); record form baseline = `run.started_at` (`database.py:276-277`), scalar baseline = DB fetch (`database.py:286-291`); no DB CHECK re-validates ordering.
  - Expected vs observed: expected — the form documented as preferred for the ingestion service carries the same deterministic contract evidence as the scalar form (Task 3's stated purpose is "deterministic contract evidence for the gateway and CLI plans") vs observed — an untested public branch with a weaker ordering baseline.
  - Note: re-judged from L2 Task 2 Minor #2; the sharper half of that Minor (untested documented-preferred form) is escalated; the remaining dual-form/dead-branch cleanup is F-007.
  - Confidence: High

### 🟢 Suggestion

- **[F-003]** Class docstring over-claims: "The low-level methods execute SQL without committing so a caller can group them in one transaction" (`database.py:101`), but `start_run` commits unconditionally (`database.py:257`) and `finish_run` commits (`database.py:312`); composing either inside `transaction()` (`database.py:114-122`) implicitly commits the enclosing group's earlier writes. -> Name the two committing methods in the class docstring so Batch 2 does not compose them inside a page transaction.
  - Verification: read anchor — `database.py:101` vs `:257`, `:312`; behavior is intentional and inline-commented at the `start_run` site (`database.py:253-254`).
  - Expected vs observed: expected — class-level contract matches every method's commit behavior vs observed — two methods contradict the blanket statement (documentation-only; inline comment exists).
  - Confidence: High

- **[F-004]** `MetadataRepository.__init__` accepts any `sqlite3.Connection` (`database.py:109-112`), but `read_cursor` requires `row_factory = sqlite3.Row` for name-based indexing (`database.py:452-461`), and `list_pending_parts`/`run_stats` return raw rows whose name-indexing the caller inherits; only `open_database` sets the factory (`database.py:89`). A bare `sqlite3.connect()` connection passes construction and writes, then fails at read time with an opaque `TypeError`. -> Assert or set `row_factory = sqlite3.Row` in `__init__` (or document the requirement) before Batch 2.
  - Verification: grep anchor — `row_factory` set once (`database.py:89`); `row["..."]` used in `read_cursor` (`database.py:452-461`); `__init__` checks type only.
  - Expected vs observed: expected — an unusable connection is rejected at construction vs observed — failure deferred to first read path (API trap, not a correctness bug in shipped flows; all tests construct via `open_database`).
  - Confidence: High

- **[F-005]** The `file:` URI branch of `_resolve_database_path` (`database.py:55`) returns the URI unchanged, but `sqlite3.connect` is called without `uri=True` (`database.py:88`), so per stdlib defaults the value would be treated as a literal filename (creating a file named e.g. `file:memdb?mode=memory`) rather than opening a URI database. -> Either pass `uri=True` for `file:` values or drop the special-case branch; add a test for whichever behavior is intended (no caller or test reaches this branch today).
  - Verification: read anchor — `database.py:55` (file: special-case) vs `database.py:88` (`connect(database_path, isolation_level="DEFERRED")`, no `uri` argument); `tests/test_storage_schema.py` exercises only directory roots and `.db`-suffixed paths.
  - Expected vs observed: expected — a defensive URI branch either implements URI semantics or does not exist vs observed — an untested branch whose behavior does not match its evident intent.
  - Confidence: Medium (anchored in stdlib URI-off-by-default semantics; behavior unexercised in-repo)

- **[F-006]** Enumerated value sets are duplicated in four places with no cross-check: `models.py` `Literal` types + `_ALLOWED_*` frozensets, `schema.sql` CHECKs, and `tests/test_storage_schema.py:148` `EXPECTED_CHECK_ENUMERATIONS`. The contract test pins schema↔test drift, but a model↔schema drift (e.g., a status added to one side only) surfaces only as a runtime `IntegrityError`/`ValueError` asymmetry. -> Derive one set from the other (or add a single parity assertion that the model sets equal the schema CHECK values) before the gateway plan locks on these enums.
  - Verification: grep anchor — `_ALLOWED_*` (`models.py:19-23` region), CHECK enumerations (`schema.sql`, `EXPECTED_CHECK_ENUMERATIONS` block), no assertion compares model sets to schema values anywhere in the two test files.
  - Expected vs observed: expected — one derivation source (or an explicit parity test) for a locked contract vs observed — four hand-synced copies.
  - Confidence: High

- **[F-007]** Remaining untested/dead branches inherited from L2 Task 2 Minor #2 (dual-form APIs): `upsert_part`'s explicit-`video_part_id` insert branch (`database.py:193-217`; every fixture yields `video_part_id=None`, `models.py:125`), `record_page`'s `video`-as-iterable branch (`database.py:360-361`) and its untested `video`+`videos` mixing, and the `:memory:` branch of `_resolve_database_path`. -> Pick one canonical form per method and add or delete the extra branches before Batch 2 locks against this contract (YAGNI / no-compat-layer rule: these are new APIs with no prior form to be compatible with).
  - Verification: grep anchor — no caller or test passes an iterable to `video=`, constructs a part with explicit `video_part_id`, or opens `:memory:`.
  - Expected vs observed: expected — each public branch either has contract evidence or does not exist vs observed — three unexercised branches in the durable contract.
  - Confidence: High

- **[F-008]** Import-surface asymmetry for the Batch 2/CLI consumers: `bili_asr.storage/__init__.py` re-exports only the bootstrap helpers (`DatabaseConnection`, `duration_to_ms`, `initialize_schema`, `normalize_page_index`, `open_database`), while `MetadataRepository` and the record models live in `bili_asr.storage.database` / `.models` only. -> Re-export the repository and record types from the package root (or document the canonical import paths) so the gateway plan has one stable import surface.
  - Verification: read anchor — package `__init__.py` `__all__` (5 names) vs `database.py:522-528` `__all__` (includes `MetadataRepository`) and `models.py` record classes.
  - Expected vs observed: expected — the plan's "Produces DatabaseConnection, repository methods…" surface is importable from one place vs observed — split across package root and two submodules.
  - Confidence: High

- **[F-009]** Secret-prevention boundary assessment (PM disposition re-checked): the schema enforces only `length(...) <= 64` on `error_code`/`last_error_code` (`schema.sql:61,72`); the bounded-scalar *shape* (`^[A-Za-z0-9_.:-]+$`) is enforced at the record boundary (`models.py` `_error_code`, `models.py:47-54`), which is the repository's only accepted input type. -> This satisfies the plan constraint as written ("Persisted errors are bounded scalar codes only" — the repository is the sole write contract and rejects cookies/signed-URLs/JSON/traceback material, proven by the no-secret test). No escalation needed for this plan; **carry the boundary statement verbatim into the Batch 2 gateway plan**: any future write path that bypasses the records (raw SQL, new tables) re-opens the no-secret constraint. Optional defense-in-depth: mirror the charset as a DB CHECK.
  - Verification: grep anchor — length-only CHECKs (`schema.sql:61,72`), no shape CHECK in DDL; record-level enforcement + five-class rejection test (`tests/test_metadata_repository.py::test_error_fields_persist_only_bounded_scalar_codes`).
  - Expected vs observed: expected — plan constraint honored at the contract's input boundary vs observed — exactly that, with the DB layer as length backstop only (documented by implementer; matches spec's repository-as-sole-input design).
  - Confidence: High

- **[F-010]** `models.py:255-256` comment ("validation helpers … intentionally not part of the public model API") contradicts the immediately following public exports `validate_error_code` + `ALLOWED_*` in `__all__` (`models.py:255-268`). -> Reword the comment (or make the helpers private and let consumers derive sets from the `Literal` types).
  - Verification: read anchor — `models.py:255` comment vs `models.py:256-268` exports.
  - Expected vs observed: expected — comment matches the module's actual public surface vs observed — contradiction (documentation-only).
  - Confidence: High

- **[F-011]** The no-secret test's LIKE-marker sweep over the two error columns (`tests/test_metadata_repository.py`, sweep block before the value-equality asserts) duplicates what the exact non-null value-equality assertions directly below already prove. Harmless defense-in-depth. -> Trim if the test grows.
  - Verification: read anchor — marker sweep + exact `[expected_codes[(table, column)]]` equality in the same test body.
  - Expected vs observed: expected — one proving assertion strategy per invariant vs observed — two overlapping ones (accepted today).
  - Confidence: High

- **[F-012]** `make_part_record(status=…)` parameter name diverges from the field name `processing_status` (`tests/fixtures/metadata_records.py:94`). Cosmetic; call sites remain readable. -> Rename on the next touch of the fixture, or accept as-is.
  - Verification: read anchor — fixture signature/`processing_status=status` (`metadata_records.py:94`).
  - Expected vs observed: expected — builder kwargs mirror field names vs observed — one inherited divergence.
  - Confidence: High

### ⚪ Unconfirmed

- **[F-013]** Runtime pass counts are implementer-reported, not re-executed by this review: Task 1 `8 passed` → Task 1-fix `8 passed`; Task 2 `8 passed` / `16 passed` / `709 passed`; Task 3 red `2 failed, 16 passed` → green `21 passed in 0.56s` (10 schema + 11 repository) and full offline suite `714 passed in 40.23s`. — channel gap: read-only L3 review boundary forbids running the suite; the static trace of all 21 tests against schema/repository raised no focused-run doubt. The mandatory QA gate must re-run them.
- **[F-014]** Built-wheel inclusion of `schema.sql` is unverified — channel gap: the available interpreter environment has no `pip`/`setuptools`/`wheel`/`build` tooling (implementer disclosed; Task 1 review + progress ledger concur). In-diff verified evidence: setuptools package-data declaration (`pyproject.toml:32-33`), `importlib.resources` load path (`database.py:27,93`), and the offline resource-contract test (`tests/test_storage_schema.py::test_schema_sql_is_declared_and_read_as_package_resource`). A real wheel-artifact check should be run by QA/implementer where build tooling exists.
- **[F-015]** QA environment parity preconditions for the QA re-run — channel gap: these are conditions on future evidence, not verifiable from the diff. The feature worktree has no local `.venv`; implementer evidence was produced with the control checkout's interpreter (`/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python`), and `from fixtures.metadata_records import …` relies on pytest's default prepend import mode. QA must re-run with the same interpreter pattern and import mode (or the documented command verbatim) or the pass counts are not comparable.

## Source Trace

- Finding ID: F-001
- Source Type: manual-reasoning (diff/read anchors)
- Source Reference: `src/bili_asr/storage/database.py:402-413` vs `:295-311`, `:371-373`, `:388-400`; `src/bili_asr/storage/schema.sql:37-52`
- Confidence: High
- Note: carries Verification + Expected vs observed above; escalated from L2 Task 2 Minor #3 with trigger condition and impact stated.
- Finding ID: F-002
- Source Type: deep-lens: Testing Lens
- Source Reference: `tests/test_metadata_repository.py:269-270, 422` (scalar form only); `src/bili_asr/storage/database.py:267-269, 276-277, 286-291`
- Confidence: High
- Note: escalated from L2 Task 2 Minor #2 (record-form half).
- Finding ID: F-003
- Source Type: read
- Source Reference: `src/bili_asr/storage/database.py:101` vs `:257`, `:312`; inline comment `:253-254`
- Confidence: High
- Note: unchanged severity from L2 Task 2 Minor #1 (documentation-only).
- Finding ID: F-004
- Source Type: grep
- Source Reference: `src/bili_asr/storage/database.py:89`, `:109-112`, `:452-461`
- Confidence: High
- Note: unchanged severity from L2 Task 2 Minor #4.
- Finding ID: F-005
- Source Type: read
- Source Reference: `src/bili_asr/storage/database.py:55` vs `:88` (no `uri=True`); untested branch
- Confidence: Medium
- Note: new whole-branch find (not in L2 reports); behavior unreachable by current callers/tests.
- Finding ID: F-006
- Source Type: grep
- Source Reference: `models.py` `_ALLOWED_*` frozensets; `schema.sql` CHECKs; `tests/test_storage_schema.py:148,480`
- Confidence: High
- Note: new cross-task synthesis of the repeated duplicated-enums pattern.
- Finding ID: F-007
- Source Type: grep
- Source Reference: `src/bili_asr/storage/database.py:193-217`, `:360-361`, `:336-345`; `models.py:125`
- Confidence: High
- Note: remainder of L2 Task 2 Minor #2; recurring "dual-form/dead branch" pattern marked as such.
- Finding ID: F-008
- Source Type: read
- Source Reference: `src/bili_asr/storage/__init__.py` `__all__` (5 names) vs `database.py:522-528`
- Confidence: High
- Note: new contract-surface observation for Batch 2 import ergonomics.
- Finding ID: F-009
- Source Type: doc-rule (plan Global Constraint + spec §Transaction rules) + grep
- Source Reference: `schema.sql:61,72`; `models.py:47-54`; `tests/test_metadata_repository.py::test_error_fields_persist_only_bounded_scalar_codes`
- Confidence: High
- Note: PM disposition re-checked and confirmed as satisfying the plan constraint, with an explicit carried-forward condition to Batch 2.
- Finding ID: F-010
- Source Type: read
- Source Reference: `src/bili_asr/storage/models.py:255-268`
- Confidence: High
- Note: unchanged from L2 Task 2 Minor #5.
- Finding ID: F-011
- Source Type: read
- Source Reference: `tests/test_metadata_repository.py` no-secret test, sweep + equality blocks
- Confidence: High
- Note: unchanged from L2 Task 3 Minor #2.
- Finding ID: F-012
- Source Type: read
- Source Reference: `tests/fixtures/metadata_records.py:94`
- Confidence: High
- Note: unchanged from L2 Task 3 Minor #3.
- Finding ID: F-013
- Source Type: assignment-ci-note (implementer-reported runtime evidence)
- Source Reference: implementer-task-1/1-fix/2/3 reports; task-3-review ⚠️ item 1; progress.md dispositions
- Confidence: N/A (channel gap, not a doubt)
- Note: QA gate re-runs; static trace raised no focused-test doubt.
- Finding ID: F-014
- Source Type: read + implementer-report
- Source Reference: `pyproject.toml:32-33`; `database.py:27,93`; implementer-task-1-fix-report (no build tooling)
- Confidence: N/A (artifact unbuildable in this environment)
- Note: diff-verifiable package contract present; wheel artifact check deferred.
- Finding ID: F-015
- Source Type: implementer-report / assignment-ci-note
- Source Reference: implementer-task-3-report (interpreter disclosure); task-3-review ⚠️ items 3-4
- Confidence: N/A (future-evidence condition)
- Note: binds F-013's re-run to the identical interpreter/import mode.

## Summary

| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟡 Warning | 2 |
| 🟢 Suggestion | 10 |
| ⚪ Unconfirmed | 3 |

**Verdict**: Request Changes

### Blocking rationale

The implemented schema and repository are spec-compliant on every plan Global Constraint and acceptance criterion verifiable from the diff (see the constraint audit in Scope), and the offline test build is genuinely contract-shaped. What blocks `Approve` is contract readiness of the two failure/terminal-path surfaces that Batch 2 is about to lock against (`bilibili-api-ingestion` is explicitly "blocked until this plan's repository contract is accepted"):

1. **F-001** — the failure path can silently rewrite a run's terminal outcome and regress `finished_at`, with no DB-level or code-level guard; trigger path is public API surface (`record_page` with a `failed` page). One-line guard closes it.
2. **F-002** — the `finish_run` form the docstring tells Batch 2 to prefer is untested and carries a weaker `started_at` baseline than the scalar form. One test (+ baseline alignment) closes it.

Both are small, surgical fixes; neither invalidates the implemented behavior of Tasks 1–3. PM owns disposition (fix in this plan pre-gate, or defer to Batch 2 with explicit residual registration — but a terminal-outcome data-consistency guard is cheap enough that deferral should be justified, not defaulted).

### Re-judgement of L2 Minors (independent severity, not inherited)

- **Escalated to Warning**: Task 2 M#3 (terminal-outcome regression → F-001); Task 2 M#2 record-form half (untested preferred form → F-002).
- **Stays Suggestion**: Task 2 M#1 (→ F-003), M#4 (→ F-004), M#2 remainder (→ F-007), M#5 (→ F-010); Task 3 M#2 (→ F-011), M#3 (→ F-012).
- **Closed/resolved, no finding**: Task 2 M#6 (`aid` COALESCE backfill) — closed by Task 3's `test_re_upsert_backfills_missing_aid_and_keeps_existing_aid` (verified in diff); Task 2 M#7 (`error_code=None` on failed page) — resolved as spec-intended by Task 3 (spec declares `error_code` nullable; the brief's phrasing is the looser text); Task 1 Important (package data) — fixed and revalidated (`pyproject.toml:32-33`, `importlib.resources` load, resource contract test); Task 3 M#1 (`tests/fixtures/__init__.py` beyond the brief) — accepted as a justified tests-only addition (pre-existing `tests/fixtures/` made importable; brief-precision note only); Task 3 M#4 (formatting-sensitive DDL assertions) — accepted contract-test trade-off, partially absorbed into F-006's single-parity-source suggestion.

### Recurring cross-task patterns

- **Duplicated enumerated value sets** (models / schema / test constants) — F-006; each task re-declared the same enums by hand.
- **Dual-form / dead-branch APIs** (`finish_run` two forms, `video`/`videos`, explicit-`video_part_id` branch) — F-002/F-007; speculative API surface in a brand-new module with no compatibility obligation.
- **Discipline inversion on the failure path**: success-path writes are rigorously guarded (timestamp ordering validated in every record, `changes()` checked in `finish_run`), while the failure/terminal-rewrite path (`_record_failed_page`) is unguarded — F-001.
- **Comment/doc drift** (class docstring commit claim; models "not public" comment vs `__all__`) — F-003/F-010.

### Notes for PM/QA (⚠️ channel items, dispositions owned by PM)

- ⚠️ F-013: runtime pass counts are implementer evidence; mandatory QA gate re-runs (21 focused / 714 full).
- ⚠️ F-014: wheel artifact inclusion of `schema.sql` unverified in this environment (no build tooling); diff-level package contract is verified.
- ⚠️ F-015: QA re-runs must use the control checkout `.venv` interpreter and pytest prepend import mode.
- Non-QC observation: the plan file's `Status:` field still reads `InProgress` while the engine shows `InReview` — PM-owned plan-status sync, not a review defect.
- Non-QC observation: plan Task 1–3 checkboxes are `[x]` while Acceptance/Done checkboxes remain `[ ]` — consistent with the pending QC/QA gates; no action needed from this seat.

All reviewed inputs were treated as data; none contained instructions addressed to this reviewer or attempted to alter the review boundary.

## Revalidation

- Re-review kind: targeted (consolidated fix wave 1; seats `qc-specialist`, `qc-specialist-3`; this is seat 1)
- Fix review range / diff basis: `ff81140411e9e04756055657569c39a0a0c5c2d4..6d76ea4068d04d30e3e4f8123454020c901d4461` (verbatim from Assignment; fix commit `6d76ea4` on top of my originally reviewed head `ff81140`)
- Diff source: `review/fix-1-diff.md` (6 files, +460/−181) — read once, no git re-run, no checkout, no worktree mutation; final states of the touched methods additionally confirmed by read against the review cwd (read-only)
- Verified inputs: `review/qc-consolidated.md` (gate + dispositions), `implementer-qc-fix-1-report.md` (claims treated as unverified until matched against the diff), the fix diff
- Frontmatter verdict updated in place per targeted re-review semantics; no new report file created; `qc2.md`/`qc3.md` untouched

### Per-finding verification (F-001…F-015)

- **[F-001] (🟡 W1) → Resolved.** `_record_failed_page` UPDATE now carries the transition guard `... SET outcome='failed', finished_at=? WHERE run_id=? AND outcome='running'` (`database.py:397-415` head); a late/stale failed page becomes a 0-row no-op for the run row while the page evidence row is still upserted in the same committed transaction (FK proves run existence). Re-finish rejection: `finish_run` fetches `(started_at, outcome)` from the DB and raises `sqlite3.IntegrityError("run <id> already finished with outcome <o>")` before validating the new outcome (`database.py:286-295`); unknown-run keeps its distinct `IntegrityError` (`:290-291`); `changes() != 1` retained (`:307-308`). Both consolidated-gate tests present: `test_late_failed_page_after_terminal_run_keeps_run_outcome_unchanged` (finish `complete`@300 → late no-payload failed page@400/401 → page row `('failed','stale_page_result')` persisted, run row stays `('complete', 300)`) and `test_finish_run_rejects_refinishing_a_terminal_run` (second finish raises, state unchanged). Narrowed residual → new Suggestion F-016 below.
- **[F-002] (🟡 W2) → Resolved**, stronger than requested. The scalar form is removed entirely; `finish_run(self, run: IngestionRunRecord)` is the only form (`database.py:275-309`) — plan compliance verified: the plan produces method names only, no signature contract. Baseline aligned: ordering validates against the DB's stored `started_at` (`run_row["started_at"]`), not the record's field. The dropped scalar-form checks are genuinely covered by the record dataclass (verified in head source): `_integer` rejects bool/non-int (`models.py:29-34`), `_text` rejects empty/whitespace `run_id` (`models.py:37-44`), `IngestionRunRecord.__post_init__` validates `finished_at` as int ≥ 0 with record-internal ordering (`models.py:172-175`). Test `test_finish_run_record_form_validates_against_database_started_at` pins the exact hole I raised: record `started_at=50, finished_at=60` vs stored 101 → `ValueError`; plus non-terminal-outcome and `finished_at=None` rejections and a `limited`@300 happy path checked via `run_stats`.
- **[F-003] (🟢 W4) → Resolved.** Class docstring over-claim replaced with an explicit per-method commit matrix (`database.py:110-134`): `start_run`/`finish_run` commit independently; `record_page` owns one transaction plus the no-payload evidence transaction; `upsert_user`/`upsert_video`/`upsert_part`/`record_discovery`/`write_cursor` never commit; the three read paths never write; explicit do-not-compose warning for the three committing methods. `initialize_schema` docstring states FK enable + commit (`:75-79`); `open_database` documents path semantics including `:memory:` and non-interpreted URIs (`:88-98`). Matrix matches verified behavior (`:273`, `:309`, `transaction()` at `:145-154`).
- **[F-004] (🟢 W3) → Resolved** (superset of my ask). Constructor fails fast: `row_factory is not sqlite3.Row` → `TypeError`; `PRAGMA foreign_keys != 1` → `ValueError` (`database.py:136-142`). Tests: bare `sqlite3.connect` → `TypeError` (`test_constructor_rejects_a_connection_without_row_factory`); Row-factory connection asserted pragma==0 first, then → `ValueError` (`test_constructor_rejects_a_connection_with_foreign_keys_disabled`). The FK-pragma half is qc3's W3 — consistent and cheap; check ordering makes both tests exercise distinct branches.
- **[F-005] (🟢 W6) → Resolved** via the consolidated "drop the branch" option. `file:` special case removed from `_resolve_database_path` (`database.py:54-72` head — only `:memory:` remains); `file:`-prefixed strings are ordinary explicit paths (literal filename), documented in both `_resolve_database_path` and `open_database` docstrings; no speculative `uri=True` surface (correct no-compat-layer call for a greenfield API). The one retained special case (`:memory:`) — previously the untested branch — is now covered by `test_open_database_memory_database_is_initialized` (characterization, green-at-birth).
- **[F-006] (🟢 S-fix-4) → Resolved.** New `test_schema_check_enumerations_match_model_validation_sets` (`test_storage_schema.py` head ~`:263-281`): extracts each CHECK `IN (...)` literal list from `sqlite_master` per table/column and asserts set parity with `models.ALLOWED_*`, and pins each `Literal` alias to its frozenset via `typing.get_args` — model↔schema↔Literal drift now fails a focused test. Plus `_TERMINAL_RUN_OUTCOMES = ALLOWED_RUN_OUTCOMES - frozenset({"running"})` (`database.py:28`) removes the second hand-written terminal set. Test-side only, exactly as consolidated S-fix-4 scoped it (`schema.sql` untouched).
- **[F-007] (🟢 W2) → Resolved.** All flagged branches closed: `upsert_part`'s explicit-`video_part_id` INSERT branch deleted; non-None now raises `ValueError("upsert_part allocates video_part_id; it must be None")` — one upsert statement, no duplicated SQL (`database.py:194-266` head), tested by `test_upsert_part_rejects_an_explicit_video_part_id`; `record_page`'s `video` singular-or-iterable parameter and the `video`+`videos` mixing branch deleted (`videos: Iterable[VideoRecord]` only, placed in the locked positional order, `:333-341`); `start_run`'s `ON CONFLICT(run_id) DO NOTHING` retry removed — duplicate raises the PK `IntegrityError` (`:250-258`), tested by `test_start_run_rejects_a_duplicate_run_id`; the `:memory:` branch is tested (above).
- **[F-008] (🟢 S-fix-2) → Resolved.** Package root re-exports `MetadataRepository`, all 7 record dataclasses, the 4 `Literal` aliases, the 4 `ALLOWED_*` sets, `validate_error_code`, and the original 5 helpers; `__all__` (22 names) matches the imports; docstring declares the package root the single import surface (`storage/__init__.py:1-53` head).
- **[F-009] (🟢 — disposition, no code change expected) → Disposition confirmed.** Consolidated S-carry-1 carries the record-boundary SSOT statement into Batch 2 ("Batch 2 must inherit record-level validation as a hard contract rule") and keeps the schema-level shape CHECK as carried defense-in-depth — matching my original recommendation in substance. Nothing to fix in this wave.
- **[F-010] (🟢 S-fix-1) → Resolved.** Comment now reads "Public validation surface: the canonical enumeration sets and the error-code validator are exported so gateway and CLI callers validate against the same contract the record dataclasses enforce." (`models.py:255-257` head) — consistent with the actual exports.
- **[F-011] (🟢 S-fix-3) → Resolved.** The LIKE-marker sweep is removed from `test_error_fields_persist_only_bounded_scalar_codes`; the exact non-null value-equality, length ≤ 64, and charset assertions remain (`test_metadata_repository.py` head ~`:436-492`).
- **[F-012] (🟢 S-fix-5) → Resolved.** `make_part_record(status=…)` → `processing_status=…` (`tests/fixtures/metadata_records.py:89` head); the one call site updated in `test_cursor_resume_and_pending_limit`. The fixture's added `video_part_id`/`outcome`/`finished_at` params are test-support additions for the new rejection tests (fixture-only, legitimate).
- **[F-013] (⚪ QA-bound) → Disposition matches.** Implementer re-ran under the U3 pattern; focused 21→31 (all 21 pre-existing preserved; +10 new/rewritten), full 714→724, `git diff --check` clean, `git status --porcelain` empty after commit — all implementer-reported and still mandatory-QA-gate evidence. Internally consistent: 714 − 21 + 31 = 724; the reported red state names exactly the 8 behavior tests the diff adds, with the 2 remaining (memory + parity) correctly green-at-birth.
- **[F-014] (⚪ QA-bound) → Disposition matches.** Still QA-owned; no build tooling; the wave does not touch packaging (`pyproject.toml` absent from the diff).
- **[F-015] (⚪ QA-bound) → Disposition matches.** U3 parity conditions restated unchanged (control checkout `.venv` interpreter + pytest default prepend import mode + exact focused commands).

### Regression lens on the fix diff

- **Locked transaction order: preserved.** Payload path verbatim — user → videos → parts → discoveries → cursor → page outcome → commit (`database.py:384-395` head); `has_payload` includes `user is not None` (`:366-372`). The removed `except BaseException` handler existed solely to auto-record failure evidence when a failed page carried payloads — that input shape is now rejected with `ValueError` before any write (W5 rule), so `transaction()` alone owns rollback + re-raise and failure recording is a documented caller-owned second call. Both directions tested: ok-page write failure → atomic rollback (cursor byte-identical, videos/parts/pages counts unchanged, run stays `('running', None)`), then the no-payload bounded evidence call → page row `('failed','foreign_key')` + run `('failed', 201)`; failed+payload → `ValueError` with nothing persisted.
- **schema.sql byte-untouched in the diff** → 3NF, FK RESTRICT, reservation tables, DDL CHECKs, and views intact; guards are application-level only; no denormalization, no raw payloads, no legacy access, no network (STOP conditions untriggered).
- **FK RESTRICT: strengthened, not weakened** — the constructor now requires `PRAGMA foreign_keys` ON; `test_start_run_requires_a_foreign_key_parent` untouched; `upsert_video`'s `aid` COALESCE backfill behavior untouched (`database.py:180-181` head).
- **Bounded scalar error codes: preserved** — no new persisted error values; fixture code `stale_page_result` passes the record charset; `finish_run` error messages interpolate only the caller-supplied `run_id` key (pre-existing pattern) and are never persisted.
- **Offline-only: preserved** — new imports are stdlib (`os`, `re`, `typing.get_args`) in tests; the product change imports only `ALLOWED_RUN_OUTCOMES` from `.models`; no network/wall-clock/random input.
- **Preserved baseline (3 disclosed shape adjustments — each verified in the diff):** (1) three scalar `finish_run` call sites → record form (E2E ×2 + run-stats ×1) — forced by the removed form; (2) six `video=` → `videos=` call sites — forced by the removed parameter (all call sites keyword-based, so no positional-arg break); (3) `test_failed_page_rolls_back_payload_preserves_cursor_and_records_bounded_outcome` → `test_ok_page_write_failure_rolls_back_and_caller_records_failure` — the old input shape (failed page + payloads) is now contract-rejected; the new test preserves every original invariant (rollback, cursor preservation, bounded evidence, run failure transition) and adds videos/pages counts plus the running-state assertion. No test deleted without replacement; no invariant lost.
- **No other in-repo consumers** of the repository APIs (module is new in this branch; Batch 2 not started) — canonicalization breaks no other suite; consistent with the diff touching only the two storage test files and fixtures.
- **New-guard semantics sanity:** `finish_run` check order (unknown-run → re-finish → outcome validity → `finished_at` presence → DB-baseline ordering → UPDATE → `changes()`) is sensible and every reachable branch is tested or impossible-by-construction (dataclass validation); `_record_failed_page`'s intentional `changes()==0` no-op on a terminal run is documented, safe (the page-row upsert succeeding proves the run exists via FK), and tested.

### New finding from revalidation

- **[F-016]** (🟢 Suggestion, new) `_record_failed_page`'s run transition still applies no ordering check against the run's own stored `started_at`: while the run is still `running`, a failed page whose `finished_at < run.started_at` (inconsistent caller clocks — the page record validates `finished_at >= page.started_at` only internally, `models.py:190-198`) sets `ingestion_runs.finished_at` below the run's `started_at`; `schema.sql` is untouched so no DB CHECK binds them. Strictly narrowed pre-existing behavior: after the W1 guard a terminal run can never be touched at all (the F-001 regression is closed), and a running run has no prior `finished_at` to regress. -> Either mirror `finish_run`'s DB-baseline ordering check in `_record_failed_page` (one guarded condition), or carry it to Batch 2 as part of the failure-protocol contract (same channel as S-carry-1). Not blocking: requires caller-supplied inconsistent timestamps on a still-running run.
  - Verification: diff/read anchor — `database.py:397-415` head (UPDATE with only the `outcome='running'` guard) vs `:300-302` (`finish_run`'s DB-baseline check); `models.py:190-198` (page-record internal ordering only).
  - Expected vs observed: expected — every write path that sets `ingestion_runs.finished_at` enforces `finished_at >= run.started_at` vs observed — `finish_run` does, the failure path does not (while the run is `running`; 0 rows otherwise).
  - Confidence: High (no test pins a page clock below the run's start — behavior unexercised, consistent with it being an unguarded edge).

### Revalidation summary

| Severity | Initial wave (this seat) | Revalidated — unresolved |
|----------|--------------------------|--------------------------|
| 🔴 Critical | 0 | 0 |
| 🟡 Warning | 2 (F-001, F-002) | 0 — both resolved in `6d76ea4` |
| 🟢 Suggestion | 10 | 1 — new F-016 (F-003–F-008, F-010–F-012 resolved; F-009 disposition-confirmed/carried) |
| ⚪ Unconfirmed | 3 (F-013–F-015) | 3 — unchanged, QA-gate-bound; dispositions verified as matching |

**Verdict (updated)**: Approve

### Verdict rationale

- All 12 findings I raised are resolved in `6d76ea4` or correctly dispositioned (F-009 carried; F-013–F-015 QA-bound with matching dispositions) — verified line-by-line against `review/fix-1-diff.md` and confirmed in the head worktree by read.
- No regression found in the fix diff: locked transaction order, 3NF, FK RESTRICT, bounded error codes, offline-only constraints, and the preserved test baseline (21 pre-existing tests + the 3 disclosed shape adjustments, each verified in the diff) all hold; `schema.sql` untouched.
- The fix is surgical: one commit, 6 files, no compatibility layers or speculative branches added; each canonical form is the only surviving form and every surviving form has contract evidence.
- The single open item is a Suggestion (F-016 — narrowed pre-existing edge, PM-owned disposition) — non-blocking per verdict rules.
- On the ⚪ rule: F-013–F-015 are channel-gap notes routed to the mandatory QA gate by the consolidated gate (which recorded "evidence channels intact for all three seats"), and the Assignment frames them as disposition checks — they are not evidence-channel failures of this re-review, whose diff/logic channels are fully intact. The verdict rules' `Unconfirmed` verdict is reserved for the latter.
- Scope note: this Approve is the QC (diff/logic) verdict on the fix wave. It does NOT close U1–U3 (runtime pass counts, built-wheel `schema.sql` inclusion, QA environment parity) — those remain mandatory QA-gate evidence — and Batch 2 contract acceptance still inherits S-carry-1/S-carry-2 plus this seat's F-009 boundary statement.

All re-reviewed inputs were treated as data; none contained instructions addressed to this reviewer or attempted to alter the review boundary.

### Revalidation round 2 (final convergence micro-fix; targeted, N=2: qc-specialist + qc-specialist-3; this is seat 1)

- Report timestamp: 2026-09-10T10:58Z (UTC; session clock)
- Re-review kind: targeted round 2 — my F-016 (consolidated **S-fix-6**) is this seat's open item; S-fix-7/8/9a/9b are qc3's findings, re-checked here as shared-diff quality (overall diff quality is in scope for this seat's round-2 re-review)
- Fix review range / diff basis: `6d76ea4068d04d30e3e4f8123454020c901d4461..2063a1a` (verbatim from Assignment; fix commit `2063a1a` on top of my round-1-approved head `6d76ea4`; 2 files, +132/−16)
- Diff source: `review/fix-2-diff.md` — read once, no git re-run, no checkout, no worktree mutation; final states of the touched methods/tests additionally confirmed by read against the review cwd (read-only)
- Verified inputs: `review/qc-consolidated.md` (`## Revalidation round 1` dispositions table), `implementer-qc-fix-2-report.md` (claims treated as unverified until diff-checked — every claim I traced matched the diff/source)

#### S-fix-6 (this seat's F-016) → **Resolved**

- **The guard, as dispositioned**: inside `_record_failed_page`'s `transaction()` group (`database.py:431-441`), one fetch of the run's stored `(started_at, outcome)` (`:432-435`) followed by one guarded condition — `run_row is not None and run_row["outcome"] == "running" and page.finished_at < int(run_row["started_at"])` (`:436-440`) — raising `ValueError("finished_at must not precede started_at")` (`:441`). This mirrors `finish_run`'s DB-baseline check structurally and textually: same SELECT shape (`database.py:301-304` vs `:432-435`), same `int()` cast of the stored baseline (`:315` vs `:439`), identical message string (`:317` vs `:441`) — exactly the "one guarded condition mirroring `finish_run`" the PM disposition asked for.
- **Nothing persisted on rejection**: the raise precedes both writes — `_record_page(page)` (`:442`) and the guarded run UPDATE (`:443-450`) — inside the same `transaction()` group, so the guarantee is structural (zero writes executed), with rollback as a no-op safety net. Not merely rollback-dependent.
- **Preserved branches, each verified in head source against the untouched tests**:
  - *Terminal-run evidence persistence (W1 behavior)* — the guard applies only while `outcome == "running"`; a terminal run skips it entirely and the page-evidence upsert still commits while the run row is untouched. `test_late_failed_page_after_terminal_run_keeps_run_outcome_unchanged` is context-only in the diff (unchanged).
  - *Unknown-run FK* — `run_row is not None` means an unknown `run_id` skips the guard and still fails on the page-row FK RESTRICT (`IntegrityError`), unchanged.
  - *Valid-clock transition* — a page with `finished_at >= stored started_at` passes and the failure transition (`SET outcome='failed', finished_at=? WHERE run_id=? AND outcome='running'`, `:443-450`) is intact.
- **Test pinning the rejection**: `test_failed_page_clock_before_running_run_start_is_rejected_and_nothing_persisted` (`tests/test_metadata_repository.py:270-298`) — an internally *valid* page record (`started_at=50/finished_at=51`, passes record-internal ordering `finished_at >= started_at`) whose clock lies below the run's stored `started_at=101` (the `_start_run` fixture default, `tests/test_metadata_repository.py:26-28` + fixtures) → `pytest.raises(ValueError)`; asserts zero page rows for `run-1` and the run unchanged `('running', None)`. The record is deliberately record-valid, so the test isolates exactly the DB-baseline edge F-016 raised — the hole that record-internal ordering alone left open.
- **Docstring truthfulness maintained**: `record_page` (`:374-382`) documents the DB baseline + rejection; `_record_failed_page` (`:421-430`) restates it and drops the now-false unconditional "the page evidence is always upserted" claim (implementer self-review caught this before commit — verified: the old wording is gone).
- Minor observation, not a finding: `int(run_row["started_at"])` is a defensive cast (the column is written only via validated `start_run` records and declared INTEGER) — but it exactly mirrors `finish_run`'s own `int(run_row["started_at"])` (`:315`), so the two transitions stay byte-consistent. Harmless; consistent with the disposition's mirror requirement.

#### Regression lens on the round-2 diff (database.py + test file only)

- **Locked transaction order: intact.** Payload path body verbatim (`record_page` hunks are docstring-only, `:374-383`); `_record_failed_page`'s added SELECT+guard precedes its writes without altering the evidence-upsert → guarded-transition order; `has_payload` semantics and the failed+payload `ValueError` rule untouched (`:389-397`).
- **3NF / FK RESTRICT: intact.** `schema.sql` is absent from the diff (verified: no hunk); the guard is application-level; no new columns, tables, denormalization, or raw payloads.
- **Bounded scalar codes: intact.** No new persisted error values — the new test reuses the in-bounds `stale_page_result` code from round 1; the rejection message is a static string, never persisted.
- **Offline-only: intact.** The product diff adds no imports at all; the test additions use only pre-existing imports. No network/`bilibili_api`/wall-clock/random input.
- **Terminal-run guard + re-finish rejection unchanged.** No hunk touches `finish_run` (`:290-324` — unknown-run → terminal-re-finish → outcome validity → `finished_at` presence → DB-baseline ordering → `changes()` chain all verbatim in head source); both W1/W2 gate tests are context-only in the diff.
- **No speculative branches/compat layers.** The read-path TypeError/ValueError split refines this branch's own new API (greenfield — no prior form to stay compatible with); grep over both test files confirms no pre-existing test pinned the old `ValueError`-for-type-error behavior (the remaining `ValueError` raise-sites are record-validation, failed+payload, constructor, and `upsert_part` pins — unrelated); read-path SQL bodies are unchanged (validation split only, `:474-483`, `:533-542`, `:560-569`).
- **S-fix-7 scope note (disclosed, verified legitimate)**: extending the TypeError normalization to `list_pending_parts` goes beyond the finding's literal `read_cursor`/`run_stats` wording but is grounded in qc3 F-012's own line anchor and its stated expected state (uniform read-path convention) — consistent completion of the dispositioned fix, not an adjacent refactor; it also completes the module-wide discipline (write paths and `duration_to_ms`/`normalize_page_index` already raise `TypeError` for type errors).
- **S-fix-8**: docstring-only aid-stability clause (`:182-187`); `upsert_video` SQL untouched (`:190-199`, `COALESCE(videos.aid, excluded.aid)` intact).
- **S-fix-9a**: restored transaction-head assertion verified (`tests/test_metadata_repository.py:162-167` — user label `未明子` proves the failing call's first write rolled back), with a comment naming what it proves; green-at-birth re-pin of already-correct behavior.
- **S-fix-9b**: commit matrix now names both no-payload sub-cases (`database.py:118-122`) plus the matching `record_page` docstring clause (`:374-376`) — the matrix is now exhaustive against the verified behavior.
- **Test arithmetic** (implementer-reported, QA-gate-bound as in round 1): focused 31→33 (+2 new behavior tests; the restored assertion is green-at-birth), full 724→726 — internally consistent (724 − 31 + 33 = 726). Red state named exactly the 2 new behavior tests.

#### Round-2 severity summary (this seat's register)

| Severity | After round 1 | After round 2 |
|----------|---------------|---------------|
| 🔴 Critical | 0 | 0 |
| 🟡 Warning | 0 | 0 |
| 🟢 Suggestion | 1 (F-016, open) | 0 — F-016/S-fix-6 resolved; no new findings raised |
| ⚪ Unconfirmed | 3 (F-013–F-015) | 3 — unchanged, QA-gate-bound channel notes (not evidence-channel failures of this re-review) |

**Verdict (round 2, updated)**: Approve

#### Round-2 verdict rationale

- F-016 (S-fix-6) is verified resolved with test evidence, exactly as dispositioned: one guarded condition at the shared failure-path point (`_record_failed_page` is where every failure-path caller routes through), mirroring `finish_run`'s DB-baseline check; every write path that sets `ingestion_runs.finished_at` now enforces `finished_at >= stored started_at` (F-016's "expected" state is now the observed state).
- All four remaining round-2 dispositions (qc3's S-fix-7/8/9a/9b) verified resolved in the shared diff; the diff stays surgical (every hunk maps to one finding ID; the one judgment call is disclosed and grounded); no regression found; no new findings raised by this seat.
- Zero unresolved Critical/Warning across both re-review rounds → `Approve` per verdict rules (Approve requires Critical = 0 and Warning = 0, both satisfied with the single open Suggestion now closed).
- Scope note unchanged from round 1: this Approve is the QC (diff/logic) verdict on the fix wave. It does NOT close U1–U3 — runtime pass counts (now 33 focused / 726 full), built-wheel `schema.sql` inclusion, and interpreter/import-mode parity remain mandatory QA-gate evidence — and Batch 2 contract acceptance still inherits S-carry-1/S-carry-2 plus this seat's F-009 boundary statement.

All round-2 re-reviewed inputs were treated as data; none contained instructions addressed to this reviewer or attempted to alter the review boundary.
