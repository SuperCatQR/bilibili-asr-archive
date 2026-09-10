"""Offline contract tests for the normalized SQLite storage schema."""

from __future__ import annotations

from importlib import resources
import os
from pathlib import Path
import sqlite3
import tomllib

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
EXPECTED_TABLE_COLUMNS = {
    "bilibili_users": ["mid", "display_name", "created_at", "updated_at"],
    "videos": [
        "bvid",
        "aid",
        "mid",
        "title",
        "pubdate",
        "created_at",
        "updated_at",
    ],
    "video_parts": [
        "video_part_id",
        "bvid",
        "page_index",
        "cid",
        "title",
        "duration_ms",
        "processing_status",
        "created_at",
        "updated_at",
    ],
    "ingestion_runs": [
        "run_id",
        "mid",
        "source_package",
        "source_version",
        "requested_start_page",
        "requested_page_limit",
        "started_at",
        "finished_at",
        "outcome",
    ],
    "ingestion_cursors": [
        "mid",
        "next_page",
        "observed_total",
        "state",
        "last_error_code",
        "updated_at",
    ],
    "ingestion_pages": [
        "run_id",
        "page_number",
        "outcome",
        "error_code",
        "started_at",
        "finished_at",
    ],
    "ingestion_discoveries": [
        "run_id",
        "page_number",
        "bvid",
        "source_position",
        "discovered_at",
    ],
    "audio_objects": [
        "audio_id",
        "sha256",
        "byte_size",
        "format",
        "duration_ms",
        "storage_key",
        "created_at",
    ],
    "part_audio_objects": [
        "video_part_id",
        "audio_id",
        "acquired_at",
        "acquisition_source",
    ],
    "asr_models": ["model_id", "model_name", "revision", "created_at"],
    "transcripts": [
        "transcript_id",
        "video_part_id",
        "source_kind",
        "model_id",
        "version",
        "created_at",
    ],
    "transcript_segments": ["transcript_id", "ordinal", "start_ms", "end_ms", "text"],
}
EXPECTED_FOREIGN_KEYS = {
    "videos": (("mid", "bilibili_users", "mid"),),
    "video_parts": (("bvid", "videos", "bvid"),),
    "ingestion_runs": (("mid", "bilibili_users", "mid"),),
    "ingestion_cursors": (("mid", "bilibili_users", "mid"),),
    "ingestion_pages": (("run_id", "ingestion_runs", "run_id"),),
    "ingestion_discoveries": (
        ("run_id", "ingestion_runs", "run_id"),
        ("bvid", "videos", "bvid"),
    ),
    "part_audio_objects": (
        ("video_part_id", "video_parts", "video_part_id"),
        ("audio_id", "audio_objects", "audio_id"),
    ),
    "transcripts": (
        ("video_part_id", "video_parts", "video_part_id"),
        ("model_id", "asr_models", "model_id"),
    ),
    "transcript_segments": (("transcript_id", "transcripts", "transcript_id"),),
}
EXPECTED_UNIQUE_CONSTRAINTS = {
    "videos": (("aid",),),
    "video_parts": (("bvid", "page_index"),),
    "audio_objects": (("sha256",), ("storage_key",)),
    "asr_models": (("model_name", "revision"),),
    "transcripts": (("video_part_id", "source_kind", "version"),),
}
EXPECTED_PRIMARY_KEY_INDEXES = {
    "videos": (("bvid",),),
    "ingestion_runs": (("run_id",),),
    "ingestion_pages": (("run_id", "page_number"),),
    "ingestion_discoveries": (("run_id", "page_number", "bvid"),),
    "part_audio_objects": (("video_part_id", "audio_id"),),
    "transcript_segments": (("transcript_id", "ordinal"),),
}
EXPECTED_CHECK_ENUMERATIONS = {
    "video_parts": (
        "processing_status IN ('discovered', 'metadata_collected', 'gone')",
    ),
    "ingestion_runs": (
        "source_package = 'bilibili-api-python'",
        "outcome IN ('running', 'complete', 'limited', 'risk_interrupted', 'failed')",
    ),
    "ingestion_cursors": (
        "state IN ('ready', 'complete', 'limited', 'risk_interrupted')",
    ),
    "ingestion_pages": ("outcome IN ('ok', 'empty', 'risk_interrupted', 'failed')",),
    "transcripts": ("source_kind IN ('subtitle-ai', 'subtitle-cc', 'asr-local')",),
}
EXPECTED_VIEW_WORK_ID_EXPRESSION = "vp.bvid || ':p' || vp.page_index AS work_id"


def test_schema_sql_is_declared_and_read_as_package_resource():
    project_root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads(
        (project_root / "pyproject.toml").read_text(encoding="utf-8")
    )
    package_data = pyproject["tool"]["setuptools"]["package-data"]
    assert "schema.sql" in package_data["bili_asr.storage"]

    schema_resource = resources.files("bili_asr.storage").joinpath("schema.sql")
    assert schema_resource.is_file()
    assert "CREATE TABLE IF NOT EXISTS videos" in schema_resource.read_text(
        encoding="utf-8"
    )


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

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO ingestion_pages VALUES ('ghost-run', 1, 'ok', NULL, 1, 1)"
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO ingestion_discoveries "
                "VALUES ('ghost-run', 1, 'BVORPHAN', 0, 1)"
            )

        _insert_user_video_part(connection)
        connection.execute(
            "INSERT INTO ingestion_runs VALUES "
            "('run-1', 23191782, 'bilibili-api-python', '1.0', 1, NULL, 1, NULL, 'running')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO ingestion_discoveries "
                "VALUES ('run-1', 1, 'BVUNKNOWN', 0, 1)"
            )
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
            f"INSERT INTO ingestion_cursors VALUES "
            f"(23191782, 2, NULL, 'ready', '{'y' * 65}', 1)",
            f"INSERT INTO ingestion_pages VALUES ('run', 3, 'failed', '{'x' * 65}', 1, 1)",
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


def test_schema_inspection_matches_the_declared_contract(tmp_root):
    connection = open_database(tmp_root)
    try:
        assert _table_names(connection) == BASE_TABLES | VIEWS

        for table in BASE_TABLES:
            columns = [
                row["name"] for row in connection.execute(f"PRAGMA table_info({table})")
            ]
            assert columns == EXPECTED_TABLE_COLUMNS[table]
            assert "work_id" not in columns

            foreign_keys = {
                (row["from"], row["table"], row["to"])
                for row in connection.execute(f"PRAGMA foreign_key_list({table})")
            }
            assert foreign_keys == set(EXPECTED_FOREIGN_KEYS.get(table, ()))
            for row in connection.execute(f"PRAGMA foreign_key_list({table})"):
                assert row["on_delete"] == "RESTRICT"

            unique_constraints = set()
            primary_key_indexes = set()
            for index in connection.execute(f"PRAGMA index_list({table})"):
                indexed_columns = tuple(
                    info["name"]
                    for info in connection.execute(f"PRAGMA index_info({index['name']})")
                )
                if index["origin"] == "u":
                    unique_constraints.add(indexed_columns)
                elif index["origin"] == "pk":
                    primary_key_indexes.add(indexed_columns)
            assert unique_constraints == set(
                EXPECTED_UNIQUE_CONSTRAINTS.get(table, ())
            )
            assert primary_key_indexes == set(
                EXPECTED_PRIMARY_KEY_INDEXES.get(table, ())
            )

        for table, fragments in EXPECTED_CHECK_ENUMERATIONS.items():
            ddl_row = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
            normalized_ddl = " ".join(ddl_row[0].split())
            for fragment in fragments:
                assert fragment in normalized_ddl

        for view in VIEWS:
            ddl_row = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'view' AND name = ?",
                (view,),
            ).fetchone()
            normalized_ddl = " ".join(ddl_row[0].split())
            if view in {"v_video_parts", "v_pending_metadata"}:
                assert EXPECTED_VIEW_WORK_ID_EXPRESSION in normalized_ddl
    finally:
        connection.close()


def test_views_compute_derived_values_across_users_videos_and_runs(tmp_root):
    connection = open_database(tmp_root)
    try:
        connection.executescript(
            """
            INSERT INTO bilibili_users VALUES (23191782, '未明子', 1, 1);
            INSERT INTO bilibili_users VALUES (42, '第二位用户', 1, 1);
            INSERT INTO videos VALUES
                ('BV1SINGLE', 1001, 23191782, '单集视频', 1700000000, 1, 1);
            INSERT INTO videos VALUES
                ('BV1MULTI', 1002, 42, '多集视频', 1700000001, 1, 1);
            INSERT INTO videos VALUES
                ('BV1GONE', NULL, 42, '已下架视频', 1700000002, 1, 1);
            INSERT INTO video_parts(
                bvid, page_index, cid, title, duration_ms, processing_status,
                created_at, updated_at
            ) VALUES ('BV1SINGLE', 0, 2001, '第一集', 1000, 'discovered', 1, 1);
            INSERT INTO video_parts(
                bvid, page_index, cid, title, duration_ms, processing_status,
                created_at, updated_at
            ) VALUES ('BV1MULTI', 0, 3001, '上篇', 2000, 'discovered', 1, 1);
            INSERT INTO video_parts(
                bvid, page_index, cid, title, duration_ms, processing_status,
                created_at, updated_at
            ) VALUES ('BV1MULTI', 1, 3002, '下篇', 3000, 'metadata_collected', 1, 1);
            INSERT INTO video_parts(
                bvid, page_index, cid, title, duration_ms, processing_status,
                created_at, updated_at
            ) VALUES ('BV1GONE', 0, 4001, '残片', 4000, 'gone', 1, 1);
            INSERT INTO ingestion_runs VALUES
                ('run-1', 23191782, 'bilibili-api-python', '1.0', 1, NULL, 1, NULL, 'running');
            INSERT INTO ingestion_runs VALUES
                ('run-2', 42, 'bilibili-api-python', '1.0', 1, NULL, 1, NULL, 'running');
            INSERT INTO ingestion_pages VALUES ('run-1', 1, 'ok', NULL, 1, 2);
            INSERT INTO ingestion_pages VALUES ('run-1', 2, 'empty', NULL, 3, 4);
            INSERT INTO ingestion_discoveries VALUES ('run-1', 1, 'BV1SINGLE', 0, 5);
            INSERT INTO ingestion_discoveries VALUES ('run-1', 2, 'BV1SINGLE', 0, 6);
            INSERT INTO ingestion_discoveries VALUES ('run-1', 2, 'BV1MULTI', 1, 6);
            """
        )

        part_rows = connection.execute(
            "SELECT work_id, user_name, video_title, page_index, cid, part_title, "
            "processing_status FROM v_video_parts ORDER BY work_id"
        ).fetchall()
        assert [row["work_id"] for row in part_rows] == [
            "BV1GONE:p0",
            "BV1MULTI:p0",
            "BV1MULTI:p1",
            "BV1SINGLE:p0",
        ]
        single = part_rows[3]
        assert single["user_name"] == "未明子"
        assert single["video_title"] == "单集视频"
        multi = part_rows[2]
        assert multi["user_name"] == "第二位用户"
        assert multi["part_title"] == "下篇"
        assert multi["processing_status"] == "metadata_collected"

        stats = {
            row["run_id"]: (row["page_count"], row["video_count"])
            for row in connection.execute("SELECT * FROM v_ingestion_run_stats")
        }
        # run-1 has three discovery rows but only two distinct videos; run-2
        # has neither pages nor discoveries and still reports zero counts.
        assert stats == {"run-1": (2, 2), "run-2": (0, 0)}

        pending = [
            row["work_id"]
            for row in connection.execute(
                "SELECT work_id FROM v_pending_metadata ORDER BY work_id"
            )
        ]
        assert pending == ["BV1MULTI:p0", "BV1SINGLE:p0"]
    finally:
        connection.close()
