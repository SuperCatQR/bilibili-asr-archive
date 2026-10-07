"""Locks implementation."""

from __future__ import annotations

import os
import sys
import threading
from contextlib import contextmanager
from typing import Iterator
from bili_asr.persistence import file_lock


ARCHIVE_WRITER_LOCK = os.path.join("coordinator", "archive-writer.lock")


class ArchiveBusyError(RuntimeError):
    """Raised when another sequential archive operation owns the root."""

    def __init__(self) -> None:
        super().__init__("archive_busy")


_ARCHIVE_WRITER_STATE = threading.local()


def _current_file_lock():
    # The coordinator is the public composition seam. Resolve its lock hook at
    # call time so tests and embedders can instrument that seam without making
    # the pipeline layer import the coordinator back.
    coordinator = sys.modules.get("bili_asr.coordinator")
    return getattr(coordinator, "file_lock", file_lock)


@contextmanager
def archive_writer(root: str | os.PathLike[str], *, blocking: bool = False) -> Iterator[None]:
    """Own the archive root, reentrant only within the owning thread."""
    lock_target = os.path.join(os.fspath(root), ARCHIVE_WRITER_LOCK)
    owned = getattr(_ARCHIVE_WRITER_STATE, "owned", None)
    if owned == lock_target:
        yield
        return
    lock = _current_file_lock()(lock_target, blocking=blocking)
    try:
        lock.__enter__()
    except OSError as exc:
        if not blocking and isinstance(exc.__cause__, BlockingIOError):
            raise ArchiveBusyError() from exc
        raise
    _ARCHIVE_WRITER_STATE.owned = lock_target
    try:
        yield
    except BaseException as exc:
        _ARCHIVE_WRITER_STATE.owned = None
        if not lock.__exit__(type(exc), exc, exc.__traceback__):
            raise
    else:
        _ARCHIVE_WRITER_STATE.owned = None
        lock.__exit__(None, None, None)
