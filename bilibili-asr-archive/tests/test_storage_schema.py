"""Offline contract tests for the normalized SQLite storage schema."""

from __future__ import annotations

import os
import sqlite3

import pytest

from bili_asr.storage import duration_to_ms, normalize_page_index, open_database


BASE_TABLES = {
    "bilibili_users",
    "videos",
    "video_parts",
    "ingestion_runs",
    "ingestion_cursors",
    "ingestion_pages",
    "ingestion_discoveries",
    "audio_objects",
    "part_audio_objects",
    "asr_models",
    "transcripts",
    "transcript_segments",
}
VIEWS = {"v_video_parts", "v_ingestion_run_stats", "v_pending_metadata"}


def _table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
    )
    return {row[0] for row in rows}


def _insert_user_video_part(connection: sqlite3.Connection) -> int:
    connection.execute(
        "INSERT INTO bilibili_users(mid, display_name, created_at, updated_at) "
        "VALUES (?, ?, ?, ?)",
        (23191782, "未明子", 100, 100),
    )
    connection.execute(
        "INSERT INTO videos(bvid, aid, mid, title, pubdate, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("BV1TEST", 1001, 23191782, "视频", 1_700_000_000, 101, 101),
    )
    cursor = connection.execute(
        """
        INSERT INTO video_parts(
            bvid, page_index, cid, title, duration_ms, processing_status,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("BV1TEST", 0, 2001, "第一段", 1_234, "discovered", 102, 102),
    )
    return int(cursor.lastrowid)


def test_fresh_database_initializes_archive_root_and_is_idempotent(tmp_root):
    connection = open_database(tmp_root)
    try:
        assert os.path.isfile(os.path.join(tmp_root, "archive.db"))
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.isolation_level == "DEFERRED"
        assert BASE_TABLES | VIEWS <= _table_names(connection)

        _insert_user_video_part(connection)
        connection.commit()
    finally:
        connection.close()

    reopened = open_database(os.path.join(tmp_root, "archive.db"))
    try:
        assert reopened.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0] == 1
        assert reopened.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        reopened.close()


def test_page_and_duration_normalization_uses_contract_formulas():
    assert duration_to_ms(12.3459) == 12_345
    assert duration_to_ms(0) == 0
    assert normalize_page_index(1) == 0
    assert normalize_page_index(3) == 2
    with pytest.raises(ValueError):
        normalize_page_index(0)
    with pytest.raises(ValueError):
        duration_to_ms(-0.1)


def test_foreign_keys_reject_orphans_and_use_restrict(tmp_root):
    connection = open_database(tmp_root)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO videos(bvid, mid, title, pubdate, created_at, updated_at) "
                "VALUES ('BVORPHAN', 999, 'orphan', 1, 1, 1)"
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO video_parts(
                    bvid, page_index, cid, title, duration_ms,
                    processing_status, created_at, updated_at
                ) VALUES ('BVORPHAN', 0, 1, 'orphan', 1, 'discovered', 1, 1)
                """
            )

        _insert_user_video_part(connection)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM bilibili_users WHERE mid = 23191782")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM videos WHERE bvid = 'BV1TEST'")

        for table in BASE_TABLES:
            for row in connection.execute(f"PRAGMA foreign_key_list({table})"):
                assert row[6].upper() == "RESTRICT"
    finally:
        connection.close()


def test_duplicate_candidate_keys_are_rejected(tmp_root):
    connection = open_database(tmp_root)
    try:
        _insert_user_video_part(connection)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO bilibili_users VALUES (23191782, 'same', 1, 1)"
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO videos VALUES ('BV1TEST', 1002, 23191782, 'same', 1, 1, 1)"
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO videos VALUES ('BV2TEST', 1001, 23191782, 'same', 1, 1, 1)"
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO video_parts(
                    bvid, page_index, cid, title, duration_ms,
                    processing_status, created_at, updated_at
                ) VALUES ('BV1TEST', 0, 2, 'duplicate', 10, 'gone', 1, 1)
                """
            )

        connection.execute(
            """
            INSERT INTO audio_objects(
                audio_id, sha256, byte_size, format, duration_ms, storage_key, created_at
            ) VALUES (1, 'hash-1', 1, 'm4a', 1, 'audio/1', 1)
            """
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO audio_objects(
                    audio_id, sha256, byte_size, format, duration_ms, storage_key, created_at
                ) VALUES (2, 'hash-1', 1, 'm4a', 1, 'audio/2', 1)
                """
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO audio_objects(
                    audio_id, sha256, byte_size, format, duration_ms, storage_key, created_at
                ) VALUES (2, 'hash-2', 1, 'm4a', 1, 'audio/1', 1)
                """
            )
    finally:
        connection.close()


def test_views_compute_work_id_and_keep_derived_values_out_of_base_tables(tmp_root):
    connection = open_database(tmp_root)
    try:
        part_id = _insert_user_video_part(connection)
        row = connection.execute(
            "SELECT * FROM v_video_parts WHERE video_part_id = ?", (part_id,)
        ).fetchone()
        assert row["work_id"] == "BV1TEST:p0"
        assert row["user_name"] == "未明子"
        assert row["video_title"] == "视频"

        for table in BASE_TABLES:
            columns = {
                item[1] for item in connection.execute(f"PRAGMA table_info({table})")
            }
            assert "work_id" not in columns
            assert "part_count" not in columns
            assert "video_count" not in columns
            assert "run_count" not in columns

        pending = connection.execute("SELECT work_id FROM v_pending_metadata").fetchall()
        assert [item[0] for item in pending] == ["BV1TEST:p0"]
    finally:
        connection.close()


def test_schema_constraints_cover_status_and_non_negative_values(tmp_root):
    connection = open_database(tmp_root)
    try:
        _insert_user_video_part(connection)
        invalid_statements = [
            "UPDATE video_parts SET page_index = -1",
            "UPDATE video_parts SET cid = 0",
            "UPDATE video_parts SET duration_ms = 0",
            "UPDATE video_parts SET processing_status = 'pending'",
            "INSERT INTO ingestion_runs VALUES ('run', 23191782, 'other', '1', 1, NULL, 1, NULL, 'running')",
            "INSERT INTO ingestion_runs VALUES ('run', 23191782, 'bilibili-api-python', '1', 0, NULL, 1, NULL, 'running')",
            "INSERT INTO ingestion_cursors VALUES (23191782, 0, NULL, 'ready', NULL, 1)",
            "INSERT INTO ingestion_pages VALUES ('run', 0, 'ok', NULL, 1, 1)",
            "INSERT INTO ingestion_pages VALUES ('run', 1, 'unknown', NULL, 1, 1)",
            "INSERT INTO audio_objects VALUES (1, 'hash', -1, 'm4a', 1, 'audio', 1)",
        ]
        for statement in invalid_statements:
            with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError)):
                connection.execute(statement)
    finally:
        connection.close()


def test_transaction_order_parents_before_children(tmp_root):
    connection = open_database(tmp_root)
    try:
        with connection:
            connection.execute(
                "INSERT INTO bilibili_users VALUES (7, 'operator', 1, 1)"
            )
            connection.execute(
                """
                INSERT INTO ingestion_runs VALUES (
                    'run-1', 7, 'bilibili-api-python', '1.0', 1, 2,
                    1, NULL, 'running'
                )
                """
            )
            connection.execute(
                "INSERT INTO videos VALUES ('BV7', 7, 7, 'title', 1, 1, 1)"
            )
            connection.execute(
                """
                INSERT INTO video_parts(
                    bvid, page_index, cid, title, duration_ms,
                    processing_status, created_at, updated_at
                ) VALUES ('BV7', 0, 70, 'part', 1000, 'discovered', 1, 1)
                """
            )
            connection.execute(
                "INSERT INTO ingestion_discoveries VALUES ('run-1', 1, 'BV7', 0, 1)"
            )
            connection.execute(
                "INSERT INTO ingestion_cursors VALUES (7, 2, 1, 'ready', NULL, 1)"
            )
            connection.execute(
                "INSERT INTO ingestion_pages VALUES ('run-1', 1, 'ok', NULL, 1, 1)"
            )

        stats = connection.execute(
            "SELECT page_count, video_count FROM v_ingestion_run_stats "
            "WHERE run_id = 'run-1'"
        ).fetchone()
        assert tuple(stats) == (1, 1)
    finally:
        connection.close()
