"""Durable standard-library file persistence primitives."""

from __future__ import annotations

from contextlib import contextmanager
import errno
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Iterator


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
def file_lock(path: str | os.PathLike[str]) -> Iterator[None]:
    """Hold an exclusive cross-process lock in a stable adjacent lock file."""
    lock_path = os.fspath(path) + ".lock"
    os.makedirs(os.path.dirname(lock_path) or ".", exist_ok=True)
    fh = open(lock_path, "a+b")
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            fh.write(b"0")
            fh.flush()
            while True:
                try:
                    msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
                    break
                except OSError as exc:
                    if exc.errno not in (errno.EACCES, errno.EDEADLK):
                        raise
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    except (ValueError, TypeError):
        raise
    except BaseException as exc:
        raise _stable_error("lock") from exc
    finally:
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


def _json_line(record: dict[str, Any]) -> bytes:
    if not isinstance(record, dict):
        raise ValueError("JSONL record must be an object")
    try:
        return (json.dumps(record, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("JSONL record is not serializable") from exc


def append_jsonl_record(path: str | os.PathLike[str], record: dict[str, Any]) -> None:
    """Append one durable JSON object without reading existing content."""
    target = os.fspath(path)
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    line = _json_line(record)
    try:
        with open(target, "ab") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
        _sync_directory(os.path.dirname(target) or ".")
    except BaseException as exc:
        if isinstance(exc, (ValueError, TypeError)):
            raise
        raise _stable_error("append") from exc


def replace_file_atomically(
    path: str | os.PathLike[str], data: bytes | str, *, temp_suffix: str = ".tmp"
) -> None:
    """Durably replace a file using an owned same-directory temporary file."""
    target = os.fspath(path)
    directory = os.path.dirname(target) or "."
    os.makedirs(directory, exist_ok=True)
    if isinstance(data, str):
        payload = data.encode("utf-8")
    elif isinstance(data, bytes):
        payload = data
    else:
        raise TypeError("atomic replacement data must be bytes or str")
    fd, temporary = tempfile.mkstemp(prefix="." + Path(target).name + ".", suffix=temp_suffix, dir=directory)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        _sync_directory(directory)
        os.replace(temporary, target)
        temporary = ""
    except BaseException as exc:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass
        raise _stable_error("replace") from exc
