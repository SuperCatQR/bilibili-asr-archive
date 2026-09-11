# Task 1 L2 re-review — stale cursor after first successful page

Range: `be4623ac682906735e24b4403c3719b4a4aa42d3..7d4161f9d73c5dbfa97ac5c4c1d5406b48c8cd66`
Diff: `.mstar/sdd/20260824-cursor-based-resume/review/task-1-fix.diff`
Prior: `.mstar/sdd/20260824-cursor-based-resume/review/task-1-review.md`
Tests: not re-run (PM: 159 passed on `7d4161f`).

### Spec Compliance

- ✅ Spec compliant for the Important finding: without `--resume`, leftover `risk_interrupted` is replaced after the first successful archive-list page merge (`cli.py` `_after_successful_page`; `state=running` never persisted). `BiliClient` still does not import `meta_cursor`; optional `on_page` is CLI-owned.
- Advance rule: `_persist_partial` (JSONL merge) runs before `_persist_cursor`.
- ✅ `--resume` path skips this replace (`args.resume` early return).
- ⚠️ Cannot verify from diff: PM pytest 159 on `7d4161f`.

### Strengths

- Regression test `test_cli_no_resume_replaces_stale_cursor_after_first_page` aborts after page 1 via sleeper, asserts sidecar is no longer `risk_interrupted` / not resumable, then `--resume` starts `pn=1`.
- Cursor I/O remains in CLI; HTTP loop only invokes a callback after a completed `_request`.
- Empty HTTP pages do not count: `not client.pages_fetched` skips merge/replace until a non-empty page is appended.

### Issues

#### Critical

(none)

#### Important

(none — prior Important is addressed)

#### Minor

1. **Mid-crawl JSONL truncation without `--resume`** — first `on_page` merges into `existing={}` and `store.save`s, so a crash after page 1 now replaces a previously complete JSONL with page-1-only rows. Matches no-resume full-rewrite semantics, just earlier; Task 2 / plan QC if a preserve-until-complete policy is wanted.
2. **Carried from prior L2:** generic `except Exception` still does not persist interrupt; `isinstance(mid, int)` still accepts `bool`. Out of scope for this fix.
3. **`on_page` is untyped** (`on_page=None`) — fine for a private seam; spec `fetch_pages` signature did not include it.

### Assessment

**Task quality:** Approved
