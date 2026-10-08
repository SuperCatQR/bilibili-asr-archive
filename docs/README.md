# 文档索引

[项目 README](../README.md) 提供安装和常用命令。以下文档以当前源码为依据，
解释工作流、数据所有权、产物契约和运行限制；架构图是可审阅的源码快照。

## 架构与数据

| 文档 | 内容 |
| --- | --- |
| [当前架构](architecture.md) | 执行模型、组件职责、数据流、状态转换、提交边界与恢复限制 |
| [历史全景架构图](architecture.html) | 5c3cc606 的组件关系快照；旧阅读入口不代表当前接口，当前出版关系见专题图 |
| [架构图维护](architecture-maintenance.md) | 提交版本、证据与生成、浏览器检查的维护流程 |
| [元数据与存储](metadata-storage.md) | SQLite 表组、采集游标、身份、不可变版本、workflow 和读取投影 |
| [AI 校对与出版架构](ai-proofreading-architecture.md) | fc66c1d 的验证专题图及当前输入冻结、完整版本、准确审核、release 与独立导出说明 |

## 工作流与产物

| 文档 | 内容 |
| --- | --- |
| [BVID 与分 P 选择](workflow-selection.md) | 批量 BVID、零基分 P、part ID、全集验证与幂等规划 |
| [任务取消](workflow-cancellation.md) | queued/running 取消、协作检查点、提交保护、依赖阻塞与终态 |
| [WebVTT 与 bundle](webvtt.md) | 五文件布局、cue 契约、完成标记及已有转录的重新发布 |
| [元数据搜索](metadata-search.md) | transcripts/metadata/all、字面匹配、排序、日期与 JSON 契约 |
| [出版与审核](publication.md) | 不可变完整版本、准确哈希审核、release、撤回及独立公开和私有导出 |
| [稿件 JSON 契约](contracts/README.md) | 新 schema、模板、catalog、manifest 与内容身份契约 |
| [AI 校对使用](ai-proofreading.md) | 配置、执行、失败恢复、重新渲染、数据与离线验证 |
| [产物根目录](artifact-root.md) | workflow 产物写根、读取回退顺序、音频与派生产物路径 |
| [归档快照与迁移](archive-snapshots.md) | 保存完整数据库与产物、离线校验、跨设备恢复与中断任务重排 |
| [音频保留与预算](audio-retention-policy.md) | 当前预算和保留策略入口、下载暂存、复用及回收边界 |
| [Issues #247–#250](feature-plan-247-250.md) | 实施前评估、实现状态、风险、验收与交付顺序 |

## ASR 参数与评测

| 文档 | 内容 |
| --- | --- |
| [ASR 参数与诊断](asr-configuration.md) | 完整配置快照、独立模型版本、逐次运行证据与质量标记 |
| [ASR 设计评审](asr-design-review.md) | 官方资料、归档定位、证据支持的基线与空热词策略 |
| [公开样本测试](asr-public-samples.md) | FLEURS 参考 CER、分块与静音对照、完整 JSON 与复现命令 |
| [WSL 验证记录](asr-wsl-validation.md) | 自动化回归、真实 CPU 模型样本与 GPU 限制 |

## 环境与部署

| 文档 | 内容 |
| --- | --- |
| [Miniconda 部署](miniconda-deployment.md) | 应用依赖、生产启动检查与独立 ASR 环境 |
| [WSL ROCm GPU](wsl-rocm-gpu.md) | 已记录的 AMD WSL2 环境、版本组合、设备探测与故障排查 |
| [CI 覆盖率门禁](ci-coverage.md) | 产品源码范围、子进程采集、行与分支阈值及本地复现 |

环境记录和实施前评估保留各自的时间背景。当前行为以源码、相应功能指南和测试为准，
不能将旧命令、旧 schema 或实验结果直接当作当前接口。
