Execute as: fullstack-dev
Delegation: forbidden
Task category: bugfix
Working branch: plan/20260825-executable-pilot-workflow
---

# Assignment — Plan A QC Warning fix (R1–R3)

Execution mode: sdd
SDD implementer session: fresh
Model tier: standard
Findings cleanup: zero-residual

Worktree path: `/root/workspace/bilibili-asr-archive/.worktrees/20260825-executable-pilot-workflow`
Plan Path: `/root/workspace/bilibili-asr-archive/.mstar/plans/20260825-executable-pilot-workflow.md`
SDD dir: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260825-executable-pilot-workflow`
execution_lease holder: `dsh:goal-9443ff6c-a480-4433-915a-cf116c1a986b`
HEAD: `301c48e0bae68213e164defa84aa42b6269d694b` (both tasks L2 Approved; do NOT redo them)

<SUBAGENT-STOP> Skip PM orchestration. Leaf implementer. Fix the three consolidated QC Warnings only.</SUBAGENT-STOP>

Consolidated: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260825-executable-pilot-workflow/review/qc-consolidated.md`
Spec: `/root/workspace/bilibili-asr-archive/.mstar/specs/asr-archive-cli.md`

## Must fix

1. **R1 — branch coverage counts this-run archives only.** Count already-`archived` opposite-branch rows from the loaded manifest (or selection set) when deciding `subtitle_count`/`audio_count`; or skip the mixed-coverage check once both branches exist as terminal `archived` in the store. A resume after missing-ASR (subtitle archived, audio processable) must be able to exit 0 once the audio branch completes.

2. **R2 — empty-selection skip too broad.** `--n < 1` or any single `archived` row must not exit 0 when processable or leftover `gone`/excluded rows remain. Only return 0 when no non-archived in-scope rows remain.

3. **R3 — named failure reporting + risk summary.** `ASRModelError` (and generic exceptions) report the exception class name as a named per-item failure, not `unexpected error`. `RiskBudgetExhausted` abort prints the same branch/terminal summary the rest of the command prints.

Cheap suggestions OK: `audio_ok` resume reuses `existing audio_path`; selected print shows expanded sibling count vs `--n`.

Tests for R1 (resume-after-partial-ASR) and R2 (empty-select skip with leftover rows). Full suite must pass.

## Tests

`PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest -q`

## Report

`/root/workspace/bilibili-asr-archive/.mstar/sdd/20260825-executable-pilot-workflow/qc-fix-report.md`

Commit. No PR. No egg-info/uv.lock.
