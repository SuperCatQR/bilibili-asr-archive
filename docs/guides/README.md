# 使用指南

[返回文档入口](../README.md)。建议按来源采集 → 任务规划 → 校对 → 审核发布的顺序阅读；配置 ASR 或维护归档时分别转到 [ASR](../asr/README.md) 和 [运维](../operations/README.md)。

| 阶段 | 文档 | 内容 |
| --- | --- | --- |
| 来源 | [采集适配器](source-adapters.md) | Bilibili/YouTube、字段观察、字幕候选与失败恢复 |
| 来源 | [来源元数据与历史包回填](source-metadata.md) | 简介、来源字段、导出和保留原转录的 bundle 刷新 |
| 查询 | [元数据与转录搜索](metadata-search.md) | 搜索范围、排序、日期和 JSON 输出 |
| 任务 | [视频与分 P 选择](workflow-selection.md) | 全集验证、选择条件与幂等规划 |
| 任务 | [取消任务](workflow-cancellation.md) | 取消、租约、提交保护与依赖边界 |
| 转录 | [WebVTT 与归档包](webvtt.md) | cue 规则、v3 完整包与旧包兼容 |
| 校对 | [AI 校对](ai-proofreading.md) | 模型配置、执行、失败恢复与确定性重渲染 |
| 出版 | [编辑、审核与发布](publication.md) | 完整 edition、准确内容审核、release、撤回与导出 |
| 出版 | [阅读系列](publication-series.md) | 人工确认的系列、并发编辑与消费契约 |
| 旧稿 | [保留旧正文导入](preserved-body-import.md) | 离线计划、原字节保留、回执与独立审核 |
| 旧稿 | [分 P 标题补充](source-part-title-supplement.md) | 本地已采集标题、冻结证据与新待审版 |
| 旧稿 | [文章简介补充](source-description-supplement.md) | 逐字段来源证据、原正文保留及新导出 profile |

存储结构的字段定义见 [SQLite 参考](../metadata-storage.md)，导出格式定义见 [契约镜像](../contracts/README.md)。
