"""Audio-directory budget gate for bounded pilot campaigns.

Filesystem-only: measures current `audio/` usage and estimates a
candidate item's audio size so the CLI can skip downloads that would
breach the operator's peak-disk cap. Never opens sockets.
"""

from __future__ import annotations

import math
import os
from typing import Any, Mapping

# 64 kbps DASH audio ceiling → 8 000 bytes/s.
BYTES_PER_SECOND_CEILING = 8_000
SKIP_REASON = "audio_budget"
_BYTES_PER_GIB = 1024 ** 3


def audio_cap_bytes(max_audio_gb: float) -> int:
    """Convert ``--max-audio-gb`` to a byte cap.

    Non-positive values map to 0 (unlimited, matching ``would_exceed_budget``).
    Any positive GiB value maps to at least 1 byte so truncating ``int()``
    cannot silently disable the cap.
    """
    if max_audio_gb <= 0:
        return 0
    return max(1, math.ceil(max_audio_gb * _BYTES_PER_GIB))


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


def parse_duration_s(duration_s: Any) -> int | None:
    """Positive duration in seconds, or None if missing/zero/unparseable."""
    try:
        seconds = int(duration_s)
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    return seconds


def estimate_audio_bytes(duration_s: Any) -> int:
    """Conservative on-disk audio size for one item (64 kbps ceiling).

    Missing/zero/unparseable duration has no known seconds and returns 0
    here. Callers that enforce a peak cap must use ``would_exceed_budget``,
    which fail-closes on unknown duration.
    """
    seconds = parse_duration_s(duration_s)
    if seconds is None:
        return 0
    return seconds * BYTES_PER_SECOND_CEILING


def would_exceed_budget(
    archive_root: str | os.PathLike[str],
    entry: Mapping[str, Any],
    max_bytes: int,
    *,
    usage_bytes: int | None = None,
) -> bool:
    """True if downloading this entry's audio would breach `max_bytes` peak.

    Unknown duration fail-closes against a finite cap so a livestream with
    empty ``duration_s`` cannot look like a 0-byte short. Pass ``usage_bytes``
    to reuse a snapshot instead of walking ``audio/`` again.
    """
    if max_bytes <= 0:
        return False  # unlimited
    if parse_duration_s(entry.get("duration_s")) is None:
        return True
    usage = audio_dir_usage_bytes(archive_root) if usage_bytes is None else usage_bytes
    return usage + estimate_audio_bytes(entry.get("duration_s")) > max_bytes


def max_duration_exceeded(entry: Mapping[str, Any], max_duration_min: Any) -> bool:
    """True if the row is longer than the campaign duration cap (0 = off).

    Missing/zero/unparseable duration fail-closes when the cap is on so it
    cannot sneak through as a 0-second short.
    """
    try:
        cap_seconds = max(0, int(max_duration_min or 0)) * 60
    except (TypeError, ValueError):
        return False
    if cap_seconds <= 0:
        return False
    duration = parse_duration_s(entry.get("duration_s"))
    if duration is None:
        return True
    return duration > cap_seconds
