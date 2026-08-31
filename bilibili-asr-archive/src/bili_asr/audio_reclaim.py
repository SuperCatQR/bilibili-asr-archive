"""Post-archive audio reclaim: delete a part's audio once transcripts exist.

Filesystem-only module. Never opens sockets, never logs credentials.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from .path_policy import confined_audio_path

_AUDIO_EXTENSIONS = (".m4a", ".flac")


def _audio_dir(archive_root: str) -> str:
    return os.path.join(archive_root, "audio")


def _candidate_paths(archive_root: str, entry: Mapping[str, Any]) -> list[str]:
    """Absolute candidate audio paths for one entry, most likely first."""
    candidates: list[str] = []
    rel = entry.get("audio_path")
    if rel:
        path = str(rel)
        candidates.append(path if os.path.isabs(path) else os.path.join(archive_root, path))
    bvid = str(entry.get("bvid") or "")
    stem = None
    if bvid and entry.get("work_id") and not entry.get("unresolved"):
        # Reuse archive_stem's page-aware rules without duplicating them.
        from .archive import archive_stem

        stem = archive_stem(dict(entry))  # type: ignore[arg-type]
    elif bvid:
        stem = bvid
    if stem:
        for ext in _AUDIO_EXTENSIONS:
            candidates.append(os.path.join(_audio_dir(archive_root), f"{stem}{ext}"))
    return candidates


def reclaim_audio(archive_root: str | os.PathLike[str], entry: Mapping[str, Any]) -> bool:
    """Unlink the entry's audio file after the row reached `archived`.

    Returns True iff a file was removed; missing files are a success no-op
    (returns False). Refuses paths outside `{archive_root}/audio/` — raises
    ValueError instead of unlinking (path-traversal guard). OSError while
    unlinking propagates to the caller (per-item, non-fatal at call sites).
    """
    root = Path(archive_root).resolve()
    removed = False
    seen: set[Path] = set()
    explicit_value = str(entry.get("audio_path") or "")
    for candidate in _candidate_paths(str(root), entry):
        candidate_path = Path(candidate)
        is_explicit = bool(explicit_value) and (
            candidate_path == Path(explicit_value)
            or candidate_path == root / explicit_value
        )
        relative = explicit_value if is_explicit else os.path.relpath(candidate, root)
        confined = confined_audio_path(root, relative, require_exists=True)
        if confined is None:
            if is_explicit:
                raise ValueError("invalid audio path")
            continue
        if confined in seen:
            continue
        seen.add(confined)
        os.unlink(confined)
        removed = True
    return removed
