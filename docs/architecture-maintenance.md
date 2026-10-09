# 架构文档与时序图维护

本套文档以 main 的一个固定源码提交为基线。文字入口是 [architecture.md](architecture.md)，两张架构图为 [全景](architecture.html)和 [AI/出版专题](ai-proofreading-architecture.html)，16 个时序流程见 [总索引](architecture-sequences.md)。[源码清单](architecture-sources.md)、[覆盖清单](architecture-coverage.json)和 [验证记录](architecture-validation.md)共同说明覆盖范围和验收身份。

JSON 是图的可编辑规格，HTML 是 Archify 生成的独立查看器，不手工修改 HTML。目录级 `.gitattributes` 对图表规格与生成 HTML 设置 `-text`，防止 Git 换行转换改变验收哈希；`sequences/.gitattributes` 仅对生成 HTML 关闭行尾空白检查，保留模板字节及 artifact SHA-256，其他空白检查继续执行。时序 Markdown 保留完整 Mermaid 的嵌套 alt/opt/loop；HTML 展开跨参与者消息，内部调用在补充卡片中说明。修改流程时同时核对 Markdown、JSON 和代码，不能只改其中一份。

## 固定源码基线

先确认目标提交，再从该提交逐项核对 CLI 登记、配置、实现、schema 和已有测试。`meta.repository.revision` 必须是源码证据对应的完整 40 位提交，不能填浮动的 main/HEAD。源路径、符号和行范围均从该提交的字节核对；文档自身提交不必改变源码基线。

```powershell
git status --short
git rev-parse main
git ls-remote origin refs/heads/main
```

本地和远端不同须在文档说明核对对象，不能把本地分支当作远端现状。未提交代码和未来设计不纳入已经生效的运行架构；有独立规划文档时保留其规划身份。实际代码变更完成后，再绑定包含变更的源码提交。

以下任一变动均需检查相关文档和时序：命令或访问策略、配置/模板、选择和计划、任务依赖/lease/attempt/cancel/retry、SDK/API、字幕/音频/ASR、文件安装/marker、AI 输入/调用/修订/渲染、edition/review/release/head/tags、公开/预览/私有导出、查询/投影/FTS、schema/view、维护锁和 ZIP 恢复。

## 完整性核对

从 registry 与 parser 收集实际命令路径，不从过时 docstring 推断入口；从 `git ls-tree` 收集全部 src Python 模块；逐个 schema 提取表、列、外键和视图。同步更新 architecture-sources.md 和 architecture-coverage.json，明确当前调用与保留库能力的区别。

每个流程核对：调用顺序和条件、读写所有者、不可变身份、事务和文件边界、lease/attempt 校验、失败/重试/取消、已提交结果保留、恢复行为和实际消费者。writer 支持某字段、enum 保留某任务类型、库中存在某服务，均不能替代当前调用点的证据。

## 生成与自动检查

以下从仓库根执行，按实际技能安装位置调整 `$archifyCli`。每个改变过的候选用新的 evidence 子目录；输出 HTML 路径保持稳定。首次生成直接执行 finalize，不先做完整 validate 后重复相同前置检查。

```powershell
$archifyCli = Join-Path $env:USERPROFILE '.agents\skills\archify\bin\archify.mjs'
$runStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$evidenceRoot = Join-Path '.archify' "architecture-maintenance-$runStamp"

node $archifyCli finalize architecture docs/architecture.json docs/architecture.html `
  --repo-root . --quality showcase --out-dir "$evidenceRoot/overview" --json
if ($LASTEXITCODE -ne 0) { throw '全景图 finalize 失败' }

node $archifyCli finalize architecture docs/ai-proofreading-architecture.json docs/ai-proofreading-architecture.html `
  --repo-root . --quality showcase --out-dir "$evidenceRoot/ai-topic" --json
if ($LASTEXITCODE -ne 0) { throw 'AI 专题图 finalize 失败' }

$sequenceSpecs = Get-ChildItem -LiteralPath docs/sequences -Filter '*.json' |
  Where-Object { $_.BaseName -match '^\d\d-[^.]+$' } | Sort-Object Name
foreach ($spec in $sequenceSpecs) {
  $htmlPath = Join-Path $spec.DirectoryName "$($spec.BaseName).html"
  node $archifyCli finalize sequence $spec.FullName $htmlPath `
    --repo-root . --quality showcase --out-dir "$evidenceRoot/$($spec.BaseName)" --json
  if ($LASTEXITCODE -ne 0) { throw "时序图 $($spec.BaseName) finalize 失败" }
}
```

以最终候选的 validate/deliver/check/browser-check 四道结果为准，核对 provenance、specification SHA-256、artifact SHA-256 和实际文件完全一致。失败后根据诊断修改，重新完整 finalize；已有浏览器证据的候选修改后使用新目录。不要把旧候选回执当作新文件验收。

## 视觉检查与已知边界

存在交叉/绕路建议时检查实际图；自动 gate 通过不等于目视通过。可用以下命令取得两个主题及端点桌面尺寸截图，目录须与该候选 finalize 一致：

```powershell
node $archifyCli visual-check docs/architecture.html `
  --out-dir "$evidenceRoot/overview" --summary --require-provenance --json
```

检查完整纵向图、关系方向和标签、节点与卡片、主题可读性、焦点/搜索/源码链接，以及导出。长图允许按 Reader 契约滚动，不能裁切内容、隐藏溢出或压小文字来通过。时序 HTML 因渲染器约束没有画同参与者自调用；对应内部步骤必须在卡片与完整 Mermaid 保留。

架构布局建议按 Archify 的 architecture-layout-repair 处理：一次有证据的节点位置调整后比较；不改善则保留较清楚的候选，并记录实际交叉/绕路限制。不能通过删除关系、缩短语义或伪造检查结果掩盖限制。`visual_review` 只有实际看过对应图才可记 passed，其他图记 not_requested 或真实跳过/失败原因。

## 验证记录与交付文件

更新 architecture-validation.md 和 architecture-validation.json，记录源码身份、范围、每份规格/产物哈希、四道 gate、浏览器尺寸/主题、可选目视检查范围、未执行的行为验证与剩余布局建议。可移植记录不包含本机用户名或绝对 evidence 路径；原始回执、截图和修复候选留在忽略的 `.archify/` 下。

提交或交付文字、JSON、生成 HTML 和覆盖/验证清单。运行 `git diff --check`，检查本次新增/修改文档的相对链接与 Mermaid 分支平衡，确认未意外改动产品源码或他人的草稿。文档检查不替代业务测试、真实 API、GPU 推理、付费模型或人工语义审核。
