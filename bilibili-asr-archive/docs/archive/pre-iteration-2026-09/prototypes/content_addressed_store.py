"""
内容寻址存储系统 - 核心实现

设计原则：
1. 音频和转录文件以 SHA-256 哈希值存储（内容寻址）
2. SQLite 存储元数据和索引
3. 导出格式按需生成（可删除重建）
"""

import hashlib
import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Optional


class ContentAddressedStore:
    """内容寻址存储：文件以哈希值命名，自动去重"""
    
    def __init__(self, root: Path):
        self.root = root
        self.audio_dir = root / "blobs" / "audio" / "sha256"
        self.transcript_dir = root / "blobs" / "transcripts" / "sha256"
        
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.transcript_dir.mkdir(parents=True, exist_ok=True)
    
    def store_audio(self, content: bytes) -> str:
        """存储音频文件，返回哈希值"""
        hash_val = hashlib.sha256(content).hexdigest()
        
        # 两级目录：sha256/a1/a1b2c3...def.m4a
        dir_path = self.audio_dir / hash_val[:2]
        file_path = dir_path / f"{hash_val}.m4a"
        
        if not file_path.exists():
            dir_path.mkdir(parents=True, exist_ok=True)
            # 原子写入
            temp_path = file_path.with_suffix('.tmp')
            temp_path.write_bytes(content)
            temp_path.rename(file_path)
        
        return hash_val
    
    def store_transcript(self, segments: list[dict]) -> str:
        """存储转录 JSON，返回哈希值"""
        content = json.dumps(segments, ensure_ascii=False, indent=2).encode('utf-8')
        hash_val = hashlib.sha256(content).hexdigest()
        
        dir_path = self.transcript_dir / hash_val[:2]
        file_path = dir_path / f"{hash_val}.json"
        
        if not file_path.exists():
            dir_path.mkdir(parents=True, exist_ok=True)
            temp_path = file_path.with_suffix('.tmp')
            temp_path.write_bytes(content)
            temp_path.rename(file_path)
        
        return hash_val
    
    def get_audio_path(self, hash_val: str) -> Path:
        """根据哈希值获取音频文件路径"""
        return self.audio_dir / hash_val[:2] / f"{hash_val}.m4a"
    
    def get_transcript_path(self, hash_val: str) -> Path:
        """根据哈希值获取转录文件路径"""
        return self.transcript_dir / hash_val[:2] / f"{hash_val}.json"
    
    def exists_audio(self, hash_val: str) -> bool:
        """检查音频是否已存在"""
        return self.get_audio_path(hash_val).exists()
    
    def exists_transcript(self, hash_val: str) -> bool:
        """检查转录是否已存在"""
        return self.get_transcript_path(hash_val).exists()


class VideoIndexDB:
    """SQLite 索引数据库：轻量级元数据和状态"""
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()
    
    def _init_schema(self):
        """初始化数据库结构"""
        self.conn.executescript("""
            -- 视频元数据表
            CREATE TABLE IF NOT EXISTS videos (
                work_id TEXT PRIMARY KEY,
                bvid TEXT NOT NULL,
                page_index INTEGER NOT NULL DEFAULT 0,
                
                -- 元信息
                title TEXT,
                duration_s INTEGER,
                pubdate INTEGER,
                
                -- 状态机
                status TEXT NOT NULL DEFAULT 'pending',
                source TEXT,  -- 'subtitle' | 'asr' | NULL
                
                -- 内容寻址哈希
                audio_hash TEXT,
                transcript_hash TEXT,
                
                -- 时间戳
                created_at INTEGER NOT NULL DEFAULT (unixepoch()),
                updated_at INTEGER NOT NULL DEFAULT (unixepoch()),
                archived_at INTEGER,
                
                UNIQUE(bvid, page_index),
                CHECK(status IN ('pending', 'meta_ok', 'needs_audio', 'audio_ok', 
                                 'asr_done', 'archived', 'gone'))
            );
            
            CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(status);
            CREATE INDEX IF NOT EXISTS idx_videos_bvid ON videos(bvid);
            
            -- 转录版本历史（支持多版本）
            CREATE TABLE IF NOT EXISTS transcript_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                work_id TEXT NOT NULL REFERENCES videos(work_id),
                version TEXT NOT NULL,
                transcript_hash TEXT NOT NULL,
                model TEXT NOT NULL,
                generated_at INTEGER NOT NULL DEFAULT (unixepoch()),
                
                UNIQUE(work_id, version)
            );
            
            -- 执行历史
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                command TEXT NOT NULL,
                started_at INTEGER NOT NULL,
                finished_at INTEGER NOT NULL,
                exit_code INTEGER NOT NULL,
                records_processed INTEGER DEFAULT 0
            );
            
            -- FTS5 全文搜索
            CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(
                work_id UNINDEXED,
                title,
                transcript_text,
                tokenize='unicode61'
            );
        """)
        self.conn.commit()
    
    def upsert_video(self, work_id: str, **fields) -> None:
        """插入或更新视频记录"""
        fields['work_id'] = work_id
        fields['updated_at'] = fields.get('updated_at', 'unixepoch()')
        
        cols = ', '.join(fields.keys())
        placeholders = ', '.join(['?' if k != 'updated_at' else 'unixepoch()' 
                                   for k in fields.keys()])
        updates = ', '.join([f"{k} = excluded.{k}" for k in fields.keys() 
                             if k != 'work_id'])
        
        sql = f"""
            INSERT INTO videos ({cols})
            VALUES ({placeholders})
            ON CONFLICT(work_id) DO UPDATE SET {updates}
        """
        
        values = [v for k, v in fields.items() if k != 'updated_at']
        self.conn.execute(sql, values)
        self.conn.commit()
    
    def get_video(self, work_id: str) -> Optional[dict]:
        """获取视频记录"""
        row = self.conn.execute(
            "SELECT * FROM videos WHERE work_id = ?", (work_id,)
        ).fetchone()
        return dict(row) if row else None
    
    def get_pending_videos(self, limit: int = 100) -> list[dict]:
        """获取待处理的视频"""
        rows = self.conn.execute("""
            SELECT * FROM videos 
            WHERE status IN ('meta_ok', 'needs_audio', 'audio_ok', 'asr_done')
            ORDER BY duration_s ASC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(row) for row in rows]
    
    def add_transcript_version(self, work_id: str, version: str, 
                               transcript_hash: str, model: str) -> None:
        """添加转录版本"""
        self.conn.execute("""
            INSERT INTO transcript_versions 
            (work_id, version, transcript_hash, model)
            VALUES (?, ?, ?, ?)
        """, (work_id, version, transcript_hash, model))
        self.conn.commit()
    
    def get_latest_transcript(self, work_id: str) -> Optional[dict]:
        """获取最新的转录版本"""
        row = self.conn.execute("""
            SELECT * FROM transcript_versions
            WHERE work_id = ?
            ORDER BY generated_at DESC
            LIMIT 1
        """, (work_id,)).fetchone()
        return dict(row) if row else None
    
    def add_run(self, run_id: str, command: str, 
                started_at: int, finished_at: int, 
                exit_code: int, records_processed: int = 0) -> None:
        """记录执行历史"""
        self.conn.execute("""
            INSERT INTO runs 
            (run_id, command, started_at, finished_at, exit_code, records_processed)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (run_id, command, started_at, finished_at, exit_code, records_processed))
        self.conn.commit()
    
    def update_search_index(self, work_id: str, title: str, text: str) -> None:
        """更新全文搜索索引"""
        # 删除旧记录
        self.conn.execute(
            "DELETE FROM search_fts WHERE work_id = ?", (work_id,)
        )
        # 插入新记录
        self.conn.execute("""
            INSERT INTO search_fts (work_id, title, transcript_text)
            VALUES (?, ?, ?)
        """, (work_id, title, text))
        self.conn.commit()
    
    def search(self, query: str, limit: int = 20) -> list[dict]:
        """全文搜索"""
        rows = self.conn.execute("""
            SELECT work_id, title, 
                   snippet(search_fts, 2, '<b>', '</b>', '...', 32) as snippet
            FROM search_fts
            WHERE search_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (query, limit)).fetchall()
        return [dict(row) for row in rows]


class ArchiveStore:
    """统一的归档存储接口"""
    
    def __init__(self, root: Path):
        self.root = root
        self.cas = ContentAddressedStore(root)
        self.db = VideoIndexDB(root / "index.db")
        self.exports_dir = root / "exports"
    
    def store_video_with_audio(self, work_id: str, bvid: str, 
                                page_index: int, title: str, 
                                duration_s: int, audio_data: bytes) -> str:
        """存储视频+音频"""
        # 1. 存储音频到 CAS
        audio_hash = self.cas.store_audio(audio_data)
        
        # 2. 更新数据库
        self.db.upsert_video(
            work_id=work_id,
            bvid=bvid,
            page_index=page_index,
            title=title,
            duration_s=duration_s,
            audio_hash=audio_hash,
            status='audio_ok'
        )
        
        return audio_hash
    
    def store_transcript(self, work_id: str, segments: list[dict], 
                         model: str = "Fun-ASR-Nano-2512") -> str:
        """存储转录结果"""
        # 1. 存储转录到 CAS
        transcript_hash = self.cas.store_transcript(segments)
        
        # 2. 获取现有视频记录
        video = self.db.get_video(work_id)
        if not video:
            raise ValueError(f"Video {work_id} not found. Store audio first.")
        
        # 3. 更新视频记录
        self.db.conn.execute("""
            UPDATE videos 
            SET transcript_hash = ?, status = ?, updated_at = unixepoch()
            WHERE work_id = ?
        """, (transcript_hash, 'archived', work_id))
        self.db.conn.commit()
        
        # 4. 添加版本记录
        version = f"v1"  # 可以改进为自动递增
        self.db.add_transcript_version(work_id, version, transcript_hash, model)
        
        # 5. 更新搜索索引
        video = self.db.get_video(work_id)
        text = self._segments_to_text(segments)
        self.db.update_search_index(work_id, video['title'], text)
        
        return transcript_hash
    
    def export_transcript(self, work_id: str, format: str = 'srt') -> Path:
        """导出转录为指定格式"""
        video = self.db.get_video(work_id)
        if not video or not video['transcript_hash']:
            raise ValueError(f"No transcript for {work_id}")
        
        # 读取转录 blob
        transcript_path = self.cas.get_transcript_path(video['transcript_hash'])
        segments = json.loads(transcript_path.read_text())
        
        # 生成目标格式
        output_dir = self.exports_dir / "transcripts" / format
        output_dir.mkdir(parents=True, exist_ok=True)
        
        stem = work_id.replace(':', '.')
        output_path = output_dir / f"{stem}.{format}"
        
        if format == 'srt':
            content = self._segments_to_srt(segments)
        elif format == 'txt':
            content = self._segments_to_text(segments)
        elif format == 'md':
            content = self._segments_to_markdown(segments, video)
        else:
            raise ValueError(f"Unsupported format: {format}")
        
        output_path.write_text(content, encoding='utf-8')
        return output_path
    
    def get_audio_path(self, work_id: str) -> Optional[Path]:
        """获取音频文件路径"""
        video = self.db.get_video(work_id)
        if not video or not video['audio_hash']:
            return None
        return self.cas.get_audio_path(video['audio_hash'])
    
    def search(self, query: str, limit: int = 20) -> list[dict]:
        """搜索视频"""
        return self.db.search(query, limit)
    
    def _segments_to_srt(self, segments: list[dict]) -> str:
        """转换为 SRT 格式"""
        lines = []
        for i, seg in enumerate(segments, 1):
            start = self._format_timestamp(seg['start'])
            end = self._format_timestamp(seg['end'])
            text = seg['text'].strip()
            lines.append(f"{i}\n{start} --> {end}\n{text}\n")
        return '\n'.join(lines)
    
    def _segments_to_text(self, segments: list[dict]) -> str:
        """转换为纯文本"""
        return ' '.join(seg['text'].strip() for seg in segments)
    
    def _segments_to_markdown(self, segments: list[dict], video: dict) -> str:
        """转换为 Markdown"""
        lines = [
            f"# {video['title']}",
            f"",
            f"**BV号**: {video['bvid']}",
            f"**时长**: {video['duration_s']}s",
            f"",
            "## 转录内容",
            ""
        ]
        for seg in segments:
            ts = self._format_timestamp(seg['start'])
            lines.append(f"**[{ts}]** {seg['text'].strip()}")
        return '\n'.join(lines)
    
    def _format_timestamp(self, seconds: float) -> str:
        """格式化时间戳"""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ============================================================
# 使用示例
# ============================================================

def example_usage():
    """演示新存储系统的使用"""
    
    # 初始化存储
    archive_root = Path("archive-v2")
    store = ArchiveStore(archive_root)
    
    # 1. 存储视频+音频
    work_id = "BV1xx411c7mD:p0"
    audio_data = b"fake audio content"  # 实际使用时从 Bilibili 下载
    
    audio_hash = store.store_video_with_audio(
        work_id=work_id,
        bvid="BV1xx411c7mD",
        page_index=0,
        title="测试视频",
        duration_s=120,
        audio_data=audio_data
    )
    print(f"✓ 音频已存储: {audio_hash[:8]}...")
    
    # 2. 运行 ASR，存储转录
    segments = [
        {"start": 0.0, "end": 5.0, "text": "大家好，欢迎来到我的频道"},
        {"start": 5.0, "end": 10.0, "text": "今天我们讨论一个有趣的话题"}
    ]
    
    transcript_hash = store.store_transcript(work_id, segments)
    print(f"✓ 转录已存储: {transcript_hash[:8]}...")
    
    # 3. 导出为不同格式
    srt_path = store.export_transcript(work_id, 'srt')
    print(f"✓ SRT 已导出: {srt_path}")
    
    txt_path = store.export_transcript(work_id, 'txt')
    print(f"✓ TXT 已导出: {txt_path}")
    
    # 4. 搜索
    results = store.search("欢迎")
    print(f"✓ 搜索结果: {len(results)} 条")
    for r in results:
        print(f"  - {r['work_id']}: {r['title']}")
    
    # 5. 获取音频路径（用于重新处理）
    audio_path = store.get_audio_path(work_id)
    print(f"✓ 音频路径: {audio_path}")
    print(f"  音频存在: {audio_path.exists()}")


if __name__ == "__main__":
    example_usage()
