# 契约治理实现与图表验证

日期：2026-10-11，Asia/Hong_Kong。固定源码 `6a8646a36f680705479a7669350fd8793551cc74`。
起点 main `bab5998dd5235a7687b479e96edf16f9ed76c7ba`；已合入 main `fd5a8068f988ed1394fdb0a7c723941cbdf5221b`（#317）。
[实施与兼容边界](contract-governance.md) · [交互图](contract-governance.html) · [机器记录](contract-governance-validation.json)

## 行为检查

| 检查 | 实际结果与范围 |
| --- | --- |
| Linux 全量（合入前） | 2510 passed / 11 skipped，626.44 秒 |
| Linux 干净提交检出及独立安装（合入前） | 40 passed，源码 `26eacf1690dcadcf367a7abb7024816006294fd2` |
| Windows 合入后契约、来源补充、保留正文导入 | 84 passed，500.29 秒 |
| Windows 导出及契约专项（合入前） | 112 passed / 2 skipped |
| Windows 独立安装 CLI（合入前） | 12 passed |
| Linux 合入后全量 | 2533 passed / 11 skipped，719.71 秒；干净提交归档 |
| Schema 与文档镜像 | 34 项登记、15 份 Schema，真实提交字节一致；六个指纹保留旧身份 |
| 静态与交付门禁 | Ruff E9、compileall、官方索引 uv lock check、git diff --check、图源码范围通过 |

集合存在重叠，不累加为独立测试总数。Linux 测试在独立 native filesystem 项目目录执行；
wheel 测试从本地依赖 wheelhouse 安装，验证时不访问网络，不继承当前源码或构建 backend。
Windows 使用 `PYTHONUTF8=1` 使中文样本和子进程编码一致。

Windows 全量尝试在合入新 main 时中断，不记为通过。另对三项 ROCm 测试在起点 main
重现相同失败：一项 Linux loader 路径期望、两项 `WinError 1314` 符号链接权限。
基线失败未改写为 skip/pass；本轮 Windows 相关迁移、导出、来源补充与安装检查单独记录。

固定指纹门禁做过反向条件实验：在独立实现副本中反转比较条件，漂移拒绝测试按
`DID NOT RAISE SnapshotDatabaseError` 失败，原实现测试通过。历史 fixture 禁止调用当前
writer/renderer，并核对固定 ID、38 张表、15 个文件及原始 JSON/字节。

## 图表身份与验收

专题图覆盖统一登记、结构/语义校验、镜像、固定 schema 指纹和冻结样本。
10 个组件、10 条关系的源码范围在固定提交核对；旧 19 张图保留其历史身份。

- specification SHA-256：`a02de1938f0c709fe429fe044486529ca55d1bab179c2225041c1bcc681c9680`。
- HTML SHA-256：`75f1e6b8c432c52db75c969c7e2e28c630b70a847e93e3451d6732d417b2ae0a`。
- Archify finalize 的 validate、deliver、check、browser-check 均通过，零 diagnostics。
- 自动浏览器检查覆盖 1440×900、2048×1320 的浅/深色主题；声明的纵向滚动按 Reader 规则接受。
- 实际查看最终 2048×1320 浅色和 1440×900 深色截图，检查主链路、次级链路、箭头、标签和节点。
- 一次位置调整让 CI→快照→指纹连续可读，移除旧绕路控制；最终没有交叉/绕路建议。

原始回执和截图在忽略的 `.archify/`；本页和 JSON 仅保存可移植结果。
不把新专题结果套用到未改动的全景/AI/时序图。

## 验证边界

按 correctness、readability、architecture、security、performance 核对代码。
Schema/validator 缓存，catalog 整体结构校验一次，业务边界继续校验语义和文件关系。
契约治理不改写既有哈希、历史 ID、旧稿件字节和事务/锁安装协议。

未执行真实上游 API、GPU 推理、付费模型调用和生产归档迁移；图表验收不替代这些检查。

## PR #326 独立审查补充

2026-10-11 对 PR 原 head `9478ffb7baa4d4e57a4975ef907d18d4327e7258` 的实现、测试、
Schema、依赖锁和 CI 失败作独立核对。上方图表仍绑定其原提交，不重新声明图形验收。

- CI run `38066742222` 的第二分片只有进程退出探测失败：`/proc/<pid>/stat` 在成功打开后读取时返回
  `ProcessLookupError`（ESRCH）。统一探测明确接受 ENOENT/ESRCH 和 zombie，仍拒绝权限错误；
  保留真实 parent SIGKILL、模型持有 GIL 和 decoder 子进程清理测试，没有增加超时或跳过。
- 两种私有 manifest 原 Schema 允许用重复路径替代必需文件。四个新增重复路径负例先在原 Schema
  失败，再补全每个必需路径的 contains 约束；有效七/十文件输出和历史摘要保持不变。
- Schema 的 `$` 可匹配最后一个换行前的位置，移除原 fullmatch 会接受损坏的摘要和 edition ID。
  六种字段负例在原 PR 复现，恢复业务边界的精确身份校验，并验证真实 snapshot 安装拒绝且无输出残留。
- 固定样本保留 database root 中的原始字幕 sidecar，其他文件在独立 artifact root，继续证明两个根
  的组合读取。wheel 验证改用非空 v3 catalog，实际解析 v2 跨 Schema 引用，并禁止网络连接。

WSL 的独立 native filesystem 源码副本完成相关回归 **233 passed / 167.31 秒**，覆盖契约、架构边界、
ASR 会话、公开/草稿/私有导出、universal 出版、保留正文、来源补充、迁移历史和隔离安装。
最后的双根样本及安装引用测试加强后，对契约、迁移历史和隔离安装再运行 **54 passed / 17.48 秒**。
集合重叠，不累加。Ruff E9、compileall、34 项登记/15 份 Schema 镜像和 git diff 检查通过。

独立副本将新恢复的 hash 判断从 `is None` 反转成 `is not None`，六个包含有效输入对照的回归全部失败；
按原字节恢复后六项通过。图稿/HTML 摘要与原记录相符，20 处源码引用范围在固定提交核对。
依赖锁确认只新增 jsonschema 及四项传递依赖，既有依赖版本没有变化。

#314 的 2026-10-11 新增要求包括受验证升级边、历史源升级矩阵及真实 planner 的零昂贵重跑证明，
应随 #327–#331 的正式升级路径验收；原 PR 的登记/导出门禁不单独证明这些新增能力。
#313 的源码回归使用合成采集标题，生产一致副本的真实 P1/P3、P2 不变、全量统计与阅读站验收仍须另行记录。
