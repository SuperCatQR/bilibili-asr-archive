# 全集选择验证、配置冻结与依赖规划

源码基线：main `9b289570494b5e8f7cc564a7eaa5b2eb2c28c3ad`。

[交互时序图](03-workflow-plan.html) · [Archify 规格](03-workflow-plan.json) · [全部时序图](../architecture-sequences.md)

## 调用顺序与条件分支

```mermaid
sequenceDiagram
    autonumber
    participant cli as 规划入口
    participant selector as 目标解析
    participant repo as 工作流仓库
    participant db as 控制与事实表
    cli->>selector: part IDs 或多个 BVID；page-index 从 0 开始；不混用选择器
    selector->>db: BVID 全部活跃分 P；显式 unknown/gone 拒绝；批量去重
    alt 目标或配置无效
    selector->>cli: 不创建部分计划；CLI 先验证目标、策略、editorial 配置和 ASR 配置
    else 有效批次
    selector-->>cli: 返回目标身份
    cli->>repo: model 与 aligner 独立 revision、device、语言、分块、timeout、hotwords、token/cache/offline 参数
    repo->>db: 完整 canonical JSON 配置与 profile 关联；同 digest 可复用
    cli->>repo: plan 全部 part
    loop 每个选中分 P
    repo->>db: 幂等 subtitle job
    alt all/selected 或 below-threshold 需要 ASR
    repo->>db: ASR dedupe key 含 profile digest；冻结当时 reference transcript ID
    repo->>db: ASR 只等待 audio succeeded；不依赖 subtitle
    opt --proofread
    repo->>db: proofread → ASR；render_document → proofread；冻结 editorial 配置
    end
    else 已达质量阈值
    repo->>db: 使用已存 workflow_quality_assessments 决策，不动态评测字幕
    end
    end
    repo-->>cli: 重复规划不复活 cancelled job；plan 不做网络或 GPU 工作
    end
    opt 已有转录重新发布
    cli->>repo: workflow publish 逐 part 验证存量转录，force 请求排队
    repo->>db: running 只更新 payload；终态发现请求变化后再入队；cancelled 不复活
    end
```

## 边界与恢复

- 库中允许 index job kind，但当前 CLI 规划与 handler 注册没有 index；FTS 由 search-index 显式执行。
- 当前 asr-policy 为 all/selected/below-threshold；selected 与 all 都对已选 part 规划，below-threshold 增加质量门槛。
- profile 登记与 jobs 规划是不同提交；不将选择验证描述为所有并发条件下的跨步骤原子事务。

## 源码证据

- [src/bili_asr/cli/workflow.py:147–353](../../src/bili_asr/cli/workflow.py#L147)：`_execute_workflow`。
- [src/bili_asr/storage/workflow_selection.py:47–136](../../src/bili_asr/storage/workflow_selection.py#L47)：`resolve_workflow_selection`。
- [src/bili_asr/storage/workflow.py:212–304](../../src/bili_asr/storage/workflow.py#L212)：`WorkflowRepository.plan`。
- [src/bili_asr/storage/workflow.py:675–731](../../src/bili_asr/storage/workflow.py#L675)：`WorkflowRepository.request_publication`。
- [src/bili_asr/storage/workflow.py:166–210](../../src/bili_asr/storage/workflow.py#L166)：`WorkflowRepository.register_profile`。
- [src/bili_asr/storage/workflow.py:544–560](../../src/bili_asr/storage/workflow.py#L544)：`WorkflowRepository._editorial_jobs`。
