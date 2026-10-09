# AI 输入冻结、块恢复、调用审计与完整修订

源码基线：main `9b289570494b5e8f7cc564a7eaa5b2eb2c28c3ad`。

[交互时序图](09-ai-proofread.html) · [Archify 规格](09-ai-proofread.json) · [全部时序图](../architecture-sequences.md)

## 调用顺序与条件分支

```mermaid
sequenceDiagram
    autonumber
    participant cli as 请求或依赖结果
    participant handler as 校对 handler
    participant repo as Editorial 仓库
    participant db as 冻结输入与块
    participant deepseek as DeepSeek API
    alt 显式 workflow proofread
    cli->>repo: part 最新 ASR 在请求时选定，或精确 base ID；参考 ID/no-reference 可显式指定
    repo->>db: 转录内容、元数据、配置、system prompt、引用与块的 input digest
    else plan --proofread 自动链
    handler->>repo: 使用精确 prerequisite result 的 transcript_id，不在重试时选择最新 ASR
    repo->>db: 当时可用同语言字幕作为参考；已绑定 input_id 重试直接读取
    end
    handler->>repo: 查租约并加载输入
    loop 每个冻结块
    handler->>repo: 读取块检查点
    alt 已完成块
    repo-->>handler: 复用块并跳过调用
    else 未完成块
    handler->>db: renew 至 api timeout + 300；begin_call 绑定准确 attempt，保存 request，不保存密钥
    handler->>deepseek: high thinking/top_p/max_tokens 来自冻结配置；无隐式 HTTP 重试
    deepseek-->>handler: 包含 usage、model 和返回思考；finish_reason 必须 stop
    handler->>repo: 真实响应或有界错误允许在取消后留存
    handler->>handler: 严格 JSON；segment 恰好一次连续有序覆盖；拒绝未知/只读来源、非段落正文
    handler->>repo: 保护性保存有效块
    repo->>db: 保存 chunk_results；取消或 lease 失效则拒绝
    opt 请求或结构校验失败
    handler->>repo: 已完成块保留；executor fail 后可显式 retry
    end
    end
    end
    handler->>repo: 提交完整 revision
    repo->>db: input_id + blocks 得到 revision digest；needs-review 或 ai-unreviewed；保护事务提交
    handler-->>cli: render_document 依赖 proofread succeeded 后才可领取
```

## 边界与恢复

- prepare 保存内容寻址输入与绑定 job 是不同事务；取消时可留下未绑定输入，但不能提交新块或新修订。
- 来源覆盖证明结构追溯，不证明模型语义保真；数字、专名、否定、立场仍需人工审核。
- 供应商已收请求而本地未保存时，retry 可能重复计费；不保证外部调用恰好一次。

## 源码证据

- [src/bili_asr/cli/workflow.py:147–353](../../src/bili_asr/cli/workflow.py#L147)：`_execute_workflow`。
- [src/bili_asr/editorial_runtime.py:33–57](../../src/bili_asr/editorial_runtime.py#L33)：`EditorialWorkflowHandlers.proofread`。
- [src/bili_asr/storage/editorial.py:81–103](../../src/bili_asr/storage/editorial.py#L81)：`EditorialRepository.freeze_job_input`。
- [src/bili_asr/storage/editorial.py:138–154](../../src/bili_asr/storage/editorial.py#L138)：`EditorialRepository.commit_revision`。
- [src/bili_asr/storage/editorial.py:53–66](../../src/bili_asr/storage/editorial.py#L53)：`EditorialRepository.prepare`。
- [src/bili_asr/storage/editorial.py:133–136](../../src/bili_asr/storage/editorial.py#L133)：`EditorialRepository.save_chunk`。
- [src/bili_asr/deepseek.py:38–58](../../src/bili_asr/deepseek.py#L38)：`DeepSeekClient.complete`。
- [src/bili_asr/deepseek.py:61–81](../../src/bili_asr/deepseek.py#L61)：`parse_response`。
