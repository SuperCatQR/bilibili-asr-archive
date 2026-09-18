---
iteration_id: iter-2026-09-text-and-ledger-precision
title: "Cue-writer Latin spacing and the six homophone hotwords measured by A/B; the pilot attempt-ledger boundary written down and an interrupted run recorded — the four residuals the previous iteration deferred, adopted with their Phase-1 work already reviewed"
status: locked
start_date: 2026-09-18
iteration_base_branch: main
spec_integration_branch: iteration/iter-2026-09-text-and-ledger-precision
target_branch: main
effort_scale: M
plans:
  - 20260918-transcript-text-precision
  - 20260918-operational-record-coverage
---

# iter-2026-09-text-and-ledger-precision Delivery Compass

## Scope

Adopts the two plans that `iter-2026-09-residual-closeout` locked at Phase 1 and then deferred on
2026-09-18 when its scope was reduced to one plan. **Both plan files already carry a completed
specify/clarify/plan and passed the three-role review chain in that iteration**; this iteration
re-points their iteration-package references and re-verifies them as a set, then executes them.

**This iteration did not do that Phase-1 work, and does not claim it.** What it inherited verbatim:
both plans' `**Goal:**`, `**Architecture:**`, Global Constraints, task steps and run commands, and the
review verdicts on them. What *this* iteration's own Phase-1 chain adds is only: (a) the adoption itself
— re-pointing the plans' iteration-package references from `iter-2026-09-residual-closeout` to this
package; (b) **criteria 1–4 below**, renumbered onto this compass's own numbering so the plans'
closure duties are checkable without reading a closed iteration's package; (c) the serial scheduling
decision and its corrected file-overlap basis (see `## Plans` §Scheduling); and (d) the re-pointed
deferral records in `## Non-Goals` / `## Roadmap Position`. No technical content of either plan is
re-derived here, and `{SPECS_DIR}` gains nothing (see §Adopted assets).

| Residual | severity | 问题 | 本迭代的处置 | 收口判据 |
|---|---|---|---|---|
| `e2e-23191782-season-7686105 · R6` | low | cue 内拉丁词粘连（`asME IDEA`、`anITEM`）：`_token_cues` 用 `"".join(parts)` 拼接，补空格的 `_join_text` 只在吸收碎片与交还标点两处调用 | 在 cue 内拼接处应用同一空格规则，且**不破坏 pinned fixture 的字节**；用省略前导空格的 token 流钉住 | 1 |
| `e2e-23191782-season-7686105 · R3` | low | 六个中文同音热词（扬弃 自在 变易 此在 感性 实存）的**收益未验证**（错误已实测 118 处） | 按其 residual 自身规定的靶子做 A/B（`BV1H69sB6EeF`，4 正确 vs 57 误写），以计数对比关闭或据实保持 open | 2 |
| `e2e-23191782-season-7686105 · R4` | low | `pilot` 不写 stage attempts，`--scope failed` 对 pilot 归档的条目失明（实测 `stages=[]`） | **写下边界**（README + `pilot --help`），消除"静默丢弃"；知识库文本经 compound 提升 | 3 |
| `e2e-23191782-season-7686105 · R5` | low | 被外部 kill 的 `run` 不留 run-ledger 记录（全仓无任何信号处理） | **实现** SIGTERM/SIGINT 处理：追加一条含局部计数的 run 记录后按约定中断码退出，用测试锚定 | 4 |

## Plans

| plan_id | Name | Status | 覆盖 residual | 收口判据 | Notes |
|---------|------|--------|---------------|----------|-------|
| `20260918-transcript-text-precision` | Cue-writer Latin spacing; hotword benefit verified | Todo | R6 + R3 | criteria 1, 2 | 含操作员归档主机上的一次 A/B 测量（同一音频、两条热词清单的文本对比） |
| `20260918-operational-record-coverage` | Pilot attempt-ledger boundary; interrupted-run record | Todo | R4 + R5 | criteria 3, 4 | 一条是**成文**（R4，不改行为），一条是**实现**（R5） |

Criteria are numbered **1–4** here and nowhere else in this package. The previous iteration's
numbering (6–9, in `iter-2026-09-residual-closeout/delivery-compass.md`) is **retired**: it was a
property of that iteration's 11-criterion set, not of the two plans, and no artifact of this iteration
may cite it. The plans' own in-body `(criterion N)` / `(compass criterion N)` cross-references were
re-pointed onto this numbering on adoption (plan 1: 6→1, 7→2; plan 2: 8→3, 9→4).

Status values: `Todo` | `InProgress` | `InReview` | `Done` | `Blocked`

### Adopted assets and what changed on adoption

- Both plan files are unchanged in substance — `**Goal:**`, `**Architecture:**`, Global Constraints,
  every task step and every run command are the ones the previous iteration locked and reviewed. Only
  their iteration-package references were re-pointed from `iter-2026-09-residual-closeout` to this
  iteration (6 references: the 2 guides they write, the 2 pointer paths in their Global Constraints, and
  the 2 criteria-citation blocks), plus the criterion numbers inside those citations.
- Their acceptance criteria are **renumbered into this compass** (1–4 below, table above); the previous
  compass's numbering (6–9) is retired with it.
- No new spec is written at this iteration's Phase 1: the two plans' contracts are fully stated in their
  own `**Requirements**`/`Interfaces` sections, and the one durable contract this work produces — the
  cue-writer rule — is captured in the pinned fixture plus the Task 1 brief.

### Scheduling

**plan order: `20260918-transcript-text-precision` → `20260918-operational-record-coverage`**, serial.
Reason, stated explicitly because it is not a technical dependency: **the two plans do not overlap on a
single file.** Read from their own `Files:` lists — plan 1 modifies `src/bili_asr/asr.py` and
`tests/test_asr_cues.py` (plus a fixture under `tests/fixtures/asr-cues/`, an A/B driver on the target
host outside the repository, and a guide in this package); plan 2 modifies `src/bili_asr/cli.py`,
`README.md`, `tests/test_run_ledger.py` and `tests/test_coordinator.py`, and optionally
`src/bili_asr/run_ledger.py`. `cli.py` is plan 2's alone; `asr.py` is plan 1's alone. There is therefore
**no same-file conflict to isolate and no integration hunk to cross-check** — the only shared resource is
this iteration's `guides/` directory, and each plan writes a distinct file in it. Serial is still the
choice, for two reasons that are about sequencing rather than safety: (i) both plans touch a shared
product surface only through their own files, but plan 2 changes `cli.py` while plan 1 changes the text
shaper that feeds the transcripts plan 2's A/B would not exercise — running them one at a time keeps the
integration tip settled for each QA wave; (ii) the plans together are ~1 S + 2 M of work, so a single
serial branch is cheaper than the worktree/lease machinery L1/L2 parallel writable tracks would need.
No plan blocks the other technically, and no merge-order dependency is claimed where none exists.

*(Corrected at this iteration's Phase 1: the draft asserted both plans "change `asr.py` and `cli.py` in
disjoint regions". They do not both change either file — the two-disjoint-regions-of-`cli.py` situation
was `iter-2026-09-residual-closeout`'s plan 1 vs plan 3, not this pair.)*

*(Re-verified after this iteration's Phase-1 review-and-edit pass, on `main` = `1cc1b2a`: the overlap
claim above was read back off both plans' corrected `Files:` rows, which carry the line anchors as
re-pointed to this tip. It still holds — plan 1's in-repo writes are `asr.py`, `tests/test_asr_cues.py`
and a fixture under `tests/fixtures/asr-cues/`; plan 2's are `cli.py`, `README.md`, two test files and
optionally `run_ledger.py`. The serial order and its two stated reasons are unchanged, and no
merge-order dependency is claimed.)*

## Milestones

| Milestone | Target date | Status |
|-----------|-------------|--------|
| Spec freeze (Phase 1 lock) | 2026-09-18 | pending |
| Dev complete (2 plans Done) | 2026-09-18 | pending |
| QC complete | 2026-09-18 | pending |
| Iteration close | 2026-09-18 | pending |

## Acceptance Criteria

> 判据编号 **1–4**，与 `## Scope` / `## Plans` 的表格互为索引。每条都给出**第三方可独立复核的观察面**：
> 要跑的命令、要读的文件、或要看的字节。命令的工作目录同两个 plan 的约定——Python / CLI / pytest 从
> **包根** `/root/workspace/bilibili-asr-archive/bilibili-asr-archive` 运行，`git` 与仓库相对路径从
> **仓库根** `/root/workspace/bilibili-asr-archive` 运行。
> 本包内**不存在**引用上一迭代（`iter-2026-09-residual-closeout`）包内路径的判据；闭环证据一律落在
> **本迭代**的 package、本仓测试文件或产品面（`README.md`、`pilot --help`）。

1. **cue 粘连消除，且 pinned fixture 不变**（`R6`）：一份 token 流省略前导空格的 fixture 下，`_token_cues`
   产出的 cue 文本在两个 ASCII 字母数字之间含空格，且**只在模型自己的识别文本已带该分隔符时**补——字符类
   条件单独成立不得补空格（单条件规则已实测会把 `tribunal`/`token`/`deepseek`/`NGO` 切成碎片）。
   `tests/fixtures/asr-cues/BV1wLTP6NE9h.p0.tokens.json` 与 `tests/test_asr_cues.py` 的既有期望**字节不变**；
   中文文本、cue 边界/数量/时间戳均不动。可复核（两条命令并列，都要满足）：
   ```bash
   cd /root/workspace/bilibili-asr-archive/bilibili-asr-archive && .venv/bin/python -m pytest tests/test_asr_cues.py -v
   cd /root/workspace/bilibili-asr-archive && git diff --stat -- bilibili-asr-archive/tests/fixtures/asr-cues/ && git diff --stat -- bilibili-asr-archive/tests/test_asr_cues.py
   ```
   第二条须**无输出**。锚定：`tests/test_asr_cues.py` 新增用例 + 既有 pinned-fixture 用例全绿。
2. **热词收益有测量，且按跑前写定的规则处置**（`R3`）：证据文件必须落在**本迭代** package 的
   `guides/hotword-ab-20260918.md`（plan 1 Task 2 Step 6 的产物），且必须同时含三侧：
   - **收益侧**：`BV1H69sB6EeF:p0`（114.5 min）两臂 GPU 转写并列的六个词**逐字计数**——`扬弃` vs
     `阳气`/`洋气`、`自在` vs `子在`、`变易` vs `变异`、`此在` vs `次在`/`词在`、`感性` vs `感兴`、
     `实存` vs `时存`；
   - **代价侧**：两臂文本相同字符率（确认阈 ≥95 %，即全局差异 ≤5 %）、cue 数、`asr_mean_confidence`、
     `asr_low_confidence_cues`；
   - **身份侧**：从两臂产物 md frontmatter 读回的两条 `asr_hotwords` 差异**恰好等于那六个词**（从产物证明，
     不从调用命令证明）。
   `R3` 按 plan 1 Task 2 Step 5 的**跑前写定**规则处置：确认 → 关闭；无实质差异 → 据实保持 open 并写明
   "该证据下无收益"；反证 → 向 PM 提移除建议（移除不是本迭代的改动）。**只跑一臂、或用季节运行的旧数字
   充当另一臂，都不构成收口证据**；主机或模型缓存不可用时如实记为 **not-run** 且 `R3` 保持 open。
   可复核：读该 guide 的方法与两臂产物；`asr.py` L156-161 是词/同音表的可核对来源。
3. **pilot 边界成文，且落在本迭代允许写入的面**（`R4`）：可复核（同一 cwd，包根）：
   ```bash
   cd /root/workspace/bilibili-asr-archive/bilibili-asr-archive && .venv/bin/python -m bili_asr pilot --help | grep -n -- "--scope failed"
   cd /root/workspace/bilibili-asr-archive/bilibili-asr-archive && grep -n -- "--scope failed" README.md
   cd /root/workspace/bilibili-asr-archive/bilibili-asr-archive && .venv/bin/python -m pytest tests/test_cli_help.py -q
   ```
   第一条须出预期行（修订前实测无输出且 exit 1，故该检查有区分度）；第二条须在退出码表旁那段 recovery
   文本里出现 pilot 边界（**该段既有的 `run --scope failed` 提及不算数**）；第三条全绿（help 文本改动不得
   破坏其断言）。知识落点文本落在**本迭代** package 的 `guides/pilot-attempt-ledger-boundary.md`，由
   `mstar-compound` 在收口时提升；`{KNOWLEDGE_DIR}/**` 在本迭代内**不被直写**。
4. **中断留痕**（`R5`）：向 `run` 发送 SIGTERM 后，`run-ledger.jsonl` 出现**恰好一条** `command: "run"`
   记录，含已完成的局部 `work_ids` 与退出码 `143`；进程以 `128+signum` 退出（SIGTERM 143 / SIGINT 130），
   **不获取/不释放/不改写归档锁状态、不重排工作、不改 manifest**；第二次信号不产生第二条记录、不产生半行；
   随后同一归档根能正常开始下一次 `run`。锚定（两条都跑）：
   ```bash
   cd /root/workspace/bilibili-asr-archive/bilibili-asr-archive && .venv/bin/python -m pytest tests/test_run_ledger.py tests/test_coordinator.py -k "interrupted or partial or ledger" -v
   cd /root/workspace/bilibili-asr-archive/bilibili-asr-archive && .venv/bin/python -m pytest tests/test_coordinator.py -k run_appends_run_ledger -v
   ```
   中断子进程用例须以子进程 stdout 的 `run: scope=… selected N row(s)` 为同步点（不用 sleep），正常退出的
   记录保持今天的字段值逐字不变。**不依赖人工观察。**

## Non-Goals

- **`e2e-23191782-season-7686105 · R1`（medium，`.db` → manifest 无桥接）仍不在本迭代范围**——它需要"哪套存储是 ASR 队列 SSOT"的规格决策，与本迭代四条小修异构。本迭代既不为它写代码、也不为它写规格；它继续以 `open` + `decision: defer` 留在 register 里。见 Roadmap Position。
- **上迭代 QC 新开的 3 条 low**（`20260918-verification-surface-truth` 的 R1/R2/R3：潜伏判定、投影重复、符号链接父目录）**不在范围**；它们是低优先级技术债，各自带有明确的重开条件。三条逐条登记在下方 Roadmap Position，含触发条件、owner 与完成定义。
- **不新增、不删除、不重排热词**：只**验证**已有六个中文热词（`R3`）的收益与代价；`DEFAULT_HOTWORDS` 的词条集合与顺序在**提交中**不变。A/B 的"无热词"臂由**临时未提交**的改动产生，任务收口前必须还原，并以后两臂产物 md frontmatter 的 `asr_hotwords` 读回 + `git status --porcelain` 干净为证（plan 1 Global Constraints）；泄漏进提交的临时改动即为一次静默的热词变更，属越界。反证情形下的**移除建议**只是建议。
- **不改冻结契约**：`coverage` 的 CSV 列（含 `denominator_*` 四列）、两个 `schema_version`、质量词表两类（defect / content）、`REASON_CODES` 顺序均不变；上迭代刚落地的良构判定（`ORDINARY_HISTORY_DIAGNOSTICS` 及其三处具名读取者：`integrity.py`、`coverage_report` 的 build 路径、`cli._cmd_coverage_quality`）与那三处读取者不动。`verify` 的退出语义沿用上迭代恢复后的含义，本迭代不重开。
- **不宣称真实环境 E2E——本迭代的验证边界，逐条写死**：
  - 判据 2 的 A/B 是**解码配置的本地集成测量**（操作员自己的归档主机、仓库自身的 venv），其证据只用于判据 2（`R3`），不用于任何其他判据；
  - 它**不是**浏览器 / 真机 / 安装部署 E2E，也不作为任何 plan 的 task 或门禁的证据义务（`mstar-harness-core` § 定向执行与验证边界）；该类验证的唯一落点是用户显式启动的独立 `mstar-e2e` workflow；
  - 主机或模型缓存不可用时，如实记为 **not-run**，`R3` **保持 open**；不得用季节运行的既有数字顶替缺失的那一臂（判据 2 末句）。
- **不做宿主插件（dsh web 面板）相关的浏览器验收。**
- **不写知识库**：`{KNOWLEDGE_DIR}/**` 在本迭代内**不被直写**；`R4` 的知识文本经 package → `mstar-compound` 在收口时提升（plan 2 Global Constraints 与 Task 1 的 Out of scope 已排除该知识文件）。
- **不碰上一迭代的闭环记录**：`{ITERATION_DIR}/iter-2026-09-residual-closeout/**` 是已关闭的 ledger，本迭代只把它当作延出决定的权威来源引用，不修改其中任何文件（含其 compass 与 specs）。

## Roadmap Position

- **Current iteration（iter-2026-09-text-and-ledger-precision）**：关闭上迭代延出的 4 条（R6/R3/R4/R5）——让归档**文本**（cue 写入器、热词）与运行**记录**（attempts、run-ledger）都不再对操作员说谎或留空；这也是对上迭代"缩减范围"的兑现。完成定义即判据 1–4，逐条给出可复核命令。
- **Next iteration（延出项按到期日排序，各自的触发条件 / owner / 完成定义都写死给没有本次对话的读者）**：

  **① `e2e-23191782-season-7686105 · R1` — 让 ASR 链从 `archive.db` 取音频工作队列**（medium）。
  - **触发条件**（满足任一即开 Prepare）：(i) 本迭代 Phase 6 收口之后；或 (ii) **下一次要跑新语料的 ASR 之前**——今天每次语料运行都必须手工造 manifest（季节 E2E 用的是目标机上的 `/root/e2e-asr/tools/seed_season.py` 脚手架，不在仓库内、不受支持），所以"下一次语料运行"就是它的实际到期日。
  - **owner**：`project-manager` 开 Prepare 并登记 plan 行；Prepare 阶段由 `@product-manager` / `@architect` 先收敛"哪套存储是 ASR 队列 SSOT"的规格，再进 Execute。
  - **完成定义**（可复核，不是"跑通一次"）：`docs/metadata-storage.md` §Boundary 已命名的三件事全部落地——从 SQLite 枚举音频工作队列、从存量转写重建 SRT/TXT/MD 投影、让旧音频 feeder 重新有源；**一条命令**即可从 `archive.db` 生成 ASR 队列而无需手工 manifest，且队列内容与 `video_parts` 中标记为待转写的 parts 集合一一对应（由集成测试锚定，测试文件与命令写进该 plan）；既有 manifest 路径**要么明确保留、要么明确下线，不留双写**；register 该条关闭时 `closure_evidence` 指向该测试与 plan。

  **② `20260918-verification-surface-truth · R1`（low，潜伏的第二处判定）**——`coverage_report._read_manifest`（L322-324）仍写着 `manifest_duplicate_work_id` 字面量并把 `valid = False`，即"把追加式状态历史当 malformed"。今天不可达（零调用点）。
  - **触发条件**：任何计划或触碰**给 `_read_manifest` 加上一个调用点**——那一刻该缺陷立即复活（re-open condition 是显式的）。
  - **owner**：`project-manager`（在触发它的那个 plan 内登记，或独立开轮）。
  - **完成定义**：**删除该 helper**。接线不是便宜修法——qc3-S5 实测它保留重复 work_id 的**第一行**而活路径保留**最后一行**、投出 tuple 形 `(code, kind)` 诊断而读取者按字符串相减、且无界读（无 `ReaderPolicy`）；任何接线都必须经 `iter_jsonl_records` 重新推导投影，而不是仅查具名集合。

  **③ `20260918-verification-surface-truth · R2`（low，投影重复）**——manifest/attempt 投影在 `CoverageReport.build`（`coverage_report.py` L65-105）与 `cli._cmd_coverage_quality`（`cli.py` L1265-1287）之间逐字重复，同一个 ordinary-history 码要在两个文件里各记一次，是当初三读取者互相矛盾的结构性成因。
  - **触发条件**：任何**触及任一 coverage 入口点**的 plan 即纳入（这是它的实际到期日——改一处而忘记另一处正是它描述的风险）。
  - **owner**：`project-manager`。
  - **完成定义**：派生**一次**投影、两个调用者共用，且 ordinary-history 的相减动作落在共享路径内部；两处的旧副本删除而非保留；由 `tests/test_coverage_report.py` 与 `tests/test_cli_help.py` 的既有 coverage 断言在新结构下全绿锚定。

  **④ `20260918-verification-surface-truth · R3`（low，符号链接父目录）**——取证钩子的日志路径仍可经**被符号链接的父目录**写入：`O_NOFOLLOW` 只拒绝最后一段是符号链接的情形，预先存在的符号链接目录 `bilibili-asr-archive/.tb/` 会被跟随。影响有界（仅测试路径、固定文件名、写入端已拒绝符号链接文件）。
  - **触发条件**：任何**触碰 `tests/conftest.py`** 的 plan，或拥有"测试基础设施加固"的那个 plan。
  - **owner**：`project-manager`。
  - **完成定义**：加 `lstat` 预检（拒绝符号链接的 `.tb/`），或以 `O_NOFOLLOW|O_DIRECTORY` 打开目录后再追加；`conftest.py` 内的注释相应更新，使后来者不把该 flag 读成"已完全保证"。

  **⑤ 调度与归属的总纪律**：②③④ 是低优先级技术债，**不阻塞任何交付**，各自带显式重开条件，可**随任意触及相应文件的 plan 一并处理**（上列触发条件就是按"会被哪类改动激活"写的）；若长期无 plan 触及，它们没有独立的到期日，也不应被提升为单独迭代的范围——`R1`（①）才是下一个应当成篇的迭代。
- **最终目标**：语料从采集到转写归档为**单一可信链路**——元数据、音频队列、转写产物与运行记录同源，且每一条交付都有可复核证据。

## Delivery Branch Policy

| Field | Value |
|-------|-------|
| `iteration_base_branch` | `main` |
| `spec_integration_branch` | `iteration/iter-2026-09-text-and-ledger-precision` |
| `target_branch` | `main` |

来源与理由：仓库 `AGENTS.md` 写明 *Default integration / PR target: `main`*、*Feature work: plan branches merging into `iteration/<iteration-id>`*；上两个迭代同形。属**成文项目约定**，非静默默认。

**Main worktree branch**：`main`。

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| cue 修复再次破坏 pinned fixture（上迭代已实测过：字符类规则会切碎单词，4/95 cue 受损） | Med | Med | 判据 1 强制 fixture 字节不变；计划 Task 1 已写明"两条件规则"（类规则 **且** 模型自身文本含分隔符），并给了 split point：若夹具把粘连形式当成期望，停下回报 PM |
| A/B 依赖目标主机与模型缓存在位 | Low | Med | 前置条件已在计划中改为**可执行的检查**（`test -x /root/e2e-asr/tools/ab.sh`、`test -d /root/e2e-asr/ab-hotwords`，逐条记录输出；该路径不在本仓，属目标归档主机）；缺失则先补驱动或如实记为 **not-run**，`R3` **保持 open**，不伪称通过 |
| "无热词"臂是临时未提交改动，泄漏进提交即为一次静默的热词变更 | Low | High | 该臂只由两臂产物 md frontmatter 的 `asr_hotwords` 读回证明（不比调用命令）；收口前要求 `cd /root/workspace/bilibili-asr-archive && git status --porcelain` 无输出 |
| SIGTERM 处理与 archive 单写者锁交互 | Low | High | 计划 Global Constraints 明确：只追加一条记录后按原语义退出，不获取/不释放锁；处理函数一次性且抛 `BaseException` 子类（`Exception` 会被 coordinator 逐阶段 handler 吞掉）；写期间两信号置 ignore；以 `SystemExit` 呈现 128+signum；用 subprocess 用例锚定，并验证随后能正常开始下一次 run |
| 中断子进程测试靠 sleep 同步 → 偶发假绿/假红 | Med | Med | 同步点写死：子进程在批次开始前打印 `run: scope=… selected N row(s)`（cli.py L2304），测试读到该行后才发信号，且 fixture 行数要保证此刻批次确实仍在进行；若进程在信号前已正常结束，断言（rc 0 ≠ 143）必须**响亮失败**，不加容差 |
| 中断路径没有 summary 对象，局部计数拿不到 | Med | Med | 计数来源为已存在的持久真相：`AttemptLedger.load()` 中 `started_at >= 本次 run 起点` 的 attempts + `compute_coverage_summary(store.load())`，`records_existing` 仍是 manifest 行数 `len(entries)`（与正常路径 cli.py L2332 逐字一致，**不是** attempts 长度），只读；复用既有 `build_run_record`，不新增第二个构造器，`exit_code` 任意 int 均可通过 `_validate_record`，无需 schema 变更 |
| 采纳的 plan 带有上一迭代的假设（如行号） | Med | Low | **本次 Phase 1 复核已逐条走过树并修正**（两个 plan 的 `Files:` / run command / 行号锚点在 `main`=1cc1b2a 上重新核对；先前的计划确实写在 `iter-2026-09-residual-closeout` 的树上）。Execute 期若再漂移，按上迭代的做法先回写 plan 再继续 |
| **plan 2 Task 2 的 split point 曾被误记为"2b 依赖 2a 的 helper 签名"** | — | Low | **已在本轮 settle**：seam 签名 `_partial_run_state(root, started_at)` 就钉在 plan 文本里，两侧对着同一冻结接口写，故 2a/2b **order-free**；已改写在 plan 的 Split point。任何后续文档若重新出现"2b 依赖 2a 签名"的说法，即为对该结论的回归 |
| **plan 1 的 cue 表曾用错 cue 编号**（草稿写 2/34/37/55，实测 3/35/38/56） | — | Med | **已在本轮修正并复现**：字符类规则实测恰好改 4 of 95 cue，编号与文本均已按 `main`=1cc1b2a 的 pin fixture 更正。该表的用途是论证"单条件规则会切碎单词"，编号错了会误导实现者去核对不存在的 cue；实现时以 Step 1 的实测为准，不以本表为准 |
| **plan 1 Step 2 的第二个用例在改动前就已经绿**（`tribunal` 原样正确） | Med | Low | **已在本轮写明**：它是 guard 而非 failing test；Step 3 的 "expect FAIL" 只适用于第一个 separator 用例。若实现者把它当 failing test 而改测试去迎合实现，正是"切碎单词"的回归路径 |
| **plan 2 的 `_partial_run_state` 第三个返回值语义歧义**（`records_existing` 是 manifest 行数 ≠ attempts 数） | Med | Med | **已在本轮写明**：helper 不重读 manifest 记该字段，run body 传 `records_existing=len(entries)`（cli.py L2332），与正常路径逐字一致；helper 若返回 attempts 长度会同时破坏"正常路径字节不变"与 ledger 内跨记录一致性 |
| **两个 plan 的 `Files:` 面被误记为有交集**（草稿曾称二者都改 `asr.py` 与 `cli.py`） | — | Low | **已在本次 Phase 1 修正**：plan 1 独享 `asr.py` / `tests/test_asr_cues.py`，plan 2 独享 `cli.py` / `README.md` / `run_ledger.py`（可选）/ 两个测试文件，交集为空，故无集成 hunk 需交叉核对、无同文件冲突需隔离（见 §Scheduling）。保留此行为记录：任何后续文档若重新出现"两 plan 改同一文件"的说法，即为对本表的回归 |

## Iteration package

| Path | Purpose |
|------|---------|
| `guides/` | `hotword-ab-20260918.md`（plan 1 Task 2 写）、`pilot-attempt-ledger-boundary.md`（plan 2 Task 1 写，经 compound 提升） |
| `specs/` | 空——本迭代无新的迭代级规格（见 Scope 说明） |
| `README.md` | Package document index |

## Phase 1 review chain (§1.6)

Three specialist roles invoked in order, one invoke each, editing the artifacts directly:

| # | Role | Findings | Highlights |
|---|------|----------|------------|
| 1 | `product-manager` | 5 (2 high) | **F1** the draft framed the adoption as if this iteration had done the Phase-1 work (and the package README claimed a lock that had not happened); **F2** the retirement of criteria numbering 6–9 was stated but never propagated — both plans' `Closes:` lines and three in-body citations still pointed at retired numbers; **F3** the scheduling justification asserted an `asr.py`+`cli.py` overlap the plans **contradict** (that was the previous iteration's plan-1-vs-plan-3 situation, imported by mistake) — corrected against the plans' own `Files:` lists; **F4** the three low deferrals lacked trigger/owner/done-definition; **F5** two criteria were missing their gates. |
| 2 | `architect` | 7 substantive | The drift was real and material, exactly where predicted: **plan 1's cited cue numbers were wrong** (2/34/37/55 hold unrelated text; the real ones are 3/35/38/56), **five `cli.py` anchors had shifted**, one test was **mislabelled as failing** when it already passes (a guard, not a failing test), `records_existing` was ambiguous (it is the manifest count, not the attempts length), and Task 2's split point was **order-free**, not dependent. It re-derived plan 1's "4 of 95 changed" claim (correct) and its two-condition rule (0 changed, fixture byte-identical), ran six `--collect-only` selectors, and verified the `asr.py`/`coordinator.py`/`run_ledger.py`/test anchors as already exact. |
| 3 | `writing-specialist` | 2 corrected, 1 reported | The compass overstated its own re-pointed reference count (5 → **6**), and plan 1 said "the six hotwords" where the corpus has **two** six-hotword sets from 2026-09 (the six *Chinese homophone* ones are this plan's subject; the six *Latin-script* ones belong to `20260912-gpu-enablement-truth · N-4`) — qualified. Everything else resolved: 14/14 residual citations, 3/3 plan ids, no criterion citation outside 1–4, zero closed-iteration pointers inside live instructions. |

**Reported, not edited** (PM owns these): the seed row's `cid` for `BV1H69sB6EeF:p0` is an operator-host manifest value that appears nowhere in the tree, so the architect could not verify it and did not edit it — Task 2 must read it from the season manifest at run time rather than trusting the plan's literal. `cue-writer` / `cue writer` orthography varies (judged tolerable, flagged).

## Quality Gate Summary

| plan_id | QC decision | QA gate | Residuals | Durable summary |
|---------|-------------|---------|-----------|-----------------|
| 20260918-transcript-text-precision | | | | |
| 20260918-operational-record-coverage | | | | |

## Compound Round Summary

> Filled at iteration-close.

- 结晶文档数：<N>
- 新增 CONCEPTS.md 条目：<N>
- 触发 compound-refresh：<是/否>

## Iteration Retrospective (minimal)

> Filled at iteration-close.

- 做得好的：
- 可改进的：
- 下迭代建议：
