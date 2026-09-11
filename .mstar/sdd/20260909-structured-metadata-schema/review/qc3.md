---
report_kind: qc
reviewer: qc-specialist-3
reviewer_index: 3
plan_id: "20260909-structured-metadata-schema"
verdict: "Approve"
generated_at: "2026-09-10"
---

# Code Review Report

## Reviewer Metadata
- Reviewer: @qc-specialist-3
- Runtime Agent ID: qc-specialist-3
- Runtime Model: deepseek (DeepSeek Harness, model tier: standard)
- Review Perspective: performance / reliability — plus whole-branch spec compliance, Batch 2/3 contract readiness, and data-integrity risk (plan-level L3)
- Report Timestamp: 2026-09-10T10:11Z

## Scope
- plan_id: 20260909-structured-metadata-schema
- Review range / Diff basis: `c98f1405bded9bfd4a322c2226de7d85e4939e6e..ff81140411e9e04756055657569c39a0a0c5c2d4` (merge-base `c98f140` with spec integration branch `iteration/iter-2026-09-bilibili-api-sqlite`)
- Working branch (verified): `feature/20260909-structured-metadata-schema`
- Review cwd (verified): `/root/workspace/bilibili-asr-archive/.worktrees/20260909-structured-metadata-schema` (`git rev-parse --show-toplevel` matches; HEAD `ff81140` contains all 4 in-scope commits `14590a3`, `5f22fc6`, `bf602b8`, `ff81140`)
- Files reviewed: 9 changed files (+2181 lines) via the authoritative review package `review/branch-diff.md`, cross-checked line-for-line against the worktree (`database.py` 528, `models.py` 268, `schema.sql` 183, `test_storage_schema.py` 576, `test_metadata_repository.py` 439, `fixtures/metadata_records.py` 166 — all match). Context inputs: `tests/conftest.py`, `pyproject.toml`, plan, primary spec, 3 L2 task reviews, 4 implementer reports, progress ledger.
- Commit range (if not identical to Review range line, explain): `c98f140..ff81140` — identical to the Review range; no other range used.
- Analysis methods: git-diff (review package + read-only `git diff --check` verification), read, grep, one scratch-dir Python stdlib probe (sqlite3 `file:` URI semantics — no project test/build/lint executed), deep-lens reasoning. No test/build/lint suites run; no git mutation; read-only on the worktree.
- Deep review: triggered (S1: 2181 lines / 9 files ≥ thresholds; S2: `schema/`-class paths (`storage/schema.sql`); S3: new storage domain absent from existing knowledge docs; S4: DDL `CREATE TABLE`).
- Lenses applied: Reliability Lens, Performance Lens, Enforcement-Path Lens, Ownership / Derived-State Lens, Data Migration Lens, Input Validation Lens, Testing Lens, Contract Lens, Error Handling Lens. (Only lenses with findings appear below.)

## Findings

### 🔴 Critical
- None. No designed-path data-loss, security, or integrity break was found in the diff. All spec-level hard invariants (3NF, `ON DELETE RESTRICT`, candidate keys, bounded scalar error codes, offline-only, no legacy JSONL access, reservation-only media tables) are present and test-anchored (see Summary verification list).

### 🟡 Warning
- [F-001] `MetadataRepository` accepts any `sqlite3.Connection` without verifying the two invariants `open_database` establishes — silent `row_factory` requirement and potentially silent loss of FK enforcement. `__init__` (`database.py:109-112`) only type-checks `sqlite3.Connection`; the read paths `read_cursor`/`run_stats` index rows by column name (`database.py:452-461`, `506-518`) and therefore require `row_factory = sqlite3.Row`, which only `open_database` sets; and FK enforcement depends on `PRAGMA foreign_keys = ON`, which only `initialize_schema` sets/verifies. A Batch 2 gateway (or Batch 3 CLI) that opens its own connection — e.g. with a custom row factory or a default factory — gets an opaque `TypeError: tuple indices must be integers` at first read, or silently loses orphan rejection. -> Fix: in `MetadataRepository.__init__`, assert `connection.row_factory is sqlite3.Row` and (read-only) `PRAGMA foreign_keys` == 1 (raise `TypeError`/`RuntimeError`), or set/normalize them; document in the class docstring.
  - Source Type: deep-lens: Contract Lens (+ Enforcement-Path Lens), recurring (escalated from L2 Task 2 Minor 4 after plan-level re-judgment)
  - Verification: diff/read/grep anchor — `database.py:109-112` (no factory/pragma check) vs `open_database`/`initialize_schema` (`database.py:88`, `96-124`) as the only place both are set; `database.py:452-461` row-name access.
  - Expected vs observed: expected the repository contract to be self-sufficient for any `sqlite3.Connection` it accepts vs observed implicit dependence on `open_database`-produced state with opaque failure at read time.
  - Confidence: High

- [F-002] `_record_failed_page` (`database.py:402-413`) performs an unguarded terminal-outcome regression: `UPDATE ingestion_runs SET outcome='failed', finished_at=? WHERE run_id=?` has no `outcome='running'` guard, no `finished_at >= started_at` re-check, and bypasses the discipline `finish_run` enforces (`database.py:346-356`). Trigger: a late/replayed failed-page record for a run already terminal (`complete`/`limited`/`failed`) — e.g. gateway retry queue processed after a crash, or a second `record_page(failed_page)` call — flips the run back to `failed` and can move `finished_at` backwards, corrupting run lifecycle evidence consumed by `v_ingestion_run_stats`/Batch 3 CLI. The designed one-pass gateway flow never hits it, which is why L2 graded it Minor; at plan level it is a state-machine integrity hole that Batch 2 will build directly on top of. -> Fix: one-line guard — `WHERE run_id = ? AND outcome = 'running'` (optionally `COALESCE` finished_at to the later value) — or reuse `finish_run`'s validation path.
  - Source Type: deep-lens: Correctness Lens (+ Ownership / Derived-State Lens), recurring (escalated from L2 Task 2 Minor 3 after plan-level re-judgment)
  - Verification: diff/read anchor — `database.py:406-412` (unguarded UPDATE) vs `finish_run` guard set (`database.py:346-363`); no test covers a failed-page record after a terminal run.
  - Expected vs observed: expected terminal run outcomes to be forward-only (per `finish_run`'s own validation) vs observed a repository write path that can regress both `outcome` and `finished_at` with no check.
  - Confidence: High

- [F-003] Commit-boundary matrix is implicit and the class docstring over-claims: `database.py:98-107` says "The low-level methods execute SQL without committing so a caller can group them in one transaction," but `start_run` (`database.py:257`), `finish_run` (`database.py:312`), `initialize_schema` (`database.py:123`), and `_record_failed_page` (via `transaction()`, `database.py:402-413`) all commit unconditionally. Composing `start_run`/`finish_run` inside `with repository.transaction():` — which the docstring invites — silently commits the enclosing group's earlier writes and leaves later writes in a new transaction. Batch 2 must know exactly which methods own commit boundaries; today it must guess. -> Fix: name the two committing methods (and `record_page`'s transaction ownership) explicitly in the class docstring, or make `start_run`/`finish_run` commit-free with explicit commit at gateway call sites.
  - Source Type: deep-lens: Contract Lens (+ Reliability Lens: resource/transaction lifecycle), recurring (escalated from L2 Task 2 Minor 1)
  - Verification: diff/read anchor — `database.py:98-107` claim vs commit sites at `123`, `257`, `312`, and `_record_failed_page`'s `transaction()`.
  - Expected vs observed: expected the docstring's commit contract to hold for all non-`record_page` methods vs observed four unconditional commit sites contradicting it.
  - Confidence: High

- [F-004] Canonical-form ambiguity plus entirely untested API branches that Batch 2 will lock against: (a) `finish_run` docstring (`database.py:266-269`) calls the `IngestionRunRecord` form "preferred", but zero tests exercise it — all 3 test call sites (`test_metadata_repository.py:269-270`, `422`) use the scalar compatibility form, and no prior API exists for it to be "compatible" with; (b) `record_page` accepts both `video=` (singular-or-iterable, 8 test sites) and keyword-only `videos=` (2 test sites) — two overlapping spellings of the same payload slot; (c) `upsert_part`'s explicit-`video_part_id` branch (`database.py:193-217`) has zero test and zero caller coverage (grep: no test constructs `VideoPartRecord(video_part_id=…)`); (d) `start_run`'s retry path (`ON CONFLICT(run_id) DO NOTHING`, "preserving an existing run on retry") is untested — only the FK-parent failure case is. Batch 2 cannot tell which form is the contract. -> Fix: pick one canonical form per method (record form for `finish_run`; `videos=` for `record_page`), test it, and drop or explicitly gate the alternatives before the gateway plan locks this interface.
  - Source Type: deep-lens: Testing Lens (+ Contract Lens), recurring (escalated from L2 Task 2 Minor 2)
  - Verification: grep anchor — `grep finish_run(` tests → 3× scalar form only; `grep video_part_id=` tests/fixtures → no explicit-id usage; `:memory:`/`file:` → no test coverage (see F-006).
  - Expected vs observed: expected the docstring-preferred form to be the tested contract vs observed the complementary untested forms are what callers/tests actually use.
  - Confidence: High

- [F-005] `record_page` failure protocol has two untested, contradictory edges on the core page path: (a) `record_page(failed_page, payloads…)` where **no** write fails silently commits the payload rows together with a `outcome='failed'` page row in one transaction and leaves the run `running` — the separate-transaction failure record only happens in the `except` branch (`database.py:392-401`), so identical input shape produces radically different persistence depending on whether a write raises; (b) for an `outcome='ok'` page whose writes **do** fail, rollback + re-raise happens but **no** failure evidence is persisted — the caller must catch the exception, build a fresh `IngestionPageRecord(outcome='failed', error_code=…)`, and re-call `record_page` with no payload; the docstring (`database.py:345-353`) does not spell out this two-step protocol while the plan bullet ("a failed page records a scalar error code … marks the run/page outcome in a separate transaction") reads as if the repository handles it. Batch 2 must implement this protocol correctly or pages silently lose failure evidence. -> Fix: (a) reject payloads when `page.outcome == 'failed'` (`ValueError`), (b) document the caller-owned failure-recording step in the `record_page` docstring, and add one test per edge.
  - Source Type: deep-lens: Error Handling Lens (+ Contract Lens), manual-reasoning on diff
  - Verification: diff/read anchor — `database.py:415-421` (`has_payload`), `430-451` (transaction + except branch: `_record_failed_page` only under `page.outcome == 'failed'`), tests cover only failed-page-with-failing-writes and failed-page-without-payloads.
  - Expected vs observed: expected one deterministic persistence outcome per input shape vs observed commit-vs-failure-evidence divergence keyed on an incidental write exception.
  - Confidence: High (static reasoning; both edges untested)

- [F-006] `open_database`'s `file:` URI special-case is untested and behavior is build-dependent: `_resolve_database_path` returns `file:`-prefixed values verbatim (`database.py:55-56`), then passes them to `sqlite3.connect(...)` **without** `uri=True` (`database.py:88`). The documented Python contract (`sqlite3.connect(uri=False)` default) is literal-path interpretation; URI parsing only activates via `uri=True` or a SQLite build compiled with `SQLITE_USE_URI`. On the current control environment URI parsing happens to be active (scratch-dir probe: `connect("file:probe2.db")` → `probe2.db` created, no literal `file:` file), but on builds where URI filenames are disabled (upstream amalgamation default) the same call silently creates a literal file named `file:…` at the wrong path. A Batch 3 caller opening a read-only/URI-style database gets silent wrong behavior depending on which machine runs the CLI. -> Fix: drop the `file:` branch (document that callers should pass plain paths) or route URI-shaped values to a `connect(..., uri=True)` call, and add a test; `:memory:` handling is fine (documented SQLite special string).
  - Source Type: deep-lens: Reliability Lens (+ Input Validation Lens), manual-reasoning + scratch-dir stdlib probe (input-output comparison; not a project test run)
  - Verification: diff/read anchor — `database.py:55-56` vs `database.py:88` (no `uri=` parameter anywhere in the file); probe output recorded in Summary; no test touches `file:`/`:memory:` (grep).
  - Expected vs observed: expected the special-cased input form to behave per the documented `sqlite3` contract on any build vs observed unspecified, build-dependent behavior with zero test coverage.
  - Confidence: Medium-High (mechanism documented by stdlib API; environment-dependent manifestation)

### 🟢 Suggestion
- [F-007] `models.py:255-268` comment/`__all__` contradiction: "Internal validation helpers are intentionally not part of the public model API" followed by exporting `validate_error_code` and the four `ALLOWED_*` sets. Either make them private (let consumers derive from the `Literal` types) or reword the comment — and consider moving the assignment block above the dataclasses for organization. -> Verification: read anchor `models.py:255-268`. Expected vs observed: comment says internal-only vs `__all__` publishes them.
- [F-008] Failed page accepts `error_code=None` (`models.py:186-198`; schema CHECKs are outcome-agnostic, `schema.sql:70-72`). The implementer resolved this as spec-intended (spec declares `error_code` nullable), which is defensible; keep it only as an explicit contract note for Batch 2 (gateway owns "failed ⇒ bounded code") or tighten at the record boundary (`outcome='failed'` ⇒ non-null bounded code). -> Verification: read anchor + implementer-task-3-report.md self-review note 2. Expected vs observed: brief wording "a failed page records a scalar error code" vs nullable-in-contract reality.
- [F-009] Secret-prevention boundary is record-level only: `schema.sql:61,72` bound `error_code`/`last_error_code` to length ≤ 64 with no shape CHECK, so raw SQL bypassing the repository can persist arbitrary ≤64-char text. Matches the plan (repository is the only accepted input path) and is now documented for Batch 2; consider a `CHECK (col GLOB '[A-Za-z0-9_.:-]*' AND length(col) <= 64)` as defense-in-depth mirroring `models._error_code` (`models.py:47-54`). -> Verification: read anchor schema vs `models.py:47-54`. Expected vs observed: invariant "bounded scalar codes only" enforced at one layer vs two-layer possibility.
- [F-010] Package export asymmetry: `storage/__init__.py:1-17` re-exports `DatabaseConnection` (a plain `TypeAlias`) plus helpers, but not `MetadataRepository` nor the `models` records — Batch 2/3 must import from submodules. Either re-export the repository + models for a single import surface or slim `__init__` consistently. -> Verification: read anchor `storage/__init__.py` vs `database.py.__all__`. Expected vs observed: primary consumer types reachable via package root vs submodule-only.
- [F-011] FK-child side lacks indexes for `ON DELETE RESTRICT` parent deletes on the hot parents: `videos.mid` and `ingestion_runs.mid` have no index (schema has no `CREATE INDEX` at all); deleting a user/run triggers per-row child scans. Negligible at current archive scale; add `CREATE INDEX videos(mid)` / `ingestion_runs(mid)` when gateway ingest volume lands. `v_ingestion_run_stats`'s full-scan GROUP BY is fine at run-count scale. -> Verification: read anchor `schema.sql` (PK/UNIQUE implicit indexes only; FK list) + Performance Lens. Expected vs observed: RESTRICT enforcement cost bounded vs full child scan per parent row.
- [F-012] Read-path shape/validation inconsistencies: `read_cursor` returns a typed `CursorRecord` while `run_stats`/`list_pending_parts` return raw `sqlite3.Row`/lists (`database.py:437-461`, `490-518`); and both `read_cursor(mid)`/`run_stats(run_id)` raise `ValueError` for what are type errors (`isinstance` failures), unlike the `TypeError` discipline used everywhere else. Minor consistency polish for Batch 3 CLI consumption. -> Verification: read anchor. Expected vs observed: uniform typed/validation convention vs mixed.
- [F-013] `upsert_part`'s two branches (`database.py:169-217`) duplicate the identical `ON CONFLICT(bvid, page_index) DO UPDATE` block; a single statement including `video_part_id` (NULL ⇒ SQLite allocates) would remove the duplicated SQL and with it the untested F-004(c) surface. -> Verification: read anchor. Expected vs observed: one logical upsert vs two near-identical statements.
- [F-014] `upsert_video`'s aid policy (`aid = COALESCE(videos.aid, excluded.aid)`, `database.py:150` — first non-null aid wins, backfills `NULL`, never overwrites) is now test-pinned (`test_re_upsert_backfills_missing_aid_and_keeps_existing_aid`) but undocumented; state the stable-identifier policy in the docstring. -> Verification: read anchor. Expected vs observed: policy discoverable from tests only vs stated at the API.

### ⚪ Unconfirmed
- [F-015] Implementer-reported runtime pass counts (Task 1: 7→8 focused; Task 2: 8 focused / 16 combined / 709 full; Task 3: red `2 failed, 16 passed` → green `21 passed in 0.56s`, full suite `714 passed in 40.23s`) — channel gap: runtime evidence is implementer-reported; the mandatory QA gate re-run is still pending, and L3/QC does not re-execute suites. (`git diff --check` for the range was **independently verified clean by this review**; not part of this item.)
- [F-016] Built wheel/sdist actually ships `schema.sql` — channel gap: package-data declaration (`pyproject.toml:29-31`) and the offline resource contract test are present, but no wheel build was ever performed (implementer-task-1-fix-report.md discloses the environment lacks pip/setuptools/build); QA should confirm on a real build artifact.
- [F-017] QA re-run interpreter/command parity — channel gap: the feature worktree has no local `.venv` (verified absent by this review), so the prescribed run command only works via the control checkout's `.venv` interpreter and pytest's default **prepend** import mode (`pyproject.toml` sets no `--import-mode`); QA must reuse the identical interpreter path and command or the `from fixtures.metadata_records import …` tests will not resolve.

## Source Trace
- Finding ID: F-001
- Source Type: deep-lens: Contract Lens; read; grep
- Source Reference: `src/bili_asr/storage/database.py:109-112` (constructor), `452-461` (row-name access) vs `88`, `96-124` (only place row_factory/pragma are set)
- Confidence: High
- Note: escalation of L2 Task 2 Minor 4 after plan-level re-judgment (Batch 2 contract readiness).

- Finding ID: F-002
- Source Type: deep-lens: Correctness Lens; read
- Source Reference: `src/bili_asr/storage/database.py:402-413` (unguarded UPDATE) vs `346-363` (`finish_run` guards); test gap: no failed-page-after-terminal-run test
- Confidence: High
- Note: escalation of L2 Task 2 Minor 3 (terminal-outcome regression path).

- Finding ID: F-003
- Source Type: deep-lens: Contract Lens; read
- Source Reference: `database.py:98-107` docstring vs commit sites `123`, `257`, `312`, `_record_failed_page` transaction
- Confidence: High
- Note: escalation of L2 Task 2 Minor 1 (composition footgun for the gateway).

- Finding ID: F-004
- Source Type: deep-lens: Testing Lens; grep
- Source Reference: `database.py:266-269` (finish_run dual form), `340-397` (`video`/`videos`), `193-217` (explicit-id branch); `tests/test_metadata_repository.py:269-270,422`, `55,236`
- Confidence: High
- Note: escalation of L2 Task 2 Minor 2; `video=`/`videos=` dual form re-confirmed live in tests.

- Finding ID: F-005
- Source Type: deep-lens: Error Handling Lens; manual-reasoning
- Source Reference: `database.py:345-353` (docstring), `415-421` (`has_payload`), `430-451` (transaction + except branch); test suite covers neither edge
- Confidence: High
- Note: plan Task 2 bullet vs implementation contract; new at plan level (not in L2 Minors).

- Finding ID: F-006
- Source Type: deep-lens: Reliability Lens; manual-reasoning; scratch-dir stdlib probe (input-output comparison)
- Source Reference: `database.py:55-56` vs `88`; probe: Python 3.12.3 / SQLite 3.45.1 parses `file:` without `uri=True` on this build (URI-enabled libsqlite3), while the documented default is literal-path
- Confidence: Medium-High
- Note: new at plan level; not in L2 Minors.

- Finding ID: F-007
- Source Type: read
- Source Reference: `src/bili_asr/storage/models.py:255-268`
- Confidence: High
- Note: L2 Task 2 Minor 5 confirmed.

- Finding ID: F-008
- Source Type: read; doc-rule
- Source Reference: `models.py:186-198`; `schema.sql:70-72`; plan Task 2 bullet; implementer-task-3-report.md note 2
- Confidence: High
- Note: L2 Task 2 Minor 7, resolved as spec-intended by implementer; kept as polish note.

- Finding ID: F-009
- Source Type: read; deep-lens: Enforcement-Path Lens
- Source Reference: `schema.sql:61,72` vs `models.py:47-54` (`_ERROR_CODE_PATTERN`)
- Confidence: High
- Note: carries Task 3 reviewer ⚠️2 to Batch 2 context.

- Finding ID: F-010
- Source Type: read
- Source Reference: `src/bili_asr/storage/__init__.py:1-17`
- Confidence: High

- Finding ID: F-011
- Source Type: deep-lens: Performance Lens; read
- Source Reference: `schema.sql` (no `CREATE INDEX`; FK list) — `videos.mid`, `ingestion_runs.mid` child lookups
- Confidence: Medium (scale-dependent)

- Finding ID: F-012
- Source Type: read
- Source Reference: `database.py:437-461`, `490-518`
- Confidence: High

- Finding ID: F-013
- Source Type: read
- Source Reference: `database.py:169-217`
- Confidence: High

- Finding ID: F-014
- Source Type: read
- Source Reference: `database.py:150`; `tests/test_metadata_repository.py:369-383`
- Confidence: High

- Finding ID: F-015
- Source Type: read (implementer reports); assignment-ci-note
- Source Reference: implementer-task-1-report.md:40-45, implementer-task-2-report.md:34-53, implementer-task-3-report.md:45-57; progress.md:39-41,82
- Confidence: n/a (evidence-failure state)
- Note: runtime proof reserved for the mandatory QA gate.

- Finding ID: F-016
- Source Type: read
- Source Reference: implementer-task-1-fix-report.md:48; progress.md:13-15; `pyproject.toml:29-31`; `test_schema_sql_is_declared_and_read_as_package_resource`
- Confidence: n/a (evidence-failure state)

- Finding ID: F-017
- Source Type: read; bash (read-only ls)
- Source Reference: feature worktree has no `.venv` (verified); `pyproject.toml` `[tool.pytest.ini_options]` has no import-mode override (default prepend); progress.md:84
- Confidence: n/a (evidence-failure state)

## Summary
| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟡 Warning | 6 |
| 🟢 Suggestion | 8 |
| ⚪ Unconfirmed | 3 |

**Verdict**: Request Changes

**Verdict rationale.** No Critical findings; the six Warnings are all unresolved at plan level, so per the verdict rules this cannot be Approve. None of them breaks the plan's own acceptance criteria on the designed path — every plan Task bullet has a test, and every statically checkable acceptance criterion verified. They are contract-integrity gaps that Batch 2 (gateway ingestion) and Batch 3 (CLI) would otherwise have to guess on: the repository's connection-state requirements (F-001), the commit-boundary matrix (F-003), the canonical method forms (F-004), the page-failure recording protocol (F-005), an unguarded terminal-outcome regression on the run state machine (F-002), and a build-dependent untested input branch (F-006). All fixes are small (guards, docstrings, form selection, tests) and should land before the gateway plan locks this repository contract; PM owns disposition (close/defer/fix) per the zero-residual policy — this report reports only.

**Whole-branch spec compliance (verified from the diff, static):**
- 3NF holds: no `work_id`/part-count/run-aggregate columns in any base table (asserted per table in `test_views_compute_work_id…` and `test_schema_inspection…`); `work_id` computed only in views + `VideoPartRecord.work_id` property.
- All FKs declared `ON DELETE RESTRICT`; tests assert `PRAGMA foreign_key_list` `on_delete == "RESTRICT"` for every FK and orphan rejection at both schema and repository layers.
- Unique candidate keys present: `(bvid, page_index)` on `video_parts`, `aid` on `videos`, `sha256`/`storage_key` on `audio_objects`, `(model_name, revision)` on `asr_models`, `(video_part_id, source_kind, version)` on `transcripts` — all with duplicate-rejection tests.
- Bounded scalar error codes only: record boundary enforces `^[A-Za-z0-9_.:-]+$` ≤ 64 chars (schema bounds length ≤ 64); no-secret test proves cookies/signed URLs/raw JSON/tracebacks are rejected and absent from persisted columns. Record-boundary-vs-column-CHECK split is documented and carried to Batch 2 (F-009).
- Offline-only: imports are stdlib-only (`sqlite3`, `dataclasses`, `re`, `math`, `pathlib`, `importlib.resources`, `contextlib`, `typing`); grep finds no `bilibili_api`/`requests`/network modules and no `manifest.jsonl`/`meta-cursor.json`/`run-ledger.jsonl` references; fixtures are literal/deterministic (no wall-clock, no network, no credentials).
- Media/transcript tables are schema reservations only: five reservation tables created empty with matching column manifests; no writes or reads anywhere in the diff.
- The three views match the primary spec's SQL verbatim; `v_ingestion_run_stats`'s double LEFT JOIN fan-out is neutralized by `COUNT(DISTINCT)` (test-verified at `(2,2)` over 3 discovery rows).
- Spec-conformant deliberate trade-off (documented by implementer + Task 1 review): `ingestion_discoveries` has no composite FK to `ingestion_pages` because the locked ordering inserts discoveries before the page row; run/video FKs still enforced.
- Plan Interfaces delivered: all 11 repository methods, all 6+1 record dataclasses, the 3 views, `open_database`/`initialize_schema`/`DatabaseConnection`, `duration_to_ms` (`floor(s*1000)`), `normalize_page_index` (`page-1`) — each offline-test-verified. `git diff --check` over `c98f140..ff81140` independently verified clean by this review.
- STOP conditions: none triggered. Scope is surgical: 9 files, no piggyback, no legacy artifacts touched.

**⚠️ For PM/QA (genuinely unverifiable from the diff):** runtime pass counts and full-suite green (F-015, QA gate re-run pending); wheel/sdist packaging of `schema.sql` on a real build (F-016); interpreter + import-mode command parity for QA re-runs — control checkout `.venv`, default pytest prepend mode, exact focused commands (F-017). PM dispositions cross-checked where the diff can verify them: record-level secret-prevention boundary confirmed (F-009); control `.venv`/prepend-mode dependencies confirmed from config (F-017); pass counts remain trusted-implementer evidence until QA re-runs.

---

## Revalidation

### Scope (targeted re-review — fix wave 1)

- plan_id: 20260909-structured-metadata-schema
- Re-validation range / Diff basis: `ff81140411e9e04756055657569c39a0a0c5c2d4..6d76ea4068d04d30e3e4f8123454020c901d4461` (fix wave 1 on top of this seat's reviewed implementation head `ff81140`), read **once** as the authoritative package `review/fix-1-diff.md` (6 files, +460/−181)
- Working branch / Review cwd: `feature/20260909-structured-metadata-schema` / `/root/workspace/bilibili-asr-archive/.worktrees/20260909-structured-metadata-schema` — taken from the assignment + diff artifact; git commands not re-run and checkout not mutated (assignment constraint). Worktree reads of every changed region matched the diff's post-images line-for-line, confirming the checkout is at the fix head.
- Inputs: this report (original wave), `review/qc-consolidated.md` (W1–W6 + S-fix-1…5 + carry/drop dispositions), `implementer-qc-fix-1-report.md` (claims treated as unverified until diff-checked).
- Analysis methods: fix-diff read (single pass), read, grep (worktree, read-only), plus one cross-read of `review/branch-diff.md` to classify the pre-existing `record_page` no-payload branch. No tests/builds/lints executed; no git mutation; only this file written.
- Report Timestamp: 2026-09-10T10:37Z

### Per-finding verification — original Warnings F-001…F-006

| ID | Finding | Status | Evidence (diff/read/grep anchors) |
|----|---------|--------|-----------------------------------|
| F-001 | constructor accepts unprepared connections | **Resolved** | `database.py:136-143`: `row_factory is not sqlite3.Row` → `TypeError`; `PRAGMA foreign_keys != 1` → `ValueError` (row_factory checked first, so the pragma read is Row-indexed); requirement documented in the class docstring (`database.py:131-133`). Tests: `test_constructor_rejects_a_connection_without_row_factory` (bare connect), `test_constructor_rejects_a_connection_with_foreign_keys_disabled` (asserts the pragma is actually 0 before constructing). |
| F-002 | unguarded terminal-outcome regression | **Resolved** | `database.py:407-414`: run failure UPDATE now guarded `WHERE run_id = ? AND outcome = 'running'`; page evidence still commits in the same transaction (stale evidence preserved, run untouched). qc2's re-finish extension also closed: `finish_run` raises `IntegrityError` on a stored non-`running` outcome before validating the new outcome (`database.py:286-295`). Tests: `test_late_failed_page_after_terminal_run_keeps_run_outcome_unchanged` (run stays `('complete', 300)` while the page row persists `failed`/`stale_page_result`) and `test_finish_run_rejects_refinishing_a_terminal_run` (second finish → `IntegrityError`, run unchanged). `changes()==0` intentionally a documented no-op — consistent with YAGNI, no invented check. |
| F-003 | commit-boundary docstring over-claim | **Resolved** | `database.py:113-129`: explicit per-method commit matrix (`start_run`/`finish_run` commit independently; `record_page` owns one transaction plus the no-payload failed evidence transaction; the five low-level writers never commit, composable via `transaction()`; the three readers never write/commit) + an explicit warning against composing the three committing methods inside a `transaction()` group. `initialize_schema` (`database.py:76-79`) and `open_database` (`database.py:88-98`) docstrings now truthful. |
| F-004 | canonical-form ambiguity + untested branches | **Resolved (a–d)** | (a) scalar `finish_run` removed; the record form is the only form (`database.py:275-309`); ordering baseline is the DB stored `started_at` — stronger than the old record-field baseline (consolidated W2 baseline alignment honored); pinned by `test_finish_run_record_form_validates_against_database_started_at` (happy path + DB-baseline violation via a *valid* record `started_at=50/finished_at=60` vs stored 101, so the rejection is genuinely the DB-baseline check + non-terminal outcome + `finished_at=None`). Dropped scalar-form checks verified unreachable: `IngestionRunRecord.__post_init__` enforces non-empty `run_id` and rejects bool/non-int `finished_at` (`models.py:162-176`, `models.py:29-34`). The 3 scalar call sites are rewritten to the record form (diff). (b) `record_page` reduced to one `videos: Iterable[VideoRecord] = ()` param in locked order, dual `video` branch and keyword-only split removed (`database.py:333-341, 363`); all 6 test call sites updated; grep: zero `video=` remaining branch-wide. (c) explicit-`video_part_id` INSERT branch removed; non-None id → `ValueError` before any write (`database.py:206-207`); pinned by `test_upsert_part_rejects_an_explicit_video_part_id`; grep: no other explicit-id constructor usage. (d) `start_run` retry `ON CONFLICT(run_id) DO NOTHING` removed; a duplicate run_id now raises the PK `IntegrityError` (`database.py:244-273`); pinned by `test_start_run_rejects_a_duplicate_run_id`. |
| F-005 | failure-protocol edges | **Resolved (a+b)** | (a) `record_page` rejects payloads on a `'failed'` page before any write (`database.py:373-374`) — the old silent "commit payloads alongside a failed page row while the run stays running" path is now impossible, so persistence is deterministic per input shape; pinned by `test_record_page_rejects_payloads_on_a_failed_page` (also asserts nothing was persisted). (b) the two-step caller-owned failure protocol is documented in the docstring (`database.py:342-360`) and pinned end-to-end by `test_ok_page_write_failure_rolls_back_and_caller_records_failure` (rollback: cursor byte-identical, videos/parts/pages counts unchanged, run stays `running`/`NULL`; then the fresh bounded failed record replayed with no payloads → evidence `failed`/`foreign_key` + run transition `('failed', 201)`). The dead except-handler was removed — its only reachable case is now rejected upfront; `transaction()` alone owns commit/rollback/re-raise. Correct simplification, no speculative error handling kept. |
| F-006 | `file:` URI branch build-dependent | **Resolved as dispositioned** | Branch dropped — the consolidated W6 fix offered drop *or* `uri=True`; PM chose drop. `_resolve_database_path` now special-cases only `:memory:` (`database.py:54-72`); both `_resolve_database_path` and `open_database` docstrings state URI strings are not interpreted and callers pass plain paths, so no build-dependent special surface remains in the code's own contract. `:memory:` retained (the archive-root heuristic would otherwise mkdir it) and pinned by `test_open_database_memory_database_is_initialized` (schema init, FK pragma, insert+commit on `:memory:`). |

### Suggestion dispositions vs consolidated (zero-residual)

| ID | Disposition | Status |
|----|-------------|--------|
| F-007 | S-fix-1 (fix now) | **Resolved** — comment now truthfully describes the exported validation surface as public (`models.py:255-257`). |
| F-008 | accepted with rationale (spec-intended: `error_code` nullable per spec) | Consistent — matches this report's fallback framing; the Batch-2 note is covered by S-carry-1's record-level-validation rule. No code change required. |
| F-009 | S-carry-1 (carried to Batch 2, durable roadmap) | Consistent — record boundary stays the secret-prevention SSOT; Batch 2 must inherit record-level validation as a hard contract rule. |
| F-010 | S-fix-2 (fix now) | **Resolved** — package root re-exports `MetadataRepository`, all 7 record dataclasses, the 4 `Literal` aliases, the 4 `ALLOWED_*` sets, `validate_error_code`, and the 5 bootstrap helpers; docstring declares the single import surface (`storage/__init__.py`). |
| F-011 | S-drop-1 (dropped until ingest volume lands) | Consistent — matches this report's own scale-dependent framing. |
| F-012 | — | **Not addressed in the fix wave; no disposition row in `qc-consolidated.md`** (the consolidated's "qc1 F-012" citation is qc1's own `status=` naming finding, not this seat's read-path shape/validation finding). Remains open (🟢). PM owes a zero-residual disposition (fix as nit, drop, or carry). |
| F-013 | incidentally fixed by W2 | **Resolved** — `upsert_part` is now a single statement; the duplicated `ON CONFLICT` SQL disappeared with the explicit-id branch (`database.py:208-230`). |
| F-014 | — | **Not addressed in the fix wave; no disposition row in `qc-consolidated.md`** (`upsert_video`'s aid-COALESCE policy is still documented only by its test). Remains open (🟢). PM owes a zero-residual disposition. |

### New findings from the fix diff (this seat)

#### 🟢 Suggestion
- [F-018] The rewritten `test_ok_page_write_failure_rolls_back_and_caller_records_failure` dropped the old test's user-row assertion (`display_name == "未明子"`), which proved the **first** write in the locked order rolled back; rollback of the transaction head is now proven only indirectly (the cursor/count/run assertions cover the tail and middle). -> Fix: one-line `SELECT display_name FROM bilibili_users` assertion before the failure replay.
  - Verification: diff anchor (removed line inside the replaced test) vs the new assertion set.
  - Expected vs observed: head-to-tail rollback proof vs tail+middle only.
- [F-019] The new commit matrix names the payload transaction and the no-payload `'failed'` evidence transaction but not the no-payload non-failed page (ok/empty/risk_interrupted), which also commits its own single-write transaction. Behavior verified correct and **unchanged** from the reviewed implementation (`database.py:379-381`; the pre-existing shape was confirmed against `review/branch-diff.md` lines 422-428, so no undocumented behavior change). -> Fix: one clause in the class matrix / `record_page` docstring to make the matrix exhaustive.
  - Verification: read anchor + old/new diff comparison.
  - Expected vs observed: exhaustive commit matrix vs one unnamed commit sub-case.

### Regression checks (from the diff, static)

- `schema.sql` untouched: no hunk in the fix diff (6 files; the guards are application-level) — no DDL change, no denormalization, no 3NF impact.
- Locked transaction order intact: payload path user → videos → parts → discoveries → cursor → page outcome → commit unchanged (`database.py:384-395`).
- 3NF intact; FK `ON DELETE RESTRICT` intact (schema untouched; the constructor now *requires* the FK pragma, strengthening enforcement).
- Bounded scalar error codes intact: new exception messages are static strings or interpolate only caller-supplied key material (`run_id`) and CHECK-constrained DB values (stored outcome); nothing is persisted outside the record boundary.
- Offline-only intact: new imports are stdlib-only (`os`, `re`, `typing.get_args`) plus intra-package imports.
- Grep sweeps: zero `video=` remaining; zero bare `status=` in storage tests/fixtures (remaining `status=` matches are unrelated ManifestStore helpers from prior plans); no repository-API callers outside `src/bili_asr/storage/` + its contract tests, so the canonicalization breaks no other suite.
- Baseline-test claim verified from the diff: the 21 pre-existing focused tests are preserved, and the claimed **3 legitimate shape adjustments** are confirmed — (1) 6× `video=`→`videos=`, (2) 3× scalar `finish_run`→record form, (3) `test_failed_page_rolls_back…` replaced by `test_ok_page_write_failure…` with its invariants preserved and extended. Two further pre-existing-test edits are separately dispositioned consolidated items, not untracked adjustments: S-fix-3 (LIKE-sweep drop) and S-fix-5 (fixture `status=`→`processing_status=` + one call site).
- Runtime counts (implementer-reported, not re-run): internally consistent — the red list is exactly the 8 guard/rejection tests that cannot pass pre-fix (the record-form and `videos=` call-site rewrites pass under both old and new signatures, correctly absent from the red list); 21 + 10 net-new = 31 focused; 693 non-storage tests unchanged (724−31 = 714−21); the 2 characterization tests are green-at-birth.

### Updated Summary

| Severity | Count (original → now) |
|----------|------------------------|
| 🔴 Critical | 0 → 0 |
| 🟡 Warning | 6 → 0 (F-001…F-006 all resolved) |
| 🟢 Suggestion | 8 → 4 open (F-012, F-014 carried over without a consolidated disposition; F-018, F-019 new; F-007/F-008/F-009/F-010/F-011/F-013 resolved or dispositioned) |
| ⚪ Unconfirmed | 3 → 3 (F-015…F-017 stand as QA-routed runtime-evidence items — L3 evidence channels intact; per the consolidated's precedent these do not constitute an Unconfirmed verdict) |

**Verdict**: Approve

**Verdict rationale (revalidation).** All six Warnings raised by this seat are resolved with verifiable diff/read/test anchors, and the fix diff introduces no Critical/Warning-class regression: the change is surgical (6 files, no `schema.sql` hunk), behavior-preserving outside the intended guards, and every surviving API form is now test-pinned. Two new 🟢 polish findings (F-018, F-019) and two carried-over 🟢 items without a consolidated disposition (F-012, F-014) remain — suggestion-class findings do not block under the verdict rules; PM owns their zero-residual disposition (fix as nits, drop, or carry). Approve is the L3 diff/logic verdict on the fix wave and the updated branch state; it does **not** waive the mandatory QA gate, which still owns F-015 (fix-wave pass counts 31 focused / 724 full, implementer-reported), F-016 (wheel/sdist actually ships `schema.sql` on a real build), and F-017 (interpreter + prepend-import-mode parity for QA re-runs).

### Round 2 — final convergence micro-fix (targeted: this seat's S-fix-7/8/9a/9b + diff quality)

#### Scope (targeted re-review round 2)

- plan_id: 20260909-structured-metadata-schema
- Re-validation range / Diff basis: `6d76ea4068d04d30e3e4f8123454020c901d4461..2063a1a` (round-2 micro-fix on top of this seat's round-1-revalidated head `6d76ea4`), read **once** as the authoritative package `review/fix-2-diff.md` (2 files, +132/−16)
- Working branch / Review cwd: `feature/20260909-structured-metadata-schema` / `/root/workspace/bilibili-asr-archive/.worktrees/20260909-structured-metadata-schema` — from assignment + diff artifact; git not re-run, checkout not mutated. Worktree reads of every changed region (class docstring, `upsert_video`, `record_page`, `_record_failed_page`, the three read paths, all three test-file hunks) matched the diff's post-images line-for-line, confirming the checkout is at the round-2 head.
- Inputs: this report (round-1 Revalidation — F-012/F-014/F-018/F-019), `review/qc-consolidated.md` (`## Revalidation round 1` + S-fix-6…9 dispositions), `implementer-qc-fix-2-report.md` (claims treated as unverified until diff-checked).
- Analysis methods: fix-diff read (single pass), read, grep (worktree, read-only — full `raise TypeError|ValueError` sweep of `database.py`). No tests/builds/lints executed; no git mutation; only this file written.
- Report Timestamp: 2026-09-10T11:00Z

#### Per-item verification (this seat's four round-2 items)

| Item | Finding | Status | Evidence (diff/read/grep anchors) |
|------|---------|--------|-----------------------------------|
| S-fix-7 | F-012 read-path shape/validation inconsistency | **Resolved** | Exception split: `read_cursor` (`database.py:480-483`) — bool/non-int `mid` → `TypeError("mid must be an integer")`, `mid < 1` → `ValueError`; `run_stats` (`:566-569`) — non-str → `TypeError`, blank → `ValueError` (`None` all-runs form unchanged, handled before the isinstance); `list_pending_parts` (`:539-542`) — bool/non-int `limit` → `TypeError`, `limit < 1` → `ValueError`. **Disclosure sound:** F-012's prose named `read_cursor`/`run_stats` ("both"), but its own Source Trace anchor (`database.py:437-461, 490-518` at the reviewed head) spans all three read paths and its stated expected state is a *uniform* read-path validation convention — normalizing the third path is the consistent completion of the dispositioned fix (same one-branch change class, test-pinned, no API redesign), not scope creep. **One module discipline confirmed by grep sweep:** all 28 `raise` sites in `database.py` — every isinstance failure raises `TypeError` (duration ×2, page-number, connection, row_factory, six record-type checks, mid/limit/run_id, cursor), every `ValueError` is a value/range/state condition (finite/non-negative, ≥1, FK pragma, non-None `video_part_id`, terminal outcome, missing `finished_at`, three clock baselines, failed-with-payload, positive ints, non-empty string). **Return shapes documented, NOT redesigned:** class docstring paragraph (`:129-135`) states the two shapes (typed `CursorRecord` vs raw `sqlite3.Row` view data) and the module-wide TypeError/ValueError argument discipline; per-method docstrings (`:475-479`, `:534-537`, `:555-559`); all three signatures unchanged — typed read-model unification stays carried to Batch 3 per the consolidated disposition. Test: `test_read_path_validation_splits_type_errors_from_value_errors` (`tests/test_metadata_repository.py:596-619`) pins 5 `TypeError` + 3 `ValueError` cases across all three methods. |
| S-fix-8 | F-014 aid-COALESCE policy undocumented | **Resolved** | `upsert_video` docstring (`database.py:182-187`) states the policy as dispositioned — first non-`None` `aid` wins, stored `NULL` backfilled, known `aid` never overwritten; SQL untouched (`:190-209`, `aid = COALESCE(videos.aid, excluded.aid)`) and the docstring claim matches the COALESCE semantics exactly; still pinned by the unmodified `test_re_upsert_backfills_missing_aid_and_keeps_existing_aid`. |
| S-fix-9a | F-018 dropped user-row rollback assertion | **Resolved** | `tests/test_metadata_repository.py:161-167`: assertion restored before the failure replay — `SELECT display_name FROM bilibili_users` == `"未明子"` with a comment naming what it proves. It is a genuine discriminator: the failing call's user write (`display_name="must roll back"`) would surface here if the transaction head had committed. Single-row table (`mid` PK) → `fetchone()` deterministic. Green-at-birth consistent with the red list (exactly the 2 new behavior tests) — the round-1 loss was assertion coverage, not behavior. |
| S-fix-9b | F-019 commit matrix omission | **Resolved** | Class matrix (`database.py:118-122`) now names the no-payload non-failed sub-case ("…either the ``'failed'`` evidence transaction (page row plus the run's failure transition) or the ok/empty/``risk_interrupted`` page-outcome write"); matching clause in the `record_page` docstring (`:374-376`). Matrix now exhaustive: `start_run`, `finish_run`, `record_page` (payload transaction + both no-payload sub-cases), the five non-committing writers, the three non-writing readers. Behavior verified unchanged from the reviewed implementation. |

**qc1's S-fix-6 (verified by this seat for regression/diff quality only — disposition owned by qc1):** the new failure-transition clock guard (`database.py:431-441`) sits inside `transaction()` before any write (reject ⇒ structurally nothing persisted), applies only while the run is `running` (`run_row is not None` and `outcome == 'running'`), reuses `finish_run`'s exact message and DB baseline (`:316-317` vs `:441`, both against `int(stored started_at)`), and is type-safe by the record contract — `IngestionPageRecord.__post_init__` (`models.py:188-198`) guarantees `finished_at` is a required non-negative `int` ≥ `started_at`, so the guard's comparison can never see `None`. Terminal-run skip (evidence persisted, run untouched) and unknown-run FK failure are unchanged and still test-pinned.

**Docstring truthfulness (implementer self-caught correction — verified):** the round-1 "The page evidence is always upserted" wording is gone. `_record_failed_page`'s docstring (`:421-430`) now ties the evidence upsert to the transition's committed transaction and states the rejection edge ("a page clock below the run's start raises ``ValueError`` and nothing is persisted"); `record_page`'s docstring (`:378-382`) documents the same baseline + rejection. Accurate for every reachable state: running + valid clock ⇒ evidence + transition commit together; running + stale clock ⇒ `ValueError`, nothing persisted; terminal run ⇒ evidence only, run untouched; unknown run ⇒ page-FK `IntegrityError` (malformed caller, outside the documented contract).

#### Regression checks (round-2 diff, static)

- `schema.sql` byte-untouched (the diff contains only `database.py` + `test_metadata_repository.py`): no DDL change; 3NF and `ON DELETE RESTRICT` intact; constructor still fail-fasts on `row_factory`/FK pragma (`database.py:146-153`).
- Locked payload-transaction order unchanged: user → videos → parts → discoveries → cursor → page outcome → commit (`database.py:407-418`); only docstring hunks sit above it.
- Round-1 guards unchanged: W1 guarded run UPDATE `WHERE run_id = ? AND outcome = 'running'` intact (`:443-450`); `finish_run` re-finish rejection intact (`:301-310`); constructor fail-fast intact; no diff hunk touches them.
- Bounded scalar error codes intact: no new persisted error values; new exception messages are static strings; `int(run_row["started_at"])` reads but never persists.
- Offline-only intact: zero new imports in the diff.
- No speculative branches: the S-fix-6 guard is one condition; no config/abstraction/fallback added; the `list_pending_parts` extension is the disclosed same-class completion, test-pinned.
- Test-file delta is exactly 3 hunks (restored assertion + 2 new tests); zero pre-existing tests edited this round — consistent with the implementer's 31→33 focused and 724 − 31 + 33 = 726 full arithmetic; the red list (2 failures) is exactly the two new behavior tests, so the TDD red→green claim is internally consistent. Runtime counts remain implementer-reported (QA gate owns the re-run).
- Observations verified and dismissed (no finding raised, no residual): (a) the class-docstring shape sentence "a list for the no-argument form" also holds for `list_pending_parts`' `limit` form — the `list[sqlite3.Row]` signature is the normative shape and the sentence asserts nothing false; (b) the `TypeError` messages "…or None" describe the accepted parameter set although `None` never reaches that branch — standard message convention, no action.

#### Updated Summary (round 2)

| Severity | Count (original → round 1 → now) |
|----------|-----------------------------------|
| 🔴 Critical | 0 → 0 → 0 |
| 🟡 Warning | 6 → 0 → 0 |
| 🟢 Suggestion open | 8 → 4 open (F-012/F-014/F-018/F-019) → **0** (all four resolved; no new findings) |
| ⚪ Unconfirmed | 3 → 3 → 3 (F-015 counts updated 31/724 → 33/726; QA-gate-routed) |

**Verdict**: Approve

**Verdict rationale (revalidation round 2).** All four round-2 items raised by this seat are resolved with verifiable diff/read/test anchors; the disclosed `list_pending_parts` extension is judged sound (inside F-012's own anchor range and its uniform-convention expected state, same change class, test-pinned); the module now carries one exception discipline (28-site grep sweep); and the round-2 diff introduces no Critical/Warning-class regression — 2 files, `schema.sql` byte-untouched, locked order and round-1 guards unchanged, no speculative surface added, and the new clock guard is record-contract type-safe. Approve is the L3 diff/logic verdict on the round-2 wave and the final branch state; it does **not** waive the mandatory QA gate, which still owns F-015 (round-2 pass counts 33 focused / 726 full, implementer-reported), F-016 (wheel/sdist actually ships `schema.sql` on a real build), and F-017 (interpreter + prepend-import-mode parity for QA re-runs).
