# Task 3 report

- Status: DONE
- Working branch used: `plan/20260824-multipart-page-aware-pipeline`
- Worktree path used: `/root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline`

## Implemented / attempted

- `write_archive` names srt/txt/raw/md with `artifact_stem` (`{bvid}.p{page_index}`); md filename includes that stem. Public URL adds `?p=` via `page_query_index` when `page_index` > 0.
- Unresolved / bare-bvid rows keep the legacy `{bvid}.*` stem and are never assigned `work_id`.
- `asr --pending` / `asr --bvid` iterate page rows, skip excluded rows, upsert by `work_id`, and read subtitle/audio files by stem. A failed p0 does not skip p1.
- `download-audio --bvid`: if `_todo_for_bvid` returns `[]` (unresolved), STOP with exit 1; do not fabricate a `needs_audio` page.
- Operator note in product `README.md` (legacy migration + page-aware resume).

## Tests

- Files: `bilibili-asr-archive/tests/test_archive_md.py`, `bilibili-asr-archive/tests/test_page_pipeline.py`
- Command (product root): `.venv-pm/bin/python -m pytest -q`
- Output: `141 passed in 0.35s` (re-run on current HEAD)

## Files changed

- `bilibili-asr-archive/src/bili_asr/archive.py`
- `bilibili-asr-archive/src/bili_asr/cli.py`
- `bilibili-asr-archive/tests/test_archive_md.py`
- `bilibili-asr-archive/tests/test_page_pipeline.py`
- `bilibili-asr-archive/README.md`

## Commits (SHAs)

- `817b5c89597ec2eda2a3ff729f440daa1a8c612a` Use artifact_stem for archive outputs and STOP unresolved --bvid (HEAD)
- parent `30a12d8f8c701935a7abd478784fbf326200968e` Cache WBI keys so two-page harvest does not exhaust nav (kept; not reverted)

## Self-review notes

- Did not add egg-info or uv.lock.
- Unknown `--bvid` still creates a fresh download/asr target; only empty `_todo_for_bvid` (unresolved/excluded) STOPs.
- Single-page adapters remain: p0 URL has no `?p=`; unresolved artifacts stay on the bare bvid.
