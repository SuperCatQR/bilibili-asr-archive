# Branch Review Package — 20260909-structured-metadata-schema

Plan: `20260909-structured-metadata-schema` (SDD)
Range: `c98f1405bded9bfd4a322c2226de7d85e4939e6e..ff81140411e9e04756055657569c39a0a0c5c2d4`
Base: `c98f140` (merge-base with spec integration branch `iteration/iter-2026-09-bilibili-api-sqlite`)
Head: `ff81140`
Working branch: `feature/20260909-structured-metadata-schema`

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
index 0000000..c1772d3
--- /dev/null
+++ b/bilibili-asr-archive/src/bili_asr/storage/database.py
@@ -0,0 +1,528 @@
+"""SQLite bootstrap and normalized metadata repository."""
+
+from __future__ import annotations
+
+from contextlib import contextmanager
+from importlib import resources
+import math
+import os
+from pathlib import Path
+import sqlite3
+from typing import Iterable, Iterator, TypeAlias
+
+from .models import (
+    CursorRecord,
+    DiscoveryRecord,
+    IngestionPageRecord,
+    IngestionRunRecord,
+    UserRecord,
+    VideoPartRecord,
+    VideoRecord,
+)
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
+class MetadataRepository:
+    """Repository for normalized metadata and ingestion state.
+
+    The low-level methods execute SQL without committing so a caller can group
+    them in one transaction. ``record_page`` is the page-level convenience
+    operation: when supplied with page payloads it owns the transaction and
+    applies the locked parent-before-child ordering. The connection's context
+    manager is also available through :meth:`transaction` for callers that
+    need to compose the lower-level methods themselves.
+    """
+
+    def __init__(self, connection: sqlite3.Connection):
+        if not isinstance(connection, sqlite3.Connection):
+            raise TypeError("connection must be a sqlite3.Connection")
+        self.connection = connection
+
+    @contextmanager
+    def transaction(self) -> Iterator[sqlite3.Connection]:
+        """Commit the enclosed repository operations or roll them back."""
+        try:
+            yield self.connection
+        except BaseException:
+            self.connection.rollback()
+            raise
+        else:
+            self.connection.commit()
+
+    def upsert_user(self, user: UserRecord) -> None:
+        """Insert or update the current display label for a user."""
+        if not isinstance(user, UserRecord):
+            raise TypeError("user must be a UserRecord")
+        self.connection.execute(
+            """
+            INSERT INTO bilibili_users(mid, display_name, created_at, updated_at)
+            VALUES (?, ?, ?, ?)
+            ON CONFLICT(mid) DO UPDATE SET
+                display_name = excluded.display_name,
+                updated_at = excluded.updated_at
+            """,
+            (user.mid, user.display_name, user.created_at, user.updated_at),
+        )
+
+    def upsert_video(self, video: VideoRecord) -> None:
+        """Insert or update a video's current canonical display fields."""
+        if not isinstance(video, VideoRecord):
+            raise TypeError("video must be a VideoRecord")
+        self.connection.execute(
+            """
+            INSERT INTO videos(
+                bvid, aid, mid, title, pubdate, created_at, updated_at
+            ) VALUES (?, ?, ?, ?, ?, ?, ?)
+            ON CONFLICT(bvid) DO UPDATE SET
+                aid = COALESCE(videos.aid, excluded.aid),
+                title = excluded.title,
+                updated_at = excluded.updated_at
+            """,
+            (
+                video.bvid,
+                video.aid,
+                video.mid,
+                video.title,
+                video.pubdate,
+                video.created_at,
+                video.updated_at,
+            ),
+        )
+
+    def upsert_part(self, part: VideoPartRecord) -> int:
+        """Insert or update a normalized part and return its local ID."""
+        if not isinstance(part, VideoPartRecord):
+            raise TypeError("part must be a VideoPartRecord")
+        if part.video_part_id is None:
+            self.connection.execute(
+                """
+                INSERT INTO video_parts(
+                    bvid, page_index, cid, title, duration_ms, processing_status,
+                    created_at, updated_at
+                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
+                ON CONFLICT(bvid, page_index) DO UPDATE SET
+                    title = excluded.title,
+                    duration_ms = excluded.duration_ms,
+                    processing_status = excluded.processing_status,
+                    updated_at = excluded.updated_at
+                """,
+                (
+                    part.bvid,
+                    part.page_index,
+                    part.cid,
+                    part.title,
+                    part.duration_ms,
+                    part.processing_status,
+                    part.created_at,
+                    part.updated_at,
+                ),
+            )
+        else:
+            self.connection.execute(
+                """
+                INSERT INTO video_parts(
+                    video_part_id, bvid, page_index, cid, title, duration_ms,
+                    processing_status, created_at, updated_at
+                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
+                ON CONFLICT(bvid, page_index) DO UPDATE SET
+                    title = excluded.title,
+                    duration_ms = excluded.duration_ms,
+                    processing_status = excluded.processing_status,
+                    updated_at = excluded.updated_at
+                """,
+                (
+                    part.video_part_id,
+                    part.bvid,
+                    part.page_index,
+                    part.cid,
+                    part.title,
+                    part.duration_ms,
+                    part.processing_status,
+                    part.created_at,
+                    part.updated_at,
+                ),
+            )
+
+        row = self.connection.execute(
+            """
+            SELECT video_part_id
+            FROM video_parts
+            WHERE bvid = ? AND page_index = ?
+            """,
+            (part.bvid, part.page_index),
+        ).fetchone()
+        if row is None:  # pragma: no cover - the preceding INSERT guarantees this
+            raise sqlite3.DatabaseError("upserted video part could not be read back")
+        return int(row[0])
+
+    def start_run(self, run: IngestionRunRecord) -> None:
+        """Insert a run record, preserving an existing run on retry."""
+        if not isinstance(run, IngestionRunRecord):
+            raise TypeError("run must be an IngestionRunRecord")
+        self.connection.execute(
+            """
+            INSERT INTO ingestion_runs(
+                run_id, mid, source_package, source_version, requested_start_page,
+                requested_page_limit, started_at, finished_at, outcome
+            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
+            ON CONFLICT(run_id) DO NOTHING
+            """,
+            (
+                run.run_id,
+                run.mid,
+                run.source_package,
+                run.source_version,
+                run.requested_start_page,
+                run.requested_page_limit,
+                run.started_at,
+                run.finished_at,
+                run.outcome,
+            ),
+        )
+        # A run is a lifecycle parent for page transactions. Commit its start
+        # independently so a failed page can roll back without deleting it.
+        self.connection.commit()
+
+    def finish_run(
+        self,
+        run: IngestionRunRecord | str,
+        outcome: str | None = None,
+        finished_at: int | None = None,
+    ) -> None:
+        """Set a run's terminal/current outcome.
+
+        The preferred form is ``finish_run(IngestionRunRecord(...))``. A scalar
+        compatibility form, ``finish_run(run_id, outcome, finished_at)``, is
+        provided for the ingestion service's terminal transition.
+        """
+        if isinstance(run, IngestionRunRecord):
+            run_id = run.run_id
+            resolved_outcome = run.outcome
+            resolved_finished_at = run.finished_at
+            if resolved_finished_at is None:
+                raise ValueError("finished_at is required when finishing a run")
+            started_at = run.started_at
+        elif isinstance(run, str):
+            run_id = run
+            if not run_id.strip():
+                raise ValueError("run_id must not be empty")
+            if outcome is None or finished_at is None:
+                raise ValueError("outcome and finished_at are required")
+            resolved_outcome = outcome
+            resolved_finished_at = finished_at
+            started_row = self.connection.execute(
+                "SELECT started_at FROM ingestion_runs WHERE run_id = ?", (run_id,)
+            ).fetchone()
+            if started_row is None:
+                raise sqlite3.IntegrityError(f"unknown run_id: {run_id}")
+            started_at = int(started_row[0])
+        else:
+            raise TypeError("run must be an IngestionRunRecord or run ID")
+
+        if resolved_outcome not in {
+            "complete",
+            "limited",
+            "risk_interrupted",
+            "failed",
+        }:
+            raise ValueError("finish_run requires a terminal run outcome")
+        if not isinstance(resolved_finished_at, int) or isinstance(resolved_finished_at, bool):
+            raise TypeError("finished_at must be an integer")
+        if resolved_finished_at < started_at:
+            raise ValueError("finished_at must not precede started_at")
+        self.connection.execute(
+            "UPDATE ingestion_runs SET finished_at = ?, outcome = ? WHERE run_id = ?",
+            (resolved_finished_at, resolved_outcome, run_id),
+        )
+        if self.connection.execute("SELECT changes()").fetchone()[0] != 1:
+            raise sqlite3.IntegrityError(f"unknown run_id: {run_id}")
+        self.connection.commit()
+
+    def _record_page(self, page: IngestionPageRecord) -> None:
+        self.connection.execute(
+            """
+            INSERT INTO ingestion_pages(
+                run_id, page_number, outcome, error_code, started_at, finished_at
+            ) VALUES (?, ?, ?, ?, ?, ?)
+            ON CONFLICT(run_id, page_number) DO UPDATE SET
+                outcome = excluded.outcome,
+                error_code = excluded.error_code,
+                started_at = excluded.started_at,
+                finished_at = excluded.finished_at
+            """,
+            (
+                page.run_id,
+                page.page_number,
+                page.outcome,
+                page.error_code,
+                page.started_at,
+                page.finished_at,
+            ),
+        )
+
+    def record_page(
+        self,
+        page: IngestionPageRecord,
+        user: UserRecord | None = None,
+        video: VideoRecord | Iterable[VideoRecord] | None = None,
+        parts: Iterable[VideoPartRecord] = (),
+        discoveries: Iterable[DiscoveryRecord] = (),
+        cursor: CursorRecord | None = None,
+        *,
+        videos: Iterable[VideoRecord] = (),
+    ) -> None:
+        """Record a page, optionally atomically persisting its complete payload.
+
+        With payload arguments this method performs the locked order: user,
+        videos, parts, discoveries, cursor, page outcome, commit. If any write
+        fails, the page transaction is rolled back. When the supplied page has
+        ``outcome='failed'``, its bounded page/run failure outcome is then
+        written in a separate transaction without persisting exception text.
+        """
+        if not isinstance(page, IngestionPageRecord):
+            raise TypeError("page must be an IngestionPageRecord")
+        video_records = tuple(videos)
+        if isinstance(video, VideoRecord):
+            video_records = (video, *video_records)
+        elif video is not None:
+            video_records = (*tuple(video), *video_records)
+        part_records = tuple(parts)
+        discovery_records = tuple(discoveries)
+        has_payload = (
+            user is not None
+            or bool(video_records)
+            or bool(part_records)
+            or bool(discovery_records)
+            or cursor is not None
+        )
+        if not has_payload:
+            if page.outcome == "failed":
+                self._record_failed_page(page)
+            else:
+                with self.transaction():
+                    self._record_page(page)
+            return
+
+        try:
+            with self.transaction():
+                if user is not None:
+                    self.upsert_user(user)
+                for video_record in video_records:
+                    self.upsert_video(video_record)
+                for part in part_records:
+                    self.upsert_part(part)
+                for discovery in discovery_records:
+                    self.record_discovery(discovery)
+                if cursor is not None:
+                    self.write_cursor(cursor)
+                self._record_page(page)
+        except BaseException:
+            if page.outcome == "failed":
+                try:
+                    self._record_failed_page(page)
+                except sqlite3.Error:
+                    # Preserve the original page error; a missing run cannot be
+                    # repaired by inventing a relationship or error detail.
+                    self.connection.rollback()
+            raise
+
+    def _record_failed_page(self, page: IngestionPageRecord) -> None:
+        """Persist only bounded failure state after a rolled-back page."""
+        with self.transaction():
+            self._record_page(page)
+            self.connection.execute(
+                """
+                UPDATE ingestion_runs
+                SET outcome = 'failed', finished_at = ?
+                WHERE run_id = ?
+                """,
+                (page.finished_at, page.run_id),
+            )
+
+    def record_discovery(self, discovery: DiscoveryRecord) -> None:
+        """Insert or update one run/page/video discovery relationship."""
+        if not isinstance(discovery, DiscoveryRecord):
+            raise TypeError("discovery must be a DiscoveryRecord")
+        self.connection.execute(
+            """
+            INSERT INTO ingestion_discoveries(
+                run_id, page_number, bvid, source_position, discovered_at
+            ) VALUES (?, ?, ?, ?, ?)
+            ON CONFLICT(run_id, page_number, bvid) DO UPDATE SET
+                source_position = excluded.source_position,
+                discovered_at = excluded.discovered_at
+            """,
+            (
+                discovery.run_id,
+                discovery.page_number,
+                discovery.bvid,
+                discovery.source_position,
+                discovery.discovered_at,
+            ),
+        )
+
+    def read_cursor(self, mid: int) -> CursorRecord | None:
+        """Read the current one-based cursor for a user."""
+        if isinstance(mid, bool) or not isinstance(mid, int) or mid < 1:
+            raise ValueError("mid must be a positive integer")
+        row = self.connection.execute(
+            """
+            SELECT mid, next_page, observed_total, state, last_error_code, updated_at
+            FROM ingestion_cursors
+            WHERE mid = ?
+            """,
+            (mid,),
+        ).fetchone()
+        if row is None:
+            return None
+        return CursorRecord(
+            mid=int(row["mid"]),
+            next_page=int(row["next_page"]),
+            observed_total=(
+                None if row["observed_total"] is None else int(row["observed_total"])
+            ),
+            state=str(row["state"]),
+            last_error_code=(
+                None if row["last_error_code"] is None else str(row["last_error_code"])
+            ),
+            updated_at=int(row["updated_at"]),
+        )
+
+    def write_cursor(self, cursor: CursorRecord) -> None:
+        """Insert or replace the resumable cursor for a user."""
+        if not isinstance(cursor, CursorRecord):
+            raise TypeError("cursor must be a CursorRecord")
+        self.connection.execute(
+            """
+            INSERT INTO ingestion_cursors(
+                mid, next_page, observed_total, state, last_error_code, updated_at
+            ) VALUES (?, ?, ?, ?, ?, ?)
+            ON CONFLICT(mid) DO UPDATE SET
+                next_page = excluded.next_page,
+                observed_total = excluded.observed_total,
+                state = excluded.state,
+                last_error_code = excluded.last_error_code,
+                updated_at = excluded.updated_at
+            """,
+            (
+                cursor.mid,
+                cursor.next_page,
+                cursor.observed_total,
+                cursor.state,
+                cursor.last_error_code,
+                cursor.updated_at,
+            ),
+        )
+
+    def list_pending_parts(self, limit: int | None = None) -> list[sqlite3.Row]:
+        """Return discovered parts in deterministic work order."""
+        if limit is not None:
+            if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
+                raise ValueError("limit must be a positive integer or None")
+            query = (
+                "SELECT * FROM v_pending_metadata "
+                "ORDER BY bvid, page_index LIMIT ?"
+            )
+            return list(self.connection.execute(query, (limit,)).fetchall())
+        return list(
+            self.connection.execute(
+                "SELECT * FROM v_pending_metadata ORDER BY bvid, page_index"
+            ).fetchall()
+        )
+
+    def run_stats(self, run_id: str | None = None) -> sqlite3.Row | list[sqlite3.Row] | None:
+        """Read normalized run/page/video counts from the repository view."""
+        if run_id is None:
+            return list(
+                self.connection.execute(
+                    "SELECT * FROM v_ingestion_run_stats ORDER BY run_id"
+                ).fetchall()
+            )
+        if not isinstance(run_id, str) or not run_id.strip():
+            raise ValueError("run_id must be a non-empty string or None")
+        return self.connection.execute(
+            "SELECT * FROM v_ingestion_run_stats WHERE run_id = ?", (run_id,)
+        ).fetchone()
+
+
+__all__ = [
+    "DatabaseConnection",
+    "MetadataRepository",
+    "duration_to_ms",
+    "initialize_schema",
+    "normalize_page_index",
+    "open_database",
+]
diff --git a/bilibili-asr-archive/src/bili_asr/storage/models.py b/bilibili-asr-archive/src/bili_asr/storage/models.py
new file mode 100644
index 0000000..266ffdd
--- /dev/null
+++ b/bilibili-asr-archive/src/bili_asr/storage/models.py
@@ -0,0 +1,268 @@
+"""Validated internal records used by the SQLite metadata repository.
+
+These dataclasses are deliberately independent of third-party API response
+objects.  They represent the scalar facts that may be persisted by the
+normalized metadata schema.
+"""
+
+from __future__ import annotations
+
+from dataclasses import dataclass
+import re
+from typing import Literal
+
+
+ProcessingStatus = Literal["discovered", "metadata_collected", "gone"]
+RunOutcome = Literal["running", "complete", "limited", "risk_interrupted", "failed"]
+PageOutcome = Literal["ok", "empty", "risk_interrupted", "failed"]
+CursorState = Literal["ready", "complete", "limited", "risk_interrupted"]
+
+_ALLOWED_PROCESSING_STATUS = frozenset({"discovered", "metadata_collected", "gone"})
+_ALLOWED_RUN_OUTCOMES = frozenset(
+    {"running", "complete", "limited", "risk_interrupted", "failed"}
+)
+_ALLOWED_PAGE_OUTCOMES = frozenset({"ok", "empty", "risk_interrupted", "failed"})
+_ALLOWED_CURSOR_STATES = frozenset({"ready", "complete", "limited", "risk_interrupted"})
+_ERROR_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]+$")
+
+
+def _integer(value: object, field: str, *, minimum: int | None = None) -> int:
+    if isinstance(value, bool) or not isinstance(value, int):
+        raise TypeError(f"{field} must be an integer")
+    if minimum is not None and value < minimum:
+        raise ValueError(f"{field} must be at least {minimum}")
+    return value
+
+
+def _text(value: object, field: str) -> str:
+    if not isinstance(value, str):
+        raise TypeError(f"{field} must be a string")
+    if not value.strip():
+        raise ValueError(f"{field} must not be empty")
+    if "\x00" in value or "\r" in value or "\n" in value:
+        raise ValueError(f"{field} contains invalid control characters")
+    return value
+
+
+def _error_code(value: object, field: str = "error_code") -> str | None:
+    if value is None:
+        return None
+    if not isinstance(value, str):
+        raise TypeError(f"{field} must be a string or None")
+    if not value or len(value) > 64 or _ERROR_CODE_PATTERN.fullmatch(value) is None:
+        raise ValueError(f"{field} must be a bounded scalar code")
+    return value
+
+
+def _choice(value: object, field: str, allowed: frozenset[str]) -> str:
+    value = _text(value, field)
+    if value not in allowed:
+        choices = ", ".join(sorted(allowed))
+        raise ValueError(f"{field} must be one of: {choices}")
+    return value
+
+
+@dataclass(frozen=True, slots=True)
+class UserRecord:
+    """Current operational metadata for one Bilibili user."""
+
+    mid: int
+    display_name: str
+    created_at: int
+    updated_at: int
+
+    def __post_init__(self) -> None:
+        _integer(self.mid, "mid", minimum=1)
+        _text(self.display_name, "display_name")
+        _integer(self.created_at, "created_at", minimum=0)
+        _integer(self.updated_at, "updated_at", minimum=0)
+        if self.updated_at < self.created_at:
+            raise ValueError("updated_at must not precede created_at")
+
+
+@dataclass(frozen=True, slots=True)
+class VideoRecord:
+    """Current operational metadata for one Bilibili video."""
+
+    bvid: str
+    aid: int | None
+    mid: int
+    title: str
+    pubdate: int
+    created_at: int
+    updated_at: int
+
+    def __post_init__(self) -> None:
+        _text(self.bvid, "bvid")
+        if self.aid is not None:
+            _integer(self.aid, "aid", minimum=1)
+        _integer(self.mid, "mid", minimum=1)
+        _text(self.title, "title")
+        _integer(self.pubdate, "pubdate", minimum=0)
+        _integer(self.created_at, "created_at", minimum=0)
+        _integer(self.updated_at, "updated_at", minimum=0)
+        if self.updated_at < self.created_at:
+            raise ValueError("updated_at must not precede created_at")
+
+
+@dataclass(frozen=True, slots=True)
+class VideoPartRecord:
+    """Normalized metadata for one video part.
+
+    ``video_part_id`` is optional for new rows because SQLite allocates the
+    local surrogate key.  ``work_id`` is intentionally computed and is never
+    persisted as a column.
+    """
+
+    bvid: str
+    page_index: int
+    cid: int
+    title: str
+    duration_ms: int
+    processing_status: ProcessingStatus
+    created_at: int
+    updated_at: int
+    video_part_id: int | None = None
+
+    def __post_init__(self) -> None:
+        _text(self.bvid, "bvid")
+        _integer(self.page_index, "page_index", minimum=0)
+        _integer(self.cid, "cid", minimum=1)
+        _text(self.title, "title")
+        _integer(self.duration_ms, "duration_ms", minimum=1)
+        _choice(self.processing_status, "processing_status", _ALLOWED_PROCESSING_STATUS)
+        _integer(self.created_at, "created_at", minimum=0)
+        _integer(self.updated_at, "updated_at", minimum=0)
+        if self.updated_at < self.created_at:
+            raise ValueError("updated_at must not precede created_at")
+        if self.video_part_id is not None:
+            _integer(self.video_part_id, "video_part_id", minimum=1)
+
+    @property
+    def work_id(self) -> str:
+        """Return the derived work identifier without storing it."""
+
+        return f"{self.bvid}:p{self.page_index}"
+
+
+@dataclass(frozen=True, slots=True)
+class IngestionRunRecord:
+    """Metadata and outcome state for one collection run."""
+
+    run_id: str
+    mid: int
+    source_package: str
+    source_version: str
+    requested_start_page: int
+    requested_page_limit: int | None
+    started_at: int
+    finished_at: int | None = None
+    outcome: RunOutcome = "running"
+
+    def __post_init__(self) -> None:
+        _text(self.run_id, "run_id")
+        _integer(self.mid, "mid", minimum=1)
+        if _text(self.source_package, "source_package") != "bilibili-api-python":
+            raise ValueError("source_package must be bilibili-api-python")
+        _text(self.source_version, "source_version")
+        _integer(self.requested_start_page, "requested_start_page", minimum=1)
+        if self.requested_page_limit is not None:
+            _integer(self.requested_page_limit, "requested_page_limit", minimum=1)
+        _integer(self.started_at, "started_at", minimum=0)
+        if self.finished_at is not None:
+            _integer(self.finished_at, "finished_at", minimum=0)
+            if self.finished_at < self.started_at:
+                raise ValueError("finished_at must not precede started_at")
+        _choice(self.outcome, "outcome", _ALLOWED_RUN_OUTCOMES)
+
+
+@dataclass(frozen=True, slots=True)
+class IngestionPageRecord:
+    """Outcome evidence for one requested page in one run."""
+
+    run_id: str
+    page_number: int
+    outcome: PageOutcome
+    error_code: str | None
+    started_at: int
+    finished_at: int
+
+    def __post_init__(self) -> None:
+        _text(self.run_id, "run_id")
+        _integer(self.page_number, "page_number", minimum=1)
+        _choice(self.outcome, "outcome", _ALLOWED_PAGE_OUTCOMES)
+        _error_code(self.error_code)
+        _integer(self.started_at, "started_at", minimum=0)
+        _integer(self.finished_at, "finished_at", minimum=0)
+        if self.finished_at < self.started_at:
+            raise ValueError("finished_at must not precede started_at")
+
+
+@dataclass(frozen=True, slots=True)
+class CursorRecord:
+    """Resumable one-based page cursor for one user."""
+
+    mid: int
+    next_page: int
+    observed_total: int | None
+    state: CursorState
+    last_error_code: str | None
+    updated_at: int
+
+    def __post_init__(self) -> None:
+        _integer(self.mid, "mid", minimum=1)
+        _integer(self.next_page, "next_page", minimum=1)
+        if self.observed_total is not None:
+            _integer(self.observed_total, "observed_total", minimum=0)
+        _choice(self.state, "state", _ALLOWED_CURSOR_STATES)
+        _error_code(self.last_error_code, "last_error_code")
+        _integer(self.updated_at, "updated_at", minimum=0)
+
+
+@dataclass(frozen=True, slots=True)
+class DiscoveryRecord:
+    """A normalized relationship between a run page and a discovered video."""
+
+    run_id: str
+    page_number: int
+    bvid: str
+    source_position: int | None
+    discovered_at: int
+
+    def __post_init__(self) -> None:
+        _text(self.run_id, "run_id")
+        _integer(self.page_number, "page_number", minimum=1)
+        _text(self.bvid, "bvid")
+        if self.source_position is not None:
+            _integer(self.source_position, "source_position", minimum=0)
+        _integer(self.discovered_at, "discovered_at", minimum=0)
+
+
+__all__ = [
+    "CursorRecord",
+    "DiscoveryRecord",
+    "IngestionPageRecord",
+    "IngestionRunRecord",
+    "PageOutcome",
+    "ProcessingStatus",
+    "RunOutcome",
+    "UserRecord",
+    "VideoPartRecord",
+    "VideoRecord",
+]
+
+
+# Internal validation helpers are intentionally not part of the public model API.
+validate_error_code = _error_code
+ALLOWED_PAGE_OUTCOMES = _ALLOWED_PAGE_OUTCOMES
+ALLOWED_RUN_OUTCOMES = _ALLOWED_RUN_OUTCOMES
+ALLOWED_CURSOR_STATES = _ALLOWED_CURSOR_STATES
+ALLOWED_PROCESSING_STATUS = _ALLOWED_PROCESSING_STATUS
+
+__all__ += [
+    "ALLOWED_CURSOR_STATES",
+    "ALLOWED_PAGE_OUTCOMES",
+    "ALLOWED_PROCESSING_STATUS",
+    "ALLOWED_RUN_OUTCOMES",
+    "validate_error_code",
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
diff --git a/bilibili-asr-archive/tests/fixtures/__init__.py b/bilibili-asr-archive/tests/fixtures/__init__.py
new file mode 100644
index 0000000..3a35c77
--- /dev/null
+++ b/bilibili-asr-archive/tests/fixtures/__init__.py
@@ -0,0 +1 @@
+"""Deterministic record factories for the offline metadata contract tests."""
diff --git a/bilibili-asr-archive/tests/fixtures/metadata_records.py b/bilibili-asr-archive/tests/fixtures/metadata_records.py
new file mode 100644
index 0000000..a37584c
--- /dev/null
+++ b/bilibili-asr-archive/tests/fixtures/metadata_records.py
@@ -0,0 +1,166 @@
+"""Deterministic record factories for the offline metadata contract tests.
+
+Every builder returns a validated internal record with fixed literal field
+values, so repeated runs observe identical rows.  Keyword arguments override
+single fields; no wall-clock time, randomness, network data, third-party
+response objects, or credentials are involved.
+"""
+
+from __future__ import annotations
+
+from bili_asr.storage.models import (
+    CursorRecord,
+    CursorState,
+    DiscoveryRecord,
+    IngestionPageRecord,
+    IngestionRunRecord,
+    PageOutcome,
+    ProcessingStatus,
+    UserRecord,
+    VideoPartRecord,
+    VideoRecord,
+)
+
+
+MID = 23191782
+
+
+def make_user_record(
+    *, display_name: str = "未明子", updated_at: int = 100
+) -> UserRecord:
+    """Build the archive owner's current user record."""
+    return UserRecord(
+        mid=MID,
+        display_name=display_name,
+        created_at=100,
+        updated_at=updated_at,
+    )
+
+
+def make_run_record(
+    run_id: str = "run-1",
+    *,
+    requested_start_page: int = 1,
+    requested_page_limit: int | None = 3,
+    started_at: int = 101,
+) -> IngestionRunRecord:
+    """Build one metadata collection run opened against the archive owner."""
+    return IngestionRunRecord(
+        run_id=run_id,
+        mid=MID,
+        source_package="bilibili-api-python",
+        source_version="17.4.2",
+        requested_start_page=requested_start_page,
+        requested_page_limit=requested_page_limit,
+        started_at=started_at,
+    )
+
+
+def make_video_record(
+    bvid: str = "BV1SINGLE",
+    *,
+    title: str = "单集视频",
+    aid: int | None = 1001,
+    updated_at: int = 102,
+) -> VideoRecord:
+    """Build a video owned by the archive owner."""
+    return VideoRecord(
+        bvid=bvid,
+        aid=aid,
+        mid=MID,
+        title=title,
+        pubdate=1_700_000_000,
+        created_at=102,
+        updated_at=updated_at,
+    )
+
+
+def make_part_record(
+    bvid: str = "BV1SINGLE",
+    *,
+    page_index: int = 0,
+    cid: int = 2001,
+    title: str = "第一集",
+    status: ProcessingStatus = "discovered",
+    updated_at: int = 103,
+) -> VideoPartRecord:
+    """Build one normalized part of a video."""
+    return VideoPartRecord(
+        bvid=bvid,
+        page_index=page_index,
+        cid=cid,
+        title=title,
+        duration_ms=1_234,
+        processing_status=status,
+        created_at=103,
+        updated_at=updated_at,
+    )
+
+
+def make_page_record(
+    run_id: str = "run-1",
+    *,
+    page_number: int = 1,
+    outcome: PageOutcome = "ok",
+    error_code: str | None = None,
+    started_at: int = 110,
+    finished_at: int = 111,
+) -> IngestionPageRecord:
+    """Build one page-outcome record for a run."""
+    return IngestionPageRecord(
+        run_id=run_id,
+        page_number=page_number,
+        outcome=outcome,
+        error_code=error_code,
+        started_at=started_at,
+        finished_at=finished_at,
+    )
+
+
+def make_cursor_record(
+    *,
+    next_page: int = 2,
+    observed_total: int | None = 2,
+    state: CursorState = "ready",
+    last_error_code: str | None = None,
+    updated_at: int = 112,
+) -> CursorRecord:
+    """Build the resumable cursor state for the archive owner."""
+    return CursorRecord(
+        mid=MID,
+        next_page=next_page,
+        observed_total=observed_total,
+        state=state,
+        last_error_code=last_error_code,
+        updated_at=updated_at,
+    )
+
+
+def make_discovery_record(
+    bvid: str,
+    *,
+    run_id: str = "run-1",
+    page_number: int = 1,
+    source_position: int | None = 0,
+    discovered_at: int = 104,
+) -> DiscoveryRecord:
+    """Build one run/page/video discovery relationship."""
+    return DiscoveryRecord(
+        run_id=run_id,
+        page_number=page_number,
+        bvid=bvid,
+        source_position=source_position,
+        discovered_at=discovered_at,
+    )
+
+
+__all__ = [
+    "MID",
+    "make_cursor_record",
+    "make_discovery_record",
+    "make_page_record",
+    "make_run_record",
+    "make_part_record",
+    "make_user_record",
+    "make_video_record",
+]
diff --git a/bilibili-asr-archive/tests/test_metadata_repository.py b/bilibili-asr-archive/tests/test_metadata_repository.py
new file mode 100644
index 0000000..7dda1c9
--- /dev/null
+++ b/bilibili-asr-archive/tests/test_metadata_repository.py
@@ -0,0 +1,439 @@
+"""Offline repository contract tests for normalized metadata persistence."""
+
+from __future__ import annotations
+
+from dataclasses import fields
+import re
+import sqlite3
+
+import pytest
+
+from bili_asr.storage.database import MetadataRepository, open_database
+from bili_asr.storage.models import UserRecord, VideoPartRecord
+from fixtures.metadata_records import (
+    MID,
+    make_cursor_record,
+    make_discovery_record,
+    make_page_record,
+    make_run_record,
+    make_part_record,
+    make_user_record,
+    make_video_record,
+)
+
+
+def _start_run(repository: MetadataRepository, run_id: str = "run-1") -> None:
+    repository.upsert_user(make_user_record())
+    repository.start_run(make_run_record(run_id))
+
+
+def test_models_validate_scalars_and_compute_work_id_without_persisting_it():
+    part = make_part_record()
+    assert part.work_id == "BV1SINGLE:p0"
+    assert "work_id" not in {field.name for field in fields(VideoPartRecord)}
+
+    with pytest.raises(ValueError):
+        make_part_record(page_index=-1)
+    with pytest.raises(ValueError):
+        make_part_record(cid=0)
+    with pytest.raises(ValueError):
+        make_page_record(outcome="failed", error_code="raw traceback\n")
+    with pytest.raises(ValueError):
+        UserRecord(mid=MID, display_name="", created_at=1, updated_at=1)
+
+
+def test_record_page_persists_single_and_multipart_entities_in_locked_order(tmp_root):
+    connection = open_database(tmp_root)
+    repository = MetadataRepository(connection)
+    try:
+        _start_run(repository)
+        multipart = make_video_record("BV1MULTI", title="多集视频", aid=1002)
+        page = make_page_record()
+        repository.record_page(
+            page,
+            user=make_user_record(),
+            videos=[make_video_record(), multipart],
+            parts=[
+                make_part_record(),
+                make_part_record("BV1MULTI", page_index=0, cid=3001, title="上篇"),
+                make_part_record("BV1MULTI", page_index=1, cid=3002, title="下篇"),
+            ],
+            discoveries=[
+                make_discovery_record("BV1SINGLE"),
+                make_discovery_record("BV1MULTI", source_position=1),
+            ],
+            cursor=make_cursor_record(),
+        )
+
+        assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 2
+        assert connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0] == 3
+        assert connection.execute("SELECT COUNT(*) FROM ingestion_discoveries").fetchone()[0] == 2
+        assert connection.execute("SELECT COUNT(*) FROM ingestion_pages").fetchone()[0] == 1
+        assert repository.read_cursor(MID) == make_cursor_record()
+
+        pending = repository.list_pending_parts()
+        assert [row["work_id"] for row in pending] == [
+            "BV1MULTI:p0",
+            "BV1MULTI:p1",
+            "BV1SINGLE:p0",
+        ]
+        stats = repository.run_stats("run-1")
+        assert stats is not None
+        assert stats["page_count"] == 1
+        assert stats["video_count"] == 2
+    finally:
+        connection.close()
+
+
+def test_repeated_page_is_idempotent_but_a_new_run_keeps_page_evidence(tmp_root):
+    connection = open_database(tmp_root)
+    repository = MetadataRepository(connection)
+    try:
+        _start_run(repository)
+        repository.record_page(
+            make_page_record(),
+            user=make_user_record(),
+            video=make_video_record(),
+            parts=[make_part_record()],
+            discoveries=[make_discovery_record("BV1SINGLE")],
+            cursor=make_cursor_record(),
+        )
+
+        repository.record_page(
+            make_page_record(finished_at=120),
+            user=make_user_record(display_name="未明子（更新）", updated_at=119),
+            video=make_video_record(title="更新后的标题", updated_at=119),
+            parts=[make_part_record(title="更新后的分集标题", updated_at=119)],
+            discoveries=[make_discovery_record("BV1SINGLE", discovered_at=119)],
+            cursor=make_cursor_record(updated_at=120),
+        )
+        assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 1
+        assert connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0] == 1
+        assert connection.execute("SELECT COUNT(*) FROM ingestion_discoveries").fetchone()[0] == 1
+        assert connection.execute("SELECT COUNT(*) FROM ingestion_pages").fetchone()[0] == 1
+        assert connection.execute("SELECT title FROM videos").fetchone()[0] == "更新后的标题"
+        assert connection.execute("SELECT aid FROM videos").fetchone()[0] == 1001
+
+        _start_run(repository, "run-2")
+        repository.record_page(
+            make_page_record("run-2"),
+            video=make_video_record(title="同一视频的第二次发现"),
+            parts=[make_part_record()],
+            discoveries=[make_discovery_record("BV1SINGLE", run_id="run-2")],
+            cursor=make_cursor_record(updated_at=130),
+        )
+        assert connection.execute("SELECT COUNT(*) FROM ingestion_pages").fetchone()[0] == 2
+        assert connection.execute("SELECT COUNT(*) FROM ingestion_discoveries").fetchone()[0] == 2
+        assert repository.run_stats("run-1")["video_count"] == 1
+        assert repository.run_stats("run-2")["video_count"] == 1
+        assert connection.execute("SELECT title FROM videos").fetchone()[0] == "同一视频的第二次发现"
+    finally:
+        connection.close()
+
+
+def test_failed_page_rolls_back_payload_preserves_cursor_and_records_bounded_outcome(tmp_root):
+    connection = open_database(tmp_root)
+    repository = MetadataRepository(connection)
+    try:
+        _start_run(repository)
+        repository.record_page(
+            make_page_record(),
+            video=make_video_record(),
+            parts=[make_part_record()],
+            discoveries=[make_discovery_record("BV1SINGLE")],
+            cursor=make_cursor_record(),
+        )
+        failed_page = make_page_record(
+            page_number=2,
+            outcome="failed",
+            error_code="foreign_key",
+            started_at=200,
+            finished_at=201,
+        )
+        with pytest.raises(sqlite3.IntegrityError):
+            repository.record_page(
+                failed_page,
+                user=make_user_record(display_name="must roll back", updated_at=200),
+                video=make_video_record(title="must roll back", updated_at=200),
+                parts=[make_part_record("BV-MISSING", title="orphan")],
+                cursor=make_cursor_record(next_page=3, updated_at=201),
+            )
+
+        assert repository.read_cursor(MID) == make_cursor_record()
+        assert connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0] == 1
+        assert connection.execute("SELECT display_name FROM bilibili_users").fetchone()[0] == "未明子"
+        page_row = connection.execute(
+            "SELECT outcome, error_code FROM ingestion_pages WHERE run_id = 'run-1' AND page_number = 2"
+        ).fetchone()
+        assert tuple(page_row) == ("failed", "foreign_key")
+        assert tuple(
+            connection.execute(
+                "SELECT outcome, finished_at FROM ingestion_runs WHERE run_id = 'run-1'"
+            ).fetchone()
+        ) == ("failed", 201)
+        assert connection.execute(
+            "SELECT COUNT(*) FROM ingestion_pages WHERE error_code LIKE '%traceback%'"
+        ).fetchone()[0] == 0
+    finally:
+        connection.close()
+
+
+def test_fk_rejection_and_delete_restriction_apply_to_repository_writes(tmp_root):
+    connection = open_database(tmp_root)
+    repository = MetadataRepository(connection)
+    try:
+        with pytest.raises(sqlite3.IntegrityError):
+            with repository.transaction():
+                repository.upsert_video(make_video_record("BV-ORPHAN"))
+        with pytest.raises(sqlite3.IntegrityError):
+            with repository.transaction():
+                repository.upsert_part(make_part_record("BV-MISSING"))
+        with pytest.raises(sqlite3.IntegrityError):
+            with repository.transaction():
+                repository.write_cursor(make_cursor_record())
+
+        with repository.transaction():
+            repository.upsert_user(make_user_record())
+            repository.upsert_video(make_video_record())
+            repository.upsert_part(make_part_record())
+
+        with pytest.raises(sqlite3.IntegrityError):
+            connection.execute("DELETE FROM bilibili_users WHERE mid = ?", (MID,))
+        with pytest.raises(sqlite3.IntegrityError):
+            connection.execute("DELETE FROM videos WHERE bvid = 'BV1SINGLE'")
+    finally:
+        connection.close()
+
+
+def test_repository_end_to_end_records_two_runs_with_cursor_transitions(tmp_root):
+    """Full page flow: user, single-part video, multipart video, two runs."""
+    connection = open_database(tmp_root)
+    repository = MetadataRepository(connection)
+    try:
+        assert repository.read_cursor(MID) is None
+
+        _start_run(repository)
+
+        # Page 1 applies the locked order in one transaction:
+        # user -> video -> parts -> discoveries -> cursor -> page outcome.
+        repository.record_page(
+            make_page_record(),
+            user=make_user_record(),
+            video=make_video_record(),
+            parts=[make_part_record()],
+            discoveries=[make_discovery_record("BV1SINGLE")],
+            cursor=make_cursor_record(),
+        )
+        assert repository.read_cursor(MID) == make_cursor_record()
+
+        repository.start_run(
+            make_run_record("run-2", requested_start_page=2, started_at=200)
+        )
+        repository.record_page(
+            make_page_record(
+                "run-2", page_number=2, started_at=201, finished_at=202
+            ),
+            videos=[
+                make_video_record("BV1MULTI", title="多集视频", aid=1002, updated_at=203)
+            ],
+            parts=[
+                make_part_record(
+                    "BV1MULTI", page_index=0, cid=3001, title="上篇", updated_at=204
+                ),
+                make_part_record(
+                    "BV1MULTI", page_index=1, cid=3002, title="下篇", updated_at=204
+                ),
+            ],
+            discoveries=[
+                make_discovery_record(
+                    "BV1MULTI", run_id="run-2", page_number=2, discovered_at=205
+                )
+            ],
+            cursor=make_cursor_record(next_page=3, updated_at=206),
+        )
+
+        # Page 3 is empty: no payload rows, only the cursor state transition.
+        repository.record_page(
+            make_page_record(
+                "run-2",
+                page_number=3,
+                outcome="empty",
+                started_at=210,
+                finished_at=211,
+            ),
+            cursor=make_cursor_record(
+                next_page=3, state="complete", updated_at=211
+            ),
+        )
+
+        repository.finish_run("run-1", "complete", 300)
+        repository.finish_run("run-2", "complete", 301)
+
+        assert connection.execute("SELECT COUNT(*) FROM bilibili_users").fetchone()[0] == 1
+        assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 2
+        assert connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0] == 3
+        page_rows = connection.execute(
+            "SELECT run_id, page_number, outcome, error_code FROM ingestion_pages "
+            "ORDER BY run_id, page_number"
+        ).fetchall()
+        assert [tuple(row) for row in page_rows] == [
+            ("run-1", 1, "ok", None),
+            ("run-2", 2, "ok", None),
+            ("run-2", 3, "empty", None),
+        ]
+        assert repository.read_cursor(MID) == make_cursor_record(
+            next_page=3, state="complete", updated_at=211
+        )
+
+        pending = repository.list_pending_parts()
+        assert [row["work_id"] for row in pending] == [
+            "BV1MULTI:p0",
+            "BV1MULTI:p1",
+            "BV1SINGLE:p0",
+        ]
+
+        stats = repository.run_stats()
+        assert [row["run_id"] for row in stats] == ["run-1", "run-2"]
+        assert (stats[0]["page_count"], stats[0]["video_count"]) == (1, 1)
+        assert (stats[1]["page_count"], stats[1]["video_count"]) == (2, 1)
+        assert all(row["outcome"] == "complete" for row in stats)
+
+        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
+    finally:
+        connection.close()
+
+
+def test_error_fields_persist_only_bounded_scalar_codes(tmp_root):
+    """The repository accepts bounded scalar codes and never secret material."""
+    connection = open_database(tmp_root)
+    repository = MetadataRepository(connection)
+    try:
+        repository.upsert_user(make_user_record())
+        repository.start_run(make_run_record())
+        repository.write_cursor(
+            make_cursor_record(state="limited", last_error_code="rate_limited")
+        )
+        repository.record_page(
+            make_page_record(
+                page_number=2,
+                outcome="failed",
+                error_code="http_412",
+                started_at=120,
+                finished_at=121,
+            )
+        )
+        assert repository.read_cursor(MID).last_error_code == "rate_limited"
+        stored_page = connection.execute(
+            "SELECT outcome, error_code FROM ingestion_pages "
+            "WHERE run_id = 'run-1' AND page_number = 2"
+        ).fetchone()
+        assert tuple(stored_page) == ("failed", "http_412")
+
+        forbidden_codes = [
+            "SESSDATA=abc123; bili_jct=def456",  # cookie material
+            "https://upos.example.com/signed-url?token",  # signed URL
+            '{"code": -403, "message": "raw"}',  # raw JSON document
+            "Traceback (most recent call last):",  # exception text
+            "e" * 65,  # exceeds the 64-character bound
+        ]
+        for code in forbidden_codes:
+            with pytest.raises(ValueError):
+                make_cursor_record(state="limited", last_error_code=code)
+            with pytest.raises(ValueError):
+                make_page_record(outcome="failed", error_code=code)
+
+        expected_codes = {
+            ("ingestion_cursors", "last_error_code"): "rate_limited",
+            ("ingestion_pages", "error_code"): "http_412",
+        }
+        for table, column in (
+            ("ingestion_cursors", "last_error_code"),
+            ("ingestion_pages", "error_code"),
+        ):
+            for marker in ("SESSDATA", "bili_jct", "https", "{", "Traceback", " "):
+                assert connection.execute(
+                    f"SELECT COUNT(*) FROM {table} WHERE {column} LIKE ?",
+                    (f"%{marker}%",),
+                ).fetchone()[0] == 0
+            values = connection.execute(
+                f"SELECT {column} FROM {table} WHERE {column} IS NOT NULL"
+            ).fetchall()
+            assert [row[0] for row in values] == [expected_codes[(table, column)]]
+            for (value,) in values:
+                assert len(value) <= 64
+                assert re.fullmatch(r"[A-Za-z0-9_.:-]+", value)
+    finally:
+        connection.close()
+
+
+def test_re_upsert_backfills_missing_aid_and_keeps_existing_aid(tmp_root):
+    connection = open_database(tmp_root)
+    repository = MetadataRepository(connection)
+    try:
+        repository.upsert_user(make_user_record())
+        repository.upsert_video(make_video_record(aid=None))
+        assert connection.execute("SELECT aid FROM videos").fetchone()[0] is None
+
+        repository.upsert_video(make_video_record())
+        assert connection.execute("SELECT aid FROM videos").fetchone()[0] == 1001
+
+        repository.upsert_video(make_video_record(aid=9999))
+        assert connection.execute("SELECT aid FROM videos").fetchone()[0] == 1001
+    finally:
+        connection.close()
+
+
+def test_cursor_resume_and_pending_limit(tmp_root):
+    connection = open_database(tmp_root)
+    repository = MetadataRepository(connection)
+    try:
+        _start_run(repository)
+        repository.record_page(
+            make_page_record(),
+            video=make_video_record(),
+            parts=[make_part_record(), make_part_record(page_index=1, cid=2002, title="第二集")],
+            discoveries=[make_discovery_record("BV1SINGLE")],
+            cursor=make_cursor_record(next_page=2),
+        )
+        repository.write_cursor(make_cursor_record(next_page=3, updated_at=130))
+        assert repository.read_cursor(MID).next_page == 3
+        assert [row["page_index"] for row in repository.list_pending_parts(limit=1)] == [0]
+
+        with repository.transaction():
+            repository.upsert_part(
+                make_part_record(page_index=1, cid=2002, title="第二集", status="metadata_collected")
+            )
+        assert [row["page_index"] for row in repository.list_pending_parts()] == [0]
+    finally:
+        connection.close()
+
+
+def test_finish_run_and_all_run_stats_are_derived_from_normalized_rows(tmp_root):
+    connection = open_database(tmp_root)
+    repository = MetadataRepository(connection)
+    try:
+        _start_run(repository)
+        repository.record_page(
+            make_page_record(),
+            video=make_video_record(),
+            parts=[make_part_record()],
+            discoveries=[make_discovery_record("BV1SINGLE")],
+        )
+        repository.finish_run("run-1", "complete", 300)
+        stats = repository.run_stats()
+        assert len(stats) == 1
+        assert stats[0]["outcome"] == "complete"
+        assert stats[0]["page_count"] == 1
+        assert stats[0]["video_count"] == 1
+    finally:
+        connection.close()
+
+
+def test_start_run_requires_a_foreign_key_parent(tmp_root):
+    connection = open_database(tmp_root)
+    repository = MetadataRepository(connection)
+    try:
+        with pytest.raises(sqlite3.IntegrityError):
+            repository.start_run(make_run_record())
+    finally:
+        connection.close()
diff --git a/bilibili-asr-archive/tests/test_storage_schema.py b/bilibili-asr-archive/tests/test_storage_schema.py
new file mode 100644
index 0000000..c91ac86
--- /dev/null
+++ b/bilibili-asr-archive/tests/test_storage_schema.py
@@ -0,0 +1,576 @@
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
+EXPECTED_TABLE_COLUMNS = {
+    "bilibili_users": ["mid", "display_name", "created_at", "updated_at"],
+    "videos": [
+        "bvid",
+        "aid",
+        "mid",
+        "title",
+        "pubdate",
+        "created_at",
+        "updated_at",
+    ],
+    "video_parts": [
+        "video_part_id",
+        "bvid",
+        "page_index",
+        "cid",
+        "title",
+        "duration_ms",
+        "processing_status",
+        "created_at",
+        "updated_at",
+    ],
+    "ingestion_runs": [
+        "run_id",
+        "mid",
+        "source_package",
+        "source_version",
+        "requested_start_page",
+        "requested_page_limit",
+        "started_at",
+        "finished_at",
+        "outcome",
+    ],
+    "ingestion_cursors": [
+        "mid",
+        "next_page",
+        "observed_total",
+        "state",
+        "last_error_code",
+        "updated_at",
+    ],
+    "ingestion_pages": [
+        "run_id",
+        "page_number",
+        "outcome",
+        "error_code",
+        "started_at",
+        "finished_at",
+    ],
+    "ingestion_discoveries": [
+        "run_id",
+        "page_number",
+        "bvid",
+        "source_position",
+        "discovered_at",
+    ],
+    "audio_objects": [
+        "audio_id",
+        "sha256",
+        "byte_size",
+        "format",
+        "duration_ms",
+        "storage_key",
+        "created_at",
+    ],
+    "part_audio_objects": [
+        "video_part_id",
+        "audio_id",
+        "acquired_at",
+        "acquisition_source",
+    ],
+    "asr_models": ["model_id", "model_name", "revision", "created_at"],
+    "transcripts": [
+        "transcript_id",
+        "video_part_id",
+        "source_kind",
+        "model_id",
+        "version",
+        "created_at",
+    ],
+    "transcript_segments": ["transcript_id", "ordinal", "start_ms", "end_ms", "text"],
+}
+EXPECTED_FOREIGN_KEYS = {
+    "videos": (("mid", "bilibili_users", "mid"),),
+    "video_parts": (("bvid", "videos", "bvid"),),
+    "ingestion_runs": (("mid", "bilibili_users", "mid"),),
+    "ingestion_cursors": (("mid", "bilibili_users", "mid"),),
+    "ingestion_pages": (("run_id", "ingestion_runs", "run_id"),),
+    "ingestion_discoveries": (
+        ("run_id", "ingestion_runs", "run_id"),
+        ("bvid", "videos", "bvid"),
+    ),
+    "part_audio_objects": (
+        ("video_part_id", "video_parts", "video_part_id"),
+        ("audio_id", "audio_objects", "audio_id"),
+    ),
+    "transcripts": (
+        ("video_part_id", "video_parts", "video_part_id"),
+        ("model_id", "asr_models", "model_id"),
+    ),
+    "transcript_segments": (("transcript_id", "transcripts", "transcript_id"),),
+}
+EXPECTED_UNIQUE_CONSTRAINTS = {
+    "videos": (("aid",),),
+    "video_parts": (("bvid", "page_index"),),
+    "audio_objects": (("sha256",), ("storage_key",)),
+    "asr_models": (("model_name", "revision"),),
+    "transcripts": (("video_part_id", "source_kind", "version"),),
+}
+EXPECTED_PRIMARY_KEY_INDEXES = {
+    "videos": (("bvid",),),
+    "ingestion_runs": (("run_id",),),
+    "ingestion_pages": (("run_id", "page_number"),),
+    "ingestion_discoveries": (("run_id", "page_number", "bvid"),),
+    "part_audio_objects": (("video_part_id", "audio_id"),),
+    "transcript_segments": (("transcript_id", "ordinal"),),
+}
+EXPECTED_CHECK_ENUMERATIONS = {
+    "video_parts": (
+        "processing_status IN ('discovered', 'metadata_collected', 'gone')",
+    ),
+    "ingestion_runs": (
+        "source_package = 'bilibili-api-python'",
+        "outcome IN ('running', 'complete', 'limited', 'risk_interrupted', 'failed')",
+    ),
+    "ingestion_cursors": (
+        "state IN ('ready', 'complete', 'limited', 'risk_interrupted')",
+    ),
+    "ingestion_pages": ("outcome IN ('ok', 'empty', 'risk_interrupted', 'failed')",),
+    "transcripts": ("source_kind IN ('subtitle-ai', 'subtitle-cc', 'asr-local')",),
+}
+EXPECTED_VIEW_WORK_ID_EXPRESSION = "vp.bvid || ':p' || vp.page_index AS work_id"
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
+        with pytest.raises(sqlite3.IntegrityError):
+            connection.execute(
+                "INSERT INTO ingestion_pages VALUES ('ghost-run', 1, 'ok', NULL, 1, 1)"
+            )
+        with pytest.raises(sqlite3.IntegrityError):
+            connection.execute(
+                "INSERT INTO ingestion_discoveries "
+                "VALUES ('ghost-run', 1, 'BVORPHAN', 0, 1)"
+            )
+
+        _insert_user_video_part(connection)
+        connection.execute(
+            "INSERT INTO ingestion_runs VALUES "
+            "('run-1', 23191782, 'bilibili-api-python', '1.0', 1, NULL, 1, NULL, 'running')"
+        )
+        with pytest.raises(sqlite3.IntegrityError):
+            connection.execute(
+                "INSERT INTO ingestion_discoveries "
+                "VALUES ('run-1', 1, 'BVUNKNOWN', 0, 1)"
+            )
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
+            f"INSERT INTO ingestion_cursors VALUES "
+            f"(23191782, 2, NULL, 'ready', '{'y' * 65}', 1)",
+            f"INSERT INTO ingestion_pages VALUES ('run', 3, 'failed', '{'x' * 65}', 1, 1)",
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
+
+
+def test_schema_inspection_matches_the_declared_contract(tmp_root):
+    connection = open_database(tmp_root)
+    try:
+        assert _table_names(connection) == BASE_TABLES | VIEWS
+
+        for table in BASE_TABLES:
+            columns = [
+                row["name"] for row in connection.execute(f"PRAGMA table_info({table})")
+            ]
+            assert columns == EXPECTED_TABLE_COLUMNS[table]
+            assert "work_id" not in columns
+
+            foreign_keys = {
+                (row["from"], row["table"], row["to"])
+                for row in connection.execute(f"PRAGMA foreign_key_list({table})")
+            }
+            assert foreign_keys == set(EXPECTED_FOREIGN_KEYS.get(table, ()))
+            for row in connection.execute(f"PRAGMA foreign_key_list({table})"):
+                assert row["on_delete"] == "RESTRICT"
+
+            unique_constraints = set()
+            primary_key_indexes = set()
+            for index in connection.execute(f"PRAGMA index_list({table})"):
+                indexed_columns = tuple(
+                    info["name"]
+                    for info in connection.execute(f"PRAGMA index_info({index['name']})")
+                )
+                if index["origin"] == "u":
+                    unique_constraints.add(indexed_columns)
+                elif index["origin"] == "pk":
+                    primary_key_indexes.add(indexed_columns)
+            assert unique_constraints == set(
+                EXPECTED_UNIQUE_CONSTRAINTS.get(table, ())
+            )
+            assert primary_key_indexes == set(
+                EXPECTED_PRIMARY_KEY_INDEXES.get(table, ())
+            )
+
+        for table, fragments in EXPECTED_CHECK_ENUMERATIONS.items():
+            ddl_row = connection.execute(
+                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
+                (table,),
+            ).fetchone()
+            normalized_ddl = " ".join(ddl_row[0].split())
+            for fragment in fragments:
+                assert fragment in normalized_ddl
+
+        for view in VIEWS:
+            ddl_row = connection.execute(
+                "SELECT sql FROM sqlite_master WHERE type = 'view' AND name = ?",
+                (view,),
+            ).fetchone()
+            normalized_ddl = " ".join(ddl_row[0].split())
+            if view in {"v_video_parts", "v_pending_metadata"}:
+                assert EXPECTED_VIEW_WORK_ID_EXPRESSION in normalized_ddl
+    finally:
+        connection.close()
+
+
+def test_views_compute_derived_values_across_users_videos_and_runs(tmp_root):
+    connection = open_database(tmp_root)
+    try:
+        connection.executescript(
+            """
+            INSERT INTO bilibili_users VALUES (23191782, '未明子', 1, 1);
+            INSERT INTO bilibili_users VALUES (42, '第二位用户', 1, 1);
+            INSERT INTO videos VALUES
+                ('BV1SINGLE', 1001, 23191782, '单集视频', 1700000000, 1, 1);
+            INSERT INTO videos VALUES
+                ('BV1MULTI', 1002, 42, '多集视频', 1700000001, 1, 1);
+            INSERT INTO videos VALUES
+                ('BV1GONE', NULL, 42, '已下架视频', 1700000002, 1, 1);
+            INSERT INTO video_parts(
+                bvid, page_index, cid, title, duration_ms, processing_status,
+                created_at, updated_at
+            ) VALUES ('BV1SINGLE', 0, 2001, '第一集', 1000, 'discovered', 1, 1);
+            INSERT INTO video_parts(
+                bvid, page_index, cid, title, duration_ms, processing_status,
+                created_at, updated_at
+            ) VALUES ('BV1MULTI', 0, 3001, '上篇', 2000, 'discovered', 1, 1);
+            INSERT INTO video_parts(
+                bvid, page_index, cid, title, duration_ms, processing_status,
+                created_at, updated_at
+            ) VALUES ('BV1MULTI', 1, 3002, '下篇', 3000, 'metadata_collected', 1, 1);
+            INSERT INTO video_parts(
+                bvid, page_index, cid, title, duration_ms, processing_status,
+                created_at, updated_at
+            ) VALUES ('BV1GONE', 0, 4001, '残片', 4000, 'gone', 1, 1);
+            INSERT INTO ingestion_runs VALUES
+                ('run-1', 23191782, 'bilibili-api-python', '1.0', 1, NULL, 1, NULL, 'running');
+            INSERT INTO ingestion_runs VALUES
+                ('run-2', 42, 'bilibili-api-python', '1.0', 1, NULL, 1, NULL, 'running');
+            INSERT INTO ingestion_pages VALUES ('run-1', 1, 'ok', NULL, 1, 2);
+            INSERT INTO ingestion_pages VALUES ('run-1', 2, 'empty', NULL, 3, 4);
+            INSERT INTO ingestion_discoveries VALUES ('run-1', 1, 'BV1SINGLE', 0, 5);
+            INSERT INTO ingestion_discoveries VALUES ('run-1', 2, 'BV1SINGLE', 0, 6);
+            INSERT INTO ingestion_discoveries VALUES ('run-1', 2, 'BV1MULTI', 1, 6);
+            """
+        )
+
+        part_rows = connection.execute(
+            "SELECT work_id, user_name, video_title, page_index, cid, part_title, "
+            "processing_status FROM v_video_parts ORDER BY work_id"
+        ).fetchall()
+        assert [row["work_id"] for row in part_rows] == [
+            "BV1GONE:p0",
+            "BV1MULTI:p0",
+            "BV1MULTI:p1",
+            "BV1SINGLE:p0",
+        ]
+        single = part_rows[3]
+        assert single["user_name"] == "未明子"
+        assert single["video_title"] == "单集视频"
+        multi = part_rows[2]
+        assert multi["user_name"] == "第二位用户"
+        assert multi["part_title"] == "下篇"
+        assert multi["processing_status"] == "metadata_collected"
+
+        stats = {
+            row["run_id"]: (row["page_count"], row["video_count"])
+            for row in connection.execute("SELECT * FROM v_ingestion_run_stats")
+        }
+        # run-1 has three discovery rows but only two distinct videos; run-2
+        # has neither pages nor discoveries and still reports zero counts.
+        assert stats == {"run-1": (2, 2), "run-2": (0, 0)}
+
+        pending = [
+            row["work_id"]
+            for row in connection.execute(
+                "SELECT work_id FROM v_pending_metadata ORDER BY work_id"
+            )
+        ]
+        assert pending == ["BV1MULTI:p0", "BV1SINGLE:p0"]
+    finally:
+        connection.close()
```
