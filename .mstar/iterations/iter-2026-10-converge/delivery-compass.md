---
iteration_id: iter-2026-10-converge
start_date: 2026-10-02
status: completed
end_date: 2026-10-02
iteration_base_branch: main
target_branch: main
plans: ["fix-006-attempt-ledger", "store-route-expressiveness", "search-n1-batching"]
---

# iter-2026-10-converge Delivery Compass

## Scope

Fix the 006 attempt-ledger regression (high), converge the store-route expressiveness gap
(F7 residual + R13/R15), and fix the search N+1 (search_blocks one-query-per-hit).

本迭代锁定的 spec 点：

- **006 fix** — restore cross-process-safe attempt numbering + the strict malformed-history
  check under the flock, preserving the O(1) single-writer batch perf.
- **Store-route expressiveness** — `pilot`/`schedule` can express "meta_ok, go harvest"; the
  12 test_scheduler/test_long_live fixtures pinned; F7 + R13/R15 closed.
- **Search N+1** — `search_blocks` issues bounded queries (batch the snippet reads / hits);
  no one-query-per-hit.

## Decisions

| # | Decision | Rationale | Source |
|---|----------|-----------|--------|
| D1 | Direction = 006-fix + store-expressiveness + search-N1 | Highest-leverage open items; all pure-code. | user + autonomous |
| D2 | Scale **M** (3 business plans) | 3 well-scoped items. | autonomous |
| D3 | Branch: base `main`, target `main`, integration `iteration/iter-2026-10-converge` | `main` is the recorded default integration/PR target. | autonomous (AGENTS.md) |
| D4 | 006 fix restores cross-process safety under the flock (re-read tail on collision), NOT by reverting to full-scan | keeps the O(1) single-writer fast path while restoring the cross-process contract the flock+O_APPEND already implies. | PM autonomous |
| D5 | Findings cleanup `allow-residual` (default) | Non-blocking R# registered + disclosed. | mstar-harness-core default |

## Open Questions

None.

## Plans

| plan_id | Name | Status | Notes |
|---------|------|--------|-------|
| fix-006-attempt-ledger | Restore cross-process attempt numbering + malformed-history check | Done | high regression |
| store-route-expressiveness | pilot/schedule "meta_ok go harvest" + pin 12 fixtures | Done | F7 + R13/R15 |
| search-n1-batching | batch search_blocks snippet reads | Done | O-R3 |

Status values: `Todo` | `InProgress` | `InReview` | `Done` | `Blocked`

## Milestones

| Milestone | Target date | Status |
|-----------|-------------|--------|
| Spec freeze (compass locked) | 2026-10-02 | done |
| Dev complete (all plans merged) | 2026-10-02 | done |
| QC complete (tri-review) | 2026-10-02 | done |
| Iteration close | 2026-10-02 | done |

## Acceptance Criteria

- 006 regression fixed (2 persistence_scale tests green); single-writer batch perf preserved.
- Store-route expressiveness landed; 12 fixtures pinned; F7 + R13/R15 closed.
- Search N+1 fixed (bounded queries).
- Findings cleanup allow-residual; no unresolved critical; one PR to `main`.

## Non-Goals

- The other open high (torch lock, 123pan WebDAV, SESSDATA) — runtime/ops, need live measurement.
- The other ~37 medium.

## Roadmap Position

- **Current iteration（iter-2026-10-converge）**：**delivered** — 006 fix + store-route expressiveness + search N+1.
- **Next iteration**：the 3 runtime/ops high (torch lock, 123pan, SESSDATA — need live measurement);
  then the medium cluster by leverage. 触发条件：this iteration merges. owner: PM.
- **最终目标**：a converged store↔chain + read-path perf baseline with only genuinely-deferred
  runtime items left open.

## Delivery Branch Policy

| Field | Value |
|-------|-------|
| `iteration_base_branch` | main |
| `spec_integration_branch` | iteration/iter-2026-10-converge |
| `target_branch` | main |

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| 006 cross-process fix reintroduces per-append cost | Med | Med | re-read only the tail on collision (cheap), not full scan; batch_cost test still ~1 re-read |
| Store-expressiveness touches pilot/schedule entry_for_item | Med | Med | pin the 12 fixtures; reuse the entry_for_item seam |
| Search N1 batching changes result order | Low | Med | keep deterministic ordering; pin with a query-count test |

## Iteration package

| Path | Purpose |
|------|---------|
| `direction-lock.md` | lock-time record |
| `guides/` | process notes |
| `specs/` | iteration-scoped specs |

## Quality Gate Summary

> Filled at iteration-close.

## Compound Round Summary

- 结晶文档数：1（新增）— `knowledge/testing-patterns/venv-editable-pth-hides-tree-under-test.md`
- 新增 CONCEPTS.md 条目：0
- 触发 compound-refresh：否
- Iteration package 盘点：`direction-lock.md` + compass 为迭代史（Keep snapshot）。

## Iteration Retrospective (minimal)

- 做得好的：006 的跨进程 regression 被真正修复（三项独立证伪都无法打破：1600 次差分模糊测试 0 mismatch）；search 批量化实测 1203 SELECT/3.70s → 5 SELECT/0.14s。
- 可改进的：(1) 我最初 dispatch 给 subagent 的 PYTHONPATH 路径是错的，导致子进程经 venv editable .pth 解析到控制检出——连续多次"subagent 失败"实为环境误判；这是本轮最大教训，已结晶。(2) 我在 falsify 后 restore 时把预-wave 文件覆盖回来，导致一个 commit 的 message 声称的修复不在树里（已用后续 commit 修正）；falsify 的 restore 必须用显式备份路径并立即重跑测试。(3) 轮次 QC 的 traceability 声明（"已登记为 residual"）当时并不成立——声明前必须核对 store。
- 下迭代建议：I-000156（store route 表达 captioned-but-unarchived，medium）需 PM/product 决策是否放宽 §7 契约；然后收敛剩余 medium。
