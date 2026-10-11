# 读取投影、覆盖、完整性、普通导出与去重

源码基线：`4f073318c944add37417416155845e55247f9bc1`；核对日期：2026-10-11（Asia/Hong_Kong）。

[交互时序图](13-projection-verify.html) · [Archify 规格](13-projection-verify.json) · [全部时序图](../architecture-sequences.md)

## 调用顺序与条件分支

```mermaid
sequenceDiagram
    autonumber
    participant cli as 查询命令
    participant projection as 工作流读取投影
    participant session as READ/RUNTIME session
    participant db as 持久事实只读库
    participant checker as 验证与报告
    participant files as 音频与 bundle
    cli->>projection: coverage/export/verify 共享投影入口；status/runs 的 DB 汇总另走元数据 repository
    projection->>session: 打开 mode=ro/query_only；共享维护访问
    session->>db: 检查 RUNTIME 契约，无 DDL；BEGIN 一次读快照
    loop 每批最多 256 个 active part
    projection->>db: part ID keyset + IN 集合查所有版本、最新 publication、所选 segments
    db-->>projection: 有界批数据；latest 按 published_at/publication_id
    projection->>projection: choose_transcript 公共总排序算 preferred；published 身份独立
    projection->>projection: LEFT JOIN 保留悬空/错 part 声明；publication_error 固定代码，正文置空
    end
    alt 已有 publication
    projection->>projection: 兼容 transcript 字段/with-text 使用 published；publication_current 表示与 preferred 是否一致
    else 尚未 publication
    projection->>projection: 兼容字段使用 preferred；无转录则 meta_ok
    end
    alt 验证实体文件
    projection->>files: 文件集合与摘要完整才能 archived
    else 保留发布声明作报告
    projection->>projection: verify_artifacts=False；坏 bundle 不能静默降级成 backlog
    end
    projection->>session: close；释放读快照和连接访问 lease
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
- writer 与 projection 复用 transcript_selection：CC > AI > ASR、family zh/en/其余、语言代码升序、同来源语言 version 降序。中文变体代码先于版本比较。
- preferred_* 与 published_* 分离；新版本尚未发布时，旧完好 publication 继续 archived/complete，导出保留已发布文本。
- artifact_json 必须有完整路径； malformed JSON/缺键不回退默认路径。最新 publication 的坏 bundle 不能由同 slot 的历史声明掩盖。
- producer 在保护事务中以 max(墙钟秒, part 已有 published_at 最大值 + 1) 写入单调提交时间，保证同秒重发布旧身份的 upsert 排在最新；突发值可短暂领先墙钟，排序语义不等于精确墙钟时间。
- LEFT JOIN 保留损坏的 publication 关系；published_transcript_missing/part_mismatch 是 bounded publication_error，with-text 保持空，不能取 preferred 或另一 part 的正文。coverage/IntegrityVerifier 按数据库关系 defect 报告，字节完整也不计 complete。
- 每批最多 256 part 的集合查询消除逐 part 的 N+1；返回 dict 恢复 pubdate 降序、BVID/page 顺序。with-text 也批量读取有效身份的 segments。
- 有界验证与 publication supervisor 代码仍保留，但没有据此虚构当前 CLI 的隐式守护链。
- dedup report 仅报告数据库中已有的重复内容身份，不选择 canonical、不合并或改写来源，也不确认磁盘文件此刻的内容。

## 源码证据

- [src/bili_asr/cli/ops.py:150](../../src/bili_asr/cli/ops.py#L150)：_cmd_verify。
- [src/bili_asr/export.py:396](../../src/bili_asr/export.py#L396)：export_records。
- [src/bili_asr/cli/dedup.py:19](../../src/bili_asr/cli/dedup.py#L19)：_cmd_dedup。
- [src/bili_asr/services/workflow_projection.py:126](../../src/bili_asr/services/workflow_projection.py#L126)：workflow_records。
- [src/bili_asr/transcript_selection.py:40](../../src/bili_asr/transcript_selection.py#L40)：choose_transcript。
- [src/bili_asr/archive_session.py:64](../../src/bili_asr/archive_session.py#L64)：ArchiveSession。
- [src/bili_asr/services/workflow_projection.py:30](../../src/bili_asr/services/workflow_projection.py#L30)：_part_batches。
- [src/bili_asr/services/workflow_projection.py:56](../../src/bili_asr/services/workflow_projection.py#L56)：_preferred_transcripts。
- [src/bili_asr/services/workflow_projection.py:72](../../src/bili_asr/services/workflow_projection.py#L72)：_latest_publications。
- [src/bili_asr/coverage_report.py:71](../../src/bili_asr/coverage_report.py#L71)：CoverageReport。
- [src/bili_asr/integrity.py:52](../../src/bili_asr/integrity.py#L52)：IntegrityVerifier。
- [src/bili_asr/services/bundle_verification.py:62](../../src/bili_asr/services/bundle_verification.py#L62)：verify_bundle。
- [src/bili_asr/archive.py:253](../../src/bili_asr/archive.py#L253)：archive_bundle_complete。
- [src/bili_asr/dedup.py:1](../../src/bili_asr/dedup.py#L1)：模块定义。

## 当前通用来源与驻留

universal-v2 使用中立 source identity 与来源查询，legacy 索引仍按原形状读取。生产完成不因正常外置降为未完成；storage availability/readiness 单独报告，默认读取不探测外部目标或下载数据。
