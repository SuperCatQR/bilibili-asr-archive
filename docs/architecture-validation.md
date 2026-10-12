# 架构与时序图验证记录

核对日期：2026-10-12（Asia/Hong_Kong）。固定源码 `3ed823c961736378d8408bba5f0535b03e0046e0` 来自独立分支 `codex/issue-reliability-metadata`，包含 #349/#350/#361 实现；不表示远端 main 或生产已更新。3 张架构图和 32 个时序流程，共 35 张图统一绑定该源码。机器记录见 [architecture-validation.json](architecture-validation.json)，覆盖见 [architecture-coverage.json](architecture-coverage.json)。

## 生成与源码检查

Archify 3.0.1 对全部 35 份最终 JSON 执行 `finalize --repo-root . --quality showcase`，每份均完成 validate、deliver、strict check 和真实 Chrome browser-check。逐份记录规格/HTML SHA-256 并核对最终收据与磁盘字节；浏览器尺寸和主题来自每张图自己的新回执。生成记录保留在忽略的 `.archify/issue-reliability-20261012/release/` 与 `release-sequences/`。JSON 保持原有 LF 字节约定，生成 HTML 未手工编辑。

全景图保留 22 处路由交叉及绕路建议。按建议尝试了一次位置调整，但候选未通过布局检查，已恢复原布局并重新通过完整门禁；没有删除关系或缩短操作语义。AI 专题图保留 6 处绕路建议。自动浏览器检查与目视验收分别记录，本轮全部图的 perceptual visual review 为 `not_requested`。

从实际 parser/registry 核对 21 个顶层命令、88 条叶命令；从固定提交文件树核对 209 个 Python 模块。数据库资源与稳定契约未变：11 份 SQL 资源、50 项稳定契约、25 份 JSON Schema。新增维护器复用现有工作流与 editorial 审计表，不在运行中安装 DDL。所有图中源码范围逐项按固定 Git blob 核验，受影响符号按 AST 重定位；Markdown 本地链接、源码行号和完整 Mermaid 分支平衡检查数量记录在机器清单。

## 实现与回归验证

- 归档主要相关回归：238 passed、3 skipped，覆盖请求、恢复、历史输入、来源元数据、出版回填、会话与架构边界。维护最终独立回归 23 passed；契约发布 gate 26 passed。
- workflow 与升级结果复用补充检查的 45 个用例通过、1 skipped。两项 Windows 默认 GBK 解码失败使用与 CI 相同的 `PYTHONUTF8=1` 重查通过。退休模块测试由既有 collect_ignore 排除，不计入本轮已收集验证范围。
- Ruff 阻塞 E9 全源/脚本/测试通过；compileall 使用外部 `PYTHONPYCACHEPREFIX` 通过，避免 Windows 受管工作树缓存目录权限问题。契约镜像核对通过：50 contracts、25 schemas。测试使用工作区外 TEMP、禁用 pytest cacheprovider，未绕过业务断言或强制退出测试进程。
- 持久预算 fence、maintenance holds、Reader observedAt 绑定分别做过条件变异：回归测试发现错误，随后恢复原逻辑并跑绿。
- Reader 配套提交 `4a5933c743a05d067ce719b63c04cb9dfbc5ab6c` 的 184 个测试通过；真实生产者生成的 v2 fixture 构建和 320/390/1440 Chromium 简介展示检查通过。归档导出政策及旧 v1 格式保持，阅读站新增准确 v1/v2 tuple 和字段证据验证。

本轮五轴审查发现并修正了旧请求策略升级、缓存坏响应重放、调用完成时间被覆盖、耗尽块优先级、泛化 HTTP 错误误重试、首次退避 anchor、状态文件别名与维护健康前置检查等边界。成功块与旧 attempt 保留；物理调用和重排预算分别持久累计，未知发送不能获得免费预算。

## 交付边界

当前是两个本地独立分支的实现与文档交付。未执行生产 timer 启用、生产重排、历史简介批量回填、真实付费 API、OpenCode Go 参数生效测试或 FP8 GPU 验收。维护上线须按 [交接手册](operations/retry-maintenance.md)保留旧 holds/累计 ledger 并停用旧 retry writer。#302 FP8、原生 v2 与单篇多字段简介补齐继续按明确范围延期。

历史验收仍见 [evidence/README.md](evidence/README.md)，保留各自原提交、日期和运行边界。新的浏览器回执不替代人工语义审核、完整生产往返、GPU 性能、远程 SSH 或外部部署验证。
