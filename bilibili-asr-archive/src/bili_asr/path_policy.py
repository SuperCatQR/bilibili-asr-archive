"""Shared confinement policy for persisted archive audio paths."""

from __future__ import annotations

import os
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

AUDIO_EXTENSIONS = frozenset({".m4a", ".flac"})


def _audio_parts(declared_path: str | os.PathLike[str]) -> tuple[str, ...] | None:
    try:
        declared = Path(os.fspath(declared_path))
    except (TypeError, ValueError):
        return None
    if declared.is_absolute() or not declared.parts:
        return None
    if any(part in ("", ".", "..") for part in declared.parts):
        return None
    if declared.parts[0] != "audio" or len(declared.parts) != 2:
        return None
    if Path(declared.parts[-1]).suffix.lower() not in AUDIO_EXTENSIONS:
        return None
    return declared.parts


def _open_audio_file(archive_root: str | os.PathLike[str], parts: tuple[str, ...]) -> int:
    root_fd = os.open(
        os.fspath(archive_root),
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    audio_fd = None
    try:
        audio_fd = os.open(
            parts[0],
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=root_fd,
        )
        fd = os.open(
            parts[1],
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=audio_fd,
        )
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            os.close(fd)
            raise OSError("audio file is not regular")
        return fd
    finally:
        if audio_fd is not None:
            os.close(audio_fd)
        os.close(root_fd)


def confined_audio_path(
    archive_root: str | os.PathLike[str],
    declared_path: str | os.PathLike[str] | None,
    *,
    require_exists: bool,
) -> Path | None:
    """Return a confined lexical audio path after no-follow validation."""
    if not isinstance(declared_path, (str, os.PathLike)):
        return None
    parts = _audio_parts(declared_path)
    if parts is None:
        return None
    try:
        root = Path(os.fspath(archive_root))
        if not root.is_absolute():
            root = Path(os.path.abspath(root))
        if require_exists:
            fd = _open_audio_file(root, parts)
            os.close(fd)
        else:
            root_fd = os.open(
                os.fspath(root),
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
            )
            try:
                audio_fd = os.open(
                    parts[0],
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=root_fd,
                )
                os.close(audio_fd)
            finally:
                os.close(root_fd)
        return root.joinpath(*parts)
    except (OSError, RuntimeError, ValueError):
        return None


@contextmanager
def confined_audio_file(
    archive_root: str | os.PathLike[str],
    declared_path: str | os.PathLike[str] | None,
    *,
    require_exists: bool = True,
) -> Iterator[str]:
    """Keep a confined audio descriptor open through the consuming operation."""
    if not isinstance(declared_path, (str, os.PathLike)):
        raise OSError("invalid audio path")
    parts = _audio_parts(declared_path)
    if parts is None or not require_exists:
        raise OSError("invalid audio path")
    fd = _open_audio_file(archive_root, parts)
    try:
        proc_fd = f"/proc/self/fd/{fd}"
        if os.name == "posix" and os.path.exists(proc_fd):
            yield proc_fd
        else:
            yield os.fspath(Path(os.path.abspath(os.fspath(archive_root))).joinpath(*parts))
    finally:
        os.close(fd)


def unlink_confined_audio(
    archive_root: str | os.PathLike[str],
    declared_path: str | os.PathLike[str],
) -> bool:
    """Unlink one validated audio entry through its anchored parent fd."""
    parts = _audio_parts(declared_path)
    if parts is None:
        raise ValueError("invalid audio path")
    root_fd = os.open(
        os.fspath(archive_root),
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    audio_fd = None
    try:
        audio_fd = os.open(
            parts[0],
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=root_fd,
        )
        try:
            fd = os.open(parts[1], os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=audio_fd)
        except FileNotFoundError:
            return False
        except OSError as exc:
            if getattr(exc, "errno", None) == getattr(os, "ELOOP", 40):
                raise ValueError("invalid audio path") from exc
            raise
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise OSError("audio file is not regular")
        finally:
            os.close(fd)
        os.unlink(parts[1], dir_fd=audio_fd)
        os.fsync(audio_fd)
        return True
    finally:
        if audio_fd is not None:
            os.close(audio_fd)
        os.close(root_fd)
