# 工作流中的音频保留与复用

当前 workflow 下载成功的音频保留在 `--archive-root` 下。字幕、ASR、转录发布或阅读文档渲染完成后，都不会自动删除音频，也不会执行目录容量预算、按年龄清理或引用计数回收。磁盘容量由运行环境和维护者管理。

旧 `schedule`、`campaign`、`pilot`、顶层 `run`、顶层 `asr` 已删除。`--keep-audio`、`--no-keep-audio`、`--max-audio-gb` 和旧 `--offline` 不是当前 workflow 参数。设置 `BILI_KEEP_AUDIO=0` 不会让当前 workflow 自动删除音频；保留的源码 helper 不等于已连接的公共功能。

## 从规划到保留

先将视频及分 P 元数据存入数据库，再规划独立的字幕、音频和 ASR jobs。示例 BVID 应替换成该数据库中已采集的视频。

```sh
bili-asr fetch-meta --archive-root archive --limit-pages 1
bili-asr workflow plan --archive-root archive --bvid BV_EXAMPLE --page-index 0
bili-asr workflow run --archive-root archive --limit 10
bili-asr workflow status --archive-root archive --jobs
```

`workflow plan` 只建立任务，不下载；`workflow run` 执行就绪任务。`--limit` 限制执行的 job 数量，不是视频数或磁盘容量。`p0` 为数据库零基 page index，对应源站 P1。

默认 `--asr-policy all` 会规划 audio/ASR；`selected` 使用显式目标；`below-threshold` 根据已存储的质量评估决定是否规划，并要求 `--quality-threshold`。字幕获取与音频/ASR 是独立生产者，已有字幕不会自动撤销已规划的音频任务。没有执行 audio job，就不会因此下载音频。

## 音频落盘的提交边界

1. 校验 job 当前 lease，按存储的 BVID、page index 和 CID 建立目标身份。
2. 在归档根的 `audio/` 下分配本次独占 staging。下载 helper 使用临时文件接收流；失败的 CDN 尝试从空文件重新开始，非空检查与必要的格式转换在 staging 完成。
3. 再次校验 lease，用 `ffprobe` 获取时长，拒绝非有限或非正时长，计算字节 SHA-256、大小及格式。
4. 进入任务拥有的短数据库事务，在同一所有权检查范围内替换最终音频、登记 `audio_objects` 并建立分 P 关联。
5. audio job 成功后，ASR 从该 dependency 的结果读取 `storage_key`，以归档根下的文件为输入。

下载、格式转换、探测和摘要计算不占用最终提交事务。最终替换及 catalog 登记受 lease/取消检查约束，避免已取消或失去 lease 的 worker 发布音频。取消在安全提交边界生效，不能保证立即中断网络请求或推理。

正常退出清理本次 staging；强制终止或掉电可能留下临时文件。当前没有自动遍历历史 staging 并回收的 workflow 任务。SQLite 和文件系统不是一个原子提交介质，失败后的 catalog 与实际文件仍需分别核对。

ASR 成功、失败或 publish 成功均不会触发删除。取消后续 ASR/publish 也不删除此前完成下载的音频。转录包有独立 marker 和摘要契约，见 [WebVTT 与五产物归档包](webvtt.md)。

## 音频存放在哪里

```text
archive/
├── archive.db                       # jobs、音频 catalog、转录及发布记录
├── audio/
│   └── BV_EXAMPLE.p0.m4a             # 下载成功后持续保留
├── transcripts/BV_EXAMPLE.p0/
│   ├── bundle.srt
│   ├── bundle.vtt
│   ├── bundle.txt
│   ├── bundle.md
│   ├── bundle.raw.json
│   └── .bundle-ready
└── documents/
    └── ...                          # 校对和阅读文档
```

workflow 的写入位置由 `--archive-root` 决定。`--artifact-root` / `BILI_ARTIFACT_ROOT` 只为部分查询和导出命令提供外部读取候选，不能重定向新下载，也不会让 ASR 从外部副本寻找输入。详见 [归档根目录与只读产物候选根](artifact-root.md)。

下载 helper 支持 `.m4a` 及部分 FLAC 流的处理和 fallback；应以实际登记的 `storage_key`、`format` 与文件内容为准，不仅凭文件名判断编码。归档根所在的存储目录决定新增音频的分区。

## Catalog 记录什么

| 表 | 主要字段 | 含义 |
| --- | --- | --- |
| `audio_objects` | `audio_id`、唯一 `sha256`、`byte_size`、`format`、`duration_ms`、唯一 `storage_key`、`created_at` | 用字节摘要标识对象，记录存储引用和媒体信息 |
| `part_audio_objects` | `video_part_id`、`audio_id`、`acquired_at`、`acquisition_source` | 保留各分 P 获取该内容的来源关联 |

当前 workflow 的 acquisition source 为 `workflow`。相同字节 SHA-256 命中同一 catalog 对象，多个分 P 可以关联同一 `audio_id`，各自身份及来源仍分别保留。

这是内容标识与关联复用。下载文件仍使用各分 P 的路径；不同分 P 下载到相同内容时，磁盘上可能保留多个文件，catalog 的 `storage_key` 不枚举所有副本。当前没有自动合并物理文件、建立硬链接、删除重复副本或垃圾回收的 workflow 步骤。

Catalog 不是实时文件清单。人为移动、改写或删除文件不会自动更新对象、关联或成功 job 的结果。判断可用性须核对实际文件；证明内容未变须重新计算摘要与 catalog 比较。

## 复用的两层含义

**任务复用**来自稳定 job 身份。每个分 P 的 audio job 有固定去重键，重复同一规划不会新建另一个 audio job。不同 ASR profile 可依赖该分 P 已成功的音频任务，继续使用保存的结果，不要求为每个模型再次下载。

**内容复用**来自 SHA-256 与关联表。多个分 P 下载到相同字节时，catalog 能识别共享对象，`dedup report` 展示这些关系。它不会在下载前通过摘要寻找尚未取得的远端内容，也不替代磁盘整理。

当前 audio handler 在下载前检查该分 P 的 canonical `audio/<bvid>.p<index>.m4a` / `.flac`，发现受约束、非空文件后重新 probe、计算哈希并在 lease guard 内登记，保留文件和修改时间，不发起下载。只有没有可复用文件时，才在本次独占 staging 内调用 `audio.download_audio`。这不是扫描任意音频目录或按远端内容摘要预取；已成功 audio job 的正常后继继续采用保存的 dependency 结果。

成功 audio job 不会因文件后来丢失而自动重排。新 ASR 读取不到该路径会失败；`workflow retry` 只重排失败 jobs，不能保证重跑已经成功的 audio job。当前也没有旧 `--offline` 那样为任意本地音频直接建立 ASR 的公共入口。

## 查看任务、转录覆盖与精确复用

```sh
bili-asr workflow status --archive-root archive --jobs
bili-asr dedup report --archive-root archive --format json --limit 20
bili-asr verify --archive-root archive --format text
bili-asr coverage --archive-root archive --format json
```

- `workflow status --jobs` 显示任务类型、状态、attempt 数和取消造成的依赖阻塞。
- `dedup report` 只读数据库，统计音频对象、关联、跨分 P 共享对象，以及来源/语言相同的精确转录重复。`--limit` 仅限制示例组数，汇总覆盖全库；它不重算音频摘要，也不测量实际释放空间。
- `verify` 检查登记发布的转录包，不是音频 catalog 与磁盘内容的全面审计。
- `coverage` 统计转录和发布完成度。当前 `reclaimed_audio` 固定为 `false`，不证明音频仍存在，不能据此筛选有音频或已回收音频的分 P。

只需重建转录文件时，可用 `workflow publish --archive-root archive --part-id 12` 请求发布，再用 `workflow run` 执行。该 publish job 使用已有存储转录，本身不下载或调用 ASR；同次 run 仍可能执行其他就绪任务，应核对 jobs 的结果。

## 容量管理的现状

当前没有默认 10 GiB 限额，也没有 `--max-audio-gb 0` 这样的不限量开关。目录随成功下载增长，staging 和转换增加运行时峰值。`--limit`、`--asr-policy` 和目标选择控制工作量，不提供文件系统硬配额。

需要限制时，使用存储系统的配额、空间监测和运行批次管理。保留音频支持人工核对、后续 profile 处理和源站删除后的证据保存。维护者若在外部清理，应先核对依赖与备份需求；移除文件会使未来音频依赖失效，当前 workflow 不自动修复 catalog 或重新下载。

当前没有自动保留规则、冷热迁移、按时长回收或完成后仅留文本的公共策略。无需设置 `BILI_KEEP_AUDIO=1` 才保留，设置 `BILI_KEEP_AUDIO=0` 也不改变行为。

## 保留源码与公共功能的区别

`audio_budget.py` 有容量测量/预算 helper，`audio_reclaim.py` 有受约束删除 helper，`artifact_root.py` 有 `resolve_keep_audio`。库代码可显式调用，但当前 CLI/`WorkflowRuntime` 没有用它们实现自动预算或回收。旧命令、flags 或环境变量不能激活这些能力。

本文不提供旧日志到 workflow jobs 的迁移命令，也不将保留源码视为兼容旧入口。相关文档：[架构](architecture.md)、[目标选择](workflow-selection.md)、[SQLite 存储](metadata-storage.md)。
