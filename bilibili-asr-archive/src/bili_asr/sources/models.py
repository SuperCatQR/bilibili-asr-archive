"""Validated DTOs and the typed gateway protocol for Bilibili metadata.

These types are application-owned: third-party response dictionaries never
leak past the gateway adapter.  The module imports nothing from
``bilibili_api``; the adapter in ``bilibili_api_gateway.py`` is the only
module allowed to import that package.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Protocol

from bili_asr.storage.models import validate_error_code


def _integer(value: object, field: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"{field} must be at least {minimum}")
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    if not value.strip():
        raise ValueError(f"{field} must not be empty")
    return value


@dataclass(frozen=True, slots=True)
class VideoSummary:
    """One video summary from a user's video page.

    ``aid`` stays nullable: the list response may omit it, and only a
    deliberate detail call may fill the gap.
    """

    bvid: str
    aid: int | None
    title: str
    pubdate: int
    mid: int

    def __post_init__(self) -> None:
        _text(self.bvid, "bvid")
        if self.aid is not None:
            _integer(self.aid, "aid", minimum=1)
        _text(self.title, "title")
        _integer(self.pubdate, "pubdate", minimum=0)
        _integer(self.mid, "mid", minimum=1)


@dataclass(frozen=True, slots=True)
class VideoPart:
    """One part of one video, normalized to a zero-based index and ms."""

    bvid: str
    page_index: int
    cid: int
    title: str
    duration_ms: int

    def __post_init__(self) -> None:
        _text(self.bvid, "bvid")
        _integer(self.page_index, "page_index", minimum=0)
        _integer(self.cid, "cid", minimum=1)
        _text(self.title, "title")
        _integer(self.duration_ms, "duration_ms", minimum=1)


@dataclass(frozen=True, slots=True)
class UserVideoPage:
    """One bounded page of one user's video summaries."""

    mid: int
    page_number: int
    videos: tuple[VideoSummary, ...]
    observed_total: int | None

    def __post_init__(self) -> None:
        _integer(self.mid, "mid", minimum=1)
        _integer(self.page_number, "page_number", minimum=1)
        if not isinstance(self.videos, tuple):
            raise TypeError("videos must be a tuple of VideoSummary")
        for video in self.videos:
            if not isinstance(video, VideoSummary):
                raise TypeError("videos must be a tuple of VideoSummary")
        if self.observed_total is not None:
            _integer(self.observed_total, "observed_total", minimum=0)


class BilibiliGateway(Protocol):
    """Application-owned gateway protocol for the pinned package adapter."""

    async def get_user_video_page(
        self, mid: int, page_number: int, page_size: int = 100
    ) -> UserVideoPage: ...

    async def get_video_parts(self, bvid: str) -> tuple[VideoPart, ...]: ...

    async def get_completed_video_summary(
        self, summary: VideoSummary
    ) -> VideoSummary: ...

    def get_package_version(self) -> str: ...


class GatewayError(Exception):
    """Base of the bounded gateway failure taxonomy.

    Carries the bounded scalar ``code`` that may be persisted in page and run
    outcome rows.  Upstream exception text, URLs, cookies, and raw response
    content never appear in the message.
    """

    default_code: ClassVar[str] = "gateway_error"

    def __init__(self, code: str | None = None, detail: str = "") -> None:
        self.code = validate_error_code(
            code if code is not None else self.default_code
        )
        self.detail = detail
        message = f"{type(self).__name__}({self.code})"
        if detail:
            message = f"{message}: {detail}"
        super().__init__(message)


class GatewayRateLimited(GatewayError):
    """Upstream rate control stopped the page (risk-control signal)."""

    default_code = "rate_limited"


class GatewayNotFound(GatewayError):
    """The requested user or video does not exist (or is gone)."""

    default_code = "not_found"


class GatewayResponseError(GatewayError):
    """The upstream API answered with an error outside shape validation."""

    default_code = "response_error"


class GatewayTransportError(GatewayError):
    """The request never produced a usable response (network/transport)."""

    default_code = "transport_error"


class GatewayShapeError(GatewayError):
    """The upstream response could not be normalized into the DTO contract."""

    default_code = "shape_error"


__all__ = [
    "BilibiliGateway",
    "GatewayError",
    "GatewayNotFound",
    "GatewayRateLimited",
    "GatewayResponseError",
    "GatewayShapeError",
    "GatewayTransportError",
    "UserVideoPage",
    "VideoPart",
    "VideoSummary",
]
