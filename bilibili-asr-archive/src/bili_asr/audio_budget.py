"""Audio-directory budget gate for bounded pilot campaigns.

Filesystem-only: measures current `audio/` usage and estimates a
candidate item's audio size so the CLI can skip downloads that would
breach the operator's peak-disk cap. Never opens sockets.
"""

from __future__ import annotations

import os
from typing import Any, Mapping

# 64 kbps DASH audio ceiling → 8 000 bytes/s.
BYTES_PER_SECOND_CEILING = 8_000
SKIP_REASON = "audio_budget"


def audio_dir_usage_bytes(archive_root: str | os.PathLike[str]) -> int:
    """Total size of files under `{archive_root}/audio` (0 if absent)."""
    audio_dir = os.path.join(os.fspath(archive_root), "audio")
    total = 0
    if not os.path.isdir(audio_dir):
        return 0
    for _dirpath, _dirnames, filenames in os.walk(audio_dir):
        for name in filenames:
            path = os.path.join(_dirpath, name)
            try:
                total += os.path.getsize(path)
            except OSError:
                continue
    return total


def estimate_audio_bytes(duration_s: Any) -> int:
    """Conservative on-disk audio size for one item (64 kbps ceiling)."""
    try:
        seconds = max(0, int(duration_s or 0))
    except (TypeError, ValueError):
        seconds = 0
    return seconds * BYTES_PER_SECOND_CEILING


def would_exceed_budget(
    archive_root: str | os.PathLike[str],
    entry: Mapping[str, Any],
    max_bytes: int,
) -> bool:
    """True if downloading this entry's audio would breach `max_bytes` peak."""
    if max_bytes <= 0:
        return False  # unlimited
    return audio_dir_usage_bytes(archive_root) + estimate_audio_bytes(
        entry.get("duration_s")
    ) > max_bytes


def max_duration_exceeded(entry: Mapping[str, Any], max_duration_min: Any) -> bool:
    """True if the row is longer than the campaign duration cap (0 = off)."""
    try:
        cap_seconds = max(0, int(max_duration_min or 0)) * 60
    except (TypeError, ValueError):
        return False
    if cap_seconds <= 0:
        return False
    try:
        duration = int(entry.get("duration_s") or 0)
    except (TypeError, ValueError):
        return False
    return duration > cap_seconds
