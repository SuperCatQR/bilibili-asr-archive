# 冻结 AI 输入、共享提交保护与逐块续跑

源码基线：`4f073318c944add37417416155845e55247f9bc1`；核对日期：2026-10-11（Asia/Hong_Kong）。

[交互时序图](09-ai-proofread.html) · [Archify 规格](09-ai-proofread.json) · [全部时序图](../architecture-sequences.md)

## 调用顺序与条件分支

```mermaid
sequenceDiagram
    autonumber
    participant cli as 请求或依赖结果
    participant handler as 校对 handler
    participant repo as Editorial 仓库
    participant guard as JobCommitGuard
    participant db as 冻结输入与块
    participant deepseek as DeepSeek API
    alt 显式 workflow proofread
    cli->>repo: WRITE Session 下选择当前最新 ASR 或精确 base ID；可显式参考 ID/no-reference
    repo->>guard: build_input 在事务外；应用层进入共享短写事务
    guard->>db: store_input 与 enqueue_editorial 原子保存输入、两个任务和 proofread→render 依赖
    else plan --proofread 自动链
    handler->>repo: 解码版本化 payload；使用精确 ASR prerequisite 成功结果；重试已有 input_id 直接读取
    repo->>guard: 锁外 build_input；保护事务内 store_input 与 job-input 绑定一起提交
    guard->>db: 冻结转录、metadata、配置、system prompt、引用和块；canonical_json 计算固定 digest
    end
    handler->>repo: 检查精确 lease 并加载不可变输入
    loop 每个冻结块
    handler->>repo: 读取 chunk checkpoint
    alt 已完成块
    repo-->>handler: 复用已验证块并跳过远端调用
    else 未完成块
    handler->>repo: renew 至 API timeout+300；begin_call 在共享提交保护下绑定准确 running attempt
    repo->>db: 保存 request_json；不保存密钥
    handler->>deepseek: 锁外发送冻结配置；thinking/top_p/max_tokens；无隐式 HTTP 重试
    deepseek-->>handler: 返回真实 envelope、usage/model；finish_reason 必须 stop
    handler->>repo: finish_call 保留真实 envelope 或有界错误；取消后审计仍可落库
    handler->>handler: 严格 JSON；恰好一次连续有序覆盖；拒绝未知/只读来源和非段落正文
    handler->>guard: save_chunk；事务进入与退出均检查准确 owner、attempt 和 lease
    guard->>db: 保存有效 chunk_results；取消或过期 lease 则拒绝并回滚
    opt 请求或结构校验失败
    handler->>repo: 已完成块保留；executor fail；显式 retry 从未完成块继续
    end
    end
    end
    handler->>guard: commit_revision 收集全部块并验证完整 segment 顺序
    guard->>db: input_id+blocks 固定 digest；needs-review 或 ai-unreviewed；短保护事务提交
    handler-->>cli: 返回 input_id/revision_id；render_document 仅在 proofread succeeded 后可领取
```

## 边界与恢复

- build_input 在事务外构建冻结内容；显式请求的 store_input、两个任务和依赖边由应用层共事务保存，失败全部回滚。自动链的 store_input 与 job-input 绑定同样共用一次保护事务。
- Workflow 与 EditorialRepository 注入同一 JobCommitGuard；准确 attempt/owner/lease 在短写事务两端校验，不再各自实现租约保护逻辑。
- 来源覆盖证明结构追溯，不能证明模型语义保真；数字、专名、否定、立场仍需人工审核。供应商已收请求而本地未存时，retry 可能重复计费。
- canonical_json 是共享纯序列化契约；editorial.canonical/digest 保留兼容导出，持久 JSON、digest 和既有 schema 未改变。

## 源码证据

- [src/bili_asr/services/workflow_application.py:74](../../src/bili_asr/services/workflow_application.py#L74)：WorkflowApplication.proofread。
- [src/bili_asr/workflow_payloads.py:77](../../src/bili_asr/workflow_payloads.py#L77)：decode_job_payload。
- [src/bili_asr/editorial_runtime.py:40](../../src/bili_asr/editorial_runtime.py#L40)：EditorialWorkflowHandlers.proofread。
- [src/bili_asr/storage/editorial.py:171](../../src/bili_asr/storage/editorial.py#L171)：EditorialRepository.freeze_job_input。
- [src/bili_asr/storage/editorial.py:206](../../src/bili_asr/storage/editorial.py#L206)：EditorialRepository.begin_call。
- [src/bili_asr/storage/editorial.py:219](../../src/bili_asr/storage/editorial.py#L219)：EditorialRepository.finish_call。
- [src/bili_asr/storage/job_commit.py:13](../../src/bili_asr/storage/job_commit.py#L13)：JobCommitGuard。
- [src/bili_asr/storage/editorial.py:135](../../src/bili_asr/storage/editorial.py#L135)：EditorialRepository.store_input。
- [src/bili_asr/storage/editorial.py:234](../../src/bili_asr/storage/editorial.py#L234)：EditorialRepository.save_chunk。
- [src/bili_asr/storage/editorial.py:239](../../src/bili_asr/storage/editorial.py#L239)：EditorialRepository.commit_revision。
- [src/bili_asr/deepseek.py:38](../../src/bili_asr/deepseek.py#L38)：DeepSeekClient.complete。
- [src/bili_asr/deepseek.py:61](../../src/bili_asr/deepseek.py#L61)：parse_response。

## 当前冻结与失败恢复

v1/v2 输入按持久版本分派，普通 proofread 优先复用可验证冻结输入；refresh-input 显式建立新快照。结构性重复 ASR 输入在模型请求前失败；failed proofread 的新配置修复保留旧证据，见 [30](30-editorial-repair.md)。
