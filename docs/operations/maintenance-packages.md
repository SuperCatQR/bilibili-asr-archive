# 离线维护包（第一阶段）

`maintenance` 提供可离线检查、带依赖闭包的私有历史包，以及只安装到新目录的
plan/apply/check 流程。它实现 issue #369 允许的第一阶段离线单向维护包。
完整 issue 的增量同步、定时备份、保留策略和 replace/merge 仍未实现。

```powershell
bili-asr maintenance export --source-root D:\archive --output D:\packages\archive.zip
bili-asr maintenance export --source-root D:\archive --part-id 12 --part-id 18 --output D:\packages\parts.zip
bili-asr maintenance export --source-root D:\archive --bvid BVexample --output D:\packages\video.zip
bili-asr maintenance inspect --package D:\packages\parts.zip
bili-asr maintenance verify --package D:\packages\parts.zip
bili-asr maintenance import-plan --package D:\packages\parts.zip --target-root D:\restored --output D:\packages\plan.json
bili-asr maintenance import-apply --plan D:\packages\plan.json
bili-asr maintenance import-check --target-root D:\restored --plan-id <plan_id>
```

源归档须已停止写入并完成 checkpoint；任何非空 WAL/journal、running 的任务或
attempt、进行中的采集 run、未完成的编辑模型调用都会拒绝导出。工具持有归档
维护锁，但不能替代停止不遵守该锁的旧进程。仅支持已有的统一本地产物目录，
不同 `--artifact-root`、只在远端存在的对象和未知根目录文件会拒绝。先完成显式
物化再导出。模型权重、凭据文件、缓存、日志和旧操作 manifest 按声明排除。

当前唯一 profile 为 `private-history`：数据库、冻结 JSON、prompt/response 和审计
历史保持原样，可能含私有文本，适用于受控归档迁移。它不会把公开阅读站导出
伪装成可恢复数据库。完整包按 checkpoint 后原数据库字节保存，包含全部已注册
扩展和本地产物；导入不恢复任务状态、不排队、不运行 ASR/LLM、不下载源媒体。

按 video/part 选择只支持没有扩展或派生搜索索引的原生 `bilibili-v1` 和
`universal-v2`。全归档迁移记录、preserved-body-import、supplement、artifact catalog、
online storage、rights 等扩展需要完整包；未经注册的选择规则会明确拒绝。
所选 part 保留所有转录版本、失败 attempt、编辑输入/调用/修订、审核事件和
current/superseded/withdrawn 发布物。闭包遵循外向（含组合）FK、明确归属的
子历史和工作流 payload/result 中已登记的身份字段。跨 part 引用会拉入该 part
的完整历史；共享 creator/profile/run 不会拉入不相关的兄弟 part。manifest 分别
记录显式选择、展开后的 part ID 和闭包策略。数据库以新文件逐行复制原 rowid
及 SQLite 值，未选行不会先写入再删除而留在 freelist。原始字幕源文件及对应
transcript bundle/sidecar 按所选源身份命名空间补充，不仅依赖 DB 中当前引用。

包是 ZIP，包含 `maintenance.json`、`archive.db` 及规范化本地相对路径。
manifest 的注册契约是 [`archive-maintenance-package/v1`](../contracts/archive-maintenance-package-v1.schema.json)，
记录源 runtime/数据库契约、源总指纹、producer version、UTC 时间、scope、每个
文件 size/SHA-256、保留 storage class 和 rowid 的表指纹及隐私策略。选择包不列出
未选文件的路径与 hash。`content_id` 绑定确定性的解码内容及源指纹；创建时间和
producer version 不参与该身份。ZIP 容器时间戳不保证字节级确定。

`inspect` 只检查包结构和 manifest 身份，输出 `payload_verified: false`。
`verify` 流式读取每个成员并检查 hash、表指纹、DB 契约/FK、全部已知 artifact
引用及 bundle marker。两者无需源归档、凭据或模型；不修改业务数据库。
重复路径、大小写/Unicode 碰撞、路径越界、links、特殊文件、加密成员、未列成员
和超大 manifest 都拒绝。单个 JSON 文档最大 16 MiB；文件内容分块处理。

`import-plan` 完整验证包，并在不创建目标的情况下检查新目录冲突、路径和空间。
计划绑定包容器 hash、content ID、目标绝对路径和 staging 空间估算。PK/FK 身份
不重编号；目标必须不存在或为空，所以不存在 merge 的身份映射和覆盖行为。
`import-apply` 重新预检，在同卷兄弟临时目录解包，写入
`documents/maintenance/<plan_id>/receipt.json`，验证完整安装后原子重命名目标。
staging 失败会清理临时目录，下次从头安全重试；不是断点续传协议。
相同计划重复 apply 在原安装基线未变时返回 `reused: true`。不同计划、改动的包、
已变更数据库/产物或额外文件会拒绝；应保留新工作再另取完整包。
`import-check` 不需要原包，验证 receipt、manifest、安装后的原数据库字节和每个
文件，报告 `installation_baseline_matches`；它不声称持续运行后的归档仍等于初装。

接受证据由 `tests/test_maintenance_package.py` 覆盖冻结历史完整 roundtrip、选中
part 的完整历史及未选对象排除、NULL 失败结果、跨 part JSON/FK 闭包、原生 v2
选择、扩展完整包、重复安装、包/目标 drift、恶意 ZIP 和 staging 中断重试。
