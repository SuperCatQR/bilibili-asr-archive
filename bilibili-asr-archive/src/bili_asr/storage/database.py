"""Database implementation."""

from __future__ import annotations

from contextlib import contextmanager
from importlib import resources
import math
import os
from pathlib import Path
import re
import sqlite3
from typing import Iterator, TypeAlias
from bili_asr.storage.models import ALLOWED_ATTEMPT_OUTCOMES, ALLOWED_RUN_OUTCOMES


DatabaseConnection: TypeAlias = sqlite3.Connection


_ARCHIVE_DATABASE_NAME = "archive.db"


_DATABASE_SUFFIXES = frozenset({".db", ".sqlite", ".sqlite3"})


_TERMINAL_RUN_OUTCOMES = ALLOWED_RUN_OUTCOMES - frozenset({"running"})


_TERMINAL_ACQUISITION_OUTCOMES = frozenset({"complete", "partial", "failed"})


_NO_TRANSCRIPT_ATTEMPT_OUTCOMES = ALLOWED_ATTEMPT_OUTCOMES - {"stored", "unchanged"}


_SCHEMA_RESOURCE = resources.files(__package__).joinpath("schema.sql")


_TRANSCRIPT_SCHEMA_RESOURCE = resources.files(__package__).joinpath(
    "schema-transcripts.sql"
)

_WORKFLOW_SCHEMA_RESOURCE = resources.files(__package__).joinpath("schema-workflow.sql")
_EDITORIAL_SCHEMA_RESOURCE = resources.files(__package__).joinpath("schema-editorial.sql")


_TRANSCRIPT_CONTRACT_COLUMNS = frozenset({"language", "content_sha256"})


_SUBTITLE_SCHEMA_OBJECTS = (
    "acquisition_attempts",
    "acquisition_runs",
    "v_pending_subtitles",
)


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


_VIEW_NAME_RE = re.compile(
    r"CREATE\s+VIEW(?:\s+IF\s+NOT\s+EXISTS)?\s+([A-Za-z_][A-Za-z0-9_]*)\s+AS\b",
    re.IGNORECASE | re.DOTALL,
)


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
        # Earlier attempts did not verify login or distinguish listing absence
        # from auth/body failures. Preserve their facts without backfilling proof.
        attempt_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(acquisition_attempts)")
        }
        for verification_column in ("credential_verified", "absence_verified"):
            if attempt_columns and verification_column not in attempt_columns:
                connection.execute(
                    f"ALTER TABLE acquisition_attempts ADD COLUMN {verification_column} "
                    "INTEGER NOT NULL DEFAULT 0 "
                    f"CHECK ({verification_column} IN (0, 1))"
                )
        connection.executescript(
            _TRANSCRIPT_SCHEMA_RESOURCE.read_text(encoding="utf-8")
        )
        connection.executescript(
            _WORKFLOW_SCHEMA_RESOURCE.read_text(encoding="utf-8")
        )
        connection.executescript(
            _EDITORIAL_SCHEMA_RESOURCE.read_text(encoding="utf-8")
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
