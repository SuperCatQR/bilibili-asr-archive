---
iteration_id: iter-2026-10-audit-burndown
start_date: 2026-10-02
status: completed
end_date: 2026-10-02
iteration_base_branch: main
target_branch: main
plans: ["001-second-pass-asr-cache-bust", "003-batch-manifest-ledger-writes", "002-store-asr-limit-once", "004-pace-metadata-getters", "007-conftest-tmp-root-syspath", "009-consolidate-cue-parsers"]
---

# iter-2026-10-audit-burndown Delivery Compass

## Scope

Execute the P1 + P2 slice of the 2026-10-02 codebase audit (`.mstar/plans/audit-2026-10-02/`), burning down
the newly-audited correctness / perf / tests / tech-debt findings on the core archival chain.

本迭代锁定的 spec 点：

- **Two-pass ASR correctness** — the second hotword pass must re-decode from a clean model/cache state
  (plan 001), removing the silent insertion-error risk in the evidence-guard repair pass.
- **Manifest ledger performance** — stop re-reading the whole `manifest.jsonl` per row during batches
  (plan 003), the O(rows × bytes) cost that dominates large-batch wall time.
- **Store-route limit correctness** — apply `--limit` once on the store-sourced `asr` queue (plan 002).
- **Metadata pacing** — pace all three per-row metadata getters behind one gateway decorator (plan 004).
- **Test-infra hardening** — fix the conftest `sys.path` + `tmp_root` PID-reuse flake (plan 007).
- **Cue-parser consolidation** — one shared transcript reader, the structural precondition for residual
  C-R3 (plan 009).

## Decisions

> Settled direction-lock items — the record a dispatched role reads instead of re-deriving context from a
> conversation it never saw. Full lock-time record: `direction-lock.md` (this package).

| # | Decision | Rationale | Source |
|---|----------|-----------|--------|
| D1 | Iteration direction = execute the 2026-10-02 audit plans | The audit is the freshest, evidence-first, already-vetted work; "全做" maps to the 10-plan set. | autonomous ranking |
| D2 | Locked scope = P1 (001, 003) + P2 (002, 004, 007, 009) = 6 business plans | Scale budget **M** = 2–3, but the 6 form the dependency-ordered P1/P2 closure; exceeding M is disclosed, not silent. Overflow (005/006/008/010) → next iteration. | autonomous ranking + scale budget |
| D3 | Branch policy: base = `main`, target = `main`, integration = `iteration/iter-2026-10-audit-burndown` | Autonomous branch resolve: `main` is the project-policy default integration / PR target recorded in root `AGENTS.md` (a documented delivery branch, not "whatever HEAD is"). | autonomous branch resolve (AGENTS.md) |
| D4 | Findings cleanup = `allow-residual` (default) | Open R# are registered in the project register + disclosed; only unresolved `critical` blocks Approve. | mstar-harness-core default |

## Open Questions

None.

## Plans

| plan_id | Name | Status | Notes |
|---------|------|--------|-------|
| 001-second-pass-asr-cache-bust | Second hotword pass re-decodes from clean state | Done | P1; depends on 010 (next iter) for the dedup half |
| 003-batch-manifest-ledger-writes | Batch manifest ledger writes | Done | P1 |
| 002-store-asr-limit-once | Apply `--limit` once on the store-sourced `asr` queue | Done | P2 |
| 004-pace-metadata-getters | Pace the three per-row metadata getters | Done | P2 |
| 007-conftest-tmp-root-syspath | Fix conftest `sys.path` + `tmp_root` PID-reuse flake | Done | P2 |
| 009-consolidate-cue-parsers | Consolidate the three cue-parsers | Done | P2; precondition for residual C-R3 |

Status values: `Todo` | `InProgress` | `InReview` | `Done` | `Blocked`

## Milestones

| Milestone | Target date | Status |
|-----------|-------------|--------|
| Spec freeze (compass locked) | 2026-10-02 | done |
| Dev complete (all plans merged) | 2026-10-02 | done |
| QC complete (per-plan tri-review) | 2026-10-02 | done |
| Iteration close | 2026-10-02 | done |

## Acceptance Criteria

- All 6 locked plans (001, 003, 002, 004, 007, 009) execute through the per-plan lifecycle and merge into
  `iteration/iter-2026-10-audit-burndown`.
- Each plan's own Done criteria hold; verification gates are scoped per plan (not repo-wide).
- Compass `## Plans` shows all 6 `Done`; one PR from the integration branch to `main`.
- Findings cleanup `allow-residual`: any open R# registered + disclosed.

## Non-Goals

- The high residual **R14** (ASR→store transcripts-row bridge) and R13/R15 store-route expressiveness — a
  larger store-architecture change; next iteration.
- The two security **Needs-verification** leads (pinned-package httpx TLS posture; WBI signing-key seeding)
  — runtime/MITM probes, not code plans.
- The four truncated audit categories (migration / dx / docs / direction) — uncollected this run.
- Re-planning the 56 already-registered residuals — cross-referenced only.
- The P3 plans **005 / 006 / 008 / 010** — lower leverage; recorded as next iteration (Roadmap Position),
  not dropped.

## Roadmap Position

- **Current iteration（iter-2026-10-audit-burndown）**：**delivered** — the P1/P2 audit slice — second-pass ASR
  correctness, manifest ledger performance, store-route limit correctness, metadata pacing, test-infra
  hardening, cue-parser consolidation.
- **Next iteration**：the P3 audit plans 005 (search-index skip-stamped), 006 (attempt-ledger in-memory
  count), 008 (pytest markers + opt-in gates), 010 (dedupe shared constant/helper clusters); **plus** the
  high residual R14 (ASR→store transcripts bridge). 触发条件：this iteration merges + closes. owner: PM.
- **最终目标**：a clean correctness + performance baseline for the core archival CLI, with the audit's
  P1–P3 findings landed and the residual register trending down.

## Delivery Branch Policy

> Mirror of frontmatter; keep in sync with workflow snapshot `{WORKFLOW_DIR}/<id>/snapshot.json` `branch` anchors.

| Field | Value |
|-------|-------|
| `iteration_base_branch` | main |
| `spec_integration_branch` | iteration/iter-2026-10-audit-burndown |
| `target_branch` | main |

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Plan 001 (cache-bust) depends on the pinned `transformers>=5.13` generate API exposing a usable cache-control knob | Med | Med | STOP condition in plan 001; if the API is absent, report + downgrade rather than guess. |
| Plan 003 (manifest journal) could break the deterministic-snapshot / crash-recovery invariant | Low | High | STOP condition in plan 003; the journal+compaction design must preserve both invariants, gated by tests. |
| Scale budget exceeded (6 > M=2–3) | — | Low | Disclosed in D2; overflow carried to Roadmap Position, not silently expanded. |
| store.db not initialized (`store.not-initialized`) blocks catalog registration | High | Low | Legacy file authority is authoritative pre-cutover (contract §1); proceed on file SSOT, register skipped. |

## Iteration package

> Sibling paths under `{ITERATION_DIR}/<iteration-id>/` — not in `{SPECS_DIR}/` or `{KNOWLEDGE_DIR}/`.
> Promoted to knowledge at iteration-close via **mstar-compound**.

| Path | Purpose |
|------|---------|
| `direction-lock.md` | Durable lock-time record (mode, rationale, acceptance, non-goals, scale budget) |
| `guides/` | Exploration, process notes |
| `specs/` | Iteration-scoped spec drafts |

## Quality Gate Summary

> Filled at iteration-close.

| plan_id | QC decision | QA gate | Residuals | Durable summary |
|---------|-------------|---------|-----------|-----------------|
| 001-second-pass-asr-cache-bust | Approve (tri 3/3 Request Changes → C1 fixed → re-review Approve) | pm-acceptance / targeted | W- (C1 closed; none open for 001) | {SDD_DIR}/001-second-pass-asr-cache-bust/task-1-review.md |
| 003-batch-manifest-ledger-writes | Approve with residuals (L2 Approved; merge regression found+fixed; QC W1-W3 residuals) | pm-acceptance / targeted | W1,W2,W3 (medium, → issue register) | {SDD_DIR}/003-batch-manifest-ledger-writes/task-1-review.md |
| 002-store-asr-limit-once | Approve (L2 Approved; 2 pre-existing R14 failures unrelated) | pm-acceptance / targeted | N/A — none open | {SDD_DIR}/002-store-asr-limit-once/task-1-review.md |
| 004-pace-metadata-getters | Approve with residuals (QC W4,S1) | pm-acceptance / targeted | W4 (medium), S1 (low) → issue register | {SDD_DIR}/004-pace-metadata-getters/task-1-review.md |
| 007-conftest-tmp-root-syspath | Approve (L2 Approved findings:[]) | pm-acceptance / targeted | N/A — none open | {SDD_DIR}/007-conftest-tmp-root-syspath/task-1-review.md |
| 009-consolidate-cue-parsers | Approve (L2 Approved findings:[]) | pm-acceptance / targeted | C-R3 follow-up (separate, already registered) | {SDD_DIR}/009-consolidate-cue-parsers/task-1-review.md |

Open residual disclosure (allow-residual): the QC tri Warnings/Suggestion W1–W4 + S1 are registered as issues in the project store (id `iter-202610-qc-W1..W4`, `iter-202610-qc-S1`), severity medium/low, tracking = issue store + this compass. No unresolved critical. The pre-existing `test_cli_queue_source` R14-surface failures (2) are a registered high residual (R14), not introduced by this iteration.

## Compound Round Summary

- 结晶文档数：2（新增）
  - `knowledge/architecture-patterns/journal-ledger-and-projection-replay.md`（plan 003 journal ledger + shared-projection replay）
  - `knowledge/testing-patterns/verify-knobs-through-production-callers.md`（plan 001 knob-through-production-caller）
- 新增 CONCEPTS.md 条目：0（无新领域词达 qualifying bar）
- 触发 compound-refresh：否（2 篇新文档，重叠已查；`journal-ledger` 与 `operational-sidecars`/`row-merge-on-terminal-transition` 相关但角度不同，非重复）
- Iteration package 盘点：`direction-lock.md` + compass 为迭代史（Keep snapshot）；无 package spec 满足 `{SPECS_DIR}` 提升准入（本轮无锁定跨迭代 spec）；guides/ 未产生独立可复用 guide。

## Iteration Retrospective (minimal)

- 做得好的：
  - 跨 plan 并行 implement（6 独立 worktree/branch，same-host 锁 + verified lease）一次成功；serial integration merge 无冲突。
  - post-merge integration smoke 抓到 plan 003 的跨模块回归（journal vs 非-store coverage reader）——persistence 层变更需要 cross-reader 检查，这点已结晶。
  - QC tri 三席独立收敛到同一 Critical（plan 001 dead knob），targeted fix + re-review 闭环。
- 可改进的：
  - plan 001 把 call-site rewiring 误 defer 到 plan 010，导致 production 中 fix 是 dead code —— "knob 必须接到 production caller"应在 plan done criteria 里就要求，而非依赖 QC 抓。
  - plan 003 的 L2 已标记 "journal staleness" Important，但 merge 后才暴露为可观察回归 —— reviewer 标记的 Important 若涉及跨模块 reader，应同轮修而非留 register。
- 下迭代建议：做 P3 plans（005/006/008/010）+ high residual R14（ASR→store transcripts bridge）；triage 本轮 QC W1–W4 + S1 residuals。
