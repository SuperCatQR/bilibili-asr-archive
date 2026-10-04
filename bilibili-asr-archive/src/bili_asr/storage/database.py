"""SQLite bootstrap and the normalized metadata and transcript repositories."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
from importlib import resources
import json
import math
import os
from pathlib import Path
import re
import sqlite3
from typing import ClassVar, Iterable, Iterator, Mapping, Sequence, TypeAlias

from .models import (
    ALLOWED_ATTEMPT_OUTCOMES,
    ALLOWED_CAPTION_SOURCE_KINDS,
    ALLOWED_LOCAL_TRANSCRIPT_SOURCE_KINDS,
    ALLOWED_QUEUE_GAPS,
    ALLOWED_RUN_OUTCOMES,
    ALLOWED_SOURCE_KINDS,
    MAX_TIMELINE_MS,
    AcquisitionRunRecord,
    CursorRecord,
    DiscoveryRecord,
    IngestionPageRecord,
    IngestionRunRecord,
    QueueGap,
    QueueGapItem,
    TranscriptRecord,
    TranscriptSegmentRecord,
    TranscriptWriteResult,
    UserRecord,
    VideoDetailRecord,
    VideoPartRecord,
    VideoRecord,
    VideoTagRecord,
    _choice,
    _content_sha256,
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
# SQLite builds before 3.32.0 cap one prepared statement at 999 host
# parameters, and the queue a derivation reads is bounded by the store rather
# than by this module (spec §2 states no queue bound), so the bvid lookups are
# issued in chunks comfortably below that ceiling instead of as one unbounded
# ``IN (...)``.
_PUBDATE_CHUNK = 900


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


#: A view name this module will interpolate into DDL.  Matched with ``match``
#: against the comment-stripped statement, so a comment that happens to contain
#: the words "CREATE VIEW" cannot supply a name for the *next* statement; the
#: keyword list rejects an unquoted identifier that is really syntax.
_VIEW_NAME_RE = re.compile(
    r"CREATE\s+VIEW(?:\s+IF\s+NOT\s+EXISTS)?\s+([A-Za-z_][A-Za-z0-9_]*)\s+AS\b",
    re.IGNORECASE | re.DOTALL,
)
#: The only shape a view name may have before it is interpolated into DDL.
_BARE_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

_SQL_KEYWORDS = frozenset(
    {"if", "not", "exists", "as", "select", "with", "values", "table", "view"}
)


def _statement_view_name(statement: str) -> str | None:
    """The view name a shipped statement defines, or ``None``.

    Comments are stripped first: a leading comment block that mentions "CREATE
    VIEW" would otherwise be matched instead of the statement's own clause.
    """

    body = "\n".join(
        line for line in statement.splitlines() if not line.lstrip().startswith("--")
    )
    match = _VIEW_NAME_RE.match(body.strip())
    if match is None:
        return None
    name = match.group(1)
    if name.casefold() in _SQL_KEYWORDS:
        return None
    return name


def _shipped_view_bodies() -> dict[str, str]:
    """The ``name -> CREATE VIEW`` bodies this build ships, keyed by view name.

    Read from the checked-in transcript script so there is one source of truth:
    the body compared against ``sqlite_master`` is the body this build would
    create.  A statement that fails to parse is skipped rather than guessed at —
    ``executescript`` below reports that failure with its own error.
    """

    script = _TRANSCRIPT_SCHEMA_RESOURCE.read_text(encoding="utf-8")
    bodies: dict[str, str] = {}
    buffer = ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if not sqlite3.complete_statement(buffer):
            continue
        statement = buffer.strip()
        buffer = ""
        if "CREATE VIEW" not in statement.upper():
            continue
        name = _statement_view_name(statement)
        if name is not None:
            bodies[name] = statement
    return bodies


def _strip_sql_comments(statement: str) -> str:
    """Remove SQL comments, respecting every quoted region.

    Both a whole-line comment and a trailing one are removed, because SQLite
    stores whatever was written: a comment left in either form would make the
    shipped and stored texts differ forever.

    The scan understands all four of SQLite's quoting forms — ``'...'`` strings
    (with ``''`` escaping), ``"..."`` and ``[...]`` identifiers, and MySQL-style
    ``` `...` ``` identifiers — plus ``/* ... */`` block comments.  It has to:
    ``--`` inside *any* quoted region is data, and a scan that only knew about
    single quotes would truncate the statement at that marker, which makes two
    views selecting *different* columns normalize equal.  That is a false
    negative — a genuinely stale body judged current — i.e. exactly the defect
    this refresh exists to close.
    """

    out: list[str] = []
    index = 0
    length = len(statement)
    # (closing character, doubled-character escape) for each quoted form.
    quotes: dict[str, tuple[str, bool]] = {
        "'": ("'", True),
        '"': ('"', True),
        "`": ("`", True),
        "[": ("]", False),
    }
    while index < length:
        char = statement[index]
        if char in quotes:
            closing, doubled = quotes[char]
            out.append(char)
            index += 1
            while index < length:
                current = statement[index]
                out.append(current)
                if current == closing:
                    if doubled and index + 1 < length and statement[index + 1] == closing:
                        out.append(current)
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            continue
        if char == "/" and index + 1 < length and statement[index + 1] == "*":
            closing_block = statement.find("*/", index + 2)
            if closing_block < 0:
                break
            index = closing_block + 2
            continue
        if char == "-" and index + 1 < length and statement[index + 1] == "-":
            # Skip to the end of the line, keeping the newline itself so two
            # tokens on either side of a removed comment do not fuse together.
            newline = statement.find("\n", index)
            if newline < 0:
                break
            index = newline
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _normalize_view_sql(statement: str) -> str:
    """Collapse a view body to the shape SQLite stores, for comparison only.

    SQLite keeps the original text of a view's ``SELECT`` but drops the trailing
    semicolon and rewrites the header, so the shipped statement and the stored
    one are never byte-equal even when the view is current.  Whitespace and case
    are collapsed as well, which makes the comparison a statement about the body
    rather than about formatting.

    Two properties are load-bearing and were each measured:

    * comments are stripped from **both** sides.  SQLite *preserves* a comment
      that sits inside a view statement, and every shipped view carries several
      (4 to 24 lines each), so stripping only the shipped body would make every
      view read as stale on every open.
    * whitespace and case are collapsed **outside string literals only**.  A body
      differing from the shipped one only inside a literal — ``'no-subtitle'``
      against ``'NO-SUBTITLE'`` — must still read as different, or a genuinely
      stale view would never refresh.
    """

    text = _strip_sql_comments(statement).strip().rstrip(";").strip()
    # SQLite also drops the IF NOT EXISTS clause when it stores a view, so the
    # shipped form has to lose it too before the two can be compared.
    text = re.sub(r"(?i)^create\s+view\s+if\s+not\s+exists\s+", "CREATE VIEW ", text)

    out: list[str] = []
    plain: list[str] = []
    index = 0
    length = len(text)

    def flush_plain() -> None:
        if plain:
            out.append(" ".join("".join(plain).casefold().split()))
            plain.clear()

    while index < length:
        char = text[index]
        if char == "'":
            flush_plain()
            literal = ["'"]
            index += 1
            while index < length:
                current = text[index]
                literal.append(current)
                if current == "'":
                    if index + 1 < length and text[index + 1] == "'":
                        literal.append("'")
                        index += 2
                        continue
                    break
                index += 1
            out.append("".join(literal))
            index += 1
            continue
        plain.append(char)
        index += 1
    flush_plain()
    return " ".join(piece for piece in out if piece)


def refresh_shipped_views(connection: sqlite3.Connection) -> int:
    """Recreate any shipped view whose stored body differs from this build's.

    ``CREATE VIEW IF NOT EXISTS`` means a re-executed schema script never updates
    a view that already exists, so a corrected predicate would silently never
    reach an existing archive.  This closes that gap without making every open a
    write:

    * the stored body is compared against the shipped one first, and nothing is
      touched when they agree — so a read-only archive, or one opened while
      another handle holds a read transaction, is not forced into a write it does
      not need;
    * a refresh runs inside a **savepoint**, so a failure cannot leave the view
      absent: ``_transaction`` commits but never issues BEGIN, which would let a
      DROP autocommit (measured: a failing CREATE then left the view missing from
      ``sqlite_master``), whereas ``ROLLBACK TO`` restores it.

    Views the shipped script defines are the only ones considered; anything else
    in the database is left alone.  Returns the number of views refreshed.
    """

    shipped = _shipped_view_bodies()
    if not shipped:
        return 0
    # Positional indexing, like ``_schema_object_names``: a caller may hand us a
    # wrapped connection without ``row_factory = sqlite3.Row``, and reading by
    # name here would raise ``TypeError`` on it.
    stored = {
        str(row[0]): str(row[1])
        for row in connection.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type = 'view' AND sql IS NOT NULL"
        )
    }
    stale = [
        name
        for name, body in shipped.items()
        if name in stored
        and _normalize_view_sql(stored[name]) != _normalize_view_sql(body)
    ]
    if not stale:
        return 0
    # The names come from this build's own script and each is re-validated as a
    # bare identifier before it can reach any DDL string.
    for name in stale:
        if not _BARE_IDENTIFIER_RE.fullmatch(name):
            raise sqlite3.DatabaseError(f"refusing to refresh view {name!r}")
    # A SAVEPOINT, not ``_transaction``: that helper commits but never issues
    # BEGIN, so a DROP inside it would autocommit and a failing CREATE would
    # leave the view *absent* — measured, and the reason this is not a plain
    # transaction block.  A savepoint is also safe when a transaction is already
    # open around this call.
    connection.execute("SAVEPOINT refresh_shipped_views")
    try:
        for name in stale:
            connection.execute(f"DROP VIEW IF EXISTS {name}")
            connection.execute(shipped[name].replace("IF NOT EXISTS ", "", 1))
    except BaseException:
        # Suppress a failure in the rollback itself so the ORIGINAL error is what
        # the caller sees; a masked syntax error would be much harder to place.
        for undo in ("ROLLBACK TO refresh_shipped_views", "RELEASE refresh_shipped_views"):
            try:
                connection.execute(undo)
            except sqlite3.Error:
                continue
        raise
    connection.execute("RELEASE refresh_shipped_views")
    return len(stale)


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
        refresh_shipped_views(connection)
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
    - ``upsert_user``, ``ensure_user``, ``upsert_video``, ``upsert_part``,
      ``record_discovery`` and ``write_cursor`` execute SQL without
      committing, so a caller can group them in one transaction through
      :meth:`transaction`.
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

    def ensure_user(self, user: UserRecord) -> None:
        """Establish a user row only when it does not exist; never rewrite one.

        The run and cursor rows carry a foreign key to ``bilibili_users(mid)``
        (``schema.sql``), so a collection run's opening write must establish the
        parent row before it starts.  It must not *update* one: that write
        happens before any page is fetched, so it has observed nothing to write,
        and an established label may not be replaced by the owner-mid
        placeholder a run-with-no-observation carries.  The placeholder is
        therefore only ever the value a row is *created* with.

        :meth:`upsert_user` stays the refreshing write: it is how a name the
        run did observe reaches an existing row, and it overwrites.
        """
        if not isinstance(user, UserRecord):
            raise TypeError("user must be a UserRecord")
        self.connection.execute(
            """
            INSERT INTO bilibili_users(mid, display_name, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(mid) DO NOTHING
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

    def upsert_video_details(self, details: VideoDetailRecord) -> None:
        """Insert or refresh one video's category and cover observation.

        **One row per video, and it is refreshed** (compass D11): a second
        collection of the same ``bvid`` replaces the row rather than adding
        one, so ``SELECT COUNT(*)`` for that video stays ``1`` forever and
        ``observed_at`` always holds the newest observation's stamp.  A reader
        must not treat this table as a history: it cannot answer "what did
        upstream say on 2026-09-26", because nothing here is dated beyond the
        single row's own last-write stamp.

        **``observed_at`` means "last *successful* collection" — the guard is
        the condition, not an adjective** (compass D15).  All three value
        columns are nullable, so an unconditional ``ON CONFLICT ... DO UPDATE
        SET`` could blank a populated row with ``NULL``s and stamp it fresh,
        recording "nothing was true at T" where the collection established no
        such thing.  The write therefore happens **only when the incoming
        observation carries at least one of ``pic``/``desc``/``tid``**: an
        all-``NULL`` observation leaves the existing row and its ``observed_at``
        untouched, and writes no row at all for a video that has none.  The
        grain is unchanged — one row per video, refreshed — so the guard
        constrains *when* the stamp moves, not what the table holds.

        **A partial observation refreshes the whole row, the stamp included.**
        "All three are ``None``" is the whole of the skip condition, so an
        observation carrying only one of the three is a successful collection:
        the row is written to exactly what it carried, the unobserved columns go
        to ``NULL``, and ``observed_at`` advances with them.  That is D11 applied
        verbatim — metadata "is refreshed on recollect … a later collection
        overwrites it" — because the row is the last collection's *view* of the
        video, not a per-column last-known-good, so a value upstream really did
        drop does not survive as a stale one.  Per-column ``COALESCE`` would keep
        a genuinely retracted cover alive, which is the same class of fiction
        D15 exists to prevent; a partial observation establishes exactly that
        much and nothing here is per-column.

        ``"desc"`` is quoted because ``desc`` is a SQL keyword and the column
        keeps upstream's own field name.  ``pic`` holds the cover URL in the
        store; ``export`` still redacts its value and this is intended and
        permanent for this iteration (compass D12 — the cover is store-only,
        and a cover that must appear in an export is a new decision).
        """

        if not isinstance(details, VideoDetailRecord):
            raise TypeError("details must be a VideoDetailRecord")
        if (
            details.pic is None
            and details.desc is None
            and details.tid is None
        ):
            # Nothing was observed: leave the row and its stamp alone, and do
            # not create one for a video that has none (D15).
            return
        self.connection.execute(
            """
            INSERT INTO video_details(bvid, pic, "desc", tid, observed_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(bvid) DO UPDATE SET
                pic = excluded.pic,
                "desc" = excluded."desc",
                tid = excluded.tid,
                observed_at = excluded.observed_at
            """,
            (
                details.bvid,
                details.pic,
                details.desc,
                details.tid,
                details.observed_at,
            ),
        )

    def upsert_video_tags(
        self, bvid: str, tags: Iterable[VideoTagRecord] = ()
    ) -> None:
        """Replace one video's tag set with the observed one.

        The tag set is a *set of facts about a video*, not an append-only
        log: recollecting a video whose tags changed must converge on what
        upstream says now rather than accumulate both answers.  The video's
        existing rows are therefore deleted and the observed set inserted, in
        one statement pair — inside the caller's transaction, so the
        replacement commits or rolls back with the rest of that page's
        payload.  ``bvid`` carries no tags is how a set is cleared.

        Order is not significant: the tag identity is ``(bvid, tag_id)``, so
        the same set converges regardless of the order upstream listed it in.
        A record whose ``bvid`` differs from the argument is refused rather
        than written under another video's key.
        """

        _text(bvid, "bvid")
        tag_records = tuple(tags)
        for tag in tag_records:
            if not isinstance(tag, VideoTagRecord):
                raise TypeError("tags must be VideoTagRecord instances")
            if tag.bvid != bvid:
                raise ValueError("every tag record must carry the given bvid")
        self.connection.execute("DELETE FROM video_tags WHERE bvid = ?", (bvid,))
        self.connection.executemany(
            """
            INSERT INTO video_tags(bvid, tag_id, tag_name, tag_type)
            VALUES (?, ?, ?, ?)
            """,
            [(tag.bvid, tag.tag_id, tag.tag_name, tag.tag_type) for tag in tag_records],
        )

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
        tags: Mapping[str, Iterable[VideoTagRecord]] | None = None,
        details: Iterable[VideoDetailRecord] = (),
    ) -> None:
        """Record one page outcome, optionally with its complete payload.

        With payload arguments the method owns one transaction and applies the
        locked parent-before-child order: user, videos, parts, tag sets,
        details, discoveries, cursor, page outcome, commit. If any write fails,
        the whole transaction is rolled back and the exception is re-raised;
        the prior cursor and entities are unchanged. Recording the resulting
        failure is the caller's step: build a fresh ``IngestionPageRecord`` with
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
        detail_records = tuple(details)
        # ``tags`` is a mapping rather than a flat iterable because the
        # replacement is per video: ``None`` means "this page observed no tag
        # sets at all" (a run whose tag calls all degraded, or a page whose
        # videos were already recorded), while a key present with an empty
        # iterable means "this video was observed to carry no tags" and clears
        # its rows.  The two are deliberately different: conflating them would
        # turn a failed tag fetch into a silent erasure of known tags.
        tag_sets = None if tags is None else dict(tags)
        has_payload = (
            user is not None
            or bool(video_records)
            or bool(part_records)
            or bool(discovery_records)
            or bool(detail_records)
            or cursor is not None
            or tag_sets is not None
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
            # Tags land after the video upserts: the tag row's foreign key
            # points at ``videos``, so an observed video must exist before its
            # tags can.  A tag set for a video this page did not upsert still
            # writes here — the FK then decides, rather than this method
            # silently dropping the observation.
            for tag_bvid, tag_records in (tag_sets or {}).items():
                self.upsert_video_tags(tag_bvid, tag_records)
            # Details land after the same video upserts, for the same foreign
            # key reason.  An all-``NULL`` record is passed through rather than
            # filtered here: ``upsert_video_details`` is where D15's
            # "observed nothing" rule lives, so it stays one rule in one place.
            for detail in detail_records:
                self.upsert_video_details(detail)
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
      ``list_pending_subtitle_parts``, ``count_pending_subtitle_parts``,
      ``list_selected_parts``, ``list_stored_transcripts`` and
      ``read_video_pubdates`` — the class's reads of the ``videos`` table, which
      :class:`MetadataRepository` owns — never write and never commit: they
      return the stored rows as they are — a typed ``TranscriptRecord`` for one
      stored version, ``sqlite3.Row`` view data otherwise.

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

    def record_local_transcript(
        self,
        *,
        run_id: str,
        video_part_id: int,
        language: str,
        segments: tuple[TranscriptSegmentRecord, ...],
        model_name: str,
        model_revision: str | None,
        started_at: int,
        finished_at: int,
        created_at: int,
    ) -> TranscriptWriteResult:
        """Store one locally-produced transcript body as a transcript version.

        The explicitly-named sibling of :meth:`record_acquired_transcript` for
        the ``'asr-local'`` identity.  The caption writer keeps validating
        against :data:`ALLOWED_CAPTION_SOURCE_KINDS`; this entry point validates
        ``source_kind`` against ``{'asr-local'}`` alone, so the caption guard is
        provably unchanged for every existing caller (plan 20260929-asr-local-
        transcript-storage, Task 1 — option (a), a second named entry point).

        The write mirrors the caption path one transaction: the model identity
        is upserted into ``asr_models`` first (the ``transcripts.model_id``
        foreign key demands a row; nothing else inserts one), the content hash
        decides ``'stored'`` vs ``'unchanged'``, and the attempt row is written
        last and committed with the version, so a version is never stored
        without its attempt evidence.  ``model_revision`` is the caller's
        provenance string, defaulting to ``""`` when the runner names none.
        """

        run_id = _text(run_id, "run_id")
        video_part_id = _integer(video_part_id, "video_part_id", minimum=1)
        language = _language_code(language)
        model_name = _text(model_name, "model_name")
        revision = _text(model_revision, "model_revision") if model_revision else ""
        segment_records = tuple(segments)
        if not segment_records:
            raise ValueError("a transcript requires at least one segment")
        started_at = _integer(started_at, "started_at", minimum=0)
        finished_at = _integer(finished_at, "finished_at", minimum=0)
        created_at = _integer(created_at, "created_at", minimum=0)
        if finished_at < started_at:
            raise ValueError("finished_at must not precede started_at")
        source_kind = _choice(
            "asr-local", "source_kind", ALLOWED_LOCAL_TRANSCRIPT_SOURCE_KINDS
        )
        canonical = self._canonical_segments(segment_records)
        content_sha256 = _segment_content_sha256(canonical)

        with _transaction(self.connection):
            self._require_video_part(video_part_id)
            self._require_acquisition_run(run_id)
            model_row = self.connection.execute(
                "SELECT model_id FROM asr_models WHERE model_name = ? AND revision = ?",
                (model_name, revision),
            ).fetchone()
            if model_row is None:
                model_cursor = self.connection.execute(
                    "INSERT INTO asr_models(model_name, revision, created_at) "
                    "VALUES (?, ?, ?)",
                    (model_name, revision, created_at),
                )
                model_id = int(model_cursor.lastrowid)
            else:
                model_id = int(model_row["model_id"])
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
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        video_part_id,
                        source_kind,
                        language,
                        model_id,
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

    def read_video_pubdates(self, bvids: Sequence[str]) -> dict[str, int]:
        """Return the stored publication second of each named video.

        ``videos.pubdate`` is the store's own fact: a derived manifest row
        carries it rather than inventing a date.  An empty input answers ``{}``
        without executing anything — ``IN ()`` is a syntax error, not a read —
        and a bvid the archive does not hold simply has no entry, so every
        lookup the caller makes for a part it just read stays answered.  A
        repeated bvid is answered once.  The keys are read in chunks of at most
        ``_PUBDATE_CHUNK`` parameters, because the caller hands over a whole
        queue: the store bounds how many distinct bvids there are, the driver
        bounds one statement, and only the first bound is this module's to
        assume.  Read-only.
        """
        if not bvids:
            return {}
        keys = tuple(dict.fromkeys(_text(bvid, "bvid") for bvid in bvids))
        pubdates: dict[str, int] = {}
        for start in range(0, len(keys), _PUBDATE_CHUNK):
            chunk = keys[start : start + _PUBDATE_CHUNK]
            placeholders = ", ".join("?" * len(chunk))
            pubdates.update(
                {
                    str(row["bvid"]): int(row["pubdate"])
                    for row in self.connection.execute(
                        f"SELECT bvid, pubdate FROM videos "
                        f"WHERE bvid IN ({placeholders})",
                        chunk,
                    ).fetchall()
                }
            )
        return pubdates

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

    def list_stored_transcripts(
        self, bvid: str | None = None, page_index: int | None = None
    ) -> list[sqlite3.Row]:
        """Return one row per stored transcript version with its part context.

        The relation is over ``transcripts``, not over parts: a part holding
        several stored versions appears once per version, and every row repeats
        its part's columns, its video's ``pubdate`` and its video's own
        ``title`` — the collection the part belongs to, carried as
        ``video_title`` beside the part's own ``part_title``.  The two are
        independent facts and the join is what keeps them apart without a second
        query.  Membership is the join to ``transcripts`` and nothing else: no
        ``processing_status`` predicate narrows it, so a part whose status is
        ``gone`` is a row here when the store holds its text.

        ``bvid`` and ``page_index`` each add one predicate when they are given
        and neither narrows the read when it is absent.  A selector naming no
        stored part — an unknown bvid, or a stored part holding no transcript —
        yields no row rather than an invented one.  The order ``bvid,
        page_index, source_kind, language, version DESC`` lives in this query,
        not in the caller, and it is deterministic row-for-row.  Read-only: no
        write, no commit.
        """
        where_clauses: list[str] = []
        parameters: list[object] = []
        if bvid is not None:
            where_clauses.append("vp.bvid = ?")
            parameters.append(_text(bvid, "bvid"))
        if page_index is not None:
            where_clauses.append("vp.page_index = ?")
            parameters.append(_integer(page_index, "page_index", minimum=0))
        query = (
            "SELECT vp.video_part_id, vp.bvid, vp.page_index, vp.cid, "
            "vp.title AS part_title, vp.duration_ms, vd.pubdate, "
            "vd.title AS video_title, "
            "t.transcript_id, t.source_kind, t.language, t.model_id, "
            "t.version, t.content_sha256, t.created_at "
            "FROM transcripts AS t "
            "JOIN video_parts AS vp ON vp.video_part_id = t.video_part_id "
            "JOIN videos AS vd ON vd.bvid = vp.bvid"
        )
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)
        query += (
            " ORDER BY vp.bvid ASC, vp.page_index ASC, t.source_kind ASC, "
            "t.language ASC, t.version DESC"
        )
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


class MediaQueueRepository:
    """The archive's queue surface: the three gap reads and the two writers.

    :meth:`list_queue_gaps` and :meth:`count_queue_gaps` return one typed entry
    per queued part, with the context and attempt evidence a caller renders it
    with.  :meth:`mark_audio_acquired` and :meth:`mark_transcript_stored` are
    the write half: each records, in one transaction, the evidence — an audio
    object or a stored transcript — that takes a part out of a queue.

    The relation is each view's own; the order is this class's.  The three gap
    views declare no ``ORDER BY``, so a caller reading them directly would take
    SQLite's row order as it comes — :meth:`list_queue_gaps` appends the locked
    work order ``pubdate DESC, bvid ASC, page_index ASC`` to every read, and
    that order is the only one the CLI may observe.  Membership is never
    re-derived here either: a part is in a queue because the view's predicates
    say so, and no argument to these methods reaches a part the view leaves
    out.

    The connection must come with ``row_factory = sqlite3.Row`` and
    ``PRAGMA foreign_keys`` enabled — exactly the state :func:`open_database`
    establishes — and must carry the transcript-schema contract, which is the
    script the three gap views are defined in: the constructor rejects
    anything else, so a caller that skipped :func:`require_subtitle_schema`
    meets the bounded rebuild error instead of a raw
    ``sqlite3.OperationalError`` from its first query.  The guard is the
    contract's own object set, not this class's views — a database carrying
    the contract but missing one gap view still answers
    ``sqlite3.OperationalError`` for that one queue, which is the honest
    report of a store that must be rebuilt.
    """

    _VIEW_BY_GAP: ClassVar[dict[str, str]] = {
        "missing_subtitle": "v_missing_subtitle",
        "missing_audio": "v_missing_audio",
        "missing_transcript": "v_missing_transcript",
    }
    # The acquisition route each queue drains, and therefore the run kind the
    # entry's ``attempt_count`` counts: a captionless part is re-attempted by a
    # subtitle run, while a part with audio evidence is decoded by an audio
    # run.  Counting one route's attempts while reading the other route's queue
    # would answer a question no caller asked.
    _KIND_BY_GAP: ClassVar[dict[str, str]] = {
        "missing_subtitle": "subtitle",
        "missing_audio": "audio",
        "missing_transcript": "audio",
    }

    def __init__(self, connection: sqlite3.Connection):
        _validate_connection(connection)
        require_subtitle_schema(connection)
        self.connection = connection

    def mark_audio_acquired(
        self,
        *,
        bvid: str,
        page_index: int,
        audio_path: str,
        sha256: str,
        byte_size: int,
        format: str,
        duration_ms: int,
        acquisition_source: str,
        acquired_at: int,
    ) -> int:
        """Record that a part's audio has been acquired.  Returns the ``audio_id``.

        **Reuse is keyed on ``storage_key`` (= the caller's ``audio_path``), not
        on ``sha256``.**  Location is the identity of an archived audio object:
        the CLI derives a deterministic per-part path, so a re-download or a
        repaired decode produces a *new* hash for the *same* archived location
        and must not become a second object.  When a row already sits at that
        path it is reused, and ``sha256`` / ``byte_size`` / ``format`` /
        ``duration_ms`` are refreshed **only when they differ** — a re-run of
        the same acquisition is a no-op, and ``created_at`` keeps first-writer
        semantics.

        Same content at a new path (no row for this path, but another row
        already holds this ``sha256``): the content-holding row is reused and
        its ``storage_key`` is repointed to the caller's path — option (a) of
        contract §4c.  The alternative (a bounded ``ValueError`` naming both
        paths) was rejected because such a part would be permanently
        unrecordable, and ``audio_objects.sha256`` is ``UNIQUE``, so the two
        paths can never own two rows.  A silent third row is never written.

        The part link is inserted with ``ON CONFLICT DO NOTHING``, so it too
        keeps first-writer semantics.  Every scalar is bounded by the module's
        validators before any statement runs, so a malformed field is refused
        instead of surfacing as a raw ``sqlite3.IntegrityError``: ``sha256``
        goes through ``_content_sha256`` (64 lowercase hex), not ``_text`` —
        the value is a content hash the clash/repoint branch below trusts, and
        free text there could rewrite another object's ``storage_key``.  The
        rest are ``_text`` / ``_integer``.  ``storage_key`` is the caller's
        ``audio_path`` verbatim — this layer does not resolve or normalize
        paths.
        """
        bvid = _text(bvid, "bvid")
        page_index = _integer(page_index, "page_index", minimum=0)
        audio_path = _text(audio_path, "audio_path")
        sha256 = _content_sha256(sha256, "sha256")
        byte_size = _integer(byte_size, "byte_size", minimum=0)
        format = _text(format, "format")
        duration_ms = _integer(duration_ms, "duration_ms", minimum=0)
        acquisition_source = _text(acquisition_source, "acquisition_source")
        acquired_at = _integer(acquired_at, "acquired_at", minimum=0)

        part = self.connection.execute(
            "SELECT video_part_id FROM video_parts WHERE bvid = ? AND page_index = ?",
            (bvid, page_index),
        ).fetchone()
        if part is None:
            raise ValueError(
                f"unknown video part: bvid={bvid!r}, page_index={page_index!r}"
            )
        video_part_id = int(part["video_part_id"])

        with _transaction(self.connection):
            existing = self.connection.execute(
                "SELECT audio_id, sha256, byte_size, format, duration_ms "
                "FROM audio_objects WHERE storage_key = ?",
                (audio_path,),
            ).fetchone()
            repoint = False
            if existing is None:
                # No row at this path: the same content may already be archived
                # under another one.  Reuse that row and move its path column to
                # the location the caller asked to occupy.
                existing = self.connection.execute(
                    "SELECT audio_id, sha256, byte_size, format, duration_ms "
                    "FROM audio_objects WHERE sha256 = ?",
                    (sha256,),
                ).fetchone()
                repoint = existing is not None

            if existing is None:
                cursor = self.connection.execute(
                    """
                    INSERT INTO audio_objects(
                        sha256, byte_size, format, duration_ms, storage_key, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (sha256, byte_size, format, duration_ms, audio_path, acquired_at),
                )
                audio_id = int(cursor.lastrowid)
            else:
                audio_id = int(existing["audio_id"])
                updates: dict[str, object] = {
                    column: value
                    for column, value in (
                        ("sha256", sha256),
                        ("byte_size", byte_size),
                        ("format", format),
                        ("duration_ms", duration_ms),
                    )
                    if existing[column] != value
                }
                if repoint:
                    updates["storage_key"] = audio_path
                elif "sha256" in updates:
                    # The path keeps its row, but this content is already
                    # archived at another location.  ``sha256`` is UNIQUE, so no
                    # single row can carry both paths: refuse instead of leaking
                    # an IntegrityError from the UPDATE below.
                    clash = self.connection.execute(
                        "SELECT storage_key FROM audio_objects "
                        "WHERE sha256 = ? AND audio_id != ?",
                        (sha256, audio_id),
                    ).fetchone()
                    if clash is not None:
                        raise ValueError(
                            "audio content already archived at "
                            f"{clash['storage_key']!r}: cannot record "
                            f"sha256={sha256!r} at storage_key={audio_path!r}"
                        )
                if updates:
                    assignments = ", ".join(f"{column} = ?" for column in updates)
                    self.connection.execute(
                        f"UPDATE audio_objects SET {assignments} WHERE audio_id = ?",
                        (*updates.values(), audio_id),
                    )

            self.connection.execute(
                """
                INSERT INTO part_audio_objects(
                    video_part_id, audio_id, acquired_at, acquisition_source
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(video_part_id, audio_id) DO NOTHING
                """,
                (video_part_id, audio_id, acquired_at, acquisition_source),
            )
        return audio_id

    def mark_transcript_stored(
        self,
        *,
        bvid: str,
        page_index: int,
        transcript_id: int,
        run_id: str,
        started_at: int,
        finished_at: int,
    ) -> None:
        """Record that a stored transcript now answers for this part.

        The attempt row is the evidence: ``outcome='stored'`` with the transcript
        reference and no error code, scoped to the caller's existing run.  The
        part's gap membership changes because that row exists, not because any
        status column is rewritten.
        """
        bvid = _text(bvid, "bvid")
        page_index = _integer(page_index, "page_index", minimum=0)
        run_id = _text(run_id, "run_id")
        transcript_id = _integer(transcript_id, "transcript_id", minimum=1)
        started_at = _integer(started_at, "started_at", minimum=0)
        finished_at = _integer(finished_at, "finished_at", minimum=0)
        if finished_at < started_at:
            raise ValueError("finished_at must not precede started_at")
        part = self.connection.execute(
            "SELECT video_part_id FROM video_parts WHERE bvid = ? AND page_index = ?",
            (bvid, page_index),
        ).fetchone()
        if part is None:
            raise ValueError(
                f"unknown video part: bvid={bvid!r}, page_index={page_index!r}"
            )
        video_part_id = int(part["video_part_id"])

        transcript = self.connection.execute(
            "SELECT video_part_id FROM transcripts WHERE transcript_id = ?",
            (transcript_id,),
        ).fetchone()
        if transcript is None or int(transcript["video_part_id"]) != video_part_id:
            raise ValueError(
                f"unknown transcript for this part: transcript_id={transcript_id!r}, "
                f"bvid={bvid!r}, page_index={page_index!r}"
            )

        run = self.connection.execute(
            "SELECT 1 FROM acquisition_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if run is None:
            raise ValueError(f"unknown run_id: {run_id!r}")

        with _transaction(self.connection):
            self.connection.execute(
                """
                INSERT INTO acquisition_attempts(
                    run_id, video_part_id, outcome, error_code, transcript_id,
                    started_at, finished_at
                ) VALUES (?, ?, 'stored', NULL, ?, ?, ?)
                ON CONFLICT(run_id, video_part_id) DO NOTHING
                """,
                (run_id, video_part_id, transcript_id, started_at, finished_at),
            )

    def list_queue_gaps(
        self,
        *,
        gap: QueueGap,
        limit: int | None = None,
        bvid: str | None = None,
        page: int | None = None,
    ) -> list[QueueGapItem]:
        """Return the parts one gap's queue holds, in the locked work order.

        ``gap`` names the queue and is validated against the three the archive
        drains; a fourth name raises ``ValueError`` rather than silently
        reading nothing.  ``limit`` follows the module-wide read rule — a
        non-integer or a ``bool`` raises ``TypeError``, a limit below ``1``
        raises ``ValueError``, and ``None`` means unbounded.  ``bvid`` and
        ``page`` each add one predicate when given, so a caller narrows the
        queue to one video or one part; neither narrows the read when absent.

        The order ``pubdate DESC, bvid ASC, page_index ASC`` is appended by
        this method, not declared by the view: newest video first, and within
        one publication second the bvid then the page index break the tie, so
        the same store always answers the same sequence — page by page, which
        is what makes ``limit`` a stable rotation through a queue instead of a
        fresh sample of it.  ``attempt_count`` is counted per entry by run kind
        (``'subtitle'`` for ``missing_subtitle``, ``'audio'`` for the other
        two) over the returned rows only, in one grouped read per page rather
        than one read per row.  Read-only: no write, no commit.
        """
        gap = _choice(gap, "gap", ALLOWED_QUEUE_GAPS)
        if limit is not None:
            if isinstance(limit, bool) or not isinstance(limit, int):
                raise TypeError("limit must be an integer or None")
            if limit < 1:
                raise ValueError("limit must be a positive integer")
        where_clauses: list[str] = []
        parameters: list[object] = []
        if bvid is not None:
            where_clauses.append("bvid = ?")
            parameters.append(_text(bvid, "bvid"))
        if page is not None:
            where_clauses.append("page_index = ?")
            parameters.append(_integer(page, "page_index", minimum=0))
        query = f"SELECT * FROM {self._VIEW_BY_GAP[gap]}"
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)
        query += " ORDER BY pubdate DESC, bvid ASC, page_index ASC"
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)
        rows = self.connection.execute(query, parameters).fetchall()
        counts = self._attempt_counts(
            [int(row["video_part_id"]) for row in rows], self._KIND_BY_GAP[gap]
        )
        return [
            self._gap_item(row, gap, counts.get(int(row["video_part_id"]), 0))
            for row in rows
        ]

    def count_queue_gaps(self) -> dict[QueueGap, int]:
        """Count the parts each of the three queues holds, all three always.

        **The three values overlap and must never be summed.**  The gaps are not
        a partition: a transcriptless part with a ``no-subtitle``/``failed``
        subtitle attempt and no audio sits in ``missing_audio``, and a part with
        audio evidence and no transcript sits in ``missing_transcript`` — a part
        may be counted by two of these keys, or by one, but ``sum(...)`` answers
        no question about the store.  A backlog total needs its own distinct
        query, not an addition of these three.

        ``0`` is reported rather than omitted: a caller renders three queue
        sizes, and a queue that drained completely is a size, not a missing
        key.  The keys come back in the declaration order of the view table
        above, so a caller iterates the mapping without re-sorting it.
        Read-only: no write, no commit.
        """
        return {
            gap: int(
                self.connection.execute(
                    f"SELECT COUNT(*) FROM {view}"
                ).fetchone()[0]
            )
            for gap, view in self._VIEW_BY_GAP.items()
        }

    def read_audio_objects(self) -> dict[str, tuple[int, str]]:
        """Map every ``audio_objects.storage_key`` to ``(byte_size, sha256)``.

        Both halves make the contract's ``already`` counter ("present **and
        matched**") checkable: a ``stat`` against the size decides the default
        run without reading a byte, so the published cost model ("zero file reads
        for a row that already exists") survives the comparison, and the stored
        digest is what ``--deep`` compares a fresh read against.
        """
        return {
            str(row["storage_key"]): (int(row["byte_size"]), str(row["sha256"]))
            for row in self.connection.execute(
                "SELECT storage_key, byte_size, sha256 FROM audio_objects "
                "ORDER BY audio_id"
            ).fetchall()
        }

    def read_part_durations(self, work_ids: Iterable[str]) -> dict[str, int]:
        """Map page-qualified work ids to the store's own ``duration_ms``.

        The manifest records whole **seconds** (``duration_s``) because its
        writers floor and clamp them, so reconstructing milliseconds from a
        manifest row loses the exact value (``1234567 ms → 1234 s → 1234000 ms``).
        The store holds the exact figure, so the reconciliation reads it here
        rather than trusting the coarser surface.  A work id whose part is absent
        is simply omitted; the caller records the schema's documented "unknown".

        The key set is read straight off the ``video_parts`` rows for the bvids
        named, then emitted in this module's ``<bvid>:p<index>`` spelling, so the
        caller never has to parse or re-derive an identity.
        """
        requested = {str(work_id) for work_id in work_ids}
        if not requested:
            return {}
        bvids = tuple(dict.fromkeys(key.split(":", 1)[0] for key in requested))
        durations: dict[str, int] = {}
        for start in range(0, len(bvids), _PUBDATE_CHUNK):
            chunk = bvids[start : start + _PUBDATE_CHUNK]
            placeholders = ", ".join("?" * len(chunk))
            for row in self.connection.execute(
                "SELECT bvid, page_index, duration_ms FROM video_parts "
                f"WHERE bvid IN ({placeholders})",
                chunk,
            ).fetchall():
                key = f"{row['bvid']}:p{int(row['page_index'])}"
                if key in requested:
                    durations[key] = int(row["duration_ms"])
        return durations

    def read_audio_object_keys(self) -> tuple[str, ...]:
        """Every ``audio_objects.storage_key``, the store's recorded locations.

        The reconciliation matches a manifest candidate on this set, because
        ``storage_key`` — not ``sha256`` — is what ``mark_audio_acquired`` uses
        as an object's identity.  Read in one query rather than per candidate so
        the inventory walk pays one store read, not one per file.
        """
        return tuple(
            str(row["storage_key"])
            for row in self.connection.execute(
                "SELECT storage_key FROM audio_objects ORDER BY audio_id"
            ).fetchall()
        )

    def read_audio_object_ids(self) -> tuple[int, ...]:
        """Every ``audio_objects.audio_id``.

        Paired with :meth:`read_linked_audio_ids` this answers the ``unlinked``
        counter: an object row that no ``part_audio_objects`` row attributes to
        a part.
        """
        return tuple(
            int(row["audio_id"])
            for row in self.connection.execute(
                "SELECT audio_id FROM audio_objects ORDER BY audio_id"
            ).fetchall()
        )

    def read_linked_audio_ids(self) -> tuple[int, ...]:
        """Every ``part_audio_objects.audio_id`` — the objects tied to a part.

        A set, not a bag: an object attributed to several parts is still one
        attributed object, and the ``unlinked`` counter is a subtraction over
        objects.
        """
        return tuple(
            int(row["audio_id"])
            for row in self.connection.execute(
                "SELECT DISTINCT audio_id FROM part_audio_objects "
                "ORDER BY audio_id"
            ).fetchall()
        )

    @staticmethod
    def _gap_item(row: sqlite3.Row, gap: str, attempt_count: int) -> QueueGapItem:
        """Map one view row to one typed queue entry, whatever the view holds.

        One mapper serves all three views.  The shared nine-column prefix is
        read by name for every one of them; the newest-attempt evidence is read
        only when the row carries the column at all, which the row's own
        ``keys()`` answers — so the one gap view that exposes the columns
        reports them, and the two that do not report ``None`` instead of
        failing the read that a captionless part must still complete.
        """
        columns = set(row.keys())

        def evidence(column: str) -> str | None:
            """Answer one evidence column's value, or None when absent."""
            if column not in columns:
                return None
            return None if row[column] is None else str(row[column])

        return QueueGapItem(
            work_id=str(row["work_id"]),
            bvid=str(row["bvid"]),
            page_index=int(row["page_index"]),
            cid=int(row["cid"]),
            gap=gap,
            pubdate=int(row["pubdate"]),
            video_title=str(row["video_title"]),
            duration_ms=int(row["duration_ms"]),
            newest_outcome=evidence("newest_outcome"),
            newest_error_code=evidence("newest_error_code"),
            attempt_count=attempt_count,
        )

    def _attempt_counts(
        self, video_part_ids: Sequence[int], kind: str
    ) -> dict[int, int]:
        """Count each named part's attempts on one acquisition route.

        One grouped read for the whole page instead of one read per entry: the
        ids are passed in chunks of at most ``_PUBDATE_CHUNK`` parameters for
        the same reason :meth:`TranscriptRepository.read_video_pubdates` chunks
        its bvids — the queue is bounded by the store rather than by this
        module, and the driver bounds one statement.  A part with no attempt on
        that route is absent from the answer rather than present with ``0``, so
        the caller owns what an unattempted part counts as.  Read-only.
        """
        if not video_part_ids:
            return {}
        counts: dict[int, int] = {}
        for start in range(0, len(video_part_ids), _PUBDATE_CHUNK):
            chunk = video_part_ids[start : start + _PUBDATE_CHUNK]
            placeholders = ", ".join("?" * len(chunk))
            counts.update(
                {
                    int(row["video_part_id"]): int(row["attempts"])
                    for row in self.connection.execute(
                        "SELECT aa.video_part_id AS video_part_id, "
                        "COUNT(*) AS attempts "
                        "FROM acquisition_attempts AS aa "
                        "JOIN acquisition_runs AS ar ON ar.run_id = aa.run_id "
                        f"WHERE ar.kind = ? AND aa.video_part_id IN ({placeholders}) "
                        "GROUP BY aa.video_part_id",
                        (kind, *chunk),
                    ).fetchall()
                }
            )
        return counts


__all__ = [
    "DatabaseConnection",
    "MediaQueueRepository",
    "MetadataRepository",
    "SchemaContractError",
    "TranscriptRepository",
    "duration_to_ms",
    "initialize_schema",
    "normalize_page_index",
    "open_database",
    "require_subtitle_schema",
]
