**Execution scope**: plan
**Execute as**: writing-specialist
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

这是 Phase 1 §1.6 **Review & Edit 链第 3 席**（writing-specialist，链尾）。前两席
（product-manager、architect）已按序跑完，你读到的就是它们的成果。

你的职责有**三件**，第三件是链尾的**收口核对**，也是 PM 置 `status: locked` 的前置：

### 1. 行文与结构（corpus hygiene）

- 读 `mstar-iteration/references/iteration-corpus-hygiene.md`（本席的细则 SSOT）并按它执行。
- `iterations/iter-2026-10-register-burndown/` package 的卫生：`delivery-compass.md`（canonical，
  不得另写根目录 flat 文件）、`direction-lock.md`、`README.md`（索引：guides/specs 归属）、
  `specs/` 下若有草案则标明 draft vs locked。
- **错放纠正**：若发现本迭代的草案被写进了 `{KNOWLEDGE_DIR}/` 或全局 `{SPECS_DIR}/`（**不得**发生），
  迁回 package 并在 README 登记 `Promotion candidate:`，留待 Phase 3 统一处置。
- `{ITERATION_DIR}/README.md`（根索引）是否需要一行 —— 需要就给一行（一次迭代 = 一行，目录链接，
  **不是** compass + workspace 双行）。
- 三个 plan 文件（`{PLAN_DIR}/asr-run-record-integrity.md`、`archive-writeback-durability.md`、
  `verification-lane-contract.md`）的行文一致性：与仓库既有 plan 的既定形态对齐
  （frontmatter 字段、`## Status` 块、`## Problem` / `## Current state` / `## Approach` / `## Files` /
  `## Out of scope` / `## Verification gates` / `## STOP conditions` / `## Done criteria` / `## Drift check`）。
  **参照物**：`{PLAN_DIR}/caption-exhaustion-attestation.md`（bug 类，最新形态）与
  `{PLAN_DIR}/journal-compaction-lifecycle.md`（sdd 形态）。

### 2. Marker 收口核对（**链尾唯一职责**）

遍历四个文档（compass + 三个 plan）与包内所有文件，按 §1.3 的唯一语法：

```text
<!-- TODO(owner: <role-id>): <what is missing and what must be decided> -->
```

统计并**报出**：除**显式重新归属给 `PM`** 的标记外，**无**标记残留。若有残留且 owner 是
`product-manager` / `architect` / `writing-specialist`，你不能静默删除 —— 你只能：(a) 若你有能力清除，
清除它；(b) 否则显式重新归属给 `PM` 并写明理由，并在 Completion Report 报出重新归属的条数。
**无 owner 的 `TBD` / `...` / `etc.` 在任何阶段都禁止** —— 发现即按 (b) 处理并在报告里点名。

### 3. 可读性复核（不改判断，只改可读性）

- 确认 compass 的 `## Scope` / `## Acceptance Criteria` / `## Non-Goals` / `## Roadmap Position` /
  `## Delivery Branch Policy` 五节都能被一个**没有本会话上下文**的承接方读懂。
- 确认三个 plan 的 `## Current state` 里每个行号引用都指得出去（文件 + 行号），没有「如上所述」这类
  依赖会话的指代。
- 中文/英文混用的既定风格保持一致（正文中文、代码与标识符英文、契约原文引英文）。

## 边界（HARD）

- **不得**向 `{KNOWLEDGE_DIR}/` 新增任何文档 —— start 链的新增只在 Phase 3 `mstar-compound`。
  既有知识文档也**不**由你修改（冲突已在第 2 席指认，处置属 Phase 3）。
- **不得**写全局 `{SPECS_DIR}/`（Phase 3 提升时写入）。
- **不得**改动 `direction-lock.md` 的五个锁定字段。
- **不得**改产品判断（第 1 席的职责）或架构判定（第 2 席的职责）—— 你改行文与结构；若你发现某个判断
  在文字上不成立，写进 Completion Report，由 PM 处置。
- **不得**创建 worktree、切换分支、commit 或 push。

## Return（Completion Report 必须含）

- 你改动的文件清单（逐文件一行）。
- **Marker 收口核对结论**（必填）：残留标记总数（除重新归属给 PM 的以外应为 0）、已清 N、
  已重新归属给 PM 的 M（逐条列出 owner 与理由）。
- `{ITERATION_DIR}/README.md` 是否新增一行（是/否 + 内容）。
- 错放文件的迁回记录（若无，写「无」）。
- 任何你认为**判断**有问题的点（不在你职权内，但要报出来）。
