# Task 3 L2 fix report

Status: DONE

Working branch used: `plan/20260824-multipart-page-aware-pipeline`
Worktree path used: `/root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline`

HEAD: `fa20305bc85db07c7b2667b1d8bf6512705c35c8`
Parent: `817b5c89597ec2eda2a3ff729f440daa1a8c612a`

## Change

`write_archive` markdown frontmatter now includes `work_id`, `page_index`, and `cid` when the entry has a `work_id` and is not `unresolved`. Unresolved / missing-`work_id` rows omit those keys (no fabricated identity).

## Tests (TDD triple)

- Files: `bilibili-asr-archive/tests/test_archive_md.py`
- Command (cwd product root): `.venv-pm/bin/python -m pytest -q`
- Output:

```
........................................................................ [ 51%]
.....................................................................    [100%]
141 passed in 0.35s
```

## Notes

Did not touch L2 minors (asr mixed exit, probe_subs WBI, `.p` assert). Did not commit `egg-info` or `uv.lock`. No PR.
