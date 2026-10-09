# 公开、未发布预览与私有审阅三种导出

源码基线：main `48b31843510e5b1d78ee4f1448cec6dee7ab2296`。

[交互时序图](12-reader-private-export.html) · [Archify 规格](12-reader-private-export.json) · [全部时序图](../architecture-sequences.md)

## 调用顺序与条件分支

```mermaid
sequenceDiagram
    autonumber
    participant cli as 导出命令
    participant exporter as 稿件导出器
    participant db as 只读一致性快照
    participant artifacts as 已登记原稿字节
    participant snapshot as 受管理目录发布
    participant consumer as 站点或审核者
    cli->>exporter: 明确选择导出类型
    exporter->>snapshot: 输出路径、链接/junction、未知文件及受管理目录归属先检查
    exporter->>db: 开始只读 snapshot
    alt publication export
    exporter->>db: 额外拒绝 published release 无匹配 head；坏关系不得被 JOIN 隐藏
    exporter->>artifacts: 精确 approved edition/review/hash、来源、模板、事件、path 与字节；对应 revision 的原始 review.md
    exporter->>exporter: schemaVersion 2；articles/part-ID/publish.md + review.md；reviewFile/hash 独立
    else publication export-drafts
    exporter->>db: 验证每个 head；仅当前 edition 且从未产生任何状态的 release
    exporter->>artifacts: 验证 AI 双稿与基线
    exporter->>exporter: publication-draft；preview.md + 原始 review.md；审核状态与准确内容身份
    else editorial export
    exporter->>db: 两者必须配对；读取父版、当前 review 行、完整 events 与冻结 AI 配置
    exporter->>artifacts: 读取固定 AI 双稿
    exporter->>exporter: edition.md/json、review.json、相对 AI 与父版的全内容 differences patches
    end
    exporter->>db: 结束读事务
    alt 任一内容或关系损坏
    exporter->>cli: 不生成部分 catalog；先前输出保留到新快照发布阶段
    else 全部验证通过
    exporter->>snapshot: 发布完整 files 集合
    snapshot->>snapshot: 校验旧受管快照；恢复已记录中断；完整 staging + manifest + snapshot digest
    snapshot->>snapshot: old→backup、stage→output、日志恢复；输出可短暂不可用
    snapshot-->>cli: 返回快照身份
    consumer->>snapshot: 阅读站实现不在本仓库；公开/预览契约分开；私有父目录不部署
    end
```

## 边界与恢复

- 读者 review.md 是 AI 初稿的原文与疑点参照，不是人工审核记录；编辑后的正文可能与它不同。
- 公开/预览均不包含 actor、审核 events、请求配置与私有差异；私有包始终另行显式导出。
- withdraw 修改 DB head；已导出或已部署副本需要再次导出和刷新，本仓库不自动发布远端站点。

## 源码证据

- [src/bili_asr/cli/publication.py:74–135](../../src/bili_asr/cli/publication.py#L74)：`_cmd_publication`。
- [src/bili_asr/cli/editorial.py:14–27](../../src/bili_asr/cli/editorial.py#L14)：`_cmd_editorial`。
- [src/bili_asr/publication_export.py:61–105](../../src/bili_asr/publication_export.py#L61)：`export_publications`。
- [src/bili_asr/publication_export.py:108–181](../../src/bili_asr/publication_export.py#L108)：`export_publication_drafts`。
- [src/bili_asr/publication_export.py:193–271](../../src/bili_asr/publication_export.py#L193)：`export_editorial`。
- [src/bili_asr/publication_export.py:19–27](../../src/bili_asr/publication_export.py#L19)：`_read_snapshot`。
- [src/bili_asr/publication.py:298–304](../../src/bili_asr/publication.py#L298)：`verify_release`。
- [src/bili_asr/publication.py:142–165](../../src/bili_asr/publication.py#L142)：`get_ai_artifacts`。
- [src/bili_asr/export_snapshot.py:367–444](../../src/bili_asr/export_snapshot.py#L367)：`replace_snapshot`。
- [src/bili_asr/publication_export.py:1–60](../../src/bili_asr/publication_export.py#L1)：`模块入口`。
