"""Shared confinement policy for persisted archive audio paths."""

from __future__ import annotations

import os
from pathlib import Path

AUDIO_EXTENSIONS = frozenset({".m4a", ".flac"})


def confined_audio_path(
    archive_root: str | os.PathLike[str],
    declared_path: str | os.PathLike[str] | None,
    *,
    require_exists: bool,
) -> Path | None:
    """Resolve a declared audio path only within ``archive_root/audio``.

    Invalid, missing, symlinked, directory, and unsupported paths all produce
    the same ``None`` outcome so callers cannot leak path or exception detail.
    """
    if not isinstance(declared_path, (str, os.PathLike)):
        return None
    try:
        declared = Path(os.fspath(declared_path))
        if declared.is_absolute() or not declared.parts or ".." in declared.parts:
            return None
        root = Path(archive_root).resolve()
        audio_root = (root / "audio").resolve()
        candidate = root / declared
        if candidate.suffix.lower() not in AUDIO_EXTENSIONS:
            return None
        if candidate.is_symlink():
            return None
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(audio_root)
        if require_exists:
            if not candidate.exists() or candidate.is_symlink() or not candidate.is_file():
                return None
            if not resolved.is_file():
                return None
        return resolved
    except (OSError, RuntimeError, ValueError):
        return None
