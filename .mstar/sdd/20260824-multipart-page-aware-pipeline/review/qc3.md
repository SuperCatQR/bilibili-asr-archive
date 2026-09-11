---
report_kind: qc
reviewer: qc-specialist-3
reviewer_index: 3
plan_id: "20260824-multipart-page-aware-pipeline"
verdict: "Approve"
generated_at: "2026-08-24"
---

# Code Review Report

## Reviewer Metadata
- Reviewer: @qc-specialist-3
- Runtime Agent ID: qc-specialist-3
- Runtime Model: grok-4.6
- Review Perspective: Performance and reliability (resume, failure isolation, resource/HTTP budgets)
- Report Timestamp: 2026-08-24T21:50:00Z

## Scope
- plan_id: `20260824-multipart-page-aware-pipeline`
- Review range / Diff basis: `a79b84b6f9586410941503a5e04989eca020efe6..fa20305bc85db07c7b2667b1d8bf6512705c35c8` / merge-base vs plan HEAD (Task 1 start `a79b84b` → HEAD `fa20305`)
- Working branch (verified): `plan/20260824-multipart-page-aware-pipeline`
- Review cwd (verified): `/root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline`
- HEAD: `fa20305bc85db07c7b2667b1d8bf6512705c35c8` (matches tip)
- Files reviewed: 15 (stat 1188 insertions / 141 deletions)
- Commit range: identical to Review range
- Analysis methods: git-diff, read, grep; deep-lens: Performance Lens, Reliability Lens, Enforcement-Path Lens, Ownership / Derived-State Lens, Testing Lens
- Deep review: triggered (S1: 1188 lines / 15 files, S3: first page-aware pipeline, S6: cli + client + manifest + archive + audio + subtitles)
- Lenses applied: Performance, Reliability, Enforcement-Path, Ownership / Derived-State, Testing (S3)
- PM pytest note (not re-run): 141 passed on `fa20305`

## Findings
### 🔴 Critical
- None.

### 🟡 Warning
- [F-001] `fetch-meta` page expansion issues extra `list_pages` HTTP **inside** the honest-resume persist path, with no isolation. Series enumeration can succeed (or partially succeed) and then `_merge_page_rows` can raise `RiskBudgetExhausted` / `APIResponseError` / `GoneResponse` / `ValueError` (missing cid). On the `except RiskBudgetExhausted` / `APIResponseError` / `GoneResponse` handlers this is a nested raise from `_persist_partial` and **skips `store.save`**, so `pages_fetched` is discarded. On the success path after `fetch_pages` returns, `_merge_page_rows` and `migrate_legacy_rows` sit **outside** the try and can abort after a successful series fetch without the redacted exit-1 path. -> Wrap `_merge_page_rows` so per-bvid `list_pages` failures are recorded and remaining bvids still persist; never call unbounded pagelist from inside the budget-exhausted handler (persist series-level rows first, expand pages in a later pass).
  - Source Type: deep-lens: Reliability Lens
  - Verification: diff/read `cli.py` `_merge_page_rows` (`client.list_pages(bvid)` per record), `_persist_partial` (merge then save), `_cmd_fetch_meta` except handlers calling `_persist_partial`, success path `merge_pages` → `_merge_page_rows` → `save` → `migrate_legacy_rows` unguarded; `bili_client.list_pages` uses `_request_with_cookies` (same risk budget as series fetch).
  - Expected vs observed: expected H2 persist of already-fetched series pages even when a later pagelist STOP fires vs observed extra HTTP on the persist path that can throw and drop the partial ledger.
  - Confidence: High

- [F-002] Page expansion is an unbounded, unsleeped pagelist burst. `fetch_pages` spaces series pages (`_sleeper(0.8+jitter)`); `_merge_page_rows` then hits pagelist once **per bvid** with no delay, and `migrate_legacy_rows` may call `list_pages` again for leftover bare keys. A 30-item series page can become 30 back-to-back pagelist calls immediately after a risk-control event — the opposite of the WBI-nav cache fix (`_wbi_key_pair`) that was added to avoid exhausting nav. -> Reuse identities already fetched, rate-limit pagelist like series pages, or expand lazily at harvest time (cid already required on probe/playurl).
  - Source Type: deep-lens: Performance Lens
  - Verification: diff/read `cli.py` `_merge_page_rows` loop vs `bili_client.fetch_pages` inter-page sleep; harvest/download loops keep `time.sleep(3.0)` between items; merge does not.
  - Expected vs observed: expected page-aware expansion to respect the existing risk/backoff envelope vs observed N extra pagelist calls with no spacing on the hottest CLI path.
  - Confidence: High

### 🟢 Suggestion
- [F-003] `--bvid` on harvest-subs / download-audio returns `None` when more than one processable row shares the bvid (`_todo_for_bvid`), and there is **no `--page` / work_id selector**. `asr --bvid` instead archives **all** matching pages. After a correct two-page `fetch-meta`, the documented restrict flag is a hard fail even though independent `work_id` rows exist. Full harvest without `--bvid` still works. -> Treat `--bvid` as “all pages of this bvid” (matching asr) or accept a `bvid:pN` work_id.
  - Source Type: deep-lens: Enforcement-Path Lens
  - Verification: diff/read `cli.py` `_todo_for_bvid` (`len(matching) > 1` → `None`) vs `_cmd_asr` list-comprehension over all non-excluded rows for that bvid; README documents STOP only for unresolved `--bvid`.
  - Expected vs observed: expected an operator path to resume one bvid’s pages vs observed harvest/download STOP with “needs an explicit page” and no flag to name the page.
  - Confidence: High

- [F-004] `probe_subs` does not rotate WBI on `-403`; only `fetch_playurl_audio` calls `_wbi_keys(refresh=True)`. Cached keys make two-page harvest cheap (good) but a stale pair fails the whole subtitle probe path without the playurl recovery. -> Mirror the one-shot refresh on player/wbi/v2 `-403`.
  - Source Type: deep-lens: Reliability Lens
  - Verification: diff/read `bili_client.py` `_wbi_keys` cache; `probe_subs` single `_wbi_keys()`; `fetch_playurl_audio` `-403` refresh block.
  - Expected vs observed: expected signed player calls to recover from rotated WBI like playurl vs observed harvest-only path with no refresh.
  - Confidence: Medium

- [F-005] Missing pagelist cid raises `ValueError`, not `AmbiguousPageError`. Harvest/download map `AmbiguousPageError` to an actionable message and `Exception` to `"unexpected error"` with continue — STOP is isolated but opaque. `fetch-meta` does not catch it at all (see F-001).
  - Source Type: deep-lens: Ownership / Derived-State Lens
  - Verification: `bili_client.list_pages` `raise ValueError(... missing cid)`; `test_list_pages_missing_cid_is_stop`; harvest except chain in `cli.py`.
  - Expected vs observed: expected a typed STOP on the enforcement path vs observed generic ValueError.
  - Confidence: High

- [F-006] `_foreign_page_stems` `os.walk`s the entire archive root (skipping only `manifest/`) on every bare-row migration. Fine for small personal archives; unbounded over `audio/` + transcripts as the corpus grows.
  - Source Type: deep-lens: Performance Lens
  - Verification: read `manifest.py` `_foreign_page_stems`.
  - Expected vs observed: expected collision checks on known artifact dirs vs observed full-tree walk.
  - Confidence: Medium

### ⚪ Unconfirmed
- None. Review range, worktree HEAD, and `plan-001.diff` were readable. Runtime suite not executed (L3). Needs L4/QA verification: implementer/PM claim `141 passed` on `fa20305`; especially fetch-meta partial persist under injected pagelist `RiskBudgetExhausted`.

## Source Trace
- Finding ID: F-001
- Source Type: deep-lens: Reliability Lens
- Source Reference: `bilibili-asr-archive/src/bili_asr/cli.py` `_merge_page_rows` / `_persist_partial` / `_cmd_fetch_meta`
- Confidence: High
- Note: F-002–F-006 traces are in each Findings bullet.

## Summary
| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟡 Warning | 2 |
| 🟢 Suggestion | 4 |
| ⚪ Unconfirmed | 0 |

**Verdict**: Approve

Page identity, cid threading, artifact stems, unresolved exclusion, and per-`work_id` harvest/audio independence look sound on the happy path (WBI cache is the right nav fix). Blocking reliability issue is that page expansion re-enters the HTTP risk budget on the persist/resume path without isolation or spacing.

## Revalidation

- Review range / Diff basis: `fa20305bc85db07c7b2667b1d8bf6512705c35c8..361530d0a4da34de93bb86c778d1efbe061500c4` / previous QC HEAD vs fix HEAD
- Working branch (verified): `plan/20260824-multipart-page-aware-pipeline`
- Review cwd (verified): `/root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline`
- HEAD: `361530d0a4da34de93bb86c778d1efbe061500c4`
- Analysis methods: git-diff (`qc-fix.diff`), read, grep; no tests/builds
- PM pytest note (not re-run): 147 passed on `361530d`
- Deep review: skipped (targeted re-review)

| ID | Original | Disposition |
|----|----------|-------------|
| F-001 Warning | `_merge_page_rows` HTTP on persist; uncaught pagelist abort skips `store.save` | **Closed.** Per-bvid `try/except` in `_merge_page_rows`; `_persist_partial` always `save`s; `test_cli_fetch_meta_pagelist_failure_keeps_other_bvid` (read, not run). Pagelist still runs on the risk-exhausted persist path, but isolated so remaining series rows land. |
| F-002 Warning | Unsleeped pagelist burst per bvid | **Closed.** One `_cached_page_lister` per fetch-meta; sleeper `0.8+jitter` between distinct bvids; migrate reuses the same cache. |
| F-003 Suggestion | `--bvid` multi-page STOP | **Out of scope / accepted.** `bvid:pN` via `parse_work_id` in `_todo_for_bvid`; harvest/download/asr share it. |
| F-004 Suggestion | `probe_subs` no WBI `-403` refresh | **Closed.** Mirrors playurl: refresh keys and retry once. |
| F-005 Suggestion | Missing-cid `ValueError` as unexpected | **Closed.** Harvest/download print STOP when message contains `missing cid` / `unresolved`. |
| F-006 Suggestion | `_foreign_page_stems` full-tree walk | **Closed.** `os.listdir` on `_ARTIFACT_REL_DIRS` only. |

Unresolved Critical: 0. Unresolved Warning: 0.

**Verdict**: Approve
