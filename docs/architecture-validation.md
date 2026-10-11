# 架构与时序图验证记录

核对日期：2026-10-11（Asia/Hong_Kong）。当前源码基线：`378f415ac5bf2a47de9137ee593f201e86827d43`。本轮整合当前主分支文档与图表目录，统一更新全景图、AI/出版专题图、契约治理图与 31 个时序流程，共 34 张交互图。机器记录见 [architecture-validation.json](architecture-validation.json)，覆盖见 [architecture-coverage.json](architecture-coverage.json)。

## Archify 交付

Archify 3.0.1 对全部 34 份当前 JSON 执行 `finalize --repo-root . --quality showcase`，重新生成对应 HTML。每张图均通过 9/9 showcase 校验、0 errors、0 warnings，并完成 deliver、strict check 和真实 Chrome browser-check。机器记录保存规格与生成文件的 SHA-256，已核对收据摘要与磁盘上的实际字节一致。完整收据保留在忽略目录 `.archify/docs-cleanup-20261011/`，各候选修正的收据使用独立子目录。

全景图仍有 22 处自动路由交叉及部分绕路建议。按照工具提示尝试了一次节点位置调整，交叉增加到 27，因此恢复原布局并重新通过完整门禁。AI 专题图保留部分弯折建议。自动检查通过不代表完整目视验收；本轮全部图的人工视觉检查记为 `not_requested`，没有复用旧版本首屏截图作新版本证据。

## 实现核对范围

- CLI parser 与 registry：20 个顶层命令、86 条实际叶命令；包含历史回填的 `--preserve-transcript` / `--dry-run`、文章补充的 `--field description` 和新导出 profile。
- 提交源码：204 个 Python 模块、11 个 SQL 资源、50 项稳定契约、25 份 JSON Schema；源码节点引用按固定提交核对，变化的函数范围与模块末尾同步到当前行号。
- 来源与转写包：六个平铺来源字段、同一只读快照批量查询、`source-metadata-v1` 发布时快照、新包 v3 与旧包 v2 兼容核验。
- 历史包回填：原 publication/转录围栏、旧 marker 和成员验证、不可变完整组保留、原 raw/provenance/coverage/character timing、安装前复验与失败路径。
- 文章补充：已保留旧正文的 v2 资格、逐字段成功观察、整批来源和双头事务校验、原文保留、待审子版、幂等回执与重新审核。
- 协议与消费者：导出集合和 profile 对 catalog 版本的选择，`universal-origin-v2` 的 origins v2 / manifest v3，旧 profile 保持与新简介补充拒绝规则，当前 Reader 的升级边界。
- 既有执行、产物、迁移与恢复路径：租约/取消、ASR 会话、在线副本、snapshot/reference backup、旧正文导入与系列出口继续保留，并重新核对源码链接。

本轮检查 Markdown 本地链接、源码行号、31 个 Mermaid 时序分支的结构平衡，以及 `git diff --check`。各项实际检查数量写入机器记录。34 张图共核对 402 处固定源码引用，覆盖 298 个去重范围、133 个路径和 246 个精确 AST 函数/类范围。独立语义审查同步修正了校对 API provider、18 个数据库指纹组合和契约计数；现行图支持 DeepSeek 与 OpenCode Go 的冻结 endpoint 选择。

## 验证边界

此次更新范围是文档与图，不替代真实网络、GPU/CPU 性能、付费模型、完整快照生产往返、远程 SSH 可用性、生产迁移或阅读站部署。外部 Reader 对新 profile 的支持仍需另行实现。独有历史测试已归入 [evidence/README.md](evidence/README.md)，继续保留其原提交、运行日期与验收范围。过时实施计划、重复图及旧图收据已删除；其中仍适用的操作说明已合入功能指南。
