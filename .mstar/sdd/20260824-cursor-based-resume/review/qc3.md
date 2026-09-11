---
report_kind: qc
reviewer: qc-specialist-3
reviewer_index: 3
plan_id: "20260824-cursor-based-resume"
verdict: "Request Changes"
generated_at: "2026-08-24"
---

# Code Review Report

## Reviewer Metadata
- Reviewer: @qc-specialist-3
- Runtime Agent ID: qc-specialist-3
- Runtime Model: grok-4.6
- Review Perspective: Performance and reliability (resume, failure isolation, cursor durability)
- Report Timestamp: 2026-08-24T00:00:00Z

## Scope
- plan_id: 20260824-cursor-based-resume
- Review range / Diff basis: `361530d0a4da34de93bb86c778d1efbe061500c4..ef21ddeb4f8bc65d01c7c0827b219873fc661e6a` / merge-base vs plan HEAD (plan 002 start `361530d` → HEAD `ef21dde`)
- Working branch (verified): `plan/20260824-cursor-based-resume`
- Review cwd (verified): `/root/workspace/bilibili-asr-archive/.worktrees/20260824-cursor-based-resume`
- Files reviewed: 5 (plus spec/plan/README)
- Commit range: `361530d0a4da34de93bb86c778d1efbe061500c4..ef21ddeb4f8bc65d01c7c0827b219873fc661e6a` (HEAD `ef21dde`)
- Analysis methods: git-diff, read, grep; deep-lens: Performance Lens, Reliability Lens, Enforcement-Path Lens, Ownership / Derived-State Lens
- Deep review: triggered (S1: 634 insertions / 5 files ≥ 200 lines; S3: new `meta_cursor` module; S6: `cli` + `bili_client` + `meta_cursor` + tests)
- Lenses applied: Performance Lens, Reliability Lens, Enforcement-Path Lens, Ownership / Derived-State Lens
- L3 only: no tests/builds/lint/HTTP. Assignment notes PM pytest 162 passed on `ef21dde` (not re-run).

## Findings
### 🔴 Critical
- None

### 🟡 Warning
- [F-001] `--resume` skips per-page JSONL and cursor advance → persist after every successful archive-list page, including resume; advance `next_page` to `last_completed_page + 1` while still `risk_interrupted` until the run terminals.
  - Source Type: deep-lens: Reliability Lens
  - Verification: diff/read `cli.py` `_after_successful_page` (`if args.resume or not client.pages_fetched: return`) vs spec advance rule and README “after each successful archive-list page merge”
  - Expected vs observed: expected ManifestStore merge + cursor write after each successful `pn` (spec `meta-cursor.md` Advance rule; README § fetch-meta) vs observed per-page persist only when **not** `--resume`; resume waits for terminal `_persist_cursor` / exception `_interrupt_cursor`. Crash after a successful resume page leaves `next_page` at the old failed `pn` (retry is idempotent, but contradicts durability and the README).
  - Confidence: High

- [F-002] Resume `seen` is session-local so `len(seen) >= total` never fires; completion depends on two empty pages and can loop if the API repeats the last page → seed `seen` from already-merged bvids, or treat `pn` vs `ceil(total/ps)` as the stop, and/or cap loops when `pn` no longer grows unique bvids.
  - Source Type: deep-lens: Performance Lens
  - Verification: diff/read `bili_client.py` `fetch_pages`: `seen: set[str] = set()` then `if total is not None and total > 0 and len(seen) >= total`; `start_page` does not preload prior pages
  - Expected vs observed: expected resume from `next_page>1` to detect full enumeration when cumulative archives reach `page.total` vs observed `seen` counting only this call. A 90-item archive resumed at pn=2 with 30/page never reaches `len(seen)>=90`. Stop then requires empty-streak≥2. If recArchives keeps returning the last non-empty page, `empty_streak` resets and the loop has no `max_pages` bound.
  - Confidence: High

- [F-003] `--limit-pages` is an absolute `pn` ceiling (`pn > max_pages` after increment), not “N pages this run” → either document as last allowed `pn`, or count pages fetched this call (`pages_this_run >= max_pages`).
  - Source Type: deep-lens: Enforcement-Path Lens
  - Verification: read `fetch_pages` stop `if max_pages is not None and pn > max_pages` vs argparse help “Stop after N pages (smoke runs)” and `test_fetch_pages_start_page` (`max_pages=2, start_page=2` fetches one page)
  - Expected vs observed: expected smoke/resume `--limit-pages N` to fetch N pages from `start_page` vs observed last requested `pn == max_pages`. `--resume` at `next_page=3` with `--limit-pages 2` fetches only pn=3 then stops (`4 > 2`). Help text and resume composition disagree.
  - Confidence: High

### 🟢 Suggestion
- [F-004] `MetaCursorStore.load` maps corrupt/invalid sidecar to `None` with no log → consider a stderr note so `--resume` failure is visible vs a silent start at pn=1 with JSONL kept.
  - Source Type: deep-lens: Ownership / Derived-State Lens
  - Verification: read `meta_cursor.py` `load` `except (ValueError, KeyError, TypeError): return None`
  - Expected vs observed: expected operator-visible failure of the authoritative cursor vs observed silent miss; `--resume` then ignores a damaged file.
  - Confidence: Medium

### ⚪ Unconfirmed
- None

## Source Trace
- Finding ID: F-001
- Source Type: deep-lens: Reliability Lens
- Source Reference: `bilibili-asr-archive/src/bili_asr/cli.py` `_after_successful_page`; spec Advance rule; README fetch-meta section
- Confidence: High
- Note: F-002 `bili_client.py` `fetch_pages` seen/total; F-003 same loop vs `--limit-pages` help; F-004 `meta_cursor.py` `load`

## Summary
| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟡 Warning | 3 |
| 🟢 Suggestion | 1 |
| ⚪ Unconfirmed | 0 |

**Verdict**: Request Changes

Atomic cursor replace, redaction, `running` not flushed, risk/API/Gone → exit 2 + `risk_interrupted`, and `--resume` mid match are sound. Blocking reliability gaps: resume does not persist per successful page; `seen>=total` is wrong after `start_page>1` (unbounded risk if last page repeats); `--limit-pages` is a pn ceiling, not a per-run count.

Needs L4/QA verification: resume + `--limit-pages`; resume until `page.total` without two trailing empty pages; kill after a successful resume page and re-`--resume`.
