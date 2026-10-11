# 旧迁移稿的分 P 标题补充（issue #313）

此功能服务同视频连续学习和复习的读者：原迁移稿的分 P 标题未知，但归档已采集
到该分 P 的标题时，以显式计划创建带标题的新 edition。第一版仅补 `partTitle`；
不刷新其他来源字段，不重跑 ASR/AI，不更换历史 AI revision 或校验参照，不发布稿件。

## 证据与版本

原 `legacy-frozen-facts-v1` 基线及历史 edition/origin 不改写，仍按旧规则验证。
新政策为 `legacy-part-title-supplement-v1`。不可变证据记录从 `video_parts` 的当前
归档投影获取值，同时核对平台、外部视频 ID、零起始分 P 索引、本地 part ID 和 CID。
证据种类 `archive-part-projection` 准确描述当前归档中的已存储字段，不声称有上游
签名或保留了原始 API 响应。操作者不能提交任意标题：apply 在写事务内重新从归档
读取证据，与计划逐项比较；重新计算计划和证据哈希也不能绕过此检查。

标题的原采集时间不可由通用 `updated_at` 证明，因此 `observedAt=null`。
`source_metadata_supplements.registered_at` 单独记录本次证据登记时间，不进入来源
观察时间或视频发布时间。现有 `metadataObservedAt` 继续保持未知。

正文、稿件 title/summary/tags、attribution 和 editorNote 均复制当前父 edition，
只改变 `source.metadata.partTitle`。新版本进入既有 `pending-review`；原 release
head 不变。正文是否 preserved 仍按原正文基线 SHA-256 判断，不因补 metadata
而改称正文已编辑。后续编辑和 source tag 同步继承补充证据；每个祖先按自己的
有效证据验证。源标题以后变更不会改写已冻结的证据。

缺失或空标题、来源绑定错误、非迁移稿、已有标题、过期 head 都有明确报告。
旧采集器曾允许单 P 用总标题回退；第一版保守拒绝与视频总标题相同的投影，
以免把回退值当成真实分段标题。这可能拒绝恰好同名的真实标题，需后续引入
明确的原始分 P 观察证据解决，不能从正文或总标题猜测。

## 安装、计划、执行与检查

先在静止的、完整的离线归档副本安装；原 preservation 扩展必须已安装。
普通读取和写入不执行 DDL。安装沿用维护锁、副本备份、完整 schema 校验和
原子切换；存在 writer 或 SQLite journal 时拒绝。备份/恢复登记新 schema 契约，
不可将装有扩展的归档交给不支持它的旧程序。

```powershell
bili-asr publication supplement-source install --archive-root ARCHIVE_COPY --format json
```

选择文件只包含 `editionIds`，每批 1..100 个唯一的**当前** edition。先查当前
head；issue 中的 ID 是排查时的版本，不保证仍为当前版本。

```json
{"editionIds":["CURRENT_P1_EDITION_ID","CURRENT_P3_EDITION_ID"]}
```

```powershell
bili-asr publication supplement-source plan --archive-root ARCHIVE_COPY --selection-file selections.json --out title-plan.json --format json
bili-asr publication supplement-source apply --archive-root ARCHIVE_COPY --plan-file title-plan.json --actor OPERATOR --format json
bili-asr publication supplement-source check --archive-root ARCHIVE_COPY --edition-id NEW_EDITION_ID --format json
```

plan 只读，`--out` 拒绝覆盖文件。输出逐字段 before/eligible 统计，以及完整
skipped/blocked 清单。原生稿件（包括 issue 的 P2）会跳过。任何 blocked 项使
该计划不能执行；应排查原因或另选无阻塞批次。apply 输出 supplemented 和
knownAfter/unknownAfter。统计限于所选范围；excludedNative 与迁移稿计数分开，
不能把排查快照中的 1,103 篇都视为有可用证据。

apply 同时检查 draft 和 release head。整个批次的 edition、review、audit、
origin、证据、head 和 receipt 在同一个 `BEGIN IMMEDIATE` 事务中提交，
不需要安装新正文文件。失败和提交前进程退出回滚整个批次；提交后退出可通过
同一计划找回结果。相同成功计划始终返回原 edition，不重置后来编辑或审核的 head。

## 成对交付与消费者

仍使用 `universal-origin-v1`（catalog v3/origins v1/manifest v2）。新能力以
独立、严格识别的政策和条件字段 `metadataSupplement` 表达：旧政策保持原字节和
验证规则，新政策要求有效证据。旧消费者会拒绝新政策，必须先更新阅读站验证器，
再交付含新政策的快照；不能静默降级为旧政策。

新 origin 保留旧 importId、AI revision/template 和正文/参照哈希；新增
`metadataSupplement={supplementId,evidence}`，partTitle 的逐字段证据 kind 为
`archive-part-projection`。证据 ID 为 canonical JSON SHA-256；平台/视频/分 P/
本地 part ID 和标题必须与 catalog 一致。CID 是冻结的采集绑定，消费者验证形状
和证据哈希，生产者还核对归档中的 CID。哈希证明一致性，不独立证明上游真实性。
manifest 原算法继续覆盖 catalog 和 origins 的实际字节，重新签 manifest 不能
绕过政策、字段和跨文件绑定检查。

```powershell
bili-asr publication export --archive-root ARCHIVE_COPY --out NEW_PUBLIC --contract-profile universal-origin-v1
bili-asr publication export-drafts --archive-root ARCHIVE_COPY --out NEW_DRAFTS --contract-profile universal-origin-v1
```

补充不会自动更新公开 release；新标题先出现在新 draft，正式公开仍须正常审核和
显式发布。使用显式范围时准确记录选中的当前 ID，不能用空目录替代真实公开内容。
阅读站必须成对校验两份快照，前端继续只读冻结 `sourceMetadata.partTitle`。

## 验证与生产边界

回归覆盖已有人工编辑、后续继承、错误平台/视频/分 P/CID、伪造值及时间、源值变化、
draft/release head 冲突、原子回滚、重复执行、并发相同计划、提交前后进程退出、
CLI、成对导出、正文/历史参照保留、归档备份恢复和原生稿件跳过。
阅读站消费生产者直接导出的合成快照，并测试重签 manifest 后的语义篡改。

这些测试使用冻结历史测试归档和模拟采集标题，不等同于生产副本验证。
上线前还须在最新生产的一致性副本核对 BV1ZK4y1Q7ge 的 P1/P3 分别为“概要”/
“如何进行真正的哲学反思”，P2 的原生来源不变，生成真实统计及失败/跳过清单。
本次代码实现不表示已经安装生产扩展、批量补充或部署网站。

2026-10-10 本地验证结果：旧稿迁移测试 37 passed；补充标题、publication、契约和
manuscript snapshot 最终组合回归 81 passed / 1 skipped；额外的损坏证据备份拒绝
和成对导出/恢复检查 4 passed。新补充流程共 21 个参数化用例。新模块 Ruff、
全仓库 E9、编译和 diff 空白检查通过。禁用 apply 的归档证据比较后，“重新计算
哈希的伪造标题”回归用例按预期失败；实验只在独立 Python 进程内修改函数。

验证还暴露两个已有 Windows 问题并修复：迁移数据库 fsync 改用可写句柄；
snapshot 的 release/来源检查在异常路径显式关闭游标，避免临时数据库占用的
清理错误掩盖真实完整性错误。后者由既有 snapshot 拒绝错误 head 的测试验证。
阅读站完整测试 124 passed，原生产快照校验和构建成功；构建临时目录使用独立
本地路径以避免 Windows 默认 Temp 的 esbuild 删除权限问题。
