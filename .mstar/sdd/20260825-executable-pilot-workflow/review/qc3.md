---
report_kind: qc
reviewer: qc-specialist-3
reviewer_index: 3
plan_id: "20260825-executable-pilot-workflow"
verdict: "Request Changes"
generated_at: "2026-08-25"
---

# Code Review Report

## Reviewer Metadata
- Reviewer: @qc-specialist-3
- Runtime Agent ID: qc-specialist-3
- Runtime Model: grok-4.6
- Review Perspective: Performance and reliability (failure isolation, abort/resume, resource reuse)
- Report Timestamp: 2026-08-25T00:00:00Z

## Scope
- plan_id: `20260825-executable-pilot-workflow`
- Review range / Diff basis: `559dfcb54816a8e275e5d162ab27f86cde187476..301c48e0bae68213e164defa84aa42b6269d694b` / plan A start vs HEAD
- Working branch (verified): `plan/20260825-executable-pilot-workflow`
- Review cwd (verified): `/root/workspace/bilibili-asr-archive/.worktrees/20260825-executable-pilot-workflow`
- Files reviewed: 4 in range (`cli.py`, `test_cli_pilot.py`, `test_pilot_select.py`, `README.md`) plus read of `asr.py`, `audio.py`, `subtitles.py` for call contracts
- Commit range: `559dfcb54816a8e275e5d162ab27f86cde187476..301c48e0bae68213e164defa84aa42b6269d694b` (HEAD `301c48e`)
- Analysis methods: git-diff, read, grep; deep-lens: Performance Lens, Reliability Lens, Enforcement-Path Lens, Ownership / Derived-State Lens
- Deep review: triggered (S1: 524 insertions / 4 files; S3: first executable mixed-branch pilot; S6: cli composition + tests + asr/audio/subtitle seams)
- Lenses applied: Performance Lens, Reliability Lens, Enforcement-Path Lens, Ownership / Derived-State Lens
- L3 only: no tests/builds/live HTTP. Assignment notes 175 pytest passed on `301c48e` (not re-run).

## Findings
### 🔴 Critical
- none

### 🟡 Warning
- [F-001] Risk-budget abort skips the operator-visible branch/terminal summary -> print the same `pilot branches:` / `pilot terminal:` epilogue (or an explicit partial-run summary) before `return 2`
  - Source Type: deep-lens: Reliability Lens
  - Verification: diff/read `bilibili-asr-archive/src/bili_asr/cli.py` `_cmd_pilot` `except bili_client.RiskBudgetExhausted` (~959–966) `return 2` with only the ceiling line; success epilogue at 1007–1012 is skipped. Contrast `ASRDependencyError` (~943–954) which at least prints `pilot branches:` before `return 1`, still skipping `pilot terminal:` lines.
  - Expected vs observed: AC requires per-item failures, branch counts, and terminal states on a bounded run vs risk-control stop leaves no branch counts / terminal list for already-archived items in this process
  - Confidence: High

- [F-002] SenseVoice / `ASRModelError` is not isolated as a reported per-item failure -> catch `asr.ASRModelError` (and print its message); keep the row non-`archived` (already true if transcribe throws after `download_audio`)
  - Source Type: deep-lens: Reliability Lens
  - Verification: read `bilibili-asr-archive/src/bili_asr/asr.py` `transcribe` raises `ASRModelError` on load/generate failure (117–121). `_cmd_pilot` only special-cases `ASRDependencyError`; `ASRModelError` falls through `except Exception` (~1001–1003) to `{label}: unexpected error` with no model/offline hint.
  - Expected vs observed: plan/AC: per-item failures reported and audio row not marked archived vs operator sees a generic unexpected error, cannot tell model-missing-weights from a harvest bug; `download_audio` may already have set `audio_ok` (resume-safe) but the failure mode is not named
  - Confidence: High

### 🟢 Suggestion
- [F-003] Each audio branch constructs FunASR `AutoModel` (plus VAD/punc) inside `transcribe` with no process-level reuse or timeout
  - Source Type: deep-lens: Performance Lens
  - Verification: `asr.py` 86–116; `_pilot_archive_asr` calls `asr.transcribe` once per audio row (`cli.py` 876–877). Default `--n 20` mixed run can load SenseVoice many times in one process.
  - Expected vs observed: bounded pilot should avoid avoidable hot-path overhead vs one full model init per archived ASR row
  - Confidence: High

- [F-004] `--n` is not a hard cap after `_expand_selected_pages`; a short selected bvid can pull every processable sibling page, each still paying `time.sleep(3.0)`
  - Source Type: deep-lens: Performance Lens
  - Verification: `cli.py` 753–767, 896–897, 1004–1005; tests assert multipart expansion beyond `--n 1`
  - Expected vs observed: spec requires every pagelist `work_id` (so expansion is intended) vs README/`selected {len}/{n}` can exceed N without stating wall-clock/risk-budget growth
  - Confidence: High

- [F-005] Multipart completeness is enforced only against rows already in the manifest, not a live pagelist
  - Source Type: deep-lens: Enforcement-Path Lens
  - Verification: `_expand_selected_pages` filters `_pilot_processable(entries)` only; no `list_pages` in `_cmd_pilot`
  - Expected vs observed: AC “every pagelist work_id processed or reported failed” vs missing sibling rows are silently omitted (not failed)
  - Confidence: Medium (fetch-meta normally writes all pages; gap only if the ledger is incomplete)

### ⚪ Unconfirmed
- none

## Source Trace
- Finding ID: F-001
- Source Type: deep-lens: Reliability Lens
- Source Reference: `bilibili-asr-archive/src/bili_asr/cli.py` RiskBudgetExhausted handler vs epilogue 1007–1023
- Confidence: High
- Note: F-002 `asr.py` + `cli.py` except chain; F-003 `asr.transcribe` / `_pilot_archive_asr`; F-004 `_expand_selected_pages`; F-005 same helper vs live pagelist

## Summary
| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟡 Warning | 2 |
| 🟢 Suggestion | 3 |
| ⚪ Unconfirmed | 0 |

**Verdict**: Request Changes

Checklist (diff/read only): error handling on abort paths incomplete (F-001/F-002); resource lifecycle of FunASR per row (F-003); unbounded extras vs `--n` (F-004); failure isolation for risk/ASR otherwise matches existing CLI patterns (3s pacing, exit 2 on budget, ASRDependencyError does not archive, download skip-if-exists).

Needs L4/QA verification: live FunASR load once-vs-N and a risk-budget abort mid-run summary (do not run here).
