# 字幕轨道选择、缺失证据与不可变转录

源码基线：main `9b289570494b5e8f7cc564a7eaa5b2eb2c28c3ad`。

[交互时序图](05-subtitle-ingest.html) · [Archify 规格](05-subtitle-ingest.json) · [全部时序图](../architecture-sequences.md)

## 调用顺序与条件分支

```mermaid
sequenceDiagram
    autonumber
    participant executor as 执行器
    participant handler as 字幕 handler
    participant ingest as SubtitleIngestor
    participant gateway as 字幕 API
    participant db as 转录与获取证据
    executor->>handler: 执行 subtitle job
    handler->>db: assert_lease
    handler->>ingest: checkpoint 与 write_guard 均绑定当前任务租约
    ingest->>db: 创建 acquisition run
    ingest->>gateway: 列出字幕轨道
    alt 轨道获取失败
    ingest->>db: 区分 not_found 与 transport/auth/shape/risk 错误
    else 可用轨道清单
    ingest->>ingest: 按语言与来源选轨
    alt 无匹配轨道
    opt 提供了凭据
    ingest->>gateway: cookie 存在不等于认证成功；验证失败作为 failed
    end
    ingest->>db: 未认证空清单不证明永久缺失；认证与 not_found 证据区别保存
    else 有轨道
    ingest->>gateway: 下载正文 segments
    alt 正文有效
    ingest->>db: 事务内检查 lease；按来源/语言/content digest 追加版本或复用旧版，并保存 stored/unchanged attempt
    else 正文消失或形状错误
    ingest->>db: subtitle_body_unavailable/shape_error 不伪装为轨道永久缺失
    end
    end
    end
    ingest->>db: complete/partial/failed；逃逸异常也收尾 failed
    ingest-->>handler: 返回 part outcome
    opt 成功存有转录版本
    handler->>db: 写入或更新该 part 的发布 job；不覆写 ASR 版本
    end
    handler-->>executor: 返回获取与发布身份
```

## 边界与恢复

- 每个 job 对应当前选择的一个分 P；ASR 不等待这条路径的成功。
- 语言、来源、内容和 version 是转录身份；同内容复用不丢失本次获取证据。
- 取消可留下失败 run/attempt 收尾；新的成功转录与新 publish 请求仍受 lease 检查。

## 源码证据

- [src/bili_asr/workflow.py:53–97](../../src/bili_asr/workflow.py#L53)：`WorkflowExecutor.run`。
- [src/bili_asr/workflow_runtime.py:79–116](../../src/bili_asr/workflow_runtime.py#L79)：`ArchiveWorkflowHandlers.subtitle`。
- [src/bili_asr/services/subtitle_ingest.py:423–470](../../src/bili_asr/services/subtitle_ingest.py#L423)：`SubtitleIngestor._acquire_part`。
- [src/bili_asr/sources/bilibili_api_gateway.py:707–1259](../../src/bili_asr/sources/bilibili_api_gateway.py#L707)：`BilibiliApiGateway`。
- [src/bili_asr/storage/transcripts.py:189–312](../../src/bili_asr/storage/transcripts.py#L189)：`TranscriptRepository.record_acquired_transcript`。
- [src/bili_asr/storage/transcripts.py:520–583](../../src/bili_asr/storage/transcripts.py#L520)：`TranscriptRepository.record_subtitle_attempt`。
