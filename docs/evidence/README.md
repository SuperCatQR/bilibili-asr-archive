# 历史验收与实验记录

[返回文档入口](../README.md)。这些记录保留原运行日期、源码身份、环境、失败和测量口径。它们用于复核历史行为，不能据此报告当前版本测试结果或生产状态。当前操作见 [使用指南](../guides/README.md)、[ASR](../asr/README.md) 和 [运维](../operations/README.md)；当前图表验收见 [architecture-validation.md](../architecture-validation.md)。

## 运行、迁移与契约

| 报告 | 原始记录 | 范围 |
| --- | --- | --- |
| [归档运行时 · 2026-10-10](archive-runtime-validation-2026-10-10.md) | [JSON](archive-runtime-validation-2026-10-10.json) | 全量回归、覆盖率、安装、快照往返及失败/跳过 |
| [契约治理 · 2026-10-11](contract-governance-validation-2026-10-11.md) | [JSON](contract-governance-validation-2026-10-11.json) | 固定指纹、历史样本、Schema 边界和独立审查 |
| Catalog Schema · 2026-10-10 | [JSON](catalog-schema-checks-2026-10-10.json) | 当时 16 份闭环导出及旧示例的结构校验 |
| [真实生产副本升级 · 2026-10-11](production-upgrade-validation-2026-10-11.md) | [JSON](production-upgrade-validation-2026-10-11.json) | 全量保真、来源标题、Reader、快照恢复与成本 |
| [在线产物存储 · 2026-10-11](artifact-online-validation-2026-10-11.md) | [JSON](artifact-online-validation-2026-10-11.json) | 多进程、崩溃、soak 与 Windows 验收范围 |
| [Bilibili 采集恢复](bili-crawl-recovery-validation.md) | 报告正文 | 翻页恢复、摘要兼容及实际回归 |
| [YouTube 字幕抓取](youtube-capture-validation.md) | 报告正文 | 抓取修复、样本及外部限制 |
| [非 perf 修复验收](non-perf-issues-validation.md) | 报告正文 | 修复范围、回归与未完成硬件验收 |

## ASR 设计、质量与性能

| 报告 | 原始记录 | 范围 |
| --- | --- | --- |
| [早期 ASR 设计评审 · 2026-10-08](asr-design-review-2026-10-08.md) | 报告正文 | 原基线缺口、质量取舍与当时建议 |
| [公开中文样本 · 2026-10-08](asr-public-samples-2026-10-08.md) | [FLEURS](asr-public-fleurs-results.json)；[60 秒](asr-public-controls-60.json)、[120 秒](asr-public-controls-120.json)、[180 秒](asr-public-controls-180.json) | CPU CER、人工拼接与静音对照 |
| [WSL ASR · 2026-10-08](asr-wsl-validation-2026-10-08.md) | [Smoke JSON](asr-wsl-smoke.json) | CPU 模型、自动回归、未知模型身份和 GPU 限制 |
| [4090 ASR · 2026-10-11](asr-gpu-validation-2026-10-11.md) | [JSON](asr-gpu-validation-2026-10-11.json) | 固定样本、GPU 时间线、策略回退与生产恢复 |
| [Perf 首批 WSL 验收](perf-evidence-validation.md) | [JSON](perf-evidence-validation.json) | 统计接口、离线测试、缺失硬件证明的边界 |
| [双声道混音优化](asr-stereo-mix-performance.md) | [实现验收 JSON](asr-stereo-mix-implementation-2026-10-11.json) | CPU 快速路径、数值兼容与不能外推的性能结论 |

上述 JSON 保留原字节和摘要。复现时使用独立输出目录；不要覆盖旧结果或把历史成功写成新的验收。
