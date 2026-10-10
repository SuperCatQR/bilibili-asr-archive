# Perf 首批实现与 WSL 验证

日期：2026-10-10。开发基线为 `origin/main` 的 `472229804283655e877a3dd01764e4991a807cc9`，独立分支为 `codex/asr-perf-evidence`。

## 本次范围

| Issue | 本次交付 | 尚未验收 |
| --- | --- | --- |
| #295 | 深度 1 预取的版本化估算、逐块准入、观测大小、等待、回退和丢弃证据；未知大小安全回退；异常清理 | 用真实 processor 校准估算、RSS/VRAM 与真实吞吐 A/B |
| #299 | 带 chunk index 的 prepare/transfer/forward/postprocess 对齐 wall trace | 对齐 batch、compile、真实收益及质量 |
| #301 | 只读固定窗口汇总；唯一音频、并发共同分母、失败/重试、延迟分位数、分组与未知值 | execution envelope、失败阶段资源、硬件身份、发布吞吐 |

三个 issue 均只完成上述子范围，不能因本次离线回归通过就关闭整项。下一批按已有评估推进 #298 的 CPU token-budget 元数据与版本化执行身份，再衔接 #296/#297 的后端端口与有界同任务 batch；#292/#302 的硬件实验仍需真实设备验收。

## 隔离环境与源码身份

- Windows managed worktree：`C:\Users\ChosenEcho\.codex\worktrees\asr-perf-evidence\bilibili-asr-archive`。
- 本地 WSL2：`Ubuntu-24.04`；原始源码字节通过 rsync 复制到 Linux 文件系统 `/home/chosenecho/asr-perf-evidence-20261010/repository`，测试不在 `/mnt/c` 执行。
- 独立 Python 3.12.3 环境：`/home/chosenecho/asr-perf-evidence-20261010/venv`。复用已有测试依赖目录，当前分支先构建 wheel 再安装至新环境；coverage 包及其子进程启动 `.pth` 单独复制到该环境，避免仅共享依赖路径时启动 hook 不生效。生产配置不被改写。
- pytest 9.1.1、coverage 7.16.2、Ruff 0.16.10；真实轻量音频库 numpy 2.5.3、soundfile 0.14.0、soxr 1.1.0。模型由既有 fake 替代；进程/session 与音频路径按测试实际执行。
- 381 份源码/测试/脚本/schema/配置文件的 Windows 与 WSL 字节逐份一致；wheel 中 157 份产品源文件与测试副本字节一致。机器凭据见 [validation JSON](perf-evidence-validation.json)，完整 manifest 和日志保存在上述 WSL 目录。

初次完整测试发现旧虚拟环境仍 editable 指向 10 月 8 日源码，导致 `test_installed_package_bootstraps_schema_and_status` 的子进程加载旧 schema。该运行被中止，不能作为最终通过证据。独立环境安装当前 wheel 后，该测试和聚焦回归重新通过；最终完整运行单独记录。

后续完整运行发现：关闭预取时提前访问 `processor`，破坏原有自定义 chunk 解码测试；现仅在启用时访问，原 raw 发布测试保持原断言并通过。另修复了测试环境缺失 coverage 子进程启动 hook，coverage 自检重新通过。两次中止运行的数据均不混入最终覆盖率。

聚焦重跑期间遇到一次 supervisor 等待超时（同期 Windows 命令启动器报告内存不足），以及 `/proc/<pid>/stat` 打开后 PID 被回收导致 ESRCH 的既有测试竞态。后者补充捕获 `ProcessLookupError`，仍要求原期限内 child 退出，没有扩大 timeout 或增加 skip。最终聚焦回归通过。完整测试使用仓库现有四分片脚本，在四份独立 Linux 副本执行，限制同时运行两片；最终报告核对所有 testcase 身份唯一且覆盖全部 2392 项。

## 验证结果

最终完整套件 **2381 passed、11 skipped、0 failed / 0 errors**（440.74 秒）。产品源码行覆盖率 **82.84%**、分支覆盖率 **71.88%**，分别通过仓库 75% / 63% 门禁。跳过项保持既有测试条件，逐项原因见保存的 JUnit。

已完成的检查：

- 聚焦回归 **171 passed**：预取、真实 workflow 落库、真实 CLI 只读、报告边界、质量、session、worker、安装包 baseline、raw 发布与 coverage 自检。
- CI 阻断检查 `ruff check src tests scripts --select E9` 和 `compileall -q src tests scripts` 通过；`git diff --check` 通过。
- wheel 与 sdist 构建成功；在源码目录外使用已安装 console script 生成报告，成功返回 0，静止归档 DB/sidecar 字节不变；缺库返回 1，且不创建归档目录。
- 把预算边界 `>` 故意改为 `>=`，180 秒边界测试失败；把共同窗口吞吐分母故意改为 attempt 耗时总和，重叠/双遍/重试测试失败。均以 assertion failure 退出 1；原字节恢复后相关 **29 passed**。变异仅在独立副本运行。

五维评审覆盖正确性、可读性、架构、安全和性能：准备线程只返回结果，诊断由调用线程合并；报告存储查询与服务聚合分层；SQL 参数化、白名单聚合、不复制逐块正文；单快照和调用者事务保护；attempt 数量硬限额且超限拒绝，不输出不完整结果。评审修复了重试的时间排序、丢弃输入引用保留、非法 schema 类型与损坏 pass 数组的误统计。单份历史 JSON 及 SQLite 扫描成本仍随历史数据大小增长，详见使用指南。

## 可复现检查

在独立 Linux 测试副本中，使用安装了该副本构建 wheel 的环境：

```bash
python -m pytest tests/test_installed_baseline.py tests/test_asr_performance.py \
  tests/test_asr_prefetch.py tests/test_asr_qwen.py tests/test_asr_quality_foundation.py \
  tests/test_asr_sessions.py tests/test_workflow_workers.py tests/test_raw_characters.py \
  tests/test_test_coverage_gate.py -q
python -m ruff check src tests scripts --select E9
python -m compileall -q src tests scripts
for shard in 0 1 2 3; do
  python scripts/pytest_shard.py --shard-index "$shard" --shard-count 4 --coverage -- \
    -q --durations=10 --junitxml="shard-$shard.xml"
done
python -m coverage combine
python -m coverage json -o coverage.json
python scripts/check_test_coverage.py coverage.json --line-min 75 --branch-min 63
```

本次真实命令使用上述独立环境的 `bin/python`，并把 `COVERAGE_FILE` 设置到单独的 `sharded-coverage/.coverage`，避免混入中止运行或变异副本的覆盖率。以上循环可串行复现同一分片集合；本次在独立副本以两路并发运行。日志及 JUnit、coverage JSON、构建物和摘要保留在 `/home/chosenecho/asr-perf-evidence-20261010/`。

离线测试证明边界、诊断和统计契约，不证明 GPU 性能提升、真实模型质量等价或默认预算适合长音频。默认预取仍关闭、预算仍 64 MiB，180 秒块仍按 703.125 MiB 保守预留处理；这些选择保留到有实测证据时再调整。
