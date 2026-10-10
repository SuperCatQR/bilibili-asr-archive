# 架构修复与文档验证记录

契约治理的新实现与专题图使用独立 [验证记录](contract-governance-validation.md)和[机器记录](contract-governance-validation.json)，绑定源码 `6a8646a36f680705479a7669350fd8793551cc74`。下列 19 张图的原始结果和哈希保留其历史身份。


核对日期：2026-10-09（Asia/Hong_Kong）。固定源码：`5d7a57e201564a10dec7a360b2ef8f7874dc51a7`，独立工作树起点为 main `6544eb85ea3e95e5b9571930fefaf35bde6b7dc1`。本轮同时完成实现修复、行为回归和文档更新。逐项修复见 [边界修复与验收](architecture-refactoring.md)，全部流程见 [17 份时序索引](architecture-sequences.md)。

## 完整 WSL 验证

最终套件在 WSL Ubuntu-24.04 的原生 Linux 文件系统中运行，源码快照逐文件核对工作树字节，独立 Python 3.12 环境真实安装全部开发依赖。完整 pytest：**2112 passed、11 skipped、0 failed、0 errors**，耗时 405.12 秒。受门禁管理的产品行覆盖率 **81.87%**，分支覆盖率 **71.06%**，分别超过 75%/63% 的项目门槛。

Ruff E9、源码/测试/脚本 compileall、sdist 与 wheel 构建通过。独立安装环境从项目外实际运行 CLI，确认四份 SQL 和冻结迁移源 JSON 已打包；缺库 READ/status/workflow status 有界失败且无目录或 DB 创建。显式 BOOTSTRAP 后，本轮已安装 CLI 的只读回归在静止归档下保持 DB/sidecar 字节不变；并发 writer 或 SQLite WAL sidecar 的外部变化不在这个字节承诺内。开发依赖审计通过，未发现已知漏洞。

交叉审查验证了事务内租约到期、等待写锁跨越期限、续约旧期限到期、取消/owner/attempt 改变、批次后段失败、稿件暂存与不可变重试、音频路径、历史 hash、真实 A→B→A 发布与消费者、索引固定上界及 legacy 恢复。受控条件变异和恢复旧控制实现均触发对应失败，原字节恢复后继续验收。历史 collect_ignore 对已移除产品路径的排除保持原状；跳过项不计为通过。

前轮完整运行曾暴露安装测试仍要求查询初始化的问题，已按 READ 契约修正。借用旧环境依赖目录的 `.pth` 没有执行 coverage 的子进程启动文件，导致嵌套采集测试零覆盖；四组对照定位后，最终环境直接安装依赖，同版本 coverage/pytest 下普通及插桩运行均通过，无需修改产品 coverage 配置。

## 覆盖与源码身份

[机器记录](architecture-validation.json) 保存实际 gate、文件 SHA-256 和浏览器证据。[覆盖清单](architecture-coverage.json) 对齐固定提交：16 个顶层命令、35 条实际命令路径、122 个 Python 产品模块、4 份 SQL schema、38 张表、8 个视图，以及 2 个运行时搜索对象。TEMP legacy key 表是构建连接的恢复辅助，不是新增归档实体。

逐项核对 parser/registry、提交文件树、内存 SQLite 对象名称与列，检查 **269 段固定源码范围**（其中 257 段精确 AST 符号）和 **698 个 Markdown 本地链接**。17 份 Mermaid 的参与者与 alt/opt/loop 平衡通过，全部图使用同一固定 SHA 和 local-only 源码链接。git diff --check 通过。原始来源 codec、profile/dedupe、稿件内容 hash 与已有持久 schema 保持兼容。

## 图表与浏览器

Archify 3.0.1 重新生成 2 张架构图与 17 张时序图。19 张均通过 showcase validate、deliver、strict provenance check 和真实 Chrome browser-check，specification/artifact 摘要与实际文件相符。每张检测 1440×900、1600×1000、1920×1080、2048×1320 的浅色视口；端点尺寸另覆盖深色，均无横向溢出。长图按 Reader 契约允许纵向滚动。

全景只改变四个节点位置，保留全部节点、关系、语义和源码。实际主链 CLI→workflow→handlers 的阻挡已移除，交叉数从 17 降为 14；超过建议转折数的路线从 8 增为 10，超过建议长度的 1 条路线消失。保留这个主链更清楚的候选，明确共享状态和消费路径仍有交叉；AI 专题保留 6 条绕路建议。零自动 diagnostics 不表示零交叉。

全景、AI 专题与重新编排的计划时序额外取得端点尺寸/主题截图，实际查看记录限于对应桌面首屏。计划时序的两个分支标题原有重叠，已调整分支间距并重新完成全部四项 gate。长页下部没有逐屏穷尽追踪，因此机器记录标为 partial，不声称完整目视验收；其余图仅有确定性的自动浏览器检查。HTML 内部动作和展开分支与同页 Mermaid 共同保持完整条件路径。

## 复现与限制

最终原始回执、截图、修复候选、源码比对和内容检查脚本保存在忽略目录 `.archify/`；可移植记录不包含本机用户名或绝对 evidence 路径。维护步骤见 [指南](architecture-maintenance.md)。本次未调用真实 Bilibili 网络、执行真实 GPU 推理、发起付费 AI 请求、部署外部阅读站或进行逐句语义审核。

SQLite 不能原子回滚文件安装；失败后的不可变稿件可验证重试，bundle marker 失败清理由保护事务负责。取消为协作式，提交 fence 阻止迟到结果。ContentRef/端口已经接入 Bilibili 真实路径，其他平台落库与迁移转换仍需独立实施；投影内部查询有界，公共完整映射仍按输出规模占用内存。
