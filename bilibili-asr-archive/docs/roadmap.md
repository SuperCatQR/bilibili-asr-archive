# Roadmap — 视频归档整合平台

Status: living document（2026-10-03 初版于分支 `thinking`；2026-10-04 二次修订：平台承诺 + 三轨道并发，已在 `main`）。
上游锚点是 [`design-philosophy.md`](design-philosophy.md)；这里把方向落成阶段。
阶段按**价值解锁**排序，不按数据源排序；每个阶段独立可验证、可交付。

> **与在飞工作的关系（2026-10-04 更新）**：`iter-2026-10-ledger-integrity` 已全部收口
> （四个 plan Done，PR #35 合并）——**Phase 0 完成**。
> 当前在飞的是 `iter-2026-10-asr-success-attestable`，即下文 **Phase 0.5**。

---

## Phase 0 — 事件流可信（已完成，2026-10-03）

**目标**：journal / ledger 作为不可变事件流是可靠的，任何当前状态都可从中重放。
**为什么排第一**：派生图的全部公理（可重放、可重建、幂等）都建立在"事件流是事实"上。
**已交付**：`caption-writeback-guard`（merge `2ad1726`）、`journal-replay-integrity`（merge `1dc720b`）、
`asr-run-id-uniqueness`（merge `4357617`）、`journal-compaction-lifecycle`（merge `ab9683a`/`ec9d3d2`）。
**出口标准达成**：journal 回放不被合法 Unicode 行分隔符截断；compaction 可达且 `save()` 顺序与兄弟方法一致；
ASR run id 唯一（纳秒时钟 + PK 兜底）；write-back 被拒时不再静默。

## Phase 0.5 — 证据层加深（进行中，2026-10-03 起；并发探索的硬前置）

**目标**：让"成功"与"耗尽"成为可证实的断言，而不是默认为真。
**为什么单独成阶段**：现实给出的新数据点——Phase 0 之后，最紧迫的不是加新处理器，
而是**现有成功判定本身不可信**（短解码可冒充成功；未见过的字幕清单可放行进付费分支）。
"事件流是事实"之后，下一步是"**事件流里的结论是事实**"。

**在飞 plan**：
- `caption-exhaustion-attestation`（InProgress）— 让 part 的字幕耗尽可能被证实，
  未见的清单不得放行进付费分支。
- `asr-coverage-attestation`（Todo）— 让 ASR 转录的覆盖可证实，短解码不得读成成功。

**出口标准**：两条 leg 各自的缺陷类被钉住且翻转（回归测试先红后绿）；
取证路径在既有 schema 内可承载（本迭代两次显式升级门：需 schema 改动/迁移即 STOP）。

**cross-cutting 前置（Phase 0.5 收口前必须关闭）**：
- `I-000190`（并发 workflow-close 写入 clobber 活跃 session 的 `status.json` 条目，
  静默暂停该 session）；`I-000207`（peer session 的 stale write 复活已关闭 plan row，
  连带复活其 execution lease）；`I-000195`（`migrate_legacy_rows` 提交 snapshot-only 视图
  后 unlink journal，永久删除 journaled 子状态）。三条同属 snapshot 写入并发缺陷族；
  processor_runs 是所有处理器的公共表，写并发只会更常见——不带病进 Phase 1。
- **editorial-stages 正式裁决（2026-10-04 已裁决：选项 (a)，正式关闭）**：
  `iter-2026-09-transcript-editorial-stages` parked 两周后**关闭，不恢复**为任何后续阶段的输入。
  其分支 ref 已于 2026-09-30 退役；`HANDOFF.md` §2/§3 同日（2026-10-04）降级为**历史记录**
  （以该文件开头的 2026-10-04 标注为准）。关闭是裁决，不是遗忘——**恢复路径保留在文字里**：
  `git fetch origin refs/pull/17/head:refs/heads/<name>` → `55f846c`，约 3 400 行
  editorial 代码的唯一住所（`aa86ea1` 的 tree 与 `55f846c` 逐字节相同）；两个未启动的
  plan 文件只存在于
  `bilibili-asr-archive/docs/archive/deletion-records-20260925/harness-editorial-stages-deleted-20260925.tar.gz`。
  将来若要重做校对/精校，**开新迭代重新论证**，不复活本 track。

## Phase 1 — 处理器注册表 + processor_runs（已承诺，方向=平台）

**目标**：把"ASR 是一个处理器实例"从理念变成骨架。
**关键前提（2026-10-04 补）**：这不是新建平行表，而是**泛化既有形状**——
- `acquisition_runs`（`schema-transcripts.sql:50`）已是 `run_id TEXT PRIMARY KEY` + `kind` +
  `outcome ∈ running/complete/partial/failed` + 起止时间，且 **`kind` 已含 `'asr'`**；
- `asr_models (model_name, revision)` + `transcripts.model_id` 已承载 processor/version 血缘；
- provenance 契约已成熟（`docs/spec-addendum-asr-archive-cli-provenance.md`）。

**范围（刻意收窄）**：

- 把上述 run 形状泛化为 `processor_runs`：`(run_id, processor, version, input_ref, params_hash, code_rev, started/finished, outcome)`
  —— 优先**扩展** `acquisition_runs` 或将其与 `asr_models` 的关系显式化，而非新建平行机制。
- 一个注册表：处理器声明输入类型与 `name@version`。
- ASR 迁入该骨架，作为第一个实例。

**明确不做**：
- 通用派生图引擎、调度器、并发执行（`sequential-no-daemon` 仍然有效）。
- **第二个处理器进入注册表**——即使接口预留了多处理器能力。预留不等于验证；
  N=2 检验属于 Phase 3，必须真实跑通，不是类型层面的"看起来支持"。

**出口标准**：ASR 重跑产生重复行数为零（幂等键生效）；`status` 能报告"哪些 audio 还没被 `asr@vX` 覆盖"。

## Phase 2 — 派生缺口队列（"收集"的声明式实现）

**目标**：`todo` / 缺口不再手写查询，而是从注册表声明自动求差集。
**范围**：给定目标 `(processor@version, 范围)`，系统算出未覆盖的输入集合并驱动执行；
替代当前 `_store_audio_todo` 的硬编码逻辑为通用缺口求值。
**出口标准**：新增一个假想的 `loudness@v1` 处理器，只需注册声明即可跑出全库响度统计，不写新的队列代码。

## Phase 3 — 音频特征层（验证 N=2）

**目标**：第一个非 ASR 处理器落地，证明注册表/缺口队列对多处理器成立。
**候选**：响度/频谱/时长统计（便宜、确定、无模型依赖）。
**出口标准**：全库 audio 的特征 artifact 带完整血缘入库；重算幂等。

## Phase 4 — 终态谓词 + 声明式收敛（"直到符合预期"）

**目标**：把 proofread 的一致率分级泛化成"终态谓词"，系统对不达标输入自动触发新一轮派生分支。
**范围**：谓词定义机制 + 分支追加（旧链保留，查询层指向新链）。
**先例**：`transcripts` 多版本 + `publish-transcripts` 投影；proofread 0.85/0.75 分级。
**出口标准**：对一批 <0.75 的转录，系统能换 `asr@v2`（或新参数）产出新分支并在投影层切换，旧版本不删。
**输入（2026-10-04 修订）**：**不含 editorial-stages 恢复**。该 track 已正式关闭（见 Phase 0.5
cross-cutting 前置），Phase 4 的谓词设计以 `proofread` 的 0.85/0.75 分级与 `transcripts` 多版本
为先例自行展开，不再把它列为预期输入。

## Phase 5 — 画面字节本体（第一类非音频字节）

**目标**：`video_objects` / `frame_objects` 实体 + 抽帧处理器，框架不变。
**范围**：抽帧、场景切分先行；画面 OCR 与 ASR 对齐在其后。
**出口标准**：画面处理器走与音频完全相同的注册表/缺口/血缘路径。

## Phase 6 — 评论 source（有界观察）

**目标**：第一个新数据源，检验 source 抽象的厚度。
**范围**：`comments` / `comment_events` 表 + 采集器；**有界观察**（时间窗/条数封顶）是显式设计决策。
**出口标准**：评论进入同一条派生管线；采集边界可配置、可重放。

## Phase 7 — 派生关系（视频之间）

**目标**：转录相似度 / embedding 近邻作为带版本的处理器产出。
**前提**：Phase 3 的 embedding 类处理器已存在；关系必须标 processor 版本。

---

## 轨道结构（2026-10-04 修订：平台方向下的并发探索）

三条并行轨道，共享一次 Phase 0.5 收口。**探索不等于落地**：

```
                Phase 0.5 (attestable) — 收口前一切并发的硬前置
                        |
        +---------------+---------------+
        |               |               |
   Track A          Track B          Track C
   骨架             内容             数据源
   Phase 1→2       Phase 4→5       Phase 6→7
        |               |               |
        v               v               v
   处理器注册表      终态谓词+画面     评论+关系
   缺口队列          有界观察
```

**硬约束**：Track B/C 的设计文档、schema 草案、采集器原型**可在任意时刻进行**
（不受 Track A 阻塞）；但**落地**（新表、新处理器注册、新 source 接入派生管线）
必须等 Track A 对应阶段就位——否则会产生孤立 schema，骨架就位时被迫重改。

| Track | 阶段 | 落地前置 | 探索（现在就能开始） |
|-------|------|---------|---------------------|
| A 骨架 | Phase 1 → Phase 2 | Phase 0.5 出口 | — |
| B 内容 | Phase 4 → Phase 5 | Phase 1 出口（软依赖，可并行设计） | proofread 谓词泛化设计；画面 schema 草案（editorial-stages 已于 2026-10-04 正式关闭，不再是本轨道的探索项） |
| C 数据源 | Phase 6 → Phase 7 | Phase 1 出口（软依赖） | 评论有界观察边界（时间窗/条数封顶/采集频率）；关系类型清单 |

## 排序逻辑（为什么 Phase 0 → 0.5 → 1 不能跳）

1. **Phase 0 先于一切**：事件流不可信，重放就是空话。（**已完成**）
2. **Phase 0.5 先于一切并发**：`I-000187`/`I-000188` 不修，任何并发探索的结果都不可信——
   不知道一条记录是真成功还是看起来成功。这不是排序偏好，是地基。
3. **Phase 1–2 先于新数据源落地**：注册表和缺口队列是所有后续环节的公共骨架；
   先有骨架，新处理器/新数据源才是"注册一下"而不是"写一条新管线"。
   **探索可以并行，落地必须排队。**
4. **Phase 3 是 N=2 检验**：只有第二个处理器真实跑通，抽象才算成立（哲学 §8）。
5. **Phase 4 是产品灵魂**：声明式收敛是"数据处理 loop"的落地，依赖 1–3 全部。
   （2026-10-04：原文所列的 editorial-stages 恢复入口已随该 track 正式关闭而移除，
   见 Phase 0.5 cross-cutting 前置与 Phase 4 的"输入"行。）
6. **画面/评论/关系放后面**：它们是水平拓展，需要的是已被验证的骨架，不是新骨架。

## 不做事项（本路线图范围内）

- 不做通用图引擎 / 分布式调度（Phase 1–3 用 `sequential-no-daemon` 足够）。
- 不引入重型数据库（SQLite + 对象仓按哲学 §5 继续）。
- 不做评论的全量无限固化（有界观察是决策，不是妥协）。
- 不为了"未来可能用到"提前建画面/评论的空表——处理器出现时表才出现。
- Phase 1 不预留多处理器接口的演示性实现——预留不等于验证，N=2 必须真实发生。
