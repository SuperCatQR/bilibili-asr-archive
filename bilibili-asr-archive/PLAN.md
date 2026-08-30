# 未明子（UID 23191782）视频 ASR 转录归档计划

> 目标：UP主全部投稿（当前可见 1737 条）→ 文字稿 + 字幕，本地归档，支持检索。
> 状态：元数据历史进度 474/1737（412 风控中断，可 `--resume` 续跑）；顺序工具链、受控 campaign、覆盖率/质量/完整性证据、检索导出与并发安全门均已交付，尚未声称完成全量语料生产。目录 `C:\WorkSpace\wmz\bilibili-asr-archive\`。

## 0. 已勘察事实

| 项 | 数据 |
|---|---|
| UP主 | 未明子，粉丝 ~63 万 |
| 投稿数 | 1737（API `x/series/recArchivesByKeywords`，2026-06 时点） |
| 已拉取 | 474 条 / 521h（2023:64 / 2024:194 / 2025:141 / 2026:75），正在翻页中 |
| 内容形态 | 直播回放（3~6h/条）、哲学课系列（1~5h）、短杂谈（几分钟） |
| 本机 | 16 核 CPU / 203GB 可用 / Python 3.12 / ffmpeg 8.1 / 无 N 卡 |
| 风控 | 无 cookie 直连 `recArchivesByKeywords` 必 412；主页 warmup 拿 buvid3 后可用，但约每 4-5 页弹一次 412，重试+warmup 可过 |

## 1. 已有成品调研（避免重复造轮子）

| 成品 | 覆盖 | 结论 |
|---|---|---|
| 知乎「主义主义转文字合集」（金山文档） | 仅【主义主义】系列，无校对 | **不满足**「全部视频」需求，但可作特定系列交叉校对参考 |
| 主义主义魔方 ismismtag.com | 教理结构化摘要 | 非逐字稿，不替代 |
| GitHub / 各社区 | 未见「未明子全量转录归档」项目 | **确认空白，需自建** |

## 2. 工具选型（对比矩阵）

> API 文档参考：`references/bilibili-API-collect/`（原仓库 SocialSisterYi/bilibili-API-collect 已于 2026-01 收 B 站律师函归档停更，使用社区 fork pskdje/bilibili-API-collect 的镜像文档）
> 成熟封装库备选：nemo2011/bilibili-api（Python，自带 WBI 签名/登录态/curl_cffi TLS 伪装，可根治 412）

### 关键 API 结论（已核对文档）

| 环节 | API | 要点 |
|---|---|---|
| 投稿列表 | `x/series/recArchivesByKeywords` | 无需 wbi；无 cookie 必 412，warmup 拿 buvid3 后可用（已实测） |
| 视频详情/cid | `x/web-interface/view` | bvid → cid（多P取 pages） |
| **字幕列表** | `x/player/wbi/v2` | `subtitle.subtitles[]`；**不登录为空数组 → AI 字幕必须登录态** |
| 字幕下载 | `aisubtitle.hdslb.com/...json` | subtitle_url 直接 GET（//开头需补https:） |
| 音频流 | `x/player/wbi/playurl` | DASH `dash.audio[]` 30216=64K；WBI 签名+SESSDATA；拉流需 Referer+UA 防 403 |
| buvid | `x/frontend/finger/spi` | 正规获取 buvid3/4，替代主页 warmup |
| 错误码 | -412=IP风控 / -352=UA或wbi不合法 / -799=频率 | 退避策略依据 |

### 2.1 B站批量下载

| 工具 | 音频only | 字幕 | 空间批量 | 断点/续传 | 结论 |
|---|---|---|---|---|---|
| **yutto** | `--audio-only` | `--download-subtitle`（AI字幕） | `space.bilibili.com/{mid}` 整空间 | ✅ 跳过已存在 | **主力** |
| BBDown | `-tv` 选音频流 | `--sub-only` | 支持 | ✅ | 备用；其 nightly 是字幕工具链的底层 |
| yt-dlp | `-x` | 支持 | 空间分页不稳 | ✅ | 备用 |
| **自写薄脚本**（requests + 上述API） | ✅ dash.audio | ✅ player/wbi/v2 | ✅ 走 manifest | ✅ | 兜底，不依赖第三方工具更新 |

### 2.2 B站字幕抓取（优先于 ASR，能省则省）

| 工具 | 形态 | 特点 |
|---|---|---|
| **yutto 内置**（player/wbi/v2 → subtitle JSON） | CLI | 与下载管线一体，自写脚本亦可 |
| SubBatch / BiliSubGet | Chrome 扩展 | 页面级批量，适合手工补少量 |
| 油猴「B站字幕提取器」 | 脚本 | 合集批量、10 种格式 |
| video-captions / bilisub / bilibili-subtitle-fetch | Python CLI | 无字幕时自动回退本地 ASR（Whisper），思路同本计划 |

### 2.3 ASR 引擎（CPU 环境）

| 模型 | 中文CER | CPU 速度 | 备注 |
|---|---|---|---|
| **SenseVoice-Small（首选）** | 7.81% | **17x 实时** | 非自回归，自带标点/ITN；GGUF + llama.cpp 8线程 ~20x |
| Paraformer-Large | 10.18% | 15x | 热词增强可选，成熟稳定 |
| faster-whisper large-v3 | ~8% | ~2-5x | 慢 5-10 倍，CPU 上不划算 |

**结论：SenseVoice-Small（FunASR / GGUF）**。2200h / 17x / 16核并行 → 数天量级，纯 CPU 可行，无需云 GPU。

## 3. 流水线设计

```
manifest.jsonl (账本, bvid为主键)
  │
  ├─① 字幕探测: player/wbi/v2 → subtitle list
  │    有 → 抓JSON字幕 → 统一为 {bvid}.srt/.txt/.md     [零ASR成本]
  │    无 → ②
  │
  ├─② 音频下载: yutto --audio-only（登录态, 限速, 分批）
  │    → audio/{bvid}.m4a（64kbps 音轨 ≈ 60-80GB）
  │
  ├─③ ASR: ffmpeg 16k单声道切片 → SenseVoice-Small
  │    → transcripts/raw/{bvid}.json（带时间戳）
  │
  ├─④ 后处理: srt / txt / md（{date}_{bvid}_{title}.md, 头部含元数据）
  │
  └─⑤ 归档账本: 状态机 pending→sub_checked→done / asr_done
       检索: SQLite FTS5 / Meilisearch（可选）
```

## 4. 成本与工期（按 1737 条 / ~2200h 计）

| 项 | 估算 |
|---|---|
| 存储 | 字幕覆盖部分音频可不存；无字幕音频 60~80GB；文本 <1GB |
| 字幕下载 | 3~7 天（限速后台跑） |
| 音频下载（无字幕部分） | 与字幕探测同步，2~4 周 |
| ASR（CPU 17x, 16核分片并行） | 数天（按字幕覆盖率打折） |
| 总花费 | ~¥0（可选云GPU加速约 ¥100-300） |

## 4b. 风险与合规

- **风控**：全部请求挂登录态（SESSDATA），限速 1~3s/req，412 退避重试已验证有效。建议小号。
- **可见性**：1737 为当前可见数；历史删稿/自见不可恢复，属硬边界。
- **合规**：个人研究存档、不公开传播；文字稿同。
- **品质**：AI字幕与ASR均无校对；哲学黑话（「场域」「齐泽克」等）需热词表或后期LLM校对。

## 5. 里程碑

| # | 里程碑 | 状态 | 完成判据 / 当前证据 |
|---|---|---|---|
| M0 | 元数据全量 | 待交付 | 仍需在授权环境继续受控枚举；只有明确 manifest 分母达到当期可见语料快照时才完成，不从历史 1737 或有限批次推断。 |
| M1 | 字幕覆盖率摸底 | 待交付 | `coverage --quality` 已交付，但仍需对完整、明确分母的语料快照执行后才能得到真实全量覆盖率。 |
| M2 | 试点 20 条 | 已交付（工程验证） | 既有 Windows WSL N=5/N=20 分阶段证据和长视频受控路径已验证字幕与 ASR 分支、预算跳过、归档及音频回收。 |
| M3 | 全量执行 | 待交付 | 受控 `campaign`、coverage、quality、verify/recovery-audit 已交付；仍需真实顺序批次、显式风险边界和最终缺失清单。 |
| M4 | 检索 | 已交付 | SQLite FTS5 搜索、过滤、重建诊断和稳定 JSON/CSV 导出已交付；manifest 仍为 SSOT。 |

## 5a. 当前 roadmap 位置

`iter-2026-08-corpus-coverage` 已 **delivered**：它交付的是可审计的顺序生产与证据骨架，而不是全量语料完成声明。当前生产模式保持 `sequential-no-daemon`。完整性 `recover` 仅记录最多 100 个当前权威缺陷候选的脱敏审计，不重排任务或改写状态；并发门即使返回 `go` 也只为后续独立批准计划提供证据。

## 6. 下一迭代触发条件

下一迭代应是**授权环境中的测量型顺序语料生产**，owner 为 operator + project manager，满足以下条件后开始：

1. 操作者在本机重新提供有效登录态；值只进入环境变量 `BILI_SESSDATA` 或命令行参数，不写入仓库、证据或日志。
2. 明确 Windows WSL archive root、可用存储、顺序批次上限、请求节奏和允许的风险停止边界。
3. 先继续元数据枚举并建立明确分母，再运行小批次 campaign；每批用 coverage/quality/verify 对账，保留 `limited`、`risk_interrupted` 和缺失清单，不把批次完成当作语料完成。
4. 只有积累了满足显式阈值的 campaign/reconciliation/recovery/ownership/isolation 证据、并发门返回 `go`，且另有批准的实现计划时，才讨论并发模式。当前不增加 daemon、service、自动启动或并发 manifest writer。
5. 说话人分离、语义纠错和公开服务继续延后，除非用户单独批准范围与成本。
