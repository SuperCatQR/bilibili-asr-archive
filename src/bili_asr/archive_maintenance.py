"""Shared writer access and exclusive snapshot access to a local archive."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import stat
import threading
from typing import Iterator


class ArchiveAccessError(ValueError):
    """An archive cannot participate in maintenance coordination."""


class ArchiveBusyError(ArchiveAccessError):
    """A writer or snapshot operation already owns conflicting access."""


_HELD = threading.local()


def _windows_lock(fd: int, *, exclusive: bool):
    import ctypes
    from ctypes import wintypes
    import msvcrt

    class Overlapped(ctypes.Structure):
        _fields_ = [
            ("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
            ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
            ("hEvent", wintypes.HANDLE),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LockFileEx.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
        wintypes.DWORD, ctypes.POINTER(Overlapped),
    ]
    kernel.LockFileEx.restype = wintypes.BOOL
    kernel.UnlockFileEx.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(Overlapped),
    ]
    kernel.UnlockFileEx.restype = wintypes.BOOL
    handle = wintypes.HANDLE(msvcrt.get_osfhandle(fd))
    overlapped = Overlapped()
    # FAIL_IMMEDIATELY plus optional EXCLUSIVE_LOCK; ordinary writers share access.
    if not kernel.LockFileEx(handle, 1 | (2 if exclusive else 0), 0, 1, 0, ctypes.byref(overlapped)):
        error = ctypes.get_last_error()
        if error in (32, 33):
            raise ArchiveBusyError("archive_busy: stop archive writers before saving or restoring")
        raise ctypes.WinError(error)

    def unlock() -> None:
        if not kernel.UnlockFileEx(handle, 0, 1, 0, ctypes.byref(overlapped)):
            raise ctypes.WinError(ctypes.get_last_error())

    return unlock


@contextmanager
def archive_access(
    root: str | os.PathLike[str], *, exclusive: bool = False, create_root: bool = True,
) -> Iterator[None]:
    """Refuse conflicting access without serializing independent workflow workers.

    The stable lock lives beside the root so restoring a staging directory can
    atomically publish an archive without moving or replacing the lock inode.
    ``create_root`` permits a missing root and creates only its parent directory.
    Programmatic writers must hold shared access across their entire operation.
    """
    requested = Path(root)
    if requested.is_symlink():
        raise ArchiveAccessError("archive root must not be a symlink")
    archive = requested.resolve()
    if archive == archive.parent:
        raise ArchiveAccessError("filesystem root cannot be an archive root")
    if archive.exists() and not archive.is_dir():
        raise ArchiveAccessError("archive root is not a directory")
    if not create_root and not archive.is_dir():
        raise ArchiveAccessError("archive root does not exist")
    if create_root:
        archive.parent.mkdir(parents=True, exist_ok=True)
    lock = archive.parent / f".{archive.name}.archive-maintenance.lock"
    key = os.path.normcase(os.fspath(lock))
    held = getattr(_HELD, "locks", None)
    if held is None:
        held = {}
        _HELD.locks = held
    if key in held:
        if exclusive and not held[key]:
            raise ArchiveBusyError("archive_busy: cannot upgrade active writer access")
        yield
        return

    fd = None
    unlock = None
    try:
        if lock.is_symlink():
            raise ArchiveAccessError("archive maintenance lock must not be a symlink")
        fd = os.open(lock, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ArchiveAccessError("archive maintenance lock is not a regular file")
        if os.name == "nt":
            unlock = _windows_lock(fd, exclusive=exclusive)
        else:
            import fcntl

            try:
                fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ArchiveBusyError(
                    "archive_busy: stop archive writers before saving or restoring"
                ) from exc
            def unlock() -> None:
                fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError as exc:
        if fd is not None:
            os.close(fd)
        raise ArchiveAccessError("archive maintenance lock cannot be acquired") from exc
    except Exception:
        if fd is not None:
            os.close(fd)
        raise

    held[key] = exclusive
    try:
        yield
    finally:
        held.pop(key, None)
        try:
            if unlock is not None:
                unlock()
        finally:
            os.close(fd)
