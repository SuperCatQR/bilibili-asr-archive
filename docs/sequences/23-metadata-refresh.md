# 增量发现、字段刷新与失败重放

源码基线：`857906d3b3c54b31fd9bc0ba94b84618f68cd6f3`。
对应 issue #286 的当前源元数据与 #287 的增量采集、字段刷新和失败补采。

[交互时序图](23-metadata-refresh.html) · [Archify 规格](23-metadata-refresh.json) · [全部时序图](../architecture-sequences.md)

## 扫描、刷新与恢复

```mermaid
sequenceDiagram
    autonumber
    participant CLI as fetch-meta
    participant Service as Ingestor / RefreshService
    participant Policy as MetadataRefreshPolicy
    participant Gateway as Bilibili gateway
    participant Budget as RequestScheduler
    participant Repo as MetadataRepository / SQLite

    alt 分页发现或恢复
        CLI->>Service: --incremental 或 --resume/--start-page
        Service->>Repo: 读取已存扫描游标；建立缺失用户和 run
        alt incremental
            Service->>Service: 强制第 1 页，重新观察 head
        else 恢复或显式起点
            Service->>Service: 显式 start-page 优先，否则存储 next_page，否则第 1 页
        end
        Service->>Gateway: 请求当前视频列表页
        Gateway->>Budget: shared run(operation, scoped_call)
        Budget->>Gateway: 计数、总 deadline、单次 timeout、pacing/cooldown 后调用
        Gateway-->>Service: 校验后的 VideoSummary 集合
        Service->>Repo: 集合读取当前 aid、parts、tags 成功状态与时间
        Service->>Policy: new/missing/stale/force 决定 expensive 操作
        Policy-->>Service: 读取或复用；发现页不被省略
        loop 每 distinct BVID
            Service->>Gateway: 必要时补 detail/parts；tags 返回本次 typed TagRead
            Gateway->>Budget: 消耗同一预算；retry/backoff 不绕过冷却
            Gateway-->>Service: DTO 或有界错误；成功 view pages 可复用
        end
        alt 本页必要 fan-out 与身份校验通过
            Service->>Repo: 一个页事务：用户、视频、parts、详情、tags、discovery、cursor、page
            Repo-->>Service: 全部提交；空页 complete，上限 limited
        else gateway、CID 或 topology 失败
            Service->>Repo: v2 另记失败 operation 的安全 mid/page
            Service->>Repo: failed/risk_interrupted page 与 run；该页无实体载荷
            Repo-->>Service: 已成功页保留；默认 cursor 不前移
        end
    else 定向刷新归档视频
        CLI->>Service: --bvid ... --fields summary details parts tags；可选 TTL/mode
        Service->>Repo: 在网络读取前校验全部 BVID 已归档
        loop 选中 BVID 与 operation
            Service->>Repo: 读取成功观察与时间
            Service->>Policy: 判断缺失或成功观察过期
            Policy-->>Service: reused 或读取
            Service->>Gateway: summary/details 共用一次 view；parts 复用已校验 pages
            Gateway->>Budget: 同一个协调器计数与 deadline
            Gateway-->>Service: present/empty/missing/unavailable/denied 字段
            alt operation 成功
                Service->>Repo: 独立事务更新已观察字段与 last-success，追加 attempt
            else operation 失败
                Service->>Repo: 保留最后成功事实；记 unavailable/denied attempt
            end
        end
        Service-->>CLI: operation/state/error_code；分页 cursor 不变
    end

    opt 显式 --refresh-failed（仅 universal-v2）
        CLI->>Service: 从最新 operation attempt 选择失败
        Service->>Repo: 读取失败 BVID/operation 与安全上下文
        alt 视频已经归档
            Service->>Gateway: 仅重抓失败 operation，成功追加结果
        else 首次发现的视频尚未保存
            Service->>Service: 用持久 mid/page 重放整页，同页去重
            Service->>Gateway: 重新读取原页面及必要 fan-out
            Service->>Repo: 原子补回实体；不回退已经更后的 cursor
            alt 源页变动，原 BV 不在该页
                Service->>Repo: 保留 metadata_retry_context_changed
            end
        end
        Service-->>CLI: 当前恢复结果与 request metrics
    end
```

## 字段、游标与预算语义

- 增量扫描明确回到上传者列表头；恢复游标表示上次扫描位置，不能作为发现新上传的增量水位。`incremental` 与 `resume/start-page` 互斥。
- 默认 `force` 保留重采行为。`new` 只补新视频的 expensive 操作；`missing` 补未成功观察；`stale` 按 last-success 与 TTL 判断。复用事实不重写观察时间，也不伪造网络调用。
- present 更新字段；明确 empty 可撤回；missing/unavailable/denied 保留最后成功事实。标签成功空集合才清空，失败仍保留旧集合。
- 分页普通 summary 允许补齐 `pubdate=0`；已知正值由显式 summary refresh 修正，传入 0 不覆盖已有正值。aid 与分 P CID 保持稳定身份，冲突不会重绑已有转录。
- 一页载荷的 SQL 提交原子。可选 tags 失败记录覆盖缺口而保留旧标签；必须的 detail/parts 失败使该页载荷不提交。显式 `skip-failed-page` 是独立游标推进操作，仍保留失败证据，限流不能跳过。
- v2 的 `source_metadata_observations` 保存逐字段当前观察与最后成功值；`metadata_refresh_attempts` 是追加尝试账本。v1 不自动补这两张表，`refresh-failed` 明确要求显式新建或迁移目标。
- 新视频失败时页事务外留下安全 mid/page；整页重放不会回退更后的成功游标。页面变化后无法找回原 BV 必须保留未解决失败。
- 请求协调器按 gateway operation 计数，应用重试与 credential 验证共用预算；单次 timeout 受总 deadline 约束，限流设置共享冷却。它只协调同一个进程内实例，SDK 内部 HTTP 子请求不逐个计量。
- 当前事实可刷新；已经冻结的 AI 输入、稿件内容、审核、release 与历史渲染字节保持原版本契约。

## 固定源码证据

- [CLI 模式、字段与预算参数](https://github.com/SuperCatQR/bilibili-asr-archive/blob/857906d3b3c54b31fd9bc0ba94b84618f68cd6f3/src/bili_asr/cli/parser.py#L38-L73)。
- [分页发现、fan-out 与事务调用](https://github.com/SuperCatQR/bilibili-asr-archive/blob/857906d3b3c54b31fd9bc0ba94b84618f68cd6f3/src/bili_asr/services/metadata_ingest.py#L240-L583)。
- [定向刷新与失败操作选择](https://github.com/SuperCatQR/bilibili-asr-archive/blob/857906d3b3c54b31fd9bc0ba94b84618f68cd6f3/src/bili_asr/services/metadata_refresh.py#L30-L151)。
- [成功观察时间与字段事务](https://github.com/SuperCatQR/bilibili-asr-archive/blob/857906d3b3c54b31fd9bc0ba94b84618f68cd6f3/src/bili_asr/services/metadata_refresh.py#L153-L202)。
- [共享计数、timeout、冷却与等待](https://github.com/SuperCatQR/bilibili-asr-archive/blob/857906d3b3c54b31fd9bc0ba94b84618f68cd6f3/src/bili_asr/request_budget.py#L14-L79)。
- [字段保留与观察账本](https://github.com/SuperCatQR/bilibili-asr-archive/blob/857906d3b3c54b31fd9bc0ba94b84618f68cd6f3/src/bili_asr/storage/metadata.py#L365-L420)。
- [页原子提交与失败证据](https://github.com/SuperCatQR/bilibili-asr-archive/blob/857906d3b3c54b31fd9bc0ba94b84618f68cd6f3/src/bili_asr/storage/metadata.py#L545-L720)。
- [v2 独立 schema 对象](https://github.com/SuperCatQR/bilibili-asr-archive/blob/857906d3b3c54b31fd9bc0ba94b84618f68cd6f3/src/bili_asr/storage/schema-observations.sql#L1-L22)。

## 交付验证

Showcase 9/9、零错误/警告，严格 artifact/provenance 检查与真实 Chrome 的四档 light、两档 dark 检查通过。宽度建议只改变 `column_fit=spread` 并重验；正常纵向页面滚动通过声明的可读布局接受，无水平溢出。保留 [紧凑交付凭据](../issue-diagram-validation/23-metadata-refresh/receipt.json)。未进行截图感知评审；离线观察与回归不代表上游账号、实网或生产 archive 切换验收。
