# 来源身份与采集适配边界

源码基线：`5d7a57e201564a10dec7a360b2ef8f7874dc51a7`。

本次引入运行时 `ContentRef` 与来源 Protocol，现有归档仍使用 Bilibili schema。
这是来源调用边界的重构：不改变数据库结构、旧 `work_id`、文件 stem、冻结输入、稿件内容或导出版本。
当前没有 YouTube adapter，也没有可接收其他平台记录的新版归档。

## 身份

`platform_identity.ContentRef(platform, external_video_id, part_index=0)` 是不可变应用类型。
`platform` 是显式小写 adapter key；外部 ID 保留大小写与原值，不当作文件路径。
`part_index` 从 0 开始；工作流和仓库继续使用内部 `video_part_id`。
通用身份不携带 `bvid`、`cid` 或凭据，不为其他平台伪造 Bilibili 字段。

`PageIdentity`、`VideoSummary` 和 `VideoPart` 提供只读 `content_ref` 属性。
属性不属于 dataclass 字段，`asdict()`、旧 JSON、摘要输入和文件 key 保持原样。
旧 `PageIdentity.work_id` 仍为 `{bvid}:p{page_index}`，stem 仍为 `{bvid}.p{page_index}`。

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
| `SubtitleSource.list_tracks/fetch_segments` | `ContentRef`、`SubtitleTrack` -> 轨道清单、毫秒字幕行 | 平台 ID 解析、认证和规范化响应；不负责选轨或转录版本 |
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

`error_codes.validate_error_code` 是来源和仓库共享的纯错误代码约束。
原 `storage.models.validate_error_code` 保留为同一函数的再导出；加载来源 DTO 与 Protocol
不再触发 SQLite 仓库和工作流模块初始化。

## 运行时组合

`workflow_runtime_ports.py` 描述 gateway、音频 client、当前进程 runner 和超时推理调用的类型。
`ArchiveWorkflowHandlers` 接受 `gateway_factory`、`audio_client_factory`、`runner_factory`
和 `timeout_transcriber`，默认组合保持现有生产实现。
CPU runner 按冻结 profile ID 缓存并在 `close()` 释放；GPU 使用独立 `timeout_transcriber`
端口，默认仍启动可终止的子进程，CPU 的 runner factory 不跨进程传递。

ASR 公共包通过普通函数提供 `asr.transcribe()` 与 `asr.provenance()`。
两者支持显式 `runner_factory`，未显式注入时使用公开包当前的 `ASRRunner`，因此原有
`asr.ASRRunner` 测试替换仍进入实际调用，但不再通过 ModuleType 写入另一个模块。
`asr.provenance` 子模块只保存语言、脱敏和证据规则，依赖方向为 `runner -> provenance`；
读取子模块函数可使用 `from bili_asr.asr.provenance import ...`。

## 第二个平台的前提

新的 adapter 可以实现相同端口，但当前 Bilibili 仓库与 `publish-v1` reader 会拒绝不同契约。
实际多平台接入仍需要独立、版本明确的 schema、平台扩展、来源观察策略、文件身份和内容契约，
并使用只读源 reader 与向独立目标写入的保真转换流程。
详见 [多平台接入与旧归档保真迁移方案](multi-platform-architecture-plan.md)。
