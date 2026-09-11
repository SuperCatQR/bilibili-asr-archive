---
report_kind: qc
reviewer: qc-specialist
reviewer_index: 1
plan_id: "20260825-executable-pilot-workflow"
verdict: "Request Changes"
generated_at: "2026-08-25"
---

# Code Review Report

## Reviewer Metadata
- Reviewer: @qc-specialist
- Runtime Agent ID: qc-specialist
- Runtime Model: grok-4.6
- Review Perspective: Architecture coherence and maintainability risk
- Report Timestamp: 2026-08-25T00:00:00Z

## Scope
- plan_id: 20260825-executable-pilot-workflow
- Review range / Diff basis: `559dfcb54816a8e275e5d162ab27f86cde187476..301c48e0bae68213e164defa84aa42b6269d694b` / plan A start vs HEAD
- Working branch (verified): `plan/20260825-executable-pilot-workflow`
- Review cwd (verified): `/root/workspace/bilibili-asr-archive/.worktrees/20260825-executable-pilot-workflow`
- Files reviewed: 4 (README.md, src/bili_asr/cli.py, tests/test_cli_pilot.py, tests/test_pilot_select.py) plus locked seams `subtitles.harvest_subtitle`, `asr.transcribe`, `archive.write_archive`, `_identity_from_entry`
- Commit range (if not identical to Review range line, explain): `559dfcb54816a8e275e5d162ab27f86cde187476..301c48e0bae68213e164defa84aa42b6269d694b` (HEAD `301c48e`)
- Analysis methods: git-diff, read, grep, deep-lens: Modularity Lens, Contract Lens, Standards Lens, Testing Lens
- Deep review: triggered (S1: 524 insertions / 4 files, S3: first executable pilot composition vs prior selection-only `_cmd_pilot`)
- Lenses applied: Modularity Lens, Contract Lens, Standards Lens, Testing Lens
- PM pytest (assignment-ci-note, not re-run): 175 passed on `301c48e`

## Findings
### 🔴 Critical
- None.

### 🟡 Warning
- [F-001] Branch-coverage gate only counts archives produced in the current process, so a documented resume after partial success cannot reach exit 0 -> count already-`archived` opposite-branch rows in the loaded manifest (or in the original selection set) when deciding `subtitle_count` / `audio_count`, or skip the mixed-coverage check once both branches exist as terminal `archived` in the store.
  - Source Type: deep-lens: Contract Lens
  - Verification: diff/read/grep anchor (`cli.py` `_PILOT_PROCESSABLE` excludes `archived`; `_cmd_pilot` increments `subtitle_count`/`audio_count` only inside this-run success paths; final `if subtitle_count == 0 or audio_count == 0: return 1`)
  - Expected vs observed: expected resume after Task 2 missing-ASR (subtitle already archived, audio still processable) to complete the audio branch and exit 0 once ASR is available vs observed second run selects only `needs_audio`/`audio_ok`, `subtitle_count` stays 0, stderr `missing branch coverage: subtitle`
  - Confidence: High
  - Trigger: first mixed run archives the subtitle row then hits `ASRDependencyError` on the audio row (covered by `test_cli_pilot_missing_asr_dependency_does_not_archive`); operator installs `[asr]` and re-runs `pilot --n 2`
  - Impact: the install-hint / non-archived-audio path cannot be completed by the same command without failing the mixed-branch proof bar; Task 2 idempotent-rerun only covers the all-archived skip, not this resume

- [F-002] Empty selection treats any `archived` row in the whole ledger as a successful “already archived” skip -> distinguish “no processable rows because the selected work is archived” from “processable set is empty while other terminal states remain” (`gone` / excluded / failed); only return 0 when every previously selected / in-scope work_id is `archived` (or when the processable set is empty *and* no non-archived in-scope rows exist)
  - Source Type: deep-lens: Contract Lens
  - Verification: diff/read/grep anchor (`cli.py` `if not selected: if any(e.get("status") == "archived" for e in entries.values()): print("pilot: skip — all selected work already archived"); return 0`)
  - Expected vs observed: expected skip-0 only when the bounded pilot has nothing left to do vs observed a single archived row plus leftover `gone`/`unresolved` yields exit 0 and a skip message that is not true of the rest of the ledger
  - Confidence: High

### 🟢 Suggestion
- [F-003] `_pilot_archive_asr` always `download_audio`s, including resume `audio_ok` rows that `_cmd_asr` already transcribes from `entry["audio_path"]` -> reuse the existing audio path when `status == "audio_ok"` (or after `download_audio` reports a cached file) so pilot and `asr` share one archive-from-audio composition
  - Source Type: deep-lens: Modularity Lens
  - Verification: diff/read/grep anchor (`cli.py` `_pilot_archive_asr` vs `_cmd_asr` audio_path join)
  - Expected vs observed: expected one composition path for audio→ASR vs observed a second download-then-transcribe helper that can rewrite audio on resume
  - Confidence: High

- [F-004] Broad `except Exception` / generic `ValueError` handling hides unexpected composition failures behind `unexpected error` with no type or traceback -> log `type(exc).__name__` (and keep the existing allowlist for cid/unresolved/missing JSON)
  - Source Type: deep-lens: Standards Lens
  - Verification: diff/read/grep anchor (`cli.py` `_cmd_pilot` `except ValueError` / `except Exception`)
  - Expected vs observed: expected operator-visible failure class vs observed silent bucket matching `_cmd_asr`
  - Confidence: Medium

- [F-005] After `_expand_selected_pages`, `pilot: selected {len(selected)}/{args.n}` can print `3/1` for a multi-part bvid; extras are required by AC but the counter still claims a hard `--n` cap -> print selected work_ids vs `--n` plus expanded sibling count
  - Source Type: deep-lens: Contract Lens
  - Verification: diff/read/grep anchor (`_expand_selected_pages` concatenates extras after `_pilot_select(..., n)`; print uses `len(selected)/args.n`)
  - Expected vs observed: expected bounded N as a selection budget with explicit page expansion vs observed a fraction that can exceed 1
  - Confidence: High

- [F-006] Tests do not cover F-001 resume-after-partial-ASR or F-002 empty-select skip; mixed/multipart/missing-branch/full-rerun/missing-ASR happy paths are present
  - Source Type: deep-lens: Testing Lens
  - Verification: diff/read/grep anchor (`tests/test_cli_pilot.py` five tests; no second `main(["pilot"...])` after the missing-ASR case)
  - Expected vs observed: expected a failing test for resume coverage vs observed only first-run missing-ASR
  - Confidence: High

### ⚪ Unconfirmed
- None.

## Source Trace
- Finding ID: F-001
- Source Type: deep-lens: Contract Lens
- Source Reference: `bilibili-asr-archive/src/bili_asr/cli.py` `_cmd_pilot` coverage return; `_PILOT_PROCESSABLE`
- Confidence: High
- Note: every finding carries `Verification` + `Expected vs observed` — see the Findings entry format above

- Finding ID: F-002
- Source Type: deep-lens: Contract Lens
- Source Reference: `bilibili-asr-archive/src/bili_asr/cli.py` empty-`selected` skip
- Confidence: High

- Finding ID: F-003
- Source Type: deep-lens: Modularity Lens
- Source Reference: `_pilot_archive_asr` vs `_cmd_asr`
- Confidence: High

- Finding ID: F-004
- Source Type: deep-lens: Standards Lens
- Source Reference: `_cmd_pilot` except blocks
- Confidence: Medium

- Finding ID: F-005
- Source Type: deep-lens: Contract Lens
- Source Reference: `_expand_selected_pages` + selected print
- Confidence: High

- Finding ID: F-006
- Source Type: deep-lens: Testing Lens
- Source Reference: `tests/test_cli_pilot.py`
- Confidence: High

## Summary
| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟡 Warning | 2 |
| 🟢 Suggestion | 4 |
| ⚪ Unconfirmed | 0 |

**Verdict**: Request Changes

Layering is otherwise coherent: HTTP stays in `BiliClient`, FunASR stays inside `asr.transcribe`, `harvest_subtitle` is not split, `--sessdata` is a cookie value and tests assert it is not echoed or persisted. Locked live seams are composed from `cli` as the plan requires. F-001/F-002 block Approve under zero-residual (unresolved Warning).

Needs L4/QA verification: focused pytest already cited by PM (175 passed on `301c48e`); do not treat that as coverage of F-001 resume.
