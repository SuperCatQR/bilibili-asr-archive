# 搜索视频元数据与转录

`bili-asr search` 从 `archive.db` 搜索已存储内容。默认搜索转录；`--scope metadata` 搜索视频标题、简介和标签，未采集转录的视频也可以命中。搜索不会访问 Bilibili 获取缺失信息。

```sh
bili-asr search "辩证法" --scope transcripts --archive-root archive
bili-asr search "辩证法" --scope metadata --format json --archive-root archive
bili-asr search "辩证法" --scope all --from 2026-01-01 --to 2026-12-31 --limit 20 --archive-root archive
```

## 查询语义

| 范围 | 数据来源 | 查询语义 | 索引要求 |
|---|---|---|---|
| `transcripts`（默认） | 转录 FTS 中的时间块 | 保留 FTS5 查询语法；语法错误时按一个字面短语重试 | 先运行 `bili-asr search-index` |
| `metadata` | `videos.title`、`video_details."desc"`、`video_tags.tag_name` | 去除查询两端空白后的字面子串 | 无需建立或更新 FTS |
| `all` | 上述两种来源 | 各来源采用各自的查询语义 | 缺转录索引时仍返回元数据 |

元数据查询中的 `%`、`_`、单/双引号和反斜杠按普通文字匹配，不作为 SQL 通配符或表达式。中文子串可直接匹配。SQLite 的默认 `LIKE` 对 ASCII 字母忽略大小写；这里不承诺全 Unicode 的大小写折叠。

元数据在采集或更新后立即可搜。该范围只打开只读数据库连接，不解析 `--artifact-root` 或产物环境配置，不读取归档文件，也不创建缺失的数据库或索引。没有简介行或标签不影响标题匹配；缺少当前元数据 schema 的表或列属于不兼容错误，不当作字段为空。

## 身份、排序和数量

元数据的多个匹配字段或多个标签合并为同一命中。一个视频有多个已存储分 P 时，每个分 P 返回一条命中；没有任何 parts 的视频返回一条整视频命中，`page_index=null`。页码使用存储的零基 index，`P0` 对应源站 P1。

元数据依次按标题命中、标签命中、简介命中排序；同优先级按发布日期降序、BVID 升序、page index 升序排序。`matched_fields` 按标题、标签、简介的优先级列出命中字段，`snippet` 显示最高优先级字段的一段文字。

`all` 先返回元数据，再返回保持现有 FTS rank 顺序的转录。同一分 P 的两种来源分别保留。`--limit` 是最终结果的总数：元数据可能占满总 limit，此时需要用 `--scope transcripts` 查看转录。元数据与 FTS 的相关性分数不能直接比较，因此元数据 `rank` 为 null。

## 表格与 JSON

表格在每行前显示 `[metadata]` 或 `[transcript]`。转录保留时间区间；元数据时间为 `—`，无 parts 的页码显示“整视频”。两种结果均显示视频标题与 UTC 发布日期。

JSON 始终为一个数组。转录原有字段保留，增加 `hit_type="transcript"`；元数据沿用公共字段，时间与 rank 为 null，并提供 `matched_fields`。例如：

```json
[
  {
    "hit_type": "metadata",
    "block_key": "metadata:BV_EXAMPLE:p0",
    "bvid": "BV_EXAMPLE",
    "page_index": 0,
    "start_ms": null,
    "end_ms": null,
    "pubdate": 1791417600,
    "text": "辩证法课程",
    "source": "metadata",
    "rank": null,
    "snippet": "title: 辩证法课程",
    "video_title": "辩证法课程",
    "matched_fields": ["title"]
  }
]
```

`--from YYYY-MM-DD` 包含该 UTC 日的开始；`--to YYYY-MM-DD` 包含该 UTC 日的全部时间，实现为下一日开始前。同一天的 `--from` 和 `--to` 可用于查一天。元数据按当前 `videos.pubdate` 过滤；转录保留既有行为，按 FTS 建索引时保存的视频发布日期过滤。日期均表示视频发布日，而非采集时间或转录时间；后续修改元数据发布日期不会自动改写已建的转录索引。

## 缺失来源、错误与重建

- 空查询或正常无匹配：exit 0，JSON 为 `[]`。
- 缺数据库：exit 0，并提示先采集/建索引；不创建文件。
- 缺转录索引：`transcripts` 为 backlog，exit 0；`all` 保留元数据并将提示写到 stderr。JSON stdout 始终只含数组。
- 运行环境缺 FTS5：`metadata` 正常查询；`all` 保留元数据并提示转录不可用；`transcripts` 为 exit 1。
- 数据库损坏、元数据 schema 不兼容、转录索引形状错误或页损坏：exit 1。即使元数据已经占满 limit，`all` 也不会掩盖转录索引缺陷。
- 无效日期、非正 limit、倒置日期窗口以及 `metadata --rebuild`：usage error，exit 2。

`--rebuild` 只用于 `transcripts` 或 `all`，在查询前运行现有增量转录建索引流程。它不会重建元数据，也不声称修复已损坏的 FTS。索引进度写到 stderr，建索引失败会传递非零状态，不继续输出搜索结果。

元数据首版使用前后通配的字面 `LIKE`，通常需要扫描元数据。SQL 在一次匹配查询中合并字段、扩展分 P 并限定结果，不逐命中查标题或标签；`LIMIT` 限定返回结果和内存，无法保证扫描成本固定。更大数据规模若需要专门元数据索引，可在实际测量后独立增加维护契约。
