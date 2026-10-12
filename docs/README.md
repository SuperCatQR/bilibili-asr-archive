# 文档入口

[项目 README](../README.md) 提供安装与常用命令。按下面的任务选择入口；每个分类页列出该目录的完整文档。

| 想做什么 | 从这里开始 |
| --- | --- |
| 第一次安装或部署 | [Miniconda 部署](operations/miniconda-deployment.md)，随后检查 [ASR 就绪条件](operations/asr-deployment-readiness.md) |
| 采集、搜索、校对或发布 | [使用指南](guides/README.md) |
| 调整识别配置、worker 或性能诊断 | [ASR 配置与执行](asr/README.md) |
| 备份、迁移、升级、恢复或管理存储 | [部署与运维](operations/README.md) |
| 了解系统边界和调用关系 | [当前架构](architecture.md)、[35 张交互图与流程入口](architecture-sequences.md) |
| 修改实现、契约或维护文档 | [开发与维护](development/README.md)、[契约镜像](contracts/README.md) |
| 查阅做过哪些实测及其限制 | [实测与实验记录](evidence/README.md) |

## 架构与数据参考

图表继续直接放在 `docs/`，同名 Markdown 说明行为，JSON 是可编辑规格，HTML 是生成的独立查看器。图表绑定固定源码提交，身份与验收范围见 [图表验证](architecture-validation.md)。

| 参考 | 说明 |
| --- | --- |
| [系统架构](architecture.md) · [HTML](architecture.html) · [JSON](architecture.json) | 执行模型、数据所有权和持久边界 |
| [AI 与出版架构](ai-proofreading-architecture.md) · [HTML](ai-proofreading-architecture.html) · [JSON](ai-proofreading-architecture.json) | 冻结输入、修订、审核、release 与导出 |
| [契约治理](contract-governance.md) · [HTML](contract-governance.html) · [JSON](contract-governance.json) | 版本矩阵、消费者、固定指纹与兼容边界 |
| [32 个完整时序](architecture-sequences.md) | CLI、来源、任务、ASR、出版、存储、迁移与恢复 |
| [SQLite 数据参考](metadata-storage.md) | 表、视图、身份、观察状态与读取投影 |
| [源码清单](architecture-sources.md) · [覆盖清单](architecture-coverage.json) | 固定提交的源码证据与覆盖范围 |
| [图表维护](architecture-maintenance.md) · [验收记录](architecture-validation.md) · [机器记录](architecture-validation.json) | 生成、源码定位、产物哈希与浏览器检查 |

## 目录约定

- `guides/`：面向日常使用的工作流、来源、内容与出版指南。
- `asr/`：当前识别配置、执行策略、worker 与性能诊断接口。
- `operations/`：部署、存储、迁移、升级、备份与恢复手册。
- `development/`：CI、发布说明与文档维护约定。
- `contracts/`：程序发布的契约镜像与示例，由契约工具校验原字节。
- `evidence/`：固定日期、源码与环境的真实测量及原始结果。

[WSL ROCm GPU 手册](wsl-rocm-gpu.md) 保留在根目录，因为环境探测工具直接输出这个路径。历史记录保留失败、跳过、未完成验收和原始身份；当前操作以功能指南与实现为准。
