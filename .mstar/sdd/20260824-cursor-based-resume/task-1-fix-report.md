# Task 1 L2 fix report — stale cursor after first successful page

Status: DONE
Working branch used: `plan/20260824-cursor-based-resume`
Worktree path used: `/root/workspace/bilibili-asr-archive/.worktrees/20260824-cursor-based-resume`
HEAD: `7d4161f9d73c5dbfa97ac5c4c1d5406b48c8cd66`

## Change

Without `--resume`, `_cmd_fetch_meta` now passes `on_page` into `BiliClient.fetch_pages`. After each successful HTTP archive-list page that produced rows, the CLI merges JSONL then replaces leftover `risk_interrupted` with `limited` or `complete` (`state=running` is never persisted). HTTP stays in `bili_client`; the client still does not import `meta_cursor`.

A later crash before the terminal persist no longer leaves the previous `next_page` consumable by `--resume`.

## TDD triple

- Tests: `bilibili-asr-archive/tests/test_meta_cursor.py` (`test_cli_no_resume_replaces_stale_cursor_after_first_page`)
- Command: `PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest -q`
- Output: `159 passed in 0.39s`

## Out of scope

Minors from L2 (bool mid; generic `except Exception` interrupt persist) not changed.
