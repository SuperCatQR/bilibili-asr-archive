"""Publication date rendering shared by stored and published records."""

import time


def pubdate_utc(pubdate: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(pubdate))


def duration_s_from_ms(duration_ms: int | None) -> int:
    """Convert stored milliseconds to whole seconds with a one-second floor."""
    if duration_ms is None:
        return 1
    if isinstance(duration_ms, bool) or not isinstance(duration_ms, int):
        raise TypeError("duration_ms must be an integer or None")
    return max(1, duration_ms // 1000)
