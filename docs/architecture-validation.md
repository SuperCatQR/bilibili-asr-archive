# 架构与时序图验证记录

核对日期：2026-10-12（Asia/Hong_Kong）。当前整合源码固定为 `96c5502119829119abce42a59804b79431895a98`，包含失败恢复 #365–#367、原主线可靠性实现和 main `84426f0` 的模块责任修复 #372–#383。产品及当前清单来自 `codex/workflow-failure-recovery`，不表示生产已部署。共 3 张架构图、33 个时序流程，即 36 张交互图；维护流程 32 保留，失败恢复为 33。机器清单见 [architecture-validation.json](architecture-validation.json)，覆盖见 [architecture-coverage.json](architecture-coverage.json)。

## 当前图件与保留快照

5 张核心图（3 架构图、流程 32/33）重定位当前源码与模块所有者，并执行 Archify 3.0.1 完整 `finalize --repo-root . --quality showcase --json`。每张 9/9 showcase 检查、0 errors/warnings，并通过 validate、deliver、strict check、真实 Chrome browser-check 四道门禁。规格、HTML、浏览器收据 SHA-256 与磁盘一致，每张记录自己的四个浏览器尺寸（1440×900、1600×1000、1920×1080、2048×1320）及 light/dark 主题检查。HTML 由工具生成。

其余 31 张详细图保留原始规格、HTML 与通过收据。其中 26 张源码身份为 `0c62a0f511880e9d07bbf9505771ec15657995e7`，14/17/24/26/27 五张仍为 `3ed823c961736378d8408bba5f0535b03e0046e0`。它们说明对应快照的详细行为与所有者，当前模块责任以 [当前架构](architecture.md) 和 [源码清单](architecture-sources.md)为准。快照 Markdown 的源码链接固定到对应 Git 提交；本轮重新核对所有图的来源与字节哈希，没有将旧收据记作新源的浏览器运行。

当前全景图按技能执行一次仅调整节点位置的试验，保留所有节点、关系、方向、标签和来源。候选四门通过，但交叉数由 22 增至 27，因此恢复原规格并重新四门验收，最终为 22。AI 专题仍有 6 项绕路建议。全部图的 perceptual visual review 为 `not_requested`，只声明自动浏览器证据。新原始收据位于忽略的 `.archify/failure-recovery-merge-20261012/coupling-final/`，全景最终为 `coupling-review-3/architecture/`；每图记录确切目录。Archify 3.0.1 已是可用版本，无更新提醒。

## 来源与内容核对

实际 parser/registry 为 21 个顶层命令、94 条叶命令；当前固定提交树为 244 个 Python 模块、12 份 SQL 资源。稳定契约为 54 项、JSON Schema 26 份。rights SQL 为默认关闭、显式初始化的可选扩展；maintenance 不在运行中安装 DDL。模块所有权改变没有重写 schema、profile、input、出版字节或重试历史。

所有图来源按自己的固定 Git blob 核验。当前 5 图的符号按 AST 和新 owner 重定位；其余详细图保持原快照范围。全部本地 Markdown 链接、可执行源码行链接、33 个完整 Mermaid 分支与所有收据哈希核对通过，准确数量见机器清单。status、explain、CLI retry、maintenance 共用 failure_policy/decide_retry/editorial_retry_facts；allowlist 只能收窄政策，校验错误和 lease recovery 不成为自动重排特例。

## 实现验证与历史证据

父代理提供的当前整合源码 `96c5502` 验证分组为：policy/status/maintenance 与 architecture/couplings 122 passed；publication/cancel/control ports/source ports/UTF-8 75 passed；editorial 与 architecture 146 passed、1 skipped；frozen compatibility 3 passed。architecture 用例有重叠，这些分组不相加为唯一测试总数。契约镜像 54/26、Ruff E9、compileall 均通过。

[合并模块修复前的完整验收记录](evidence/architecture-pre-coupling-validation-2026-10-12.json)保留当时 36 图混合来源和集成提交 `08a56ecfe79cebf16b1eda7680233acd6d454bf2` 的测试证据。[Linux CI run 38230792994](https://github.com/SuperCatQR/bilibili-asr-archive/actions/runs/38230792994) 对该提交 8 项检查通过，3357 passed、11 skipped、0 failures/errors；1 条 warning。行覆盖率 84.89%（22413/26401），分支覆盖率 74.50%（7089/9516），通过 75%/63% 门槛。它是前次集成提交的证据，当前最终提交 CI 由父交付流程另行记录。

更早主线 35 图的 [原始验收 JSON](evidence/architecture-main-validation-2026-10-12.json)、[模块边界修复报告](development/module-coupling-fixes.md)和 [实测索引](evidence/README.md)分别保留原来源与测试口径，未将历史结论升级为当前完整验收。

## 交付边界

最终整合 CI 的导入顺序测试发现 CLI 帮助入口仍有两处提前加载 ASR runner/session 的顶层导入。已移除重复导入，保留 `_execute_workflow` 执行时的局部导入；导入顺序、架构边界与相关工作流测试重新验证为 88 passed。该修正不改变恢复政策或模块所有权，图中源码行号继续绑定已明确记录的 `96c5502` 快照，最终提交另行运行完整 CI。

本轮没有启用生产 timer、重排生产任务、历史批量回填、付费 API、OpenCode Go 实网参数验证或 FP8 GPU 验收。部署按 [维护交接手册](operations/retry-maintenance.md)保留 holds/累计 ledger，停用旧 retry writer，使用同一个现有锁。策略模板允许已知 transport 错误、两次重试及 [0,600] 退避，空 selector 必须填入复核范围；浏览器门禁不替代生产往返或外部部署验证。
