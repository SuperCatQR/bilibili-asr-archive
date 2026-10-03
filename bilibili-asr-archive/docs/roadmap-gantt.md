# Roadmap 甘特图

配套 [`roadmap.md`](roadmap.md)。时间为**相对估算**（以一人 + agent 计），
日历锚点以实际推进为准；W = 周。轨道结构与落地约束见 [roadmap.md](roadmap.md) §轨道结构。

> **状态快照 2026-10-04**：Phase 0 已全部收口（PR #35 合并，post-merge close 完成）。
> **Phase 0.5**（`iter-2026-10-asr-success-attestable`）为在飞迭代，是所有并发探索的硬前置。
> 三条轨道（骨架/内容/数据源）在 Phase 0.5 出口后并行启动，落地受 Track A 前置约束。

```mermaid
gantt
    dateFormat  YYYY-MM-DD
    axisFormat  %m-%d
    todayMarker stroke-width:3px,stroke:#d33,opacity:0.7

    section Phase 0 事件流可信
    caption-writeback-guard (Done)        :done,   p0a, 2026-10-02, 2d
    journal-replay-integrity (Done)       :done,   p0b, 2026-10-03, 1d
    asr-run-id-uniqueness (Done)          :done,   p0c, 2026-10-03, 1d
    journal-compaction-lifecycle (Done)   :done,   p0d, 2026-10-03, 1d
    Phase 0 出口 — PR #35 merged          :milestone, m0, 2026-10-03, 0d

    section Phase 0.5 证据层 (硬前置)
    I-190/195/207 snapshot并发写入修复    :        p05fix, 2026-10-04, 3d
    editorial-stages 正式裁决             :        p05ed, 2026-10-04, 1d
    caption-exhaustion-attestation        :active, p05a, 2026-10-04, 4d
    asr-coverage-attestation (待放行)     :        p05b, after p05a, 5d
    Phase 0.5 出口 — 成功/耗尽可证实      :milestone, m05, after p05b, 0d

    section Track A 骨架
    processor_runs 表 + 血缘 schema       :        p1a, after m05, 4d
    处理器注册表 (name@version, 输入类型)  :        p1b, after p1a, 3d
    ASR 迁入骨架 (唯一允许的第一个实例)    :        p1c, after p1b, 4d
    Phase 1 出口 — 重跑零重复行           :milestone, m1, after p1c, 0d
    声明式差集求值 (替代 _store_audio_todo) :      p2a, after m1, 5d
    注册即跑通假想 loudness 处理器         :        p2b, after p2a, 3d
    Phase 2 出口 — 不写新队列代码          :milestone, m2, after p2b, 0d

    section Track B 内容 (探索可提前)
    proofread 谓词泛化设计文档             :        p4design, 2026-10-04, 4d
    画面 schema 草案 + 采集边界            :        p5design, 2026-10-04, 3d
    终态谓词定义机制 (泛化 proofread 分级)  :       p4a, after m1, 5d
    派生分支追加 + 投影层切换              :        p4b, after p4a, 5d
    Phase 4 出口 — <0.75 自动出新分支     :milestone, m4, after p4b, 0d
    video_objects / frame_objects 实体    :        p5a, after m4, 4d
    抽帧 + 场景切分处理器                 :        p5b, after p5a, 5d
    画面 OCR 与 ASR 对齐                 :        p5c, after p5b, 6d
    Phase 5 出口 — 与音频同一路径         :milestone, m5, after p5c, 0d

    section Track C 数据源 (探索可提前)
    评论有界观察边界设计                   :        p6design, 2026-10-04, 2d
    关系类型清单 (声明/派生/语料)          :        p7design, 2026-10-04, 1d
    comments / comment_events 表          :        p6a, after m1, 3d
    有界观察采集器 (时间窗/条数封顶)       :        p6b, after p6a, 4d
    Phase 6 出口 — 评论进同一派生管线      :milestone, m6, after p6b, 0d
    转录相似度 / embedding 近邻           :        p7a, after m6, 4d
    关系带 processor 版本入库              :        p7b, after p7a, 5d
    Phase 7 出口 — 关系可随算法重算        :milestone, m7, after p7b, 0d

    section Phase 3 N=2 检验
    响度/频谱/时长统计处理器              :        p3a, after m2, 4d
    全库特征 artifact 带血缘入库           :        p3b, after p3a, 3d
    Phase 3 出口 — 抽象对多处理器成立      :milestone, m3, after p3b, 0d
```

## 读图说明

- **Phase 0 四行是已收口的在飞 plan**（`iter-2026-10-ledger-integrity`，PR #35）：
  `caption-writeback-guard` → `2ad1726`、`journal-replay-integrity` → `1dc720b`、
  `asr-run-id-uniqueness` → `4357617`、`journal-compaction-lifecycle` → `ab9683a`/`ec9d3d2`；
  `m0` 已于 2026-10-03 达成（合并 `53c11a8`，close `ad165aa`）。
- **Phase 0.5 是所有并发探索的硬前置**。除两个 attestation leg 外，
  `I-000190`/`I-000195`/`I-000207`（snapshot 并发写入缺陷族）与 editorial-stages 裁决
  也在本阶段关闭——processor_runs 是公共表，写并发只会更常见。
- **`p4design` / `p5design` / `p6design` / `p7design` 从 2026-10-04 开始**，
  与 Phase 0.5 并行——这些是纯设计/草案工作，不产生 schema 落地，不受 Track A 阻塞。
  这是"并发探索"的准确含义。
- **落地依赖（硬约束）**：
  `p4a`/`p6a` 等所有 Track B/C 落地任务都锚在 `m1`（Phase 1 出口）之后；
  即使设计提前完成，新表/新处理器注册/新 source 接入也必须等骨架就位。
- **Track B/C 之间无硬依赖**——`p6a` 不依赖 `m4`，`p5a` 不依赖 `m6`；
  一人开发时仍建议串行（注意力成本），但结构上允许并行。
- **Phase 3（N=2 检验）独立于 Track B/C**——它在 Track A 之后立即开始，
  验证注册表对第二个处理器的真实承载力，不依赖画面或评论。
- **关键路径**：`p05a→p05b` → `p1a→p1b→p1c` → `p2a→p2b` → `p3a→p3b`。
  Track B/C 的探索并行不在这条路径上；落地并行可以，但每个 Track 的落地仍走自己的链。
- 竖红线为当前日期，落在 Phase 0.5 上，与在飞状态一致。

## 压缩空间

| 手段 | 压缩对象 | 代价 |
|---|---|---|
| Phase 0.5 两条 leg 并行（`asr-coverage-attestation` 与 `caption-exhaustion-attestation` 无代码依赖） | 总时长 ~5d | 两线都动取证路径，须错峰改 `subtitle_ingest`/`asr` 观测面；需操作者放行 D12 |
| Track B/C 探索与 Phase 0.5 全并行 | 设计阶段 ~5d | 已体现在图中；无额外代价 |
| Phase 3 用现成 loudness 库而非自研 | p3a 2d | 血缘字段照记，依赖外部库版本 |
| Track B/C 落地并行（一人多上下文） | m2→m6 总时长 | 注意力切换成本；不建议在一人模式下做 |
