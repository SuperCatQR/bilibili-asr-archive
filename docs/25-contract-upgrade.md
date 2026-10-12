# 冻结契约路径、保真转换与新目标安装

源码基线：`0c62a0f511880e9d07bbf9505771ec15657995e7`；核对日期：2026-10-12（Asia/Hong_Kong）。

[交互图](25-contract-upgrade.html) · [JSON 规格](25-contract-upgrade.json) · [时序索引](architecture-sequences.md)

```mermaid
sequenceDiagram
    autonumber
    participant op as 操作员
    participant upgrade as 升级用例
    participant registry as 契约登记
    participant source as 源归档
    participant stage as 私有暂存
    participant target as 新归档
op->>upgrade: 停写、checkpoint 后 upgrade-plan；源/产物/目标互不包含
    upgrade->>source: MAINTENANCE 锁；typed rows、文件、schema、WAL 与活跃任务检查
    upgrade->>registry: 精确源/目标组合；歧义路径须显式 edge
    registry-->>upgrade: 已登记转换器、版本与保留政策
    upgrade->>source: 绑定库外 control-state 字节与 hold；未声明则要求执行交接
    upgrade-->>op: plan_id、完整基线、代码摘要、空间估算；无昂贵重算
    op->>upgrade: upgrade-apply 同一冻结计划
    upgrade->>source: 重新计划；源、控制状态或转换器改变则拒绝
    upgrade->>stage: 流式复制源字节和遮蔽证据；不修改原源
    loop 每条登记转换边
        upgrade->>stage: 执行转换；精确契约、FK、typed rows 与保留文件核验
    end
    alt 完整目标与源再次核验通过
        upgrade->>stage: 写绑定 DB/文件/plan 的 receipt；fsync
        upgrade->>target: 同父目录原子安装；父目录同步
        upgrade-->>op: installed；同步警告单独报告；不启动 worker 或解除 hold
    else 复制/转换/核验失败
        upgrade->>stage: 清理本次私有暂存；源保留
        upgrade-->>op: 有界失败证据；目标不服务半成品
    end
    op->>upgrade: upgrade-check 外部 expected_plan_id
    upgrade->>target: 核验安装基线和 receipt；新业务写入不能伪装重复升级
    upgrade-->>op: 匹配或保留新增成果后报告基线变化
```

## 边界与恢复

- 版本数字不决定升级顺序，普通 READ/WRITE 不执行 DDL。
- 升级、interrupted-job recovery 和执行权交接是独立用例。相同成功基线可复用，运行后分叉不可自动合并。
- 完整快照自包含；引用备份仅保存可核验引用，见 27。

## 源码证据

- [src/bili_asr/cli/archive.py:1](../src/bili_asr/cli/archive.py#L1)：模块定义。
- [src/bili_asr/services/archive_upgrade.py:140](../src/bili_asr/services/archive_upgrade.py#L140)：plan_upgrade。
- [src/bili_asr/services/archive_upgrade.py:255](../src/bili_asr/services/archive_upgrade.py#L255)：apply_upgrade。
- [src/bili_asr/contracts/registry.py:336](../src/bili_asr/contracts/registry.py#L336)：upgrade_path。
- [src/bili_asr/services/archive_upgrade.py:73](../src/bili_asr/services/archive_upgrade.py#L73)：_inventory。
- [src/bili_asr/services/archive_upgrade.py:217](../src/bili_asr/services/archive_upgrade.py#L217)：_convert。
- [src/bili_asr/services/archive_upgrade.py:334](../src/bili_asr/services/archive_upgrade.py#L334)：check_upgrade。
