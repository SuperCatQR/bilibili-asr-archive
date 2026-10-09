# CLI 启动、路径策略与数据库契约

源码基线：main `9b289570494b5e8f7cc564a7eaa5b2eb2c28c3ad`。

[交互时序图](01-cli-bootstrap.html) · [Archify 规格](01-cli-bootstrap.json) · [全部时序图](../architecture-sequences.md)

## 调用顺序与条件分支

```mermaid
sequenceDiagram
    autonumber
    participant operator as 操作者
    participant cli as CLI 入口
    participant paths as 路径与维护锁
    participant handler as 命令处理器
    participant db as archive.db
    operator->>cli: 安装入口或 python -m bili_asr；解析命令与子命令
    alt 无子命令或帮助请求
    cli-->>operator: 输出帮助并退出
    else 有效命令
    cli->>paths: 注册表 NONE/READ/WRITE；子命令覆盖；metadata search 跳过产物探测
    opt 需要产物根
    paths->>paths: flag > BILI_ARTIFACT_ROOT > archive root；WRITE 检查可写性；READ 按配置根再旧根读取
    end
    opt 写归档或初始化查询
    cli->>paths: 普通 writer 可并发；与 snapshot 独占锁冲突时明确失败
    end
    cli->>handler: 分派已注册入口
    alt 使用 open_database
    handler->>db: 设置 busy timeout / foreign_keys；检查旧 manuscript 与全部持久表契约
    alt 表契约兼容
    db->>db: 允许新增 video_tag_observations；刷新已交付视图；不 ALTER 历史业务表
    db-->>handler: 返回连接
    else 不兼容
    db->>handler: SchemaContractError；保留原库，需要另建兼容库
    end
    else 只读消费入口
    handler->>db: 投影、搜索、稿件导出不通过 schema 初始化
    end
    handler-->>cli: 返回结果与退出码
    cli->>paths: 释放维护锁
    cli-->>operator: 结果与诊断按各命令契约输出；BUSY/LOCKED 超时给出可恢复诊断
    end
```

## 边界与恢复

- status/runs 在库存在时仍使用初始化连接，并持有共享维护锁；workflow 查询也可初始化新库。
- 共享 OS 维护锁只协调合作写入者与快照；SQLite BEGIN IMMEDIATE 决定事务写入顺序。
- 注册表中共有 15 个顶层命令；旧版命令不能由源码中的历史 docstring 推断为当前入口。

## 源码证据

- [src/bili_asr/cli/parser.py:11–113](../../src/bili_asr/cli/parser.py#L11)：`build_parser`。
- [src/bili_asr/cli/main.py:41–106](../../src/bili_asr/cli/main.py#L41)：`_main`。
- [src/bili_asr/cli/registry.py:1–54](../../src/bili_asr/cli/registry.py#L1)：`模块入口`。
- [src/bili_asr/artifact_root.py:1–60](../../src/bili_asr/artifact_root.py#L1)：`模块入口`。
- [src/bili_asr/archive_maintenance.py:64–137](../../src/bili_asr/archive_maintenance.py#L64)：`archive_access`。
- [src/bili_asr/cli/workflow.py:147–353](../../src/bili_asr/cli/workflow.py#L147)：`_execute_workflow`。
- [src/bili_asr/cli/publication.py:74–135](../../src/bili_asr/cli/publication.py#L74)：`_cmd_publication`。
- [src/bili_asr/storage/database.py:508–532](../../src/bili_asr/storage/database.py#L508)：`initialize_schema`。
- [src/bili_asr/storage/database.py:549–567](../../src/bili_asr/storage/database.py#L549)：`open_database`。
