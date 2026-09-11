# Task 1 report — Execute a bounded mixed pilot

- Status: DONE
- Working branch used: `plan/20260825-executable-pilot-workflow`
- Worktree path used: `/root/workspace/bilibili-asr-archive/.worktrees/20260825-executable-pilot-workflow`
- Commit: `8de38460fc58294e12fc97c2ef318965d7875b67`
- BASE_SHA: `559dfcb54816a8e275e5d162ab27f86cde187476`

## Implemented

- `_pilot_select` chooses processable `meta_ok` / `subtitle_done` / `needs_audio` / `audio_ok` rows, prefers short `duration_s`, and still reserves one known subtitle row and one known audio row when those statuses already exist.
- `_expand_selected_pages` pulls in every processable pagelist `work_id` for selected bvids (no page-1-only success).
- `bili-asr pilot --n N` harvests first; subtitle hits call `write_archive(..., source="subtitle")` without `transcribe`; misses call `download_audio` then `transcribe` then `write_archive(..., source="asr")` and persist `archived` plus `audio_path`.
- Per-item failures continue; missing subtitle or audio-asr coverage exits 1 and names the missing branch; `ASRDependencyError` prints the install hint and does not mark the row archived.
- `--sessdata` / `BILI_SESSDATA` is a cookie value via `_resolve_sessdata`; never printed or written to the ledger.

## Tests (TDD triple)

- Test files: `bilibili-asr-archive/tests/test_pilot_select.py`, `bilibili-asr-archive/tests/test_cli_pilot.py`
- Command (worktree package root, sibling venv, no live HTTP):

```text
PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest tests/test_pilot_select.py tests/test_cli_pilot.py -q
PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest -q
```

- Output:

```text
......                                                                   [100%]
6 passed in 0.05s
173 passed in 0.64s
```

Fake `build_default_transport` + stubbed `asr.transcribe`.

## Files changed

- `bilibili-asr-archive/src/bili_asr/cli.py`
- `bilibili-asr-archive/tests/test_pilot_select.py`
- `bilibili-asr-archive/tests/test_cli_pilot.py`
- `bilibili-asr-archive/README.md`

## Self-review

- Live seams unchanged (`harvest_subtitle` status string, `download_audio` path, lazy `transcribe`, keyword-only `write_archive`).
- `bili_client` remains the only HTTP owner; FunASR is not imported at CLI import time.
- Task 2 (idempotent rerun coverage as a dedicated test, extra ASR-missing fixture) is out of this task; skip-archived is already implied by the processable selector.
