"""Models implementation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


@dataclass(frozen=True)
class SearchQuery:
    """Structured search query with manifest filters and pagination bounds."""

    query: str = ""
    status: str | Sequence[str] | set[str] | None = None
    source: str | Sequence[str] | set[str] | None = None
    language: str | Sequence[str] | set[str] | None = None
    scope: str | None = None
    work_id: str | Sequence[str] | set[str] | None = None
    title: str | None = None
    min_duration_s: float | int | None = None
    max_duration_s: float | int | None = None
    limit: int | None = None
    offset: int = 0
    auto_build: bool = True
    rebuild: bool = False


@dataclass
class SearchResult:
    """A single matched transcript search hit."""

    work_id: str
    title: str
    status: str
    score: float
    path: str
    duration_s: float | int = 0
    transcript_snippet: str = ""
    archive_paths: dict[str, str] = field(default_factory=dict)
    source: str = ""
    language: str = ""
    pubdate: int | None = None
    bvid: str = ""
    page_index: int | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a sanitized dictionary representation of the search hit."""
        bvid_val = self.bvid
        if not bvid_val and ":" in self.work_id:
            bvid_val = self.work_id.split(":")[0]
        elif not bvid_val:
            bvid_val = self.work_id

        return {
            "work_id": self.work_id,
            "bvid": bvid_val,
            "page_index": self.page_index,
            "title": self.title,
            "status": self.status,
            "score": self.score,
            "path": self.path,
            "duration_s": self.duration_s,
            "source": self.source,
            "language": self.language,
            "pubdate": self.pubdate,
            "transcript_snippet": self.transcript_snippet,
            "archive_paths": dict(self.archive_paths),
        }


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
