# YouTube 字幕抓取修复与 WSL 验证

日期：2026-10-10（Asia/Hong_Kong）。分支：`codex/youtube-review-fixes`。
基线：`b584f6ac29b9e6acf598496c255ee73753063074`。

Issue #278 已随 PR #293 合并并关闭。本次修复最新实现中的字幕接入缺陷，
不重复实现已合并的多平台 schema、迁移器或 YouTube adapter。

## 修复行为

- yt-dlp 的字幕 URL `lang/tlang` 和自动字幕 `-orig` 标记优先于视频语言推断。
  这避免视频语言缺失或与字幕源语言不同时，将自动翻译误标为原始字幕。
  URL 留在 adapter 内，持久 provenance 只记录语言与翻译状态。
- 明确的自动翻译默认不参与选轨；原始人工字幕优先于原始自动字幕。
  仅有翻译轨道时保留 `youtube_caption_translation_only` 的 unavailable 观察和失败尝试，
  不生成可信无字幕证据，不让该结果进入自动音频缺口队列。
- 32 条预算限制实际正文尝试数。大清单可在预算内取得有效字幕；耗尽且仍有未尝试候选时
  返回 `youtube_caption_candidate_budget`，而不是在读取首个候选前失败。
- `[]/false/空字符串/0` 等畸形清单不再通过空值回退变成成功空清单。
  非法轨道字段、URL 或原语言均映射为有界 `youtube_caption_inventory_shape`。
- 成功观察新增 `youtube-original-captions-v1` 选轨策略和实际尝试数。
  无字幕资格策略、数据库契约和历史观察保持原有版本。

## 实际验证

独立 WSL 原生目录：`/home/chosenecho/youtube-review-fixes-20261010/repository`。
Ubuntu-24.04，Python 3.12.3，内核 `6.6.114.1-microsoft-standard-WSL2`。
使用项目 lock 导出的 dev + youtube 依赖创建独立 venv，安装 editable 项目；
不使用 Windows `.venv` 或生产 GPU 环境。

| 检查 | 结果 |
| --- | --- |
| 新回归在未修复基线运行 | 10 failed、29 passed，复现目标缺陷 |
| 首轮 YouTube 专项 | 39 passed |
| 最终受影响回归 | 223 passed、0 failed、0 skipped；94.80 秒 |
| 修改 Python 文件 Ruff `E9,F` | 通过 |
| 修改产品文件 compileall | 通过 |
| `uv lock --check` | 通过；依赖未变更 |
| 锁定 yt-dlp 的实际 CLI 参数解析 | `--help` 通过；无网络请求 |
| 隔离 mutation | 反转翻译过滤谓词后 5 条选轨回归失败；finally 恢复源文件原字节 |

最终回归覆盖 YouTube adapter/工作流、来源 registry/adapter/search/request scope、
通用归档与出版、字幕候选、工作流依赖注入、音频暂存、架构边界，以及旧源预检和保真样本。
YouTube 测试运行真实受控子进程，包含超时、输出预算、取消及退出 leader 的后代回收；
提取响应使用本地 fixture，不访问真实视频。

日志保存在 `/home/chosenecho/youtube-review-fixes-20261010/`：
`before-fix.log`、`after-fix.log`、`regression.log`、`pytest.xml`、`mutation.log`。

```sh
python -m pytest -q \
  tests/test_youtube_source.py tests/test_youtube_workflow.py \
  tests/test_source_registry.py tests/test_source_adapters.py \
  tests/test_source_search.py tests/test_source_request_scope.py \
  tests/test_universal_archive.py tests/test_universal_publication.py \
  tests/test_subtitle_candidates.py tests/test_workflow_source_factories.py \
  tests/test_workflow_audio_staging.py tests/test_architecture_boundaries.py \
  tests/test_migration_preflight.py tests/test_migration_preservation_baseline.py
```

## 验证边界

本机已安装锁定的 yt-dlp 2026.8.19、yt-dlp-ejs 0.8.0 和 ffmpeg/ffprobe；
`source doctor` 如实报告缺少 Deno、`ready=false`。
未执行真实 YouTube 网络、账号、GPU ASR 或生产迁移验收；以上结果不是在线抓取成功证明。
提取器未给出可判断的翻译证据时仍保留 `translated=null`，不把未知强行标成已确认原语言。
