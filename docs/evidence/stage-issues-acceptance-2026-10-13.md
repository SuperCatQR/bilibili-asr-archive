# 阶段审查修复与验收 · 2026-10-13

本记录对应 [阶段审查总览 #415](https://github.com/SuperCatQR/bilibili-asr-archive/issues/415)。审查发现的产品问题已有实现和回归测试，交付保持为 Draft PR。真实模型对照没有取得成功响应，#412 的模型能力、语义质量、实际 usage 和成本验收仍未完成。没有合并、部署或改动生产归档。

## 源码身份与验证范围

| 身份 | 固定值 |
| --- | --- |
| 修复比较基线 / 验收时远端 main | `b07c51c5e38ef9680572a393e185d5a77b61579e` |
| Linux 全量验收提交 | `19b118e8c39323763630716ecf29000158ac1af1` |
| 分层 PR 最终实现提交 | `feb88b0ae8eb35a87b7a56b4656a3be9371919de`，PR #435 |
| 上述两个提交共同的 Git tree | `7bf7439a2a80ef61053291f034d326065b95e15d` |
| 验收日期 | 2026-10-13，Asia/Hong_Kong |

全量验收提交与 PR #435 的文件树完全相同。随本记录增加的证据文件和索引属于文档变更；这里的测试结果绑定上述固定实现树。审查阶段的原始失败、历史 issue 描述及中间运行没有被改写为成功。

## 目标、问题与实现

| 目标 | 已确认问题 | 修复边界与审阅入口 |
| --- | --- | --- |
| 保留两平台原字段，使用超集统一 | #401 原始字段不可逆丢失；#402 Bilibili 多行简介丢失；#403 YouTube 简介、标签、封面未进入持久事实 | [#417](https://github.com/SuperCatQR/bilibili-asr-archive/pull/417)、[#422](https://github.com/SuperCatQR/bilibili-asr-archive/pull/422)、[#424](https://github.com/SuperCatQR/bilibili-asr-archive/pull/424)：追加原始观测、版本化投影、实际接受字段的凭据与离线重投影；[#432](https://github.com/SuperCatQR/bilibili-asr-archive/pull/432) 补有界批量读取及冻结证据集成 |
| 音频到 ASR 的实际输入可验证 | #404 音频被替换仍可使用旧 hash；#405 最终文件安装缺少持久化边界 | [#418](https://github.com/SuperCatQR/bilibili-asr-archive/pull/418)：验证实际字节和文件 generation，固定推理输入，持久化安装；[#434](https://github.com/SuperCatQR/bilibili-asr-archive/pull/434) 覆盖替换、ABA 与失败清理 |
| 独立音频归档、压缩备份及显式条件删除 | #406 缺少独立自动生命周期 | [#421](https://github.com/SuperCatQR/bilibili-asr-archive/pull/421)：独立 policy runner、显式 `allow_delete`、副本和 hold 检查、逐对象回执、容量及锁边界；压缩只针对媒体包 |
| 全任务状态自动备份，保留失败与控制状态 | #407 holds/ledger 不能完整往返；#408 OpenCode doctor 使用错误的凭据判断；#409 只读备份检查额外落盘媒体 | [#419](https://github.com/SuperCatQR/bilibili-asr-archive/pull/419)：scoped typed retry 状态、endpoint 凭据选择、流式检查；任务状态包不压缩，支持离线 reader |
| 音频已迁出后仍能备份及读取状态 | #426 冷音频缺失使任务状态备份失效 | [#431](https://github.com/SuperCatQR/bilibili-asr-archive/pull/431)：显式 v2 冷媒体引用，记录副本及冻结原始身份，离线状态读取不要求恢复媒体；[#435](https://github.com/SuperCatQR/bilibili-asr-archive/pull/435) 提供真实 SSH 与恢复失败边界测试 |
| ASR 质量在付费下游前阻断 | #410 倒退时间线仍可进入 AI 校对 | [#420](https://github.com/SuperCatQR/bilibili-asr-archive/pull/420)：保存原始输出与质量证据，准入失败明确阻断，修复使用新版本；保留旧 attempts 与 hold |
| 校对预算、较大分块与可审计重试 | #411 字节/token 单位漂移；#412 段数上限长期主导分块；#413 replay 全库扫描；#425 provider response ID 与预算/重试投影不完整 | [#423](https://github.com/SuperCatQR/bilibili-asr-archive/pull/423)：冻结 `token-budget-v2`，定向 replay 索引，显式 baseline/large preset，对照物理调用预算及未知 usage/cost；真实模型结果见下文 |
| 最终产物完整来源链 | #414 缺少统一 reader 与可携带索引 | [#427](https://github.com/SuperCatQR/bilibili-asr-archive/pull/427)–[#430](https://github.com/SuperCatQR/bilibili-asr-archive/pull/430)：最终产物、release、edition、冻结输入、transcript、实际 ASR 与 AI 调用、原始平台观测及音频身份；私有导出与授权公开摘要各自校验 |
| 跨模块故障与篡改边界 | 单纯成功路径不足以证明身份和恢复闭环 | [#433](https://github.com/SuperCatQR/bilibili-asr-archive/pull/433)、[#434](https://github.com/SuperCatQR/bilibili-asr-archive/pull/434)、[#435](https://github.com/SuperCatQR/bilibili-asr-archive/pull/435)：重新封装摘要后仍拒绝错误证据、真实文件竞争、事务中断、cold 引用及 provider/retry 非法控制 |

旧 Draft PR 的独立分支没有包含所有后续集成修复，其中部分当前 head 的 CI 仍有失败；它们用于逐模块审阅，不能把集成测试成功当作各旧分支都通过。#432–#435 的当前 head 已通过 GitHub 检查。本次对 main 的完整交付候选包含整个实现树、后续测试与本证据，保留 Draft 状态。

操作说明见 [原始平台观测](../operations/platform-observations.md)、[音频保留策略](../operations/audio-retention.md)、[任务状态自动备份](../operations/task-state-automation.md)、[离线状态读取](../operations/task-state-reader.md)、[ASR 准入与修复](../operations/asr-admission-and-repair.md)、[校对预算及对照](../operations/editorial-budget-and-comparison.md) 和 [产物来源链](../operations/artifact-provenance.md)。

## 最终 Linux 全量回归

测试在授权测试服务器的独立 checkout 和临时输出目录执行。Python 3.12.15、pytest 9.1.1、coverage 7.16.2；本轮没有启动生产 worker 或 GPU 推理。四个分片使用同一收集清单，分配 4,486 个唯一节点，没有重复或漏分；JUnit 节点数量与分片选择一致。

| 指标 | 最终值 |
| --- | --- |
| 测试总数 | 4,486 |
| 通过 / 失败 / error / 跳过 | 4,470 / 0 / 0 / 16 |
| 四分片运行及汇总用时 | 742.06 秒 |
| 执行行覆盖 | 29,488 / 33,700，87.50% |
| 分支覆盖 | 9,968 / 12,682，78.60% |
| coverage 综合展示值 | 85.07%，不能与纯执行行比例混用 |
| 现有全量阈值 | 行 80%、分支 70%，均通过 |
| 变更行检查 | 109 个产品文件，4,369 / 4,582 个变更行已覆盖，每个文件至少 90%，检查通过 |

16 个跳过分别是：7 个已退休的旧 CLI/manifest 路径、3 个未显式启用的真实平台 smoke、2 个未启用的 1,001/10,001 分页 scale 用例、1 个 Windows junction 用例和 3 个仅面向 Ubuntu 24.04 CI 的 ffmpeg 安装用例。全量成功不等于这些场景已在此次 Linux 环境执行。其逐节点原因保存在 [跳过清单](stage-issues-2026-10-13/skips.json)。

测试入口为 `scripts/pytest_shard.py`，四片各启用 coverage，指定相同 `--contract-baseline-ref`。合并执行记录后运行 `scripts/check_test_coverage.py --line-min 80 --branch-min 70` 和 `scripts/check_changed_coverage.py --base <基线> --line-min 90`。没有降低阈值、修改 allowlist 或把 mutation 失败记录混入最终覆盖率。

[全量结果](stage-issues-2026-10-13/linux-result.json) 保留固定提交、四片统计和完整性检查；[逐文件变更覆盖](stage-issues-2026-10-13/changed-coverage.json) 保留覆盖及未覆盖行。Windows 本地的 mypy、Ruff 致命错误检查、compileall、锁文件/依赖导出和契约文档检查通过；这不替代 Linux 全量结果。#432–#435 另有 GitHub Windows、打包、安全和四片测试检查。

## 冻结历史与反向验证

原有 36 个已发布数据库 schema fingerprint 保持不变，新组合通过追加注册进入升级路径。注册升级边共 24 条。以下冻结 fixture 没有改写，回归保留原 hash、行身份、原始失败、输入/请求字节及历史 producer 选择：

| Fixture | SHA-256 |
| --- | --- |
| `bilibili-v1-frozen.zip` | `20790dfc0acec3dda5707cb534907374c458f99b04f1947dc865ffe67b93770b` |
| `bilibili-v1-frozen.json` | `2e2d67cac953c115d541e210cd663c91adc07327ff3c158947eb0e9621849844` |
| `contracts-release-baseline-v1.json` | `7ea6da1930354dbb5e871ae84828b189138d88a2b1467c33edd75174913f194e` |

后续边界补强新增 75 个来源/私有来源链用例、36 个运行时/音频 generation 用例和 48 个备份恢复用例。独立 mutation 曾临时移除实际音频 generation 防护及备份版本校验，相应用例确实失败；产品文件恢复后重新执行，最终全量使用恢复后的源码。篡改测试包含更新外层 hash 后仍不能通过的错误原始字段绑定，避免只证明摘要失配。

## 真实 SSH 冷存储与离线状态验收

`scripts/validate_cold_task_state_ssh.py` 在授权测试环境使用真实 Paramiko 连接临时 OpenSSH 服务，后端为 `ssh-directory/v1`。本轮结果 [cold-state-ssh.json](stage-issues-2026-10-13/cold-state-ssh.json) 为 passed，用时 4.575 秒。

- 显式策略压缩并迁出 14 字节样本音频，验证原始 SHA-256、包 SHA-256 和副本 generation；损坏远端副本被拒绝。
- 删除测试源和冷存储目标，随后停止 sshd，再执行离线状态 verify/read/record/extract。状态包使用 `ZIP_STORED`，所有表 ledger、失败 attempt、retry hold 与预算字节保持一致。
- 状态读取没有恢复媒体：`media_restored=false`、`media_restore_required=true`；外部音频引用仍可读取，但不会把已不可访问的媒体标记为当前已验证。
- 验收使用临时凭据和显式预建 remote root，禁用环境凭据；临时服务、密钥及目录在结束后清理。

这个样本证明传输、身份校验、显式媒体生命周期与断网后的状态读取边界。它没有测量长音频压缩率、长期空间收益、网络吞吐，也不是生产冷存储或真实断电验收。

## 真实模型对照：未通过的外部验收

用户授权最多 4 次物理调用。对照使用冻结的 300 段输入，source input ID 为 `e5ba726b502775884e475193980e43648ac34bcb9763fd59f70600a8d2722d43`，endpoint 为 `https://opencode.ai/zen/go/v1`，请求 model alias 为 `deepseek-v4.1-flash`。

| Preset | 规划 / 实际物理调用 | 结果 |
| --- | --- | --- |
| `baseline-v1` | 2 / 2；段边界 0、256、300 | 两次 `DeepSeekTransportError`，耗时 37,296 ms 和 30,187 ms；没有接受的 chunk |
| `large-v1` | 1 / 1；段边界 0、300 | `DeepSeekTransportError`，耗时 37,233 ms；没有接受的 chunk |

实际共 3 次，没有自动重试或第四次调用。规划结果显示 large 可以把该输入的请求数从 2 降为 1，但没有成功的 provider 输出，不能据此判断语义质量、完整性、实际成本或效率改善。baseline 两块估计请求 token 分别为 26,063 和 6,564；large 一块估计为 30,264。样本未触及 1M 边界。

1,048,576 上下文及 163,840 输出 token 是此次冻结配置，状态仍为 `config_only`，实际 provider capability 为 `not_verified`。usage 和 cost 均为 unknown；缺失计数不是零消耗。真实质量为 `not_reviewed`。默认保持 `baseline-v1`，large 必须显式选择。#412 继续开放，不能标为真实大上下文验收完成。

[脱敏模型报告](stage-issues-2026-10-13/editorial-comparison.json) 只保留预算、身份摘要和调用结局，不含密钥、请求正文、完整转录或 provider 原始响应。本轮测试凭据未进入代码、证据或 PR。

## 本轮结论的边界

本记录确认固定实现树的离线回归、既定覆盖率门槛、冻结历史兼容、显式文件维护流程、真实 SSH 与断网状态读取。真实平台字段覆盖范围仍受 endpoint、鉴权和返回内容限制，应读取完整性报告及原始观测；本轮未做两平台实网完整性认证。真实 GPU 质量、长时存储收益、真实掉电和 #412 的成功模型输出仍需要独立验收。

所有修复 issue 与 Draft PR 保留审阅状态。后续合并应以完整候选对 main 的 diff 和当前 CI 为依据，合并后重新固定发布身份；本记录不会把 Draft 交付写成生产已部署。
