"""Typed gateway adapter over the pinned ``bilibili-api-python`` package.

This is the ONLY application module allowed to import ``bilibili_api`` (plan
Global Constraints and the gateway spec's dependency contract).  Every method
converts one upstream response into validated application DTOs. When explicit
source-observations/v1 storage is installed, metadata endpoint responses are
captured privately before normalization; transport credentials are excluded
with recorded JSON pointers. Public DTOs and diagnostics never return raw
responses, credentials, or exception text. Upstream failures map onto the bounded exception taxonomy in
``bili_asr.sources.models``; only the scalar ``code`` is persisted. Operator
diagnostics can additionally expose allowlisted operation names and numeric
HTTP/API codes, never raw exceptions or response content.

A signed subtitle URL exists for the duration of one call only: it is resolved
here — normalized to ``https:`` when upstream answers it protocol-relative —
handed to the package transport, and never stored on a DTO, a message, or a
record.  The subtitle-body fetch carries an explicitly empty credential, so the
API credential never reaches the CDN host.
"""

from __future__ import annotations

import asyncio
import dataclasses
import importlib.metadata
import math
import os
import random
import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from bilibili_api import Credential, request_settings
from bilibili_api.exceptions import (
    ApiException,
    NetworkException,
    ResponseCodeException,
    ResponseException,
    WbiRetryTimesExceedException,
)
from bilibili_api.user import API as USER_API
from bilibili_api.user import User, VideoOrder
from bilibili_api.utils.network import Api, lazy_settings, session_pool
from bilibili_api.video import API as VIDEO_API
from bilibili_api.video import Video

from bili_asr.bili_client import NAV_URL
from bili_asr.config import resolve_proxy
from bili_asr.request_budget import RequestScheduler
from bili_asr.source_observations import PlatformObservation
from bili_asr.sources.bilibili_metadata_codec import (
    _complete_summary_from_detail,
    _extract_page_items,
    _normalize_video_parts,
    _normalize_video_summary_item,
    _normalize_video_tags,
    _read_observed_total,
)
from bili_asr.sources.models import (
    GatewayAuthenticationError,
    GatewayDiagnostic,
    GatewayError,
    GatewayNotFound,
    GatewayRateLimited,
    GatewayResponseError,
    GatewayShapeError,
    GatewayTransportError,
    SubtitleBodyRead,
    SubtitleSegment,
    SubtitleTrack,
    TagRead,
    UserVideoPage,
    VideoMetadataRead,
    VideoPart,
    VideoSummary,
    VideoTag,
)
from bili_asr.sources.request_scope import sdk_settings_scope

PACKAGE_DISTRIBUTION_NAME = "bilibili-api-python"
PINNED_PACKAGE_VERSION = "17.4.2"

# Upstream rate-control and gone signals, from the pinned API behavior
# (HTTP challenge statuses; API body codes documented by bilibili-API-collect).
_RATE_LIMITED_API_CODES = frozenset({-412, -352, -799})
_NOT_FOUND_API_CODES = frozenset({-404, -62002})
_RATE_LIMITED_HTTP_STATUSES = frozenset({412, 429})
_NOT_FOUND_HTTP_STATUSES = frozenset({404})

# A login rejection is not evidence that a part has no subtitles.  Keep this
# separate from gone signals so failed authentication cannot admit audio work.
_AUTHENTICATION_API_CODES = frozenset({-101})

# Same shape check the package itself applies in Video.set_bvid.
_BVID_PATTERN = re.compile(r"^BV[a-zA-Z0-9]{10}$")

# Per-row metadata pacing, in the same range the legacy page-fetch path
# (``BiliClient.fetch_pages``) already sleeps between whole pages: the
# inter-page formula there is ``0.8 + jitter * 0.8`` with jitter in
# ``[0, 1)``, i.e. a uniform 0.8-1.6 s delay.  ``fetch-meta`` fires these
# getters once per video per page (~30 rows), so a full-corpus page
# otherwise issues ~90 back-to-back upstream calls — the exact pattern
# that trips risk control (``-412``) mid-run.  Execution stays strictly
# sequential (``sequential-no-daemon`` is by design); only the delay is
# added.
# Use a wider inter-operation delay for long creator-page enumerations.  The
# shorter legacy range is too aggressive once the upstream WAF has issued a
# 412 challenge; 3-5 seconds leaves more room between signed requests while
# keeping the collector sequential and resumable.
_METADATA_PACING_MIN_SECONDS = 3.0
_METADATA_PACING_JITTER_SPAN_SECONDS = 2.0

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
#
# Only the three names this adapter uses are imported from the pin's ``user``
# module — the endpoint description, ``User`` and ``VideoOrder``.  Binding the
# whole module instead (``from bilibili_api import user``) made every endpoint
# description in the package source-reachable here through ``user.get_api``
# without the import boundary noticing; that hole was residual R1 of
# ``20260911-subtitle-gateway``, and this narrowed import is its closure.  The
# ``video`` module below is narrowed for the same reason.
_USER_VIDEO_PAGE_ENDPOINT = USER_API["info"]["video"]

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

# The package's own endpoint description for the video-tag call
# (``bilibili_api.video.API["info"]["tags"]``).  It is the one documented
# metadata route that answers anonymously — the descriptor's ``verify`` is
# ``false`` and the live probe confirms it — so this call carries the
# credential the adapter already holds and requires none: no credential is
# ever *added* to turn it on.  Only ``url``/``method``/``verify`` are read from
# the description; ``params`` there is field documentation (``aid``/``bvid``),
# not a parameter mapping to forward verbatim, and the adapter sends ``bvid``
# alone because the tag set is a property of the video rather than of a part.
_TAG_ENDPOINT = VIDEO_API["info"]["tags"]


def _require_positive_argument(value: object, field: str) -> None:
    """Reject caller-argument violations before any upstream call."""

    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} must be a positive integer")
























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


def _read_subtitle_document(document: object) -> SubtitleBodyRead:
    """Preserve legal empty-body evidence without treating damaged timing as empty."""
    segments = _normalize_subtitle_document(document)
    body = document["body"]
    if segments:
        return SubtitleBodyRead(segments, len(body))
    for entry in body:
        start = _read_caption_milliseconds(entry, "from")
        end = _read_caption_milliseconds(entry, "to")
        if start < 0 or end <= start:
            raise GatewayShapeError(code="subtitle_timeline_invalid")
    return SubtitleBodyRead((), len(body), "empty_text" if body else "empty_body")


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




class BilibiliApiGateway:
    """Concrete :class:`BilibiliGateway` adapter over the pinned package."""

    def __init__(
        self,
        sessdata: str | None = None,
        proxy: str | None = None,
        *,
        _sleeper: Callable[[float], Awaitable[object]] | None = None,
        _jitter: Callable[[], float] | None = None,
        request_scheduler: RequestScheduler | None = None,
    ) -> None:
        """Build the package credential and retain request-scoped proxy config.

        The optional SESSDATA value is passed to the package ``Credential``
        object only.  It is never written to DTOs, logs, exception messages,
        or persistent records.

        ``proxy`` is an explicit programmatic override; when it is blank or
        omitted the locked chain in :mod:`bili_asr.config` decides
        (``BILI_HTTP_PROXY`` first, then the conventional host variables).
        Construction does not mutate the SDK's process-global settings.
        Each upstream request owns those settings under a loop-neutral,
        cross-thread lock and restores the previous value on every exit.
        The pinned client applies the setting when it creates or updates
        its event-loop session. The resolved value never appears in DTOs,
        logs, exception messages or persistent records.
        """

        self._credential = Credential(sessdata=sessdata) if sessdata else Credential()
        self.tag_error_code: str | None = None
        self._metadata_credential_checked = not bool(sessdata)
        self.resolved_proxy = resolve_proxy(proxy, os.environ)
        self._w_webid_by_mid: dict[int, str] = {}
        self._observation_sink = None
        self.request_scheduler = request_scheduler or RequestScheduler(sleeper=_sleeper or asyncio.sleep)
        # Pacing seams, mirroring the legacy page-fetch path's sleeper/jitter
        # injection: tests substitute non-blocking fakes so the pacing sleep
        # is asserted without slowing the suite.  The default sleeper is
        # ``asyncio.sleep`` — a plain awaitable — so awaiting it in the async
        # getters yields to the event loop instead of blocking it the way
        # ``time.sleep`` would.
        self._sleeper: Callable[[float], Awaitable[object]] = (
            _sleeper if _sleeper is not None else asyncio.sleep
        )
        self._jitter: Callable[[], float] = (
            _jitter if _jitter is not None else lambda: random.uniform(0.0, 1.0)
        )

    def set_observation_sink(self, sink) -> None:
        """Bind a private append-only capture sink; transport calls stay excluded."""
        self._observation_sink = sink

    async def _read_metadata(self, operation, call, *, scope, capture_operation, endpoint):
        try:
            payload = await self._await_upstream(operation, call)
        except GatewayError as error:
            if self._observation_sink is not None:
                self._observation_sink(PlatformObservation.capture(
                    platform="bilibili", operation=capture_operation, endpoint=endpoint, scope=scope,
                    extractor=PACKAGE_DISTRIBUTION_NAME, extractor_version=self.get_package_version(),
                    state="denied" if isinstance(error, GatewayAuthenticationError) else "failed",
                    error_code=error.code))
            raise
        observation = None
        if self._observation_sink is not None:
            observation = PlatformObservation.capture(
                platform="bilibili", operation=capture_operation, endpoint=endpoint, scope=scope,
                extractor=PACKAGE_DISTRIBUTION_NAME, extractor_version=self.get_package_version(), payload=payload)
            self._observation_sink(observation)
        return payload, observation

    async def _pace(self) -> None:
        """Sleep the per-row metadata delay before one upstream call.

        The single pacing primitive shared by the three per-row getters
        (``get_completed_video_summary`` / ``get_video_parts`` /
        ``get_video_tags``): a 30-video page normally needs 61 business
        operations when every summary already carries aid, with extra
        detail operations only for missing aid or verified collaboration.
        The delay matches the
        documented inter-page range used by ``fetch_pages`` and the run
        stays strictly sequential.  The sleep itself is awaited (the default
        sleeper is ``asyncio.sleep``), so the event loop is yielded rather
        than blocked.

        Pacing is unconditional by design: every caller pays the delay, which
        is what keeps a page-driven enumeration inside the risk-control
        budget.  A row-count gate existed here between 2026-10-02 and
        2026-10-04 (``set_pacing_floor``, removed by the ruling on
        ``I-000173``/``I-000142``) — it never had a production caller, so it
        only ever documented an opt-out the product did not offer.
        """

        await self._sleeper(
            _METADATA_PACING_MIN_SECONDS
            + max(0.0, self._jitter()) * _METADATA_PACING_JITTER_SPAN_SECONDS
        )

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
        if not self._metadata_credential_checked:
            # A configured cookie is not proof of login. The pin's WBI key
            # getter ignores nav's -101 and can still send a rejected cookie
            # to arc/search, which obscures authentication behind risk control.
            await self._validate_credentials("validate_metadata_credentials")
            self._metadata_credential_checked = True
        response, observation = await self._read_metadata(
            "get_user_video_page",
            lambda: self._fetch_user_video_page(mid, page_number, page_size),
            scope={"creatorId": str(mid), "pageNumber": page_number, "pageSize": page_size},
            capture_operation="creator-page", endpoint="user/info/video",
        )
        summaries: list[VideoSummary] = []
        verified: dict[str, VideoSummary] = {}
        from bili_asr.sources.bilibili_metadata_codec import (
            bind_completed,
            bind_summary,
        )
        items = _extract_page_items(response)
        prefix = "/list/vlist/" if isinstance(response.get("list"), Mapping) else "/list/"
        for index, item in enumerate(items):
            owner_mid = item.get("mid") if isinstance(item, Mapping) else None
            if (
                isinstance(owner_mid, int)
                and not isinstance(owner_mid, bool)
                and owner_mid > 0
                and owner_mid != mid
            ):
                # Collaboration posts appear on participants' upload pages.
                # Validate the actual owner first, then require independent
                # detail evidence of the requested user's participation.
                summary = _normalize_video_summary_item(item, owner_mid)
                summary = bind_summary(summary, observation, item, prefix + str(index))
                if summary.bvid not in verified:
                    await self._pace()
                    detail, detail_observation = await self._read_metadata(
                        "get_completed_video_summary",
                        lambda: Video(
                            bvid=summary.bvid, credential=self._credential
                        ).get_info(),
                        scope={"externalVideoId": summary.bvid}, capture_operation="details", endpoint="video/info/detail",
                    )
                    if not isinstance(detail, Mapping):
                        raise GatewayShapeError(
                            detail="video owner mid differs without verified participation"
                        )
                    completed = _complete_summary_from_detail(summary, detail)
                    completed = bind_completed(completed, detail_observation)
                    if summary.aid is not None and completed.aid != summary.aid:
                        raise GatewayShapeError(detail="collaboration detail aid mismatch")
                    staff = detail.get("staff")
                    collaborators = tuple(
                        member["mid"]
                        for member in staff
                        if isinstance(member, Mapping)
                        and isinstance(member.get("mid"), int)
                        and not isinstance(member["mid"], bool)
                        and member["mid"] > 0
                    ) if isinstance(staff, list) else ()
                    if mid not in collaborators:
                        raise GatewayShapeError(
                            detail="video owner mid differs without verified participation"
                        )
                    verified[summary.bvid] = dataclasses.replace(
                        completed, collaborator_mids=collaborators
                    )
                summaries.append(verified[summary.bvid])
            else:
                summaries.append(bind_summary(_normalize_video_summary_item(item, mid), observation, item, prefix + str(index)))
        try:
            return UserVideoPage(
                mid=mid, page_number=page_number, videos=tuple(summaries),
                observed_total=_read_observed_total(response),
            )
        except (TypeError, ValueError) as exc:
            raise GatewayShapeError(detail=f"page {page_number} is not normalizable") from exc

    async def get_video_parts(
        self, bvid: str, video_title_fallback: str = ""
    ) -> tuple[VideoPart, ...]:
        """Fetch and normalize the part records of one video."""

        if not isinstance(bvid, str) or _BVID_PATTERN.fullmatch(bvid) is None:
            raise ValueError("bvid must be a BV-prefixed 10-character id")
        await self._pace()
        pages, observation = await self._read_metadata(
            "get_video_parts",
            lambda: Video(bvid=bvid, credential=self._credential).get_pages(),
            scope={"externalVideoId": bvid}, capture_operation="parts", endpoint="video/info/pages",
        )
        from bili_asr.sources.bilibili_metadata_codec import bind_parts
        return bind_parts(_normalize_video_parts(pages, bvid, video_title_fallback), observation, bvid, video_title_fallback)

    async def get_completed_video_summary(self, summary: VideoSummary) -> VideoSummary:
        """Fill a summary's missing aid through its detail response.

        A summary that already carries ``aid`` is returned unchanged, so no
        detail call is ever made speculatively.
        """

        if not isinstance(summary, VideoSummary):
            raise TypeError("summary must be a VideoSummary")
        if summary.aid is not None:
            return summary
        await self._pace()
        detail, observation = await self._read_metadata(
            "get_completed_video_summary",
            lambda: Video(
                bvid=summary.bvid, credential=self._credential
            ).get_info(),
            scope={"externalVideoId": summary.bvid}, capture_operation="details", endpoint="video/info/detail",
        )
        from bili_asr.sources.bilibili_metadata_codec import bind_completed
        return bind_completed(_complete_summary_from_detail(summary, detail), observation)

    async def get_video_metadata(self, bvid: str) -> VideoMetadataRead:
        """Read a full source observation for explicit historical refresh.

        Parts in a verified view response can be reused. Missing pages do not
        imply no parts; the application falls back to the dedicated endpoint.
        """
        if not isinstance(bvid, str) or _BVID_PATTERN.fullmatch(bvid) is None:
            raise ValueError("bvid must be a BV-prefixed 10-character id")
        await self._pace()
        detail, observation = await self._read_metadata("get_completed_video_summary", lambda: Video(
            bvid=bvid, credential=self._credential).get_info(), scope={"externalVideoId": bvid},
            capture_operation="details", endpoint="video/info/detail")
        from bili_asr.sources.bilibili_metadata_codec import (
            bind_metadata,
            normalize_video_metadata,
        )
        return bind_metadata(normalize_video_metadata(detail, bvid), observation)

    async def get_video_tags(self, bvid: str) -> tuple[VideoTag, ...] | None:
        """Compatibility surface; acquisition uses the independent typed read."""
        read = await self.read_video_tags(bvid)
        self.tag_error_code = read.error_code
        return read.tags

    async def read_video_tags(self, bvid: str) -> TagRead:
        """List the tags one video carries right now.

        One unsigned, WBI-free call: the endpoint's description declares
        neither ``verify`` nor ``wbi``, and the live probe confirms it answers
        with the ``bvid`` alone — so no credential is *required* for it and
        none is added to turn it on.  The credential the adapter already holds
        is still passed through, because the request path is the same for
        every call and dropping it would be a second, silent change.

        **This call degrades rather than fails.** It is the one metadata call
        the plan treats as best-effort: *every* classified upstream failure —
        risk control, not-found, an unclassified response error, or a broken
        transport — is answered with ``None`` so the run continues, and
        the bounded code travels on the exception mapped by ``_await_upstream``
        and caught here.  Nothing is logged, printed, or persisted by this
        method; ``tag_error_code`` exposes only the bounded category to the
        caller and is reset on each request. Raw responses never escape.

        Catching the whole taxonomy is deliberate rather than loose.  The
        endpoint sits in the risk-control family, so a challenge can arrive as
        any of those classes — the sibling WBI endpoint in that family answers
        HTTP 412, and a WAF front can just as well answer an unclassified
        error.  Degrading on only two of them would leave the run failing on
        the same underlying event under a different code, which is exactly the
        hard dependency the plan forbids.

        A *malformed successful* response is the deliberate exception: that is
        a shape error, raised by the normalizer outside this guard, because an
        unreadable payload is a defect rather than an upstream mood.  Masking
        it as "no tags" would hide it behind the same empty tuple a
        legitimate empty inventory produces.

        **``None`` and ``()`` are different answers, and the difference is the
        whole point of the return type** (compass **D16**, 2026-09-27).
        ``None`` is "this call could not read the tags this time"; ``()`` is
        "read it, and this video carries none", which the normalizer returns
        for ``data: []``.  The write side acts on the distinction: the ingestor
        omits a ``None`` bvid from a page's tag sets, and ``record_page``
        treats an absent key as "no news" rather than as an observation to
        write, so a degraded re-run leaves the tags a previous run stored
        **untouched**.  Returning ``()`` here instead would make one degraded
        fetch clear a stored set, which is the erasure D16 rules out.
        """

        if not isinstance(bvid, str) or _BVID_PATTERN.fullmatch(bvid) is None:
            raise ValueError("bvid must be a BV-prefixed 10-character id")
        await self._pace()
        try:
            response, observation = await self._read_metadata(
                "get_video_tags",
                lambda: Api(
                    url=_TAG_ENDPOINT["url"],
                    method=_TAG_ENDPOINT["method"],
                    verify=_TAG_ENDPOINT["verify"],
                    wbi=False,
                    dm=False,
                    credential=self._credential,
                )
                .update_params(bvid=bvid)
                .result,
                scope={"externalVideoId": bvid}, capture_operation="tags", endpoint="video/info/tags",
            )
        except GatewayError as error:
            # Best-effort call, and *not* an observation: ``None`` tells the
            # caller the tags could not be read, which is what keeps
            # ``record_page`` from clearing rows a previous run stored
            # (compass D16).  ``()`` here would be a lie about what upstream
            # said. Only the bounded category is retained for caller-owned
            # observation evidence; the original exception is not re-raised.
            return TagRead(None, error.code)
        from bili_asr.metadata_acceptance import SourceFieldReceipt
        from bili_asr.sources.bilibili_metadata_codec import tags_value
        tags = _normalize_video_tags(response)
        receipt = None if observation is None else SourceFieldReceipt.create(field="tags", value=tags_value(tags),
            observation=observation, pointer="", normalizer="bilibili-tags/v1", context={"bvid": bvid})
        return TagRead(tags, source_receipt=receipt)

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

    async def validate_subtitle_credentials(self) -> None:
        """Require a current logged-in nav response before recording absence.

        Check every credentialed empty observation rather than caching a valid
        answer for a whole batch: a cookie can expire while that batch runs.
        The nav payload and its account details never leave this boundary.
        """

        await self._validate_credentials("validate_subtitle_credentials")

    async def _validate_credentials(self, operation: str) -> None:
        response = await self._await_upstream(
            operation,
            lambda: Api(
                url=NAV_URL, method="GET", verify=False, wbi=False, dm=False,
                credential=self._credential,
            ).result,
            authentication_api_codes=_AUTHENTICATION_API_CODES,
        )
        if not isinstance(response, Mapping) or not isinstance(response.get("isLogin"), bool):
            raise GatewayShapeError(detail=operation)
        if not response["isLogin"]:
            raise GatewayAuthenticationError(detail=operation)

    async def fetch_subtitle_segments(
        self, track: SubtitleTrack, bvid: str, cid: int
    ) -> tuple[SubtitleSegment, ...]:
        """Retain the strict nonempty API for existing callers."""
        document = await self._fetch_caption_document(track, bvid, cid)
        segments = _normalize_subtitle_document(document)
        if not segments:
            raise GatewayNotFound(detail="fetch_subtitle_segments")
        return segments

    async def read_subtitle_body(
        self, track: SubtitleTrack, bvid: str, cid: int
    ) -> SubtitleBodyRead:
        document = await self._fetch_caption_document(track, bvid, cid)
        return _read_subtitle_document(document)

    async def _fetch_caption_document(self, track: SubtitleTrack, bvid: str, cid: int) -> object:
        """Read one document; signed URL refresh remains bounded to one retry.

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
        return document

    def get_package_version(self) -> str:
        """Return the pinned package version for run metadata."""

        try:
            return importlib.metadata.version(PACKAGE_DISTRIBUTION_NAME)
        except importlib.metadata.PackageNotFoundError:
            return PINNED_PACKAGE_VERSION

    async def _fetch_user_video_page(
        self, mid: int, page_number: int, page_size: int
    ) -> Any:
        """Issue one WBI-signed request with the upload page's context fields.

        The request is built from the package's own endpoint description and
        signed by the package's ``Api``.  These fields are this adapter's:
        ``dm`` is disabled, because the device-fingerprint parameters it would
        add cannot be satisfied here and the endpoint answers HTTP 412 with
        them; and ``w_webid`` retains the adapter's explicit string fallback.
        The upload
        page context (``web_location``, ``special_type``, and ``index``) and
        the string ``order_avoided`` follow the current web request rather
        than the older package defaults. They are passed before WBI signing;
        this request shape does not guarantee that upstream risk control
        will allow a page.
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
                order=VideoOrder.PUBDATE.value,
                order_avoided="true",
                platform="web",
                web_location="333.1387",
                special_type="",
                index=0,
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
        failure names the boundary the caller invoked.  Login rejection is an
        authentication failure, never a definitive absence of subtitles.
        """

        response = await self._await_upstream(
            operation,
            lambda: self._fetch_subtitle_inventory(bvid, cid),
            authentication_api_codes=_AUTHENTICATION_API_CODES,
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

        from bili_asr.platform_access import require_platform_access
        require_platform_access()
        if mid not in self._w_webid_by_mid:
            try:
                access_id: object = await User(
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
        authentication_api_codes: frozenset[int] = frozenset(),
    ) -> Any:
        """Await one upstream call and map its failures onto the taxonomy.

        The mapped exception message carries the bounded code and operation
        name only. Its diagnostic carries validated numeric HTTP/API codes
        or a fixed reason. Upstream text, URLs and payload content stay local.
        """

        from bili_asr.platform_access import require_platform_access
        require_platform_access()

        async def scoped_call():
            async with sdk_settings_scope(
                request_settings, self.resolved_proxy,
                client_pools=session_pool, client_settings=lazy_settings,
            ):
                return await call()

        async def mapped_call():
            return await self._mapped_call(
                operation, scoped_call, not_found_api_codes=not_found_api_codes,
                authentication_api_codes=authentication_api_codes,
            )

        return await self.request_scheduler.run(operation, mapped_call)

    async def _mapped_call(self, operation: str, call: Callable[[], Awaitable[Any]], *,
                           not_found_api_codes: frozenset[int],
                           authentication_api_codes: frozenset[int]) -> Any:
        try:
            return await call()
        except NetworkException as exc:
            diagnostic = GatewayDiagnostic(
                operation,
                http_status=exc.status if type(exc.status) is int and 100 <= exc.status <= 599 else None,
            )
            if exc.status in _RATE_LIMITED_HTTP_STATUSES:
                raise GatewayRateLimited(detail=operation, diagnostic=diagnostic) from exc
            if exc.status in _NOT_FOUND_HTTP_STATUSES:
                raise GatewayNotFound(detail=operation, diagnostic=diagnostic) from exc
            raise GatewayTransportError(detail=operation, diagnostic=diagnostic) from exc
        except ResponseCodeException as exc:
            diagnostic = GatewayDiagnostic(
                operation,
                api_code=exc.code if type(exc.code) is int and -(2**31) <= exc.code < 2**31 else None,
            )
            if exc.code in _RATE_LIMITED_API_CODES:
                raise GatewayRateLimited(detail=operation, diagnostic=diagnostic) from exc
            if exc.code in authentication_api_codes:
                raise GatewayAuthenticationError(detail=operation, diagnostic=diagnostic) from exc
            if exc.code in not_found_api_codes:
                raise GatewayNotFound(detail=operation, diagnostic=diagnostic) from exc
            raise GatewayResponseError(detail=operation, diagnostic=diagnostic) from exc
        except WbiRetryTimesExceedException as exc:
            raise GatewayRateLimited(detail=operation, diagnostic=GatewayDiagnostic(
                operation, reason="wbi_retry_exhausted")) from exc
        except ResponseException as exc:
            raise GatewayResponseError(detail=operation, diagnostic=GatewayDiagnostic(
                operation, reason="response_error")) from exc
        except ApiException as exc:
            raise GatewayResponseError(detail=operation, diagnostic=GatewayDiagnostic(
                operation, reason="response_error")) from exc
        except Exception as exc:
            raise GatewayTransportError(detail=operation, diagnostic=GatewayDiagnostic(
                operation, reason="transport_error")) from exc


__all__ = ["BilibiliApiGateway"]
