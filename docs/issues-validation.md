# 本轮 WSL 验证与交付边界

验证日期：2026-10-10（Asia/Hong_Kong）。独立分支为 `codex/open-issues-implementation`，从 main 的 `effd9df473fca382133067eb1b7e04143ccbb849` 开始；最终被测试的源码身份为 `857906d3b3c54b31fd9bc0ba94b84618f68cd6f3`。本报告及图表在其后以文档提交保存，不改变该源码身份。机器结果、逐项 skip 原因及构建摘要见 [issues-validation.json](issues-validation.json)。

## 最终结果

| 检查 | 实际结果 |
| --- | --- |
| WSL 完整默认回归 | **2323 passed、11 skipped、0 failed、0 errors**；pytest 输出耗时 **702.54 秒** |
| 产品行覆盖 | **82.52%**：13910 / 16856；门槛 75% |
| 产品分支覆盖 | **71.47%**：4207 / 5886；门槛 63% |
| 源码清单门禁 | 所有产品 Python 文件都计入覆盖分母；无测试/脚本混入，无排除新模块或降低阈值 |
| Ruff / 编译 | `src scripts tests --select E9` 与 compileall 通过；修改的检索模块、音频及专项文件另做所需 F 检查 |
| 锁文件 | `uv lock --check` 通过 |
| wheel 与 sdist | 两类产物均构建成功；SHA-256 与字节数见机器记录 |
| 独立 wheel 安装 | 新虚拟环境中安装 wheel，`/tmp` 下运行；无 editable 源码回退；8 项 SQL/冻结契约资源完整 |
| 安装后业务 smoke | universal 初始化 → 完整 snapshot save/check/restore → readonly doctor 通过；doctor 前后 DB 字节一致 |
| 可选 YouTube 依赖 | 基础 wheel 未安装 extra/EJS/Deno 时，`source doctor` 如实返回 `ready: false`、exit 1；基础安装仍可工作 |
| 安装依赖一致性 | `pip check` 无破损要求 |
| 安全审计 | 锁定 dev+asr+youtube 的 **92 个依赖、0 个已知漏洞**；主机单独提供的 Torch/驱动不在该计数内 |
| JSON Schema | 9 个 schema 自身有效；已完成闭环导出及有效旧版示例共 16 份 catalog 通过，包含版本 2 / 3；[检查范围](issue-diagram-validation/catalog-schema-checks.json) |
| 架构与时序 | 新增 1 张架构图 + 7 张时序图，全部四门禁通过、Showcase 9/9、0 errors/warnings；[最终图表凭据](issue-diagram-validation/README.md) |

运行环境是 Ubuntu-24.04、Python 3.12.3、WSL2 Linux 6.6.114.1、ffmpeg 6.1.1。测试在独立的 WSL 原生文件系统副本执行，复制完成后才启动最终运行；源、测试、脚本、pyproject 和 lock 文件逐文件验证 SHA-256。机器报告保留这些文件的摘要，能够确认完整测试对应最终源码，而不是另一工作树或之前的草稿。未为覆盖率改动已有 collect-ignore，也未把已退役控制流程重新启用。

11 项 skip 包含 7 项已退役 CLI/coordinator 流程、3 项须显式开启的 live 网络 smoke，以及 1 项 Windows junction 语义测试。它们没有被计为通过。当前 SQLite 工作流、快照与进程组的新回归按默认测试实际执行。

## 关键行为与五轴审查

| 维度 | 检查与修复依据 |
| --- | --- |
| 正确性 | 新旧 SQLite 契约、冻结旧 archive 的 38 表 typed 值/rowid/JSON 与产物字节、完整快照恢复、双平台校对→审核→发布→混合出口；安装后的审计/fsync 失败如实报告已安装；字幕合法空与不确定错误分开 |
| 可读性 | 平台身份/metadata DTO、候选排序、调用预算、运行绑定及版本 codec 有明确所有者；共享纯策略只有一个常量来源，不加入失效私有 alias |
| 架构 | SQLite 拥有持久进度；平台 adapter 不写 DB，GPU 子进程不持连接；worker 在原 job/owner/attempt/lease 围栏下提交；当前来源 metadata 与冻结 input/edition 的所有权分开 |
| 安全 | 外部来源 bounds/Unicode/int64、受限路径、无链接模型清单、完整 bundle/hash、坏契约 marker、私有子进程大小/超时与安全 diagnostic；cookie 路径/内容不得进入 metadata、任务结果或 DB |
| 性能 | 元数据集合投影使用有界 batch，修复 N+1；旧 metadata 的 3000 条 fixture 仍为总计 5 条 SQL，FTS 搜索至多 4 次 SELECT；字幕、网络请求、IPC、预取与恢复查询有明确预算 |

审查发现并修复了 FTS 缓存日期过期、YouTube 时间戳 fallback、来源 DTO 边界及运行时 cookie 配置。最终全量回归又发现搜索多一次契约探测和音频复用调用旧方法的问题；修复保留原查询预算断言，并增加空/不支持 marker × 两种检索的四条拒绝读取回归。对应最后补丁提交为 `857906d`。

专项测试实际覆盖持久 spawn 请求的身份、迟到响应、配置变化、超时、取消、lease 丢失、崩溃、大 IPC、父 SIGKILL 后回收、drain 和下一块准备。字幕专项覆盖候选 fallback、合法空、认证/限流/结构错误、预算与旧依赖 plan/apply。刷新专项覆盖 head/resume、字段 present/empty/unavailable、失败重抓、CID 冲突、页事务和批量投影。

两项 mutation 只在独立进程中修改运行时对象，未改磁盘源码：去掉 ASR 响应身份围栏后迟到响应回归失败；将权威发布日期谓词退回 FTS 缓存日期后，Bilibili/YouTube 两条日期修正回归均失败。它们证明测试能够识别被保护的错误行为，不是完整 mutation coverage。

审计发现的三个传递依赖已在 lock 中修复：multidict 6.9.1 保留 6.x 并修复 C 扩展泄漏/并发错误；PyJWT 2.15.1 修复合法 Base64URL padding 兼容；urllib3 2.8.0 修复代理 TLS 与流式解码安全问题。升级按官方变更核对，并用完整回归及严格审计验证，参考 [multidict changelog](https://multidict.aio-libs.org/en/stable/changes/)、[PyJWT changelog](https://pyjwt.readthedocs.io/en/latest/changelog.html)、[urllib3 changelog](https://urllib3.readthedocs.io/en/stable/changelog.html)。本次没有把安全修复扩大为无关的 multidict 7.x 升级。

## 复现

在最终提交的全新 WSL 原生 checkout 创建 Python 3.12 环境，安装锁定 dev/youtube 要求并保持主机 GPU 环境独立。然后在仓库根运行：

```bash
uv export --frozen --extra dev --extra youtube --no-hashes --no-emit-project \
  --output-file /tmp/issue-validation-requirements.txt
python -m pip install -r /tmp/issue-validation-requirements.txt
python -m pip install --no-deps -e .
mkdir -p /tmp/issue-validation/coverage
export COVERAGE_FILE=/tmp/issue-validation/coverage/.coverage
python -m coverage run -m pytest -q --durations=20 \
  --basetemp=/tmp/issue-validation/pytest --junitxml=/tmp/issue-validation/pytest.xml
python -m coverage combine /tmp/issue-validation/coverage
python -m coverage json -o /tmp/issue-validation/coverage.json
python scripts/check_test_coverage.py /tmp/issue-validation/coverage.json --line-min 75 --branch-min 63
python -m ruff check src scripts tests --select E9
python -m compileall -q src tests scripts
python -m build --sdist --wheel
```

使用独立 venv 安装生成 wheel 后，从源码目录之外调用 CLI，验证 SQL 资源和真实初始化/快照/doctor。完整日志、XML、覆盖报告和构建产物的本次原件保存在本机 `/home/chosenecho/open-issues-validation-20261009/`；`final3-*` 与 `coverage-final3-*` 对应本报告。后续运行需使用自己的输出目录，不能把旧日志写成新验证。

## 仍需实际环境验收的边界

本轮范围为 #278、#279、#282、#285、#286、#287、#288，排除 #289 BW1000。以下条件在相应 issue 的最终关闭前仍需明确验收：

- #278：真实旧生产归档副本的完整预检/迁移/切换演练、真实 YouTube 人工/自动/无字幕样本、外部阅读站支持 catalog 3；频道/播放列表批量发现仍为后续范围。
- #279/#288：真实 ROCm/CUDA 的模型复用、显存、吞吐及准备重叠对照；Linux 故障测试不能证明 Windows 全进程树回收。当前预取只提前准备同任务下一块，未提前领取下一任务；trace 是 wall time。
- #282：目标主机的真实 GPU/模型加载与授权可用性；doctor 报告环境要求，未在线验证账号；恢复后仍由操作者显式启动 worker。
- #285/#286/#287：真实账号与当前生产数据集的采集/刷新验收；合法空字幕不能当作静音音频结论，失败/重试及 hold 历史保留。

本轮不替换生产 writer、不移动生产归档、不关闭上述 issues。代码、文档、图表和离线验证已经形成独立可审阅分支；外部系统和硬件验收的证据需要各自的数据及环境。
