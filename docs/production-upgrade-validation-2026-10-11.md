# 真实归档副本升级与恢复验收（2026-10-11）

本记录对应 #313、#327–#331。使用生产归档的一致隔离副本完成正式升级、来源证据补充、
当前导出、独立阅读站消费和完整快照往返。原生产目录没有作为升级目标，未部署候选程序、
切换生产根、启动新 worker 或解除 retry hold。下列数量都是本次冻结副本的事实。

## 一致源与正式升级

源程序为 `bab5998`，原归档位于 `/root/autodl-tmp/archive`。
先持有现有运维 maintenance lock，保存六个生产父进程及其子进程的 PID 启动身份，
检查 running job 和未结束 attempt 均为零，暂停这些已知写入进程，再次检查无活动执行、
WAL 没有未提交数据。独立看门狗限制暂停时间，finally 恢复原进程。
这不是在线 DB backup 加并发文件复制。

2026-10-11 01:58:49（Asia/Hong_Kong）形成的捕获记录：

| 项目 | 实际结果 |
| --- | --- |
| 文件 | 18,236 个，共 32,807,760,386 字节 |
| DB | 1,588,740,096 字节；SHA256 `3a589f285607e4697345136eab52f698ebb9598969247f9cf0ec0788ee4318f9` |
| 复制 | 44.425 秒；逐文件流式摘要并复查源，源 DB 不变 |
| 运维控制副本 | SHA256 `3646a9cf6e976c38bca5050535cbe1468a7c0c056001cd53f41dc31e836280bf` |
| 冻结任务状态 | succeeded 9,899；queued 1,907；failed 27；cancelled 875；running 0 |

源文件按实际容量分放在任务专用系统盘和内存盘目录，通过明确的 artifact root 读入。
提交 `150ff29` 的正式 `plan_upgrade → apply_upgrade → check_upgrade` 生成
`universal-v2 + preserved-body-import-v1 + legacy-part-title-supplement-v1`。
plan ID 为 `ce8c03b855c144b2c102f9a28c2ba54a07cfb58ee0cb6472f14fe88d637a0df5`，
receipt ID 为 `2f4494a67ef7f6f258d3af560358bce563eca66aa3528904fba8002819b94b74`。

计划、转换及最终检查均比较全部权威表的 rowid、SQLite 类型和原始值，以及完整文件集合与 SHA。
计划完成时累计 110.116 秒，apply 完成时累计 607.528 秒，最终检查累计 669.038 秒；
进程 `ru_maxrss` 为 141,644 KiB。三个时间是同一起点的累计值，不能相加。
没有将行数或 Schema 通过作为保真证明。全量逐对象原始清单保存在证据目录。

四个库外 hold 以原 job ID 和控制文件摘要绑定，报告明确 `handoff_required=true`、
`continuation_allowed=false`。其中包括字幕源不可用的 `0fb2c544-66c5-4da2-b44c-0824f25c9574`
以及时间线发布失败的 `01ae2045-56f2-4c80-8d9d-78ccf24346a1`。
原失败 attempts 和原始 transcript 保留；没有把空字幕诊断成静音，也没有排序或 clamp 时间戳。
运维原文件没有混入公开导出。

## 来源标题、正文和真实消费端

对原有 1,103 个 preserved-body draft head 分 12 批只读规划：`partTitle` 原已知 0、未知 1,103；
690 个具有本政策可用的来源绑定，413 个因可能只是视频总标题回填而阻塞。没有把 1,103 篇全部视为可补充。
本次只显式应用复现视频 `BV1ZK4y1Q7ge` 的 P1/P3，两篇均重新进入 pending-review；
余下 1,101 个原 head 保持不变，其中 688 个可补充候选未应用，413 个仍未知。
来源是归档中可验证的 part 投影，无法证明原观察时间时仍为 null。

| 分 P | part ID | 导出标题 | 本次行为 |
| --- | --- | --- | --- |
| P1 | 1771 | 概要 | 新 edition `3e34b4e71a2f4415a45952620c328b93`，原正文 SHA 不变 |
| P2 | 1772 | 如何破除庸俗的人文主义 | 原生冻结来源不参与补充，正文和来源不变 |
| P3 | 1773 | 如何进行真正的哲学反思 | 新 edition `67fac83464bf45d0bf82fcc82a93ed21`，原正文 SHA 不变 |

需要区分线上阅读站旧快照与本次生产数据库：本次源 DB 已有 P2 的原生 AI revision，
但尚无对应 native edition/head。仅在隔离副本中，使用既有付费结果生成 382 个原生待审预览，
包括 P2 的 `96ceab2b733149c7a071fc7998d04cb3`；这不是修改线上旧 edition。
没有生成新的 AI input、模型调用或批准。原生预览与两篇标题补充后，导出为公开 0、draft 1,485。

补充前后对 `editorial_inputs`、`editorial_revisions`、`editorial_chunk_results`、
`editorial_model_calls`、`workflow_jobs`、`workflow_attempts`、`publication_releases`、
`transcripts`、`transcript_segments` 九张表作全量 typed-row 比较，完全相同。
正文 UTF-8 摘要、历史 AI 参照、旧 editions/origins 和审核绑定另行验证；重复 apply 幂等。
三篇私有导出按各自实际政策验证七/十文件集合。

独立 checkout 阅读站 `9f7d063`，使用它的 `validateSiteSnapshots(includeOrigins=true)`
验证完整公开/draft 配对，然后直接调用真实 `partsListMarkup`、`adjacentParts`、
`resolveReaderRoute` 和 `readerPartRoute`。三篇目录标题正确，前后链接与每个分 P 的连续阅读
路由保持原模式和目标身份，没有“分段标题未提供”。这是实际消费者的结构、目录及路由验证；
不声称已做浏览器视觉验收或上线部署。

上述业务转换、全量保护检查和导出耗时 263.476 秒，`ru_maxrss` 298,608 KiB。
下载、ASR 和 AI 调用均为零。真实生产没有历史 release，不能把“验证 0 个 release”当成覆盖：
current/superseded/withdrawn、多 release、人工编辑和 draft/release 双 head 由固定历史 ZIP
通过正式升级后的独立预期测试覆盖。

## 完整快照与恢复

使用提交 `a5483a8`，完整快照采用可选 `deflate` level 1，默认 stored 行为保持。
包格式及 manifest 的未压缩文件 SHA 语义不变。快照包含完整音频、正文和所有必需历史文件，
不是引用型备份。

| 项目 | 实际结果 |
| --- | --- |
| snapshot ID | `be5912f8-ecc3-45fe-acea-3b23db357d02` |
| 文件 / 原始量 | 18,237 个 / 32,828,875,334 字节 |
| ZIP 大小 | 29,786,196,049 字节 |
| ZIP SHA256 | `38b8aa18b1496e7999194e92779605338d694e29a7031cf83d2a47b47146f6298` |
| save | 1,074.793 秒 |
| save + check | 1,300.824 秒；含最后包摘要的脚本总计 1,326.794 秒 |
| restore + 前置复核 + 恢复后全量复核 | 350.608 秒；`ru_maxrss` 111,280 KiB |

在完整 ZIP 独立校验成功后，复核所有冗余隔离源字节，再仅清理本任务的旧隔离副本，
将 ZIP 完整恢复到新目录。恢复后所有权威表和全部 artifact 字节逐项与保存前一致，
五类 recovery 变更计数全部为零，未重排任务、增加 attempt 或运行昂贵计算。

文件同时保留量和文件系统观测另存证据；完整 ZIP 与恢复副本同时占约 62.6 GB 内存盘。
快照过程中一次 `/proc` 观测的 VmHWM 为 61,476 KiB，该数字只是当时的高水位，
不能冒充完整快照全过程的最终 RSS 峰值。后续读取也没有借此声称复制速度或内存固定不变。

## 冻结样本、零重跑和故障边界

`test_archive_upgrade.py` 直接展开已提交 frozen ZIP；原 ZIP 和 expected 的固定 SHA 由发布门禁保护。
正式路径覆盖 legacy、原生/已迁移 universal、preserved、来源补充及存储扩展组合。
`test_upgrade_result_reuse.py` 调用真实 planner/handler：已完成结果零下载/ASR/AI，
同时一条合法未完成任务仍通过真实 claim/finish 前进。部分已提交 AI chunk 保留，显式重试只调用缺失块；
failed/cancelled 不被重新规划复活。生产全队列没有用实际昂贵重跑来验证这项性质。

已注入空间不足、源/计划/代码变化、WAL、未知扩展、缺文件、复制/转换/核验/安装中断、
错误 receipt、删除或改写无引用旧文件、新业务写入后重复 apply、未知 hold 关联。
拒绝结果均保留源与新增事实，半成品不会作为完整目标安装。合法 VTT 派生验证已有 segments 摘要，
非法时间线准确拒绝。这些故障发生在隔离测试，没有故意破坏生产源。

## 切换与回退手册

执行命令、空间条件、正式 plan/apply/check 和控制文件交接见 [显式契约升级](archive-upgrades.md)。
正式切换前，另行停止旧 worker，checkpoint 并保存完整备份，检查 plan 的精确源/目标/转换器，
验收目标数据与导出，设置新程序、归档根、artifact roots 和 runtime bindings。
先只读查询、verify、doctor，核对原模型身份与库外 holds，再显式选择允许续跑的任务。
本次演练本身不构成已经切换生产或交接控制权。

新目标业务写入前可停新进程，回到旧程序、根与配置。写入后必须保留新目标和新增事实，
必要时临时用旧源只读服务；不存在自动反向降级或两库无损合并保证。
生产源清理与保留期限属于独立操作，不是本次升级动作。

完整逐对象证据目录为 `/root/bili-issues-20261011-evidence`。
仓库提交脱敏摘要与 receipt 文件 SHA，不提交正文、凭据或完整运维 state；
该目录的运行脚本和逐文件/表报告用于复核，证据时间不代表之后的实时生产状态。
