# 长期归档架构：内容寻址 + 版本化

## 核心原则

**不可变性优先**：音频和转录一旦生成，永不删除，只添加新版本。

---

## 目录结构

```
archive/
│
├── index.db                    # 🔵 轻量级索引（可重建）
│
├── blobs/                      # 🟢 内容寻址存储（不可变）
│   ├── audio/
│   │   └── sha256/
│   │       └── a1/
│   │           └── a1b2c3...def.m4a
│   └── transcripts/
│       └── sha256/
│           └── e4/
│               └── e4f5g6...hij.json
│
├── refs/                       # 🔗 引用层（指向 blobs）
│   └── videos/
│       └── BV1xx411c7mD/
│           ├── p0/
│           │   ├── audio@a1b2c3...def
│           │   ├── transcript@e4f5g6...hij
│           │   └── metadata.json
│           └── p1/
│               ├── audio@...
│               └── transcript@...
│
└── exports/                    # 📦 派生产物（可删除重建）
    └── transcripts/
        ├── srt/
        │   └── BV1xx411c7mD.p0.srt
        ├── txt/
        │   └── BV1xx411c7mD.p0.txt
        └── md/
            └── BV1xx411c7mD.p0.md
```

---

## 设计细节

### 1. 内容寻址存储 (blobs/)

**原理**：文件以其 SHA-256 哈希值命名，自然去重

```python
def store_blob(content: bytes, type: str) -> str:
    """存储不可变内容块，返回哈希值"""
    hash_val = hashlib.sha256(content).hexdigest()
    
    # 两级目录避免单目录文件过多
    dir_path = f"blobs/{type}/sha256/{hash_val[:2]}"
    file_path = f"{dir_path}/{hash_val}.{ext}"
    
    if not os.path.exists(file_path):
        os.makedirs(dir_path, exist_ok=True)
        # 原子写入
        temp = f"{file_path}.tmp"
        with open(temp, 'wb') as f:
            f.write(content)
        os.rename(temp, file_path)
    
    return hash_val

# 示例
audio_hash = store_blob(audio_data, 'audio')
# → blobs/audio/sha256/a1/a1b2c3...def.m4a
```

**优点**：
- ✅ 自动去重（同一音频只存一份）
- ✅ 内容不可变（哈希值变了就是新文件）
- ✅ 完整性校验内置

---

### 2. 引用层 (refs/)

**原理**：符号链接或元数据文件指向 blobs

```json
// refs/videos/BV1xx411c7mD/p0/metadata.json
{
  "work_id": "BV1xx411c7mD:p0",
  "bvid": "BV1xx411c7mD",
  "page_index": 0,
  "title": "视频标题",
  "duration_s": 1234,
  "pubdate": 1693843200,
  
  "artifacts": {
    "audio": {
      "hash": "a1b2c3...def",
      "path": "../../../../../../blobs/audio/sha256/a1/a1b2c3...def.m4a",
      "size": 12345678,
      "format": "m4a",
      "downloaded_at": 1693843200
    },
    "transcripts": [
      {
        "version": "v1",
        "hash": "e4f5g6...hij",
        "path": "../../../../../../blobs/transcripts/sha256/e4/e4f5g6...hij.json",
        "model": "FunAudioLLM/Fun-ASR-Nano-2512",
        "source": "asr",
        "generated_at": 1693843300
      }
    ]
  }
}
```

**优点**：
- ✅ 人类可读的目录结构
- ✅ 支持版本历史（多个 transcript 版本共存）
- ✅ 元数据和内容分离

---

### 3. 索引数据库 (index.db)

**仅存快速查询需要的字段**：

```sql
CREATE TABLE videos (
    work_id TEXT PRIMARY KEY,
    bvid TEXT NOT NULL,
    page_index INTEGER NOT NULL,
    title TEXT,
    duration_s INTEGER,
    status TEXT NOT NULL,  -- 'pending', 'indexed', 'archived'
    
    -- 指向 refs/ 的路径
    ref_path TEXT,  -- refs/videos/BV1xx411c7mD/p0/
    
    -- 冗余字段加速查询
    has_audio BOOLEAN DEFAULT 0,
    has_transcript BOOLEAN DEFAULT 0,
    audio_size_bytes INTEGER,
    
    indexed_at INTEGER NOT NULL
);

-- FTS5 全文搜索
CREATE VIRTUAL TABLE search_fts USING fts5(
    work_id UNINDEXED,
    title,
    transcript_text,
    tokenize='unicode61'
);
```

**关键**：数据库损坏后可以从 `refs/` 重建：

```python
def rebuild_index():
    """扫描 refs/ 重建索引"""
    for metadata_file in Path("refs/videos").rglob("metadata.json"):
        meta = json.loads(metadata_file.read_text())
        
        db.execute("""
            INSERT OR REPLACE INTO videos 
            (work_id, bvid, title, has_audio, has_transcript, ref_path)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            meta['work_id'],
            meta['bvid'],
            meta['title'],
            'audio' in meta['artifacts'],
            len(meta['artifacts'].get('transcripts', [])) > 0,
            str(metadata_file.parent)
        ))
```

---

### 4. 导出层 (exports/)

**按需生成，可随时删除重建**：

```python
def export_transcript(work_id: str, format: str):
    """从 blobs 生成导出文件"""
    meta = load_metadata(work_id)
    latest_transcript = meta['artifacts']['transcripts'][-1]
    
    # 从 blob 读取原始 segments
    blob_path = Path(latest_transcript['path'])
    segments = json.loads(blob_path.read_text())
    
    # 生成目标格式
    if format == 'srt':
        output = segments_to_srt(segments)
        export_path = f"exports/transcripts/srt/{work_id}.srt"
    
    Path(export_path).parent.mkdir(parents=True, exist_ok=True)
    Path(export_path).write_text(output)
```

---

## 对比：当前架构 vs 新架构

| 特性 | 当前架构 | 新架构 |
|-----|---------|--------|
| **音频保留** | ❌ archived 后删除 | ✅ 永久保存在 blobs/ |
| **转录版本** | ❌ 只保留最新 | ✅ 多版本共存 |
| **去重** | ❌ 相同音频多份存储 | ✅ 内容寻址自动去重 |
| **完整性** | ✅ Bundle marker | ✅ SHA-256 哈希 |
| **重新处理** | ❌ 需要重新下载音频 | ✅ 直接读 blobs/ |
| **索引重建** | ⚠️ 依赖 JSONL | ✅ 扫描 refs/ |

---

## 工作流示例

### 场景1：首次归档

```python
# 1. 下载音频
audio_data = download_audio(bvid, page_index)
audio_hash = store_blob(audio_data, 'audio')

# 2. 运行 ASR
segments = run_asr(audio_data)
transcript_data = json.dumps(segments).encode()
transcript_hash = store_blob(transcript_data, 'transcripts')

# 3. 创建引用
metadata = {
    "work_id": f"{bvid}:p{page_index}",
    "artifacts": {
        "audio": {"hash": audio_hash, ...},
        "transcripts": [{
            "version": "v1",
            "hash": transcript_hash,
            "model": "Fun-ASR-Nano-2512",
            "generated_at": int(time.time())
        }]
    }
}
save_metadata(f"refs/videos/{bvid}/p{page_index}/metadata.json", metadata)

# 4. 更新索引
db.execute("INSERT INTO videos (...) VALUES (...)")
```

### 场景2：用更好的模型重新处理

```python
# 2025年：有了新模型
for work_id in db.execute("SELECT work_id FROM videos WHERE has_audio = 1"):
    # 1. 从 blobs 读取音频（无需重新下载）
    meta = load_metadata(work_id)
    audio_blob = Path(meta['artifacts']['audio']['path'])
    
    # 2. 运行新模型
    segments_v2 = run_asr_v2(audio_blob.read_bytes())
    transcript_hash_v2 = store_blob(json.dumps(segments_v2).encode(), 'transcripts')
    
    # 3. 添加新版本（不删除旧版本）
    meta['artifacts']['transcripts'].append({
        "version": "v2",
        "hash": transcript_hash_v2,
        "model": "Whisper-V3-Turbo",
        "generated_at": int(time.time())
    })
    save_metadata(ref_path, meta)
```

### 场景3：导出为传统格式

```bash
# 按需生成 SRT（可以删除后重新生成）
bili-asr export --format srt --output exports/transcripts/srt/

# 生成的文件可以随时删除
rm -rf exports/
bili-asr export --format all  # 重新生成
```

---

## 迁移路径

### 阶段1：保留现有音频

```bash
# 1. 停止自动删除音频
# 修改代码：注释掉 audio_reclaim 逻辑

# 2. 将现有音频移动到 blobs/
python scripts/migrate_to_content_addressed.py \
    --audio-dir archive/audio \
    --output archive/blobs/audio
```

### 阶段2：重新组织转录文件

```bash
# 将现有 transcripts/raw/*.json 移动到 blobs/
python scripts/migrate_transcripts.py \
    --source archive/transcripts/raw \
    --output archive/blobs/transcripts
```

### 阶段3：生成引用层

```python
# 从 manifest.jsonl 生成 refs/
def generate_refs():
    for entry in read_manifest():
        work_id = entry['work_id']
        bvid, page_index = parse_work_id(work_id)
        
        # 计算现有文件的哈希
        audio_hash = compute_hash(entry['audio_path'])
        transcript_hash = compute_hash(entry['raw_path'])
        
        # 创建元数据
        metadata = {...}
        ref_dir = f"refs/videos/{bvid}/p{page_index}"
        os.makedirs(ref_dir, exist_ok=True)
        save_json(f"{ref_dir}/metadata.json", metadata)
```

---

## 磁盘空间考量

### 当前架构（删除音频）

```
2200 个视频 × 平均 50 MB = 110 GB
转录文件：~2 GB
总计：~112 GB
```

### 新架构（保留音频）

```
音频 blobs：110 GB（内容寻址去重后可能更少）
转录 blobs：2 GB
索引数据库：~10 MB
导出文件（可选）：~2 GB
总计：~112-114 GB
```

**结论**：磁盘成本几乎相同，但获得了：
- ✅ 未来重新处理能力
- ✅ 防止 Bilibili 删除视频
- ✅ 多版本转录历史

---

## 推荐方案

基于你的需求（**长期保存 + 未来重处理**），我建议：

### 短期（1 周）
1. **立即停止删除音频**
2. 将现有架构的 `audio/` 改为永久保存
3. 修改 `archived` 状态逻辑：不再调用 `audio_reclaim`

### 中期（1 月）
1. 实现内容寻址存储 `blobs/`
2. 将现有文件迁移到新结构
3. 保留 manifest.jsonl 作为过渡

### 长期（3 月）
1. 完全切换到 `refs/ + index.db` 架构
2. 删除旧的 JSONL 文件
3. 实现版本化转录支持

---

要我帮你实现"立即停止删除音频"的快速修复吗？
