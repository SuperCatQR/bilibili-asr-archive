---
report_kind: qc
reviewer: qc-specialist-2
reviewer_index: 2
plan_id: "20260824-multipart-page-aware-pipeline"
verdict: "Approve"
generated_at: "2026-08-24"
---

# Code Review Report

## Reviewer Metadata
- Reviewer: @qc-specialist-2
- Runtime Agent ID: qc-specialist-2
- Runtime Model: grok-4.6
- Review Perspective: Security and correctness risk
- Report Timestamp: 2026-08-24T21:50:00Z

## Scope
- plan_id: `20260824-multipart-page-aware-pipeline`
- Review range / Diff basis: `a79b84b6f9586410941503a5e04989eca020efe6..fa20305bc85db07c7b2667b1d8bf6512705c35c8` (merge-base vs plan HEAD; Task 1 start `a79b84b` → HEAD `fa20305`)
- Working branch (verified): `plan/20260824-multipart-page-aware-pipeline`
- Review cwd (verified): `/root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline`
- Files reviewed: 15 (stat of assigned range)
- Commit range: identical to Review range (`a79b84b6..fa20305b`)
- Analysis methods: git-diff --stat, read, grep, deep-lens: Security Lens, Correctness Lens, Bounds Lens, Real-Entry-Path Lens, Input Validation Lens
- Deep review: triggered (S1: 1188 insertions / 15 files, S6: page_identity + manifest + cli + bili_client + subtitles + audio + archive)

HEAD `fa20305bc85db07c7b2667b1d8bf6512705c35c8` matches Assignment tip. No tests/builds/lint/HTTP executed. Assignment notes 141 pytest passed on this SHA (L1; not re-run).

## Findings
### 🔴 Critical
- None.

### 🟡 Warning
- [F-001] `harvest-subs --bvid` on an unresolved bare row does not STOP (exit 1). `_todo_for_bvid` returns `[]` when `get_compatible` is excluded; `_cmd_harvest_subs` then treats empty todo as a successful no-op (rc 0, no stderr). `download-audio --bvid` and `asr --bvid` both print `unresolved; not assigned to a page` and return 1. Plan/commit contract: STOP unresolved `--bvid`. Batch harvest without `--bvid` correctly skips.
  - Source Type: deep-lens: Correctness Lens / Real-Entry-Path Lens
  - Verification: diff/read/grep — [cli.py](/root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/src/bili_asr/cli.py) `_todo_for_bvid` ~145-157, `_cmd_harvest_subs` 341-353 vs `_cmd_download_audio` 418-430 and `_cmd_asr` 565-578; [test_page_pipeline.py](/root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/tests/test_page_pipeline.py) `test_cli_download_audio_bvid_unresolved_stops` only.
  - Expected vs observed: expected operator `--bvid` on unresolved exits 1 without assignment vs harvest-subs exits 0 with a quiet 0/0 summary.
  - Confidence: High
  - Fix: After resolving `--bvid` todo, if the only match is excluded/unresolved, print the same STOP line and return 1 (do not synthesize a pending row; do not call `harvest_subtitle`).

- [F-002] Legacy migration STOP does not treat existing `{bvid}.p0` artifacts as collisions. `_foreign_page_stems` only records `page_index != 0`. Plan STOP: "Migration would overwrite an existing `{bvid}.pN` artifact". Destination of unambiguous migrate is always `format_work_id(bvid, 0)` / `{bvid}.p0`. Prior page-aware files for p0 (ledger lost, files remain) allow migrate + later harvest/audio to overwrite p0 outputs.
  - Source Type: deep-lens: Correctness Lens / Bounds Lens
  - Verification: read [manifest.py](/root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/src/bili_asr/manifest.py) `_foreign_page_stems` 234-255 (`if page_index != 0`), `migrate_legacy_rows` 188-211.
  - Expected vs observed: expected any `{bvid}.pN` including N=0 blocks migrate vs only N!=0 freezes the row.
  - Confidence: High
  - Fix: Treat any matching `{bvid}.pN` stem (including p0) as collision, or explicitly compare destination `artifact_stem` paths and raise `ManifestMigrationCollision` / freeze unresolved.

### 🟢 Suggestion
- [F-003] `harvest_subtitle(str)` after `migrate_legacy_rows` still falls through to `resolve_page_identity` when the row is unresolved (no `work_id`). That can mint a `PageIdentity` and write `{bvid}.p0` artifacts; `_ledger_entry` then `get_compatible` copies `unresolved=True` onto a new `work_id` key without deleting the bare row. CLI batch paths skip excluded rows; the library seam does not.
  - Source Type: deep-lens: Enforcement-Path / Correctness Lens
  - Verification: read [subtitles.py](/root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/src/bili_asr/subtitles.py) 94-114, 72-79.
  - Expected vs observed: expected unresolved never assigned a page vs library path can still resolve pagelist length 1.
  - Confidence: Medium
  - Fix: If `get_compatible` returns unresolved/excluded, raise/return without `resolve_page_identity`.

- [F-004] `list_pages` missing-cid STOP is `ValueError`; harvest/download CLI `except Exception` maps it to "unexpected error" and continues the batch. Operator does not see the STOP reason.
  - Source Type: deep-lens: Correctness Lens
  - Verification: [bili_client.py](/root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/src/bili_asr/bili_client.py) 470-471; [cli.py](/root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/src/bili_asr/cli.py) 389-392, 492-495.
  - Expected vs observed: expected visible STOP vs generic unexpected error.
  - Confidence: Medium

### ⚪ Unconfirmed
- None. Review-package path and worktree HEAD were readable; assigned range reproduced via `git log` / `git diff --stat`.

## Source Trace
- Finding ID: F-001
- Source Type: deep-lens: Correctness Lens
- Source Reference: `bili_asr/cli.py` `_cmd_harvest_subs` vs `_cmd_download_audio` unresolved `--bvid`
- Confidence: High
- Note: F-002..F-004 traced above; every finding has Verification + Expected vs observed.

## Summary
| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟡 Warning | 2 |
| 🟢 Suggestion | 2 |
| ⚪ Unconfirmed | 0 |

**Verdict**: Approve

Cid threading (`probe_subs` / `fetch_playurl_audio` refuse `cid is None` on multi-part; harvest/audio tests assert per-page cids), `artifact_stem` colon ban, WBI key cache, SESSDATA-not-on-CDN, and batch skip of unresolved rows look correct from the diff. Needs L4/QA verification: pytest suite already cited by PM on `361530d` (147 passed) — do not re-run here.

## Revalidation
- Review range / Diff basis: `fa20305bc85db07c7b2667b1d8bf6512705c35c8..361530d0a4da34de93bb86c778d1efbe061500c4` (previous QC HEAD vs fix HEAD)
- Working branch (verified): `plan/20260824-multipart-page-aware-pipeline`
- Review cwd (verified): `/root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline`
- HEAD: `361530d0a4da34de93bb86c778d1efbe061500c4`
- Methods: git-diff --stat of assigned range, read/grep of cli/manifest/subtitles, qc-fix.diff + qc-fix-report. No tests/builds. PM pytest 147 passed on this SHA (L1; not re-run).

| ID | Original | Disposition |
|----|----------|-------------|
| F-001 (Warning) | `harvest-subs --bvid` on unresolved returned rc 0 | **Fixed.** `_cmd_harvest_subs` empty todo prints `{bvid}: unresolved; not assigned to a page` and returns 1. `_todo_for_bvid` no longer synthesizes a pending row. Test `test_cli_harvest_subs_bvid_unresolved_stops` in the fix diff. |
| F-002 (Warning) | `_foreign_page_stems` skipped p0 | **Fixed.** Any `{bvid}.pN` matching `_STEM_PAGE_RE` is a collision, including p0. `test_migrate_collision_on_existing_p0_artifact`. |
| F-003 (Suggestion) | library `harvest_subtitle(str)` resolved unresolved rows | **Fixed.** Unresolved/excluded `get_compatible`/`get` raises `ValueError` before `resolve_page_identity`. `test_harvest_subtitle_str_skips_unresolved`. |
| F-004 (Suggestion) | missing-cid `ValueError` mapped to unexpected error | **Fixed.** harvest/download catch `ValueError` and print the message when it contains `missing cid` or `unresolved`. |

No remaining Critical/Warning on these items. No new correctness/security findings in the targeted range that reopen the gate.

**Revalidation verdict**: Approve

## Completion Report
- Role: qc-specialist-2
- Working branch used: plan/20260824-multipart-page-aware-pipeline
- Review cwd: `/root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline`
- Report: `.mstar/sdd/20260824-multipart-page-aware-pipeline/review/qc2.md`
- Verdict: Approve (F-001..F-004 closed)
- Worktree: not mutated; no PR; no tests run
