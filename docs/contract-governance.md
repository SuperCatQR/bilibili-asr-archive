# 契约治理与兼容边界

本轮修复对应 [#314](https://github.com/SuperCatQR/bilibili-asr-archive/issues/314)、
[#315](https://github.com/SuperCatQR/bilibili-asr-archive/issues/315) 和
[#316](https://github.com/SuperCatQR/bilibili-asr-archive/issues/316)。源码基线为 `6a8646a36f680705479a7669350fd8793551cc74`，
起点为 main `bab5998dd5235a7687b479e96edf16f9ed76c7ba`，随后合入当前 main `fd5a8068f988ed1394fdb0a7c723941cbdf5221b`（#317）。
[交互架构图](contract-governance.html)（[规格](contract-governance.json)）描述本轮登记、校验、
历史保真与文档发布边界；[验证记录](contract-governance-validation.md)说明实际检查范围。

## 权威来源与责任

`src/bili_asr/contracts/registry.py` 登记 34 项契约的稳定身份、owner、authority、consumers、
capabilities 和 dependencies，其中 15 项有可执行 JSON Schema。
登记记录是检索入口：数据库表结构仍由所属 SQL 和专用检查器定义，稿件内容身份仍由所属纯函数定义。
它不负责执行数据库初始化、来源采集、迁移或调度。

| 类别 | 权威定义 | 校验职责 |
| --- | --- | --- |
| 数据库运行契约 | `storage/archive_contracts.py` 与对应 SQL | 允许哪些运行访问；不在读取时升级旧库 |
| 快照数据库身份 | `contracts/database-fingerprints.json` 与 `storage/snapshots.py` | 固定 schema 指纹；完整库和产物保真 |
| 固定旧迁移源 | `storage/migration-source-bilibili-v1.json` 与 `migration_source.py` | 独立的严格源检查，只读；转换到明确目标 |
| workflow / profile / evidence | 登记的版本常量与各自模型、存储边界 | 类型、语义和持久化版本；延续既有缺省 payload v1 |
| 稿件 JSON 结构 | `contracts/schemas/` | 必填字段、字段集合、类型、枚举、版本与跨 Schema 引用 |
| 内容身份与模板 | `canonical_json.py`、`publication_content*.py`、`manuscript_templates.py` | 内容摘要、引用一致性、历史 Markdown 字节 |
| 公共标量输入 | `contracts/values.py` | 来源模型和存储模型共用整数、单行文本、字幕文本规则 |

`contracts` 不反向导入 storage、services、sources、CLI 或网络运行模块。
登记查询依赖标准库；JSON Schema 校验按需使用安装包的 `jsonschema` 和 `referencing`。
所有 `$ref` 都从本地资源 registry 解析；URI 是资源身份，不会触发 HTTP 获取。
未知版本或不支持的 capability 会明确拒绝。

## 结构与业务校验的调用边界

公开、预览、私有导出在 `export_snapshot.py` 的托管快照检查入口调用统一结构校验。
公开 catalog v3 的混合历史条目通过本地引用校验 v2 条目和来源元数据。
结构通过后继续检查真实整数、来源 URL/slug、模板/内容版本组合、文件集合、实际 SHA-256、
origins/series 引用关系及快照身份。JSON Schema 不替代这些语义与完整性检查。

catalog 只整体结构校验一次，随后逐条进行语义校验；Schema 与 validator 缓存于进程。
失败诊断包含契约身份、字段路径和校验关键字，不回显私有稿件内容或拒绝值。
既有 staging、锁、journal、marker 和替换协议沿用原入口。

## 支持矩阵与历史身份

| 边界 | 当前选择 | 兼容约束 |
| --- | --- | --- |
| 运行数据库 | `bilibili-v1` / `universal-v2` | 运行、快照、固定迁移源使用各自检查政策 |
| 迁移 | 固定 Bilibili v1 源 → `universal-v2` | 单独目标；旧源字节、历史行及 ID 保留 |
| workflow payload / ASR | payload v1、profile v2、evidence v1 | 版本常量集中；原有序列化和哈希算法不变 |
| 公共与预览 catalog | v2 / v3 | v3 支持明确的混合条目；未知版本无默认回退 |
| 普通 manifest | v1 | 公共、预览、私有各有独立 Schema |
| 来源导出 profile | `universal-origin-v1`、manifest v2 | catalog v3 加 origins v1；按显式 profile 验证 |
| 来源补充策略 | `legacy-part-title-supplement-v1` | 只使用明确的归档证据；依赖 preserved-body 扩展，独立固定指纹 |
| 普通私有审阅包 | 七文件布局 | `editorial-export-manifest/v1` |
| 迁移正文私有审阅包 | 十文件布局 | `editorial-import-export-manifest/v1`；多三个保留正文/来源/差异文件 |
| 私有 review JSON | envelope v1、AI 模板 v1 或 v2 | 两个布局身份分别校验；不能把旧模板常量改成接受任意值 |
| 输入、内容和模板 | frozen-input v1/v2、content v1/v2、AI/publish v1/v2 | 历史格式和新格式各自保留生成与读取规则 |

七文件与十文件 manifest 都保留既有 wire `schemaVersion: 1`；区别在登记的布局身份，
不伪造新的历史导出版本。review 也保留 envelope v1，以真实 `ai.templateVersion` 选择布局。
13 份已有 Schema 入包，新增两份独立 Schema；其中七文件 manifest 的结构校验修复为要求每个路径恰好出现一次，
十文件布局同样明确要求包含 import-origin.json，拒绝用重复路径替代必需文件，即使重复项哈希不同。
这是对原有准确文件集合约束的补全；有效历史输出仍通过，原格式、内容/产物哈希和生成 Markdown 不重写。
合入 #317 后，origins v1 延续旧策略分支，并按显式 `legacy-part-title-supplement-v1` 策略接受有证据的分 P 标题；
这项数据库扩展、导出策略及其对 preserved-body 扩展的依赖也已登记。

这次登记覆盖迁移和出版涉及的主要稳定边界，未把全部内部 DTO 自动变成外部协议。
新增持久化格式或外部消费格式时需要补登记及实际消费者，不能仅增加一条目录记录就声明已支持。

## 数据库指纹与冻结样本

`database-fingerprints.json` 保留起点提交的四个既有快照指纹：两个数据库契约，分别带/不带
preserved-body 扩展；另固定当前 main 的两个 source-supplement 扩展组合，共六个身份。带扩展的 v1 指纹仅保留原快照检查器的既有组合能力，不新增 v1 扩展安装入口。
检查器从当前 SQL 构建参考结构后必须匹配固定指纹；已有契约的 DDL 漂移会报错，
不能随着 writer 更新悄悄重定义旧快照。schema 指纹、快照内容身份、迁移源 fingerprint 是不同标识。

`tests/fixtures/migration_archive.py` 直接展开已经提交的 `bilibili-v1-frozen.zip` 与 JSON 清单，
不再调用当前 writer 重造旧库。样本保留固定 ID、38 张历史表、15 个托管文件及冻结 JSON/字节。
测试覆盖源与产物分根、旧样本不调用当前写入/渲染函数、迁移和输出字节保真、契约漂移拒绝。

Windows 初始化和转换的 owned staging 数据库用 `r+b` 描述符执行 `fsync`，
满足 Windows 的描述符要求；源文件仍以只读方式备份和校验。

## 变更流程与 CI 门禁

1. 在所属模块明确版本、读取兼容性和写入行为，新增登记的 owner、authority、消费者及依赖。
2. JSON 结构只在 `src/bili_asr/contracts/schemas/` 修改；需要改变历史语义时另建身份，保留旧定义。
3. 用真实消费者调用统一结构校验；关系、哈希、路径、数据库状态仍在原业务边界验证。
4. 新数据库契约建立独立 SQL、严格检查及转换路径，再保存明确的指纹；禁止自动刷新旧指纹来绕过失败。
5. 增加独立历史样本与有区分力的兼容/拒绝测试，更新文档矩阵与源码证据。
6. 发布文档镜像并执行门禁，完成代码提交后再绑定架构图的完整源码提交。

```powershell
python -m bili_asr.contracts
python -m bili_asr.contracts --write-docs docs/contracts
python -m bili_asr.contracts --check-docs docs/contracts
python -m pytest -q tests/test_contract_registry.py tests/test_architecture_boundaries.py
```

`docs/contracts/*.schema.json` 和 `registry.json` 是发布镜像，按字节校验并禁用 Git 行尾转换。
CI 在测试 lane 校验全部资源和镜像，在 package lane 校验真实 wheel 的资源。
安装测试先准备 `.test-wheelhouse`，测试期间只从本地 wheel 安装 Schema 依赖；
可用 `BILI_ASR_TEST_WHEELHOUSE` 指定其他本地目录。Windows 完整测试使用 `PYTHONUTF8=1`，
使父进程、子进程和中文样本使用一致编码。

```powershell
python -m pip download --dest .test-wheelhouse "jsonschema>=4.25,<5"
$env:PYTHONUTF8 = '1'
python -m pytest -q tests/test_installed_cli.py
uv lock --check --default-index https://pypi.org/simple
```

依赖锁由 uv 从官方 PyPI 重建：新增 Schema 校验依赖，既有包版本保持不变。
本机继承的镜像曾返回 metadata 404，验证 lock 时显式指定官方索引；CI 用清洁安装环境。

## 后续扩展

跨模块契约继续按稳定边界逐项登记。版本变化须写明消费者能力；发生不兼容升级时先交付旧格式读取、
目标 writer、转换和验证，再推进运行切换。来源采集规则、运行数据库的宽松政策和历史源的严格政策
保持在各自所有者内，登记负责把它们关联成可查、可验的依赖图。

## 发布验收矩阵与支持收缩门禁

`contracts.registry` 的 `UPGRADE_ACCEPTANCE` 与同一份 `UPGRADE_EDGES` 一一对应，
由 catalog 的 `release_acceptance` 发布到 `docs/contracts/registry.json`。每行指定
固定历史 ZIP、expected JSON 与验收测试的实际 node ID。带参数的精确节点绑定具体的
源/目标组合；无参数后缀的函数节点可匹配该函数的已收集参数化用例，不匹配相似名称。
当前历史源、原生源和各扩展组合在 `test_archive_upgrade.py` 使用可读参数 ID。

四个 CI 分片沿用 `scripts/pytest_shard.py`。它先完整执行 pytest collection，再验证
所有升级边都有矩阵行、固定文件存在且 SHA256 一致、每个要求的 node ID 真正出现，
最后才分配并执行测试。`collect_ignore`、删掉用例或删掉一个必要参数节点会阻断门禁；
测试文件仍存在、注释提到测试、静态扫描到函数名，都不算覆盖。门禁通过只说明验收用例
参与测试，不能替代分片执行成功、人工代码审查或真实运行环境验收。

矩阵还要求真实隔离安装测试参与收集。该测试从 wheel 所在环境遍历全部登记 authority，
通过 `importlib.resources` 读取 SQL/JSON 并与源码摘要逐项比较，同时验证所有 Schema
离线可用。新增扩展忘记进入 package-data 会直接失败，源码树可读不能替代 wheel 证据。

`FROZEN_RELEASE_FILES` 独立固定旧 ZIP 与 expected JSON 的 SHA256；旧文件保持原字节。
新增 `contracts-release-baseline-v1.json` 记录 `91aeb026` 的 capability/consumer 基线，
也被固定摘要保护。正常 PR 还比较基分支完整提交中的 catalog，push 比较此前提交，
CI 使用完整 Git 历史；指定基线读取失败会阻断。首次 push/手动本地运行仍有固定基线。
历史 catalog 已发布的冻结证据不可通过同时修改样本和当前摘要来重新绑定。

删除已知契约、减少 capability 或 consumer，必须在 `CONTRACT_TRANSITIONS` 中登记
`replacement` 或 `reader-retirement`、原因、精确 source/target、完整已登记路径和逐边
acceptance 证据。声明本身不能跳过矩阵：无路径、不连续路径、错误目标和缺验收均拒绝。
新增独立契约可以直接登记，不强造不存在的迁移前身。变更语义仍由所属检查器和历史
回归验证，门禁不会从版本号自动推断支持能力或自动执行升级。

发布说明使用 [版本发布模板](version-release-template.md)，列出行为变化、消费者版本、
剩余能力、昂贵补算、源到目标路径、历史保真证明以及运行交接。需要对任意历史提交
进行额外基线比较时，可向分片脚本传 `--contract-baseline-ref` 加完整 Git SHA。
