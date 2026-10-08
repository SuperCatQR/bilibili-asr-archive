# CI 测试覆盖率门禁

PR 和 main CI 都在四个分片中运行完整的默认测试集，随后由
`tests / coverage report` 汇总覆盖率并执行门禁。该 job 已列入 main 的必需检查，
门禁失败会阻止合并。

## 测量范围

`pyproject.toml` 中的 coverage 配置只统计 `src/` 产品源码，同时启用行与分支测量。
未执行的源码文件也进入报告分母；测试代码和开发脚本不计入产品覆盖率。
因此新报告不能直接与此前包含 `tests/` 的总覆盖率比较。

使用 coverage.py 7.10.6 或更新版本，通过 `subprocess` patch 自动采集同一 Python
环境中的子进程，通过 `_exit` patch 在调用 `os._exit()` 前保存数据。
各进程写独立数据文件，四个分片上传后统一 combine；相对路径与路径别名避免不同
工作目录产生重复条目。

独立安装测试继续使用干净虚拟环境，不为测量而给产品 wheel 添加 coverage 依赖。
没有安装 coverage 的独立解释器、主动清理采集变量的环境，以及 SIGKILL 等无法
正常保存的进程，不保证能够采集。报告缺失覆盖不等于该模块没有测试。
真实 GPU 推理和默认跳过的 live/scale 测试仍不属于这项门禁的保证范围。

## 门禁规则

工作流分别要求产品行覆盖率至少 75%，分支覆盖率至少 63%。比较使用原始计数，
不会因为显示时四舍五入而放过低于阈值的结果。
检查器还核对源码文件清单：源码缺失、报告混入非产品文件或空测量均失败。
新增未执行的模块会降低覆盖率，不能从分母中静默消失。

这是固定最低门槛，不是逐提交自动递增的基线。覆盖率在门槛以上下降时不会自动阻断；
评审仍应检查高风险分支和新增行为。后续提高门槛应以完整四分片结果为依据。

初始 WSL 全集基线为行覆盖率 75.74%（7644/10092）、分支覆盖率 64.05%
（2156/3366）。`tests/conftest.py` 的 `collect_ignore` 停止收集旧控制流程测试，
但部分对应模块仍在源码中，因此这些文件现在会以低覆盖或零覆盖进入分母。
本次不重新启用已退役的测试，也不为提高百分比排除这些模块。

## 本地复现与排查

在项目根目录、已安装 dev 依赖且 ffmpeg 可用的环境中执行：

```bash
python -m coverage erase
python scripts/pytest_shard.py --shard-index 0 --shard-count 1 --coverage -- -q
python -m coverage combine
python -m coverage report
python -m coverage json -o coverage.json
python scripts/check_test_coverage.py coverage.json --line-min 75 --branch-min 63
```

CI 的 `coverage-<run_id>` artifact 保留 XML 和 JSON 报告 14 天，门禁失败后仍会上传。
JSON 包含逐文件行和分支计数，用于区分功能未测试、子进程未采集和文件路径映射问题。
不要通过排除产品模块、计入测试文件或降低阈值来掩盖回归。

配置语义参考 [coverage.py 官方配置文档](https://coverage.readthedocs.io/en/7.16.2/config.html)。
