# 统一维护访问、公开清单与归档 ZIP 恢复

源码基线：架构修复提交 `5d7a57e201564a10dec7a360b2ef8f7874dc51a7`。

[交互时序图](15-archive-snapshot.html) · [Archify 规格](15-archive-snapshot.json) · [全部时序图](../architecture-sequences.md)

## 调用顺序与条件分支

```mermaid
sequenceDiagram
    autonumber
    participant cli as snapshot 命令
    participant access as ArchiveSession
    participant service as 快照服务
    participant db as 数据库与身份
    participant files as 清单与 ZIP
    cli->>access: CommandSpec 声明 save/restore MAINTENANCE；check 无档案连接；稳定锁位于根旁
    cli->>service: 选择 save/check/restore；服务库入口也独立取得维护访问
    alt save
    service->>access: MAINTENANCE.access；排除全部 Session reader/writer/heartbeat；持锁直到安装结束
    service->>db: 无 DDL 校验 schema/integrity/FK；拒绝有效 lease 的 running job
    service->>files: artifact_inventory.collect_artifacts；配置产物根优先，档案根回退；递归拒绝暂存、链接与碰撞
    service->>db: SQLite backup；有界 busy deadline；备份后再次校验 schema/FK 并拒绝活跃 job
    loop archive.db 与全部已选物理产物
    service->>files: stream_hash 每次最多 1MiB；边写 ZIP 边 hash；读前/open/读后身份核对；每文件 size/SHA-256
    end
    service->>db: required_artifacts；音频、成功 attempt、完整 bundle/marker、双稿、全部历史 release
    db->>db: storage.publication.verify_release_identity 读取准确 edition/review/events；纯 publication_identity 验证历史 renderer
    service->>files: 加入 manifest；复核 ZIP 内全部 marker；fsync 后不覆盖安装到根外新目标
    service->>access: 退出维护上下文；stage 清理；临时 DB 不建立持久锁文件
    else check
    service->>files: 严格 portable 路径、成员集合/size/hash、公共 bundle basenames/marker；仅提取临时 DB
    service->>db: 校验 snapshot contract 与所有 references；不创建持久档案，不刷新源 schema
    else restore
    service->>access: MAINTENANCE.access 允许新目标；目标不存在或为空；稳定锁不随 rename 移动
    service->>files: ZIP 解包到 staging；校验全部 manifest/hash/marker/reference；通过后才允许恢复任务
    service->>db: running attempt failed/snapshot_restored；running job queued；清 lease；cancelled 保留
    service->>db: 未完成 ingestion/acquisition 失败；未结束 model call 记录恢复原因；只改恢复 staging
    service->>db: 再次 schema/FK 校验并 fsync
    service->>files: 暂存 rename 为恢复 root；产物合并到恢复根；不覆盖旧档案
    service->>access: 释放目标维护访问并清理 staging
    end
    service-->>cli: 返回快照或恢复统计；任一校验失败立即停止并释放已持访问
```

## 边界与恢复

- MAINTENANCE 由统一 ArchiveSession 取得独占访问；普通查询、写入和心跳连接均持有共享访问直至 close。外部直接 SQLite writer 仍必须由操作者停止。
- artifact_inventory 统一路径、冲突、临时文件和有界流式 hash；artifacts 公开 BUNDLE_BASENAMES/BUNDLE_MARKER_NAME/owns_bundle_paths，维护服务不导入 archive 私有实现。
- 快照 storage 通过 storage.publication 的公开 identity reader 校验历史 release；纯 publication_identity 验证准确审核、事件、path/hash 和固定 renderer，无反向 application 依赖。
- check 不打开持久 archive Session。stage DB 使用共享 connect_database 配置且不创建邻接维护锁；恢复只改 staging，成功后才发布目标根。

## 源码证据

- [src/bili_asr/cli/snapshot.py:29–47](../../src/bili_asr/cli/snapshot.py#L29)：`_cmd_snapshot`。
- [src/bili_asr/cli/registry.py:1–65](../../src/bili_asr/cli/registry.py#L1)：`模块边界`。
- [src/bili_asr/archive_session.py:95–104](../../src/bili_asr/archive_session.py#L95)：`ArchiveSession.access`。
- [src/bili_asr/archive_maintenance.py:84–160](../../src/bili_asr/archive_maintenance.py#L84)：`archive_access`。
- [src/bili_asr/services/archive_snapshot.py:157–221](../../src/bili_asr/services/archive_snapshot.py#L157)：`save_snapshot`。
- [src/bili_asr/services/archive_snapshot.py:317–323](../../src/bili_asr/services/archive_snapshot.py#L317)：`check_snapshot`。
- [src/bili_asr/services/archive_snapshot.py:335–360](../../src/bili_asr/services/archive_snapshot.py#L335)：`restore_snapshot`。
- [src/bili_asr/storage/snapshots.py:182–206](../../src/bili_asr/storage/snapshots.py#L182)：`create_database_snapshot`。
- [src/bili_asr/storage/snapshots.py:235–294](../../src/bili_asr/storage/snapshots.py#L235)：`required_artifacts`。
- [src/bili_asr/storage/snapshots.py:297–343](../../src/bili_asr/storage/snapshots.py#L297)：`recover_interrupted_jobs`。
- [src/bili_asr/artifact_inventory.py:89–119](../../src/bili_asr/artifact_inventory.py#L89)：`collect_artifacts`。
- [src/bili_asr/artifact_inventory.py:122–130](../../src/bili_asr/artifact_inventory.py#L122)：`stream_hash`。
- [src/bili_asr/services/archive_snapshot.py:291–314](../../src/bili_asr/services/archive_snapshot.py#L291)：`_validate_into`。
- [src/bili_asr/storage/publication.py:303–311](../../src/bili_asr/storage/publication.py#L303)：`verify_release_identity`。
- [src/bili_asr/publication_identity.py:12–41](../../src/bili_asr/publication_identity.py#L12)：`validate_release_identity`。
- [src/bili_asr/artifacts.py:1–33](../../src/bili_asr/artifacts.py#L1)：`模块边界`。
