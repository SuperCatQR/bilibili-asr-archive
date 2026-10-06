# Iteration package — iter-2026-10-register-burndown

迭代包索引。三份业务 plan（`M` 预算上限 = 3）从 register 的 open 行按簇修复 ≥20 行。

| Path | What it is | Status |
|------|------------|--------|
| `direction-lock.md` | Lock-time record（autonomous 路线；五字段在此先落盘，再进 compass） | locked 2026-10-05 |
| `delivery-compass.md` | 迭代指南针（scope / decisions / open questions / plans / acceptance / non-goals / branch policy） | `active` → `locked`（§1.6 后） |
| `guides/` | 探索与过程笔记（**已有六份**：`phase-2-readiness.md` = Phase 2 ceremony 的实测契约、`issue-declaration.md` = store-id ↔ GitHub-issue 映射、`pr-214-overlap-audit.md`、`relock-after-pr214.md` / `relock-decision-2026-10-06.md` = PR #214 落 main 后的 relock，`ref-retirement-2026-10-06.md` = 三个已合并 ref 的就地删除裁定与恢复路径） | — |
| `specs/` | 迭代级 spec 草案（若某 Task 需要长期契约，在此起草；全局 `{SPECS_DIR}` 在 Phase 3 提升时写入） | — |

## Plans（业务 plan 计入 `M` 预算 = 3）

| plan_id | Plan file | Cluster | Target rows |
|---------|-----------|---------|-------------|
| `asr-run-record-integrity` | `{PLAN_DIR}/asr-run-record-integrity.md` | B1 | 10 |
| `archive-writeback-durability` | `{PLAN_DIR}/archive-writeback-durability.md` | B2 | 6 |
| `verification-lane-contract` | `{PLAN_DIR}/verification-lane-contract.md` | B3 | 5 |

## 目标行（21，≥20 必须关闭）

`I-000182` `I-000183` `I-000184` `I-000197` `I-000198` `I-000199` `I-000180` `I-000171` `I-000176`
`I-000194`（B1）· `I-000191` `I-000192` `I-000193` `I-000196` `I-000202` `I-000203`（B2）·
`I-000168` `I-000174` `I-000175` `I-000210` `I-000211`（B3）

### 容错只有 1 行（compass D12）

`I-000182` **不能**靠判定为 `I-000154` 的重复来免除：`I-000154` 已于 2026-10-04 以 `duplicate` 关闭，
而它关的是 run_id 同秒撞主键（`I-000166`，已 resolved）—— 与「`kind=asr` run 永不收尾」不是同一缺陷。
所以 21 行必须真关 ≥20。

### 关闭通道（compass D11，seat-1 实测）

`disposition = resolved` 只能经引擎的 privileged verb 写入，而它需要一条**引擎签发的、绑定到 running
workflow** 的 session envelope。本迭代 snapshot 是 `running` 且 `catalog_execution_bindings` 已有它的
committed 行，所以：**Phase 3 的第一个动作**是把 coordinator 绑到本迭代 workflow
（`mstar plan bind --coordinator --workflow iter-2026-10-register-burndown --session-id <id>`），
之后 `issue close --id … --expect <revision>` 才可用。不要引用 `I-000186`（"close channel unreachable"）
当作本轮不可关闭的依据 —— 那条测的是「所有既有 snapshot 都 terminal」的状态快照。

## Promotion candidates（Phase 3 提升时处置）

| Candidate | Intended target | Note |
|---|---|---|
| B1 的「一次调用 = 一个 run，且 run 必须收尾」契约 | `{KNOWLEDGE_DIR}/architecture-patterns/` | 与既有 `run-scoped-asr-provenance.md` 同一族，提及时**合并**而非新增 |
| B2 的「journal 解码策略单一来源」规则 | `{KNOWLEDGE_DIR}/architecture-patterns/` | 与 `AttemptLedger` 的严格规则同址，避免两处规则各说各话 |
| B3 的「空清单与看不见的清单是同一返回值」推论 | `{KNOWLEDGE_DIR}/architecture-patterns/subtitle-acquisition-contract.md` | 既有文档的修订而非新文档；**并且**要补上「有凭据的观测」这一维度（`I-000210` 抬升的是证据标准：`credential_present` 只记存在、不记有效 —— 有效性的缺口是 `I-000041`） |

## seat-1（product-manager）复核要点（2026-10-06）

- `I-000041` 的排除**成立**，但依据是 occurrence payload 里的 `decision`/`target`（裸 token 不是决定），
  且它**没有承接者** —— 见 compass `## Non-Goals` 的专节与 `## Roadmap Position` 的非产品段。
- `I-000195` 已于 2026-10-04 `resolved`，compass 与 `docs/roadmap.md:38-42` 把它当作未关的 Phase 0.5
  前置是**前提漂移**（compass D13）。
- 三份 plan 各新增一节 `## 产品侧判定`，标出初稿里**判错的前提**与**窄于 acceptance 的 Files 面**；
  architect（第 2 席）应把它们当作输入而不是旁注。
