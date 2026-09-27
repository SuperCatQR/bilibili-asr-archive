---
iteration_id: iter-2026-09-coverage-truth
start_date: 2026-09-27
status: locked
iteration_base_branch: main
target_branch: main
plans:
  - 20260927-archive-db-queue-cutover
  - 20260927-evidence-dashboard
---

# iter-2026-09-coverage-truth Delivery Compass

## Scope

本迭代锁定的 spec 点：

- **archive.db 成为唯一工作队列 SSOT**：`fetch-meta` 已写入的 metadata（videos / video_parts / 作者 / 标签）直接驱动 `download-audio` / `asr` / `run` / `pilot` / `verify` / `coverage`；`derive-manifest` 的 manifest 桥接退役（legacy 覆盖洞随之消失）。注：iter-2026-09-queue-bridge 已完成过"队列半边"的切换（`completed`），本迭代把该路径延伸为**唯一**队列并删除桥接命令。
- **verify / coverage 的 exit 语义修复**：healthy archive 仅因尚有未处理行不再 exit 1（当前实测 84 defects 全是 `retryable_incomplete` backlog 而非错误）；两个 public reader 不再把正常 manifest 判 malformed。
- **`status` 升级为队列视图**：操作者可读地回答"下一个该做什么、为什么"——哪些 part 缺字幕 / 缺音频 / 缺转写，按 pubdate 新发布优先排序。
- **覆盖率数字本机可复现**：headline coverage figure（150/1730 型数字）不再引自另一台机器；verify/coverage 的输出可由本机 store 重建。
- **D6 的假阴性修复**：死 SESSDATA 导致的空 inventory 不再被记为 `no-subtitle`（记入 A plan 范围，D6）。

## Decisions

| # | Decision | Rationale | Source |
|---|----------|-----------|--------|
| D1 | 范围 = A（archive.db cutover）+ B（证据看板）两个 plan；C（proofread 产品化 + hotword 闭环）下一迭代 | 用户选择；A 消 deferred residual 密度最高处（含 1 条 high），B 是日常运营与自动化的前置；C 需要 GPU 机 A/B 环境，风险隔离 | user instruction |
| D2 | cutover 形态 = 双轨收敛：archive.db 提升为唯一队列；manifest 降级为 attempt ledger（run/coordinator 仍写）+ legacy 兼容读 1–2 个 iteration 后删 | 符合"移除过时路径"核心守则但控制验收风险；完全单轨的测试迁移面本迭代收不住 | user instruction |
| D3 | A、B 两个 plan 各建独立 feature worktree 并行 SDD；integration merge 串行（integration_merge_lease 单 holder） | 本机同主机、共享 flock 可用，满足 §2.0 #5 跨 plan 并行安全闸；两 plan 写面以 cli.py / 新 service 模块为主，重叠区（verify/coverage/status 处理器）在 merge 时由后 merge 方 rebase 解决 | user instruction |
| D4 | hotword guard + A/B 验证挪到下一迭代（C），本迭代不动 asr.py 的 hotword 路径 | hotword 的 high residual（插入源）与 cutover 写面零重叠；合并会扩大本迭代 blast radius | grill-me |
| D5 | exit 语义具体形态（exit 0 + `--strict` 开关 vs 分级 exit code vs 纯文档化契约）留给 plan Prepare 阶段 architect 定稿， compass 不预设 | exit 语义有多种合规实现；Prepare 的 specify/clarify 环节更适合权衡 | grill-me |
| D6 | 死 SESSDATA → 空 inventory → `no-subtitle` 假阴性（20260925-archive-db-review R1, high）纳入 A 的 plan 范围：subtitle_ingest 的 outcome 映射必须区分"凭证无效/空响应"与"确认无字幕" | 同属"store 里的真相不可信"主题，且与 harvest/probe 的队列视图（B）共享 outcome 定义 | grill-me |
| D7 | status 队列视图信息架构定稿（Q1 收敛）：按缺口类型分三组（缺字幕/缺音频/缺转写，固定顺序）+ 每组 top-N 明细（默认 N=20，`--all` 全量），组内 pubdate 降序（同 pubdate 按 bvid 字典序 + page_index 保证确定性）；首行 summary header（三组计数 + last-fetch 时间戳）；**不含完成速率信息**（速率需时间窗语义 + part 级完成时间戳，两 plan 数据面均不支持，留 iteration-close 评估）；"新发布优先"= 排序规则非过滤规则，不设天数阈值 | 操作者的问题是"下一个该做什么"——按缺口分组直接给出行动分类（先补字幕/先补音频/先补转写）；按视频分组会让一个视频的多 part 缺口跨组、判读需心算；速率列在本迭代会出假数字，诚实暴露优于虚假精确 | product-manager（Prepare 链 seat 1，2026-09-27）；完整 spec 落 B plan `## Decisions` DD2 |

## Open Questions

| # | Question | Owner | Blocking? |
|---|----------|-------|-----------|
| ~~Q1~~ | **已收敛 → D7**（2026-09-27 product-manager seat 1）：分组/top-N/速率列/阈值四项全部定稿 | — | — |
| ~~Q2~~ | **已收敛 → D8**（2026-09-27 architect seat 2）：回滚 = 隐藏 `--queue-source {store,manifest}` 开关 + attempt ledger 持续写入双载体；legacy 兼容读删除触发器 = 下一 iteration close 时评估（contract §7） | — | — |
| ~~Q3~~ | **已收敛 → D9**（2026-09-27 architect seat 2）：选 (a) backlog→exit 0 + `--strict`；调用方盘点零迁移（exit-code-contract §3） | — | — |
| ~~Q4~~ | **已收敛 → D10**（2026-09-27 architect seat 2）：单 plan SDD 六 task / 四 task，依赖序与 split point 已写；共享接口 `MediaQueueRepository`（contract §4） | — | — |

| D8 | cutover 回滚载体 = 隐藏 `--queue-source {store,manifest}` 开关（默认 `store`；`download-audio` / `asr` / `pilot` / `run` 四个命令；`schedule` / `campaign` 与新删的 `derive-manifest` 不给开关）；legacy manifest 只读兼容窗口的可测量删除触发器 | 代码级单 revert 路径对非 git 操作者不可操作；开关使命令行可审计且不留持久状态文件（不违 no-migration 纪律）；开关与 compat-read 评估同在下一迭代 C 的 compound close 移除（**更正 2026-09-27**：本条在 seat 2 链内曾以 DD5"无运行时开关"形态落盘，同轮由 seat 2 自我更正为 DD6 flag 形态——compass/contract/plan 三处已一致） | architect seat 2 |
| D9 | verify/coverage exit 形态 = backlog→exit 0 + `--strict` 恢复 exit 1 | 调用方零迁移；分级 exit code invent 新词汇；doc-only 不解决 cron 痛点 | architect seat 2 |
| D10 | SDD 切分：cutover 六 task（T1→(T2∥T5)→T3→T4→T6，T2 预声明 split point）+ dashboard 四 task（T1→T2→(T3∥T4)）；共享接口 = `MediaQueueRepository`（`list_queue_gaps`/`count_queue_gaps`→`QueueGapItem`；三 gap；排序 pubdate DESC, bvid ASC, page_index ASC），签名定于 queue-cutover-contract §4（cutover Task 1 实现，dashboard Task 3 消费；dashboard 用接口桩先行、A merge 后切真实现） | 两 plan 写面在 cli.py 重叠区最小化；第二份 SQL 禁止；接口签名先冻结让并行开发只对接口不对实现 | architect seat 2 |
| D11 | `processing_status` 收敛 = 可达性收敛（写纪律 + 读纪律），非 schema 变更：`metadata_collected` 不再有写路径，pending 视图按 `='discovered'` 过滤，旧库残留渲染为惰性计数、永不再被选中；目标可达集 `{discovered, gone}` | CREATE IF NOT EXISTS 禁 ALTER 且 no-migration 禁重建表；新列/新表会给两态真相引入第二来源且需双写 | architect seat 2（cutover plan DD3 定稿） |
| D12 | 音频证据边界：`audio_objects` / `part_audio_objects` 的首个 writer 归 iter-2026-09-metadata-audio-layout 的 audio-inventory plan（已 registered、同主机并行）；本迭代 cutover 音频证据写 `acquisition_attempts(kind='audio')`，"audio evidence"判据 = 二者之一（fresh 库 attempts-audio 或 part_audio_objects）；旧库（无 attempts.kind 列）退化为可接受过渡态 | 切清两 iteration 写面，避免同主机并行 plan 撞 audio_objects 首写；旧库不半应用（media-queue service 拒写旧 attempts 表） | architect seat 2（cutover spec §10） |

## Plans

| plan_id | Name | Status | Notes |
|---------|------|--------|-------|
| 20260927-archive-db-queue-cutover | Archive.db 队列 SSOT cutover（退役 manifest 桥） | Todo | SDD；feature worktree；含 D6 的 SESSDATA 假阴性修复 |
| 20260927-evidence-dashboard | Evidence dashboard（队列视图 + exit 语义 + 覆盖率本机可复现） | Todo | SDD；feature worktree；与 A 并行，merge 串行 |

Status values: `Todo` | `InProgress` | `InReview` | `Done` | `Blocked`

## Milestones

| Milestone | Target date | Status |
|-----------|-------------|--------|
| Spec freeze | 2026-09-27 | pending |
| Dev complete | 2026-09-28 | pending |
| QC complete | 2026-09-28 | pending |
| Iteration close | 2026-09-29 | pending |

## Acceptance Criteria

- [ ] 验收环境：仅有 archive.db（`fetch-meta` 产物，无 manifest 目录）的 fresh archive root。`download-audio --bvid <part>` → `asr --bvid <part>` 各 exit 0，完成后 store 中该 part 从 `v_pending_subtitles`（及对应音频/转写缺口枚举）消失、产物路径可查询；`pilot` / `run` 同环境可完成一轮 bounded 运行
- [ ] `bili-asr derive-manifest <args>` 以 `invalid choice: 'derive-manifest'` 失败（exit 2）；此后全仓库 `grep -rn "derive-manifest" src/ tests/` 无匹配（仅 docs 迁移说明保留）；iter-2026-09-queue-bridge R2（legacy bare-bvid 覆盖洞）随代码删除关闭
- [ ] 在 e2e-23191782-subtitle-publish-webdav 的实测档案形态（84 条 `retryable_incomplete` backlog + 6 条 published，零 malformed）上：`verify` 与 `coverage` 均 exit 0 且输出中 backlog 类与 malformed 类 findings 分节；人为损坏一条 manifest 行（真格式错误）后 exit 非 0（码值按 D5/Q3 定稿的 DD1 形态，落在 plan DoD）；e2e-season-7686105 R2（high）关闭
- [ ] `bili-asr status` 在 metadata-only root 上按 D7/DD2 输出：首行 summary（三组计数 + last-fetch 时间戳）、缺字幕/缺音频/缺转写三组各自计数行、组内 pubdate 降序 top-20 明细（`--all` 不截断）；同一 host 按 plan 文档注记的重跑命令可复现 headline 覆盖率数字（archive-db-review R3 关闭）
- [ ] 以伪造/失效 SESSDATA 跑 `harvest-subs`：受影响 part 全部记 `failed`（含凭证无效 evidence），store 中 `no-subtitle` outcome 零新增、受影响 part 仍在 `v_pending_subtitles` 枚举内（archive-db-review R1, high 关闭）
- [ ] 两个 plan 各自完成 SDD（全部 task InReview→Done）+ plan QC tri-review 结论为 Approve（非 Approve 的须以 open issue 形式显式披露并登记 severity）；`iteration/iter-2026-09-coverage-truth` 分支 CI/test 全绿，PR 开到 `main`

## Non-Goals

- **不动 hotword 路径**（asr.py 的 DEFAULT_HOTWORDS / 注入逻辑）——下一迭代 C；本迭代任何 plan 不得修改 asr.py 的 hotword 相关行（避免与进行中的 aac-decode-contract 撞面）
- **不做 proofread 产品化**——下一迭代 C；proofread-transcripts 产物仍在 /mnt/123pan 手工管线
- **不做输出布局形状决策**（iter-2026-09-metadata-audio-layout 的 Q4–Q6）——那个决策属于该 iteration 的 operator，与本迭代并行不悖
- **不改 run/scheduler/campaign 的 attempt ledger 语义**——manifest 仍写 attempt 记录（D2 双轨收敛的另一半），只退役其"队列"角色
- **不动 `fetch-meta` 的既有 metadata 列**——本迭代消费 metadata-audio-layout 正在写入的表，不与之争写面

## Roadmap Position

- **Current iteration（iter-2026-09-coverage-truth）**：`_default` roadmap 的 P0 全部两条（queue-ssot-cutover + evidence dashboard 的 exit/覆盖率部分）；C（proofread 产品化 + hotword 闭环）= roadmap P1 下移到下一迭代
- **Next iteration**：proofread-pipeline + hotword 闭环（触发条件：本 iteration Phase 6 close 之后；owner：PM/operator）；可能同时并入输出布局决策的第三个 plan（触发条件：operator 拍板 metadata-audio-layout 的 Q4–Q6）
- **最终目标**：操作者对本机归档状态有单一、诚实、可复现的真相视图（roadmap Direction 第 2/3 条）

## Delivery Branch Policy

| Field | Value |
|-------|-------|
| `iteration_base_branch` | `main`（当前 1f2dcd0；进行中的 iter-2026-09-metadata-audio-layout 的 integration 分支已另建，无冲突） |
| `spec_integration_branch` | `iteration/iter-2026-09-coverage-truth`（本迭代 §6 创建） |
| `target_branch` | `main`（AGENTS.md 默认集成/PR 目标） |

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| 与 iter-2026-09-metadata-audio-layout 的 T1b/audio-inventory 写面重叠（cli.py / storage/models.py） | Med | Med | Phase 2 派发前核对对方 plan 的 Files list（28 文件，asr.py 仅在 Out-of-scope）；重叠文件以先 merge 方为准，后 merge 方 rebase；integration_merge_lease 串行 |
| 与 20260927-aac-decode-contract 撞车（asr.py / conftest） | Low | Med | 本迭代 plans 的 Files 明确排除 asr.py / tests/conftest.py（Non-Goals 已写） |
| cutover 后某些隐含依赖 manifest 队列的 e2e fixture 失效 | Med | Med | plan 的 Prepare 阶段列 e2e fixture 影响面清单（Q3 同款动作），compat read 窗口兜底 |
| exit 语义变更破坏既有 cron/文档期望 | Low | Low | D5/Q3 要求列出全部调用方后再定形态；文档同步更新 |

## Iteration package

| Path | Purpose |
|------|---------|
| `guides/` | 探索笔记（本迭代暂未使用） |
| `specs/` | 迭代级 spec 草稿（ Prepare 阶段由 architect 落 queue-cutover-contract.md / exit-code-contract.md） |
| `README.md` | Package 文档索引 |

## Quality Gate Summary

> Filled at iteration-close.

| plan_id | QC decision | QA gate | Residuals | Durable summary |
|---------|-------------|---------|-----------|-----------------|
| 20260927-archive-db-queue-cutover | — | — | — | — |
| 20260927-evidence-dashboard | — | — | — | — |

## Compound Round Summary

> Filled at iteration-close.

- 结晶文档数：—
- 新增 CONCEPTS.md 条目：—
- 触发 compound-refresh：—
