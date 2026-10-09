# 固定旧源迁移预检与完整历史校验

源码基线：main `48b31843510e5b1d78ee4f1448cec6dee7ab2296`。

[交互时序图](17-migration-preflight.html) · [Archify 规格](17-migration-preflight.json) · [全部时序图](../architecture-sequences.md) · [操作指南](../archive-migration-preflight.md)

## 调用顺序与条件分支

```mermaid
sequenceDiagram
    autonumber
    participant cli as archive CLI
    participant service as migration_preflight
    participant lock as 源维护独占锁
    participant legacy as 固定旧源契约/身份校验
    participant files as 源 DB 与全部产物文件
    cli->>service: --source-root；可选 --source-artifact-root；忽略当前运行根环境配置
    service->>files: 检查 lexical 祖先/目录/DB 普通文件、根重叠规则
    service->>lock: exclusive=True；create_root=False
    service->>files: 非空 WAL/journal 拒绝；记录 DB 物理身份
    service->>legacy: inspect_migration_source；mode=ro&immutable=1；query_only / trusted_schema OFF
    legacy->>legacy: integrity、固定 66 DDL 对象、完整已知 FTS 组、manuscript v1、FK
    alt 有效或缺失 lease 的 running job
    legacy-->>service: 拒绝源仍有未安全停止的任务
    else 仅过期 running 或无 running
    loop 38 张权威表按有效 rowid 顺序
    legacy->>legacy: 行数/摘要；包含 rowid、SQLite 类型、原始 TEXT/BLOB 字节
    end
    legacy-->>service: 固定契约身份、逐表指纹、派生对象、过期 running 数
    end
    service->>files: DB 全文件哈希；按规则检查根条目和五类目录
    loop 显式产物根优先、归档根回退的全部物理文件
    files->>files: 拒绝链接/暂存/不可移植路径/大小写碰撞；读前/open/读后身份与流式哈希
    alt 相同 key 已选中
    files-->>service: 记录遮蔽副本与 selected_base；副本仍纳入变化检测
    else 首次 key
    files-->>service: 登记 selected / physical / identity
    end
    end
    service->>legacy: 第二个 immutable 只读连接；legacy_artifact_references
    legacy->>legacy: 所有冻结输入、revision 内容哈希、job/input/part 与源身份
    legacy->>legacy: 已登记双稿必须配对；固定 ai-draft-v1 重新渲染摘要
    legacy->>legacy: edition 内容/父版/审核事件完整链、actor/note、draft/release head
    legacy->>legacy: 全部历史 release 含替换/撤回；事件终态、固定 publish-v1 路径与字节
    legacy-->>service: 音频/成功 attempt、bundle/marker、双稿、历史 release 全部引用
    service->>files: 引用必须存在且大小/hash 相符；marker 必须准确声明五文件
    service->>legacy: 读取未完成 ingestion/acquisition run 与 model call 计数
    service->>files: 再扫描集合、物理身份、DB/sidecar 与排除项，变化即失败
    alt 全部校验通过
    service->>service: 计算 contract + DB hash + 去 base 的 selected files 源 fingerprint
    service->>lock: 上下文释放源锁
    service-->>cli: valid=true；表/文件/遮蔽/排除/候选报告；JSON/text；退出 0
    else 任一阶段失败（立即中止，后续动作不执行）
    opt 已成功获取源锁
    service->>lock: 异常上下文释放源锁
    end
    service-->>cli: 有界 ValueError/OSError 诊断；stderr；退出 1
    end
```

## 边界与恢复

- 操作者必须停止全部 writer 并完成 checkpoint；非空 WAL/journal、有效或缺失租约的 running job 拒绝。
- 旧源契约固定于 9b28957；运行架构证据固定于当前 main。immutable / query_only 不调用当前 initializer。
- 服务持有源独占维护锁；只报告恢复候选，不恢复、不转换、不创建目标。锁协调文件位于根旁。
- DDL / integrity / FK / manuscript v1；38 表逐行包含 rowid、SQLite 类型与原始 TEXT/BLOB 字节，已知完整 FTS 组归类为派生缓存。
- 校验所有 input/revision 身份与 job/part 绑定；双稿配对和 ai-draft-v1 渲染摘要；edition/父版/准确审核事件链与双 head。
- 全部历史 release 状态、事件与 publish-v1 字节；音频对象/成功 attempt、bundle 五文件及 marker、AI 双稿/历史发布引用。
- 五类目录全量扫描；产物根优先旧根回退，遮蔽文件也哈希；未知/暂存/链接/路径碰撞拒绝，凭据/模型/日志/缓存仅排除名称。
- 哈希前后校验身份；完成时复查文件集合、全部物理身份、DB/sidecar 与排除项，变化即失败。
- 所有失败分支立即结束预检；图中 B01/B02 展开为互斥结果，已获取的锁由上下文释放。预检报告包含私有路径。

## 源码证据

- [src/bili_asr/cli/archive.py:25–46](../../src/bili_asr/cli/archive.py#L25)：`_cmd_archive`。
- [src/bili_asr/services/migration_preflight.py:118–212](../../src/bili_asr/services/migration_preflight.py#L118)：`migration_preflight`。
- [src/bili_asr/archive_maintenance.py:64–137](../../src/bili_asr/archive_maintenance.py#L64)：`archive_access`。
- [src/bili_asr/storage/migration_source.py:176–228](../../src/bili_asr/storage/migration_source.py#L176)：`inspect_migration_source`。
- [src/bili_asr/storage/migration_artifacts.py:147–189](../../src/bili_asr/storage/migration_artifacts.py#L147)：`_legacy_editorial_checks`。
- [src/bili_asr/storage/migration_artifacts.py:88–144](../../src/bili_asr/storage/migration_artifacts.py#L88)：`_legacy_publication_checks`。
- [src/bili_asr/services/migration_preflight.py:44–53](../../src/bili_asr/services/migration_preflight.py#L44)：`_hash_file`。
- [src/bili_asr/services/migration_preflight.py:95–115](../../src/bili_asr/services/migration_preflight.py#L95)：`_verify_markers`。
- [src/bili_asr/storage/migration_artifacts.py:192–252](../../src/bili_asr/storage/migration_artifacts.py#L192)：`_legacy_artifact_references`。
