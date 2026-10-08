# 按 BVID 或分 P 规划工作流

`workflow plan` 只使用已经采集到 SQLite 的元数据，不会因缺少视频而自动发起网络请求。先通过 `fetch-meta` 采集视频，再选择存储的目标：

```sh
bili-asr workflow plan --bvid BV_EXAMPLE_A
bili-asr workflow plan --bvid BV_EXAMPLE_A --page-index 0
bili-asr workflow plan --bvid BV_EXAMPLE_A --bvid BV_EXAMPLE_B --proofread
bili-asr workflow plan --part-id 12 --part-id 13
```

`--bvid` 和 `--part-id` 均可重复，两种形式互斥。`--page-index` 是数据库保存的零基索引，`0` 对应源站 P1；它仅能与 `--bvid` 一起使用。选择多个 BVID 时，同一个索引用于每个视频，任何一个视频缺少该 P 都使整个请求失败。

未指定索引时，每个 BVID 选择所有仍可处理的分 P，并在摘要中列出已标记 `gone` 的排除项。显式指定的 part ID 或 BVID/index 如果为 `gone`，会报错。未知 BVID、没有存储 parts 的视频、全部 parts 都为 `gone` 的视频以及不存在的 BVID/index 都有明确诊断。一个请求内的选择错误会一并报告；发现这些错误后，不创建 ASR profile 或 jobs。

计划摘要逐项显示 `bvid`、`page_index`、`video_part_id` 和 `work_id`，稳定按 BVID、page index 和内部 ID 排序。重复输入先去重；相同选择再次规划仍显示相同目标，新建 job 计数为零。

目标解析后，沿用原有规划器的 ASR profile、`all` / `selected` / `below-threshold` 策略及 `--proofread` 依赖。`below-threshold` 仍要求 `--quality-threshold` 为 0 到 1 之间的值，并依据已存储的质量评估决定是否创建 audio/ASR 及后续校对任务。BVID 选择不会改变字幕采集与 ASR 的独立关系。
