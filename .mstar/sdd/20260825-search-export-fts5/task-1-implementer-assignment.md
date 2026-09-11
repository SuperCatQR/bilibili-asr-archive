Execute as: fullstack-dev
Delegation: forbidden
Task category: implement
Working branch: plan/20260825-search-export-fts5
---

# Assignment — Plan D Task 1 (index build + search)

Execution mode: sdd
SDD implementer session: fresh
Model tier: standard
Findings cleanup: zero-residual

Worktree path: `/root/workspace/bilibili-asr-archive/.worktrees/20260825-search-export-fts5`
Plan Path: `/root/workspace/bilibili-asr-archive/.mstar/plans/20260825-search-export-fts5.md`
SDD dir: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260825-search-export-fts5`

<SUBAGENT-STOP> Skip PM orchestration. Leaf implementer for Task 1 only.</SUBAGENT-STOP>

Brief: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260825-search-export-fts5/task-1-brief.md`
Plan: `/root/workspace/bilibili-asr-archive/.mstar/plans/20260825-search-export-fts5.md`

## Scope (Task 1 only)

- `SearchIndex.build(manifest)` indexes only **completed transcript** rows: `archived` or `subtitle_done` **with transcript/archive paths present**. `audio_ok` without transcripts is not searchable as complete.
- `bili-asr search` queries FTS5 with ranking; bounded `--limit`; no results → exit 1 with clear message.
- Rebuild idempotent; stale detection documented.
- FTS5 unavailable → environment prerequisite error (no silent skip of core behavior).

## Tests

Focused + full suite:
```
cd /root/workspace/bilibili-asr-archive/.worktrees/20260825-search-export-fts5/bilibili-asr-archive
PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest tests/test_search_index.py -q
PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest -q
```

## Report

`/root/workspace/bilibili-asr-archive/.mstar/sdd/20260825-search-export-fts5/task-1-report.md`

Commit on working branch. No PR. No egg-info/uv.lock.
