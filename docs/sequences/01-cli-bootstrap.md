# CLI 启动、路径策略与数据库契约

源码基线：本次架构边界修复的固定代码提交 `5d7a57e201564a10dec7a360b2ef8f7874dc51a7`；这是从 main 开始的本地修复身份，不表示远端 main 已包含修复。

[交互时序图](01-cli-bootstrap.html) · [Archify 规格](01-cli-bootstrap.json) · [全部时序图](../architecture-sequences.md)

## 调用顺序与条件分支

```mermaid
sequenceDiagram
    autonumber
    participant operator as 操作者
    participant cli as CLI 入口
    participant session as ArchiveSession 与产物根
    participant handler as 命令处理器
    participant db as archive.db
    operator->>cli: 安装入口或 python -m bili_asr；解析命令与子命令
    alt 无子命令或帮助请求
    cli-->>operator: 输出帮助并退出
    else 有效命令
    cli->>session: CommandSpec 独立声明 artifact 与 database 模式；子命令覆盖
    opt 需要产物根
    session->>session: flag > BILI_ARTIFACT_ROOT > archive root；WRITE 检查可写性；metadata search 跳过产物探测
    end
    opt 需要数据库访问
    cli->>session: READ/WRITE/BOOTSTRAP 共享锁；MAINTENANCE 独占；覆盖整个命令调用
    end
    cli->>handler: 分派已注册入口
    alt 显式 BOOTSTRAP
    handler->>session: 采集或全新 archive 初始化
    session->>db: 先检查表契约，再 initialize_schema 与刷新 shipped views
    db-->>session: 返回配置连接；不兼容则 SchemaContractError
    else READ 或 WRITE 已有运行库
    handler->>session: open_archive_connection；RUNTIME 或 MANUSCRIPT 契约
    session->>db: mode=ro/query_only 或 mode=rw；busy timeout/foreign_keys；只读契约检查，无 DDL
    db-->>session: 有效连接；缺失或不兼容明确失败，不自动补库
    else 专用历史索引
    handler->>session: READ/WRITE + NONE；专用 store/index 形状检查
    session->>db: 保留旧 schema；显式 build 只允许 FTS DDL，新空归档才 BOOTSTRAP
    else archive migration-preflight
    handler->>session: 显式源根；服务获取 MAINTENANCE 独占锁
    handler->>db: immutable=1 / query_only；固定旧源契约，不调用 initializer
    end
    session-->>handler: 连接绑定维护访问 lease，程序化调用直到 close 才释放
    handler-->>cli: 返回结果与退出码
    cli->>session: 关闭连接、释放命令访问；嵌套用户引用计数支持非 LIFO 关闭
    cli-->>operator: 结果与诊断按各命令契约输出；BUSY/LOCKED 超时给出可恢复诊断
    end
```

## 边界与恢复

- status/runs、workflow status/explain 和常规消费者使用 READ；查询不会初始化新库或刷新视图。WRITE 同样不运行 initializer。
- BOOTSTRAP 是唯一 schema 初始化入口；NONE 留给历史索引/专用契约，不能作为业务库绕过校验的默认模式。
- open_archive_connection 返回的连接持有 session lease，close 才释放；失败契约检查也关闭连接并释放锁。
- 共享 OS 维护锁只协调合作写入者与快照/预检；SQLite BEGIN IMMEDIATE 决定事务写入顺序。
- 注册表中共有 16 个顶层命令；旧版命令不能由源码中的历史 docstring 推断为当前入口。

## 源码证据

- [src/bili_asr/cli/parser.py:11–115](../../src/bili_asr/cli/parser.py#L11)：`build_parser`。
- [src/bili_asr/cli/main.py:41–102](../../src/bili_asr/cli/main.py#L41)：`_main`。
- [src/bili_asr/cli/registry.py:20–40](../../src/bili_asr/cli/registry.py#L20)：`CommandSpec`。
- [src/bili_asr/cli/workflow.py:147–271](../../src/bili_asr/cli/workflow.py#L147)：`_execute_workflow`。
- [src/bili_asr/cli/publication.py:60–121](../../src/bili_asr/cli/publication.py#L60)：`_cmd_publication`。
- [src/bili_asr/archive_session.py:64–149](../../src/bili_asr/archive_session.py#L64)：`ArchiveSession`。
- [src/bili_asr/archive_maintenance.py:84–160](../../src/bili_asr/archive_maintenance.py#L84)：`archive_access`。
- [src/bili_asr/storage/database.py:87–111](../../src/bili_asr/storage/database.py#L87)：`connect_database`。
- [src/bili_asr/storage/database.py:525–537](../../src/bili_asr/storage/database.py#L525)：`initialize_schema`。
- [src/bili_asr/storage/database.py:540–561](../../src/bili_asr/storage/database.py#L540)：`require_archive_schema`。
