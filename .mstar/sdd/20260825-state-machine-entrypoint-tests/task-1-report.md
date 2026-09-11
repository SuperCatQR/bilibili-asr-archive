# Task 1 report — command-level state transitions

- Status: DONE
- Role: fullstack-dev (fresh SDD implementer)
- Working branch used: `plan/20260825-state-machine-entrypoint-tests`
- Worktree path used: `/root/workspace/bilibili-asr-archive/.worktrees/20260825-state-machine-entrypoint-tests`
- HEAD: `10ebd0238e73efe35e0d7a4adaaabfc58a37d470`
- BASE_SHA: `c4ce9bbb8b6c0709699df68489619ac3e6ef5ff3`

## Implemented

New `bilibili-asr-archive/tests/test_cli_asr.py` drives shipped commands (`harvest-subs`, `download-audio`, `asr`) with fake HTTP (`RouterTransport`) and stubbed `asr.transcribe`. Product source unchanged.

| Case | Assertion |
|------|-----------|
| Audio branch | `meta_ok` → harvest `needs_audio` → download `audio_ok` → asr `archived`; transcribe called once on the downloaded file |
| Subtitle branch | `meta_ok` → harvest `subtitle_done` → asr `archived`; transcribe never called |
| Risk exhaustion | two `meta_ok` rows; first harvest `subtitle_done`; second `-412` budget → exit 2; second row still `meta_ok`; stderr has resume wording |
| Missing ASR extra | audio path to `audio_ok`, then `ASRDependencyError` on `asr --pending` → exit 1; status stays `audio_ok` |
| Idempotent rerun | unique JSONL `work_id`s; second `asr --pending` leaves ledger bytes and unrelated `archived` row untouched |

Monkeypatch: `build_default_transport`, `default_sleeper`, `asr.transcribe` only. No live HTTP, model download, or ffmpeg.

## Tests (TDD triple)

- Test file: `bilibili-asr-archive/tests/test_cli_asr.py` (also ran existing `tests/test_cli_pilot.py`, `tests/test_manifest.py`)
- Command (from package root in the feature worktree):

```text
PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest tests/test_cli_asr.py tests/test_cli_pilot.py tests/test_manifest.py -q
```

- Output: `33 passed in 3.15s`

Full suite:

```text
PYTHONPATH=src .../python -m pytest tests -q
```

- Output: `185 passed in 3.67s`

## Files changed

- `bilibili-asr-archive/tests/test_cli_asr.py` (new)

## Self-review

- Did not change mixed per-video exit-code behavior.
- Did not invent statuses; JSONL field is `status`.
- Each command constructs a new `BiliClient`; audio-path tests rebuild transport per call so harvest does not exhaust download queues.
- `test_cli_pilot.py` / `test_manifest.py` already cover overlapping pilot/manifest cases; no extra edits required.

No PR opened.
