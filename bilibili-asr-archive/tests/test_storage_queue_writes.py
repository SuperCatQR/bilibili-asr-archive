"""Offline tests for the media queue acquisition write path."""

from __future__ import annotations

import pytest

from bili_asr.storage import MediaQueueRepository, open_database


def _insert_user_video_part(connection, *, bvid: str = "BV1TEST", page_index: int = 0) -> int:
    connection.execute(
        "INSERT INTO bilibili_users(mid, display_name, created_at, updated_at) "
        "VALUES (?, ?, ?, ?)",
        (23191782, "未明子", 100, 100),
    )
    connection.execute(
        "INSERT INTO videos(bvid, aid, mid, title, pubdate, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (bvid, 1001, 23191782, "视频", 1_700_000_000, 101, 101),
    )
    cursor = connection.execute(
        """
        INSERT INTO video_parts(
            bvid, page_index, cid, title, duration_ms, processing_status,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (bvid, page_index, 2001, "第一段", 1_234, "discovered", 102, 102),
    )
    return int(cursor.lastrowid)


def test_mark_audio_acquired_inserts_reuses_and_rejects_unknown_parts(tmp_root):
    connection = open_database(tmp_root)
    try:
        part_id = _insert_user_video_part(connection)
        repository = MediaQueueRepository(connection)

        audio_id = repository.mark_audio_acquired(
            bvid="BV1TEST",
            page_index=0,
            audio_path="audio/BV1TEST-p0.m4a",
            sha256="hash-1",
            byte_size=4_096,
            format="m4a",
            duration_ms=1_234,
            acquisition_source="download",
            acquired_at=500,
        )

        objects = connection.execute(
            "SELECT audio_id, sha256, byte_size, format, duration_ms, storage_key, "
            "created_at FROM audio_objects"
        ).fetchall()
        assert len(objects) == 1
        assert objects[0]["audio_id"] == audio_id
        assert objects[0]["sha256"] == "hash-1"
        assert objects[0]["storage_key"] == "audio/BV1TEST-p0.m4a"
        assert objects[0]["created_at"] == 500

        links = connection.execute(
            "SELECT video_part_id, audio_id, acquired_at, acquisition_source "
            "FROM part_audio_objects"
        ).fetchall()
        assert len(links) == 1
        assert links[0]["video_part_id"] == part_id
        assert links[0]["audio_id"] == audio_id
        assert links[0]["acquired_at"] == 500
        assert links[0]["acquisition_source"] == "download"

        # Same sha256 (different path) reuses the object and the link.
        again = repository.mark_audio_acquired(
            bvid="BV1TEST",
            page_index=0,
            audio_path="audio/BV1TEST-p0-renamed.m4a",
            sha256="hash-1",
            byte_size=4_096,
            format="m4a",
            duration_ms=1_234,
            acquisition_source="cache_hit",
            acquired_at=900,
        )

        assert again == audio_id
        assert (
            connection.execute("SELECT COUNT(*) FROM audio_objects").fetchone()[0] == 1
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM part_audio_objects").fetchone()[0]
            == 1
        )

        with pytest.raises(ValueError):
            repository.mark_audio_acquired(
                bvid="BVUNKNOWN",
                page_index=0,
                audio_path="audio/unknown.m4a",
                sha256="hash-2",
                byte_size=1,
                format="m4a",
                duration_ms=1,
                acquisition_source="download",
                acquired_at=1_000,
            )
    finally:
        connection.close()
