---
report_kind: qc
reviewer: qc-specialist
reviewer_index: 1
plan_id: "20260824-cursor-based-resume"
verdict: "Request Changes"
generated_at: "2026-08-24"
---

# Code Review Report

## Reviewer Metadata
- Reviewer: @qc-specialist
- Runtime Agent ID: qc-specialist
- Runtime Model: grok-4.6
- Review Perspective: Architecture coherence and maintainability risk
- Report Timestamp: 2026-08-24T23:50:00Z

## Scope
- plan_id: `20260824-cursor-based-resume`
- Review range / Diff basis: `361530d0a4da34de93bb86c778d1efbe061500c4..ef21ddeb4f8bc65d01c7c0827b219873fc661e6a` / merge-base vs plan HEAD (plan 002 start `361530d` → HEAD `ef21dde`)
- Working branch (verified): `plan/20260824-cursor-based-resume`
- Review cwd (verified): `/root/workspace/bilibili-asr-archive/.worktrees/20260824-cursor-based-resume`
- Files reviewed: 5 (`README.md`, `bili_client.py`, `cli.py`, `meta_cursor.py`, `tests/test_meta_cursor.py`)
- Commit range: `361530d0a4da34de93bb86c778d1efbe061500c4..ef21ddeb4f8bc65d01c7c0827b219873fc661e6a` (HEAD `ef21dde`)
- Analysis methods: git-diff, read, grep; deep-lens: Modularity, Contract, Standards, Testing
- Deep review: triggered (S1: 634 insertions / 5 files, S3: first `MetaCursorStore` module)
- Lenses applied: Modularity Lens, Contract Lens, Standards Lens, Testing Lens
- PM pytest (not re-run): 162 passed on `ef21dde`

Checkout: `git rev-parse --show-toplevel` and `git branch --show-current` match Assignment `Review cwd` / `Working branch`. HEAD is `ef21ddeb4f8bc65d01c7c0827b219873fc661e6a`.

## Findings
### 🔴 Critical
- None

### 🟡 Warning
- **F-001** Non-resume `on_page` persists JSONL from `existing={}` after the first archive page, which can clobber a previously complete manifest mid-run. -> Persist cursor-only on the first successful page (spec: replace leftover sidecar), or load/merge prior JSONL unless the operator explicitly requested a fresh rewrite; do not `store.save` a page-1 prefix over a full archive.
  - Verification: diff/read/grep anchor — [cli.py](/root/workspace/bilibili-asr-archive/.worktrees/20260824-cursor-based-resume/bilibili-asr-archive/src/bili_asr/cli.py) `_cmd_fetch_meta` sets `existing = store.load() if args.resume else {}`; `_after_successful_page` returns only when `args.resume`, otherwise `_persist_partial(client, store, existing, ...)`. `_persist_partial` always `store.save(entries)` from `merge_pages(client.pages_fetched)` plus that `existing`. Spec [meta-cursor.md](/root/workspace/bilibili-asr-archive/.mstar/iterations/iter-2026-08-archive-foundations/specs/meta-cursor.md) Ownership: replace stale **cursor** after first successful page, not the JSONL catalog.
  - Expected vs observed: expected first-page hook replaces `meta-cursor.json` without shrinking `manifest` JSONL; observed non-resume run writes JSONL containing only the current crawl's pages so far (page 1 ≈ 30 rows). A later risk stop then `_persist_partial` again against the already-truncated `store.load()`. Pre-existing end-of-run replace without `--resume` is a full enumeration; the new per-page save is a **prefix** write.

### 🟢 Suggestion
- **F-002** Dual persist strategy: `--resume` skips `on_page` entirely (`if args.resume: return`), so JSONL/cursor advance only on interrupt or terminal success. Spec advance rule is “persist cursor after the corresponding ManifestStore merge for that archive list page.” Kill during a multi-page resume re-fetches from the original `next_page` (last-write-wins, no dupes). Unify: same per-page merge+cursor advance on both paths, with `risk_interrupted` until terminal `complete`/`limited`.
  - Verification: diff/read — `cli.py` `_after_successful_page` first guard; interrupt path `_interrupt_cursor` only in except blocks.
  - Expected vs observed: expected one persist policy; observed resume is batch-at-end, non-resume is per-page.

- **F-003** `fetch_pages(..., on_page=None)` is an undeclared public-seam expansion. Plan Interfaces: “Add `start_page: int = 1` only; no filesystem I/O in `bili_client`.” The callback keeps FS out of the client (Modularity: good) but is untyped and invokes after empty pages as well as content pages. Type as `Callable[[], None] | None` and document that empty pages still fire (CLI no-ops when `pages_fetched` is empty).
  - Verification: spec `fetch_pages` signature vs [bili_client.py](/root/workspace/bilibili-asr-archive/.worktrees/20260824-cursor-based-resume/bilibili-asr-archive/src/bili_asr/bili_client.py) `on_page()`.
  - Expected vs observed: expected start_page-only public API; observed extra hook. Isolation invariant still holds (`test_bili_client_does_not_import_meta_cursor`).

- **F-004** `_persist_partial` re-merges **all** `pages_fetched` and rewrites JSONL after every page on the non-resume path (O(pages²) I/O). Fine for a personal UP crawl; if kept, merge only the latest page into `existing`.
  - Verification: `_after_successful_page` → `_persist_partial` → `merge_pages(client.pages_fetched)`.
  - Expected vs observed: expected incremental page merge; observed full replay each callback.

### ⚪ Unconfirmed
- None

## Source Trace
- Finding ID: F-001
- Source Type: deep-lens: Modularity Lens
- Source Reference: `cli.py` `_cmd_fetch_meta` / `_after_successful_page` / `_persist_partial`; spec Ownership + Advance rule
- Confidence: High

- Finding ID: F-002
- Source Type: deep-lens: Contract Lens
- Source Reference: `cli.py` `if args.resume or not client.pages_fetched: return`
- Confidence: High

- Finding ID: F-003
- Source Type: deep-lens: Contract Lens
- Source Reference: `bili_client.fetch_pages` vs `meta-cursor.md` `fetch_pages` seam
- Confidence: High

- Finding ID: F-004
- Source Type: deep-lens: Modularity Lens
- Source Reference: `_persist_partial` + `on_page` loop
- Confidence: Medium

## Summary
| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟡 Warning | 1 |
| 🟢 Suggestion | 3 |
| ⚪ Unconfirmed | 0 |

**Verdict**: Request Changes

Checklist (diff/read only): naming OK (`MetaCursorStore`, `resume_start_page`, `risk_interrupted`); HTTP vs FS split holds; atomic `os.replace`; `running` rejected on persist; `--resume` gated on mid+state; `complete` vs `limited` distinguished in README and CLI summary; tests cover page-2 stop, no duplicate `work_id`, redaction, stale-cursor replace. F-001 is the blocking maintainability/data-contract issue for this seat.

Needs L4/QA verification: none from this seat beyond the PM-cited 162-pass suite (not re-run).
