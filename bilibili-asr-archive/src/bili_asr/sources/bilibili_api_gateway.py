"""Typed gateway adapter over the pinned ``bilibili-api-python`` package.

This is the ONLY application module allowed to import ``bilibili_api`` (plan
Global Constraints and the gateway spec's dependency contract).  Every method
converts one upstream response into validated application DTOs and never
retains, logs, or returns the response dictionary, credentials, or raw
exception text.  Upstream failures map onto the bounded exception taxonomy in
``bili_asr.sources.models``; only the scalar ``code`` may leave the process.

A signed subtitle URL exists for the duration of one call only: it is resolved
here — normalized to ``https:`` when upstream answers it protocol-relative —
handed to the package transport, and never stored on a DTO, a message, or a
record.  The subtitle-body fetch carries an explicitly empty credential, so the
API credential never reaches the CDN host.
"""

from __future__ import annotations

import importlib.metadata
import math
import os
import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from bilibili_api import Credential, request_settings, user
from bilibili_api.exceptions import (
    ApiException,
    NetworkException,
    ResponseCodeException,
    ResponseException,
    WbiRetryTimesExceedException,
)
from bilibili_api.utils.network import Api
from bilibili_api.video import API as VIDEO_API, Video

from bili_asr.config import resolve_proxy
from bili_asr.sources.models import (
    GatewayNotFound,
    GatewayRateLimited,
    GatewayResponseError,
    GatewayShapeError,
    GatewayTransportError,
    SubtitleSegment,
    SubtitleTrack,
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

# The subtitle calls add the login signal to the shipped not-found set: ``-101``
# means the credential in effect saw nothing for this part, which the caller
# records as ``no-subtitle``.  The metadata path keeps the shipped set, where
# ``-101`` stays a generic response error.
_SUBTITLE_NOT_FOUND_API_CODES = _NOT_FOUND_API_CODES | {-101}

# Same shape check the package itself applies in Video.set_bvid.
_BVID_PATTERN = re.compile(r"^BV[a-zA-Z0-9]{10}$")

# The one scheme a signed subtitle-document URL is put on the wire under, and
# the plain-``http`` form upstream may answer with instead.  Upstream answers
# the URL sometimes protocol-relative and sometimes absolute (spec section
# 1.3); the document's own request carries no credential by design, but the
# signed URL is itself the capability token for the document, so it is
# normalized to ``https:`` rather than forwarded as delivered.
_HTTPS_SCHEME = "https://"
_PLAIN_HTTP_SCHEME = "http://"

# The package's own endpoint description for the user-video page call
# (``bilibili_api.user.API["info"]["video"]``).  ``url``/``method``/
# ``verify``/``wbi`` are read from it so this adapter cannot drift from the
# pinned package; ``dm`` is deliberately overridden per call (see
# ``BilibiliApiGateway._fetch_user_video_page``).
_USER_VIDEO_PAGE_ENDPOINT = user.API["info"]["video"]

# The package's own endpoint description for the player call
# (``bilibili_api.video.API["info"]["get_player_info"]``), whose unwrapped
# payload carries the part's subtitle inventory.  ``url``/``method``/``wbi``
# are read from it for the same reason; ``dm`` and ``verify`` are deliberately
# overridden per call (see ``BilibiliApiGateway._fetch_subtitle_inventory``).
# Only the endpoint description and ``Video`` are imported from the pin's
# ``video`` module: binding the whole module would make its other names
# (``Episode``, ``VideoOnlineMonitor``, ``get_api``, ``get_cid_info``,
# ``get_client``) source-reachable here without the import boundary noticing.
_PLAYER_INFO_ENDPOINT = VIDEO_API["info"]["get_player_info"]


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


def _extract_subtitle_entries(response: object) -> list:
    """Extract the player payload's ``subtitle.subtitles`` inventory array.

    A payload that carries no subtitle container, and a container that carries
    no ``subtitles`` list at all, are an empty inventory — the honest reading of
    a probe whose credential saw nothing, and a legitimate result rather than a
    failure.  A present container of another shape cannot be read as an
    inventory at all and is a bounded shape error.
    """

    if not isinstance(response, Mapping):
        raise GatewayShapeError(detail="player response is not a mapping")
    subtitle = response.get("subtitle")
    if subtitle is None:
        return []
    if not isinstance(subtitle, Mapping):
        raise GatewayShapeError(detail="player subtitle is not a mapping")
    entries = subtitle.get("subtitles")
    if entries is None:
        return []
    if not isinstance(entries, list):
        raise GatewayShapeError(detail="player subtitles is not an array")
    return entries


def _normalize_subtitle_tracks(entries: object) -> tuple[SubtitleTrack, ...]:
    """Convert the inventory array into validated track DTOs."""

    if not isinstance(entries, list):
        raise GatewayShapeError(detail="subtitle inventory is not an array")
    return tuple(_normalize_subtitle_track(entry) for entry in entries)


def _normalize_subtitle_track(entry: object) -> SubtitleTrack:
    """Convert one inventory entry into a validated, trimmed track DTO.

    ``lan``/``lan_doc`` are trimmed here so the caller can print them as-is,
    and the entry's own AI marker decides ``is_ai``.  The signed
    ``subtitle_url`` the entry also carries is deliberately not read: it never
    crosses the gateway boundary.
    """

    if not isinstance(entry, Mapping):
        raise GatewayShapeError(detail="subtitle track is not a mapping")
    language = entry.get("lan")
    if not isinstance(language, str) or not language.strip():
        raise GatewayShapeError(detail="subtitle track has no language")
    label = entry.get("lan_doc")
    if not isinstance(label, str) or not label.strip():
        raise GatewayShapeError(detail="subtitle track has no label")
    try:
        return SubtitleTrack(
            language=language.strip(),
            label=label.strip(),
            is_ai=_read_track_is_ai(entry),
            track_id=_read_optional_track_id(entry.get("id")),
        )
    except (TypeError, ValueError) as exc:
        raise GatewayShapeError(detail="subtitle track is not normalizable") from exc


def _read_optional_track_id(value: object) -> str | None:
    """Read an entry's ``id`` as the track-identity string, when present.

    Absent stays absent; a present value must be the upstream integer id, which
    is rendered as the string the DTO carries.
    """

    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise GatewayShapeError(detail="subtitle track has no valid id")
    return str(value)


def _read_track_is_ai(entry: Mapping) -> bool:
    """Derive ``is_ai`` from the entry's own upstream AI markers.

    ``ai_status`` is ``0`` for a track that never touched machine processing and
    positive once it did; ``type`` is ``1`` for a machine-generated caption.  A
    track carrying neither marker is reported as CC — the conservative reading
    the product semantics lock — and the ``lan`` prefix is deliberately not
    consulted, because the marker is the locked signal.
    """

    ai_status = _read_ai_marker(entry, "ai_status")
    caption_type = _read_ai_marker(entry, "type")
    return (ai_status is not None and ai_status > 0) or caption_type == 1


def _read_ai_marker(entry: Mapping, field: str) -> int | None:
    """Read one optional non-negative integer AI marker from an entry."""

    value = entry.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise GatewayShapeError(
            detail=f"subtitle track has an invalid {field} marker"
        )
    return value


def _resolve_subtitle_document_url(track: SubtitleTrack, entries: list) -> str:
    """Resolve one requested track's signed document URL from a fresh listing.

    A track is matched on ``language`` + ``is_ai``.  Several matches are broken
    by the requested ``track_id`` when the request carries one; otherwise the
    listing is ambiguous and the call fails as a bounded shape error.  No match
    at all means the track is not visible any more (``not_found``).  The
    resolved URL is returned for the duration of one call only and never
    reaches a DTO or an error message.
    """

    listed = [(_normalize_subtitle_track(entry), entry) for entry in entries]
    candidates = [
        (candidate, entry)
        for candidate, entry in listed
        if candidate.language == track.language and candidate.is_ai == track.is_ai
    ]
    if not candidates:
        raise GatewayNotFound(detail="fetch_subtitle_segments")
    if len(candidates) > 1 and track.track_id is not None:
        identified = [
            (candidate, entry)
            for candidate, entry in candidates
            if candidate.track_id == track.track_id
        ]
        if len(identified) == 1:
            candidates = identified
    if len(candidates) > 1:
        raise GatewayShapeError(detail="subtitle track match is ambiguous")
    return _read_subtitle_document_url(candidates[0][1])


def _read_subtitle_document_url(entry: Mapping) -> str:
    """Read one entry's signed document URL, normalized to ``https:``.

    Upstream answers the URL sometimes absolutely and sometimes
    protocol-relative, and an absolute answer is not guaranteed to be TLS, so
    the scheme is decided here rather than taken as delivered: a
    protocol-relative value and a plain ``http:`` value are both rewritten to
    ``https:`` — the signed URL *is* the document's capability token, so it
    never rides a cleartext request — while a value that is neither of those
    nor already ``https:`` cannot be read as this document's URL at all and is
    a bounded shape error.  Every value that leaves this function is therefore
    an absolute ``https:`` URL; it is handed to the package transport for the
    duration of one call and stays process-local.
    """

    url = entry.get("subtitle_url")
    if not isinstance(url, str) or not url.strip():
        raise GatewayShapeError(detail="subtitle track has no document URL")
    normalized = url.strip()
    if normalized.startswith("//"):
        return f"https:{normalized}"
    if normalized.startswith(_PLAIN_HTTP_SCHEME):
        return f"{_HTTPS_SCHEME}{normalized[len(_PLAIN_HTTP_SCHEME):]}"
    if normalized.startswith(_HTTPS_SCHEME):
        return normalized
    raise GatewayShapeError(detail="subtitle track has an unreadable document URL")


def _normalize_subtitle_document(document: object) -> tuple[SubtitleSegment, ...]:
    """Convert one subtitle document into the caption rows that survive.

    A document that cannot be read as a subtitle document at all raises a
    bounded shape error; a row that reads as a segment but carries nothing
    usable is dropped, so every other row of the document stays usable.
    """

    if not isinstance(document, Mapping):
        raise GatewayShapeError(detail="subtitle document is not a mapping")
    body = document.get("body")
    if not isinstance(body, list):
        raise GatewayShapeError(detail="subtitle document has no body array")
    return tuple(
        segment
        for segment in (_normalize_subtitle_segment(entry) for entry in body)
        if segment is not None
    )


def _normalize_subtitle_segment(entry: object) -> SubtitleSegment | None:
    """Convert one caption row, or drop it when it carries nothing usable.

    The conversion is the metadata path's ``floor(seconds * 1000)``, and the
    drop rules are evaluated on the converted milliseconds: a row survives
    exactly when ``end_ms > start_ms >= 0`` with text non-empty after
    stripping.  ``None`` marks a dropped row — a per-row tolerance, never a
    document-level failure.
    """

    if not isinstance(entry, Mapping):
        raise GatewayShapeError(detail="subtitle entry is not a mapping")
    start_ms = _read_caption_milliseconds(entry, "from")
    end_ms = _read_caption_milliseconds(entry, "to")
    content = entry.get("content")
    if not isinstance(content, str):
        raise GatewayShapeError(detail="subtitle entry has no content")
    text = content.strip()
    if start_ms < 0 or end_ms <= start_ms or not text:
        return None
    return SubtitleSegment(start_ms=start_ms, end_ms=end_ms, text=text)


def _read_caption_milliseconds(entry: Mapping, field: str) -> int:
    """Read one caption timestamp as milliseconds, using ``floor``.

    A missing, non-numeric, boolean, or non-finite value cannot be read as a
    segment at all, and neither can a finite value whose millisecond product
    leaves the float range: both stay bounded shape errors instead of escaping
    as ``ValueError``/``OverflowError`` out of ``math.floor``.
    """

    seconds = entry.get(field)
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        raise GatewayShapeError(detail=f"subtitle entry has no numeric {field}")
    milliseconds = seconds * 1000
    if isinstance(milliseconds, float) and not math.isfinite(milliseconds):
        raise GatewayShapeError(detail=f"subtitle entry has an unreadable {field}")
    return math.floor(milliseconds)


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

    def __init__(self, sessdata: str | None = None, proxy: str | None = None) -> None:
        """Build the package credential and apply one resolved proxy.

        The optional SESSDATA value is passed to the package ``Credential``
        object only.  It is never written to DTOs, logs, exception messages,
        or persistent records.

        ``proxy`` is an explicit programmatic override; when it is blank or
        omitted the locked chain in :mod:`bili_asr.config` decides
        (``BILI_HTTP_PROXY`` first, then the conventional host variables).
        A resolved proxy is applied here, once, through the package's
        request settings: that is the value the pinned ``CurlCFFIClient``
        reads when it builds its session, and its own default
        (``proxies={"all": ""}``) would otherwise defeat ``trust_env`` and
        ignore environment proxies.  ``Credential(proxy=...)`` is
        deliberately not used — it swaps that same global setting around
        every call instead of configuring it.  When nothing resolves, the
        library default is left untouched.  The resolved value is
        configuration, not a credential, and still never appears in DTOs,
        logs, exception messages, or persistent records.
        """

        self._credential = Credential(sessdata=sessdata) if sessdata else Credential()
        self.resolved_proxy = resolve_proxy(proxy, os.environ)
        if self.resolved_proxy is not None:
            request_settings.set_proxy(self.resolved_proxy)
        self._w_webid_by_mid: dict[int, str] = {}

    async def get_user_video_page(
        self, mid: int, page_number: int, page_size: int = 30
    ) -> UserVideoPage:
        """Fetch and normalize exactly one bounded user-video page.

        The default is the upstream-accepted page size declared by the
        :class:`~bili_asr.sources.models.BilibiliGateway` protocol; an
        explicit ``page_size`` still overrides it.
        """

        _require_positive_argument(mid, "mid")
        _require_positive_argument(page_number, "page_number")
        _require_positive_argument(page_size, "page_size")
        response = await self._await_upstream(
            "get_user_video_page",
            lambda: self._fetch_user_video_page(mid, page_number, page_size),
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
            lambda: Video(
                bvid=summary.bvid, credential=self._credential
            ).get_info(),
        )
        return _complete_summary_from_detail(summary, detail)

    async def get_subtitle_tracks(
        self, bvid: str, cid: int
    ) -> tuple[SubtitleTrack, ...]:
        """List the subtitle inventory one part exposes right now.

        One WBI-signed player call in the locked shape (section 1.2 of the
        gateway spec) and one normalized track per inventory entry, in upstream
        order.  An inventory the credential in effect could not see is an empty
        tuple — never a ``not_found`` failure and never a placeholder track.
        """

        if not isinstance(bvid, str) or _BVID_PATTERN.fullmatch(bvid) is None:
            raise ValueError("bvid must be a BV-prefixed 10-character id")
        _require_positive_argument(cid, "cid")
        entries = await self._list_subtitle_entries(
            bvid, cid, operation="get_subtitle_tracks"
        )
        return _normalize_subtitle_tracks(entries)

    async def fetch_subtitle_segments(
        self, track: SubtitleTrack, bvid: str, cid: int
    ) -> tuple[SubtitleSegment, ...]:
        """Fetch and normalize one requested track's caption document.

        The signed URL never crosses the boundary, so the requested track is
        resolved through a fresh listing of the part.  A body fetch that fails
        in the expiry/transport class gets exactly one more listing + fetch
        pair; rate control and every other classified failure propagate as they
        are.  Nothing usable — an empty document included — is
        ``GatewayNotFound``, and the return is never an empty tuple.
        """

        if not isinstance(track, SubtitleTrack):
            raise TypeError("track must be a SubtitleTrack")
        if not isinstance(bvid, str) or _BVID_PATTERN.fullmatch(bvid) is None:
            raise ValueError("bvid must be a BV-prefixed 10-character id")
        _require_positive_argument(cid, "cid")

        entries = await self._list_subtitle_entries(
            bvid, cid, operation="fetch_subtitle_segments"
        )
        try:
            document = await self._fetch_subtitle_document(
                _resolve_subtitle_document_url(track, entries)
            )
            segments = _normalize_subtitle_document(document)
        except GatewayTransportError:
            # A signature that no longer works is the one failure class worth a
            # second attempt: re-list once for a fresh URL and fetch once more.
            # There is no third attempt and no loop.
            entries = await self._list_subtitle_entries(
                bvid, cid, operation="fetch_subtitle_segments"
            )
            document = await self._fetch_subtitle_document(
                _resolve_subtitle_document_url(track, entries)
            )
            segments = _normalize_subtitle_document(document)
        if not segments:
            raise GatewayNotFound(detail="fetch_subtitle_segments")
        return segments

    def get_package_version(self) -> str:
        """Return the pinned package version for run metadata."""

        try:
            return importlib.metadata.version(PACKAGE_DISTRIBUTION_NAME)
        except importlib.metadata.PackageNotFoundError:
            return PINNED_PACKAGE_VERSION

    async def _fetch_user_video_page(
        self, mid: int, page_number: int, page_size: int
    ) -> Any:
        """Issue one WBI-signed page request in the shape upstream accepts.

        The request is built from the package's own endpoint description and
        signed by the package's ``Api``.  Two fields are this adapter's:
        ``dm`` is disabled, because the device-fingerprint parameters it would
        add cannot be satisfied here and the endpoint answers HTTP 412 with
        them; and ``w_webid`` is always sent as a present string, because the
        endpoint answers HTTP 412 when the parameter is missing.  Every other
        parameter name and value stays exactly the set the package's own page
        call sends.
        """

        w_webid = await self._resolve_w_webid(mid)
        return await (
            Api(
                url=_USER_VIDEO_PAGE_ENDPOINT["url"],
                method=_USER_VIDEO_PAGE_ENDPOINT["method"],
                verify=_USER_VIDEO_PAGE_ENDPOINT["verify"],
                wbi=_USER_VIDEO_PAGE_ENDPOINT["wbi"],
                dm=False,
                credential=self._credential,
            )
            .update_params(
                mid=mid,
                ps=page_size,
                tid=0,
                pn=page_number,
                keyword="",
                order=user.VideoOrder.PUBDATE.value,
                order_avoided=True,
                platform="web",
                w_webid=w_webid,
            )
            .result
        )

    async def _fetch_subtitle_inventory(self, bvid: str, cid: int) -> Any:
        """Issue one WBI-signed player request in the locked call shape.

        ``url``/``method``/``wbi`` are read from the package's own endpoint
        description, and the parameters are that description's declared set
        with ``bvid`` substituted for the declared ``aid`` alternative, so one
        request per part is paid and no aid-resolution call is added.  Two
        fields are this adapter's: ``verify`` is turned off, because the pin's
        ``verify=True`` performs no upstream check at all — it only raises
        locally when no SESSDATA is configured, which would turn an honest
        anonymous probe into an exception — and ``dm`` is turned off, because
        the device-fingerprint parameters it would add cannot be supplied
        truthfully and the sibling WBI endpoint in the same risk-control family
        answered HTTP 412 with them.  Neither ``need_login_subtitle`` nor
        ``w_webid`` is sent: the installed pin declares neither for this
        endpoint, and the package's own player call sends neither.
        """

        return await (
            Api(
                url=_PLAYER_INFO_ENDPOINT["url"],
                method=_PLAYER_INFO_ENDPOINT["method"],
                verify=False,
                wbi=_PLAYER_INFO_ENDPOINT["wbi"],
                dm=False,
                credential=self._credential,
            )
            .update_params(
                bvid=bvid,
                cid=cid,
                isGaiaAvoided=False,
                web_location=1315873,
            )
            .result
        )

    async def _list_subtitle_entries(
        self, bvid: str, cid: int, *, operation: str
    ) -> list:
        """List one part's subtitle inventory entries through the taxonomy.

        ``operation`` is the public method this listing serves, so a mapped
        failure names the boundary the caller invoked.  The subtitle calls pass
        the extended not-found set, where ``-101`` means "nothing visible under
        this credential" rather than a generic response error.
        """

        response = await self._await_upstream(
            operation,
            lambda: self._fetch_subtitle_inventory(bvid, cid),
            not_found_api_codes=_SUBTITLE_NOT_FOUND_API_CODES,
        )
        return _extract_subtitle_entries(response)

    async def _fetch_subtitle_document(self, url: str) -> Any:
        """Fetch one signed subtitle document through the package transport.

        The call is built with an explicitly empty ``Credential()``, so the API
        credential never reaches the CDN host, and it is issued as
        ``request(raw=True)``: a subtitle document carries no ``code``/``data``
        envelope for the pin's default unwrapping to strip.  The URL is a
        parameter of this call only and is never stored anywhere.
        """

        return await self._await_upstream(
            "fetch_subtitle_segments",
            lambda: Api(
                url=url,
                method="GET",
                wbi=False,
                dm=False,
                verify=False,
                credential=Credential(),
            ).request(raw=True),
        )

    async def _resolve_w_webid(self, mid: int) -> str:
        """Resolve the page request's ``w_webid`` parameter for one user.

        The package's ``User.get_access_id`` scrapes the user's dynamic page,
        which no longer server-renders ``access_id``: the route costs one
        extra page fetch and currently yields nothing.  The token is a request
        parameter rather than a credential, and the endpoint requires it to be
        present, so an unavailable token degrades to the empty string instead
        of failing the page call.  Each user's outcome is remembered for this
        adapter's lifetime, so at most one scrape attempt happens per user no
        matter how many pages are collected.
        """

        if mid not in self._w_webid_by_mid:
            try:
                access_id: object = await user.User(
                    uid=mid, credential=self._credential
                ).get_access_id()
            except Exception:
                # Best effort only: this optional token route must never fail
                # the metadata call it decorates.
                access_id = None
            self._w_webid_by_mid[mid] = access_id if isinstance(access_id, str) else ""
        return self._w_webid_by_mid[mid]

    async def _await_upstream(
        self,
        operation: str,
        call: Callable[[], Awaitable[Any]],
        *,
        not_found_api_codes: frozenset[int] = _NOT_FOUND_API_CODES,
    ) -> Any:
        """Await one upstream call and map its failures onto the taxonomy.

        The mapped exception message carries the bounded code and the
        operation name only; upstream text, URLs, and payload content stay
        process-local.  ``not_found_api_codes`` is the not-found set of the
        boundary being served: the metadata path keeps the shipped one, where
        ``-101`` is a response error, while the subtitle calls extend it so the
        login signal reads as "not visible".
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
            if exc.code in not_found_api_codes:
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
