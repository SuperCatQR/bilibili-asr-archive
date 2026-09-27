---
plan_id: 20260927-evidence-dashboard
title: Evidence dashboard — 队列视图 + exit 语义修复 + 覆盖率本机可复现
status: active
owner: project-manager
created_at: 2026-09-27
iteration_refs: [iter-2026-09-coverage-truth]
spec_integration_branch: iteration/iter-2026-09-coverage-truth
merge_target: iteration/iter-2026-09-coverage-truth
primary_spec: .mstar/iterations/iter-2026-09-coverage-truth/specs/exit-code-contract.md
execution_mode: sdd
plan_parallelism: parallel
enforcement: soft
---

# 20260927-evidence-dashboard

**Main worktree branch**: `main`（control root；本 plan 不切换）

## Problem Statement

操作者无法从工具直接读出"下一个该做什么"，且两个 reader 的 exit 语义把 backlog 当错误：

- `verify` / `coverage` 在 healthy-but-backlogged archive 上 exit 1：e2e-23191782-subtitle-publish-webdav 实测 84 defects 全是 `retryable_incomplete`、全落在 `needs_audio` 行，6 条 published 行零缺陷——exit 1 不是因为档案坏了，而是因为还有工作没做
- e2e-23191782-season-7686105 R2（high，RESOLVED 余留面）：verify 曾把正常 manifest 判 malformed——exit 契约的文档化与"malformed 仅限真格式错误"的判据需要落成代码级断言
- headline 覆盖率数字（150/1730, 8.7%）来自另一台机器（20260925-archive-db-review R3-low）：本机无法复现
- `status` 只打印 collected metadata 状态，不打印队列缺口

**已确认的 residual（本 plan 关闭目标）**：

| Residual | Severity | 关闭条件 |
|----------|----------|----------|
| e2e-23191782-subtitle-publish-webdav R3（healthy archive exit 1） | low | exit 契约修复且文档化 |
| e2e-23191782-season-7686105 R2 余留面（exit 契约文档化） | high 之文档面 | 契约写入 docs + 代码断言 |
| 20260925-archive-db-review R3（headline 数字来源他机） | low | 覆盖率数字由本机 store/manifest 重建 |

## Scope（In）

**Operator 视角的问题**：谁受影响 —— 每天/每周跑归档链的操作者本人，以及任何想挂 cron/自动化的人。三个日常动作今天都不可用：(a) 跑完一轮想看"还剩什么、先做什么"，`status` 只给 metadata 采集状态、不给队列缺口；(b) `verify` / `coverage` 在 healthy 档案上 exit 1，cron 永远报警；(c) 对外报覆盖率数字时只能说"来自另一台机器"。本 plan 修这三件事。

- `verify` / `coverage` 的 exit 契约修复（形态已定稿 = **(a) backlog → exit 0，`--strict` 恢复 exit 1**；见 Decisions DD1 + `specs/exit-code-contract.md` §1–§2）+ 调用方影响面清单（已定稿于 exit-code-contract §3：无脚本/docs/e2e 依赖 backlog 时非零）
- malformed 判据收紧为真格式错误（manifest schema 违反 / store 损坏），与 backlog 类（`retryable_incomplete` / `needs_audio` / `pending`）在输出与 exit 上分离
- `status` 子命令升级：队列视图 = 缺字幕 / 缺音频 / 缺转写分组计数 + 明细列表（默认 top-N，可 `--all`），排序 = pubdate 新发布优先；数据源定稿为 **store-first、manifest-never**（DD2 信息架构 + exit-code-contract §4；查询层写在 store 侧 `MediaQueueRepository` 接口上）
- 覆盖率输出附**可复现注记**：数字来源（store 行数 / manifest 行数）与生成命令，使 headline 数字本机可重建

## Out of Scope

- 队列查询面本身的 schema/视图建设（A plan Task 1）；本 plan 只写读取/展示层
- `status` 之外的 dashboard 形态（TUI / Web / 定时报告）——CLI 文本输出即本迭代交付
- `check-asr-env` 的 shell 环境问题（subtitle-publish R1：HSA 前缀 vs 默认 shell）——下一迭代 host-maintenance 轮次

## Files（预期写面）

- `src/bili_asr/cli.py`（status / verify / coverage 三个 handler 与参数）
- `src/bili_asr/integrity.py`（findings 分级）
- `src/bili_asr/coverage_report.py`（数字注记与来源标注）
- `src/bili_asr/storage/database.py`（队列视图的读取接口，只读）
- `tests/test_cli_help.py` / 相关 verify/coverage/status 单测
- `docs/`（exit 契约文档；README 命令章节同步）

## Decisions（plan 级，承接 compass D5）

- DD1 exit 形态 = **(a) backlog → exit 0，`--strict` 恢复 exit 1**——findings 分两级：`defect`（malformed/损坏，非空 → exit 1）与 `backlog`（未处理工作，单独 `backlog:` 节打印，零 exit 贡献）。调用方影响面已盘点：无脚本/docs/e2e 依赖"backlog 时非零"行为（exit-code-contract §3），README 命令表加一句 `--strict` 说明即可。契约全文 + 四条代码级断言见 `specs/exit-code-contract.md`
- **DD2 status 队列视图的信息架构（Q1 已定稿，2026-09-27 product-manager）**：

  **分组**：按缺口类型分三组，固定顺序输出 —— `缺字幕`（store 中无 transcript 且非 gone）、`缺音频`（有字幕缺口转音频链的 part：已判定需要音频但尚无音频对象/产物）、`缺转写`（有音频、无转写产物）。每组打印 `组名: <总数>` 计数行，组间空行分隔。不按视频分组（一个视频的多 part 缺口会跨组，按视频分组会让"先做什么"的判读依赖跨组心算）。

  **明细行**：每组内按 pubdate 新发布优先排序（pubdate 相同按 bvid 字典序再按 page_index，保证确定性）；默认只打印每组的 top-N 明细，**N=20**；`--all` 打印全量；被截断时组计数行追加 `（显示 20/<总数>，--all 查看全部）`。明细行格式：`  <work_id>  <pubdate YYYY-MM-DD>  <part 标题截断 40 字符>` —— 单行可读，不带 reason 列（组名即原因）。

  **summary header**：输出首行 = `queue: <缺字幕 n1> | <缺音频 n2> | <缺转写 n3>（last fetch: <最近一次 fetch-meta run 的 finished_at 或 "never">）`——一行回答"队列总貌 + 数据新鲜度"。

  **不含完成速率信息**：本期不加 completion-rate / throughput 列。理由：速率需要一个时间窗语义（每日？每周？），窗口定义本身又是一个产品决策，且 store 当前不记 part 级完成时间戳（A plan cutover 回写时机见 DD2，未必含 timestamp）——两 plan 都无数据支撑，硬做会出假数字。完成速率列留作 backlog 项，由 iteration-close 时评估（触发条件：A plan 的回写含时间戳）。

  **判定阈值**：本决策不设"几天内算新发布"的阈值 —— 排序按 pubdate 严格降序，无时间窗过滤；"新发布优先"= 排序规则而非过滤规则。若未来要"只看最近 N 天"，作为新 flag 另议，不进本 plan。

  **数据源承接**：本 plan 的查询层写在 store 侧读取接口上；A plan merge 前接口可双读（manifest + store）兜底，A merge 后切 store 单读——接口签名本 plan Prepare 阶段与 A plan 对齐（见 Task 分解 marker）。

## Task 分解

SDD 四 task，依赖序：T1 → T2 → (T3 ∥ T4)。T3 消费 A plan Task 1 实现的 `MediaQueueRepository` 接口（`list_queue_gaps` / `count_queue_gaps`，签名已定于 `specs/queue-cutover-contract.md` §4——cutover 实现，dashboard 只消费）。**接口消费对齐（architect，seat 2 定稿）**：本 plan Task 3 的查询层只依赖该签名，**不依赖 A 的落地时序**；A merge 前 Task 3 以接口桩（fake repository 返回确定性 `QueueGapItem`）驱动展示层与排序/top-N 逻辑，A merge 后切真实现。status 命令的**数据源定稿为 store-first、manifest-never**（见 exit-code-contract §4：store 是队列权威 compass D2；manifest 在 compat 窗口内只是 legacy reader，永不作 status 数据源）。

- **Task 1**: findings 分级 + exit 契约（`defect` / `backlog` 两级的数据结构与打印分节）+ `--strict`。Verification: exit-code-contract §6.1 的 before/after fixture（84 needs_audio + 6 published → exit 0 + backlog 节；--strict → exit 1）；Effort M
- **Task 2**: malformed 判据收紧为真格式错误 + "well-formed manifest 永不为 defect"的代码断言。Verification: exit-code-contract §6.2（单行损坏 JSONL → exit 1 且无 backlog 误报）；Effort S
- **Task 3**: status 队列视图（DD2 形态：三组固定序 + top-20 + `--all` + summary header）。Verification: DoD-2/3 + exit-code-contract §6.4（metadata-only root 三组的确定性输出）；Effort M
- **Task 4**: coverage 数字注记（来源行数 + 复现命令）+ README/docs 同步。Verification: DoD-4/5；Effort S

## Verification

- 每 task：scoped 单测 + Task 1/2 用 e2e-23191782-subtitle-publish-webdav 的实测档案形态（84 needs_audio + 6 published）做 before/after exit code 证据
- Plan 级 gate：`status` 在 fresh root 与在 metadata-only root 上分别输出可预期的缺口分组；exit 契约的 docs + 代码断言一致

## Definition of Done（可观察结局）

1. `verify` / `coverage` 在 e2e-23191782-subtitle-publish-webdav 实测档案形态（84 needs_audio backlog + 6 published，无任何 malformed）上 exit 0，输出中 backlog 类 findings 与 malformed 类 findings 分节打印；同一档案人为损坏一行 manifest（真格式错误）时 exit 非 0（具体码值按 DD1 形态）
2. `status` 在 metadata-only root（fetch-meta 后、无任何字幕/音频动作）打印三组缺口计数，缺字幕组计数 = store 中无 transcript 非 gone part 数，其余两组为 0 或对应计数；在 fresh root（无 archive.db）仍答配置错误 exit 1（现行 `status`/`runs` exit 契约不变）
3. `status --all` 输出不被截断；默认输出每组恰 20 行明细（当组计数 >20 时）
4. `coverage` 输出附注记：数字来源（store 行数 / manifest 行数分别多少）+ 重建该数字的确切命令；按注记命令在操作机重跑可复现同一 headline 数字
5. DD1 选定的 exit 形态对应的文档章节与代码断言一致（docs 不描述已不存在的 exit 行为）
6. 调用方影响面清单落盘 plan（或 linked issue），列全 `verify` / `coverage` 的全部已知调用方（cron 条目 / README / docs / e2e 期望）及其需要/不需要的变更

## Residuals disclosure

关闭 3 条见表。本 plan 预计**新产生** 0 条；若 DD1 选择保留旧行为的开关形态，需在 docs 写明默认行为变更日期。

## Open Questions（plan 级）

无——Q1 已由 product-manager 定稿（DD2/D7），Q3 已由 architect 定稿（DD1 + exit-code-contract）。
