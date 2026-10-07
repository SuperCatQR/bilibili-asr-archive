"""Models implementation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TranscriptSearchHit:
    """One matched time-bounded transcript block."""

    block_key: str
    bvid: str
    page_index: int
    start_ms: int
    end_ms: int
    pubdate: int
    text: str
    source: str
    rank: float
    snippet: str
    video_title: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "block_key": self.block_key,
            "bvid": self.bvid,
            "page_index": self.page_index,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "pubdate": self.pubdate,
            "text": self.text,
            "source": self.source,
            "rank": self.rank,
            "snippet": self.snippet,
            "video_title": self.video_title,
        }
