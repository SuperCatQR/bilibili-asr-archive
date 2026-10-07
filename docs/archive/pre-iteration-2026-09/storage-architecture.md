# 存储架构提案：双层分离

## 设计原则

**过程与结果分离**：
- **过程数据** = 易变的状态机、进度、日志 → `state.db` (SQLite)
- **结果数据** = 不可变的转录文件 → `artifacts/` (文件系统)

---

## 目录结构

```
archive/
├── state.db                    # 🔵 过程数据库（可删除重建）
│
├── artifacts/                  # 🟢 不可变结果（长期保存）
│   ├── transcripts/
│   │   ├── srt/
│   │   │   └── BV1xx.p0.srt
│   │   ├── txt/
│   │   │   └── BV1xx.p0.txt
│   │   ├── md/
│   │   │   └── BV1xx.p0.md
│   │   └── raw/
│   │       └── BV1xx.p0.json
│   └── subtitles/
│       └── BV1xx.p0.json       # 原始 Bilibili 字幕
│
└── temp/                       # 🟡 临时文件（可随时删除）
    └── audio/
        └── BV1xx.p0.m4a
```

---

## SQLite 数据库：state.db

### 仅存储轻量级元数据和状态

```sql
-- ============================================================
-- 视频元数据表（替代 manifest.jsonl）
-- ============================================================
CREATE TABLE videos (
    work_id TEXT PRIMARY KEY,
    bvid TEXT NOT NULL,
    page_index INTEGER NOT NULL,
    
    -- 元信息（来自 Bilibili API）
    title TEXT,
    duration_s INTEGER,
    pubdate INTEGER,
    
    -- 状态机
    status TEXT NOT NULL CHECK(status IN (
        'pending', 'meta_ok', 'sub_checked', 'subtitle_done',
        'needs_audio', 'audio_ok', 'asr_done', 'archived', 'gone'
    )),
    source TEXT CHECK(source IN ('subtitle', 'asr')),
    
    -- 文件引用（相对路径，不存实际内容）
    srt_path TEXT,              -- artifacts/transcripts/srt/BV1xx.p0.srt
    txt_path TEXT,
    md_path TEXT,
    raw_path TEXT,
    
    -- 时间戳
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    updated_at INTEGER NOT NULL DEFAULT (unixepoch()),
    archived_at INTEGER,
    
    UNIQUE(bvid, page_index)
);

-- ============================================================
-- 执行日志（替代 run-ledger.jsonl）
-- ============================================================
CREATE TABLE runs (
    run_id TEXT PRIMARY KEY,
    command TEXT NOT NULL,
    started_at INTEGER NOT NULL,
    finished_at INTEGER NOT NULL,
    exit_code INTEGER NOT NULL,
    
    -- 执行统计
    records_processed INTEGER DEFAULT 0,
    records_succeeded INTEGER DEFAULT 0,
    records_failed INTEGER DEFAULT 0
);

-- ============================================================
-- 阶段尝试（替代 attempts.jsonl）
-- ============================================================
CREATE TABLE attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_id TEXT NOT NULL REFERENCES videos(work_id),
    stage TEXT NOT NULL CHECK(stage IN ('harvest', 'download', 'asr', 'archive')),
    attempt_num INTEGER NOT NULL,
    
    outcome TEXT NOT NULL CHECK(outcome IN ('ok', 'failed', 'skipped')),
    error_code TEXT,
    
    started_at INTEGER NOT NULL,
    finished_at INTEGER NOT NULL,
    
    UNIQUE(work_id, stage, attempt_num)
);

-- ============================================================
-- 进度游标（替代 meta-cursor.json 等）
-- ============================================================
CREATE TABLE cursors (
    name TEXT PRIMARY KEY,      -- 'meta_fetch', 'scheduler', 'campaign'
    state TEXT NOT NULL,        -- 'initial', 'complete', 'limited', 'risk_interrupted'
    data TEXT,                  -- JSON 扩展数据
    updated_at INTEGER NOT NULL DEFAULT (unixepoch())
);

-- 示例数据
INSERT INTO cursors (name, state, data) VALUES 
('meta_fetch', 'complete', '{"mid": 23191782, "next_page": 1}');
```

### 关键特性

1. **videos 表只存引用**，不存转录内容
   ```python
   # ✅ 正确：轻量级引用
   {"srt_path": "artifacts/transcripts/srt/BV1xx.p0.srt"}
   
   # ❌ 错误：把内容塞进数据库
   {"srt_content": "1\n00:00:00,000 --> 00:00:05,000\n大家好..."}
   ```

2. **可以随时重建**
   ```bash
   # 删除状态库
   rm archive/state.db
   
   # 扫描 artifacts/ 重建索引
   bili-asr rebuild-index --scan artifacts/transcripts
   ```

3. **备份策略不同**
   ```bash
   # 状态数据：定期备份即可
   cp state.db state.db.backup
   
   # 结果数据：必须永久保存
   rsync -av artifacts/ /backup/bilibili-archive/
   ```

---

## 文件系统：artifacts/

### 内容寻址 + 不可变存储

```python
# 写入一次后永不修改
def publish_transcript(work_id: str, segments: list):
    stem = artifact_stem(work_id)
    
    # 1. 写入四个文件到 artifacts/
    srt_path = f"artifacts/transcripts/srt/{stem}.srt"
    txt_path = f"artifacts/transcripts/txt/{stem}.txt"
    md_path = f"artifacts/transcripts/md/{stem}.md"
    raw_path = f"artifacts/transcripts/raw/{stem}.json"
    
    write_file(srt_path, segments_to_srt(segments))
    write_file(txt_path, segments_to_txt(segments))
    write_file(md_path, segments_to_md(segments))
    write_file(raw_path, json.dumps(segments))
    
    # 2. 计算 SHA-256 校验和
    bundle_marker = {
        "schema": "archive-bundle-v1",
        "artifacts": {
            "srt": {"path": srt_path, "sha256": sha256(srt_path)},
            "txt": {"path": txt_path, "sha256": sha256(txt_path)},
            "md": {"path": md_path, "sha256": sha256(md_path)},
            "raw": {"path": raw_path, "sha256": sha256(raw_path)}
        }
    }
    write_file(f"{srt_path}.bundle-ready", json.dumps(bundle_marker))
    
    # 3. 仅更新数据库引用（不存内容）
    db.execute("""
        UPDATE videos 
        SET status = 'archived',
            srt_path = ?,
            txt_path = ?,
            md_path = ?,
            raw_path = ?,
            archived_at = unixepoch()
        WHERE work_id = ?
    """, (srt_path, txt_path, md_path, raw_path, work_id))
```

### 优点

- ✅ 文件可以单独备份/移动/归档
- ✅ 支持 rsync 增量同步
- ✅ 可以挂载到只读文件系统
- ✅ 校验和保证完整性

---

## 临时文件：temp/

```
temp/
└── audio/
    └── BV1xx.p0.m4a        # 用完即删（archived 后自动清理）
```

- **不需要持久化**
- **崩溃后可重新下载**
- **不参与备份**

---

## 对比：当前架构 vs 新架构

| 数据类型 | 当前方案 | 新方案 | 改进点 |
|---------|---------|--------|--------|
| 视频状态 | `manifest.jsonl` | `state.db:videos` | 事务、索引、并发 |
| 执行日志 | `run-ledger.jsonl` | `state.db:runs` | SQL 聚合查询 |
| 阶段尝试 | `attempts.jsonl` | `state.db:attempts` | 外键约束 |
| 进度游标 | 5 个独立 JSON | `state.db:cursors` | 统一管理 |
| 转录文件 | `transcripts/*` | `artifacts/transcripts/*` | **不变** |
| 音频文件 | `audio/` | `temp/audio/` | 语义更清晰 |

---

## 迁移路径

### 阶段1：创建新库 + 导入历史数据

```bash
# 1. 创建数据库
sqlite3 archive/state.db < schema.sql

# 2. 从 JSONL 导入
python scripts/migrate_jsonl_to_sqlite.py \
    --jsonl archive/manifest/manifest.jsonl \
    --db archive/state.db

# 3. 验证数据一致性
python scripts/verify_migration.py
```

### 阶段2：重构代码

```python
# 旧代码
class ManifestStore:
    def load(self):
        return self._read_jsonl()

# 新代码
class StateDB:
    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)
    
    def get_video(self, work_id: str):
        return self.conn.execute(
            "SELECT * FROM videos WHERE work_id = ?", 
            (work_id,)
        ).fetchone()
```

### 阶段3：清理旧文件

```bash
# 备份后删除
mv archive/manifest archive/manifest.backup
mv archive/coordinator archive/coordinator.backup
rm archive/*.json  # meta-cursor, scheduler, campaign
```

---

## 最佳实践

### 1. 数据库只存索引，不存内容

```python
# ✅ 好：轻量级引用
db.execute("UPDATE videos SET srt_path = ?", ("artifacts/.../x.srt",))

# ❌ 坏：把 10MB 文件塞进 BLOB
db.execute("UPDATE videos SET srt_content = ?", (open("x.srt").read(),))
```

### 2. 结果文件不可变

```python
# ✅ 好：发现错误后重新生成新文件
new_srt = f"artifacts/transcripts/srt/{stem}.v2.srt"

# ❌ 坏：修改已归档的文件
os.remove("artifacts/transcripts/srt/{stem}.srt")  # 破坏校验和！
```

### 3. 状态库可重建

```python
def rebuild_index():
    """从 artifacts/ 扫描所有文件，重建 state.db"""
    for srt_file in Path("artifacts/transcripts/srt").glob("*.srt"):
        work_id = parse_stem(srt_file.stem)
        db.execute("""
            INSERT OR REPLACE INTO videos (work_id, status, srt_path)
            VALUES (?, 'archived', ?)
        """, (work_id, str(srt_file)))
```

---

## 总结

| 层级 | 存储 | 特性 | 备份策略 |
|-----|------|------|---------|
| **过程** | `state.db` | 易变、可重建 | 定期快照 |
| **结果** | `artifacts/` | 不可变、关键 | 永久保存 |
| **临时** | `temp/` | 短暂、可丢弃 | 不备份 |

**核心理念**：数据库是索引，文件系统是仓库。
