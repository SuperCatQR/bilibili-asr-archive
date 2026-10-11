# 架构与时序图验证记录

核对日期：2026-10-11（Asia/Hong_Kong）。当前源码基线：`4f073318c944add37417416155845e55247f9bc1`。本轮针对最新 main 重新核对 parser/registry、提交源码文件树、契约资源、来源/产物/ASR/出版实现，并更新当前架构文本与 30 个时序流程。机器记录见 [architecture-validation.json](architecture-validation.json)，覆盖见 [architecture-coverage.json](architecture-coverage.json)。

## Archify 交付

Archify 3.0.1 对当前工作区存在的架构图和时序图执行 finalize；规格、HTML、deliver、strict check 和真实 Chrome browser-check 的摘要与 SHA-256 写入机器记录。全景图和 AI 专题图的 browser-check 均通过；时序图 01–30 的现有 HTML 均由对应规格生成并完成自动门禁。截图证据保留在忽略目录 `.archify/refresh-20261011/`，本页不声称人工逐屏视觉验收。

全景图的自动检查建议继续检查路由交叉/绕路（当前图保留语义完整性，未删除关系以降低诊断）；AI 专题图保留若干长路线建议。全景图实际查看了 1440×900 light 首屏，记录为 partial；其余图为 not_requested。没有逐屏检查完整长页，不声称完整目视验收。

## 实现核对范围

- CLI parser 与 registry：20 个顶层命令、86 条实际叶命令，含 `artifacts`、`remote`、`reference`、`source`、`workflow supervise/role`、契约升级和显式来源路径。
- 来源：universal-v2 的中立 source identity、Bilibili/YouTube adapter、字段观察、字幕候选预算与失败证据。
- 执行：claim 前 candidate/输入/pin/空间/GPU 准入，父进程租约 fence，persistent/legacy/oneshot 会话，单任务 ASR/alignment batching。
- 产物：完整组、catalog/target/replica、transfer/release journal、online policy、consumer pin、外置对象精确恢复。
- 契约与恢复：离线 Schema registry、upgrade path、新目标保真安装、完整 snapshot、非自包含 reference backup、旧正文导入与系列导出。

## 验证边界

文档检查不替代真实网络、GPU/CPU 性能、付费模型、完整快照生产往返、远程 SSH 可用性、阅读站部署或人工语义审核。历史测试记录仍保留原提交和运行日期；本轮没有把历史测试数字改写成当前执行结果。
