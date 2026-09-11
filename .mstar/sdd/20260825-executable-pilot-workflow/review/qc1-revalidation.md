---
report_kind: qc
reviewer: qc-specialist
reviewer_index: 1
plan_id: "20260825-executable-pilot-workflow"
verdict: "Approve"
generated_at: "2026-08-25"
---

# Code Review Report

## Reviewer Metadata
- Reviewer: @qc-specialist
- Runtime Agent ID: qc-specialist
- Runtime Model: grok-4.6
- Review Perspective: Architecture coherence and maintainability risk (targeted revalidation R1–R3)
- Report Timestamp: 2026-08-25T12:00:00Z

## Scope
- plan_id: 20260825-executable-pilot-workflow
- Review range / Diff basis: `301c48e0bae68213e164defa84aa42b6269d694b..c4ce9bbb8b6c0709699df68489619ac3e6ef5ff3` / prior QC HEAD vs fix HEAD
- Working branch (verified): `plan/20260825-executable-pilot-workflow`
- Review cwd (verified): `/root/workspace/bilibili-asr-archive/.worktrees/20260825-executable-pilot-workflow`
- Files reviewed: 2 (`src/bili_asr/cli.py`, `tests/test_cli_pilot.py`) plus read of `audio.download_audio` skip-if-exists
- Commit range: identical to Review range; HEAD `c4ce9bbb8b6c0709699df68489619ac3e6ef5ff3`
- Analysis methods: git-diff, read, grep (no test/build runs)
- Deep review: skipped (targeted revalidation exception)
- PM pytest (assignment-ci-note, not re-run): 180 passed on `c4ce9bb`

## Revalidation

Prior QC1 (`review/qc1.md`) verdict Request Changes. Consolidated open Warnings R1–R3.

### R1 — branch coverage counts only this run (QC1-F-001)

**Status: closed**

`_archived_branch_counts` seeds `subtitle_count`/`audio_count` from ledger rows with `status == "archived"` (`audio_path` → audio-asr, else subtitle). `_cmd_pilot` still increments on this-run archive. Archived rows are skipped in the loop, so resume after Task-2 missing-ASR (subtitle already archived, audio still processable) does not leave `subtitle_count == 0`.

Test `test_cli_pilot_resume_after_partial_asr_counts_archived_subtitle` encodes the two-run sequence and asserts exit 0 without `missing branch coverage`.

Heuristic is coarse (any archived `audio_path` is audio-asr) but matches the consolidated fix and subtitle archive does not set `audio_path`.

### R2 — empty-selection skip too broad (QC1-F-002)

**Status: closed**

`leftover` is every non-`archived` row. Empty `selected` with leftover → exit 1 `no processable rows`. Skip-0 only when leftover is empty and at least one archived row exists. Empty manifest still exits 1.

`--n 0` with processable rows and archived+`gone` are covered by `test_cli_pilot_empty_n_with_processable_rows_does_not_skip` and `test_cli_pilot_archived_plus_gone_does_not_skip`.

### R3 — named failures / risk summary (QC1-F-004; consolidated R3)

**Status: closed**

Generic `ValueError` and `except Exception` print `type(exc).__name__`. `RiskBudgetExhausted` calls `_pilot_print_summary` before exit 2. `ASRDependencyError` also prints the shared summary.

Tests: `test_cli_pilot_asr_model_error_names_exception`, `test_cli_pilot_risk_budget_prints_branch_summary`.

### Cheap suggestions from prior QC1

- F-003: `audio_ok` reuses existing `audio_path` when the file exists; `download_audio` still skip-if-exists on that path.
- F-005: selected print is row count vs `--n` plus pagelist note.
- F-006: R1/R2 tests added.

## Findings
### Critical
- None.

### Warning
- None.

### Suggestion
- None remaining from this wave.

### Unconfirmed
- None.

## Source Trace
- Finding ID: R1 (closed)
- Source Type: git-diff
- Source Reference: `cli.py` `_archived_branch_counts`, `_cmd_pilot` seed + skip-archived
- Confidence: High

- Finding ID: R2 (closed)
- Source Type: git-diff
- Source Reference: `cli.py` leftover / empty-selected branch
- Confidence: High

- Finding ID: R3 (closed)
- Source Type: git-diff
- Source Reference: `_pilot_print_summary`; `except` naming
- Confidence: High

## Summary
| Severity | Count |
|----------|-------|
| Critical | 0 |
| Warning | 0 |
| Suggestion | 0 |
| Unconfirmed | 0 |

**Verdict**: Approve

R1–R3 closed on `c4ce9bb`. Zero-residual for this seat.

Needs L4/QA verification: PM-cited 180 passed on `c4ce9bb` (not re-run here).
