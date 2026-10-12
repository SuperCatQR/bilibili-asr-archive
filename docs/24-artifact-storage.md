# 产物副本、迁出、消费 pin 与精确恢复

源码基线：`3ed823c961736378d8408bba5f0535b03e0046e0`；核对日期：2026-10-12（Asia/Hong_Kong）。

[交互图](24-artifact-storage.html) · [JSON 规格](24-artifact-storage.json) · [时序索引](architecture-sequences.md)

```mermaid
sequenceDiagram
    autonumber
    participant op as 运维或消费者
    participant service as 存储用例
    participant db as 副本 Catalog
    participant local as 本地文件
    participant target as 已绑定目录
op->>service: inventory/deep 与冻结 plan；显式 holds 声明
    service->>db: 读取生产引用、pin、组与副本身份；生产状态独立于驻留
    service->>local: 核验 size/hash/generation；文本必须是完整不可变组
    service-->>op: plan 摘要、候选和保留理由；未知 hold 阻止释放
    op->>service: transfer copy/offload；重新核验同一计划
    alt 手动维护窗口
        service->>local: archive 独占维护锁
    else artifact-online 显式策略
        service->>local: 共享维护锁、publication 资源锁和对象独占 fence
    end
    service->>target: 有界批次流式写不可变包；目标身份校验
    target-->>service: 重新读取完整包与成员；SHA/大小/manifest 一致
    service->>db: 登记 verified 外部副本和 transfer journal
    opt offload 且所有保留条件满足
        service->>local: 准确源代次隔离到 quarantine；保存 release intent
        service->>target: 删除前重读目标对象并固定目标代次
        service->>db: 短 BEGIN IMMEDIATE；复验 live hold、consumer、pin 与策略
        service->>local: 删除自有隔离副本；目标代次不得变化
        service->>db: 登记 released；不重置 job、attempt 或审核
    end
    op->>service: 消费准确已登记音频；claim 前检查
    service->>local: 共享对象 fence 与持久 consumer pin
    alt 输入外置
        service->>db: 预留恢复空间与 ASR 工作空间；按对象去重恢复
        service->>target: 读取准确对象包
        service->>local: hash 校验后安装原 storage key；组恢复 marker 最后安装
    else 目标/空间不可用
        service->>db: 保存 input blocked 与 60 秒 backoff
        service-->>op: 不 claim，不消耗 attempt；保留生产成果
    end
    service-->>op: ready 后执行；pin 持有到本次消费结束
```

## 边界与恢复

- 生产完成、历史核验、副本驻留、目标可用性和本地 readiness 是不同事实。
- 在线策略默认 off；消费 pin 的释放由持有进程和内核锁证明，不能只按 lease/PID 超时猜测。
- SQLite/文件无跨介质事务；transfer 与 release journal 保留失败恢复证据。

## 源码证据

- [src/bili_asr/cli/artifacts.py:1](../src/bili_asr/cli/artifacts.py#L1)：模块定义。
- [src/bili_asr/services/artifact_transfer.py:286](../src/bili_asr/services/artifact_transfer.py#L286)：transfer_artifacts。
- [src/bili_asr/services/artifact_consumer.py:42](../src/bili_asr/services/artifact_consumer.py#L42)：candidate_artifact_access。
- [src/bili_asr/storage/artifact_catalog.py:186](../src/bili_asr/storage/artifact_catalog.py#L186)：ArtifactCatalog。
- [src/bili_asr/services/artifact_release.py:1](../src/bili_asr/services/artifact_release.py#L1)：模块定义。
- [src/bili_asr/services/artifact_groups.py:169](../src/bili_asr/services/artifact_groups.py#L169)：restore_artifact_group。
- [src/bili_asr/artifact_packages.py:1](../src/bili_asr/artifact_packages.py#L1)：模块定义。
- [src/bili_asr/storage_targets.py:1](../src/bili_asr/storage_targets.py#L1)：模块定义。
