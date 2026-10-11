# 当前完整时序图

30 个流程与两张架构图统一绑定 `4f073318c944add37417416155845e55247f9bc1`；核对日期 2026-10-11（Asia/Hong_Kong）。从原 01–23 流程保留完整分支并更新源码引用，07 重写为当前 ASR 执行分派，19 加入 claim 前准备，08 对齐 v2/v3 与历史组，24–30 补齐最新存储、契约、批处理及编辑能力。

Markdown 的 Mermaid 保留 alt/opt/loop/par 和内部动作；HTML 按条件路径展开跨参与者消息，B 编号与完整条件卡片对应。互斥分支不同时执行，纵向位置不表示墙钟耗时。每条 HTML 消息的注释保存完整操作，短标签用于默认阅读。

| 编号 | 完整说明与 Mermaid | 交互图与规格 |
| --- | --- | --- |
| 01 | [CLI、显式数据库模式与 session 生命周期](sequences/01-cli-bootstrap.md) | [HTML](sequences/01-cli-bootstrap.html) · [JSON](sequences/01-cli-bootstrap.json) |
| 02 | [分页元数据采集、来源身份与原始标签](sequences/02-metadata-tags.md) | [HTML](sequences/02-metadata-tags.html) · [JSON](sequences/02-metadata-tags.json) |
| 03 | [全集选择验证、配置冻结与依赖规划](sequences/03-workflow-plan.md) | [HTML](sequences/03-workflow-plan.html) · [JSON](sequences/03-workflow-plan.json) |
| 04 | [任务认领、共享提交保护、心跳与取消重试](sequences/04-lease-cancel-retry.md) | [HTML](sequences/04-lease-cancel-retry.html) · [JSON](sequences/04-lease-cancel-retry.json) |
| 05 | [字幕来源端口、缺失证据与不可变转录](sequences/05-subtitle-ingest.md) | [HTML](sequences/05-subtitle-ingest.html) · [JSON](sequences/05-subtitle-ingest.json) |
| 06 | [音频来源、流式摘要与受保护登记](sequences/06-audio-download.md) | [HTML](sequences/06-audio-download.html) · [JSON](sequences/06-audio-download.json) |
| 07 | [ASR 执行分派、冻结输入与受保护结果](sequences/07-asr-runtime.md) | [HTML](sequences/07-asr-runtime.html) · [JSON](sequences/07-asr-runtime.json) |
| 08 | [择优转录、五文件发布与完成标记](sequences/08-transcript-bundle.md) | [HTML](sequences/08-transcript-bundle.html) · [JSON](sequences/08-transcript-bundle.json) |
| 09 | [冻结 AI 输入、共享提交保护与逐块续跑](sequences/09-ai-proofread.md) | [HTML](sequences/09-ai-proofread.html) · [JSON](sequences/09-ai-proofread.json) |
| 10 | [确定性 AI 双稿、锁外暂存与保护登记](sequences/10-document-render.md) | [HTML](sequences/10-document-render.html) · [JSON](sequences/10-document-render.json) |
| 11 | [完整版本、审核、发布与撤回](sequences/11-publication-lifecycle.md) | [HTML](sequences/11-publication-lifecycle.html) · [JSON](sequences/11-publication-lifecycle.json) |
| 12 | [公开、未发布预览与私有审阅三种导出](sequences/12-reader-private-export.md) | [HTML](sequences/12-reader-private-export.html) · [JSON](sequences/12-reader-private-export.json) |
| 13 | [偏好/发布身份、批量投影与完整性诊断](sequences/13-projection-verify.md) | [HTML](sequences/13-projection-verify.html) · [JSON](sequences/13-projection-verify.json) |
| 14 | [有界 FTS keyset、恢复与组合查询](sequences/14-search-index.md) | [HTML](sequences/14-search-index.html) · [JSON](sequences/14-search-index.json) |
| 15 | [统一维护访问、公开清单与归档 ZIP 恢复](sequences/15-archive-snapshot.md) | [HTML](sequences/15-archive-snapshot.html) · [JSON](sequences/15-archive-snapshot.json) |
| 16 | [运维查询、显式库工具与独立 worker 组合入口](sequences/16-library-and-operations.md) | [HTML](sequences/16-library-and-operations.html) · [JSON](sequences/16-library-and-operations.json) |
| 17 | [固定旧源契约、公开清单与完整历史预检](sequences/17-migration-preflight.md) | [HTML](sequences/17-migration-preflight.html) · [JSON](sequences/17-migration-preflight.json) |
| 18 | [旧归档显式迁移：保真、恢复审计与切换验证](sequences/18-universal-migration.md) | [HTML](sequences/18-universal-migration.html) · [JSON](sequences/18-universal-migration.json) |
| 19 | [持久 GPU 会话：租约、热模型与故障回收](sequences/19-persistent-asr.md) | [HTML](sequences/19-persistent-asr.html) · [JSON](sequences/19-persistent-asr.json) |
| 20 | [快照恢复：完整校验、暂存改写与安装审计](sequences/20-recovery-plan.md) | [HTML](sequences/20-recovery-plan.html) · [JSON](sequences/20-recovery-plan.json) |
| 21 | [YouTube 单视频：统一任务、租约与归档消费链](sequences/21-youtube-workflow.md) | [HTML](sequences/21-youtube-workflow.html) · [JSON](sequences/21-youtube-workflow.json) |
| 22 | [字幕候选、可信证据与独立 ASR](sequences/22-subtitle-candidates.md) | [HTML](sequences/22-subtitle-candidates.html) · [JSON](sequences/22-subtitle-candidates.json) |
| 23 | [增量发现、字段刷新与失败重放](sequences/23-metadata-refresh.md) | [HTML](sequences/23-metadata-refresh.html) · [JSON](sequences/23-metadata-refresh.json) |
| 24 | [产物副本、迁出、消费 pin 与精确恢复](sequences/24-artifact-storage.md) | [HTML](sequences/24-artifact-storage.html) · [JSON](sequences/24-artifact-storage.json) |
| 25 | [冻结契约路径、保真转换与新目标安装](sequences/25-contract-upgrade.md) | [HTML](sequences/25-contract-upgrade.html) · [JSON](sequences/25-contract-upgrade.json) |
| 26 | [单任务有界批处理、原始对齐与策略证据](sequences/26-asr-batching.md) | [HTML](sequences/26-asr-batching.html) · [JSON](sequences/26-asr-batching.json) |
| 27 | [SSH 精确包与非自包含引用备份的执行交接](sequences/27-reference-backup.md) | [HTML](sequences/27-reference-backup.html) · [JSON](sequences/27-reference-backup.json) |
| 28 | [保留旧正文、来源补充与重新审核](sequences/28-preserved-body.md) | [HTML](sequences/28-preserved-body.html) · [JSON](sequences/28-preserved-body.json) |
| 29 | [编辑系列 CAS、导出绑定与静态消费](sequences/29-publication-series.md) | [HTML](sequences/29-publication-series.html) · [JSON](sequences/29-publication-series.json) |
| 30 | [冻结失败诊断、显式修复与输入重用](sequences/30-editorial-repair.md) | [HTML](sequences/30-editorial-repair.html) · [JSON](sequences/30-editorial-repair.json) |

## 本轮新增流程

24：对象、完整组、迁出与消费 pin/精确恢复；25：登记契约路径与新目录保真升级；26：同任务有界 ASR/alignment 批处理；27：SSH 与非自包含引用备份；28：保留旧正文与独立来源补充；29：编辑系列和导出 CAS；30：失败校对的显式修复与冻结输入重用。

固定源码、命令、全部模块和数据库契约见[源码清单](architecture-sources.md)，产物摘要与自动浏览器范围见[验证记录](architecture-validation.md)。此前 issue-diagram-validation 与 issues-validation 记录保留历史提交与验收范围，不作为本轮最新产物凭据。
