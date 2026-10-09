# 完整时序图

基线：main `9b289570494b5e8f7cc564a7eaa5b2eb2c28c3ad`；核对日期：2026-10-09（Asia/Hong_Kong）。

以下 16 个流程覆盖当前 CLI、生产链路、持久提交、读取消费、恢复及保留库能力。每页包含可直接渲染的 Mermaid 时序图、条件分支、交互 HTML、JSON 规格和源码证据。

HTML 按发生顺序展开条件分支，每段 B 编号对应卡片中的完整嵌套条件路径，区域标题注明 alt/opt/loop；互斥分支只在条件成立时执行。同参与者内部动作保留在补充卡片。Markdown 中的 Mermaid 保留完整自调用与嵌套分支结构。时间轴纵向排列表示顺序，不表示墙钟耗时。

| 序号 | 时序文档 | 交互图 |
| --- | --- | --- |
| 01 | [CLI 启动、路径策略与数据库契约](sequences/01-cli-bootstrap.md) | [HTML](sequences/01-cli-bootstrap.html) · [JSON](sequences/01-cli-bootstrap.json) |
| 02 | [分页元数据采集、失败恢复与原始标签](sequences/02-metadata-tags.md) | [HTML](sequences/02-metadata-tags.html) · [JSON](sequences/02-metadata-tags.json) |
| 03 | [全集选择验证、配置冻结与依赖规划](sequences/03-workflow-plan.md) | [HTML](sequences/03-workflow-plan.html) · [JSON](sequences/03-workflow-plan.json) |
| 04 | [任务认领、心跳、取消、租约回收与重试](sequences/04-lease-cancel-retry.md) | [HTML](sequences/04-lease-cancel-retry.html) · [JSON](sequences/04-lease-cancel-retry.json) |
| 05 | [字幕轨道选择、缺失证据与不可变转录](sequences/05-subtitle-ingest.md) | [HTML](sequences/05-subtitle-ingest.html) · [JSON](sequences/05-subtitle-ingest.json) |
| 06 | [音频复用、隔离下载与受保护登记](sequences/06-audio-download.md) | [HTML](sequences/06-audio-download.html) · [JSON](sequences/06-audio-download.json) |
| 07 | [ASR 配置重建、GPU 超时、分块与逐次证据](sequences/07-asr-runtime.md) | [HTML](sequences/07-asr-runtime.html) · [JSON](sequences/07-asr-runtime.json) |
| 08 | [择优转录、五文件发布与完成标记](sequences/08-transcript-bundle.md) | [HTML](sequences/08-transcript-bundle.html) · [JSON](sequences/08-transcript-bundle.json) |
| 09 | [AI 输入冻结、块恢复、调用审计与完整修订](sequences/09-ai-proofread.md) | [HTML](sequences/09-ai-proofread.html) · [JSON](sequences/09-ai-proofread.json) |
| 10 | [确定性 AI 双稿渲染与历史模板验证](sequences/10-document-render.md) | [HTML](sequences/10-document-render.html) · [JSON](sequences/10-document-render.json) |
| 11 | [完整 edition、准确审核、release 替换与撤回](sequences/11-publication-lifecycle.md) | [HTML](sequences/11-publication-lifecycle.html) · [JSON](sequences/11-publication-lifecycle.json) |
| 12 | [公开、未发布预览与私有审阅三种导出](sequences/12-reader-private-export.md) | [HTML](sequences/12-reader-private-export.html) · [JSON](sequences/12-reader-private-export.json) |
| 13 | [读取投影、覆盖、完整性、普通导出与去重](sequences/13-projection-verify.md) | [HTML](sequences/13-projection-verify.html) · [JSON](sequences/13-projection-verify.json) |
| 14 | [FTS 增量索引、元数据检索与组合结果](sequences/14-search-index.md) | [HTML](sequences/14-search-index.html) · [JSON](sequences/14-search-index.json) |
| 15 | [归档 ZIP 保存、离线校验与跨设备恢复](sequences/15-archive-snapshot.md) | [HTML](sequences/15-archive-snapshot.html) · [JSON](sequences/15-archive-snapshot.json) |
| 16 | [部署启动与保留库工具的显式调用边界](sequences/16-library-and-operations.md) | [HTML](sequences/16-library-and-operations.html) · [JSON](sequences/16-library-and-operations.json) |

## 覆盖索引

| 业务面 | 流程 |
| --- | --- |
| 启动、路径、安全边界、schema | 01 |
| 用户分页、视频详情/分 P、标签与失败恢复 | 02 |
| 批量选择、profile、任务去重与依赖、重新发布 | 03 |
| claim、heartbeat、cancel、lease reclaim、retry、terminal | 04 |
| 字幕、凭据证明、获取记录、不可变版本 | 05 |
| 音频复用、下载、探测、哈希、对象登记 | 06 |
| Qwen3、解码、分块、对齐、两遍、GPU watchdog、质量证据 | 07 |
| 原始 bundle、五文件 marker、事务保护与失败清理 | 08 |
| 显式和自动校对、冻结输入、块重用、调用审计 | 09 |
| AI 双稿、固定模板、文件登记、历史版本验证 | 10 |
| edition、tags sync、review、release、替换/撤回 | 11 |
| 公开/预览/私有导出、输出恢复与消费边界 | 12 |
| status/runs/coverage/verify/export/dedup 与派生投影 | 01、13 |
| FTS build/repair 与 metadata/transcripts/all search | 14 |
| ZIP save/check/restore 与中断恢复 | 15 |
| production、check-asr-env、保留工具能力 | 16 |

源码模块、SQL 表/视图和全部命令登记的清单见 [源码与覆盖清单](architecture-sources.md)。验收记录见 [图表验证记录](architecture-validation.md)。
