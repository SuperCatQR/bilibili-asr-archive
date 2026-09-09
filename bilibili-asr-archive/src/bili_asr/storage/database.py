"""SQLite bootstrap for normalized Bilibili metadata storage."""

from __future__ import annotations

import math
import os
from pathlib import Path
import sqlite3
from typing import TypeAlias


DatabaseConnection: TypeAlias = sqlite3.Connection
_ARCHIVE_DATABASE_NAME = "archive.db"
_DATABASE_SUFFIXES = frozenset({".db", ".sqlite", ".sqlite3"})
_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


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
    connection.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
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


__all__ = [
    "DatabaseConnection",
    "duration_to_ms",
    "initialize_schema",
    "normalize_page_index",
    "open_database",
]
