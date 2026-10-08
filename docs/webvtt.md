# WebVTT 与五产物归档包

每次发布都从同一个存储转录版本生成 SRT、WebVTT、纯文本、Markdown 和原始 JSON。WebVTT 不触发新的字幕请求或 ASR 推理；它使用 SRT 同源的 cue 时间、文本和顺序。

## 产物与完整性

一个分 P 的完整目录如下，`p0` 是存储的零基 page index：

```text
transcripts/BV_EXAMPLE.p0/
  bundle.srt
  bundle.vtt
  bundle.txt
  bundle.md
  bundle.raw.json
  .bundle-ready
```

公共路径字段为 `srt_path`、`vtt_path`、`txt_path`、`md_path`、`raw_path`，均相对产物根目录记录。JSON 导出包含 `vtt_path`；CSV 的标准列顺序将它放在 `srt_path` 后。

`.bundle-ready` 使用 `archive-bundle-v2`，必须声明五项路径及各自的 SHA-256。只有路径、文件和五项摘要全部匹配，读者才承认完整包；缺少 VTT、损坏 VTT、遗漏 marker 条目或使用旧 marker 版本都会失败。验证逐块读取文件，不依赖大小与修改时间推断内容相同。独立验证 worker 使用同一契约。

发布前先在临时位置编码、写入、同步并计算摘要；最终替换前失效旧 marker，依次替换五项产物，最后提交新 marker。中途失败时没有有效 marker，读者不会把部分替换计为完成。工作流传入的 publication guard 覆盖全部最终替换、marker 提交和 publication 登记，使该阶段与取消操作串行化。guard 收到失败清理回调，在 SQLite 回滚和写锁释放前失效 marker；旧 attempt 退出时不能再删除接手 worker 的有效 marker。文件系统和 SQLite 仍是两个提交介质；异常后的可见性由 marker 和摘要共同保护。

`verify` 将已登记发布但缺失或损坏产物的包报告为缺陷，默认退出码为 1；未发布的转录保留为 backlog。`coverage` 不将缺少有效五产物包的分 P 计为 complete。两者使用配置的产物根目录及归档根目录作为读取候选，支持产物位于独立目录。

## 文本和时间规则

WebVTT 是 UTF-8 文本，使用 LF 换行。空序列的纯格式化结果为 `WEBVTT\n\n`；正常工作流仍要求存储转录至少包含一个有效 segment。

```vtt
WEBVTT

1
00:00:00.000 --> 00:00:02.501
第一行
第二行 &lt;b&gt; &amp; 字面文本

2
00:00:02.000 --> 00:00:04.000
允许时间重叠
```

时间先按与 SRT 相同的规则转换为整数毫秒，再格式化为 `HH:MM:SS.mmm`。小时可以超过两位。cue 的起点必须按原序不递减，终点必须大于起点；前后 cue 重叠允许。

普通多行文本保留；CRLF 和 CR 转为 LF。`&`、`<`、`>` 编码为文本引用，使浏览器显示原字符而不将它们解释为 WebVTT 标记。例如源文本的字面 `&amp;` 输出为 `&amp;amp;`，播放时仍显示 `&amp;`。

以下输入不能在保留原序与显示文本的前提下表示为本项目的合法 VTT，因此拒绝整个包发布，报告 cue 编号和有界原因：

- 起点倒序，或时间非有限、负数、毫秒取整后时长为零。
- 空文本、文本内部空行、开头或结尾空行，包括仅有空白的行。
- NUL 字符。

不会自动排序、丢弃 cue 或只发布剩余四项。纯 SRT formatter 的既有行为保留；普通存储数据仍由转录模型校验。本次额外的发布约束专门保护 WebVTT 的可表示性。格式依据为 [W3C WebVTT 规范](https://www.w3.org/TR/webvtt1/)。

## 重建已有包

旧四产物包不兼容 `archive-bundle-v2`，也不做自动迁移。存储转录无需重新获取；在兼容当前 workflow schema 的数据库上，显式为已有分 P 请求重新发布即可生成五项产物：

```sh
bili-asr workflow publish --archive-root data --part-id 12 --part-id 13
bili-asr workflow run --archive-root data --limit 2
bili-asr verify --archive-root data --format json
```

`workflow publish` 从已有存储版本中选择当前优先转录，为 publish job 请求重新执行。只请求发布不会下载音频或调用 ASR；`workflow run` 仍按队列优先级执行，若还有其他待执行任务，需继续运行到对应 publish job 完成，并通过 status 查看结果。普通重复 `workflow plan` 不保证已经成功的 publish job 再次执行。

已经取消的 publish job 保持取消状态，命令明确报告受抑制的请求；该命令不能作为恢复取消任务的途径。旧数据库的 attempt CHECK 约束若不支持当前取消契约，会得到 schema 不兼容诊断，须遵循 [功能实施计划中的旧库策略](feature-plan-247-250.md#旧库策略) 备份并重建，不能通过重新安装程序替代数据库重建。

## 离线验证

`tests/test_webvtt.py` 覆盖空格式化、毫秒及小时边界、中文多行、文本转义、重叠/倒序、不可表示文本、五产物 marker、VTT 缺失与同大小/mtime 篡改、独立验证 worker、guard 的提交范围、替换及提交失败清理，以及工作流发布后的 verify/coverage/export。使用归档根目录与独立产物根目录两种布局执行集成验证。
