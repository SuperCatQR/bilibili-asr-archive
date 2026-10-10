# 文档索引

[项目 README](../README.md) 提供安装和常用命令。以下文档以当前源码为依据，
解释工作流、数据所有权、产物契约和运行限制；架构图是可审阅的源码快照。

本分支新增来源、迁移、恢复检查和 GPU worker 的完整实施说明见
[Issues 实现与架构边界](issues-implementation.md)。下列原有架构图绑定其固定提交，新增能力以本分支实施说明、对应使用指南和测试为准。

本轮新增 [多平台归档架构图](issues-architecture.html)（[JSON](issues-architecture.json)）、
[七张新增时序图](architecture-sequences.md#本轮新增流程)、[图表凭据](issue-diagram-validation/README.md)
和 [WSL 验证记录](issues-validation.md)。新图绑定完成实现后的固定源码，旧图保留历史身份。

## 架构与数据

| 文档 | 内容 |
| --- | --- |
| [契约治理与兼容边界](contract-governance.md) | 单一登记、15 份离线 Schema、版本矩阵、冻结样本与变更门禁；[交互图](contract-governance.html)、[验证](contract-governance-validation.md) |
| [当前架构](architecture.md) | 固定提交的执行模型，以及本分支新增职责与契约入口 |
| [音频分层与手动迁出](artifact-storage.md) | 只读盘点、保真 catalog 升级、目标封包核验、条件释放和同 SHA 恢复；生产状态独立延续 |
| [SSH 存储与引用型备份](remote-reference-backups.md) | 已核验远程包、明确的外部依赖、离线/在线检查、保真状态恢复与显式 worker 交接 |
| [全景架构图](architecture.html) | 固定提交的可交互组件、关系与源码证据；[JSON](architecture.json) |
| [完整时序图](architecture-sequences.md) | 17 个完整流程，含 Mermaid 条件/循环、交互 HTML 与源码证据 |
| [源码与覆盖清单](architecture-sources.md) | 固定提交的 16 个顶层命令、35 条命令路径、122 个模块与旧 schema；[机器清单](architecture-coverage.json) |
| [图表验证记录](architecture-validation.md) | 19 张图的规格/文件摘要、四阶段检查与浏览器证据范围 |
| [架构图维护](architecture-maintenance.md) | 提交版本、证据与生成、浏览器检查的维护流程 |
| [元数据与存储](metadata-storage.md) | SQLite 表组、采集游标、身份、不可变版本、workflow 和读取投影 |
| [AI 校对与出版架构](ai-proofreading-architecture.md) | 固定提交的输入冻结、历史模板、完整版本、标签、审核、release 与三类导出 |
| [Issues 架构评估](issues-architecture-assessment.md) | 实施前对七项 issues 的代码依据、依赖、风险与验收要求 |
| [Issues 实现与架构边界](issues-implementation.md) | 本分支七项实现、层间依赖、新旧契约、操作入口与验证限制 |

## 工作流与产物

| 文档 | 内容 |
| --- | --- |
| [BVID 与分 P 选择](workflow-selection.md) | 批量 BVID、零基分 P、part ID、全集验证与幂等规划 |
| [任务取消](workflow-cancellation.md) | queued/running 取消、协作检查点、提交保护、依赖阻塞与终态 |
| [WebVTT 与 bundle](webvtt.md) | 五文件布局、cue 契约、完成标记及已有转录的重新发布 |
| [元数据搜索](metadata-search.md) | transcripts/metadata/all、字面匹配、排序、日期与 JSON 契约 |
| [出版与审核](publication.md) | 不可变完整版本、准确哈希审核、release、撤回、公开正文与校验参照及完整私有审阅包 |
| [保留旧正文的迁移导入](preserved-body-import.md) | 离线扩展安装、只读计划、字节保留、幂等回执、独立审核与来源导出协议 |
| [稿件 JSON 契约](contracts/README.md) | 新 schema、模板、catalog、manifest 与内容身份契约 |
| [AI 校对使用](ai-proofreading.md) | 配置、执行、失败恢复、重新渲染、数据与离线验证 |
| [产物根目录](artifact-root.md) | workflow 产物写根、读取回退顺序、音频与派生产物路径 |
| [归档快照与迁移](archive-snapshots.md) | 保存完整数据库与产物、离线校验、跨设备恢复与中断任务重排 |
| [显式契约升级](archive-upgrades.md) | 登记路径、绑定源与转换器的计划、隔离转换、逐表保真和完成核验 |
| [固定旧源迁移预检](archive-migration-preflight.md) | 停止/checkpoint 前置条件、显式源根、清点/历史身份校验与失败边界 |
| [多平台实施方案](multi-platform-architecture-plan.md) | 历史设计计划；本分支已实现部分见 Issues 实施说明 |
| [音频保留与预算](audio-retention-policy.md) | 当前预算和保留策略入口、下载暂存、复用及回收边界 |
| [Issues #247–#250](feature-plan-247-250.md) | 实施前评估、实现状态、风险、验收与交付顺序 |

## ASR 参数与评测

| 文档 | 内容 |
| --- | --- |
| [ASR 参数与诊断](asr-configuration.md) | 完整配置快照、独立模型版本、逐次运行证据与质量标记 |
| [ASR worker](asr-workers.md) | 角色、固定 slot、持久模型会话、drain、准备预算与运行限制 |
| [ASR 吞吐汇总](asr-performance.md) | 已有 evidence 的只读窗口报告、重试成本、缺失值与预取回退统计 |
| [ASR 设计评审](asr-design-review.md) | 官方资料、归档定位、证据支持的基线与空热词策略 |
| [公开样本测试](asr-public-samples.md) | FLEURS 参考 CER、分块与静音对照、完整 JSON 与复现命令 |
| [WSL 验证记录](asr-wsl-validation.md) | 自动化回归、真实 CPU 模型样本与 GPU 限制 |

## 环境与部署

| 文档 | 内容 |
| --- | --- |
| [ASR 部署与就绪](asr-deployment-readiness.md) | 只读检查、领取前模型准备、显式预热和持久缓存边界 |
| [海光 BW1000 验收](hygon-bw1000-validation.md) | 双模型精度、平台探测、目标环境门槛和实机验收流程 |
| [非 perf 修复验证](non-perf-issues-validation.md) | #305/#306/#300/#289 的交付范围、回归记录和硬件待办 |
| [Miniconda 部署](miniconda-deployment.md) | 应用依赖、生产启动检查与独立 ASR 环境 |
| [WSL ROCm GPU](wsl-rocm-gpu.md) | 已记录的 AMD WSL2 环境、版本组合、设备探测与故障排查 |
| [CI 覆盖率门禁](ci-coverage.md) | 产品源码范围、子进程采集、行与分支阈值及本地复现 |

环境记录和实施前评估保留各自的时间背景。当前行为以源码、相应功能指南和测试为准，
不能将旧命令、旧 schema 或实验结果直接当作当前接口。
