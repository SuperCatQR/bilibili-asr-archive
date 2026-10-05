# PR #214 overlap audit — `codex/audio-pipeline-reliability` vs `iter-2026-10-register-burndown`

> Read-only evidence record. Written 2026-10-06 on request ("有新pr，看一下与你目标有无冲突").
> Every claim below is anchored to a command that can be re-run; `PR` = `origin/codex/audio-pipeline-reliability`
> (`88dbea3`), baseline `main` = `c59a1e6`. This file changes no plan, compass, or store row — the
> disposition it recommends still needs the Phase-1 lock to finish and the PM's ruling.

## 0. What the PR is

| Field | Value |
|---|---|
| PR | [#214](https://github.com/SuperCatQR/bilibili-asr-archive/pull/214) `Harden audio pipeline recovery and archive reliability` |
| head → base | `codex/audio-pipeline-reliability` → `main` |
| head sha | `88dbea3` | 
| base / merge-base | `main` = `c59a1e6`; merge-base = `f537cb5` (both are docs-only commits on top of it) |
| size | 148 files, **+13 155 / −2 718**, 7 commits |
| mergeable | `MERGEABLE`, `mergeStateStatus: UNSTABLE` (CI red) |
| CI | `python` job **fails** (2 runs, identical): 7 failed / 2 653 passed / 61 skipped — 4 × `test_asr_qwen.py` "`ffmpeg` binary is not on PATH" (real CI env defect: `.github/workflows/ci.yml` installing it nowhere), 3 × `test_audio_pipeline_reliability.py` FLAC-conversion assertions (same missing-binary root cause) |
| issue links | No `I-000xxx` in commits or PR body; the PR instead ships the batch ledger `bilibili-asr-archive/verification-results/issue-fix-batches.md`, which claims **41 / 40** register-backed fixes and names several of our rows by store id |

## 1. Verdict

**No conflict at the harness level; direct, substantial conflict at the defect level.** The PR is a
*fourth* workstream over the same ground as B1/B2/B3, authored outside this iteration, with its own
fix ledger. It touches none of this iteration's artifacts (no `.mstar/**`, no compass/plans) and is not
merged, but its branch already contains code+tests satisfying **20 of our 21 declared rows** (the 21st,
`I-000211`, only partially — see §2). If it lands before our iteration closes, those rows become
*already-fixed reports*, which our own acceptance criteria explicitly exclude from the ≥20 count
(compass AC #1 + `direction-lock.md` §3).

One caveat for anybody closing rows from the PR's ledger: three of its Batch-1 GitHub numbers are
rotated — its `#184` / `#185` / `#186` describe the content of GitHub `#185` / `#186` / `#184`
(selector / language / run-finish respectively). The §2 table below is keyed by **store id**, verified
against code, not by the ledger's numbers.

**Recommended disposition: reconcile before Phase 2 dispatch, not after** — re-baseline the iteration
against the PR's fixes (keep only the rows the PR does not actually satisfy), and settle the
one-writer question (§5). Do **not** simply start Phase 2 on `c59a1e6` as the plans stand.

## 2. Row-by-row (our 21 declared rows)

Method: `git show`/`git grep` on the PR branch, per row, against the row's own acceptance text
(`gh issue view <n> --json body` § Completion contract). "Covered" means *the acceptance's verification
clause is satisfied by code+tests on the PR branch*, not that a ledger says so.

| store id | GitHub | PR status | Evidence on the PR branch |
|---|---|---|---|
| `I-000182` | #184 | **covered** | `cli/asr.py:351`, `cli/pilot.py:733`, `coordinator.py:722` all call `finish_asr_run`; `tests/test_audio_pipeline_reliability.py:104-124` asserts `outcome=complete` + `finished_at`, `:222-223` covers failed→complete overwrite |
| `I-000183` | #185 | **covered** | `queue_source.py:152/:248` `selector_kind="bvid" if selector_target else "pending"` + `selector_target`/`requested_limit` recorded; `test_audio_pipeline_reliability.py` (pending/bvid parametrized) |
| `I-000184` | #186 | **covered** | `asr.provenance_language` (`asr.py:48`) + `_last_language` (`:1180`, `:1351` reset, `:1437` set, `:1545` read); `cli/asr.py:319` and `:1012` both use it; test asserts `language=="Chinese"` |
| `I-000197` | #199 | **covered** | `_report_refused_asr_run` docstring now states the three scopes (source instance / coordinator invocation / later invocation), `queue_source.py:285`; coordinator carries the latch across batches |
| `I-000198` | #200 | **covered** | `except (_sqlite3.Error, OSError, ValueError, TypeError)` `queue_source.py:~257`; `test_audio_pipeline_reliability.py:229-245` drives a lost `row_factory` and asserts `[... (TypeError)]` |
| `I-000199` | #201 | **covered** | `diagnostics.write_stderr` — descriptor-level `os.write`, cannot dirty a dead buffer; `test_closed_stderr_diagnostics_preserve_process_exit_status` (4 sites) |
| `I-000180` | #182 | **covered** | `queue_source.py` timestamps now `_common._now()` (`:156/:178/:198/:240/:276/:434/:457`); `tests/test_pipeline_writeback_safety.py:115-179` (two clock tests) |
| `I-000171` | #173 | **covered** | `page_identity.writeback_identity` (`:42`) — work_id-derived, skips bare-bvid/conflicting rows; `test_writeback_uses_work_id_and_never_attributes_legacy_row_to_p0` |
| `I-000176` | #178 | **covered** | `test_asr_archive_manifest_carries_branch_and_language` runs a real `RunCoordinator.run_batch` and reads the persisted transcript row (`source_kind='asr-local'`, `language='Chinese'`), `test_pipeline_writeback_safety.py:~244-262`; fixture repair on the same ground |
| `I-000194` | #196 | **covered** | `cli/asr.py:303-333`: `_mark_archived`/`store.upsert` happen first, the store write-back moved after publication inside its own `try` with `write_stderr` |
| `I-000191` | #193 | **covered** | both superseded docstrings gone: `git grep "before the attempt ledger records" $PR -- src` → empty |
| `I-000192` | #194 | **covered** | `coordinator._record_transcript_writeback_failure` + call-site `try` with `except Exception` (`coordinator.py:852-854`); `test_connection_contract_failure_preserves_archive_across_batches` |
| `I-000193` | #195 | **covered, shape different** | durable, queryable marker `transcript_writeback_error` / `transcript_writeback_failed_at` on the manifest row (`coordinator.py:755`), cleared on a later success (`:772-781`); `test_failed_scope_reselects_archived_transcript_writeback_failure` proves re-drive. Our plan's Q1 assumed an attempt-ledger/store-level signal — the PR answers it with a manifest-row marker |
| `I-000196` | #198 | **covered** (policy = ours' option A) | `manifest.py:335` `raw.decode("utf-8")` — strict, no `errors="replace"`; ledger names #198 |
| `I-000202` | #204 | **covered** | `self._journal_bytes` absent from the PR branch (`git grep` empty, no test references) |
| `I-000203` | #205 | **covered, closes one of our two options** | Our plan's Q2 asked to *close* the window or *write the precondition down*; `save()` is now rewritten (caller-view journal handoff → `_replace_snapshot` → `_remove_journal`, `manifest.py:584-625`). **Partial**: the residual "a crash between publish and discard re-publishes journal rows" is gone, but the accept-precondition half (the docstring still describes the no-argument path) and its witness are only asserted in the PR's ledger, not in a test we can point at. Treat as "mostly covered, verify at re-baseline" |
| `I-000168` | #170 | **covered** | `conftest.py:198-221` performs `pytest.skip(reason)` itself; `tests/test_opt_in_gate.py` — 16 nested-pytest cases proving fixture-only skipping |
| `I-000174` | #176 | **covered** | `tests/test_installed_cli.py:54-77` `test_installed_console_script_opens_and_initializes_database` — console script run, `sqlite_master` asserted to carry `table transcripts` + `view v_missing_audio` |
| `I-000175` | #177 | **covered** | installer family moved to the new `tests/test_installed_cli.py`; `scripts/verify_baseline.py:278` exclusion set now `{test_verify_baseline.py, test_installed_cli.py}` — `test_cli_help.py` no longer excluded |
| `I-000210` | #210 | **covered** | new `acquisition_attempts.credential_verified` column + `absence_verified` (in-place `ALTER TABLE ADD COLUMN`, `database.py:437`), views now require `credential_present = 1 AND credential_verified = 1` (`schema-transcripts.sql:291/:315`); `test_only_authenticated_empty_observations_corroborate_exhaustion` |
| `I-000211` | #211 | **partially** | probe stays read-only (`subtitle_ingest.py:319`, `cli/meta.py:135` docstrings) and `_probe_part` does not record. The row asks for a *recorded decision*; that claim currently lives only in the PR's own batch ledger, not in a durable harness artifact |

**Totals: 18 of 21 fully satisfied on the PR branch; 3 with residual work** — `I-000203` (window
closed, precondition/witness not yet pinned), `I-000211` (recorded decision still only in the PR's
own ledger), and `I-000176`'s "end-to-end witness" reading, which the PR satisfies for the
coordinator route but which we read as also covering the in-process CLI route. **Zero rows
unaddressed in code.**

Independently of that table, the PR's ledger also claims rows we deliberately excluded
(`I-000189` #191, `I-000209` #209, `I-000135/136`) and ~26 further rows beyond our 21 — total claim
41/40. Those are not ours to verify.

## 3. Files the PR author rewrote (our plans' write targets)

`git diff --stat main...$PR` — this is why a later start on `c59a1e6` would not rebase cleanly:

| file | delta | our plan |
|---|---|---|
| `src/bili_asr/services/queue_source.py` | +264/−… | B1 |
| `src/bili_asr/cli/asr.py` | 116 lines | B1 |
| `src/bili_asr/coordinator.py` | 324 lines | B1 + B2 |
| `src/bili_asr/manifest.py` | 180 lines | B2 |
| `src/bili_asr/services/subtitle_ingest.py` | 36 lines | B1 + B3 |
| `src/bili_asr/storage/schema-transcripts.sql` | 157 lines | B3 |
| `tests/conftest.py` | 50 lines | B3 |
| `scripts/verify_baseline.py` | 5 lines | B3 |
| `tests/test_cli_help.py` / **new** `tests/test_installed_cli.py` | 14/−60 · new | B3 |

Also rewritten on the PR branch and inside B1/B2's blast radius:
`storage/database.py`, `storage/schema.sql`, `page_identity.py`, `cli/pilot.py`, `archive.py`,
`asr.py`, `run_ledger.py`, `audio*.py`, plus 82 test files (many new).

## 4. Second-order conflicts with our own commitments

1. **Count.** Compass AC #1 requires ≥20 rows closed **by fixing their subject in code**; a row whose
   subject the PR already fixed is by our own `D4` recorded as *already-fixed and not counted*. After
   #214, at most 1 of 21 rows is ours to fix → the iteration's headline deliverable collapses even
   though everything else about the iteration is sound.
2. **No-schema-migration commitment.** Compass AC #5 + `direction-lock.md` §3.5: *"no target fix
   requires in-place DDL. A fix that would need one is STOPped and re-scoped, not migrated."*
   The PR crosses that line for `I-000210`: `ALTER TABLE acquisition_attempts ADD COLUMN
   credential_verified` (with `absence_verified`). Our own plan had scoped `I-000210` to a
   **view-predicate change only** ("仅视图谓词，非 DDL"). Doing it our way afterwards would be a
   re-implementation of a schema change that will already be on `main`.
3. **Engine `3.11.2` schema rebuild path.** `database.py:425-450` also runs `executescript` on both
   schema resources for every open, and the DDL runs behind `_accepts_transcript_script(connection)`.
   Our iteration already touches `storage/schema-transcripts.sql`; a concurrent edit is a
   merge-order hazard, not just a textual one.
4. **`verification-results/` is a new tracked surface.** The PR adds
   `verification-results/issue-fix-batches.md` + `audio-pipeline-2026-10-04.md` establishing a
   *fix-ledger* convention outside `{HARNESS_DIR}`. If that lands, our closure evidence should point
   at it (or at least not contradict it).

## 5. What the PR does **not** do

- It does **not** close any store row: `mstar issue close` never appears; GitHub issue states are
  explicitly "unchanged" per the ledger's own preamble. So the **store's 125 open rows stay open**, and
  our closure route (`{SPECS_DIR}/issue-store-close-route.md`) is still the only channel capable of
  producing `disposition=resolved`.
- It does **not** touch `.mstar/**` — no compass, plan, snapshot, or status.json change; the audit
  lifecycle's wedge (`I-000215`) is untouched.
- It does **not** fix its own CI: the `python` job is red on 7 tests for a missing `ffmpeg`, so
  "required CI green" is currently unsatisfiable for #214 as written.
- It does **not** make `main` move: head is `88dbea3`, base is still `c59a1e6`.

## 6. Decision the operator/PM has to make

Two coherent routes, mutually exclusive; **do not** run both:

**Route A — absorb first (recommended).**
1. #214 merges (or is rebased and merged) *before* our Phase 2 starts; green CI is a precondition
   (fix `ci.yml` to install `ffmpeg`, or drop the 7 env-dependent tests from the blocking job).
2. Re-run the row-by-row table against the new `main`; every row it satisfies moves to
   *already-fixed-with-evidence* and is **excluded** from the ≥20 count.
3. Re-scope B1/B2/B3 to the residue (today: `I-000211`'s recorded decision plus whatever the
   re-check finds un-satisfied), or negotiate a new scale/plan set — `M`'s 3-plan budget cannot be
   spent on 1 row, so this likely becomes a **new** direction lock, not a patch to the current one.
4. Closures must cite the PR's fixing commits and its ledger rows, so the store and GitHub mirror agree.

**Route B — keep our iteration and land it first.**
Only honest if we can point at ≥20 rows whose acceptance the PR does *not* satisfy — today that number
is 0. Choosing B against this evidence means the iteration's AC is not reachable and its closure would
have to be recorded as *superseded by #214*, not as "fixed 20 rows".

Either way, the PM (not this read-only audit) owns: the re-baseline decision, any plan/compass rewrite,
and the single-writer rule while #214 is open.

## 7. Reproduction

```bash
export HTTPS_PROXY=http://127.0.0.1:7890   # GitHub is only reachable via the local proxy here
PR=origin/codex/audio-pipeline-reliability
git fetch origin codex/audio-pipeline-reliability
git diff --stat main...$PR
git grep -n "finish_asr_run" $PR -- bilibili-asr-archive/src
git grep -n "selector_kind" $PR -- bilibili-asr-archive/src/bili_asr/services/queue_source.py
git grep -n "errors=" $PR -- bilibili-asr-archive/src/bili_asr/manifest.py
git grep -n "credential_verified" $PR -- bilibili-asr-archive/src/bili_asr/storage/schema-transcripts.sql
git show $PR:bilibili-asr-archive/verification-results/issue-fix-batches.md
gh pr view 214 --repo SuperCatQR/bilibili-asr-archive --json mergeable,mergeStateStatus,statusCheckRollup
```
