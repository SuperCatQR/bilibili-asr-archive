# 读取投影、覆盖、完整性、普通导出与去重

源码基线：main `9b289570494b5e8f7cc564a7eaa5b2eb2c28c3ad`。

[交互时序图](13-projection-verify.html) · [Archify 规格](13-projection-verify.json) · [全部时序图](../architecture-sequences.md)

## 调用顺序与条件分支

```mermaid
sequenceDiagram
    autonumber
    participant cli as 查询命令
    participant projection as 工作流读取投影
    participant db as 持久事实只读库
    participant checker as 验证与报告
    participant files as 音频与 bundle
    cli->>projection: coverage/export/verify 共享投影入口；status/runs 的 DB 汇总另走元数据 repository
    projection->>db: active parts、择优 transcript、对应 workflow_publications
    db-->>projection: 来源版本与声明路径
    alt 验证实体文件
    projection->>files: 文件集合与摘要完整才能 archived
    else 保留发布声明作报告
    projection->>projection: verify_artifacts=False；坏 bundle 不能静默降级成 backlog
    end
    projection-->>cli: meta_ok/subtitle_done/asr_done/archived 是投影状态，不是 workflow job 状态
    alt coverage
    cli->>checker: JSON/CSV；strict 且 diagnostics 非空退出 1
    else verify
    cli->>checker: 区分 backlog 与 defect；声称已发布却缺失/损坏必须报告
    checker->>files: 校验声明 bundle 的 marker、精确文件集合、受限路径和 hash；当前 IntegrityVerifier 不遍历全部音频/AI/出版稿件
    else 普通 export
    cli->>checker: --status 与 --with-text；普通数据导出不等于 publication 快照
    else dedup report
    cli->>db: 读取精确内容身份
    cli->>db: 读取已存音频 hash/关联与 transcript 的 source/language/content_hash 分组；不重新读文件或计算摘要
    end
    checker-->>cli: 输出报告与退出码
    opt 独立有界 bundle verification 服务
    cli->>checker: 此服务保留独立调用能力，当前 workflow.publish/verify CLI 不默认调用该子进程接口
    checker->>files: timeout 终止；真实 read_bytes 扣减预算；超限/无效响应明确报错
    end
```

## 边界与恢复

- 缺失任务或尚未发布通常是 backlog；声明已发布但字节不符是 defect；不能由 absent marker 推断所有场景的同一退出码。
- writer 的语言 family 总排序与 operational projection 的中文优先启发式不同，文档不把两种实现写成完全相同。
- 有界验证与 publication supervisor 代码仍保留，但没有据此虚构当前 CLI 的隐式守护链。
- dedup report 仅报告数据库中已有的重复内容身份，不选择 canonical、不合并或改写来源，也不确认磁盘文件此刻的内容。

## 源码证据

- [src/bili_asr/cli/ops.py:135–163](../../src/bili_asr/cli/ops.py#L135)：`_cmd_verify`。
- [src/bili_asr/cli/status_cmd.py:59–73](../../src/bili_asr/cli/status_cmd.py#L59)：`_cmd_coverage`。
- [src/bili_asr/cli/dedup.py:26–43](../../src/bili_asr/cli/dedup.py#L26)：`_cmd_dedup`。
- [src/bili_asr/services/workflow_projection.py:55–158](../../src/bili_asr/services/workflow_projection.py#L55)：`workflow_records`。
- [src/bili_asr/integrity.py:52–83](../../src/bili_asr/integrity.py#L52)：`IntegrityVerifier`。
- [src/bili_asr/coverage_report.py:1–60](../../src/bili_asr/coverage_report.py#L1)：`模块入口`。
- [src/bili_asr/services/bundle_verification.py:72–160](../../src/bili_asr/services/bundle_verification.py#L72)：`verify_bundle`。
- [src/bili_asr/archive.py:254–336](../../src/bili_asr/archive.py#L254)：`archive_bundle_complete`。
- [src/bili_asr/dedup.py:1–60](../../src/bili_asr/dedup.py#L1)：`模块入口`。
