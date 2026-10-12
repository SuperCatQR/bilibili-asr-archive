# 部署与运维

[返回文档入口](../README.md)。按目标选择手册；升级、恢复和存储操作的准入、计划与交接要求在各自文档中说明。

| 任务 | 文档 | 范围 |
| --- | --- | --- |
| 安装 | [Miniconda 部署](miniconda-deployment.md) | 应用与独立 ASR 环境、启动前检查 |
| 就绪 | [模型就绪与预热](asr-deployment-readiness.md) | 只读探测、领取前准备、显式预热和缓存 |
| 质量 | [运行健康与发布恢复](quality-and-release.md) | 只读状态、实机验收、隔离恢复与交接 |
| AMD WSL | [ROCm GPU 手册](../wsl-rocm-gpu.md) | 已记录环境组合、设备探测与故障排查 |
| 海光 | [BW1000 验收步骤](hygon-bw1000-validation.md) | 目标硬件上的验收流程；仍需实机证据 |
| 根目录 | [归档与产物根](artifact-root.md) | 配置优先级、写根与读取回退 |
| 空间 | [音频保留策略](audio-retention-policy.md) | 预算、复用、回收和消费者边界 |
| 分层存储 | [产物迁出与恢复](artifact-storage.md) | catalog、目标包、条件释放和精确恢复 |
| 远程 | [SSH 存储与引用备份](remote-reference-backups.md) | host key、读回核验、外部依赖及执行权交接 |
| 备份 | [完整快照](archive-snapshots.md) | 一致性、校验、恢复规划和运行时绑定 |
| 旧库 | [迁移预检](archive-migration-preflight.md) | 固定源契约、历史文件与失败边界 |
| 升级 | [显式契约升级](archive-upgrades.md) | 注册路径、隔离目标、保真和完成检查 |
| 内容升级 | [历史证据与内容政策](content-upgrade-policies.md) | 数据库与内容升级边界、旧时间证据生成 VTT |
| 成本 | [升级结果复用](upgrade-result-reuse.md) | 计划证据、已成功结果和昂贵补算边界 |
| 失败恢复 | [工作流失败与重试](workflow-failures.md) | jobs/attempts 口径、外部 holds、错误政策、安全诊断和显式修复 |
| 重试接管 | [有界重试维护](retry-maintenance.md) | 显式范围、既有 holds/ledger、最新失败尝试与独立健康 |

做过的验收与局限见 [历史证据](../evidence/README.md)；日常采集和出版见 [使用指南](../guides/README.md)。
