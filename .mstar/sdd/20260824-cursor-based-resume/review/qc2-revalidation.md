---
report_kind: qc
reviewer: qc-specialist-2
reviewer_index: 2
plan_id: "20260824-cursor-based-resume"
verdict: "Approve"
generated_at: "2026-08-25"
---

# Code Review Report — Targeted Revalidation

## Reviewer Metadata
- Reviewer: @qc-specialist-2
- Runtime Agent ID: qc-specialist-2
- Runtime Model: grok-4.6
- Review Perspective: Security and correctness risk (R1–R4 only)
- Report Timestamp: 2026-08-25T00:20:00Z

## Scope
- plan_id: `20260824-cursor-based-resume`
- Review range / Diff basis: `ef21ddeb4f8bc65d01c7c0827b219873fc661e6a..9ab3507f06a32c23f4a42561dcf918071289326b` / prior QC HEAD vs fix HEAD
- Working branch (verified): `plan/20260824-cursor-based-resume`
- Review cwd (verified): `/root/workspace/bilibili-asr-archive/.worktrees/20260824-cursor-based-resume`
- HEAD (verified): `9ab3507f06a32c23f4a42561dcf918071289326b`
- Files reviewed: README.md, bili_client.py, cli.py, meta_cursor.py, test_meta_cursor.py, test_fetch_meta.py
- Commit range: `ef21dde..9ab3507` (one commit: `Fix fetch-meta cursor persist, JSONL merge, and page-limit semantics`)
- Analysis methods: git-diff, read, grep (no test/build)
- Deep review: skipped (targeted re-review exception)
- Prior: `review/qc2.md` (Request Changes; F-001 / F-002 Warnings)
- Consolidated: R1–R4 open Warnings
- PM pytest (not re-run): 167 passed on `9ab3507`

## Revalidation

### R1 — resume skips per-page persist (QC2-F-001) — **closed**
- Prior: `_after_successful_page` returned when `args.resume`, so JSONL/cursor only flushed on exception or terminal success.
- Fix: early-return removed. Every `on_page` merge writes JSONL then `state=risk_interrupted` with `next_page = last_completed_page + 1`. Terminal `complete`/`limited` still written only after `fetch_pages` returns. Store still rejects `running`.
- Verification: read `cli.py` `_after_successful_page` / post-`fetch_pages` `_persist_cursor`; grep `bili_client.py` has no `meta_cursor` import.
- Expected vs observed: expected per-page persist on resume vs observed persist on both resume and non-resume; crash mid-run now leaves auto-resumable `risk_interrupted`.
- Confidence: High

### R2 — non-resume page-1 JSONL prefix clobber (QC1-F-001) — **closed**
- Prior: `existing={}` without `--resume`, so first persist overwrote a complete catalog with a page-1 prefix.
- Fix: `existing = store.load()` always; last-write-wins merge. Leftover cursor is still replaced (now mid-run `risk_interrupted`, then terminal `complete`/`limited`).
- Verification: read `cli.py` `_cmd_fetch_meta` load + `_persist_partial`; test `test_cli_no_resume_merges_prior_jsonl_not_prefix` asserts `BVOLD` kept.
- Expected vs observed: expected catalog not shrunk vs observed always-merge JSONL.
- Confidence: High

### R3 — `--limit-pages` absolute `pn` ceiling (QC2-F-002) — **closed**
- Prior: `if max_pages is not None and pn > max_pages` after `start_page` existed.
- Fix: `pages_this_call` increments per successful HTTP page this call; stop when `pages_this_call >= max_pages`. Help text “Stop after N pages” now matches.
- Verification: read `bili_client.py` loop; test `test_cli_limit_pages_counts_this_call` expects `pn` `[5, 6]` for `--resume` from 5 plus `--limit-pages 2`.
- Expected vs observed: expected a per-run budget vs observed `pages_this_call`.
- Confidence: High

### R4 — resume `seen` session-local (QC3-F-002) — **closed**
- Prior: `len(seen) >= total` never fired after `start_page>1`; stop depended on empty-page streak.
- Fix: seed `seen` from JSONL bvids / `parse_work_id`; stop on `pn >= ceil(total/ps)`, non-empty page with no new bvids, `len(seen) >= total`, or two empty pages. HTTP stays in `bili_client`.
- Verification: read `fetch_pages`; grep `meta_cursor` in `bili_client.py` = none; tests `test_fetch_pages_stops_at_last_catalog_page` / `test_fetch_pages_stops_when_nonempty_adds_no_new`.
- Expected vs observed: expected last-catalog / no-new-bvid stop vs observed those predicates plus seeded `seen`.
- Confidence: High

### QC2-F-003 (Suggestion) — **superseded / improved**
Mid-run sidecar is now `risk_interrupted`, so SIGKILL after page 1 of an uncapped crawl is `--resume` consumable. README states only exit-2 `risk_interrupted` is auto-resumable. Original “first-page `limited` looks like an intentional cap” is gone.

Cheap items in the same commit (type of `on_page`, README, corrupt `load()` stderr) are consistent with source; not blocking.

## Findings
### 🔴 Critical
- None

### 🟡 Warning
- None (R1–R4 closed on this range)

### 🟢 Suggestion
- None new

### ⚪ Unconfirmed
- None

## Source Trace
- Finding ID: R1–R4 revalidation
- Source Type: git-diff | read | grep
- Source Reference: `bili_client.py` `fetch_pages`; `cli.py` `_cmd_fetch_meta`; `review/qc-fix.diff`
- Confidence: High

## Summary
| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟡 Warning | 0 |
| 🟢 Suggestion | 0 |
| ⚪ Unconfirmed | 0 |

**Verdict**: Approve

Needs L4/QA verification: PM already cites 167 passed on `9ab3507` (not re-run here).
