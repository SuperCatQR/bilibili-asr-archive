# 来源身份与采集适配边界

本文描述当前工作分支的实现；最终提交与验证范围以架构索引为准。

来源身份、平台网络适配、采集策略、数据库持久化和任务调度分别由独立模块负责。
默认新建库继续采用 `bilibili-v1`；显式 `archive init` 或保真迁移创建 `universal-v2`，
后者支持 Bilibili 与单个 YouTube 视频。旧 Bilibili 工作 ID、文件 stem、冻结输入、
稿件内容与渲染版本保持原契约，新能力使用明确的新版本。

## 身份

`platform_identity.ContentRef(platform, external_video_id, part_index=0)` 是不可变应用类型。
`platform` 是显式小写 adapter key；外部 ID 保留大小写与原值，不当作文件路径。
`part_index` 从 0 开始；工作流和仓库继续使用内部 `video_part_id`。
通用身份不携带 `bvid`、`cid` 或凭据，不为其他平台伪造 Bilibili 字段。

`PageIdentity`、`VideoSummary` 和 `VideoPart` 提供只读 `content_ref` 属性。
属性不属于 dataclass 字段，`asdict()`、旧 JSON、摘要输入和文件 key 保持原样。
旧 `PageIdentity.work_id` 仍为 `{bvid}:p{page_index}`，stem 仍为 `{bvid}.p{page_index}`。

`source_identity` 为已注册平台提供 URL、显示工作 ID 和安全文件 stem。
YouTube 以真实 11 字符 video ID 和唯一零基处理单元表示，章节与 playlist 不转换成分 P。
其文件 stem 使用平台名和 ID 的 SHA-256，不将原始外部 ID 直接拼接为路径。
`SourceRepository.part()` 返回统一的 `ContentRef` 与内部 part ID；YouTube 的 `bvid/cid`
为 NULL。默认 Bilibili 表及固定旧源 reader 不接受这些通用记录。

顶层纯 `bilibili_identity.legacy_bilibili_source_ref` 严格读取旧 `publish-v1` 的
`bvid/pageIndex/videoPartId/url` 对象，返回用于校验和调用的 `ContentRef`。
它不修改输入，不允许额外的 `platform` 字段，也不能被用于替换旧内容的哈希输入。
`bilibili_source_url` 保留既有 `https://www.bilibili.com/video/{bvid}/?p=N` URL 形状。
`sources.bilibili_identity` 保留普通再导出；稿件纯规则直接依赖顶层 codec，
不通过来源包初始化 gateway 或 adapter。

## 来源接口

`sources/protocols.py` 定义三个应用自有端口：

| 接口 | 输入与返回 | 职责 |
| --- | --- | --- |
| `MetadataSource.get_parts` | `ContentRef` -> 具有 `content_ref/title/duration_ms` 的处理单元 | 读取视频真实处理单元；作者发现和分页仍是独立的平台操作 |
| `SubtitleSource.list_tracks/read_body` | `ContentRef`、`SubtitleTrack` -> 轨道清单、`SubtitleBodyRead` | 保留有效正文、合法空正文与正文不可读的差别；不负责候选排序或转录版本 |
| `SubtitleSource.fetch_segments` | `ContentRef`、`SubtitleTrack` -> 非空毫秒字幕行 | 兼容已有严格正文读取；不可用正文保留有界异常 |
| `SubtitleSource.verify_access` | `ContentRef` -> `SourceAccessObservation` | 给出匿名/credentialed 上下文与验证结果；不直接决定 ASR 资格 |
| `AudioSource.download_audio` | `ContentRef`、目标路径与暂存根 -> 实际文件路径 | 在调用方的暂存范围内下载；允许实际保留 `.flac` 后缀 |

端口不返回签名媒体 URL、cookies 或原始第三方字典，不调度任务、不写数据库。
音频 handler 继续负责探测、流式 hash、取消/租约检查、最终安装和登记。
下载器中的路径约束与现有安全安装机制继续生效。

## 当前 Bilibili 接入

`sources/bilibili_source.py` 中的三个 adapter 包装现有 gateway/client。
metadata adapter 保留 `VideoPart` 的真实 `cid` 扩展；`MetadataIngestor` 经 `get_parts` 调用它。
subtitle adapter 通过注入的 `ContentRef -> cid` 解析器获取真实 ID，audio adapter 通过
`ContentRef -> PageIdentity` 解析器获取当前分 P 身份。错误平台、未知分 P、非法 cid 或不匹配身份会在网络调用前拒绝。

`ArchiveWorkflowHandlers.audio` 已调用 `BilibiliAudioSource`。handler 在探测前验证返回文件位于
本次暂存 `audio/`、stem 对应当前分 P 且后缀为 `.m4a/.flac`，拒绝越界和符号链接。
`artifact_inventory.stream_hash` 以固定块大小累计字节数与 SHA-256，不把完整音频读入内存。

`SubtitleIngestor` 支持显式 `source=`；原有 gateway 注入继续可用，通过已读取的分 P 行建立适配器，
不会为每次网络调用新增 SQL 查询。选轨、逐 part 事务和 bounded error 映射保留在应用服务。
匿名访问观察即使被验证，也不会写成 Bilibili `credential_verified=1`。
配置了 cookie 但登录验证失败时，仍记录失败，不能生成可信的空字幕清单。
轨道清单的明确 `not_found` 与正文消失保持不同证据语义。

`SubtitleBodyRead` 显式记录规范化 segments、原始行数与 `empty_body/empty_text`。
`subtitle_policy.rank_candidates()` 根据语言偏好、family、CC/AI 和上游顺序排列候选；
`SubtitleIngestor` 在默认 32 个候选、120 秒总正文预算内逐项读取。
合法空正文继续下一个候选；可替代的 shape/transport/正文消失允许探测其他候选，
找到有效正文即可存储。auth/rate control 立即停止，超时、预算耗尽或尚存读取不确定性
保留失败。所有候选确定合法为空时记录 `no-subtitle`、error=NULL、两个验证标志均为 0，
workflow attempt 额外保存 `visible_candidates_exhausted` 与安全候选诊断。
这不会扩充旧 `v_missing_audio` 的可信缺失条件。ASR 的 `all/selected` 图仍只依赖 audio；
需要该 fallback 时必须提供 ASR profile，`below-threshold` 对未知质量分数不会自动计划 ASR。

元数据 gateway 的 `get_video_metadata()` 返回 `VideoMetadataRead`，将 summary、逐字段
`MetadataFieldObservation` 与可复用 view pages 一并交付；仅在 pages 缺失时补 pagelist。
`read_video_tags()` 返回 `TagRead`，错误类别随当前调用返回。旧 `get_video_tags()` 与
`tag_error_code` 仅保留兼容，正式服务不通过共享可变属性读取错误。
`MetadataRefreshPolicy` 负责 new/missing/stale/force 判断；仓库负责当前事实、观察与页事务，
来源适配器不自行决定刷新、覆盖或失败补抓。

`RequestScheduler` 在一个协调器内对 gateway 操作计数、串行化、设置单次超时和总预算，
并共享 rate-control 冷却。它计量应用 gateway 操作，而非 SDK 内部每次 HTTP 子请求，
也不协调其他进程的请求。SDK 的进程全局 proxy 仅在请求期间设置，使用可取消等待的
线程锁协调不同 event loop/线程，退出、异常和取消都恢复原值；构造 gateway 不修改全局设置。

## 来源元数据与冻结内容

纯 `SourceMetadataSnapshot` 使用 `source-metadata-v1` 结构，包含真实来源身份、视频/分 P
标题、作者、原始 Unix 发布时间、派生 UTC RFC3339 时间、观察时间、简介、封面、分区、
标签与可用的 aid/时长。未知时间保持 NULL 或原始 0，派生时间为 NULL，不推测为 1970 年。
封面仅允许无参数和凭据的 HTTPS Bilibili 公共图片域；文本、数值、标签数量与重复项均校验。
YouTube 尚未建模的封面、简介、分区与 tags 保持未知。

`MetadataRepository.read_source_metadata(part_id)` 是当前可变事实的单条读取接口；
`read_source_metadata_many(part_ids)` 一次最多接受 256 个 part ID，用集合查询读取来源、
作者与 Bilibili 详情，再按视频集合读取标签。混合平台投影每批调用一次该方法，
没有逐 part 的 SQL；任何未归档 ID 都使整次批读取失败。v1 投影继续使用旧字段和读取路径。
新稿件内容 v2 将该对象放进 `source.metadata`，其作者、发布时间等随 edition/hash 冻结；
之后刷新源元数据不改旧 edition、审核或 release。旧内容与渲染 v1 不增加字段、不重算 hash。

`error_codes.validate_error_code` 是来源和仓库共享的纯错误代码约束。
原 `storage.models.validate_error_code` 保留为同一函数的再导出；加载来源 DTO 与 Protocol
不再触发 SQLite 仓库和工作流模块初始化。

## 运行时组合

`workflow_runtime_ports.py` 描述 gateway、音频 client、当前进程 runner 和超时推理调用的类型。
`ArchiveWorkflowHandlers` 接受 `gateway_factory`、`audio_client_factory`、`runner_factory`
和 `timeout_transcriber`，并支持显式 `inference_session` 与 runtime binding resolver。
CPU runner 按冻结 profile 与实际 runtime binding 缓存并在 `close()` 释放；GPU 可选 legacy、
oneshot 或 persistent session，session 子进程只负责推理，父进程继续负责租约、取消、
音频/转录写入与发布。当前进程 runner factory 不跨进程传递，详见 [ASR workers](asr-workers.md)。

ASR 公共包通过普通函数提供 `asr.transcribe()` 与 `asr.provenance()`。
两者支持显式 `runner_factory`，未显式注入时使用公开包当前的 `ASRRunner`，因此原有
`asr.ASRRunner` 测试替换仍进入实际调用，但不再通过 ModuleType 写入另一个模块。
`asr.provenance` 子模块只保存语言、脱敏和证据规则，依赖方向为 `runner -> provenance`；
读取子模块函数可使用 `from bili_asr.asr.provenance import ...`。

## YouTube 与显式通用归档

`source import --youtube ID_OR_URL` 只接收单个允许的 YouTube 视频 URL/ID，并要求已显式创建的
`universal-v2` 归档。`SourceRegistry` 静态组合 adapter，`SourceWorkflowHandlers` 按真实平台
分发字幕/音频，ASR 与 publication 继续使用现有工作流和权威结果事务。
YouTube adapter 使用锁定的 yt-dlp/EJS 子进程、受控输出、超时、取消与暂存边界；
`source doctor` 只检查本机依赖，不安装、不发网络请求。

从 checkout 安装时使用锁文件选中的可选依赖：

```sh
uv sync --locked --extra youtube
bili-asr source doctor
bili-asr archive init --target-root universal-archive
bili-asr source import --archive-root universal-archive --youtube aBcdEfGhIjK
# 使用 import 返回的内部 part ID 规划任务
bili-asr workflow plan --archive-root universal-archive --part-id 1
bili-asr workflow run --archive-root universal-archive --role acquisition
```

`youtube` extra 固定 `yt-dlp[default]==2026.8.19` 与 `yt-dlp-ejs==0.8.0`；
独立安装的 Deno 必须为 2.3.0 或更新版本，`ffmpeg/ffprobe` 也须在 PATH。
Node 的存在不能代替该 adapter 当前声明的 Deno 要求。doctor 返回 `ready=false` 时退出 1；
版本不符不会自动升级或绕过检查。下载进程禁用外部配置、自动更新、远程 JS component
和 download-archive ledger，原始响应、签名 URL 和私有 cookies 留在 adapter 内。
`source import --cookies FILE` 的显式 Netscape 文件优先于当前运行环境。
后续 worker 如需受限内容访问，由操作者重新设置 `BILI_YOUTUBE_COOKIES` 为私有 Netscape
cookie 文件路径；registry 在运行时读取，路径与内容不进入来源 metadata、job payload 或结果。
未配置时使用匿名访问。import 成功或本地 doctor 通过不能证明后续账号授权有效。

YouTube 发布时间只接受 extractor 提供的合法精确 `release_timestamp` 或 `timestamp`；
前者缺失或非法时尝试后者。只有 `upload_date` 的来源时间显示未知，不推断 UTC 午夜秒值。

YouTube 字幕有单独的 `youtube-public-v1` 观察与候选策略，保留原语言、翻译状态和
json3 规范化 provenance。正文使用 `read_body` 明确区分非空与合法空数据，兼容
`fetch_segments` 只是该读取的包装；handler 遍历候选，有成功正文才存转录。
候选有正文不可用或全部合法为空时记录 unavailable，而可信空轨道列表使用专属
`youtube-public-v1` 观察。匿名可见性、没有轨道与正文不可用分别记录，不能借用
Bilibili 已认证空列表规则。通过离线测试不表示当前 YouTube 网络、账号或 JS runtime 已实测可用。

通用目标新增真实 `source_creators/source_videos` 及 platform observations；旧源保持固定契约。
`archive migrate` 从只读旧源向独立空目标转换并校验，旧冻结 JSON、审核、release、
转录与文件字节的保留不依赖新 reader 重写旧内容。原设计背景见
[多平台接入与旧归档保真迁移方案](multi-platform-architecture-plan.md)，实际操作以当前迁移指南为准。
