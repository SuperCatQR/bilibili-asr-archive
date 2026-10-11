# 保留旧正文的迁移导入

此功能将归档中经过校验的 v1 AI 正文或指定旧 edition 正文导入为新的 content v2
稿件。旧 input/revision 和 review 文件继续使用真实的 v1 身份。导入不调用 ASR、AI、
补采或工作流重试，不新增 ai-draft-v2 产物。新完整对象重新进入 pending-review。

## 安装与计划

先在离线归档副本安装 `preserved-body-import-v1` 扩展。安装持有维护锁，在数据库
副本上安装、校验 schema，再切换数据库；存在 writer 或 SQLite journal 时拒绝。
普通 READ/WRITE 不执行 DDL。安装会改变 snapshot 数据库契约摘要，旧程序不能读取
此扩展的导入稿件，因此不能与新程序混用。

```powershell
bili-asr publication import-preserved install --archive-root ARCHIVE_COPY --format json
```

选择文件仅包含 `selectors`，每个选择准确包含 `kind` 和 `id`：

```json
{"selectors":[{"kind":"ai-revision","id":"VERIFIED_REVISION_ID"},{"kind":"edition","id":"VERIFIED_EDITION_ID"}]}
```

```powershell
bili-asr publication import-preserved plan --archive-root ARCHIVE_COPY --selection-file selections.json --out plan.json --format json
bili-asr publication import-preserved apply --archive-root ARCHIVE_COPY --plan-file plan.json --actor OPERATOR --format json
bili-asr publication import-preserved check --archive-root ARCHIVE_COPY --edition-id IMPORTED_EDITION_ID --format json
```

计划命令只读，输出完整计划及摘要；`--out` 只创建新文件。任何阻塞项使退出码为 1，
apply 拒绝整个批次。每批最多 100 个选择，基线正文和参照共最多 64 MiB；同一 part
不能有多个候选。已有 content v2
草稿的 part 会跳过。选择 ai-revision 而现有 edition 正文不同，会明确报告
`discardsCurrentEdits`。apply 校验冻结内容和原文件、检查预期 draft/release head，
将 edition、origin、pending review、audit 和 receipt 同时提交。原公开 head 保持有效。

首版固定使用 `legacy-frozen-facts-v1` 元数据政策：视频标题和平台身份来自旧冻结输入，
其他没有旧输入证据的字段为 null，来源 tags 为 [] 并标记 unobserved。稿件的编辑
title/summary/tags 与来源事实分开保存。不会把当前数据库投影或迁移时间当成旧来源
事实。后续分 P 标题补充使用独立政策和不可变证据，见
[旧迁移稿的分 P 标题补充](source-part-title-supplement.md)；不改变本政策或历史基线。

正文按 UTF-8 原始字节比较；CRLF、BOM、首尾空白等导致现有规范化改变字节时返回
`body_not_canonical`。导入不修复字节后宣称保留。edition 选择保留真实编辑字段，
AI 选择使用旧 ai-draft.md；不会从 publish.md 猜测正文边界。旧 attribution/editorNote
保留在私有基线，新说明明确表明没有重新调用 AI、此完整版本需要人工审核。

## 重试、编辑和发布

相同成功计划返回原 edition/import ID，用户之后的编辑、审核和 draft head 不重置。
并发 head 变化要求重新生成计划。基线和 origin 为不可变侧表，原 authority 行不改写。
正文基线放在 `documents/imports/<importId>/body.md`，参照字节放在同目录 review.md。

暂存使用独占锁和 ownership journal，位于归档 artifact inventory 以外。进程退出后，
下一次 apply 只清理 journal 指明的、文件名与边界验证通过的暂存文件。已安装但未提交
的基线文件按内容哈希复用，不删除。snapshot 仍携带所有登记基线和不可变历史文件。

后续 `publication edit` 或 `sync-source-tags` 在同一事务继承 origin。正文等于基线
时 relation=preserved，变化时 relation=derived；来源 metadata 不能通过编辑更换。
公开发布仍须正常审核新 edition 的完整 contentSha256，并显式指定预期旧 release。
原 review.md 是历史 AI 基线，不能视为已审核当前编辑正文。

## 导出协议

迁移稿必须使用 `universal-origin-v1`；普通 manifest v1 导出拒绝迁移稿。

```powershell
bili-asr publication export-drafts --archive-root ARCHIVE_COPY --out NEW_DRAFTS --contract-profile universal-origin-v1
bili-asr publication export --archive-root ARCHIVE_COPY --out NEW_PUBLICATIONS --contract-profile universal-origin-v1
```

该 profile 只接受真实 content v2 文章，使用 catalog v3、origins v1、manifest v2。
仍在公开 head 上的旧 content v1 稿件会阻塞整个 profile 导出，必须先完成审核并显式
发布迁移稿，或以重复的 `--release-id CURRENT_RELEASE_ID` 显式选择公开范围。
草稿范围使用重复的 `--edition-id CURRENT_EDITION_ID`。选择项必须唯一、存在并仍为当前
head；草稿选择不能是已有 release 的版本。未指定范围时保持原来的完整目录语义，
不会静默漏掉旧公开版。`--empty-scope` 可产生有意为空的范围，不能与具体 ID 同用；
服务 API 使用显式空列表实现相同语义。
空公开目录同样输出 catalog v3、origins 空数组和 manifest v2。

origin 每篇一个，准确区分 ai-generated-v2、preserved-legacy-body 和
edited-after-preservation。公开证据仅包含身份、哈希、政策和逐字段证据摘要，不包含
私有基线说明、提示词、审核备注或绝对路径。导入稿 catalog.aiRevisionId 是旧 revision。

manifest v2 的 snapshotId 为 canonical JSON 的 SHA-256，输入包含 schemaVersion、
manuscriptType、contractProfile、排序后的 files。manifest 不列自身，必须列 catalog
和 origins；manifest v1 算法保持原值。消费者须同时校验准确字段、文件白名单、文件
哈希、metadata/revision/review 绑定、origin 唯一性和正文保留声明。
JSON Schema 描述字段形状；跨文件关系与语义规则以运行时验证器和测试为准。

私有 editorial export 增加 import-origin.json、preserved-body.md 和
differences/preserved.patch；原始 AI template 继续显示 ai-draft-v1。

此提交实现生产者导入与交付协议；阅读站配套分支 `codex/preserved-body-origins` 实现
catalog v3/manifest v2 严格解析与来源展示，包含生产者直接导出的三种来源测试快照。
部署前须将两份快照一起验证切换；现有阅读站 main 仍须先合并对应消费者改动。
实现和测试不表示已经安装生产扩展、批量迁移历史稿、修改相关 issue 或发布网站。

## 隔离验证结果

2026-10-10 在生产 SQLite 的一致性副本选择了 3 个真实旧 AI 修订，导入、检查、
重复执行及显式范围导出成功，3 个旧正文 SHA-256 与导入正文完全相等。
只在副本安装扩展，模型调用、工作流任务、失败尝试计数均未改变，生产归档未修改。
副本读取未复制的历史产物时依赖生产归档只读回退，因此不是可移机的完整归档。

测试包括 CLI、原子批次、并发 head 冲突、进程退出前后恢复、后续编辑继承来源、
审核发布、snapshot 保存/校验/恢复、来源语义篡改、BOM/CRLF 保留边界及范围导出。
阅读站配套测试使用直接导出的三种来源合成快照，真实样本也已验证能打开阅读。
