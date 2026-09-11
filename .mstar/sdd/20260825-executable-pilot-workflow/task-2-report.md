# Task 2 report — Pin idempotent reruns and dependency errors

Status: DONE
Working branch used: `plan/20260825-executable-pilot-workflow`
Worktree path used: `/root/workspace/bilibili-asr-archive/.worktrees/20260825-executable-pilot-workflow`
HEAD: `301c48e0bae68213e164defa84aa42b6269d694b`
BASE_SHA: `8de38460fc58294e12fc97c2ef318965d7875b67`

## What changed

- `_cmd_pilot` treats a completed archive as a skip: no processable rows but existing `archived` entries print `pilot: skip — all selected work already archived` and exit 0 (no harvest/ASR/upsert).
- Loop skips any selected `archived` row.
- `ASRDependencyError` still prints the exception (install hint) and “row not archived”, then prints branch counts before exiting 1.

## TDD triple

- Test files: `bilibili-asr-archive/tests/test_cli_pilot.py`, `bilibili-asr-archive/tests/test_pilot_select.py`
- Command:

```text
PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest tests/test_pilot_select.py tests/test_cli_pilot.py -q
```

- Output: `8 passed in 0.08s`

Full suite (same interpreter, package cwd): `175 passed in 0.45s`

New coverage:

- `test_cli_pilot_completed_rerun_skips_archived` — second `pilot --n 2` does not grow JSONL or files; ASR not called again.
- `test_cli_pilot_missing_asr_dependency_does_not_archive` — hint `pip install -e "bilibili-asr-archive/[asr]"` on stderr; subtitle archived, audio row not; rc 1.
- Existing mixed test still asserts subtitle never calls ASR; audio path exactly once.

## git

Commit `301c48e` — `bilibili-asr-archive/src/bili_asr/cli.py`, `bilibili-asr-archive/tests/test_cli_pilot.py` only. No PR. No egg-info/uv.lock.

README already documents rerun skip and optional-ASR failure (Task 1).
