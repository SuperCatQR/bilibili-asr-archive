Execute as: fullstack-dev
Delegation: forbidden
Task category: implement
Working branch: plan/20260825-search-export-fts5
---

# Assignment — Plan D Task 2 (export + integration)

Execution mode: sdd
SDD implementer session: fresh
Model tier: standard
Findings cleanup: zero-residual

Worktree path: `/root/workspace/bilibili-asr-archive/.worktrees/20260825-search-export-fts5`
Plan Path: `/root/workspace/bilibili-asr-archive/.mstar/plans/20260825-search-export-fts5.md`
SDD dir: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260825-search-export-fts5`

<SUBAGENT-STOP> Skip PM orchestration. Leaf implementer for Task 2 only.</SUBAGENT-STOP>

Brief: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260825-search-export-fts5/task-2-brief.md`
Plan: `/root/workspace/bilibili-asr-archive/.mstar/plans/20260825-search-export-fts5.md`

## Scope (Task 2 only)

- `bili-asr export --format json|csv [--out <path>] [--status ...] [--with-text] [--archive-root]` → manifest-derived metadata; transcript bodies only with `--with-text`.
- `--with-text` includes transcript text; never includes credentials/signed URLs.
- README documents search/export, rebuild, and manifest-as-SSOT boundary.
- Manifest stays SSOT; export never rewrites it.

## Tests

Focused + full suite:
```
cd /root/workspace/bilibili-asr-archive/.worktrees/20260825-search-export-fts5/bilibili-asr-archive
PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest tests/test_search_index.py -q
PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest -q
```

## Report

`/root/workspace/bilibili-asr-archive/.mstar/sdd/20260825-search-export-fts5/task-2-report.md`

Commit on working branch. No PR. No egg-info/uv.lock.
