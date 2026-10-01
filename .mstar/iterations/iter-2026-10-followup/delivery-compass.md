---
iteration_id: iter-2026-10-followup
start_date: 2026-10-02
status: completed
end_date: 2026-10-02
iteration_base_branch: main
target_branch: main
plans: ["r14-asr-transcript-writeback", "qc-w1-compact-journal-guard", "qc-w2-search-index-stale", "qc-w3-upsert-cross-process", "qc-w4-pace-async", "005-search-index-skip-stamped", "006-attempt-ledger-inmemory", "008-pytest-markers", "010-dedupe-shared-helpers"]
---

# iter-2026-10-followup Delivery Compass

## Scope

Close the 2026-10-02 QC residuals, land the ASR→store transcript write-back (high residual R14),
and deliver the four deferred P3 audit plans.

本迭代锁定的 spec 点：

- **R14 ASR transcript write-back** — the ASR/archive path records a `transcripts` row through
  the repository's own writer so `v_missing_transcript` converges.
- **QC W1** — `ManifestStore.compact()` must not delete the journal when the snapshot is absent.
- **QC W2** — `search_index.is_stale()` must be journal-aware (not snapshot-mtime-only).
- **QC W3** — `ManifestStore.upsert()` cross-process invalidation (revalidate on journal change).
- **QC W4 + S1** — metadata `_pace` must yield to the event loop (asyncio), gated on row count.
- **P3 005** — search-index skip already-stamped parts before the filesystem probe.
- **P3 006** — attempt-ledger in-memory count (drop the per-append full-file rescan).
- **P3 008** — register pytest markers + centralize the live/scale opt-in gates.
- **P3 010** — dedupe the shared constant/helper clusters.

## Decisions

| # | Decision | Rationale | Source |
|---|----------|-----------|--------|
| D1 | Direction = QC residuals + R14 + P3 005/006/008/010 | Picks up exactly what the prior iteration + user flagged as next. | user instruction |
| D2 | Scale **XL** (9 business plans) | The scope spans 4 QC fixes + R14 + 4 P3 plans; exceeds L(≤4). | autonomous + user |
| D3 | Branch: base `main`, target `main`, integration `iteration/iter-2026-10-followup` | `main` is the recorded default integration/PR target. | autonomous branch resolve (AGENTS.md) |
| D4 | S1 folded into W4 (one pacing plan) | S1 (unconditional pacing) and W4 (event-loop sleep) are the same surface. | autonomous ranking |
| D5 | Findings cleanup `allow-residual` (default) | Non-blocking R# registered + disclosed. | mstar-harness-core default |

## Open Questions

None.

## Plans

| plan_id | Name | Status | Notes |
|---------|------|--------|-------|
| r14-asr-transcript-writeback | ASR→store transcript write-back (R14) | Done | high residual; owning plan 20260929-asr-local-transcript-storage |
| qc-w1-compact-journal-guard | compact() keep journal when snapshot absent | Done | QC W1 |
| qc-w2-search-index-stale | is_stale journal-aware | Done | QC W2 |
| qc-w3-upsert-cross-process | upsert cross-process invalidation | Done | QC W3 |
| qc-w4-pace-async | _pace asyncio + row-count gate | Done | QC W4 + S1 |
| 005-search-index-skip-stamped | search-index skip already-stamped | Done | P3 |
| 006-attempt-ledger-inmemory | attempt-ledger in-memory count | Done | P3 |
| 008-pytest-markers | pytest markers + opt-in gates | Done | P3 |
| 010-dedupe-shared-helpers | dedupe shared constant/helper clusters | Done | P3 |

Status values: `Todo` | `InProgress` | `InReview` | `Done` | `Blocked`

## Milestones

| Milestone | Target date | Status |
|-----------|-------------|--------|
| Spec freeze (compass locked) | 2026-10-02 | done |
| Dev complete (all plans merged) | 2026-10-02 | done |
| QC complete (tri-review) | 2026-10-02 | done |
| Iteration close | 2026-10-02 | done |

## Acceptance Criteria

- W1–W4 + S1 fixed; R14 write-back landed (two pinning tests pass); P3 005/006/008/010 merged.
- Each plan's scoped tests green; one PR to `main`.
- Findings cleanup allow-residual; no unresolved critical.

## Non-Goals

- The P3 security Needs-verification leads (httpx TLS; WBI seeding) — runtime probes.
- Registered residuals beyond W1–W4+S1.
- R13/R15 as separate plans (context for R14 only).

## Roadmap Position

- **Current iteration（iter-2026-10-followup）**：**delivered** — closes the 2026-10-02 QC residuals + R14 + the
  P3 audit tail (005/006/008/010).
- **Next iteration**：the audit's two security Needs-verification leads (runtime-confirmed
  fixes), R13/R15 store-route expressiveness, and any new residuals. 触发条件：this iteration
  merges + closes. owner: PM.
- **最终目标**：a clean correctness + performance baseline with the residual register trending
  down and the store↔chain bridge (R14) closed.

## Delivery Branch Policy

| Field | Value |
|-------|-------|
| `iteration_base_branch` | main |
| `spec_integration_branch` | iteration/iter-2026-10-followup |
| `target_branch` | main |

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| R14 touches store schema/gap views | Med | High | reuse the owning plan's design; run the two pinning tests + storage schema tests |
| 010 dedup spans many files | Med | Med | per-cluster commits; owning-suite tests after each |
| 008 edits shared conftest | Low | Med | run tmp_root + marker tests + smoke |

## Iteration package

| Path | Purpose |
|------|---------|
| `direction-lock.md` | lock-time record |
| `guides/` | process notes |
| `specs/` | iteration-scoped specs |

## Quality Gate Summary

> Filled at iteration-close.

## Compound Round Summary

- 结晶文档数：1（新增）— `knowledge/testing-patterns/parallel-lane-file-contamination.md`
- 新增 CONCEPTS.md 条目：0
- 触发 compound-refresh：否
- Iteration package 盘点：`direction-lock.md` + compass 为迭代史（Keep snapshot）；无 package spec 满足 `{SPECS_DIR}` 提升准入。

## Iteration Retrospective (minimal)

- 做得好的：9-plan 跨 lane 并行一次成功；R14（HIGH-risk store change）两个 pinning tests 从 base FAIL → integration PASS；QC tri 3/3  unanimous Approve、0 Critical。
- 可改进的：两个 lane 对（005+W2 / W1+W3）触碰同一文件导致跨-lane 污染——已结晶为知识；QC tri 抓到 005 的 commit 混入 W2 hunk，靠 merge 去重安全解决。
- 下迭代建议：R14 的 coordinator/run + subtitle-arm 收尾；010 cluster 5 的 stem-contract PM 决策；pre-existing test drift（18 failures）专项修复。
