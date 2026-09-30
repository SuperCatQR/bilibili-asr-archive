---
plan_id: 20260930-metadata-shape-resilience
title: 元数据边界形状韧性 — 了结 R6/M-R2 的「整页失败」决策（多行 description 使枚举永久卡死）
status: registered
owner: project-manager
created_at: 2026-09-30
iteration_refs: []
primary_spec: .mstar/specs/asr-archive-cli.md
execution_mode: sdd
plan_parallelism: serial
enforcement: soft
gate_decision: pass
gate_decision_reason: >-
  Prepare satisfied by measurement, not by speculation. The decision this plan closes was
  explicitly deferred with "Needs a decision, not a guess" (residual
  20260926-video-metadata-enrichment · R6, decision: defer, owner @project-manager). The E2E
  workflow e2e-23191782-love-items-dual-route has since supplied the measurement R6 lacked: a
  live 4-item enumeration blocked 13/13 attempts on one page, cause located at
  sources/models.py:112 (_text rejects \n on `desc`), blast radius measured at 4 items across
  2 of 5 sampled pages, and `desc` proven to have ZERO readers in the whole src tree. Scope is
  therefore the ruling + its implementation, not a hunt.
---

# 元数据边界形状韧性 — 让一页中的一个畸形条目不再永久卡死枚举

**Main worktree branch**: `main`（control root；本 plan 不切换）

> **For agentic workers:** REQUIRED SUB-SKILL: `mstar-sdd`. Checkbox syntax.

## Problem Statement

**一句话**：上游一条视频的 `description` 里有一个换行符，就让 `fetch-meta` **永远无法越过那一页**——不是重试能过的问题，是 cursor 拒绝推进，全量归档从此断在那里。

**操作者视角**（谁在受影响）：任何想归档 UID 23191782 全部投稿的人。日常三步里的第一步 `fetch-meta` 会在第一个含多行简介的稿件所在页卡死，`--resume` 只是原地打转。目标机上实测 **13/13 次尝试全部 exit 2**，两次爬梯（5 次 + 12 次）都没过。

### 这不是本 plan 发现的，是已登记悬置的决策

residual **`20260926-video-metadata-enrichment · R6`**（severity medium，`decision: defer`，owner `@project-manager`）原文：

> A multi-line upstream `description` would raise `GatewayShapeError` from `_text` (it rejects
> `\n`/`\r`) and therefore fail the WHOLE page — the same blast radius as Task 1's blank-`author`
> M3. Flagged by the Task 4 implementer rather than worked around, and consistent with `title`'s
> existing discipline, **but unruled**: either the boundary should normalise newlines the way
> caption text does, or the terminal-on-malformed choice is accepted and pinned.
> **Needs a decision, not a guess.**

**本 plan 的职责就是给出那个 decision，并实现它。** 它不再是猜测——E2E 已提供 R6 当时缺的实测。
同族还有 **`M-R2`**（tag endpoint 同类的整页+整 run 失败，severity medium，open），
以及已闭环的 `M3`（blank `author`，其 blast radius 已被 `test_a_blank_author_costs_every_item_on_the_page` 固定）。

### 实测证据（全部来自 e2e-23191782-love-items-dual-route，2026-09-30）

| # | 事实 | 证据 |
|---|---|---|
| E1 | 页 6 一项畸形 → 整页失败，**13/13 次** exit 2；页 1 同凭据同主机正常 | `a2-endpoint.log`, `a2-fetch-meta.log`, `a2c-widen.log` |
| E2 | 肇事条目 `BV18b9DYeE3s`，肇事字段**只有** `desc`，肇事字符**只有** `\n`(0x0a)；同页 29/30 项正常 | `a2-item-field-level.log` |
| E3 | 杀伤面不是孤例：抽样页 2–6，**页 3 有 3 项**、页 6 有 1 项，**全因多行 `description`** | `a2-blast-radius.log` |
| E4 | 卡死是**永久**的：cursor `next_page=6, state=ready`，任何 gateway 非限流失败都映射为 `failed/failed`，**不推进 cursor** | `a2-diag.log` + `metadata_ingest.py:_page_and_run_outcomes` |
| E5 | 上游确有此类数据：`BV18b9DYeE3s` 的 `created=1741387364`、`pubdate=None`，是**真实在架稿件** | `a2-item-field-level.log` |
| E6 | `desc` **全仓零读者**：全 src 树没有一个 `SELECT … FROM video_details`；`export` 的 16 个标准列不含 `desc`；`desc` 也不进任何 frontmatter | `grep -rn "FROM video_details" src/` 空；`export.py:22-39`；`archive.py:560` |

### 关键是"整页失败"本身是一个**有意决策**，不是疏漏

`test_a_blank_author_costs_every_item_on_the_page` 的 docstring 写着：

> Documents the M3 blast radius: the fallback one layer down never gets its chance, because the
> page-level error is terminal and the sibling entries are never persisted either.

而它上一条测试的 docstring 说得更明确：**"pins the cost so the policy stays a decision rather than an accident."**

**所以本 plan 不得把"整页失败"当成 bug 顺手改掉。** `title`/`bvid`/`author` 的严格纪律是有理由的
（`author` 的空值有下游 fallback，而"上游真发了一个空格"不该被 fallback 掩盖）。
`desc` 与它们不同的地方只有一处，但那处是决定性的：**它没有任何读者，也就没有任何 fallback 需要保护。**

## 决策（本 plan 要落的那一条）

**D-1：`desc` 在边界归一化，`_text` 的纪律对其它字段一律不动。**

理由按证据排列，不按偏好：

1. **`_text` 注释给出的理由是"这些字段由 CLI 逐行原样打印，控制字符会撕开锁定的输出形状"。对 `desc` 这个理由不成立**——E6 证明 `desc` 零读者，没有任何输出形状依赖它。该注释自己不适用于此字段，这不是我在曲解它，是它写明的适用范围（"operator-facing … printed verbatim, one line per record"）。
2. **仓库里已有同形的先例，且是为同一个字符、同一个理由**：`_caption_text` 的 docstring——"rejecting `\n` here would turn a real caption into a document-level shape error"。多行简介与多行字幕是同一类上游事实。
3. **丢弃是对的，而且是可表达的**：`upsert_video_details` 的跳过条件是三者**全**为 `None`（`database.py:462-470`，D15）。把 `desc` 归一为 `None` 时 `pic`/`tid` 仍在，**整行照写、`observed_at` 照动**，不触发 D15 跳过、不产生"观测到空"的假事实。`test_upsert_video_details_advances_for_a_desc_only_observation` 覆盖的是"只有 desc 被观测到"那一支，与"desc 不可表示故为 None"不冲突。
4. **sqlite 不是限制**：`\n`/`\r`/`\x00`/`\t`/`\x0b`/`\x0c` 全部字节完整往返（实测）。所以这是纯粹的 DTO 策略问题，改 DTO 不需要碰 schema、不需要迁移。

**具体形状**（层已定：`_read_optional_text`；以下为落点细节）：

- `desc` 的控制字符在**边界读取层 `_read_optional_text`** 被处理成"不可表示 → 缺失"，**不**在存储层放宽 `_text`，也**不**在 DTO 的 `__post_init__` 里再放宽一次（层叠的宽松会让人说不清哪层负责什么）。
- **作用域必须限制到 `desc`**：`pic` 走同一函数，规则写成字段无关会让 `pic` 的纪律无声放宽——已实测，见 `## 已收口的决策` Q1。
- **`_text` 本身不动**——它仍拒绝 `title`/`bvid`/`author`/`tag_name` 等的控制字符，`M3` 的钉子和 `test_a_blank_author_costs_every_item_on_the_page` 的意图保持有效。
- `desc` 的其它畸形（非字符串、纯空白）行为保持不变：非字符串是被记 `detail` 的 bounded shape error，空白 → `None`。
- **`tid` 不动**（E3 未观测到它携带控制字符；不为未观测的形状改代码）。

**D-2：`part_title` 与 `tag_name` 不改，但必须被显式记录为"已知同类、未变更"。**

`_normalize_video_parts`（`:333`）与 `_normalize_video_tags`（`:348`）是同样的页级扇出，`part_title`/`tag_name` 走同一个 `_text`。
- **不为它们改代码**：没有观测到此类数据，改它就是为想象买单；且 `part_title` **会**进 frontmatter 的 `title` 键（`archive.py:560`），逐行输出这条理由**对它成立**——真要保持一行。
- **但必须在交付物里写明它们的暴露面**：多行分P标题同样会卡死整页。这是**登记为 residual**，不是本 plan 的范围。

**D-3：「整页失败」的终局保留，但"永久"去掉——机制已由 PM 定为「显式跳过页 + 记录缺口」。**

修好 `desc` 之后，**下一个**未预料的字段畸形仍会整页失败。区别在于：现在它**永久**卡死（E4：cursor 不推进，`--resume` 原地打转）。这两件事必须分开处置：

- **整页失败本身：保留。** 它是有意决策，有钉子，且"部分页"会让 `observed_total` 与 `videos` 计数对不上，制造新的计数不诚实。
- **永久性：去掉，用「显式跳过页 + 记录缺口」。** PM 决定（2026-09-30），不是 implementer 的自由选择：
  - 卡死页可被操作者**显式跳过**（新增显式旗标/命令，**不**是默认行为）；
  - 跳过必须留下**可读的缺口证据**：`ingestion_pages` 记该页 `failed` + 错误码，`status` / `runs` 如实显示"这一页没取到"；
  - **不得**把缺口静默当成取完：`observed_total` 与实际条数不一致时，读者必须能看见；
  - 不得为"跳过"引入任何静默的默认路径。

  这一面**不是可选的**：只修 `desc` 等于说"下一个未知畸形再来一次"。而 R6 的措辞（"either … or …"）明确把"接受并钉住终局"当成一条正当选项——本 plan 选的正是它，**加上**去掉永久性。

## 现状精确坐标（动手前须重读）

| 位置 | 现状 |
|---|---|
| `src/bili_asr/sources/models.py:111-112` | `if self.desc is not None: _text(self.desc, "desc")` ← DTO 层的拒绝点 |
| `src/bili_asr/sources/models.py:25-43` | `_text`，`:41-42` 拒绝 `\x00`/`\r`/`\n`。**本 plan 不改这里** |
| `src/bili_asr/sources/models.py:46-60` | `_caption_text`，先例：控制字符**保留** |
| `src/bili_asr/sources/bilibili_api_gateway.py:182-199` | `_read_optional_text` ← **D-1 的落点**（PM 决定）。docstring 自称控制字符是 bounded shape error 但**实际不检查** |
| `src/bili_asr/sources/bilibili_api_gateway.py:281-283` | **页级扇出**：整页在一个推导式里归一化，一项抛错整页失败（**保留**，见 D-3） |
| `src/bili_asr/sources/bilibili_api_gateway.py:333` | `_normalize_video_parts`，同样的扇出（D-2 的暴露面） |
| `src/bili_asr/sources/bilibili_api_gateway.py:348` | `_normalize_video_tags`，同样的扇出（`M-R2` 已登记） |
| `src/bili_asr/storage/models.py:255-263` | `VideoDetailRecord` 的 `_text(self.desc)` —— **本 plan 不改**（见下方更正） |
| `src/bili_asr/storage/database.py:462-470` | D15 跳过条件是三者全 `None` |
| `src/bili_asr/storage/schema.sql:54-61` | `"desc" TEXT`，**无 CHECK 约束** |
| `src/bili_asr/services/metadata_ingest.py:_page_and_run_outcomes` | 非限流 gateway 失败 → `failed/failed`，cursor 不动 |

### 更正：只有一个交付点，不是两个（计划期实测推翻）

本计划早先写的是"**两个拒绝点**（sources 的 DTO 与 storage 的 record）都必须处理，只改一处会在
另一处再炸"。**PM 在计划期的原型实测证明这句话是错的**，必须更正，否则 implementer 会去改一个
不需要改的文件：

实测（在未修构建上用 monkeypatch 试跑 D-1 的边界规则，**未改任何文件**）：

```
[1] desc multi-line via the page boundary:
    page OK, n = 2
    sibling survived: BV1good00001 | desc = '哲学讲座摘要'
    bad one: bvid = BV18b9DYeE3s | desc = None         <- 边界吞掉，整页存活
[2] sources DTO constructed directly with desc="a\nb":  still rejected   (defence in depth intact)
[3] storage DTO constructed directly with desc="a\nb":  still rejected   (defence in depth intact)
[4] NEGATIVE CONTROL: title with \n still fails the whole page            (correct)
```

结论：

- **`VideoDetailRecord` 无需改动。** 它在全 src 树**只有一个构造点**
  （`services/metadata_ingest.py:545-548`），其 `desc=summary.desc` 拿到的**已经是边界归一后的值**——
  边界吞掉后传下来就是 `None`，storage DTO 的 `_text` 永远看不到 `"a\nb"`。
- 两个 DTO 的 `_text` 拒绝**保留**，构成 defence in depth（[2]/[3] 证明它们仍会拒绝直接构造的坏值）。
  **这不是缺陷，是好事**，不要"顺手统一"掉。
- 所以 **D-1 只有一个改动点：`_read_optional_text`**（+ 它的 docstring，见 `## Open question` 的收口）。

**这条更正是本计划自查的产物，保留原文痕迹是为了让 implementer 看见推理链，而不是只看见结论。**

## Interfaces

- **`VideoSummary.desc`**：类型与可空性**不变**（`str | None`）。变化仅在"什么样的 `desc` 值被接受"。
- **`VideoDetailRecord.desc`**：同上。
- **`_text`**：签名与语义**不变**。新增的宽松行为**不**通过给它加参数实现——另一个字段需要它时再谈。
- **`videos` / `video_details` 表**：schema **不变**，无迁移。
- **`fetch-meta` CLI 表面**：本 plan 的 D-3 面若引入"跳过页"或"推进 cursor"的开关，是一个**新增**的显式命令/旗标，不是默认行为改变。默认路径的行为必须保持可预测。
- **`_normalize_user_video_page` / `_normalize_video_parts` / `_normalize_video_tags`**：签名不变。

## Naming decisions

> 按 `USER.md` 的强制要求，命名一律经 `naming-analyzer` 决定，不凭直觉。

待定的命名（implementer 在 T1 前用 skill 定，并把结论写回本节）：

| 待命名 | 约束 |
|---|---|
| `desc` 归一化后的行为名 | 必须表达"不可表示→缺失"，不要用 `sanitize`/`clean` 这类含糊词 |
| D-3 的跳过/推进开关 | 必须让操作者一眼看出它**留下缺口证据**，不能听起来像"忽略错误" |
| 新增的 residual id | 沿用 register 现有 `R#` 序列 |

## Constraints

- **不得**放宽 `_text`（会让 `M3` 的钉子失效，且把纪律从这个字段扩散到全部字段）。
- **不得**改 `title`/`bvid`/`author`/`pic`/`tid`/`tag_name`/`part_title` 的接受规则。
- **不得**改 schema 或引入迁移。
- **不得**让"跳过页"在默认路径上静默发生——它必须是显式的、且 `status`/`runs` 如实显示缺口。
- **不得**把 `test_a_blank_author_costs_every_item_on_the_page` 删掉或改宽；它的意图（整页失败是有意决策）保持不变。
- 全量测试**不在**本 plan 授权内；实现自检用受影响范围的定向单测（见下）。

## Verification mode

`scoped-check`（定向单测 + RED→GREEN 复现）。

### RED 基座已在计划期实测（不是声称，是跑出来的）

在**未修**的 pad `main`（`68770b1`）上，用 `PYTHONPATH=src:tests` 跑既有 fixture 得到的实测结果——
implementer 开工后应能逐字复现同样的四条：

```
=== RED-1: default fixture desc is single-line; does the suite reach the defect? ===
   description: '哲学讲座简介'
   -> accepted, desc = '哲学讲座简介'          # 既有 fixture 够不到缺陷，这就是它漏到今天的原因

=== RED-2: multi-line desc FAILS on the unfixed build (the defect) ===
   -> GatewayShapeError: GatewayShapeError(shape_error): video item is not normalizable

=== RED-3: one bad item kills the whole page ===
   -> GatewayShapeError: GatewayShapeError(shape_error): video item is not normalizable   (BV1good00001 never came back)

=== NEGATIVE CONTROL: title with \n must STILL fail (also after the fix) ===
   -> GatewayShapeError: GatewayShapeError(shape_error): video item is not normalizable   (correct)

=== storage side: second rejection point ===
   -> ValueError: desc contains invalid control characters   (second rejection point confirmed)
```

复现命令（pad，`bilibili-asr-archive/` 目录下）：

```python
import sys; sys.path.insert(0,'src'); sys.path.insert(0,'tests')
from fixtures.fake_bilibili_gateway import make_vlist_item, make_videos_response
from bili_asr.sources.bilibili_api_gateway import _normalize_video_summary_item, _normalize_user_video_page
MID=23191782
_normalize_video_summary_item(make_vlist_item(description="a\nb"), MID)   # RED-2: raises
_normalize_video_summary_item(make_vlist_item(title="正常\n伪造"), MID)   # negative control: must keep raising
```

**注意**：`tests/test_bilibili_api_gateway.py` 有一个本地包装 `_normalize_video_summary_item(item)`（`:365-376`）
单参数补 `requested_mid=MID`；上面的复现走的是**真实双参签名**。T2 新增用例走测试文件内的包装即可。

**必须有 RED→GREEN 证据**，且 fixture 必须能真正触达失败面
（`{KNOWLEDGE_DIR}/testing-patterns/absence-assertion-negative-control.md`：fixture 到不了 falsifier 的测试是文档不是验证）：

1. **RED（先证伪）**：在**未修**的构建上，一个含多行 `description` 的 `make_vlist_item` 必须让 `_normalize_video_summary_item` 抛 `GatewayShapeError`。既有 fixture `make_vlist_item`（`tests/fixtures/fake_bilibili_gateway.py:831-868`）的 `description` 默认值是**单行** `"哲学讲座简介"`，所以现有测试**够不到**这个缺陷——这正是它漏到现在的原因，修复必须补上能触达的 fixture。
2. **GREEN**：同一 fixture 在修后不抛错，且 `desc` 落到约定的缺失值；`pic`/`tid` 仍照常读出。
3. **负对照（同一轮内）**：**同一个页 fixture 里**放一个 `title` 含 `\n` 的条目——它**必须仍然整页失败**（证明没有把纪律从 `desc` 漏到别的字段，也证明失败面仍然可达）。
4. **存储侧**：`VideoDetailRecord(desc="a\nb")` 修后不抛，且 `upsert_video_details` 写入的行里 `pic`/`tid` 照常、`observed_at` 照常推进（D15 跳过**未**被误触发）。
5. **D-3 面**：一个永久卡死页在修后可被显式越过的证据，以及越过之后 `status`/`runs` **确实**显示了缺口。

## Tasks

### Task 1 — 在 `_read_optional_text` 归一化 `desc`（PM 已定层：Q1）

**Files:** `bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py`

**Scene:** 这是本 plan 的核心修复。上游一条视频的 `description` 里有一个 `\n`，`_text` 就拒绝它，而页级扇出（`:281-283`）让整页失败，cursor 又不推进（`:E4`），于是全量归档永久卡死在那一页。

**实现要求：**

1. 在 `_read_optional_text`（`:182`）里，把**仅限 `desc` 字段**的"控制字符文本 → 视为缺失（返回 `None`）"规则落地。
   - **作用域必须限制到 `desc`**。`pic` 与 `desc` 走同一函数；把规则写成字段无关会**无声放宽 `pic` 的纪律**（已实测，见计划 `## 已收口的决策` Q1）。
   - `pic` 的行为**必须保持不变**：含 `\x00`/`\r`/`\n` 的 `pic` 仍须让整页失败。
2. 同函数的 docstring（`:183-192`）**必须同步改写成真话**：它现在声称"text carrying a control character the storage contract rejects, is a bounded shape error"，但函数实际不检查。改写后要准确描述"控制字符文本 → 缺失"这条新规则，并说明为什么 `desc` 与 `pic` 可以不同。
   - **不得**让新代码与旧 docstring 并存（`{KNOWLEDGE_DIR}/best-practices/claim-scope-discipline.md` 点名的那类缺陷）。
3. **不改** `sources/models.py` 与 `storage/models.py`：`VideoDetailRecord` 只有一个构造点（`metadata_ingest.py:545-548`），其 `desc=summary.desc` 拿到的已是边界归一后的值，storage DTO 永远看不到坏值。两个 DTO 的 `_text` 拒绝保留，构成 defence in depth。
4. **不改** `_text` 本身（它仍拒绝 `title`/`bvid`/`author`/`tag_name` 的控制字符）。
5. 命名：如需新符号（常量、helper、谓词），用 `naming-analyzer` 决定，并把结论写回计划 `## Naming decisions`。

**Verification（RED→GREEN，必须真跑）：**

- **RED（先证伪）**：在未修的构建上，`_normalize_video_summary_item(make_vlist_item(description="a\nb"), 23191782)` 必须抛 `GatewayShapeError`。
- **GREEN**：修后同一输入不抛错，`desc` 为 `None`，且该页**同页其它条目存活**。
- **负对照 A（`title`）**：`make_vlist_item(title="正常\n伪造")` 修后**仍须**整页失败。
- **负对照 B（`pic`）**：`make_vlist_item(pic="http://x/c\n.jpg")` 修后**仍须**整页失败。若它变绿，说明作用域漏了，本任务不算完成。
- **存储侧**：`VideoDetailRecord(desc="a\nb")` 修后**仍**抛 `ValueError`（defence in depth 未被破坏）。
- 既有测试 `test_a_blank_author_costs_every_item_on_the_page` 仍须绿（整页失败是有意决策，未被本任务改变）。

**Task budget (implement / ops rounds):** 2

### Task 2 — 补能触达缺陷的回归用例与两条负对照

**Files:** `bilibili-asr-archive/tests/test_bilibili_api_gateway.py`

**Scene:** 缺陷漏到现在的原因是**既有 fixture 够不到它**：`make_vlist_item` 的 `description` 默认值是单行 `"哲学讲座简介"`，全测试套**没有任何用例**传过多行 `description`。本任务补上能真正触达 falsifier 的用例。

**实现要求：**

1. 新增用例覆盖 Task 1 的 RED→GREEN 四条（多行 `desc` 通过、`desc` 为 `None`、同页其它条目存活、存储 DTO 仍拒）。
2. 新增**两条**负对照，且必须与正例**在同一轮内**：
   - `title` 含 `\n` → 整页仍失败；
   - `pic` 含 `\n` → 整页仍失败。
   - 断言**行为**（整页失败），不要断言 `GatewayShapeError` 的 `detail` 文本（无测试固定该文本，锁文本会制造假脆弱）。
3. `make_vlist_item` **已支持**经 `**overrides` 传多行值（实测确认），**无需**扩 fixture——除非 implementer 发现必须。
4. 用例命名遵循该文件既有风格（`test_<subject>_<expectation>`）。

**Verification：**

- 用例在**未修**构建上红、修后绿（正例）；两条负对照在**两个**构建上都红（它们测的是**别的**字段仍被拒绝）。
- 只跑 `tests/test_bilibili_api_gateway.py`，**不**跑全套。

**Task budget (implement / ops rounds):** 2

### Task 3 — D-3：显式跳过页 + 记录缺口（PM 已定机制：Q2）

**Files:** `bilibili-asr-archive/src/bili_asr/cli/`（新增旗标/命令）、`bilibili-asr-archive/src/bili_asr/services/metadata_ingest.py`（缺口记录）、`bilibili-asr-archive/tests/`（对应新测试）

**Scene:** 修好 `desc` 只等于"下一个未预料的畸形再来一次"。今天一个未知字段畸形的代价是**永久**卡死——cursor 不推进，`--resume` 原地打转（实测 13/13 次 exit 2）。本任务去掉"永久"，**保留**整页失败本身。

**四条硬约束（PM 已定，不可协商）：**

1. **显式**：跳过必须由操作者主动触发（新增旗标/命令），**不得**在任何默认路径上静默发生。
2. **留证**：被跳过的页必须在 `ingestion_pages` 记为 `failed` + 错误码。
3. **如实显示缺口**：`status` / `runs` 必须让读者看见"这一页没取到"；`observed_total` 与实际条数不一致时必须可见，**不得**把缺口静默当成取完。
4. **不进默认路径**：不带旗标时，卡死页的行为与今天完全一致（exit 非 0）。

**实现要求：**

- 命名（旗标名、命令名、任何新符号）用 `naming-analyzer` 决定，写回计划 `## Naming decisions`。旗标名必须让操作者一眼看出它**留下缺口证据**，不能听起来像"忽略错误"。
- 不改变 `_page_and_run_outcomes` 对**默认**路径的映射。
- **不得**为 D-3 引入新的 schema 迁移以外的破坏性变更；如确需 schema 变更，先 `Blocked` 回报 PM。

**Verification：**

- 默认路径行为未变：不带旗标时卡死页仍 exit 非 0（用可复现的畸形 fixture 驱动）。
- 带旗标时：该页被跳过，`ingestion_pages` 有 `failed` 行 + 错误码，cursor 推进，命令 exit 0。
- 跳过之后 `status` / `runs` 输出**确实**显示了缺口（贴实际输出）。
- 只跑受影响测试文件。

**Task budget (implement / ops rounds):** 3

### Task 4 — 真机复现（PM 已授权：Q3）

**Files:** 无产品文件改动；产物为证据文件

**Scene:** 唯一的**真机**证据。其余全是离线单测。

**目标机**：`ssh -i /root/.ssh/id_ed25519 chosenecho@192.168.3.21 "wsl -e bash -s"` + 引号 heredoc（远端 shell 是 cmd.exe，**没有 `;`**）。

**执行要求：**

1. 把修复后的代码带到目标机。**注意**：目标机 `/root/e2e-asr/love-dual-route/build` 是一个 **detached worktree**（`ed291be`），其上 `models.py` 含**相同缺陷`；产品 `.venv` 的 editable install 指向**主 checkout**——所以必须 `PYTHONPATH=<修复后的 src>` 才能测到修复。
2. `fetch-meta --resume`（route-1 root：`/root/e2e-asr/love-dual-route/route1`），证明页 6 可过。
3. 记录：命令、退出码、`videos` 计数、四个 `work_id` 的 `duration_s`。

**副作用（已告知操作者）：** route-1 store 会从 30 条推进到约 60 条。

**Verification：**

- 该命令 exit 0 且四项 `work_id` 齐、`duration_s` 正。
- **若未执行则记 `not-run`，不得声称已验证。**
- 凭证纪律：`set -a; . /root/.config/bili-asr/session.env; set +a`，**绝不**打印或记录值。

**Task budget (implement / ops rounds):** 2

### Task 5 — 关闭 R6 并登记新 residual

**Files:** `.mstar/projects/_default/residuals.json`、计划 `## Naming decisions`

**Scene:** 收口。R6 是一个**已登记、悬置**的决策（`decision: defer`），本 plan 的职责就是给它 decision 并实现。

**实现要求：**

1. 在 `20260926-video-metadata-enrichment` 桶内把 **R6** 关到 `closed`，关闭说明**必须带具体证据指针**（E1–E6 + 本 plan 的 RED→GREEN 证据路径）。
2. 把 **D-2** 的暴露面登记为新 residual：`part_title` / `tag_name` 走同样的页级扇出与 `_text`，多行值同样会卡死整页。沿用该桶现有 `R#` 序列（当前最大 `R7`）。
3. **`M-R2`（tag endpoint）保持 `open`**，只在关闭说明里如实转述其状态——**不得**顺手关掉，也不得改动它。
4. 新条目须带 `id` / `severity` / `source` / `scope` / `decision` / `owner` / `target` / `tracking` / `what` / `lifecycle`，与该文件既有条目同形。

**Verification：**

- `mstar lint` / 校验器对该 register 通过；
- R6 的关闭说明能让人从它出发找到证据，不需要读本对话。
- `M-R2` 仍是 `open`（贴 grep 输出）。

**Task budget (implement / ops rounds):** 2

## Out of scope（明确不做）

- `M-R2`（tag endpoint 同类问题）——只在 T5 如实转述其状态，不顺手改。
- `part_title` / `tag_name` 的接受规则——登记为 residual。
- 放宽 `_text` 的全局纪律。
- 已有的 `title` 多行风险（本 plan 未观测到，不为想象买单）。
- 排队里的 `20260929-asr-local-transcript-storage` 与 `20260929-derive-manifest-retirement` 两个 registered plan——与本案无关。
- 全量测试套件。

## 已收口的决策（PM 2026-09-30，不再是 implementer 的自由选择）

原计划把下面两条列为"留给 implementer 的决策点"。**PM 已定**，implementer 执行即可，不要再选：

| # | 决策 | 结论 | 依据 |
|---|---|---|---|
| **Q1** | `desc` 归一化放哪一层 | **`_read_optional_text`（边界读取层）** | 该函数 docstring 已**声称**控制字符是 bounded shape error 但实际不检查；把规则放这里让那段文字从假话变真话，且 `pic`/`desc` 共用一条路径。计划期原型实测证明它足够（见上文更正：storage DTO 无需改动） |
| **Q2** | D-3 的越过机制形状 | **显式跳过页 + 记录缺口** | 见 `## 决策` D-3；已写死四条硬约束（显式、留证、不得静默、不得进默认路径） |
| **Q3** | T4 真机复现是否授权 | **已授权** | PM 明确同意在目标机复现；仍须记 `not-run` 而非声称通过，若未执行 |

### Q1 附带的必做项：那句 docstring 必须一起改

`_read_optional_text` 的 docstring 现在写着：

> A present non-string, or text carrying a control character the storage contract rejects, is a
> bounded shape error like every sibling field's.

**这句在改动前是假的**（函数只做 `.strip() or None`）。Q1 落地后它需要被改写成**真实**的行为描述——
描述"控制字符文本 → 视为缺失"这条新规则，以及为什么 `desc` 与 `pic` 可以不同。
**不得**让新代码与旧 docstring 并存：那是 `{KNOWLEDGE_DIR}/best-practices/claim-scope-discipline.md`
点名的那一类缺陷（"a docstring claiming an unimplemented refusal"），本仓库此前已经犯过并记录在案。

**同时**：既然 `_read_optional_text` 现在真的会**处理**控制字符，而 `pic` 走同一函数——必须明确写清
`pic` 的行为是否随之改变。**答案：不改变。** `pic` 是 URL，含控制字符就是坏数据；本 plan **不为
未观测的形状改 `pic`**（E3 未观测到 `pic` 携带控制字符）。

**这条不是忠告，是实测出来的陷阱。** 计划期原型把"吞掉控制字符"写成字段无关的规则后实测：

```
=== BASELINE (unfixed): control-char pic -> GatewayShapeError          (page fails, correct today)
=== NAIVE boundary rule (field-agnostic): page OK, pic = None          <- pic SILENTLY LOOSENED
=== FIELD-SCOPED rule (only desc relaxed): desc -> None;  pic -> still GatewayShapeError   (correct)
```

所以 **T1 必须把规则作用域限制到 `desc`**（按字段名分支，或拆成两个函数），并带上一条
**`pic` 负对照**：含控制字符的 `pic` 在修后**仍须**让整页失败。若它变绿，说明纪律漏了，
T1 不算完成。
