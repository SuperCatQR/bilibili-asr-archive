---
plan_id: 20261001-cli-import-integrity
title: CLI 导入完整性与测试门控修复 — 了结 R10/R11（`asr` 命令在 main 上完全不可用）
status: registered
owner: project-manager
created_at: 2026-10-01
iteration_refs: []
primary_spec: .mstar/specs/asr-archive-cli.md
execution_mode: sdd
plan_parallelism: serial
enforcement: soft
gate_decision: pass
gate_decision_reason: >-
  Prepare satisfied by measurement. R10 and R11 were found by E2E round 2 and falsified by control
  experiments, not inferred: the AST audit of src/bili_asr/cli/*.py names 12 unresolved symbols
  across three modules; the blast radius was measured by lifting the test gate in two stages
  (1844 passed -> 1849 passed/144 skipped -> 106 failed); and the pad/target contrast rules out the
  installs as the cause. The defect is not a hypothesis and needs no further investigation.
---

# CLI 导入完整性与测试门控修复 — 让 `bili-asr asr` 不再 NameError

**Main worktree branch**: `main`（control root；本 plan 不切换）

> **For agentic workers:** REQUIRED SUB-SKILL: `mstar-sdd`. Checkbox syntax.

## Problem Statement

`bili-asr asr` **在本 plan 之前完全不可用**。任何调用在加载模型之前就抛
`NameError: name '_queue_source_is_manifest' is not defined`（`cli/asr.py:77`）。

根因是 CLI 拆分（`7a26158`，已在 `origin/main`）把 `cli.py` 拆成 `cli/` 子包时，
**三个模块的 import 块没有补齐**。AST 审计（只用 `ast` 模块，不信 grep）给出 12 处：

| 模块 | 未解析名 | 行 | 可达性 |
|---|---|---|---|
| `cli/asr.py` | `_queue_source_is_manifest` | 77 | **LIVE** — `asr` 命令每次必炸 |
| | `_store_transcript_todo` | 88 | LIVE |
| | `_subtitle_segments` | 167 | LIVE |
| | `_audio_base_holding` | 189 | LIVE |
| | `_reclaim_after_archive` | 231 | LIVE |
| `cli/pilot.py` | `_AUDIO_BUDGET_SKIP_HINT` | 499 | LIVE — `pilot` 命令 |
| | `_record_api_error` | 554 | LIVE |
| `cli/publish.py` | `_queue_source_is_manifest` | 319 | **DEAD** — 见下 |
| | `_store_audio_todo` | 358 | DEAD |
| | `_resolve_sessdata` | 367 | DEAD |
| | `_record_api_error` | 435 | DEAD |
| `cli/pilot.py` | `ArtifactRoots` | 98 | 良性 — 仅类型注解，`from __future__ import annotations` 下不求值 |

`publish.py` 那四处之所以 DEAD：`_cmd_download_audio` 在 `publish.py:309` 与 `queue.py:240`
**重复定义**，而 dispatcher 走 `queue.py`，`cli/__init__.py:37` 也只从 `queue` 导出。
**实测两处 AST 完全相同**（`ast.dump` 逐字节相等），所以 `publish.py` 那份是纯死代码。

### 为什么全项目从没发现（这才是真正的缺陷）

`tests/_asr_fakes.py:148-149` 用 `pytest.importorskip` 双重门控 ASR 替身：

```python
np = pytest.importorskip("numpy", reason="the ASR path reads audio through numpy")
sf = pytest.importorskip("soundfile", reason="the ASR path reads audio through soundfile")
```

pad venv **两个都没有** → `install()` 在 **fixture setup 阶段**抛 `Skipped` → 测试体
（含那句 `main([...])`）**从未执行**。E2E 实测的两段式门：

```
无依赖          -> 1844 passed,   0 failed   (35 个 ASR 测试全 skip)
+ numpy         -> 1849 passed, 144 skipped   (仍然盲)
+ soundfile     ->  106 failed                (缺陷立即暴露)
+ soxr          ->   81 failed                (去掉环境噪音后的真实面)
```

**门控本身也不完整**：`pyproject.toml` 的 `[asr]` extra 声明 4 个依赖
（`transformers`、`accelerate`、`soundfile`、`soxr`），门控只检查了其中 2 个。

### 控制实验（排除"是装包造成的"）

目标机 `192.168.3.21` 原生带 numpy、本会话未在其上装任何包，
对同样文件复现同样失败（`20 failed, 17 passed`）。装包没有制造缺陷，
只是移开了掩盖它的门。

## 决策（PM 已定，implementer 执行即可）

| # | 决策 | 结论 | 依据 |
|---|---|---|---|
| **D-1** | `publish.py` 的死副本怎么办 | **整段删除 `_cmd_download_audio` 及其专属私有 helper** | 两处 AST 实测相同，dispatcher 与 `__init__` 都走 `queue.py`。删除一次消掉 4 处遗漏，且消除"改一处漏一处"的结构性隐患。**不选**给它补 import——那会让死代码继续可编译 |
| **D-2** | 测试门控怎么修 | **把三个轻量依赖声明为测试依赖，删除 importorskip 门控；不装重量级依赖** | **本行于 2026-10-01 经 PM 实测更正**（原写"让替身不再需要 numpy"，那是错的，见下）。`numpy`/`soundfile`/`soxr` 是 `[asr]` extra 里的**轻量**成员（MB 级，纯 CPU），而 `transformers`/`accelerate`/`torch` 是重量级且**测试根本不需要**——它们已被 `conftest.py:151` 的 `mock_torch` 与 `_asr_fakes` 完整替身。实测：只装前三个、不装 transformers/torch/accelerate，ASR 测试**照常执行** |
| **D-3** | R11 那批 fixture 缺口 | **在本 plan 内一并修** | 同一次"门开之后"的暴露面，同一批测试文件，分两个 plan 会让第二个 plan 依赖第一个的未合并状态。R11 的登记说"same owner as the suite" |

## 现状精确坐标（2026-10-01 实测，`main` = `8bf734f`）

- `src/bili_asr/cli/asr.py:8-19` — `from bili_asr.cli._shared import (...)` 列了 10 个名字，
  含 `_open_read_repository`、`_subtitle_schema_rebuild_line`、`_todo_for_bvid`，**缺 2 个**
  （`_queue_source_is_manifest`、`_store_transcript_todo`）
- `src/bili_asr/cli/asr.py:72-77` — `_cmd_asr` 体内已有函数内 import 风格
  （`from bili_asr import archive, asr` 等）；三个 `_shared`/`pilot` helper 需要在此取其一的风格
- `src/bili_asr/cli/pilot.py:97,123,161` — `_subtitle_segments`/`_audio_base_holding`/`_reclaim_after_archive`
  的定义地。**注意**：`pilot.py:27` 模块级 import `asr.py`，所以 `asr.py` **不能**在模块级反向 import
  `pilot.py`（会成环）——必须用函数内 import
- `src/bili_asr/cli/publish.py:309` — 待删除的死 `_cmd_download_audio` 起点
- `src/bili_asr/cli/_shared.py:149,195` — 两个待补 import 的定义地
- `tests/_asr_fakes.py:148-149` — 待移除的双重门控
- 12 个失败测试文件（gate 开、装齐 deps 后 81 个失败）：
  `test_cli_asr`(17) `test_cli_artifact_root`(16) `test_cli_pilot`(12)
  `test_mixed_outcome_contract`(11) `test_scheduler`(9) `test_long_live`(8)
  `test_cli_queue_source`(2) `test_campaign`(2) `test_page_pipeline`(1)
  `test_derived_queue_chain`(1) `test_audio_budget`(1) `test_artifact_root_writes`(1)

## Interfaces

- **不改任何公开 CLI 接口**：`asr`/`pilot`/`download-audio` 的参数、退出码、输出格式全部保持
- **不改 `_shared.py` 的任何定义**（12 处遗漏都在调用侧，定义侧是完整的）
- **不改 `cli/__init__.py` 的导出**（它已经从 `queue` 导出 `_cmd_download_audio`）
- 删除 `publish.py` 的死副本后，`publish.py` 的导出面必须不变——它本来就不导出这个

## Naming decisions

（本 plan 不引入新命名——只补 import 与删死代码。命名合规性由 naming-analyzer 规则约束：
Python snake_case 函数、`_` 前缀私有、`UPPER_SNAKE` 常量。删除的 `_cmd_download_audio`
在 `queue.py` 保留原名，**不重命名**，因为它的名字已准确且被 `__init__` 导出。）

## Constraints

- **不得**改 `_shared.py`、`queue.py` 的定义
- **不得**改 `cli/asr.py` 的模块级 import 顺序或引入新的模块级反向依赖（会成环）
- **不得**为通过测试而安装 `transformers`/`torch`——见 D-2
- **不得**改任何测试的**断言意图**；R11 只补 fixture 的前置条件（建 `archive.db`），
  不改 `assert rc == 0`
- **不得**删除或放宽任何现有测试
- 全量测试**在**本 plan 授权内（这是修复验证的必要条件——gate 是缺陷的一部分）

## Verification mode

**RED→GREEN 是强制证据**，且必须在 **gate 移除后**的干净环境里取得：

1. **RED**（在 `main` = `8bf734f`，gate 已移除、只装轻量三依赖）：
   `bili-asr asr --pending --archive-root <tmp>` 抛 `NameError`
2. **GREEN**（本 plan 落地后，同一环境同一命令）：给出**正常产品错误**或成功，不再是 `NameError`
3. **AST 审计**：`unresolved names == []`（`argparse` 除外，注解良性），输出须贴出
4. **门控移除的证明**：`grep -c importorskip tests/_asr_fakes.py` == 0，且
   `pytest --collect-only -q | tail -1` 的 collected 数**增加**（skip 变执行）
5. **目标文件全绿**：12 个失败文件全部 0 failed
6. **全套件**：给出最终 `passed/failed/skipped` 三个数，且 `failed == 0`

**不得**用"我装了依赖所以绿了"来交差——D-2 明确禁止。

## Tasks

### Task 1 — 补 `asr.py` 的 5 处遗漏（含防环）

补 `asr.py` 缺失的 5 个名字：
- `_queue_source_is_manifest`、`_store_transcript_todo` → 加入现有 `from bili_asr.cli._shared import (...)`
  块，**保持字母序**（现有块是字母序）
- `_subtitle_segments`、`_audio_base_holding`、`_reclaim_after_archive` → **函数内 import**
  （在 `_cmd_asr` 体内），并在注释里写明原因：`pilot.py:27` 模块级 import 本模块，模块级反向 import 会成环

**验收**：AST 审计中 `asr.py` 的 unresolved 为空；`python -c "import bili_asr.cli.asr"` 成功；
`bili-asr asr --pending --archive-root <空目录>` 给出产品错误而非 NameError。

### Task 2 — 补 `pilot.py` 的 2 处遗漏 + 删除 `publish.py` 的死副本

- `pilot.py`：补 `_AUDIO_BUDGET_SKIP_HINT`、`_record_api_error` 到它现有的
  `from bili_asr.cli._shared import (...)` 块，保持字母序
- `publish.py`：**删除** `_cmd_download_audio`（`:309` 起）及其**只被它使用**的私有 helper；
  删除前先用 AST 确认哪些 helper 只被它引用，**不得**误删 `publish.py` 其它命令用到的函数

**验收**：AST 审计中 `pilot.py` 只剩良性的 `ArtifactRoots`，`publish.py` 为空；
`python -c "import bili_asr.cli.publish, bili_asr.cli.pilot"` 成功；
`cli/__init__.py` 的 `_cmd_download_audio` 仍解析到 `queue.py` 的那个。

### Task 3 — 移除测试门控（D-2 的核心）

`tests/_asr_fakes.py:148-149` 用双重 `pytest.importorskip` 门控整个 ASR 替身。**删除这两行**，
并把它们所要求的三个轻量依赖声明为测试依赖。

**PM 实测更正（原任务描述有错，以此为准）：** 本任务原本要求"让替身不再需要 numpy/soundfile"。
**那是不可行的**，实现前已实测：`src/bili_asr/asr.py` 在被替身覆盖的路径上直接调用
`np.asarray`、`np.convolve`、`np.pad`、`np.abs`、`np.ones`、`np.argmin`，以及 `soxr.resample`
（`:1063-1081`、`:665-714`）。这些是**被测代码**的调用，不是测试的调用——替身无法把它们藏掉，
除非连被测代码一起伪造，那就不再是测试了。

正确做法：这三个依赖是 `[asr]` extra 里的**轻量成员**（MB 级、纯 CPU），把它们加入
`pyproject.toml` 的 `[dev]` extra（或等价地声明为测试依赖），然后删除门控。
**不得**把 `transformers`/`accelerate`/`torch` 加进去——它们是 GB 级且测试用不上
（`mock_torch` + `_asr_fakes` 已完整替身；实测只装轻量三个即可执行）。

**验收**：`grep -c importorskip tests/_asr_fakes.py` == 0；
`pytest tests/test_cli_asr.py --collect-only -q | tail -1` 的 collected 数等于该文件全部测试数；
且在**未安装** transformers/torch/accelerate 的环境里跑得动（贴 `python -c "import transformers"` 失败的证据）。

### Task 4 — 修 R11 的 fixture 缺口

**PM 实测更正（2026-10-01，T1/T2 已合并后）：** 本任务原估"12 个文件里属于 R11 类的测试"。实测后
的范围是 **12 个文件 / 81 个失败**，且 R10 已由 T1/T2 清除（12 个文件里实际 `NameError` 异常数为 **0**）。
剩余失败的归因（gate 已开、轻量三依赖已在）：

| 文件 | failed | 其中 db-gate 类 | 其余 |
|---|---|---|---|
| `test_cli_asr` | 17 | 9 | `assert 1 == 0`（rc 失败，同类；gate 行在 stdout） |
| `test_cli_artifact_root` | 16 | 7 | 同上 |
| `test_cli_pilot` | 12 | 6 | 同上 |
| `test_mixed_outcome_contract` | 11 | 3 | 同上 |
| `test_scheduler` | 9 | 1 | 同上 |
| `test_long_live` | 8 | 4 | 同上 |
| `test_campaign` | 2 | 0 | 同上 |
| `test_cli_queue_source` | 2 | 0 | `assert [QueueGapItem...] == []`（见下） |
| `test_page_pipeline` | 1 | 0 | `assert 'audio_ok' == 'archived'`（见下） |
| `test_derived_queue_chain` | 1 | 0 | `assert 0 == 1` |
| `test_audio_budget` | 1 | 1 | — |
| `test_artifact_root_writes` | 1 | 0 | `assert False` |

**统一根因**：这些 fixture 只 seed `ManifestStore`，不 seed `archive.db`。而 `asr`/`pilot`/`schedule`/
`campaign` 的**默认队列源是 store**（`queue_source.py:184-186`：库不存在时 `open_queue_source` 返回
`None`），于是命令在 precheck 就 exit 1，测试的 `assert rc == 0` 失败。`tests/test_cli_asr.py:160`
自己就写明了这一点（"the store source needs a seeded archive.db, which this fixture omits"）。

**做法**：加一个共用 helper 创建 `archive.db`。**不要**发明新写法——仓内已有两处先例：
- `tests/test_cli_publish_transcripts.py:117` 的 `_seed_archive(root, parts=PARTS)` 用 `open_database(root)`
- `tests/test_fetch_meta_skip_failed_page.py:140` 直接用 `open_database(tmp_root)`

`open_database(root)` 会建表（`storage/database.py:198`）。helper 命名按 naming-analyzer：动词短语、
snake_case、`_` 私有 → **`_seed_archive_database(root)`**。

**若某个测试的失败不是 db-gate 类**，**不要**为了让测试变绿而改断言。逐个判定后如实报告：
- `test_cli_queue_source` 的 `== []` 与 `test_page_pipeline` 的 `'audio_ok' == 'archived'` 可能触及
  **F7（ASR 不写 transcript 行）** 或队列视图语义——那是本 plan 的 **Out of scope**。
  这类**不修**，如实报告并留给 F7 的归属 plan。
- 判定标准：先补 fixture 前置条件，再看该测试是否转绿。仍红的，就是另一类，报告它。

**验收**：每个由 fixture 修复而转绿的测试贴出实际输出；未能转绿的一个个列出，
并给出它们的真实失败原因（不得含糊带过）。

### Task 4b — 清除 `test_asr_qwen.py` 的 34 处同类门控

Task 3 只改了 `_asr_fakes.py` 的那一处门控（patch 把 Step 3 限定为"报告"）。实现者随后报告：
`tests/test_asr_qwen.py` 里还有 **34** 处 `pytest.importorskip`——numpy ×19、soundfile ×14、soxr ×1。
PM 判定这属于同一缺陷类，纳入本 plan。

**为什么必须一并修**：Task 3 之后，`_asr_fakes.py` 的立场变成"轻量三依赖在每个主机上都跑"，
而 `test_asr_qwen.py` 仍在缺依赖时 skip——同一棵测试树里两个相反的立场。其中 `:744` 的 soxr 门控
最尖锐：它是 `soxr.resample` 路径的**唯一**覆盖，而本 plan 更正后的 D-2 正是以该路径"无法被替身
藏掉"为由把 soxr 列为测试依赖。留着它等于自相矛盾。

**做法**：与 Task 3 的 Step 2 同一变换——`pytest.importorskip("X")` → 直接的 `import X`，
**不改任何断言**。34 处一次性机械转换。

**注意**：`test_asr_qwen.py` 可能有**其他**正当的可选依赖门控（例如真需要 GPU 的）。逐个判定，
只转换 numpy/soundfile/soxr 三类；若发现别类，**保留并报告**。

**验收**：
- `grep -rn "importorskip" tests/ | grep -E "numpy|soundfile|soxr"` → 空
- `pytest tests/test_asr_qwen.py -q` 贴出实际输出；与转换前对比 collected 数**上升**
- 未安装 transformers/torch/accelerate 的前提下仍能执行（贴三者 import 失败的证据）
- 若有保留的门控，逐个说明理由

### Task 5 — 关闭 R10/R11 并记录

- register：`R10` → `accept`/`resolved`，关闭说明带证据指针（AST 审计输出、
  RED→GREEN 命令与输出、AST 审计前后对比、12 文件全绿输出、全套件三数）
- register：`R11` → 同上
- **不得**顺手改 R8/R9（`--start-page` 回退、`part_title`/`tag_name` 暴露面）——它们与本 plan 无关
- 计划文件 `## Naming decisions` 若需回填，由 PM 收口

**验收**：`validate_harness_state.py` 通过；R10/R11 的 `lifecycle` 为 `resolved` 且
`closed_at` 为 2026-10-01；R8/R9 仍为 `open`（贴 grep 输出）。

## Out of scope（明确不做）

- **`--start-page` + 回退边界（R8/R9）** —— 已登记，不属本 plan
- **`part_title`/`tag_name` 的接受规则** —— R8，同上
- **B7 的队列不收敛（F7）** —— 归 `20260929-asr-local-transcript-storage`，本 plan 不碰 store 语义
- **`verify`/`coverage` 的 exit-code 不对称（F6）** —— 已对照证实为既有行为，另案
- **把 `transformers`/`torch` 加入 CI 环境** —— D-2 明确不做
- **`publish.py` 的其它内容** —— 只删死副本
- **目标机上的运行** —— 本 plan 是纯本地修复；真机复测归 E2E workflow

## 已收口的决策（PM 2026-10-01）

`## 决策` 表的 D-1/D-2/D-3 三条已由 PM 定，implementer **不要再选**。

## 复现（本计划的可核验形式）

```bash
cd /root/workspace/bilibili-asr-archive/bilibili-asr-archive
# 1) AST 审计（当前 main 应给出 12 处）
python3 - <<'PY'
import ast,builtins,glob,os
for p in sorted(glob.glob('src/bili_asr/cli/*.py')):
    tree=ast.parse(open(p).read()); defined=set(dir(builtins))
    for n in ast.walk(tree):
        if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)): defined.add(n.name)
        elif isinstance(n,ast.Name) and isinstance(n.ctx,ast.Store): defined.add(n.id)
        elif isinstance(n,ast.arg): defined.add(n.arg)
        elif isinstance(n,ast.alias): defined.add((n.asname or n.name).split('.')[0])
        elif isinstance(n,ast.ExceptHandler) and n.name: defined.add(n.name)
    used={}
    for n in ast.walk(tree):
        if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Load): used.setdefault(n.id,n.lineno)
    unk=sorted((ln,nm) for nm,ln in used.items() if nm not in defined and nm!='argparse')
    if unk: print(os.path.basename(p),unk)
PY
# 2) 命令级 RED
rm -rf /tmp/r10-red && PYTHONPATH=$PWD/src ./.venv/bin/python -m bili_asr asr --pending --archive-root /tmp/r10-red
