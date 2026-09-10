"""Typed gateway adapter over the pinned ``bilibili-api-python`` package.

This is the ONLY application module allowed to import ``bilibili_api`` (plan
Global Constraints and the gateway spec's dependency contract).  Every method
converts one upstream response into validated application DTOs and never
retains, logs, or returns the response dictionary, credentials, or raw
exception text.  Upstream failures map onto the bounded exception taxonomy in
``bili_asr.sources.models``; only the scalar ``code`` may leave the process.
"""

from __future__ import annotations

import importlib.metadata
import math
import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from bilibili_api import Credential
from bilibili_api.exceptions import (
    ApiException,
    NetworkException,
    ResponseCodeException,
    ResponseException,
    WbiRetryTimesExceedException,
)
from bilibili_api.user import User
from bilibili_api.video import Video

from bili_asr.sources.models import (
    GatewayNotFound,
    GatewayRateLimited,
    GatewayResponseError,
    GatewayShapeError,
    GatewayTransportError,
    UserVideoPage,
    VideoPart,
    VideoSummary,
)

PACKAGE_DISTRIBUTION_NAME = "bilibili-api-python"
PINNED_PACKAGE_VERSION = "17.4.2"

# Upstream rate-control and gone signals, from the pinned API behavior
# (HTTP challenge statuses; API body codes documented by bilibili-API-collect).
_RATE_LIMITED_API_CODES = frozenset({-412, -352, -799})
_NOT_FOUND_API_CODES = frozenset({-404, -62002})
_RATE_LIMITED_HTTP_STATUSES = frozenset({412, 429})
_NOT_FOUND_HTTP_STATUSES = frozenset({404})

# Same shape check the package itself applies in Video.set_bvid.
_BVID_PATTERN = re.compile(r"^BV[a-zA-Z0-9]{10}$")


def _require_positive_argument(value: object, field: str) -> None:
    """Reject caller-argument violations before any upstream call."""

    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} must be a positive integer")


def _extract_page_items(response: object) -> list:
    """Extract the video item array from the arc/search inner data."""

    if not isinstance(response, Mapping):
        raise GatewayShapeError(detail="response is not a mapping")
    container = response.get("list")
    if isinstance(container, Mapping):
        items = container.get("vlist")
        if not isinstance(items, list):
            raise GatewayShapeError(detail="list.vlist is not an array")
        return items
    if isinstance(container, list):
        return container
    raise GatewayShapeError(detail="response has no video list")


def _read_observed_total(response: Mapping) -> int | None:
    """Read the total video count when the response carries it."""

    page = response.get("page")
    if page is None:
        return None
    if not isinstance(page, Mapping):
        raise GatewayShapeError(detail="page is not a mapping")
    count = page.get("count")
    if count is None:
        return None
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise GatewayShapeError(detail="page.count is not a valid total")
    return count


def _read_pubdate(item: Mapping) -> int:
    """Read the publish timestamp; ``created`` first, ``pubdate`` fallback."""

    for field in ("created", "pubdate"):
        value = item.get(field)
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise GatewayShapeError(detail=f"{field} is not a timestamp")
            return value
    raise GatewayShapeError(detail="no publish timestamp")


def _read_optional_aid(item: Mapping) -> int | None:
    """Read the aid when present; absent stays absent, never speculative."""

    value = item.get("aid")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise GatewayShapeError(detail="aid is not a positive av number")
    return value


def _normalize_video_summary_item(item: object, requested_mid: int) -> VideoSummary:
    """Convert one vlist item into a validated summary DTO."""

    if not isinstance(item, Mapping):
        raise GatewayShapeError(detail="video item is not a mapping")
    bvid = item.get("bvid")
    if not isinstance(bvid, str) or _BVID_PATTERN.fullmatch(bvid) is None:
        raise GatewayShapeError(detail="video item has no valid bvid")
    title = item.get("title")
    if not isinstance(title, str) or not title.strip():
        raise GatewayShapeError(detail="video item has no title")
    owner_mid = item.get("mid")
    if isinstance(owner_mid, bool) or not isinstance(owner_mid, int):
        raise GatewayShapeError(detail="video item has no owner mid")
    if owner_mid != requested_mid:
        raise GatewayShapeError(
            detail="video item owner mid does not match the requested user"
        )
    return VideoSummary(
        bvid=bvid,
        aid=_read_optional_aid(item),
        title=title.strip(),
        pubdate=_read_pubdate(item),
        mid=owner_mid,
    )


def _normalize_user_video_page(
    response: object, requested_mid: int, page_number: int
) -> UserVideoPage:
    """Convert the arc/search inner data into one validated page DTO."""

    items = _extract_page_items(response)
    summaries = tuple(
        _normalize_video_summary_item(item, requested_mid) for item in items
    )
    try:
        return UserVideoPage(
            mid=requested_mid,
            page_number=page_number,
            videos=summaries,
            observed_total=_read_observed_total(response),
        )
    except (TypeError, ValueError) as exc:
        raise GatewayShapeError(detail=f"page {page_number} is not normalizable") from exc


def _normalize_video_part_item(item: object, bvid: str) -> VideoPart:
    """Convert one pagelist element into a validated part DTO."""

    if not isinstance(item, Mapping):
        raise GatewayShapeError(detail="page item is not a mapping")
    api_page = item.get("page")
    if isinstance(api_page, bool) or not isinstance(api_page, int) or api_page < 1:
        raise GatewayShapeError(detail="page item has no one-based page")
    cid = item.get("cid")
    if isinstance(cid, bool) or not isinstance(cid, int) or cid < 1:
        raise GatewayShapeError(detail="page item has no positive cid")
    part_title = item.get("part")
    if not isinstance(part_title, str) or not part_title.strip():
        raise GatewayShapeError(detail="page item has no title")
    duration_seconds = item.get("duration")
    if (
        isinstance(duration_seconds, bool)
        or not isinstance(duration_seconds, (int, float))
        or duration_seconds < 0
    ):
        raise GatewayShapeError(detail="page item has no duration")
    try:
        return VideoPart(
            bvid=bvid,
            page_index=api_page - 1,
            cid=cid,
            title=part_title.strip(),
            duration_ms=math.floor(duration_seconds * 1000),
        )
    except (TypeError, ValueError) as exc:
        raise GatewayShapeError(detail="page item is not normalizable") from exc


def _normalize_video_parts(pages: object, bvid: str) -> tuple[VideoPart, ...]:
    """Convert the pagelist array into validated part DTOs."""

    if not isinstance(pages, list):
        raise GatewayShapeError(detail="response is not an array")
    return tuple(_normalize_video_part_item(item, bvid) for item in pages)


def _complete_summary_from_detail(
    summary: VideoSummary, detail: object
) -> VideoSummary:
    """Fill the summary's missing aid from its detail response.

    Only ``aid`` is taken from the detail; every other field stays exactly as
    the list response delivered it.  A detail owned by another user, or one
    naming another video, is a bounded shape error.
    """

    if not isinstance(detail, Mapping):
        raise GatewayShapeError(detail="detail is not a mapping")
    detail_aid = detail.get("aid")
    if isinstance(detail_aid, bool) or not isinstance(detail_aid, int) or detail_aid < 1:
        raise GatewayShapeError(detail="detail has no aid")
    detail_owner = detail.get("owner")
    detail_mid = None
    if isinstance(detail_owner, Mapping):
        candidate = detail_owner.get("mid")
        if isinstance(candidate, int) and not isinstance(candidate, bool):
            detail_mid = candidate
    if detail_mid is None or detail_mid != summary.mid:
        raise GatewayShapeError(
            detail="detail owner mid does not match the summary"
        )
    detail_bvid = detail.get("bvid")
    if not isinstance(detail_bvid, str) or detail_bvid != summary.bvid:
        raise GatewayShapeError(detail="detail bvid does not match the summary")
    return VideoSummary(
        bvid=summary.bvid,
        aid=detail_aid,
        title=summary.title,
        pubdate=summary.pubdate,
        mid=summary.mid,
    )


class BilibiliApiGateway:
    """Concrete :class:`BilibiliGateway` adapter over the pinned package."""

    def __init__(self, sessdata: str | None = None) -> None:
        """Build the package credential; a blank value means public access.

        The optional SESSDATA value is passed to the package ``Credential``
        object only.  It is never written to DTOs, logs, exception messages,
        or persistent records.
        """

        self._credential = Credential(sessdata=sessdata) if sessdata else Credential()

    async def get_user_video_page(
        self, mid: int, page_number: int, page_size: int = 100
    ) -> UserVideoPage:
        """Fetch and normalize exactly one bounded user-video page."""

        _require_positive_argument(mid, "mid")
        _require_positive_argument(page_number, "page_number")
        _require_positive_argument(page_size, "page_size")
        response = await self._await_upstream(
            "get_user_video_page",
            lambda: User(
                uid=mid, credential=self._credential
            ).get_videos(pn=page_number, ps=page_size),
        )
        return _normalize_user_video_page(response, requested_mid=mid, page_number=page_number)

    async def get_video_parts(self, bvid: str) -> tuple[VideoPart, ...]:
        """Fetch and normalize the part records of one video."""

        if not isinstance(bvid, str) or _BVID_PATTERN.fullmatch(bvid) is None:
            raise ValueError("bvid must be a BV-prefixed 10-character id")
        pages = await self._await_upstream(
            "get_video_parts",
            lambda: Video(bvid=bvid, credential=self._credential).get_pages(),
        )
        return _normalize_video_parts(pages, bvid)

    async def get_completed_video_summary(self, summary: VideoSummary) -> VideoSummary:
        """Fill a summary's missing aid through its detail response.

        A summary that already carries ``aid`` is returned unchanged, so no
        detail call is ever made speculatively.
        """

        if not isinstance(summary, VideoSummary):
            raise TypeError("summary must be a VideoSummary")
        if summary.aid is not None:
            return summary
        detail = await self._await_upstream(
            "get_completed_video_summary",
            lambda: Video(bvid=summary.bvid, credential=self._credential).get_info(),
        )
        return _complete_summary_from_detail(summary, detail)

    def get_package_version(self) -> str:
        """Return the pinned package version for run metadata."""

        try:
            return importlib.metadata.version(PACKAGE_DISTRIBUTION_NAME)
        except importlib.metadata.PackageNotFoundError:
            return PINNED_PACKAGE_VERSION

    async def _await_upstream(
        self, operation: str, call: Callable[[], Awaitable[Any]]
    ) -> Any:
        """Await one upstream call and map its failures onto the taxonomy.

        The mapped exception message carries the bounded code and the
        operation name only; upstream text, URLs, and payload content stay
        process-local.
        """

        try:
            return await call()
        except NetworkException as exc:
            if exc.status in _RATE_LIMITED_HTTP_STATUSES:
                raise GatewayRateLimited(detail=operation) from exc
            if exc.status in _NOT_FOUND_HTTP_STATUSES:
                raise GatewayNotFound(detail=operation) from exc
            raise GatewayTransportError(detail=operation) from exc
        except ResponseCodeException as exc:
            if exc.code in _RATE_LIMITED_API_CODES:
                raise GatewayRateLimited(detail=operation) from exc
            if exc.code in _NOT_FOUND_API_CODES:
                raise GatewayNotFound(detail=operation) from exc
            raise GatewayResponseError(detail=operation) from exc
        except WbiRetryTimesExceedException as exc:
            raise GatewayRateLimited(detail=operation) from exc
        except ResponseException as exc:
            raise GatewayResponseError(detail=operation) from exc
        except ApiException as exc:
            raise GatewayResponseError(detail=operation) from exc
        except Exception as exc:
            raise GatewayTransportError(detail=operation) from exc


__all__ = ["BilibiliApiGateway"]
