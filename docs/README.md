# 文档索引

[项目 README](../README.md) 提供安装和常用命令。以下文档以当前源码为依据，
解释工作流、数据所有权、产物契约和运行限制；架构图是可审阅的源码快照。

## 架构与数据

| 文档 | 内容 |
| --- | --- |
| [当前架构](architecture.md) | 执行模型、组件职责、数据流、状态转换、提交边界与恢复限制 |
| [交互式架构图](architecture.html) | 可探索的组件关系图；[JSON 规格](architecture.json)记录源码证据 |
| [架构图维护](architecture-maintenance.md) | 提交版本、证据与生成、浏览器检查的维护流程 |
| [元数据与存储](metadata-storage.md) | SQLite 表组、采集游标、身份、不可变版本、workflow 和读取投影 |
| [AI 校对架构](ai-proofreading-architecture.md) | 输入冻结、来源追溯、模型调用、修订与阅读文档的详细架构 |

## 工作流与产物

| 文档 | 内容 |
| --- | --- |
| [BVID 与分 P 选择](workflow-selection.md) | 批量 BVID、零基分 P、part ID、全集验证与幂等规划 |
| [任务取消](workflow-cancellation.md) | queued/running 取消、协作检查点、提交保护、依赖阻塞与终态 |
| [WebVTT 与 bundle](webvtt.md) | 五文件布局、cue 契约、完成标记及已有转录的重新发布 |
| [元数据搜索](metadata-search.md) | transcripts/metadata/all、字面匹配、排序、日期与 JSON 契约 |
| [AI 校对使用](ai-proofreading.md) | 配置、执行、失败恢复、重新渲染、数据与离线验证 |
| [产物根目录](artifact-root.md) | workflow 产物写根、读取回退顺序、音频与派生产物路径 |
| [音频保留与预算](audio-retention-policy.md) | 当前预算和保留策略入口、下载暂存、复用及回收边界 |
| [Issues #247–#250](feature-plan-247-250.md) | 实施前评估、实现状态、风险、验收与交付顺序 |

## 环境

| 文档 | 内容 |
| --- | --- |
| [Miniconda 部署](miniconda-deployment.md) | 应用依赖、生产启动检查与独立 ASR 环境 |
| [WSL ROCm GPU](wsl-rocm-gpu.md) | 已记录的 AMD WSL2 环境、版本组合、设备探测与故障排查 |

环境记录和实施前评估保留各自的时间背景。当前行为以源码、相应功能指南和测试为准，
不能将旧命令、旧 schema 或实验结果直接当作当前接口。
