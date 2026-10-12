# 项目回归测试记录（2026-10-12，WSL）

## 结论与版本口径

按用户要求，本记录的测试命令、解释器、浏览器和构建工具全部在 WSL Linux 内运行。当前版本默认 Python 回归**通过**：**3143 passed、0 failed、0 errors、11 skipped**，收集 3154 项，JUnit 耗时 1950.28 秒。行覆盖率 **84.41%**、分支覆盖率 **73.86%**，覆盖率门禁退出码 0。

实网测试单独执行，结果为 **1 passed、1 failed、1 skipped**：元数据请求被上游 `rate_limited` 拒绝，公共元数据成功路径尚未验收。GPU 环境检查 5 项失败，真实 GPU 推理未验收。阅读站 Node 测试、内容校验、构建及桌面/移动 Chromium 交互检查通过，但构建有包体积告警。因此不能将本次结果表述为“线上链路全部通过”。

测试期间共享工作区发生版本变化。原固定副本 `ab2dcffa7c583cb7bcd191b7812ea4b37acee798` 的测试继续完成，历史结果为 3235 passed、0 failed、0 errors、11 skipped；它不是本报告的当前版本结论。用户明确选择以变化后的当前工作区为准，因此再次冻结并完整重跑，最终以 **`7409c50dc6de0c2c558d44ba6edbebc5308bbda2` 加冻结时工作树字节**为准，不将不同版本的节点数量或失败数直接比较为平台差异。

- 当前 Python 固定副本：`/home/chosenecho/bili-asr-regression/current-20261012-38wgk7iu`，723 个输入文件。
- 阅读站独立仓库 HEAD：`7a13d8b6b3276a14e5afd6d7e0373290c37369cc`，60 个输入文件；版本变化期间其字节保持一致。
- 输入与 SHA-256 清单：[regression-test-2026-10-12.inputs.json](regression-test-2026-10-12.inputs.json)。记录同时包含两个 Python 版本和阅读站。
- 机器可读结果、跳过原因、失败详情、日志摘要：[regression-test-2026-10-12.json](regression-test-2026-10-12.json)。
- 测试后固定副本输入校验：Python 改变 0、缺失 0；阅读站改变 0、缺失 0。
- 测试后原工作区相对最终固定副本：改变 0、缺失 0；逐文件详情见 JSON。报告文件写入后的变化属于记录产出，不包含在该采样中。

先前 Windows 报告已保留到 `.tmp/regression-windows-superseded-20261012.md`，仅作历史证据。该报告不满足用户指定的 WSL 测试平台，且源版本不同，不能作为本次 WSL 回归的当前缺陷结论。

## 测试环境与覆盖范围

- Ubuntu 24.04 / WSL2，Linux kernel `6.6.114.1-microsoft-standard-WSL2`，用户 `chosenecho`，locale `C.UTF-8`。
- Python 3.12.3、pytest 9.1.1、coverage 7.16.2、Ruff 0.16.10；解释器 `/mnt/c/WorkSpace/bilibili-asr-archive/.venv-wsl/bin/python`。
- uv 0.11.14、pip-audit 2.10.1 使用独立 WSL 工具环境。Node 22.23.1、pnpm 12.11.2、Playwright 1.63.0、Chromium 153.0.8010.12 均为 Linux 运行时。
- 默认测试覆盖元数据及字幕入库、SQLite 存储与队列、音频与 ASR 编排、工作流依赖/租约/取消/重试、发布与编辑校对、导入补充、搜索、归档迁移、快照恢复、产物存储、CLI 与隔离安装、契约及发布门禁。每个模块的节点数见 JSON `default_pytest.module_counts`。
- 遵循仓库默认收集规则；`collect_ignore` 排除 66 个历史退役测试文件，完整清单见 JSON。未强行恢复针对已移除模块的测试。
- 默认套件中的 live smoke 通过环境变量单独启用并执行；没有收集到独立可执行的 scale 场景，不能宣称做过压力容量验收。

## 执行结果

| 验证项 | 结果 |
| --- | --- |
| 当前版本全量 pytest | 3143 passed / 0 failed / 0 errors / 11 skipped |
| 行覆盖率 | 21210 / 25128 = 84.41%，门槛 75% |
| 分支覆盖率 | 6665 / 9024 = 73.86%，门槛 63% |
| 契约发布收集门禁 | 9 条升级边、3 个冻结文件验证通过；基线 `05fba1341a26c5eeb9cfd77629ce09314e5b26f4` |
| 锁定依赖安全审计 | 默认 + dev + remote，66 个依赖，已知漏洞 0 |
| wheel / sdist 构建 | 通过 |
| 干净虚拟环境 wheel 安装与资源核对 | 通过；pip check、CLI help、契约镜像、SQL/JSON authority 字节校验均退出 0 |
| 实网 smoke | 1 passed / 1 failed / 1 skipped；上游限流 |
| GPU 环境检查 | exit 1，5 项失败 |
| 阅读站 Node 测试 | 10 passed / 0 failed |
| 阅读站锁定依赖审计 | npm 官方审计接口通过，exit 0；详细级别计数见 JSON |
| 阅读站目录校验 | 20 篇通过 |
| 阅读站生产构建 | 通过；主 JS 2689.66 kB，gzip 812.56 kB，存在体积告警 |
| 阅读站浏览器交互 | 16 组通过 / 0 失败；桌面 1365×900、移动视口 390×844 |

其他当前版本检查：

| 检查 | 结果 |
| --- | --- |
| lock | 通过（exit 0） |
| lint | 通过（exit 0） |
| compile | 通过（exit 0） |
| contracts | 通过（exit 0） |
| audit-export | 通过（exit 0） |
| audit | 通过（exit 0） |
| build | 通过（exit 0） |

浏览器检查使用实际生产构建，逐一访问 20 篇阅读稿和 20 篇审核稿，验证目录、`/` 搜索快捷键、搜索/空结果/重置、全部标签筛选、阅读与审核页切换、目录锚点、返回目录、不存在路由、主题保存后刷新、首页及文章页无横向溢出；每组使用独立浏览器上下文并监控 `pageerror`，16 组均无页面 JS 异常。不点击 GitHub Issue 或外部视频链接，不产生外部写入。

## 问题与复测记录

### REG-WSL-001：editable 安装路径错误（测试环境，已解决）

初始 WSL 全量记录为 3215 passed、8 failed、12 errors、11 skipped。7 个失败涉及子进程 `ModuleNotFoundError: No module named 'bili_asr'`：`.venv-wsl` 的 editable 配置指向不存在的重复目录 `/mnt/c/WorkSpace/bilibili-asr-archive/bilibili-asr-archive/src`。直接导入和子进程安装状态不同，不能将此归因于工作流恢复实现。

在 WSL 运行 `.venv-wsl/bin/python -m pip install --no-deps --no-build-isolation -e .` 后修复。崩溃恢复、并发补充导入、正文导入和契约相关复测 96 passed；最终当前版本全量结果以上表为准。证据：`.tmp/wsl-editable-install-20261012.log`、`.tmp/wsl-retry-final-20261012.xml`。

### REG-WSL-002：隔离安装缺少离线依赖（测试环境，已解决）

初始 1 个失败和 12 个 setup error 来自 `No matching distribution found for jsonschema<5,>=4.25`。按 CI 要求向 `.test-wheelhouse` 下载 Linux/Python 3.12 可用的 jsonschema 及其传递依赖，并显式设置 `BILI_ASR_TEST_WHEELHOUSE`。安装与 baseline 复测 15 passed；当前版本全量和新 wheel 干净环境安装均继续覆盖。证据：`.tmp/wsl-wheelhouse-20261012.log`、`.tmp/wsl-installed-final-20261012.xml`、`.tmp/wsl-current-clean-wheel-20261012.log`。

### REG-WSL-003：公开元数据实网请求限流（外部依赖，未解决）

当前版本复现节点 `tests/test_bilibili_api_gateway.py::test_live_smoke_single_public_page_for_archive_owner` 失败：

```text
live one-page smoke ended in a bounded upstream failure (code='rate_limited'); rerun when upstream recovers
```

`tests/test_live_metadata_smoke.py::test_live_smoke_fetch_meta_one_page_lands_normalized_rows` 按现有测试策略跳过，原因同为匿名请求 `rate_limited`、exit 2；`tests/test_live_subtitle_smoke.py::test_live_subtitle_probe_reports_one_real_part_inventory` 通过。结果仅代表探测时刻，没有将测试 skip 改为通过，也没有反复请求上游。应在上游恢复或明确配置凭据的测试环境下重新验证元数据成功路径。证据：`.tmp/wsl-current-live-20261012.log` / `.xml`，默认与实网结果分别统计。

### REG-WSL-004：本地 GPU ASR 环境不可用（部署环境，未解决）

使用 `.venv-wsl-asr/bin/python scripts/check_asr_env.py`，5 项检查失败，实测包括：`/dev/dxg` 路径存在但未打开，`HSA_ENABLE_DXG_DETECTION` 未设置；动态加载路径未找到 ROCm 用户态库；torch 为 `2.14.1+cpu`、HIP 缺失；torch/lib 未找到 `libhsa-runtime64.so`；`torch.cuda.is_available()` 为 False。

这些结果不足以判断物理 GPU 或驱动损坏，但说明此虚拟环境不能用来验收 GPU 推理。离线 ASR 测试含 fake 模型，不能替代真实模型识别质量、对齐准确度和吞吐测试。本次未修改 GPU 部署或生产运行时。证据：`.tmp/wsl-gpu_environment-20261012.log`。探针源码在两次冻结之间字节未变化。

### REG-WSL-005：阅读站主 JS 包过大（性能告警，未解决）

生产构建主 JS 为 **2689.66 kB，gzip 812.56 kB**，超过 Vite 默认 500 kB 的 chunk 告警阈值。阅读稿和审核稿通过 eager raw glob 随主入口加载，后续应评估内容按需加载或拆包。当前构建和交互通过；没有做限速 Web Vitals 或弱网测量，不能将包体积直接写成已证实的首屏耗时故障。证据：`.tmp/wsl-reading-build-20261012.log`、`reading-site/src/main.js`。

### REG-WSL-006：Chromium 缺少系统动态库（测试环境，已解决）

首次启动 Linux Chromium 失败：`libnspr4.so: cannot open shared object file`。为独立测试工具环境安装 Playwright Chromium 和官方 Linux 系统依赖后，桌面及移动视口 16 组检查全部通过。没有改动阅读站产品代码或锁文件。证据：`.tmp/wsl-reading-browser-20261012.json`，复现脚本 `.tmp/wsl_reading_browser_20261012.py`。

### REG-WSL-007：回归期间工作区版本发生变化（证据口径，已处理）

首轮固定副本有 3246 个默认测试节点，变化后的版本有 3154 个节点，差异涉及工作流失败恢复、编辑校对及其测试，不能把旧副本结果当成当前工作区结果。保留首轮的输入清单和完整日志；根据用户选择重新冻结当前版本并完整执行第二轮。本报告结果均标明所属版本，没有用两个版本间的数量变化推断回归优劣。

### REG-WSL-008：npm 镜像没有安全审计接口（测试环境，已解决）

`pnpm audit --json` 初次返回 `ERR_PNPM_AUDIT_ENDPOINT_NOT_EXISTS`，指向 `registry.npmmirror.com` 的 advisory endpoint。保留该失败日志，用命令级 `--registry https://registry.npmjs.org` 重新审计后退出 0，未改锁文件或依赖版本。证据：`.tmp/wsl-reading-audit-mirror-failure-20261012.log`、`.tmp/wsl-reading-audit-20261012.json`。

### REG-WSL-009：ASR 子进程信号量清理告警（运行时观察，定向复测未复现）

当前版本完整套件共 7 条 warning：1 条是测试刻意构造重复 ZIP 成员 `package.json` 时的告警；另 6 条出现在 `tests/test_asr_sessions.py::test_each_response_identity_field_is_fenced_before_returning_real_child_result[generation]`，Python 3.12 的 `multiprocessing.resource_tracker` 提示 `ResourceTracker called reentrantly for resource cleanup`、信号量 `might leak`。该节点在全量中通过，没有据此认定真实资源泄漏。

保留全量告警后，使用同一固定版本独立复测该节点两次，均为 1 passed，未再产生该告警。作为待观察项记录，未通过屏蔽 warning 或修改产品清理逻辑消除现象。证据：`.tmp/wsl-current-pytest-20261012.log`、`.tmp/wsl-resource-tracker-retry-20261012.json`。

## 默认跳过项与未验证边界

| 节点 | 原因 |
| --- | --- |
| `tests/test_artifact_root_write_probe.py::test_cli_rejects_an_unsyncable_root_before_taking_the_writer_lock` | legacy asr command was replaced by SQLite workflow handlers |
| `tests/test_artifact_root_write_probe.py::test_audio_inventory_reuses_the_invocations_resolved_roots` | derive-audio-inventory command was retired with the manifest queue |
| `tests/test_audio_reclaim.py::test_coordinator_archive_stage_reclaims_audio` | archive execution now belongs to SQLite workflow jobs |
| `tests/test_audio_retention_policy.py::test_coordinator_respects_keep_audio_policy` | archive execution now belongs to SQLite workflow jobs |
| `tests/test_bilibili_api_gateway.py::test_live_smoke_single_public_page_for_archive_owner` | live smoke is opt-in: set BILI_LIVE_SMOKE=1 to request it |
| `tests/test_live_metadata_smoke.py::test_live_smoke_fetch_meta_one_page_lands_normalized_rows` | live smoke is opt-in: set BILI_LIVE_SMOKE=1 to request it |
| `tests/test_live_subtitle_smoke.py::test_live_subtitle_probe_reports_one_real_part_inventory` | live subtitle probe is opt-in: set BILI_LIVE_SMOKE=1 to request it |
| `tests/test_migration_source.py::test_standalone_reader_refuses_database_under_junction` | Windows junction path semantics |
| `tests/test_proofread.py::test_cli_proofread_writes_under_proofread_work` | standalone proofread CLI was replaced by workflow proofread jobs |
| `tests/test_proofread.py::test_cli_proofread_merge_publishes_and_counts` | standalone proofread merge CLI was replaced by workflow rendering |
| `tests/test_quality.py::test_recorded_cue_fixture_still_exits_zero` | legacy manifest-backed quality CLI was replaced by workflow quality evidence |

本轮没有执行真实付费 AI 请求、远程部署、生产 worker 操作或线上队列状态统计；没有使用当前报告断言历史生产异常已修复。安全审计范围为默认 + dev + remote 的锁定依赖，不包括重量级 ASR 或 youtube extra。浏览器结果是 Chromium 桌面及移动视口模拟，不含其他浏览器内核、真实手机、截图基线对比或完整无障碍审计。

当前版本默认套件未记录失败或 setup error；实网失败和 GPU 环境限制仍按上述问题保持未解决。

## 复现与原始证据

WSL 执行入口：

```bash
bash /mnt/c/WorkSpace/bilibili-asr-archive/.tmp/run_wsl_current_regression.sh
```

该脚本读取 `.tmp/wsl-current-snapshot-path.txt`，设置固定副本的 `PYTHONPATH` 和离线 wheelhouse，用源码树外 `--basetemp` 执行默认全量测试并生成覆盖率。再次运行会覆盖同名日志，复核历史结果应先复制到新输出前缀。契约发布门禁使用实际收集节点与父提交 registry 做比较；返回内容保存在本报告 JSON 中。

- 当前 pytest：`.tmp/wsl-current-pytest-20261012.log`、`.xml`、`.exit`。
- 当前覆盖率：`.tmp/wsl-current-coverage-20261012.json`、`.xml`、`.txt`；门禁 `.tmp/wsl-current-coverage-gate-20261012.log`。
- 当前质量与安全：`.tmp/wsl-current-checks-20261012.json`、`.tmp/wsl-current-audit-results-20261012.json`。
- 当前打包安装：`.tmp/wsl-current-build-20261012.log`、`.tmp/wsl-current-clean-wheel-20261012.json`。
- 阅读站：`.tmp/wsl-reading-tests-20261012.log`、`.tmp/wsl-reading-validate-20261012.log`、`.tmp/wsl-reading-build-20261012.log`、`.tmp/wsl-reading-browser-20261012.json`。
- 首轮环境失败：`.tmp/wsl-regression-pytest-20261012.log` / `.xml`；原固定版本：`.tmp/wsl-final-pytest-20261012.log` / `.xml`。

`.tmp` 为本地诊断目录，通常不进入 Git。关键计数、失败文本、跳过原因、输入清单和日志 SHA-256 已写入 `docs/evidence` 的 JSON 记录；分享完整原始日志时需另行携带 `.tmp` 对应文件。本次只写测试证据和测试环境配置，未为消除失败修改产品源码、测试断言或 skip 策略。
