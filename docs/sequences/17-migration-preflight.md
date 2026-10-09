# 固定旧源契约、公开清单与完整历史预检

源码基线：架构修复提交 `5d7a57e201564a10dec7a360b2ef8f7874dc51a7`。

[交互时序图](17-migration-preflight.html) · [Archify 规格](17-migration-preflight.json) · [全部时序图](../architecture-sequences.md)

## 调用顺序与条件分支

```mermaid
sequenceDiagram
    autonumber
    participant cli as archive 命令
    participant service as migration_preflight
    participant access as ArchiveSession
    participant legacy as 固定旧源校验
    participant files as 公共清单与源文件
    cli->>service: CommandSpec.archive_argument=source_root；显式 --source-root/--source-artifact-root；忽略运行根环境
    service->>files: 先检查词法祖先、DB 普通文件、根重叠；未规范化前拒绝 links 与 reparse
    service->>access: MAINTENANCE.access；不创建源 root；独占访问，只写根旁协调锁
    service->>files: 非空 WAL/journal 拒绝；记录 DB 物理身份
    service->>legacy: inspect_migration_source；固定 mode=ro&immutable=1；query_only/trusted_schema OFF
    legacy->>legacy: 固定 66 DDL 对象、已知完整 FTS、manuscript v1、integrity/FK；从未运行当前 bootstrap
    alt running job 有有效或缺失 lease
    legacy-->>service: 立即拒绝；要求停止 writer 并 checkpoint
    else 无 running 或仅过期 running
    loop 38 张权威表
    legacy->>legacy: 包含有效 rowid、SQLite 类型与原始 TEXT/BLOB 字节的完整逐行指纹
    end
    legacy-->>service: 固定 contract/source revision、逐表指纹、派生对象、过期 running 数
    end
    service->>files: DB 有界流式 hash；公开 artifact_inventory.collect_artifacts/portable_artifact_parts 检查全部目录
    loop 显式产物根优先、归档根回退的全部物理文件
    files->>files: 拒绝暂存、链接、大小写/Unicode 与 file-parent 冲突；读前/open/读后身份检查；每次 1MiB hash
    alt 已有 selected key
    files-->>service: 遮蔽副本仍哈希、记 physical identity 和 selected_base
    else 首次 key
    files-->>service: 登记 selected/physical/identity
    end
    end
    service->>legacy: 第二个 immutable 连接；legacy_artifact_references 完整历史身份校验
    legacy->>legacy: input/revision/source/job/part 绑定；固定 ai-draft-v1 双稿配对和重新渲染摘要
    legacy->>legacy: edition/父版/准确 review actor-note/事件全链与双 head
    legacy->>legacy: 全部历史 release 含替换和撤回，固定 publish-v1 路径、字节、事件终态
    legacy-->>service: 返回音频/成功 attempt、五文件 bundle/marker、双稿和所有 release 引用
    service->>files: 每个历史引用必须存在且 size/hash 匹配
    service->>legacy: 读取未完成 ingestion/acquisition run 与 model call 数，仅报告恢复候选
    service->>files: 完整 marker 准确声明固定五文件，路径与摘要逐一匹配 selected 清单
    service->>files: 重查集合、全部 physical identity、DB/sidecar、排除名称；变化立即失败
    alt 全部阶段通过
    service->>service: contract+DB hash+去 base 的 selected files 构成源 fingerprint
    service->>access: 退出上下文释放维护访问
    service-->>cli: JSON/text valid=true；table/file/shadowed/excluded/recovery；退出 0
    else 任一阶段失败立即停止
    service->>access: 如已取得访问，由异常上下文释放
    service-->>cli: 有界诊断到 stderr；无成功报告；退出 1
    end
```

## 边界与恢复

- 迁移源契约仍固定于 legacy source revision 9b28957；运行入口证据固定于本次代码提交。共享清单和 Session 只协调访问，从不升级或重写旧源 DDL/JSON/hash。
- Session 在本路径仅提供 MAINTENANCE.access；旧源的 immutable/trusted_schema OFF 是独立冻结读取规则，不调用当前 runtime schema 检查或 initializer。
- migration_preflight 直接使用 artifact_inventory 公开路径、临时文件、冲突、inventory 和 stream_hash 契约，不再导入 archive_snapshot 私有函数。
- 显式产物根优先、归档根回退；遮蔽文件也参与 hash 与变化检查。五类目录全量扫描，credentials/models/logs/cache 只排除名称，不扫描内容。
- 必须停止所有 writer 并 checkpoint，包括未采用维护协议的旧程序。报告包含私有路径；此入口只报告候选，不恢复、不转换、不创建目标档案。

## 源码证据

- [src/bili_asr/cli/archive.py:25–46](../../src/bili_asr/cli/archive.py#L25)：`_cmd_archive`。
- [src/bili_asr/cli/registry.py:1–65](../../src/bili_asr/cli/registry.py#L1)：`模块边界`。
- [src/bili_asr/services/migration_preflight.py:119–213](../../src/bili_asr/services/migration_preflight.py#L119)：`migration_preflight`。
- [src/bili_asr/archive_session.py:95–104](../../src/bili_asr/archive_session.py#L95)：`ArchiveSession.access`。
- [src/bili_asr/archive_maintenance.py:84–160](../../src/bili_asr/archive_maintenance.py#L84)：`archive_access`。
- [src/bili_asr/storage/migration_source.py:176–228](../../src/bili_asr/storage/migration_source.py#L176)：`inspect_migration_source`。
- [src/bili_asr/storage/migration_artifacts.py:147–189](../../src/bili_asr/storage/migration_artifacts.py#L147)：`_legacy_editorial_checks`。
- [src/bili_asr/storage/migration_artifacts.py:88–144](../../src/bili_asr/storage/migration_artifacts.py#L88)：`_legacy_publication_checks`。
- [src/bili_asr/artifact_inventory.py:89–119](../../src/bili_asr/artifact_inventory.py#L89)：`collect_artifacts`。
- [src/bili_asr/artifact_inventory.py:122–130](../../src/bili_asr/artifact_inventory.py#L122)：`stream_hash`。
- [src/bili_asr/services/migration_preflight.py:45–54](../../src/bili_asr/services/migration_preflight.py#L45)：`_hash_file`。
- [src/bili_asr/storage/migration_artifacts.py:192–252](../../src/bili_asr/storage/migration_artifacts.py#L192)：`_legacy_artifact_references`。
- [src/bili_asr/artifact_inventory.py:34–46](../../src/bili_asr/artifact_inventory.py#L34)：`portable_artifact_parts`。
- [src/bili_asr/artifact_inventory.py:53–72](../../src/bili_asr/artifact_inventory.py#L53)：`check_artifact_collisions`。
