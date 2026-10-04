# Roadmap 甘特图 — 多轨道视图

配套 [`roadmap.md`](roadmap.md)。本页有两个视图，**同一份数据**：

| 视图 | 位置 | 用途 |
|---|---|---|
| 交互式（多轨道） | [`roadmap-gantt.html`](roadmap-gantt.html) | 五条泳道、里程碑菱形、跨泳道硬门禁、缩放/聚焦/打印 |
| 文本台账 | 本页下方 | 可 diff、可 grep、可评审 |

两个视图都由 `scripts/build_roadmap_gantt.py` 的 `_ROADMAP` 数据模型渲染，
`python3 scripts/build_roadmap_gantt.py --check` 会在数据与产物不一致时退出 1。
**不要手改 HTML**：改数据模型后重新生成，否则两者会漂移——这正是上一版
（Mermaid `section` 版）的失效模式：图与正文各写各的。

## 为什么不再用 Mermaid `gantt`

Mermaid 的 `section` 是**视觉分带**，不是泳道：它没有依赖链、没有跨轨道门禁、
一条泳道只能有一个里程碑。用它画这份路线图会强制产生两个错误印象——
（a）Phase 1–7 是顺序瀑布，而实际上三条轨道在 Phase 0.5 出口后**并行**；
（b）"落地受 Track A 约束"这条硬规则无处可画。

现在这张图把这三点画成事实：

- **五条泳道**各自独立：Phase 0.5 证据层（硬前置）、Track A 骨架、Track B 内容、
  Track C 数据源、N=2 检验。
- **菱形 = 泳道出口里程碑**，达成日由依赖链**推导**而非写死；同泳道里程碑按时间自上而下排列。
- **橙色虚线 = 跨泳道硬门禁**，从 `after` 边**自动推导**——图不可能与依赖数据不符。

## 任务台账

<!-- BEGIN GENERATED: build_roadmap_gantt.py --table -->
| id | 名称 | 泳道 | 起 | 天 | 状态 | 备注 |
|---|---|---|---|---|---|---|
| `p05ed` | editorial-stages 裁决 | Phase 0.5 — 证据层 | 2026-10-04 | 2 | 已完成 | 2026-10-04 裁决 = 正式 close（不恢复）；HANDOFF §2/§3 降为历史记录 |
| `p05fix` | snapshot 写并发缺陷族 | Phase 0.5 — 证据层 | 2026-10-04 | 4 | 进行中 | I-000190 / I-000195 / I-000207 |
| `p4design` | proofread 谓词泛化设计 | Track B — 内容 | 2026-10-04 | 4 | 可开始 | 纯设计，不产生 schema，不受骨架阻塞 |
| `p5design` | 画面 schema 草案 | Track B — 内容 | 2026-10-04 | 3 | 可开始 | 纯设计 |
| `p6design` | 评论有界观察边界设计 | Track C — 数据源 | 2026-10-04 | 2 | 可开始 | 时间窗 / 条数封顶 / 采集频率 |
| `p7design` | 关系类型清单 | Track C — 数据源 | 2026-10-04 | 1 | 可开始 | 声明 / 派生 / 语料 |
| `p05a` | caption-exhaustion-attestation | Phase 0.5 — 证据层 | 2026-10-08 | 4 | 进行中 | 已合并 ff11351 · PR #212；此行保留取证轨迹 |
| `p05b` | asr-coverage-attestation | Phase 0.5 — 证据层 | 2026-10-12 | 5 | 被阻塞 | I-000188 · 待操作者放行（D12 / I-000201） |
| `m-gate`◆ | 成功与耗尽可证实 | Phase 0.5 — 证据层 | 2026-10-17 | — | 被阻塞 | |
| `p1a` | processor_runs + 血缘 schema | Track A — 骨架 | 2026-10-17 | 4 | 被阻塞 | 扩展 acquisition_runs，不建平行表 |
| `p1b` | 处理器注册表 name@version | Track A — 骨架 | 2026-10-21 | 3 | 被阻塞 | |
| `p1c` | ASR 迁入骨架（第一个实例） | Track A — 骨架 | 2026-10-24 | 4 | 被阻塞 | |
| `m-p1`◆ | Phase 1 出口：重跑零重复行 | Track A — 骨架 | 2026-10-28 | — | 被阻塞 | |
| `p2a` | 声明式差集求值 | Track A — 骨架 | 2026-10-28 | 5 | 被阻塞 | 替代 _store_audio_todo 硬编码 |
| `p4a` | 终态谓词定义机制 | Track B — 内容 | 2026-10-28 | 5 | 被阻塞 | |
| `p6a` | comments / comment_events 表 | Track C — 数据源 | 2026-10-28 | 3 | 被阻塞 | |
| `p6b` | 有界观察采集器 | Track C — 数据源 | 2026-10-31 | 4 | 被阻塞 | |
| `p2b` | 注册即跑通假想 loudness | Track A — 骨架 | 2026-11-02 | 3 | 被阻塞 | |
| `p4b` | 派生分支追加 + 投影层切换 | Track B — 内容 | 2026-11-02 | 5 | 被阻塞 | |
| `m-p6`◆ | 评论进入同一派生管线 | Track C — 数据源 | 2026-11-04 | — | 被阻塞 | |
| `p7a` | 转录相似度 / embedding 近邻 | Track C — 数据源 | 2026-11-04 | 4 | 被阻塞 | |
| `m-p2`◆ | Phase 2 出口：不写新队列代码 | Track A — 骨架 | 2026-11-05 | — | 被阻塞 | |
| `p3a` | 响度 / 频谱 / 时长统计处理器 | N=2 检验 | 2026-11-05 | 4 | 被阻塞 | 现成库优先，血缘字段照记 |
| `m-p4`◆ | Phase 4 出口：<0.75 自动出新分支 | Track B — 内容 | 2026-11-07 | — | 被阻塞 | |
| `p5a` | video_objects / frame_objects | Track B — 内容 | 2026-11-07 | 4 | 被阻塞 | |
| `p7b` | 关系带 processor 版本入库 | Track C — 数据源 | 2026-11-08 | 5 | 被阻塞 | |
| `p3b` | 全库特征 artifact 带血缘入库 | N=2 检验 | 2026-11-09 | 3 | 被阻塞 | |
| `p5b` | 抽帧 + 场景切分处理器 | Track B — 内容 | 2026-11-11 | 5 | 被阻塞 | |
| `m-p3`◆ | 抽象对多处理器成立 | N=2 检验 | 2026-11-12 | — | 被阻塞 | |
| `m-p7`◆ | 关系可随算法重算 | Track C — 数据源 | 2026-11-13 | — | 被阻塞 | |
| `p5c` | 画面 OCR 与 ASR 对齐 | Track B — 内容 | 2026-11-16 | 6 | 被阻塞 | |
| `m-p5`◆ | 画面与音频同一路径 | Track B — 内容 | 2026-11-22 | — | 被阻塞 | |
<!-- END GENERATED -->

## 跨泳道硬门禁

| 源 | 目标 | 跨泳道 |
|---|---|---|
| `m-gate` | `p1a` | Phase 0.5 → Track A |
| `m-p1` | `p4a` | Track A → Track B |
| `m-p1` | `p6a` | Track A → Track C |
| `m-p2` | `p3a` | Track A → N=2 检验 |
| `m-p4` | `p5a` | Track B 内部阶段 |
| `m-p6` | `p7a` | Track C 内部阶段 |

## 读图说明

- **Phase 0.5 是所有并发的硬前置。** 除两条 attestation leg 外，
  `I-000190`/`I-000195`/`I-000207`（snapshot 写并发缺陷族）也在本阶段关闭——
  `processor_runs` 是公共表，写并发只会更常见。
  `p05ed`（editorial-stages 裁决）已于 2026-10-04 **完成**：裁决为正式 close、不恢复；
  `HANDOFF.md` §2/§3 降为历史记录（见 `roadmap.md` Phase 0.5 cross-cutting 前置）。
- **Track B/C 现在就能开始的是设计，不是落地。**
  `p4design`/`p5design`/`p6design`/`p7design` 不产生 schema、不接派生管线，
  因此写在 2026-10-04（与门禁同日）且不连任何门禁线。
  这是"并发探索"的准确含义：**探索可以并行，落地必须排队。**
- **落地依赖（硬约束）**：所有 Track B/C 落地任务锚在 `m-p1` 之后；
  即使设计提前完成，新表/新处理器注册/新 source 接入也必须等骨架就位，
  否则会产生孤立 schema，骨架就位时被迫重改。
- **Track B/C 之间无硬依赖**——`p6a` 不依赖 `m-p4`，`p5a` 不依赖 `m-p6`；
  一人推进时仍建议串行（注意力切换成本），但结构上允许并行。
- **N=2 检验独立于 Track B/C**——它在 Track A 之后立即开始（`m-p2` → `p3a`），
  验证注册表对第二个处理器的真实承载力，不依赖画面或评论。
- **关键路径**：`m-gate → p1a → p1b → p1c → m-p1 → p2a → p2b → m-p2 → p3a → p3b → m-p3`，
  末端 2026-11-12（图中底部红线）。Track B/C 的探索并行不在这条路径上。

## 工期口径

天数是**相对估算**，锚点 `2026-10-04`，按"一人 + agent"计。日历值会随实际推进漂移；
可靠的是**依赖结构与门禁关系**，那部分是数据模型推导出来的，不是估出来的。
估算刻意留松：本仓已实测过 agent 工作会打乱直觉上的大小排序，
看起来有余量的计划通常没有。

## 压缩空间

| 手段 | 压缩对象 | 代价 |
|---|---|---|
| Phase 0.5 两条 leg 并行（`p05a` 与 `p05b` 无代码依赖） | 总时长 ~5 天 | 两线都动取证路径，须错峰改 `subtitle_ingest`/`asr` 观测面；需操作者放行 D12 |
| Track B/C 探索与 Phase 0.5 全并行 | 设计阶段 ~4 天 | 已体现在图中；无额外代价 |
| N=2 用现成 loudness 库而非自研 | `p3a` 约 2 天 | 血缘字段照记，依赖外部库版本 |
| Track B/C 落地并行（一人多上下文） | `m-p2`→`m-p7` 总时长 | 注意力切换成本；不建议在一人模式下做 |
| ~~`p05ed`（editorial 裁决）与 `p05fix` 并行~~ | — | **已完成 2026-10-04**（正式 close、不恢复）；压缩手段本身不再适用 |

## 重新生成

```bash
python3 scripts/build_roadmap_gantt.py              # 写 docs/roadmap-gantt.html
python3 scripts/build_roadmap_gantt.py --check      # 数据与产物不一致时退出 1
python3 scripts/build_roadmap_gantt.py --table      # 打印上面的任务台账
```
