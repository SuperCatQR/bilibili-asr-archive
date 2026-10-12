# 项目质量与发布管理

## 合并门禁

默认 CI 要求全量 Linux 四分片、Windows 文件锁与恢复回归、产品安装验证、
锁定依赖审计、Ruff 和渐进类型检查通过。行覆盖率至少 80%，分支至少 70%。
PR 的新增/修改产品 Python 文件逐文件要求至少 90% 的修改行覆盖率，分母仅
包括可执行行；新增的 coverage exclusion 仍计为未覆盖，不允许用 pragma
绕过。删除行和注释不计入。差异与精确 PR base SHA 比较，缺少报告明确失败。
行覆盖不证明断言或所有输入组合正确，关键异常分支必须独立审查。

覆盖 artifact 包含 `changed-coverage.json`、`coverage-risks.json` 和 Markdown
清单。风险清单优先列数据库、工作流、发布、文件写入和备份恢复的未覆盖分支，
同时保留具体行号与排除行。每次修改先查相关模块，并把实际缺陷补成回归。
全库总覆盖率下降仍超过门槛时，需要在 PR 解释原因；当前不以小数波动机械
阻塞并发代码重构。禁止为了数字删除验收用例或排除产品模块。

Ruff 全库阻塞 E9/F821/F822/F823。mypy 从 filesystem 与 schema 两个无应用
依赖的边界模块开始，严格模式检查；其他模块尚未宣称通过类型检查。mypy
作为 dev 依赖锁定，不进入产品运行时依赖。Windows 分支由 Windows runner
实际执行，Linux mypy 无法替代 Windows 运行验证。

首次创建输出锁要求同目录文件系统支持硬链接（如 NTFS、ext4）；先完整初始化
私有文件再原子发布锁名。不支持硬链接时明确拒绝写入，不降级为会覆盖持有者
inode 的方案。已有锁文件继续沿用原文件名和 marker。

## 关键行为验收矩阵

| 风险 | 必须验证的行为 | 当前回归入口 |
| --- | --- | --- |
| 数据丢失 | 完整备份恢复、损坏拒绝、目标不覆盖、空间不足 | `test_archive_snapshot.py`、`test_reference_backup.py` |
| 历史破坏 | 迁移保留记录、文件、失败 attempts 与 holds | `test_migration_preservation_baseline.py`、`test_archive_upgrade.py` |
| 重复执行 | 多进程 claim、幂等导入、并发补充 | `test_workflow_issue_regressions.py`、`test_source_supplement.py` |
| 取消后写入 | 迟到的 API 返回、租约回收、原始诊断保留 | `test_workflow_cancellation.py` |
| 文件与锁 | 原子写、短写、失败清理、Windows 阻塞竞争、损坏 marker | `test_file_ops.py`、`test_export_lock.py` |
| 来源与质量 | 空字幕与静音区别、时间戳与发布契约 | `test_live_subtitle_smoke.py` 离线分支及现有质量/发布回归 |
| 真实环境 | 上游 API、规模、实际模型识别与对齐 | 显式验收入口与实机证据，不由 mocks 推断 |

风险报告是持续补测的清单，并不表示所有关键分支已覆盖。PR 模板要求记录
行为变化、测试、独立审查、平台限制和恢复方案。小改动保持单一目的；依赖
更新逐包审查，检查版本、许可、传递依赖和锁文件，不批量升级后盲目合并。
个人维护时不要求自己批准自己的 PR；重要改动提供独立审查证据和 CI。

## 发布前执行

1. 以完整提交 SHA 标识版本，确认 main 的全部必需检查通过，保存 wheel、
   sdist、BUILDINFO 与 SHA256SUMS。填写[发布模板](version-release-template.md)。
2. 手动运行 `Release validation` 的 recovery 范围，在临时目录用合成档案
   演练备份、损坏拒绝、恢复和历史保真。真实生产备份另按
   [快照手册](../operations/archive-snapshots.md)恢复到新隔离目录并核验，
   不覆盖源库，不自动启动 worker，不清除 holds。
3. 改动网络边界时显式运行 live 范围。匿名风控、不可用样本等 skip 会使
   验收判为未完成，保留 JUnit；不得把“测试命令退出 0”当成真实验证通过。
   该范围最多请求现有有界 metadata/subtitle 探针，不下载媒体，不调用 AI。
   在仓库 Actions variables 配置已有真实依据的 `BILI_PLATFORM_ACCESS_REFERENCE`
   与 `BILI_CONTENT_PROCESSING_REFERENCE`，只填私有记录的非敏感编号；有登录
   需要时凭据仅放 `BILI_SESSDATA` secret。缺少依据时保留阻塞，不临时关闭策略。
4. 涉及规模时显式运行 scale 范围。空测试集或 skip 都不能提供成功证据。
   当前对 SQLite 工作流验证 1,001 和 10,001 个分 P（3,003/30,003 个任务）的
   规划、幂等重放、领取和失败历史保留，记录规划耗时；不把它当成模型吞吐测试。
   这类运行不与每次 PR 的快速默认集混合。
5. 涉及 ASR runtime、模型、精度、GPU 驱动时，在目标实机执行
   [GPU 验收](../operations/quality-and-release.md)，记录实际版本、绑定身份、
   识别/对齐输出质量、耗时和显存。无可用硬件时明确 blocked，不能用 CUDA
   可见、张量运算或 mocked 模型替代真实推理。
6. 生产发布先停止新增领取并安排 worker 交接，保留原环境、原档案和完整
   验证备份。代码回退不撤销数据库迁移；需要恢复数据时只使用核验过的
   备份和显式恢复计划。发布后先小范围验证再恢复正常工作量。

仓库没有自动发布到生产或自动升级生产依赖的任务；合并通过不等于实机发布。

## 每周与每次故障

- 查看 CI 是否稳定：同一提交重跑才通过属于待定位问题，保留首次 JUnit、
  日志、归属计划和环境，区分代码、测试、上游和 runner 故障。不得默认无限重跑。
- 查看 CI 耗时和风险清单：四分片是否失衡、最慢文件是否变化，完整默认 CI
  以约 5 分钟为维护目标，持续超过 10 分钟再采样分析；不是用超时截断测试。
- 查看安全提醒：Dependabot、secret scanning 和推送保护；泄露凭据应立即
  在服务商撤销并轮换，删除提交不能使它失效。
- 查看生产健康：队列停滞、最新失败、worker/重试维护分别是否新鲜、磁盘
  余量与 AI 调用成本。详见[运行检查](../operations/quality-and-release.md)。
- 每次线上缺陷补回归；记录触发条件、受影响的 job/attempt、原始错误、
  恢复结果与残余风险。历史失败和 holds 保留，修复不等于立即授权全部重试。

参考：[Google 测试覆盖率实践](https://testing.googleblog.com/2020/08/code-coverage-best-practices.html)、
[coverage.py 分支测量](https://coverage.readthedocs.io/en/latest/branch.html)、
[uv Dependabot 集成](https://docs.astral.sh/uv/guides/integration/dependabot/)。
