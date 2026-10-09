# 任务认领、心跳、取消、租约回收与重试

源码基线：main `48b31843510e5b1d78ee4f1448cec6dee7ab2296`。

[交互时序图](04-lease-cancel-retry.html) · [Archify 规格](04-lease-cancel-retry.json) · [全部时序图](../architecture-sequences.md)

## 调用顺序与条件分支

```mermaid
sequenceDiagram
    autonumber
    participant operator as 控制命令
    participant executor as Executor
    participant heartbeat as 心跳线程
    participant handler as 业务 handler
    participant db as 任务与 attempt
    operator->>executor: workflow run
    loop 顺序领取直到空闲或 limit
    executor->>db: BEGIN IMMEDIATE
    db->>db: 旧 running attempt → failed/lease_expired；job → queued；保留证据
    executor->>db: available_at 已到且所有 prerequisite succeeded；priority/created_at/job_id 排序
    alt 无任务
    db-->>executor: 返回 idle
    else 有任务
    db-->>executor: running、lease owner、expires、attempt_count+1；创建 attempt
    executor-->>heartbeat: file-backed SQLite 在心跳线程内建立连接；内存库无独立续租连接
    heartbeat-->>db: 默认 lease/3；首次立即续租；失效停止；暂时错误下次重试
    executor->>handler: 执行锁外耗时工作
    opt 并发显式取消
    operator->>db: queued/running → cancelled；清 lease；running attempt 同时 cancelled
    end
    handler->>db: job_id + owner + attempt_count + 未过期 lease；owned_transaction 与取消共用写锁
    alt 取消或旧 worker
    db->>handler: JobCancelledError / LeaseLostError；已提交事实及调用审计保留
    else 有效 owner
    handler->>db: 提交业务结果
    end
    handler-->>executor: 返回结果或错误
    executor->>db: 再校验精确 attempt；no_handler 明确失败；取消计数与失败计数分开
    executor->>heartbeat: 停止并关闭连接
    end
    end
    opt workflow retry
    operator->>db: 按 part/job/kind 筛选；保留 attempt；cancelled/succeeded 不被 retry 恢复
    end
    executor-->>operator: failed 非零使 CLI 退出 1；cancelled 单独统计
```

## 边界与恢复

- 网络、GPU 和模型调用是协作取消；当前 workflow run 不提供立即终止每个在途请求的保证。
- 取消不级联删除依赖；依赖 cancelled 的 queued job 由 status/explain 派生为 blocked。
- 结果提交与 executor 的终态提交是独立事务；崩溃后可出现已存结果但 job 仍 running，需要幂等恢复。

## 源码证据

- [src/bili_asr/cli/workflow.py:147–353](../../src/bili_asr/cli/workflow.py#L147)：`_execute_workflow`。
- [src/bili_asr/workflow.py:53–97](../../src/bili_asr/workflow.py#L53)：`WorkflowExecutor.run`。
- [src/bili_asr/workflow.py:145–171](../../src/bili_asr/workflow.py#L145)：`_LeaseHeartbeat._run`。
- [src/bili_asr/workflow_runtime.py:45–417](../../src/bili_asr/workflow_runtime.py#L45)：`ArchiveWorkflowHandlers`。
- [src/bili_asr/editorial_runtime.py:17–89](../../src/bili_asr/editorial_runtime.py#L17)：`EditorialWorkflowHandlers`。
- [src/bili_asr/storage/workflow.py:306–372](../../src/bili_asr/storage/workflow.py#L306)：`WorkflowRepository.claim`。
- [src/bili_asr/storage/workflow.py:450–498](../../src/bili_asr/storage/workflow.py#L450)：`WorkflowRepository.cancel`。
- [src/bili_asr/storage/workflow.py:829–892](../../src/bili_asr/storage/workflow.py#L829)：`WorkflowRepository._terminal`。
