# BV16jryYNEbT 完整链路实测

测试日期：2026-10-06。

视频：【好自为之】富人们应该怎样兜底性地押宝中国经济；长度 1035 秒；分 P 数 1。

链路：视频元数据 → 独立采集 B 站 AI 字幕和音频 → 本地 Qwen3-ASR → DeepSeek 校对 → Markdown 渲染。

WSL Python 3.12.3；PyTorch 2.14.1+cpu；本次设备为 CPU。
ASR 使用此前从 ModelScope 下载的 Qwen3-ASR-1.7B-hf 和 Qwen3-ForcedAligner-0.6B-hf 本地模型；本次未重新下载模型。

| 阶段 | 结果 |
|---|---|
| subtitle-ai | 451 段，4177 字，版本 1 |
| asr-local | 151 段，4713 字，版本 1 |
| AI 校对 | 1 个输入块 → 29 个阅读段落，5 个疑点 |
| 阅读稿 | 4287 字；只有段落文字 |

校对模型：`deepseek-flash`；思考强度：`high`；`top_p=0.95`。

| 阶段 | 耗时（秒） |
|---|---:|
| subtitle | 0.46 |
| audio | 1.05 |
| asr | 868.79 |
| proofread | 65.04 |
| render_document | 0.01 |
| publish | 0.03 |
| 工作流合计 | 935.42 |

| API 调用 | 输入 token | 输出 token | 推理 token |
|---|---:|---:|---:|
| 1 | 25327 | 15791 | 11948 |

验证项：

- `sqlite_integrity`：通过。
- `foreign_keys`：通过。
- `jobs_succeeded`：通过。
- `asr_coverage`：通过。
- `audio_hash_1`：通过。
- `audio_duration_1`：通过。
- `raw_publications`：通过。
- `both_sources`：通过。
- `asr_bundle`：通过。
- `asr_timeline`：通过。
- `unchanged_base`：通过。
- `unchanged_reference`：通过。
- `source_coverage_5f836587b14b5642c7cff6874989922a01fff19cfd1aab0bc0bfaaeeb87691e2`：通过。
- `documents_present_5f836587b14b5642c7cff6874989922a01fff19cfd1aab0bc0bfaaeeb87691e2`：通过。
- `document_hash_reading.md`：通过。
- `deterministic_reading.md`：通过。
- `plain_reading_body`：通过。
- `document_hash_review.md`：通过。
- `deterministic_review.md`：通过。
- `reading_created`：通过。
- `high_thinking`：通过。
- `top_p`：通过。
- `model_calls_valid`：通过。
- `requests_contain_no_credentials`：通过。

ASR 时间跨度覆盖率：99.8694%；阈值 97%；短覆盖标记 `0`。

空闲恢复验证：成功 0、失败 0、idle=True；未重复采集、转写或请求模型。

正文没有话题标题、时间戳或来源 ID。原始 ASR 和字幕均保留；校对记录包含原文、整理稿、回看时间和疑点。
来源段覆盖与顺序校验通过；这是结构和溯源验证，不能替代语义人工校核。

本次阅读稿仍保留较多“明白吗”“whatever”等口语插话，部分句子仍不够流畅；含混英文、数字或专名需要结合原音确认。结构校验通过不表示文字质量完全达标。

输入快照：`18ef3802ba3032c8da620ee11d5490a2e6ab971a92220608112503426da84f51`。

修订：`5f836587b14b5642c7cff6874989922a01fff19cfd1aab0bc0bfaaeeb87691e2`。

产物：

- [阅读稿](../models/e2e-BV16jryYNEbT/proofreading-review/reading.md)
- [校对记录](../models/e2e-BV16jryYNEbT/proofreading-review/review.md)
- [完整验证数据](../models/e2e-BV16jryYNEbT/verification.json)
- [工作流日志](../models/e2e-BV16jryYNEbT/report.json)

阅读稿开头：

最后一点我要讲的是：如果你有很多钱，是挺有钱的一个人，我还是建议押宝我们国家的发展。钱逃出去，我不是很赞成；变成美元或者什么 whatever，变成欧元逃出去，我不是很赞成。我还是看好中国的发展。但是这个钱，我建议买什么呢？

验证导出脚本首轮因尚未创建 `asr-review` 目录而失败；创建目录后重新验证通过。此问题发生在独立验证脚本，六个工作流任务均首次成功，未重复转写或调用 AI。
