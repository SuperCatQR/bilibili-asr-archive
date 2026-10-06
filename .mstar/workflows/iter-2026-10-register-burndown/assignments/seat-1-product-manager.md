**Execution scope**: plan
**Execute as**: product-manager
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

这是 `iter-2026-10-register-burndown` 迭代的 Phase 1 §1.6 **Review & Edit 链第 1 席**（product-manager）。
方向已由 `/iteration-loop` 以 **autonomous** 路线锁定（记录在 `direction-lock.md`，五字段已落盘）。
你的职责是**产品范围与优先级**：审 PM 初稿的范围边界，把产品侧缺的上下文补齐，**就地编辑**这些文件：

1. `{ITERATION_DIR}/iter-2026-10-register-burndown/delivery-compass.md`
2. `{PLAN_DIR}/asr-run-record-integrity.md`（B1）
3. `{PLAN_DIR}/archive-writeback-durability.md`（B2）
4. `{PLAN_DIR}/verification-lane-contract.md`（B3）
5. `{ITERATION_DIR}/iter-2026-10-register-burndown/README.md`（按需）

三个 plan 文件的头部都带 `<!-- TODO(owner: architect): … -->` 标记 —— 那些**不是你的**，别动。
你要清的是 owner 指向 `product-manager` 的标记（本轮没有预置；若你新增，必须自己在同一轮清掉或显式
重新归属给 PM 并写明理由）。

## 产品侧的具体判定点

- **`## Acceptance Criteria` 与 `## Non-Goals`**：逐条读，确认每一条都能被一个承接方独立判定真伪；
  非目标每条都有理由，且理由不是「没时间」。
- **行选择的产品相关性**：21 个目标行是否真的是「值得这个迭代修的缺陷」？有没有哪一行其实是
  产品决策（需要 owner 而不是代码）？若有，把它从 plan 的 Captured issues 里移出、写进 compass
  `## Roadmap Position` 并给 owner。
- **`I-000041`（high）**：PM 初稿把它列为「store 内 `acceptance` 字段即 `defer`」而排除。请**核实**
  这个字段的原文（`{HARNESS_DIR}/store.db` 的 `issues.acceptance`），若原文并非一个明确的延期决定，
  你就必须改这条判断：要么把它纳入范围（并说明谁的计划容纳它），要么在 compass 里把排除理由写成
  你核实到的事实。
- **`I-000210` / `I-000211` 的产品后果**：B3 把「匿名 run 不得满足空清单 corroboration」当成缺陷。
  请判定：修掉它之后，**匿名机器**上的操作者会看到什么变化（例如某个 part 永远无法被确认耗尽）？
  如果这个后果需要一个产品决定（而不是实现者自己选），在 compass `## Open Questions` 落一行并给
  owner，或写成 `## Decisions` 的一条已决事项。
- **`## Roadmap Position`**：Current / Next / 最终目标三段是否都能被下一个迭代的 PM 直接采用？
  Next 里的每一项是否都有 owner 与触发条件？
- **Q1 / Q2 两行 Open Questions**（B2 的 `I-000193` 落点、B3 的 `I-000211` 落点）：确认 owner 是
  `architect` 且 `Blocking? = No`。若你认为其中任一条**应当**是 blocking，现在就写上——`Blocking? = Yes`
  的行必须在 lock 前收敛，不能留给下一位。

## 边界（HARD）

- **不得**向 `{KNOWLEDGE_DIR}/` 新增任何文档（知识新增只在 Phase 3 `mstar-compound`）。
- **不得**写 `{SPECS_DIR}/`（全局 specs 在 Phase 3 提升时写入）。
- **不得**编辑 `direction-lock.md` 的五个锁定字段（范围、验收、非目标、预算、分支策略中已被 operator/
  命令层固定的部分）；你要改的是**初稿**，不是 lock 记录。
- **不得**创建 worktree、切换分支、commit 或 push。
- 措辞与排版不是你的职责（第 3 席是 writing-specialist），你只管产品判断与上下文完整性。

## Return（Completion Report 必须含）

- 你改动的文件清单（逐文件一行，说明改了什么产品判断）。
- **Marker 清除计数**：已清 N / 已重新归属 M（本轮应为你自己新增的那些）。
- `I-000041` 的核实结论（`acceptance` 字段原文 + 你的判定）。
- 任何你认为 PM 初稿**判错**的产品侧判断，直接写出来并给依据——不要为了让文稿好看而沉默。
