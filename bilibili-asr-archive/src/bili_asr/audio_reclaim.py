"""Post-archive audio reclaim: delete a part's audio once transcripts exist.

Filesystem-only module. Never opens sockets, never logs credentials.
"""

from __future__ import annotations

import os
from typing import Any, Mapping

from .path_policy import unlink_confined_audio

_AUDIO_EXTENSIONS = (".m4a", ".flac")


def _audio_dir(archive_root: str) -> str:
    return os.path.join(archive_root, "audio")


def _candidate_paths(archive_root: str, entry: Mapping[str, Any]) -> list[str]:
    """Relative audio candidates for one entry, most likely first."""
    candidates: list[str] = []
    rel = entry.get("audio_path")
    if rel:
        candidates.append(str(rel))
    bvid = str(entry.get("bvid") or "")
    stem = None
    if bvid and entry.get("work_id") and not entry.get("unresolved"):
        from .archive import archive_stem

        stem = archive_stem(dict(entry))  # type: ignore[arg-type]
    elif bvid:
        stem = bvid
    if stem:
        for ext in _AUDIO_EXTENSIONS:
            candidates.append(os.path.join("audio", f"{stem}{ext}"))
    return candidates


def reclaim_audio(archive_root: str | os.PathLike[str], entry: Mapping[str, Any]) -> bool:
    """Unlink confined audio entries after a row reached `archived`.
    
    Skipped when BILI_KEEP_AUDIO=1 to retain audio for future reprocessing.
    """
    # Check environment variable to preserve audio files
    if os.environ.get("BILI_KEEP_AUDIO") == "1":
        return False
    
    root = os.path.abspath(os.fspath(archive_root))
    removed = False
    seen: set[str] = set()
    explicit_value = str(entry.get("audio_path") or "")
    for relative in _candidate_paths(root, entry):
        if relative in seen:
            continue
        seen.add(relative)
        try:
            did_remove = unlink_confined_audio(root, relative)
        except ValueError:
            if relative == explicit_value:
                raise
            continue
        if did_remove:
            removed = True
    return removed
