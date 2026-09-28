# 音频保留策略使用指南

## 背景

`bilibili-asr-archive` 在视频转录完成并达到 `archived` 状态后，**默认保留音频文件**。

音频是唯一的证据：Bilibili 删掉视频后它无法再取回，换更合适的 ASR 模型重跑也要靠它，人工核对转录质量同样要对照它。所以保留是默认，**回收（删除）是显式选项**。

- ✅ 可以用更好的模型重新处理
- ✅ Bilibili 删除视频后音频仍在
- ✅ 可以对照原始音频验证转录质量
- ⚠️ 代价是磁盘占用：音频是转录文本的几十倍（见下方「磁盘空间考量」）

---

## 快速开始

### 保留音频（默认）

什么都不用做：

```bash
bili-asr pilot --n 20 --archive-root archive
```

### 归档后删除音频

```bash
# 只对这一次运行生效
bili-asr pilot --n 20 --no-keep-audio --archive-root archive

# 或者长期用环境变量
export BILI_KEEP_AUDIO=0
bili-asr run --scope pending --archive-root archive
```

### 保留音频、同时不让磁盘上界截断下载

保留意味着 `audio/` 只会增长，而 `--max-audio-gb`（默认 10 GiB）是 fail-closed 的：跑到某个点之后，每一行都会以
`audio_budget` 被跳过。要长期保留又想一直下载，就把上界设为不限（四个命令都接受 `0`，只有
`schedule --allow-long-live` 例外，见下）：

```bash
bili-asr campaign --scope pending --limit 500 --max-audio-gb 0 --archive-root archive
```

**只有 `pilot` 和 `run` 的跳过行会把这个参数名一并打出来**（`pilot` 打在 stderr，`run` 的行带 `run:` 前缀）：

```
BV1xx:p0: skipped (audio_budget); audio-dir budget cap reached (--max-audio-gb 0 = unlimited)
```

`schedule` 的跳过行只打原因（`schedule: <work_id>: skipped (audio_budget)`），`campaign` 只在 JSON 摘要的
`reason_codes` 里报告 `audio_budget` —— 两者都不带这段提示。另外 `schedule --allow-long-live` 要求上界必须
开着：在那个模式下传 `--max-audio-gb 0` 会被直接拒绝（退出码 1），要保留就请把上界调大。

---

## 配置项

`asr`、`pilot`、`run`、`schedule`、`campaign` 五个归档命令带 `--keep-audio/--no-keep-audio` 参数；参数在命令入口**解析一次**，然后作为值传给下游，库层不再读环境变量。

| 设置 | 行为 |
|-----|---|
| 什么都不设 | **保留**（默认） |
| `--keep-audio` | 保留 |
| `--no-keep-audio` | **回收**：archived 后删除该行的音频（两个根目录下都找） |
| `BILI_KEEP_AUDIO=1` | 保留 |
| `BILI_KEEP_AUDIO=0` | 回收 |
| `BILI_KEEP_AUDIO=` 其它值（含空/空白） | **保留**（默认） |

- **参数优先于环境变量**；环境变量只在没有参数时才起作用。
- `BILI_KEEP_AUDIO=" 1 "` **不是**字面量 `1`，因此等于「默认」= 保留。旧的 `== "1"` 比较会把它当成未设置而回收，新的规则不会。
- 回收是**尽力而为**的：行已经 `archived`（转录已落盘），回收失败不会让这一行变成失败。
- 回收会删掉该行音频的**所有副本**：配置根目录下的和归档根目录下的。「不要保留这一行的音频」指的是这个音频本身，不是某一个路径。
- **已经被回收的音频无法恢复**，这是整个功能里唯一不可逆的部分。

> 行为变化提示：本策略翻转之前，未设置 `BILI_KEEP_AUDIO` 表示**删除**。`=1` 和 `=0` 的含义没有变，只有「未设置」这一格从删除变成了保留。要恢复旧行为，显式设置 `BILI_KEEP_AUDIO=0` 或传 `--no-keep-audio`。

---

## 使用场景

### 场景1：长期归档 + 未来重新处理

```bash
# 首次归档（当时使用 Fun-ASR-Nano-2512；2026-09-24 起为 Qwen3-ASR-1.7B + 强制对齐器）；音频默认保留
bili-asr pilot --n 100 --max-audio-gb 0 --archive-root archive

# 2027年：有了更好的模型
# 音频文件仍在 audio/，可以直接重跑 ASR
bili-asr run --scope archived --offline --archive-root archive
```

### 场景2：防止 Bilibili 删除视频

```bash
# 音频默认就留着
bili-asr pilot --n 20

# 即使 Bilibili 删除了视频，你仍有：
# - audio/BV1xx.p0.m4a        （原始音频）
# - transcripts/...           （转录文件）
```

### 场景3：质量验证

```bash
bili-asr run --scope pending --archive-root archive

# 对比转录文本和原始音频
mplayer archive/audio/BV1xx.p0.m4a
cat archive/transcripts/BV1xx.p0/bundle.txt
```

### 场景4：磁盘吃紧，只要文本

```bash
# 这次运行归档完就删音频
bili-asr schedule --scope pending --limit 200 --no-keep-audio --archive-root archive

# 或者长期如此
export BILI_KEEP_AUDIO=0
```

---

## 磁盘空间考量

### 典型空间占用

```
2200 个视频示例：
- 音频文件（平均 50 MB/视频）：~110 GB
- 转录文件（SRT/TXT/MD/JSON）：~2 GB
- 总计：~112 GB
```

**音频在哪个分区**由 [artifact-root.md](./artifact-root.md) 里的 `--artifact-root` 决定：产物（含 `audio/`）可以放到挂载点，状态（manifest、`archive.db`、锁、sidecar）留在归档根目录。`--max-audio-gb` 统计的正是**配置根目录**的 `audio/` 用量，不会把留在归档根目录的历史音频算进来。

### 空间管理策略

#### 策略1：分级存储

```bash
# 短视频：保留音频（默认）
bili-asr run --scope pending --archive-root /ssd/archive

# 长视频：不保留音频（节省空间）
bili-asr run --scope long_videos --no-keep-audio --archive-root /hdd/archive
```

#### 策略2：选择性保留

```bash
# 只保留重要 UP 主的音频
if [ "$BILI_MID" == "23191782" ]; then
    export BILI_KEEP_AUDIO=1
else
    export BILI_KEEP_AUDIO=0
fi
bili-asr fetch-meta --mid $BILI_MID
```

#### 策略3：事后清理

```bash
# 先全部保留（默认行为），验证质量后手工删除低价值音频
bili-asr pilot --n 100 --max-audio-gb 0 --archive-root archive
find archive/audio -name "*.m4a" -size +100M -delete
```

---

## 与现有功能的兼容性

### ✅ 兼容的功能

- `--max-audio-gb`：磁盘上界仍然 fail-closed，统计配置根目录的 `audio/`；**保留 + 上界要注意**，长期保留时用
  `--max-audio-gb 0`（见快速开始）
- `--offline`：离线模式下从已有音频重新处理
- `coverage --quality`：质量检查识别已回收的音频
- `verify`：完整性验证在配置根目录与归档根目录上都做探测，同一份归档有根目录和没根目录得到相同结论
- `--artifact-root`：音频随产物一起搬到挂载点，回收也在两个根目录上生效

### ⚠️ 行为变化

| 场景 | 之前（未设置变量） | 现在（未设置变量） |
|-----|-------------------|-------------------|
| `status=archived` 后 | 音频文件被删除 | **音频文件保留** |
| `audio/` 目录大小 | 仅包含未完成的视频 | 包含所有已下载的音频 |
| 重新运行 ASR | 需要重新下载音频 | 直接使用本地音频 |

要回到删除行为：`--no-keep-audio` 或 `BILI_KEEP_AUDIO=0`。

---

## 迁移指南

### 从旧默认（删除）切到新的默认（保留）

```bash
# 1. 什么都不用设置：新默认就是保留
# 2. 已经归档的视频，其音频在旧默认下已经被删除，只能重新下载
# 3. 查看没有音频的已归档视频
bili-asr coverage --archive-root archive --format json | \
    jq '.rows[] | select(.status == "archived" and .reclaimed_audio == true)'
```

### 从保留切到删除

```bash
# 1. 让每次运行都显式回收
export BILI_KEEP_AUDIO=0
#    或：在命令上写 --no-keep-audio

# 2. 手工清理已有音频文件（工具不会替你删历史文件）
find archive/audio -name "*.m4a" -type f -delete
find archive/audio -name "*.flac" -type f -delete

# 3. 之后的归档会自动删除音频
bili-asr pilot --n 20
```

---

## 常见问题

### Q: 为什么默认改成保留了？

**A**: 删除是不可逆的，而保留只是占磁盘。转录文本无法在事后补回音频；音频能。需要省空间的操作者可以一行开关回到旧行为。

### Q: 保留音频后可以手动删除吗？

**A**: 可以。删除音频不影响已有的转录文件。

```bash
# 删除特定视频的音频
rm archive/audio/BV1xx.p0.m4a

# 删除所有音频
rm -rf archive/audio/*.m4a
```

### Q: 如何检查哪些视频还留着音频？

**A**: 使用 `coverage` 命令：

```bash
bili-asr coverage --archive-root archive --format json | \
    jq '.rows[] | select(.reclaimed_audio == false) | {work_id, status}'
```

### Q: 保留之后为什么下载开始被跳过了？

**A**: 因为音频上界 `--max-audio-gb`（默认 10 GiB）统计的 `audio/` 目录不再变小。把
`audio-dir budget cap reached (--max-audio-gb 0 = unlimited)` 打出来的是 `run` 和 `pilot` 的跳过行；
`schedule` 只打 `(audio_budget)`，`campaign` 只在 `reason_codes` 里报告。保留音频就传 `--max-audio-gb 0`，
或者把上界调大 —— 注意 `schedule --allow-long-live` 拒绝 `0`，那个模式下只能调大。

### Q: 音频保留影响性能吗？

**A**: 不影响。保留只是跳过删除步骤，不改变 ASR 处理速度。

### Q: 我想只保留部分视频的音频怎么办？

**A**: 目前保留策略是每次运行（或每个环境变量）一个值。可以：
1. 分批运行，切换 `--keep-audio/--no-keep-audio`
2. 事后手动删除低价值音频

---

## 技术细节

### 实现原理

保留策略在**命令入口解析一次**（`--keep-audio/--no-keep-audio`，否则 `BILI_KEEP_AUDIO`，否则默认保留），然后作为
`keep` 值传给 `audio_reclaim.reclaim_audio(root, entry, *, artifact_roots=None, keep)`。库层**不**读环境变量：

```python
def reclaim_audio(archive_root, entry, *, artifact_roots=None, keep: bool) -> bool:
    """archived 之后回收音频；keep=True 表示保留（默认策略），直接返回。"""
    if keep:
        return False
    roots = artifact_roots if artifact_roots is not None else ArtifactRoots.of(archive_root)
    for base in roots.read_bases():      # 两个根目录下都找这份音频
        for relative in _candidate_paths(entry):
            unlink_confined_audio(base, relative)
```

删除通过**已打开的 `audio/` 目录描述符**进行（`O_NOFOLLOW`，先改名到随机隔离名再校验再 unlink），所以不会跟随被换掉的符号链接去删到外面。

### 文件结构

```
archive/                       # 归档根目录 = 状态（D13）；配了 --artifact-root 时产物在那边
├── manifest/
│   └── manifest.jsonl         # 元数据（记录 root 相对的 audio_path）
└── ...

<mount>/                       # 产物根目录（--artifact-root）
├── audio/
│   ├── BV1xx.p0.m4a           # 默认保留；--no-keep-audio 才删
│   └── BV1yy.p0.m4a
└── transcripts/               # 转录文件（始终保留）
    ├── srt/
    ├── txt/
    ├── md/
    └── raw/
```

---

## 未来增强

考虑中的功能：

- [ ] 基于视频属性的自动保留规则（时长、UP主、标签）
- [ ] 压缩存储（FLAC → Opus，节省 50% 空间）
- [ ] 分级存储（热数据 SSD，冷数据 HDD/云存储）
- [ ] 音频去重（内容寻址，相同音频只存一份）

---

## 相关文档

- [artifact-root.md](./artifact-root.md) —— 产物根目录（`--artifact-root`）与两个根目录的分工
- [../README.md](../README.md#audio-retain-reclaim-and-the-disk-cap) —— 保留、回收与磁盘上界
- [metadata-storage.md](./metadata-storage.md) —— SQLite 元数据存储
