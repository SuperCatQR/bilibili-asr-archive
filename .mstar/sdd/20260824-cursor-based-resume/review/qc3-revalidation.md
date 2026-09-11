---
report_kind: qc
reviewer: qc-specialist-3
reviewer_index: 3
plan_id: "20260824-cursor-based-resume"
verdict: "Request Changes"
generated_at: "2026-08-24"
---

# Code Review Report — QC3 targeted revalidation

## Reviewer Metadata
- Reviewer: @qc-specialist-3
- Runtime Agent ID: qc-specialist-3
- Runtime Model: grok-4.6
- Review Perspective: Performance and reliability (R1–R4 only)
- Report Timestamp: 2026-08-24T00:20:00Z

## Scope
- plan_id: 20260824-cursor-based-resume
- Review range / Diff basis: `ef21ddeb4f8bc65d01c7c0827b219873fc661e6a..9ab3507f06a32c23f4a42561dcf918071289326b` / prior QC HEAD vs fix HEAD
- Working branch (verified): `plan/20260824-cursor-based-resume`
- Review cwd (verified): `/root/workspace/bilibili-asr-archive/.worktrees/20260824-cursor-based-resume`
- HEAD (verified): `9ab3507f06a32c23f4a42561dcf918071289326b`
- Files reviewed: fix diff (`cli.py`, `bili_client.py`, `meta_cursor.py`, tests, README)
- Analysis methods: git rev-parse, read, grep; no tests/builds/lint
- Deep review: skipped (targeted re-review exception)
- L3 only: Assignment notes PM pytest 167 passed on `9ab3507` (not re-run)

## Revalidation (R1–R4)

| ID | Prior QC3 | Status after `9ab3507` |
|----|-----------|------------------------|
| R1 (QC3-F-001) | resume skipped `_after_successful_page` | **Closed.** Callback no longer returns on `args.resume`. Each successful HTTP page merges JSONL and writes `state=risk_interrupted`, `next_page=last_completed_page+1`. Terminal `complete`/`limited` remains after `fetch_pages` returns. `running` is still not flushed. |
| R2 (QC1-F-001) | non-resume JSONL prefix clobber | **Closed.** `existing = store.load()` always; last-write-wins merge. Leftover cursor is replaced on the first mid-run persist, then terminal `complete`/`limited`. Catalog is not replaced with a page-1 prefix. |
| R3 (QC3-F-003) | `max_pages` was absolute `pn` ceiling | **Closed.** `pages_this_call` counts HTTP pages this call; stop is `pages_this_call >= max_pages`. Help text “Stop after N pages” now matches. `pn += 1` is after the stop checks. |
| R4 (QC3-F-002) | resume `seen` session-local | **Resume path closed; recrawl regression open.** `known_bvids` seeds `seen`; stop on `ceil(total/ps)`, no new bvids, `len(seen) >= total`, or two empty pages. `bili_client` still does not import `meta_cursor`. CLI always passes `known_bvids` from the full JSONL, including **without** `--resume`. |

Cheap suggestions from consolidated (typed `on_page`, README resume-only exit-2, corrupt `load()` stderr): present in the fix; not re-opened.

## Findings
### 🔴 Critical
- None

### 🟡 Warning
- [F-005] R4 seed is applied on non-resume recrawl → pass `known_bvids` only when `--resume` (or skip the “no new bvids” stop when `start_page == 1` and the run is a full recrawl).
  - Source Type: read
  - Verification: `cli.py` always builds `known_bvids` from `existing` and passes `known_bvids or None` into `fetch_pages`; `bili_client.py` then `if arcs and not added: enumeration_complete; break` **before** `pn >= last_pn`.
  - Expected vs observed: expected a no-`--resume` run from pn=1 to walk `ceil(total/ps)` and last-write-wins refresh the catalog (README: start at page 1, merge JSONL, do not shrink) vs observed first overlapping page (`added` empty because JSONL already has those bvids) marks complete and stops after one HTTP page.
  - Confidence: High

### 🟢 Suggestion
- None remaining from the original F-004 (stderr on corrupt load is in `meta_cursor.load`).

### ⚪ Unconfirmed
- None

## Source Trace
- Finding ID: F-005
- Source Type: read
- Source Reference: `bilibili-asr-archive/src/bili_asr/cli.py` known_bvids loop + `fetch_pages(..., known_bvids=...)`; `bili_client.py` `added = new_bvids - seen` then early complete
- Confidence: High
- Note: R1–R3 and resume-side R4 verified on the same range; F-005 is a fix-wave regression of R4’s seed.

## Summary
| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟡 Warning | 1 |
| 🟢 Suggestion | 0 |
| ⚪ Unconfirmed | 0 |

**Verdict**: Request Changes

R1–R3 and the resume half of R4 hold on diff/read. Do not Approve while F-005 remains: a non-resume recrawl with a populated JSONL can complete after the first overlapping page.

Needs L4/QA verification (do not run here): `--resume` + `--limit-pages 2` from `next_page=5`; kill after a successful resume page; recrawl without `--resume` against a multi-page catalog.
