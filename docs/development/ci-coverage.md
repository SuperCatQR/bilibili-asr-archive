# CI 测试覆盖率门禁

PR 和 main CI 都在四个 Linux 分片中运行完整的默认测试集，另在 Windows
实际验证进程锁、并发补充和备份恢复，随后由
`tests / coverage report` 汇总覆盖率并执行门禁。该 job 已列入 main 的必需检查，
门禁失败会阻止合并。

## 依赖安装与分片

CI 使用固定版本 uv 0.11.14，并按 `uv.lock` 缓存下载与构建产物。
测试环境用 `uv sync --locked --extra dev` 安装；安全审计使用锁文件导出的默认、
dev 和 remote 依赖；Ruff、mypy、pip-audit 和 coverage 版本也从锁文件读取。
pip、setuptools 和 wheel 是隔离安装测试需要的构建工具，单独安装在测试环境中。
离线 jsonschema wheelhouse 下载使用锁文件导出的 runtime constraints，避免出现
主环境与隔离环境解析到不同版本的情况。产品 wheel 在独立环境中安装并按锁文件
约束运行时依赖，继续检查 console script、文档镜像及 SQL/JSON authority 字节。

分片先实际收集完整节点并运行契约发布门禁，再按测试文件分配到四个 runner。
同一文件内的参数化节点不会分开，模块 fixture 因而只在一片初始化。
调度读取 `scripts/pytest-shard-durations.json` 中每个测试文件的历史平均节点耗时，
按预计耗时从大到小分配给当前负载最小的分片，路径和分片索引用于确定性排序。
新增文件使用每节点 1 秒的默认估计，新增节点按实际收集数计算；历史记录中的
已删除文件不参与分配。耗时记录缺失时仍执行完整默认集，格式错误则明确失败。

耗时记录只影响测试归属，不决定哪些测试被执行。记录来自完整 Linux 四分片的
JUnit，包含环境、源码起点和各输入日志 SHA-256；WSL 与 GitHub runner 的耗时
不能等同。优化 SQL 规范化或 fixture 后需要重新测量，不能继续沿用旧权重。
更新耗时记录后须确认分片互斥且并集等于实际收集节点。

成功 CI 会在 coverage artifact 中提供 `pytest-shard-durations.json` 候选，
供人工检查后更新仓库中的同名文件。`scripts/update_pytest_durations.py` 按
每片的最新运行尝试选择报告：重跑失败 job 时保留其余成功分片的旧尝试，最新
artifact 缺少 XML 则拒绝沿用旧报告。脚本检查失败/错误、完整 testcase 数、
实际模块路径、合法耗时以及 JUnit 与 shard plan 的数量对应关系。
失败或中断的测试不能覆盖已有调度权重。下载同一 run 的 pytest diagnostics
并保留 artifact 目录名称后，在对应源码 checkout 中执行：

```bash
python scripts/update_pytest_durations.py pytest-diagnostics --shard-count 4 \
  --source-ref <tested-commit> --output scripts/pytest-shard-durations.json
```

保留四个分片和完整默认测试集。两个昂贵 fixture 通过 session 模板准备已经
迁移的档案，每个测试复制到独立目录并重新打开自己的数据库；权限仍在各自
副本中设置。复制拒绝 SQLite WAL、SHM 和 journal sidecar。迁移验收测试继续
直接执行实际迁移。契约校验只缓存有界的纯 SQL 文本规范化，每次仍读取实时
`sqlite_master`，并检查同连接或其他连接执行的 schema 修改。

测试 checkout 使用浅克隆，随后仅获取 PR base SHA 或 push before SHA，继续
运行同一契约发布门禁。ffmpeg 前置同时检查 ffmpeg 与 ffprobe；需要安装时
只访问签名验证的 Ubuntu 官方源，每次更新和安装均有超时，并提供另一个官方
镜像的有限回退。不会因为 runner 上其他无关 apt 源更新失败而阻塞整个安装。

每片将完整归属计划写入 `test-results/shard-plan.json`，并用 pytest 参数文件
传递选定节点，避免把长参数化列表拼进系统命令行。空片直接退出，不会误跑全库。
pytest 参数文件需要 8.2 或更新版本，当前锁定版本满足要求。临时目录放在
`RUNNER_TEMP`，避免隔离安装测试把 staging 放到源码树内。

失败诊断上传 `test-results/` 中的 JUnit、完整执行日志、分片计划，以及现有
`.tb/errors.log`。各片在独立 runner 上执行；本地并行复现也应使用独立 checkout，
不要让多个分片争用同一测试工作区。

## 测量范围

`pyproject.toml` 中的 coverage 配置只统计 `src/` 产品源码，同时启用行与分支测量。
未执行的源码文件也进入报告分母；测试代码和开发脚本不计入产品覆盖率。
因此新报告不能直接与此前包含 `tests/` 的总覆盖率比较。

使用 coverage.py 7.10.6 或更新版本，通过 `subprocess` patch 自动采集同一 Python
环境中的子进程，通过 `_exit` patch 在调用 `os._exit()` 前保存数据。
各进程写独立数据文件，四个 Linux 分片与 Windows 上传后统一 combine；相对路径与路径别名避免不同
工作目录产生重复条目。

独立安装测试继续使用干净虚拟环境，不为测量而给产品 wheel 添加 coverage 依赖。
没有安装 coverage 的独立解释器、主动清理采集变量的环境，以及 SIGKILL 等无法
正常保存的进程，不保证能够采集。报告缺失覆盖不等于该模块没有测试。
真实 GPU 推理和默认跳过的 live/scale 测试仍不属于这项门禁的保证范围。

## 门禁规则

工作流分别要求产品行覆盖率至少 80%，分支覆盖率至少 70%。比较使用原始计数，
不会因为显示时四舍五入而放过低于阈值的结果。
检查器还核对源码文件清单：源码缺失、报告混入非产品文件或空测量均失败。
新增未执行的模块会降低覆盖率，不能从分母中静默消失。

这是固定最低门槛，不是逐提交自动递增的基线。覆盖率在门槛以上下降时不会自动阻断；
评审仍应检查高风险分支和新增行为。PR 另逐文件要求修改的可执行行覆盖率至少
90%，以精确 PR base SHA 比较；排除行仍计为未覆盖。缺少模块报告或不能解析的
带引号路径明确失败，删除行、注释不要求执行证据。
`changed-coverage.json` 提供差异门禁明细，`coverage-risks.json` 和 Markdown
清单列出关键模块未覆盖的行与分支。完整规则见[质量管理](quality-management.md)。

## 本地复现与排查

在项目根目录、已安装 dev 依赖且 ffmpeg 可用的环境中执行：

```bash
python -m coverage erase
python scripts/pytest_shard.py --shard-index 0 --shard-count 1 --coverage -- -q
python -m coverage combine
python -m coverage report
python -m coverage json -o coverage.json
python scripts/check_test_coverage.py coverage.json --line-min 80 --branch-min 70
```

CI 的 `coverage-<run_id>-<run_attempt>` artifact 保留 XML 和 JSON 报告 14 天，门禁失败后仍会上传。
JSON 包含逐文件行和分支计数，用于区分功能未测试、子进程未采集和文件路径映射问题。
不要通过排除产品模块、计入测试文件或降低阈值来掩盖回归。

原始覆盖数据使用一级压缩，兼顾 SQLite 数据的传输体积和压缩开销；wheel 和
sdist 已压缩，使用零压缩上传，避免重复压缩产生额外 CPU 开销。
artifact 名称包含运行尝试编号，重跑失败 job 不会与原 artifact 同名冲突。
覆盖率汇总下载同一 run 的所有尝试：仅重跑失败 job 时，成功分片可能仍属于旧尝试；
同一 run 的尝试始终针对同一提交，因此保留旧成功片并合并重跑数据。

分片本地复现（WSL 或其他 Linux 环境）：

```bash
uv sync --locked --extra dev
uv pip install --python .venv/bin/python pip 'setuptools>=69' wheel
uv export --locked --no-dev --no-emit-project --no-hashes --output-file runtime-constraints.txt
.venv/bin/python -m pip download --dest .test-wheelhouse -c runtime-constraints.txt 'jsonschema>=4.25,<5'
.venv/bin/python scripts/pytest_shard.py --shard-index 0 --shard-count 4 \
  --plan-output test-results/shard-plan.json --coverage -- \
  -q -ra --basetemp /tmp/bili-asr-pytest-shard-0
```

若源码 checkout 本身位于 `/tmp`，应将 `--basetemp` 改到源码树之外的其他可写目录。

配置语义参考 [coverage.py 官方配置文档](https://coverage.readthedocs.io/en/7.16.2/config.html)。
