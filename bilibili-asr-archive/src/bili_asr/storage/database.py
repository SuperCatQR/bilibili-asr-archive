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
    ALLOWED_RUN_OUTCOMES,
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
_TERMINAL_RUN_OUTCOMES = ALLOWED_RUN_OUTCOMES - frozenset({"running"})
_SCHEMA_RESOURCE = resources.files(__package__).joinpath("schema.sql")
_TRANSCRIPT_SCHEMA_RESOURCE = resources.files(__package__).joinpath(
    "schema-transcripts.sql"
)
# The columns and objects only the transcript contract has: the bootstrap
# decision reads the columns, the capability guard reads both.
_TRANSCRIPT_CONTRACT_COLUMNS = frozenset({"language", "content_sha256"})
_SUBTITLE_SCHEMA_OBJECTS = (
    "acquisition_attempts",
    "acquisition_runs",
    "v_pending_subtitles",
)


class SchemaContractError(RuntimeError):
    """Raised when a database does not carry the transcript-schema contract.

    The archive database is rebuildable by policy, so there is no migration
    path: callers report the rebuild procedure instead of upgrading in place.
    """


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
    """Accept either an archive root or an explicit SQLite database path.

    ``:memory:`` opens an unnamed in-memory database. URI strings are not
    interpreted: a ``file:``-prefixed value is handled as an ordinary file
    name like any other explicit path.
    """
    value = os.fspath(path)
    if value == ":memory:":
        return value

    candidate = Path(value)
    if candidate.is_dir() or (
        not candidate.exists() and candidate.suffix.lower() not in _DATABASE_SUFFIXES
    ):
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate / _ARCHIVE_DATABASE_NAME
    candidate.parent.mkdir(parents=True, exist_ok=True)
    return candidate


def _transcripts_columns(connection: sqlite3.Connection) -> frozenset[str]:
    """Return the column names of ``transcripts``; empty when it is absent."""
    return frozenset(
        row[1] for row in connection.execute("PRAGMA table_info(transcripts)")
    )


def _schema_object_names(connection: sqlite3.Connection) -> frozenset[str]:
    """Return every table and view name the database declares."""
    return frozenset(
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
        )
    )


def _accepts_transcript_script(connection: sqlite3.Connection) -> bool:
    """Report whether the transcript schema script belongs in this database.

    True for a fresh database (``transcripts`` absent) and for a database that
    already carries the transcript columns; False for a database created
    before this contract, which keeps the shape it has.
    """
    columns = _transcripts_columns(connection)
    return not columns or _TRANSCRIPT_CONTRACT_COLUMNS <= columns


def _has_subtitle_schema(connection: sqlite3.Connection) -> bool:
    """Report whether the transcript-schema contract is present."""
    if not _TRANSCRIPT_CONTRACT_COLUMNS <= _transcripts_columns(connection):
        return False
    return set(_SUBTITLE_SCHEMA_OBJECTS) <= _schema_object_names(connection)


def initialize_schema(connection: sqlite3.Connection) -> sqlite3.Connection:
    """Initialize ``connection`` from the checked-in schema scripts, idempotently.

    Enables foreign-key enforcement, executes ``schema.sql``, and then applies
    ``schema-transcripts.sql`` only when ``transcripts`` is absent or already
    carries the transcript columns.  A database created before that contract
    keeps the shape it has: the transcript script is skipped, so nothing
    half-applies and the metadata path keeps working.  Commits the scripts.
    """
    connection.execute("PRAGMA foreign_keys = ON")
    if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise sqlite3.DatabaseError("SQLite foreign-key enforcement could not be enabled")
    connection.executescript(_SCHEMA_RESOURCE.read_text(encoding="utf-8"))
    if _accepts_transcript_script(connection):
        connection.executescript(
            _TRANSCRIPT_SCHEMA_RESOURCE.read_text(encoding="utf-8")
        )
    connection.commit()
    return connection


def require_subtitle_schema(connection: sqlite3.Connection) -> None:
    """Require the transcript-schema contract on ``connection``.

    The check is structural — the ``transcripts`` columns only this contract
    has, plus the process-record tables and the pending view — because a stale
    version stamp can lie and a missing column cannot.  A database that
    predates the contract raises :class:`SchemaContractError`; the caller
    reports the rebuild procedure and stops.
    """
    if _has_subtitle_schema(connection):
        return
    raise SchemaContractError(
        "archive database predates the transcript schema; rebuild it "
        "(delete archive.db and re-run fetch-meta)"
    )


def open_database(path: str | os.PathLike[str]) -> DatabaseConnection:
    """Open and initialize ``archive.db`` below an archive root.

    Existing directories are interpreted as archive roots. Paths ending in a
    normal SQLite suffix (``.db``, ``.sqlite``, or ``.sqlite3``) are treated as
    explicit database files, which is useful for tests and callers with a
    custom filename; ``:memory:`` opens an in-memory database. URI strings are
    not interpreted, so callers pass plain paths. Connections use an explicit
    deferred transaction mode; callers can use ``with connection:`` for
    atomic write groups.
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

    Commit boundaries per public method:

    - ``start_run`` commits its own insert so a failed page can roll back
      without deleting the run parent.
    - ``finish_run`` commits its own terminal transition.
    - ``record_page`` owns one transaction for its arguments and commits it,
      or rolls it back and re-raises on a write failure; with no payload
      arguments it still commits its own single-write transaction — either
      the ``'failed'`` evidence transaction (page row plus the run's failure
      transition) or the ok/empty/``risk_interrupted`` page-outcome write.
    - ``upsert_user``, ``upsert_video``, ``upsert_part``, ``record_discovery``
      and ``write_cursor`` execute SQL without committing, so a caller can
      group them in one transaction through :meth:`transaction`.
    - ``read_cursor``, ``list_pending_parts`` and ``run_stats`` never write
      or commit.

    Read paths return two shapes: ``read_cursor`` converts its single row
    into a typed ``CursorRecord`` (``None`` when absent), while
    ``list_pending_parts`` and ``run_stats`` return raw ``sqlite3.Row``
    view data — a list for the no-argument form, a single row or ``None``
    for the keyed form. Read-path arguments follow the module-wide
    validation discipline: type errors raise ``TypeError`` and value
    errors raise ``ValueError``.

    Do not compose ``start_run``, ``finish_run`` or ``record_page`` inside a
    :meth:`transaction` group: each commits independently and would commit
    the enclosing group's earlier writes.

    The connection must come with ``row_factory = sqlite3.Row`` and
    ``PRAGMA foreign_keys`` enabled — exactly the state :func:`open_database`
    establishes; the constructor rejects anything else.
    """

    def __init__(self, connection: sqlite3.Connection):
        if not isinstance(connection, sqlite3.Connection):
            raise TypeError("connection must be a sqlite3.Connection")
        if connection.row_factory is not sqlite3.Row:
            raise TypeError("connection must use the sqlite3.Row row_factory")
        if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            raise ValueError("connection must have PRAGMA foreign_keys enabled")
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
        """Insert or update a video's current canonical display fields.

        The stored ``aid`` is a stable identifier: the first non-``None``
        ``aid`` wins — a stored ``NULL`` is backfilled from the incoming
        record, and a known ``aid`` is never overwritten.
        """
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
        """Insert or update a normalized part and return its local ID.

        ``video_part_id`` is allocated by the repository, so the record must
        carry ``video_part_id=None``; a non-``None`` id raises ``ValueError``.
        Conflicts on ``(bvid, page_index)`` update only the current display
        fields and non-key facts.
        """
        if not isinstance(part, VideoPartRecord):
            raise TypeError("part must be a VideoPartRecord")
        if part.video_part_id is not None:
            raise ValueError("upsert_part allocates video_part_id; it must be None")
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
        """Insert one new run record.

        ``run_id`` is the primary key and is never reused: a duplicate raises
        ``sqlite3.IntegrityError``.
        """
        if not isinstance(run, IngestionRunRecord):
            raise TypeError("run must be an IngestionRunRecord")
        self.connection.execute(
            """
            INSERT INTO ingestion_runs(
                run_id, mid, source_package, source_version, requested_start_page,
                requested_page_limit, started_at, finished_at, outcome
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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

    def finish_run(self, run: IngestionRunRecord) -> None:
        """Finish a run with its terminal outcome and finish timestamp.

        The canonical form is ``finish_run(IngestionRunRecord(...))`` with a
        terminal ``outcome`` and an integer ``finished_at``. The ordering
        baseline is the run's stored ``started_at``, not the record's own
        ``started_at`` field. Re-finishing is rejected: a run whose stored
        outcome is already terminal raises ``sqlite3.IntegrityError``.
        """
        if not isinstance(run, IngestionRunRecord):
            raise TypeError("run must be an IngestionRunRecord")
        run_row = self.connection.execute(
            "SELECT started_at, outcome FROM ingestion_runs WHERE run_id = ?",
            (run.run_id,),
        ).fetchone()
        if run_row is None:
            raise sqlite3.IntegrityError(f"unknown run_id: {run.run_id}")
        if run_row["outcome"] != "running":
            raise sqlite3.IntegrityError(
                f"run {run.run_id} already finished with outcome {run_row['outcome']}"
            )
        if run.outcome not in _TERMINAL_RUN_OUTCOMES:
            raise ValueError("finish_run requires a terminal run outcome")
        if run.finished_at is None:
            raise ValueError("finished_at is required when finishing a run")
        started_at = int(run_row["started_at"])
        if run.finished_at < started_at:
            raise ValueError("finished_at must not precede started_at")
        self.connection.execute(
            "UPDATE ingestion_runs SET finished_at = ?, outcome = ? WHERE run_id = ?",
            (run.finished_at, run.outcome, run.run_id),
        )
        if self.connection.execute("SELECT changes()").fetchone()[0] != 1:
            raise sqlite3.IntegrityError(f"unknown run_id: {run.run_id}")
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
        videos: Iterable[VideoRecord] = (),
        parts: Iterable[VideoPartRecord] = (),
        discoveries: Iterable[DiscoveryRecord] = (),
        cursor: CursorRecord | None = None,
    ) -> None:
        """Record one page outcome, optionally with its complete payload.

        With payload arguments the method owns one transaction and applies the
        locked parent-before-child order: user, videos, parts, discoveries,
        cursor, page outcome, commit. If any write fails, the whole
        transaction is rolled back and the exception is re-raised; the prior
        cursor and entities are unchanged. Recording the resulting failure is
        the caller's step: build a fresh ``IngestionPageRecord`` with
        ``outcome='failed'`` and a bounded ``error_code`` and call this method
        again with no payload arguments.

        A ``'failed'`` page therefore never carries payloads — supplying
        payload arguments with ``outcome='failed'`` raises ``ValueError``
        before any write. A no-payload ``'failed'`` page is recorded in its
        own committed transaction together with the parent run's failure
        transition. When that run is already terminal, the page evidence is
        still persisted while the run's outcome and ``finished_at`` stay
        unchanged. A no-payload page with a non-failed outcome (``ok``,
        ``empty``, ``risk_interrupted``) likewise commits its own
        single-write transaction for the page-outcome row.

        The failure transition applies only while the run is still
        ``running`` and uses the run's stored ``started_at`` as its ordering
        baseline — the same DB baseline as :meth:`finish_run`: a failed page
        whose ``finished_at`` precedes the run's stored ``started_at`` is
        rejected with ``ValueError`` and nothing is persisted.
        """
        if not isinstance(page, IngestionPageRecord):
            raise TypeError("page must be an IngestionPageRecord")
        video_records = tuple(videos)
        part_records = tuple(parts)
        discovery_records = tuple(discoveries)
        has_payload = (
            user is not None
            or bool(video_records)
            or bool(part_records)
            or bool(discovery_records)
            or cursor is not None
        )
        if page.outcome == "failed" and has_payload:
            raise ValueError("a failed page is recorded without payload arguments")

        if not has_payload:
            if page.outcome == "failed":
                self._record_failed_page(page)
            else:
                with self.transaction():
                    self._record_page(page)
            return

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

    def _record_failed_page(self, page: IngestionPageRecord) -> None:
        """Persist only bounded failure state after a rolled-back page.

        The page evidence is upserted in the same committed transaction as
        the parent run's failure transition, which applies only while the
        run is still ``'running'`` — a late or stale failed page can never
        regress a terminal outcome or move ``finished_at`` backwards. The
        transition validates against the run's stored ``started_at`` (the
        same DB baseline as :meth:`finish_run`): a page clock below the
        run's start raises ``ValueError`` and nothing is persisted.
        """
        with self.transaction():
            run_row = self.connection.execute(
                "SELECT started_at, outcome FROM ingestion_runs WHERE run_id = ?",
                (page.run_id,),
            ).fetchone()
            if (
                run_row is not None
                and run_row["outcome"] == "running"
                and page.finished_at < int(run_row["started_at"])
            ):
                raise ValueError("finished_at must not precede started_at")
            self._record_page(page)
            self.connection.execute(
                """
                UPDATE ingestion_runs
                SET outcome = 'failed', finished_at = ?
                WHERE run_id = ? AND outcome = 'running'
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
        """Read the current one-based cursor for a user.

        Returns a typed ``CursorRecord`` or ``None`` when the user has no
        cursor row.
        """
        if isinstance(mid, bool) or not isinstance(mid, int):
            raise TypeError("mid must be an integer")
        if mid < 1:
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
        """Return discovered parts in deterministic work order.

        Rows come straight from the ``v_pending_metadata`` view.
        """
        if limit is not None:
            if isinstance(limit, bool) or not isinstance(limit, int):
                raise TypeError("limit must be an integer or None")
            if limit < 1:
                raise ValueError("limit must be a positive integer")
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
        """Read normalized run/page/video counts from the repository view.

        Returns one ``v_ingestion_run_stats`` row for a ``run_id``, or a
        list of every run's rows when ``run_id`` is ``None``.
        """
        if run_id is None:
            return list(
                self.connection.execute(
                    "SELECT * FROM v_ingestion_run_stats ORDER BY run_id"
                ).fetchall()
            )
        if not isinstance(run_id, str):
            raise TypeError("run_id must be a string or None")
        if not run_id.strip():
            raise ValueError("run_id must be a non-empty string")
        return self.connection.execute(
            "SELECT * FROM v_ingestion_run_stats WHERE run_id = ?", (run_id,)
        ).fetchone()


__all__ = [
    "DatabaseConnection",
    "MetadataRepository",
    "SchemaContractError",
    "duration_to_ms",
    "initialize_schema",
    "normalize_page_index",
    "open_database",
    "require_subtitle_schema",
]
