# 历史文章简介补充

`publication supplement-source plan --field description` 从本地已采集的
`video_details.desc` 创建计划，`apply` 创建新的 `pending-review` 子版本。
它不调用 B 站或 AI，正文 UTF-8 字节、编辑摘要、标题、文章标签和旧发布版本保持原样。
补充后的 `sourceMetadata.description` 不是文章的 `summary`。

本次支持已执行 `publication import-preserved` 的历史 v2 文章。
原生 v2 文章按 `not-preserved-legacy` 跳过；它们仍保留 AI 输入当时冻结的来源信息。
已有 `partTitle` 补充证据的文章明确阻止再次补简介，目前不支持多字段补充链。
简介为 `null` 的本地来源会阻止计划；真实采集到的空字符串可以补入。
已冻结非空或空字符串简介的文章跳过，不覆盖旧事实。

```powershell
# 在离线升级并安装 import-preserved、supplement-source 扩展的归档副本上执行。
# selection.json: {"editionIds": ["当前文章版本的 32 位 ID"]}
bili-asr publication supplement-source plan --archive-root <archive> --field description --selection-file selection.json --out description-plan.json --format json
bili-asr publication supplement-source apply --archive-root <archive> --plan-file description-plan.json --actor <operator> --format json
bili-asr publication supplement-source check --archive-root <archive> --edition-id <new-edition-id> --format json
```

计划绑定当前文章 hash、草稿头、发布头、来源 identity/CID 和简介值。
执行期间任意一项改变都会整批回滚，须重新生成计划；相同计划重复执行返回同一回执。
新版后续人工编辑继续继承不可变来源证据。原文及其历史 AI 产物无需重生成。
新版本须走现有 `review`、`publish` 流程，`apply` 不批准或发布。

公开证据使用 `legacy-description-supplement-v1` policy，
`archive-video-details-projection` sourceKind，version 2 supplement。
`observedAt` 仅取简介字段成功采集记录的 `last_success_at`，
并核对保存的 `value_json`。后来请求失败不丢失上次成功证据。
缺少逐字段采集证据时为 `null`，不会把整行的更新时间当作简介采集时间，
更不会声称简介就是历史文章发布时的原始值。注册时间与采集时间分开保存。

新简介版本必须用 `--contract-profile universal-origin-v2` 导出。
catalog 仍为 v3，source-metadata 仍为 v1；origins schema 为 2，manifest 为 3。
旧 `universal-origin-v1` profile 及既有冻结 schema 不变，并明确拒绝简介补充版本。
当前 `markdown-reading-site` 仅支持旧 profile：在消费者实现新 profile 之前，
新简介版本只能在本仓库验证和审核，不能导入现有 reader。
实现不修改另一仓库或绕过消费者的未知字段检查。

新 profile 接受旧原生、保留旧正文、partTitle 补充的 origin，也接受简介补充。
简介值、hash、采集时间、policy 和每字段 metadataEvidence 会交叉验证；
不能改一个 JSON 的值或时间再声称证据仍有效。
