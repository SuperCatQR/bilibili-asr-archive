-- SQLite 统一数据库架构提案
-- 替代当前的 manifest.jsonl + 多个 sidecar 文件

-- ============================================================
-- 核心表：视频记录（替代 manifest.jsonl）
-- ============================================================
CREATE TABLE videos (
    work_id TEXT PRIMARY KEY,           -- BV1xx411c7mD:p0
    bvid TEXT NOT NULL,
    page_index INTEGER NOT NULL DEFAULT 0,
    cid INTEGER,
    
    -- 元数据
    title TEXT,
    duration_s INTEGER,
    page_label TEXT,
    pubdate INTEGER,                    -- Unix timestamp
    
    -- 状态机
    status TEXT NOT NULL DEFAULT 'pending',
    source TEXT,                        -- 'subtitle' | 'asr' | NULL
    
    -- 文件路径（相对于 archive-root）
    audio_path TEXT,
    srt_path TEXT,
    txt_path TEXT,
    md_path TEXT,
    raw_path TEXT,
    
    -- 标记
    unresolved BOOLEAN DEFAULT 0,
    unresolved_reason TEXT,
    
    -- 时间戳
    created_at INTEGER NOT NULL,        -- Unix timestamp
    updated_at INTEGER NOT NULL,
    archived_at INTEGER,                -- 完成归档的时间
    
    UNIQUE(bvid, page_index),
    CHECK(status IN ('pending', 'meta_ok', 'sub_checked', 'subtitle_done', 
                     'needs_audio', 'audio_ok', 'asr_done', 'archived', 'gone'))
);

CREATE INDEX idx_videos_status ON videos(status);
CREATE INDEX idx_videos_bvid ON videos(bvid);
CREATE INDEX idx_videos_updated ON videos(updated_at);

-- ============================================================
-- 执行历史（替代 run-ledger.jsonl）
-- ============================================================
CREATE TABLE run_ledger (
    run_id TEXT PRIMARY KEY,            -- run-20260824123456-abc123
    command TEXT NOT NULL,              -- 'fetch-meta' | 'pilot' | 'run' | 'schedule'
    started_at INTEGER NOT NULL,
    finished_at INTEGER NOT NULL,
    exit_code INTEGER NOT NULL,
    
    mid INTEGER,                        -- Bilibili UP主 ID
    pages_fetched INTEGER,
    records_fetched INTEGER,
    records_existing INTEGER,
    last_api_error_code TEXT,           -- 标量错误码
    
    -- 快照
    coverage_summary TEXT,              -- JSON: {"archived": 100, "pending": 50}
    cursor_snapshot TEXT                -- JSON: meta-cursor 状态
);

CREATE INDEX idx_run_ledger_started ON run_ledger(started_at DESC);

-- ============================================================
-- 阶段尝试（替代 coordinator/attempts.jsonl）
-- ============================================================
CREATE TABLE stage_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_id TEXT NOT NULL,
    stage TEXT NOT NULL,                -- 'harvest' | 'download' | 'asr' | 'archive'
    attempt INTEGER NOT NULL,           -- 每个 work_id + stage 的尝试次数
    
    outcome TEXT NOT NULL,              -- 'ok' | 'failed' | 'skipped'
    error_code TEXT,                    -- 标量错误码或 skip reason
    
    artifact_paths TEXT,                -- JSON 数组
    started_at INTEGER NOT NULL,
    finished_at INTEGER NOT NULL,
    
    FOREIGN KEY(work_id) REFERENCES videos(work_id),
    CHECK(stage IN ('harvest', 'download', 'asr', 'archive')),
    CHECK(outcome IN ('ok', 'failed', 'skipped')),
    UNIQUE(work_id, stage, attempt)
);

CREATE INDEX idx_attempts_work ON stage_attempts(work_id);
CREATE INDEX idx_attempts_outcome ON stage_attempts(outcome, work_id);

-- ============================================================
-- 元数据抓取进度（替代 meta-cursor.json）
-- ============================================================
CREATE TABLE meta_cursor (
    mid INTEGER PRIMARY KEY,
    next_page INTEGER NOT NULL DEFAULT 1,
    total INTEGER,
    state TEXT NOT NULL DEFAULT 'initial',
    last_api_error_code TEXT,
    updated_at INTEGER NOT NULL,
    
    CHECK(state IN ('initial', 'complete', 'limited', 'risk_interrupted'))
);

-- ============================================================
-- 调度检查点（替代 scheduler.json）
-- ============================================================
CREATE TABLE scheduler_checkpoint (
    id INTEGER PRIMARY KEY CHECK(id = 1), -- 单行表
    scope TEXT NOT NULL,
    state TEXT NOT NULL,                -- 'complete' | 'limited' | 'risk_interrupted'
    limit_value INTEGER,
    allow_long_live BOOLEAN DEFAULT 0,
    processed_work_ids TEXT,            -- JSON 数组
    updated_at INTEGER NOT NULL,
    
    CHECK(state IN ('complete', 'limited', 'risk_interrupted'))
);

-- ============================================================
-- 批次审计（替代 campaign.json）
-- ============================================================
CREATE TABLE campaign_checkpoint (
    id INTEGER PRIMARY KEY CHECK(id = 1), -- 单行表
    snapshot_id TEXT NOT NULL,
    scope TEXT NOT NULL,
    state TEXT NOT NULL,
    limit_value INTEGER NOT NULL,
    policy_fingerprint TEXT,
    processed_work_ids TEXT,            -- JSON 数组
    updated_at INTEGER NOT NULL,
    
    CHECK(state IN ('complete', 'limited', 'risk_interrupted'))
);

-- ============================================================
-- 全文搜索（保留独立的 search.db 或合并）
-- ============================================================
-- 选项1：保留独立 search.db（当前方案）
-- 选项2：合并到主库
CREATE VIRTUAL TABLE IF NOT EXISTS transcripts_fts USING fts5(
    work_id UNINDEXED,
    title,
    transcript_text,
    content=videos,
    content_rowid=rowid
);

-- FTS5 触发器：自动同步
CREATE TRIGGER videos_ai AFTER INSERT ON videos BEGIN
    INSERT INTO transcripts_fts(rowid, work_id, title, transcript_text)
    SELECT rowid, work_id, title, '' FROM videos WHERE work_id = new.work_id;
END;

CREATE TRIGGER videos_ad AFTER DELETE ON videos BEGIN
    DELETE FROM transcripts_fts WHERE rowid = old.rowid;
END;

CREATE TRIGGER videos_au AFTER UPDATE ON videos BEGIN
    UPDATE transcripts_fts SET title = new.title WHERE rowid = new.rowid;
END;

-- ============================================================
-- 数据库元信息
-- ============================================================
CREATE TABLE schema_version (
    version INTEGER PRIMARY KEY,
    applied_at INTEGER NOT NULL
);

INSERT INTO schema_version (version, applied_at) VALUES (1, unixepoch());

-- ============================================================
-- 常用查询视图
-- ============================================================

-- 需要处理的视频
CREATE VIEW v_pending AS
SELECT * FROM videos 
WHERE status IN ('meta_ok', 'sub_checked', 'needs_audio', 'audio_ok', 'asr_done')
ORDER BY duration_s ASC;

-- 失败的尝试
CREATE VIEW v_failed_attempts AS
SELECT DISTINCT work_id, stage, MAX(attempt) as last_attempt
FROM stage_attempts
WHERE outcome = 'failed'
GROUP BY work_id, stage;

-- 覆盖率统计
CREATE VIEW v_coverage_stats AS
SELECT 
    status,
    COUNT(*) as count,
    SUM(duration_s) as total_duration_s,
    ROUND(AVG(duration_s), 2) as avg_duration_s
FROM videos
GROUP BY status;

-- 最近的运行
CREATE VIEW v_recent_runs AS
SELECT 
    run_id,
    command,
    datetime(started_at, 'unixepoch') as started,
    exit_code,
    json_extract(coverage_summary, '$.archived') as archived_count
FROM run_ledger
ORDER BY started_at DESC
LIMIT 10;
