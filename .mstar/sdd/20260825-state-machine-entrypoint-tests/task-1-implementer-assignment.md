Execute as: fullstack-dev
Delegation: forbidden
Task category: implement
Working branch: plan/20260825-state-machine-entrypoint-tests
---

# Assignment — Plan B Task 1 (command-level state transitions)

Execution mode: sdd
SDD implementer session: fresh
Model tier: standard
Findings cleanup: zero-residual

Worktree path: `/root/workspace/bilibili-asr-archive/.worktrees/20260825-state-machine-entrypoint-tests`
Plan Path: `/root/workspace/bilibili-asr-archive/.mstar/plans/20260825-state-machine-entrypoint-tests.md`
SDD dir: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260825-state-machine-entrypoint-tests`
execution_lease holder: `dsh:goal-9443ff6c-a480-4433-915a-cf116c1a986b`
BASE_SHA: `c4ce9bbb8b6c0709699df68489619ac3e6ef5ff3` (plan A merged)

<SUBAGENT-STOP> Skip PM orchestration. Leaf implementer for Task 1 only.</SUBAGENT-STOP>

Load: `mstar-harness-core` → `mstar-host` → `references/dsh.md` → `mstar-roles` → `references/fullstack-dev.md` → `mstar-coding-behavior` → `mstar-sdd`.

Brief: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260825-state-machine-entrypoint-tests/task-1-brief.md`
Plan: `/root/workspace/bilibili-asr-archive/.mstar/plans/20260825-state-machine-entrypoint-tests.md`

## Key constraints

- Tests only (new `tests/test_cli_asr.py` + extend `test_cli_pilot.py` / `test_manifest.py` as needed); no product source changes unless a minimal test hook is required.
- Fake transport + stubbed `asr.transcribe`; monkeypatch only `build_default_transport`, `default_sleeper`, `asr.transcribe`.
- Assert externally visible outcomes: exit code, stdout/stderr, manifest records, artifact files.
- Frozen transitions: `meta_ok -> needs_audio -> audio_ok -> archived`; `meta_ok -> subtitle_done -> archived` (ASR not called). JSONL field `status`; no new intermediate statuses.
- Exit codes: 0 success; 1 usage/config/ASRDependencyError; 2 RiskBudgetExhausted/terminal gone. Do NOT "fix" mixed per-video exit-code.
- No live HTTP, model downloads, ffmpeg execution.

## Tests

`PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest tests/test_cli_asr.py tests/test_cli_pilot.py tests/test_manifest.py -q` then full suite.

## Report

`/root/workspace/bilibili-asr-archive/.mstar/sdd/20260825-state-machine-entrypoint-tests/task-1-report.md`

Commit on working branch. No PR. No egg-info/uv.lock.
