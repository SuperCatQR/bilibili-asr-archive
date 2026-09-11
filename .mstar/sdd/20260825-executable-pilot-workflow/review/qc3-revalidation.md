---
report_kind: qc
reviewer: qc-specialist-3
reviewer_index: 3
plan_id: "20260825-executable-pilot-workflow"
verdict: "Approve"
generated_at: "2026-08-25"
---

# Code Review Report — Revalidation

## Reviewer Metadata
- Reviewer: @qc-specialist-3
- Runtime Agent ID: qc-specialist-3
- Runtime Model: grok-4.6
- Review Perspective: Performance and reliability (failure isolation, abort/resume, resource reuse)
- Report Timestamp: 2026-08-25T10:30:00Z

## Scope
- plan_id: `20260825-executable-pilot-workflow`
- Review range / Diff basis: `301c48e0bae68213e164defa84aa42b6269d694b..c4ce9bbb8b6c0709699df68489619ac3e6ef5ff3` / prior QC HEAD vs fix HEAD
- Working branch (verified): `plan/20260825-executable-pilot-workflow`
- Review cwd (verified): `/root/workspace/bilibili-asr-archive/.worktrees/20260825-executable-pilot-workflow`
- HEAD (verified): `c4ce9bbb8b6c0709699df68489619ac3e6ef5ff3`
- Files reviewed: `cli.py`, `test_cli_pilot.py` (fix range); read of `asr.py` `ASRModelError`; package `review/qc-fix.diff`
- Analysis methods: git-diff, read, grep; targeted R1–R3 only
- L3 only: no tests/builds. Assignment notes 180 pytest passed on `c4ce9bb` (not re-run).

## Revalidation

### R3 (QC3-F-001) Risk-budget abort summary — closed
- Verification: `cli.py` `except bili_client.RiskBudgetExhausted` now calls `_pilot_print_summary(subtitle_count, audio_count, failed, terminals)` then `return 2`. Same helper used on the normal epilogue and `ASRDependencyError` abort.
- Expected vs observed: operator-visible `pilot branches:` / `pilot terminal:` on risk stop vs previously only the ceiling line.
- Confidence: High
- Note: `_pilot_print_summary` still omits `failed=` when `failed == 0`; risk path increments `failed` first, so the failed count is present on this abort.

### R3 (QC3-F-002) Named ASR / generic failures — closed
- Verification: `except Exception as exc` prints `{label}: {type(exc).__name__}`. `ASRModelError` subclasses `RuntimeError` and is not caught earlier, so the operator sees `ASRModelError` rather than `unexpected error`. Dedicated `except asr.ASRModelError` is not present; consolidated R3 asked for class name, which this satisfies.
- Expected vs observed: named per-item failure vs generic unexpected error.
- Confidence: High
- Residual wording: still no model/offline hint beyond the class name; not a Warning under R3 as written.

### R1 / R2 (not originally QC3 Warnings)
- R1: `_archived_branch_counts` seeds from ledger `archived` rows. Reliability of mixed-branch resume is improved; no new abort-path issue from this seat.
- R2: empty selection with leftover non-archived rows exits 1. `--n < 1` no longer takes the completed-rerun skip when processable rows exist.

### Cheap suggestions from original QC3
- F-003 FunASR per-row init: **not addressed** (still Suggestion; not in R1–R3).
- F-004 `--n` vs expand: selected print now `selected {len} rows (--n {n}; includes pagelist siblings)` — **addressed**.
- F-005 live pagelist completeness: **not addressed** (still Suggestion; Medium; out of this wave).

### Cheap audio reuse
- `audio_ok` + existing `audio_path` file: reuse `out_path` before `download_audio`. Reliability-positive; no new Warning.

## Findings
### Critical
- none

### Warning
- none (prior F-001 / F-002 closed in this range)

### Suggestion
- [F-003] FunASR `AutoModel` still constructed inside `transcribe` per audio row (unchanged)
  - Verification: `asr.py` transcribe body; `_pilot_archive_asr` still calls `asr.transcribe` once per row
  - Expected vs observed: process-level reuse vs one init per archived ASR row
- [F-005] Multipart completeness still only vs in-manifest processable siblings (unchanged)

### Unconfirmed
- none

## Summary
| Severity | Count |
|----------|-------|
| Critical | 0 |
| Warning | 0 |
| Suggestion | 2 (pre-existing, non-blocking) |
| Unconfirmed | 0 |

**Verdict**: Approve

Needs L4/QA verification: live FunASR load once-vs-N (F-003); do not run here.
