---
report_kind: qc
reviewer: qc-specialist-2
reviewer_index: 2
plan_id: "20260825-state-machine-entrypoint-tests"
verdict: "Approve"
generated_at: "2026-08-25T12:20:00+08:00"
---

# Code Review Report

## Reviewer Metadata
- Reviewer: @qc-specialist-2
- Runtime Agent ID: qc-specialist-2
- Runtime Model: gemini-3.7-flash
- Review Perspective: Security and correctness risk
- Report Timestamp: 2026-08-25T12:20:00+08:00

## Scope
- plan_id: `20260825-state-machine-entrypoint-tests`
- Review range / Diff basis: `c4ce9bbb8b6c0709699df68489619ac3e6ef5ff3..79652889e7e7b7a6c8419a4bf30badf6f73ee757` / plan B start (plan A merge) vs HEAD
- Working branch (verified): `plan/20260825-state-machine-entrypoint-tests`
- Review cwd (verified): `/root/workspace/bilibili-asr-archive/.worktrees/20260825-state-machine-entrypoint-tests`
- Files reviewed: 2 test files modified in diff (`tests/test_cli_asr.py`, `tests/test_cli_help.py`), plus reference modules (`cli.py`, `manifest.py`, `asr.py`, `bili_client.py`, `test_audio.py`, `test_subtitles.py`, `test_cli_pilot.py`), plan document, and frozen spec `asr-archive-cli.md`
- Commit range: `c4ce9bbb8b6c0709699df68489619ac3e6ef5ff3..79652889e7e7b7a6c8419a4bf30badf6f73ee757` (HEAD `7965288`)
- Analysis methods: git-diff (`plan-B.diff`), read, grep, deep-lens: Security Lens, Correctness Lens, Bounds Lens, Real-Entry-Path Lens
- Deep review: triggered (S1: 391 insertions across 2 test files; S6: full state machine transition testing and subprocess packaging entrypoint validation)
- Lenses applied: Security Lens, Correctness Lens, Bounds Lens, Real-Entry-Path Lens
- PM pytest evidence (not re-run): 189 passed on `7965288`

## Findings
### 🔴 Critical
- None.

### 🟡 Warning
- None.

### 🟢 Suggestion
- [F-001] `_run_installed` and `_run_module` in `test_cli_help.py` invoke `subprocess.run` without an explicit `timeout` argument -> Add a sensible subprocess timeout (e.g., `timeout=30`) as defensive hygiene against potential hung subprocesses in CI / testing environments.
  - Source Type: deep-lens: Security Lens
  - Verification: `bilibili-asr-archive/tests/test_cli_help.py:47-66` defines `_run_installed` and `_run_module` wrapping `subprocess.run(...)` with `capture_output=True, text=True` but no `timeout`.
  - Expected vs observed: test subprocess calls specify defensive execution bounds vs unbounded subprocess run.
  - Confidence: High
  - Impact: Low risk; commands under test (`--help`, `status`) terminate in milliseconds, but explicit timeouts protect against hangs.

- [F-002] Fixture parameter `tmp_path` in `test_cli_help.py` is annotated as `pytest.TempPathFactory` instead of `pathlib.Path` -> Update type annotation to `pathlib.Path`.
  - Source Type: deep-lens: Standards Lens
  - Verification: `bilibili-asr-archive/tests/test_cli_help.py:82, 92, 126` annotates `tmp_path: pytest.TempPathFactory`. The pytest built-in fixture `tmp_path` injects a `pathlib.Path` instance, while `pytest.TempPathFactory` is for `tmp_path_factory`.
  - Expected vs observed: type annotation matches runtime fixture type (`pathlib.Path`) vs factory class annotation.
  - Confidence: High
  - Impact: Benign cosmetic type hint; runtime execution and string conversion `str(tmp_path)` are unaffected.

- [F-003] Unused imported symbol `artifact_stem` in `test_cli_asr.py:12` -> Remove unused import to keep dependencies tidy.
  - Source Type: deep-lens: Standards Lens
  - Verification: `bilibili-asr-archive/tests/test_cli_asr.py:12` imports `artifact_stem, page_identity`; only `page_identity` is referenced in the file.
  - Expected vs observed: imported symbols are referenced vs unused import present.
  - Confidence: High
  - Impact: Benign lint/cosmetic only.

### ⚪ Unconfirmed
- None.

## Security & Correctness Assessment

### Security Lens
- **Subprocess Execution Safety**: `_run_installed` and `_run_module` invoke commands via argument lists (`[exe, *args]` / `[sys.executable, "-m", "bili_asr", *args]`), avoiding `shell=True` and preventing shell injection vulnerabilities.
- **Environment Isolation**: `_run_installed` cleanly strips `PYTHONPATH` from `os.environ` (`env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}`), ensuring that the installed console script tests execute strictly against installed packages rather than repository source trees.
- **Credential Hygiene**: No secrets, auth cookies, or mock SESSDATA tokens are leaked or hardcoded in global fixtures.
- **Filesystem Boundaries**: All test routines operate within isolated temporary directories (`tmp_root` / `tmp_path`), guaranteeing no unintended side-effects or mutations on live archive directories.

### Correctness & State Machine Lens
- **Audio Pipeline Transition (`meta_ok -> needs_audio -> audio_ok -> archived`)**: Verified through sequential CLI invocations (`harvest-subs` -> `download-audio` -> `asr`). Manifest status transitions, intermediate disk artifacts (`audio_path`, `srt_path`), and exact single-pass ASR transcription calls are asserted.
- **Subtitle Pipeline Transition (`meta_ok -> subtitle_done -> archived`)**: Verified through `harvest-subs` -> `asr`. Asserts that subtitle extraction produces valid transcript outputs and correctly skips ASR execution (`transcribe_calls == []`).
- **Risk Budget Exhaustion (Exit 2 & State Preservation)**: Validated under simulated 412 risk-control responses. Manifest entries maintain last stable states (`subtitle_done` for successful video, `meta_ok` for throttled video), emitting proper resume instructions on stderr.
- **Missing Optional Dependency (Exit 1 & Non-Archived Status)**: Verified using `ASRDependencyError`. Asserts exit code 1, actionable stderr installation guidance, and guarantees the record remains in `audio_ok` without premature transition to `archived`.
- **Rerun Idempotency & Manifest Integrity**: Verified that repeated executions of `asr` produce identical JSONL records without duplicate lines or unintended mutations on unrelated archive entries.

### Real-Entry-Path & Packaging Lens
- **Console Script Execution**: Tests locate the installed binary via Python virtualenv binary directories and PATH, skipping gracefully with actionable `pip install -e ".[asr,dev]"` instructions when the package is uninstalled without polluting test output.
- **Separation of Packaging vs Module Tests**: Subprocess execution of `bili-asr` is completely decoupled from `python -m bili_asr` and direct `cli.main` tests.

## Source Trace
- Finding ID: F-001
- Source Type: deep-lens: Security Lens
- Source Reference: `bilibili-asr-archive/tests/test_cli_help.py:47-66`
- Confidence: High

- Finding ID: F-002
- Source Type: deep-lens: Standards Lens
- Source Reference: `bilibili-asr-archive/tests/test_cli_help.py:82, 92, 126`
- Confidence: High

- Finding ID: F-003
- Source Type: deep-lens: Standards Lens
- Source Reference: `bilibili-asr-archive/tests/test_cli_asr.py:12`
- Confidence: High

## Summary
| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟡 Warning | 0 |
| 🟢 Suggestion | 3 |
| ⚪ Unconfirmed | 0 |

**Verdict**: Approve

The implementation strictly satisfies all plan objectives, contract boundaries, and security/correctness requirements with zero residual regressions.

## Completion Report
- Role: qc-specialist-2 (Seat 2)
- Working branch: `plan/20260825-state-machine-entrypoint-tests`
- Review cwd: `/root/workspace/bilibili-asr-archive/.worktrees/20260825-state-machine-entrypoint-tests`
- Report: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260825-state-machine-entrypoint-tests/review/qc2.md`
- Verdict: Approve
- Worktree: not mutated; no PR
