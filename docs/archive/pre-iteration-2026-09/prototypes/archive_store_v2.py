"""
Bilibili ASR Archive - 新存储系统 (3NF)

基于 schema-3nf.sql 的完整实现
"""

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Optional, List, Dict, Any


class ArchiveDB:
    """3NF 数据库封装"""
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()
    
    def _init_schema(self):
        """初始化数据库结构"""
        schema_path = Path(__file__).parent.parent / "schema-3nf.sql"
        if schema_path.exists():
            with open(schema_path) as f:
                self.conn.executescript(f.read())
        else:
            # 内联 schema（用于独立部署）
            self.conn.executescript("""
                -- 核心表
                CREATE TABLE IF NOT EXISTS up_masters (
                    mid INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    total_videos INTEGER DEFAULT 0,
                    archived_videos INTEGER DEFAULT 0,
                    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
                    updated_at INTEGER NOT NULL DEFAULT (unixepoch())
                );
                
                CREATE TABLE IF NOT EXISTS videos (
                    bvid TEXT PRIMARY KEY,
                    mid INTEGER NOT NULL REFERENCES up_masters(mid),
                    title TEXT NOT NULL,
                    description TEXT,
                    pubdate INTEGER NOT NULL,
                    duration_s INTEGER NOT NULL,
                    is_multipart BOOLEAN NOT NULL DEFAULT 0,
                    part_count INTEGER NOT NULL DEFAULT 1,
                    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
                    updated_at INTEGER NOT NULL DEFAULT (unixepoch())
                );
                
                CREATE TABLE IF NOT EXISTS video_parts (
                    work_id TEXT PRIMARY KEY,
                    bvid TEXT NOT NULL REFERENCES videos(bvid),
                    page_index INTEGER NOT NULL,
                    cid INTEGER NOT NULL,
                    part_title TEXT,
                    duration_s INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    source TEXT,
                    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
                    updated_at INTEGER NOT NULL DEFAULT (unixepoch()),
                    UNIQUE(bvid, page_index),
                    CHECK(status IN ('pending', 'meta_ok', 'needs_audio', 'audio_ok', 'asr_done', 'archived', 'gone')),
                    CHECK(source IN ('subtitle', 'asr'))
                );
                
                CREATE TABLE IF NOT EXISTS audio_blobs (
                    hash TEXT PRIMARY KEY,
                    size_bytes INTEGER NOT NULL,
                    format TEXT NOT NULL,
                    duration_s INTEGER,
                    storage_path TEXT NOT NULL,
                    ref_count INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL DEFAULT (unixepoch())
                );
                
                CREATE TABLE IF NOT EXISTS transcript_blobs (
                    hash TEXT PRIMARY KEY,
                    size_bytes INTEGER NOT NULL,
                    segment_count INTEGER NOT NULL,
                    storage_path TEXT NOT NULL,
                    ref_count INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL DEFAULT (unixepoch())
                );
                
                CREATE TABLE IF NOT EXISTS part_audio_map (
                    work_id TEXT PRIMARY KEY REFERENCES video_parts(work_id),
                    audio_hash TEXT NOT NULL REFERENCES audio_blobs(hash),
                    downloaded_at INTEGER NOT NULL,
                    download_source TEXT,
                    UNIQUE(work_id, audio_hash)
                );
                
                CREATE TABLE IF NOT EXISTS part_transcript_map (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    work_id TEXT NOT NULL REFERENCES video_parts(work_id),
                    transcript_hash TEXT NOT NULL REFERENCES transcript_blobs(hash),
                    version INTEGER NOT NULL,
                    is_latest BOOLEAN NOT NULL DEFAULT 1,
                    model_name TEXT NOT NULL,
                    device TEXT,
                    avg_confidence REAL,
                    generated_at INTEGER NOT NULL DEFAULT (unixepoch()),
                    UNIQUE(work_id, version)
                );
                
                -- 索引
                CREATE INDEX IF NOT EXISTS idx_videos_mid ON videos(mid);
                CREATE INDEX IF NOT EXISTS idx_parts_status ON video_parts(status);
                CREATE INDEX IF NOT EXISTS idx_parts_bvid ON video_parts(bvid);
                CREATE INDEX IF NOT EXISTS idx_part_audio_hash ON part_audio_map(audio_hash);
                CREATE INDEX IF NOT EXISTS idx_part_transcript_work ON part_transcript_map(work_id);
                CREATE INDEX IF NOT EXISTS idx_part_transcript_hash ON part_transcript_map(transcript_hash);
                
                -- 触发器
                CREATE TRIGGER IF NOT EXISTS audio_blob_ref_inc
                AFTER INSERT ON part_audio_map
                BEGIN
                    UPDATE audio_blobs SET ref_count = ref_count + 1 WHERE hash = NEW.audio_hash;
                END;
                
                CREATE TRIGGER IF NOT EXISTS audio_blob_ref_dec
                AFTER DELETE ON part_audio_map
                BEGIN
                    UPDATE audio_blobs SET ref_count = ref_count - 1 WHERE hash = OLD.audio_hash;
                END;
                
                CREATE TRIGGER IF NOT EXISTS transcript_blob_ref_inc
                AFTER INSERT ON part_transcript_map
                BEGIN
                    UPDATE transcript_blobs SET ref_count = ref_count + 1 WHERE hash = NEW.transcript_hash;
                END;
                
                CREATE TRIGGER IF NOT EXISTS transcript_blob_ref_dec
                AFTER DELETE ON part_transcript_map
                BEGIN
                    UPDATE transcript_blobs SET ref_count = ref_count - 1 WHERE hash = OLD.transcript_hash;
                END;
                
                CREATE TRIGGER IF NOT EXISTS transcript_version_latest
                AFTER INSERT ON part_transcript_map
                BEGIN
                    UPDATE part_transcript_map SET is_latest = 0 
                    WHERE work_id = NEW.work_id AND id != NEW.id;
                END;
            """)
        self.conn.commit()
    
    # ==================== UP 主 ====================
    
    def upsert_up_master(self, mid: int, name: str) -> None:
        """插入或更新 UP 主"""
        self.conn.execute("""
            INSERT INTO up_masters (mid, name)
            VALUES (?, ?)
            ON CONFLICT(mid) DO UPDATE SET
                name = excluded.name,
                updated_at = unixepoch()
        """, (mid, name))
        self.conn.commit()
    
    # ==================== 视频 ====================
    
    def upsert_video(self, bvid: str, mid: int, title: str, 
                     pubdate: int, duration_s: int, 
                     part_count: int = 1) -> None:
        """插入或更新视频"""
        self.conn.execute("""
            INSERT INTO videos (bvid, mid, title, pubdate, duration_s, 
                               is_multipart, part_count)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(bvid) DO UPDATE SET
                title = excluded.title,
                part_count = excluded.part_count,
                updated_at = unixepoch()
        """, (bvid, mid, title, pubdate, duration_s, 
              part_count > 1, part_count))
        self.conn.commit()
    
    # ==================== 视频分P ====================
    
    def upsert_video_part(self, work_id: str, bvid: str, page_index: int,
                          cid: int, part_title: str, duration_s: int,
                          status: str = 'pending') -> None:
        """插入或更新视频分P"""
        self.conn.execute("""
            INSERT INTO video_parts 
            (work_id, bvid, page_index, cid, part_title, duration_s, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(work_id) DO UPDATE SET
                part_title = excluded.part_title,
                status = excluded.status,
                updated_at = unixepoch()
        """, (work_id, bvid, page_index, cid, part_title, duration_s, status))
        self.conn.commit()
    
    def update_part_status(self, work_id: str, status: str, 
                           source: Optional[str] = None) -> None:
        """更新分P状态"""
        if source:
            self.conn.execute("""
                UPDATE video_parts 
                SET status = ?, source = ?, updated_at = unixepoch()
                WHERE work_id = ?
            """, (status, source, work_id))
        else:
            self.conn.execute("""
                UPDATE video_parts 
                SET status = ?, updated_at = unixepoch()
                WHERE work_id = ?
            """, (status, work_id))
        self.conn.commit()
    
    def get_video_part(self, work_id: str) -> Optional[Dict]:
        """获取视频分P"""
        row = self.conn.execute("""
            SELECT * FROM video_parts WHERE work_id = ?
        """, (work_id,)).fetchone()
        return dict(row) if row else None
    
    def get_pending_parts(self, limit: int = 100) -> List[Dict]:
        """获取待处理的视频分P"""
        rows = self.conn.execute("""
            SELECT * FROM video_parts
            WHERE status IN ('meta_ok', 'needs_audio', 'audio_ok', 'asr_done')
            ORDER BY duration_s ASC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(row) for row in rows]
    
    # ==================== 音频 Blob ====================
    
    def store_audio_blob(self, audio_data: bytes, format: str = 'm4a',
                         duration_s: Optional[int] = None) -> str:
        """存储音频 Blob，返回哈希值"""
        audio_hash = hashlib.sha256(audio_data).hexdigest()
        storage_path = f"blobs/audio/sha256/{audio_hash[:2]}/{audio_hash}.{format}"
        
        self.conn.execute("""
            INSERT OR IGNORE INTO audio_blobs 
            (hash, size_bytes, format, duration_s, storage_path)
            VALUES (?, ?, ?, ?, ?)
        """, (audio_hash, len(audio_data), format, duration_s, storage_path))
        self.conn.commit()
        
        return audio_hash
    
    def link_audio_to_part(self, work_id: str, audio_hash: str,
                           download_source: str = 'bilibili') -> None:
        """关联音频到视频分P"""
        self.conn.execute("""
            INSERT OR REPLACE INTO part_audio_map 
            (work_id, audio_hash, downloaded_at, download_source)
            VALUES (?, ?, unixepoch(), ?)
        """, (work_id, audio_hash, download_source))
        self.conn.commit()
    
    def get_audio_path(self, work_id: str) -> Optional[str]:
        """获取音频存储路径"""
        row = self.conn.execute("""
            SELECT ab.storage_path
            FROM part_audio_map pam
            JOIN audio_blobs ab ON pam.audio_hash = ab.hash
            WHERE pam.work_id = ?
        """, (work_id,)).fetchone()
        return row[0] if row else None
    
    # ==================== 转录 Blob ====================
    
    def store_transcript_blob(self, segments: List[Dict]) -> str:
        """存储转录 Blob，返回哈希值"""
        transcript_data = json.dumps(segments, ensure_ascii=False).encode()
        transcript_hash = hashlib.sha256(transcript_data).hexdigest()
        storage_path = f"blobs/transcripts/sha256/{transcript_hash[:2]}/{transcript_hash}.json"
        
        self.conn.execute("""
            INSERT OR IGNORE INTO transcript_blobs
            (hash, size_bytes, segment_count, storage_path)
            VALUES (?, ?, ?, ?)
        """, (transcript_hash, len(transcript_data), len(segments), storage_path))
        self.conn.commit()
        
        return transcript_hash
    
    def link_transcript_to_part(self, work_id: str, transcript_hash: str,
                                model_name: str, device: str = 'cuda') -> int:
        """关联转录到视频分P，返回版本号"""
        # 获取下一个版本号
        version = self.conn.execute("""
            SELECT COALESCE(MAX(version), 0) + 1
            FROM part_transcript_map
            WHERE work_id = ?
        """, (work_id,)).fetchone()[0]
        
        # 插入新版本
        self.conn.execute("""
            INSERT INTO part_transcript_map
            (work_id, transcript_hash, version, model_name, device, is_latest)
            VALUES (?, ?, ?, ?, ?, 1)
        """, (work_id, transcript_hash, version, model_name, device))
        self.conn.commit()
        
        return version
    
    def get_latest_transcript(self, work_id: str) -> Optional[Dict]:
        """获取最新的转录"""
        row = self.conn.execute("""
            SELECT ptm.*, tb.storage_path, tb.segment_count
            FROM part_transcript_map ptm
            JOIN transcript_blobs tb ON ptm.transcript_hash = tb.hash
            WHERE ptm.work_id = ? AND ptm.is_latest = 1
        """, (work_id,)).fetchone()
        return dict(row) if row else None
    
    def get_transcript_versions(self, work_id: str) -> List[Dict]:
        """获取所有转录版本"""
        rows = self.conn.execute("""
            SELECT ptm.*, tb.storage_path
            FROM part_transcript_map ptm
            JOIN transcript_blobs tb ON ptm.transcript_hash = tb.hash
            WHERE ptm.work_id = ?
            ORDER BY ptm.version DESC
        """, (work_id,)).fetchall()
        return [dict(row) for row in rows]
    
    # ==================== 统计查询 ====================
    
    def get_status_stats(self) -> Dict[str, int]:
        """获取状态统计"""
        rows = self.conn.execute("""
            SELECT status, COUNT(*) as count
            FROM video_parts
            GROUP BY status
        """).fetchall()
        return {row[0]: row[1] for row in rows}
    
    def get_storage_stats(self) -> Dict[str, Any]:
        """获取存储统计"""
        audio_stats = self.conn.execute("""
            SELECT 
                COUNT(*) as count,
                SUM(size_bytes) as total_bytes,
                SUM(ref_count) as total_refs
            FROM audio_blobs
        """).fetchone()
        
        transcript_stats = self.conn.execute("""
            SELECT 
                COUNT(*) as count,
                SUM(size_bytes) as total_bytes,
                SUM(ref_count) as total_refs
            FROM transcript_blobs
        """).fetchone()
        
        return {
            'audio': {
                'blob_count': audio_stats[0],
                'total_bytes': audio_stats[1] or 0,
                'total_refs': audio_stats[2] or 0
            },
            'transcript': {
                'blob_count': transcript_stats[0],
                'total_bytes': transcript_stats[1] or 0,
                'total_refs': transcript_stats[2] or 0
            }
        }
    
    # ==================== 垃圾回收 ====================
    
    def garbage_collect(self) -> Dict[str, int]:
        """清理未被引用的 Blob"""
        audio_deleted = self.conn.execute("""
            DELETE FROM audio_blobs WHERE ref_count = 0
        """).rowcount
        
        transcript_deleted = self.conn.execute("""
            DELETE FROM transcript_blobs WHERE ref_count = 0
        """).rowcount
        
        self.conn.commit()
        
        return {
            'audio_deleted': audio_deleted,
            'transcript_deleted': transcript_deleted
        }


class BlobStore:
    """文件系统 Blob 存储"""
    
    def __init__(self, root: Path):
        self.root = root
        self.audio_dir = root / "blobs" / "audio" / "sha256"
        self.transcript_dir = root / "blobs" / "transcripts" / "sha256"
        
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.transcript_dir.mkdir(parents=True, exist_ok=True)
    
    def write_audio(self, audio_hash: str, data: bytes, format: str = 'm4a') -> Path:
        """写入音频文件"""
        subdir = self.audio_dir / audio_hash[:2]
        subdir.mkdir(exist_ok=True)
        
        path = subdir / f"{audio_hash}.{format}"
        if not path.exists():
            temp = path.with_suffix('.tmp')
            temp.write_bytes(data)
            temp.rename(path)
        
        return path
    
    def write_transcript(self, transcript_hash: str, segments: List[Dict]) -> Path:
        """写入转录文件"""
        subdir = self.transcript_dir / transcript_hash[:2]
        subdir.mkdir(exist_ok=True)
        
        path = subdir / f"{transcript_hash}.json"
        if not path.exists():
            temp = path.with_suffix('.tmp')
            temp.write_text(json.dumps(segments, ensure_ascii=False, indent=2))
            temp.rename(path)
        
        return path
    
    def read_audio(self, audio_hash: str, format: str = 'm4a') -> bytes:
        """读取音频文件"""
        path = self.audio_dir / audio_hash[:2] / f"{audio_hash}.{format}"
        return path.read_bytes()
    
    def read_transcript(self, transcript_hash: str) -> List[Dict]:
        """读取转录文件"""
        path = self.transcript_dir / transcript_hash[:2] / f"{transcript_hash}.json"
        return json.loads(path.read_text())


class ArchiveStore:
    """统一的归档存储接口"""
    
    def __init__(self, root: Path):
        self.root = root
        self.db = ArchiveDB(root / "archive.db")
        self.blobs = BlobStore(root)
    
    def add_up_master(self, mid: int, name: str):
        """添加 UP 主"""
        self.db.upsert_up_master(mid, name)
    
    def add_video(self, bvid: str, mid: int, title: str, pubdate: int,
                  duration_s: int, parts: List[Dict]) -> None:
        """添加视频和所有分P"""
        # 1. 添加视频
        self.db.upsert_video(bvid, mid, title, pubdate, duration_s, len(parts))
        
        # 2. 添加所有分P
        for part in parts:
            work_id = f"{bvid}:p{part['page_index']}"
            self.db.upsert_video_part(
                work_id=work_id,
                bvid=bvid,
                page_index=part['page_index'],
                cid=part['cid'],
                part_title=part.get('part_title', title),
                duration_s=part['duration_s'],
                status='meta_ok'
            )
    
    def store_audio(self, work_id: str, audio_data: bytes,
                    format: str = 'm4a', duration_s: Optional[int] = None) -> str:
        """存储音频"""
        # 1. 存储到数据库（获取哈希）
        audio_hash = self.db.store_audio_blob(audio_data, format, duration_s)
        
        # 2. 写入文件系统
        self.blobs.write_audio(audio_hash, audio_data, format)
        
        # 3. 关联到视频分P
        self.db.link_audio_to_part(work_id, audio_hash)
        
        # 4. 更新状态
        self.db.update_part_status(work_id, 'audio_ok')
        
        return audio_hash
    
    def store_transcript(self, work_id: str, segments: List[Dict],
                         model_name: str = 'Fun-ASR-Nano-2512',
                         device: str = 'cuda', source: str = 'asr') -> str:
        """存储转录"""
        # 1. 存储到数据库（获取哈希）
        transcript_hash = self.db.store_transcript_blob(segments)
        
        # 2. 写入文件系统
        self.blobs.write_transcript(transcript_hash, segments)
        
        # 3. 关联到视频分P
        version = self.db.link_transcript_to_part(
            work_id, transcript_hash, model_name, device
        )
        
        # 4. 更新状态
        self.db.update_part_status(work_id, 'archived', source)
        
        return transcript_hash
    
    def get_audio_data(self, work_id: str) -> Optional[bytes]:
        """获取音频数据"""
        path = self.db.get_audio_path(work_id)
        if not path:
            return None
        
        full_path = self.root / path
        return full_path.read_bytes() if full_path.exists() else None
    
    def get_transcript_data(self, work_id: str) -> Optional[List[Dict]]:
        """获取最新转录数据"""
        transcript = self.db.get_latest_transcript(work_id)
        if not transcript:
            return None
        
        full_path = self.root / transcript['storage_path']
        return json.loads(full_path.read_text()) if full_path.exists() else None
