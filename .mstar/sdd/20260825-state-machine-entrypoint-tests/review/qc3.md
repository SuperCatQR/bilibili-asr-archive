---
report_kind: qc
reviewer: qc-specialist-3
reviewer_index: 3
plan_id: "20260825-state-machine-entrypoint-tests"
verdict: "Approve"
generated_at: "2026-08-25T12:18:00+08:00"
---

# Code Review Report

## Reviewer Metadata
- Reviewer: @qc-specialist-3
- Runtime Agent ID: qc-specialist-3
- Runtime Model: Gemini 3.7 Flash (High)
- Review Perspective: Performance and reliability (failure isolation, abort/resume, resource reuse, subprocess isolation)
- Report Timestamp: 2026-08-25T12:18:00+08:00

## Scope
- plan_id: `20260825-state-machine-entrypoint-tests`
- Review range / Diff basis: `c4ce9bbb8b6c0709699df68489619ac3e6ef5ff3..79652889e7e7b7a6c8419a4bf30badf6f73ee757` (plan B start / plan A merge vs HEAD `7965288`)
- Working branch (verified): `plan/20260825-state-machine-entrypoint-tests`
- Review cwd (verified): `/root/workspace/bilibili-asr-archive/.worktrees/20260825-state-machine-entrypoint-tests`
- Files reviewed: 2 in diff (`bilibili-asr-archive/tests/test_cli_asr.py`, `bilibili-asr-archive/tests/test_cli_help.py`), plus plan doc (`.mstar/plans/20260825-state-machine-entrypoint-tests.md`), spec (`.mstar/specs/asr-archive-cli.md`), and related test fixtures (`conftest.py`, `test_audio.py`, `test_subtitles.py`)
- Commit range: `c4ce9bbb8b6c0709699df68489619ac3e6ef5ff3..79652889e7e7b7a6c8419a4bf30badf6f73ee757`
- Analysis methods: git-diff review, static source and boundary analysis, seam verification, failure injection path validation; no tests, builds, lint, or live HTTP were run (PM reported 189 pytest passed on `7965288`)
- Deep review: triggered (S1: 391 insertions / 2 test files; S6: command state-machine orchestration, installed console script packaging verification, mock seams)
- Lenses applied: Performance Lens, Reliability Lens, Failure Isolation / Abort-Resume Lens, Resource Lifecycle / Subprocess Lens, Testing / Mock Boundary Lens

## Findings
### 🔴 Critical
- None.

### 🟡 Warning
- None.

### 🟢 Suggestion
- [F-001] Subprocess helpers in `test_cli_help.py` (`_run_installed` and `_run_module`) do not specify an execution `timeout`
  - Source Type: deep-lens: Resource Lifecycle / Subprocess Lens
  - Verification: `bilibili-asr-archive/tests/test_cli_help.py:47-66`. `subprocess.run` is invoked without `timeout=...`.
  - Expected vs observed: While `bili-asr --help` and `bili-asr status` are fast, specifying a defensive timeout (e.g., `timeout=15`) on subprocess test helpers prevents test runner hangs in constrained CI environments if a binary hangs.
  - Confidence: High

- [F-002] Type annotations for `tmp_path` parameters in `test_cli_help.py` use `pytest.TempPathFactory` instead of `pathlib.Path`
  - Source Type: deep-lens: Testing / Mock Boundary Lens
  - Verification: `bilibili-asr-archive/tests/test_cli_help.py:82, 92, 126`. `tmp_path` is a `pathlib.Path` fixture; `pytest.TempPathFactory` is the type for `tmp_path_factory`.
  - Expected vs observed: Pure cosmetic type-hint inaccuracy with zero runtime impact, but should be annotated as `pathlib.Path` for strict typing tools.
  - Confidence: High

- [F-003] Unused import `artifact_stem` in `test_cli_asr.py`
  - Source Type: deep-lens: Static Hygiene
  - Verification: `bilibili-asr-archive/tests/test_cli_asr.py:12` imports `artifact_stem` from `bili_asr.page_identity`, which is not referenced in the file.
  - Expected vs observed: Remove unused import to maintain clean flake8/ruff lint hygiene.
  - Confidence: High

### ⚪ Unconfirmed
- None.

## Source Trace
- Finding ID: F-001
  - Source Type: deep-lens: Resource Lifecycle / Subprocess Lens
  - Source Reference: `bilibili-asr-archive/tests/test_cli_help.py:47-66`
  - Confidence: High
  - Note: Best-practice defensive subprocess timeout.

- Finding ID: F-002
  - Source Type: deep-lens: Testing / Mock Boundary Lens
  - Source Reference: `bilibili-asr-archive/tests/test_cli_help.py:82, 92, 126`
  - Confidence: High
  - Note: Minor type annotation cosmetic.

- Finding ID: F-003
  - Source Type: deep-lens: Static Hygiene
  - Source Reference: `bilibili-asr-archive/tests/test_cli_asr.py:12`
  - Confidence: High
  - Note: Harmless unused import.

## Reliability & Performance Assessment

1. **State Machine Transitions & Ledger Integrity**:
   - `test_cli_audio_branch_meta_ok_needs_audio_audio_ok_archived` rigorously verifies the entire audio pipeline transition (`meta_ok -> needs_audio -> audio_ok -> archived`) across `harvest-subs`, `download-audio`, and `asr --pending`, verifying that artifact generation and transcription occur exactly once.
   - `test_cli_subtitle_branch_meta_ok_subtitle_done_archived_skips_asr` explicitly asserts that the subtitle-hit branch (`meta_ok -> subtitle_done -> archived`) skips ASR invocation altogether (`transcribe_calls == []`).
   - `test_cli_asr_rerun_idempotent_leaves_unrelated_rows` validates JSONL idempotency under re-runs: line count, unique work IDs, and unrelated manifest rows (`BVother`) remain byte-exact and untouched across multiple executions.

2. **Failure Isolation & Abort/Resume**:
   - `test_cli_harvest_risk_exhaustion_preserves_last_stable_status` verifies the risk-control ceiling behavior (exit code 2): earlier successful rows (`BVok`) retain `subtitle_done`, while the blocked row (`BVrisk`) stays stable in `meta_ok` without ledger corruption or half-written states.
   - `test_cli_asr_missing_optional_asr_exits_1_non_archived` verifies that missing ASR optional dependency exits 1 with clear stderr instructions (`ASR dependency unavailable`), keeping the manifest item in `audio_ok` without marking it falsely `archived`.

3. **Installed Entrypoint & Packaging Isolation**:
   - `test_cli_help.py` enforces real packaging boundary verification: `_run_installed` strips `PYTHONPATH` from the subprocess environment, ensuring `bili-asr` executes as a genuine installed console script.
   - The `installed_bili_asr` fixture provides a graceful `pytest.skip` with clear installation prerequisites (`pip install -e '.[asr,dev]'`) when the binary is absent, guaranteeing zero environment mutation during test discovery/execution.
   - Module entrypoint (`python -m bili_asr`) and direct API (`cli.main`) tests are cleanly separated from the console script integration tests.

4. **Resource Management & Test Performance**:
   - `_patch_cli` replaces `bc.default_sleeper` with a zero-delay noop lambda and routes HTTP calls through memory-backed `RouterTransport`.
   - `asr.transcribe` is fully stubbed; no live network sockets, FunASR model weights, torch imports, or ffmpeg processes are spawned during test execution.
   - Per-test temp roots (`tmp_root` / `tmp_path`) ensure complete file isolation without cross-test leakage.

## Summary
| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟡 Warning | 0 |
| 🟢 Suggestion | 3 |
| ⚪ Unconfirmed | 0 |

**Verdict**: Approve
