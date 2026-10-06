---
plan_id: archive-writeback-durability
project: _default
status: draft
created_at: 2026-10-05
execution_mode: sdd
plan_parallelism: serial
---
# Plan archive-writeback-durability — Make the archive record durable, the write-back honest, and the journal policy single-sourced

**Main worktree branch**: `main`（control root 驻留分支；本 plan 不切换。Phase 1 lock 轮观察于 2026-10-05，`c59a1e6`）

## Status
- **Priority**: P1
- **Effort**: M
- **Risk**: MED（`manifest.py` 是 archive 的 SSOT 写入器，`save()` 的顺序改动必须在崩溃窗口语义下推进；`coordinator.py` 的写回失败面已经有既有测试钉住）
- **Confidence**: HIGH（6 行均为 register 内 `open` 行，逐行在 `c59a1e6` 复核）
- **Fingerprint**: iter-2026-10-register-burndown/b2-writeback-durability
- **Depends on**: none（与 B1 共享 `coordinator.py` 文件但不同函数面；若两者并行实现，**必须**按文件串行合并）
- **Category**: bug
- **Evidence**: 见下 `## Current state`
- **Planned at**: commit `c59a1e6`, 2026-10-05
- **Captured issues**: `I-000191`, `I-000192`, `I-000193`, `I-000196`, `I-000202`, `I-000203`
- **Iteration**: `iter-2026-10-register-burndown`（compass B2）

## Problem

记录层有两类缺陷，一类是**说了假话**，一类是**窗口/hidden state 没被决定**。

说假话的两个：

- `coordinator.py` 的两处 docstring 仍在断言 caption write-back 跑在 `archive: ok` 记录**之前**，
  而 plan `caption-writeback-guard` 的调用点搬迁已经使之为假；`:735` 那处还附了一个「summary 读的
  行数」的机制断言，而 `fully_processed` 数的是 `RowResult`，从来没有读者实现过那个机制。这两句是
  该处 R14 契约的**唯一**描述，后来的读者会照它再推导出一个不存在的约束。
- 写回失败在 caption 侧**没有调用点吞没边界**：行的持久结论正确（bundle 已发布记为 `archived`、
  账本记 `archive: ok`），但 `_record_subtitle_transcript` 之外的 store 故障会冒出调用点，让操作者
  在一行**已经落盘**的档案上看到 exit 1。ASR 兄弟路径在自己 try 里吞，两条腿恰好在这点上不一致。
  （ASR 侧的对应问题在 B1 `I-000194`，本 plan 只负责 caption 侧。）

没被决定的窗口三个：

- manifest journal 的**解码策略**在三处读者里不对称：`_replay_latest` 用
  `errors="replace"`，而 sidecar projection 与 `AttemptLedger._replay_tail` 都是严格解码并有测试
  钉住「被破坏的记录不得通过 U+FFFD 冒充合法」。因为 manifest 侧替换，`work_id` 里的一个坏字节会
  变成一个**不同的合法 key**，而随后的 `save()` 会把这个替换后的 key **写进快照**并删掉 journal ——
  会写的读者把损坏洗成了持久记录，而只报的读者是严格的。
- `_journal_bytes` 在压缩触发改成基于文件大小后成为**只写状态**，而 `save()` 的空路径把它清零的
  同时磁盘上可能还留着撕裂的 journal。
- `save()` 先发布快照再丢弃 journal；这个窗口里的崩溃会让后续的「journal 优先」读取把旧 journal
  行**重新发布**到快照之上。docstring 记的是**读**语义，没记这个写窗口。

## Current state（excerpts — 动手前须对 live code 复核）

- `I-000191`：`src/bili_asr/coordinator.py:735-738`（「write-back runs before the attempt ledger
  records the `archive: ok`」+ 「the row count the summary reads」）与 `:1373-1379`（同类断言）。
  验收要求 `grep -n 'before the attempt ledger records' coordinator.py` 为空。**seat-1 实测更正
  （见 `## 产品侧判定` P6）**：`:1373-1379` 不是 docstring，那段是 `_caption_language_from_entry`
  的收尾与 `_caption_transcript_segments`；第二个「summary reads」断言实际在 `:772-774`
  （`_record_asr_transcript` 的 docstring），且 `grep -n 'before the attempt ledger records'` 在
  全 `src/` 下**只有 `:737` 一处命中**。
- `I-000192`：`src/bili_asr/coordinator.py:860-868` — `_record_subtitle_transcript` 在
  `_mark_archived` 之后被调用，**无** try/except；其内部只转换它自己校验的参数形状（`ValueError`）。
  **seat-1 复核**：该行存在，但初稿对它「危险程度」的描述需要一处更正 —— 被调函数
  `qs.record_caption_transcript`（`queue_source.py:457-516`）**自己已经吞掉**
  `(_sqlite3.Error, OSError, ValueError, TypeError, KeyError)`，所以今天真正会冒出调用点的只有
  **那五类之外**的 store 故障（例如连接契约被替换后的 `AttributeError`，与 `I-000198` 是同一族）。
  这不改变该行的结论（调用点仍缺 swallow 边界，且 ASR 侧的形状不同），但改变它的**见证写法**：
  注入的故障必须落在那五类之外，否则红相不会出现。
- `I-000193`：`src/bili_asr/coordinator.py:1056-1062` — `process_row` 对 `TERMINAL_STATUSES`
  提前返回，而 `archived` 是终态（`manifest.py` 的终态集合），所以一行若在写回失败后停在
  `archived`，它永远拿不到 transcripts 行，且失败只留在一次性的 stderr 行里。
- `I-000196`：`src/bili_asr/manifest.py:288`（`raw.decode("utf-8", errors="replace")`）对
  `src/bili_asr/sidecar_projection.py:131` / `:135-136`（严格 + `invalid_utf8`）与
  `src/bili_asr/coordinator.py:315-316`（严格，规则原文）及
  `tests/…::test_invalid_bytes_in_tail_fail_closed`（钉住）。
- `I-000202`：`src/bili_asr/manifest.py:131` 初始化、`:385` 累加、`:233`/`:239`/`:510`/`:529`/
  `:564`/`:588`/`:664`/`:723` 的赋值与重置；压缩触发已是文件大小函数（`_maybe_compact_locked` 的两处
  `os.path.getsize`）。**seat-1 实测**：`_journal_bytes` 的 14 处出现**全部**是赋值或 `= 0` 重置，
  **零个读站点**（`_maybe_compact_locked` 从磁盘读尺寸）—— 所以「删除」这条路的证据是完整的，
  不存在被遗漏的读依赖；`_replay_latest` 的返回元组第二元素（`:244` 签名、`:269`/`:274`/`:322` 三处
  `return …, journal_bytes`）在删除后会变成只写，应当一并收窄。
- `I-000203`：`src/bili_asr/manifest.py:513-526` — `_replace_snapshot(current)` 后
  `_remove_journal()`；`:496-503` 的 docstring 只记读语义。**seat-1 复核补充**：同一个「先发布、
  后丢弃」的窗口在 `compact()`（`:526-538`）与 `:721-722` 也各有一份，`save()` 不是唯一实例；
  该行的 acceptance 只点名 `save()`，所以**不要**顺手改另两处而不写明 —— 要么在本 plan 里具名一并处理，
  要么在 `## Out of scope` 里写明它们仍带着同一窗口。

## Approach

两个 Task：

- **Task 1（说真话，低风险，先做）**：修正 `coordinator.py` 两处 docstring 到实际契约（write-back 是
  best-effort、跑在 `_mark_archived` 之后、在 archive 成功守卫之外、其结果不改写行的 archived 结论），
  删掉「行数读者」这个不存在的机制断言；在 caption 写回调用点加局部 try，把非 `ValueError` 的 store
  故障按 ASR 侧同样的方式记为 skip 并返回（行的 archived 结论与账本 `archive: ok` 不变）。
- **Task 2（把三个窗口/策略一次决定）**：
  - `I-000196`：**选定单一策略并写在一处**（与 `AttemptLedger` 的分歧规则同址），并保证「替换过的
    key 绝不被 `save()` 写回快照」这条不变量成立；策略选择与拒绝理由写进任务记录。
  - `I-000202`：删除 `_journal_bytes`（连同赋值与 `_replay_latest` 返回元组的第二个元素）或就地
    文档化；`save()` 空路径的重置必须与「磁盘上可能还有撕裂 journal」的事实一致（先看它是否仍被
    任何读路径依赖）。
  - `I-000203`：关闭窗口（把丢弃条件绑定到「已发布的快照被观察为 durable」）或把前提写下来；
    两条路的取舍属 STOP 条件。

<!-- TODO(owner: architect): (a) I-000196 的策略选择 —— 严格解码（与 AttemptLedger 一致，代价是一个坏字节让 `load()` 在一个可 resume 的 SSOT 上失败）vs 替换但绝不写回；给出一条推荐并说明它在 resume 语义下的后果。(b) I-000203 的取舍：真关闭窗口（需要 durability 观察，成本与平台相关）vs 写明文前提（今天没有任何 `src/` 调用者用 `save(entries)` 形式）。(c) I-000193 的落点：加一条 attempt-ledger/ store 级可查询信号，还是把 gap view 的后果写成 tracked decision 并给出 owner。 -->

## 产品侧判定（seat-1 复核，2026-10-06 — 范围与后果的表述）

- **P6 — `I-000191` 的第二个断言位置写错了，而验收命令只覆盖第一个。** 初稿写「`:1373-1379`（同类断言）」，
  实测那段是 `_caption_language_from_entry` 的收尾与 `_caption_transcript_segments`（不涉及排序断言）；
  真正的第二处是 `:772-774`（`_record_asr_transcript` docstring 的 *"the manifest-side evidence the
  summary reads"*）。而该行的验收命令 `grep -n 'before the attempt ledger records'` 在全 `src/` 下
  **只命中 `:737` 一处** —— 也就是说：只跑这条命令，`:772-774` 那句「summary reads」的同类断言会**留在原地**
  而验收仍显示绿。**改法**：把见证扩成两条 grep（一条对 `before the attempt ledger records`，一条对
  `the summary reads`），或在 review-gate summary 里逐句列出两句的修订位置。
- **P7 — 这条缺陷的产品后果比初稿写的更重，值得写进行文（第 3 席请保留这个事实）。** `:737` 与 `:772`
  这两句 docstring 是**唯一**描述该处 R14 契约的文本；两句都会让下一个读者**推出一个不存在的约束**
  （「write-back 必须在账本之前」/「summary 数账本行」）。这不是措辞问题：R14 的调用点搬迁已经把顺序反过来了，
  而 `fully_processed` 数的是 `RowResult`（`RunSummary.fully_processed`）——**从来没有读者实现过**「账本行数」
  这个机制。也就是说，照 docstring 实现的下一个人会**制造**一个新缺陷。保持「修正到实际契约」这一目标不变，
  但请在 `## Problem` 里保留「会误导实现」这一句，而不是只写「说了假话」。
- **P8 — `I-000193` 有一个初稿没有写的产品后果，必须在收口前写明（不影响 Q1 的 owner/Blocking）。**
  `archived` 是终态（`process_row` 在 `coordinator.py:1071-1074` 提前返回），所以「写回失败的行」在**行的层面
  不可重驱**。把它修成「durable queryable signal」只解决 (a)；要满足 acceptance 的 (b)（re-drivable **或**
  把不可修复性写成 tracked decision），**必须**有一个具名的出口。若 architect 选「写成 tracked decision」，
  该 decision 需要 **owner + 触发条件**，否则这一行会在关闭后留下一个静默缺口（这正是 compass
  `## Roadmap Position` 的最终目标在防的那件事）。
- **P9 — B1/B2 共享 `coordinator.py`，且有一处会互相覆盖的判断。** B2 的 P6 要改 `:772-774` 的 docstring；
  B1 的 P5 要改 `:799` 的写入值（同一个函数 `_record_asr_transcript` 内）。两者都在该函数的 docstring/体内，
  按文件串行是必需的（初稿已在 `**Depends on**` 里写了「按文件串行合并」）—— 这里只是把**具体行**点出来，
  免得两个实施者在同一段里各改一半。

## Files

- **Modify**: `bilibili-asr-archive/src/bili_asr/coordinator.py`
- **Modify**: `bilibili-asr-archive/src/bili_asr/manifest.py`
- **Test**: `bilibili-asr-archive/tests/test_manifest.py`（或该模块既有测试文件）—— 解码策略、
  `save()` 窗口、`_journal_bytes` 移除后的读取面
- **Test**: `bilibili-asr-archive/tests/test_coordinator.py` —— 调用点吞没边界（注入 store 故障）

## Out of scope

- `src/bili_asr/sidecar_projection.py` 的严格解码行为 —— 它是本 plan 的**参照物**，不改。
- `AttemptLedger._replay_tail`（`coordinator.py:315-316`）的严格规则与其钉住测试 —— 不改。
- ASR 侧的 write-back 顺序 —— 属 B1 `I-000194`。
- `manifest.py` 的压缩阈值本身（`_JOURNAL_COMPACT_THRESHOLD` / `_JOURNAL_WRAP_BYTES_FACTOR`）——
  已由 plan `journal-compaction-lifecycle` 定过，本 plan 只处理 `_journal_bytes` 的只写状态。

## Verification gates

- **每个 Task 的 red→green 见证**：`I-000196` 的见证 = 在 journal 行 `work_id` 内注入一个孤立
  `0xFF`，断言所选策略的两个性质（fail-closed，或加载后**不**被 `save()` 写回快照）；
  `I-000192` 的见证 = 注入 store 故障后断言 exit 0 且行仍 `archived`；`I-000191` 的见证 =
  `grep -n 'before the attempt ledger records' coordinator.py` 为空（修复前非空）。
- **模块套件**：
  `PYTHONPATH=$PWD/src /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest bilibili-asr-archive/tests/test_manifest.py bilibili-asr-archive/tests/test_coordinator.py -q`
  （在 plan feature worktree 内执行）
- **无 schema migration**：`git diff --stat` 不得出现 `schema-*.sql` 的 DDL 变化。

## STOP conditions

- `I-000196` 的两条路若都无法在不破坏 resume 语义的前提下成立（严格会让可 resume 的 SSOT 因一个坏
  字节永久打不开，替换-but-不写回需要额外状态）→ STOP 并给出两条路的实测后果，由 PM 决策。
- `I-000203` 若需要平台相关的 durability 观察（fsync/目录 fsync 语义）而仓库没有既有工具 → STOP，
  改走「写明文前提」并在 Done criteria 里改验收形态。
- `_journal_bytes` 若发现仍有**读**路径依赖（例如某处用它判断是否需要压缩）→ STOP 并列出行号，
  不删。
- `coordinator.py` 的写回失败面若有本 plan 文件列表外的调用者 → STOP 并列出。

## Done criteria

- [ ] `I-000191` / `I-000192` / `I-000193` / `I-000196` / `I-000202` / `I-000203` 六行各自的见证在
      修复前失败、修复后通过（red/green 记录在 review-gate summary）。
- [ ] 上列模块套件通过；既有失败基线（动手前实测）不变。
- [ ] `grep -n 'before the attempt ledger records' bilibili-asr-archive/src/bili_asr/coordinator.py`
      退出 1（无匹配）。
- [ ] `git diff --check` 退出 0；`git status --short` 无本 plan Files 列表之外的文件。
- [ ] 六行全部经 store 关闭（`disposition = resolved`），closure evidence 指向本 plan 的修复提交。

## Drift check

`git diff --stat c59a1e6..HEAD -- src/bili_asr/coordinator.py src/bili_asr/manifest.py` —— 若任一
in-scope 文件已变，先重读 `## Current state` 的行号断言再动手。
