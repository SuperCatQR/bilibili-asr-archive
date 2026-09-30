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

from bilibili_api import Credential, request_settings
from bilibili_api.exceptions import (
    ApiException,
    NetworkException,
    ResponseCodeException,
    ResponseException,
    WbiRetryTimesExceedException,
)
from bilibili_api.user import API as USER_API, User, VideoOrder
from bilibili_api.utils.network import Api
from bilibili_api.video import API as VIDEO_API, Video

from bili_asr.config import resolve_proxy
from bili_asr.sources.models import (
    GatewayError,
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
    VideoTag,
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

# Exactly the characters the storage contract's ``_text`` rule refuses (its
# message is "contains invalid control characters").  ``\t``/``\x0b``/``\x0c``
# are deliberately absent: that rule accepts them, and a predicate over
# ``str.isspace()`` here would quietly widen this set.  A field whose stored
# text has no reader that renders it can be read as absent instead of raising
# on these; a field with a locked output shape cannot (see
# ``_read_optional_text``).
_INVALID_CONTROL_CHARACTERS = ("\x00", "\r", "\n")

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


def _read_optional_text(
    item: Mapping,
    field: str,
    *,
    control_characters_are_absence: bool = False,
) -> str | None:
    """Read one optional text field, collapsing blank text to absence.

    Upstream leaves these fields present-but-empty on real items; empty is not
    a value the store should carry, because the ingestor counts an observation
    by whether the field holds anything and a blank would count as one.  So the
    collapse happens here, where "upstream sent an empty string" and "upstream
    sent nothing" are both still distinguishable from a real value.  A present
    non-string is a bounded shape error like every sibling field's.

    ``control_characters_are_absence`` is how the **caller** says whether the
    storage contract's refusal of ``\\x00``/``\\r``/``\\n`` should be answered
    with absence or with that refusal.  It is opt-in per field rather than a
    rule this function applies to everything it reads, because the two callers
    answer differently and the difference is a decision, not an oversight:

    * ``desc`` passes it.  The description is the one field here that no
      output renders — it is neither in the CLI's locked one-line-per-record
      listing nor among the export's columns, so it has no shape to break and a
      control character only makes the value unrepresentable.  Reading it as
      absent keeps the page, its sibling items and the cursor, where raising
      discards all three.
    * ``pic`` does not, and that is deliberate.  A cover URL carrying a control
      character is corrupt data rather than a line break, so it stays a page
      failure.  A field-agnostic rule here would silently relax ``pic`` — which
      is why this is a parameter with a default that preserves the old
      behaviour, instead of something the reader switches on by itself.

    The strip runs first, so a control character that is only transport
    whitespace is already gone and never reaches that decision: ``"\\na"`` is
    ``"a"`` here, exactly as it was before.  What the flag decides is only the
    value left after stripping still carrying one.
    """

    value = item.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise GatewayShapeError(detail=f"video item has no valid {field}")
    text = value.strip()
    if control_characters_are_absence and any(
        mark in text for mark in _INVALID_CONTROL_CHARACTERS
    ):
        return None
    return text or None


def _read_optional_typeid(item: Mapping) -> int | None:
    """Read the list item's ``typeid`` when present; absent stays absent.

    The spelling is this endpoint's own — the view endpoint names the same
    thing ``tid`` — and the DTO field keeps the stored column's name.  A
    present-and-unusable value is a bounded shape error: the storage contract
    checks ``tid IS NULL OR tid > 0``, and failing here keeps a bad category id
    from surfacing as an ``IntegrityError`` inside a page transaction after the
    rest of the page normalized cleanly.
    """

    value = item.get("typeid")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise GatewayShapeError(detail="video item has no valid typeid")
    return value


def _normalize_video_summary_item(item: object, requested_mid: int) -> VideoSummary:
    """Convert one vlist item into a validated summary DTO.

    The uploader name is read when the item carries one and stays ``None`` when
    it does not: absence is a fact about this response rather than something to
    paper over here, because the placeholder the user record falls back to is
    the ingestor's decision, not this boundary's.

    The category and cover are read the same way, from the keys **this** list
    endpoint uses (``typeid``/``pic``/``description``), and they are never
    filled from a second call: the task stores what a response already received
    carried, and an item that omitted them establishes nothing about them.
    """

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
    author = item.get("author")
    if author is not None and (not isinstance(author, str) or not author.strip()):
        # Present but unusable is a shape error, like the title's arm above;
        # only the absent case is legitimate (see the docstring).
        raise GatewayShapeError(detail="video item has no valid author")
    try:
        return VideoSummary(
            bvid=bvid,
            aid=_read_optional_aid(item),
            title=title.strip(),
            pubdate=_read_pubdate(item),
            mid=owner_mid,
            author=None if author is None else author.strip(),
            pic=_read_optional_text(item, "pic"),
            desc=_read_optional_text(
                item, "description", control_characters_are_absence=True
            ),
            tid=_read_optional_typeid(item),
        )
    except (TypeError, ValueError) as exc:
        # The DTO rejects text the storage contract cannot hold either — a title
        # carrying a control character, for instance — and that is a bounded
        # shape error at this boundary, like every sibling normalizer's, rather
        # than a raw validation error escaping the gateway.
        raise GatewayShapeError(detail="video item is not normalizable") from exc


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


def _normalize_video_tags(entries: object) -> tuple[VideoTag, ...]:
    """Convert the tag array into validated tag DTOs.

    A video with no tags answers with an empty array, which is an honest
    observation rather than a failure.  ``tag_id`` and ``tag_name`` are
    required — an entry missing either cannot be identified or displayed, so
    it is a bounded shape error rather than a dropped row: silently skipping
    one would report "this video has N-1 tags" as if upstream had said so.
    """

    if not isinstance(entries, list):
        raise GatewayShapeError(detail="tag response is not an array")
    return tuple(_normalize_video_tag(entry) for entry in entries)


def _normalize_video_tag(entry: object) -> VideoTag:
    """Convert one documented tag entry into a validated tag DTO."""

    if not isinstance(entry, Mapping):
        raise GatewayShapeError(detail="tag entry is not a mapping")
    tag_id = entry.get("tag_id")
    if isinstance(tag_id, bool) or not isinstance(tag_id, int) or tag_id < 1:
        raise GatewayShapeError(detail="tag entry has no positive tag_id")
    tag_name = entry.get("tag_name")
    if not isinstance(tag_name, str) or not tag_name.strip():
        raise GatewayShapeError(detail="tag entry has no tag_name")
    tag_type = entry.get("tag_type")
    if not isinstance(tag_type, str) or not tag_type.strip():
        raise GatewayShapeError(detail="tag entry has no tag_type")
    try:
        return VideoTag(
            tag_id=tag_id,
            tag_name=tag_name.strip(),
            tag_type=tag_type.strip(),
        )
    except (TypeError, ValueError) as exc:
        raise GatewayShapeError(detail="tag entry is not normalizable") from exc


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
    the list response delivered it — the uploader name, category and cover
    included, because the detail is not asked for them and this rebuild is the
    only constructor between the page boundary and the ingestor.  Dropping
    ``author`` here would silently discard a name the page did carry on exactly
    the aid-less entries this path exists for, and the same holds for
    ``pic``/``desc``/``tid``: the detail response does carry ``tid``/``pic``/
    ``desc``, but filling them from it would make these fields come from a
    second call on some entries and the page on others, which is the
    distinction the task exists to keep.  A detail owned by another user, or
    one naming another video, is a bounded shape error.
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
        author=summary.author,
        pic=summary.pic,
        desc=summary.desc,
        tid=summary.tid,
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

    async def get_video_tags(self, bvid: str) -> tuple[VideoTag, ...] | None:
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
        method; the code is available to the caller through the same taxonomy
        every other call uses, and the raw response never reaches anyone.

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
        try:
            response = await self._await_upstream(
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
            )
        except GatewayError:
            # Best-effort call, and *not* an observation: ``None`` tells the
            # caller the tags could not be read, which is what keeps
            # ``record_page`` from clearing rows a previous run stored
            # (compass D16).  ``()`` here would be a lie about what upstream
            # said.  The mapped exception carried the bounded code; it is not
            # re-raised and not written anywhere by this method.
            return None
        return _normalize_video_tags(response)

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
                order=VideoOrder.PUBDATE.value,
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
