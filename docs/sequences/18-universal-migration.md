# 旧归档显式迁移：保真、恢复审计与切换验证

源码固定于提交 `857906d3b3c54b31fd9bc0ba94b84618f68cd6f3`；旧源的独立读取契约仍固定于 `9b289570494b5e8f7cc564a7eaa5b2eb2c28c3ad`，保真基准包由变更前的 writer 生成。

[交互时序图](18-universal-migration.html) · [完整 Archify 规格](18-universal-migration.json) · [本轮实现说明](../issues-implementation.md)

```mermaid
sequenceDiagram
    autonumber
    participant CLI as archive CLI
    participant M as archive_migration
    participant P as 固定旧源预检
    participant S as 旧源 DB
    participant T as 独立 v2 staging DB
    participant F as 源文件与目标目录
    CLI->>M: migrate；显式 source-root / source-snapshot、target-root
    M->>M: 拒绝链接、重叠根；按确定顺序持有源和目标维护锁
    M->>P: migration_preflight
    P->>S: immutable/query_only；固定 DDL、integrity、FK 与完整历史
    alt 有非空 WAL/journal 或有效/缺失 lease
        P-->>CLI: 拒绝；要求停止 writer 并 checkpoint
    else 源为停止且已 checkpoint 的支持版本
        P->>S: 流式读取38张表，记录rowid、类型、原始TEXT/BLOB摘要
        P->>F: 全量清单、读前后身份、所有历史引用与完整marker核验
        P-->>M: source fingerprint、逐表/文件清单、恢复候选
    end
    alt dry-run
        M-->>CLI: 只返回计划，不创建目标
    else 同源指纹的已完成目标
        M->>T: migration-check
        M-->>CLI: reused=true；不重复转换
    else 新的空目标，且空间和expected-fingerprint检查通过
        M->>S: 只读一致SQLite backup到调用专属临时目录
        M->>T: 显式bootstrap universal-v2
        loop 每张旧权威表
            M->>S: 读取有效rowid及逐单元格SQLite类型/原始字节
            M->>T: 插入原rowid；TEXT通过CAST原样绑定
            M->>T: 原字段逐表摘要必须与源一致
        end
        M->>T: 为旧input/content注册不可变version=1；检查FK
        M->>F: 全部产物流式复制到staging，fsync并比对size/SHA
        M->>T: 校验目标schema和所有产物引用
        M->>T: 仅恢复已确认中断的目标job/attempt/run/model call
        T-->>M: 每个允许变更的before/after、identity、reason
        M->>F: 写ID映射、typed导入行账本及各自hash
        M->>T: 写immutable migration_records
        M->>F: 写精确JSON迁移报告，flush/fsync
        M->>T: 重验schema、全部产物及审计引用
        M->>P: 再次预检；源fingerprint仍须一致
        M->>F: fsync DB和目录；检查空目标后rename安装
        alt 安装后父目录同步失败
            M-->>CLI: installed=true + target_parent_directory_sync_failed
        else 同步成功
            M-->>CLI: 完成报告，source_unchanged=true
        end
    end
    CLI->>M: 切换后可重复运行migration-check
    M->>T: 只读检查唯一immutable报告及身份
    M->>F: 磁盘报告精确字节、ID映射和typed行账本摘要
    M->>T: 按导入rowid校验冻结列，新增行不影响基线
    M->>F: 音频、双稿、全部历史release原始字节必须不变
    M->>T: 当前元数据/head/控制状态变化按表报告
    M-->>CLI: valid、imported_baseline_matches、current_fact_deltas、mutable_artifact_deltas
```

迁移只恢复 staging 目标。旧源不会被升级、恢复任务、重编码 JSON 或清理历史；已完成和取消的旧历史在搬运时保持原值。源 writer 必须已经停止，维护锁无法代替停止不遵守此协议的旧进程。任一安装前步骤失败仅清理调用专属临时目录，不发布部分目标。

持续 checker 保护冻结权威行、原始 payload 和历史文件，同时允许切换后的新行与可变事实继续演进。唯一 payload 例外是已知的规范 `publish:<part_id>` 请求：同一 part 可改为另一真实转录 ID，其他字段、JSON表示和存储类型仍受严格约束。元数据、发布 heads、调度状态、tags/依赖关系的合法变化按表计数；可变 transcript bundle 差异单独列出。ID映射、行账本和磁盘报告都是快照的必需引用，缺失或摘要不符会拒绝保存/校验。

源码证据均使用固定提交：

| 责任 | 证据 |
| --- | --- |
| 显式入口与快照迁移选项 | [cli/archive.py:25–59](https://github.com/SuperCatQR/bilibili-asr-archive/blob/857906d3b3c54b31fd9bc0ba94b84618f68cd6f3/src/bili_asr/cli/archive.py#L25-L59) |
| 固定旧源预检和停止条件 | [migration_preflight.py:119–213](https://github.com/SuperCatQR/bilibili-asr-archive/blob/857906d3b3c54b31fd9bc0ba94b84618f68cd6f3/src/bili_asr/services/migration_preflight.py#L119-L213) |
| 原始typed搬运、比对及目标恢复 | [archive_migration.py:51–128](https://github.com/SuperCatQR/bilibili-asr-archive/blob/857906d3b3c54b31fd9bc0ba94b84618f68cd6f3/src/bili_asr/services/archive_migration.py#L51-L128) |
| 导入行账本、保护策略与publish例外 | [archive_migration.py:158–297](https://github.com/SuperCatQR/bilibili-asr-archive/blob/857906d3b3c54b31fd9bc0ba94b84618f68cd6f3/src/bili_asr/services/archive_migration.py#L158-L297) |
| staging、文件复制、审计和安装 | [archive_migration.py:300–395](https://github.com/SuperCatQR/bilibili-asr-archive/blob/857906d3b3c54b31fd9bc0ba94b84618f68cd6f3/src/bili_asr/services/archive_migration.py#L300-L395) |
| 切换后只读checker | [archive_migration.py:425–474](https://github.com/SuperCatQR/bilibili-asr-archive/blob/857906d3b3c54b31fd9bc0ba94b84618f68cd6f3/src/bili_asr/services/archive_migration.py#L425-L474) |
| 快照必须携带迁移审计引用 | [storage/snapshots.py:244–351](https://github.com/SuperCatQR/bilibili-asr-archive/blob/857906d3b3c54b31fd9bc0ba94b84618f68cd6f3/src/bili_asr/storage/snapshots.py#L244-L351) |

图的验证状态见 [本轮图表验证凭据](../issue-diagram-validation/README.md)。自动化 browser-check 与视觉人工审阅分开记录。
