# 失败状态、政策决策与受保护重排

本流程补齐 #365–367 的观测与恢复边界；源码提交及图表 gate 见 [验证记录](architecture-validation.md)。
[交互图](33-workflow-failure-recovery.html) · [JSON](33-workflow-failure-recovery.json) · [操作手册](operations/workflow-failures.md)

```mermaid
sequenceDiagram
    autonumber
    participant cli as 操作员与控制器
    participant state as 显式控制文件
    participant report as 状态与恢复投影
    participant retry as 受保护重试用例
    participant policy as 纯错误政策
    participant db as SQLite jobs 与 attempts
    cli->>report: status --failed/--json 或 explain；窗口与分页
    report->>state: 有界读取 holds/ledger；未提供保持未知
    report->>db: 一致只读快照；jobs/attempts 分开聚合，finished_at 半开窗口
    report->>policy: 纯分类原错误码；返回版本化默认政策
    policy-->>report: 政策与恢复动作；动态未知异常保守处理
    report->>report: decide_retry 结合控制、预算、退避和替代关系
    report-->>cli: 同一文本/JSON 报告；安全诊断与命令模板，不输出原响应
    cli->>retry: 明确自动/手动/精确 override；控制证据与选择器
    retry->>state: 读取控制摘要；hold 永不被 override 解除
    retry->>db: 读取准确 job 与最新 attempt、替代任务
    retry->>policy: 纯分类失败类别；返回默认预算与恢复政策
    policy-->>retry: 版本化政策；未知错误禁止自动重试
    retry->>retry: decide_retry 检查控制完整性、hold、预算、退避和替代状态
    alt dry-run 或政策拒绝
    retry-->>cli: 逐项 allowed/reason；不写数据库或控制文件
    else 决策允许且实际恢复
    retry->>db: JobCommitGuard BEGIN IMMEDIATE；复验已检查 job/attempt
    retry->>state: 复验控制摘要；变化拒绝或回滚
    retry->>db: 仅将准确 failed job 排队；保留所有 attempts 与冻结输入
    retry->>state: 提交前再次核对摘要；外部所有者仍须串行化文件更新
    retry-->>cli: 重排数量与每项决定；后续 worker 另行 claim
    end
```

## 数据与执行边界

- 当前失败 jobs、全部历史失败 attempts、窗口计数、holds 与替代任务是不同维度，不能相加。
- 外部控制未提供/不完整时不假定为空；明确不存在控制才能声明 no-control-state。
- 政策与诊断不替代人工来源或音频审核。修复旧校对建立新输入与链路，旧失败仍保留，见 [30](30-editorial-repair.md)。
- SQLite 与外部控制文件没有跨介质原子事务；摘要复验不能代替控制文件写入者的串行协调。
- 错误政策和查询不安装新 SQL；新 CLI/控制器使用统一用例，旧库级手动工具需要显式迁移调用点。

## 源码证据

- [workflow_failure_policy.py](../src/bili_asr/workflow_failure_policy.py)：纯分类与有限默认预算。
- [workflow_status.py](../src/bili_asr/services/workflow_status.py)：安全状态投影与恢复模板。
- [workflow_retry.py](../src/bili_asr/services/workflow_retry.py)：控制证据、决定和事务复验。
- [storage/workflow_status.py](../src/bili_asr/storage/workflow_status.py)：只读事实和分组。
- [storage/workflow_retry.py](../src/bili_asr/storage/workflow_retry.py)：准确快照及写入边界。
