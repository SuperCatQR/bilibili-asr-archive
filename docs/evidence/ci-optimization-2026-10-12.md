# CI 优化验收记录（2026-10-12）

## 改动与范围

以提交 `7409c50dc6de0c2c558d44ba6edbebc5308bbda2` 的工作树为基础优化主仓库 CI。仅改动 `.github/workflows/ci.yml`、分片脚本、新增耗时提示及其回归测试，并更新 CI 使用文档。保留原有四片 job 名称、必需检查接口、默认测试范围、契约发布门禁以及 75% 行 / 63% 分支覆盖率门槛。验证命令全部在 WSL Linux 中执行。

- 使用固定 uv 0.11.14；setup-uv 固定官方提交 SHA，缓存按 `uv.lock` 及 job 区分。
- 产品测试依赖由 `uv sync --locked --extra dev` 安装；审计及产品 wheel 的运行时安装使用锁文件导出的要求。Ruff、pip-audit、coverage 版本从锁文件读取；pip/setuptools/wheel 继续作为隔离安装所需的构建工具单独安装。
- 测试按文件保持在同一片，减少 module fixture 重复初始化；按照历史每节点耗时乘实际节点数做确定性负载分配。新文件也参与分配，历史记录不用于过滤测试。
- 使用 pytest 参数文件，避免长节点列表进入系统命令行；空片明确退出，失败码原样传回。契约发布检查仍在执行分片之前进行。
- `RUNNER_TEMP` 中创建 pytest 临时根，离线 wheelhouse 使用 runtime constraints。
- 上传完整日志、JUnit、分片计划、审计 JSON；显式 Bash 启用 pipefail，日志 tee 不会掩盖测试失败。
- artifact 名称加入 run attempt，覆盖率合并保留同一 run 中不同尝试的成功片；覆盖数据一级压缩，已压缩发布包零压缩。

## 实际验证

四个 WSL 原生目录分别安装锁定依赖、各自执行完整分片，源码树和临时根彼此独立。合计 **3154 passed、11 skipped、0 failed、0 errors**，包含新增 11 项 CI 回归测试。重新收集 3165 个节点并验证四片互斥、并集相等、同一文件唯一归属。

| 分片 | 节点 | 通过 | 跳过 | pytest 耗时 |
| --- | --- | --- | --- | --- |
| 1 | 1081 | 1077 | 4 | 587.36 秒 |
| 2 | 679 | 674 | 5 | 564.19 秒 |
| 3 | 798 | 797 | 1 | 467.81 秒 |
| 4 | 607 | 606 | 1 | 461.25 秒 |

使用修改后的 coverage job 的实际 shell 命令汇总 217 个原始数据文件，独立安装锁定 coverage、combine、生成 JSON/XML、执行门禁均退出 0：

- 行覆盖率：21203 / 25128 = **84.38%**，最低 75%。
- 分支覆盖率：6663 / 9024 = **73.84%**，最低 63%。
- 新 quality job 的工具安装、Ruff E9、compileall 全部通过。
- 新 security job 的锁定要求导出、工具安装及漏洞审计通过；JSON 结果保留在独立验证目录。
- 新 package job 的 uv build、独立运行时安装、CLI help、契约文档镜像、SQL/JSON authority 字节核对、发布包 SHA-256 校验全部通过。
- 使用 runtime constraints 的离线 wheelhouse 下载通过；其后的隔离安装与 baseline 复测 **15 passed**。本地下载使用已有 wheel 作为来源，仍按同一锁定版本约束解析。
- `actionlint` 1.7.12、YAML 解析、18 段 Bash 语法检查通过。
- 分片 / 契约 / 覆盖率相关 focused suite **41 passed**；另在临时副本中移除空片保护，回归测试如预期失败，确认测试可以捕获该错误。原代码未被变异修改。

## 耗时解释与保留限制

初始调度提示来自此前 2026-10-12 全量 WSL JUnit，保存 source SHA 和日志摘要。按该样本估算，旧节点轮询四片约 429～533 秒，新文件分片约 485 秒/片；加入新增测试后估算约 488.6 秒/片。提示用于分配，不能保证 GitHub runner 的实际时间。

本次四片在同一 WSL 主机并行运行，实际 pytest 最大耗时约 9 分 47 秒。原 CI 已经四片并行，因此不能将此前本地单进程 32 分钟与本轮并行时间相比较，宣称这是 CI 提速比例。

第一次从空环境运行 uv sync 在本地 240 秒的准备上限内未完成，测试尚未开始；保留 `.tmp/ci-cold-install-*-20261012.log`。使用与锁文件摘要匹配的本机缓存 wheel 预热各环境后，实际 locked sync、工具前置检查和分片执行完成。该问题没有通过改锁文件或放宽测试断言规避；本轮不提供 GitHub 网络下的冷安装耗时保证。打包验证也使用本机缓存预热。

默认 live smoke 和 Windows junction 等 11 个跳过项沿用现有策略；实网/GPU 边界见此前 [项目回归记录](regression-test-2026-10-12.md)。本轮离线验证不改变这些结论。测试日志仍保留原有 malformed ZIP、ASR resource tracker 等运行时告警，没有屏蔽 warning。

GitHub 上实际 action 的安装、cache hit、artifact 传输及完整远端运行尚未触发；验证的是 WSL 中的相同 shell 命令、测试执行和覆盖率汇总。真实云端性能应以随后 CI 运行的 job 时间为准。

## 文件与证据

- [机器可读验收结果](ci-optimization-2026-10-12.json)：分片计数与耗时、覆盖率、step 退出码、源码摘要、日志摘要和环境预热说明。
- [CI 使用说明](../development/ci-coverage.md)：依赖安装、调度、重跑和本地复现。
- 原始日志：`.tmp/ci-shard-0-20261012.log` 至 `.tmp/ci-shard-3-20261012.log`，以及 `.tmp/ci-coverage-job-20261012.log`、`.tmp/ci-job-*-20261012.log`、`.tmp/ci-locked-wheelhouse-20261012.log`。
- 四片完整归属计划位于各独立验证目录的 `test-results/shard-plan.json`；目录见机器记录 `execution.base`。

CI 配置参考 [uv 官方 GitHub Actions 指南](https://docs.astral.sh/uv/guides/integration/github/)；节点参数文件参考 [pytest 官方调用说明](https://docs.pytest.org/en/stable/how-to/usage.html#read-arguments-from-file)。

## 提交前同步验收

2026-10-12 推送前远端 main 已更新至 `98904edbb01fd23a5c3fb857a27e919df6b34e70`，与原验证工作树出现业务提交分叉。本次在独立 WSL worktree 中以该远端版本为基础移植 CI 优化及历史回归记录，不合并原本地业务分支。上文全量测试与覆盖率数字仍对应原工作树，不能作为新远端业务版本的全量验收结论。

整合保留远端定时回归、UTF-8 环境、包许可证检查、JUnit 汇总和节点参数文件 helper。JUnit 汇总移到覆盖率生成之后，使失败报告不会阻止覆盖率诊断生成；删除 download-artifact 不支持的 `if-no-artifact-found` 参数。

新基线上的分片、契约、覆盖率和依赖锁专项测试共 **45 passed**。最终 actionlint、全部 19 段 Bash 语法、`uv lock --check`、Git diff whitespace 检查通过；JUnit 汇总用此前四片真实报告运行，输出 3154 passed、0 failed、0 errors、11 skipped。远端完整 CI 尚待分支 PR 或手动触发后验证。

## PR #384 远端验收与工作区后续整理

2026-10-12 17:24（Asia/Hong_Kong），[PR #384](https://github.com/SuperCatQR/bilibili-asr-archive/pull/384) 已合并为 `85d5795d8cc739fe81bfdee8a67eda17466b736d`。[远端 CI 38228504283](https://github.com/SuperCatQR/bilibili-asr-archive/actions/runs/38228504283) 测试源码为 `a61b8e191c723a11560f7f6a5f1deac242b510e2`；全部八项必需检查成功。

| 分片 | 通过 | 跳过 | pytest 耗时 |
| --- | --- | --- | --- |
| 1 | 749 | 3 | 403.29 秒 |
| 2 | 945 | 4 | 374.34 秒 |
| 3 | 835 | 1 | 382.98 秒 |
| 4 | 727 | 3 | 506.19 秒 |

合计 **3256 passed、11 skipped、0 failed**；质量、安全、打包及原有 75% 行 / 63% 分支覆盖率门禁均通过。这组结果补充了前文当时尚未触发远端 CI 的状态，前文 WSL 数字仍属于原记录版本，不作替换或混算。

原工作区 11 个未提交文件已保存为本地快照 `eea90ad`。其中八个与合并后的 main 内容一致，另外三个保留整合前的工作流、分片实现和验收说明。后续 PR 基于最新 main，保留已合并的定时、安全和报告检查，仅将本地 TemporaryDirectory 清理方式融入已有 `_write_node_ids()`，并记录本次远端验收。

后续变更验证全部在 WSL 进行：分片 / 契约 / 覆盖率 / 依赖锁专项 **46 passed**，actionlint、Ruff E9、Git whitespace 检查通过。临时模块中禁用目录清理后，新异常路径测试如预期失败，确认回归测试能发现该问题；生产文件未被变异修改。这次后续变更的全量 CI 应以对应 PR 的新运行结果为准。
