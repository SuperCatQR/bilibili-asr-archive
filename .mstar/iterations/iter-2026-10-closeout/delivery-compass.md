---
iteration_id: iter-2026-10-closeout
start_date: 2026-10-02
status: completed
end_date: 2026-10-02
iteration_base_branch: main
target_branch: main
plans: ["r14-routes-writeback", "stem-contract-consolidation", "test-drift-repair"]
---

# iter-2026-10-closeout Delivery Compass

## Scope

Finish the R14 ASR→store transcript write-back on the remaining routes (coordinator/run-batch +
subtitle-arm), decide + land the 010 cluster-5 canonical-stem contract, and fix the pre-existing
test drift (18 failures).

本迭代锁定的 spec 点：

- **R14 routes** — the coordinator/run-batch ASR path and the subtitle-arm write-back record
  `transcripts` rows so `v_missing_transcript` converges on all routes.
- **Stem contract** — the three divergent canonical-stem implementations (quality / integrity /
  coordinator-archive_stem) consolidated to a single PM-decided contract.
- **Test drift** — the 18 pre-existing failures in test_scheduler/test_coordinator/test_metadata_cli
  repaired so those suites go green.

## Decisions

| # | Decision | Rationale | Source |
|---|----------|-----------|--------|
| D1 | Direction = R14 routes + stem contract + test drift | Picks up exactly what the prior iteration deferred. | user + autonomous |
| D2 | Scale **L** (3 business plans) | The scope is 3 well-scoped follow-ons. | autonomous |
| D3 | Branch: base `main`, target `main`, integration `iteration/iter-2026-10-closeout` | `main` is the recorded default integration/PR target. | autonomous (AGENTS.md) |
| D4 | Findings cleanup `allow-residual` (default) | Non-blocking R# registered + disclosed. | mstar-harness-core default |
| D5 | Stem contract decision (PM, this compass): consolidate on the **archive_stem** semantics — a part's stem derives from its `(bvid, page_index)` identity; the stem must be parseable back to that identity; `page_label` is a display concern, NOT part of the stem; a row missing `bvid` raises. | archive_stem is the only impl that (a) derives from the canonical identity, (b) raises on missing bvid (fail-loud), and (c) is the publication stem the archive actually writes. quality/integrity's page_label/mismatch fallbacks are display-only. | PM autonomous decision |

## Open Questions

None (D5 settles the stem contract).

## Plans

| plan_id | Name | Status | Notes |
|---------|------|--------|-------|
| r14-routes-writeback | R14 coordinator/run + subtitle-arm write-back | Done | closes F7 (high) |
| stem-contract-consolidation | canonical-stem contract (D5) consolidation | Done | 010 cluster 5 |
| test-drift-repair | fix the 18 pre-existing test failures | Done | medium drift issue |

Status values: `Todo` | `InProgress` | `InReview` | `Done` | `Blocked`

## Milestones

| Milestone | Target date | Status |
|-----------|-------------|--------|
| Spec freeze (compass locked) | 2026-10-02 | done |
| Dev complete (all plans merged) | 2026-10-02 | done |
| QC complete (tri-review) | 2026-10-02 | done |
| Iteration close | 2026-10-02 | done |

## Acceptance Criteria

- R14 routes landed (coordinator/run + subtitle-arm); F7 closed; gap view converges on all routes.
- Stem contract consolidated to D5; the three impls delegate to one function; divergence table resolved.
- The 18 drift failures fixed; test_scheduler/test_coordinator/test_metadata_cli green.
- Findings cleanup allow-residual; no unresolved critical; one PR to `main`.

## Non-Goals

- The other ~50 open residuals (security leads, WAL, raw-sidecar size, etc.).
- R13/R15 as separate plans.

## Roadmap Position

- **Current iteration（iter-2026-10-closeout）**：**delivered** — closes R14 routes + stem contract + test drift.
- **Next iteration**：the remaining open residuals by leverage — the 4 high (torch lock, WebDAV/123pan,
  SESSDATA dead-credential, + any new), then the medium cluster. 触发条件：this iteration merges. owner: PM.
- **最终目标**：a green, converged correctness baseline with the residual register trending to only
  genuinely-deferred items.

## Delivery Branch Policy

| Field | Value |
|-------|-------|
| `iteration_base_branch` | main |
| `spec_integration_branch` | iteration/iter-2026-10-closeout |
| `target_branch` | main |

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Stem consolidation changes a reader's behaviour | Med | Med | pin the chosen contract with a charactarization test; per-file verify consumers |
| Drift fixes touch shared fixtures | Med | Med | fix the fixture root cause (snapshot not written), not per-test |
| R14 routes need coordinator/pilot write-back source | Low | Med | reuse the lazy write-back source pattern from pilot |

## Iteration package

| Path | Purpose |
|------|---------|
| `direction-lock.md` | lock-time record |
| `guides/` | process notes |
| `specs/` | iteration-scoped specs |

## Quality Gate Summary

> Filled at iteration-close.

## Compound Round Summary

- 结晶文档数：0（本轮 3 plans 主要是收尾/收敛；无新非显而易见知识达 Q1-Q8 门槛 — 跨-lane 污染知识已在 iter-2026-10-followup 沉淀）
- 新增 CONCEPTS.md 条目：0
- 触发 compound-refresh：否
- Iteration package 盘点：`direction-lock.md` + compass 为迭代史（Keep snapshot）；无 package spec 满足 `{SPECS_DIR}` 提升准入。

## Iteration Retrospective (minimal)

- 做得好的：R14 routes（HIGH-risk）+ stem 契约 + drift 修复 3 plans 全 Done；QC tri 3/3 unanimous Approve；drift 修复用 root-cause（fixture）而非 per-test patch。
- 可改进的：006 的 in-memory attempt map 引入了 2 个真 regression（cross-process + malformed-history）——上一轮 QC C1 式的 "knob 未接 production" 教训在此复现为 "perf 优化丢了 cross-process 契约"；drift 修复暴露它，已登记 high issue。
- 下迭代建议：修 006 regression（high）；010 cluster 5 已在本轮 D5 决策下完成；继续按 leverage 收敛剩余 medium（raw-sidecar size、WAL、search N+1 等）。
