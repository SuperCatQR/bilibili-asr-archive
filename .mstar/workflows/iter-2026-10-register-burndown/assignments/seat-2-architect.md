**Execution scope**: plan
**Execute as**: architect
**Delegation**: forbidden
**Task category**: audit
**Control harness root**: /root/workspace/bilibili-asr-archive/.mstar
**Workflow id**: iter-2026-10-register-burndown
**Iteration id**: iter-2026-10-register-burndown
**Compass ref**: iterations/iter-2026-10-register-burndown/delivery-compass.md
**Direction-lock record**: iterations/iter-2026-10-register-burndown/direction-lock.md
**Package root**: iterations/iter-2026-10-register-burndown/
**Worktree path**: /root/workspace/bilibili-asr-archive
**Branch policy**: direct on main — Phase 1 的写入目标全是主 checkout 内的 `.mstar/` 工件；本席位不得切换分支、不得创建 worktree、不得 push
**Budget (review / QC seats)**: 1
**Return shape (review / QC seats)**: edits landed on disk + Completion Report
**Task budget (implement / ops rounds)**: 1
**Main worktree branch**: main

---


## 你要做的事

这是 Phase 1 §1.6 **Review & Edit 链第 2 席**（architect）。第 1 席（product-manager）已经跑完，
它改过的文件就是你要读的**当前状态**。

你的职责是**架构与长期契约（specs）**：把三个 plan 里的技术判断收敛成可执行的接口与边界，并清掉
owner 指向 `architect` 的标记。**就地编辑**：

1. `{PLAN_DIR}/asr-run-record-integrity.md`（B1）
2. `{PLAN_DIR}/archive-writeback-durability.md`（B2）
3. `{PLAN_DIR}/verification-lane-contract.md`（B3）
4. `{ITERATION_DIR}/iter-2026-10-register-burndown/specs/` —— **若**某个判定需要一份迭代级契约文档
   （例如「一次调用 = 一个 run，且 run 必须收尾」这条不变量），在此起草（`<iteration-id>/specs/` 是
   Phase 1 的规格书写位置；全局 `{SPECS_DIR}/` 在 Phase 3 提升时写入）。**不需要**就别造文档。
5. `{ITERATION_DIR}/iter-2026-10-register-burndown/delivery-compass.md` —— 仅 `## Decisions` /
   `## Open Questions` / `## Risk Register` 三节，按需。

## 必须回答的判定点（这些是 plan 里 `<!-- TODO(owner: architect) -->` 标记的主体）

**B1 `asr-run-record-integrity`：**
- `finish_asr_run` 的 **outcome 取值集合**，以及它在 CLI 退出路径上的**唯一**调用点（第二次调用会
  改变语义 —— 明确说明为什么唯一，或给出幂等保证）。
- selector 透传的形状：给 `ensure_asr_run` 加参数，还是新开一个 scope 参数对象？给出推荐与理由，
  并说明它对既有调用者的影响面（先 `grep -rn "ensure_asr_run" bilibili-asr-archive/`）。
- `I-000199` 的两条路（接受「诊断可能改变退出码」并写下 vs 改写入路径使其不改变退出码）在
  `services/_common.py` 既有约定下的取舍 —— 给出推荐。**注意**：这条的结论必须来自实测探针，
  你只负责给出**取舍准则**，不负责跑探针。
- `I-000198` 的 `except` 面：哪些异常类属于「store 拒绝」（可被重述为 refused run），哪些属于
  「连接契约违反」（必须逃逸或单独上报）？给出分界线。

**B2 `archive-writeback-durability`：**
- `I-000196` 的解码策略选择：**严格解码**（与 `AttemptLedger._replay_tail` 及
  `tests/…::test_invalid_bytes_in_tail_fail_closed` 一致；代价是一个坏字节让一个可 resume 的 SSOT
  永久打不开）vs **替换但绝不把替换后的 key 写回快照**。给出一条推荐并说明它在 resume 语义下的后果。
- `I-000203` 的取舍：真关闭 publish→discard 窗口（需要 durability 观察，成本与平台相关）vs 把前提
  写下来（今天没有任何 `src/` 调用者用 `save(entries)` 形式）。给出推荐与判据。
- `I-000193` 的落点：加一条 attempt-ledger / store 级可查询信号，还是把 gap view 的后果写成 tracked
  decision 并给出 owner？这条同时是 compass 的 **Q1**，请一并收敛（收敛后把 Q1 从 `## Open Questions`
  撤出并计入 `## Decisions`，或在 Q1 上写明你的结论与 owner 变更）。
- `_journal_bytes` 删除的影响面：先 `grep -rn "_journal_bytes" bilibili-asr-archive/`，确认是否真有
  读路径；有就列出行号，没有就确认可删。

**B3 `verification-lane-contract`：**
- `I-000174` 的「schema 派生的退出」具体是什么：开库成功 + 断言某张 schema 表存在，还是刻意触发一个
  schema 派生的错误退出？给出可判定的形态（承接方要能直接写成断言）。
- `I-000175` 的迁移方向：移 5 个 installer 测试到 `tests/test_installed_cli.py`（保留排除集）还是移
  in-process 家族出去（改排除集）？说明它对 `scripts/verify_baseline.py:270-282` 的 staged-tree 逻辑
  的影响。**先读那段代码再答。**
- `I-000211` 的落点（同时是 compass 的 **Q2**）：probe 落 observation 需要一条 acquisition_run
  （attempt rows 有外键），成本包含一次 run 生命周期 —— 值不值得？还是把「不留痕」写成显式决定？
  给出推荐并把 Q2 收敛（同上）。

## 你要检查的架构面（不限于 marker）

- **跨 plan 的写目标冲突**：B1 与 B2 **都改** `src/bili_asr/coordinator.py`。三个 plan 是 `serial`
  执行，但请确认按此顺序不会产生语义冲突（例如 B1 改了 `:798` 的 page 身份、B2 改了 `:735`/`:860`
  的 docstring 与调用点吞没）；若顺序有关，在 compass `## Decisions` 写明建议顺序。
- **`I-000171` 与 `I-000176` 的一致性**：前者要求 page 身份由 `work_id` 推导、推不出就跳过写回；
  后者要求「一行 store 路由 ASR 行断言 transcripts join 计数」。跳过写回的行会不会让后者的见证
  变成假绿？若会，写明见证必须用什么样的行。
- **`I-000210` 的谓词改动面**：`v_missing_audio` 的 `empty_inventory_confirmations` 子句改动会不会
  影响其它视图或既有行？先读 `schema-transcripts.sql` 相关段落再答。
- **B1/B2/B3 与既有 knowledge 的冲突**：读 `{KNOWLEDGE_DIR}/architecture-patterns/` 下与
  subtitle-acquisition / run-scoped-provenance / verify-coverage 相关的既有文档，确认本迭代的判定
  **不与之矛盾**；若矛盾，指出并说明哪一条应当改（注意：知识文档的修改是 Phase 3 `mstar-compound`
  的事，你只指出冲突）。

## 边界（HARD）

- **不得**向 `{KNOWLEDGE_DIR}/` 新增任何文档（也不得修改既有知识文档本体 —— 冲突只做指认）。
- **不得**写全局 `{SPECS_DIR}/`（Phase 3 提升时写入）；迭代级规格只写
  `iterations/iter-2026-10-register-burndown/specs/`。
- **不得**创建 worktree、切换分支、commit 或 push。
- **不得**替承接方决定实现细节到「伪代码即实现」的程度 —— 给接口、边界、判据与 STOP 条件，
  不写整段实现。

## Return（Completion Report 必须含）

- 你改动的文件清单（逐文件一行）。
- **Marker 清除计数**：已清 N / 已重新归属 M。**本节是本报告的必填项** —— 若你有无法清除的 architect
  marker，必须在完成前显式重新归属给 `PM` 并写明理由。
- 两条 Open Questions（Q1/Q2）的收敛结果：撤出（计入 Decisions）或保留（写明为何非阻塞）。
- 你**拒绝**的 PM 初稿判定（若有），与你的依据。

---

## 已测量的证据（PM 在本轮实测，2026-10-05；**不要**重跑，直接据此取舍）

`I-000199` 的退出码问题已用最小探针复现，四条对照（CPython 3.12，`os.close(2)` 在进程中途关闭 fd 2）：

| 变体 | 写入方式 | 观测退出码 |
|---|---|---|
| 现状 | `print(..., file=sys.stderr)`（buffered text stream，`sys.stderr` 仍是活包装器） | **120** |
| 变体 A | 完全不写 | 0 |
| 变体 B | `print(...)` + 显式 `sys.stderr.flush()` | **120** |
| 变体 C | `sys.stderr.write(...)` + 显式 `flush()` | **120** |
| 变体 D | `os.write(2, b"...")`（无缓冲、直写 fd），`OSError` 被吞 | **0** |

结论（你据此判定，不必自行推导）：**显式 flush 救不了它，因为失败发生在解释器 shutdown 刷缓冲区时；唯一改变退出码的写法是绕开文本缓冲层（直写 fd）。** 因此 `I-000199` 的两条路具体是：

- **(接受)** 把「stderr 中途死亡时诊断可能把退出码改成 120」写成 plan 级契约的一条，并给 owner；
- **(改写入路径)** 让 `_report_refused_asr_run` 的诊断走无缓冲写入（变体 D 的形状），代价是放弃 `print` 的文本层语义（编码、错误策略）并把该细节局限在诊断函数内。

给出你的推荐与判据：哪一条更符合 `services/_common.py` 与 D8 的既有约定（先在源码里找这两个名字的约定原文再答）。

## PM 复核结果：三个 plan 里的 **行号漂移**（2026-10-05 在 `c59a1e6` 实测；请在你这轮直接用右列）

PM 在 lock 前把三份 draft 的引用逐条对 HEAD 复核过。**左列是 draft 现在写的（来自四天前的 audit），
右列是 HEAD 的实测值** —— 请把 plan 里对应的行号改成右列（这些是「引用准确性」，属你的技术复核范围）：

| 行 | draft 写的 | HEAD 实测 |
|---|---|---|
| `I-000184` write-back site | `cli/asr.py:289` | **`cli/asr.py:293`**；另有 **`cli/pilot.py:611`** 与 **`coordinator.py:799`**（三处同形 `… or "und"`，本 plan 的 acceptance 若只修 asr.py 一处，必须在 plan 里说明另外两处的处置） |
| `I-000171` page 身份 site | `cli/asr.py:294`、`cli/pilot.py:367` / `:605` | **`cli/asr.py:298`**、**`cli/pilot.py:372`** / **`:610`**（`coordinator.py:759` / `:798` 正确）。**另注意**：`page_identity.py:96`、`archive.py:54` / `:59`、`cli/queue.py:400`、`subtitles.py:123` 也有同形表达式，但**不是** write-back 调用点 —— 你的判定必须说明这些为什么**不**在本行范围内（否则承接方会扩大手术面） |
| `I-000199` 诊断写入点 | `queue_source.py:206-222` | 实测 `except (OSError, ValueError, TypeError)` 在 **`:220`**；latch 读写在 **`:208`** / **`:210`**；`sys.stderr is None` 守卫在 `:213` 附近 |
| `I-000192` caption 写回调用点 | `coordinator.py:860-868` | 调用点在 **`:866`**（`_record_subtitle_transcript(` 的最后一次出现） |
| `I-000193` 终态提前返回 | `coordinator.py:1056-1062` | `TERMINAL_STATUSES` 出现在 **`:30`**（定义）、**`:1071`**、**`:1160`** —— draft 的 `:1056-1062` 未命中，请按实测重定位并写准 |
| `I-000203` save() 顺序 | `manifest.py:513-526` | `_replace_snapshot(current)` 在 **`:519`**（空路径）与 **`:531`**（正常路径），`_remove_journal()` 紧随其后 |
| `I-000175` 排除集 | `scripts/verify_baseline.py:275` | 实测在 **`:273-278`** 的 `ignore=lambda …` 集合内（三个名字正确，位置以 `:275` 附近为准） |
| `I-000210` 计数子句 | `schema-transcripts.sql:214-219` | 正确；**但**该 CTE **没有** select `credential_present`（`ar.credential_present` 目前只在 `:113` / `:134` 的其它视图出现），所以修法必须**先把它加进 CTE 的 select list** —— 视图可重建、无 DDL 迁移，符合 compass 的「无 in-place migration」约束。请把这个形状写进 plan 的 Approach |
| `I-000211` | `subtitle_ingest.py:424-436` | `_probe_parts` 在 **`:417`**、`_probe_part` 在 **`:424`**、`_acquire_parts` 在 **`:435`**、`_acquire_part` 在 **`:447`** |

**另有一条你必须判断的范围事实**：`I-000184` 的 acceptance 写的是「the default asr path stores
language=…」，而实测有**三处**同形回退（`asr.py:293`、`pilot.py:611`、`coordinator.py:799`）。请判定：
本行是只修 `asr.py`（acceptance 的字面范围），还是三处一起修（同一缺陷类）。给出推荐与理由；
若判定三处一起修，把 `cli/pilot.py` 与 `coordinator.py` 的相应位置写进 plan 的 Files 列表。
