---
iteration_id: iter-2026-09-residual-closeout
title: "Residual closeout: one definition of manifest well-formedness for every reader, cue-writer Latin spacing, hotword benefit verified, operational records completed, intermittent suite red diagnosed"
status: locked
start_date: 2026-09-18
iteration_base_branch: main
spec_integration_branch: iteration/iter-2026-09-residual-closeout
target_branch: main
effort_scale: M
plans:
  - 20260918-verification-surface-truth
  - 20260918-transcript-text-precision
  - 20260918-operational-record-coverage
---

# iter-2026-09-residual-closeout Delivery Compass

## Scope

本迭代锁定 6 条已登记 residual 的修复（open register 共 7 条，`R1` 明确排除，见 Non-Goals 与 Roadmap Position）。
每条都已有实测证据与定位过的根因；本迭代的职责是把它们**修好并用证据关闭**，不是重新调查。

本表是范围 SSOT：**6 条在范围内、1 条明确排除**，两向可追溯——每条在范围内的 residual 都指向一个 plan（见 `## Plans`）与一条收口判据（下表 `收口判据` 列的编号即 `## Acceptance Criteria` 的编号）；反过来 11 条判据没有一条是无主的：判据 1–9 各自回指一条 residual，判据 10（register 收口）与判据 11（受影响测试全绿且逐字记录）是 iteration 级关口，覆盖全部 6 条。

| Residual | severity | 问题 | 本迭代的处置 | 收口判据 |
|---|---|---|---|---|
| `e2e-23191782-season-7686105 · R2` | **high** | 同一个"正常产出的 manifest"被两个读取者判为 malformed：`verify` 在健康归档上 exit 1（`manifest_duplicate_work_id` → 词表未识别 → `structural_input_error`），普通 `coverage` 因 `manifest_state` 被覆写为 `malformed` 而**丢失分母**；而 `coverage --quality` 无该覆写、分母正确，**退出码却同样为 1**（2026-09-18 架构复核实测） | 把"良构"定义收敛为一处——三个读取者各减去同一个具名集合（`integrity.py`、`coverage_report.build`、`cli._cmd_coverage_quality`）；用**带真实状态历史**的 fixture 钉住退出契约与分母 | 1, 2, 3, 4 |
| `20260917-hotword-acronym-precision · R1` | low | 全量测试间歇性变红（同一工作树四次跑为 261 / 0 / 196 / 0 个 setup error，跨文件） | 有界诊断到底：复现并抓 traceback → 定位根因 → 本仓可修则修，否则以"诊断机制 + 边界"收口（判据 5 的两条分支，`closure_note` 必须写明走了哪条） | 5 |
| `e2e-23191782-season-7686105 · R6` | low | cue 内拉丁词粘连（`asME IDEA`、`anITEM`）：`_token_cues` 用 `"".join(parts)` 拼接，而补空格的 `_join_text` 只在吸收碎片与交还标点两处调用 | 在 cue 内拼接处应用同一空格规则；fixture 用省略前导空格的 token 流钉住 | 6 |
| `e2e-23191782-season-7686105 · R3` | low | 六个中文同音热词（扬弃 自在 变易 此在 感性 实存）的**收益未验证**（错误已实测 118 处） | 按其 residual 自身规定的靶子做 A/B（`BV1H69sB6EeF:p0`，4 正确 vs 57 误写），以计数对比关闭或据实保持 open | 7 |
| `e2e-23191782-season-7686105 · R4` | low | `pilot` 不写 stage attempts，`--scope failed` 对 pilot 归档的条目失明（实测 `stages=[]`） | 按操作员决定**写下边界**（`pilot --help` + `README.md`；知识落点文本先落在迭代包 `guides/`，由 `mstar-compound` 在 iteration-close 提升），消除"静默丢弃" | 8 |
| `e2e-23191782-season-7686105 · R5` | low | 被外部 kill 的 `run` 不留 run-ledger 记录（全仓无任何信号处理） | **实现** SIGTERM/SIGINT 处理：追加一条含局部计数的 run 记录后按约定中断码退出，用测试锚定 | 9 |

## Plans

| plan_id | Name | Status | 覆盖 residual | 收口判据 | Notes |
|---------|------|--------|---------------|----------|-------|
| `20260918-verification-surface-truth` | Manifest well-formedness defined once; the intermittent suite red diagnosed | Todo | R2 + `20260917-hotword-acronym-precision · R1` | 1, 2, 3, 4, 5 | **唯一 `high`**；先行（理由见下）。改动面：一个具名常量 + **三个**读取者（`integrity.py`、`coverage_report.build`、`cli._cmd_coverage_quality`，2026-09-18 架构复核后由两处修正为三处），并反向修订三处断言旧契约的现存用例 |
| `20260918-transcript-text-precision` | Cue-writer Latin spacing; hotword benefit verified | Todo | R6 + R3 | 6, 7 | 含操作员归档主机上的一次 A/B 测量；该测量的边界见 Non-Goals |
| `20260918-operational-record-coverage` | Pilot attempt-ledger boundary; interrupted-run record | Todo | R4 + R5 | 8, 9 | 一条是**成文**（R4，不改行为），一条是**实现**（R5） |

Status values: `Todo` | `InProgress` | `InReview` | `Done` | `Blocked`

**调度顺序（显式）：** plan 1 → plan 2 / plan 3（后两者在 plan 1 派发之后并行）。
理由：plan 1 是唯一含 `high` 条目的计划，并且它修的是本迭代**自己的度量面**——`verify` 的退出码、`coverage` 的分母、全量套件的红绿，正是另外两个 plan 的证据被读取时所用的仪器。仪器说谎时，任何"全绿"都不构成证据，所以它先落地。

**依赖：** 三个 plan 之间**无技术前置依赖**——plan 1 无前置，plan 2 / 3 不必等它 `Done`。文件面**不是完全不相交**（2026-09-18 架构复核后修正）：plan 1 的 Task 1 需要改 `cli.py` 的 `_cmd_coverage_quality` 诊断投影（L1267-1274），plan 3 的 Task 2 需要改同一个文件的 `_cmd_run`（L2306-2337）；两段互不重叠，可并行派发，但**集成合并时必须显式核对两段都在**（对照两个 plan 的行号区间做 `git diff` 复核），并在合并后重跑 `coverage` 与中断路径各自的测试。除此之外 plan 2 独享 `asr.py` / `tests/test_asr_cues.py`，plan 3 独享 `run_ledger` 相关测试。

随之有三条纪律：(a) plan 1 先派发——是顺序，不是门禁；(b) plan 1 的 Task 1–2 落地前，任何 plan 不得把未修复的 `verify` 或普通 `coverage` 输出当作自己"通过"的证据（那正是本迭代要消灭的谎）；(c) 三个 plan 的改动落在三个功能分支上，合并顺序不影响结论，但 `cli.py` 的两段必须在合并后各有一份可复核证据。

**命令工作目录约定（所有 plan 与判据一致）：** 本仓有两个根，互不包含——**仓库根** `/root/workspace/bilibili-asr-archive`（含 `.mstar/`、`.git/`、包目录 `bilibili-asr-archive/`）与**包根** `/root/workspace/bilibili-asr-archive/bilibili-asr-archive`（含 `.venv/`、`src/`、`tests/`）。Python / CLI / pytest 一律从**包根**运行：`cd /root/workspace/bilibili-asr-archive/bilibili-asr-archive && .venv/bin/python …`；`git` 与仓库相对路径从**仓库根**运行。`bilibili-asr-archive/.venv/bin/python -m pytest tests/…` 这种写法在两个根下都跑不通（仓库根没有 `tests/`，包根没有 `bilibili-asr-archive/.venv`），本迭代的三个 plan 已全部改为带 `cd` 的形式。

## Milestones

| Milestone | Target date | Status |
|-----------|-------------|--------|
| Spec freeze (Phase 1 lock) | 2026-09-18 | pending |
| Dev complete (3 plans Done) | 2026-09-18 | pending |
| QC complete | 2026-09-18 | pending |
| Iteration close | 2026-09-18 | pending |

## Acceptance Criteria

> 每条判据都给出**可复核的观察面**：要跑的命令、要读的文件、或要看的字节。判据编号被 `## Scope` 与 `## Plans` 的表格引用。
> **命令的工作目录与写法**：本仓有两个根，互不包含——**仓库根** `/root/workspace/bilibili-asr-archive`（含 `.mstar/`、`.git/`、包目录 `bilibili-asr-archive/`）与**包根** `/root/workspace/bilibili-asr-archive/bilibili-asr-archive`（含 `.venv/`、`src/`、`tests/`）。下文的命令一律写成可直接粘贴的形式：Python / CLI / pytest 先 `cd /root/workspace/bilibili-asr-archive/bilibili-asr-archive`（包根；`bili-asr …` 是已安装入口，等价写法 `.venv/bin/python -m bili_asr …`），`git` 与仓库相对路径先 `cd /root/workspace/bilibili-asr-archive`（仓库根）。`bilibili-asr-archive/.venv/bin/python -m pytest tests/…` 这种写法在两个根下都不可执行，本迭代已全部改掉。

1. **良构定义唯一，且没有第二处判定**（R2）：`specs/manifest-well-formedness.md` §2 的"追加式状态历史 = 良构"是本迭代唯一的书面定义，源码中不存在与之冲突的判定。可复核（仓库根）：`cd /root/workspace/bilibili-asr-archive && grep -rn --include='*.py' "manifest_duplicate_work_id" bilibili-asr-archive/src/bili_asr/` 的输出中**不再出现** `coverage_report.py` 的 `manifest_state = "malformed"` 覆写行（修订前位于 L76-77，是分母丢失的直接原因；发射点 `sidecar_projection.py:216` 与记录类归档 `coverage_report.py:325` 保留），且 `integrity.py` 中不再有把该诊断归入 `structural_input_error` 的分支；两个读取者的一致结论由判据 2、3 的两条实测命令分别证明（同一归档，同一结论）。
2. **`verify` 退出契约按其文档含义成立，且是双向的**（R2）：对一条已完整归档的健康行，`cd /root/workspace/bilibili-asr-archive/bilibili-asr-archive && .venv/bin/python -m bili_asr verify --archive-root <root> --trusted-local --scope <work_id> --format text` 输出 `defects: 0` 且 **exit 0**（实测靶子：季节归档 `BV1RFoxBqEzo:p0`；修订前为 `diagnostic: structural_input_error` / `EXIT=1`；该 fixture 需带 `coordinator/attempts.jsonl`，否则 `missing_attempts_sidecar` 会以另一个理由把 exit 留在 1）；对真实损坏输入仍 fail closed——非 `defects: 0`，或非零 exit。两个方向都由 `tests/test_integrity.py` 中带**真实状态历史**的用例锚定（`-k append_only_history` 及 Task 2 新增用例），并在 plan 1 的 Completion Report 里附该归档与季节靶子的逐字输出。
3. **`coverage` 分母可用**（R2）：`cd /root/workspace/bilibili-asr-archive/bilibili-asr-archive && .venv/bin/python -m bili_asr coverage --archive-root <root> --format json` 的 `denominator.state == "available"` 且 `denominator.count` 等于该 root 的 work_id 数（实测靶子：季节归档 `count: 39`；修订前 `{"count": null, "state": "unavailable"}` 且 exit 1）。**架构复核新增（2026-09-18，请在 spec freeze 前确认或收窄）**：本判据原本只钉分母；实测显示只删 `manifest_state` 覆写时 `denominator` 已恢复（`{count: 2, state: available}`）而退出码仍为 1（`_cmd_coverage` 对任何 diagnostic 返回 1，该码仍在报告的 `diagnostics` 里），即"看着修好了、契约仍是坏的"。因此 spec §3.3 把"同一命令 exit 0 且 `diagnostics` 不含 `manifest_duplicate_work_id`"写进了定义，判据 3 的观察面随之包含这两项。锚定：`tests/test_coverage_report.py` 的分母用例（含两处旧契约断言的**反向**修订）。CSV 投影的 `denominator_*` 四列与 `schema_version` 保持字节不变（与 Non-Goals 的冻结契约一致）。
4. **状态历史 fixture 落地**（R2）：新增/扩展的 fixture 在 manifest 中为**同一 work_id 写两行以上**（真实 `needs_audio` → `audio_ok` → `archived` 历史），并**断言两端**——退出码与分母。现有 fixture 每 work_id 只写一行、只断言 `defects == []`，正是漏检原因；另有三处现存用例断言的是**旧契约**（`tests/test_coverage_report.py:129`、`:248`、`tests/test_cli_help.py:227` 的后半），必须反向修订而非删除。可复核：fixture 与断言出现在 `tests/test_integrity.py` / `tests/test_coverage_report.py` / `tests/test_cli_help.py`，且判据 2、3 的命令在该 fixture 上给出预期结果。
5. **间歇红收口，且写明走了哪条分支**（`20260917-hotword-acronym-precision · R1`）：
   - **(a) 复现**：以 `cd /root/workspace/bilibili-asr-archive/bilibili-asr-archive && .venv/bin/python -m pytest -q --tb=long > /tmp/suite-red.log 2>&1` 跑到红，读日志的 **`ERRORS` 段**（不是 summary——上次正是 grep summary 失败）：把失败 fixture、其 scope、异常类型与根因写进 plan 1 的 Completion Report。根因在本仓 → 修复 + 测试；根因在本仓之外 → 落 conftest 级的 traceback 持久化钩子（写到固定路径）+ 在定位到的文件里写明边界（触发条件、触发后怎么办）。
   - **(b) 有界预算内未复现**：交付物是**机制**（同一个持久化钩子）+ 逐字记录的各次全量运行结果（`<n> passed, <m> errors`），不是"没复现所以没事"。
   - **"未复现"本身不构成关闭理由**：register 该条的 `closure_note` 必须写明走 (a) 还是 (b)、证据落在哪个文件、以及"下一片红"从哪里读。给不出这三项的收口即为未通过。全量运行许可**仅限本判据**（plan 1 Global Constraints 记录的操作员授权，不扩展到其他任务）。
6. **cue 粘连消除，且 pinned fixture 字节不变**（R6）：一份 token 流省略前导空格的 fixture 下，`_token_cues` 产出的 cue 文本在两个 ASCII 字母数字之间含空格（`tests/test_asr_cues.py` 新增用例）；同时既有 pinned fixture `tests/fixtures/asr-cues/BV1wLTP6NE9h.p0.tokens.json` 与 `tests/test_asr_cues.py` 的既有期望**字节不变**——不得在模型已给空格处插空格，不改中文，不改 cue 边界/计数/时间轴。可复核：`cd /root/workspace/bilibili-asr-archive/bilibili-asr-archive && .venv/bin/python -m pytest tests/test_asr_cues.py -v` 全绿 **且** `cd /root/workspace/bilibili-asr-archive && git diff --stat -- bilibili-asr-archive/tests/fixtures/asr-cues/` 无输出。
   **架构复核补充（2026-09-18，请在 spec freeze 前确认）**：实测表明"两侧都是 ASCII 字母数字就补空格"的**单条件**规则会把单词切成碎片（pinned fixture 95 条 cue 中改动 4 条，全部是词内插空格：`tribunal`→`trib unal`、`token`→`t oken`、`deepseek`→`deep se ek`、`NGO`→`N GO`），因为 token 流本身无法区分"丢分隔符的两个词"与"一个词被切成碎片"。故本判据的新增 fixture 除了 token 流省略前导空格，其**识别文本（`item["text"]`）里必须已经带有那个分隔符**——规则只把模型自己文本中已有的分隔符补回，字符类条件单独成立不得补空格。plan 2 Architecture 与 Task 1 Step 1 已按此改写，并以 pinned fixture 字节不变为硬门。
7. **热词收益与代价都有测量，且按预先写定的规则处置**（R3）：对 `BV1H69sB6EeF:p0`（114.5 min）跑两臂 GPU 转写 A/B，证据文件 `{ITERATION_DIR}/iter-2026-09-residual-closeout/guides/hotword-ab-20260918.md` 必须含：
   - 收益侧：六个术语各自 **正确形式 vs 同音误写** 的逐字计数（`扬弃` vs 阳气+洋气、`自在` vs 子在、`变易` vs 变异、`此在` vs 次在+词在、`感性` vs 感兴、`实存` vs 时存），两臂并列；
   - 代价侧：两臂文本的相同字符率（确认阈 ≥95 %，即全局差异 ≤5 %）、cue 数、`asr_mean_confidence`、`asr_low_confidence_cues`；
   - 身份侧：从两臂产物的 md frontmatter 读回的 `asr_hotwords` 差异**恰好等于那六个词**（从产物证明，不从调用命令证明）。
   `R3` 依 plan 2 Task 2 Step 5 的**跑前写定**规则处置：确认 → 关闭；无实质差异 → 据实保持 open 并写明"该证据下无收益"；反证 → 向 PM 提出移除建议（移除本身不是本迭代的改动）。**只跑一臂、或用季节运行的旧数字充当另一臂，都不构成收口证据。**
8. **pilot 边界成文，且落在本迭代允许写入的面**（R4）：`cd /root/workspace/bilibili-asr-archive/bilibili-asr-archive && .venv/bin/python -m bili_asr pilot --help`（`./.venv/bin/bili-asr` 是等价入口，但不在 PATH 上）的输出中出现字面量 `--scope failed`，并说明 pilot 驱动的归档不在其恢复面内及原因；`README.md` 的 recovery 段（退出码表旁、今天已写有 `run --scope failed` 的那一段）写明同一件事——该段既有的提及不算数；知识落点文本先落在 `{ITERATION_DIR}/iter-2026-09-residual-closeout/guides/pilot-attempt-ledger-boundary.md`，由 `mstar-compound` 在 iteration-close 提升。**本迭代不编辑 `{KNOWLEDGE_DIR}/**`**（见 Non-Goals）。可复核：plan 3 Task 1 Step 3 的三条命令（同一 cwd 下的 `pilot --help` 出预期行、`grep -n -- "--scope failed" README.md` 出预期段、`.venv/bin/python -m pytest tests/test_cli_help.py -q` 全绿），逐条记录 expected / observed。修订前实测：`pilot --help | grep -n -- "--scope failed"` 无输出且 exit 1，故该检查具有区分度。
9. **中断留痕**（R5）：向 `run` 发送 `SIGTERM` 后，`run-ledger.jsonl` 中出现**恰好一条** `command: "run"` 记录，含已完成的局部计数（`work_ids`）与退出码；进程按约定中断码退出；同一 root 的下一次 `run` 能正常开始（不留不可重入的 `.lock` 状态）。由测试锚定：`tests/test_run_ledger.py`（记录构造）与 `tests/test_coordinator.py`（子进程 + 信号），**不依赖人工观察**。
10. **register 收口**（覆盖 6 条）：6 条目标 residual 在 `{PROJECT_DIR}/_default/residuals.json` 内 **in place** 关闭（`lifecycle` + `closed_at` + `closure_note`/`closure_evidence`），`closure_note` 指出由哪条判据/哪个测试关闭；或据实保持 open 并写明原因与剩余触发条件。`e2e-23191782-season-7686105 · R1` 保持 **open**（`decision: defer`），且 `## Roadmap Position` 已记录其触发条件、owner 与完成定义。归属：`R3` 按 plan 2 Task 2 Step 6 处置——**该任务只报告决定并落证据文件，register 的写入由 `project-manager` 执行**（plan 2 Task 2 的 Files 与 Step 6 已按此对齐；register 写入是 PM 的域操作）；其余各条的 in-place 关闭由 `project-manager` 在对应 plan 的 Done / QA 关口执行。
11. **受影响测试全绿，且结果逐字记录**（覆盖 6 条）：每个 plan 声明的受影响测试以 plan 中给出的命令通过，结果**逐字**记入该 plan 的 Completion Report（`<n> passed, <m> errors`；间歇类按判据 5 记录至少两次全量运行的结果），**不以"跑过一遍"替代**判据 2/3/6/7/9 的断言。本迭代的验收测试面：`tests/test_integrity.py`、`tests/test_coverage_report.py`、`tests/test_cli_help.py`、`tests/test_asr_cues.py`、`tests/test_run_ledger.py`、`tests/test_coordinator.py`（全量套件只在判据 5 的许可下运行）。

## Non-Goals

- **`e2e-23191782-season-7686105 · R1`（medium，`.db` → manifest 无桥接）不在本迭代范围**。它是架构迁移（`docs/metadata-storage.md` §Boundary 已列出三件事），需要"哪套存储是 ASR 队列 SSOT"的规格决策，与本迭代的 6 条小修异构。本迭代不为它写代码、也不为它写规格；唯一动作是按判据 10 让它以 `open` 状态连同触发条件留在 register 里。见 Roadmap Position。
- **不新增、不删除、不重排热词**：本迭代只**验证**已有六个中文热词（R3）的收益与代价，`DEFAULT_HOTWORDS` 的词条集合与顺序在**提交中**不变。A/B 的"无热词"臂由**临时未提交**的改动产生，任务收口前必须还原，并以后两臂产物 md frontmatter 的 `asr_hotwords` 读回 + `git status --porcelain` 干净为证（plan 2 Global Constraints）；一个泄漏进提交的临时改动就是一次静默的热词变更，属于本迭代的越界。反证情形下的**移除建议**只是建议，不是本迭代的改动。
- **不改冻结契约**：`coverage` 的 CSV 列（含 `denominator_*` 四列）、`schema_version`、质量词表（defect/content 两类）、`REASON_CODES` 顺序均不变；`verify` 的诊断词表也不被扩成"对任何诊断都沉默"——追加式状态历史**之外**的诊断语义保持不变。`verify` 的退出语义不是被"修改"，而是被**恢复到其文档含义**（exit 0 ⟺ 无缺陷且无诊断）。
- **不重写 manifest 存储模型**：追加式 + 投影式是 `operational-sidecars.md` #10 的既定不变量，本迭代不引入 manifest 压缩/原地重写。
- **不编辑知识库**：`{KNOWLEDGE_DIR}/**` 在本迭代内**不被写入**。`architecture-patterns/operational-sidecars.md` 的边界改写属于 `mstar-compound` 的 iteration-close 动作；R4 的知识落点文本先落在迭代包 `guides/pilot-attempt-ledger-boundary.md`（plan 3 Task 1 的 Out of scope 已明确排除该知识文件）。
- **不宣称真实环境 E2E——本迭代的验证边界，逐条写死**：
  - plan 2 Task 2 在操作员自己的归档主机上、对同一音频跑两臂 GPU 转写，这是**本机解码配置的集成测量**，其证据只用于判据 7（`R3`），不用于任何其他判据；
  - 它**不是**浏览器 / 真机 / 安装部署 E2E，也不作为任何 plan 的 task 或门禁的证据义务（`mstar-harness-core` § 定向执行与验证边界）；该类验证的唯一落点是用户显式启动的独立 `mstar-e2e` workflow；
  - 主机或模型缓存不可用时，如实记为 **not-run**，`R3` **保持 open**；不得用季节运行的既有数字顶替缺失的那一臂（判据 7 末句）。
- **不做宿主插件（dsh web 面板）相关的浏览器验收**。

## Roadmap Position

- **Current iteration（iter-2026-09-residual-closeout）**：把 open register 的 6 条（1 high + 5 low）修好并**以证据关闭**，使项目的自证工具（`verify` / `coverage` / 测试套件）、归档文本（cue 写入器、热词）与运行记录（attempts / run ledger）三者都不再对操作员说谎或留空。
- **Next iteration（本迭代明确排除，不是遗漏）**：**`R1` — 让 ASR 链从 `archive.db` 取音频工作队列**（`docs/metadata-storage.md` §Boundary 已命名的三件事：从 SQLite 枚举音频工作队列、从存量转写重建 SRT/TXT/MD 投影、让旧音频 feeder 重新有源）。它在本迭代内**保持 open**（register 该条 `lifecycle` 不改、`decision` 仍为 `defer`），判据 10 负责核对这一点。以下三项写给**没有本次对话的读者**：
  - **触发条件**（满足任一即开 Prepare）：(i) 本迭代 Phase 6 收口之后；或 (ii) **下一次要跑新语料的 ASR 之前**——今天每次语料运行都必须手工造 manifest（季节 E2E 用的是目标机上的 `/root/e2e-asr/tools/seed_season.py` 脚手架，不在仓库内、不受支持），所以"下一次语料运行"就是这个缺口的实际到期日。
  - **owner**：`project-manager` 开 Prepare 并登记 plan 行；Prepare 阶段由 `@product-manager` / `@architect` 先收敛"哪套存储是 ASR 队列 SSOT"的规格，再进 Execute。
  - **完成定义**（可复核，不是"跑通一次"）：三件事全部落地；**一条命令**即可从 `archive.db` 生成 ASR 队列而无需手工 manifest，且队列内容与 `video_parts` 中标记为待转写的 parts 集合一一对应（由集成测试锚定，测试文件与命令写进该 plan）；既有 manifest 路径**要么明确保留、要么明确下线，不留双写**；register 该条关闭时 `closure_evidence` 指向该测试与 plan。
- **最终目标**：语料从采集到转写归档为**单一可信链路**——元数据、音频队列、转写产物与运行记录同源，且每一条交付都有可复核证据。

## Delivery Branch Policy

> Mirror of frontmatter; keep in sync with workflow snapshot `{WORKFLOW_DIR}/iter-2026-09-residual-closeout/snapshot.json` `branch` anchors.

| Field | Value |
|-------|-------|
| `iteration_base_branch` | `main` |
| `spec_integration_branch` | `iteration/iter-2026-09-residual-closeout` |
| `target_branch` | `main` |

来源与理由：仓库 `AGENTS.md`（信息源优先级 2，高于 skill 文本）写明 *Default integration / PR target: `main`*，*Feature work: plan branches merging into `iteration/<iteration-id>`*；上一迭代 `iter-2026-09-asr-ops-hardening` 的 compass 亦为 `base=main / integration=iteration/<id> / target=main`。属**成文项目约定**，非"因为存在 main 就默认 main"。

**Main worktree branch**（主 checkout 驻留事实，非 `branch.base`）：`main`。

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| 间歇红在全量测试中不可复现（当前 4 次跑 2 次红） | Med | Med | 有界诊断，两条分支都算通过但**必须写明走了哪条**（判据 5）：(a) 复现 → 读日志 `ERRORS` 段抓 traceback、根因写入 plan 1 的 Completion Report；(b) 预算内未复现 → 交付 traceback 持久化钩子（机制）+ 逐字运行记录，register 的 `closure_note` 写明分支、证据文件与"下一片红从哪里读"。只写"未复现"即为未通过。命令工作目录 = 包根 |
| `verify` 行为变更被误当作"放宽门禁" | Low | High | 机制写死：三个读取者**只减去一个具名集合**（`ORDINARY_HISTORY_DIAGNOSTICS`，定义在发射该码的 `sidecar_projection.py` 旁），`integrity.py` 的 else 分支对**其他任何**未识别码仍然 fail closed（plan 1 Global Constraints 的 bidirectional 条）；判据 2 要求健康输入 exit 0 **且**真实损坏输入仍非零；`recover` 的 `authoritative` 由投影的诊断集合算出（integrity.py L233-236），实测识别分支加入后 `authoritative` 与 `defects` 逐字不变 |
| 只删除 `coverage_report.py` 的 malformed 覆写，误以为 `coverage` 已修好 | **High** | Med | 实测：覆写删除后 `denominator` 回到 `{count: 2, state: available}`，但该码仍在报告的 `diagnostics` 里，而 `_cmd_coverage` 是 `1 if report.data["diagnostics"] else 0` → **仍 exit 1**，`cumulative.state` 也停在 `incomplete`。缓解：plan 1 Task 1 在 `coverage_report.build`（L68-75）与 `cli._cmd_coverage_quality`（L1267-1274）两处同样减去该集合，Task 2 对 `coverage` 断言 denominator **与退出码**两端；spec §3.3 已写明 exit 0 是该定义的一部分 |
| 按"两个 ASCII 字母数字相邻就补空格"改 cue 写入器，把单词切成碎片 | **High** | **High** | 实测（2026-09-18，内存中改 `asr.py` 副本跑 pinned fixture）：该规则在 95 条 cue 中改动 4 条，且**每一条都是在单个拉丁词内部插空格**（`tribunal`→`trib unal`、`token`→`t oken`、`deepseek`→`deep se ek`、`NGO`→`N GO`），因为 token 流无法区分"丢分隔符的两个词"与"一个词被切成碎片"。缓解：规则加第二个必要条件——分隔符必须出现在模型自己的识别文本里（`item["text"]`，`normalize_result` 已持有）；实测该二条件规则下 pinned fixture **95 条逐字不变**，而合成粘连流 `asME IDEA` → `as ME IDEA`。plan 2 Task 1 把"先测量"写成 Step 1，并允许以"数据不支持该规则"收口 |
| `full tri-review` 期间 cue 写入器改动触及既有 asr-cues fixture | Low | Med | 验收项 6 明写既有 fixture 字节不变，并给出可复核形式（`pytest tests/test_asr_cues.py` 全绿 **且** `git diff --stat` 对该 fixture 为空）；该 fixture 是 pinned 回归锚。注意这条只有在采用上面的二条件规则时才成立——字符类单条件规则已被实测证伪，任何"改动 fixture 期望值以让测试变绿"的做法都属越界 |
| plan 2 的 GPU A/B 依赖目标主机与模型缓存可用 | Low | Med | 前置条件在 plan 2 Task 2 Step 1 改为**可执行的检查**（`test -x /root/e2e-asr/tools/ab.sh`、`test -d /root/e2e-asr/ab-hotwords`，逐条记录输出；该路径不在本仓，2026-09-18 在本工作机上不存在——它属于目标归档主机），缺失则先补驱动或如实记为 **not-run**、不伪称通过，且 `R3` **保持 open**（判据 7 末句明禁"用季节运行的旧数字顶替缺失的那一臂"） |
| plan 2 的"无热词"臂是临时未提交改动，泄漏进提交即为一次静默的热词变更 | Low | High | 该臂只由两臂产物 md frontmatter 的 `asr_hotwords` 读回证明（不比调用命令），收口前要求 `cd /root/workspace/bilibili-asr-archive && git status --porcelain` 无输出（plan 2 Task 2 Step 2 / Step 6）；越界后果由 Non-Goals 的热词条目点名 |
| SIGTERM 处理与 archive 单写者锁交互引入新缺陷 | Low | High | 设计写死在 plan 3 Global Constraints：`run` 属 `_ARCHIVE_WRITER_COMMANDS`，写记录时命令**已持有**锁，中断路径不获取/不释放/不窃取锁，`archive_writer` 的 `except BaseException` 在展开时释放 flock，故下一次 `run` 可正常重入（判据 9 断言这一点）；处理函数**一次性**且抛 `BaseException` 子类（`Exception` 会被 coordinator 逐阶段 `except Exception` 吞掉、批次继续）；记录只由唯一的 `finally` 写一次，写期间把两个信号置为 ignore，因此第二个信号既不能产生第二条记录也不能产生半行；退出码为 128+signum（SIGTERM 143 / SIGINT 130）并以 `SystemExit` 呈现，避免 traceback 把中断混进 exit 1 |
| 中断路径在"没有 summary 对象"的前提下拿不到局部计数（`run_batch` 抛异常即不返回） | Med | Med | 计数来源改为已存在的持久真相：`AttemptLedger.load()` 中 `started_at >= 本次 run 起点` 的 attempts + `compute_coverage_summary(store.load())` + `len(entries)`，只读、不 requeue、不改 manifest；复用既有 `build_run_record`，不新增第二个构造器（`build_run_record` 已接受 `work_ids`/`records_count`/`coverage_summary`），`exit_code` 任意 int 均可通过 `_validate_record`，无需 schema 变更 |
| 中断子进程测试靠 sleep 同步 → 偶发假绿/假红 | Med | Med | 同步点写死：子进程在批次开始前打印 `run: scope=… selected N row(s)`（cli.py L2303），测试读到该行后才发 `SIGTERM`，且 fixture 的行数要保证此刻批次确实还在进行（逐行输出只在整批返回后才打印，stdout 没有更晚的锚点）；若进程在信号前已正常结束，断言（rc 0 ≠ 143）必须**响亮失败**，不得加容差 |
| plan 1 与 plan 3 都要改 `cli.py`，`## Plans` 的"文件面无交集"不再成立 | Med | Low | 两处落在互不重叠的区域（plan 1：`_cmd_coverage_quality` 的诊断投影 L1267-1274；plan 3：`_cmd_run` L2306-2337），可并行派发，但集成合并时必须显式核对这两段都还在（QC 层面 `git diff` 对照两个 plan 的行号区间），且合并后 `coverage` 与中断路径各自的测试都要重跑 |

## Iteration package

> Sibling paths under `{ITERATION_DIR}/iter-2026-09-residual-closeout/` — not in `{SPECS_DIR}/` or `{KNOWLEDGE_DIR}/`. Promoted to knowledge at iteration-close via **`mstar-compound`**.

| Path | Purpose |
|------|---------|
| `guides/` | Exploration, process notes |
| `specs/manifest-well-formedness.md` | 本迭代锁定的"良构"定义与三个读取者的统一契约（plan 1 的规格基线） |
| `README.md` | Package document index |

## Phase 1 review chain (§1.6)

Three specialist roles were invoked **in order**, one invoke each, each editing the artifacts directly
(not writing commentary in their place). The chain is the §1.6 completion evidence; this record is the
PM's index into it.

| # | Role | What it owned | Findings | Disposition |
|---|------|---------------|----------|-------------|
| 1 | `product-manager` | Scope, plans table, acceptance criteria, non-goals, roadmap, risk register; plan `Goal:` lines | 8 (2 high) | All fixed in place. **F1 (high):** the acceptance criterion for `R4` required editing `{KNOWLEDGE_DIR}`, which plan 3 and the Phase-1 boundary both forbid — an unclaimable criterion that implied an out-of-scope write; rewritten onto the two product surfaces plus the package guide. **F2 (high):** the intermittent-red criterion demanded a root cause while the risk register blessed a diagnosability close — both branches are now explicit and a closure must name which one it took. **F8:** register writes were assigned to an implementer; the PM corrected the plan (see below). |
| 2 | `architect` | The locked contract, plan internals (architecture, interfaces, effort, split points, run commands), technical risk rows | 11 corrections | All applied. Four were load-bearing: **C1** dropping the `coverage` override alone still leaves the code in `diagnostics` and `_cmd_coverage` exits non-zero — the half-fix is now explicitly rejected; **C2** `coverage --quality` was mis-described as correct (its *denominator* is; its exit code is also 1), so the fix needs a third reader site; **C3** the spec's "record-kind diagnostic at L325" cited a function with **no call site** (dead code) — corrected to the real reason; **C4** the drafted cue-writer rule damaged the pinned fixture (`tribunal`→`trib unal`, `deepseek`→`deep se ek`, 4 of 95 cues) because a token stream cannot tell a lost word separator from word shards — replaced with a two-condition rule measured at 95/95 cues byte-identical. Also corrected line references, named three tests that pin the old contract, and gave the interruption path its real design (no `RunSummary` on that path; a plain `Exception` handler would be swallowed by the coordinator's per-stage handlers). |
| 3 | `writing-specialist` | Writing, terminology, cross-references, corpus hygiene, indexes | 7 corrected, 2 none | All applied. Two were substantive: the compass `## Scope` still described the *pre-review* defect framing (two readers "adopting the existing correct judgement") in a document whose own criteria now say three; and the package README plus the spec header claimed `locked at Phase 1` while the PM lock had not happened yet — both re-worded to `active (chain complete; PM lock pending)` / `…PM lock pending`. No misplaced document was found: nothing iteration-scoped sits in `{SPECS_DIR}`, no flat legacy compass was introduced, and `{KNOWLEDGE_DIR}` gained no row from this chain. |

**PM decisions taken on the chain's output** (PM-domain, not specialist content):

- **F8 / C10 (register ownership):** plan 2 Task 2 has the implementer *report* the A/B verdict and
  forbids it from editing `{PROJECT_DIR}/_default/residuals.json`; the PM closes or keeps `R3`. A child
  Assignment inherits its task scope, not the coordinator's register authority.
- **C1 and C4's criterion tightenings accepted** (criteria 3 and 6): the acceptance criteria now also
  require exit 0 with no history-driven diagnostic, and require the new fixture's recognised text itself
  to carry the separator. Neither expands scope; both are what makes the criteria able to reject the
  half-fix and the fixture-damaging variant.
- **C11 (shared file):** plan 1 Task 1 and plan 3 Task 2 both touch `cli.py` in disjoint regions. The
  snapshot records `plan_parallelism: serial`, so scheduling stays serial; the integration merge must
  verify both hunks regardless.

**State-plane defects the PM fixed while registering** (recorded because they are the kind of thing a
later reader will hit): the workflow snapshot must carry a lifecycle `status` from
`running | paused | completed | failed | stopped` — `active` is the *compass* vocabulary and is invalid
here; and optional snapshot keys with no value must be **omitted**, not `null` (a `null`
`integration_worktree_path` fails the absolute-path validator and makes the whole snapshot unreadable to
the engine). Both were caught by the engine, not by review, and both are fixed.

## Quality Gate Summary

> Filled at iteration-close. Human summary only; per-plan gate details stay in each main plan, and open residual SSOT stays in `{PROJECT_DIR}/<id>/residuals.json`.

| plan_id | QC decision | QA gate | Residuals | Durable summary |
|---------|-------------|---------|-----------|-----------------|
| 20260918-verification-surface-truth | | | | |
| 20260918-transcript-text-precision | | | | |
| 20260918-operational-record-coverage | | | | |

Notes:

- Raw review bundle: `{SDD_DIR}/review/` (ephemeral; do not rely on it after Done).
- Open residual SSOT: `{PROJECT_DIR}/_default/residuals.json` `entries[<plan-id>]`.

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
