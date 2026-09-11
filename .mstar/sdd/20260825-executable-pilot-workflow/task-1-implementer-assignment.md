Execute as: fullstack-dev
Delegation: forbidden
Task category: implement
Working branch: plan/20260825-executable-pilot-workflow
---

# Assignment — Plan A Task 1 (executable pilot)

Execution mode: sdd
SDD implementer session: fresh
Model tier: standard
Findings cleanup: zero-residual

Worktree path: `/root/workspace/bilibili-asr-archive/.worktrees/20260825-executable-pilot-workflow`
Plan Path: `/root/workspace/bilibili-asr-archive/.mstar/plans/20260825-executable-pilot-workflow.md`
SDD dir: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260825-executable-pilot-workflow`
execution_lease holder: `dsh:goal-9443ff6c-a480-4433-915a-cf116c1a986b`
BASE_SHA: `559dfcb54816a8e275e5d162ab27f86cde187476`

<SUBAGENT-STOP> Skip PM orchestration. Leaf implementer for Task 1 only.</SUBAGENT-STOP>

Load: `mstar-harness-core` → `mstar-host` → `references/dsh.md` → `mstar-roles` → `references/fullstack-dev.md` → `mstar-coding-behavior` → `mstar-sdd`.

Brief: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260825-executable-pilot-workflow/task-1-brief.md`
Plan: `/root/workspace/bilibili-asr-archive/.mstar/plans/20260825-executable-pilot-workflow.md`

## Key constraints (from locked plan)

- `harvest_subtitle` returns status string (`subtitle_done` | `needs_audio`), not a path; `download_audio` returns audio path; `transcribe` lazy-imports funasr; `write_archive` keyword-only `source`/`raw`.
- `--sessdata` is a cookie VALUE via `_resolve_sessdata`; never echoed/persisted.
- No schema migration; JSONL last-write-wins per `work_id`; `VALID_STATUSES`/`classify_risk` unchanged.
- Multi-part: every pagelist `work_id` (`bvid:pN`) processed or reported failed; no page-1-only success.
- No live HTTP in tests (inject fake transport + stub `asr.transcribe`).
- Missing ASR → `ASRDependencyError` + install hint + nonzero; never `archived`.

## Tests

Use sibling venv (no venv in this worktree):
`PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest -q`

Focused: `... tests/test_pilot_select.py tests/test_cli_pilot.py -q` then full suite.

## Report

`/root/workspace/bilibili-asr-archive/.mstar/sdd/20260825-executable-pilot-workflow/task-1-report.md`

Commit on working branch. No PR. No egg-info/uv.lock.
