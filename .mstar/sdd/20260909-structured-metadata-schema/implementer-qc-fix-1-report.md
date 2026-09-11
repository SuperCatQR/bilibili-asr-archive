# QC Fix Wave 1 — Implementer Report

- Plan: `20260909-structured-metadata-schema`
- Role: fullstack-dev (leaf executor, no delegation)
- Working branch: `feature/20260909-structured-metadata-schema`
- Commit: `6d76ea4` — `fix(storage): enforce run transition guards and canonical repository forms`
- Base: HEAD at dispatch `ff81140` (worktree was clean)
- Report destination honored; no other harness artifacts written.

## Status: DONE

All consolidated findings fixed in one commit on the working branch: W1–W6 plus
S-fix-1…S-fix-5. Tasks 1–3 implemented behavior otherwise stands (surgical fix
round). No plan STOP condition triggered: no denormalization (schema.sql is
byte-untouched), no raw payloads, no network, no legacy JSONL access.

## Implemented — per-finding disposition

### W1 — transition guard (qc1 F-001 · qc3 F-002 · qc2 QC2-001)

- `_record_failed_page` now guards the run failure transition:
  `SET outcome='failed', finished_at=? WHERE run_id=? AND outcome='running'`
  (`database.py:408-415`). The page evidence row is still upserted in the same
  committed transaction, so a late/stale failed page appends evidence without
  ever regressing a terminal outcome or moving `finished_at` backwards.
- `finish_run` fetches `(started_at, outcome)` from the DB and raises
  `sqlite3.IntegrityError("run <id> already finished with outcome <o>")` when the
  stored outcome is not `'running'` (`database.py:286-295`) — re-finishing is
  rejected, not silently overwritten. The subsequent `changes() != 1` check is
  retained for the unknown-run case.
- Tests (red→green):
  - `test_late_failed_page_after_terminal_run_keeps_run_outcome_unchanged`
    (`tests/test_metadata_repository.py:228`) — finish_run(`complete`, 300), then a
    no-payload failed page: page row persisted (`failed`/`stale_page_result`), run
    row stays `('complete', 300)`.
  - `test_finish_run_rejects_refinishing_a_terminal_run`
    (`tests/test_metadata_repository.py:264`) — second finish raises
    `IntegrityError`; outcome/finished_at unchanged.

### W2 — canonical-form reduction (qc1 F-002/F-007 · qc3 F-004 · qc2 QC2-005)

Single canonical form per public API; speculative forms and uncalled branches
removed (greenfield API, no compatibility layers added):

- `finish_run(run: IngestionRunRecord)` — the docstring-"preferred" record form is
  now the ONLY form; the scalar "compatibility form" (`finish_run(run_id, outcome,
  finished_at)`) is removed (`database.py:275-309`). Ordering baseline is the run's
  stored `started_at` from the DB (the record's own `started_at` field is no longer
  the baseline). Redundant scalar-form checks (`isinstance(finished_at, int)`,
  empty-`run_id` strip) dropped — the record dataclass validates; the surviving
  form re-checks only reachable conditions (terminal outcome, non-None
  `finished_at`, ordering vs DB baseline). Docstring states all of this truthfully.
- `record_page(page, user, videos, parts, discoveries, cursor)` — `video`/
  `videos` dual params reduced to one `videos: Iterable[VideoRecord]` parameter,
  now in the locked order (user → videos → parts → discoveries → cursor) with no
  keyword-only split (`database.py:333-342`); the singular-or-iterable `video`
  branch and its mixing behavior are gone (`database.py` old `357-361`).
- `upsert_part` — the explicit-`video_part_id` INSERT branch (old `193-217`) is
  removed; a record with a non-None `video_part_id` raises
  `ValueError("upsert_part allocates video_part_id; it must be None")`
  (`database.py:206-207`). One upsert statement, no duplicated SQL (also closes
  qc3 F-013's duplication note as a side effect).
- `start_run` — the `ON CONFLICT(run_id) DO NOTHING` retry no-op is removed; a
  duplicate `run_id` now raises `sqlite3.IntegrityError` from the PK constraint
  (`database.py:244-273`). Runs are caller-supplied keys and are never reused.
- Tests for every surviving form (red→green unless noted):
  - `test_finish_run_record_form_validates_against_database_started_at`
    (`tests/test_metadata_repository.py:281`) — record-form happy path
    (`limited`, 300) plus three rejections: DB-baseline violation (record
    `started_at=50, finished_at=60` vs stored 101), non-terminal record outcome,
    `finished_at=None`.
  - `test_start_run_rejects_a_duplicate_run_id` (`tests/test_metadata_repository.py:569`).
  - `test_upsert_part_rejects_an_explicit_video_part_id` (`tests/test_metadata_repository.py:580`).
  - `test_open_database_memory_database_is_initialized` (`tests/test_storage_schema.py:249`)
    — characterization test pinning the retained `:memory:` branch (green at birth).

### W3 — constructor validation (qc3 F-001 · qc1 F-004 · qc2 QC2-006)

- `MetadataRepository.__init__` fails fast (`database.py:136-143`):
  - `row_factory is not sqlite3.Row` → `TypeError("connection must use the
    sqlite3.Row row_factory")`;
  - `PRAGMA foreign_keys` != 1 → `ValueError("connection must have PRAGMA
    foreign_keys enabled")`.
- Tests (red→green): `test_constructor_rejects_a_connection_without_row_factory`
  (`:593`), `test_constructor_rejects_a_connection_with_foreign_keys_disabled`
  (`:602` — asserts the pragma is actually 0 before constructing).

### W4 — commit-boundary matrix (qc3 F-003 · qc1 F-003 · qc2 QC2-004)

- Class docstring over-claim replaced with an explicit per-method commit matrix
  (`database.py:110-134`): `start_run` / `finish_run` commit independently;
  `record_page` owns one transaction (commit-or-rollback) plus the no-payload
  failed-page evidence transaction; `upsert_user`, `upsert_video`, `upsert_part`,
  `record_discovery`, `write_cursor` never commit (composable via `transaction()`);
  `read_cursor`, `list_pending_parts`, `run_stats` never write or commit. An
  explicit warning forbids composing the three committing methods inside a
  `transaction()` group.
- `initialize_schema` docstring now states it commits the schema script
  (`database.py:75-79`); `open_database` docstring documents the path semantics
  (`database.py:88-98`).

### W5 — record_page failure-protocol edges (qc3 F-005 · qc2 QC2-009)

- Edge (a) fixed per the recommended fix: `record_page` rejects payloads on a
  `'failed'` page — `ValueError("a failed page is recorded without payload
  arguments")` raised before any write (`database.py:374-375`). The old behavior
  (payloads silently committed together with a `'failed'` page row while the run
  stayed `running`) silently violated the spec's bounded failure protocol and is
  now impossible; persistence outcome is deterministic per input shape.
- Edge (b) documented as the correct two-step protocol: an `ok` page whose writes
  fail rolls back atomically, re-raises, and leaves prior state untouched;
  failure evidence is caller-owned — a fresh `IngestionPageRecord(outcome='failed',
  error_code=<bounded>)` replayed with no payload arguments (`database.py:343-361`
  docstring).
- Tests:
  - `test_record_page_rejects_payloads_on_a_failed_page` (`:195`) — red→green;
    also asserts nothing was persisted (run `running`, no page row, no videos).
  - `test_ok_page_write_failure_rolls_back_and_caller_records_failure` (`:135`)
    — replaces `test_failed_page_rolls_back_payload_preserves_cursor_and_records_bounded_outcome`;
    proves the ok-page rollback (cursor byte-identical, counts unchanged, run
    stays `running`/`finished_at=NULL`) and the caller's second no-payload call
    recording bounded evidence (`failed`/`foreign_key`) plus the run failure
    transition (`failed`, 201).

### W6 — `file:` URI branch (qc3 F-006 · qc1 F-005 · qc2 QC2-003)

- Branch dropped: no consumer passes `file:` URIs, and a real `uri=True` surface
  would be speculative for a greenfield path that documents plain paths. A
  `file:`-prefixed string is now handled like any other explicit path (literal
  filename; SQLite URI semantics are not interpreted) — `_resolve_database_path`
  (`database.py:54-72`), documented in `_resolve_database_path` and
  `open_database` docstrings. No build-dependent behavior remains.
- The `:memory:` special case is retained (the archive-root heuristic would
  otherwise turn `:memory:` into a directory) and is now covered by
  `test_open_database_memory_database_is_initialized`.

### S-fix-1 — models.py comment vs `__all__` (qc1 F-010 · qc3 F-007)

- Comment corrected: the exported `validate_error_code` + `ALLOWED_*` sets are now
  described truthfully as the public validation surface for gateway/CLI callers
  (`models.py:255-256`).

### S-fix-2 — `storage/__init__.py` export asymmetry (qc1 F-008 · qc3 F-010 · qc2 QC2-008)

- Package root re-exports the full surface: `MetadataRepository`, all seven record
  dataclasses, the four `Literal` type aliases, the four `ALLOWED_*` sets,
  `validate_error_code`, and the five bootstrap helpers; module docstring states
  the package root is the single import surface (`storage/__init__.py:1-53`).

### S-fix-3 — redundant LIKE-marker sweep (qc1 F-011)

- The LIKE-marker sweep in `test_error_fields_persist_only_bounded_scalar_codes`
  is dropped; the exact non-null value-equality, length ≤ 64, and charset
  assertions remain (`tests/test_metadata_repository.py:436-492`).

### S-fix-4 — enum CHECK literal duplication (qc1 F-006 · qc3 S)

- Single shared Python constants: `models.ALLOWED_*` (backing `_ALLOWED_*`
  frozensets) are now asserted against the executed DDL by
  `test_schema_check_enumerations_match_model_validation_sets`
  (`tests/test_storage_schema.py:263`), which extracts each CHECK `IN (...)`
  literal list from `sqlite_master` per table/column and requires set parity with
  the model sets; it additionally pins each `Literal` type alias against its
  frozenset via `typing.get_args` (Literal ↔ frozenset ↔ DDL all guarded).
- `database._TERMINAL_RUN_OUTCOMES` is derived from `ALLOWED_RUN_OUTCOMES`
  (`database.py:28`) instead of a second hand-written terminal set.

### S-fix-5 — `status=` parameter name (qc1 F-012 · qc3 S)

- `make_part_record(status=…)` renamed to `processing_status=` (fixture kwarg now
  mirrors the field/column name exactly; `tests/fixtures/metadata_records.py:89`),
  and the one call site updated
  (`tests/test_metadata_repository.py` `test_cursor_resume_and_pending_limit`).
- `naming-analyzer` skill loaded and applied before finalizing identifiers: kwargs
  mirror field names (`processing_status`, `outcome`, `finished_at`,
  `video_part_id` — no abbreviations); new test names are descriptive snake_case
  verb phrases (`test_late_failed_page_after_terminal_run_keeps_run_outcome_unchanged`,
  `test_finish_run_rejects_refinishing_a_terminal_run`, `test_record_page_rejects_payloads_on_a_failed_page`,
  `test_ok_page_write_failure_rolls_back_and_caller_records_failure`,
  `test_finish_run_record_form_validates_against_database_started_at`,
  `test_start_run_rejects_a_duplicate_run_id`,
  `test_upsert_part_rejects_an_explicit_video_part_id`,
  `test_constructor_rejects_a_connection_without_row_factory`,
  `test_constructor_rejects_a_connection_with_foreign_keys_disabled`,
  `test_open_database_memory_database_is_initialized`,
  `test_schema_check_enumerations_match_model_validation_sets`) — 见名之意，没有歧义.

## Tests

Environment note: the feature worktree has no local `.venv`; all runs use the
control checkout's interpreter `/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python`
with pytest default prepend import mode (same pattern the implementation round
used — QA parity note U3 unchanged).

### TDD red state (before product fixes)

Command:
```
cd /root/workspace/bilibili-asr-archive/.worktrees/20260909-structured-metadata-schema/bilibili-asr-archive \
  && /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest \
     tests/test_storage_schema.py tests/test_metadata_repository.py -q
```
Output:
```
FAILED tests/test_metadata_repository.py::test_record_page_rejects_payloads_on_a_failed_page
FAILED tests/test_metadata_repository.py::test_late_failed_page_after_terminal_run_keeps_run_outcome_unchanged
FAILED tests/test_metadata_repository.py::test_finish_run_rejects_refinishing_a_terminal_run
FAILED tests/test_metadata_repository.py::test_finish_run_record_form_validates_against_database_started_at
FAILED tests/test_metadata_repository.py::test_start_run_rejects_a_duplicate_run_id
FAILED tests/test_metadata_repository.py::test_upsert_part_rejects_an_explicit_video_part_id
FAILED tests/test_metadata_repository.py::test_constructor_rejects_a_connection_without_row_factory
FAILED tests/test_metadata_repository.py::test_constructor_rejects_a_connection_with_foreign_keys_disabled
8 failed, 23 passed in 1.07s
```
(The two green-at-birth tests are characterization/guard tests:
`test_open_database_memory_database_is_initialized` pins the retained `:memory:`
branch; the S-fix-4 parity test guards an already-equal contract.)

### Focused green (after fixes)

Same command, `-v`:
```
tests/test_storage_schema.py ............ (12 passed)
tests/test_metadata_repository.py ................. (19 passed)
31 passed in 0.76s
```
Baseline was `21 passed in 0.58s` (10 schema + 11 repository) — all 21 pre-existing
tests still pass; +10 new/rewritten.

### Full offline suite (final committed state)

```
cd /root/workspace/bilibili-asr-archive/.worktrees/20260909-structured-metadata-schema/bilibili-asr-archive \
  && /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest -q
...
724 passed in 40.47s
```
Baseline was `714 passed in 40.32s`; +10 = the new/rewritten tests. No regression.

### Verification discipline

```
git diff --check  →  clean (exit 0)
git status --porcelain after commit  →  empty
```

## Files changed (all inside the feature worktree; one commit `6d76ea4`)

| File | Change |
|---|---|
| `bilibili-asr-archive/src/bili_asr/storage/database.py` | W1 guard + re-finish rejection; W2 canonical forms (`finish_run` record-only, `record_page` videos-only, `upsert_part` allocation, `start_run` duplicate rejection); W3 constructor checks; W4/W5/W6 docstrings; `:memory:`-only path special case |
| `bilibili-asr-archive/src/bili_asr/storage/models.py` | S-fix-1 comment fix; `VideoPartRecord` docstring truth (repository allocates the id) |
| `bilibili-asr-archive/src/bili_asr/storage/__init__.py` | S-fix-2 full re-export surface |
| `bilibili-asr-archive/tests/fixtures/metadata_records.py` | S-fix-5 `status=`→`processing_status=`; `make_run_record` gains `outcome`/`finished_at`; `make_part_record` gains `video_part_id` |
| `bilibili-asr-archive/tests/test_metadata_repository.py` | 4 new tests + 1 rewritten (W1/W2/W5), 6 `video=`→`videos=` call-site updates, 3 scalar `finish_run`→record-form updates, S-fix-3 LIKE sweep drop, 2 constructor tests |
| `bilibili-asr-archive/tests/test_storage_schema.py` | 2 new tests (`:memory:`; S-fix-4 parity) + imports |

`schema.sql`: **not modified** (guards are application-level; no schema/DDL change,
no denormalizing constraint, no 3NF impact).

## Baseline behavior adjustments (called out, per assignment)

1. Three scalar `finish_run` call sites rewritten to the record form — the scalar
   form was the removed compatibility form (W2).
2. Six `record_page(video=…)` call sites rewritten to `videos=[…]` (W2).
3. `test_failed_page_rolls_back_payload_preserves_cursor_and_records_bounded_outcome`
   replaced by `test_ok_page_write_failure_rolls_back_and_caller_records_failure`:
   a `failed` page with payloads is now rejected (`ValueError`) instead of
   committing payloads, so the old test shape no longer exists; its invariants
   (rollback, cursor preservation, bounded evidence, run failure transition) are
   preserved in the new two-step test (W5).

## Self-review notes

- `_record_failed_page` intentionally does not raise when `changes()==0`: the
  page-row upsert succeeding proves the run exists (FK), so `changes()==0` can
  only mean the run is terminal — the documented no-op preserves evidence without
  corruption. No `changes()` check invented for an impossible path (YAGNI).
- `finish_run` checks the stored outcome before the requested-outcome validation,
  so a re-finish attempt raises `IntegrityError` regardless of the new outcome's
  validity, and the unknown-run case keeps its own distinct `IntegrityError`.
- `record_page`'s payload path lost its `except`-handler because the W5 rule
  removes the only case that used it (failed page + payloads); `transaction()`
  alone now owns commit/rollback + re-raise. No speculative error handling kept.
- Parameter order of `record_page` now mirrors the locked order exactly; every
  call site already used keyword arguments (verified by grep — no positional
  payload args anywhere in src/ or tests/).
- No consumer outside `src/bili_asr/storage/` and the storage contract tests
  imports the repository APIs (grep-verified), so the canonicalization breaks no
  other suite; the 693 non-storage tests pass unchanged (714−21 → 724−31).
- Errors stay bounded scalar codes; no cookies/signed URLs/raw JSON/tracebacks
  introduced anywhere (message strings are static; `run_id` interpolation in
  `finish_run` errors is caller-supplied key material only, matching the
  pre-existing `unknown run_id` pattern).
- Out-of-scope items untouched: no schema-level error-code shape CHECK (carried),
  no schema version stamp (carried), no FK-child indexes (dropped) — matching the
  consolidated disposition.
- Environment note: no build tooling exists here, so the U2 wheel-artifact
  question remains QA-owned and unchanged by this wave.
