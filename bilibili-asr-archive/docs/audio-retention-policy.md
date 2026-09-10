# 音频保留策略使用指南

## 背景

默认情况下，`bilibili-asr-archive` 在视频转录完成并达到 `archived` 状态后会**自动删除音频文件**以节省磁盘空间。这在磁盘受限的环境中很有用，但有以下限制：

- ❌ 无法使用更好的 ASR 模型重新处理
- ❌ Bilibili 删除视频后无法恢复音频
- ❌ 无法验证转录质量（对比原始音频）

## 新功能：可配置的音频保留

通过设置环境变量 `BILI_KEEP_AUDIO=1`，你可以**永久保留音频文件**，支持未来的重新处理。

---

## 快速开始

### 方法1：环境变量（推荐）

```bash
# 在 .env 文件中设置
echo "BILI_KEEP_AUDIO=1" >> .env

# 或在命令行中设置
export BILI_KEEP_AUDIO=1

# 运行归档命令
bili-asr pilot --n 20 --archive-root archive
```

### 方法2：每次运行时指定

```bash
BILI_KEEP_AUDIO=1 bili-asr pilot --n 20 --archive-root archive
BILI_KEEP_AUDIO=1 bili-asr run --scope pending --archive-root archive
```

---

## 配置项

| 环境变量 | 值 | 行为 |
|---------|---|------|
| `BILI_KEEP_AUDIO` | `1` | **保留音频**：archived 后不删除音频文件 |
| `BILI_KEEP_AUDIO` | `0` 或未设置 | **删除音频**（默认）：archived 后自动删除 |

---

## 使用场景

### 场景1：长期归档 + 未来重新处理

```bash
# .env 文件
BILI_KEEP_AUDIO=1

# 首次归档（使用 Fun-ASR-Nano-2512）
bili-asr pilot --n 100 --archive-root archive

# 2025年：有了更好的模型
# 音频文件仍在 archive/audio/，可以直接重新跑 ASR
bili-asr run --scope archived --offline --archive-root archive
```

### 场景2：防止 Bilibili 删除视频

```bash
# 保留音频作为备份
BILI_KEEP_AUDIO=1 bili-asr pilot --n 20

# 即使 Bilibili 删除了视频，你仍有：
# - archive/audio/BV1xx.p0.m4a （原始音频）
# - archive/transcripts/... （转录文件）
```

### 场景3：质量验证

```bash
# 保留音频用于人工验证
BILI_KEEP_AUDIO=1 bili-asr run --scope pending

# 对比转录文本和原始音频
mplayer archive/audio/BV1xx.p0.m4a
cat archive/transcripts/txt/BV1xx.p0.txt
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

### 空间管理策略

#### 策略1：分级存储

```bash
# 短视频：保留音频
BILI_KEEP_AUDIO=1 bili-asr run --scope pending --archive-root /ssd/archive

# 长视频：不保留音频（节省空间）
BILI_KEEP_AUDIO=0 bili-asr run --scope long_videos --archive-root /hdd/archive
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
# 先保留所有音频
BILI_KEEP_AUDIO=1 bili-asr pilot --n 100

# 验证转录质量后，手工删除低价值音频
find archive/audio -name "*.m4a" -size +100M -delete
```

---

## 与现有功能的兼容性

### ✅ 兼容的功能

- `--max-audio-gb`：磁盘预算控制仍然有效
- `--offline`：离线模式下从已有音频重新处理
- `coverage --quality`：质量检查识别已回收的音频
- `verify`：完整性验证适配音频保留策略

### ⚠️ 行为变化

| 场景 | `BILI_KEEP_AUDIO=0`（默认） | `BILI_KEEP_AUDIO=1` |
|-----|---------------------------|-------------------|
| `status=archived` 后 | 音频文件被删除 | 音频文件保留 |
| `audio/` 目录大小 | 仅包含未完成的视频 | 包含所有已下载的音频 |
| 重新运行 ASR | 需要重新下载音频 | 直接使用本地音频 |

---

## 迁移指南

### 从默认行为迁移到保留策略

如果你之前使用默认设置（删除音频），现在想保留：

```bash
# 1. 设置环境变量
echo "BILI_KEEP_AUDIO=1" >> .env

# 2. 对于已归档的视频，音频已被删除
# 只能对新视频生效，旧视频需要重新下载

# 3. 查看已删除音频的视频
bili-asr coverage --archive-root archive --format json | \
    jq '.videos[] | select(.status == "archived" and .has_audio == false)'
```

### 从保留策略迁移到默认行为

如果你想切换回自动删除：

```bash
# 1. 移除或注释环境变量
# BILI_KEEP_AUDIO=1  # 注释掉

# 2. 手动清理现有音频文件
find archive/audio -name "*.m4a" -type f -delete
find archive/audio -name "*.flac" -type f -delete

# 3. 未来的归档会自动删除音频
bili-asr pilot --n 20
```

---

## 常见问题

### Q: 为什么默认会删除音频？

**A**: 节省磁盘空间。对于大型归档（数千个视频），音频文件可能占用数百 GB。

### Q: 保留音频后可以手动删除吗？

**A**: 可以。音频文件在 `archive/audio/` 目录下，删除后不影响已有的转录文件。

```bash
# 删除特定视频的音频
rm archive/audio/BV1xx411c7mD.p0.m4a

# 删除所有音频
rm -rf archive/audio/*.m4a
```

### Q: 如何检查哪些视频保留了音频？

**A**: 使用 `coverage` 命令：

```bash
bili-asr coverage --archive-root archive --format json | \
    jq '.videos[] | select(.has_audio == true) | {work_id, audio_size_mb}'
```

### Q: 音频保留影响性能吗？

**A**: 不影响。音频保留只是跳过删除步骤，不会影响 ASR 处理速度。

### Q: 我想只保留部分视频的音频怎么办？

**A**: 目前环境变量是全局设置。如果需要细粒度控制，可以：
1. 分批运行，切换环境变量
2. 事后手动删除低价值音频
3. 提交功能请求支持基于规则的保留策略

---

## 技术细节

### 实现原理

`audio_reclaim.py` 在 `status=archived` 后调用，检查 `BILI_KEEP_AUDIO` 环境变量：

```python
def reclaim_audio(archive_root, entry):
    """删除已归档视频的音频文件（如果配置允许）"""
    if os.environ.get("BILI_KEEP_AUDIO") == "1":
        return False  # 跳过删除
    
    # 默认行为：删除音频文件
    unlink_confined_audio(archive_root, entry['audio_path'])
    return True
```

### 文件结构

```
archive/
├── audio/                          # 音频文件
│   ├── BV1xx.p0.m4a               # BILI_KEEP_AUDIO=1 时保留
│   └── BV1yy.p0.m4a
├── transcripts/                    # 转录文件（始终保留）
│   ├── srt/
│   ├── txt/
│   ├── md/
│   └── raw/
└── manifest/
    └── manifest.jsonl              # 元数据（记录 audio_path）
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

- [content-addressed-storage.md](./content-addressed-storage.md) - 长期归档架构提案
- [storage-architecture.md](./storage-architecture.md) - 双层存储设计
- [README.md](../README.md#audio-reclaim-and-bounded-disk-campaigns) - 原始音频回收文档
