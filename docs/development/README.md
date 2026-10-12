# 开发与维护

[返回文档入口](../README.md)。实现、契约和图表各自有权威来源；修改后按相应入口验证。

| 文档 | 范围 |
| --- | --- |
| [CI 覆盖率](ci-coverage.md) | 产品源码范围、子进程采集、阈值与本地复现 |
| [发布说明模板](version-release-template.md) | 行为、契约身份、历史证明、运行交接和成本 |
| [契约治理](../contract-governance.md) | 登记、结构与语义校验、固定历史样本和升级边界 |
| [契约镜像](../contracts/README.md) | Schema、registry、版本矩阵及离线校验 |
| [架构图维护](../architecture-maintenance.md) | 固定源码证据、JSON 规格、生成和浏览器验收 |
| [SQLite 参考](../metadata-storage.md) | 数据所有权、身份、观察、表与视图 |

## 文档维护规则

功能使用放 `guides/`，识别配置与执行放 `asr/`，归档和环境操作放 `operations/`，开发门禁放 `development/`。日期与环境绑定的验收、实验结果放 `evidence/`，保留原提交、失败与限制，不改写成当前状态。长期指南用功能命名；Issue 编号可保留在正文追溯。

新增或移动文档时同时更新分类页、`docs/README.md`、项目 README 和相对链接。35 张图保持在 `docs/` 根目录；规格和 HTML 修改必须按图表维护流程重新验收。`docs/contracts/` 是程序镜像，使用契约工具发布和检查，不能借整理目录修改 Schema 身份。`docs/wsl-rocm-gpu.md` 是探测工具输出的稳定路径。


[模块边界修复 #372–#383](module-coupling-fixes.md) 保留固定基线、责任调整和真实测试范围；最新整合身份见 [当前架构](../architecture.md)。
