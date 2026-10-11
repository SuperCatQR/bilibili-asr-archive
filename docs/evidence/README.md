# 历史验收与实测记录

这里保存有独立复现价值的历史行为证据。每份记录仍绑定原源码提交、运行日期与环境，不能据此报告当前生产进度或当前版本测试结果。当前架构图的规格、产物哈希与浏览器检查统一见 [architecture-validation.md](../architecture-validation.md)。

| 记录 | 范围 |
| --- | --- |
| [归档运行时 · 2026-10-10](archive-runtime-validation-2026-10-10.md) · [机器记录](archive-runtime-validation-2026-10-10.json) | 全量回归、覆盖率、隔离安装、快照往返、失败/跳过与构建摘要 |
| [契约治理 · 2026-10-11](contract-governance-validation-2026-10-11.md) · [机器记录](contract-governance-validation-2026-10-11.json) | 固定指纹、冻结历史样本、Schema 边界、独立审查和反向条件实验 |
| [Catalog Schema · 2026-10-10](catalog-schema-checks-2026-10-10.json) | 当时 16 份闭环导出及旧版示例的结构校验 |

生产异常、GPU 和性能实测继续保留在各自原文档中，由 [文档入口](../README.md) 按主题导航；这些记录含独有环境限制、失败尝试与用户约束。旧实施前计划、重复图及被替代的图表收据已删除，其历史仍可通过 Git 查询。
