---
report_kind: qc-fix
plan_id: "20260824-cursor-based-resume"
role: fullstack-dev
head_before: "ef21ddeb4f8bc65d01c7c0827b219873fc661e6a"
head: "9ab3507f06a32c23f4a42561dcf918071289326b"
---

# QC Warning fix report

Worktree path used: `/root/workspace/bilibili-asr-archive/.worktrees/20260824-cursor-based-resume`
Working branch used: `plan/20260824-cursor-based-resume`

## Fixes

1. **R1** — `_after_successful_page` now runs on resume and non-resume. Each successful archive-list page merges JSONL and persists `state=risk_interrupted` with `next_page = last_completed_page + 1`. Terminal `complete`/`limited` is written only after `fetch_pages` returns. `running` is still rejected by the store.

2. **R2** — `fetch-meta` always loads the existing JSONL and last-write-wins merges. Without `--resume` the leftover cursor is replaced; a complete catalog is not overwritten with a page-1 prefix.

3. **R3** — `max_pages` counts HTTP pages fetched **this call**, not `pn > N`.

4. **R4** — Stop when `pn >= ceil(total/ps)`, when a non-empty page adds no new bvids, when `len(seen) >= total`, or after two empty pages. Optional `known_bvids` seeds `seen`; `bili_client` still does not import `meta_cursor`.

Cheap: `on_page: Callable[[], None] | None`; README states only exit-2 `risk_interrupted` is `--resume` consumable; corrupt `load()` prints to stderr.

## Tests

Command: `PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest -q`

Output: `167 passed in 0.53s`

New/updated: `tests/test_meta_cursor.py` (R1–R4 + corrupt load), `tests/test_fetch_meta.py` (pacing totals).

---

# F-005 (QC3 revalidation)

HEAD before this fix: `9ab3507f06a32c23f4a42561dcf918071289326b`

`cli._cmd_fetch_meta` now seeds `known_bvids` **only when `--resume`**. Full recrawl passes `known_bvids=None` so `fetch_pages` cannot stop on the first overlapping JSONL page; it still walks `ceil(total/ps)` and last-write-wins refreshes the ledger. `BiliClient` still has no `meta_cursor` import.

Regression: `test_cli_full_recrawl_walks_catalog_despite_page1_overlap` in `tests/test_meta_cursor.py`. Resume-seeding test `test_fetch_pages_stops_when_nonempty_adds_no_new` remains green.

Command: `PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest -q`

Output: `168 passed in 0.49s`
