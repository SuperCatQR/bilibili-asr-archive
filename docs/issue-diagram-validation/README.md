# 本轮新增图表验证

八张图统一绑定源码提交 `857906d3b3c54b31fd9bc0ba94b84618f68cd6f3`，核对日期为 2026-10-10（Asia/Hong_Kong）。图的版本身份独立于后续文档提交；原有 19 张图继续保留自己的固定提交，不用新增版本号覆盖历史证据。

| 图 | 可审阅说明 / 交互产物 | 最终规格、HTML 与验证凭据 |
| --- | --- | --- |
| 多平台归档边界 | [实现与架构](../issues-implementation.md) · [HTML](../issues-architecture.html) | [JSON](../issues-architecture.json) · [receipt](issues-architecture/receipt.json) |
| 显式旧归档迁移 | [说明](../sequences/18-universal-migration.md) · [HTML](../sequences/18-universal-migration.html) | [JSON](../sequences/18-universal-migration.json) · [receipt](18-universal-migration/receipt.json) |
| 持久 ASR 与监督进程 | [说明](../sequences/19-persistent-asr.md) · [HTML](../sequences/19-persistent-asr.html) | [JSON](../sequences/19-persistent-asr.json) · [receipt](19-persistent-asr/receipt.json) |
| 恢复计划与环境 | [说明](../sequences/20-recovery-plan.md) · [HTML](../sequences/20-recovery-plan.html) | [JSON](../sequences/20-recovery-plan.json) · [receipt](20-recovery-plan/receipt.json) |
| YouTube 单视频闭环 | [说明](../sequences/21-youtube-workflow.md) · [HTML](../sequences/21-youtube-workflow.html) | [JSON](../sequences/21-youtube-workflow.json) · [receipt](21-youtube-workflow/receipt.json) |
| 字幕候选与旧依赖 | [说明](../sequences/22-subtitle-candidates.md) · [HTML](../sequences/22-subtitle-candidates.html) | [JSON](../sequences/22-subtitle-candidates.json) · [receipt](22-subtitle-candidates/receipt.json) |
| 元数据增量与刷新 | [说明](../sequences/23-metadata-refresh.md) · [HTML](../sequences/23-metadata-refresh.html) | [JSON](../sequences/23-metadata-refresh.json) · [receipt](23-metadata-refresh/receipt.json) |
| 来源冻结、审核与混合出版 | [说明](../issues-publication-sequence.md) · [HTML](../issues-publication-sequence.html) | [JSON](../issues-publication-sequence.json) · [receipt](issues-publication-sequence/receipt.json) |

每张最终候选通过 Showcase **9/9、0 errors、0 warnings**，`validate`、`deliver`、strict `check` 和真实 Chrome `browser-check` 四阶段全部通过。每份 receipt 记录相对文件路径、规格与 HTML 的 SHA-256、固定源码、门禁、浏览器产物身份和 update 状态。源码检查另见 [source-checks.json](source-checks.json)：八张图的 **121 处行引用、52 个提交内源码文件**与当前内容一致，行范围有效。

自动浏览器验证使用 READ/Still，覆盖四档 light 桌面视口及两档 dark 状态、横向包含、可读纵向滚动、主题及 viewer 控件。长时序的纵向滚动是正常阅读行为；图上的先后位置不表示真实执行耗时。自动检查不能代替设备性能测试，也不证明业务外部系统已经部署。

架构图根据交叉提示完成一次只改位置/尺寸的布局审查，已解析交叉提示由 8 降至 5，随后重新通过完整门禁。最终产物另行生成四张绑定 HTML 摘要的截图，实际查看了 1440×900 light 与 2048×1320 dark：主路径与标签可读，小桌面保留纵向滚动，仍有五处交叉建议。receipt 将自动截图证据与这次实际感知查看分别记录，不声称零交叉。

七张时序图的 `visualReview` 均为 `not-requested`，声明范围为自动化检查。出版、22、23 在本轮布局阶段根据宽度建议采用 `column_fit=spread`；18 完成一次 spread 尝试后按交付要求恢复 fixed，仍保留约 29.1% 右侧空白建议。其 [历史宽度记录](18-universal-migration.width-review.json) 明确属于 `5aa729...` 的布局阶段，最终 receipt 绑定 `857906d...` 的产物，不能互换文件摘要。再次绑定最终源码时没有继续迭代布局。

完整原始 finalize/browser/capture 证据保存在本机忽略目录 `.archify/final-diagrams-20261010/` 和 `.archify/final-sequences-20261010/`，仓库只保存可移植的最终凭据。重放时使用各图冻结 JSON，在全新 evidence 目录运行：

```bash
node /path/to/archify/bin/archify.mjs finalize architecture \
  docs/issues-architecture.json docs/issues-architecture.html \
  --repo-root . --quality showcase --out-dir /tmp/archify-replay/architecture --json
node /path/to/archify/bin/archify.mjs finalize sequence \
  docs/sequences/18-universal-migration.json docs/sequences/18-universal-migration.html \
  --repo-root . --quality showcase --out-dir /tmp/archify-replay/migration --json
```

不同产物共用输出目录时需顺序交付，不能通过删除锁绕过 provenance。重放生成的新 HTML 须使用同次新 receipt；当前精确 SHA 只对应本仓库保存的交付字节。
