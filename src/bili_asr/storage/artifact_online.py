"""Optional online coordination schema; runtime access never installs it."""
from __future__ import annotations

import sqlite3
from functools import lru_cache

from bili_asr.storage.artifact_catalog import require_artifact_catalog

EXTENSION = "artifact-online-v1"
SCHEMA_RESOURCE = "schema-artifact-online.sql"


@lru_cache(maxsize=1)
def extension_objects():
    from bili_asr.storage.archive_contracts import _resource
    with sqlite3.connect(":memory:") as reference:
        reference.executescript(_resource(SCHEMA_RESOURCE))
        return {row[0]: (row[1], row[2]) for row in reference.execute(
            "SELECT name,type,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'")}


def require_artifact_online(connection: sqlite3.Connection, *, required: bool = False) -> bool:
    from bili_asr.storage.database import SchemaContractError, _normalize_manuscript_sql
    expected = extension_objects()
    actual = {row[0]: (row[1], row[2]) for row in connection.execute(
        "SELECT name,type,sql FROM sqlite_master WHERE sql IS NOT NULL")}
    if not expected.keys() & actual.keys():
        if required:
            raise SchemaContractError("artifact-online-v1: run explicit archive upgrade into a separate empty target first")
        return False
    require_artifact_catalog(connection, required=True)
    for name, (kind, sql) in expected.items():
        current = actual.get(name)
        if current is None or current[0] != kind or _normalize_manuscript_sql(current[1]) != _normalize_manuscript_sql(sql):
            raise SchemaContractError(f"artifact-online-v1: missing or altered object: {name}")
    if [tuple(row) for row in connection.execute("SELECT singleton,version FROM artifact_online_contract")] != [(1, 1)]:
        raise SchemaContractError("artifact-online-v1: unsupported contract marker")
    return True


def install_online_in_staged_copy(connection: sqlite3.Connection) -> None:
    """Internal converter step; caller owns and verifies an unpublished stage."""
    from bili_asr.storage.archive_contracts import _resource
    require_artifact_catalog(connection, required=True)
    if require_artifact_online(connection):
        raise ValueError("artifact-online-v1 is already installed")
    if connection.in_transaction:
        raise ValueError("online extension installation requires no active transaction")
    connection.executescript(_resource(SCHEMA_RESOURCE))
    require_artifact_online(connection, required=True)
