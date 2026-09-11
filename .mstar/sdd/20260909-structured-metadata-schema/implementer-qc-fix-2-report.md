# Implementer Report — QC Fix Round 2 (final convergence micro-fix)

- Plan: `20260909-structured-metadata-schema` (SDD, Batch 1)
- Working branch: `feature/20260909-structured-metadata-schema` · Worktree: `/root/workspace/bilibili-asr-archive/.worktrees/20260909-structured-metadata-schema`
- Fix commit: `2063a1a` (`6d76ea4..2063a1a`, 2 files, +132/−16) — committed on the Working branch only; no push; `main`/integration branches untouched
- Inputs verified: `review/qc-consolidated.md` (round-1 revalidation + round-2 dispositions), `qc1.md` `## Revalidation` F-016, `qc3.md` `## Revalidation` F-012/F-014/F-018/F-019, plan Global Constraints + STOP conditions
- Round-1 baseline reproduced before changes: focused **31 passed** at `6d76ea4`

## Status: DONE

All five round-2 findings (S-fix-6, S-fix-7, S-fix-8, S-fix-9a, S-fix-9b) fixed in one
commit. No STOP condition triggered: no legacy archive access, no network/`bilibili_api`
import, no denormalization, `schema.sql` byte-untouched, no raw payloads persisted.

## Implemented (per-finding disposition)

### S-fix-6 — failure-path run transition ordering check (qc1 F-016) — FIXED

- `database.py:420-459` (`_record_failed_page`): while the run is still `'running'`,
  the failure transition now mirrors `finish_run`'s DB-baseline check — one fetch of
  the run's stored `(started_at, outcome)` followed by one guarded condition
  (`run_row is not None and run_row["outcome"] == "running" and page.finished_at <
  int(run_row["started_at"])`, `database.py:432-441`); a violating page raises
  `ValueError("finished_at must not precede started_at")` — the same message as
  `finish_run` (`database.py:317`) — inside the `transaction()` group, so the whole
  call persists nothing (page evidence included; rollback is a no-op safety net
  because the check precedes every write).
- Preserved by construction and by tests: terminal runs skip the guard entirely
  (W1 evidence-persist behavior unchanged — `test_late_failed_page_after_terminal_run_keeps_run_outcome_unchanged`
  still passes); unknown `run_id` skips the guard and still fails on the page-row FK
  (unchanged); valid-clock failed pages still transition (`finished_at=201 >= stored 101`).
- Docstrings updated: `record_page` (`database.py:374-384`) documents the ordering
  baseline + rejection; `_record_failed_page` (`database.py:420-431`) restated — the
  former "page evidence is always upserted" claim is corrected (no longer
  unconditional).
- Test (red→green): `test_failed_page_clock_before_running_run_start_is_rejected_and_nothing_persisted`
  (`tests/test_metadata_repository.py:270-297`) — valid page record
  (`started_at=50/finished_at=51`) below the run's stored `started_at=101` raises
  `ValueError`; asserts zero page rows and run unchanged `('running', None)`.

### S-fix-7 — read-path exception discipline + return-shape documentation (qc3 F-012) — FIXED

- Exception normalization (type errors → `TypeError`, value errors stay `ValueError`):
  - `read_cursor` (`database.py:474-484`): bool/non-int `mid` → `TypeError("mid must
    be an integer")`; `mid < 1` → `ValueError("mid must be a positive integer")`.
  - `run_stats` (`database.py:554-571`): non-str `run_id` → `TypeError("run_id must
    be a string or None")`; blank string → `ValueError("run_id must be a non-empty
    string")`; `None` all-runs form unchanged.
  - `list_pending_parts` (`database.py:533-545`): bool/non-int `limit` →
    `TypeError("limit must be an integer or None")`; `limit < 1` →
    `ValueError("limit must be a positive integer")`.
  - Scope note (disclosed): qc3 F-012 names `read_cursor`/`run_stats` ("both"), but
    the finding's own line anchor covers `list_pending_parts` too
    (`database.py:490-518` of the reviewed head) and its stated expected state is a
    uniform read-path validation convention; normalizing all three read paths is the
    consistent completion of the dispositioned fix, not an adjacent refactor. The
    whole module now has one discipline: type errors → `TypeError` (e.g.
    `duration_to_ms`, `normalize_page_index`, all write-path isinstance checks),
    value errors → `ValueError`.
- Return-shape convention documented, return types NOT redesigned (typed read-model
  unification stays carried to the Batch 3 CLI contract per the consolidated
  disposition): class docstring paragraph `database.py:129-137` ("Read paths return
  two shapes: typed `CursorRecord` vs raw `sqlite3.Row` view data — list for the
  no-argument form, single row or `None` for the keyed form — and the module-wide
  TypeError/ValueError argument discipline"); per-method docstrings for `read_cursor`
  (`:474-478`), `list_pending_parts` (`:533-537`), `run_stats` (`:554-560`).
- Test (red→green): `test_read_path_validation_splits_type_errors_from_value_errors`
  (`tests/test_metadata_repository.py:596-622`) — pins `TypeError` for
  `read_cursor(True)`/`read_cursor("23191782")`/`run_stats(23191782)`/
  `list_pending_parts(limit="1")`/`list_pending_parts(limit=True)` and `ValueError`
  for `read_cursor(0)`/`run_stats("   ")`/`list_pending_parts(limit=0)`.
- No existing test pinned the old `ValueError` behavior (verified by grep over both
  test files before editing) — zero test-shape adjustments needed; all 31 pre-existing
  tests pass unmodified.

### S-fix-8 — `upsert_video` stable-identifier policy docstring (qc3 F-014) — FIXED

- `database.py:181-189`: one docstring clause stating the policy the aid-COALESCE
  test pins — "The stored ``aid`` is a stable identifier: the first non-``None``
  ``aid`` wins — a stored ``NULL`` is backfilled from the incoming record, and a
  known ``aid`` is never overwritten." Behavior unchanged (`database.py:190-194` SQL
  untouched); pinned by the pre-existing `test_re_upsert_backfills_missing_aid_and_keeps_existing_aid`.

### S-fix-9a — restored transaction-head rollback assertion (qc3 F-018) — FIXED

- `tests/test_metadata_repository.py:161-166` in
  `test_ok_page_write_failure_rolls_back_and_caller_records_failure`: one assertion
  restored before the failure replay —
  `SELECT display_name FROM bilibili_users` == `"未明子"` — proving the FIRST write
  in the locked order (the user upsert of the failing call) rolled back; the comment
  names what it proves. Green-at-birth (the behavior was already correct; the
  assertion was the lost proof). All other invariants of the test untouched.

### S-fix-9b — exhaustive commit matrix (qc3 F-019) — FIXED

- Class docstring commit matrix (`database.py:118-122`): the `record_page` row now
  also names the no-payload non-failed page sub-case — "with no payload arguments it
  still commits its own single-write transaction — either the ``'failed'`` evidence
  transaction (page row plus the run's failure transition) or the
  ok/empty/``risk_interrupted`` page-outcome write."
- `record_page` docstring (`database.py:374-377`): matching clause ("A no-payload
  page with a non-failed outcome (``ok``, ``empty``, ``risk_interrupted``) likewise
  commits its own single-write transaction for the page-outcome row."). Behavior
  unchanged and verified (E2E `empty` page path and both no-payload sub-case tests
  pass unchanged).

## Tests

Environment (unchanged from round 1 / U3 parity): the feature worktree has no local
`.venv`; all runs use the control checkout's interpreter
`/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python` with
pytest default prepend import mode, from the worktree package dir.

### TDD red state (before product fixes; tests added first)

```
cd /root/workspace/bilibili-asr-archive/.worktrees/20260909-structured-metadata-schema/bilibili-asr-archive \
  && /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest \
     tests/test_storage_schema.py tests/test_metadata_repository.py -q
FAILED tests/test_metadata_repository.py::test_failed_page_clock_before_running_run_start_is_rejected_and_nothing_persisted
FAILED tests/test_metadata_repository.py::test_read_path_validation_splits_type_errors_from_value_errors
2 failed, 31 passed in 0.84s
```

(The red list is exactly the 2 new behavior tests; the S-fix-9a restored assertion is
green-at-birth by design — it re-pins already-correct rollback behavior.)

### Focused green (after fixes, committed state)

```
cd /root/workspace/bilibili-asr-archive/.worktrees/20260909-structured-metadata-schema/bilibili-asr-archive \
  && /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest \
     tests/test_storage_schema.py tests/test_metadata_repository.py -v
...
33 passed in 0.82s
```

Baseline 31 → 33: all 31 pre-existing tests preserved, +2 new (S-fix-6, S-fix-7).

### Full offline suite (final committed state)

```
cd /root/workspace/bilibili-asr-archive/.worktrees/20260909-structured-metadata-schema/bilibili-asr-archive \
  && /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest -q
...
726 passed in 40.02s
```

Baseline 724 → 726 (+2 new tests); arithmetic consistent (724 − 31 + 33 = 726). No
regression.

### Verification discipline

```
git diff --check  →  clean (exit 0, run pre-commit and at committed state)
git status --porcelain after commit  →  empty
```

## Files changed (one commit `2063a1a`, all inside the feature worktree)

| File | Change |
|------|--------|
| `bilibili-asr-archive/src/bili_asr/storage/database.py` | `_record_failed_page` DB-baseline clock guard + docstrings (`:374-384`, `:420-459`); class docstring commit-matrix exhaustiveness + read-path return-shape paragraph (`:118-137`); `upsert_video` aid-policy clause (`:181-189`); `read_cursor`/`list_pending_parts`/`run_stats` TypeError/ValueError split + docstrings (`:474-484`, `:533-545`, `:554-571`) |
| `bilibili-asr-archive/tests/test_metadata_repository.py` | restored user-row rollback assertion in `test_ok_page_write_failure_rolls_back_and_caller_records_failure` (`:161-166`); new `test_failed_page_clock_before_running_run_start_is_rejected_and_nothing_persisted` (`:270-297`); new `test_read_path_validation_splits_type_errors_from_value_errors` (`:596-622`) |

`schema.sql` untouched this round (verified: no diff hunk). No other files touched.

## Self-review notes

- **Surgical scope**: every hunk maps to one finding ID; no opportunistic refactors.
  The only judgment call beyond the literal finding text — extending the TypeError
  normalization to `list_pending_parts` — is grounded in F-012's own anchor range and
  its uniform-convention expected state, and is disclosed above. Product identifiers
  untouched; the two new test names were run through the `naming-analyzer` skill
  (见名之意，没有歧义; they follow the suite's existing long descriptive
  `test_<behavior>` convention, parallel to
  `test_late_failed_page_after_terminal_run_keeps_run_outcome_unchanged`).
- **Guard semantics sanity (S-fix-6)**: check order in `_record_failed_page` is fetch
  → running-only baseline guard → page-evidence upsert → guarded run UPDATE. A
  rejected clock raises before any write, so "nothing is persisted" holds
  structurally, not just by rollback. Terminal-run no-op (W1), unknown-run FK error,
  and the valid-clock transition are each still pinned by pre-existing tests that
  pass unmodified.
- **Docstring truthfulness**: the round-1 wording "The page evidence is always
  upserted" became false under the new guard and was rewritten during self-review
  (caught before commit); `record_page`'s failure-protocol documentation now covers
  all three commit shapes plus the rejection edge.
- **Hard constraints re-verified**: all tests offline (stdlib-only diff; no network,
  `bilibili_api`, credentials, weights, or legacy-JSONL access); bounded scalar error
  codes untouched (no new persisted error values; exception messages are static
  strings); 3NF untouched; locked payload-transaction order untouched; `schema.sql`
  byte-untouched; `git diff --check` clean; worktree clean after the single commit.
- **Out-of-scope items respected**: no typed read-model returns for
  `run_stats`/`list_pending_parts` (Batch 3 carry), no schema error-code CHECK or
  version stamp (Batch 2), no FK-child indexes (dropped). The docstrings state the
  current shapes as the contract without redesigning them.
- **QA-gate items remain QA-owned** (unchanged from round 1): runtime pass-count
  parity (now 33 focused / 726 full, implementer-reported), wheel/sdist
  `schema.sql` inclusion on a real build, and interpreter/import-mode parity for the
  QA re-run (same control-`.venv` pattern used here).

## Files

- Report: `.mstar/sdd/20260909-structured-metadata-schema/implementer-qc-fix-2-report.md` (this file)
- Commit: `2063a1a` on `feature/20260909-structured-metadata-schema` (worktree `/root/workspace/bilibili-asr-archive/.worktrees/20260909-structured-metadata-schema`)
