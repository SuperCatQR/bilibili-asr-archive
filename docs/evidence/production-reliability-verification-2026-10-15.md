# Issues #449–#458：修复与本地验证记录

日期：2026-10-15（Asia/Hong_Kong）。分支：
`codex/fix-production-issues-449-458`。修改前基线：
`e57edffa5da92e352d0fc5600236bc2020b402dc`；其中原有的四个本地运维提交保留。

服务器已由用户关闭。本记录区分代码实现、本地测试、安装包验证与生产验收；
没有连接服务器、启动生产任务、执行付费模型调用或删除生产音频。
详细影响规模、原始故障链与置信度见
[生产问题评估](production-failure-review-2026-10-15.md)，
修复范围及上线条件见[逐项修复计划](../plans/production-reliability-449-458.md)。
评估中的队列、文件数与耗时均为关闭服务器之前的历史快照。

## 架构边界与完成范围

| Issue | 本次实现 | 已覆盖的本地边界 | 仍需生产环境确认 |
| --- | --- | --- | --- |
| #449 | SDK 请求作用域回收自身创建的客户端，在事件循环销毁前关闭；保留其他作用域的资源 | 真实 SDK 无网络分配、反复建销事件循环、跨线程循环、嵌套、重复取消、关闭失败与原错误保留 | 排空旧进程、重启后验证 FD 趋势和原工作流 |
| #450 | 统一白名单异常诊断，保留 SQLite 扩展码、errno、阶段和有限数值位置；维护既有领域错误语义 | 一次性与常驻 ASR IPC、未知异常、恶意错误文本、诊断持久化失败 | 新失败记录的可诊断性及无敏感内容 |
| #451 | 冻结 profile 的可选版本化 deadline；总预算、启动时间和无真实进展时间分开监督 | 旧 profile 字节/摘要兼容、长音频预算上限、真实完成事件、心跳不能续命、可终止 CPU/子进程 | GPU 长音频与冻结参数、超时回收效果 |
| #452 | 合并前保留未对齐文本的有界证据，admission 拒绝不可表示对齐 | 零长区间、未匹配文本、合并后掩盖错误、证据大小上限；不制造或重排时间戳 | 取回原 BV1PM411U789 音频及推理单元，定位原始成因并重新对齐 |
| #453 | 完整 wheel 构建、文件清单与摘要、启动时版本身份、worker 健康记录、运行中文件漂移触发排空 | 提交归档构建、隔离安装、实际 CLI、worker 身份生命周期、包文件篡改拒绝 | 目标机依赖、数据库只读兼容、真实 GPU ASR/发布、受控切换与回滚 |
| #454 | 在既有采集器上增加持久化、有限重试监督，记录真实进度和累计等待 | 重启保留冷却/预算、无进展阈值、提交后崩溃恢复、取消、未全量时不得报完成 | 支持的上游访问恢复和 UID 实际覆盖边界 |
| #455 | 新增独立复制计划契约；复制与源文件释放各自计划、冻结和授权 | AI 等待/失败/hold 时复制、校验回执、损坏或中断、异常持久化 release intent 不得被复制命令推进 | 验证本机备份目标、更新服务器外部备份 helper、逐文件复核后释放 |
| #456 | 只读计划绑定准确替代 ASR 证据；显式应用后新建下游 DAG，保留旧尝试与边 | plan ID、幂等、回滚、执行中/已尝试/hold/歧义链拒绝、冻结输入、预算与交付状态 | 对两条实际替代链执行 dry-run，再应用经过审核的计划 |
| #457 | 区分 length/filter/tool/未知或缺失 finish_reason/空 stop；阻止相同冻结输入的无意义付费重试 | 有限响应分类、历史只读诊断、不泄漏正文、过滤与协议拒绝的调用数限制 | 新真实 provider 响应及账单/状态核对 |
| #458 | 统一评估、实现、验证和生产验收记录 | 跨模块回归、打包契约、代码审查、故障注入与安装验证 | 子 issue 满足各自真实验收条件后再关闭 |

既有 #350 的 schema、引用、段落和预算约束保留。本轮增加三类合成坏输出的
回归；十个原始私有生产样本尚未完成本次验收。拒绝错误对齐也不能视为原音频
已经正确识别。这两个边界都不以“本地测试通过”代替真实样本结果。

核心权威保持为现有工作流数据库、冻结 profile、admission 和 artifact/receipt
目录。没有增加第二套任务队列、SQLite schema migration 或运行时依赖。
失败记录、retry hold、原始推理证据和旧依赖保持可追溯。新服务分别负责监督、
恢复计划和进程观察，复用原有事务、锁、IO 和排空协议。

## 提交与并行工作

用户要求使用子代理。主代理负责请求资源归属、发布身份、集成和审查；
三个子代理分别负责 ASR/诊断、采集/备份、工作流/校对，各自完成实现、
定向验证和交叉审查。共享入口修改按顺序集成，子代理没有独立提交或部署。

| 提交 | 内容 |
| --- | --- |
| `0a10e3a` | #449 请求资源归属与清理 |
| `ce7e640` | #450/#451/#452 异常、deadline 与对齐 |
| `36b71a3` | #454 采集监督 |
| `3b7aba9` | #455 复制/释放分离 |
| `2662ff4` | #456/#457 下游恢复与 provider 语义 |
| `5f90d0d` | #453 完整发布与进程身份 |
| `d824f0f` | #458 评估、规模、故障链和验收计划 |
| `7ef2ef3` | 全量回归发现的固定异常代码兼容修正 |

## 五维代码审查与故障注入

采用 `code-review-and-quality` skill。以下为实际复核内容，不代表生产验收：

| 维度 | 重点与结果 |
| --- | --- |
| 正确性 | 核对请求所有权、取消时清理、旧 profile 摘要、进度来源、替代链唯一性、复制/释放操作类型和历史错误分类；修正了审查中发现的边界缺口 |
| 可读性 | 将通用安全诊断与领域映射分离，将轻量 ASR 进度协议独立，给监督/恢复/发布分别保留清晰入口与 runbook |
| 架构 | 复用数据库事务与 artifact 最终写入围栏；恢复创建新 DAG；状态观察失败不能覆盖业务尝试结果；禁止运行时热替换包文件 |
| 安全 | 清单和健康记录不含 .env/cookie/provider 正文；未知异常文本不落盘；复制不能启动或恢复删除意图；删除仍检查源身份、回执、消费者和 hold |
| 性能/资源 | 清理有超时；采集重试有累计上限；deadline 有硬上限与无进展窗口；对齐证据有界；包漂移检查每五秒并在尝试边界复核 |

四组关键条件反转实验均证明对应回归测试会失败，随后恢复：

1. 将真实进展判定改为允许心跳续命，deadline 回归失败；恢复后通过。
2. 关闭 filter 的付费重试阻断，fake provider 出现第二次调用，回归失败；恢复后通过。
3. 在隔离包副本反转文件清单漂移比较，4 项测试失败；恢复后 4 项通过。
   主工作树未被该突变修改，结果为 `.tmp/release-mutation-result.json`。
4. 在隔离副本移除历史 `ConnectError` 分类，两个错误分类/持久化回归失败；
   恢复后通过。该修正保持有限白名单，不信任未知类名或任意 `error_code`。

额外修正包括：健康记录写入异常只请求排空且不覆盖业务结果；所有新建 SDK
客户端都尝试关闭；重复取消不能跳过清理；复制即使遇到异常数据库意图行也
不获得释放权限；成功替代链必须先验证冻结源身份才能进入后续付费流程。

## 本地检查

以下命令均成功退出：

```text
.venv/Scripts/python.exe -m ruff check src scripts tests --select E9,F821,F822,F823
.venv/Scripts/python.exe -m mypy
.venv/Scripts/python.exe -m bili_asr.contracts --check-docs docs/contracts
.venv/Scripts/python.exe -m compileall -q src scripts
```

契约检查为 78 个契约、44 份 schema。`mypy` 仅覆盖仓库当前配置的两个严格
类型检查模块，不能据此宣称整个项目完成类型检查。

各实现组的定向验证有重叠，不能相加为独立测试总数：

| 组 | 结果/范围 |
| --- | --- |
| 请求生命周期及采集调用兼容 | 441 passed、1 skipped |
| ASR/诊断实现组 | 283 passed、12 skipped；另对集成后的 session/profile/deadline 与架构边界复核为 97 passed、4 skipped |
| 采集监督/复制/保留/契约/CLI 最终组 | 150 passed |
| 校对/恢复兼容组 | 265 passed、1 skipped；最终专用组 24 passed |
| 发布/启动/工作流边界与 ASR 部署检查组 | 71 passed、9 skipped |
| 全量结束后集成的异常分类兼容修正 | 75 passed、1 skipped，13.88 秒；跳过项为 Windows 不具备的 POSIX RLIMIT_NOFILE 检查 |

全量命令在 `d824f0f` 上收集并执行 4,846 项测试，启用 `PYTHONUTF8=1`。
实际结果为 **4,702 passed、100 skipped、33 failed、12 errors**，耗时
2,809.40 秒（46 分 49 秒），另有 4 个 warning。日志为
`.tmp/production-reliability-final-tests.txt`。这是失败的完整运行，不能计作
全量通过。没有修改收集忽略规则、降低断言或跳过本轮出现的失败。

其中 `test_editorial_transport_retry_has_remaining_physical_budget` 是本轮引入
的兼容回归：安全诊断将既有 `ConnectError` 收窄成 `Exception`，维护重试的
allowlist 因此跳过仍有物理调用预算的任务。修复范围是补齐既有策略使用的
十种固定类代码，并测试未知类名、伪造属性和敏感正文仍被过滤；领域适配器
继续优先保留自己的稳定代码。完整运行结束后才集成这一补丁，因此上述
完整运行对应同一版本。集成后的四个相关测试文件为 **75 passed / 1 skipped**，
原失败节点通过；没有重跑第二次全量，不能将局部复核与前次完整运行的通过
数相加。主树日志/XML 为 `.tmp/retry-fixed-class-codes-main-validation.txt/.xml`，
隔离反转实验见 `.tmp/retry-fixed-class-codes-summary.md`。

其余 **32 个失败和 12 个初始化错误均在修改前基线独立复现**。这是失败
归因，不是将失败改记为通过；临时目录修正后仍存在的平台与依赖限制如下。

## 原基线与运行环境对照

对失败使用 `git archive` 独立导出原基线，显式 `PYTHONPATH` 并检查
`bili_asr.__file__`，避免把当前源码误当成基线。相关文件还与提交内容进行
规范换行后的哈希对照。结果文件均位于工作区 `.tmp`，不是生产服务器日志。

已独立确认的失败包括 Windows 无 symlink 权限、POSIX 专用路径/替换钩子
假设、本机 Bash/WSL 拒绝执行，以及临时目录导致的 SQLite 和安装隔离错误。
默认 AppData 临时目录存在但创建唯一探针文件返回 PermissionError；Python
退回源码目录，使安装测试触发“staging destination must be outside the
source tree”。纯 SQLite 的内存数据库写约 8 MB 临时表也能复现
`SQLITE_CANTOPEN`。这些证据不能被替换成 FD 泄漏或数据库损坏的推断。

环境修正仅为子进程指定源码树外的可写临时目录，产品代码、测试断言和
staging 安全检查不变；各组按实际使用记录 TEMP/TMP/TMPDIR/SQLITE_TMPDIR。

| 对照范围 | 原环境基线 | 显式可写临时目录后的基线 / 当前树 |
| --- | --- | --- |
| 精确 editorial replay 查询节点 | 1 failed，SQLite CANTOPEN | 各 1 passed |
| metadata 万条历史查询 + release gate 两节点 | 各 2 failed，CANTOPEN / 临时根路径前缀 | 各 2 passed |
| 六个维护测试文件，117 项 | 100 passed / 17 failed | 各 114 passed / 3 failed，逐节点及错误签名相同 |
| 模型权重 symlink 拒绝节点 | 1 failed，WinError 1314 | 当前树相同；临时目录不能赋予 symlink 权限 |
| coverage 子进程与未执行源码节点 | Windows JSON 路径与硬编码 POSIX 断言不符 | 两树各 1 failed；run/combine/json 均成功，child 已测量、untouched 为零覆盖 |
| verify-baseline 两节点 | 两树各 2 failed，staging 目录 / WinError 1314 | 两树各 1 passed / 1 failed；preflight 通过，symlink 权限仍不足 |

维护组原来的 16 个 CANTOPEN 全部消失，14 项通过，2 项继续到原有的
Linux `renameat2` 要求并拒绝 Windows 原子交换；第三个残余失败是 Windows
目录 fsync 提前返回与 POSIX 故障注入测试的假设不符。没有为这些测试放宽
原子性与错误处理。证据为 `.tmp/baseline-maintenance-recheck.txt/.xml`、
`.tmp/baseline-maintenance-corrected.txt/.xml`、
`.tmp/current-maintenance-corrected.txt/.xml` 与
`.tmp/baseline-maintenance-temp-diagnostic.txt`。

完整 installed CLI 组在原环境基线与当前树均为 1 failed / 12 errors，
停在 staging 目录隔离。修正临时目录后，该冲突消失，但两树仍各为
1 failed / 12 errors：uv cache 默认目录不可写；独立 stdlib 安装推进到
离线依赖安装，缺少 Windows 平台的 `rpds-py>=0.7.1`。再给单节点指定可写
UV_CACHE_DIR 后，两树都推进到相同的离线轮子缺失。现有 wheelhouse 只有
manylinux 的 rpds_py；没有下载或伪造兼容轮子。这组正文尚未执行，不能
宣称通过。前后对照为 `.tmp/tempdir-correction-summary.md`。

完整运行的其余原有失败为 audio reclaim 的三个 Windows symlink/路径钩子
节点，以及 ASR 部署自检的四个 POSIX loader/symlink/Bash 节点。原始基线
精确复现见 `.tmp/baseline-e57edff-recheck-summary.md`。coverage 对照还验证了
两树 `[tool.coverage]` 整表和测试文件相同；原始报告中 child 覆盖 1 行、
untouched 覆盖 0 行，失败发生在路径键格式断言，见
`.tmp/coverage-temp-recheck-summary.md`。verify-baseline 的子进程调用在测试中
全部被 mock，不涉及实际 uv/pip 安装；证据为
`.tmp/verify-exact-causality.txt` 与两树 `verify-exact-recheck` 日志/XML。

## 完整候选包与隔离安装

初始候选从已提交的 `d824f0f8601d59f106de8f60fdadac7b1ab33c34` 构建，
不使用未提交工作树或旧 build 目录。应用 wheel 离线构建并以
`--no-index --no-deps` 安装到独立目录；这不是在空环境中重新解析所有 GPU
依赖的验收。初始候选已经被包含异常分类兼容修正的最终候选替代；
下面保留初始身份用于追溯，不应再用于部署。

| 字段 | 值 |
| --- | --- |
| wheel | `.tmp/production-release-20261015-candidate/bili_asr-0.1.0-py3-none-any.whl` |
| release 清单 | `.tmp/production-release-20261015-candidate/release.json` |
| 代码提交 | `d824f0f8601d59f106de8f60fdadac7b1ab33c34` |
| build ID | `c974b39bb5311a06dbdc73114a92750518c070df055d4cf316b86ae16025826b` |
| wheel SHA-256 | `7cbe3176aa8cbe31843c0e87641a0ffad51c4c4e0f1de8e7776b42d3a6939620` |
| lock SHA-256 | `35bbf90c82a4f0d3995f618dc10626e97b0e15c857ea797dda38ec0ce45eadc8` |
| 清单范围 | 378 个 Python/JSON/SQL 包文件 |

以隔离解释器运行安装后的包，8 项 CLI 检查全部退出 0：版本、帮助、
editorial 恢复入口、工作流计划、复制计划、传输入口、初始化测试库状态、
工作流状态。另实际创建 worker 健康记录，核对正确 build ID 的运行与停止
状态；暂时改动已安装包文件后，真实 CLI 退出 2 拒绝漂移，恢复原字节后
重新核对完整清单为 verified。验证结果为
`.tmp/production-release-20261015-verification.json`。

最终候选从 `7ef2ef3` 构建，重复离线安装和上述完整检查，全部符合预期：

| 字段 | 最终值 |
| --- | --- |
| wheel | `.tmp/production-release-20261015-final/bili_asr-0.1.0-py3-none-any.whl` |
| release 清单 | `.tmp/production-release-20261015-final/release.json` |
| 代码提交 | `7ef2ef3205326ffd29c163896b413eb273ecf666` |
| build ID | `57a0e291efe3cc72e4e44d87e4f9cdad639a7b29eb6b67027b88a260b1b5bc7d` |
| wheel SHA-256 | `3302dc731bde13e7abe4d756c6f1177a495a11acbbacbdc46e60475d1fe742ba` |
| lock SHA-256 | `35bbf90c82a4f0d3995f618dc10626e97b0e15c857ea797dda38ec0ce45eadc8` |
| 清单范围 | 378 个 Python/JSON/SQL 包文件 |
| 隔离安装 | `.tmp/production-release-20261015-final-check/installed` |
| CLI / worker / 漂移 | 8 项退出 0 / running→stopped 身份正确 / 拒绝漂移后恢复 verified |
| 机器验证结果 | `.tmp/production-release-20261015-final-verification.json` |

后续验证记录提交仅修改文档，不改变该代码提交的包内容。最终 wheel 并未
部署到服务器，也没有在目标 GPU 环境中解析和验收全部依赖。

这些检查的 GPU acceptance 为 `not_run`，provider calls 为 0，
production acceptance 为 `pending`。本轮没有将任何 issue 标为生产已验证。

## 服务器恢复后的验收顺序

1. 保留原环境、数据库备份、冻结 profile、失败尝试和私有运行状态；盘点所有
   scheduler、worker 与外部备份 helper，排空旧版本并核对 lease/reader pin。
2. 在新环境使用适合目标 GPU 的 Torch、锁定依赖和国内镜像/离线 wheelhouse，
   安装完整候选包。校验 release 清单、依赖、数据库只读兼容与新进程身份。
3. 使用短音频和代表性长音频执行真实 ASR、对齐、admission、发布；原始异常
   音频单独验收。核对 FD、deadline、拒绝证据和 worker 排空行为。
4. 恢复采集时沿用已持久化监督预算，核对上游枚举边界；更新备份 helper，
   分别核对复制回执与释放阻塞；只按经复核的释放计划删除源文件。
5. 对替代 ASR 链先 dry-run 再应用，保留旧失败历史。付费校对须单独核对配置、
   预算和真实坏输出样本；状态/排队本身不执行付费调用。
6. 按各 issue 的验收条件记录实际结果；切换或回滚使用完整环境与匹配清单。
   不能用拷贝单文件、重置历史或放宽质量契约完成验收。

具体指令和回滚约束见[发布操作手册](../operations/production-release.md)、
[采集监督](../operations/metadata-supervision.md)、
[音频保留](../operations/audio-retention.md)、
[校对链恢复](../operations/editorial-recovery.md)与
[ASR 可靠性](../production-asr-reliability.md)。
