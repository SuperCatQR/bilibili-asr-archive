# Task 2 Diff

Base: `5f22fc6e81371f79cd4f0660cc79eb7f8cae9bfa`
Head: `bf602b8`

```diff
diff --git a/bilibili-asr-archive/src/bili_asr/storage/database.py b/bilibili-asr-archive/src/bili_asr/storage/database.py
index 27df44a..c1772d3 100644
--- a/bilibili-asr-archive/src/bili_asr/storage/database.py
+++ b/bilibili-asr-archive/src/bili_asr/storage/database.py
@@ -1,13 +1,24 @@
-"""SQLite bootstrap for normalized Bilibili metadata storage."""
+"""SQLite bootstrap and normalized metadata repository."""
 
 from __future__ import annotations
 
+from contextlib import contextmanager
 from importlib import resources
 import math
 import os
 from pathlib import Path
 import sqlite3
-from typing import TypeAlias
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
 
 
 DatabaseConnection: TypeAlias = sqlite3.Connection
@@ -84,8 +95,432 @@ def open_database(path: str | os.PathLike[str]) -> DatabaseConnection:
     return connection
 
 
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
 __all__ = [
     "DatabaseConnection",
+    "MetadataRepository",
     "duration_to_ms",
     "initialize_schema",
     "normalize_page_index",
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
diff --git a/bilibili-asr-archive/tests/test_metadata_repository.py b/bilibili-asr-archive/tests/test_metadata_repository.py
new file mode 100644
index 0000000..6fdfda2
--- /dev/null
+++ b/bilibili-asr-archive/tests/test_metadata_repository.py
@@ -0,0 +1,356 @@
+"""Offline repository contract tests for normalized metadata persistence."""
+
+from __future__ import annotations
+
+from dataclasses import fields
+import sqlite3
+
+import pytest
+
+from bili_asr.storage.database import MetadataRepository, open_database
+from bili_asr.storage.models import (
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
+MID = 23191782
+
+
+def _user(*, display_name: str = "未明子", updated_at: int = 100) -> UserRecord:
+    return UserRecord(mid=MID, display_name=display_name, created_at=100, updated_at=updated_at)
+
+
+def _run(run_id: str = "run-1") -> IngestionRunRecord:
+    return IngestionRunRecord(
+        run_id=run_id,
+        mid=MID,
+        source_package="bilibili-api-python",
+        source_version="17.4.2",
+        requested_start_page=1,
+        requested_page_limit=3,
+        started_at=101,
+    )
+
+
+def _video(
+    bvid: str = "BV1SINGLE",
+    *,
+    title: str = "单集视频",
+    aid: int | None = 1001,
+    updated_at: int = 102,
+) -> VideoRecord:
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
+def _part(
+    bvid: str = "BV1SINGLE",
+    *,
+    page_index: int = 0,
+    cid: int = 2001,
+    title: str = "第一集",
+    status: str = "discovered",
+    updated_at: int = 103,
+) -> VideoPartRecord:
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
+def _page(
+    run_id: str = "run-1",
+    *,
+    page_number: int = 1,
+    outcome: str = "ok",
+    error_code: str | None = None,
+    started_at: int = 110,
+    finished_at: int = 111,
+) -> IngestionPageRecord:
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
+def _cursor(*, next_page: int = 2, updated_at: int = 112) -> CursorRecord:
+    return CursorRecord(
+        mid=MID,
+        next_page=next_page,
+        observed_total=2,
+        state="ready",
+        last_error_code=None,
+        updated_at=updated_at,
+    )
+
+
+def _discovery(
+    bvid: str,
+    *,
+    run_id: str = "run-1",
+    page_number: int = 1,
+    source_position: int = 0,
+    discovered_at: int = 104,
+) -> DiscoveryRecord:
+    return DiscoveryRecord(
+        run_id=run_id,
+        page_number=page_number,
+        bvid=bvid,
+        source_position=source_position,
+        discovered_at=discovered_at,
+    )
+
+
+def _start_run(repository: MetadataRepository, run_id: str = "run-1") -> None:
+    repository.upsert_user(_user())
+    repository.start_run(_run(run_id))
+
+
+def test_models_validate_scalars_and_compute_work_id_without_persisting_it():
+    part = _part()
+    assert part.work_id == "BV1SINGLE:p0"
+    assert "work_id" not in {field.name for field in fields(VideoPartRecord)}
+
+    with pytest.raises(ValueError):
+        _part(page_index=-1)
+    with pytest.raises(ValueError):
+        _part(cid=0)
+    with pytest.raises(ValueError):
+        _page(outcome="failed", error_code="raw traceback\n")
+    with pytest.raises(ValueError):
+        UserRecord(mid=MID, display_name="", created_at=1, updated_at=1)
+
+
+def test_record_page_persists_single_and_multipart_entities_in_locked_order(tmp_root):
+    connection = open_database(tmp_root)
+    repository = MetadataRepository(connection)
+    try:
+        _start_run(repository)
+        multipart = _video("BV1MULTI", title="多集视频", aid=1002)
+        page = _page()
+        repository.record_page(
+            page,
+            user=_user(),
+            videos=[_video(), multipart],
+            parts=[
+                _part(),
+                _part("BV1MULTI", page_index=0, cid=3001, title="上篇"),
+                _part("BV1MULTI", page_index=1, cid=3002, title="下篇"),
+            ],
+            discoveries=[
+                _discovery("BV1SINGLE"),
+                _discovery("BV1MULTI", source_position=1),
+            ],
+            cursor=_cursor(),
+        )
+
+        assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 2
+        assert connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0] == 3
+        assert connection.execute("SELECT COUNT(*) FROM ingestion_discoveries").fetchone()[0] == 2
+        assert connection.execute("SELECT COUNT(*) FROM ingestion_pages").fetchone()[0] == 1
+        assert repository.read_cursor(MID) == _cursor()
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
+            _page(),
+            user=_user(),
+            video=_video(),
+            parts=[_part()],
+            discoveries=[_discovery("BV1SINGLE")],
+            cursor=_cursor(),
+        )
+
+        repository.record_page(
+            _page(finished_at=120),
+            user=_user(display_name="未明子（更新）", updated_at=119),
+            video=_video(title="更新后的标题", updated_at=119),
+            parts=[_part(title="更新后的分集标题", updated_at=119)],
+            discoveries=[_discovery("BV1SINGLE", discovered_at=119)],
+            cursor=_cursor(updated_at=120),
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
+            _page("run-2"),
+            video=_video(title="同一视频的第二次发现"),
+            parts=[_part()],
+            discoveries=[_discovery("BV1SINGLE", run_id="run-2")],
+            cursor=_cursor(updated_at=130),
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
+            _page(),
+            video=_video(),
+            parts=[_part()],
+            discoveries=[_discovery("BV1SINGLE")],
+            cursor=_cursor(),
+        )
+        failed_page = _page(
+            page_number=2,
+            outcome="failed",
+            error_code="foreign_key",
+            started_at=200,
+            finished_at=201,
+        )
+        with pytest.raises(sqlite3.IntegrityError):
+            repository.record_page(
+                failed_page,
+                user=_user(display_name="must roll back", updated_at=200),
+                video=_video(title="must roll back", updated_at=200),
+                parts=[_part("BV-MISSING", title="orphan")],
+                cursor=_cursor(next_page=3, updated_at=201),
+            )
+
+        assert repository.read_cursor(MID) == _cursor()
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
+                repository.upsert_video(_video("BV-ORPHAN"))
+
+        with repository.transaction():
+            repository.upsert_user(_user())
+            repository.upsert_video(_video())
+            repository.upsert_part(_part())
+
+        with pytest.raises(sqlite3.IntegrityError):
+            connection.execute("DELETE FROM bilibili_users WHERE mid = ?", (MID,))
+        with pytest.raises(sqlite3.IntegrityError):
+            connection.execute("DELETE FROM videos WHERE bvid = 'BV1SINGLE'")
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
+            _page(),
+            video=_video(),
+            parts=[_part(), _part(page_index=1, cid=2002, title="第二集")],
+            discoveries=[_discovery("BV1SINGLE")],
+            cursor=_cursor(next_page=2),
+        )
+        repository.write_cursor(_cursor(next_page=3, updated_at=130))
+        assert repository.read_cursor(MID).next_page == 3
+        assert [row["page_index"] for row in repository.list_pending_parts(limit=1)] == [0]
+
+        with repository.transaction():
+            repository.upsert_part(_part(page_index=1, cid=2002, title="第二集", status="metadata_collected"))
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
+            _page(),
+            video=_video(),
+            parts=[_part()],
+            discoveries=[_discovery("BV1SINGLE")],
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
+            repository.start_run(_run())
+    finally:
+        connection.close()
+
```
