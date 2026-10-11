# 编辑系列 CAS、导出绑定与静态消费

源码基线：`4f073318c944add37417416155845e55247f9bc1`；核对日期：2026-10-11（Asia/Hong_Kong）。

[交互图](29-publication-series.html) · [JSON 规格](29-publication-series.json) · [时序索引](../architecture-sequences.md)

```mermaid
sequenceDiagram
    autonumber
    participant op as 人工编辑
    participant series as 系列策略
    participant files as 私有编辑 JSON
    participant exporter as 公开或预览导出
    participant site as 静态消费契约
op->>series: validate/show；明确系列成员、顺序、证据与 knownMissing
    series->>files: 严格 UTF-8/重复 key/字段/语义检查；不打开归档 DB
    op->>series: edit 完整替换、actor 与 expected 原文件 SHA 或 new
    series->>files: 独占文件锁、摘要 CAS、暂存 fsync 与原子替换
    series-->>op: 新摘要；替换后同步失败须重新读取现状
    op->>exporter: 显式 series-file 与 public/drafts 范围
    exporter->>files: 冻结并校验私有系列源
    exporter->>series: 按导出文章与稿件类型绑定；不猜测关系或补成员
    series-->>exporter: series.json；私有证据和操作者不公开
    exporter->>site: manifest 登记准确系列成员、大小和 hash
    site-->>op: 阅读站按契约消费；站点部署属于外部仓库
```

## 边界与恢复

- 系列是独立编辑元数据，不改既有正文、edition/release 或来源事实。
- 编号间隔不自动表示缺失，只有编辑确认的 knownMissing 可输出。

## 源码证据

- [src/bili_asr/cli/publication.py:1](../../src/bili_asr/cli/publication.py#L1)：模块定义。
- [src/bili_asr/publication_series.py:133](../../src/bili_asr/publication_series.py#L133)：edit_series。
- [src/bili_asr/publication_series.py:174](../../src/bili_asr/publication_series.py#L174)：project_series。
- [src/bili_asr/publication_series.py:48](../../src/bili_asr/publication_series.py#L48)：read_series_with_sha256。
- [src/bili_asr/publication_export.py:1](../../src/bili_asr/publication_export.py#L1)：模块定义。
- [src/bili_asr/contracts/schemas/publication-series.schema.json:1](../../src/bili_asr/contracts/schemas/publication-series.schema.json#L1)：模块定义。
