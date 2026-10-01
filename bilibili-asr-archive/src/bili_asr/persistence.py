"""Durable standard-library file persistence primitives."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import errno
import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Any, Iterator, Mapping


def utc_now_iso() -> str:
    """Single UTC ISO-8601 timestamp source (``...Z``, microsecond precision)."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class PersistenceError(OSError):
    """Stable, redacted persistence failure."""


def _stable_error(operation: str) -> PersistenceError:
    return PersistenceError(f"persistence {operation} failed")


def _sync_directory(directory: str) -> None:
    flags = getattr(os, "O_DIRECTORY", 0) | os.O_RDONLY
    fd = os.open(directory, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def file_lock(path: str | os.PathLike[str], *, blocking: bool = True) -> Iterator[None]:
    """Hold an exclusive cross-process lock in a stable adjacent lock file."""
    requested = os.fspath(path)
    lock_path = requested if requested.endswith(".lock") else requested + ".lock"
    # flock is process-associated on some platforms; keep nested same-thread
    # ownership explicit so public wrappers can safely share one root lock.
    state = getattr(_LOCK_STATE, "held", None)
    if state is None:
        state = {}
        _LOCK_STATE.held = state
    existing = state.get(lock_path)
    if existing is not None:
        state[lock_path] = existing + 1
        try:
            yield
        finally:
            if state[lock_path] == 1:
                del state[lock_path]
            else:
                state[lock_path] -= 1
        return
    try:
        os.makedirs(os.path.dirname(lock_path) or ".", exist_ok=True)
        fh = open(lock_path, "a+b")
    except (ValueError, TypeError):
        raise
    except OSError as exc:
        raise _stable_error("lock") from exc
    acquired = False
    try:
        try:
            if os.name == "nt":
                import msvcrt
                fh.seek(0, os.SEEK_END)
                if fh.tell() == 0:
                    fh.write(b"0")
                    fh.flush()
                fh.seek(0)
                msvcrt.locking(
                    fh.fileno(), msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1
                )
                acquired = True
            else:
                import fcntl
                flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
                fcntl.flock(fh.fileno(), flags)
                acquired = True
        except (ValueError, TypeError):
            raise
        except OSError as exc:
            raise _stable_error("lock") from exc
        state[lock_path] = 1
        yield
    finally:
        state.pop(lock_path, None)
        if acquired:
            try:
                if os.name == "nt":
                    import msvcrt
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        fh.close()

_LOCK_STATE = threading.local()


def _json_line(record: dict[str, Any]) -> bytes:
    if not isinstance(record, dict):
        raise ValueError("JSONL record must be an object")
    try:
        return (json.dumps(record, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("JSONL record is not serializable") from exc


def append_jsonl_record(path: str | os.PathLike[str], record: Mapping[str, Any], *, lock_path: str | os.PathLike[str] | None = None) -> None:
    """Append one durable JSON object; caller owns any external lock.

    ``lock_path`` is retained for source compatibility and is intentionally
    ignored. Callers that need cross-process serialization must hold
    :func:`file_lock` around this primitive.
    """
    del lock_path
    target = os.fspath(path)
    line = _json_line(dict(record))
    try:
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        with open(target, "ab") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
        _sync_directory(os.path.dirname(target) or ".")
    except (ValueError, TypeError):
        raise
    except OSError as exc:
        raise _stable_error("append") from exc


def _replace_directory_sync(directory: str) -> None:
    try:
        _sync_directory(directory)
    except OSError as exc:
        raise _stable_error("replace") from exc


def replace_file_atomically(
    path: str | os.PathLike[str], data: bytes | str, *, temp_suffix: str = ".tmp"
) -> None:
    """Durably replace a file using an owned same-directory temporary file."""
    target = os.fspath(path)
    directory = os.path.dirname(target) or "."
    if isinstance(data, str):
        payload = data.encode("utf-8")
    elif isinstance(data, bytes):
        payload = data
    else:
        raise TypeError("atomic replacement data must be bytes or str")
    temporary = ""
    try:
        os.makedirs(directory, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix="." + Path(target).name + ".", suffix=temp_suffix, dir=directory
        )
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        _replace_directory_sync(directory)
        os.replace(temporary, target)
        temporary = ""
        _replace_directory_sync(directory)
    except (ValueError, TypeError):
        raise
    except OSError as exc:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass
        raise _stable_error("replace") from exc
