# CI 热点优化验证（2026-10-12）

优化分支为 `codex/ci-performance-20261012`，实现以主分支
`84426f01451255ab81080715aa1b2f284c1c586f` 为基础。原工作区起点
`eea90ad1b6a739527b1f7bce67e680f5ec96a3db` 保留在原快照分支中。

## 诊断依据

评估实时读取 GitHub Actions 运行、job/step 时间，并下载两个成功 run 的
全部四片 JUnit 和归属计划。近期成功 CI 总耗时约 13–14 分钟；
[run 38241838619](https://github.com/SuperCatQR/bilibili-asr-archive/actions/runs/38241838619)
的四个 pytest step 分别为 666 / 623 / 706 / 467 秒，关键路径为测试执行。
正常依赖安装只需 1–3 秒，coverage 汇总约 20–29 秒。

在 [run 38239158375](https://github.com/SuperCatQR/bilibili-asr-archive/actions/runs/38239158375)
与 [run 38238477041](https://github.com/SuperCatQR/bilibili-asr-archive/actions/runs/38238477041)
中，preserved body import、archive upgrade、source supplement、description
supplement 四个文件合计只有 102 个节点，却占累计 testcase 时间的
56.89% / 57.88%。JUnit 包含 setup/call/teardown，不能把跨 runner 累计时间
当成工作流墙钟时间。

本地 cProfile 的代表性用例中，SQL 规范化 28,858 次调用累计 11.569 秒，
约占带分析器运行时间的 56%。迁移 fixture 在每个测试中重复建立、迁移、
安装扩展和检查档案，也是明显重复成本。分片原权重源于旧 WSL 运行，不能
继续准确估计优化后的成本。

## 实现

- 给纯 SQL 文本规范化添加两个容量为 2,048 的 LRU 缓存。每次契约检查仍
  读取实际 `sqlite_master`，不缓存“数据库已验证”的结论。回归覆盖同连接
  和其他连接对预热 schema 的修改。
- session fixture 一次准备迁移模板，每个测试复制独立数据库和 artifact
  文件，再打开自己的连接并记录自己的测试权限。复制拒绝 WAL/SHM/journal
  sidecar；迁移验收仍执行实际迁移。
- 从完整四片 JUnit 刷新按文件平均节点耗时，保持四个分片和完整默认集。
  CI 自动产生可审查的候选 artifact。最新重跑缺报告、测试失败、非法耗时
  或完成数量不匹配时拒绝更新旧提示。
- 测试 checkout 使用浅克隆，并单独获取精确 PR base / push before SHA，
  保留契约发布门禁。
- ffmpeg/ffprobe 已可用时立即返回；否则只更新签名的 Ubuntu 官方源，有限
  超时并切换官方镜像回退。脚本不改 runner 的系统源文件。
- lease 心跳保留实际取消异常，消除 API 返回与取消观测之间导致
  `JobCancelledError` 被替换为普通 `LeaseLostError` 的竞态。

主分支现有 weekly 回归、UTF-8 设置、锁定依赖、许可证检查、完整诊断、
回归摘要和产品覆盖率门槛均保留。未增加 runner 矩阵规模或降低覆盖率门槛。

## 同环境热点对照

Ubuntu 24.04 WSL、Python 3.12.3，两个独立源码树，使用同一组已准备好的
依赖，顺序执行 `test_description_supplement.py` 的 8 个测试。两轮都启用
branch coverage，均 8 passed；对照期间没有并发全量测试。

| 代码 | 进程墙钟 | pytest 报告耗时 |
| --- | ---: | ---: |
| 未修改的最新主分支 `84426f0` | 113.63 秒 | 113.07 秒 |
| 最新主分支加本次优化 | 7.15 秒 | 6.65 秒 |

该测试组进程墙钟下降约 93.7%。这是热点样本的同环境结果，不能外推为整个
GitHub CI 的提速比例。原工作区上的早期对照为 105.61 / 6.24 秒，两轮同样
通过；最终结论优先使用上表最新主分支对照。

## 全量与审查

完整验证在四个独立 Linux 源码树中并行执行，临时目录位于源码树外。
实际命令为：

```bash
python scripts/pytest_shard.py --shard-index <0..3> --shard-count 4 \
  --plan-output test-results/shard-plan.json --coverage -- \
  -q -ra --durations=15 --basetemp <outside-checkout> \
  --junitxml=test-results/pytest-<1..4>.xml
```

最新主分支首轮全量为 3,343 passed / 11 skipped / 0 failed / 0 errors，
四片包含全部 3,354 个唯一节点，归属计划互斥且一致。四片进程墙钟分别为
251.95 / 227.87 / 237.40 / 248.40 秒。合并覆盖率为产品行 84.81%
（22,159 / 26,127）、产品分支 74.25%（6,957 / 9,370），高于 75% / 63%
门槛。这轮结果用于最终耗时权重，最终权重的复验数据见同名 JSON。

最终权重的第二轮全量同样为 3,343 passed / 11 skipped，分片互斥且覆盖全部
3,354 节点。四片进程墙钟为 250.45 / 243.92 / 243.85 / 240.38 秒；产品
行覆盖率 84.79%（22,152 / 26,127）、分支覆盖率 74.26%（6,958 / 9,370）。
两轮均通过既有门槛；并发路径的覆盖计数存在小幅波动。

环境复用了已准备好的虚拟环境与离线 wheelhouse，核对 65 项已安装 Linux
测试依赖均满足 `uv.lock`。此处耗时只计收集、门禁和带 coverage 的 pytest
进程，不包含 GitHub runner 排队、checkout、依赖准备或 artifact 上传。
尚未触发远端优化分支 CI，因此不能宣称 GitHub 实测从 13 分钟降到 4 分钟。

Ruff 阻塞规则与新增 Python 文件的未定义/未使用检查、compileall、actionlint
和 `git diff --check` 均通过。独立 `gpt-6-astra` 审查在迁移到最新主分支后
未发现 Critical / Required 问题；取消异常和报告完整性两项变异实验均被相应
回归测试拦截，原文件已恢复。

## 保留的失败证据

- 原工作区全量首轮暴露了复制 conftest 的隔离诊断测试不应依赖新增 fixture
  模块，以及本地 basetemp 不应在源码树中。已改为延迟导入并把临时目录移到
  树外，后续原工作区和最新主分支的完整 Linux 测试均通过。
- Windows 首轮暴露未指定 UTF-8 的 fixture JSON 读取，已显式指定编码。
- 最新主分支 Windows 专项为 114 passed / 1 failed；失败为
  `test_concurrent_identical_batches_share_the_same_editions`，堆栈指向已有
  `file_ops.exclusive_lock` 读取被字节锁占用的 marker。用未修改的主分支源码
  独立复现同一失败（1 failed），确认不是本次优化引入；Ubuntu 全量对应
  并发测试通过。未把 Windows 结果表述为全绿。
- 离线重新解析准备阶段遇到 cache/wheel 不完整，保留失败日志后复用已有
  环境，再按锁文件核验版本。未修改依赖锁文件。

原始本地证据位于 `.tmp/ci-assessment-20261012/` 和
`.tmp/ci-opt-20261012/`，包括 GitHub 响应、JUnit、归属计划、完整日志、
初次失败日志、依赖清单、对照测量与变异实验。同名 JSON 保存关键数值与
JUnit/日志哈希；这些本地路径不保证在其他机器存在。
