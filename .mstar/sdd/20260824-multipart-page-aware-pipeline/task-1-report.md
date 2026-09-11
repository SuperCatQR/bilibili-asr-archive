# Task 1 report — Define identity and migrate legacy rows

- Status: DONE
- Worktree path used: `/root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline`
- Working branch: `plan/20260824-multipart-page-aware-pipeline`

## Implemented / attempted

- Added `bili_asr.page_identity` with frozen `PageIdentity`, `format_work_id`, `parse_work_id`, `artifact_stem`, and `page_query_index`.
- `ManifestStore` now keys JSONL by `work_id` when present; `bvid` remains required. Legacy bare-bvid rows still load under the original `bvid` key to feed migration.
- `get(work_id)` is exact. `get_compatible(bvid)` returns the single processable row, or a preserved unresolved bare row, and never guesses among multiple pages.
- `migrate_legacy_rows(pages_for, archive_root)` is atomic (`save` via `.tmp` + `os.replace`):
  - Unambiguous (pagelist length 1, no `{bvid}.pN` N≠0 artifacts, destination `work_id` free): rewrite key to `{bvid}:p0`, set `page_index`/`cid`/`page_label` from the injected pagelist.
  - Ambiguous: original fields preserved; additive `unresolved` / `unresolved_reason=ambiguous_bare_bvid` / `excluded_from_page_processing`; no `work_id`/`page_index`/`cid` invented.
  - Collision with an existing destination `work_id` row raises `ManifestMigrationCollision`.
- `bili-asr status` prints unresolved count and identifiers. Operator rewrite CLI is out of scope.

## Tests

Command (product root):

```text
uv venv .venv-task1 --python 3.12
uv pip install -e '.[dev]' --python .venv-task1/bin/python
.venv-task1/bin/python -m pytest
```

Output:

```text
collected 127 items
...
============================= 127 passed in 0.62s ==============================
```

TDD: new red-path cases live in `tests/test_page_identity.py` (stem has no `:`) and `tests/test_manifest.py` (single-page migrate; freeze multi-page bare row; `get_compatible` does not guess; artifact / work_id collision). Existing harvest/audio tests still pass via legacy bare-bvid keys.

Local `.venv-task1` and egg-info were not committed.

## Files changed

- `bilibili-asr-archive/src/bili_asr/page_identity.py` (new)
- `bilibili-asr-archive/src/bili_asr/manifest.py`
- `bilibili-asr-archive/src/bili_asr/cli.py`
- `bilibili-asr-archive/tests/test_page_identity.py` (new)
- `bilibili-asr-archive/tests/test_manifest.py`

## Commits (SHAs)

- `d15f50f72cb978848308e369258cf7551e918168` Add page identity and migrate unambiguous legacy manifest rows

## Self-review notes

- Harvest / playurl still take bare `bvid`; Task 1 did not rewire those seams.
- `upsert` still accepts legacy rows without `work_id` so existing callers keep working; automatic rows that include `work_id` are keyed by it.
- `cid` is never used as a primary key.
- `artifact_stem` is `{bvid}.p{page_index}`; `:` stays only in `work_id`.
- No live HTTP, no model download, no SESSDATA/signed-URL logging changes.
