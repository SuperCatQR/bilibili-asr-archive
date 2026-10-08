"""Read-only archive contracts, database backups, and restored-job recovery."""

from __future__ import annotations

from contextlib import closing
from functools import lru_cache
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
import time
from typing import Any

from bili_asr.archive import BUNDLE_MARKER_NAME, _owned_bundle_parts
from bili_asr.artifacts import REQUIRED_ARTIFACT_KEYS
from bili_asr.storage.database import (
    _normalize_view_sql,
    _strip_sql_comments,
    initialize_schema,
)


_BACKUP_TIMEOUT_SECONDS = 10.0
_PUBLICATION_KEYS = REQUIRED_ARTIFACT_KEYS
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_WINDOWS_DEVICE = re.compile(r"(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)", re.I)


class SnapshotDatabaseError(ValueError):
    """The archive database or one of its portable references is invalid."""


def _connect(database_path: Path, *, readonly: bool = True) -> sqlite3.Connection:
    path = Path(database_path).resolve()
    if not path.is_file():
        raise SnapshotDatabaseError(f"archive database is missing: {path}")
    mode = "ro" if readonly else "rw"
    connection = sqlite3.connect(
        path.as_uri() + f"?mode={mode}", uri=True, timeout=0.2
    )
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _checks(sql: str) -> list[str]:
    """Read CHECK bodies; PRAGMA exposes columns/FKs but not CHECK constraints."""
    text = _strip_sql_comments(sql)
    checks: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char in "'\"`[":
            closing = "]" if char == "[" else char
            index += 1
            while index < len(text):
                if text[index] == closing:
                    if closing != "]" and text[index:index + 2] == closing * 2:
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            continue
        match = re.match(r"CHECK\s*\(", text[index:], flags=re.I)
        if match is None or (index and (text[index - 1].isalnum() or text[index - 1] == "_")):
            index += 1
            continue
        start = index + match.end()
        cursor, depth = start, 1
        quote: str | None = None
        while cursor < len(text) and depth:
            current = text[cursor]
            if quote is not None:
                if current == quote:
                    if quote != "]" and text[cursor:cursor + 2] == quote * 2:
                        cursor += 2
                        continue
                    quote = None
            elif current in "'\"`[":
                quote = "]" if current == "[" else current
            elif current == "(":
                depth += 1
            elif current == ")":
                depth -= 1
            cursor += 1
        if depth:
            raise SnapshotDatabaseError("malformed CHECK constraint in archive schema")
        checks.append(_normalize_view_sql(text[start:cursor - 1]))
        index = cursor
    return sorted(checks)


def _index_shape(connection: sqlite3.Connection, name: str) -> list[list[Any]]:
    return [
        [row[2], row[3], row[4], row[5]]
        for row in connection.execute(f"PRAGMA index_xinfo({_identifier(name)})")
    ]


def _table_shape(connection: sqlite3.Connection, name: str, sql: str) -> dict[str, Any]:
    columns = [list(row[1:]) for row in connection.execute(
        f"PRAGMA table_xinfo({_identifier(name)})"
    )]
    foreign_keys = [list(row[1:]) for row in connection.execute(
        f"PRAGMA foreign_key_list({_identifier(name)})"
    )]
    constraints = [
        [row[2], row[3], row[4], _index_shape(connection, row[1])]
        for row in connection.execute(f"PRAGMA index_list({_identifier(name)})")
        if row[3] in ("u", "pk")
    ]
    flags = [list(row[3:]) for row in connection.execute("PRAGMA table_list")
             if row[0] == "main" and row[1] == name]
    return {
        # Match the runtime's strict table contract so a restored archive also
        # passes open_database, including historical ALTER layouts it rejects.
        "sql": _normalize_view_sql(sql),
        "columns": columns,
        "foreign_keys": sorted(foreign_keys, key=repr),
        "constraints": sorted(constraints, key=repr),
        "checks": _checks(sql),
        "flags": flags,
    }


def _schema(connection: sqlite3.Connection) -> dict[str, Any]:
    objects: dict[str, Any] = {}
    for kind, name, sql in connection.execute(
        "SELECT type, name, sql FROM sqlite_master "
        "WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ):
        if kind == "table":
            body: Any = _table_shape(connection, name, sql)
        else:
            body = _normalize_view_sql(sql)
        objects[name] = {"kind": kind, "body": body}
    return objects


@lru_cache(maxsize=1)
def _current_contract() -> tuple[dict[str, Any], str]:
    with closing(sqlite3.connect(":memory:")) as connection:
        initialize_schema(connection)
        required = _schema(connection)
    canonical = json.dumps(required, sort_keys=True, separators=(",", ":"))
    return required, "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_snapshot_database(database_path: Path, expected_contract: str | None = None) -> str:
    """Require the current shipped schema and healthy data without changing it."""
    required, contract = _current_contract()
    if expected_contract is not None and expected_contract != contract:
        raise SnapshotDatabaseError("snapshot database contract is unsupported by this build")
    try:
        with closing(_connect(database_path)) as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchall()
            if integrity != [("ok",)]:
                details = "; ".join(str(row[0]) for row in integrity[:5])
                raise SnapshotDatabaseError(f"archive database integrity check failed: {details}")
            actual = _schema(connection)
            for name, shape in actual.items():
                if shape["kind"] == "trigger" and name not in required:
                    raise SnapshotDatabaseError(f"archive database has unsupported trigger {name}")
            for name, shape in required.items():
                if name not in actual:
                    raise SnapshotDatabaseError(f"archive database contract is missing {name}")
                if actual[name] != shape:
                    raise SnapshotDatabaseError(f"archive database contract is incompatible at {name}")
            violation = connection.execute("PRAGMA foreign_key_check").fetchone()
            if violation is not None:
                raise SnapshotDatabaseError(f"archive database foreign-key check failed: {violation}")
    except sqlite3.Error as exc:
        raise SnapshotDatabaseError(f"cannot validate archive database: {exc}") from exc
    return contract


def create_database_snapshot(source_db: Path, target_db: Path) -> str:
    """Back up a read-only source, refusing overwrite and indefinitely busy locks."""
    source_db, target_db = Path(source_db), Path(target_db)
    if source_db.resolve() == target_db.resolve():
        raise SnapshotDatabaseError("database snapshot target must differ from its source")
    created = False
    try:
        with closing(_connect(source_db)) as source:
            with target_db.open("xb"):
                created = True
            with closing(_connect(target_db, readonly=False)) as target:
                deadline = time.monotonic() + _BACKUP_TIMEOUT_SECONDS

                def progress(status: int, remaining: int, total: int) -> None:
                    if status in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED) and time.monotonic() >= deadline:
                        raise SnapshotDatabaseError("database snapshot timed out waiting for a database lock")

                source.backup(target, pages=256, progress=progress, sleep=0.05)
        return validate_snapshot_database(target_db)
    except (OSError, sqlite3.Error, SnapshotDatabaseError) as exc:
        if created:
            target_db.unlink(missing_ok=True)
        if isinstance(exc, SnapshotDatabaseError):
            raise
        raise SnapshotDatabaseError(f"cannot create database snapshot: {exc}") from exc


def _portable_key(value: object) -> str:
    if not isinstance(value, str) or not value or value.startswith("/") or "\\" in value:
        raise SnapshotDatabaseError(f"invalid portable artifact path: {value!r}")
    parts = value.split("/")
    for part in parts:
        if (part in ("", ".", "..") or part[-1:] in (".", " ")
                or any(ord(char) < 32 or char in '<>:"|?*' for char in part)
                or _WINDOWS_DEVICE.match(part)):
            raise SnapshotDatabaseError(f"invalid portable artifact path: {value!r}")
    return value


def _digest(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or _HASH.fullmatch(value) is None:
        raise SnapshotDatabaseError(f"invalid artifact SHA-256: {value!r}")
    return value


def _object(value: str, description: str) -> dict[str, Any]:
    try:
        result = json.loads(value)
    except (TypeError, ValueError) as exc:
        raise SnapshotDatabaseError(f"invalid {description} JSON") from exc
    if not isinstance(result, dict):
        raise SnapshotDatabaseError(f"{description} must be a JSON object")
    return result


def required_artifacts(database_path: Path) -> dict[str, str | None]:
    """Read all required file references, including audio attempt dedup paths."""
    validate_snapshot_database(database_path)
    result: dict[str, str | None] = {}

    def add(path: object, digest: object = None) -> None:
        key, expected = _portable_key(path), _digest(digest)
        previous = result.get(key)
        if previous is not None and expected is not None and previous != expected:
            raise SnapshotDatabaseError(f"conflicting artifact hashes for {key}")
        result[key] = previous if previous is not None else expected

    try:
        with closing(_connect(database_path)) as connection:
            for key, digest in connection.execute("SELECT storage_key, sha256 FROM audio_objects"):
                add(key, digest)
            for (raw,) in connection.execute(
                "SELECT a.result_json FROM workflow_attempts AS a "
                "JOIN workflow_jobs AS j ON j.job_id = a.job_id "
                "WHERE a.outcome = 'succeeded' AND j.kind = 'audio'"
            ):
                payload = _object(raw, "successful audio attempt result")
                add(payload.get("storage_key"), payload.get("sha256"))
            for (raw,) in connection.execute("SELECT artifact_json FROM workflow_publications"):
                payload = _object(raw, "workflow publication artifacts")
                for key in _PUBLICATION_KEYS:
                    add(payload.get(key))
                if set(payload) != set(_PUBLICATION_KEYS) or not _owned_bundle_parts(payload):
                    raise SnapshotDatabaseError("workflow publication artifacts do not describe one complete bundle")
                add(str(PurePosixPath(payload["srt_path"]).parent / BUNDLE_MARKER_NAME))
            for key, digest in connection.execute(
                "SELECT relative_path, content_sha256 FROM document_artifacts"
            ):
                add(key, digest)
    except sqlite3.Error as exc:
        raise SnapshotDatabaseError(f"cannot read archive artifact references: {exc}") from exc
    return result


def recover_interrupted_jobs(database_path: Path, snapshot_id: str) -> dict[str, int]:
    """Recover only a restored staging DB, leaving all completed history intact."""
    if not isinstance(snapshot_id, str) or not snapshot_id.strip():
        raise SnapshotDatabaseError("snapshot_id must be non-empty")
    validate_snapshot_database(database_path)
    now = int(time.time())
    counts: dict[str, int] = {}
    try:
        with closing(_connect(database_path, readonly=False)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                attempts = connection.execute(
                    "SELECT attempt_id, result_json FROM workflow_attempts WHERE outcome = 'running'"
                ).fetchall()
                for attempt_id, raw in attempts:
                    evidence = {} if raw is None else _object(raw, "running attempt result")
                    evidence["snapshot_recovery"] = {
                        "snapshot_id": snapshot_id, "reason": "interrupted_by_restore"
                    }
                    connection.execute(
                        "UPDATE workflow_attempts SET outcome = 'failed', "
                        "finished_at = max(started_at, ?), error_code = 'snapshot_restored', result_json = ? "
                        "WHERE attempt_id = ?",
                        (now, json.dumps(evidence, sort_keys=True, separators=(",", ":")), attempt_id),
                    )
                counts["workflow_attempts"] = len(attempts)
                counts["workflow_jobs"] = connection.execute(
                    "UPDATE workflow_jobs SET status = 'queued', lease_owner = NULL, "
                    "lease_expires_at = NULL, available_at = ?, updated_at = ?, "
                    "last_error_code = 'snapshot_restored' WHERE status = 'running'", (now, now)
                ).rowcount
                for table in ("ingestion_runs", "acquisition_runs"):
                    counts[table] = connection.execute(
                        f"UPDATE {table} SET outcome = 'failed', finished_at = max(started_at, ?) "
                        "WHERE outcome = 'running'", (now,)
                    ).rowcount
                counts["editorial_model_calls"] = connection.execute(
                    "UPDATE editorial_model_calls SET finished_at = max(started_at, ?), "
                    "error_code = 'snapshot_restored' WHERE finished_at IS NULL", (now,)
                ).rowcount
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
    except sqlite3.Error as exc:
        raise SnapshotDatabaseError(f"cannot recover restored archive database: {exc}") from exc
    return counts


__all__ = [
    "SnapshotDatabaseError",
    "create_database_snapshot",
    "recover_interrupted_jobs",
    "required_artifacts",
    "validate_snapshot_database",
]
