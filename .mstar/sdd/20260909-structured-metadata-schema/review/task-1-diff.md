# Task 1 Diff

Base: `c98f1405bded9bfd4a322c2226de7d85e4939e6e`
Head: `5f22fc6e81371f79cd4f0660cc79eb7f8cae9bfa`

```diff
diff --git a/bilibili-asr-archive/pyproject.toml b/bilibili-asr-archive/pyproject.toml
index 4902e16..e296835 100644
--- a/bilibili-asr-archive/pyproject.toml
+++ b/bilibili-asr-archive/pyproject.toml
@@ -29,5 +29,8 @@ asr = [
 [tool.setuptools.packages.find]
 where = ["src"]
 
+[tool.setuptools.package-data]
+"bili_asr.storage" = ["schema.sql"]
+
 [tool.pytest.ini_options]
 testpaths = ["tests"]
diff --git a/bilibili-asr-archive/src/bili_asr/storage/__init__.py b/bilibili-asr-archive/src/bili_asr/storage/__init__.py
new file mode 100644
index 0000000..034e017
--- /dev/null
+++ b/bilibili-asr-archive/src/bili_asr/storage/__init__.py
@@ -0,0 +1,17 @@
+"""Normalized SQLite storage for Bilibili metadata."""
+
+from .database import (
+    DatabaseConnection,
+    duration_to_ms,
+    initialize_schema,
+    normalize_page_index,
+    open_database,
+)
+
+__all__ = [
+    "DatabaseConnection",
+    "duration_to_ms",
+    "initialize_schema",
+    "normalize_page_index",
+    "open_database",
+]
diff --git a/bilibili-asr-archive/src/bili_asr/storage/database.py b/bilibili-asr-archive/src/bili_asr/storage/database.py
new file mode 100644
index 0000000..27df44a
--- /dev/null
+++ b/bilibili-asr-archive/src/bili_asr/storage/database.py
@@ -0,0 +1,93 @@
+"""SQLite bootstrap for normalized Bilibili metadata storage."""
+
+from __future__ import annotations
+
+from importlib import resources
+import math
+import os
+from pathlib import Path
+import sqlite3
+from typing import TypeAlias
+
+
+DatabaseConnection: TypeAlias = sqlite3.Connection
+_ARCHIVE_DATABASE_NAME = "archive.db"
+_DATABASE_SUFFIXES = frozenset({".db", ".sqlite", ".sqlite3"})
+_SCHEMA_RESOURCE = resources.files(__package__).joinpath("schema.sql")
+
+
+def duration_to_ms(seconds: int | float) -> int:
+    """Convert a non-negative duration in seconds to floored milliseconds."""
+    if isinstance(seconds, bool):
+        raise TypeError("duration must be numeric")
+    try:
+        value = float(seconds)
+    except (TypeError, ValueError) as exc:
+        raise TypeError("duration must be numeric") from exc
+    if not math.isfinite(value) or value < 0:
+        raise ValueError("duration must be finite and non-negative")
+    return math.floor(value * 1000)
+
+
+def normalize_page_index(page_number: int) -> int:
+    """Convert a one-based Bilibili page number to a zero-based part index."""
+    if isinstance(page_number, bool) or not isinstance(page_number, int):
+        raise TypeError("page number must be an integer")
+    if page_number < 1:
+        raise ValueError("page number must be at least 1")
+    return page_number - 1
+
+
+def _resolve_database_path(path: str | os.PathLike[str]) -> str | os.PathLike[str]:
+    """Accept either an archive root or an explicit SQLite database path."""
+    value = os.fspath(path)
+    if value in {":memory:"} or (isinstance(value, str) and value.startswith("file:")):
+        return value
+
+    candidate = Path(value)
+    if candidate.is_dir() or (
+        not candidate.exists() and candidate.suffix.lower() not in _DATABASE_SUFFIXES
+    ):
+        candidate.mkdir(parents=True, exist_ok=True)
+        return candidate / _ARCHIVE_DATABASE_NAME
+    candidate.parent.mkdir(parents=True, exist_ok=True)
+    return candidate
+
+
+def initialize_schema(connection: sqlite3.Connection) -> sqlite3.Connection:
+    """Initialize ``connection`` from the checked-in schema, idempotently."""
+    connection.execute("PRAGMA foreign_keys = ON")
+    if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
+        raise sqlite3.DatabaseError("SQLite foreign-key enforcement could not be enabled")
+    connection.executescript(_SCHEMA_RESOURCE.read_text(encoding="utf-8"))
+    connection.commit()
+    return connection
+
+
+def open_database(path: str | os.PathLike[str]) -> DatabaseConnection:
+    """Open and initialize ``archive.db`` below an archive root.
+
+    Existing directories are interpreted as archive roots. Paths ending in a
+    normal SQLite suffix (``.db``, ``.sqlite``, or ``.sqlite3``) are treated as
+    explicit database files, which is useful for tests and callers with a
+    custom filename. Connections use an explicit deferred transaction mode;
+    callers can use ``with connection:`` for atomic write groups.
+    """
+    database_path = _resolve_database_path(path)
+    connection = sqlite3.connect(database_path, isolation_level="DEFERRED")
+    connection.row_factory = sqlite3.Row
+    try:
+        initialize_schema(connection)
+    except BaseException:
+        connection.close()
+        raise
+    return connection
+
+
+__all__ = [
+    "DatabaseConnection",
+    "duration_to_ms",
+    "initialize_schema",
+    "normalize_page_index",
+    "open_database",
+]
diff --git a/bilibili-asr-archive/src/bili_asr/storage/schema.sql b/bilibili-asr-archive/src/bili_asr/storage/schema.sql
new file mode 100644
index 0000000..d83e669
--- /dev/null
+++ b/bilibili-asr-archive/src/bili_asr/storage/schema.sql
@@ -0,0 +1,183 @@
+PRAGMA foreign_keys = ON;
+
+CREATE TABLE IF NOT EXISTS bilibili_users (
+    mid INTEGER PRIMARY KEY,
+    display_name TEXT NOT NULL,
+    created_at INTEGER NOT NULL,
+    updated_at INTEGER NOT NULL
+);
+
+CREATE TABLE IF NOT EXISTS videos (
+    bvid TEXT PRIMARY KEY,
+    aid INTEGER UNIQUE,
+    mid INTEGER NOT NULL,
+    title TEXT NOT NULL,
+    pubdate INTEGER NOT NULL,
+    created_at INTEGER NOT NULL,
+    updated_at INTEGER NOT NULL,
+    FOREIGN KEY (mid) REFERENCES bilibili_users(mid) ON DELETE RESTRICT
+);
+
+CREATE TABLE IF NOT EXISTS video_parts (
+    video_part_id INTEGER PRIMARY KEY,
+    bvid TEXT NOT NULL,
+    page_index INTEGER NOT NULL CHECK (page_index >= 0),
+    cid INTEGER NOT NULL CHECK (cid > 0),
+    title TEXT NOT NULL,
+    duration_ms INTEGER NOT NULL CHECK (duration_ms > 0),
+    processing_status TEXT NOT NULL CHECK (
+        processing_status IN ('discovered', 'metadata_collected', 'gone')
+    ),
+    created_at INTEGER NOT NULL,
+    updated_at INTEGER NOT NULL,
+    UNIQUE (bvid, page_index),
+    FOREIGN KEY (bvid) REFERENCES videos(bvid) ON DELETE RESTRICT
+);
+
+CREATE TABLE IF NOT EXISTS ingestion_runs (
+    run_id TEXT PRIMARY KEY,
+    mid INTEGER NOT NULL,
+    source_package TEXT NOT NULL CHECK (source_package = 'bilibili-api-python'),
+    source_version TEXT NOT NULL,
+    requested_start_page INTEGER NOT NULL CHECK (requested_start_page >= 1),
+    requested_page_limit INTEGER CHECK (
+        requested_page_limit IS NULL OR requested_page_limit > 0
+    ),
+    started_at INTEGER NOT NULL,
+    finished_at INTEGER,
+    outcome TEXT NOT NULL CHECK (
+        outcome IN ('running', 'complete', 'limited', 'risk_interrupted', 'failed')
+    ),
+    FOREIGN KEY (mid) REFERENCES bilibili_users(mid) ON DELETE RESTRICT
+);
+
+CREATE TABLE IF NOT EXISTS ingestion_cursors (
+    mid INTEGER PRIMARY KEY,
+    next_page INTEGER NOT NULL CHECK (next_page >= 1),
+    observed_total INTEGER CHECK (observed_total IS NULL OR observed_total >= 0),
+    state TEXT NOT NULL CHECK (
+        state IN ('ready', 'complete', 'limited', 'risk_interrupted')
+    ),
+    last_error_code TEXT CHECK (last_error_code IS NULL OR length(last_error_code) <= 64),
+    updated_at INTEGER NOT NULL,
+    FOREIGN KEY (mid) REFERENCES bilibili_users(mid) ON DELETE RESTRICT
+);
+
+CREATE TABLE IF NOT EXISTS ingestion_pages (
+    run_id TEXT NOT NULL,
+    page_number INTEGER NOT NULL CHECK (page_number >= 1),
+    outcome TEXT NOT NULL CHECK (
+        outcome IN ('ok', 'empty', 'risk_interrupted', 'failed')
+    ),
+    error_code TEXT CHECK (error_code IS NULL OR length(error_code) <= 64),
+    started_at INTEGER NOT NULL,
+    finished_at INTEGER NOT NULL,
+    PRIMARY KEY (run_id, page_number),
+    FOREIGN KEY (run_id) REFERENCES ingestion_runs(run_id) ON DELETE RESTRICT
+);
+
+CREATE TABLE IF NOT EXISTS ingestion_discoveries (
+    run_id TEXT NOT NULL,
+    page_number INTEGER NOT NULL CHECK (page_number >= 1),
+    bvid TEXT NOT NULL,
+    source_position INTEGER CHECK (source_position IS NULL OR source_position >= 0),
+    discovered_at INTEGER NOT NULL,
+    PRIMARY KEY (run_id, page_number, bvid),
+    FOREIGN KEY (run_id) REFERENCES ingestion_runs(run_id) ON DELETE RESTRICT,
+    FOREIGN KEY (bvid) REFERENCES videos(bvid) ON DELETE RESTRICT
+);
+
+-- Reserved structured media boundary. These tables are intentionally empty in
+-- the metadata plan; media bytes remain external objects referenced by key.
+CREATE TABLE IF NOT EXISTS audio_objects (
+    audio_id INTEGER PRIMARY KEY,
+    sha256 TEXT NOT NULL UNIQUE,
+    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
+    format TEXT NOT NULL,
+    duration_ms INTEGER NOT NULL CHECK (duration_ms >= 0),
+    storage_key TEXT NOT NULL UNIQUE,
+    created_at INTEGER NOT NULL
+);
+
+CREATE TABLE IF NOT EXISTS part_audio_objects (
+    video_part_id INTEGER NOT NULL,
+    audio_id INTEGER NOT NULL,
+    acquired_at INTEGER NOT NULL,
+    acquisition_source TEXT NOT NULL,
+    PRIMARY KEY (video_part_id, audio_id),
+    FOREIGN KEY (video_part_id) REFERENCES video_parts(video_part_id) ON DELETE RESTRICT,
+    FOREIGN KEY (audio_id) REFERENCES audio_objects(audio_id) ON DELETE RESTRICT
+);
+
+CREATE TABLE IF NOT EXISTS asr_models (
+    model_id INTEGER PRIMARY KEY,
+    model_name TEXT NOT NULL,
+    revision TEXT NOT NULL,
+    created_at INTEGER NOT NULL,
+    UNIQUE (model_name, revision)
+);
+
+CREATE TABLE IF NOT EXISTS transcripts (
+    transcript_id INTEGER PRIMARY KEY,
+    video_part_id INTEGER NOT NULL,
+    source_kind TEXT NOT NULL CHECK (
+        source_kind IN ('subtitle-ai', 'subtitle-cc', 'asr-local')
+    ),
+    model_id INTEGER,
+    version INTEGER NOT NULL CHECK (version > 0),
+    created_at INTEGER NOT NULL,
+    UNIQUE (video_part_id, source_kind, version),
+    FOREIGN KEY (video_part_id) REFERENCES video_parts(video_part_id) ON DELETE RESTRICT,
+    FOREIGN KEY (model_id) REFERENCES asr_models(model_id) ON DELETE RESTRICT
+);
+
+CREATE TABLE IF NOT EXISTS transcript_segments (
+    transcript_id INTEGER NOT NULL,
+    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
+    start_ms INTEGER NOT NULL CHECK (start_ms >= 0),
+    end_ms INTEGER NOT NULL CHECK (end_ms > start_ms),
+    text TEXT NOT NULL,
+    PRIMARY KEY (transcript_id, ordinal),
+    FOREIGN KEY (transcript_id) REFERENCES transcripts(transcript_id) ON DELETE RESTRICT
+);
+
+CREATE VIEW IF NOT EXISTS v_video_parts AS
+SELECT
+    vp.video_part_id,
+    vp.bvid || ':p' || vp.page_index AS work_id,
+    u.display_name AS user_name,
+    v.title AS video_title,
+    vp.page_index,
+    vp.cid,
+    vp.title AS part_title,
+    vp.duration_ms,
+    vp.processing_status,
+    vp.created_at,
+    vp.updated_at
+FROM video_parts AS vp
+JOIN videos AS v ON vp.bvid = v.bvid
+JOIN bilibili_users AS u ON v.mid = u.mid;
+
+CREATE VIEW IF NOT EXISTS v_ingestion_run_stats AS
+SELECT
+    ir.run_id,
+    ir.mid,
+    ir.started_at,
+    ir.finished_at,
+    ir.outcome,
+    COUNT(DISTINCT ip.page_number) AS page_count,
+    COUNT(DISTINCT id.bvid) AS video_count
+FROM ingestion_runs AS ir
+LEFT JOIN ingestion_pages AS ip ON ir.run_id = ip.run_id
+LEFT JOIN ingestion_discoveries AS id ON ir.run_id = id.run_id
+GROUP BY ir.run_id;
+
+CREATE VIEW IF NOT EXISTS v_pending_metadata AS
+SELECT
+    vp.video_part_id,
+    vp.bvid || ':p' || vp.page_index AS work_id,
+    vp.bvid,
+    vp.page_index,
+    vp.processing_status
+FROM video_parts AS vp
+WHERE vp.processing_status = 'discovered';
diff --git a/bilibili-asr-archive/tests/test_storage_schema.py b/bilibili-asr-archive/tests/test_storage_schema.py
new file mode 100644
index 0000000..f372ec8
--- /dev/null
+++ b/bilibili-asr-archive/tests/test_storage_schema.py
@@ -0,0 +1,285 @@
+"""Offline contract tests for the normalized SQLite storage schema."""
+
+from __future__ import annotations
+
+from importlib import resources
+import os
+from pathlib import Path
+import sqlite3
+import tomllib
+
+import pytest
+
+from bili_asr.storage import duration_to_ms, normalize_page_index, open_database
+
+
+BASE_TABLES = {
+    "bilibili_users",
+    "videos",
+    "video_parts",
+    "ingestion_runs",
+    "ingestion_cursors",
+    "ingestion_pages",
+    "ingestion_discoveries",
+    "audio_objects",
+    "part_audio_objects",
+    "asr_models",
+    "transcripts",
+    "transcript_segments",
+}
+VIEWS = {"v_video_parts", "v_ingestion_run_stats", "v_pending_metadata"}
+
+
+def test_schema_sql_is_declared_and_read_as_package_resource():
+    project_root = Path(__file__).resolve().parents[1]
+    pyproject = tomllib.loads(
+        (project_root / "pyproject.toml").read_text(encoding="utf-8")
+    )
+    package_data = pyproject["tool"]["setuptools"]["package-data"]
+    assert "schema.sql" in package_data["bili_asr.storage"]
+
+    schema_resource = resources.files("bili_asr.storage").joinpath("schema.sql")
+    assert schema_resource.is_file()
+    assert "CREATE TABLE IF NOT EXISTS videos" in schema_resource.read_text(
+        encoding="utf-8"
+    )
+
+
+def _table_names(connection: sqlite3.Connection) -> set[str]:
+    rows = connection.execute(
+        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
+    )
+    return {row[0] for row in rows}
+
+
+def _insert_user_video_part(connection: sqlite3.Connection) -> int:
+    connection.execute(
+        "INSERT INTO bilibili_users(mid, display_name, created_at, updated_at) "
+        "VALUES (?, ?, ?, ?)",
+        (23191782, "未明子", 100, 100),
+    )
+    connection.execute(
+        "INSERT INTO videos(bvid, aid, mid, title, pubdate, created_at, updated_at) "
+        "VALUES (?, ?, ?, ?, ?, ?, ?)",
+        ("BV1TEST", 1001, 23191782, "视频", 1_700_000_000, 101, 101),
+    )
+    cursor = connection.execute(
+        """
+        INSERT INTO video_parts(
+            bvid, page_index, cid, title, duration_ms, processing_status,
+            created_at, updated_at
+        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
+        """,
+        ("BV1TEST", 0, 2001, "第一段", 1_234, "discovered", 102, 102),
+    )
+    return int(cursor.lastrowid)
+
+
+def test_fresh_database_initializes_archive_root_and_is_idempotent(tmp_root):
+    connection = open_database(tmp_root)
+    try:
+        assert os.path.isfile(os.path.join(tmp_root, "archive.db"))
+        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
+        assert connection.isolation_level == "DEFERRED"
+        assert BASE_TABLES | VIEWS <= _table_names(connection)
+
+        _insert_user_video_part(connection)
+        connection.commit()
+    finally:
+        connection.close()
+
+    reopened = open_database(os.path.join(tmp_root, "archive.db"))
+    try:
+        assert reopened.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0] == 1
+        assert reopened.execute("PRAGMA foreign_keys").fetchone()[0] == 1
+    finally:
+        reopened.close()
+
+
+def test_page_and_duration_normalization_uses_contract_formulas():
+    assert duration_to_ms(12.3459) == 12_345
+    assert duration_to_ms(0) == 0
+    assert normalize_page_index(1) == 0
+    assert normalize_page_index(3) == 2
+    with pytest.raises(ValueError):
+        normalize_page_index(0)
+    with pytest.raises(ValueError):
+        duration_to_ms(-0.1)
+
+
+def test_foreign_keys_reject_orphans_and_use_restrict(tmp_root):
+    connection = open_database(tmp_root)
+    try:
+        with pytest.raises(sqlite3.IntegrityError):
+            connection.execute(
+                "INSERT INTO videos(bvid, mid, title, pubdate, created_at, updated_at) "
+                "VALUES ('BVORPHAN', 999, 'orphan', 1, 1, 1)"
+            )
+        with pytest.raises(sqlite3.IntegrityError):
+            connection.execute(
+                """
+                INSERT INTO video_parts(
+                    bvid, page_index, cid, title, duration_ms,
+                    processing_status, created_at, updated_at
+                ) VALUES ('BVORPHAN', 0, 1, 'orphan', 1, 'discovered', 1, 1)
+                """
+            )
+
+        _insert_user_video_part(connection)
+        with pytest.raises(sqlite3.IntegrityError):
+            connection.execute("DELETE FROM bilibili_users WHERE mid = 23191782")
+        with pytest.raises(sqlite3.IntegrityError):
+            connection.execute("DELETE FROM videos WHERE bvid = 'BV1TEST'")
+
+        for table in BASE_TABLES:
+            for row in connection.execute(f"PRAGMA foreign_key_list({table})"):
+                assert row[6].upper() == "RESTRICT"
+    finally:
+        connection.close()
+
+
+def test_duplicate_candidate_keys_are_rejected(tmp_root):
+    connection = open_database(tmp_root)
+    try:
+        _insert_user_video_part(connection)
+        with pytest.raises(sqlite3.IntegrityError):
+            connection.execute(
+                "INSERT INTO bilibili_users VALUES (23191782, 'same', 1, 1)"
+            )
+        with pytest.raises(sqlite3.IntegrityError):
+            connection.execute(
+                "INSERT INTO videos VALUES ('BV1TEST', 1002, 23191782, 'same', 1, 1, 1)"
+            )
+        with pytest.raises(sqlite3.IntegrityError):
+            connection.execute(
+                "INSERT INTO videos VALUES ('BV2TEST', 1001, 23191782, 'same', 1, 1, 1)"
+            )
+        with pytest.raises(sqlite3.IntegrityError):
+            connection.execute(
+                """
+                INSERT INTO video_parts(
+                    bvid, page_index, cid, title, duration_ms,
+                    processing_status, created_at, updated_at
+                ) VALUES ('BV1TEST', 0, 2, 'duplicate', 10, 'gone', 1, 1)
+                """
+            )
+
+        connection.execute(
+            """
+            INSERT INTO audio_objects(
+                audio_id, sha256, byte_size, format, duration_ms, storage_key, created_at
+            ) VALUES (1, 'hash-1', 1, 'm4a', 1, 'audio/1', 1)
+            """
+        )
+        with pytest.raises(sqlite3.IntegrityError):
+            connection.execute(
+                """
+                INSERT INTO audio_objects(
+                    audio_id, sha256, byte_size, format, duration_ms, storage_key, created_at
+                ) VALUES (2, 'hash-1', 1, 'm4a', 1, 'audio/2', 1)
+                """
+            )
+        with pytest.raises(sqlite3.IntegrityError):
+            connection.execute(
+                """
+                INSERT INTO audio_objects(
+                    audio_id, sha256, byte_size, format, duration_ms, storage_key, created_at
+                ) VALUES (2, 'hash-2', 1, 'm4a', 1, 'audio/1', 1)
+                """
+            )
+    finally:
+        connection.close()
+
+
+def test_views_compute_work_id_and_keep_derived_values_out_of_base_tables(tmp_root):
+    connection = open_database(tmp_root)
+    try:
+        part_id = _insert_user_video_part(connection)
+        row = connection.execute(
+            "SELECT * FROM v_video_parts WHERE video_part_id = ?", (part_id,)
+        ).fetchone()
+        assert row["work_id"] == "BV1TEST:p0"
+        assert row["user_name"] == "未明子"
+        assert row["video_title"] == "视频"
+
+        for table in BASE_TABLES:
+            columns = {
+                item[1] for item in connection.execute(f"PRAGMA table_info({table})")
+            }
+            assert "work_id" not in columns
+            assert "part_count" not in columns
+            assert "video_count" not in columns
+            assert "run_count" not in columns
+
+        pending = connection.execute("SELECT work_id FROM v_pending_metadata").fetchall()
+        assert [item[0] for item in pending] == ["BV1TEST:p0"]
+    finally:
+        connection.close()
+
+
+def test_schema_constraints_cover_status_and_non_negative_values(tmp_root):
+    connection = open_database(tmp_root)
+    try:
+        _insert_user_video_part(connection)
+        invalid_statements = [
+            "UPDATE video_parts SET page_index = -1",
+            "UPDATE video_parts SET cid = 0",
+            "UPDATE video_parts SET duration_ms = 0",
+            "UPDATE video_parts SET processing_status = 'pending'",
+            "INSERT INTO ingestion_runs VALUES ('run', 23191782, 'other', '1', 1, NULL, 1, NULL, 'running')",
+            "INSERT INTO ingestion_runs VALUES ('run', 23191782, 'bilibili-api-python', '1', 0, NULL, 1, NULL, 'running')",
+            "INSERT INTO ingestion_cursors VALUES (23191782, 0, NULL, 'ready', NULL, 1)",
+            "INSERT INTO ingestion_pages VALUES ('run', 0, 'ok', NULL, 1, 1)",
+            "INSERT INTO ingestion_pages VALUES ('run', 1, 'unknown', NULL, 1, 1)",
+            "INSERT INTO audio_objects VALUES (1, 'hash', -1, 'm4a', 1, 'audio', 1)",
+        ]
+        for statement in invalid_statements:
+            with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError)):
+                connection.execute(statement)
+    finally:
+        connection.close()
+
+
+def test_transaction_order_parents_before_children(tmp_root):
+    connection = open_database(tmp_root)
+    try:
+        with connection:
+            connection.execute(
+                "INSERT INTO bilibili_users VALUES (7, 'operator', 1, 1)"
+            )
+            connection.execute(
+                """
+                INSERT INTO ingestion_runs VALUES (
+                    'run-1', 7, 'bilibili-api-python', '1.0', 1, 2,
+                    1, NULL, 'running'
+                )
+                """
+            )
+            connection.execute(
+                "INSERT INTO videos VALUES ('BV7', 7, 7, 'title', 1, 1, 1)"
+            )
+            connection.execute(
+                """
+                INSERT INTO video_parts(
+                    bvid, page_index, cid, title, duration_ms,
+                    processing_status, created_at, updated_at
+                ) VALUES ('BV7', 0, 70, 'part', 1000, 'discovered', 1, 1)
+                """
+            )
+            connection.execute(
+                "INSERT INTO ingestion_discoveries VALUES ('run-1', 1, 'BV7', 0, 1)"
+            )
+            connection.execute(
+                "INSERT INTO ingestion_cursors VALUES (7, 2, 1, 'ready', NULL, 1)"
+            )
+            connection.execute(
+                "INSERT INTO ingestion_pages VALUES ('run-1', 1, 'ok', NULL, 1, 1)"
+            )
+
+        stats = connection.execute(
+            "SELECT page_count, video_count FROM v_ingestion_run_stats "
+            "WHERE run_id = 'run-1'"
+        ).fetchone()
+        assert tuple(stats) == (1, 1)
+    finally:
+        connection.close()

```
