# 稿件编辑、审核与发布

AI 合成稿件、校验参照稿件与发布稿件各有明确身份。AI 工作流生成的正文只能作为编辑来源，
人工审核针对一份不可变的完整 edition。网站将已发布 release 与显式导出的未发布预览分开显示，
公开预览不构成人工批准，也不产生 release。

## 对象与文件

| 对象 | 文件与职责 |
| --- | --- |
| AI revision | 固定输入、模型配置和经过校验的段落结果；不表示人工批准 |
| AI 合成稿件 | `documents/part-<ID>/<REVISION>/ai-draft-v1/ai-draft.md`；只有整理后的正文 |
| 校验参照稿件 | 同 revision、同模板的 `review.md`；原文对照、来源、时间、模型参数和疑点 |
| Publication edition | 数据库内不可变的完整读者内容；每版独立审核 |
| Publication release | `publications/part-<ID>/<RELEASE>/publish-v1/publish.md`；仅由获批 edition 生成 |

每个分 P 有独立的当前 edition 与当前 release 指针。A 已发布时创建、编辑或审核 B，
公开导出继续使用 A；B 获批后仍须显式执行 publish 才会替换 A。撤回当前 release 后公开目录不再
包含该文章，内部 edition、审核、release 与事件继续保留。AI 重跑也不自动更换正在审核的来源。

新稿件契约没有旧 schema 迁移、命令别名或 manifest 转换。旧 `reading-v2`、旧稿件数据库或
旧数组 catalog 会在修改数据库或导出目录之前拒绝。使用独立新归档验证，无须删除原归档。

## 创建与编辑

先通过 `workflow proofread` 与 `workflow run --only-editorial` 取得已渲染 revision，
再显式创建 edition。这里的 ID 都是程序返回的准确标识，不能使用视频 BV 号代替。

```bash
bili-asr publication create --archive-root /srv/bili-archive \
  --revision-id R --actor editor --format json

bili-asr publication show --archive-root /srv/bili-archive \
  --edition-id E --format json
```

create 从已登记、通过字节哈希校验的 AI 合成稿生成待审 edition。可以原样采用 AI 正文，
新版本仍须独立审核。已有当前 edition 时，create 还需 `--expected-edition-id E`；
该字段明确说明编辑者看到的当前草稿，版本冲突会失败而不会覆盖另一位编辑者的工作。

edition 的完整内容是规范化 JSON：`title`、`markdown`、`summary`、`tags`、`source`、
`attribution`、`editorNote`。source 冻结 BVID、分 P、videoPartId 与来源 URL；其他读者可见字段
连同正文一起纳入 `content_sha256`，不会在导出时临时读取变化的视频标题。操作者和内部理由
存审计记录，不进入公开文章。操作者字符串是记录标识，不代表身份认证。

修改内容会创建新的 edition，`--edition-id` 是预期当前父版本。Markdown 文件提供完整新正文，
可选 metadata 文件提供严格 JSON 对象，仅允许 `title`、`summary`、`tags`、`attribution`、
`editorNote`，不允许改变来源身份、未知字段或重复 JSON key。

```bash
bili-asr publication edit --archive-root /srv/bili-archive \
  --edition-id E --markdown-file revised.md --metadata-file metadata.json \
  --actor editor --note "核对专名并补充读者可见说明" --format json
```

示例 `metadata.json`：

```json
{
  "title": "整理后的文章标题",
  "summary": "用于目录展示的摘要",
  "tags": ["访谈"],
  "attribution": "根据视频口述整理",
  "editorNote": "编辑增补内容已在正文注明归属。"
}
```

主动增加背景、观点或其他来源时，应在正文或读者可见编辑说明中标明归属。
原始 AI revision 和校验参照稿件保留为基线，不把人工意见回写其中。

## 精确版本审核

用 show 或内部导出核验完整内容并取得 `content_sha256`。审核命令同时要求目标 edition、
审阅者看到的准确哈希与预期原状态；旧哈希、错误状态或关系冲突会失败。

```bash
bili-asr publication review --archive-root /srv/bili-archive \
  --edition-id E --status in-review --expected-status pending-review \
  --content-sha256 H --actor reviewer --note "开始核验来源与疑点"

bili-asr publication review --archive-root /srv/bili-archive \
  --edition-id E --status approved --expected-status in-review \
  --content-sha256 H --actor reviewer --note "确认此完整版本" \
  --issue-url https://github.com/OWNER/REPO/issues/123
```

状态为 `pending-review -> in-review -> approved`；审阅中也可进入 `changes-requested` 或
`rejected`。未改内容的 changes-requested 版本可回到 in-review；正文或元数据有改动时必须创建
新的 pending-review edition。approved 与 rejected 为终态，后续修正创建新版本。
审核意见、操作者和可选讨论 URL 都会保留。任何自动工作流、重渲染或重导出都不提供人工批准。

## 发布与撤回

```bash
bili-asr publication publish --archive-root /srv/bili-archive \
  --edition-id E --actor publisher --format json
```

首次发布没有旧 release 时不传预期版本；替换 A 时必须增加 `--expected-release-id A`。
服务会重新验证 edition 完整内容、精确 approval、分 P 关系与文件哈希，在写入固定发布文件后
事务切换 release 指针。B 写入或登记失败时 A 保持有效；重试相同 edition 使用同一 release ID，
不重复新增发布记录和事件。已替换或撤回的 release 不会因为重复 publish 自动重新上线。
已登记文件损坏或缺失会报错，不通过重试静默覆盖。

```bash
bili-asr publication withdraw --archive-root /srv/bili-archive \
  --release-id L --actor publisher --note "撤回原因" --format json
```

withdraw 只操作明确指定的 release。撤回历史 release 不会下线另一有效版本。
撤回当前 release 后需重新导出、构建和部署站点，并清理部署端旧文件及缓存；本地导出不能撤销
已经部署到服务器或 CDN 的副本。重新上线采用新的 edition、审核与发布流程。

工作流的 `publish` 仍表示 SRT/VTT/TXT/Markdown/raw JSON 转录 bundle 发布，文章发布入口是
`publication publish`，两者互不代替。

## 已发布、未发布预览与内部导出

公开导出只读取有效 release，验证 release -> edition -> approval 关系、内容与发布字节哈希，
并完整校验同一 AI revision 的配对基线与原始 `review.md` 字节。
没有有效 release 的分 P 不出现；损坏发布稿会让整次导出失败，不回退 AI 或待审稿。

```bash
bili-asr publication export --archive-root /srv/bili-archive \
  --out /srv/public-content --format json
```

`catalog.json` 使用明确 envelope：

```json
{
  "schemaVersion": 2,
  "manuscriptType": "publication",
  "articles": []
}
```

条目携带冻结标题、摘要、标签和来源、edition/release/revision ID、完整内容与发布文件 SHA-256、
模板和发布时间。条目还必需包含 `reviewFile` 与 `reviewArtifactSha256`，分别指向
`articles/part-<videoPartId>/review.md` 及其原始字节 SHA-256。
该文件取自条目的固定 `aiRevisionId`，保存原文与整理稿、疑点、来源、回看链接及非敏感模型参数，
按原始字节复制，不重新渲染，也不代表对人工编辑后的 edition 提供审核或批准。
`publication-export-manifest.json` 仍采用 schemaVersion 1，登记 catalog、正文和参照稿全部文件。
公开输出不含未发布 edition、模型请求或完整响应、`review.json`、人工审核意见、审核人或内部事件。

两类读者 catalog 均严格要求 version 2，不接受 version 1，包括旧空目录。升级时先用新的输出目录
重新导出并验证，再整体替换阅读站中的快照；旧快照备份保留在服务目录外。不自动迁移旧数据，
不放宽字段、路径或摘要校验。通用 manifest 的 schemaVersion 保持 1，不能与 catalog 版本混淆。

导出先完整验证并准备新快照，再借助独占锁、私有 staging/备份与恢复日志提交。切换中输出可能
短暂不可用，成功快照不会混合新旧 catalog 与文章。下次调用先恢复未完成提交；输出有未知手工
文件或错误 manifest 时拒绝。替换与撤回后旧受管文件不会保留在新公开目录。

内部审阅导出必须明确选择同一来源关系的 revision 和 edition：

```bash
bili-asr editorial export --archive-root /srv/bili-archive \
  --revision-id R --edition-id E --out /srv/internal-review --format json
```

它提供配对的 `ai-draft.md`、校验参照稿件 `review.md`、所选 edition、相对父版本与 AI 基线的
差异、审核信息及内部 manifest。第一版的父版本比较采用 AI 基线。必要的模型配置保留在参照稿中，
不默认复制完整请求或思考响应。内部与公开导出使用不同 schema、不同目录，互相混用会拒绝。

阅读站 `SuperCatQR/markdown-reading-site` 是独立仓库。已发布栏目只消费 `publication export` 的
有效 release；未发布栏目消费下面独立的读者预览契约。完整内部审阅目录不作为网站搜索来源。

### 未发布稿公开预览

维护者可以明确将当前未发布 edition 的读者内容公开，用于在网站查看和核验：

```bash
bili-asr publication export-drafts --archive-root /srv/bili-archive \
  --out /srv/draft-content --format json
```

它只选择各分 P 的当前 edition，并排除曾产生任何 release 的 edition。已发布、已替换或已撤回的
历史版本不会重新作为草稿公开；同一分 P 的有效 A 与未发布 B 可以分别查看。审核通过但尚未
显式 publish 的 B 仍标为“已审核，未发布”。待审核、审核中、待修改和未采用状态也按实际值显示。

输出采用 `schemaVersion: 2`、`manuscriptType: "publication-draft"` 的 catalog 和独立
schemaVersion 1 的 `publication-draft-export-manifest.json`，正文文件为 `drafts/edition-<ID>/preview.md`，
配对参照文件为 `drafts/edition-<ID>/review.md`，由必需的 `reviewFile` 和 `reviewArtifactSha256` 标识。
条目携带冻结读者内容、来源、edition/revision ID、内容与文件哈希、审核状态及创建时间，
不携带 release ID、发布时间、审核人、内部意见、`review.json` 或审计事件。
公开参照稿保留原有原文对照、疑点、回看链接与非敏感模型参数；不输出完整模型请求或响应。
导出保持只读，验证来源与完整内容，沿用目录锁、完整快照和中断恢复。

将已发布输出放入阅读站 `content/`，将预览输出放入独立 `draft-content/`，然后分别验证并构建。
网站提供“已发布 / 未发布”入口；预览页明确提示内容尚未正式发布，并显示准确版本与哈希。
两个栏目分别搜索，预览不会替换已发布正文或改变审核与 release 指针。
这条命令会准备可公开的待审正文和配对原文参照稿，执行和部署前应确认所选归档适合公开。
三个导出种类的 schema 与目录互不混用；删除网站预览时须重新导出并同步构建、部署和缓存。

## 根目录与错误

所有操作支持 `--archive-root` 与 `--format text|json`。create、publication export、export-drafts、editorial export
读取产物根；publish 写产物根并做写权限校验。它们接受 `--artifact-root`，读取先探测产物根再
归档根；数据库始终在归档根。edit/review/withdraw/show 不访问产物根，因此不接受该参数。
AI workflow 的文档目前直接写归档根，详见 [artifact-root.md](artifact-root.md)。

路径必须是受控身份目录内的规范相对路径。根、父目录与目标上的符号链接、junction、reparse point，
非 UTF-8 文件、错误内容哈希和逃逸路径均拒绝。导出不可覆盖源产物、数据库或源归档的祖先目录。

命令成功返回 0；业务、完整性、旧契约或并发冲突返回 1，并输出对应错误标识。
缺少必需参数、未知命令等解析错误沿用 argparse 的退出码 2。
并发失败后先重新 show 并核对当前版本，不应机械套用新的预期 ID 或哈希继续操作。


## 原视频标签

新 edition 创建时按相同 BVID 的 `video_tags.tag_name` 冻结主题；按 tag_id 顺序去重，
不从标题、编号或 AI 正文推断。所有分 P 共用视频的源标签，后续源标签变化不影响旧版哈希或已发布文件。
未尝试或最新观察失败时 create 会提示覆盖缺口；无标签时保持空数组，已保存标签仍可作为上次成功集合使用。

先补采源标签，再显式同步已有 edition：

```bash
bili-asr fetch-tags --archive-root /srv/bili-archive --bvid BVxxxxxxxxxx
bili-asr publication sync-source-tags --archive-root /srv/bili-archive \
  --edition-id E --actor editor --note "同步原视频标签" --format json
```

sync-source-tags 要求 E 是当前父版本，记录 actor、来源说明和审计事件，生成新的待审核 edition。
只在有成功观察或已有非空源集合时允许同步；未观察或本次不可用时先补采。
成功观察空集合可以生成空主题的新版本。原版、AI revision、正文与现有 release 继续保留。
