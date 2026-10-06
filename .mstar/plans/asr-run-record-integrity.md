---
plan_id: asr-run-record-integrity
project: _default
status: draft
created_at: 2026-10-05
execution_mode: sdd
plan_parallelism: serial
---
# Plan asr-run-record-integrity — Make an ASR invocation's run record and write-back tell the truth

**Main worktree branch**: `main`（control root 驻留分支；本 plan 不切换。Phase 1 lock 轮观察于 2026-10-05，`c59a1e6`）

## Status
- **Priority**: P1
- **Effort**: M
- **Risk**: MED（触碰 `cli/asr.py` 的 write-back 顺序与 `queue_source.py` 的异常面；两处都有既有测试覆盖，且关行依赖它们）
- **Confidence**: HIGH（全部 10 行为 register 内 `open` 行，且逐行在 `c59a1e6` 复核过证据仍成立）
- **Fingerprint**: iter-2026-10-register-burndown/b1-asr-run-record
- **Depends on**: none
- **Category**: bug
- **Evidence**: 见下 `## Current state` 的逐行行号（均为 `c59a1e6` 实测）
- **Planned at**: commit `c59a1e6`, 2026-10-05
- **Captured issues**: `I-000182`, `I-000183`, `I-000184`, `I-000197`, `I-000198`, `I-000199`, `I-000180`, `I-000171`, `I-000176`, `I-000194`
- **Iteration**: `iter-2026-10-register-burndown`（compass B1）

## Problem

一次 ASR 调用留下的**持久记录**与它实际做的事不一致，四个方向：

1. **run 永远不结束** —— `kind=asr` 的 acquisition run 没有收尾调用，`outcome` 永远是 `running`、
   `finished_at` 永远 `NULL`。任何问「这次 ASR 跑完了吗」的消费者（run 账本显示、将来的 resume、
   coverage/integrity 读者）拿到永久错误答案。字幕路径有收尾、ASR 路径没有，所以这不是「run 概念
   未实现」，是**一条腿漏了**。
2. **作用域记成 whole-queue** —— `asr --bvid X:p0` 记 `selector_kind=pending, selector_target=NULL`，
   与无界队列跑法不可区分；schema 里 `bvid` selector 必须带 target 的 CHECK 被恒定写 `pending` 架空。
3. **语言记成 `und`** —— 中文转写的 transcripts 行 `language='und'`（provenance 无 language 时的回退
   常量），削弱 `search --language` 过滤，并让唯一键 `(video_part_id, source_kind, language, version)`
   比设计意图更粗。
4. **write-back 失败会计与顺序** —— `cli/asr.py` 的 ASR write-back 仍跑在「标记 archived」之前、且在
   archive 成功守卫**之内**，与 caption 侧已确立的不变量（一旦 bundle 发布且完整性已验证，行就是
   `archived`，写回是 best-effort）相反；`I-000171` 的 page 身份默认 0 会把 bare-bvid 行的转写盖到
   p0 的 `video_part` 上；`I-000176` 说明这条写回至今**没有端到端见证**，只有直接调用
   `record_local_transcript` 的单测。

D8 拒绝诊断那三行（`I-000197`/`I-000198`/`I-000199`）是同一族：诊断的作用域、异常面、以及「stderr
中途死掉会把退出码改成 120」这三件事都没被写清或收窄，于是下一个人只能靠读实现猜。

## Current state（excerpts — 动手前须对 live code 复核）

- `I-000182`：`grep -rn "finish_acquisition_run" src/` → 仅
  `src/bili_asr/services/subtitle_ingest.py:359` / `:384`；`services/queue_source.py` 的
  `ensure_asr_run`（`:143-172`）只 `start_acquisition_run`。
- `I-000183`：`src/bili_asr/services/queue_source.py:166-168` —
  `selector_kind="pending", selector_target=None, requested_limit=None`（与 `command` 无关的常量）。
- `I-000184`：`src/bili_asr/cli/asr.py:289` —
  `language = (provenance or {}).get("language") or "und"`
  （同址 `coordinator.py:799`、`cli/pilot.py:609` 是同一形状的另外两处）。**seat-1 复核更正（见下
  `## 产品侧判定` P1）**：`provenance` 由 `runner.provenance()` 产出，**它确实暴露 `language`**
  （`asr.py:1497`：`"language": _redact(config.language or "")`，来源是 `asr.py:511` 的
  `os.environ.get(ASR_LANGUAGE_ENV_VAR) or None`）—— 所以 `und` 出现的条件是「**环境变量未设**」，
  不是「provenance 不暴露语言」。真正的缺口在另一头：解码器**已经解析出**语言
  （`_transcribe_chunk` 返回 `(text, str(parsed.get("language") or ""))`，`asr.py:1236`），但管线
  只用它做对齐、**从不落到 runner 上**（`asr.py:1369` 解包后即丢），所以它无法到达 write-back。
- `I-000198`：`src/bili_asr/services/queue_source.py:174` 捕获
  `(_sqlite3.Error, OSError, ValueError)`；连接契约违反（`TypeError`/`AttributeError`）逃逸出
  write-back，被上游重述成「行失败」而非「store 拒绝」。
- `I-000199`：`src/bili_asr/services/queue_source.py:206-222` 先守 `sys.stderr is None` 再
  `print(..., file=...)`，失败被 `except (OSError, ValueError, TypeError)` 吞掉，但 CPython 在
  shutdown 刷不出缓冲时给**退出码 120**。
- `I-000180`：`src/bili_asr/services/queue_source.py:22` 模块级 `import time`，`:153` 又
  `import time as _time` 遮蔽；`:98`/`:359`/`:382`/`:439`/`:502` 是**真实使用的** `time.*` 调用点
  （不是死代码），`services/_common.py:14` 的 `_now()` 是既定单一可注入时钟。**未用导入的地点在
  `queue_source.py` 之外的 `src/bili_asr/cli/meta.py`**（seat-1 实测 11 个，见 `## 产品侧判定` P2），
  而 `queue_source.py` 自身除 `from __future__ import annotations` 外**没有**未用导入。
- `I-000171`：`src/bili_asr/coordinator.py:759` / `:798`、`src/bili_asr/cli/asr.py:294`、
  `src/bili_asr/cli/pilot.py:367` / `:605` 仍用 `int(entry.get("page_index") or 0)`。**seat-1 复核**：
  实测 `coordinator.py` 的 `:759` 在 `_record_subtitle_transcript` **内部**、`:798` 在
  `_record_asr_transcript` **内部**，两者都是**写回路径**；`cli/pilot.py` 的 `:367` 则是
  `mark_audio_acquired`（audio 回写）—— 该文件里 `:605` 才是 ASR transcript 写回。`I-000171` 的
  acceptance 只说「each write-back」，所以五处都在字形范围内，但**只有 transcript 写回**有那条
  「bare-bvid 行会盖到 p0」的失败模式（`mark_audio_acquired` 的 p0 盖写是另一个后果，未被该行命名）——
  实施时按行 acceptance 处理，不对 `:367` 做未命名的扩面。
- `I-000194`：`src/bili_asr/cli/asr.py:288-296` 的 write-back 位于 per-row `try` 内、在
  `updated["status"] = "archived"`（`:299-301`）之前。
- `I-000176`：`tests/test_coordinator.py:1620-1667` 已见证 run-batch 正路径；缺的是 store 路由
  ASR 行的 join 计数断言 + `ensure_asr_run` 失败时「archive 仍成功」的见证。

## 产品侧判定（seat-1 复核，2026-10-06 — 改的是**范围与后果的表述**，不增删目标行）

- **P1 — `I-000184`：初稿的前提是错的，STOP 条件可能因此永远不会触发。** `runner.provenance()` 的
  `language` 键**可以非空**（`asr.py:1497` 从 `config.language` 取值，后者来自
  `BILI_ASR_LANGUAGE`）；它为空只说明**这次运行没设那个环境变量**。因此 Task 2 的措辞「provenance
  确实不暴露语言时，落一个被写下的常量」会把一个**可修的真缺陷**写成一个合规的常量回退 —— 而
  `## STOP conditions` 第一条（「provenance 确实不暴露任何语言来源 … 由 PM 决定落常量」）也建立在
  同一误判上。**改法**：语言来源有两条且都真实 ——（a）配置侧（现成，但只在运维设了环境变量时非空）、
  （b）解码器**已解析但被丢弃**的检出语言（`_transcribe_chunk` 的第二返回值）。把「落 `und` 还是
  落检出语言」作为**架构决定**交给已有的 architect marker（它是接口形状问题：检出语言要存在
  runner 的哪个字段上、两趟（two-pass）里取哪一趟），不由实施者就地选择。**不要在未问之前**
  把检出语言丢掉，也不要为了「让行可关」而把 `und` 写成「已按设计」。
- **P2 — `I-000180` 的第二半不在本 plan 的 Files 里。** 该行 acceptance 是两个合取项：
  「queue_source 用共享时钟（或移除 shadow 与额外调用点并写明理由）**且**两个未用导入被删除；
  另加一条 lint 规则或 pin 防止复发」。seat-1 用 AST 逐名统计实测：
  - `queue_source.py`：`import time`（`:22`）被 `:98` 的 `time.strftime` **真实使用**，`:153` 的
    `import time as _time`（`:160`/`:161`）也是真实使用 —— 「shadow」和「额外调用点」都在
    `:359`/`:382`/`:439`/`:502` 的 `int(time.time())` 上。该文件**没有**未用导入。
  - `cli/meta.py`：**11 个**真未用导入（`DEFAULT_ARCHIVE_ROOT`、`_archive_database_exists`、
    `_format_run_line`、`_identity_from_entry`、`_open_read_connection`、`_open_read_repository`、
    `_record_api_error`、`_run_error_codes`、`_subtitle_schema_rebuild_line`、`_todo_for_bvid`、
    `DEFAULT_MID`），行号 `:11`–`:27`，均为 plan-010 去重后留在 import 块的**导入点残留**。
  「a lint rule or a pin」这一项在仓库里**没有既有载体**（`tests/` 下没有导入卫生测试），需要新建
  一个最小 pin（AST 允许清单或一个断言现有导入都可解析的测试）—— 否则这一行只能靠人再看一次。
  **Files 需补 `cli/meta.py`（+ 一个测试文件）**；不补则该行会「见证通过但 acceptance 未满足」。
- **P3 — `I-000199` 的 acceptance 面比 Files 宽。** 该行要求**逐站点**探针（三处：`queue_source._report_refused_asr_run`、
  `coordinator._print_model_constructions`、`cli/asr.py:102`），或让三处**共享**一条不改变退出码的写入路径。
  本 plan 的 Files 只覆盖前两处所在的文件（`queue_source.py` / `coordinator.py` 未列、`cli/asr.py` 已列），
  请**明确写清**：这三处是「都要改」，还是「都要探针、只改其中一处」。默认建议走**共享写入路径**（一处实现，
  三处引用），因为逐站点探针的结论会随 CPython 版本漂移（该 plan 自己的 STOP 条件也承认这一点）。
- **P4 — `I-000171` 的 `cli/pilot.py` 不能算作关闭见证。** seat-1 逐行核对：无任何目标行的 acceptance 文本
  命名 `pilot`（`I-000176` 只要求 store 路由的一条 join 计数断言 + 一条 `ensure_asr_run` 失败见证）。
  在 `pilot.py` 里顺带改是对的方向，但**不要**把它写成该行的 closure evidence —— 关闭证据只能引用行
  acceptance 点名的那条见证。
- **P5 — 与 B2 的接口面（产品可见的后果，不是重构）。** `coordinator.py:799` 与 `cli/pilot.py:609` 是
  `I-000184` 同形状的另外两处 `language='und'` 写入点。若只改 `cli/asr.py`，则**同一条缺陷在同一张表里
  留下两条不一致的写入路径**（`asr` 命令行写真实语言、coordinator/pilot 写 `und`），而 `transcripts` 的
  UNIQUE 是 `(video_part_id, source_kind, language, version)` ⇒ 同一 part 经不同路由会落在**不同的行**上。
  本 plan 要么三处一起改，要么在 `## Out of scope` 里显式写明「另两处留给谁、何时」，**不得**留成隐含。

## Approach

四个 Task，按「先让记录可信，再让会计可信」排序（Task 2/3 依赖 Task 1 建立的 run 收尾点）：

- **Task 1（run 生命周期 + 作用域）**：给 `QueueSource` 加一个收尾入口（例如
  `finish_asr_run(outcome, ...)`），在 ASR 调用的退出路径上调用一次（成功 → `complete`，异常 →
  该次运行的失败态），并把 `ensure_asr_run` 的 selector 参数从调用方透传（bvid/page → `bvid` +
  target；无参 → `pending`）。字幕路径既有的两个 `finish_acquisition_run` 调用点不动。
- **Task 2（语言 + page 身份）**：write-back 的 `language` 取自 provenance 的真实值；provenance
  确实不暴露语言时，落一个**被写下的常量**并就地注明理由（不静默回退）。page 身份改为由行
  `work_id` 推导；推不出 page 的行**跳过写回**并在日志里说明，而不是盖到 p0。
- **Task 3（write-back 顺序与守卫）**：把 `cli/asr.py` 的 ASR write-back 移到
  `updated["status"] = "archived"` 与 `store.upsert` 之后、且移出 archive 成功守卫（best-effort
  语义与 caption 侧一致）；补上 `tests/test_coordinator.py` 之外的 store 路由端到端见证（Task 4
  的 `I-000176` 用例即其入口）。
- **Task 4（诊断面收窄与见证）**：`ensure_asr_run` 的 `except` 面按「连接契约违反不得被重述为
  store 拒绝」收窄/分流；`_report_refused_asr_run` 的 latch 作用域在实现处与调用处写明「一次调用
  = 一个 batch = 一个 source」；`I-000199` 的退出码行为**先测量再落结论**（接受并写下，或改写入
  路径使其不改变退出码）；`queue_source` 回到单一可注入时钟并清掉未使用导入；补
  `I-000176` 的两个见证。

<!-- TODO(owner: architect): 逐 Task 的接口形状与 STOP 边界 —— 具体是 (a) finish_asr_run 的 outcome 取值集合与其在 CLI 退出路径上的**唯一**调用点（避免第二次调用改变语义），(b) selector 透传是给 ensure_asr_run 加参数还是新开一个 scope 参数对象，(c) I-000199 的两条路（接受 vs 改写入路径）在 `services/_common.py` 既有约定下的取舍。 -->

## Files

- **Modify**: `bilibili-asr-archive/src/bili_asr/services/queue_source.py`
- **Modify**: `bilibili-asr-archive/src/bili_asr/cli/asr.py`
- **Modify**: `bilibili-asr-archive/src/bili_asr/coordinator.py`（`I-000171` 的 page 身份一半 +
  `I-000184` 在 `:799` 的同形状写入点，见 P1/P5）
- **Modify**: `bilibili-asr-archive/src/bili_asr/cli/pilot.py`（同上；**但 pilot 不产生任何目标行的
  关闭见证**，见 P4）
- **Modify**: `bilibili-asr-archive/src/bili_asr/services/subtitle_ingest.py`（仅当 `I-000180` 的
  时钟收敛需要它；不动其两个 `finish_acquisition_run` 调用点）
- **Modify**: `bilibili-asr-archive/src/bili_asr/cli/meta.py`（`I-000180` 的第二个合取项 —— 11 个未用
  导入，`:11`–`:27`，见 P2；该文件与三簇的其它行无关，改动仅限删导入）
- **Test**: `bilibili-asr-archive/tests/test_queue_source.py`（或该模块既有测试文件）—— run 收尾、
  selector、except 分流、latch 说明
  - **注**：`tests/test_queue_source.py` **不存在**；队列侧的既有测试文件是
    `tests/test_storage_queue_gaps.py` / `tests/test_storage_queue_writes.py` /
    `tests/test_derived_queue_chain.py` / `tests/test_cli_queue_source.py`。落哪个以「哪张表断言哪件事」
    为准，不要新建一个语义重复的文件。
- **Test**: `bilibili-asr-archive/tests/test_coordinator.py` —— store 路由 ASR 行 join 计数 +
  `ensure_asr_run` 失败仍 archive 成功（`I-000176`）
- **Test**: `bilibili-asr-archive/tests/test_cli_asr.py`（或该模块既有测试文件）—— write-back 顺序与
  page 身份
- **Test**: 新增一个**导入卫生 pin**（`I-000180` 的第二合取项，见 P2）—— 位置建议
  `tests/test_import_hygiene.py`；断言 `bili_asr` 下 `cli/meta.py` 的导入集合与一个显式的
  「允许存在但未使用」清单相等，或等价地断言每个导入名在模块体内出现至少一次。

## Out of scope

- 字幕路径的 `finish_acquisition_run` 既有调用点（`subtitle_ingest.py:359` / `:384`）—— 本 plan 的
  验收面明确要求它们不变。
- `video_part` / `transcripts` 的 schema 变更 —— 本 plan 不引入 in-place migration。
- `I-000193`（终态 caption 行的写回失败可识别性）—— 属 B2 `archive-writeback-durability`。
- engine 侧 `I-000190` / `I-000207` —— 非产品代码，进 compass Non-Goals。

## Verification gates

- **每个 Task 的 red→green 见证**：先写出会失败的断言（对 `I-000182`：断言 `finished_at IS NOT NULL`
  在修复前失败；对 `I-000183`：断言 `selector_kind='bvid'` 在修复前失败），再实现。见证命令与计数
  写进本 plan 的 durable review-gate summary。
- **模块套件**：
  - `PYTHONPATH=$PWD/src /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest bilibili-asr-archive/tests/test_queue_source.py bilibili-asr-archive/tests/test_coordinator.py -q`
    （在 plan feature worktree 内执行；具体 selector 以该 worktree 的测试布局为准）
  - **seat-1 实测更正**：这条命令**今天必然以 `file or directory not found` 失败** ——
    `bilibili-asr-archive/tests/test_queue_source.py` 不存在（实测退出 4，`no tests ran`）。同样，
    从**仓库根**执行时 `$PWD/src` 解析到不存在的 `/root/workspace/bilibili-asr-archive/src`（真正的包在
    `bilibili-asr-archive/src`），之所以还能导入只是因为 conftest 自己插了路径。落地时把 selector 换成
    实际文件名（`test_storage_queue_gaps.py` / `test_storage_queue_writes.py` / `test_derived_queue_chain.py` /
    `test_cli_queue_source.py` 中真正钉住本 plan 断言的那些），并在 **`bilibili-asr-archive/` 目录内**执行。
- **诊断面测量**：`I-000199` 的退出码结论必须来自**实际跑过的**探针（stderr 在进程中途关闭、
  记录进程退出码），不接受推断。
- **无 schema migration**：`git diff --stat` 不得出现 `schema-*.sql` 的 DDL 变化。

## STOP conditions

- `runner.provenance()` 确实不暴露任何语言来源、且实现侧无法在不猜的前提下得出语言 → STOP，
  报告实测的 provenance 键集，由 PM 决定落常量还是把该行标为 blocked（**不得**猜一个语言）。
  **seat-1 更正（P1）**：本条的前提**已不成立** —— provenance 暴露 `language`（`asr.py:1497`），且
  解码器还额外解析出检出语言（`asr.py:1236`）只是被丢弃。所以本条**不会**触发；真正该 STOP 的情形是
  「把检出语言持久化到 runner 会改变 `two_pass_transcribe` 的返回契约」——那时按 marker 交 architect，
  而不是落 `und`。
- `finish_asr_run` 的唯一调用点无法在 `cli/asr.py` 的退出路径上确定（例如存在本 plan 文件列表外的
  调用者）→ STOP 并列出多出的调用者，不擅自扩大签名改动面。
- `I-000199` 的探针显示退出码行为**因 CPython 版本而异** → STOP 并记录两个版本下的实测值。
- 任一目标行的 claim 在动手时已被 HEAD 修复 → 仍按本 plan 的见证要求记录 red/green（red 无法复现即
  already-fixed），并把该行从「本 plan 关闭」改为「已修、补记证据」。
- **新增**：`I-000180` 的「lint rule or a pin」若无法在不引入新依赖的前提下落地（仓库 `dev` extra 里
  没有 lint 工具）→ STOP 并报告，由 PM 决定「用 AST 自写 pin」还是「把该合取项显式留给下一轮」，
  **不得**只做时钟收敛就把该行关掉。

## Done criteria

- [ ] `I-000182` / `I-000183` / `I-000184` / `I-000197` / `I-000198` / `I-000199` / `I-000180` /
      `I-000171` / `I-000176` / `I-000194` 十行各自的见证在修复前失败、修复后通过（red/green 记录在
      review-gate summary）。
- [ ] `I-000180` 的**两个**合取项都成立：时钟收敛 **且**「一个 lint 规则或 pin 防止复发」落地
      （见 P2；仅做前者不算满足该行 acceptance）。
- [ ] `I-000184` 的三处写入点（`cli/asr.py:289`、`coordinator.py:799`、`cli/pilot.py:609`）对**同一
      part 经不同路由**写出同一个语言值；或另两处的去向在 `## Out of scope` 里具名（见 P5）。
- [ ] 上列模块套件通过；既有失败基线（动手前实测）不变。
- [ ] `grep -rn "finish_acquisition_run" src/` 在 asr 路径上也出现收尾调用点。
- [ ] `git diff --check` 退出 0；`git status --short` 无本 plan Files 列表之外的文件。
- [ ] 十行全部经 store 关闭（`disposition = resolved`），closure evidence 指向本 plan 的修复提交。
      **前置**：先把 coordinator 绑到本迭代 workflow（compass D11）—— 否则 `resolved` 写不进去，
      这一条会成为「已修但关不掉」。

## Drift check

`git diff --stat c59a1e6..HEAD -- src/bili_asr/services/queue_source.py src/bili_asr/cli/asr.py src/bili_asr/coordinator.py src/bili_asr/cli/pilot.py` —— 若任一 in-scope 文件已变，先重读
`## Current state` 的行号断言再动手。
