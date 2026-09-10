"""SQLite bootstrap and normalized metadata repository."""

from __future__ import annotations

from contextlib import contextmanager
from importlib import resources
import math
import os
from pathlib import Path
import sqlite3
from typing import Iterable, Iterator, TypeAlias

from .models import (
    CursorRecord,
    DiscoveryRecord,
    IngestionPageRecord,
    IngestionRunRecord,
    UserRecord,
    VideoPartRecord,
    VideoRecord,
)


DatabaseConnection: TypeAlias = sqlite3.Connection
_ARCHIVE_DATABASE_NAME = "archive.db"
_DATABASE_SUFFIXES = frozenset({".db", ".sqlite", ".sqlite3"})
_SCHEMA_RESOURCE = resources.files(__package__).joinpath("schema.sql")


def duration_to_ms(seconds: int | float) -> int:
    """Convert a non-negative duration in seconds to floored milliseconds."""
    if isinstance(seconds, bool):
        raise TypeError("duration must be numeric")
    try:
        value = float(seconds)
    except (TypeError, ValueError) as exc:
        raise TypeError("duration must be numeric") from exc
    if not math.isfinite(value) or value < 0:
        raise ValueError("duration must be finite and non-negative")
    return math.floor(value * 1000)


def normalize_page_index(page_number: int) -> int:
    """Convert a one-based Bilibili page number to a zero-based part index."""
    if isinstance(page_number, bool) or not isinstance(page_number, int):
        raise TypeError("page number must be an integer")
    if page_number < 1:
        raise ValueError("page number must be at least 1")
    return page_number - 1


def _resolve_database_path(path: str | os.PathLike[str]) -> str | os.PathLike[str]:
    """Accept either an archive root or an explicit SQLite database path."""
    value = os.fspath(path)
    if value in {":memory:"} or (isinstance(value, str) and value.startswith("file:")):
        return value

    candidate = Path(value)
    if candidate.is_dir() or (
        not candidate.exists() and candidate.suffix.lower() not in _DATABASE_SUFFIXES
    ):
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate / _ARCHIVE_DATABASE_NAME
    candidate.parent.mkdir(parents=True, exist_ok=True)
    return candidate


def initialize_schema(connection: sqlite3.Connection) -> sqlite3.Connection:
    """Initialize ``connection`` from the checked-in schema, idempotently."""
    connection.execute("PRAGMA foreign_keys = ON")
    if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise sqlite3.DatabaseError("SQLite foreign-key enforcement could not be enabled")
    connection.executescript(_SCHEMA_RESOURCE.read_text(encoding="utf-8"))
    connection.commit()
    return connection


def open_database(path: str | os.PathLike[str]) -> DatabaseConnection:
    """Open and initialize ``archive.db`` below an archive root.

    Existing directories are interpreted as archive roots. Paths ending in a
    normal SQLite suffix (``.db``, ``.sqlite``, or ``.sqlite3``) are treated as
    explicit database files, which is useful for tests and callers with a
    custom filename. Connections use an explicit deferred transaction mode;
    callers can use ``with connection:`` for atomic write groups.
    """
    database_path = _resolve_database_path(path)
    connection = sqlite3.connect(database_path, isolation_level="DEFERRED")
    connection.row_factory = sqlite3.Row
    try:
        initialize_schema(connection)
    except BaseException:
        connection.close()
        raise
    return connection


class MetadataRepository:
    """Repository for normalized metadata and ingestion state.

    The low-level methods execute SQL without committing so a caller can group
    them in one transaction. ``record_page`` is the page-level convenience
    operation: when supplied with page payloads it owns the transaction and
    applies the locked parent-before-child ordering. The connection's context
    manager is also available through :meth:`transaction` for callers that
    need to compose the lower-level methods themselves.
    """

    def __init__(self, connection: sqlite3.Connection):
        if not isinstance(connection, sqlite3.Connection):
            raise TypeError("connection must be a sqlite3.Connection")
        self.connection = connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Commit the enclosed repository operations or roll them back."""
        try:
            yield self.connection
        except BaseException:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()

    def upsert_user(self, user: UserRecord) -> None:
        """Insert or update the current display label for a user."""
        if not isinstance(user, UserRecord):
            raise TypeError("user must be a UserRecord")
        self.connection.execute(
            """
            INSERT INTO bilibili_users(mid, display_name, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(mid) DO UPDATE SET
                display_name = excluded.display_name,
                updated_at = excluded.updated_at
            """,
            (user.mid, user.display_name, user.created_at, user.updated_at),
        )

    def upsert_video(self, video: VideoRecord) -> None:
        """Insert or update a video's current canonical display fields."""
        if not isinstance(video, VideoRecord):
            raise TypeError("video must be a VideoRecord")
        self.connection.execute(
            """
            INSERT INTO videos(
                bvid, aid, mid, title, pubdate, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(bvid) DO UPDATE SET
                aid = COALESCE(videos.aid, excluded.aid),
                title = excluded.title,
                updated_at = excluded.updated_at
            """,
            (
                video.bvid,
                video.aid,
                video.mid,
                video.title,
                video.pubdate,
                video.created_at,
                video.updated_at,
            ),
        )

    def upsert_part(self, part: VideoPartRecord) -> int:
        """Insert or update a normalized part and return its local ID."""
        if not isinstance(part, VideoPartRecord):
            raise TypeError("part must be a VideoPartRecord")
        if part.video_part_id is None:
            self.connection.execute(
                """
                INSERT INTO video_parts(
                    bvid, page_index, cid, title, duration_ms, processing_status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(bvid, page_index) DO UPDATE SET
                    title = excluded.title,
                    duration_ms = excluded.duration_ms,
                    processing_status = excluded.processing_status,
                    updated_at = excluded.updated_at
                """,
                (
                    part.bvid,
                    part.page_index,
                    part.cid,
                    part.title,
                    part.duration_ms,
                    part.processing_status,
                    part.created_at,
                    part.updated_at,
                ),
            )
        else:
            self.connection.execute(
                """
                INSERT INTO video_parts(
                    video_part_id, bvid, page_index, cid, title, duration_ms,
                    processing_status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(bvid, page_index) DO UPDATE SET
                    title = excluded.title,
                    duration_ms = excluded.duration_ms,
                    processing_status = excluded.processing_status,
                    updated_at = excluded.updated_at
                """,
                (
                    part.video_part_id,
                    part.bvid,
                    part.page_index,
                    part.cid,
                    part.title,
                    part.duration_ms,
                    part.processing_status,
                    part.created_at,
                    part.updated_at,
                ),
            )

        row = self.connection.execute(
            """
            SELECT video_part_id
            FROM video_parts
            WHERE bvid = ? AND page_index = ?
            """,
            (part.bvid, part.page_index),
        ).fetchone()
        if row is None:  # pragma: no cover - the preceding INSERT guarantees this
            raise sqlite3.DatabaseError("upserted video part could not be read back")
        return int(row[0])

    def start_run(self, run: IngestionRunRecord) -> None:
        """Insert a run record, preserving an existing run on retry."""
        if not isinstance(run, IngestionRunRecord):
            raise TypeError("run must be an IngestionRunRecord")
        self.connection.execute(
            """
            INSERT INTO ingestion_runs(
                run_id, mid, source_package, source_version, requested_start_page,
                requested_page_limit, started_at, finished_at, outcome
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO NOTHING
            """,
            (
                run.run_id,
                run.mid,
                run.source_package,
                run.source_version,
                run.requested_start_page,
                run.requested_page_limit,
                run.started_at,
                run.finished_at,
                run.outcome,
            ),
        )
        # A run is a lifecycle parent for page transactions. Commit its start
        # independently so a failed page can roll back without deleting it.
        self.connection.commit()

    def finish_run(
        self,
        run: IngestionRunRecord | str,
        outcome: str | None = None,
        finished_at: int | None = None,
    ) -> None:
        """Set a run's terminal/current outcome.

        The preferred form is ``finish_run(IngestionRunRecord(...))``. A scalar
        compatibility form, ``finish_run(run_id, outcome, finished_at)``, is
        provided for the ingestion service's terminal transition.
        """
        if isinstance(run, IngestionRunRecord):
            run_id = run.run_id
            resolved_outcome = run.outcome
            resolved_finished_at = run.finished_at
            if resolved_finished_at is None:
                raise ValueError("finished_at is required when finishing a run")
            started_at = run.started_at
        elif isinstance(run, str):
            run_id = run
            if not run_id.strip():
                raise ValueError("run_id must not be empty")
            if outcome is None or finished_at is None:
                raise ValueError("outcome and finished_at are required")
            resolved_outcome = outcome
            resolved_finished_at = finished_at
            started_row = self.connection.execute(
                "SELECT started_at FROM ingestion_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if started_row is None:
                raise sqlite3.IntegrityError(f"unknown run_id: {run_id}")
            started_at = int(started_row[0])
        else:
            raise TypeError("run must be an IngestionRunRecord or run ID")

        if resolved_outcome not in {
            "complete",
            "limited",
            "risk_interrupted",
            "failed",
        }:
            raise ValueError("finish_run requires a terminal run outcome")
        if not isinstance(resolved_finished_at, int) or isinstance(resolved_finished_at, bool):
            raise TypeError("finished_at must be an integer")
        if resolved_finished_at < started_at:
            raise ValueError("finished_at must not precede started_at")
        self.connection.execute(
            "UPDATE ingestion_runs SET finished_at = ?, outcome = ? WHERE run_id = ?",
            (resolved_finished_at, resolved_outcome, run_id),
        )
        if self.connection.execute("SELECT changes()").fetchone()[0] != 1:
            raise sqlite3.IntegrityError(f"unknown run_id: {run_id}")
        self.connection.commit()

    def _record_page(self, page: IngestionPageRecord) -> None:
        self.connection.execute(
            """
            INSERT INTO ingestion_pages(
                run_id, page_number, outcome, error_code, started_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id, page_number) DO UPDATE SET
                outcome = excluded.outcome,
                error_code = excluded.error_code,
                started_at = excluded.started_at,
                finished_at = excluded.finished_at
            """,
            (
                page.run_id,
                page.page_number,
                page.outcome,
                page.error_code,
                page.started_at,
                page.finished_at,
            ),
        )

    def record_page(
        self,
        page: IngestionPageRecord,
        user: UserRecord | None = None,
        video: VideoRecord | Iterable[VideoRecord] | None = None,
        parts: Iterable[VideoPartRecord] = (),
        discoveries: Iterable[DiscoveryRecord] = (),
        cursor: CursorRecord | None = None,
        *,
        videos: Iterable[VideoRecord] = (),
    ) -> None:
        """Record a page, optionally atomically persisting its complete payload.

        With payload arguments this method performs the locked order: user,
        videos, parts, discoveries, cursor, page outcome, commit. If any write
        fails, the page transaction is rolled back. When the supplied page has
        ``outcome='failed'``, its bounded page/run failure outcome is then
        written in a separate transaction without persisting exception text.
        """
        if not isinstance(page, IngestionPageRecord):
            raise TypeError("page must be an IngestionPageRecord")
        video_records = tuple(videos)
        if isinstance(video, VideoRecord):
            video_records = (video, *video_records)
        elif video is not None:
            video_records = (*tuple(video), *video_records)
        part_records = tuple(parts)
        discovery_records = tuple(discoveries)
        has_payload = (
            user is not None
            or bool(video_records)
            or bool(part_records)
            or bool(discovery_records)
            or cursor is not None
        )
        if not has_payload:
            if page.outcome == "failed":
                self._record_failed_page(page)
            else:
                with self.transaction():
                    self._record_page(page)
            return

        try:
            with self.transaction():
                if user is not None:
                    self.upsert_user(user)
                for video_record in video_records:
                    self.upsert_video(video_record)
                for part in part_records:
                    self.upsert_part(part)
                for discovery in discovery_records:
                    self.record_discovery(discovery)
                if cursor is not None:
                    self.write_cursor(cursor)
                self._record_page(page)
        except BaseException:
            if page.outcome == "failed":
                try:
                    self._record_failed_page(page)
                except sqlite3.Error:
                    # Preserve the original page error; a missing run cannot be
                    # repaired by inventing a relationship or error detail.
                    self.connection.rollback()
            raise

    def _record_failed_page(self, page: IngestionPageRecord) -> None:
        """Persist only bounded failure state after a rolled-back page."""
        with self.transaction():
            self._record_page(page)
            self.connection.execute(
                """
                UPDATE ingestion_runs
                SET outcome = 'failed', finished_at = ?
                WHERE run_id = ?
                """,
                (page.finished_at, page.run_id),
            )

    def record_discovery(self, discovery: DiscoveryRecord) -> None:
        """Insert or update one run/page/video discovery relationship."""
        if not isinstance(discovery, DiscoveryRecord):
            raise TypeError("discovery must be a DiscoveryRecord")
        self.connection.execute(
            """
            INSERT INTO ingestion_discoveries(
                run_id, page_number, bvid, source_position, discovered_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(run_id, page_number, bvid) DO UPDATE SET
                source_position = excluded.source_position,
                discovered_at = excluded.discovered_at
            """,
            (
                discovery.run_id,
                discovery.page_number,
                discovery.bvid,
                discovery.source_position,
                discovery.discovered_at,
            ),
        )

    def read_cursor(self, mid: int) -> CursorRecord | None:
        """Read the current one-based cursor for a user."""
        if isinstance(mid, bool) or not isinstance(mid, int) or mid < 1:
            raise ValueError("mid must be a positive integer")
        row = self.connection.execute(
            """
            SELECT mid, next_page, observed_total, state, last_error_code, updated_at
            FROM ingestion_cursors
            WHERE mid = ?
            """,
            (mid,),
        ).fetchone()
        if row is None:
            return None
        return CursorRecord(
            mid=int(row["mid"]),
            next_page=int(row["next_page"]),
            observed_total=(
                None if row["observed_total"] is None else int(row["observed_total"])
            ),
            state=str(row["state"]),
            last_error_code=(
                None if row["last_error_code"] is None else str(row["last_error_code"])
            ),
            updated_at=int(row["updated_at"]),
        )

    def write_cursor(self, cursor: CursorRecord) -> None:
        """Insert or replace the resumable cursor for a user."""
        if not isinstance(cursor, CursorRecord):
            raise TypeError("cursor must be a CursorRecord")
        self.connection.execute(
            """
            INSERT INTO ingestion_cursors(
                mid, next_page, observed_total, state, last_error_code, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(mid) DO UPDATE SET
                next_page = excluded.next_page,
                observed_total = excluded.observed_total,
                state = excluded.state,
                last_error_code = excluded.last_error_code,
                updated_at = excluded.updated_at
            """,
            (
                cursor.mid,
                cursor.next_page,
                cursor.observed_total,
                cursor.state,
                cursor.last_error_code,
                cursor.updated_at,
            ),
        )

    def list_pending_parts(self, limit: int | None = None) -> list[sqlite3.Row]:
        """Return discovered parts in deterministic work order."""
        if limit is not None:
            if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
                raise ValueError("limit must be a positive integer or None")
            query = (
                "SELECT * FROM v_pending_metadata "
                "ORDER BY bvid, page_index LIMIT ?"
            )
            return list(self.connection.execute(query, (limit,)).fetchall())
        return list(
            self.connection.execute(
                "SELECT * FROM v_pending_metadata ORDER BY bvid, page_index"
            ).fetchall()
        )

    def run_stats(self, run_id: str | None = None) -> sqlite3.Row | list[sqlite3.Row] | None:
        """Read normalized run/page/video counts from the repository view."""
        if run_id is None:
            return list(
                self.connection.execute(
                    "SELECT * FROM v_ingestion_run_stats ORDER BY run_id"
                ).fetchall()
            )
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run_id must be a non-empty string or None")
        return self.connection.execute(
            "SELECT * FROM v_ingestion_run_stats WHERE run_id = ?", (run_id,)
        ).fetchone()


__all__ = [
    "DatabaseConnection",
    "MetadataRepository",
    "duration_to_ms",
    "initialize_schema",
    "normalize_page_index",
    "open_database",
]
