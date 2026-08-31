"""Shared confinement policy for persisted archive audio paths."""

from __future__ import annotations

import os
import stat
from pathlib import Path

AUDIO_EXTENSIONS = frozenset({".m4a", ".flac"})


def confined_audio_path(
    archive_root: str | os.PathLike[str],
    declared_path: str | os.PathLike[str] | None,
    *,
    require_exists: bool,
) -> Path | None:
    """Return a confined audio path, using no-follow checks for existing files."""
    if not isinstance(declared_path, (str, os.PathLike)):
        return None
    try:
        root = Path(archive_root).resolve()
        audio = root / "audio"
        if audio.is_symlink() or not audio.is_dir():
            return None
        declared = Path(os.fspath(declared_path))
        if declared.is_absolute() or not declared.parts or any(p in ("", ".", "..") for p in declared.parts):
            return None
        candidate = root / declared
        if candidate.suffix.lower() not in AUDIO_EXTENSIONS:
            return None
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(audio.resolve())
        if candidate.exists() or candidate.is_symlink():
            info = candidate.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                return None
            if require_exists:
                fd = os.open(candidate, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                try:
                    if not stat.S_ISREG(os.fstat(fd).st_mode):
                        return None
                finally:
                    os.close(fd)
        elif require_exists:
            return None
        return candidate if not candidate.is_symlink() else None
    except (OSError, RuntimeError, ValueError):
        return None
