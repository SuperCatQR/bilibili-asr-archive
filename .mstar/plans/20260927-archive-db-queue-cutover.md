---
plan_id: 20260927-archive-db-queue-cutover
title: Archive.db 队列 SSOT cutover — 退役 manifest 桥接
status: active
owner: project-manager
created_at: 2026-09-27
iteration_refs: [iter-2026-09-coverage-truth]
spec_integration_branch: iteration/iter-2026-09-coverage-truth
merge_target: iteration/iter-2026-09-coverage-truth
primary_spec: .mstar/iterations/iter-2026-09-coverage-truth/specs/queue-cutover-contract.md
execution_mode: sdd
plan_parallelism: parallel
enforcement: soft
---

# 20260927-archive-db-queue-cutover

**Main worktree branch**: `main`（control root；本 plan 不切换）

## Problem Statement

ASR 链的队列真相分裂在两处：`fetch-meta` 把真实 metadata 写入 SQLite（archive.db），但 `download-audio` / `asr` / `pilot` / `run` / `schedule` / `campaign` 只读 `manifest/manifest.jsonl`；连接两者的 `derive-manifest` 是 additive 桥，带有 legacy bare-bvid 覆盖洞（iter-2026-09-queue-bridge R2），且 ASR 结果从不回写 store（e2e-asr-vs-subtitle R3）。

**Operator 视角的问题**（谁在受影响）：操作者的日常三步 —— `fetch-meta` → 字幕入档（`harvest-subs`）→ 音频转写链（`download-audio` → `asr`，或一把梭 `run` / `schedule` / `campaign`）—— 在第二步和第三步之间断裂。字幕已入 store 的 part 必须再跑一次 `derive-manifest` 桥接命令才能让音频链看见，而桥本身是 additive 的、对 legacy bare-bvid 行有覆盖洞（重复下载+重复 ASR），桥不写回的漏洞让 store 永远停留在旧状态。后果：

- AI 字幕 part 进不了 audio→ASR 分支（e2e-longform R2）；`download-audio --bvid` 对未入队的 part 答 "unresolved"
- ASR 完成后 archive.db 的 part 状态永远停在 `audio_ok`，`v_pending_*` 视图看不到产出
- 队列排序/去重逻辑（manifest 侧）与 metadata 真相（store 侧）各自为政

**已确认的 residual（本 plan 关闭目标）**：

| Residual | Severity | 关闭条件 |
|----------|----------|----------|
| e2e-23191782-season-7686105 R1（archive.db→ASR 无桥） | medium | ASR 链以 store 队列为输入 |
| iter-2026-09-queue-bridge R2（legacy bare-bvid 覆盖洞） | low | derive-manifest 退役 |
| e2e-23191782-asr-vs-subtitle-webdav R3（ASR work never reaches the store） | medium | ASR 完成回写 store |
| 20260925-archive-db-review R1（死 SESSDATA 空 inventory → `no-subtitle` 假阴性，**high**） | high | subtitle_ingest outcome 映射区分凭证无效/空响应 vs 确认无字幕 |
| 20260925-archive-db-review R2（`processing_status` 不可达状态 `metadata_collected`） | medium | 状态机收敛 |

## Scope（In）

- `download-audio` / `asr` / `pilot` 的队列输入从 manifest 切换为 archive.db 查询（按 `MediaQueueRepository` 的三 gap 选择器——`missing_subtitle` / `missing_audio` / `missing_transcript`，即 D7/DD4 的三缺口组——及 D6 修正后的 outcome 视图）
- `run` / `schedule` / `campaign` 协调器的 stage 输入同步切换；manifest 降级为 attempt ledger（仍写，不读）
- `derive-manifest` 命令删除（含其测试）；legacy manifest 文件保留**只读兼容**（verify/coverage 的 manifest 读取路径本 plan 不动，归 20260927-evidence-dashboard）
- ASR 完成 / 字幕 harvest 完成时回写 store 的 part 状态与产物路径
- `subtitle_ingest` 的 outcome 映射修复（D6）：空 inventory / 凭证错误 → `failed` + 明确 evidence；不得记 `no-subtitle`
- `video_parts.processing_status` 状态机收敛（去掉 `metadata_collected` 不可达态）

## Target State（用户价值陈述）

操作者的三步日常链变成"store 单向驱动、无桥接命令"：

1. `fetch-meta` 写入 archive.db —— 不变
2. `harvest-subs` 从 archive.db 选件、回写 archive.db —— 不变（本 plan 不动）
3. `download-audio` / `asr` / `pilot` / `run` / `schedule` / `campaign` **直接以 archive.db 为工作队列**：选型 = "store 中无 transcript 且非 gone 的 part"（字幕缺口）与 "有音频、无转写"（转写缺口）；完成时回写 store，使 `v_pending_*` 视图与产物路径即刻反映现实

manifest 降级为 attempt ledger：`run` / `schedule` / `campaign` / `pilot` 仍写 attempt 行（断点续跑语义不变），但**任何命令不再从 manifest 选工作**。`derive-manifest` 子命令删除。

**可观察行为变更（CLI surface）**：

| 变更 | 之前 | 之后 |
|------|------|------|
| `derive-manifest` 子命令 | 存在（桥接 store→manifest） | **删除**；`bili-asr derive-manifest` 答 `invalid choice`（argparse exit 2） |
| 操作者跑音频链前 | 必须先 `derive-manifest` 把 store 队列 append 进 manifest | 直接跑 `download-audio --missing-subs` / `asr --pending`；队列来自 store 查询 |
| `download-audio --bvid X` 对"字幕已入 store 但从未进 manifest"的 part | 答 unresolved（unresolved：manifest 里没有对应行） | 正常选中并下载（store 队列命中） |
| ASR / harvest 完成后 store 状态 | `audio_ok` 永远不变，`v_pending_*` 不收敛 | part 完成即回写，pending 视图行数随完成递减 |
| `harvest-subs` 用死 SESSDATA 跑 | 空 inventory 被记无语义信号的 `no-subtitle`（R1） | `no-subtitle` 保留但 `error_code=not_found`（语义更正 = "该凭证实际没看到内容"，覆盖死凭证空响应与上游 not_found）；operator 据此 re-probe 已知正片判凭证有效性（spec §5，gateway `-101` 已走 `not_found`，故不新增 outcome） |
| `status` 依赖的 pending 查询 | —— | 本 plan 只保证 store 查询面充足；展示形态归 evidence-dashboard plan |

**Operator 迁移说明（写进 plan，实现时同步 docs）**：三步链里删掉 `derive-manifest` 这一步即可，其余命令名与参数不变；`--missing-subs` / `--pending` 语义保留（"全量处理当前队列缺口"），只是队列来源换为 store。回滚路径（architect seat 2 按 DD6 更正）：`download-audio` / `asr` / `pilot` / `run` 加隐藏 `--queue-source {store,manifest}`（默认 store），operator 可用 `--queue-source manifest` 临时回退到 manifest 队列读；`schedule` / `campaign` 无开关（批处理链直接切 store）。该 flag 在下一迭代 C compound 收口时随 legacy 兼容读一并评估删除。

## Out of Scope

- `asr.py` 的 hotword / DEFAULT_HOTWORDS 任何行（iteration compass Non-Goal D4；同时避开 aac-decode-contract 的写面）
- `verify` / `coverage` 的 exit 语义（另一 plan）；但本 plan 不得破坏它们现有读取面
- `status` 队列视图的信息架构（另一 plan）；本 plan 只保证 store 侧有支撑该视图所需的查询面
- `fetch-meta` 的 metadata 列扩展（iter-2026-09-metadata-audio-layout 的 T1b 负责 video_title，本 plan 消费即可）

## Files（预期写面）

- `src/bili_asr/cli.py`（download-audio / asr / pilot / run / schedule / campaign 的输入装配、删 derive-manifest 子命令）
- `src/bili_asr/services/manifest_derivation.py`（**删除**）
- `src/bili_asr/services/subtitle_ingest.py`（outcome 映射）
- `src/bili_asr/services/metadata_ingest.py`（processing_status 收敛，如涉）
- `src/bili_asr/storage/schema.sql` + `storage/database.py`（队列视图 / 回写接口；CREATE IF NOT EXISTS 约定，不改既有列——metadata-coverage-contract 的 five-hop 规则）
- `src/bili_asr/coordinator.py` / `scheduler.py` / `campaign.py`（stage 输入）
- `tests/test_cli_derive_manifest.py`（**删除**）；`tests/test_cli_*.py` 中队列输入相关的夹具改造
- `docs/metadata-storage.md`（边界章节更新）

## Decisions（plan 级，承接 compass D2/D6）

- DD1 双轨收敛：store 为唯一队列；manifest 仅作 attempt ledger（run/coordinator 写），保留 legacy 只读兼容 1–2 个 iteration（删除时间表 = 下一迭代 C 的 compound 收口时评估）
- DD2 回写时机：ASR/harvest 的**每个 part 完成时**即回写（不等 run 结束），与 manifest attempt 行的落盘时机对齐
- DD3 `processing_status` 收敛：**删除不可达状态 `metadata_collected`**（architect seat 2 精确化）——收敛 = 可达性收敛，非 schema 变更：写纪律（无任何写路径产生它，`metadata_ingest.py:426` 已只写 `discovered`）+ 读纪律（pending 视图按 `='discovered'` 过滤，旧库残留 `metadata_collected` 渲染为惰性计数、永不再被选中）。因 `CREATE … IF NOT EXISTS` 禁 ALTER 且 no-migration 禁重建表，CHECK 保持原样；目标可达集实收敛为 `{discovered, gone}`（DD3 原描述的 metadata_done/字幕/音频/转写各态由 queue-cutover-contract §3/§4 的 transcript/audio 证据承载，不落 processing_status 列）。详见 `specs/queue-cutover-contract.md` §6
- DD4 共享接口（architect seat 2 定名）= `MediaQueueRepository`（`storage/database.py` 新增窄接口，命名对齐既有 `MetadataRepository`/`TranscriptRepository`）。**读模型** = `QueueGapItem`（`work_id/bvid/page_index/gap/pubdate/video_title/duration_ms/newest_outcome/newest_error_code/attempt_count`）+ `list_queue_gaps(gap=…)` / `count_queue_gaps()`；**三 gap**（missing_subtitle / missing_audio / missing_transcript）对应 dashboard D7 三缺口组，组序固定、组内 `pubdate DESC, bvid ASC, page_index ASC`。**写模型** = `mark_audio_acquired` / `mark_transcript_stored`（仅本 plan 用）。dashboard plan 的读取层只许依赖此接口，第二份 SQL 不许出现（`specs/queue-cutover-contract.md` §4）
- DD5 ~~无运行时回滚开关~~ **（architect seat 2 修订，见 DD6 取代本条）**：原案 attempt ledger 持续写入即回滚载体（revert merge commit 指回 manifest 读，无数据迁移）。
- DD6 回滚开关（Q2 定稿）= **运行时 flag `--queue-source {store,manifest}`**（默认 `store`，仅 `download-audio` / `asr` / `pilot` / `run` 四个 handler；`schedule` / `campaign` 与已删的 `derive-manifest` 不留开关，批处理链直接切 store）。理由：一次 revert 在代码层已可行，但 flag 让非 git operator 可显式回滚、命令行可审计，且不引入违背 no-migration 的持久状态文件。存在期 = 本 plan merge 至下一迭代 C compound 收口（与 legacy 兼容读删除评估同点）。**注意 DD6 与 §Operator 迁移说明"不引入运行时开关"一句冲突，以 DD6 为准（seat 2 更正迁移说明）**。legacy 兼容读删除触发 = 一个完整 operator 周期内 verify/coverage/publish-transcripts store-first 运行且 manifest fallback 命中为零，下一迭代 C compound 收口评估（owner PM）（`specs/queue-cutover-contract.md` §7）

## Task 分解

SDD 单 plan 六 task，依赖序：T1 → (T2 ∥ T5) → T3 → T4 → T6（T2/T5 写面不相交：cli.py+storage vs services/subtitle_ingest+metadata_ingest）。不拆 sub-plan——六个 task 单链可在两波内闭合。

- **Task 1**: store 队列查询面 —— `MediaQueueRepository`（§4 冻结签名：读模型 `QueueGapItem`+`list_queue_gaps`/`count_queue_gaps`，写模型 `mark_audio_acquired`/`mark_transcript_stored`）+ 三 gap 视图 + schema 增量（CREATE VIEW IF NOT EXISTS，five-hop 不改既有表/列）。**音频证据边界（architect seat 2）**：`audio_objects`/`part_audio_objects` 的首个 writer 是 metadata-audio-layout 的 audio-inventory plan（已 registered、同主机并行）；本 task **不**写这两张表，cutover 音频证据写 `acquisition_attempts(kind='audio')`，"audio evidence" 判据 = 二者之一（fresh 库 attempts-audio 或 part_audio_objects；旧库缺 attempts.kind 列则退化为无-audio 行可 over-select，可接受过渡态，见 spec §10）。Verification: 单测直怼 `MediaQueueRepository`（fresh fixture store 断言三 gap 返回集与排序）+ fake-gateway 驱动 rotation 断言（R1）；Effort M
- **Task 2**: download-audio / asr / pilot 输入切换 + `--queue-source {store,manifest}` flag（DD6）+ `mark_audio_acquired` / `mark_transcript_stored` 回写接线。Verification: fresh-root 端到端（DoD-1 脚本：download → asr → pending 行消失）+ `--queue-source manifest` 回滚冒烟；Effort L——**预先声明的 split point**：若一轮装不下，拆 "下载切换" 与 "ASR 切换+回写" 两半，上半先合
- **Task 3**: coordinator / scheduler / campaign 输入切换 + manifest 降级为 attempt ledger（写不停、读断绝）。Verification: DoD-3（删 manifest 目录重跑行为一致）；Effort M
- **Task 4: derive-manifest 删除 + legacy 兼容读验证（队列决策零依赖 manifest 的代码断言）**。Verification: DoD-2（invalid choice + grep 干净）+ R2 回归形态（queue-cutover-contract §8.2）；Effort S
- **Task 5**: subtitle_ingest outcome 映射修复（D6，credential-validity 区分）+ `processing_status` 收敛。Verification: DoD-4 死凭证 replay fixture（seat 2 精确化——伪造凭证经 listing 走 `-101` → `not_found` 路径，故 D6 的可机读证据 = 空 inventory + 凭证在场时 `no-subtitle` 的 `error_code` 带凭证在场语义，而非另造 `indeterminate_credential`——该词不入 shipped schema 的 attempt CHECK，见 spec §5）；Effort M
- **Task 6**: 文档（metadata-storage.md 边界章节重写 + README 三步链删 derive 步）+ e2e fixture 影响面收尾 + DoD 全量复跑。Verification: 全部 DoD 1–6 复跑证据；Effort M

## Verification

- 每 task：scoped 单测（PYTEST 命令在 SDD task brief 中写明）
- Plan 级 gate：在 fresh root（仅 fetch-meta 过的 store，无 manifest 行）上跑通 `download-audio --bvid` → `asr` → store 回写可见（`v_pending_subtitles` 行数随完成递减）——验收脚本由 Task 2 产出、Task 6 复跑
- 全量测试套件不在本机跑（CI 边界），但 plan 的 SDD reviewer 与 QC 各自跑受影响面

## Definition of Done（可观察结局）

1. 在仅有 archive.db（无 manifest 目录）的 fresh root 上：`download-audio --bvid <part>` → `asr --bvid <part>` 各 exit 0，store 中该 part 的 pending 行从 `v_pending_subtitles` / 音频缺口枚举消失，转写产物路径回写可见（CLI 输出 + store 行双证据）
2. `bili-asr derive-manifest ...` 报 `invalid choice: 'derive-manifest'`（exit 2），`src/bili_asr/services/manifest_derivation.py` 与 `tests/test_cli_derive_manifest.py` 不存在；`grep -rn derive-manifest src/ tests/` 仅剩 docs 迁移说明
3. `run` / `schedule` / `campaign` 在 fresh root 上仍可完成一轮：manifest 目录里出现 attempt ledger 行（写入未断），但删除 manifest 目录后重跑，行为仅表现为"从头开始建 ledger"，队列选择结果与 store 一致（不依赖 manifest 行存在）
4. 死 SESSDATA（伪造凭证）跑 `harvest-subs`：受影响 part 的 attempt 记 `no-subtitle` + `error_code=not_found`（"凭证在场但没看到内容"的可机读信号——spec §5 的最终语义；不新增 `failed` outcome，因 shipped gateway 已将 `-101` 映为 `not_found`），run 记录携带凭证在场标记；operator 用已知正片 re-probe 即可判定凭证死活（R1 的关闭条件）；`v_pending_subtitles` 仍枚举这些 part
5. 现网档案根（本机 ~/archive 或仓库约定根）上 `verify` / `coverage` 的输出与退出码与本 plan 动工前一致（本 plan 不得改变它们的读取面——它们是另一 plan 的修改对象）
6. `status` / `runs` 在 metadata-only root 与 fresh root 上的 exit 语义不变（0/1 两态，无新输出形状依赖）

## Residuals disclosure

关闭 5 条见 Problem Statement 表；本 plan 预计**新产生** 0–2 条 low（legacy 兼容读的删除时间表披露），QC 时登记。

## Open Questions（plan 级）

无——Q2/Q4 已由 architect 定稿（DD3/DD4/DD5 + Task 分解）；Q3 归 dashboard plan。
