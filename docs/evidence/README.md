# 实测与实验记录

[返回文档入口](../README.md)。这里保留独立的生产、存储、CPU/GPU 和质量测量及其原运行日期、源码身份、环境、失败和测量口径。它们用于复核历史行为，不能据此报告当前版本测试结果或生产状态。当前操作见 [使用指南](../guides/README.md)、[ASR](../asr/README.md) 和 [运维](../operations/README.md)；当前图表验收见 [architecture-validation.md](../architecture-validation.md)。

## 生产迁移与存储

| 报告 | 原始记录 | 范围 |
| --- | --- | --- |
| [真实生产副本升级 · 2026-10-11](production-upgrade-validation-2026-10-11.md) | [JSON](production-upgrade-validation-2026-10-11.json) | 全量保真、来源标题、Reader、快照恢复与成本 |
| [在线产物存储 · 2026-10-11](artifact-online-validation-2026-10-11.md) | [JSON](artifact-online-validation-2026-10-11.json) | 多进程、崩溃、soak 与 Windows 验收范围 |

## ASR 质量与性能

| 报告 | 原始记录 | 范围 |
| --- | --- | --- |
| [公开中文样本 · 2026-10-08](asr-public-samples-2026-10-08.md) | [FLEURS](asr-public-fleurs-results.json)；[60 秒](asr-public-controls-60.json)、[120 秒](asr-public-controls-120.json)、[180 秒](asr-public-controls-180.json) | CPU CER、人工拼接、静音对照及单条 CPU 链路样本；[Smoke JSON](asr-wsl-smoke.json) |
| [4090 ASR · 2026-10-11](asr-gpu-validation-2026-10-11.md) | [JSON](asr-gpu-validation-2026-10-11.json) | 固定样本、GPU 时间线、策略回退与生产恢复 |
| [双声道混音优化](asr-stereo-mix-performance.md) | [实现验收 JSON](asr-stereo-mix-implementation-2026-10-11.json) | CPU 快速路径、数值兼容与不能外推的性能结论 |

上述 JSON 保留原字节和摘要。复现时使用独立输出目录；不要覆盖旧结果或把历史成功写成新的验收。
