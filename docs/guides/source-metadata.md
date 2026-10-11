# 来源元数据和历史回填

这次实现把数据库里已经保存的视频简介、UP 主、标签和详情采集时间带到独立产物。它不会为了导出重新访问 B 站，也不会用简介替换编辑摘要或转录正文。

## 新产物

| 字段 | 来源 | 缺失和时间语义 |
| --- | --- | --- |
| `video_description` | `video_details.desc` | JSON/Markdown 为 `null`；CSV 为空，不填入 AI 摘要 |
| `uploader_mid` | `videos.mid` | Bilibili 整数标识；其他平台为 `null` |
| `uploader_name` | `bilibili_users.display_name` 或平台作者名称 | 当前保存的名字，不保证与详情同时采集 |
| `video_tags` | `video_tags` | 按 tag ID 排序、按名称去重的数组；CSV 用 JSON 数组字符串 |
| `video_tags_state` | `video_tag_observations.state` | `success_nonempty`、`success_empty`、`unavailable`，没有观察证据为 `null` |
| `video_details_observed_at` | `video_details.observed_at` | Unix 秒；详情行最后成功写入时间，不冒充所有字段共同采集时间 |

`bundle.md` 的 frontmatter 和 JSON/CSV 通用导出使用这些字段。CSV 六列追加在原标准列、可选正文列和已有额外列之后，原位置保持不动。同一个视频的所有分 P 共享简介，分 P 标题和身份独立保留。简介保留中文、换行、引号、反斜杠和普通链接；通用导出会继续过滤凭据、签名 URL 和 Bilibili 媒体链接，其他字段仍按原规则脱敏。

bundle v3 的 `source-metadata.json` 继续使用严格的 `source-metadata-v1` 快照，它是 bundle JSON 来源快照的权威副本。raw JSON 不重复嵌入来源快照；公开 `artifact_json` 仍是原来的五个路径，sidecar 由 v3 marker 纳入完整性验证。SRT、VTT、TXT 格式和正文不变。冻结快照的既有长度与字符校验仍会拒绝非法内容，不会静默截断。

## 历史 bundle 回填

先在维护窗口将源 archive 升级到一个独立的新 archive 目录，保留原目录；然后在新目录运行回填：

```text
bili-asr artifacts upgrade --archive-root <old-archive> --target-root <new-archive>
bili-asr workflow publish --archive-root <new-archive> --part-id <id> --preserve-transcript --dry-run
bili-asr workflow publish --archive-root <new-archive> --part-id <id> --preserve-transcript
bili-asr workflow run --archive-root <new-archive> --kind publish
```

如果 archive 已安装 artifact catalog，可直接使用它。产物有独立目录时，规划和执行都显式传 `--artifact-root` 或设置同一个 `BILI_ARTIFACT_ROOT`。回填必须有 catalog，避免旧文件在没有保存的情况下被替换；未安装时明确报错，不自动修改数据库 Schema。

`--dry-run` 列出当前最新 bundle 的 transcript、发布时间和两个内容哈希。实际回填把这组信息作为队列请求的一部分；worker 再核对它们，失败就停止并要求重新规划。它锁定原来发布的转录，即使后来又采到了更优字幕，也不会换正文。发布前验证旧 bundle 和 marker，把它们保存成不可变 artifact group，再生成新的 v3 bundle。旧文件和 marker 的字节可从 artifact objects 恢复；原转录段、ASR provenance、character timing、coverage 和历史执行记录保留。恢复到旧 slot 时仍遵循 artifact group 的冲突检查，不能用旧版本覆盖不同的新文件。

这次回填使用当前数据库中的元数据，不知道旧发布当天的简介。`video_description = null` 只能说明当前没有可用的已存简介。需要补抓缺失详情时，应另行执行来源采集并保留证据，然后再显式回填。回填只运行 publish job，无需联网、下载音频或运行 ASR。普通 `workflow publish` 继续按照已有规则选择当前最优转录，补简介应使用 `--preserve-transcript`。

## 通用导出和旧文章

重新执行普通 export 会获得当前数据库元数据，不改写旧 bundle。bundle 侧保留发布时快照，两者可能不同；详情时间与 source metadata 的既有 `metadataObservedAt` 含义也不同。

旧文章的简介补充生成新的待审子版本，复制原 markdown 正文和编辑摘要，旧版本与正式发布保持不变。具体操作、支持范围、严格的证据时间规则和阅读站新 profile 要求见 [历史文章简介补充](source-description-supplement.md)。文章补充不会自动通过审核或发布。
