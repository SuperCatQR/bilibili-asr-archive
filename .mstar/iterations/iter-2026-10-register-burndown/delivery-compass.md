---
iteration_id: iter-2026-10-register-burndown
start_date: 2026-10-05
status: active
iteration_base_branch: main
target_branch: main
plans: [asr-run-record-integrity, archive-writeback-durability, verification-lane-contract]
---

# iter-2026-10-register-burndown Delivery Compass

## Scope

本迭代锁定的 spec 点（三簇，均为**修复**而非再评估）：

- **B1 / `asr-run-record-integrity`** — ASR 路径的 run record 与 write-back 真实性：`kind=asr`
  的 acquisition run 必须收尾（`I-000182`）、必须记下它实际的作用域（`I-000183`）、必须记下真实的
  语言（`I-000184`）；D8 拒绝诊断的作用域/异常面/退出码必须被写清或收窄（`I-000197`/`I-000198`/
  `I-000199`）；`queue_source.py` 的时钟与导入面必须回到单一 injectable clock（`I-000180`）；
  write-back 的 page 身份必须由 `work_id` 推导（`I-000171`）；R14 write-back 必须有端到端见证
  （`I-000176`）；`cli/asr.py` 的 ASR write-back 必须与 caption 同侧、在 archive 成功守卫之外
  （`I-000194`）。
- **B2 / `archive-writeback-durability`** — 记录层的持久性与诚实性：coordinator 的两处 docstring
  必须陈述真实契约（`I-000191`）；caption write-back 必须在调用点有 swallow 边界（`I-000192`）；
  写回失败的终态行必须可识别且可处置（`I-000193`）；manifest journal 的解码策略必须**只在一处决定**
  且不再把替换字符写回快照（`I-000196`）；`_journal_bytes` 这个只写状态必须删除或说明（`I-000202`）；
  `save()` 的 publish→discard 窗口必须关闭或把前提写下来（`I-000203`）。
- **B3 / `verification-lane-contract`** — 验证通道本身要能证明它声称证明的事：`opt_in_gate` 必须
  自己 skip（`I-000168`）；installed console-script 通道必须真的打开一次数据库（`I-000174`）；
  baseline 通道不得整体排除 `test_cli_help.py`（`I-000175`）；空清单的 corroboration 不得由
  `credential_present=0` 的 run 满足（`I-000210`）；`probe-subs` 的观察必须留下持久痕迹或把不留痕
  的决定写下来（`I-000211`）。

## Decisions

| # | Decision | Rationale | Source |
|---|----------|-----------|--------|
| D1 | 方向 = 三批缺陷 burndown（B1/B2/B3），目标是**修复** ≥20 个 open 行 | 用户指令「评估项目issue，一批一批修复，至少修复20个」；125 行里最多的一簇正是 B1 家族 | user instruction |
| D2 | Scale = `M`（命令行未给 scale token → 文档默认值）→ **3** 个业务 plan（上限） | `iteration-loop` § Args 默认 `M`；只计业务 plan，Review 链/QC/QA/compound/close/PR 不占名额 | autonomous ranking |
| D3 | 优先集群而非逐行：B1(10) + B2(6) + B3(5) = 21 行 | 集群共享根因与测试面，「≥20」才不是 20 个互不相关的单文件修补 | autonomous ranking |
| D4 | 行选择以 **HEAD 复核**为准，四天前的 audit 结论只作输入 | 复核已证实 `I-000182/183/184/196/168` 在 `c59a1e6` 仍成立；结论失真的行按 already-fixed 记录且**不计入** 20 | autonomous ranking |
| D5 | `I-000215` / `I-000190` / `I-000207` / `I-000195` 明确不做 | 全为 engine（`@mstar-harness` 3.11.2）缺陷，非产品代码可修；`I-000215` 已由 operator 裁定为 owner 名下 blocker | autonomous ranking |
| D6 | `I-000041` 不做、不计入（**排除成立，理由已按实测改正**） | seat-1 复核（2026-10-06）：`issues.acceptance` 的原文是一个裸 token `defer`，**不是**决定本身。决定在 `occurrences.evidence_json`（legacy residual `20260925-archive-db-review` R1）里，逐字含 `"decision":"defer"`、`"owner":"@project-manager"`、`"target"`（closing condition：凭证有效性以「re-login 后重探六个已知正例」或「显式判定账号不可用」为准，且 outcome mapping 要能区分不可用凭证与真空清单）与 `"tracking"`（触发器：**下一个恢复 caption 路径的会话**，在任何 `harvest-subs`/`probe-subs` 打真实语料之前）。同一列 + 同一 payload 形态承载全部 76 个裸 token 的 open 行（实测 76/76 都带 `decision`+`owner`+`target`），所以按记录排除是成立的；**不成立的是初稿的措辞**（裸 token 当成决定本身）。它的触发器属于**下一个恢复 caption 路径的会话**，承接面见 `## Roadmap Position`，owner = `@project-manager`（payload 原文） | autonomous ranking + seat-1 复核 |
| D7 | 分支策略：base `main` / integration `iteration/iter-2026-10-register-burndown` / target `main` | 前两轮迭代 compass frontmatter 同值 + 仓库 `AGENTS.md` Branch policy | autonomous ranking |
| D8 | 本仓库 `.mstar/**` 被 git 跟踪（与 harness 默认 gitignore 契约不同），故 Phase 1 产物按仓库 `AGENTS.md` 规则在 §6 前提交到 integration 分支 | `.mstar/AGENTS.md`「tracked is necessary, not automatic」：未提交的 plan 在 worktree 里不存在 | autonomous ranking |
| D9 | 不修 wedged lifecycle，且本迭代每条命令都显式 `--workflow <id>` | 双 active lifecycle 会让无参数选择返回 `unbound-multi-active`；显式寻址即可绕开，无需冒第二次 wedge 的风险 | autonomous ranking |
| D10 | 不给 payload/closure 伪造证据：closure evidence 只引用真实跑过的命令与真实存在的路径 | `{SPECS_DIR}/issue-store-close-route.md` §「Consequence a reader must carry」：store 的 open 是通道产物，closure 记录才是事实；本迭代两头都要真 | autonomous ranking |
| D11 | **`≥20 resolved` 可达，但必须先补一步不在初稿里的 ceremony**：把 coordinator 绑定到**本迭代自己的** workflow（`mstar plan bind --coordinator --workflow iter-2026-10-register-burndown --session-id <id>`），之后 `issue close` 就有引擎签发的 envelope。owner = PM，属 Phase 3 收口步骤 | seat-1 于 2026-10-06 在**本 harness 的字节副本**（`/root/tmp-work/pm-probe`，含同一 `store.db` / snapshot / catalog binding）上实测：bind 返回 `plan.bind.ok`，随后 `issue close --id I-000210 --disposition resolved --expect 1` 返回 `issue.close.ok`，行翻转 + `issue_transitions.imported=0`。`I-000186`（"close channel unreachable"）测的是 **所有既有 snapshot 都 terminal** 这一状态，本迭代的 snapshot 是 `running`（`catalog_execution_bindings` 已有该 workflow 的 committed 行），所以那条结论对本轮不适用；真实 harness 未被探针改动 | seat-1 复核 |
| D12 | `I-000182` **不是** `I-000154` 的重复，21 行就是 21 行，容错只有 1 行 | `I-000154`（low, improvement, "unbounded growth, carry-forward"）已于 2026-10-04 以 `duplicate` 关闭，理由写的是「identical subject … asr-run-id-uniqueness plan」——那条车辆是 run_id 同秒撞主键（`I-000166`，已 resolved），与 `I-000182`（`kind=asr` run 永不收尾）**不是同一缺陷**。所以既不能靠「再判一次重复」省下 `I-000182`，也不能沿用 `I-000154` 的关闭理由 | seat-1 复核 |
| D13 | `I-000195` **已 resolved**（2026-10-04T06:19:12.112Z），compass Non-Goals 与 `bilibili-asr-archive/docs/roadmap.md:38-42` 把它当作未关的 Phase 0.5 前置，是**前提漂移**；本轮按已关处置，不列为非目标 | store `disposition=resolved`，`closed_at` 与 `updated_at` 均为 2026-10-04T06:19:12.112Z，closure_note 指向回归测试与合并提交 | seat-1 复核 |
| D14 | `I-000041`（high）**不由本迭代任何 plan 承接**：它的触发器是「下一个恢复 caption 路径的会话」，但它的 closing condition 是**凭证有效性**（re-login 后重探六个已知正例，或显式判定账号不可用），这是 operator 的账号动作，不是产品代码可修。B3 触的是同一张表（`I-000210`/`I-000211`），但改的是 corroboration 规则，**不**建立凭证有效性 —— 不能拿它给 B3 凑数 | 见 D6 的 payload 原文（`target` 与 `tracking` 两个字段逐字）；B3 的行选择见其 `## Out of scope` | seat-1 复核 |
| D15 | `I-000210` 的产品后果**写明**（不是新决定，是该行 acceptance 要求 "with the resulting consequence stated"）：排除 `credential_present=0` 后，**匿名机器**上那些只有匿名观测的 part 永远无法确认 exhaust —— 它们进不了 `v_missing_audio` 的付费分支（该视图是阴性谓词），因此永远不会被下载音频、不会被 ASR，留在 `v_pending_subtitles` 里并在 `v_part_pipeline` 渲染为 `no_subtitle`。操作者看到的是**待办队列变长且不动**，而不是错误 | `storage/schema-transcripts.sql` 的 `v_missing_audio`（`:199-250`；阴性谓词 = 结尾的 `AND NOT EXISTS part_audio_objects`）与 `v_part_pipeline`（`:286-347` 的 `audio_pending`/`no_subtitle` 分支） | seat-1 复核 |
| D15b | **上一条不是假设：这台机器今天就是匿名态。** `I-000041` 的 occurrence 证据记着 `/x/web-interface/nav` 返回 `code=-101`/`isLogin=false`（带 `.env` cookie 与不带都一样），且 40 条随机采样 0/40 有 track、6 个已知正例 0/6 —— 所以 B3 修好 `I-000210` 之后，**audio 队列在凭证问题解决前无法推进**（只对「靠匿名观测证明耗尽」的那些 part）。这与 `I-000041` 是**同一件事的两面**：B3 只把「假绿灯」关掉，`I-000041` 才是恢复通路的动作 | `I-000041` occurrence payload 的 `source` 字段（2026-09-25 两次探针，`evidence_json.source` 逐字含这两个读数） | seat-1 复核 |
| D15c | 因此 **`I-000041` 的优先度在 B3 落地后上升**：它从「一个 high 的 review-obligation」变成「B3 修复效果的前置条件」。这不改变排除本身（closing condition 仍是 operator 的账号动作），但改变 `## Roadmap Position` 里的排序：它应当排在「下一轮 register 续批」**之前** | 由 D15 + D15b 推出；排序落点在 `## Roadmap Position` 的 Next iteration（非产品）段 | seat-1 复核 |
| D16 | `empty_inventory_confirmations` 在 schema 里**有两份**（`:214` 与 `:304`，分别在 `v_missing_audio` 与 `v_part_pipeline` 内，各自 `:236`/`:336` 消费），`I-000210` 的 acceptance 自己要求「CTE 与钉住它的测试必须一起动」。B3 的 Files/见证只覆盖 `v_missing_audio` —— 收口时**两份一起改**，否则两个视图对同一个 part 会给出不同答案（fixture 自己的注释写着 "so the two views never disagree"）。**seat-1 已实测代价**：两份同改后，全量套件从 `36 failed` 变成 `40 failed`（新增 4 条，清零 0 条）；只改一份或不改调用方 fixture 时新增 **14** 条，分布在四个文件 | `I-000210` acceptance 原文点名 `schema-transcripts.sql` 的 CTE + 实测（`/root/tmp-work/pkg-base` vs `pkg-filt2` 的全量套件对比） | seat-1 复核 |
| D17 | `I-000184` 的修法是**产品可见的身份决定**，不只是「补一个字段」：`transcripts` 的 UNIQUE 是 `(video_part_id, source_kind, language, version)`，所以把语言从常量 `und` 改成真实值会改变**同一 part 重跑的版本归并行为**（不同语言 → 不同行，而非同键新版本）。同时 **`search --language` 不受益**：index 只从 manifest 快照取语言（`search_index.py:649`：`entry.get("sub_lan") or entry.get("lan") or entry.get("language")`），从不读 `transcripts.language` —— 因此 B1 不得声称该行修好即「ASR 行可被语言检索」。受益者是**store 路由的消费者**（gap view / 直接查 `transcripts`） | `storage/schema-transcripts.sql` 的 `transcripts` UNIQUE 约束（`:25`）+ `asr.py:1497`（provenance 暴露 `language`）+ `search_index.py:649`（语言只来自 manifest 快照） | seat-1 复核 |
| D18 | `I-000180` 的 acceptance 是**两件事**（时钟收敛 **+** 清掉两个未用导入），而 `cli/meta.py` 实测有 **11 个**真未用导入（`DEFAULT_ARCHIVE_ROOT`/`_archive_database_exists`/`_format_run_line`/`_identity_from_entry`/`_open_read_connection`/`_open_read_repository`/`_record_api_error`/`_run_error_codes`/`_subtitle_schema_rebuild_line`/`_todo_for_bvid`/`DEFAULT_MID`，均为 plan-010 去重后的 import-site 残留）。B1 的 Files 只列 `queue_source.py`，若不加 `cli/meta.py`，这条行的 acceptance 会**假通过**（行可关、其余未清）。owner：B1 实施者 | AST 逐名计数（每个名字在模块体内出现次数 = 1，即只在 import 行出现）；`queue_source.py` 本身无未用导入 | seat-1 复核 |

## Open Questions

| # | Question | Owner | Blocking? | Marker carrier（终线前必须清） |
|---|----------|-------|-----------|------|
| Q1 | B2 的 `I-000193`「可识别 + 可重驱」落点：是加一条 attempt-ledger 记录，还是把 gap view 的后果写成 tracked decision？两条路成本差一倍 | architect | No | `{PLAN_DIR}/archive-writeback-durability.md` 的 architect marker (c) |
| Q2 | B3 的 `I-000211`：`probe-subs` 是否应当落一条 acquisition_run（需要 attempt rows 的外键），还是把「不留痕」写成显式决定？ | architect | No | `{PLAN_DIR}/verification-lane-contract.md` 的 architect marker (c) |

**seat-1 复核（2026-10-06）**：两行的 owner 均为 `architect`、`Blocking?` 均为 `No`，按初稿保留 —— 两条路都**不需要**在本轮收敛：Q1 的两条路各自可独立判定真伪（`I-000193` 的 acceptance 明写「attempt-ledger/store 级可查询信号」**或**「书面的 tracked decision + owner」），Q2 同理（落 observation **或**把不留痕写成显式决定），所以任一条先定都不阻塞另一条 plan 动手。**但 `Blocking? = No` 不等于可以悬空**：两行都已由 §1.3(iii) 的 marker 形态承载（见上表第三列），终线前由 architect 清除或重新归属给 `PM`。另注：`I-000211` 的 acceptance 自己指出「若决定落 observation，probe 观测到的空清单会**计入 corroboration**，与 `I-000210` 交互，使计数器无需 harvest 即可达」，因此 Q2 的答案会**反过来约束 `I-000210` 的修法**（若 probe 也写 run，则「匿名 run 不得满足 corroboration」这条过滤必须同时决定 probe run 的 eligibility）。architect 收敛 Q2 时须把这条交互一并写下。

## Plans

| plan_id | Name | Status | Notes |
|---------|------|--------|-------|
| asr-run-record-integrity | B1 — ASR run record and write-back truth | Todo | 10 rows |
| archive-writeback-durability | B2 — caption write-back + manifest durability | Todo | 6 rows |
| verification-lane-contract | B3 — verification lane and absence-evidence contract | Todo | 5 rows |

## Milestones

| Milestone | Target date | Status |
|-----------|-------------|--------|
| Spec freeze（compass `locked`） | 2026-10-05 | pending |
| B1/B2/B3 dev complete | 2026-10-05 | pending |
| QC + QA gates complete | 2026-10-05 | pending |
| Iteration close（§3）+ PR（§4） | 2026-10-06 | pending |
| Post-merge close（§6.1–§6.4） | 2026-10-06 | pending |

**seat-1 注（2026-10-06，产品优先级）**：前两项的 target date **已经过去**（`start_date: 2026-10-05`，
§1.6 链到 2026-10-06 仍在进行中）。这不改变任何一个里程碑的**内容**，但它改变**排期判断**：本迭代的
三个 plan 都是 `Effort: M`、且 B3 的 `I-000210` 实测会牵动四个测试文件（见该 plan P10），所以
「Spec freeze 之后同一天 dev complete + QC/QA + close + PR」这条链在剩余时间里是**乐观的**。
PM 在 lock 时应当二选一，**不要**让日期保持原样而实际滑期：(a) 把后两项的 target date 明确后移并在
此处写出理由，或 (b) 保留日期但在 `## Risk Register` 里登记「B1/B2/B3 同日完成 + 同日过 QC/QA」
为一条风险并写缓解。**seat-1 倾向 (a)** —— 三条 plan 里 B1 有 4 个 Task、B3 有 2 个 Task 且每个 Task
都要求 red→green 见证，同一天完成的假设没有证据支持。这不是「没时间」式的排除，而是排期本身要与
实测工作量一致。

## Acceptance Criteria

- 21 个目标行中 **≥20** 个以 `disposition = resolved` 落库，且 closure evidence 指向真实修复提交；以
  re-adjudication（`waived`/`duplicate`/`superseded`）关闭的行**单列**且不计入。
  - **可达性前置（D11，seat-1 实测）**：`resolved` 只能经引擎的 privileged verb 写入，而该 verb 需要
    一条**引擎签发的、绑定到 running workflow** 的 session envelope。本迭代自己的 snapshot 是
    `running` 且 `catalog_execution_bindings` 已有它的 committed 行，所以先把 coordinator 绑到
    `iter-2026-10-register-burndown` 即可；**不得**把 `I-000186`（"close channel unreachable"）当作
    本轮不可关闭的依据 —— 那条测的是「所有既有 snapshot 都 terminal」的状态快照，而本轮不是。
  - **容错只有 1 行**（D12）：`I-000182` 不能靠「再判一次 `duplicate`」省掉。
- 每个被关行的结论都有 **red→green** 见证（测试或具名 scoped check），并写进该 plan 的 durable
  review-gate summary。
- 每个 plan 自己的模块套件通过；既有失败基线是**实测记录**，不是断言。
- 未关行（含 `I-000041`、`I-000136`、`I-000135`、`I-000209`、`I-000189`，以及三簇内的溢出条目）在
  `## Roadmap Position` 带**实测原因、owner 与触发条件**出现，不留静默 stale `open`。
- 无 in-place schema migration（`I-000210` 改的是视图谓词，`refresh_shipped_views()` 会把既有档案里
  的视图重建，无需重建库）。
- 收口后 `mstar status tech-debt` 的 open 计数反映下降（基线实测 2026-10-06：`total_open=125`，
  `high 5 / medium 40 / low 80`）。

## Non-Goals

- **`I-000215` 与 wedged audit lifecycle** — engine 缺陷，operator 已裁定为 owner blocker；修它需要
  upstream seam，本迭代不碰，且不依赖它（D9）。owner：`@mstar-harness`（engine）／operator 记账；
  触发：engine 提供 re-point/abandon seam，或 operator 接受该 lifecycle 作为常驻 residual（该行
  acceptance 的第三个出口）。
- **`I-000190` / `I-000207`** — engine 共享寄存器 lost-update 家族（`status.json` / snapshot 写入并发），
  非产品代码；本迭代**不修也不依赖**（D9 用显式 `--workflow` 绕开）。owner：operator（engine 侧）；
  触发：下一轮 engine 升级或该族在真实并发里再次咬人。**注**：`I-000195` 曾在初稿与本条并列，但它
  已于 2026-10-04T06:19:12.112Z `resolved`（D13），不再是非目标。
- **`I-000136` / `I-000135`** — 依赖闭包 / `uv.lock` 陈旧；重生成会把 PyPI CUDA torch 拉到唯一产出
  GPU 结果的机器上，保持为文档化的人工步骤。不是「没时间」：这是**唯一一台**已验证 ROCm 机器的
  资产保护。owner：`@project-manager`（store 内既有值，保持）；触发：出现第二台可重生成 lock 的
  主机，或 `uv sync` 路径被真实读者踩到。
- **`I-000041`** — §「`I-000041` 的处置」见下（D6 / D14）。不是「没时间」，是它的 closing condition
  要求一个 operator 的账号动作。
- **`I-000209`（无 CI）** — 建 CI 是仓库/主机操作，不是缺陷主体的修复。owner：operator；触发：本迭代
  收口（见 `## Roadmap Position` 第二段）。
- **`I-000189`（proofread-merge 块核算）** — 自身成立（`medium`，acceptance 可独立判定），但与三簇任一
  plan 的模块无交集。**不用它给 B2 凑数**：它的验收面在 `proofread-merge` 工具链，而 B2 的六行全在
  `coordinator.py`/`manifest.py`，把两者塞进一个 plan 只会让 red/green 见证互相污染。owner：PM；
  触发：下一轮 register 续批（`## Roadmap Position` 第一段已列）。
- **greenfield 可行性工作**（新 processor、语料扩张、布局迁移）— 本迭代只修既有主体。

### `I-000041` 的处置（seat-1 复核后）

**状态**：`open`，`severity=high`，`owner=@project-manager`，`kind=review-obligation`。**它是唯一一条
「高严重度且本迭代三条 plan 都修不了」的 open 行**，所以排除理由必须写实。

`issues.acceptance` 的原文是一个裸 token：`defer`。它不是决定本身；决定在
`occurrences.evidence_json`（legacy residual `20260925-archive-db-review` R1）：

- `"decision": "defer"`，`"owner": "@project-manager"`
- `"target"`（closing condition）：*"The next session that resumes the caption path, before any
  `harvest-subs` / `probe-subs` invocation against the live corpus. Closing condition: the credential's
  validity is established one way or the other (re-login and re-probe the six known positives, or an
  explicit decision that the account is unavailable), and the outcome mapping either separates an
  unusable credential from a genuinely empty inventory or the ledger says which of the two readings
  applies."*
- `"tracking"`：*"… It blocks any coverage-expansion decision: the caption channel's yield is
  unmeasurable until it resolves, and that measurement is what decides whether expanding coverage costs
  minutes (captions exist) or 7-11 days of GPU (they do not)."*

**判定**：排除**成立**，但依据是「记录在案的延期 + 只有 operator 能执行的 closing condition」，**不是**
「裸 token 即决定」。**且必须承认它没有承接者**：它的触发器（下一个恢复 caption 路径的会话）落在
**本迭代之外**，而本迭代 B3 触的正是 caption 路径的表 —— 所以本轮**明确不承接**它（不建立凭证有效性），
并把承接面写进 `## Roadmap Position`（owner = operator，触发 = 任何一次针对真实语料的新
`harvest-subs`/`probe-subs` 之前）。**相邻但不同**：`I-000210`/`I-000211` 修的是 corroboration 规则，
即使两者都落地，一条**过期**凭证仍会写 `credential_present=1` 且被当作「已认证者什么都没看见」——
这条假阴性本迭代不消除，不要把它读成已修。

## Roadmap Position

> 三段都按「下一个迭代的 PM 能直接采用」写：每项带 owner 与**触发条件**（不是日期）。

- **Current iteration（iter-2026-10-register-burndown）**：把 register 里三簇真实缺陷按批修掉，使
  open 行数从 125 实质性下降 ≥20，并让每一条下降都可回溯到一次修复与一个见证。收口的最后一步是 D11
  的 coordinator 绑定 —— 没有它，`resolved` 无法写入，本段的目标不可达；owner：PM，触发：Phase 3。
- **Next iteration（产品）**：register 剩余簇的续批 —— ①`I-000189`（proofread-merge 块核算，`medium`，
  与三簇无交集，单独成批）；②empty-inventory 家族在 `I-000210` 之外的部分（`I-000185`：`coverage`/`verify`
  在健康档案上因「CLI 路径不写证据 sidecar」而退非零）；③page 身份家族在 `I-000171` 之外的部分
  （`I-000133`：`derive-manifest` 的加性策略不看 legacy bare-`bvid` 行，`acceptance='defer'`，
  owner=`@project-manager`）。触发：本迭代收口且 register 复核一次；owner：PM。
  **但先做下面非产品段的 `I-000041`**（D15b/D15c：它是 `I-000210` 修复生效的前置条件）。
- **Next iteration（非产品，需 operator）**：
  - **`I-000041`**（high，caption 凭证有效性）— **最高优先度的非产品项**（D15c）。owner = operator
    （payload 原文为 `@project-manager`，但 closing condition 是账号动作）。触发：**任何**一次针对
    真实语料的新 `harvest-subs`/`probe-subs` 之前 —— 这也是它自己的 `target` 原文；且 B3 落地后它
    同时是 audio 队列恢复推进的前置。承接形态建议：operator 完成 re-login 并重探六个已知正例
    （或显式判定账号不可用），然后把结果写成 outcome mapping 的判据。
  - **`I-000209`**（无 CI）：owner = operator。触发：本迭代收口后第一件事（三簇的红绿见证目前全靠
    人工跑，CI 是让它们**持续**成立的最低成本手段）。**注（seat-1 实测）**：本机的 baseline lane 还
    额外受限于环境 —— 五个 installer 测试因 offline uv 缓存缺 `bilibili-api-python==17.4.2` 恒红；
    建 CI 时必须一并决定「CI 是否具备装依赖的网络」，否则那条 lane 在 CI 里也是恒红。
  - **`I-000215`** + `I-000190` / `I-000207`（engine）：owner = operator / `@mstar-harness`。触发：engine
    升级，或该族再次在真实并发里咬人（`I-000215` 的 acceptance 也允许「记录为常驻 residual」这一出口）。
- **最终目标**：register 的 open 集合里不再有「已修但没关」或「没修但没人认领」的行 —— 每一行要么关，
  要么带着 owner 与触发条件躺着。**seat-1 注**：这条目标目前**不成立**，且原因是结构性的而非遗漏 ——
  实测 125 个 open 行里有 **76 行的 `acceptance` 是裸 token**（`defer` 73 / `accept` 3），全都带
  `@project-manager` 类 owner 与 payload 里的 `target`/`closing condition`，即**大批已裁定但无日历的
  延期**；同时有 `I-000150`/`I-000153`/`I-000152` 这类 acceptance 只写 `addressed in a future tidy
  plan` 的行（前两条 owner=`project-manager`）—— 「tidy plan」没有载体、没有触发条件。下一轮 PM 若要
  让本段目标成立，应当**先**把这些延期行按 payload 的 `target` 归类出可执行的触发条件，而不是继续按
  簇挑缺陷修。

## Delivery Branch Policy

| Field | Value |
|-------|-------|
| `iteration_base_branch` | `main` |
| `spec_integration_branch` | `iteration/iter-2026-10-register-burndown` |
| `target_branch` | `main` |

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| 四天前的 audit 结论在 HEAD 已失真，导致工作量错估 | Med | Med | D4：每行动手前对 HEAD 复核；失真行按 already-fixed 记录并从计数剔除 |
| 双 active lifecycle 使无参数选择返回 `unbound-multi-active` | High | Low | D9：每条命令显式 `--workflow <id>` / 显式 envelope |
| `.mstar/**` 被跟踪，ceremony 的每次 snapshot 写入都会脏化 control root | High | Med | D8：在专用 integration worktree 里跑 ceremony；按仓库 `AGENTS.md` 只暂存本会话作者的文件 |
| 三个簇合计 21 行，若某簇超出预期，`M` 名额不允许加 plan | Med | Med | 溢出规则：进 `## Roadmap Position`，不扩预算、不造 process plan |
| 触碰 `storage/schema-transcripts.sql` 的视图谓词（`I-000210`）可能影响既有行 | Low | Med | 该视图可重建（无 in-place migration）；B3 计划内先跑 `v_missing_audio` 的全量对比再改谓词 |
| 只改 `v_missing_audio` 里的 `empty_inventory_confirmations`、漏掉 `v_part_pipeline` 里的第二份拷贝，使两个视图对同一 part 给出不同答案 | **High** | Med | D16：两处 CTE（`:214` / `:304`）必须同改；见证里加一条「两视图一致」断言，而不是只比 `v_missing_audio` 的前后结果集 |
| `resolved` 写入通道在收口当轮才发现不可用，导致 21 行全部只能记成「已修未关」 | Med | High | D11：**已在本 harness 的字节副本上实测通过**（bind → close → `imported=0`），不是推断；收口的第一个动作就是 bind，先做再做别的 ceremony |
| `I-000210` 修好后，匿名机器上的 part 永远停在待办队列（见 D15），被误读成「修坏了」 | Med | Low | D15 已把该后果写成产品事实；B3 的验收里要求 witness 同时断言「有凭据的两次观测仍使 part 准入」，使「不变差」可被检验 |
| 目标行的 acceptance 比 plan 的 Files 面更宽（`I-000180` 的两个未用导入在 `cli/meta.py`、`I-000199` 的三处诊断站点），实施后「见证通过但行不可关」 | Med | Med | 三份 plan 的 Done criteria 都要求「经 store 关闭」；实施前先按行 acceptance 逐条核对 Files 清单，缺口写进 plan 而非留给关闭时发现 |

## Iteration package

| Path | Purpose |
|------|---------|
| `direction-lock.md` | Lock-time record（autonomous 路线；五个字段在此落盘后再进 compass） |
| `guides/` | 探索与过程笔记（**已有三份**：`phase-2-readiness.md` 的 Ceremony 实测契约、`issue-declaration.md` 的 store-id ↔ GitHub-issue 映射、`pr-214-overlap-audit.md`；不是空目录） |
| `specs/` | 迭代级 spec 草案（本迭代按需；全局 `{SPECS_DIR}` 在 Phase 3 提升） |
| `README.md` | Package 索引 |

## Quality Gate Summary

> Filled at iteration-close.

| plan_id | QC decision | QA gate | Residuals | Durable summary |
|---------|-------------|---------|-----------|-----------------|
| asr-run-record-integrity | — | mandatory | — | — |
| archive-writeback-durability | — | mandatory | — | — |
| verification-lane-contract | — | mandatory | — | — |

## Compound Round Summary

> Filled at iteration-close.

- 结晶文档数：—
- 新增 CONCEPTS.md 条目：—
- 触发 compound-refresh：—

## Iteration Retrospective (minimal)

> Filled at iteration-close.

- 做得好的：
- 可改进的：
- 下迭代建议：
