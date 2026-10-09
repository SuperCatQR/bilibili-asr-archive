# 分页元数据采集、来源身份与原始标签

源码基线：`5d7a57e201564a10dec7a360b2ef8f7874dc51a7`（架构解耦修复后的代码提交；源码链接采用本地路径）。

[Archify 规格](02-metadata-tags.json) · [交互时序图](02-metadata-tags.html) · [全部时序图](../architecture-sequences.md)

## 调用顺序与条件分支

```mermaid
sequenceDiagram
    autonumber
    participant cli as 采集命令
    participant ingest as 采集服务
    participant source as 分 P 来源端口
    participant gateway as B站网关
    participant remote as Bilibili API
    participant db as 元数据表组
    cli->>ingest: mid、显式起页/恢复、页数、page_retries、skip_failed_page
    ingest->>db: 建立 user；从持久游标或显式页号开始并记录 SDK 版本
    loop 每页直到空页、上限或失败
    ingest->>gateway: 请求用户视频页
    gateway->>remote: SDK 请求及 pacing
    remote-->>gateway: 页面响应或有界上游失败
    gateway-->>ingest: 类型化 DTO 或 GatewayError
    opt 传输/限流错误且尚有页面重试次数
    ingest->>ingest: 30/60/120/240/300 秒退避；最多 page_retries 次重试，上限 5
    ingest->>gateway: 仅重试同一页列表；不重放已成功的逐视频采集
    end
    alt 页面成功且非空
    ingest->>gateway: 页内按 BVID 去重；缺失 aid 的摘要由详情补充
    gateway->>remote: 缺失字段才读取详情
    remote-->>gateway: 完整 VideoSummary
    gateway-->>ingest: 保留实际上传者和协作者
    ingest->>source: get_parts(summary.content_ref, video_title_fallback)
    source->>gateway: 校验平台后用真实 external_video_id 取 pagelist
    gateway->>remote: 获取分 P 清单
    remote-->>gateway: 真实 cid、分 P 标题与时长
    gateway-->>source: VideoPart DTO
    source-->>ingest: 拒绝其他视频的 parts；保留真实 cid 与旧 DTO 字段
    ingest->>gateway: 每次 run 重新观察 tags；本次有界 LRU 避免重复请求
    gateway->>remote: 读取原始标签
    remote-->>gateway: 成功标签集合或不可用观察
    gateway-->>ingest: unavailable 与成功空集合保持不同
    ingest->>db: users/videos/parts/details、标签观察、page/discoveries、cursor 同一页事务
    else 页面成功且为空
    ingest->>db: 保存空页与 complete cursor；终止循环
    else 页请求最终失败
    ingest->>db: failed/risk_interrupted run 与 page；保留可恢复位置
    opt skip-failed-page 且 failed
    ingest->>db: 只推进未来 run cursor；本次仍失败；risk_interrupted 不跳过
    end
    end
    end
    ingest->>db: complete/limited/risk_interrupted 各自提交；failed 已由 page 事务终结
    ingest-->>cli: 采集与标签统计
    opt 显式 fetch-tags
    cli->>ingest: 验证所有已存 BVID
    ingest->>gateway: 逐视频重新读取 tags
    ingest->>db: 成功非空替换；成功空清空；不可用保留旧标签并记录 unavailable
    end
```

## 边界与恢复

- SESSDATA 是否存在与凭据是否有效是不同事实；秘密和瞬时签名 URL 不作为长期归档内容。
- VideoSummary.content_ref 是视频查找引用；BilibiliMetadataSource 返回每个真实分 P，保留 cid，ContentRef 不进入数据库或旧 JSON 字段。
- 创建者发现、页面恢复、摘要补充与原始标签仍属于 Bilibili gateway；通用 MetadataSource 端口当前只承担 parts 查询。
- page_retries 的退避由采集服务拥有；标签失败是可选数据失败，不把成功页变成失败页。
- 原始标签只在 edition create 或显式 sync-source-tags 时冻结；抓取更新不改写既有 edition/release。

## 源码证据

- [src/bili_asr/cli/meta.py:14–81](../../src/bili_asr/cli/meta.py#L14)：`_cmd_fetch_meta`。
- [src/bili_asr/cli/meta.py:84–108](../../src/bili_asr/cli/meta.py#L84)：`_cmd_fetch_tags`。
- [src/bili_asr/services/metadata_ingest.py:305–537](../../src/bili_asr/services/metadata_ingest.py#L305)：`MetadataIngestor._collect`。
- [src/bili_asr/services/video_tags.py:20–56](../../src/bili_asr/services/video_tags.py#L20)：`refresh_video_tags`。
- [src/bili_asr/sources/bilibili_source.py:36–45](../../src/bili_asr/sources/bilibili_source.py#L36)：`BilibiliMetadataSource.get_parts`。
- [src/bili_asr/platform_identity.py:17–48](../../src/bili_asr/platform_identity.py#L17)：`ContentRef`。
- [src/bili_asr/sources/bilibili_api_gateway.py:707–1259](../../src/bili_asr/sources/bilibili_api_gateway.py#L707)：`BilibiliApiGateway`。
- [src/bili_asr/sources/bilibili_api_gateway.py:784–861](../../src/bili_asr/sources/bilibili_api_gateway.py#L784)：`BilibiliApiGateway.get_user_video_page`。
- [src/bili_asr/sources/bilibili_api_gateway.py:863–875](../../src/bili_asr/sources/bilibili_api_gateway.py#L863)：`BilibiliApiGateway.get_video_parts`。
- [src/bili_asr/sources/bilibili_api_gateway.py:897–969](../../src/bili_asr/sources/bilibili_api_gateway.py#L897)：`BilibiliApiGateway.get_video_tags`。
- [src/bili_asr/storage/metadata.py:15–649](../../src/bili_asr/storage/metadata.py#L15)：`MetadataRepository`。
- [src/bili_asr/sources/protocols.py:49–59](../../src/bili_asr/sources/protocols.py#L49)：`MetadataSource`。
- [src/bili_asr/sources/models.py:65–128](../../src/bili_asr/sources/models.py#L65)：`VideoSummary`。
- [src/bili_asr/sources/models.py:132–152](../../src/bili_asr/sources/models.py#L132)：`VideoPart`。
- [src/bili_asr/error_codes.py:10–23](../../src/bili_asr/error_codes.py#L10)：`validate_error_code`。
