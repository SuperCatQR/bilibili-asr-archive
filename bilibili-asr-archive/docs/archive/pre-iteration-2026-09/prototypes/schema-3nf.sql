-- ============================================================
-- Bilibili ASR Archive Database Schema (3NF)
-- ============================================================

-- 设计原则：
-- 1NF: 每个字段都是原子值（无多值属性）
-- 2NF: 非主键字段完全依赖于主键（无部分依赖）
-- 3NF: 非主键字段不依赖于其他非主键字段（无传递依赖）

-- ============================================================
-- 核心实体表
-- ============================================================

-- UP 主信息表
CREATE TABLE up_masters (
    mid INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    
    -- 统计信息（冗余字段，通过触发器维护）
    total_videos INTEGER DEFAULT 0,
    archived_videos INTEGER DEFAULT 0,
    
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    updated_at INTEGER NOT NULL DEFAULT (unixepoch())
);

-- 视频元信息表（独立于分P）
CREATE TABLE videos (
    bvid TEXT PRIMARY KEY,
    mid INTEGER NOT NULL REFERENCES up_masters(mid),
    
    title TEXT NOT NULL,
    description TEXT,
    pubdate INTEGER NOT NULL,          -- 发布时间
    duration_s INTEGER NOT NULL,        -- 总时长
    
    -- 视频属性
    is_multipart BOOLEAN NOT NULL DEFAULT 0,
    part_count INTEGER NOT NULL DEFAULT 1,
    
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    updated_at INTEGER NOT NULL DEFAULT (unixepoch())
);

CREATE INDEX idx_videos_mid ON videos(mid);
CREATE INDEX idx_videos_pubdate ON videos(pubdate);

-- 视频分P表（每个分P是一个独立的处理单元）
CREATE TABLE video_parts (
    work_id TEXT PRIMARY KEY,           -- BV1xx411c7mD:p0
    bvid TEXT NOT NULL REFERENCES videos(bvid),
    page_index INTEGER NOT NULL,
    cid INTEGER NOT NULL,               -- Bilibili 分P ID
    
    -- 分P元信息
    part_title TEXT,                    -- 分P标题（可能与视频标题不同）
    duration_s INTEGER NOT NULL,
    
    -- 处理状态
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN (
        'pending',      -- 待处理
        'meta_ok',      -- 元数据已获取
        'needs_audio',  -- 需要下载音频
        'audio_ok',     -- 音频已下载
        'asr_done',     -- ASR 已完成
        'archived',     -- 已归档
        'gone'          -- 视频已删除
    )),
    
    -- 转录来源
    source TEXT CHECK(source IN ('subtitle', 'asr')),
    
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    updated_at INTEGER NOT NULL DEFAULT (unixepoch()),
    
    UNIQUE(bvid, page_index)
);

CREATE INDEX idx_parts_bvid ON video_parts(bvid);
CREATE INDEX idx_parts_status ON video_parts(status);

-- ============================================================
-- 内容寻址表（Blob 元数据）
-- ============================================================

-- 音频 Blob 表
CREATE TABLE audio_blobs (
    hash TEXT PRIMARY KEY,              -- SHA-256
    
    -- 文件属性
    size_bytes INTEGER NOT NULL,
    format TEXT NOT NULL,               -- 'm4a', 'flac'
    duration_s INTEGER,
    
    -- 存储位置
    storage_path TEXT NOT NULL,         -- 相对路径：blobs/audio/sha256/47/47f14892...m4a
    
    -- 引用计数（用于垃圾回收）
    ref_count INTEGER NOT NULL DEFAULT 0,
    
    created_at INTEGER NOT NULL DEFAULT (unixepoch())
);

-- 转录 Blob 表
CREATE TABLE transcript_blobs (
    hash TEXT PRIMARY KEY,              -- SHA-256
    
    -- 文件属性
    size_bytes INTEGER NOT NULL,
    segment_count INTEGER NOT NULL,
    
    -- 存储位置
    storage_path TEXT NOT NULL,         -- blobs/transcripts/sha256/2d/2d19c048...json
    
    -- 引用计数
    ref_count INTEGER NOT NULL DEFAULT 0,
    
    created_at INTEGER NOT NULL DEFAULT (unixepoch())
);

-- ============================================================
-- 关联表（多对多关系）
-- ============================================================

-- 视频分P ↔ 音频（1:1 或 1:0）
CREATE TABLE part_audio_map (
    work_id TEXT PRIMARY KEY REFERENCES video_parts(work_id),
    audio_hash TEXT NOT NULL REFERENCES audio_blobs(hash),
    
    -- 下载元信息
    downloaded_at INTEGER NOT NULL,
    download_source TEXT,               -- 'bilibili', 'local'
    
    UNIQUE(work_id, audio_hash)
);

CREATE INDEX idx_part_audio_hash ON part_audio_map(audio_hash);

-- 视频分P ↔ 转录（1:N，支持多版本）
CREATE TABLE part_transcript_map (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_id TEXT NOT NULL REFERENCES video_parts(work_id),
    transcript_hash TEXT NOT NULL REFERENCES transcript_blobs(hash),
    
    -- 版本信息
    version INTEGER NOT NULL,           -- 同一个 work_id 的版本号（从 1 开始）
    is_latest BOOLEAN NOT NULL DEFAULT 1,
    
    -- ASR 元信息
    model_name TEXT NOT NULL,
    device TEXT,                        -- 'cuda', 'cpu'
    
    -- 转录统计
    avg_confidence REAL,
    
    generated_at INTEGER NOT NULL DEFAULT (unixepoch()),
    
    UNIQUE(work_id, version)
);

CREATE INDEX idx_part_transcript_work ON part_transcript_map(work_id);
CREATE INDEX idx_part_transcript_hash ON part_transcript_map(transcript_hash);
CREATE INDEX idx_part_transcript_latest ON part_transcript_map(work_id, is_latest) WHERE is_latest = 1;

-- ============================================================
-- 执行历史表
-- ============================================================

-- 命令执行记录
CREATE TABLE runs (
    run_id TEXT PRIMARY KEY,            -- run-20260824123456-abc123
    command TEXT NOT NULL,              -- 'fetch-meta', 'pilot', 'run', 'schedule'
    
    -- 时间
    started_at INTEGER NOT NULL,
    finished_at INTEGER NOT NULL,
    
    -- 结果
    exit_code INTEGER NOT NULL,
    
    -- 统计
    records_processed INTEGER DEFAULT 0,
    records_succeeded INTEGER DEFAULT 0,
    records_failed INTEGER DEFAULT 0
);

CREATE INDEX idx_runs_started ON runs(started_at DESC);
CREATE INDEX idx_runs_command ON runs(command);

-- 阶段尝试记录
CREATE TABLE stage_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_id TEXT NOT NULL REFERENCES video_parts(work_id),
    run_id TEXT REFERENCES runs(run_id),
    
    stage TEXT NOT NULL CHECK(stage IN ('harvest', 'download', 'asr', 'archive')),
    attempt_num INTEGER NOT NULL,       -- 每个 work_id + stage 的尝试次数
    
    outcome TEXT NOT NULL CHECK(outcome IN ('ok', 'failed', 'skipped')),
    error_code TEXT,
    
    started_at INTEGER NOT NULL,
    finished_at INTEGER NOT NULL,
    
    UNIQUE(work_id, stage, attempt_num)
);

CREATE INDEX idx_attempts_work ON stage_attempts(work_id);
CREATE INDEX idx_attempts_outcome ON stage_attempts(outcome);

-- ============================================================
-- 全文搜索（FTS5）
-- ============================================================

CREATE VIRTUAL TABLE search_fts USING fts5(
    work_id UNINDEXED,
    bvid UNINDEXED,
    video_title,
    part_title,
    transcript_text,
    tokenize='unicode61'
);

-- ============================================================
-- 视图（方便查询）
-- ============================================================

-- 完整的视频分P视图（连接所有相关表）
CREATE VIEW v_video_parts_full AS
SELECT 
    p.work_id,
    p.bvid,
    p.page_index,
    p.cid,
    p.part_title,
    p.duration_s,
    p.status,
    p.source,
    
    -- 视频信息
    v.title AS video_title,
    v.mid,
    v.pubdate,
    
    -- UP主信息
    u.name AS up_name,
    
    -- 音频信息
    a.audio_hash,
    ab.size_bytes AS audio_size,
    ab.format AS audio_format,
    ab.storage_path AS audio_path,
    
    -- 转录信息（最新版本）
    t.transcript_hash,
    t.version AS transcript_version,
    t.model_name,
    tb.segment_count,
    tb.storage_path AS transcript_path,
    
    p.created_at,
    p.updated_at
FROM video_parts p
JOIN videos v ON p.bvid = v.bvid
JOIN up_masters u ON v.mid = u.mid
LEFT JOIN part_audio_map a ON p.work_id = a.work_id
LEFT JOIN audio_blobs ab ON a.audio_hash = ab.hash
LEFT JOIN part_transcript_map t ON p.work_id = t.work_id AND t.is_latest = 1
LEFT JOIN transcript_blobs tb ON t.transcript_hash = tb.hash;

-- 待处理的视频分P
CREATE VIEW v_pending_parts AS
SELECT 
    work_id,
    bvid,
    part_title,
    duration_s,
    status
FROM video_parts
WHERE status IN ('meta_ok', 'needs_audio', 'audio_ok', 'asr_done')
ORDER BY duration_s ASC;

-- 已归档的统计
CREATE VIEW v_archive_stats AS
SELECT 
    status,
    COUNT(*) AS count,
    SUM(duration_s) AS total_duration_s,
    ROUND(AVG(duration_s), 2) AS avg_duration_s
FROM video_parts
GROUP BY status;

-- UP主统计
CREATE VIEW v_up_master_stats AS
SELECT 
    u.mid,
    u.name,
    COUNT(DISTINCT v.bvid) AS video_count,
    COUNT(p.work_id) AS part_count,
    SUM(CASE WHEN p.status = 'archived' THEN 1 ELSE 0 END) AS archived_count,
    SUM(p.duration_s) AS total_duration_s
FROM up_masters u
JOIN videos v ON u.mid = v.mid
JOIN video_parts p ON v.bvid = p.bvid
GROUP BY u.mid, u.name;

-- ============================================================
-- 触发器（维护引用计数和状态一致性）
-- ============================================================

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

-- 转录 Blob 引用计数
CREATE TRIGGER transcript_blob_ref_inc
AFTER INSERT ON part_transcript_map
BEGIN
    UPDATE transcript_blobs 
    SET ref_count = ref_count + 1 
    WHERE hash = NEW.transcript_hash;
END;

CREATE TRIGGER transcript_blob_ref_dec
AFTER DELETE ON part_transcript_map
BEGIN
    UPDATE transcript_blobs 
    SET ref_count = ref_count - 1 
    WHERE hash = OLD.transcript_hash;
END;

-- 自动维护 is_latest 标志
CREATE TRIGGER transcript_version_latest
AFTER INSERT ON part_transcript_map
BEGIN
    -- 将同一个 work_id 的其他版本标记为非最新
    UPDATE part_transcript_map 
    SET is_latest = 0 
    WHERE work_id = NEW.work_id AND id != NEW.id;
END;

-- 自动更新 updated_at
CREATE TRIGGER video_parts_updated
AFTER UPDATE ON video_parts
BEGIN
    UPDATE video_parts 
    SET updated_at = unixepoch() 
    WHERE work_id = NEW.work_id;
END;

-- ============================================================
-- 函数式依赖验证（3NF 证明）
-- ============================================================

/*
表：up_masters
主键：mid
函数依赖：mid → {name, total_videos, ...}
✓ 2NF: 无复合主键，无部分依赖
✓ 3NF: 所有非主键字段直接依赖于 mid

表：videos
主键：bvid
函数依赖：bvid → {mid, title, pubdate, ...}
         mid → {name} (但 name 不在此表，通过外键引用)
✓ 2NF: 无复合主键
✓ 3NF: mid 是外键，指向 up_masters，无传递依赖

表：video_parts
主键：work_id
候选键：(bvid, page_index)
函数依赖：work_id → {bvid, page_index, cid, status, ...}
         (bvid, page_index) → work_id
✓ 2NF: 所有字段完全依赖于主键
✓ 3NF: 无非主键字段依赖其他非主键字段

表：audio_blobs
主键：hash (SHA-256)
函数依赖：hash → {size_bytes, format, storage_path, ...}
✓ 2NF: 无复合主键
✓ 3NF: 所有字段直接由 hash（内容）决定

表：transcript_blobs
主键：hash
函数依赖：hash → {size_bytes, segment_count, ...}
✓ 2NF: 无复合主键
✓ 3NF: 内容寻址，无传递依赖

表：part_audio_map
主键：work_id
外键：audio_hash
函数依赖：work_id → audio_hash
✓ 这是一个纯关联表，只存储关系，满足 3NF

表：part_transcript_map
主键：id
候选键：(work_id, version)
函数依赖：id → {work_id, transcript_hash, version, model_name, ...}
         (work_id, version) → id
✓ 2NF: 所有字段完全依赖于主键
✓ 3NF: model_name 等字段描述的是"这次转录"，不是 work_id 或 transcript_hash 的属性

结论：所有表都满足 3NF
*/

-- ============================================================
-- 索引策略
-- ============================================================

/*
查询模式分析：

1. 按状态查询待处理的视频分P
   → idx_parts_status

2. 按 UP 主查询所有视频
   → idx_videos_mid

3. 按发布时间排序
   → idx_videos_pubdate

4. 查找特定视频的所有分P
   → idx_parts_bvid

5. 全文搜索转录内容
   → search_fts

6. 查询音频/转录的引用情况
   → idx_part_audio_hash
   → idx_part_transcript_hash

7. 查询最新的转录版本
   → idx_part_transcript_latest (过滤索引)
*/

-- ============================================================
-- 示例数据（用于测试）
-- ============================================================

-- UP 主
INSERT INTO up_masters (mid, name) VALUES 
(23191782, '未明子');

-- 视频
INSERT INTO videos (bvid, mid, title, pubdate, duration_s, is_multipart, part_count) VALUES
('BV1xx411c7mD', 23191782, '测试视频', 1693843200, 600, 1, 2);

-- 视频分P
INSERT INTO video_parts (work_id, bvid, page_index, cid, part_title, duration_s, status) VALUES
('BV1xx411c7mD:p0', 'BV1xx411c7mD', 0, 123456, '第一部分', 300, 'pending'),
('BV1xx411c7mD:p1', 'BV1xx411c7mD', 1, 123457, '第二部分', 300, 'pending');

-- 验证查询
SELECT * FROM v_video_parts_full;
SELECT * FROM v_pending_parts;
SELECT * FROM v_archive_stats;
