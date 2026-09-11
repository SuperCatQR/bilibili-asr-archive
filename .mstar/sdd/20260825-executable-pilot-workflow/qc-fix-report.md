# QC fix report — 20260825-executable-pilot-workflow

Role: fullstack-dev
Working branch used: plan/20260825-executable-pilot-workflow
Worktree path used: /root/workspace/bilibili-asr-archive/.worktrees/20260825-executable-pilot-workflow
HEAD: `c4ce9bbb8b6c0709699df68489619ac3e6ef5ff3`

## Fixes

- **R1**: `_archived_branch_counts` seeds `subtitle_count`/`audio_count` from already-`archived` ledger rows (`audio_path` → audio-asr, else subtitle). Resume after subtitle archived + audio still processable no longer reports missing subtitle coverage.
- **R2**: empty selection only skips with exit 0 when every in-scope row is `archived`. `--n < 1` or leftover `gone`/excluded/processable rows exit 1 (`no processable rows`).
- **R3**: generic/`ASRModelError` per-item lines use `type(exc).__name__`. `RiskBudgetExhausted` prints the same branch/terminal summary via `_pilot_print_summary` before exit 2.

Cheap: `audio_ok` reuses existing `audio_path` when the file is present; selected print reports expanded row count vs `--n`.

## Tests

Command: `PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest -q`

Result: `180 passed in 0.54s`

New cases in `bilibili-asr-archive/tests/test_cli_pilot.py`:
- `test_cli_pilot_resume_after_partial_asr_counts_archived_subtitle`
- `test_cli_pilot_empty_n_with_processable_rows_does_not_skip`
- `test_cli_pilot_archived_plus_gone_does_not_skip`
- `test_cli_pilot_asr_model_error_names_exception`
- `test_cli_pilot_risk_budget_prints_branch_summary`

No PR.
