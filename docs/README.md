# 文档入口

当前产品由 SQLite 工作流驱动：保存来源事实、不可变转录、处理尝试与发布记录，再生成归档包和阅读投影。安装和命令概览见 [项目 README](../README.md)，模块与状态边界从 [当前架构](architecture.md) 开始阅读。

## 当前架构、ASR 与阅读流程

| 文档 | 内容 |
|---|---|
| [当前架构](architecture.md) / [交互式总图](architecture.html) | 系统定位、模块边界、任务生命周期、状态所有权与运行限制 |
| [ASR 参数与诊断](asr-configuration.md) | 有效配置快照、默认参数、CLI、每次运行证据、风险标记与存储兼容 |
| [ASR 设计评审](asr-design-review.md) | 官方资料、面向归档与阅读的设计取舍、调优实验和后续实施建议 |
| [WSL 验证记录](asr-wsl-validation.md) | 测试环境、自动化回归、真实 CPU 模型样本与 GPU 验证限制 |
| [AI 校对使用说明](ai-proofreading.md) | 工作流与 DeepSeek 校对的参数、数据库及输出契约 |
| [AI 校对架构](ai-proofreading-architecture.md) | 固定输入、来源覆盖、修订、确定性渲染、静态阅读站与人审 |
| [架构图维护](architecture-maintenance.md) | 固定源码提交、编辑 JSON、生成 HTML 与浏览器校验流程 |

架构图中完整系统关系较多，可缩放、平移并选择路径查看节点与源码证据；阅读模块职责和规则时，文字版架构及专项文档提供更直接的入口。

## 历史资料与适用范围

以下页面保留旧实现或机器环境的背景。其首页已标明当前边界；执行命令以当前 `bili-asr --help`、项目 README 和上表文档为准。

| 文档 | 当前适用范围 |
|---|---|
| [元数据存储](metadata-storage.md) | 早期元数据与字幕 schema 背景；旧 `harvest-subs` / manifest 描述不能作为当前工作流契约 |
| [WSL ROCm 配方](wsl-rocm-gpu.md) | 2026-09-12 特定 AMD 环境的历史记录；不表示本次 WSL 环境 GPU 可用 |
| [产物根目录](artifact-root.md) | 旧写入流水线说明；当前 `--artifact-root` 属于读取类命令，workflow 不提供独立写入根入口 |
| [音频保留策略](audio-retention-policy.md) | 旧归档命令的保留与回收策略背景；当前 CLI 没有其中的生命周期开关 |
