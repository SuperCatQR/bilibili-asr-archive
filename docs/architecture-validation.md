# 架构与时序图验证记录

核对日期：2026-10-12（Asia/Hong_Kong）。源码清单和本轮受影响图绑定独立分支 `codex/workflow-failure-recovery` 的 `813982215dab490ca462f991a5b440bd2ef19621`，并不表示修复已合并或部署。机器记录见 [architecture-validation.json](architecture-validation.json)，覆盖见 [architecture-coverage.json](architecture-coverage.json)。

## 本轮源码与图表身份

本轮修复 #365–367：纯错误政策、安全状态投影、显式外部控制和受保护重排，以及编辑/发布错误的稳定诊断。源码清单实际核对 209 个 Python 模块、11 份 SQL、53 项稳定契约、25 份 Schema、20 个顶层命令和 86 条叶命令。基础 SQL 无变更。

35 张交互图中，19 张受影响既有图重新绑定本轮源码并生成 HTML；新增流程 32 展示失败状态和重排。其余 15 张未改变规格/HTML，保留 `378f415ac5bf2a47de9137ee593f201e86827d43` 和 2026-10-11 的原收据身份；逐图记录日期、源码、哈希和 gate，不把旧收据记为新验收。下方历史记录保留其原范围。

Archify 3.0.1 对本轮 20 张图完成 `finalize --repo-root . --quality showcase`，每张 9/9、0 errors、0 warnings，validate/deliver/strict check/browser-check 全部 pass。浏览器检查包含 1440×900 与 2048×1320 的 light/dark；没有要求或声称完整人工视觉检查，`visual_review=not_requested`。回执在忽略目录 `.archify/workflow-failure-20261012/`，记录内不包含本机绝对路径。

全景图尝试一次仅节点位置的布局调整，交叉从 22 增至 27，恢复原布局后重新 finalize，仍保留 22 处交叉与部分绕路建议。AI 专题有六条弯折建议。04 新增重试角色导致列宽检查失败，最终 HTML 将 Executor 与重试用例在“执行与重试”列分段展开，并在卡片说明两个不同用例；完整 Mermaid 保留参与者边界，流程 32 单独展开重试职责。没有缩小文字或隐藏消息。

本轮核对 35 份规格/产物的实际 SHA-256 与新收据或保留记录一致；420 处固定源码引用范围、1,044 个文档本地链接和 32 个 Mermaid 分支平衡通过。源码行范围针对各图实际绑定提交检查，其他图不会因为当前文件行号变化自动获得新身份。

## 实现验证

最终固定源码扩展回归 240 passed、1 skipped（51.42 秒）；此前相关集 229 passed，包括失败分类、状态口径/窗口/安全诊断、控制证据、预算/退避、hold、精确 override、控制文件与任务变化回滚、重排至成功、取消/租约围栏、校对修复、发布质量以及契约登记。子代理交叉审查覆盖正确性、可读性、架构、安全和性能；隔离 mutation 检查确认移除 hold 检查、误允许 402/源质量/修订错误会被回归阻止。

`ruff check src scripts tests --select E9`、全部变更源码 lint、compileall、`uv lock --check --default-index https://pypi.org/simple`、53/25 契约镜像检查通过。`uv build` 被本机 uv cache 文件权限阻断；使用同一 setuptools 后端直接构建 wheel 成功，wheel 含全部五个新模块与 25 份 Schema。

全量原始结果为 3132 passed、19 failed、12 errors、82 skipped、2 warnings（1084.77 秒）。一项旧 retry 预期已按新准入规则更新并通过，一项 upgrade 在执行时检测到源码变化后固定复验通过；其他为 Windows 权限/路径/锁及安装临时目录环境问题。另一轮相关集出现既有取消/心跳诊断竞争，单独和最终扩展集复验通过，仍保留观察；详见 [实现验收记录](evidence/workflow-failure-recovery-2026-10-12.md)。不声明完整套件通过。

## 使用与验证边界

[失败恢复操作说明](operations/workflow-failures.md)明确要求外部控制证据：未提供/不完整时状态保持 unknown，并拒绝重排；hold、预算、退避和活动替代任务不能由人工 override 绕过。控制文件所有者须串行化 hold/ledger 更新和重试调用；摘要复验没有 SQLite/文件跨介质原子性。

没有调用生产网络、GPU、付费模型、部署或修改外部控制文件。旧库级手动工具保留兼容能力，生产控制器须显式迁移调用点，升级 wheel 不等于控制脚本已采用政策。普通 retry 延续原冻结输入；新输入 repair 保留旧失败、attempt、模型响应及 holds。文档和离线回归不证明生产异常已恢复，也不替代源音频与语义审核。

---

# 2026-10-11 历史基线验收

核对日期：2026-10-11（Asia/Hong_Kong）。当时源码基线：`378f415ac5bf2a47de9137ee593f201e86827d43`。本轮整合当前主分支文档与图表目录，统一更新全景图、AI/出版专题图、契约治理图与 31 个时序流程，共 34 张交互图。机器记录见 [architecture-validation.json](architecture-validation.json)，覆盖见 [architecture-coverage.json](architecture-coverage.json)。

## Archify 交付

Archify 3.0.1 对当时全部 34 份 JSON 执行 `finalize --repo-root . --quality showcase`，重新生成对应 HTML。每张图均通过 9/9 showcase 校验、0 errors、0 warnings，并完成 deliver、strict check 和真实 Chrome browser-check。机器记录保存规格与生成文件的 SHA-256，已核对收据摘要与磁盘上的实际字节一致。完整收据保留在忽略目录 `.archify/docs-cleanup-20261011/`，各候选修正的收据使用独立子目录。

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
