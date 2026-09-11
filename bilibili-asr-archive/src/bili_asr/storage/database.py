"""SQLite bootstrap and the normalized metadata and transcript repositories."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
from importlib import resources
import json
import math
import os
from pathlib import Path
import sqlite3
from typing import Iterable, Iterator, TypeAlias

from .models import (
    ALLOWED_ATTEMPT_OUTCOMES,
    ALLOWED_CAPTION_SOURCE_KINDS,
    ALLOWED_RUN_OUTCOMES,
    ALLOWED_SOURCE_KINDS,
    MAX_TIMELINE_MS,
    AcquisitionRunRecord,
    CursorRecord,
    DiscoveryRecord,
    IngestionPageRecord,
    IngestionRunRecord,
    TranscriptRecord,
    TranscriptSegmentRecord,
    TranscriptWriteResult,
    UserRecord,
    VideoPartRecord,
    VideoRecord,
    _choice,
    _error_code,
    _integer,
    _text,
)


DatabaseConnection: TypeAlias = sqlite3.Connection
_ARCHIVE_DATABASE_NAME = "archive.db"
_DATABASE_SUFFIXES = frozenset({".db", ".sqlite", ".sqlite3"})
_TERMINAL_RUN_OUTCOMES = ALLOWED_RUN_OUTCOMES - frozenset({"running"})
_TERMINAL_ACQUISITION_OUTCOMES = frozenset({"complete", "partial", "failed"})
# The attempt outcomes ``record_subtitle_attempt`` owns: evidence of an
# attempt that produced no transcript.  ``stored`` and ``unchanged`` are the
# write path's own outcomes and are derived from it, never accepted here.
_NO_TRANSCRIPT_ATTEMPT_OUTCOMES = ALLOWED_ATTEMPT_OUTCOMES - {"stored", "unchanged"}
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


def _validate_connection(connection: sqlite3.Connection) -> None:
    """Require the connection state every repository in this module is built on.

    The connection must come with ``row_factory = sqlite3.Row`` and
    ``PRAGMA foreign_keys`` enabled — exactly the state :func:`open_database`
    establishes.
    """
    if not isinstance(connection, sqlite3.Connection):
        raise TypeError("connection must be a sqlite3.Connection")
    if connection.row_factory is not sqlite3.Row:
        raise TypeError("connection must use the sqlite3.Row row_factory")
    if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise ValueError("connection must have PRAGMA foreign_keys enabled")


@contextmanager
def _transaction(connection: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Serve this module's one transaction discipline for a write group.

    The enclosed writes are committed together on success; any exception rolls
    the whole group back and is re-raised, so a caller never observes half of a
    write group.
    """
    try:
        yield connection
    except BaseException:
        connection.rollback()
        raise
    else:
        connection.commit()


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
        _validate_connection(connection)
        self.connection = connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Commit the enclosed repository operations or roll them back."""
        with _transaction(self.connection) as connection:
            yield connection

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


def _language_code(value: object) -> str:
    """Return the trimmed caption language code ``value`` carries.

    The stored language is the upstream ``lan`` the gateway already normalized,
    trimmed and non-empty.  Trimming happens here as well so ``' zh-CN '`` and
    ``'zh-CN'`` name one transcript identity.
    """
    return _text(value, "language").strip()


def _segment_content_sha256(triples: list[list[int | str]]) -> str:
    """Digest the canonical segment JSON exactly as the contract defines it."""
    canonical = json.dumps(triples, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class TranscriptRepository:
    """Repository for acquired transcripts and their acquisition process records.

    Commit boundaries per public method:

    - ``start_acquisition_run`` commits its own insert so a part that fails
      later can roll back without losing the run parent.
    - ``finish_acquisition_run`` commits its own terminal transition.
    - ``record_acquired_transcript`` owns one transaction: it validates the
      part and the arguments, computes the content hash, appends a version with
      its segments only when the content is new, writes the attempt row with
      the resulting ``'stored'``/``'unchanged'`` outcome, and commits — or
      rolls back wholly, so a version is never stored without the attempt
      evidence that produced it.
    - ``record_subtitle_attempt`` owns one transaction for one ``'no-subtitle'``
      or ``'failed'`` attempt and commits it.
    - ``read_transcript``, ``list_transcript_versions``,
      ``list_pending_subtitle_parts``, ``count_pending_subtitle_parts`` and
      ``list_selected_parts`` never write and never commit: they return the
      stored rows as they are — a typed ``TranscriptRecord`` for one stored
      version, ``sqlite3.Row`` view data otherwise.

    Versions are immutable: no method rewrites or deletes a transcript row, a
    segment row, or an attempt row, and no method recomputes the outcome of a
    run that already finished.  Attempt evidence is append-only per
    ``(run_id, video_part_id)`` and is never a terminal per-part state, so a
    part recorded without a caption stays re-attemptable in a later run.

    Do not compose ``start_acquisition_run``, ``finish_acquisition_run``,
    ``record_acquired_transcript`` or ``record_subtitle_attempt`` inside a
    :meth:`MetadataRepository.transaction` group: each commits independently
    and would commit the enclosing group's earlier writes.

    The connection must come with ``row_factory = sqlite3.Row`` and
    ``PRAGMA foreign_keys`` enabled — exactly the state :func:`open_database`
    establishes — and must carry the transcript-schema contract: the
    constructor rejects anything else, so a caller that skipped
    :func:`require_subtitle_schema` still meets the bounded rebuild error
    instead of a raw ``sqlite3.OperationalError`` from its first query.
    """

    def __init__(self, connection: sqlite3.Connection):
        _validate_connection(connection)
        require_subtitle_schema(connection)
        self.connection = connection

    def start_acquisition_run(self, run: AcquisitionRunRecord) -> None:
        """Insert one new acquisition run.

        ``run_id`` is the primary key and is never reused: a duplicate raises
        ``sqlite3.IntegrityError``.  The run is committed on its own so a
        failed part can roll back without deleting its parent.
        """
        if not isinstance(run, AcquisitionRunRecord):
            raise TypeError("run must be an AcquisitionRunRecord")
        self.connection.execute(
            """
            INSERT INTO acquisition_runs(
                run_id, kind, selector_kind, selector_target, requested_limit,
                credential_present, started_at, finished_at, outcome
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.run_id,
                run.kind,
                run.selector_kind,
                run.selector_target,
                run.requested_limit,
                int(run.credential_present),
                run.started_at,
                run.finished_at,
                run.outcome,
            ),
        )
        # A run is a lifecycle parent for attempt transactions. Commit its
        # start independently so a failed part can roll back without it.
        self.connection.commit()

    def finish_acquisition_run(
        self, run_id: str, finished_at: int, *, outcome: str | None = None
    ) -> str:
        """Finish a run with its outcome and finish timestamp; return the outcome.

        The outcome is the explicit ``outcome`` when given, otherwise it is
        derived from the run's attempt rows: ``'failed'`` when every attempt of
        a non-empty set failed, ``'partial'`` when failed and non-failed
        attempts coexist, and ``'complete'`` otherwise — including a run with
        no attempts, which means the bounded work set was empty and nothing
        failed.  The ordering baseline is the run's stored ``started_at``, not
        a caller-supplied clock.  Re-finishing is rejected: a run whose stored
        outcome is already terminal raises ``sqlite3.IntegrityError`` and keeps
        both its outcome and its ``finished_at``.

        ``run_id`` is validated by the same helper every other identifier in
        this class goes through, so a malformed one is answered with the same
        bounded message its siblings produce.
        """
        run_id = _text(run_id, "run_id")
        _integer(finished_at, "finished_at", minimum=0)
        if outcome is not None:
            _choice(outcome, "outcome", _TERMINAL_ACQUISITION_OUTCOMES)
        run_row = self.connection.execute(
            "SELECT started_at, outcome FROM acquisition_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if run_row is None:
            raise sqlite3.IntegrityError(f"unknown run_id: {run_id}")
        if run_row["outcome"] != "running":
            raise sqlite3.IntegrityError(
                f"run {run_id} already finished with outcome {run_row['outcome']}"
            )
        if finished_at < int(run_row["started_at"]):
            raise ValueError("finished_at must not precede started_at")
        resolved = (
            outcome if outcome is not None else self._run_outcome_from_attempts(run_id)
        )
        self.connection.execute(
            """
            UPDATE acquisition_runs
            SET finished_at = ?, outcome = ?
            WHERE run_id = ? AND outcome = 'running'
            """,
            (finished_at, resolved, run_id),
        )
        if self.connection.execute("SELECT changes()").fetchone()[0] != 1:
            raise sqlite3.IntegrityError(f"run {run_id} is no longer running")
        self.connection.commit()
        return resolved

    def record_acquired_transcript(
        self,
        *,
        run_id: str,
        video_part_id: int,
        source_kind: str,
        language: str,
        segments: tuple[TranscriptSegmentRecord, ...],
        started_at: int,
        finished_at: int,
        created_at: int,
    ) -> TranscriptWriteResult:
        """Store one acquired caption body as a transcript version, idempotently.

        One transaction: the part and the arguments are validated, the content
        hash is computed over the canonical segment JSON, and then either
        nothing is written — when a version of ``(video_part_id, source_kind,
        language)`` already carries that hash, in which case the attempt is
        recorded ``'unchanged'`` and points at the version the operator already
        holds — or the next version is appended with its segments and the
        attempt is recorded ``'stored'``.  Either way the attempt row is
        written last and the transaction is committed; any failure — a write
        violation as much as an attempt row the key ``(run_id,
        video_part_id)`` already holds — rolls the whole call back, so no
        version is stored without its attempt evidence.

        Normalization at this boundary, not in the caller: the text of every
        segment is stored and hashed trimmed, the language is stored trimmed,
        and a millisecond value above :data:`MAX_TIMELINE_MS` is rejected with
        ``ValueError`` rather than reaching SQLite as an unrepresentable
        integer.  ``source_kind`` is one of the two caption kinds; an empty
        ``segments`` tuple, a non-positive ``video_part_id``, and an
        ``end_ms``/``start_ms`` violation are rejected with ``ValueError``.
        The run's outcome is left alone: a finished run is never recomputed.
        """
        run_id = _text(run_id, "run_id")
        video_part_id = _integer(video_part_id, "video_part_id", minimum=1)
        source_kind = _choice(
            source_kind, "source_kind", ALLOWED_CAPTION_SOURCE_KINDS
        )
        language = _language_code(language)
        segment_records = tuple(segments)
        if not segment_records:
            raise ValueError("a transcript requires at least one segment")
        started_at = _integer(started_at, "started_at", minimum=0)
        finished_at = _integer(finished_at, "finished_at", minimum=0)
        created_at = _integer(created_at, "created_at", minimum=0)
        if finished_at < started_at:
            raise ValueError("finished_at must not precede started_at")
        canonical = self._canonical_segments(segment_records)
        content_sha256 = _segment_content_sha256(canonical)

        with _transaction(self.connection):
            self._require_video_part(video_part_id)
            self._require_acquisition_run(run_id)
            existing_row = self.connection.execute(
                """
                SELECT transcript_id, version
                FROM transcripts
                WHERE video_part_id = ? AND source_kind = ? AND language = ?
                  AND content_sha256 = ?
                """,
                (video_part_id, source_kind, language, content_sha256),
            ).fetchone()
            if existing_row is None:
                version = self._next_transcript_version(
                    video_part_id, source_kind, language
                )
                cursor = self.connection.execute(
                    """
                    INSERT INTO transcripts(
                        video_part_id, source_kind, language, model_id, version,
                        content_sha256, created_at
                    ) VALUES (?, ?, ?, NULL, ?, ?, ?)
                    """,
                    (
                        video_part_id,
                        source_kind,
                        language,
                        version,
                        content_sha256,
                        created_at,
                    ),
                )
                transcript_id = int(cursor.lastrowid)
                self.connection.executemany(
                    """
                    INSERT INTO transcript_segments(
                        transcript_id, ordinal, start_ms, end_ms, text
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    [
                        (transcript_id, ordinal, start_ms, end_ms, text)
                        for ordinal, (start_ms, end_ms, text) in enumerate(canonical)
                    ],
                )
                outcome = "stored"
            else:
                transcript_id = int(existing_row["transcript_id"])
                version = int(existing_row["version"])
                outcome = "unchanged"
            self.connection.execute(
                """
                INSERT INTO acquisition_attempts(
                    run_id, video_part_id, outcome, error_code, transcript_id,
                    started_at, finished_at
                ) VALUES (?, ?, ?, NULL, ?, ?, ?)
                """,
                (
                    run_id,
                    video_part_id,
                    outcome,
                    transcript_id,
                    started_at,
                    finished_at,
                ),
            )

        return TranscriptWriteResult(
            outcome=outcome,
            transcript_id=transcript_id,
            version=version,
            content_sha256=content_sha256,
        )

    def record_subtitle_attempt(
        self,
        *,
        run_id: str,
        video_part_id: int,
        outcome: str,
        error_code: str | None,
        started_at: int,
        finished_at: int,
    ) -> None:
        """Record one attempt that produced no transcript.

        One transaction for one ``'no-subtitle'``/``'failed'`` attempt.  The
        attempt table's CHECK matrix is enforced here as well: a ``'failed'``
        attempt requires a bounded ``error_code``, a ``'no-subtitle'`` attempt
        carries either no code (upstream listed nothing) or exactly
        ``'not_found'`` (upstream signalled "not visible"), and neither outcome
        may reference a transcript.  The attempt row is therefore the whole
        evidence — append-only per ``(run_id, video_part_id)`` and never a
        terminal per-part state, so a part recorded here is re-attemptable in a
        later run.
        """
        run_id = _text(run_id, "run_id")
        video_part_id = _integer(video_part_id, "video_part_id", minimum=1)
        outcome = _choice(outcome, "outcome", _NO_TRANSCRIPT_ATTEMPT_OUTCOMES)
        error_code = _error_code(error_code)
        if outcome == "failed" and error_code is None:
            raise ValueError("a failed attempt requires a bounded error_code")
        if outcome == "no-subtitle" and error_code not in (None, "not_found"):
            raise ValueError(
                "a no-subtitle attempt carries no error_code or not_found"
            )
        started_at = _integer(started_at, "started_at", minimum=0)
        finished_at = _integer(finished_at, "finished_at", minimum=0)
        if finished_at < started_at:
            raise ValueError("finished_at must not precede started_at")

        with _transaction(self.connection):
            self._require_video_part(video_part_id)
            self._require_acquisition_run(run_id)
            self.connection.execute(
                """
                INSERT INTO acquisition_attempts(
                    run_id, video_part_id, outcome, error_code, transcript_id,
                    started_at, finished_at
                ) VALUES (?, ?, ?, ?, NULL, ?, ?)
                """,
                (run_id, video_part_id, outcome, error_code, started_at, finished_at),
            )

    def read_transcript(
        self,
        video_part_id: int,
        source_kind: str,
        language: str,
        version: int | None = None,
    ) -> TranscriptRecord | None:
        """Read one stored transcript version with its segment timeline.

        ``version=None`` reads the latest version of the identity; an explicit
        ``version`` reads that one, which stays readable after a newer version
        is written.  ``None`` means the archive holds no such version.  The
        language is trimmed exactly as the write path trims it, so the identity
        a caller names here is the identity the store holds, and ``source_kind``
        is validated against the whole vocabulary the column's CHECK accepts —
        the ``asr-local`` reservation simply has no rows yet.  Read-only: no
        write, no commit.
        """
        video_part_id = _integer(video_part_id, "video_part_id", minimum=1)
        source_kind = _choice(source_kind, "source_kind", ALLOWED_SOURCE_KINDS)
        language = _language_code(language)
        if version is None:
            query = (
                "SELECT * FROM transcripts WHERE video_part_id = ? "
                "AND source_kind = ? AND language = ? ORDER BY version DESC LIMIT 1"
            )
            parameters: tuple[object, ...] = (video_part_id, source_kind, language)
        else:
            query = (
                "SELECT * FROM transcripts WHERE video_part_id = ? "
                "AND source_kind = ? AND language = ? AND version = ?"
            )
            parameters = (
                video_part_id,
                source_kind,
                language,
                _integer(version, "version", minimum=1),
            )
        row = self.connection.execute(query, parameters).fetchone()
        if row is None:
            return None
        transcript_id = int(row["transcript_id"])
        return TranscriptRecord(
            transcript_id=transcript_id,
            video_part_id=int(row["video_part_id"]),
            source_kind=str(row["source_kind"]),
            language=str(row["language"]),
            model_id=None if row["model_id"] is None else int(row["model_id"]),
            version=int(row["version"]),
            content_sha256=str(row["content_sha256"]),
            created_at=int(row["created_at"]),
            segments=self._stored_segments(transcript_id),
        )

    def list_transcript_versions(
        self, video_part_id: int, source_kind: str, language: str
    ) -> list[sqlite3.Row]:
        """List one transcript identity's stored versions, oldest first.

        Rows come straight from ``transcripts`` and carry every stored column;
        an identity the archive does not hold yields an empty list.  Read-only.
        """
        video_part_id = _integer(video_part_id, "video_part_id", minimum=1)
        source_kind = _choice(source_kind, "source_kind", ALLOWED_SOURCE_KINDS)
        language = _language_code(language)
        return list(
            self.connection.execute(
                """
                SELECT * FROM transcripts
                WHERE video_part_id = ? AND source_kind = ? AND language = ?
                ORDER BY version
                """,
                (video_part_id, source_kind, language),
            ).fetchall()
        )

    def list_pending_subtitle_parts(
        self, limit: int | None = None
    ) -> list[sqlite3.Row]:
        """Return the captionless parts in the locked work order.

        Rows come straight from the ``v_pending_subtitles`` view, which carries
        the newest attempt's evidence for every part that holds no transcript.
        The repository — not the view — imposes the order
        ``attempted ASC, last_attempt_at ASC, bvid ASC, page_index ASC``, so
        never-attempted parts come before previously attempted ones and the
        oldest attempt comes first: successive bounded runs rotate through the
        captionless backlog instead of re-attempting the same head.  The key
        list stays verbatim even though ``attempted`` is implied by
        ``last_attempt_at IS NULL`` (which SQLite sorts first): it is the locked
        contract the CLI reads, not a query to be shortened.  Read-only.
        """
        if limit is not None:
            if isinstance(limit, bool) or not isinstance(limit, int):
                raise TypeError("limit must be an integer or None")
            if limit < 1:
                raise ValueError("limit must be a positive integer")
            query = (
                "SELECT * FROM v_pending_subtitles "
                "ORDER BY attempted ASC, last_attempt_at ASC, bvid ASC, page_index ASC "
                "LIMIT ?"
            )
            return list(self.connection.execute(query, (limit,)).fetchall())
        return list(
            self.connection.execute(
                "SELECT * FROM v_pending_subtitles "
                "ORDER BY attempted ASC, last_attempt_at ASC, bvid ASC, page_index ASC"
            ).fetchall()
        )

    def count_pending_subtitle_parts(self) -> int:
        """Count the parts the pending relation holds. Read-only."""
        return int(
            self.connection.execute(
                "SELECT COUNT(*) FROM v_pending_subtitles"
            ).fetchone()[0]
        )

    def list_selected_parts(
        self, bvid: str, page_index: int | None = None
    ) -> list[sqlite3.Row]:
        """Return the stored parts of one explicit selection, or no rows.

        Rows come straight from the ``v_video_parts`` view — the view carries the
        ``work_id``, the user and video context, but not the ``bvid`` itself, so
        the selector joins the part's own row to reach it — ordered by
        ``page_index``.  An unknown ``bvid`` — or an unknown ``bvid:pN`` —
        yields an empty list rather than an invented row, the honest answer the
        caller reports as a usage error.  An explicit selection is not filtered
        by ``processing_status``: explicit means explicit, and the evidence a
        run writes then records what upstream really returned.  Read-only.
        """
        bvid = _text(bvid, "bvid")
        if page_index is None:
            query = (
                "SELECT vvp.* FROM v_video_parts AS vvp "
                "JOIN video_parts AS vp ON vp.video_part_id = vvp.video_part_id "
                "WHERE vp.bvid = ? ORDER BY vvp.page_index"
            )
            parameters: tuple[object, ...] = (bvid,)
        else:
            query = (
                "SELECT vvp.* FROM v_video_parts AS vvp "
                "JOIN video_parts AS vp ON vp.video_part_id = vvp.video_part_id "
                "WHERE vp.bvid = ? AND vvp.page_index = ?"
            )
            parameters = (bvid, _integer(page_index, "page_index", minimum=0))
        return list(self.connection.execute(query, parameters).fetchall())

    def _stored_segments(
        self, transcript_id: int
    ) -> tuple[TranscriptSegmentRecord, ...]:
        """Return one version's segments in ordinal order, verbatim as stored."""
        return tuple(
            TranscriptSegmentRecord(
                start_ms=int(row["start_ms"]),
                end_ms=int(row["end_ms"]),
                text=str(row["text"]),
            )
            for row in self.connection.execute(
                """
                SELECT start_ms, end_ms, text FROM transcript_segments
                WHERE transcript_id = ? ORDER BY ordinal
                """,
                (transcript_id,),
            ).fetchall()
        )

    def _require_video_part(self, video_part_id: int) -> None:
        """Require that ``video_part_id`` names a part the archive already holds.

        Bounded, named evidence instead of the raw foreign-key message: both
        write paths reference the part, so an unknown one fails the whole call
        before anything is written.
        """
        row = self.connection.execute(
            "SELECT 1 FROM video_parts WHERE video_part_id = ?", (video_part_id,)
        ).fetchone()
        if row is None:
            raise sqlite3.IntegrityError(f"unknown video_part_id: {video_part_id}")

    def _require_acquisition_run(self, run_id: str) -> None:
        """Require that ``run_id`` names an acquisition run.

        The attempt row that references the run is written last, so an unknown
        run leaves no transcript version or segment behind.
        """
        row = self.connection.execute(
            "SELECT 1 FROM acquisition_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise sqlite3.IntegrityError(f"unknown run_id: {run_id}")

    def _canonical_segments(
        self, segments: tuple[TranscriptSegmentRecord, ...]
    ) -> list[list[int | str]]:
        """Return the ordered ``[start_ms, end_ms, text]`` triples to store.

        The storage boundary re-validates the timeline instead of trusting the
        caller: a segment below zero, an ``end_ms`` that does not exceed its
        ``start_ms``, a millisecond value above :data:`MAX_TIMELINE_MS`, or
        text that is empty once trimmed raises ``ValueError``.  The text of
        each triple is its trimmed form — what the row stores and what the
        content hash covers — and the ordinal is the position, so upstream
        order is preserved verbatim, overlaps included.
        """
        canonical: list[list[int | str]] = []
        for index, segment in enumerate(segments):
            if not isinstance(segment, TranscriptSegmentRecord):
                raise TypeError(
                    f"segments[{index}] must be a TranscriptSegmentRecord"
                )
            start_ms = _integer(
                segment.start_ms,
                f"segments[{index}].start_ms",
                minimum=0,
                maximum=MAX_TIMELINE_MS,
            )
            end_ms = _integer(
                segment.end_ms,
                f"segments[{index}].end_ms",
                minimum=1,
                maximum=MAX_TIMELINE_MS,
            )
            if end_ms <= start_ms:
                raise ValueError(
                    f"segments[{index}].end_ms must be greater than start_ms"
                )
            text = segment.text.strip()
            if not text:
                raise ValueError(f"segments[{index}].text must not be empty")
            canonical.append([start_ms, end_ms, text])
        return canonical

    def _next_transcript_version(
        self, video_part_id: int, source_kind: str, language: str
    ) -> int:
        """Return the next version number of one transcript identity."""
        row = self.connection.execute(
            """
            SELECT COALESCE(MAX(version), 0) + 1 AS next_version
            FROM transcripts
            WHERE video_part_id = ? AND source_kind = ? AND language = ?
            """,
            (video_part_id, source_kind, language),
        ).fetchone()
        return int(row["next_version"])

    def _run_outcome_from_attempts(self, run_id: str) -> str:
        """Derive a run's outcome from the attempt rows it holds."""
        counts = {
            str(row["outcome"]): int(row["attempts"])
            for row in self.connection.execute(
                """
                SELECT outcome, COUNT(*) AS attempts
                FROM acquisition_attempts
                WHERE run_id = ?
                GROUP BY outcome
                """,
                (run_id,),
            ).fetchall()
        }
        attempts = sum(counts.values())
        failed = counts.get("failed", 0)
        if failed and failed == attempts:
            return "failed"
        if failed:
            return "partial"
        return "complete"


__all__ = [
    "DatabaseConnection",
    "MetadataRepository",
    "SchemaContractError",
    "TranscriptRepository",
    "duration_to_ms",
    "initialize_schema",
    "normalize_page_index",
    "open_database",
    "require_subtitle_schema",
]
