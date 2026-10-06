"""Publication date rendering shared by stored and published records."""

import time


def pubdate_utc(pubdate: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(pubdate))
