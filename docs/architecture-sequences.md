# 当前完整时序图

原主分支32个流程与三张架构图的历史验收绑定 `3ed823c961736378d8408bba5f0535b03e0046e0`；核对日期 2026-10-12（Asia/Hong_Kong）。本轮源码位于独立修复分支，未表示远端 main 或生产已更新。09 加入有界恢复，32 加入独立周期失败维护，12/31 记录 Reader 配套提交。既有 #348 流程：08 加入锁定原转录的 v3 回填，12 展示新的 origin profile，13 展示批量来源字段，28 展示简介证据与待审子版；31 串起旧 bundle 回填和旧文章补充。已有流程的条件和源码证据保留并核对。

Markdown 的 Mermaid 保留 alt/opt/loop/par 和内部动作；HTML 按条件路径展开跨参与者消息，B 编号与完整条件卡片对应。互斥分支不同时执行，纵向位置不表示墙钟耗时。每条 HTML 消息的注释保存完整操作，短标签用于默认阅读。

| 编号 | 完整说明与 Mermaid | 交互图与规格 |
| --- | --- | --- |
| 01 | [CLI、显式数据库模式与 session 生命周期](01-cli-bootstrap.md) | [HTML](01-cli-bootstrap.html) · [JSON](01-cli-bootstrap.json) |
| 02 | [分页元数据采集、来源身份与原始标签](02-metadata-tags.md) | [HTML](02-metadata-tags.html) · [JSON](02-metadata-tags.json) |
| 03 | [全集选择验证、配置冻结与依赖规划](03-workflow-plan.md) | [HTML](03-workflow-plan.html) · [JSON](03-workflow-plan.json) |
| 04 | [任务认领、共享提交保护、心跳与取消重试](04-lease-cancel-retry.md) | [HTML](04-lease-cancel-retry.html) · [JSON](04-lease-cancel-retry.json) |
| 05 | [字幕来源端口、缺失证据与不可变转录](05-subtitle-ingest.md) | [HTML](05-subtitle-ingest.html) · [JSON](05-subtitle-ingest.json) |
| 06 | [音频来源、流式摘要与受保护登记](06-audio-download.md) | [HTML](06-audio-download.html) · [JSON](06-audio-download.json) |
| 07 | [ASR 执行分派、冻结输入与受保护结果](07-asr-runtime.md) | [HTML](07-asr-runtime.html) · [JSON](07-asr-runtime.json) |
| 08 | [择优发布、锁定原转录回填与 bundle v3](08-transcript-bundle.md) | [HTML](08-transcript-bundle.html) · [JSON](08-transcript-bundle.json) |
| 09 | [冻结 AI 输入、共享提交保护与逐块续跑](09-ai-proofread.md) | [HTML](09-ai-proofread.html) · [JSON](09-ai-proofread.json) |
| 10 | [确定性 AI 双稿、锁外暂存与保护登记](10-document-render.md) | [HTML](10-document-render.html) · [JSON](10-document-render.json) |
| 11 | [完整版本、审核、发布与撤回](11-publication-lifecycle.md) | [HTML](11-publication-lifecycle.html) · [JSON](11-publication-lifecycle.json) |
| 12 | [公开、未发布预览与私有审阅三种导出](12-reader-private-export.md) | [HTML](12-reader-private-export.html) · [JSON](12-reader-private-export.json) |
| 13 | [偏好/发布身份、批量投影与完整性诊断](13-projection-verify.md) | [HTML](13-projection-verify.html) · [JSON](13-projection-verify.json) |
| 14 | [有界 FTS keyset、恢复与组合查询](14-search-index.md) | [HTML](14-search-index.html) · [JSON](14-search-index.json) |
| 15 | [统一维护访问、公开清单与归档 ZIP 恢复](15-archive-snapshot.md) | [HTML](15-archive-snapshot.html) · [JSON](15-archive-snapshot.json) |
| 16 | [运维查询、显式库工具与独立 worker 组合入口](16-library-and-operations.md) | [HTML](16-library-and-operations.html) · [JSON](16-library-and-operations.json) |
| 17 | [固定旧源契约、公开清单与完整历史预检](17-migration-preflight.md) | [HTML](17-migration-preflight.html) · [JSON](17-migration-preflight.json) |
| 18 | [旧归档显式迁移：保真、恢复审计与切换验证](18-universal-migration.md) | [HTML](18-universal-migration.html) · [JSON](18-universal-migration.json) |
| 19 | [持久 GPU 会话：租约、热模型与故障回收](19-persistent-asr.md) | [HTML](19-persistent-asr.html) · [JSON](19-persistent-asr.json) |
| 20 | [快照恢复：完整校验、暂存改写与安装审计](20-recovery-plan.md) | [HTML](20-recovery-plan.html) · [JSON](20-recovery-plan.json) |
| 21 | [YouTube 单视频：统一任务、租约与归档消费链](21-youtube-workflow.md) | [HTML](21-youtube-workflow.html) · [JSON](21-youtube-workflow.json) |
| 22 | [字幕候选、可信证据与独立 ASR](22-subtitle-candidates.md) | [HTML](22-subtitle-candidates.html) · [JSON](22-subtitle-candidates.json) |
| 23 | [增量发现、字段刷新与失败重放](23-metadata-refresh.md) | [HTML](23-metadata-refresh.html) · [JSON](23-metadata-refresh.json) |
| 24 | [产物副本、迁出、消费 pin 与精确恢复](24-artifact-storage.md) | [HTML](24-artifact-storage.html) · [JSON](24-artifact-storage.json) |
| 25 | [冻结契约路径、保真转换与新目标安装](25-contract-upgrade.md) | [HTML](25-contract-upgrade.html) · [JSON](25-contract-upgrade.json) |
| 26 | [单任务有界批处理、原始对齐与策略证据](26-asr-batching.md) | [HTML](26-asr-batching.html) · [JSON](26-asr-batching.json) |
| 27 | [SSH 精确包与非自包含引用备份的执行交接](27-reference-backup.md) | [HTML](27-reference-backup.html) · [JSON](27-reference-backup.json) |
| 28 | [保留旧正文、来源补充与重新审核](28-preserved-body.md) | [HTML](28-preserved-body.html) · [JSON](28-preserved-body.json) |
| 29 | [编辑系列 CAS、导出绑定与静态消费](29-publication-series.md) | [HTML](29-publication-series.html) · [JSON](29-publication-series.json) |
| 30 | [冻结失败诊断、显式修复与输入重用](30-editorial-repair.md) | [HTML](30-editorial-repair.html) · [JSON](30-editorial-repair.json) |
| 31 | [来源元数据、旧包回填与文章简介补充](31-source-metadata-migration.md) | [HTML](31-source-metadata-migration.html) · [JSON](31-source-metadata-migration.json) |

| 32 | [失败重试维护：周期接管、预算与健康](32-retry-maintenance.md) | [HTML](32-retry-maintenance.html) · [JSON](32-retry-maintenance.json) |
| 33 | [失败状态、政策决策与受保护重排](33-workflow-failure-recovery.md) | [HTML](33-workflow-failure-recovery.html) · [JSON](33-workflow-failure-recovery.json) |

## 本轮新增流程

33 展示一致只读快照、jobs/attempts/窗口口径、安全诊断、纯错误分类、显式库外控制证据与受保护重排。04 更新准入，09 在持久块恢复基础上补充稳定诊断，30 展示安全状态和修复指引。旧失败、attempt、冻结输入、原响应与 holds 保留。合并后的图表尚需绑定完整源码提交并重新执行四道 gate，逐项身份以验证记录为准。

31 区分两个显式操作：已安装 catalog 的旧 bundle 在 publication 围栏内保留原转录并冻结当前来源；已保留旧正文的文章根据本地逐字段证据新建待审子版，审核后用 universal-origin-v2 导出。两条链不触发 ASR/AI，也不自动发布或升级外部阅读站。

固定源码、命令、全部模块和数据库契约见[源码清单](architecture-sources.md)，产物摘要与自动浏览器范围见[验证记录](architecture-validation.md)。历史行为验收见 [evidence/README.md](evidence/README.md)，仅代表各自原提交和运行范围。
