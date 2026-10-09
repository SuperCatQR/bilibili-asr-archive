# 音频复用、隔离下载与受保护登记

源码基线：main `9b289570494b5e8f7cc564a7eaa5b2eb2c28c3ad`。

[交互时序图](06-audio-download.html) · [Archify 规格](06-audio-download.json) · [全部时序图](../architecture-sequences.md)

## 调用顺序与条件分支

```mermaid
sequenceDiagram
    autonumber
    participant handler as 音频 handler
    participant paths as 路径和暂存
    participant downloader as 音频下载器
    participant cdn as DASH 与 CDN
    participant db as 音频与 lease
    handler->>db: 读取 part 并查租约
    handler->>paths: audio/<BVID>.p<零基页>.m4a；拒绝越界、符号链接和非音频对象
    paths-->>handler: 配置产物根优先，archive root 回退；非空 M4A/FLAC
    alt 文件可复用
    handler->>downloader: 复用仍验证 duration、字节数、后缀和 digest
    else 需要下载
    handler->>paths: 在最终 audio/ 下创建 .workflow-audio-*；其中保留 downloader 需要的 audio/ 子目录
    handler->>downloader: 下载至暂存 audio/
    downloader->>cdn: 请求 DASH 签名 URL
    cdn-->>downloader: 流式音频字节
    downloader->>paths: 真实 FLAC 在无 ffmpeg 时保留 .flac；不以 .m4a 冒充
    downloader-->>handler: 返回实际文件路径
    handler->>downloader: 探测有界 30 秒；duration 必须有限且大于 0；hash 在事务外
    end
    handler->>db: BEGIN IMMEDIATE 后检查精确租约
    handler->>paths: 仅下载分支 os.replace；复用分支不搬移旧根对象
    handler->>db: audio_objects 按 sha256 去重；part_audio_objects 保存 workflow 来源
    db-->>handler: key、hash、duration 成为下游 ASR prerequisite result
    handler->>paths: 正常和失败均退出 TemporaryDirectory；不回收已有音频
```

## 边界与恢复

- 当前 workflow 无成功后的自动音频删除、keep-audio 或 max-audio-gb 命令参数。
- 下载、探测、hash 不占 SQLite 写事务；最终替换和登记共享租约保护写锁。
- SQLite rollback 无法回滚已替换的文件；inventory/verify/快照校验是独立核对机制。

## 源码证据

- [src/bili_asr/workflow_runtime.py:118–141](../../src/bili_asr/workflow_runtime.py#L118)：`ArchiveWorkflowHandlers.audio`。
- [src/bili_asr/workflow_runtime.py:150–184](../../src/bili_asr/workflow_runtime.py#L150)：`ArchiveWorkflowHandlers._store_audio`。
- [src/bili_asr/artifact_root.py:1–60](../../src/bili_asr/artifact_root.py#L1)：`模块入口`。
- [src/bili_asr/path_policy.py:1–60](../../src/bili_asr/path_policy.py#L1)：`模块入口`。
- [src/bili_asr/audio.py:1–60](../../src/bili_asr/audio.py#L1)：`模块入口`。
- [src/bili_asr/bili_client.py:219–657](../../src/bili_asr/bili_client.py#L219)：`BiliClient`。
- [src/bili_asr/storage/workflow.py:413–422](../../src/bili_asr/storage/workflow.py#L413)：`WorkflowRepository.owned_transaction`。
