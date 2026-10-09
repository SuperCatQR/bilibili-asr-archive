# 归档 ZIP 保存、离线校验与跨设备恢复

源码基线：main `48b31843510e5b1d78ee4f1448cec6dee7ab2296`。

[交互时序图](15-archive-snapshot.html) · [Archify 规格](15-archive-snapshot.json) · [全部时序图](../architecture-sequences.md)

## 调用顺序与条件分支

```mermaid
sequenceDiagram
    autonumber
    participant cli as snapshot 命令
    participant service as 快照服务
    participant lock as 维护独占锁
    participant db as 数据库及恢复
    participant files as 产物根与 ZIP
    cli->>service: 选择 save/check/restore
    alt save
    service->>lock: 停止合作写入者；拒绝仍持有有效 lease 的 running job；目标在源根外且不存在
    service->>db: SQLite backup 不是直接复制 live DB；有界 busy deadline；备份后再验 schema/FK
    service->>files: 产物根优先、archive 根回退；排除 staging；检查重复路径、链接、读前后文件身份
    service->>files: 音频、bundle marker、AI 双稿、所有历史 release 固定文件；包括 superseded/withdrawn
    service->>files: 每文件 size/SHA-256、database contract、snapshot ID；fsync 后不覆盖安装 ZIP
    service->>lock: 释放独占锁
    else check
    service->>files: 严格路径、成员集合/size/hash、bundle marker；只落临时 archive.db
    service->>db: check 不修改源 archive 或创建新持久 archive
    else restore
    service->>lock: 目标不存在或空；源 ZIP 不在目标内；拒绝链接/路径冲突
    service->>files: 先验证全部 size/hash/manifest、marker 与 DB references
    service->>db: running attempt → failed/snapshot_restored；running job → queued；清 lease
    service->>db: ingestion/acquisition running → failed；未结束 model call 记录 snapshot_restored；cancelled 保留
    service->>db: 再次校验并 fsync
    service->>files: 成功前不覆盖旧档案；暂存 rename；产物归并到恢复 root
    service->>lock: 释放独占锁
    end
    service-->>cli: 返回快照或恢复统计
```

## 边界与恢复

- 私有归档快照保存完整数据库与历史产物；与公开阅读目录快照用途和数据集合不同。
- 过期 running job 可随 save 保留，restore 再恢复；有效运行租约会被 save 拒绝。
- 维护协议只约束合作 writer；直接绕开 CLI/repository 的外部写入仍需操作者停止。

## 源码证据

- [src/bili_asr/cli/snapshot.py:28–46](../../src/bili_asr/cli/snapshot.py#L28)：`_cmd_snapshot`。
- [src/bili_asr/services/archive_snapshot.py:260–324](../../src/bili_asr/services/archive_snapshot.py#L260)：`save_snapshot`。
- [src/bili_asr/services/archive_snapshot.py:420–426](../../src/bili_asr/services/archive_snapshot.py#L420)：`check_snapshot`。
- [src/bili_asr/services/archive_snapshot.py:438–463](../../src/bili_asr/services/archive_snapshot.py#L438)：`restore_snapshot`。
- [src/bili_asr/archive_maintenance.py:64–137](../../src/bili_asr/archive_maintenance.py#L64)：`archive_access`。
- [src/bili_asr/storage/snapshots.py:185–209](../../src/bili_asr/storage/snapshots.py#L185)：`create_database_snapshot`。
- [src/bili_asr/storage/snapshots.py:305–351](../../src/bili_asr/storage/snapshots.py#L305)：`recover_interrupted_jobs`。
- [src/bili_asr/services/archive_snapshot.py:394–417](../../src/bili_asr/services/archive_snapshot.py#L394)：`_validate_into`。
- [src/bili_asr/storage/snapshots.py:242–302](../../src/bili_asr/storage/snapshots.py#L242)：`required_artifacts`。
