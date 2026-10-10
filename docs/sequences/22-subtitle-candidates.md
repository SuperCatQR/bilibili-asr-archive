# 字幕候选、可信证据与独立 ASR

源码基线：`857906d3b3c54b31fd9bc0ba94b84618f68cd6f3`。
对应 issue #285 的字幕结果分类与旧依赖修复；旧文档中的历史基线不被本图替换。

[交互时序图](22-subtitle-candidates.html) · [Archify 规格](22-subtitle-candidates.json) · [全部时序图](../architecture-sequences.md)

## 候选处理与任务执行

```mermaid
sequenceDiagram
    autonumber
    participant CLI as workflow 命令
    participant Jobs as 规划与任务库
    participant Worker as Executor / handler
    participant Ingest as SubtitleIngestor
    participant Source as 来源 adapter / gateway
    participant Facts as 转录与观察库

    opt 显式修复旧字幕门控依赖
        CLI->>Jobs: READ 预览 1..256 个已归档 part
        Jobs-->>CLI: 任务/依赖变化与 plan_id；拒绝 touched part 活跃任务、跨 part 或歧义音频
        CLI->>Jobs: WRITE --apply --expected-plan-id；可选 --retry-failed
        Jobs->>Jobs: BEGIN IMMEDIATE 内重新预览并比较 plan_id
        alt 计划仍一致
            Jobs->>Jobs: 移除 queued/failed audio/ASR 的旧 subtitle 依赖；确保 ASR→audio
            Jobs-->>CLI: applied=true；终态与 attempt 历史保留
        else 已变化
            Jobs-->>CLI: 拒绝 stale plan；事务不修改
        end
    end

    CLI->>Jobs: 新 plan：subtitle 独立；all/selected 建立 audio→ASR
    Worker->>Jobs: 领取就绪 subtitle；精确绑定 owner/attempt/lease
    Worker->>Ingest: harvest；传入结果事务围栏及 checkpoint
    Ingest->>Source: list_tracks(ContentRef)
    alt 列表明确 not_found
        Ingest->>Facts: no-subtitle，absence_verified=1；使用旧缺口规则
    else 空列表或没有匹配语言
        Ingest->>Source: verify_access，在剩余 deadline 内
        alt 验证失败、超时
            Ingest->>Facts: failed，受控错误
        else 访问验证成功
            Ingest->>Facts: no-subtitle；仅真正空清单且 credentialed verified 才置 credential_verified
        end
    else 可见候选
        Ingest->>Ingest: 按语言 family、CC/AI、上游顺序；显式语言偏好只保留匹配轨道
        loop 最多 32 候选，共享默认 120 秒总预算
            Ingest->>Source: read_body(track, ContentRef)，使用剩余时间并检查租约
            Source-->>Ingest: SubtitleBodyRead 或受控 GatewayError
            alt 正文有效非空
                Ingest->>Facts: 原子存 transcript/segments/attempt，或相同内容 unchanged
            else 合法 empty_body/empty_text
                Ingest->>Ingest: 保存候选证据，继续下一轨
            else shape/transport/正文消失
                Ingest->>Ingest: 保留不确定错误，可尝试替代轨
            else auth/rate/timeout/request_budget_exhausted
                Ingest->>Facts: 立即 failed；不探测后续候选
            end
        end
        alt 存在有效替代轨
            Ingest-->>Worker: stored/unchanged 与安全候选摘要
        else 不确定错误或候选数预算耗尽
            Ingest->>Facts: failed；不能将未完全读取当作耗尽
            Ingest-->>Worker: JobExecutionError，受控 error_code 与摘要
        else 所有候选均合法为空
            Ingest->>Facts: no-subtitle，error=NULL，credential/absence verified 均为 0
            Ingest-->>Worker: visible_candidates_exhausted
        end
    end
    Worker->>Jobs: 围栏内结束 attempt；有成功 transcript 时另请求 publish

    par 独立音频路径
        Worker->>Jobs: 领取 audio；没有 subtitle prerequisite
        Worker->>Facts: 下载、探测、hash、安装并登记音频事实
    and 字幕路径
        Worker->>Jobs: subtitle 可独立成功或失败
    end
    Worker->>Jobs: audio succeeded 后领取 ASR
    Worker->>Facts: 推理结果经取消/租约围栏写转录与运行证据
```

## 条件与边界

- 合法空正文与空 inventory 不同：可见正文全部为空不会新增 Bilibili 可信缺失权限；旧 `v_missing_audio` 仍要求明确已验证 not_found，或多次独立 credentialed 空 inventory。
- 文本为空可以合法；无效/非有限时间轴、缺字段、破损正文不能被转成合法空结果。严格兼容 `fetch_segments` 路径仍拒绝没有有效 segment 的正文。
- 一轮字幕最多存一个有效轨道；前面的空轨道或可替代失败不阻止后面有效轨道。所有候选未确定可读时保持失败。
- `all/selected` 需要 ASR profile；`below-threshold` 仅对已知低分规划 audio/ASR，未知分数不自动生成该链。字幕合法空结果不负责自动改写计划。
- 修复只作用于明确选中 part 的旧生产者依赖；应用保留 attempts、attempt_count 与 succeeded/cancelled 终态。failed audio/ASR 是否重排由显式 flag 控制。
- acquiring 转录与工作流 attempt 是两种证据。handler 结果通过 owner/attempt/lease 围栏提交，失败摘要只含有界代码、候选身份与计数，不保存 cookie、URL 或原始异常文本。
- 本图聚焦 Bilibili 候选语义；YouTube 的 public inventory 与 json3 provenance 使用单独版本化策略，不能借用 Bilibili 的 credential 标志。

## 固定源码证据

- [CLI 的预览/应用入口](https://github.com/SuperCatQR/bilibili-asr-archive/blob/857906d3b3c54b31fd9bc0ba94b84618f68cd6f3/src/bili_asr/cli/workflow.py#L189-L221)。
- [任务规划的独立依赖](https://github.com/SuperCatQR/bilibili-asr-archive/blob/857906d3b3c54b31fd9bc0ba94b84618f68cd6f3/src/bili_asr/workflow_planning.py#L60-L91)。
- [旧图修复与事务内计划复验](https://github.com/SuperCatQR/bilibili-asr-archive/blob/857906d3b3c54b31fd9bc0ba94b84618f68cd6f3/src/bili_asr/storage/workflow_dependency_repair.py#L12-L85)。
- [候选预算、typed 读取及失败条件](https://github.com/SuperCatQR/bilibili-asr-archive/blob/857906d3b3c54b31fd9bc0ba94b84618f68cd6f3/src/bili_asr/services/subtitle_ingest.py#L467-L565)。
- [gateway 合法空正文规范化](https://github.com/SuperCatQR/bilibili-asr-archive/blob/857906d3b3c54b31fd9bc0ba94b84618f68cd6f3/src/bili_asr/sources/bilibili_api_gateway.py#L645-L656)。
- [Bilibili 可信缺口视图](https://github.com/SuperCatQR/bilibili-asr-archive/blob/857906d3b3c54b31fd9bc0ba94b84618f68cd6f3/src/bili_asr/storage/schema-transcripts.sql#L262-L331)。
- [handler 的结果与诊断](https://github.com/SuperCatQR/bilibili-asr-archive/blob/857906d3b3c54b31fd9bc0ba94b84618f68cd6f3/src/bili_asr/workflow_runtime.py#L120-L163)。

## 交付验证

Showcase 9/9、零错误/警告，严格 artifact/provenance 检查与真实 Chrome 的四档 light、两档 dark 检查通过，READ/Still 状态和水平包含通过。按宽度建议仅将列展开为 `spread` 后完整重验。保留 [紧凑交付凭据](../issue-diagram-validation/22-subtitle-candidates/receipt.json)；未进行截图感知评审，不以离线验证推断账号、实网或 GPU 吞吐可用。
