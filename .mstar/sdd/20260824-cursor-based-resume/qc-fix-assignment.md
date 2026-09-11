Execute as: fullstack-dev
Delegation: forbidden
Task category: bugfix
Working branch: plan/20260824-cursor-based-resume
---

# Assignment — Plan 002 QC Warning fix

Execution mode: sdd
SDD implementer session: fresh
Model tier: standard
Findings cleanup: zero-residual

Worktree path: `/root/workspace/bilibili-asr-archive/.worktrees/20260824-cursor-based-resume`
Plan Path: `/root/workspace/bilibili-asr-archive/.mstar/plans/20260824-cursor-based-resume.md`
SDD dir: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260824-cursor-based-resume`
execution_lease holder: `dsh:goal-9443ff6c-a480-4433-915a-cf116c1a986b`
HEAD: `ef21ddeb4f8bc65d01c7c0827b219873fc661e6a`

<SUBAGENT-STOP> Skip PM orchestration. Leaf implementer. Fix the four consolidated Warnings.</SUBAGENT-STOP>

Consolidated: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260824-cursor-based-resume/review/qc-consolidated.md`
Spec: `/root/workspace/bilibili-asr-archive/.mstar/iterations/iter-2026-08-archive-foundations/specs/meta-cursor.md`

## Must fix

1. Per-page JSONL + cursor persist on **both** resume and non-resume after each successful archive-list page. `--resume` must not skip `_after_successful_page`. While crawling, keep `risk_interrupted` and set `next_page` to last merged `pn+1`. Terminal `complete`/`limited` still only at run end. Never persist `running`.

2. Without `--resume`, do not overwrite a previously complete JSONL with a page-1 prefix. Replace leftover **cursor**; merge prior JSONL (last-write-wins).

3. `--limit-pages N` counts pages fetched **this call**, not `pn > N`.

4. Resume completion must not rely only on two empty pages. Stop when `pn` exceeds `ceil(total/ps)` and/or a non-empty page adds no new bvids. Seed `seen` only if you pass already-known bvids into `fetch_pages` — `BiliClient` still must not import `meta_cursor`.

5. **F-005 (QC3 revalidation)**: `known_bvids` is built from JSONL **always**, including without `--resume`. A full recrawl can stop after the first overlapping page (no-new-bvid → `enumeration_complete`). Pass `known_bvids` **only when `--resume`** (or skip the no-new-bvid stop when `start_page == 1` full recrawl). Add a test: recrawl from pn=1 with pre-existing JSONL must walk to `ceil(total/ps)` and refresh, not stop after page 1.

Tests for each Warning. `PYTHONPATH=src` + `/root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest -q`

Cheap suggestions OK: type `on_page`; README that only exit-2 `risk_interrupted` is auto-resumable; stderr on corrupt cursor load.

Report: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260824-cursor-based-resume/qc-fix-report.md`

Commit. No PR. No egg-info/uv.lock.
