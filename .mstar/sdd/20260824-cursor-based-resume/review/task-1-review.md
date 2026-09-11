# Task 1 L2 review — Persist and consume cursor

Range: `361530d0a4da34de93bb86c778d1efbe061500c4..be4623ac682906735e24b4403c3719b4a4aa42d3`
Diff: `.mstar/sdd/20260824-cursor-based-resume/review/task-1.diff`
Tests: not re-run (PM: 158 passed on `be4623a`).

### Spec Compliance

- ❌ Issues found
  - `cli.py` `_cmd_fetch_meta`: without `--resume`, stale `meta-cursor.json` is replaced only after `fetch_pages` returns and the **full** JSONL save, or on interrupt via `_interrupt_cursor`. Spec + Task 1 brief: replace leftover `risk_interrupted` **after the first successful page of the new run**. There is no per-page merge/cursor write inside the success path (`cli.py` ~310–379; `bili_client.fetch_pages` still batches in memory).
- ✅ Otherwise aligned: `MetaCursorStore` schema/path/atomic `os.replace`; `state=running` rejected on persist; `--resume` only matching-mid `risk_interrupted`; risk/API/Gone persist `next_page=last_failed_page` and exit 2; `limited` vs `complete` summary; `fetch_pages(..., start_page=1)` sets `pn = start_page`; `BiliClient` does not import `meta_cursor`.
- ⚠️ Cannot verify from diff: PM pytest 158 on `be4623a`; Task 2 still owns page-2 stop/resume JSONL idempotency and broader credential scan.

### Strengths

- Cursor I/O stays in CLI/`MetaCursorStore`; HTTP remains in `bili_client`.
- `resume_start_page` is a tight predicate (state + mid).
- Total-reached is classified `complete` before the `max_pages` break, so a cap that also hits `total` does not print `limited`.
- Tests cover schema, running-not-persisted, atomic replace, start_page pn, risk exit 2, resume pn=2, no-resume pn=1, limited summary, complete + no SESSDATA/cookie in sidecar.

### Issues

#### Critical

(none)

#### Important

1. **Stale cursor not replaced after first successful page (without `--resume`)** — `cli.py` success path persists once after the whole crawl (`_persist_cursor` after `store.save`). A fresh run that has already received page 1 in memory, then dies before return (or hits the generic `except Exception` at ~356, which neither partial-saves nor touches the sidecar), leaves the previous `risk_interrupted` file. A later `--resume` will consume that old `next_page`. Spec: replace after first successful page of the new run. Fix belongs next to the first successful merge (or an explicit first-page cursor replace), not only at crawl end.

#### Minor

1. **`except Exception` does not persist interrupt** — pre-existing H1 redaction path; still no cursor write. Risk/API/Gone are covered. Task 2 may want an explicit note; not required for Task 1 if first-page replace is fixed on the success path.
2. **`isinstance(mid, int)` accepts `bool`** — JSON `true` would validate as mid. Unlikely on this sidecar.

### Assessment

**Task quality:** Needs fixes
