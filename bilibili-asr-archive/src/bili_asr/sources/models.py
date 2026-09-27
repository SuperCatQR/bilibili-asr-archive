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
    """Validate one printable, non-empty text field of a DTO.

    The rule is the storage contract's own (``storage.models._text``): a
    non-empty string after stripping that carries no control character.  A
    control character is rejected rather than kept because these fields are
    operator-facing — the CLI prints them verbatim, one line per record — so a
    value carrying ``\\x00``, ``\\r``, or ``\\n`` would split a locked output
    shape instead of being displayed.  Caption body text is the one documented
    exception and goes through :func:`_caption_text` instead, mirroring the
    storage contract's own split.
    """
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    if not value.strip():
        raise ValueError(f"{field} must not be empty")
    if "\x00" in value or "\r" in value or "\n" in value:
        raise ValueError(f"{field} contains invalid control characters")
    return value


def _caption_text(value: object, field: str) -> str:
    """Validate one caption body row: a string non-empty after stripping.

    The mirror of ``storage.models._caption_text``, which the storage contract
    states explicitly: unlike :func:`_text`, control characters inside a
    caption body are *kept*, because a stored caption is verbatim apart from
    trimming.  A cue may legitimately span two lines, so rejecting ``\\n`` here
    would turn a real caption into a document-level shape error — and the store
    is the boundary that decides what it can hold, not this DTO.
    """
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

    ``author`` is the uploader's own display name as this page reported it, and
    it is nullable too: the list response may omit it, and absence stays
    absence rather than being filled with ``str(mid)`` here.  The gateway must
    not fabricate a display label, because ``None`` is what lets the ingestor
    tell "upstream sent no name" from "upstream sent this name" — the ingestor
    owns the user record, so the fallback is its decision, not this DTO's.

    ``pic``/``desc``/``tid`` are the video's cover URL, description and
    category id as **this list response** carried them, and all three are
    nullable: upstream leaves the description empty on some videos and the
    fields are read from the response already received, so absence is a fact
    about the page rather than an error.  The category key is spelled
    ``typeid`` on this endpoint (the view endpoint calls it ``tid``) and this
    field keeps the stored column's name.  These are the three values the
    ``video_details`` row is built from, and a run that observed none of them
    writes no row — so blank text is normalized to ``None`` at the boundary,
    where "upstream sent nothing" can still be told from "upstream sent a
    space".
    """

    bvid: str
    aid: int | None
    title: str
    pubdate: int
    mid: int
    author: str | None = None
    pic: str | None = None
    desc: str | None = None
    tid: int | None = None

    def __post_init__(self) -> None:
        _text(self.bvid, "bvid")
        if self.aid is not None:
            _integer(self.aid, "aid", minimum=1)
        _text(self.title, "title")
        _integer(self.pubdate, "pubdate", minimum=0)
        _integer(self.mid, "mid", minimum=1)
        if self.author is not None:
            _text(self.author, "author")
        if self.pic is not None:
            _text(self.pic, "pic")
        if self.desc is not None:
            _text(self.desc, "desc")
        if self.tid is not None:
            _integer(self.tid, "tid", minimum=1)


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
class VideoTag:
    """One tag upstream reports for one video, normalized to three fields.

    Like ``SubtitleTrack``, this is one entry of an inventory whose owner is
    the *call's* argument: ``get_video_tags(bvid)`` already names the video, so
    the DTO does not repeat it.  The identity is ``(bvid, tag_id)`` and the
    store holds both; here the ``bvid`` is the caller's, carried to the
    repository by the ingestor rather than through every entry.

    ``tag_name`` is a display label upstream may rename while the id stays the
    same, and ``tag_type`` is upstream's own classification (``old_channel``
    and the like).  Only these three are carried: upstream's response also
    holds a ``music_id`` and a ``jump_url``, and neither is a fact this archive
    stores — a URL in particular is the kind of value the store's no-URL rule
    keeps out, so it never reaches a DTO in the first place.
    """

    tag_id: int
    tag_name: str
    tag_type: str

    def __post_init__(self) -> None:
        _integer(self.tag_id, "tag_id", minimum=1)
        _text(self.tag_name, "tag_name")
        _text(self.tag_type, "tag_type")


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


@dataclass(frozen=True, slots=True)
class SubtitleTrack:
    """One subtitle inventory entry of one part, as upstream listed it.

    ``language`` is the upstream ``lan`` code and ``label`` its human-readable
    ``lan_doc``; both are printable as-is.  ``is_ai`` separates
    machine-generated captions from uploader/human ones.  ``track_id`` is the
    track's upstream identity when it carries one — never a URL: a signed
    ``subtitle_url`` is process-local for the duration of one call and cannot
    reach this DTO.
    """

    language: str
    label: str
    is_ai: bool
    track_id: str | None

    def __post_init__(self) -> None:
        _text(self.language, "language")
        # The service derives the language family from the primary subtag, so a
        # vocabulary it could not rank (``-zh``) is rejected here.
        if not self.language.split("-", 1)[0].strip():
            raise ValueError("language must carry a non-empty primary subtag")
        _text(self.label, "label")
        if not isinstance(self.is_ai, bool):
            raise TypeError("is_ai must be a boolean")
        if self.track_id is not None:
            _text(self.track_id, "track_id")


@dataclass(frozen=True, slots=True)
class SubtitleSegment:
    """One normalized caption row in milliseconds.

    ``end_ms > start_ms >= 0`` with ``text`` non-empty after stripping is the
    invariant this DTO enforces on what a call returns.  It is not a filter:
    the adapter drops a row carrying nothing usable before constructing it.
    ``text`` is validated as caption body text (:func:`_caption_text`), so a
    cue that legitimately spans two lines stays one row — the store keeps
    caption text verbatim, control characters included.
    """

    start_ms: int
    end_ms: int
    text: str

    def __post_init__(self) -> None:
        _integer(self.start_ms, "start_ms", minimum=0)
        _integer(self.end_ms, "end_ms", minimum=1)
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        _caption_text(self.text, "text")


class BilibiliGateway(Protocol):
    """Application-owned gateway protocol for the pinned package adapter."""

    # 30 is the page size the user-video endpoint accepts: the pinned package
    # documents ``ps`` as ``const int: 30`` and upstream answers ``ps=100``
    # with its bounded ``-400``/HTTP 412 rejection.
    async def get_user_video_page(
        self, mid: int, page_number: int, page_size: int = 30
    ) -> UserVideoPage: ...

    async def get_video_parts(self, bvid: str) -> tuple[VideoPart, ...]: ...

    async def get_completed_video_summary(
        self, summary: VideoSummary
    ) -> VideoSummary: ...

    # The tag set is a property of the VIDEO, not of a part: it is fetched
    # once per video and cached for the run's duration.  A tag fetch is
    # retry-free and degrades rather than raising — risk control and transport
    # failures on this call may not fail the collection run — but the
    # degradation is a *third state*, not an empty set: ``None`` means "this
    # call could not read the tags this time" and ``()`` means "read it, and
    # this video carries none".  Callers must not turn the first into the
    # second: the ingestor omits such a bvid from a page's tag sets, so
    # nothing is written for it and rows a previous run stored survive
    # (compass D16).  A key present with an empty iterable is the observation
    # that clears them.
    async def get_video_tags(self, bvid: str) -> tuple[VideoTag, ...] | None: ...

    # A subtitle inventory is an observation, not a promise: an empty tuple
    # means nothing usable was visible with the credentials in effect, and it
    # is a legitimate result rather than a ``not_found`` failure.
    async def get_subtitle_tracks(
        self, bvid: str, cid: int
    ) -> tuple[SubtitleTrack, ...]: ...

    # The body fetch is the opposite signal, because an empty success would
    # claim a subtitle it does not have: nothing usable raises
    # ``GatewayNotFound`` and the return is never an empty tuple.
    async def fetch_subtitle_segments(
        self, track: SubtitleTrack, bvid: str, cid: int
    ) -> tuple[SubtitleSegment, ...]: ...

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
    "SubtitleSegment",
    "SubtitleTrack",
    "UserVideoPage",
    "VideoPart",
    "VideoSummary",
    "VideoTag",
]
