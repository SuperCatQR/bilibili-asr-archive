# DeepSeek AI 校对使用说明

当前阅读稿版通过 DeepSeek 官方 API 的 `deepseek-flash` 模型处理固定的数据库转录版本。
AI 返回带来源 ID 的完整阅读段落，程序校验后保存独立修订，生成中文 Markdown 阅读稿和校对记录。
业务进度保存在 SQLite；工作器重启后读取固定输入与已有块结果继续执行。

## 运行前提

- Python 3.12+ 与项目基础依赖。仅运行校对和文档渲染不需要 GPU、ASR 模型或 ffmpeg。
- 归档数据库已存储基础转录。默认使用所选视频部分最新的本地 ASR 版本。
- 新建数据库使用包含 `proofread` / `render_document` 的工作流表结构。
- 真实校对需要环境变量 `DEEPSEEK_API_KEY`。密钥仅进入 HTTP Authorization，不写入模型请求快照、结果或文档。

本次不提供旧工作流表的迁移。若旧 `workflow_jobs` 的类型约束不支持校对任务，计划会明确报错，
需要重新建立归档数据库；程序不会自动删除、重建或迁移现有库。仅重新安装 Python 包不能修改旧表约束。

## 处理已有转录

以下 Linux / WSL 示例中的 `101` 是数据库 `video_part_id`，不是视频 BV 号。
在安全的运行环境设置密钥后执行：

```bash
bili-asr workflow proofread --archive-root /srv/bili-archive --part-id 101
bili-asr workflow run --archive-root /srv/bili-archive --only-editorial
bili-asr workflow status --archive-root /srv/bili-archive
```

可以用 Python 查询视频部分 ID 和已经存储的转录 ID：

```python
import sqlite3

with sqlite3.connect('/srv/bili-archive/archive.db') as db:
    print(db.execute('''
        SELECT p.video_part_id, p.bvid, p.page_index, t.transcript_id,
               t.source_kind, t.language, t.version
        FROM video_parts AS p
        JOIN transcripts AS t ON t.video_part_id = p.video_part_id
        WHERE p.bvid = ?
        ORDER BY p.page_index, t.transcript_id
    ''', ('BV1o24y157iQ',)).fetchall())
```

`proofread` 在计划时固定基础转录、当时可用的字幕、视频标题、模型参数和提示词。
后续出现新的转录或标题变化，不会替换已有任务的输入。参考字幕优先 CC，再选 AI 字幕。
匹配时识别 `Chinese`、`ai-zh`、`zh-CN`、`zh-Hans` 等同类语言标签，原始标签仍保留在快照中。

明确指定转录版本或不用参考字幕：

```bash
bili-asr workflow proofread --archive-root /srv/bili-archive \
  --base-transcript-id 201 --reference-transcript-id 202

bili-asr workflow proofread --archive-root /srv/bili-archive \
  --base-transcript-id 201 --no-reference
```

显式基础 ID 也允许选择原始字幕版本；默认 `--part-id` 路径要求已有 ASR。
参考转录必须是同一视频部分和兼容语言的字幕，不能引用另一视频的字幕。
相同固定输入与配置重复计划会命中已有任务。修改输入版本或配置会产生新的输入标识。

## 接入采集与 ASR 主链路

```bash
bili-asr workflow plan --archive-root /srv/bili-archive --part-id 101 \
  --asr-policy all --proofread \
  --model /srv/models/Qwen3-ASR-1.7B-hf \
  --aligner /srv/models/Qwen3-ForcedAligner-0.6B-hf
bili-asr workflow run --archive-root /srv/bili-archive
```

任务依赖为 `audio → asr → proofread → render_document`。字幕采集独立运行，
字幕失败不会阻止 ASR 或校对。自动校对固定其 ASR 前置任务成功返回的准确 `transcript_id`，
在首次执行时取已有字幕并冻结；重试不会切换为最新 ASR 或后续到达的字幕。
原始转录发布继续独立执行，不等待校对。

## 大块预算

官方模型文档列出 1M 上下文和 384K 最大输出，代码使用以下上限和默认值：

| 参数 | 默认值 | 作用 |
| --- | ---: | --- |
| `--reasoning-effort` | `high` | 开启思考；可选 low / high / max |
| `--top-p` | 0.95 | 思考模式有效范围 0.95–1.0 |
| `--editorial-model` | `deepseek-flash` | API 模型标识 |
| `--context-tokens` | 1,048,576 | 总上下文预算 |
| `--max-input-tokens` | 480,000 | 提示词、基础文字、参考字幕和只读上下文的预算 |
| `--max-output-tokens` | 262,144 | 修订输出预留；不可超过 393,216 |
| `--context-segments` | 2 | 每块前后各保留的只读基础片段数 |
| `--api-timeout` | 1,800 秒 | HTTP 读取超时；每次请求前续租任务 |

另预留 16,384 token 的安全空间。当前没有依赖供应商 tokenizer，使用 UTF-8 字节数作为保守
输入估算，同时预留思考、完整段落、来源 ID 和疑点输出长度。它通常会高估文本 token 数，不代表实际计费用量。
实际供应商用量来自响应的 `usage`，保存在调用记录中。

每块尽量包含最多的完整原始片段。可容纳的整篇转录会保持为单块；输出预算不足时仍需分块，
因为 1M 输入上下文不能保证全文修订输出也能装下。参考字幕按片段时间交集匹配；
基础片段恰好归属一个块，邻块上下文只读，未匹配参考字幕记录到校对记录。
单个原始片段超过预算时明确失败，不截断文字。

```bash
bili-asr workflow proofread --archive-root /srv/bili-archive --part-id 101 \
  --max-input-tokens 600000 --max-output-tokens 393216
```

服务返回 `finish_reason=length`、空内容、无效 JSON、重复 JSON 字段、未知片段、漏段、乱序、
正文混入标题或时间戳、非相邻来源或未知引用时，任务失败并保留调用证据，不提交完整修订或阅读稿。
请求采用 JSON object 模式，默认 `thinking={"type":"enabled","reasoning_effort":"high"}`，
`top_p=0.95`，不发送 temperature，无隐式 HTTP 自动重试。
官方接口在 high 思考模式下将小于 0.95 的 top_p 按 0.95 处理；本地配置直接拒绝无效范围。

官方参考：[模型规格](https://api-docs.deepseek.com/quick_start/pricing/)、
[Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)、
[JSON 模式](https://api-docs.deepseek.com/guides/json_mode/)。

## 修订与文档

当前规则 `readable-prose-v2` 的目标是让转录可阅读，语句和局部论述关系通顺。
允许删除无意义填充词、口吃重复和半句重启，合并相邻字幕，恢复跨段切开的词，
补齐标点、调整局部语序。保留原话的观点、例子、论据、强调、因果与转折；不生成摘要或扩写。
参考字幕只作证据，不假定一定比 ASR 正确。数字、专名、否定、立场等实质疑点不得猜改。
疑点另存 `issues`，不回退整段为原始口语，周围语句继续整理。
无独立信息的半句重启和未说完插话移入校对记录，正文续接完整意思；不凭空补齐实质内容。

模型输出结构：

```json
{"chunk_id":"输入中的块ID","paragraphs":[
  {"segment_ids":["t2:s0","t2:s1"],"text":"完整、通顺的正文段落。","issues":[]}
]}
```

每个段落关联连续基础片段，所有可编辑片段按顺序出现且恰好一次。程序验证来源覆盖和引用，
不能仅凭结构校验判断语义准确。保存的段落同时包含程序取得的原文和时间范围，供独立审核。
每个输入片段提供 `allowed_issue_refs`，列出本片段及相交参考字幕；段落疑点只能引用其合并片段
允许 ID 的并集。无关引用会失败，不会被程序静默替换成其他证据。

产物路径：

```text
<archive-root>/documents/part-<video_part_id>/<revision_id>/reading-v2/
  reading.md
  review.md
```

`reading.md` 只有整理后的正文段落，不含视频标题、话题标题、目录、时间戳、脚注或审核说明。
`review.md` 保存模型思考和采样参数、固定输入、每段全部来源 ID、原文与整理稿对照、
时间范围、回看链接、疑点和未匹配参考字幕，并注明未经人工复核。
源文本按字面转义，不能把字幕中的 HTML 或链接指令直接变成文档行为。
旧规则和旧模板不兼容；需要按当前规则创建新的固定输入和修订，不能把旧结果冒充新稿。

## 失败重试与重新渲染

```bash
bili-asr workflow retry --archive-root /srv/bili-archive --part-id 101
bili-asr workflow run --archive-root /srv/bili-archive --only-editorial
```

每个通过校验的块立即保存。进程重启、超时或模型响应无效后，重试复用已保存块，
只重新请求尚未通过校验的块。全部块完成后才提交完整修订和解锁渲染任务。
如果请求已到达供应商，但本地尚未保存结果时进程退出，重试可能重复计费；不承诺外部调用 exactly-once。
租约续期和尝试编号校验阻止过期工作器提交新块或覆盖新的任务尝试。

读取成功校对尝试的 `result_json`，或查询 `editorial_revisions`，取得 `revision_id` 后：

```bash
bili-asr workflow render --archive-root /srv/bili-archive --revision-id <revision_id>
bili-asr workflow run --archive-root /srv/bili-archive --only-editorial
```

重渲染不需要 API 密钥，不调用模型，可修复已删除的 Markdown。
相同已保存修订和 `reading-v2` 模板生成相同字节；模板内容改变时需要新的模板版本和实现，
当前只支持 `reading-v2`。文件通过临时文件、fsync 和原子替换写入，数据库记录路径及 SHA-256。

## 数据与离线验证

| 表 | 内容 |
| --- | --- |
| `editorial_inputs` | 完整固定输入、来源 ID、配置、提示词正文与散列、分块及引用 |
| `editorial_job_inputs` | 工作流任务与固定输入的绑定 |
| `editorial_model_calls` | 所属工作流尝试、请求、实际响应、用量、错误码和时间 |
| `editorial_chunk_results` | 每个块通过校验后的完整段落、来源 ID、原文和疑点 JSON |
| `editorial_revisions` | 全部块的完整修订、内容标识、`ai-unreviewed` / `needs-review` 质量状态 |
| `document_artifacts` | 修订、模板、文件路径和散列 |

没有另建调度器；任务和终态仍归属于 `workflow_jobs` / `workflow_attempts`。
段落和块信息保存在结构化 JSON 中，当前实现不额外建 `editorial_changes` / `editorial_blocks` 表。

```bash
python -m pytest tests/test_ai_editorial.py tests/test_workflow_control_plane.py -q
```

测试使用合成转录、模拟模型和被拦截的 HTTP 响应，不连接 DeepSeek 或 B站，不需要 API 密钥。
覆盖输入固定、上下文和输出预算、语言标签、结构校验、识别疑点、HTTP 失败、逐块恢复、
ASR 独立依赖、租约、Markdown 转义及字节一致的重新渲染。
当前离线验证覆盖跨段成句、疑点不回退正文、来源覆盖与只读上下文边界、纯正文输出，
以及 high 思考和 top_p 参数的请求与快照。离线测试不连接 DeepSeek 或 B 站；
真实素材的人工回听和逐句准确率评估仍需单独记录，不能把结构校验当作语义质量结论。
