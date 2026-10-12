# 架构与时序图验证记录

核对日期：2026-10-12（Asia/Hong_Kong）。当前产品源码固定为 `0c62a0f511880e9d07bbf9505771ec15657995e7`，来自 `codex/workflow-failure-recovery` 合并分支，包含 #365/#366/#367 与主线 #349/#350/#361。共有 3 张架构图、33 个时序流程，即 36 张交互图；主线维护流程 32 保留，失败恢复为流程 33。机器清单见 [architecture-validation.json](architecture-validation.json)，源码覆盖见 [architecture-coverage.json](architecture-coverage.json)。

## 当前图件验收

31 张受源码或政策变化影响的图已重定位源码符号和行范围，使用 Archify 3.0.1 完整执行 `finalize --repo-root . --quality showcase --json`。每张都有 9/9 showcase 检查、0 errors、0 warnings，并通过 validate、deliver、strict check、真实 Chrome browser-check 四道门禁。规格、HTML 和浏览器收据 SHA-256 与磁盘字节一致；每张记录自身的 1440×900、1600×1000、1920×1080、2048×1320 浏览器尺寸及主题检查。HTML 全部由工具生成。

5 张源码引用未变的图保留原始 JSON/HTML 和主线历史收据：14 搜索索引、17 迁移预检、24 产物存储、26 ASR 批处理、27 引用备份。其源码身份仍为 `3ed823c961736378d8408bba5f0535b03e0046e0`，本次仅重新核对字节哈希和固定源码范围，没有将历史浏览器运行记作新运行。原始 35 图主线验收保存在 [历史机器记录](evidence/architecture-main-validation-2026-10-12.json)。当前清单逐图标明新收据或历史复用身份。

本轮实际执行一次全景位置调整，仅交换 SQLite 与 GPU 节点所在行，保留所有节点、关系、方向、标签和来源。候选四门通过，但路由交叉由 22 增至 27，因此恢复原规格并重新完成四门验收，最终仍为 22 处交叉。AI 专题图的绕路建议保留。自动门禁不等于目视验收，本轮 perceptual visual review 均为 `not_requested`。原始收据位于忽略的 `.archify/failure-recovery-merge-20261012/`，当前清单记录每张的确切目录。Archify 已安装与可用版本均为 3.0.1，无更新提醒。

## 内容与来源核对

实际 parser/registry 为 21 个顶层命令、94 条叶命令；固定提交树为 218 个 Python 模块、12 份 SQL 资源。稳定契约 54 项、JSON Schema 26 份。新增 rights SQL 是显式初始化且默认关闭的可选扩展，不并入基础表契约；maintenance 复用现有工作流和 editorial 表，不在运行中安装 DDL。

全部 36 图核对 441 项固定源码引用，其中 430 项显式行范围；本地 Markdown 链接、源码行号和 33 个完整 Mermaid 分支均逐项检查，最终数量记录在机器清单。来源符号按固定 Git blob 的 AST 重定位，未变图保持原来源身份。status、explain、CLI retry 与 maintenance 的文档和图件均使用共享 failure_policy、decide_retry 与 editorial_retry_facts；维护 allowlist 只收窄政策，校验错误和 lease recovery 不成为自动重排特例。

## 合并实现验证

父代理提供的集成源码验证对应 `08a56ecfe79cebf16b1eda7680233acd6d454bf2`：本地 focused 回归 315 passed、2 skipped，补充回归 63 passed，Ruff E9、compileall 和契约镜像检查通过；相关政策与物理预算条件变异被测试捕获，原逻辑恢复后跑绿。

[Linux 集成 CI run 38230792994](https://github.com/SuperCatQR/bilibili-asr-archive/actions/runs/38230792994) 的 8 项检查全部通过：四个测试分片、quality、security、package、coverage。合计 3357 passed、11 skipped、0 failed/errors；一个分片有 1 条 warning。产品行覆盖率为 84.89%（22413/26401），分支覆盖率为 74.50%（7089/9516），超过 75%/63% 门槛。此证据绑定该集成代码提交；最终文档提交的 CI 由交付流程另行记录，不冒充已经运行。

主线历史测试、Reader 配套检查与生产/硬件边界保留原身份，见 [历史图表机器记录](evidence/architecture-main-validation-2026-10-12.json) 和 [实测索引](evidence/README.md)。部署政策模板单独修正为允许 deepseek_transport_failed/历史 DeepSeekTransportError、两次重试与 [0,600] 退避，空 selector 仍须操作员填写；它没有改变产品源码身份。

## 交付边界

文档描述合并分支中的实现与已完成验收，不表示生产 timer 已启用或生产任务已重排。本轮没有执行历史批量回填、付费 API、OpenCode Go 参数实网生效或 FP8 GPU 验收。维护上线按 [交接手册](operations/retry-maintenance.md)保留旧 holds/累计 ledger，停用旧 retry writer，并使用同一个现有锁。浏览器收据不能替代生产往返、GPU 性能、远程 SSH 或外部部署验证。
