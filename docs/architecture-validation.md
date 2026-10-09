# 架构与时序图验证记录

核对日期：2026-10-09（Asia/Hong_Kong）。源码基线：main `9b289570494b5e8f7cc564a7eaa5b2eb2c28c3ad`，核对时本地 main 与 origin/main、远端 refs/heads/main 相同。本次更新以该提交的已提交字节为准。

可机读的完整结果、每份规格与 HTML 的 SHA-256、浏览器尺寸/主题和检查状态保存在 [architecture-validation.json](architecture-validation.json)。[coverage.json](architecture-coverage.json)列出逐项覆盖对象；[源码说明](architecture-sources.md)提供命令、模块、字段与外键的阅读索引。

## 覆盖和内容复核

| 检查范围 | 数量 | 核对方法 |
| --- | --- | --- |
| 顶层命令 | 15 | pinned registry 的 COMMANDS 与 parser 登记 |
| 实际命令路径 | 34 | 解析各 parser 的真实 add_parser，和覆盖清单逐项比对 |
| 产品 Python 模块 | 97 | pinned `git ls-tree` 的全部 src Python 文件，与模块清单逐项比对 |
| SQL schema | 4 | 在隔离内存 SQLite 中加载固定提交的四份 SQL |
| schema 持久表 / 派生视图 | 38 / 8 | 对照 sqlite_master、全部 table_info 字段及来源定义 |
| 动态 FTS 逻辑对象 | 2 | 固定源码的 DDL、常量与完整字段；不把 shadow tables/临时 probe 计作业务实体 |
| 独立时序流程 | 16 | 启动、采集、计划、执行、生产、AI、出版、导出、读取、检索、快照和保留库能力 |
| 交互 HTML | 18 | 两张架构图与 16 张时序图，规格和产物身份逐一绑定 |

全部图节点/参与者均带 pinned 源路径、有效行范围和入口说明。覆盖清单列出未由当前 CLI 自动调用的保留能力；它们以显式库工具身份出现。内容复核还检查本次修改/新增 Markdown 的本地链接、16 个 Mermaid 时序块的参与者与分支配对，以及完整暂存提交的 `git diff --cached --check`。生成时序 HTML 的模板含空白行尾空格，目录级 `.gitattributes` 仅对这些 HTML 关闭 blank-at-eol 检查，保留已验证产物字节与哈希；其他空白检查继续执行。

## 自动验收

使用 Archify 3.0.1，全部 18 份最终候选通过 showcase 级别的 validate、deliver、strict check 和 browser-check，最终 diagnostics 均为空。候选变动后重新 finalize，最终记录只绑定最后一次成功交付的 specification / artifact SHA-256；旧失败候选或旧截图不充当当前验收。

browser-check 使用 Chrome，以 READ / still 状态检查 light / dark 两种主题，桌面尺寸为 1440×900、1600×1000、1920×1080、2048×1320。全部横向 containment 和可读性检查通过；长图按 Reader 的 intrinsic-height 契约允许页面纵向滚动。没有通过裁切内容或隐藏 overflow 强制适配。

18 份最终图另行执行 artifact-bound visual-check：1440×900 与 2048×1320、light / dark 四组截图，containment/readability/viewerChrome/themeStates/captures 均通过。这是额外的自动截图证据，独立于目视判断。

## 实际视觉复核

实际检查全景、AI/出版专题及 07 ASR、11 出版生命周期、15 ZIP 恢复的完整页面和主题端点截图。记录中的 `visual_review: passed` 仅用于这些已查看的图；其他图为 `not_requested`，它们的自动检查与截图仍全部通过。完整页面另在 1600×1000 浏览器中截图，确认流程末端、补充卡片和节点索引存在，无横向溢出。

时序图的实际复核发现分支标题向前避让、偏离所属步骤，已修正：为每段分支预留空间，B 编号卡片保存完整嵌套条件路径，完整 Mermaid 保存自调用与所有嵌套结构。修正后 16 图全部重新生成、重新完成四道验收与截图；已查看的时序图目视修正轮次为 1。

全景图有 20 个节点、27 条关系；AI 专题有 15 个节点、17 条关系。全景仍有 19 处自动处理的交叉、5 条超过建议转折数量的路径；AI 专题有 6 条绕路建议。全景做过一次仅改位置的修复尝试，新候选未改善验收，因此保留通过检查的布局。方向、关系和全部源码证据保留；密集连线可使用缩放、焦点模式、专题图和具体时序阅读。自动零 diagnostics 不代表交叉数量为零。

## 原始证据、复现与边界

原始 finalize / browser-check / visual-check 回执、截图、布局修复候选和内容核对脚本留在本地忽略目录 `.archify/architecture-main-20261009-122936/`，不作为可移植产品文档提交。JSON 验证记录使用仓库相对路径，不含本机绝对路径。重现方式见 [维护指南](architecture-maintenance.md)。

本次更改限于 docs；没有修改产品逻辑。本次未运行完整业务回归、真实 Bilibili 网络访问、GPU 推理、付费 DeepSeek 请求、外部阅读站部署或人工逐句语义审核。自动图表验收、静态源码核对和实际视觉检查各有明确范围，不能替代这些运行验证。
