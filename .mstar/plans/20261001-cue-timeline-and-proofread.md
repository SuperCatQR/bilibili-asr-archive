---
plan_id: 20261001-cue-timeline-and-proofread
project: _default
primary_spec: .mstar/specs/asr-archive-cli.md
status: draft
created_at: 2026-10-01
execution_mode: sdd
plan_parallelism: serial
enforcement: soft
main_worktree_branch: main
qa_gate: mandatory
qa_mode: targeted
blocked_by: ["R10 (cli import integrity) — A 的重跑需要 `bili-asr asr` 可执行"]
---

# 时间轴精细化 + 校对环节重构（A + D + C）

> 来源：operator 2026-10-01 直接请求。起因是 E2E round 2 产出四稿后发现**本地 ASR 的时间轴质量差**，
> 经代码追查确认「不是没有强对齐，而是强对齐的产物被合并规则糊掉了」。operator 已定：
> 校准目标**对齐字幕**、**句子通顺优先**、D 落点**扩展 `bundle.raw.json`**、**接受重跑一次 GPU**、
> **已发布产物不改**。

## Problem Statement

三条独立但相互纠缠的缺陷，合并成一个 plan 处理（分开做会互相返工）：

**P1 — 时间轴粒度被合并规则毁掉（产品缺陷，A）。**
`Qwen3-ForcedAligner-0.6B` 返回的是**逐字符**时间戳（`asr.py:10-12` 的模块 docstring 自述
"per-character `{text, start_time, end_time}`"），精度是够的。但 `_aligned_cues`
（`asr.py:763`）把逐字符单元按**字幕可读性规则**合并：

```python
_SENTENCE_ENDINGS   = "。！？!?"      # 只认这四类
_CUE_MAX_CHARS      = 60              # 对中文口语太宽
_CUE_MAX_GAP_SECONDS = 1.0            # 唯一实际生效的断点
_CUE_MIN_CHARS      = 6
_CUE_MIN_SECONDS    = 1.0             # 不足者并入前一条，只撑大 end
```

该 docstring 承认这是 **FunASR 时代的规则原样搬运**："The rules were measured on this corpus and
are product decisions, so only their input changed."

**实测基线**（route2 四稿，2143 cues）：

| 指标 | 本地 ASR（现） | AI 字幕（目标） |
|---|---|---|
| 中位时长 | **5.20 s** | 2.20 s |
| 中位字数 | **25** | 10 |
| 最长 cue | **487 字** | 25 字 |
| **句末标点收尾率** | **39%** | — |

全文有 **5909 个**标点，但规则只用了**句末类的 831 个**——`，、；：` 共 5078 个被忽略。
"句子不通顺"的机制就在这里：一个 cue 常常在逗号中间断掉或跨过多句。

**P2 — 逐字符时间戳被丢弃（架构缺陷，D）。**
`bundle.raw.json` 只存 cue 级 `{start,end,text}`（已实测确认：顶层 keys = `provenance`/`segments`/`source`）。
后果：**任何 cue 规则的调整都必须重跑 GPU**（实测 37 分钟/四稿）。若留存字符级，调规则是纯 CPU
重切（毫秒级）。本次 operator 接受重跑一次，但**只这一次**——D 就是为了让它成为最后一次。

**P3 — `proofread` 会静默产出假校对（产品缺陷，C）。**
两个缺陷，均已实测复现：

1. **`source` 不校验**：`read_asr_route_ms`（`proofread.py:466-480`）只检查文件存在与可解析，
   **不检查 `source` 字段**。于是在只有字幕产物的 root 上，它会把 `source=subtitle-ai` 派生的
   `bundle.raw.json` 当作 ASR 路使用，产出**全部 `agree 1.000`** 的并排表（实测 64 blocks 全 1.000）。
   那是自己跟自己比，一个需要裁决的地方都没有——**假校对**，且不报错。
2. ~~**两路必须同 root**~~ → **【2026-10-01 更正：此条是错的，PM 写的，勿照此实现】**
   原文写「ASR 路从 `artifact_root` 取，字幕路从 `archive_root/archive.db` 取，所以两路必须同 root」。
   **事实：改动前两路本来就各取一个独立的 CLI 参数**（`--artifact-root` 与 `--archive-root`），
   分离形态一直可达：`--archive-root <字幕 root> --artifact-root <ASR root>`（L2 审查者在改前模块上
   实证渲染真实两 root 对 → 52 blocks、**0 个 1.000**）。所以真正的缺口**不是"必须同 root"**，
   而是「**要移动一个读 root 就必须同时移动写基**」——新参数 `--asr-root` / `--caption-root`
   提供的正是"读 root 与写基解耦"这一较窄的能力。
   本条错误已传入实现者报告并被沿用，由 L2 审查抓出，见 `lane-2-report.md` 的 PM 验证节。

## 决策（operator 2026-10-01，不再是实现者的自由选择）

| # | 决策 | 结论 | 依据 |
|---|---|---|---|
| **D-1** | D 的落点 | **扩展 `bundle.raw.json`**，不写 `transcript_segments` | `transcript_segments`（`start_ms/end_ms` INTEGER）本可容纳字符级，但那条路是 `20260929-asr-local-transcript-storage`（`status: registered`）的地盘——它正要用 `asr-local` 打开写入路径。两 plan 争同一块地会互相返工。D 的目的是"转写产物完整性"，属 `raw.json` 职责；等那个 plan 落地后若需字符级，从 raw 读即可 |
| **D-2** | 已发布产物 | **不改** | 四稿现存产物是 E2E 证据的一部分（sha256 已记入 `reports/e2e.md`）。A 落地后**新建**产物，旧的不动 |
| **D-3** | 重跑授权 | **接受一次** | A 必须重跑才能验证新时间轴。但**仅此一次**——D 落地后调规则免 GPU |
| **D-4** | 校准目标 | **对齐字幕 + 句子通顺优先** | operator 原话。量化为：中位时长 2.0–3.5 s、中位字数 10–16、句末收尾率 ≥ 70%。**句子通顺优先于数值贴合**——若两者冲突，取通顺 |
| **D-5** | 字符级存储形态 | **并行数组**（`starts`/`ends` + 整串 `text`） | 决定正确，但**本行原先的体积数字是错的，2026-10-01 实测后更正**：原写"对象数组 8x / 并行数组 2.8x"，实测**并行数组在真实产物上是 6.4–7.6x（均值 6.95x）**。原因见下 |

### D-5 更正：2.8x 是在错误的量级上估的（2026-10-01 实测）

原估算只算了**数组本身的推测体积**，没算两件事，而它们在真实产物上占主导：

1. **写入器用 `indent=2`**（`archive.py:631`）——每个数字独占一行，固定 **8 字节/数字** 的缩进开销。
   字符级数组有 ~5 万个数字，仅缩进就 ~400 KB。
2. **时间戳本身带浮点噪声**：真实已发布的 `segments` 里，**79% 的时间戳带 ≥7 位小数**
   （实测分布：13 位占 57%、7 位占 20%、14 位占 3%；样本 `184.38206250000002`）。
   且这**不是** `characters` 引入的——`segments` 本来就有，因为 chunk offset 是
   `boundary_samples/16000.0`（`asr.py:712`），天然产生长小数。
   `characters` 的作用是把这类数字的数量从 ~1.5k 放大到 ~50k，于是效应才显出来。

**区间（BV1BdtazGEBE 上逐项实算，2026-10-01）**：基线 156 750 B。

| 序列化 | 倍数 | 增量 |
|---|---|---|
| 现状（`indent=2`，原精度） | **8.55x** | +1.13 MB |
| `indent=2` + round 到 2 位 | 6.28x | +0.79 MB |
| 紧凑 + 原精度 | 5.91x | +0.73 MB |
| 紧凑 + round 到 2 位 | 3.64x | +0.39 MB |

即**诚实区间是 3.6x ～ 8.6x，现状态是 8.55x**（Lane 1 报告曾写 6.67x，那是"3 位小数"下的值，
而写入器不做 round；L2 审查 F1 指出后已更正）。

**为什么仍然接受**：D 的目的是用磁盘换掉 GPU 时间。四稿合计多 ~3–5 MB，相对同批产物 93 MB 的音频
可忽略，而换到的是"调 cue 规则免 37 分钟重跑"。**且这是上限**——真机重跑后若嫌大，
round 到 2 位即可降到 6.28x，不会动已发布产物（旧产物已是原状，新产物从下一稿起用新规则，
但那是格式变更，须单独变更并升 schema，D-2 仍然成立）。若将来确有字节预算，杠杆按收益排序：
(a) `raw_path` 改紧凑序列化——**但该行与已发布产物共享**，改动会让旧产物字节全变，与 D-2 冲突，
须单独变更并升 schema；(b) 时间戳 round 到 2 位（实测 6.85x → 4.80x），**同样影响已发布产物字节**。
两者都**不在本 plan 范围**，登记为残余。

## 现状精确坐标（已实测，非推断）

| 位置 | 事实 |
|---|---|
> 行号于 2026-10-01 逐条 `sed` 核验；本 plan 的可信度依赖它们，实现前若漂移请先校正再动手。

| 位置 | 事实 |
|---|---|
| `src/bili_asr/asr.py:74-79` | `_SENTENCE_ENDINGS`（74）+ 五个 `_CUE_*` 常量（75-79） |
| `src/bili_asr/asr.py:763-845` | `_aligned_cues()`：状态机（下一个 `# ---` 区隔在 847）。`close()` 内的"不足则并入前一条"是巨型 cue 的直接成因 |
| `src/bili_asr/asr.py:718-760` | `_thread_text()`：把标点缝回字符流。**这是字符级信息的最后一个持有者** |
| `src/bili_asr/asr.py:1110-1111` | 调用点：`pieces.extend(_thread_text(...))`（1110）→ `return _aligned_cues(pieces)`（1111）。**D 要在这里留存** |
| `src/bili_asr/asr.py:1029-1045` | `_align_chunk()`：`decode_forced_alignment` 返回逐单元 `{text,start_time,end_time}` |
| `src/bili_asr/archive.py` / `writer_*.py` | `write_archive` 落 `bundle.raw.json`——D 要在此处写入新字段（实现时先定位确切函数） |
| `src/bili_asr/proofread.py:466-497` | `read_asr_route_ms()`：**不校验 source**（C-1 缺陷） |
| `src/bili_asr/proofread.py:499-585` | `read_subtitle_route_ms()`：从 `archive_root/archive.db` 读 caption 行 |
| `src/bili_asr/proofread.py:587-622` | `build_sidebyside()`：两路 + work_dir 都从 `artifact_root` 派生 |

**被 pin 住的规则**（改 A 必须同步处理）：`tests/test_asr_qwen.py`（10 处引用）、
`tests/test_archive_md.py`（3 处）、`tests/test_quality.py`（1 处）。

## Interfaces

**D — `bundle.raw.json` 新增字段**（向后兼容：旧产物无此字段，读取方必须容忍缺失）：

```json
{
  "schema": "archive-raw-v2",
  "source": "asr",
  "segments": [ {"start": 0.32, "end": 5.76, "text": "..."}, ... ],
  "characters": {
    "text": "<与 segments 拼接逐字相同>",
    "starts": [0.32, 0.40, ...],
    "ends":   [0.40, 0.48, ...]
  }
}
```

- `characters.text` **必须**等于 `"".join(s["text"] for s in segments)`——这是可断言的完整性条件
- 三个数组等长；`starts[i] <= ends[i]`；单调不减
- 字幕派生的 raw（`source=subtitle-ai`）**不产出** `characters`（那些产物没有字符级信息，伪造等于撒谎）

**C — `proofread` 的两个新行为**：
- `read_asr_route_ms` 必须拒绝 `source != "asr"` 的 raw，错误信息点名实际 source
- 新增 `--asr-root` / `--caption-root` 可选参数，未给时回落到现行为（同 root）。给出时两路各自解析

**A — 规则常量**（实现时调参，但语义固定）：
- 断句标点从 `_SENTENCE_ENDINGS`（4 类）扩展到含次级标点，但**次级标点只在 cue 已达可读长度时才断**
- `_CUE_MAX_CHARS` 显著下调
- `_CUE_MAX_GAP_SECONDS` 下调
- `_CUE_MIN_*` 的"并入前一条"逻辑保留（它防的是碎片），但**不得**让 cue 超过新的上限

## Naming decisions

> 本表由 PM 维护；实现者不得直接改本表（并行 track 时尤其）。命名一律经 `naming-analyzer`。

| 概念 | 选定名 | 依据 |
|---|---|---|
| 字符级容器 | **`characters`** | 与 `segments` 并列、同为复数名词，读者一眼知道是"更细的一层"；不用 `chars`（缩写）、不用 `alignment`（那只描述来源不描述内容） |
| 时间戳数组 | **`starts` / `ends`** | 与既有 `segments[].start/end` 同词，避免 `start_ms` vs `start` 的单位混淆（这里沿用秒，与 segments 一致） |
| schema 标识 | **`archive-raw-v2`** | 既有 `.bundle-ready` 用 `archive-bundle-v1` 先例，同族命名 |
| 跨 root 参数 | **`--asr-root` / `--caption-root`** | 按"内容来源"命名而非 `--route1/--route2`（后者是 E2E 内部术语，见 20261001 分享目录命名决策）；与 `--archive-root`/`--artifact-root` 的 `-root` 后缀一致 |
| 重切器（若实现） | **`retile_cues`** | 动宾结构，描述"重新切 tiles"；不用 `reflow`（暗示文本重排）、不用 `reprocess`（太泛） |

## 约束

**不得**：
- 改动 `transcript_segments` 表结构或 `ALLOWED_CAPTION_SOURCE_KINDS`（留给 `20260929-asr-local-transcript-storage`）
- 修改已发布的四稿产物（D-2）
- 为字幕派生的 raw 伪造 `characters` 字段
- 放宽 `_text` / `storage/models.py` 的接受规则
- 让 `characters` 缺失成为**读取方的硬错误**——旧产物必须仍可读（向后兼容是硬要求）
- 在 A 里顺手改本文档未列的其他规则

**必须**：
- A 落地前，先在**真实音频**上做 A/B 对比测量（不能只看单条稿件的单条 cue）
- 每个数值目标都从**实测**得出，不引用本 plan 的数字作为自有验证
- 若"句子通顺"与"数值贴合"冲突，**取通顺**并在交付说明里写明牺牲了哪个数值

## Verification mode

**RED 基线**（实现前必须能复现）：
1. `yaml` 实测：现产物 `句末收尾率 = 39%`、`最长 cue = 487 字`（脚本见 `## 复现`）
2. `proofread` 对只有字幕的 root → 产出全 `agree 1.000` 的并排表（假校对）
3. `proofread` 对只有 ASR 的 root → `missing caption route` 拒绝
4. `raw.json` 无 `characters` 字段

**GREEN 目标**：
- 新产物 `句末收尾率 ≥ 70%`、`最长 cue ≤ 上限`、`中位时长 2.0–3.5 s`
- `proofread` 对错 root 报**点名 source 的错误**，不再静默通过
- `proofread` 用 `--asr-root`/`--caption-root` 能在分离的两个 root 上跑通
- `characters.text == "".join(segments[].text)` 在四稿上逐字成立

## Tasks

### Task 1 — D：`bundle.raw.json` 留存字符级时间戳

**Files:** `src/bili_asr/asr.py`（`_thread_text` 返回或旁路出字符级）、`src/bili_asr/archive.py` 或
对应 writer（写入 `characters`）、`src/bili_asr/storage/models.py`（若需 schema 常量）、
新增 `tests/test_raw_characters.py`

**要求：**
1. `_thread_text` 已是字符级信息的最后持有者（`:718-760`）。让它把 pieces **同时**交给两处：
   现有 `_aligned_cues`（行为不变）与一个新的字符级抽取器。**不得**改变 `_aligned_cues` 的行为。
2. 写入 `characters`：`text` / `starts` / `ends`，秒为单位与 `segments` 一致。
3. **完整性断言**（必须实现，不是测试里才有）：`characters.text == "".join(s["text"] for s in segments)`，
   不等则拒绝写出并报错。
4. `source != "asr"` 的产物**不写** `characters`。
5. 向后兼容：读取方（`proofread`、`coverage` 等）遇到无 `characters` 的旧产物必须仍能工作。
6. 测试：小片段构造 + 完整四稿的字段一致性；含"字幕派生 raw 无 characters"的负对照。

**Task budget:** 2

### Task 2 — A：cue 切分规则校准到字幕粒度

**Files:** `src/bili_asr/asr.py`（常量 + `_aligned_cues`）、`tests/test_asr_qwen.py`、
`tests/test_archive_md.py`、`tests/test_quality.py`

**要求：**
1. 调整常量与断句语义，目标按 D-4。**次级标点只在 cue 已达可读长度时断**——否则会把
   "呃，那个，" 切成一堆碎片。
2. `close()` 的"不足则并入前一条"逻辑保留，但**新增约束：并入后不得突破新的上限**。
   若会突破，则改为独立成 cue（宁可多一条短 cue，也不要一条巨型 cue）。
3. 用 `characters`（Task 1 的产物）做**纯 CPU 重切验证** —— 这条同时验证 D 的价值。
4. 三个测试文件的既有断言按新规则更新；**每个被改的断言都要在报告里说明改了什么、为什么**。
5. 报告必须含**四稿的前后对比表**（中位时长/中位字数/最长 cue/句末收尾率），数字来自实测。

**Task budget:** 2

### Task 3 — C：`proofread` 的 source 校验 + 跨 root

**Files:** `src/bili_asr/proofread.py`、`src/bili_asr/cli/publish.py`（新增参数）、
`src/bili_asr/cli/parser.py`、新增 `tests/test_proofread_routes.py`

**要求：**
1. `read_asr_route_ms` 校验 `source == "asr"`，否则 `ProofreadRouteError` 且**错误信息点名实际 source**。
2. `--asr-root` / `--caption-root` 可选参数；未给时行为与现在**逐字不变**（回归保护）。
   **参数名已按 `## Naming decisions` 定下**，且其真实作用是「读 root 与写基解耦」，
   不是「让原本必须同 root 的两路能分开」（见上方 Problem Statement P3.2 的更正）。
3. 负对照测试：对字幕派生的 raw 必须**报错**（RED 基线第 2 条），这是本 task 的核心防回归。
4. **传默认值不算测行为**（L2 审查在 Task 3 上实测到的坑，Task 2 同类风险）：
   若新增参数在每个调用点传的都是它已有的默认值，那么"忽略该参数"的实现能通过全部测试。
   **每个新参数至少要有一个"取值 ≠ 默认值"的用例**，否则用突变实验（把参数换成常量）自查。
5. CLI 层与新库层各需一个行为用例：库层测 `build_sidebyside`，CLI 层测 argparse 转发
   （实测：删掉 `publish.py` 里的转发 kwargs 后，仅库层测试仍全绿）。
4. 分离 root 的正例测试：用两个 root 跑通并排表。

**Task budget:** 2

### Task 4 — 真机重跑与验证（D-3 授权的那一次）

**Files:** 目标机操作，无产品代码改动；报告写 `{SDD_DIR}`

**要求：**
1. 前置：**`bili-asr asr` 必须已可用**（R10）。若 R10 未落地，本 task `blocked`，**不得**用
   build 内 hot-fix 冒充（那是 E2E 的一次性手段，不是本 plan 的交付方式）。
2. 传输新构建到目标机；**新建**产物根（不覆盖 route1/route2，D-2）。
3. 重跑四稿 GPU。
4. 记录：前后对比表、GPU 时长、`characters` 字段的实际大小增长、`proofread` 在真实两路数据上的
   并排表**至少抽 5 个 block 人工检视**（数值达标但句子不通顺，就是没达标）。
5. 与 `20260929-asr-local-transcript-storage` 的边界：**不碰** `transcripts` 表写入。

**Task budget:** 3

### Task 5 — 收口：文档、register、残余登记

**Files:** `bilibili-asr-archive/README.md`（cue 规则与 `characters` 字段）、`{PLAN_DIR}` 本 plan 的
`## Naming decisions` 回填、`{PROJECT_DIR}/_default/residuals.json`

**要求：**
1. README 更新：cue 规则变了、（若实现）`characters` 字段的存在与兼容语义。
2. 如实登记本 plan 产生的残余（若 A 为了通顺牺牲了某个数值目标，**必须**登记为残余并写明）。
3. 若发现 `proofread` 还有其他同类"静默通过"路径，登记为 residual 而非顺手改。

**Task budget:** 1

## 执行状态（PM 2026-10-01 回填，不改变任何任务文本）

本 plan 的 Tasks 无 checkbox 语法，此前无法从文件读出进度。以下为**核实后**的状态：

| Task | 状态 | 证据 |
|---|---|---|
| Task 1 — `characters` 字段 | **DONE** | `08b26ae`（lane-1-report.md；`tests/test_raw_characters.py` 存在；`archive.py` 21 处 `characters`） |
| Task 2 — cue 切分规则校准到字幕粒度 | **DONE** | `asr.py` 16 处 `_CUE_*`；随 lane-1/lane-2 合并进入 `main` |
| Task 3 — `proofread` 的 source 校验 + 跨 root | **DONE** | `1de131a`（lane-2-report.md） |
| Task 4 — **真机重跑与验证** | **NOT DELIVERED** | `{SDD_DIR}` 内无 task-4 报告、无真机记录、无前后对比表。其前置（R10）**现已满足**，所以它没做不是 blocked，而是未执行 |
| Task 5 — 收口：文档、register、残余登记 | **部分** | README 已含 `characters`/cue（1 处 / 20 处）；`## Naming decisions` 已回填；残余已登记 `C-R1`~`C-R4`。**但 Task 4 未做意味着 Task 5 的"真机验证结论"也不存在** |

**结论：本 plan 的代码工作已完成并全部在 `main`，但 Task 4 的验证从未执行。**
因此它的收口状态记为 **Done（代码）／ Task 4 转交** 而不是完整 Done ——
把未验证的 plan 标成完整 Done 正是本仓一直在清除的"声明宽于证据"缺陷。

**Task 4 的转交去向：** 它是"真机重跑四稿 GPU + `proofread` 至少抽 5 个 block 人工检视"，
与 `20260929-asr-local-transcript-storage` 的真机验证是同一次目标机作业，**应合并为一次执行**，
而不是两次上机。已登记为残余 `C-R5`。

## Out of scope（明确不做）

- **`transcript_segments` / `asr-local` 写入路径** —— 属 `20260929-asr-local-transcript-storage`
- **E2E 的 F7 收敛缺口**（ASR 写完不落 `transcripts` 行）—— 同上，本 plan 不碰
- **改已发布的四稿产物**（D-2）
- **`_CUE_*` 之外的其他规则**（如 `_thread_text` 的标点缝合逻辑本身）
- **`proofread-merge` 的裁决语义**（本次只修它的输入前提）
- **R10 / R11 本身** —— 分别为 `20261001-cli-import-integrity` 与既有 residual，本 plan 只在 Task 4 依赖前者
- **全量测试套件** —— 用受影响范围的定向单测

## 复现（本 plan 数字的可核验形式）

```bash
# 基线指标（在目标机上，读 route2 现有产物）
python3 - <<'PY'
import json, re, statistics as st
A='/mnt/e/bili-e2e/love-dual-route/route2/transcripts'
FIN='。！？!?'
for b in ('BV1Y7M4zNEfF','BV1vNTqzFEve','BV1zz5zzFENq','BV1BdtazGEBE'):
    segs=json.load(open(f'{A}/{b}.p0/bundle.raw.json'))['segments']
    d=[s['end']-s['start'] for s in segs]; c=[len(s['text']) for s in segs]
    e=sum(1 for s in segs if s['text'].strip()[-1:] in FIN) if segs else 0
    print(b, len(segs), round(st.median(d),2), st.median(c), max(c), f"{e/len(segs)*100:.0f}%")
PY
```

对照 `reports/e2e.md` § round 2 与 `evidence/round2/` 的原始日志。

## 已收口的决策（operator 2026-10-01）

| # | 问题 | 结论 |
|---|---|---|
| **Q1** | D 的落点 | 扩展 `bundle.raw.json`（不写 `transcript_segments`） |
| **Q2** | 校准目标 | 对齐字幕，**句子通顺优先** |
| **Q3** | 是否接受重跑 | 接受**一次**；D 落地后调规则免 GPU |
| **Q4** | 已发布产物 | 不改，新建 |
