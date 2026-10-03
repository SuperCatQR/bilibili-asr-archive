# Roadmap 甘特图

配套 [`roadmap.md`](roadmap.md)。时间为**相对估算**（以一人 + agent 计），
日历锚点以实际推进为准；W = 周。依赖关系见 [roadmap.md](roadmap.md) §排序逻辑。

```mermaid
gantt
    dateFormat  YYYY-MM-DD
    axisFormat  %m-%d
    todayMarker stroke-width:3px,stroke:#d33,opacity:0.7

    section Phase 0 事件流可信
    caption-writeback-guard (Done)        :done,   p0a, 2026-09-28, 3d
    journal-replay-integrity (Done)       :done,   p0b, 2026-09-30, 3d
    asr-run-id-uniqueness (InProgress)    :active, p0c, 2026-10-01, 6d
    journal-compaction-lifecycle (Todo)   :        p0d, after p0c, 4d
    iter-2026-10 合并 + 收口               :milestone, m0, after p0d, 0d

    section Phase 1 处理器骨架
    processor_runs 表 + 血缘 schema       :        p1a, after m0, 4d
    处理器注册表 (name@version, 输入类型)  :        p1b, after p1a, 3d
    ASR 迁入骨架 (第一个实例)              :        p1c, after p1b, 4d
    Phase 1 出口: 重跑零重复行            :milestone, m1, after p1c, 0d

    section Phase 2 缺口队列
    声明式差集求值 (替代 _store_audio_todo) :      p2a, after m1, 5d
    注册即跑通假想 loudness 处理器         :        p2b, after p2a, 3d
    Phase 2 出口: 不写新队列代码           :milestone, m2, after p2b, 0d

    section Phase 3 音频特征层 (N=2 检验)
    响度/频谱/时长统计处理器              :        p3a, after m2, 4d
    全库特征 artifact 带血缘入库           :        p3b, after p3a, 3d
    Phase 3 出口: 抽象对多处理器成立       :milestone, m3, after p3b, 0d

    section Phase 4 谓词收敛
    终态谓词定义机制 (泛化 proofread 分级)  :       p4a, after m3, 5d
    派生分支追加 + 投影层切换              :        p4b, after p4a, 5d
    Phase 4 出口: <0.75 转录自动出新分支   :milestone, m4, after p4b, 0d

    section Phase 5 画面字节本体
    video_objects / frame_objects 实体    :        p5a, after m4, 4d
    抽帧 + 场景切分处理器                 :        p5b, after p5a, 5d
    画面 OCR 与 ASR 对齐                 :        p5c, after p5b, 6d
    Phase 5 出口: 与音频同一路径          :milestone, m5, after p5c, 0d

    section Phase 6 评论 source
    comments / comment_events 表          :        p6a, after m5, 3d
    有界观察采集器 (时间窗/条数封顶)       :        p6b, after p6a, 4d
    Phase 6 出口: 评论进同一派生管线       :milestone, m6, after p6b, 0d

    section Phase 7 派生关系
    转录相似度处理器                      :        p7a, after m6, 4d
    embedding 近邻关系 (带 processor 版本) :        p7b, after p7a, 5d
    Phase 7 出口: 关系可随算法重算         :milestone, m7, after p7b, 0d
```

## 读图说明

- **Phase 0 的四行是真实在飞 plan**，与 `iter-2026-10-ledger-integrity` 一一对应；
  其日期按实际进度估，`asr-run-id-uniqueness` 为当前激活项。
- **Phase 1–7 全部锚在 `m0`（迭代合并）之后顺延**，不是日历承诺——
  它们是相对工期，合并越早开始得越早。
- **关键路径**：`p1a→p1b→p1c`（骨架三连）是后续一切的总前置，任何压缩都从这里入手。
- **Phase 5/6/7 之间无硬依赖**，骨架就绪后三者可按兴趣重排或并行（一人开发时仍建议串行）。
- 竖红线为当前日期（2026-10-03），落在 `asr-run-id-uniqueness` 上，与在飞状态一致。

## 压缩空间

| 手段 | 压缩对象 | 代价 |
|---|---|---|
| Phase 1 与 Phase 0 的 `journal-compaction-lifecycle` 并行 | 总时长 ~4d | 两线都动 store schema，需错峰迁移 |
| Phase 3 用现成 loudness 库而非自研 | p3a 2d | 血缘字段照记，依赖外部库版本 |
| Phase 5/6 对调 | 不改变总长 | 取决于画面与评论哪个更急迫（产品判断） |
