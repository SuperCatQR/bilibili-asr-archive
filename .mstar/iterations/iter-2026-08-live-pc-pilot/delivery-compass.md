---
iteration_id: iter-2026-08-live-pc-pilot
start_date: 2026-08-26
status: completed
end_date: 2026-08-26
iteration_base_branch: main
target_branch: main
plans:
  - 20260826-audio-reclaim-on-archive
  - 20260826-bounded-live-pc-pilot
---

# iter-2026-08-live-pc-pilot Delivery Compass

## Scope

Locked direction (interactive grill-me, 2026-08-26):

- Prove PLAN.md **M2** on the **Windows WSL PC** (192.168.1.21 / DESKTOP-HHFROLO), not a full-corpus crawl.
- Two-branch live proof with the test-account SESSDATA via `BILI_SESSDATA` / `--sessdata` (cookie value only; never persist).
- **Audio peak &lt; 10 GiB** on that machine.
- After a row reaches `archived`, **delete the local m4a**; keep audio on failed / not-yet-archived rows.
- Staged N: **smoke N=3–5 first**, then **N=20**. Skip multi-hour livestreams in this iteration (at most none in smoke; N=20 still prefers short `duration_s`).

Spec points this iteration:

1. Post-archive audio reclaim (filesystem + manifest path fields; no JSONL schema migration).
2. Operator-facing budget: stop or skip before audio download would breach 10 GiB peak; duration filter so long lives are not selected for this pilot.
3. Documented WSL runbook + measured evidence (disk, both `source=subtitle` and `source=asr`).

## Plans

| plan_id | Name | Status | Notes |
|---------|------|--------|-------|
| 20260826-audio-reclaim-on-archive | Delete m4a after successful archive | Done | merged ad31964; 286 passed |
| 20260826-bounded-live-pc-pilot | 10 GiB budget + staged live PC pilot | Done | live WSL staged N=5/N=20 passed; latest code 4e00fb3; 299 passed; evidence: `live-pilot-evidence.md` |

Status values: `Todo` | `InProgress` | `InReview` | `Done` | `Blocked`

## Milestones

| Milestone | Target date | Status |
|-----------|-------------|--------|
| Direction lock + compass | 2026-08-26 | done (grill) |
| Review chain + PM lock | 2026-08-26 | done |
| Plan A reclaim | 2026-08-26 | done |
| Plan B budget + WSL smoke N=3–5 | 2026-08-27 | done; live subtitle + ASR + reclaim + budget-skip evidence in `live-pilot-evidence.md` |
| WSL N=20 under 10 GiB | 2026-08-27 | done; staged N=20 exit 0, subtitle=19/audio-asr=1, final audio=0 B |
| Iteration close | 2026-08-27 | ready for Phase 3 close |

## Acceptance Criteria

1. **Reclaim:** when a work_id becomes `archived` (subtitle or ASR path), the on-disk m4a for that stem is removed; failed/needs_audio/audio_ok rows keep audio; tests use a fake filesystem (no live HTTP).
2. **Budget:** before each audio download, `pilot` / `run` compute current `audio/` usage plus a conservative estimate (`duration_s` × 64 kbps ceiling) for the candidate item; if the result would exceed `--max-audio-gb` (default 10), that item is **skipped with a named reason** (`audio_budget`) and the batch continues; the run exits nonzero only when budget-skips left **no** eligible item for a required branch. Credentials never appear in skip reasons or output.
3. **Staged live proof (Windows WSL):** smoke `pilot --n 3` (or 5) shows both branches; then `--n 20` excluding long livestreams; `du` of `audio/` stays under 10 GiB; `status` / `runs` inspectable.
4. **Safety:** SESSDATA only in env/flag; absent from manifest, cursor, ledger, coordinator, search index. Full pytest suite green on fakes.

## Non-Goals

- Full visible-corpus scheduling (PLAN M0/M1/M3).
- Speakers / diarization / LLM cleanup / GUI / Meilisearch.
- Changing frozen risk taxonomy or JSONL row schema.
- Replacing `pilot` with `run`.
- Storing SESSDATA in git, MEMORY.md, or docs.

## Roadmap Position

- **Delivered iteration（iter-2026-08-live-pc-pilot）**：PC-bounded live M2 proof + audio reclaim + 10 GiB peak guard. Windows WSL staged N=5 and N=20 both completed with subtitle and ASR coverage; the bounded archive ended with `audio/` at 0 bytes. **Deferred long-live proof**: PLAN M2's "含超长直播回放" clause remains deferred to the full-corpus iteration (owner: project-manager; trigger: this iteration's PR merged to `main`; completion = at least one multi-hour livestream archived with reclaim keeping peak below budget). This iteration used a 45-minute threshold via `--max-duration-min` and proves the bounded-disk contract only.
- **Next iteration**：full-visible-corpus scheduling + deferred long-live proof; owner: project-manager; trigger: this iteration's PR merged to `main` and a renewed account session is available for a bounded live preflight.
- **最终目标**：PLAN M3 全量账本；本轮只证明可在 10 GiB 峰值下安全试点。

## Delivery Branch Policy

> Mirror of frontmatter; keep in sync with workflow snapshot `workflows/<id>/snapshot.json` branch anchors.

| Field | Value |
|-------|-------|
| `iteration_base_branch` | `main` |
| `spec_integration_branch` | `iteration/iter-2026-08-live-pc-pilot` |
| `target_branch` | `main` |

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Live 412 / empty subs without SESSDATA | High | High | Test alt cookie on WSL only; Path A fallback already specified |
| Long livestream blows 10 GiB | Medium | High | Prefer short `duration_s`; skip lives this round; delete m4a on archive |
| WSL disk vs Windows disk confusion | Medium | Medium | Archive root on WSL filesystem; measure `du` there |
| Cookie pasted into logs | Low | High | Existing redaction tests; never echo |

## Iteration package

| Path | Purpose |
|------|---------|
| `guides/` | Phase 1 review-chain assignments |
| `specs/` | Iteration deltas (reclaim + budget); warehouse MVP stays `.mstar/specs/asr-archive-cli.md` |
| `README.md` | Index |

## Grill-me lock log

- Direction: A — Windows PC bounded live run (not full corpus, not CI-first).
- Audio: A — delete m4a after successful `archived`.
- Host: A — Windows WSL compute box.
- N: C — smoke 3–5 then 20.
- Branch: A — `main` → `iteration/iter-2026-08-live-pc-pilot` → PR `main`.

## Review chain record (§1.6)

- 2026-08-26: subagent dispatch attempted 3× for the review chain (2 background + 1 foreground); all failed with no output (DSH subagent channel outage; shell verified healthy). **User explicitly waived subagent dispatch ("PM-only review")** per `mstar-iteration` §1.6 exception.
- PM executed the three seats' edits directly: product (roadmap/deferred long-live, budget/skip semantics), architect (locked interfaces for reclaim helper + budget gate; iteration spec deltas `specs/reclaim-budget-delta.md`), writing (runbook rewrite, corpus hygiene scan clean: no knowledge-tree additions, no cookie literals, frozen spec untouched).
- compass `status: locked` 2026-08-26.

## Quality Gate Summary

- Source verification: full fake-HTTP/local filesystem suite passed `299 passed in 4.82s` at `4e00fb3`.
- Live QA: Windows WSL staged smoke completed with `pilot batch branches: subtitle=3, audio-asr=2`; staged N=20 completed with `subtitle=19, audio-asr=1`, exit 0.
- Bounded disk: named `audio_budget` pre-download skip was observed; final staged `audio/` usage was 0 bytes after successful archives, with an observed active-ASR sample of 5,768,297 bytes.
- Safety: staged archive credential scan was clean. No residual findings are open.

## Compound Round Summary

- Updated existing knowledge SSOT `.mstar/knowledge/architecture-patterns/bilibili-asr-archive-cli.md` rather than creating a duplicate. The update records the transient-audio budget, duration filter, post-archive reclaim, `audio_ok` reuse, and batch-versus-coverage reporting policy. `mstar_compound_validate` passed.
- Package inventory: `specs/reclaim-budget-delta.md` and `guides/wsl-pc-pilot.md` were retained as iteration records; their durable operating rules were incorporated into the existing architecture knowledge document. The two review-seat assignment files are transient review choreography and were skipped. `live-pilot-evidence.md` is retained as measured QA evidence, not promoted as general guidance. `README.md` remains the package index.
- No new knowledge document or CONCEPTS entry was needed; the knowledge index already points to the updated existing document.

## Iteration Retrospective (minimal)

- A short-video pilot can initially contain only subtitle hits. Keep the two-branch contract strict, discover an eligible `needs_audio` row within the same duration policy, then resume rather than widening the long-video threshold.
- A locally available `audio_ok` artifact is a retry input, not a new download. Reusing it avoids both budget double-counting and repeated HTTP work.
- The Windows WSL environment required a matched CPU `torch` / `torchaudio` pair before FunASR could import `AutoModel`; this belongs in environment setup, not in the base CLI dependency group.
