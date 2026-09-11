---
plan_id: 20260825-run-coordinator-offline
reviewer: qc-specialist-3
review_range: 5b392cc64f44099e48f83e32a8fc2ade6fe01e4c..2abf3e45ec560266c304a7d7d03438a5b7f137a0
verdict: "Approve"
generated_at: "2026-08-25"
---

# Code Review Report

## Reviewer Metadata
- Reviewer: @qc-specialist-3 (seat 3 of 3; focus: Performance and reliability risk)
- Runtime Agent ID: qc-specialist-3
- Runtime Model: glm-5.3
- Review Perspective: Performance and reliability risk — batch continue-on-failure robustness, resource lifecycle, retry/risk-budget behavior, sleep/cadence, ledger I/O cost, rerun idempotence under repeated crashes
- Report Timestamp: 2026-08-25T21:45:00Z

## Scope
- plan_id: 20260825-run-coordinator-offline
- Review range / Diff basis: 5b392cc64f44099e48f83e32a8fc2ade6fe01e4c..2abf3e45ec560266c304a7d7d03438a5b7f137a0 (merge-base = integration branch HEAD)
- Working branch (verified): plan/20260825-run-coordinator-offline
- Review cwd (verified): /root/workspace/bilibili-asr-archive/.worktrees/20260825-run-coordinator-offline (git rev-parse --show-toplevel; branch matches)
- Files reviewed: 4 (cli.py, coordinator.py, test_coordinator.py, README.md) via branch-review.diff (1407 lines, read in full) + source cross-checks in the worktree
- Commit range: identical to Review range (2 commits: 6827180 Task 1, 2abf3e4 Task 2)
- Analysis methods: git-diff, read, grep; cross-checks against `bili_client.py` (exception hierarchy, `_GoneResponse`/`GoneResponse` alias, `RiskBudgetExhausted`), `audio.py` (`download_audio` resumability + `_mark_audio_ok`), `cli.py` (`_todo_for_bvid`, pilot error convention), `subtitles.py`, `manifest.py`. No test/build/lint runs (L3).

## Findings

### 🔴 Critical
(none)

### 🟡 Warning

- W1: `download` and `archive` stage failures leave no `failed` attempt record in the sidecar ledger — the failure-tracking contract ("every executed stage atomically appends a record"; README lines 33–39) is violated for these stages, and `--scope failed` re-selection silently misses such rows. -> Wrap the `audio_module.download_audio` call in `_stage_download` and the `archive_module.write_archive` calls in `_stage_archive_from_subtitle` / `_stage_asr_archive` (plus `_mark_archived`/`store.upsert`) in try/except that records `("download"|"archive", work_id, "failed", error_code=_safe_error_code(exc))` before re-raising, mirroring the existing harvest/asr wrappers.
  - Verification: diff/read anchor. `coordinator.py` `_stage_download` (diff lines 686–707) has no try/except around `download_audio`; `_stage_archive_from_subtitle` (lines 605–632) and `_stage_asr_archive` (lines 642–684) have none around `write_archive` / `_mark_archived`. `process_row`'s outer `except Exception` (lines 787–797) only appends to `result.failure_codes` — its own comment says stage records are "written by the stage wrappers", so no ledger record is emitted for download/archive failures. `_cmd_run`'s `failed` scope (`cli.py` lines 135–138) selects rows solely from ledger records with `outcome == "failed"`.
  - Expected vs observed: expected — a row whose download persistently fails (e.g. `StreamDownloadError`) or whose archive write fails (e.g. disk-full/permission) has a `failed` attempt record and is re-selected by `run --scope failed`; observed — only `harvest` and `asr` failures are recorded (harvest wrapper lines 756–761; asr wrapper lines 661–666), so download/archive failures appear only in the one-run stderr summary and in `pending` scope, never in `failed` scope. Test coverage confirms the gap: `test_coordinator.py` covers asr-failure recording (lines 1144–1153) but has no test for a recorded failed download or archive attempt.

- (assessed, not re-flagged as new) Known plan-QC notes on this lens:
  - M3 O(n²) whole-file rewrite per append — assessed **not** a Warning: atomicity (tmp + fsync + `os.replace`, diff lines 431–448) is the correct crash-safety tradeoff for a personal-archive CLI; ledger grows ~3–4 records/row × rows, so a full-channel backlog plus repeated reruns stays in the low-thousands-of-lines range (sub-MB file, single-digit-ms per rewrite). Downgraded to 🟢 S1 with a marker request.
  - M5 sleep precision, T2-M1 double-read (`_subtitle_segments` read once in `process_row` offline branch and again inside `_stage_archive_from_subtitle`, diff lines 727/612), T2-M2 `started_at` omission on the offline-skip record (line 735: no `started_at` passed) — all assessed not Warnings on the reliability lens: costs are bounded, skipped-record timestamps remain valid ISO strings, and none affects continue-on-failure or idempotence behavior.

### 🟢 Suggestion
- S1 (M3): add a `simplify:` marker on `AttemptLedger.append` naming the O(n²) whole-file-rewrite-per-append ceiling and the upgrade path (open-append + `flush`/`fsync`, or periodic compaction), per the coding-behavior marker convention.
  - Verification: diff anchor lines 423–449; no `simplify:`/`temporary` marker present.
  - Expected vs observed: expected — deliberate ceiling flagged in code; observed — unmarked.
- S2: `_safe_error_code` (coordinator.py lines 330–341) truncates string codes to 64 chars but does not sanitize `_FORBIDDEN_MARKERS`; an exception whose `.code`/`.last_code` string attribute contains `http://`, `cookie`, etc. would pass through and make `_validate_attempt` reject the record, so `_record` itself raises `ValueError`, displacing the original stage exception and losing the attempt line (batch still continues via `run_batch`'s generic catch). Low likelihood (codes in this codebase are ints or slugs like `pagelist-empty`), but the failure-recording path should be defensive: strip/replace forbidden markers in `_safe_error_code` instead of letting validation reject.
  - Verification: read anchor — `_safe_error_code` vs `_FORBIDDEN_MARKERS`/`_validate_attempt` in the same file; the only guard is the 64-char truncation.
  - Expected vs observed: expected — every executed stage produces a ledger record even when the code string is hostile; observed — a marker-bearing code aborts recording and masks the original error.
- S3: `--limit 0` (or negative) yields an empty selection that is "vacuously fully processed" → exit 0 (cli.py lines 186–190 with `RunSummary.fully_processed`). Consider treating `limit <= 0` as a usage error (exit 1) to distinguish "nothing selected" from "operator typo".
  - Verification: diff anchor lines 186–190 + `fully_processed` definition (lines 479–485).
  - Expected vs observed: expected — nonsensical limit flagged; observed — silent success exit 0.
- S4: `RunSummary.skipped_rows`/`failed`/`ok_count` are recomputed properties iterating `results` on each access; `_cmd_run` calls them repeatedly (lines 208–233). Trivial at CLI scale — noting only for symmetry with a future larger caller. No change requested.

### ⚪ Unconfirmed
(none — all evidence channels intact: diff parsed, worktree readable, branch/range verified)

## Source Trace
- Finding ID: W1
- Source Type: git-diff + read (worktree `src/bili_asr/coordinator.py`, `src/bili_asr/cli.py`)
- Source Reference: coordinator.py `_stage_download` / `_stage_archive_from_subtitle` / `_stage_asr_archive` / `process_row` outer except; cli.py `_run_scope_rows` failed-scope set; README "Stage-attempt ledger" section; test_coordinator.py failure-recording tests (asr only)
- Confidence: High
- Finding ID: S1 (M3 assessment)
- Source Type: git-diff
- Source Reference: coordinator.py `AttemptLedger.append` (tmp + fsync + os.replace whole-file rewrite)
- Confidence: High
- Finding ID: S2
- Source Type: read
- Source Reference: coordinator.py `_safe_error_code` vs `_validate_attempt`/`_FORBIDDEN_MARKERS`
- Confidence: Medium
- Finding ID: S3
- Source Type: git-diff
- Source Reference: cli.py `--limit` handling + `RunSummary.fully_processed`
- Confidence: High
- Finding ID: S4
- Source Type: git-diff
- Source Reference: coordinator.py `RunSummary` properties; cli.py `_cmd_run` summary printing
- Confidence: High
- Note: every finding carries Verification + Expected vs observed (see Findings above)

## Summary
| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟡 Warning | 1 |
| 🟢 Suggestion | 4 |
| ⚪ Unconfirmed | 0 |

**Verdict**: Request Changes

## Revalidation

- Re-review mode: targeted (in-place, fix round)
- Fix diff read once: `review/qc-fix.diff` (491 lines, read in full); cross-checked against worktree HEAD `d665034` (verified `git rev-parse HEAD` + `git branch --show-current` = `plan/20260825-run-coordinator-offline`; single fix commit on top of `2abf3e4`)
- Fix range: `2abf3e4..d665034` (5 files, +297/−49)
- Implementer dispositions (`task-2-report.md` § QC fix round) treated as unverified until checked against source; all claims below were confirmed by direct read of the worktree, not the report.

### Per-finding revalidation

- **W1 (download/archive failure records) — RESOLVED.**
  - `_stage_download` (coordinator.py ~lines 461–476): `audio_module.download_audio` now wrapped in `try/except Exception` → `_record("download", work_id, "failed", error_code=_safe_error_code(exc), started_at=started)` → `raise`. Re-raise preserved.
  - `_stage_archive_from_subtitle` (~lines 373–384) and `_stage_asr_archive` (~lines 426–438): both `write_archive` calls wrapped identically with `("archive", "failed")` records + re-raise.
  - No double-record: `process_row`'s outer `except` only appends to `result.failure_codes` (no `_record` call), and `run_batch`'s `_fail` dedupes by code — comment "stage-level attempt records are written by the stage wrappers" now holds for all four stages.
  - Batch-continues semantics intact: re-raised exceptions land in `run_batch`'s per-row catch chain (`RiskBudgetExhausted`/`GoneResponse`/`APIResponseError`/generic `Exception`), none of which records a duplicate stage attempt.
  - Test coverage gap closed: three new tests (`test_run_download_failure_recorded_and_reselected_by_failed_scope`, `test_run_offline_archive_write_failure_recorded`, `test_run_offline_asr_path_archive_write_failure_recorded`) cover all three wrapped sites, assert exact `(stage, outcome)` sequences, redaction (`"cdn exploded" not in attempts.jsonl`), and `--scope failed` re-selection through the wired `failed_work_ids()` path.

- **S1 (simplify marker) — RESOLVED.** `AttemptLedger.append` (coordinator.py lines 166–170) now carries a `simplify:` comment naming the O(n²) whole-file-rewrite-per-append ceiling and both upgrade paths (open-append + flush/fsync; periodic per-work compaction), per the coding-behavior marker convention.

- **S2 (`_safe_error_code` sanitization) — RESOLVED.** New `_MARKER_RE` (case-insensitive alternation over all `_FORBIDDEN_MARKERS`) + `_sanitize_code_str` (sanitize **then** truncate to 64 — correct order, so the output can never exceed `_MAX_ERROR_CODE_LEN` nor carry a marker); applied to both the string-code branch and the exception-name fallback. `_validate_attempt`'s lowercase-marker scan can no longer reject a `_safe_error_code` output, so `_record` never throws from a hostile code string and never masks the original stage exception. Test `test_safe_error_code_sanitizes_forbidden_markers` covers the hostile-code case end-to-end through `coord._record`.

- **S3 (`--limit <= 0`) — RESOLVED.** `_cmd_run` (cli.py lines 1344–1348) rejects non-positive limits with `run: --limit must be a positive integer` on stderr, exit 1, **before** scope resolution and client construction — no HTTP, no batch output; dead `if args.limit <= 0: rows = []` branch removed (now a clean `rows = rows[: args.limit]`). Test asserts `rc == 1`, stderr message, `transport.calls == []`, no `selected` output.

### New-issue sanity check (performance/reliability lens)

- Dir-fsync (qc2-F-003 addition): placed after `os.replace`, best-effort `except OSError: pass`; `dirfd` closed in `finally`; failure cannot undo the already-atomic replace nor mask the append. Correct.
- Wrapper exception paths: wrappers catch `Exception` only — `KeyboardInterrupt`/`BaseException` propagate without a phantom record, matching harvest/asr wrappers; only theoretical residual is an OSError from the ledger append itself displacing the stage exception, identical to the pre-existing wrapper pattern and not introduced by this fix.
- `fully_processed` change (F-002, qc2's finding but on my lens): `r.ok or r.skip_reason == "already_terminal"` — non-terminal skips (offline/missing_audio) still count as unprocessed → exit 1, preserving the reliability signal.
- Test robustness: all new tests offline or monkeypatched (no live HTTP), reuse existing fixtures; sequence assertions (`== [("download","failed")]` etc.) are deterministic.
- No new Critical/Warning findings on this lens.

### Verdict

| Severity | Count (post-fix) |
|----------|------------------|
| 🔴 Critical | 0 |
| 🟡 Warning | 0 (W1 resolved) |
| 🟢 Suggestion | 0 open (S1/S2/S3 resolved; S4 was no-change-requested) |

**Verdict**: **Approve** (all seat-3 findings resolved; remaining open findings on my lens: 0)

*Note (L3 boundary): the implementer's pytest runs (277 passed) are implementer-claimed evidence and were not executed by this reviewer per QC NEVER rules; final runtime verification belongs to the QA gate.*

- Revalidation Timestamp: 2026-08-25T22:30:00Z
