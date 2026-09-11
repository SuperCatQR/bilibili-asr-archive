---
report_kind: qc
reviewer: qc-specialist-2
reviewer_index: 2
plan_id: "20260825-executable-pilot-workflow"
verdict: "Approve"
generated_at: "2026-08-25"
---

# Code Review Report

## Reviewer Metadata
- Reviewer: @qc-specialist-2
- Runtime Agent ID: qc-specialist-2
- Runtime Model: grok-4.6
- Review Perspective: Security and correctness risk (targeted revalidation R1–R3)
- Report Timestamp: 2026-08-25T12:00:00Z

## Scope
- plan_id: 20260825-executable-pilot-workflow
- Review range / Diff basis: `301c48e0bae68213e164defa84aa42b6269d694b..c4ce9bbb8b6c0709699df68489619ac3e6ef5ff3` / prior QC HEAD vs fix HEAD
- Working branch (verified): plan/20260825-executable-pilot-workflow
- Review cwd (verified): /root/workspace/bilibili-asr-archive/.worktrees/20260825-executable-pilot-workflow
- Files reviewed: 2 (`cli.py`, `test_cli_pilot.py`) plus `qc-fix.diff` / `qc-fix-report.md`
- Commit range: 301c48e0bae68213e164defa84aa42b6269d694b..c4ce9bbb8b6c0709699df68489619ac3e6ef5ff3 (HEAD c4ce9bb)
- Analysis methods: git-diff, read, grep; targeted revalidation of QC2 F-001/F-002/F-003 mapped to consolidated R2/R1/R3
- Deep review: not re-triggered (targeted revalidation exception; fix range is one commit / two files)

HEAD matches Assignment tip. No worktree mutation. Tests/builds not run (L3). Assignment notes PM pytest 180 passed on `c4ce9bb` (read-only).

## Revalidation

| ID | Prior | Status | Evidence |
|----|-------|--------|----------|
| R1 / QC2-F-002 | Warning | **Closed** | `_archived_branch_counts` seeds `subtitle_count`/`audio_count` from ledger `archived` rows (`audio_path` → audio-asr, else subtitle) before the process loop; this-run archives still increment. Resume with leftover `needs_audio`/`audio_ok` no longer starts at 0/0. Test: `test_cli_pilot_resume_after_partial_asr_counts_archived_subtitle`. |
| R2 / QC2-F-001 | Warning | **Closed** | Empty selection: any non-`archived` leftover → stderr `no processable rows` exit 1; skip-0 only when leftover is empty and at least one `archived` row exists. `--n 0` with processable rows cannot claim completed-rerun skip. Tests: `test_cli_pilot_empty_n_with_processable_rows_does_not_skip`, `test_cli_pilot_archived_plus_gone_does_not_skip`. |
| R3 / QC2-F-003 | Suggestion (consolidated Warning) | **Closed** | Generic/`ValueError` fallback and `except Exception` print `type(exc).__name__` (covers `ASRModelError`). `RiskBudgetExhausted` calls `_pilot_print_summary` before exit 2. Tests: `test_cli_pilot_asr_model_error_names_exception`, `test_cli_pilot_risk_budget_prints_branch_summary`. |

Cheap suggestions from consolidated (audio_ok reuse existing file; selected print vs `--n`) are in the same diff; not re-raised.

## Findings
### 🔴 Critical
- None

### 🟡 Warning
- None (prior R1–R3 closed)

### 🟢 Suggestion
- None new

### ⚪ Unconfirmed
- None

## Source Trace
- Finding ID: R1–R3 closed
- Source Type: git-diff | read
- Source Reference: `bilibili-asr-archive/src/bili_asr/cli.py` `_archived_branch_counts`, leftover empty-select branch, `_pilot_print_summary`, named `except Exception as exc`
- Confidence: High

## Summary
| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟡 Warning | 0 |
| 🟢 Suggestion | 0 |
| ⚪ Unconfirmed | 0 |

**Verdict**: Approve

Needs L4/QA verification: Assignment cites 180 passed on `c4ce9bb`; do not re-run here.
