---
report_kind: qc
reviewer: qc-specialist
reviewer_index: 1
plan_id: "20260824-multipart-page-aware-pipeline"
verdict: "Approve"
generated_at: "2026-08-24"
---

# Code Review Report

## Reviewer Metadata
- Reviewer: @qc-specialist
- Runtime Agent ID: qc-specialist
- Runtime Model: grok-4.6
- Review Perspective: Architecture coherence and maintainability risk
- Report Timestamp: 2026-08-24T13:48:56Z

## Scope
- plan_id: `20260824-multipart-page-aware-pipeline`
- Review range / Diff basis: `a79b84b6f9586410941503a5e04989eca020efe6..fa20305bc85db07c7b2667b1d8bf6512705c35c8` / merge-base vs plan HEAD (Task 1 start `a79b84b` → HEAD `fa20305`)
- Working branch (verified): `plan/20260824-multipart-page-aware-pipeline`
- Review cwd (verified): `/root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline`
- HEAD (verified): `fa20305bc85db07c7b2667b1d8bf6512705c35c8`
- Files reviewed: 15 (`git diff --stat` on Review range; 1188 insertions / 141 deletions)
- Commit range: identical to Review range
- Analysis methods: git-diff, read, grep, deep-lens: Modularity Lens, Contract Lens
- Deep review: triggered (S1: 1188 lines / 15 files, S6: page_identity + manifest + bili_client + cli + harvest/audio/archive)
- Lenses applied: Modularity Lens, Contract Lens
- PM pytest evidence (not re-run): 141 passed on `fa20305`

## Findings
### 🔴 Critical
- none

### 🟡 Warning
- [F-001] `ManifestStore.upsert` still accepts new automatic rows without `work_id`; CLI error/direct paths recreate the bare-bvid class the migration was meant to retire. -> Require `work_id` on new processable rows (legacy load/migrate remains the only bare-key path); `_record_api_error` / `asr --bvid` unknown-entry must `get`/`upsert` by `work_id` (or `get_compatible` then STOP), never insert `{bvid, status}` keyed only by bvid.
  - Source Type: deep-lens: Contract Lens
  - Verification: diff/read/grep anchor (`bilibili-asr-archive/src/bili_asr/manifest.py` `_entry_key` / `upsert` allows missing `work_id`; `cli.py` `_record_api_error` `store.get(bvid)` then `entry = {"bvid": bvid, "status": starting_status}`; `_cmd_probe_subs` passes `starting_status="meta_ok"`; `_cmd_asr` synthesizes `{"bvid": args.bvid, "status": "audio_ok"}`)
  - Expected vs observed: architecture ManifestStore contract (`upsert` keys by `work_id`; rejects missing `work_id` for new automatic rows) vs observed upsert + probe-subs API-error path that can write a second ledger identity beside `BVxx:pN` rows
  - Confidence: High

- [F-002] Bare `--bvid` CLI targeting is not one contract. harvest-subs / download-audio STOP when more than one processable page exists (`_todo_for_bvid` returns `None`); `asr --bvid` archives every matching page. Architecture: all bvid-accepting commands resolve via `list_pages` + `get_compatible` and STOP on multi-part without an explicit page. There is still no `--work-id` / `--page` flag, so operators cannot target one part except by omitting `--bvid` (full batch). -> Pick one operator contract (STOP vs process-all-pages) and apply it to harvest, download-audio, and asr; if STOP, add an explicit page selector or document that multipart targeting is batch-only.
  - Source Type: deep-lens: Contract Lens
  - Verification: diff/read/grep anchor (`cli.py` `_todo_for_bvid` `len(matching) > 1 -> None`; `_cmd_harvest_subs` / `_cmd_download_audio` vs `_cmd_asr` `todo = [e for e in entries.values() if e.get("bvid") == args.bvid ...]`; architecture § API Contracts last paragraph)
  - Expected vs observed: uniform STOP (or uniform per-page enumeration) vs mixed STOP / process-all
  - Confidence: High

### 🟢 Suggestion
- [F-003] `list_pages` does not keep pagelist per-part duration; `_merge_page_rows` copies recArchives video-level `duration_s` onto every page. Pilot/status totals then over-count multipart videos. -> Stamp `part.get("duration")` on `PageIdentity` or the ledger row when present.
  - Source Type: deep-lens: Modularity Lens
  - Verification: diff/read/grep anchor (`bili_client.py` `list_pages` builds identity from cid/part only; `cli.py` `_merge_page_rows` `entry.update(meta)` then `apply_identity`)
  - Expected vs observed: page row duration matches the part vs video duration duplicated per page
  - Confidence: Medium

- [F-004] `download_audio` docstring claims skip-existing happens before any pagelist/playurl call, but `resolve_page_identity(client, target)` runs first (pagelist when `target` is a bare bvid). -> Reorder skip-before-network for stem-known `PageIdentity`, or correct the comment.
  - Source Type: git-diff
  - Verification: diff/read/grep anchor (`audio.py` `download_audio` identity resolve then `_existing_audio`)
  - Expected vs observed: no HTTP on existing file vs pagelist on str targets before skip
  - Confidence: High

### ⚪ Unconfirmed
- none

## Source Trace
- Finding ID: F-001
- Source Type: deep-lens: Contract Lens
- Source Reference: `manifest.py` upsert/`_entry_key`; `cli.py` `_record_api_error`, `_cmd_probe_subs`, `_cmd_asr`
- Confidence: High
- Note: every finding carries Verification + Expected vs observed above

- Finding ID: F-002
- Source Type: deep-lens: Contract Lens
- Source Reference: `cli.py` `_todo_for_bvid` vs `_cmd_asr`; architecture CLI paragraph
- Confidence: High

- Finding ID: F-003
- Source Type: deep-lens: Modularity Lens
- Source Reference: `bili_client.list_pages`; `cli._merge_page_rows`
- Confidence: Medium

- Finding ID: F-004
- Source Type: git-diff
- Source Reference: `audio.py` `download_audio`
- Confidence: High

## Summary
| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟡 Warning | 2 |
| 🟢 Suggestion | 2 |
| ⚪ Unconfirmed | 0 |

**Verdict**: Request Changes (superseded by Revalidation)

Core page identity (`PageIdentity`, `artifact_stem`, `list_pages`, cid threading, unresolved skip, independent p0/p1 status) matches the locked architecture. HTTP stays in `bili_client`. Blocking for this seat is the incomplete work_id write-path (F-001) and inconsistent `--bvid` operator contract (F-002).

Needs L4/QA verification: full pytest already cited by PM (141 passed); do not re-run here. Runtime proof of probe-subs error writing a sibling bare row is a diff-logic claim for implementer tests, not this seat.

## Revalidation

- Review range / Diff basis: `fa20305bc85db07c7b2667b1d8bf6512705c35c8..361530d0a4da34de93bb86c778d1efbe061500c4` / previous QC HEAD vs fix HEAD
- Working branch (verified): `plan/20260824-multipart-page-aware-pipeline`
- Review cwd (verified): `/root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline`
- HEAD (verified): `361530d0a4da34de93bb86c778d1efbe061500c4`
- Analysis methods: git-log, git-diff (`qc-fix.diff`), read, grep
- Deep review: skipped (targeted re-review)
- PM pytest evidence (not re-run): 147 passed on `361530d`

| ID | Original | Disposition |
|----|----------|-------------|
| F-001 Warning | `upsert` + CLI error/direct paths could invent bare-bvid processable rows | **Resolved.** `upsert` raises `ValueError("new automatic row requires work_id")` unless freeze (unresolved/excluded) or legacy bare-key update. `_record_api_error` only patches `get` / `get_compatible`; unknown `--bvid` no longer inserts `{bvid, status}`. |
| F-002 Warning | harvest/download STOP on multi-part; `asr --bvid` processed all pages | **Resolved.** harvest-subs, download-audio, and asr all call `_todo_for_bvid`: `None` on multi-part, `[]` on unknown/unresolved, single page via `parse_work_id` (`bvid:pN`). Help text matches. |
| F-004 Suggestion | `download_audio` skip after pagelist for stem-known identity | **Resolved (in-scope).** `PageIdentity` targets skip via `_existing_audio` before any HTTP; str targets still resolve first. |
| F-003 Suggestion | duration on `PageIdentity` / page rows | **Out of scope** (locked struct); not re-opened. |

Unresolved Critical/Warning after revalidation: none.

**Verdict**: Approve

## Completion Report
- Role: qc-specialist
- Working branch used: plan/20260824-multipart-page-aware-pipeline
- Review cwd: `/root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline`
- Report: `.mstar/sdd/20260824-multipart-page-aware-pipeline/review/qc1.md`
- Verdict: Approve (targeted revalidation; F-001/F-002/F-004 closed; F-003 deferred)
- Worktree: not mutated; no PR
