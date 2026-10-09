# 音频来源、流式摘要与受保护登记

源码基线：`5d7a57e201564a10dec7a360b2ef8f7874dc51a7`（架构解耦修复后的代码提交；源码链接采用本地路径）。

[Archify 规格](06-audio-download.json) · [交互时序图](06-audio-download.html) · [全部时序图](../architecture-sequences.md)

## 调用顺序与条件分支

```mermaid
sequenceDiagram
    autonumber
    participant handler as 音频 handler
    participant paths as 文件与路径
    participant source as 音频来源端口
    participant downloader as 安全下载器
    participant cdn as DASH 与 CDN
    participant db as 音频与 lease
    handler->>db: 解码任务、读取真实 part 并 assert_lease
    handler->>paths: 旧 audio/BVID.p零基页.m4a key；拒绝越界、symlink 与非音频对象
    paths-->>handler: 配置产物根优先、archive root 回退；非空 M4A/FLAC
    alt 文件可复用
    handler->>handler: ffprobe 30 秒；duration 有限且大于 0；stream_hash 累计字节与 SHA-256
    else 需要下载
    handler->>handler: audio_client_factory(sessdata) 创建或复用本次 client
    handler->>paths: 最终 audio/ 下创建 .workflow-audio-*，其中保留 audio/ 子目录
    handler->>source: download_audio(ContentRef, target, staging_root)
    source->>source: 解析真实 PageIdentity；平台、引用与 cid 不匹配则拒绝
    source->>downloader: 原有 PageIdentity 与 ArtifactRoots.of(staging_root)
    downloader->>cdn: 通过实际 client 查询 DASH 签名地址并下载
    cdn-->>downloader: descriptor-safe 暂存流式字节；瞬时 URL 不进入归档
    opt 真实 FLAC 且 ffmpeg 不可用
    downloader->>paths: 保留 .flac；不用 .m4a 后缀冒充 FLAC
    end
    downloader-->>source: 实际最终容器路径
    source-->>handler: Path；保留真实 suffix
    handler->>paths: 探测前校验本次 staging/audio、同 stem、M4A/FLAC 与无 symlink
    paths-->>handler: 违规拒绝；只允许本次暂存普通音频文件
    handler->>handler: ffprobe 上限 30 秒；duration 有限且大于 0；stream_hash 不读整文件
    end
    handler->>db: owned_transaction 取得写锁并检查精确 lease
    opt 下载产生新文件
    handler->>paths: os.replace 暂存文件到最终同 suffix 目标
    end
    handler->>db: audio_objects 按 sha256 去重；part_audio_objects 保存 workflow 来源
    db-->>handler: key、hash、duration 成为 ASR prerequisite result
    handler->>paths: TemporaryDirectory 正常/失败均清理；不回收已有音频
```

## 边界与恢复

- ContentRef 只作为运行时来源输入；BilibiliAudioSource 通过真实 PageIdentity 调用现有安全下载器，旧 stem/key 保持原样。
- 探测前拒绝暂存目录外路径、错误后缀、其他分 P stem 和符号链接；真实 FLAC 返回值继续使用 .flac。
- ffprobe、下载和固定块 stream_hash 在 SQLite 写事务外执行；最终文件替换与登记共享租约保护写锁。
- 当前 workflow 无成功后的自动音频删除、keep-audio 或 max-audio-gb 命令参数。复用分支不搬移旧根音频。
- SQLite rollback 无法回滚已替换的文件；inventory/verify/快照校验仍是独立核对机制。

## 源码证据

- [src/bili_asr/workflow_runtime.py:135–159](../../src/bili_asr/workflow_runtime.py#L135)：`ArchiveWorkflowHandlers.audio`。
- [src/bili_asr/workflow_runtime.py:161–172](../../src/bili_asr/workflow_runtime.py#L161)：`ArchiveWorkflowHandlers._download_audio`。
- [src/bili_asr/workflow_runtime.py:174–209](../../src/bili_asr/workflow_runtime.py#L174)：`ArchiveWorkflowHandlers._store_audio`。
- [src/bili_asr/artifact_root.py:369–388](../../src/bili_asr/artifact_root.py#L369)：`usable_audio_path`。
- [src/bili_asr/path_policy.py:101–143](../../src/bili_asr/path_policy.py#L101)：`confined_audio_path`。
- [src/bili_asr/artifact_inventory.py:122–130](../../src/bili_asr/artifact_inventory.py#L122)：`stream_hash`。
- [src/bili_asr/sources/bilibili_source.py:90–118](../../src/bili_asr/sources/bilibili_source.py#L90)：`BilibiliAudioSource`。
- [src/bili_asr/sources/protocols.py:79–89](../../src/bili_asr/sources/protocols.py#L79)：`AudioSource`。
- [src/bili_asr/audio.py:222–337](../../src/bili_asr/audio.py#L222)：`download_audio`。
- [src/bili_asr/bili_client.py:602–630](../../src/bili_asr/bili_client.py#L602)：`BiliClient.fetch_playurl_audio`。
- [src/bili_asr/bili_client.py:632–657](../../src/bili_asr/bili_client.py#L632)：`BiliClient.download_audio_stream`。
- [src/bili_asr/storage/workflow.py:283–291](../../src/bili_asr/storage/workflow.py#L283)：`WorkflowRepository.owned_transaction`。
- [src/bili_asr/workflow_runtime_ports.py:19–20](../../src/bili_asr/workflow_runtime_ports.py#L19)：`AudioClientFactory`。
- [src/bili_asr/page_identity.py:19–30](../../src/bili_asr/page_identity.py#L19)：`PageIdentity`。
- [src/bili_asr/platform_identity.py:17–48](../../src/bili_asr/platform_identity.py#L17)：`ContentRef`。
