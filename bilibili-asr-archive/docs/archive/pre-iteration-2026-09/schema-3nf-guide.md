# 3NF 数据库 Schema 文档

## 🎯 设计目标

1. **严格 3NF**：无部分依赖、无传递依赖
2. **内容寻址**：音频和转录以 SHA-256 存储，自动去重
3. **版本管理**：支持同一视频的多个转录版本
4. **引用计数**：自动管理 Blob 生命周期
5. **查询优化**：合理的索引和视图

---

## 📊 ER 图

```
┌─────────────────┐
│   up_masters    │
│─────────────────│
│ PK: mid         │ 1
│     name        │───────┐
│     ...         │       │
└─────────────────┘       │
                          │ N
                    ┌─────▼──────┐
                    │   videos   │
                    │────────────│
                    │ PK: bvid   │ 1
                    │ FK: mid    │───────┐
                    │     title  │       │
                    │     ...    │       │
                    └────────────┘       │
                                         │ N
                                   ┌─────▼────────────┐
                                   │   video_parts    │
                                   │──────────────────│
                                   │ PK: work_id      │
                                   │ FK: bvid         │
                                   │     page_index   │
                                   │     status       │
                                   │     ...          │
                                   └────┬─────────┬───┘
                                        │ 1       │ 1
                                        │         │
                         ┌──────────────┘         └──────────────┐
                         │ 1                                     │ N
              ┌──────────▼──────────┐                 ┌─────────▼────────────┐
              │   part_audio_map    │                 │ part_transcript_map  │
              │─────────────────────│                 │──────────────────────│
              │ PK: work_id         │                 │ PK: id               │
              │ FK: work_id         │                 │ FK: work_id          │
              │ FK: audio_hash      │                 │ FK: transcript_hash  │
              │     downloaded_at   │                 │     version          │
              │     ...             │                 │     model_name       │
              └──────────┬──────────┘                 │     is_latest        │
                         │ N                          │     ...              │
                         │                            └─────────┬────────────┘
                         │                                      │ N
                         │ 1                                    │ 1
              ┌──────────▼──────────┐                 ┌────────▼─────────────┐
              │   audio_blobs       │                 │  transcript_blobs    │
              │─────────────────────│                 │──────────────────────│
              │ PK: hash (SHA-256)  │                 │ PK: hash (SHA-256)   │
              │     size_bytes      │                 │     size_bytes       │
              │     format          │                 │     segment_count    │
              │     storage_path    │                 │     storage_path     │
              │     ref_count       │                 │     ref_count        │
              │     ...             │                 │     ...              │
              └─────────────────────┘                 └──────────────────────┘
```

---

## 📋 表结构详解

### 核心实体表

#### 1. `up_masters` (UP 主)
| 字段 | 类型 | 约束 | 说明 |
|-----|------|------|------|
| `mid` | INTEGER | PK | Bilibili UP 主 ID |
| `name` | TEXT | NOT NULL | UP 主昵称 |
| `total_videos` | INTEGER | DEFAULT 0 | 视频总数（冗余字段） |
| `archived_videos` | INTEGER | DEFAULT 0 | 已归档数量 |
| `created_at` | INTEGER | NOT NULL | 创建时间 |
| `updated_at` | INTEGER | NOT NULL | 更新时间 |

**函数依赖**: `mid → {name, total_videos, ...}`  
✓ 3NF: 所有字段直接依赖主键

---

#### 2. `videos` (视频)
| 字段 | 类型 | 约束 | 说明 |
|-----|------|------|------|
| `bvid` | TEXT | PK | Bilibili 视频 ID |
| `mid` | INTEGER | FK → up_masters | UP 主 ID |
| `title` | TEXT | NOT NULL | 视频标题 |
| `description` | TEXT | | 视频简介 |
| `pubdate` | INTEGER | NOT NULL | 发布时间 |
| `duration_s` | INTEGER | NOT NULL | 总时长（秒） |
| `is_multipart` | BOOLEAN | DEFAULT 0 | 是否多分P |
| `part_count` | INTEGER | DEFAULT 1 | 分P数量 |
| `created_at` | INTEGER | NOT NULL | 创建时间 |
| `updated_at` | INTEGER | NOT NULL | 更新时间 |

**函数依赖**: `bvid → {mid, title, pubdate, ...}`  
✓ 3NF: `mid` 是外键，通过引用获取 UP 主信息，无传递依赖

---

#### 3. `video_parts` (视频分P)
| 字段 | 类型 | 约束 | 说明 |
|-----|------|------|------|
| `work_id` | TEXT | PK | BV1xx:p0 |
| `bvid` | TEXT | FK → videos | 视频 ID |
| `page_index` | INTEGER | NOT NULL | 分P索引（从 0 开始） |
| `cid` | INTEGER | NOT NULL | Bilibili 分P ID |
| `part_title` | TEXT | | 分P标题 |
| `duration_s` | INTEGER | NOT NULL | 时长 |
| `status` | TEXT | NOT NULL | 处理状态 |
| `source` | TEXT | | 转录来源 (subtitle/asr) |
| `created_at` | INTEGER | NOT NULL | 创建时间 |
| `updated_at` | INTEGER | NOT NULL | 更新时间 |

**约束**:
- `UNIQUE(bvid, page_index)`
- `CHECK(status IN ('pending', 'meta_ok', 'needs_audio', 'audio_ok', 'asr_done', 'archived', 'gone'))`

**函数依赖**: 
- `work_id → {bvid, page_index, cid, status, ...}`
- `(bvid, page_index) → work_id`

✓ 3NF: 无非主键字段依赖其他非主键字段

---

### Blob 表（内容寻址）

#### 4. `audio_blobs` (音频 Blob)
| 字段 | 类型 | 约束 | 说明 |
|-----|------|------|------|
| `hash` | TEXT | PK | SHA-256 哈希值 |
| `size_bytes` | INTEGER | NOT NULL | 文件大小 |
| `format` | TEXT | NOT NULL | 音频格式 (m4a/flac) |
| `duration_s` | INTEGER | | 音频时长 |
| `storage_path` | TEXT | NOT NULL | 存储路径 |
| `ref_count` | INTEGER | DEFAULT 0 | 引用计数 |
| `created_at` | INTEGER | NOT NULL | 创建时间 |

**函数依赖**: `hash → {size_bytes, format, storage_path, ...}`  
✓ 3NF: 内容寻址，所有属性由内容（hash）决定

---

#### 5. `transcript_blobs` (转录 Blob)
| 字段 | 类型 | 约束 | 说明 |
|-----|------|------|------|
| `hash` | TEXT | PK | SHA-256 哈希值 |
| `size_bytes` | INTEGER | NOT NULL | 文件大小 |
| `segment_count` | INTEGER | NOT NULL | 片段数量 |
| `storage_path` | TEXT | NOT NULL | 存储路径 |
| `ref_count` | INTEGER | DEFAULT 0 | 引用计数 |
| `created_at` | INTEGER | NOT NULL | 创建时间 |

**函数依赖**: `hash → {size_bytes, segment_count, ...}`  
✓ 3NF: 内容寻址

---

### 关联表（多对多）

#### 6. `part_audio_map` (分P ↔ 音频)
| 字段 | 类型 | 约束 | 说明 |
|-----|------|------|------|
| `work_id` | TEXT | PK, FK → video_parts | 分P ID |
| `audio_hash` | TEXT | FK → audio_blobs | 音频哈希 |
| `downloaded_at` | INTEGER | NOT NULL | 下载时间 |
| `download_source` | TEXT | | 下载来源 |

**关系**: 1:1（一个分P对应一个音频）  
✓ 3NF: 纯关联表，只存储关系

---

#### 7. `part_transcript_map` (分P ↔ 转录)
| 字段 | 类型 | 约束 | 说明 |
|-----|------|------|------|
| `id` | INTEGER | PK AUTOINCREMENT | 自增 ID |
| `work_id` | TEXT | FK → video_parts | 分P ID |
| `transcript_hash` | TEXT | FK → transcript_blobs | 转录哈希 |
| `version` | INTEGER | NOT NULL | 版本号 |
| `is_latest` | BOOLEAN | DEFAULT 1 | 是否最新版本 |
| `model_name` | TEXT | NOT NULL | ASR 模型名 |
| `device` | TEXT | | 设备 (cuda/cpu) |
| `avg_confidence` | REAL | | 平均置信度 |
| `generated_at` | INTEGER | NOT NULL | 生成时间 |

**约束**: `UNIQUE(work_id, version)`  
**关系**: 1:N（一个分P可以有多个转录版本）

**函数依赖**: 
- `id → {work_id, transcript_hash, version, model_name, ...}`
- `(work_id, version) → id`

✓ 3NF: `model_name` 等字段描述的是"这次转录"，不是 work_id 的属性

---

### 执行历史表

#### 8. `runs` (命令执行)
| 字段 | 类型 | 约束 | 说明 |
|-----|------|------|------|
| `run_id` | TEXT | PK | 运行 ID |
| `command` | TEXT | NOT NULL | 命令名称 |
| `started_at` | INTEGER | NOT NULL | 开始时间 |
| `finished_at` | INTEGER | NOT NULL | 结束时间 |
| `exit_code` | INTEGER | NOT NULL | 退出码 |
| `records_processed` | INTEGER | DEFAULT 0 | 处理数量 |
| `records_succeeded` | INTEGER | DEFAULT 0 | 成功数量 |
| `records_failed` | INTEGER | DEFAULT 0 | 失败数量 |

✓ 3NF: 所有字段描述这次运行

---

#### 9. `stage_attempts` (阶段尝试)
| 字段 | 类型 | 约束 | 说明 |
|-----|------|------|------|
| `id` | INTEGER | PK AUTOINCREMENT | 自增 ID |
| `work_id` | TEXT | FK → video_parts | 分P ID |
| `run_id` | TEXT | FK → runs | 运行 ID |
| `stage` | TEXT | NOT NULL | 阶段 |
| `attempt_num` | INTEGER | NOT NULL | 尝试次数 |
| `outcome` | TEXT | NOT NULL | 结果 |
| `error_code` | TEXT | | 错误码 |
| `started_at` | INTEGER | NOT NULL | 开始时间 |
| `finished_at` | INTEGER | NOT NULL | 结束时间 |

**约束**: 
- `UNIQUE(work_id, stage, attempt_num)`
- `CHECK(stage IN ('harvest', 'download', 'asr', 'archive'))`
- `CHECK(outcome IN ('ok', 'failed', 'skipped'))`

✓ 3NF: 所有字段描述这次尝试

---

## 🔍 视图（便捷查询）

### 1. `v_video_parts_full` (完整视图)

```sql
SELECT 
    p.work_id,
    p.bvid,
    p.page_index,
    p.part_title,
    p.status,
    
    v.title AS video_title,
    v.mid,
    u.name AS up_name,
    
    a.audio_hash,
    ab.audio_path,
    
    t.transcript_hash,
    t.version AS transcript_version,
    t.model_name,
    tb.transcript_path
FROM video_parts p
JOIN videos v ON p.bvid = v.bvid
JOIN up_masters u ON v.mid = u.mid
LEFT JOIN part_audio_map a ON p.work_id = a.work_id
LEFT JOIN audio_blobs ab ON a.audio_hash = ab.hash
LEFT JOIN part_transcript_map t ON p.work_id = t.work_id AND t.is_latest = 1
LEFT JOIN transcript_blobs tb ON t.transcript_hash = tb.hash;
```

---

### 2. `v_pending_parts` (待处理)

```sql
SELECT work_id, bvid, part_title, duration_s, status
FROM video_parts
WHERE status IN ('meta_ok', 'needs_audio', 'audio_ok', 'asr_done')
ORDER BY duration_s ASC;
```

---

### 3. `v_archive_stats` (统计)

```sql
SELECT 
    status,
    COUNT(*) AS count,
    SUM(duration_s) AS total_duration_s,
    ROUND(AVG(duration_s), 2) AS avg_duration_s
FROM video_parts
GROUP BY status;
```

---

### 4. `v_up_master_stats` (UP主统计)

```sql
SELECT 
    u.mid,
    u.name,
    COUNT(DISTINCT v.bvid) AS video_count,
    COUNT(p.work_id) AS part_count,
    SUM(CASE WHEN p.status = 'archived' THEN 1 ELSE 0 END) AS archived_count
FROM up_masters u
JOIN videos v ON u.mid = v.mid
JOIN video_parts p ON v.bvid = p.bvid
GROUP BY u.mid;
```

---

## ⚙️ 触发器（自动维护）

### 1. 引用计数管理

```sql
-- 音频 Blob 引用计数
CREATE TRIGGER audio_blob_ref_inc
AFTER INSERT ON part_audio_map
BEGIN
    UPDATE audio_blobs 
    SET ref_count = ref_count + 1 
    WHERE hash = NEW.audio_hash;
END;

CREATE TRIGGER audio_blob_ref_dec
AFTER DELETE ON part_audio_map
BEGIN
    UPDATE audio_blobs 
    SET ref_count = ref_count - 1 
    WHERE hash = OLD.audio_hash;
END;
```

**用途**: 垃圾回收
```sql
-- 删除未被引用的 Blob
DELETE FROM audio_blobs WHERE ref_count = 0;
```

---

### 2. 自动标记最新版本

```sql
CREATE TRIGGER transcript_version_latest
AFTER INSERT ON part_transcript_map
BEGIN
    -- 将同一个 work_id 的其他版本标记为非最新
    UPDATE part_transcript_map 
    SET is_latest = 0 
    WHERE work_id = NEW.work_id AND id != NEW.id;
END;
```

---

### 3. 自动更新时间戳

```sql
CREATE TRIGGER video_parts_updated
AFTER UPDATE ON video_parts
BEGIN
    UPDATE video_parts 
    SET updated_at = unixepoch() 
    WHERE work_id = NEW.work_id;
END;
```

---

## 🔐 3NF 验证

### 范式定义

**1NF**（第一范式）:
- ✓ 每个字段都是原子值
- ✓ 无重复组

**2NF**（第二范式）:
- ✓ 满足 1NF
- ✓ 非主键字段**完全依赖**于主键（无部分依赖）

**3NF**（第三范式）:
- ✓ 满足 2NF
- ✓ 非主键字段**不传递依赖**于主键

---

### 逐表验证

#### `up_masters`
- **主键**: `mid`
- **函数依赖**: `mid → {name, total_videos, ...}`
- ✓ 2NF: 单主键，无部分依赖
- ✓ 3NF: 所有字段直接依赖 `mid`

---

#### `videos`
- **主键**: `bvid`
- **外键**: `mid → up_masters`
- **函数依赖**: `bvid → {mid, title, pubdate, ...}`
- ✓ 2NF: 单主键
- ✓ 3NF: `mid` 是外键引用，UP 主名字在 `up_masters` 表，无传递依赖

**反例**（如果违反 3NF）:
```sql
-- ❌ 违反 3NF 的设计
CREATE TABLE videos (
    bvid TEXT PRIMARY KEY,
    mid INTEGER,
    up_name TEXT,  -- 传递依赖：bvid → mid → up_name
    title TEXT
);
```
**问题**: `up_name` 依赖于 `mid`，而 `mid` 依赖于 `bvid`，形成传递依赖 `bvid → mid → up_name`

---

#### `video_parts`
- **主键**: `work_id`
- **候选键**: `(bvid, page_index)`
- **函数依赖**: 
  - `work_id → {bvid, page_index, cid, status, ...}`
  - `(bvid, page_index) → work_id`
- ✓ 2NF: 所有非主键字段完全依赖于 `work_id`
- ✓ 3NF: 无非主键字段依赖其他非主键字段

---

#### `audio_blobs` / `transcript_blobs`
- **主键**: `hash` (SHA-256)
- **函数依赖**: `hash → {size_bytes, format, storage_path, ...}`
- ✓ 2NF: 单主键
- ✓ 3NF: 内容寻址，所有属性由内容（hash）唯一决定

**特性**: 内容寻址天然满足 3NF

---

#### `part_audio_map` / `part_transcript_map`
- **主键**: `work_id` / `id`
- **外键**: `audio_hash`, `transcript_hash`
- ✓ 2NF: 纯关联表
- ✓ 3NF: 只存储关系和关系属性（如 `downloaded_at`, `model_name`）

---

### 结论

✅ **所有表都严格满足 3NF**

---

## 📊 索引策略

### 主查询模式

1. **按状态查询待处理视频**
   ```sql
   SELECT * FROM video_parts WHERE status = 'pending';
   ```
   → `idx_parts_status`

2. **查询 UP 主的所有视频**
   ```sql
   SELECT * FROM videos WHERE mid = 23191782;
   ```
   → `idx_videos_mid`

3. **按发布时间排序**
   ```sql
   SELECT * FROM videos ORDER BY pubdate DESC;
   ```
   → `idx_videos_pubdate`

4. **查询特定视频的所有分P**
   ```sql
   SELECT * FROM video_parts WHERE bvid = 'BV1xx';
   ```
   → `idx_parts_bvid`

5. **全文搜索**
   ```sql
   SELECT * FROM search_fts WHERE search_fts MATCH '黑格尔';
   ```
   → FTS5 内置索引

6. **查询最新转录**
   ```sql
   SELECT * FROM part_transcript_map WHERE work_id = 'BV1xx:p0' AND is_latest = 1;
   ```
   → `idx_part_transcript_latest` (过滤索引)

---

## 🚀 使用示例

### 1. 插入新视频

```sql
-- 1. 插入 UP 主（如果不存在）
INSERT OR IGNORE INTO up_masters (mid, name) 
VALUES (23191782, '未明子');

-- 2. 插入视频
INSERT INTO videos (bvid, mid, title, pubdate, duration_s, part_count)
VALUES ('BV1xx411c7mD', 23191782, '测试视频', 1693843200, 600, 2);

-- 3. 插入分P
INSERT INTO video_parts (work_id, bvid, page_index, cid, part_title, duration_s)
VALUES 
('BV1xx411c7mD:p0', 'BV1xx411c7mD', 0, 123456, 'P1', 300),
('BV1xx411c7mD:p1', 'BV1xx411c7mD', 1, 123457, 'P2', 300);
```

---

### 2. 存储音频

```python
import hashlib

# 计算哈希
audio_data = open('audio.m4a', 'rb').read()
audio_hash = hashlib.sha256(audio_data).hexdigest()
storage_path = f"blobs/audio/sha256/{audio_hash[:2]}/{audio_hash}.m4a"

# 1. 插入 Blob
conn.execute("""
    INSERT OR IGNORE INTO audio_blobs (hash, size_bytes, format, storage_path)
    VALUES (?, ?, 'm4a', ?)
""", (audio_hash, len(audio_data), storage_path))

# 2. 关联到分P
conn.execute("""
    INSERT INTO part_audio_map (work_id, audio_hash, downloaded_at)
    VALUES ('BV1xx411c7mD:p0', ?, unixepoch())
""", (audio_hash,))

# 触发器自动增加 ref_count
```

---

### 3. 存储转录（支持多版本）

```python
import json

segments = [{"start": 0, "end": 5, "text": "..."}]
transcript_data = json.dumps(segments).encode()
transcript_hash = hashlib.sha256(transcript_data).hexdigest()
storage_path = f"blobs/transcripts/sha256/{transcript_hash[:2]}/{transcript_hash}.json"

# 1. 插入 Blob
conn.execute("""
    INSERT OR IGNORE INTO transcript_blobs 
    (hash, size_bytes, segment_count, storage_path)
    VALUES (?, ?, ?, ?)
""", (transcript_hash, len(transcript_data), len(segments), storage_path))

# 2. 获取下一个版本号
version = conn.execute("""
    SELECT COALESCE(MAX(version), 0) + 1
    FROM part_transcript_map
    WHERE work_id = 'BV1xx411c7mD:p0'
""").fetchone()[0]

# 3. 插入新版本
conn.execute("""
    INSERT INTO part_transcript_map 
    (work_id, transcript_hash, version, model_name, is_latest)
    VALUES ('BV1xx411c7mD:p0', ?, ?, 'Fun-ASR-Nano', 1)
""", (transcript_hash, version))

# 触发器自动：
# - 增加 ref_count
# - 将旧版本的 is_latest 设为 0
```

---

### 4. 查询完整信息

```sql
-- 查询一个视频分P的完整信息
SELECT * FROM v_video_parts_full 
WHERE work_id = 'BV1xx411c7mD:p0';

-- 结果包含：
-- - 视频标题、UP主名字
-- - 音频哈希、存储路径
-- - 最新转录哈希、模型名、版本号
```

---

### 5. 全文搜索

```sql
-- 搜索转录内容
SELECT work_id, video_title, snippet(search_fts, 4, '<b>', '</b>', '...', 32) AS snippet
FROM search_fts
WHERE search_fts MATCH '黑格尔 AND 辩证法'
ORDER BY rank
LIMIT 20;
```

---

### 6. 垃圾回收

```sql
-- 删除未被引用的 Blob
DELETE FROM audio_blobs WHERE ref_count = 0;
DELETE FROM transcript_blobs WHERE ref_count = 0;
```

---

## 📈 性能优化

### 查询优化建议

1. **使用视图简化查询**
   ```sql
   -- ✅ 好
   SELECT * FROM v_video_parts_full WHERE status = 'pending';
   
   -- ❌ 差（手写多表 JOIN）
   SELECT p.*, v.title, u.name, ...
   FROM video_parts p JOIN videos v ...
   ```

2. **利用过滤索引**
   ```sql
   -- 自动使用 idx_part_transcript_latest
   SELECT * FROM part_transcript_map 
   WHERE work_id = ? AND is_latest = 1;
   ```

3. **批量插入使用事务**
   ```python
   with conn:  # 自动 BEGIN/COMMIT
       for record in records:
           conn.execute("INSERT INTO ...", record)
   ```

---

## 🎯 总结

### 优势

✅ **严格 3NF**: 无冗余、无异常  
✅ **内容寻址**: 自动去重、完整性保证  
✅ **版本管理**: 支持重新处理  
✅ **引用计数**: 自动垃圾回收  
✅ **查询性能**: 合理索引、预定义视图  
✅ **事务安全**: ACID 保证

### 与旧架构对比

| 维度 | 旧架构 | 3NF 架构 |
|-----|--------|----------|
| **状态管理** | 8 个 JSONL/JSON 文件 | 1 个 SQLite |
| **音频保留** | archived 后删除 | 永久保留 + 引用计数 |
| **版本管理** | ❌ 无 | ✅ part_transcript_map |
| **内容去重** | ❌ 无 | ✅ SHA-256 哈希 |
| **数据一致性** | 手工同步 | ACID 事务 |
| **查询性能** | O(n) 扫描 | O(1) 索引 |
| **范式** | ❌ 不满足 | ✅ 3NF |

### 下一步

1. 实现 Python ORM 封装（基于这个 schema）
2. 编写迁移脚本（JSONL → SQLite）
3. 集成到现有 CLI

**准备好了吗？要我写 Python ORM 封装吗？**
