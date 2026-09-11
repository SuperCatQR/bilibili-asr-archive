---
report_kind: qc
reviewer: qc-specialist-2
reviewer_index: 2
plan_id: "20260825-executable-pilot-workflow"
verdict: "Request Changes"
generated_at: "2026-08-25"
---

# Code Review Report

## Reviewer Metadata
- Reviewer: @qc-specialist-2
- Runtime Agent ID: qc-specialist-2
- Runtime Model: grok-4.6
- Review Perspective: Security and correctness risk
- Report Timestamp: 2026-08-25T00:00:00Z

## Scope
- plan_id: 20260825-executable-pilot-workflow
- Review range / Diff basis: `559dfcb54816a8e275e5d162ab27f86cde187476..301c48e0bae68213e164defa84aa42b6269d694b` / plan A start vs HEAD
- Working branch (verified): plan/20260825-executable-pilot-workflow
- Review cwd (verified): /root/workspace/bilibili-asr-archive/.worktrees/20260825-executable-pilot-workflow
- Files reviewed: 4 (README.md, cli.py, test_cli_pilot.py, test_pilot_select.py) plus helpers harvest_subtitle / download_audio / ManifestStore.upsert / asr.py import boundary
- Commit range: 559dfcb54816a8e275e5d162ab27f86cde187476..301c48e0bae68213e164defa84aa42b6269d694b (HEAD 301c48e)
- Analysis methods: git-diff, review-package plan-A.diff, read, grep; deep-lens Security / Correctness / Bounds / Real-Entry-Path
- Deep review: triggered (S1: 524 insertions / 4 files, S3: first executable mixed-branch pilot vs prior select-only)
- Lenses applied: Security Lens, Correctness Lens, Bounds Lens, Real-Entry-Path Lens

HEAD matches Assignment tip. No worktree mutation. Tests/builds not run (L3). Assignment notes PM pytest 175 passed on `301c48e` (read-only).

## Findings
### 🔴 Critical
- None

### 🟡 Warning
- [F-001] `--n < 1` with any `archived` row reports a successful completed-rerun skip -> reject non-positive `--n` before the empty-selection shortcut, or distinguish "selector empty because n<1" from "nothing processable because already archived"
  - Source Type: deep-lens: Bounds Lens
  - Verification: diff/read/grep anchor (`cli.py` `_pilot_select` returns `[]` when `n < 1`; `_cmd_pilot` then `if not selected` / `any(... status == "archived")` prints `pilot: skip — all selected work already archived` and `return 0`)
  - Expected vs observed: expected invalid/zero bound not to claim idempotent completed skip vs observed `pilot --n 0` (or negative) succeeding whenever the ledger already has an archived row, even if processable `meta_ok` rows remain
  - Confidence: High

- [F-002] Mixed-branch coverage is counted only for archives created in this invocation, so a resumable leftover set that is single-branch exits 1 even when the other branch is already `archived` -> count historical terminals in the selected bvids (or in the ledger) toward coverage, or skip the missing-branch gate when this run is a partial resume of an already mixed corpus
  - Source Type: deep-lens: Correctness Lens
  - Verification: diff/read/grep anchor (`_cmd_pilot` increments `subtitle_count` / `audio_count` only after `_pilot_archive_*`; `archived` rows are not in `_PILOT_PROCESSABLE` so they never enter `selected`; empty `selected` is the only idempotent skip. Frozen spec: all commands idempotent/resumable; plan AC: unavailable branch coverage vs completed rerun)
  - Expected vs observed: expected a later `pilot --n N` that only has leftover `needs_audio`/`audio_ok` (subtitle already archived) to resume that work vs observed `subtitle_count == 0` → `missing branch coverage: subtitle` and exit 1
  - Confidence: High

### 🟢 Suggestion
- [F-003] `ASRModelError` (and other post-download ASR failures) fall through `except Exception` as `unexpected error` with no install/model hint -> catch `asr.ASRModelError` beside `ASRDependencyError` with a stable stderr line (row still not `archived`)
  - Source Type: deep-lens: Correctness Lens
  - Verification: diff/read/grep anchor (`cli.py` `_cmd_pilot` handles `ASRDependencyError` only; `asr.py` defines `ASRModelError`; generic `except Exception` prints `unexpected error`)
  - Expected vs observed: expected operator-visible SenseVoice load/transcribe failure vs observed opaque unexpected error
  - Confidence: Medium

### ⚪ Unconfirmed
- None

## Source Trace
- Finding ID: F-001
- Source Type: deep-lens: Bounds Lens
- Source Reference: `bilibili-asr-archive/src/bili_asr/cli.py` `_pilot_select` / `_cmd_pilot` empty-selection skip
- Confidence: High
- Note: F-002 Correctness Lens on coverage counters; F-003 Suggestion on ASRModelError

## Summary
| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟡 Warning | 2 |
| 🟢 Suggestion | 1 |
| ⚪ Unconfirmed | 0 |

**Verdict**: Request Changes

Security Lens: `--sessdata` is a cookie value via `_resolve_sessdata`; tests assert the secret is absent from stdout/stderr/manifest; harvest still downloads signed subtitle URLs without persisting them. No Critical credential leak in the diff.

Real-Entry-Path Lens: `tests/test_cli_pilot.py` drives shipped `main(["pilot", ...])` with injected transport + stubbed `asr.transcribe` (no FunASR at `asr` module import).

Needs L4/QA verification: focused pytest already cited by PM on `301c48e`; do not re-run here. After F-001/F-002 fix, add cases for `--n 0` with mixed archived+processable, and a resume where subtitle is already archived and only the audio leftover remains.
