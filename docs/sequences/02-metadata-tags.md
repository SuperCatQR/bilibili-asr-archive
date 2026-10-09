# 分页元数据采集、失败恢复与原始标签

源码基线：main `48b31843510e5b1d78ee4f1448cec6dee7ab2296`。

[交互时序图](02-metadata-tags.html) · [Archify 规格](02-metadata-tags.json) · [全部时序图](../architecture-sequences.md)

## 调用顺序与条件分支

```mermaid
sequenceDiagram
    autonumber
    participant cli as 采集命令
    participant ingest as 采集服务
    participant gateway as B站适配器
    participant remote as Bilibili API
    participant db as 元数据表组
    cli->>ingest: mid、显式起页/恢复、页数限制、page_retries、skip_failed_page
    ingest->>db: 建立 user；从持久游标或显式页号开始，记录 SDK 版本
    loop 每页直到空页、上限或失败
    ingest->>gateway: 请求用户视频页
    gateway->>remote: SDK 请求及 pacing
    opt 可重试的传输或限流错误
    gateway-->>ingest: 返回有界错误
    ingest->>gateway: 最多 5 次；30/60/120/240/300 秒等待；仅页面请求重试
    end
    remote-->>gateway: 视频摘要与总数
    gateway-->>ingest: 类型化 DTO
    alt 页面成功且非空
    ingest->>gateway: 页内按 BVID 去重；缺失摘要由详情补充；获取 parts
    ingest->>gateway: 每次 run 重新观察；有界 LRU 只避免本次重复请求
    gateway->>remote: 详情、parts、tags
    remote-->>ingest: 经 gateway 返回；标签 unavailable 与成功空集合不同
    ingest->>db: users/videos/parts/details、标签及观察、page/discoveries、cursor 同一页事务
    else 空页
    ingest->>db: 空页与 complete cursor；终止循环
    else 页请求失败
    ingest->>db: failed/risk_interrupted run 与 page；保留可恢复位置
    opt skip-failed-page 且 failed
    ingest->>db: 只推进未来 run 的 cursor；本次仍失败；risk_interrupted 不跳过
    end
    end
    end
    ingest->>db: complete/limited/risk_interrupted 各自提交；failed 已由 page 事务终结
    ingest-->>cli: 采集与标签统计
    opt 显式 fetch-tags
    cli->>ingest: 验证所有已存 BVID
    ingest->>gateway: 逐视频重取 tags
    ingest->>db: 成功非空替换标签；成功空清空；不可用保留旧标签并记录 unavailable
    end
```

## 边界与恢复

- SESSDATA 是否存在与凭据是否有效是不同事实；秘密和瞬时签名 URL 不作为长期归档内容。
- 原始标签只在 edition create 或显式 sync-source-tags 时冻结；抓取更新不改写既有 edition/release。
- page_retries 的退避由采集服务拥有；标签失败是可选数据失败，不把成功页变成失败页。

## 源码证据

- [src/bili_asr/cli/meta.py:13–80](../../src/bili_asr/cli/meta.py#L13)：`_cmd_fetch_meta`。
- [src/bili_asr/cli/meta.py:83–108](../../src/bili_asr/cli/meta.py#L83)：`_cmd_fetch_tags`。
- [src/bili_asr/services/metadata_ingest.py:303–535](../../src/bili_asr/services/metadata_ingest.py#L303)：`MetadataIngestor._collect`。
- [src/bili_asr/services/video_tags.py:20–56](../../src/bili_asr/services/video_tags.py#L20)：`refresh_video_tags`。
- [src/bili_asr/sources/bilibili_api_gateway.py:707–1259](../../src/bili_asr/sources/bilibili_api_gateway.py#L707)：`BilibiliApiGateway`。
- [src/bili_asr/sources/models.py:245–296](../../src/bili_asr/sources/models.py#L245)：`BilibiliGateway`。
- [src/bili_asr/storage/metadata.py:15–649](../../src/bili_asr/storage/metadata.py#L15)：`MetadataRepository`。
