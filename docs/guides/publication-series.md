# 编辑确认的阅读系列

系列用于帮助读者按编辑确认的顺序连续阅读多个视频。系列属于单独版本化的编辑元数据，
不改写既有 edition、release、正文或来源事实，不从标题、编号、AI 输出推断关联。
当前交付仅建立维护、导出和消费契约，未为现有生产内容录入未经确认的关联。

## 私有编辑源

JSON 根对象准确包含 `schemaVersion: 1`、`updatedBy`、`series`。`updatedBy` 为操作者记录标识，
不是身份认证；私有源应保存在版本控制或有备份的编辑工作区，不能放在站点快照内部。
`series` 可以是空数组，明确表示当前没有已确认系列。合成示例：

```json
{
  "schemaVersion": 1,
  "updatedBy": "synthetic-editor",
  "series": [{
    "id": "synthetic-course",
    "title": "合成示例，不表示实际内容关系",
    "sourceUrl": "https://example.org/editor-confirmation",
    "evidence": "合成编辑确认记录：第一讲、第三讲及第二讲缺失",
    "members": [
      {"bvid": "BV1xx411c7mD", "label": "合成第一讲", "ordinal": 1},
      {"bvid": "BV1xx411c7mE", "label": "合成第三讲", "ordinal": 3}
    ],
    "knownMissing": [{"ordinal": 2, "label": "合成第二讲", "note": "合成编辑明确确认缺失"}]
  }]
}
```

`id` 匹配 `[a-z0-9]+(?:-[a-z0-9]+)*`，在整个源中唯一。每个系列至少一个已确认成员，
BV 号匹配 `BV[0-9A-Za-z]{10}`，在该系列内唯一；同一视频可被编辑登记在多个系列。
成员与已知缺失各自按正安全整数 `ordinal`（1 至 9007199254740991）严格递增，彼此不重叠，布尔值不是整数。
编号允许有间隔，间隔本身不表示缺失。`knownMissing` 仅列出编辑明确确认的缺失位置。

标题、证据、标签、缺失说明和操作者均为非空文本，去除首尾空白，不接受 U+0000–001F 控制字符。
`sourceUrl` 为编辑确认依据的绝对 HTTPS 地址（字面 `https://` 前缀），需有主机、合法端口，不接受凭据、任何 `#` fragment、
空白或反斜线；可以链接原视频、编辑记录或人工确认的 issue。未知字段、重复 JSON key、
非 UTF-8 与非有限 JSON 数值均拒绝。JSON Schema 描述字段形状，程序还执行上述语义校验。

## 编辑命令

```bash
bili-asr publication series validate --series-file candidate.json
bili-asr publication series edit --input candidate.json --out series-editorial.json \
  --actor editor --expected-sha256 new
bili-asr publication series show --series-file series-editorial.json
# 后续编辑使用 show 返回的原文件 sha256，防止覆盖他人的更改。
bili-asr publication series edit --input revised.json --out series-editorial.json \
  --actor editor --expected-sha256 CURRENT_RAW_FILE_SHA256
```

三个命令仅访问明确指定的 JSON 文件，不打开、初始化或迁移归档数据库。命令始终输出 JSON。
`edit` 处理完整替换，规范化后用 `--actor` 更新 `updatedBy`，在独占锁中核对原文件字节 SHA-256，
临时文件写入并 fsync 后原子替换，在释放锁和报告成功前同步父目录（POSIX 执行目录 fsync，Windows 沿用现有平台约定）。不存在的文件只接受 `new`，现有无效文件和版本冲突拒绝。
替换前失败时原文件保留；替换后目录同步失败则命令报错，但新文件可能已可见，重试前应重新读取当前 SHA-256。`.文件名.export.lock` 是持久锁标记，不能当作编辑内容公开或随意删除。
对链接或 reparse-point 路径拒绝写入。

## 可选公开快照成员

```bash
bili-asr publication export --archive-root archive --out public-content \
  --series-file series-editorial.json
bili-asr publication export-drafts --archive-root archive --out draft-content \
  --series-file series-editorial.json
```

不传参数时行为与既有快照一致，不生成 `series.json`。传入时生成公开 `series.json`，
并作为普通文件登记在原 version-1 manifest 的排序文件列表中，其字节哈希参与 `snapshotId`。
catalog 既有 version 2 或 3、稿件内容哈希、review 原文和 release 事实不变。
再次不带参数导出会明确移除旧快照中的可选系列文件；输出仍必须是准确的受管理集合。

公开根对象准确包含 `schemaVersion: 1`、当前类别 `manuscriptType`、`editorialVersion`、`series`。
不公开 `updatedBy`。`editorialVersion` 是规范化私有对象经
`json.dumps(ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"`
编码为 UTF-8 后的 SHA-256，series 按 id 排序，成员及缺失按已验证的 ordinal 顺序。
该值标记明确编辑源版本，不代表人工审核稿件通过；公开消费者只校验 64 位小写十六进制，
不能用它复原或验证私有 actor，也不能替代 manifest 中的公开文件字节哈希。

公开系列保持上述准确字段，每个成员额外拥有 `entries` 数组。数组包含该 BV 在当前类别中
**全部且仅有**的导出条目，按 `(pageIndex 或 partIndex, slug)` 升序。每条准确包含
`slug`、`editionId`、`contentSha256`、`artifactSha256`，且值必须与该类别 catalog 完全相等。
version-3 条目仅当 `platform == "bilibili"` 时用 `externalVideoId` 匹配 BV。
全部条目依然先经过现有 catalog 身份、来源 URL、哈希和文件集合校验。

`entries: []` 表示已确认成员在本次、本类别快照没有可供阅读的稿件，可能尚未导出、仅存在于
另一类别或已撤回；不得推断视频内容缺失、跳过已知缺失提示或链接到其他类别。
已发布 A 与未发布 B 分开绑定各自当前快照，系列关系不把 B 变成正式发布。
归档导出及前端消费必须拒绝漏项、额外成员绑定、陈旧版本、乱序、错类别和不准确哈希。

## 验证

`tests/test_publication_series.py` 使用合成 SQLite 归档及离线 AI 测试替身验证编辑 CAS、原子失败保留、
严格字段/JSON/URL、所有分 P 的精确绑定、版本与类别隔离、发布撤回、草稿快照、哈希损坏和失败导出保留。
既有 publication/export/CLI 及 manifest 契约测试仍适用。所有示例关系都是合成测试，
不得据此修改真实生产关联或声称已有真实系列。

本机扩展回归限制（2026-10-10）：上游未修改基线 `ea4f57f` 与本分支均复现
`test_export_lock.py` 的四个 Windows byte-range lock 内读取失败，以及
`test_universal_publication.py` 的三个迁移/bootstrap 在只读数据库文件上执行 fsync 的 EBADF 失败。
`test_cli_registry.py` 在该基线还因不存在的 `bili_asr.coordinator` 导入失败，无法收集。
这些基线问题不表示新增系列校验通过了这些测试，且本轮不扩展到迁移系统修复。
本轮关键 publication、export、draft、CLI、identity 和 review 回归独立执行。

本轮关键组合 `test_publication_series.py`、`test_publication_export.py`、
`test_publication_draft_export.py`、`test_publication_cli.py`、`test_publication.py`、
`test_publication_contracts.py` 与 `test_publication_review_export.py` 通过 174 项、
跳过 6 项（本机无法创建 symlink）；随后新增的两个 CLI 导出验收也通过。
系列专项最终通过 33 项、跳过 1 项。
最终同一合成数据库中一个 BV 正式发布、另一个 BV 仅有未发布 edition，导出的两类别快照已通过
阅读站 `validateSiteSnapshots` 交叉校验，未将旧草稿与同版正式发布放入同一验收快照。
