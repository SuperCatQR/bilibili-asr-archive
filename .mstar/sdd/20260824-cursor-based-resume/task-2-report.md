# Task 2 report — Prove idempotency and security

- Status: DONE
- Working branch used: `plan/20260824-cursor-based-resume`
- Worktree path used: `/root/workspace/bilibili-asr-archive/.worktrees/20260824-cursor-based-resume`
- HEAD: `ef21ddeb4f8bc65d01c7c0827b219873fc661e6a`

## Implemented

- End-to-end test: page-1 merge, 412 exhaust on page 2 → `next_page=2` / `risk_interrupted` / JSONL only BV1A+BV1B; `--resume` requests `pn=2`, adds BV1C, no duplicate `work_id` lines, terminal `complete`.
- Cursor persist strips extra keys; `last_api_error_code` must be a short redacted scalar; forbidden markers (`SESSDATA`, cookie, URLs, Traceback) rejected.
- README documents `--resume`, exit 2, sidecar fields, and that failed pages are not claimed complete.

## Tests (TDD triple)

- Files: `bilibili-asr-archive/tests/test_meta_cursor.py`
- Command (from `bilibili-asr-archive/` in the feature worktree):

```text
PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest -q
```

- Output: `162 passed in 0.46s` (no live HTTP)

## Files changed

- `bilibili-asr-archive/src/bili_asr/meta_cursor.py`
- `bilibili-asr-archive/tests/test_meta_cursor.py`
- `bilibili-asr-archive/README.md`

## Self-review

- HTTP remains in `bili_client`; cursor still schema-only.
- T1 leftover-cursor replace behavior untouched.
- No PR, no egg-info/uv.lock.
