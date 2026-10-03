---
iteration_id: iter-2026-10-asr-success-attestable
start_date: 2026-10-03
status: completed
iteration_base_branch: main
target_branch: main
plans:
  - asr-coverage-attestation
  - caption-exhaustion-attestation
---

# iter-2026-10-asr-success-attestable Delivery Compass

## Scope

本迭代锁定的 spec 点：**ASR 阶段的"成功"必须可被证实（attestable）**——当一条 ASR 记录进入归档并显示为成功时，它的成功必须附带可核验的范围证据，而不是仅凭"没有抛异常"。

两条 spec 点，各自修正一个**成功外观下的错误归档**：

1. **覆盖率可证实**（`I-000188`，high）——本机实测：`BV1YFEUzpEsT:p0` 的解码音频 73.561 s，归档转写只有 13 段、跨度 0.0–59.0 s，**20% 的语音未被触及**，而该 run 记为 `outcome=stored`、bundle `archived`、无 `error_code`、无告警。写路径里**没有任何地方**把产出跨度与解码时长作比较。
2. **字幕耗尽可证实**（`I-000187`，high）——本机实测：`probe-subs` 报 `tracks=0 / (no subtitles visible) / failed=0`，数分钟后 `harvest-subs` 却为同一 part 存下 `subtitle-ai`，再探变 `tracks=1`。同一 part、同一命令、只差时间，答案翻转。而 `no-subtitle` 正是 `v_missing_audio` 准入**付费分支**（下载音频 + GPU ASR）的凭据。

## Decisions

| # | Decision | Rationale | Source |
|---|----------|-----------|--------|
| D1 | 本迭代只做 `I-000187` + `I-000188`，**不含** `I-000166` | `I-000166` 已是既有 plan `asr-run-id-uniqueness` 的捕获对象（该 plan 第 24 行 `**Captured issue**: I-000166`，正文完整：Problem / Current state / Invariant / Contracts / Tasks / STOP / Drift / Done criteria），且已在活跃迭代 `iter-2026-10-ledger-integrity` 中排队为 `Todo`。纳入会造成**两个 plan 修同一已捕获 issue**，且引擎对此**无护栏**（会安静地产生重复劳动与冲突写入）。 | user instruction（操作者 2026-10-03 选 A） |
| D2 | 两个 spec 点合为**一个**迭代方向，而非两个独立迭代 | 两者是**同一族**：都是"账本说成功、事实不是"（与 `I-000166` 同族）。合并可共用一次方向锁定与一次 review 链，且它们的验收都需要同一套"成功必须自证"的契约语言。 | user instruction + 本会话实测聚类 |
| D3 | 方向命名使用 `asr-success-attestable`（attestable = 可被证实/可出具证据） | 遵循本仓命名惯例（`iter-2026-10-ledger-integrity` 等 kebab-case 主题名）；用 `attestable` 而非 `coverage` 是因为第二项约束的对象是**字幕耗尽判定**而非覆盖率，用后者会把范围写窄。 | naming-analyzer skill |
| D4 | `iteration_base_branch = main`，`target_branch = main` | 本仓 `AGENTS.md` 第 18–21 行明确：`Default integration / PR target: main`；feature 分支合入 `iteration/<iteration-id>`。非"因为存在 main 就默认"。 | repo convention（`AGENTS.md`） |
| D5 | 验收必须落在**可由测试证明**的层面，不接受"改了但无法证伪"的实现 | `I-000188` 的实测事实是：该缺陷**没有任何检测机制**（唯一发现它的是 opt-in 且在发布之后的 proofread Guard A）。因此新契约必须自带 witness，否则下一个会话仍会重演。 | 本会话 E2E 结论 |
| D6 | **存量数据（原 Q4）：本迭代不重扫、不 reconcile、不改写任何已归档的短覆盖转写或已写入的 `no-subtitle`/`failed` attempt 行**；但新证据必须能从**存档本身**读出，且必须存在**只读**检出路径，使运营者能在不重跑任何 part 的前提下找出既有的短覆盖记录。运营者对**单个 part** 的主动重跑不在此限——重跑须按 AC8 给出与本次产出一致的判定 | (a) 改写已发布产物与历史 attempt 行的爆炸半径与本迭代"不改 schema、最小爆炸半径"的既定决策直接冲突，且触及写边界（published bundle 不得改写）契约；(b) "显著不足"的判定规则（阈值、粒度）要待 Q1/Q2 由 architect 收敛后才存在——在规则定下来之前做 reconcile，等于把尚未收敛的阈值写进历史数据；(c) 但"看不见"本身就是 `I-000188` 的成因：若存量缺口在新契约落地后仍不可被任何只读路径发现，等于把同一缺陷留在既有归档里——故**可检出性是硬要求，改写不是** | product-manager ruling（本席；依据 §Scope "成功必须可证实" 与 D5 的证伪要求） |
| D7 | `I-000189`（原 Q5，`proofread-merge` 静默丢弃缺行块，medium）**不并入**本迭代 | (a) 不同方向：本迭代锁定的是 ASR 阶段的成功可证实（`I-000187`/`I-000188`），`I-000189` 在 proofread 合并路径上，其证据形态（合并台账 / 块计数）不共用本迭代的契约语言；(b) 优先级：本迭代由两条 high 占满（2 个业务 plan），把一条 medium 与两条 high 混排会稀释验收焦点；(c) 处置不是关闭：它保持 `open`，归入 proofread 旁路是否入口的下一轮方向决策（见 §Roadmap Position 的 Next iteration） | product-manager ruling（本席） |
| D11 | **Q6 的裁决（操作者 2026-10-03）：证据另处承载（方案 2）** —— 覆盖率证据落 **manifest 行**（`decoded_s`/`produced_s`/`coverage`/`coverage_min`，实测不拒未知键），字幕准入区分另用**非 `error_code` 载体**；**不新增任何 outcome / `error_code` 取值** | D8/D9/D10 引入的词汇被既有 `CHECK`（`schema-transcripts.sql:88-91`）与 Python 守卫（`database.py:1304-1307`）双重拒绝，而 schema 走 `CREATE TABLE IF NOT EXISTS`，既有库不重访该约束 —— 故扩宽词汇（方案 1）需要迁移故事，正是本仓“可重建、无就地迁移”决策要避开的；方案 3（复用旧词汇）实测**不可行**：`v_missing_audio` 已把 `outcome='failed'` 视为立即准入，用它表达“空清单”会得到立即放行，正好是 D10 意图的反面。方案 2 对覆盖率半边零 DDL（`validate_manifest_record` 末尾 `return dict(entry)`），故取之 | user instruction（操作者裁决，登记 `I-000200`） |
| D12 | **`I-000188` 暂缓（操作者 2026-10-03）**：`asr-coverage-attestation` 不进入实现，缺陷**保持 open 且不修**；其 Phase 1 产物（计划、D8/D9、两份 witness 规格）原样保留 | 操作者明示「先不动 188，登记」。该缺陷是真机复现的 high，且是「账本说成功、事实不是」这一类（与 `I-000166`/`I-000187` 同族）—— 故必须**登记为有意暂缓而非无人发现**（`I-000201` 记录其完整证据与复现路径）。它与 Q6 裁决的耦合：D8/D9 的载体改写同样随本项暂缓 | user instruction（操作者裁决，登记 `I-000201`） |

## Open Questions

| # | Question | Owner | Blocking? |
|---|----------|-------|-----------|
| ~~Q1~~ | **已收敛 → D8**（architect）：**标记而非阻断** —— 保留转写，写入 `outcome=stored-short` + `error_code=coverage-shortfall`，证据随行 | — | — |
| ~~Q2~~ | **已收敛 → D9**（architect）：粒度 = **per-part 单一跨度**（`produced_s` 对本次 run 实测的 `decoded_s`）；阈值由实测基准推得 `COVERAGE_MIN = 0.97`；tiling 承诺用作**分母的定义**，不作读时断言 | — | — |
| ~~Q3~~ | **已收敛 → D10**（architect）：选 **(b) 记录可区分成因** + indefinite 佐证 —— `not_found` / `no-language-match` 为 definite，`inventory-empty` 为 indefinite 且需 `COUNT(DISTINCT run_id) >= 2`；`v_missing_audio` 谓词相应改写 | — | — |
| ~~Q6~~ | **已收敛 → D11**（操作者裁决 2026-10-03）：**方案 2 —— 证据另处承载**。覆盖率证据落 **manifest 行**（实测不拒未知键：`manifest.py:105` 为 `return dict(entry)`，零 DDL）；字幕准入区分另找**非 `error_code` 载体**（如同行上的观测计数）。**不新增任何 outcome / error_code 取值**。 | — | — |

> Q4/Q5 → D6 / D7（product-manager）；Q1–Q3 → D8 / D9 / D10（architect，`specs/architect-decisions.md`）；Q6 → **D11（操作者裁决 2026-10-03，方案 2）**。**本表无未决行**（原行撤出，非静默删除）。记录：`I-000200`。

## Plans

| plan_id | Name | Status | Notes |
|---------|------|--------|-------|
| `asr-coverage-attestation` | ASR 产出覆盖率必须可证实（`I-000188`） | **Blocked** （本轮不实施 — 见 D12/`I-000201`；Phase 1 产物保留，待操作者放行） | **操作者 2026-10-03 裁决：先不动 `I-000188`，仅登记状态（`I-000201`）**。Phase 1 产物保留；实现待操作者放行 |
| `caption-exhaustion-attestation` | 字幕耗尽判定必须可证实（`I-000187`） | Todo | 业务 plan 2 |

## Milestones

| Milestone | Target date | Status |
|-----------|-------------|--------|
| Spec freeze | 2026-10-03 | pending |
| Dev complete | TBD | pending |
| QC complete | TBD | pending |
| Iteration close | TBD | pending |

## Acceptance Criteria

- **AC1** 一条 ASR 记录在声称为成功时，附带可核验的覆盖率证据；产出跨度显著短于解码音频时，归档**不再**表现为无保留的成功（具体形态由 Q1 收敛）。**"可核验"的三条硬条件**：(a) 证据**从存档本身读出**（store 行或 bundle/侧车），不是只存在于日志、stderr 或运行期内存；(b) 其值可由该次运行的产出跨度与解码音频长度**复算一致**——它是对事实的记录，不是对意图的声明；(c) 证据缺失本身不得被读作"无缺口"。
- **AC2** 存在一个**不需要**人工目视、**不需要** GPU/网络/凭据的自动 witness，在"解码音频全长、模型只覆盖部分"的场景下让测试变红（先红后绿，red/green 证据入 task report）；并断言**反面**：全覆盖转写**不**产生缺口标记（防"永远报警"的假修复）。实测基准夹具：73.561 s 输入 / 0–59.0 s 产出必须被捕捉，且不得让既有全套测试变红。
- **AC3** 空字幕清单不再产生**持久的**`no-subtitle` 耗尽判定；`probe-subs` 与 `harvest-subs` 对同一 part 在同一时刻给出一致答案（或差异被显式记录为可区分状态）。**"持久"的可判定含义**：单次空清单后，该 part 要么不进入 `v_missing_audio`，要么进入时携带使读方能区分"未看见"与"确无"的标记——两种形态之一必须在**读侧可观测**，不靠人工约定。
- **AC4** `v_missing_audio` 的准入语义与新判定一致：一次空清单不足以把一个 part 判为"字幕已耗尽"，从而不再误入付费分支；且**反向保护**：确无字幕的 part（对照基准：三次探测皆 `tracks=0` 的那一个）仍能进入付费分支——两个方向各有断言，缺一不算通过。
- **AC5** 每个 plan 的 verification gates 带**记录证据**通过（red/green、离线 witness 运行记录、受影响消费方清单）；QC 在集成分支头上执行。证据可对照该 plan 的 `## Done criteria` 逐条核对，不以叙述代替。
- **AC6** 迭代收口：compound 轮落地、PR 开出并 merge-ready。
- **AC7**（operator-facing，新增）运营者能**在不重跑任何 part、不改写任何记录**的前提下，从归档自身的**只读**路径看出：哪些已归档转写覆盖显著不足、哪些 part 的"字幕耗尽"判定是单次空清单留下的。输出须带可核验的证据字段与数值（不是一句"可能有问题"）。此条只要求**可检出**，不要求 reconcile（见 D6）。
- **AC8**（重跑语义，新增）重跑不得成为"洗白"路径：修复后对一条修复前已记为无保留成功的短覆盖记录重跑该 part，归档只允许两种自洽结局——(a) 产出覆盖提升，证据随之更新为全覆盖；或 (b) 覆盖仍不足，归档不再表现为无保留成功。**不允许**第三态（旧成功记录仍在而新证据无归属，或重跑后证据消失）。断言：一条**离线**（fake 模型）重跑路径 witness 覆盖上述两种结局。

## Non-Goals

- **不含 `I-000166`（run id 撞键）** — 已有专属 plan `asr-run-id-uniqueness` 在活跃迭代中排队；理由见 D1。
- **不改 schema、不做就地迁移** — 与上一迭代既有决策一致，保持爆炸半径小。**此条不排除**在既有词汇表 / 视图文本内的改动（本仓策略是 schema 可重建、无迁移路径：`schema-transcripts.sql` 的视图谓词与既有 outcome/error_code 词汇的调整属本迭代 in-scope，见 `caption-exhaustion-attestation` Task 1）；**新增列或任何需要就地迁移的改动**则由 Q1/Q2/Q3 在 architect 阶段裁决后另行评估。
- **不修"难音频"本身** — 实测显示该区在自身电平下模型输出 0 字符、`+20 dB` 才出字且两版本互不一致；本迭代的契约是**如实报告覆盖范围**，不是提升识别率。
- **不做提升识别率的模型调参** — `_MAX_NEW_TOKENS_PER_AUDIO_SECOND` 8→32 实测逐字节相同，已排除为原因；调参不在本迭代。
- **不动 `proofread` 链** — Guard A 已证明能抓到该缺陷（它是**事后**的 opt-in 机制，故不能作为本迭代的检测手段，见 AC2）；`I-000189` 不并入本迭代，见 D7。
- **不做语料级重跑** — 本迭代交付契约与 witness，**不重扫、不改写**历史归档与既有 attempt 行（D6）。**此条不排除 AC7 的只读检出路径**：存量缺口必须可被发现，只是不作自动 reconcile。

## Roadmap Position

- **Current iteration（iter-2026-10-asr-success-attestable）**：把 ASR 阶段的"成功"从"没有抛异常"升级为"附带可核验的范围证据"，修正 `I-000187` 与 `I-000188` 两条 high。
- **Next iteration**：`iter-2026-10-ledger-integrity` 的剩余 plan（`asr-run-id-uniqueness` / `journal-compaction-lifecycle` 视其进度）与 `proofread` 旁路产物是否入口（`I-000189`）；触发条件：本迭代收口后。owner：PM。
- **最终目标**：归档的每一条记录都能被信任为"它说的就是它做的"——这是 `I-000166` / `I-000187` / `I-000188` 共同的根。

## Delivery Branch Policy

| Field | Value |
|-------|-------|
| `iteration_base_branch` | `main` |
| `spec_integration_branch` | `iteration/iter-2026-10-asr-success-attestable` |
| `target_branch` | `main` |

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| 与活跃迭代 `iter-2026-10-ledger-integrity` 并存 → 两条 running 迭代注册 | Med | Med | 限制写入路径：只创建**本迭代**的 plan 文件与 package，不碰其四个 plan、不改 `status.json` 中它的行 |
| 覆盖率契约与既有归档语义冲突（存量短覆盖记录） | Med | Med | D6 已裁定：本迭代只交付新契约与**只读**检出路径（AC7），不重扫/不改写存量 |
| 覆盖率断言的阈值选择不当 → 既有合法记录变红 | Med | High | AC2 的基准来自实测（73.561 / 59.0）而非拍脑袋；阈值须能通过既有全套测试 |
| `I-000187` 的修法触及 `v_missing_audio` SQL → 波及队列准入 | Med | High | 该视图是 store 路由的唯一准入面；改前须列出全部消费方（`cli/_shared.py`） |
| 真实测试需要 GPU + 联网（B站凭据）→ CI 无法覆盖 | High | Med | 契约层用 fake/单元 witness；真机验证按 `mstar-e2e` 单独进行（本会话已验证该通道可用） |

## Iteration package

- `specs/` — 本迭代锁定的规格（Phase 1 只写 `<iteration-id>/specs/`；全局 `{SPECS_DIR}` 在 Phase 3 提升）
- `guides/` — 按需

## Close-out (2026-10-04)

**Iteration closed with one plan Done and one intentionally deferred.**

| plan | outcome |
|---|---|
| `caption-exhaustion-attestation` | **Done** — merged to `main` as `ff11351` (PR #212). Closes `I-000187`. |
| `asr-coverage-attestation` | **Blocked, not abandoned** — deferred by operator ruling (`I-000201`, decision D12). `I-000188` remains open and unfixed **by choice, recorded**, with its full reproduction and evidence trail. Its Phase 1 artifacts (plan, D8/D9, both witness specs) are preserved so the work resumes without re-derivation. |

The iteration is not "all plans done"; it is closed at the operator's instruction with the remaining
plan's deferral on the record. That distinction matters because a later reader must not read
`asr-coverage-attestation` as a plan nobody finished.

### What landed

The defect closed here is the same failure class the whole direction was opened against: **a ledger
saying success while the fact differs.** An empty caption inventory — which the gateway itself
describes as possibly invisible to the credential in use — was recorded once and read as proof the
video had no captions, routing a part that *did* have subtitles into the paid ASR branch. Measured on
real hardware, twice.

The fix leaves the recording path untouched, because it already drew the distinction; only the
reading path conflated it. That is why the change is a view predicate and a corroboration count
rather than new vocabulary — and why the first design, which proposed new `error_code` values, had to
be re-carriered when it turned out the schema's own CHECK refuses them on every existing database.

### What the review loop cost, and why it was worth it

Four adversarial rounds. Each found a defect in the previous round's fix:

1. the refresh performed a `DROP`/`CREATE` on every open — turning every read into a write, breaking
   concurrent readers and read-only archives, and leaving a view absent on a mid-script failure;
2. its conditional replacement matched the view name with an unanchored search over the statement's
   comment block, compared bodies literal-blind, and returned *mangled text* that every equality test
   passed because both sides were mangled identically;
3. the absolute assertion added for that mangling pinned 30-character toy strings while the real
   bodies normalize to over a thousand, so a length-gated defect still slipped through;
4. the round that finally caught the scan's remaining quote forms.

Every one of those was found by running the code, not by reading it. The single highest-value test in
the change is the one that asserts an **absolute** property of a **real** input, because a symmetric
defect is invisible to every comparison.

### Honest residuals

- `I-000187` still reads `open` in the store: the `close` channel refuses without a scoped session
  envelope (`I-000186`). The closure evidence is recorded at
  `.mstar/sdd/caption-exhaustion-attestation/I-000187-closure.md` with the exact command to close the
  row when the channel works.
- `I-000210` — two credential-absent runs satisfy the corroboration rule.
- `I-000211` — `probe-subs` still leaves no durable trace.
- `I-000212` — two architect seats were dispatched against a stale premise.
- `I-000213`/`I-000214` — probe rows created to test the mutation channel; no technical content.
