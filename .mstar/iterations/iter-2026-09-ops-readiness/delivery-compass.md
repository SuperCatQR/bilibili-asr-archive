---
iteration_id: iter-2026-09-ops-readiness
start_date: 2026-09-27
end_date: 2026-09-28
status: completed
iteration_base_branch: main
target_branch: main
plans:
  - 20260928-queue-cli-cutover
  - 20260928-hotword-injection-governance
  - 20260928-proofread-pipeline
  - 20260928-transcript-search
  - 20260928-ops-docs-and-closeout
spec_integration_branch: iteration/iter-2026-09-ops-readiness
enforcement: soft
---

# iter-2026-09-ops-readiness Delivery Compass

## Scope

Operational readiness of the archive: the queue SSOT cutover's CLI/coordinator wiring
(deferred D-1..D-5 of `20260927-archive-db-queue-cutover`), the operator evidence dashboard's
`status` queue view (deferred B-D1/B-D2 of `20260927-evidence-dashboard`), hotword/provenance
injection governance (residual `20260922-proofread-wave · R1`, high), proofread pipeline
productization (`bili-asr proofread`, roadmap P1), and the transcript retrieval layer
(`bili-asr search`, FTS5). Locked autonomously this session per user instruction
("挑搞优先级的做了，可用agentteam XL"); lock record: `direction-lock.md` in this package.

## Decisions

| # | Decision | Rationale | Source |
|---|----------|-----------|--------|
| D1 | Five business plans, scale XL (at cap): queue-cli-cutover, hotword-injection-governance, proofread-pipeline, transcript-search, ops-docs-and-closeout | Residual density: D-1 wiring unblocks every downstream automation; hotword R1 is the last `high`; proofread/search close the two biggest user-visible gaps | autonomous ranking + roadmap P0/P1 |
| D2 | Branch policy: base `main`, integration `iteration/iter-2026-09-ops-readiness`, target `main` | Continuity with all prior iterations in this repo (every snapshot uses the same triple) | prior compass frontmatter |
| D3 | Interrupt resilience / large-input protection deferred out of this iteration | Smaller shippable slices win; capacity already at the XL cap with 5 plans | autonomous-direction-lock heuristic 4 |
| D4 | Existing sealed plan `20260825-search-export-fts5` is a reference only; `20260928-transcript-search` re-scopes retrieval to FTS5-over-archived-transcripts with pubdate filters | The 2026-08 plan predates the SQLite cutover and the transcript store; its file is kept as evidence, not re-opened | repo evidence |

## Open Questions

| # | Question | Owner | Blocking? |
|---|----------|-------|-----------|
| Q1 | Under `--queue-source manifest`, should `status` still read the store? — **RULED YES** (product-manager, Phase 1 review): `status` is store-native; the flag governs queue inputs only. Pinned in plan `20260928-queue-cli-cutover` MQ1; not re-openable without a new product decision | product-manager (ruled) | No |
| Q2 | Keep-vs-drop per hotword token depends on the A/B measurement inside the governance plan; tokens with no measured benefit are dropped | product-manager (within plan 2) | No |

## Plans

| plan_id | Name | Status | Notes |
|---------|------|--------|-------|
| 20260928-queue-cli-cutover | Queue SSOT CLI/coordinator wiring + status queue view + cutover docs | Done | merged to integration (tip a16aebc); QC tri approve-with-residuals |
| 20260928-hotword-injection-governance | Hotword insertion-error governance + benefit A/B | Done | merged to integration (tip a16aebc); QC tri approve-with-residuals |
| 20260928-proofread-pipeline | `bili-asr proofread` subcommand (merge-v2 productization) | Done | merged to integration (tip a16aebc); QC tri approve-with-residuals |
| 20260928-transcript-search | `bili-asr search` FTS5 retrieval over archived transcripts | Done | merged to integration (tip a16aebc); QC tri approve-with-residuals |
| 20260928-ops-docs-and-closeout | Coverage provenance note, README three-step chain, deferred-tail docs | Done | merged to integration (tip a16aebc); QC tri approve-with-residuals |

## Milestones

| Milestone | Target date | Status |
|-----------|-------------|--------|
| queue-cli-cutover merged to integration | 2026-09-28 | open |
| hotword governance decided (keep/drop per token) | 2026-09-28 | open |
| proofread + search subcommands landed | 2026-09-29 | open |
| Phase 3 close + PR + Phase 6 post-merge close | 2026-09-30 | open |

## Acceptance Criteria

- Fresh archive.db-only root completes `download-audio` → `asr` with the store as the sole
  queue input; `--queue-source {store,manifest}` rollback flag works; `derive-manifest` is gone.
- `status` renders the three gap groups (contract §4: never sum the counts), top-20 default,
  `--all`, summary header with last-fetch time.
- `provenance.hotwords` can no longer inject characters into transcripts; a per-token
  keep/drop decision backed by measured word accuracy exists in the plan record.
- `bili-asr proofread` produces the side-by-side table + alignment jsonl with count guards.
- `bili-asr search <query>` returns bvid + time-ranged matches with pubdate filtering.
- All plans pass plan QC tri (N=3) + QA gate; compound round + roadmap `delivered` update.

## Non-Goals

- Interrupt resilience / SIGKILL journaling; large-input streaming caps (deferred; roadmap).
- Knowledge-base hygiene, README GPU self-check (deferred; roadmap).
- Cron/daemon automation, GPU batch inference (next iteration; needs D-1).
- Speaker diarization; editorial-stages parked-lifecycle recovery.

## Roadmap Position

- Current iteration: operational readiness — queue truth at the CLI surface, hotword honesty,
  proofreading and retrieval as CLI capabilities.
- Next iteration: `ops-automation` (cron/daemon incremental patrol, health report) + P3
  protection slice (interrupt resilience, large-input streaming) + knowledge hygiene,
  owner PM, trigger = this iteration's Phase 6 close.

## Delivery Branch Policy

| Field | Value |
|-------|-------|
| iteration_base_branch | main |
| spec_integration_branch | iteration/iter-2026-09-ops-readiness |
| target_branch | main |

## Compound Round Summary

- 本迭代 inline 实现（subagent 通道在本会话被宿主禁用），compound 候选登记到下一迭代统一结晶：queue_source 双语模块模式、FTS 门控 shim 模式（无迁移规则下的增量索引）、证据守卫 two-pass 重播种、merge-v2 块的纯函数对齐。待 Q1–Q8 自检后写入 {KNOWLEDGE_DIR}。
- package 盘点：direction-lock 记录保留；本迭代无新 spec 除 proofread.md（已随 PR 落在 {SPECS_DIR}）。


## Quality Gate Summary

| plan_id | QC | Residuals (tracking) |
|---------|----|----------------------|
| 20260928-queue-cli-cutover | QC tri approve-with-residuals（blocking F1/F2 已修） | O-R1..O-R7（register iter-2026-09-ops-readiness 组）+ roadmap P2.5（D-3/D-4 剩余面、asr-local storage） |
| 20260928-hotword-injection-governance | 同上 | A/B 数字 PENDING-OPERATOR（roadmap P2.5） |
| 20260928-proofread-pipeline | 同上 | 无 plan 级新 residual |
| 20260928-transcript-search | 同上 | O-R3/O-R4/O-R5（search 性能与记账） |
| 20260928-ops-docs-and-closeout | inline（PM） | B-D2 coverage provenance note 尾项 |

Unresolved critical: none.

## Iteration Retrospective (minimal)

- 宿主在本会话禁用 subagent 通道——四个 plan 全部主会话 inline 实现；`workflow` 工具的只读 fan-out（QC tri）不受限，成为审查路径。教训：Mnemon 受限会话的 fork 继承同样禁用 subagent，iteration-loop 的 SDD 派发要预备 inline 回退。
- QC seat 3 的两个 blocking 发现（混合 id 空间 stamp、kept-vs-dropped 两遍解码门）都靠「执行复现」坐实——只读审查的执行复现价值再次验证。
- B-D1（status 队列视图）在本迭代落地；B-D2（coverage provenance note）与 D-3/D-4 剩余面（derive-manifest 删除、subtitle_ingest outcome 映射）显式登记 roadmap P2.5，不留口头债。
