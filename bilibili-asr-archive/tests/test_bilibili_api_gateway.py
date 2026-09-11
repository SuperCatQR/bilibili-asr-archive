"""Offline contract tests for the typed Bilibili gateway boundary.

Every functional test runs against a fake ``bilibili_api`` package installed
on ``sys.modules`` before the gateway module is (re-)imported, so neither the
real package nor network access is ever required.  The fake package seam, the
shared scripted protocol double, and the secret/raw-payload sentinels live in
``tests/fixtures/fake_bilibili_gateway.py``.  The fake mirrors only the
documented import surface the gateway may use (``Credential``, the ``user``
endpoint description and ``access_id`` route, the WBI-signed
``utils.network.Api``, the ``user``/``video`` endpoint descriptions,
``video.Video``, and the exceptions taxonomy) and exposes no subtitle,
playback, audio, or download *package method*, which makes silent use of other
package APIs impossible: the player call and the signed subtitle-document
fetch are issued through the package's own ``Api`` like the page call.  The
import boundary and the method
surface itself are
additionally inspected statically with AST over the package sources.  The
only networked test is the opt-in live smoke, which skips unless
``BILI_LIVE_SMOKE=1`` is set.  The packaging-contract test is the one
exception to the "installed distribution never needed" rule: it reads the
pinned distribution's metadata and fails loudly when that distribution is
absent, because the contract it checks cannot be proven without it.
"""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import importlib
import importlib.metadata
import inspect
import os
import pathlib
import tomllib

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from bili_asr.config import PROXY_ENV_VAR, PROXY_ENV_VARS, resolve_proxy
from bili_asr.services.metadata_ingest import MetadataIngestor
from bili_asr.sources.models import (
    BilibiliGateway,
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
from bili_asr.storage.database import MetadataRepository, open_database
from fixtures.fake_bilibili_gateway import (
    BVID,
    DOCUMENTED_METADATA_CALLS,
    FAKE_PLAYER_ENDPOINT,
    FAKE_USER_VIDEO_PAGE_ENDPOINT,
    MID,
    MIRRORED_ENDPOINT_FIELDS,
    NO_LEAK_MARKERS,
    PROTOCOL_RELATIVE_SUBTITLE_URL,
    PUBDATE,
    RAW_JSON_BODY_MARKER,
    SESSDATA_BOUNDARY_VALUE,
    SIGNED_SUBTITLE_URL_MARKER,
    SIGNED_URL_MARKER,
    UPSTREAM_ERROR_TEXT,
    FakeNetworkException,
    FakeResponseCodeException,
    FakeResponseException,
    FakeUpstreamScript,
    FakeWbiRetryTimesExceedException,
    assert_leaks_no_markers,
    assert_only_documented_metadata_calls,
    bilibili_api_seam,
    build_fake_package,
    make_detail_response,
    make_part_item,
    make_player_response,
    make_subtitle_document,
    make_subtitle_entry,
    make_subtitle_track,
    make_videos_response,
    make_vlist_item,
    persisted_row_text,
)

PINNED_PACKAGE_DISTRIBUTION_NAME = "bilibili-api-python"
PINNED_PACKAGE_VERSION = "17.4.2"

#: PEP 503 canonical name of the runtime HTTP backend this project declares.
#: The pinned package drives whichever client is installed while declaring
#: none itself, so this declaration is what lets a fresh install reach the
#: network at all.
HTTP_BACKEND_CANONICAL_NAME = "curl-cffi"

#: The HTTP clients the pinned package can drive, named in its own error
#: message (``pip3 install (curl_cffi|httpx|aiohttp)``).  None of them may
#: arrive through the application's dependency closure on its own.
PACKAGE_HTTP_CLIENT_CANONICAL_NAMES = frozenset({"curl-cffi", "httpx", "aiohttp"})

#: The exact bilibili_api import surface the adapter is allowed to use.  The
#: user-video page call is issued through ``user``'s own endpoint description
#: and the WBI-signed ``utils.network.Api``, not through a ``user`` delegate;
#: the subtitle call reads its transport fields from the player endpoint
#: description the same way.  The ``video`` module is deliberately bound to its
#: two needed names instead of the whole module (only ``API``, locally aliased
#: to ``VIDEO_API`` so it cannot be confused with the ``Api`` request class, and
#: ``Video``), so ``Episode``, ``VideoOnlineMonitor``, ``get_api``,
#: ``get_cid_info`` and ``get_client`` are not source-reachable here.
ALLOWED_PACKAGE_IMPORTS = {
    "bilibili_api": {"Credential", "request_settings", "user"},
    "bilibili_api.utils.network": {"Api"},
    "bilibili_api.video": {"API", "Video"},
    "bilibili_api.exceptions": {
        "ApiException",
        "NetworkException",
        "ResponseCodeException",
        "ResponseException",
        "WbiRetryTimesExceedException",
    },
}

#: Realistic-looking proxy URL: configuration rather than a credential, but it
#: must still stay off DTOs, mapped errors, debug renders, and persisted rows.
PROXY_BOUNDARY_VALUE = "http://PROXY-URL-THAT-MUST-NOT-LEAK:7890"

#: Realistic-looking ``access_id`` token: a request parameter the package
#: route may yield, which must stay off DTOs and mapped errors like every
#: other upstream value.
ACCESS_ID_BOUNDARY_VALUE = "ACCESS-ID-THAT-MUST-NOT-LEAK"

#: Sentinel endpoint URL proving the transport fields are read from the
#: package's own endpoint description instead of being hard-coded.
CHANGED_ENDPOINT_URL = "https://changed-endpoint.example.invalid/x/space/wbi/arc/search"

#: The part cid the scripted subtitle calls are issued for: a part identity,
#: never a subtitle identity.
PART_CID = 2222

#: Sentinel player-endpoint URL proving the player call's transport fields are
#: read from the package's own player description instead of being hard-coded.
CHANGED_PLAYER_ENDPOINT_URL = (
    "https://changed-player.example.invalid/x/player/wbi/v2"
)


#: A second signed subtitle-document URL for one part.  It extends the seam's
#: sentinel — so a leak of it is still caught by the no-secret scanner — and it
#: lets a test prove the ``track_id`` tie-break fetched the entry the request
#: named rather than the first match.
SECOND_SUBTITLE_URL = SIGNED_SUBTITLE_URL_MARKER + "&second=1"


def _probe_installed_pinned_endpoint() -> dict | str:
    """Read the pin's endpoint description, or the reason it could not be read.

    Runs once, at module import time — before any seam fixture can install the
    fake ``bilibili_api`` package on ``sys.modules``: a lazy import inside a
    seam test would return the fake, and the mirror would then be compared
    against itself.  The description is pure package data, so this needs no
    network.  A string return is a human-readable reason (distribution absent,
    key renamed, unexpected shape) that the parity tests turn into a loud
    failure with install guidance.
    """

    try:
        module = importlib.import_module("bilibili_api.user")
        endpoint = module.API["info"]["video"]
    except (ImportError, KeyError, AttributeError, TypeError) as error:
        return f"{type(error).__name__}: {error}"
    if not isinstance(endpoint, dict):
        return f"the description is not a mapping ({type(endpoint).__name__})"
    return dict(endpoint)


#: The installed pin's own user-video endpoint description, captured before the
#: seam can shadow the package; see :func:`_probe_installed_pinned_endpoint`.
_INSTALLED_PINNED_ENDPOINT = _probe_installed_pinned_endpoint()


def _probe_installed_pinned_player_endpoint() -> dict | str:
    """Read the pin's player endpoint description, or why it could not be read.

    Captured at import time for the same reason as the user-video description:
    a lazy import inside a seam test would return the fake.  The description is
    pure package data, so this needs no network.
    """

    try:
        module = importlib.import_module("bilibili_api.video")
        endpoint = module.API["info"]["get_player_info"]
    except (ImportError, KeyError, AttributeError, TypeError) as error:
        return f"{type(error).__name__}: {error}"
    if not isinstance(endpoint, dict):
        return f"the description is not a mapping ({type(endpoint).__name__})"
    return dict(endpoint)


#: The installed pin's own player endpoint description, captured the same way.
_INSTALLED_PINNED_PLAYER_ENDPOINT = _probe_installed_pinned_player_endpoint()


def _probe_installed_api_call_shape() -> dict | str:
    """Read the pin's ``Api`` constructor fields and ``request`` signature.

    Captured at import time for the same reason as the endpoint descriptions.
    The shape matters because the seam must not accept a call the pin would
    reject: in the pin ``raw``/``byte`` are ``request`` arguments, not
    constructor fields, so a double that took ``raw=True`` at construction
    would pass offline and raise ``TypeError`` live.
    """

    try:
        api = importlib.import_module("bilibili_api.utils.network").Api
        return {
            "fields": [field.name for field in dataclasses.fields(api)],
            "request": [
                (parameter.name, str(parameter.kind), parameter.default)
                for parameter in inspect.signature(api.request).parameters.values()
            ],
        }
    except (ImportError, AttributeError, TypeError, ValueError) as error:
        return f"{type(error).__name__}: {error}"


#: The installed pin's ``Api`` call shape, captured the same way.
_INSTALLED_API_CALL_SHAPE = _probe_installed_api_call_shape()


def _probe_installed_request_settings_parameters() -> dict | str:
    """Read the pin's request-settings parameter shapes, or why not.

    Captured at import time for the same reason as the endpoint description: a
    lazy import inside a seam test would read the fake.  Only the parameter
    name/kind/default triples are kept — the shape a mirrored double must not
    loosen (``RequestSettings.set_proxy(self, proxy: str)`` has no default).
    """

    try:
        settings = importlib.import_module("bilibili_api").request_settings
        return {
            name: [
                (parameter.name, str(parameter.kind), parameter.default)
                for parameter in inspect.signature(
                    getattr(settings, name)
                ).parameters.values()
            ]
            for name in ("set_proxy", "get_proxy")
        }
    except (ImportError, AttributeError, TypeError, ValueError) as error:
        return f"{type(error).__name__}: {error}"


#: The installed pin's request-settings parameter shapes, captured the same way.
_INSTALLED_REQUEST_SETTINGS_PARAMETERS = _probe_installed_request_settings_parameters()


def _require_installed(probe: dict | str, what: str) -> dict:
    """Return a successful import-time probe, or fail loudly with guidance."""

    if isinstance(probe, str):
        pytest.fail(
            f"this parity contract needs the pinned distribution's {what}"
            f" ({PINNED_PACKAGE_DISTRIBUTION_NAME}=={PINNED_PACKAGE_VERSION});"
            f" it could not be read ({probe}). Run uv sync first."
        )
    return probe


#: The complete documented exception surface the fake seam must mirror.
ALLOWED_EXCEPTION_NAMES = (
    "ApiException",
    "NetworkException",
    "ResponseCodeException",
    "ResponseException",
    "WbiRetryTimesExceedException",
)

#: Attribute names that would mark playback/danmaku/audio/ASR/export/media
#: usage — the surfaces outside this plan's boundary.  Tokens are matched as
#: plain substrings, so only unambiguous names belong here (``stream`` would
#: false-positive on ``_await_upstream``).  The PM-authorized Task-2 update
#: removed only the subtitle/player half of the acquisition family on
#: 2026-09-11: this plan legitimately issues the player and subtitle-document
#: calls, and ``test_gateway_source_never_names_forbidden_seam_methods`` now
#: positively asserts that surface instead (see
#: ``AUTHORIZED_SUBTITLE_ATTRIBUTES``).  ``download`` came back the same day
#: (Task-2 review tightening M2): this iteration acquires no media, and leaving
#: it out would un-guard a future ``get_download_url``.
FORBIDDEN_SEAM_METHOD_TOKENS = (
    "playback",
    "playurl",
    "play_url",
    "download",
    "danmaku",
    "audio",
    "asr",
    "export",
)

#: The tokens the authorized update removed from the forbidden list and this
#: plan still needs.  They are kept here only so the positive control below can
#: prove the removal is load-bearing: each asserted attribute name still carries
#: one of them.
AUTHORIZED_SEAM_METHOD_TOKENS = ("subtitle", "player")

#: The adapter's own subtitle-surface attributes the token scan must be able to
#: see.  Asserting them present keeps the forbidden-token check non-vacuous: it
#: cannot pass merely because the adapter carries no subtitle code at all.
AUTHORIZED_SUBTITLE_ATTRIBUTES = (
    "_fetch_subtitle_document",
    "_fetch_subtitle_inventory",
    "_list_subtitle_entries",
)


def _public_names(obj: object) -> list[str]:
    """List the public (non-dunder) names on a module or class."""

    return sorted(name for name in vars(obj) if not name.startswith("_"))


def _load_gateway(sessdata: str | None = None, proxy: str | None = None):
    """Import the adapter against the installed seam and build it."""

    module = importlib.import_module("bili_asr.sources.bilibili_api_gateway")
    return module.BilibiliApiGateway(sessdata=sessdata, proxy=proxy)


# --------------------------------------------------- deterministic factories


def _summary(**overrides: object) -> VideoSummary:
    """Build one validated summary DTO; aid is missing by default."""

    values = {
        "bvid": BVID,
        "aid": None,
        "title": "未明子讲座",
        "pubdate": PUBDATE,
        "mid": MID,
    }
    values.update(overrides)
    return VideoSummary(**values)


# ------------------------------------------------ user page: DTO normalization


def test_get_user_video_page_normalizes_documented_fields(bilibili_api_seam):
    """One bounded call maps vlist scalars into validated DTO fields."""

    bilibili_api_seam.videos_response = make_videos_response(
        make_vlist_item(title="  未明子讲座  "), count=7
    )
    gateway = _load_gateway(sessdata=SESSDATA_BOUNDARY_VALUE)

    page = asyncio.run(gateway.get_user_video_page(MID, page_number=1))

    assert isinstance(page, UserVideoPage)
    assert page.mid == MID
    assert page.page_number == 1
    assert page.observed_total == 7
    assert isinstance(page.videos, tuple)
    (summary,) = page.videos
    assert isinstance(summary, VideoSummary)
    assert summary.bvid == BVID
    assert summary.aid == 111
    assert summary.title == "未明子讲座"
    assert summary.pubdate == PUBDATE
    assert summary.mid == MID
    assert bilibili_api_seam.calls == ["space.arc.search(pn=1, ps=30)"]
    # The credential value must never surface on any DTO or page.
    assert SESSDATA_BOUNDARY_VALUE not in repr(page)
    assert SESSDATA_BOUNDARY_VALUE not in str(page)


def test_get_user_video_page_forwards_requested_page_and_size(bilibili_api_seam):
    """The adapter passes the documented page parameters only."""

    bilibili_api_seam.videos_response = make_videos_response(make_vlist_item(), count=1)
    gateway = _load_gateway()

    asyncio.run(gateway.get_user_video_page(MID, page_number=4, page_size=50))

    assert bilibili_api_seam.calls == ["space.arc.search(pn=4, ps=50)"]


def test_get_user_video_page_defaults_to_upstream_accepted_size(bilibili_api_seam):
    """An omitted page size issues the upstream-accepted ``ps=30``.

    The endpoint answers the former ``ps=100`` default with its bounded
    ``-400``/HTTP 412 rejection, so the protocol declaration and the adapter
    both default to 30 — reverting either to 100 fails this test.
    """

    bilibili_api_seam.videos_response = make_videos_response(make_vlist_item(), count=1)
    gateway = _load_gateway()

    asyncio.run(gateway.get_user_video_page(MID, page_number=1))

    assert bilibili_api_seam.calls == ["space.arc.search(pn=1, ps=30)"]
    declared = inspect.signature(BilibiliGateway.get_user_video_page)
    assert declared.parameters["page_size"].default == 30


def test_get_user_video_page_explicit_size_override_keeps_normalization(
    bilibili_api_seam,
):
    """An explicit page size still flows through and normalizes the page."""

    bilibili_api_seam.videos_response = make_videos_response(
        make_vlist_item(title="  未明子讲座  "), count=7
    )
    gateway = _load_gateway()

    page = asyncio.run(gateway.get_user_video_page(MID, page_number=2, page_size=50))

    assert bilibili_api_seam.calls == ["space.arc.search(pn=2, ps=50)"]
    assert isinstance(page, UserVideoPage)
    assert (page.mid, page.page_number, page.observed_total) == (MID, 2, 7)
    assert isinstance(page.videos, tuple)
    (summary,) = page.videos
    assert isinstance(summary, VideoSummary)
    assert (summary.bvid, summary.aid, summary.title, summary.pubdate, summary.mid) == (
        BVID,
        111,
        "未明子讲座",
        PUBDATE,
        MID,
    )


def test_get_user_video_page_tolerates_plain_list_container(bilibili_api_seam):
    """A plain ``list`` array instead of ``list.vlist`` normalizes too."""

    bilibili_api_seam.videos_response = {"list": [make_vlist_item()], "page": {"count": 3}}
    gateway = _load_gateway()

    page = asyncio.run(gateway.get_user_video_page(MID, page_number=2))

    assert page.observed_total == 3
    assert [summary.bvid for summary in page.videos] == [BVID]


def test_get_user_video_page_observed_total_absent_is_none(bilibili_api_seam):
    """A response without a total field yields ``observed_total=None``."""

    bilibili_api_seam.videos_response = make_videos_response(make_vlist_item(), count=None)
    gateway = _load_gateway()

    page = asyncio.run(gateway.get_user_video_page(MID, page_number=1))

    assert page.observed_total is None


def test_get_user_video_page_accepts_pubdate_fallback_field(bilibili_api_seam):
    """An item carrying ``pubdate`` instead of ``created`` still normalizes."""

    bilibili_api_seam.videos_response = make_videos_response(
        {"bvid": BVID, "aid": 111, "title": "未明子讲座", "pubdate": PUBDATE, "mid": MID},
        count=1,
    )
    gateway = _load_gateway()

    page = asyncio.run(gateway.get_user_video_page(MID, page_number=1))

    assert page.videos[0].pubdate == PUBDATE


def test_get_user_video_page_returns_empty_page(bilibili_api_seam):
    """An empty vlist is a valid empty page."""

    bilibili_api_seam.videos_response = make_videos_response()
    gateway = _load_gateway()

    page = asyncio.run(gateway.get_user_video_page(MID, page_number=5))

    assert page.videos == ()
    assert page.observed_total == 2


# ------------------------------------------ user page: argument/shape rejection


@pytest.mark.parametrize(
    ("mid", "page_number", "page_size"),
    [(0, 1, 100), (MID, 0, 100), (MID, 1, 0)],
)
def test_get_user_video_page_rejects_invalid_arguments(
    bilibili_api_seam, mid, page_number, page_size
):
    """Caller-argument violations raise ValueError before any API call."""

    gateway = _load_gateway()

    with pytest.raises(ValueError):
        asyncio.run(gateway.get_user_video_page(mid, page_number=page_number, page_size=page_size))
    assert bilibili_api_seam.calls == []


def test_get_user_video_page_rejects_non_mapping_response(bilibili_api_seam):
    """A non-dictionary upstream response is a shape error."""

    gateway = _load_gateway()
    for broken in (None, "ok", 5, [1, 2]):
        bilibili_api_seam.videos_response = broken
        with pytest.raises(GatewayShapeError):
            asyncio.run(gateway.get_user_video_page(MID, page_number=1))


def test_get_user_video_page_rejects_unknown_list_shape(bilibili_api_seam):
    """An unrecognizable ``list`` container is a shape error."""

    gateway = _load_gateway()
    for broken in ({"list": {"nolist": []}}, {"list": "no"}, {"videos": []}):
        bilibili_api_seam.videos_response = broken
        with pytest.raises(GatewayShapeError):
            asyncio.run(gateway.get_user_video_page(MID, page_number=1))


def test_get_user_video_page_rejects_foreign_owner_mid(bilibili_api_seam):
    """Items owned by another user are rejected as a bounded shape error."""

    bilibili_api_seam.videos_response = make_videos_response(make_vlist_item(mid=MID + 1))
    gateway = _load_gateway()

    with pytest.raises(GatewayShapeError) as caught:
        asyncio.run(gateway.get_user_video_page(MID, page_number=1))

    assert caught.value.code == "shape_error"
    assert "mid" in str(caught.value)


def test_get_user_video_page_rejects_a_title_with_control_characters(
    bilibili_api_seam,
):
    """A title the storage contract cannot hold is a bounded shape error here.

    The DTO applies the same printable-text rule the storage contract applies, so
    the metadata path stays bounded: an upstream title carrying a control
    character is rejected as this page's ``shape_error`` instead of escaping as a
    raw validation error from a later write.
    """

    bilibili_api_seam.videos_response = make_videos_response(
        make_vlist_item(title="未明子讲座\n伪造第二行"), count=1
    )
    gateway = _load_gateway()

    with pytest.raises(GatewayShapeError) as caught:
        asyncio.run(gateway.get_user_video_page(MID, page_number=1))

    assert caught.value.code == "shape_error"
    assert bilibili_api_seam.calls == ["space.arc.search(pn=1, ps=30)"]


def test_get_user_video_page_rejects_missing_owner_mid(bilibili_api_seam):
    """An item without an owner mid cannot prove ownership."""

    bilibili_api_seam.videos_response = make_videos_response(
        {"bvid": BVID, "aid": 111, "title": "未明子讲座", "created": PUBDATE}
    )
    gateway = _load_gateway()

    with pytest.raises(GatewayShapeError):
        asyncio.run(gateway.get_user_video_page(MID, page_number=1))


@pytest.mark.parametrize(
    "broken_item",
    [
        {},
        {"bvid": "", "title": "未明子讲座", "created": PUBDATE, "mid": MID},
        {"bvid": "   ", "title": "未明子讲座", "created": PUBDATE, "mid": MID},
        {"bvid": BVID, "title": "   ", "created": PUBDATE, "mid": MID},
        {"bvid": 123, "title": "未明子讲座", "created": PUBDATE, "mid": MID},
        {"bvid": BVID, "title": "未明子讲座", "created": "no", "mid": MID},
        {"bvid": BVID, "title": "未明子讲座", "created": True, "mid": MID},
        {"bvid": BVID, "title": "未明子讲座", "created": -1, "mid": MID},
        {"bvid": BVID, "title": "未明子讲座", "created": PUBDATE, "aid": 0, "mid": MID},
        {"bvid": BVID, "title": "未明子讲座", "created": PUBDATE, "aid": True, "mid": MID},
        {"bvid": BVID, "title": "未明子讲座", "created": PUBDATE, "aid": "111", "mid": MID},
        {"bvid": BVID, "title": "未明子讲座", "created": PUBDATE, "mid": True},
        {"bvid": BVID, "title": "未明子讲座", "created": PUBDATE, "mid": "23191782"},
        [make_vlist_item()],
    ],
)
def test_get_user_video_page_rejects_malformed_items(bilibili_api_seam, broken_item):
    """Every required scalar is validated before a DTO is returned."""

    bilibili_api_seam.videos_response = make_videos_response(broken_item)
    gateway = _load_gateway()

    with pytest.raises(GatewayShapeError):
        asyncio.run(gateway.get_user_video_page(MID, page_number=1))


def test_get_user_video_page_rejects_malformed_observed_total(bilibili_api_seam):
    """A present but non-integer total is a shape error, not a silent None."""

    bilibili_api_seam.videos_response = {
        "list": {"vlist": [make_vlist_item()]},
        "page": {"count": "many"},
    }
    gateway = _load_gateway()

    with pytest.raises(GatewayShapeError):
        asyncio.run(gateway.get_user_video_page(MID, page_number=1))


@pytest.mark.parametrize(
    ("malformed_bvid", "aid"),
    [
        ("BV1SHORT", 111),
        ("BV1SHORT", None),
        ("av170001", 111),
    ],
)
def test_get_user_video_page_rejects_malformed_upstream_bvid(
    bilibili_api_seam, malformed_bvid, aid
):
    """A non-empty but malformed upstream bvid is a bounded shape error.

    The same shape defect stays bounded on both aid paths: the page
    boundary rejects the item before any parts or detail call could
    consume the malformed id downstream.
    """

    bilibili_api_seam.videos_response = make_videos_response(
        make_vlist_item(bvid=malformed_bvid, aid=aid), count=1
    )
    gateway = _load_gateway()

    with pytest.raises(GatewayShapeError) as caught:
        asyncio.run(gateway.get_user_video_page(MID, page_number=1))

    assert caught.value.code == "shape_error"
    assert "bvid" in str(caught.value)
    assert bilibili_api_seam.calls == ["space.arc.search(pn=1, ps=30)"]


# ------------------------------------- user page: risk-control-safe request


def test_user_video_page_request_carries_the_documented_parameter_set(
    bilibili_api_seam,
):
    """The page request sends the package's parameters with ``dm`` disabled.

    Device-fingerprint parameters cannot be satisfied here and make the
    endpoint answer HTTP 412; the same endpoint answers ``code=0`` without
    them, and the request must still carry ``w_webid`` (empty is the value
    the unavailable token route degrades to).
    """

    bilibili_api_seam.videos_response = make_videos_response(make_vlist_item(), count=1)
    gateway = _load_gateway()

    asyncio.run(gateway.get_user_video_page(MID, page_number=2, page_size=50))

    (request,) = bilibili_api_seam.api_requests
    assert request.dm is False
    assert [key for key in request.params if key.startswith("dm_")] == []
    assert request.params == {
        "mid": MID,
        "ps": 50,
        "tid": 0,
        "pn": 2,
        "keyword": "",
        "order": "pubdate",
        "order_avoided": True,
        "platform": "web",
        "w_webid": "",
    }


def test_user_video_page_request_prefers_the_package_access_id(bilibili_api_seam):
    """A non-empty ``access_id`` from the package route is what gets sent."""

    bilibili_api_seam.access_id = ACCESS_ID_BOUNDARY_VALUE
    bilibili_api_seam.videos_response = make_videos_response(make_vlist_item(), count=1)
    gateway = _load_gateway()

    page = asyncio.run(gateway.get_user_video_page(MID, page_number=1))

    assert bilibili_api_seam.access_id_calls == [f"user.get_access_id(uid={MID})"]
    assert (
        bilibili_api_seam.api_requests[0].params["w_webid"]
        == ACCESS_ID_BOUNDARY_VALUE
    )
    # A request parameter still never surfaces on a DTO.
    assert ACCESS_ID_BOUNDARY_VALUE not in repr(page)


def test_user_video_page_request_falls_back_to_empty_w_webid_when_the_route_fails(
    bilibili_api_seam,
):
    """A failing token scrape never fails the page call itself."""

    bilibili_api_seam.access_id_error = FakeNetworkException(412, UPSTREAM_ERROR_TEXT)
    bilibili_api_seam.videos_response = make_videos_response(make_vlist_item(), count=1)
    gateway = _load_gateway()

    page = asyncio.run(gateway.get_user_video_page(MID, page_number=1))

    assert page.observed_total == 1
    assert bilibili_api_seam.api_requests[0].params["w_webid"] == ""
    assert UPSTREAM_ERROR_TEXT not in str(page)


def test_user_video_page_resolves_the_access_id_once_per_user(bilibili_api_seam):
    """Repeated pages of one user scrape the token route at most once."""

    bilibili_api_seam.videos_response = make_videos_response(make_vlist_item(), count=1)
    gateway = _load_gateway()

    asyncio.run(gateway.get_user_video_page(MID, page_number=1))
    asyncio.run(gateway.get_user_video_page(MID, page_number=2))

    assert bilibili_api_seam.access_id_calls == [f"user.get_access_id(uid={MID})"]
    assert len(bilibili_api_seam.api_requests) == 2


def test_user_video_page_resolves_the_access_id_per_user(bilibili_api_seam):
    """The memoized token is bound to the user it was scraped for."""

    bilibili_api_seam.videos_response = make_videos_response(make_vlist_item(), count=1)
    gateway = _load_gateway()

    asyncio.run(gateway.get_user_video_page(MID, page_number=1))

    bilibili_api_seam.videos_response = make_videos_response(
        make_vlist_item(mid=MID + 1), count=1
    )
    asyncio.run(gateway.get_user_video_page(MID + 1, page_number=1))

    assert bilibili_api_seam.access_id_calls == [
        f"user.get_access_id(uid={MID})",
        f"user.get_access_id(uid={MID + 1})",
    ]


def test_user_video_page_request_takes_its_transport_from_the_package_endpoint(
    bilibili_api_seam,
):
    """``url``/``method``/``verify``/``wbi`` come from the package description."""

    bilibili_api_seam.videos_response = make_videos_response(make_vlist_item(), count=1)
    gateway = _load_gateway()

    asyncio.run(gateway.get_user_video_page(MID, page_number=1))

    (request,) = bilibili_api_seam.api_requests
    assert request.url == FAKE_USER_VIDEO_PAGE_ENDPOINT["url"]
    assert request.method == FAKE_USER_VIDEO_PAGE_ENDPOINT["method"]
    assert request.wbi is FAKE_USER_VIDEO_PAGE_ENDPOINT["wbi"]
    assert request.verify is FAKE_USER_VIDEO_PAGE_ENDPOINT["verify"]
    # The package's own description carries ``dm: True``; the adapter turns
    # that off itself.
    assert FAKE_USER_VIDEO_PAGE_ENDPOINT["dm"] is True
    assert request.dm is False


def test_user_video_page_request_follows_a_changed_package_endpoint(
    bilibili_api_seam,
):
    """No transport field is hard-coded: the package description decides."""

    bilibili_api_seam.user_video_page_endpoint["url"] = CHANGED_ENDPOINT_URL
    bilibili_api_seam.user_video_page_endpoint["wbi"] = False
    bilibili_api_seam.videos_response = make_videos_response(make_vlist_item(), count=1)
    gateway = _load_gateway()

    asyncio.run(gateway.get_user_video_page(MID, page_number=1))

    (request,) = bilibili_api_seam.api_requests
    assert request.url == CHANGED_ENDPOINT_URL
    assert request.wbi is False


def test_fake_endpoint_mirror_matches_the_installed_pinned_description():
    """The seam's mirrored endpoint description is the installed pin's.

    ``FAKE_USER_VIDEO_PAGE_ENDPOINT`` is the sole offline oracle for the
    risk-control-relevant call shape, so its claim to mirror
    ``bilibili_api.user.API["info"]["video"]`` literally is checked against
    the distribution it mirrors, not only against itself (the same
    packaging-parity pattern the HTTP-backend test uses).  A pin bump that
    renames a key or flips ``verify``/``wbi``/``dm`` fails here instead of
    staying green offline and surfacing only live.

    Offline and deterministic: reading the installed distribution is the only
    I/O.  When its description cannot be read the test fails loudly with
    install guidance, because the contract it checks cannot be proven without
    it.
    """

    pinned_endpoint = _require_installed(
        _INSTALLED_PINNED_ENDPOINT, "endpoint description"
    )

    for field in MIRRORED_ENDPOINT_FIELDS:
        assert FAKE_USER_VIDEO_PAGE_ENDPOINT[field] == pinned_endpoint[field], (
            f"the fake endpoint mirror drifted from the installed pin on {field!r}"
        )
    # ``dm`` is mirrored literally too: the pin's ``True`` is the very field
    # the adapter overrides, so the mirror must keep carrying it.
    assert FAKE_USER_VIDEO_PAGE_ENDPOINT["dm"] is True
    assert pinned_endpoint["dm"] is True
    # The parameter names the adapter forwards are the pin's own set.
    assert set(FAKE_USER_VIDEO_PAGE_ENDPOINT["params"]) == set(pinned_endpoint["params"])


def test_adapter_overrides_only_dm_of_the_installed_pinned_endpoint(
    bilibili_api_seam,
):
    """``dm`` is the only field the adapter changes on the pin's own shape.

    The mirror-parity test above proves the seam's description equals the
    installed pin's; this test scripts the seam with the pin's *own* values
    and runs the real adapter, so the issued request reproduces every transport
    field of the pinned distribution except ``dm``, which the
    risk-control-safe shape turns off.  Together they pin the shipped call
    shape to the distribution the adapter actually drives.
    """

    pinned_endpoint = _require_installed(
        _INSTALLED_PINNED_ENDPOINT, "endpoint description"
    )
    bilibili_api_seam.user_video_page_endpoint.update(pinned_endpoint)
    bilibili_api_seam.videos_response = make_videos_response(make_vlist_item(), count=1)
    gateway = _load_gateway()

    asyncio.run(gateway.get_user_video_page(MID, page_number=1))

    (request,) = bilibili_api_seam.api_requests
    for field in MIRRORED_ENDPOINT_FIELDS:
        assert getattr(request, field) == pinned_endpoint[field]
    assert pinned_endpoint["dm"] is True
    assert request.dm is False


def test_fake_request_settings_double_is_no_more_permissive_than_the_pin():
    """The seam keeps the pin's strict ``set_proxy``/``get_proxy`` shapes.

    ``bilibili_api.request_settings`` is the pinned package's process-global
    ``RequestSettings`` instance, whose ``set_proxy(self, proxy: str)`` has no
    default: a no-argument call raises ``TypeError`` against the real package.
    The seam mirrors it as a module-level function, so a default added there
    would let a no-argument call pass offline and fail live; the pin's own
    parameter shapes are compared instead.

    Offline and deterministic: the pinned distribution is read for its
    signatures only, and the fake is built directly (no seam fixture).
    """

    pinned_parameters = _require_installed(
        _INSTALLED_REQUEST_SETTINGS_PARAMETERS, "request-settings parameter shapes"
    )
    fake_settings = build_fake_package(FakeUpstreamScript())[
        "bilibili_api.request_settings"
    ]

    for name in ("set_proxy", "get_proxy"):
        mirrored_parameters = [
            (parameter.name, str(parameter.kind), parameter.default)
            for parameter in inspect.signature(
                getattr(fake_settings, name)
            ).parameters.values()
        ]
        assert mirrored_parameters == pinned_parameters[name], (
            f"the seam's {name} signature is more permissive than the pin's"
        )


# -------------------------------------------------------------- video parts


def test_get_video_parts_converts_page_index_and_duration(bilibili_api_seam):
    """One-based ``page`` and seconds become zero-based index and ms."""

    bilibili_api_seam.parts_response = [
        make_part_item(cid=2222, page=1, part="  第一部分  ", duration=12),
        make_part_item(cid=3333, page=3, part="第三部分", duration=10.5),
    ]
    gateway = _load_gateway()

    parts = asyncio.run(gateway.get_video_parts(BVID))

    assert parts == (
        VideoPart(bvid=BVID, page_index=0, cid=2222, title="第一部分", duration_ms=12000),
        VideoPart(bvid=BVID, page_index=2, cid=3333, title="第三部分", duration_ms=10500),
    )
    assert bilibili_api_seam.calls == ["video.get_pages"]


def test_get_video_parts_empty_list_returns_empty_tuple(bilibili_api_seam):
    """No pages means an empty tuple, not an error."""

    bilibili_api_seam.parts_response = []
    gateway = _load_gateway()

    assert asyncio.run(gateway.get_video_parts(BVID)) == ()


def test_get_video_parts_rejects_invalid_bvid_argument(bilibili_api_seam):
    """A malformed caller bvid raises ValueError without touching the API."""

    gateway = _load_gateway()

    for broken_bvid in ("", "   ", "BV123", "av12345678901", 12345):
        with pytest.raises(ValueError):
            asyncio.run(gateway.get_video_parts(broken_bvid))
    assert bilibili_api_seam.calls == []


def test_get_video_parts_tolerates_unknown_keys(bilibili_api_seam):
    """Unknown extra keys on a part item are ignored, not rejected."""

    bilibili_api_seam.parts_response = [make_part_item(dimension={"width": 1})]
    gateway = _load_gateway()

    parts = asyncio.run(gateway.get_video_parts(BVID))

    assert parts == (
        VideoPart(bvid=BVID, page_index=0, cid=2222, title="第一部分", duration_ms=12000),
    )


@pytest.mark.parametrize(
    "broken_item",
    [
        {},
        {"cid": 0, "page": 1, "part": "第一部分", "duration": 12},
        {"cid": "2222", "page": 1, "part": "第一部分", "duration": 12},
        {"cid": True, "page": 1, "part": "第一部分", "duration": 12},
        {"cid": 2222, "page": 0, "part": "第一部分", "duration": 12},
        {"cid": 2222, "page": "1", "part": "第一部分", "duration": 12},
        {"cid": 2222, "page": True, "part": "第一部分", "duration": 12},
        {"cid": 2222, "page": 1, "part": "  ", "duration": 12},
        {"cid": 2222, "page": 1, "part": 7, "duration": 12},
        {"cid": 2222, "page": 1, "part": "第一部分", "duration": 0},
        {"cid": 2222, "page": 1, "part": "第一部分", "duration": -3},
        {"cid": 2222, "page": 1, "part": "第一部分", "duration": "12"},
        {"cid": 2222, "page": 1, "part": "第一部分", "duration": True},
        [make_part_item()],
        "第一部分",
    ],
)
def test_get_video_parts_rejects_malformed_items(bilibili_api_seam, broken_item):
    """Every part scalar is validated before a DTO is returned."""

    bilibili_api_seam.parts_response = [broken_item]
    gateway = _load_gateway()

    with pytest.raises(GatewayShapeError):
        asyncio.run(gateway.get_video_parts(BVID))


def test_get_video_parts_rejects_non_list_response(bilibili_api_seam):
    """A pagelist response that is not an array is a shape error."""

    gateway = _load_gateway()
    for broken in (None, {"pages": []}, "ok"):
        bilibili_api_seam.parts_response = broken
        with pytest.raises(GatewayShapeError):
            asyncio.run(gateway.get_video_parts(BVID))


# ------------------------------------------------------------ error mapping


@pytest.mark.parametrize(
    ("upstream_error", "expected"),
    [
        (FakeNetworkException(412, UPSTREAM_ERROR_TEXT), GatewayRateLimited),
        (FakeNetworkException(429, UPSTREAM_ERROR_TEXT), GatewayRateLimited),
        (FakeNetworkException(404, UPSTREAM_ERROR_TEXT), GatewayNotFound),
        (FakeNetworkException(503, UPSTREAM_ERROR_TEXT), GatewayTransportError),
        (FakeResponseCodeException(-412, UPSTREAM_ERROR_TEXT), GatewayRateLimited),
        (FakeResponseCodeException(-352, UPSTREAM_ERROR_TEXT), GatewayRateLimited),
        (FakeResponseCodeException(-799, UPSTREAM_ERROR_TEXT), GatewayRateLimited),
        (FakeResponseCodeException(-404, UPSTREAM_ERROR_TEXT), GatewayNotFound),
        (FakeResponseCodeException(-62002, UPSTREAM_ERROR_TEXT), GatewayNotFound),
        (FakeResponseCodeException(-101, UPSTREAM_ERROR_TEXT), GatewayResponseError),
        (FakeResponseCodeException(-1, UPSTREAM_ERROR_TEXT), GatewayResponseError),
        (FakeResponseException(UPSTREAM_ERROR_TEXT), GatewayResponseError),
        (FakeWbiRetryTimesExceedException(), GatewayRateLimited),
        (RuntimeError(UPSTREAM_ERROR_TEXT), GatewayTransportError),
    ],
)
def test_user_page_failures_map_onto_bounded_taxonomy(
    bilibili_api_seam, upstream_error, expected
):
    """Upstream failures become one bounded gateway error with its class code."""

    bilibili_api_seam.videos_error = upstream_error
    gateway = _load_gateway()

    with pytest.raises(expected) as caught:
        asyncio.run(gateway.get_user_video_page(MID, page_number=1))

    assert caught.value.code == expected.default_code
    # Raw exception text and URLs stay process-local: never in the mapped error.
    assert UPSTREAM_ERROR_TEXT not in str(caught.value)


@pytest.mark.parametrize(
    ("upstream_error", "expected"),
    [
        (FakeNetworkException(412, UPSTREAM_ERROR_TEXT), GatewayRateLimited),
        (FakeResponseCodeException(-404, UPSTREAM_ERROR_TEXT), GatewayNotFound),
        (RuntimeError(UPSTREAM_ERROR_TEXT), GatewayTransportError),
    ],
)
def test_part_failures_map_onto_bounded_taxonomy(
    bilibili_api_seam, upstream_error, expected
):
    """The parts boundary maps upstream failures the same way."""

    bilibili_api_seam.parts_error = upstream_error
    gateway = _load_gateway()

    with pytest.raises(expected) as caught:
        asyncio.run(gateway.get_video_parts(BVID))

    assert caught.value.code == expected.default_code
    assert UPSTREAM_ERROR_TEXT not in str(caught.value)


@pytest.mark.parametrize(
    ("upstream_error", "expected"),
    [
        (FakeNetworkException(412, UPSTREAM_ERROR_TEXT), GatewayRateLimited),
        (FakeResponseCodeException(-404, UPSTREAM_ERROR_TEXT), GatewayNotFound),
        (RuntimeError(UPSTREAM_ERROR_TEXT), GatewayTransportError),
    ],
)
def test_completed_summary_failures_map_onto_bounded_taxonomy(
    bilibili_api_seam, upstream_error, expected
):
    """The get_info boundary maps upstream failures the same way."""

    bilibili_api_seam.info_error = upstream_error
    gateway = _load_gateway()

    with pytest.raises(expected) as caught:
        asyncio.run(gateway.get_completed_video_summary(_summary(aid=None)))

    assert caught.value.code == expected.default_code
    assert UPSTREAM_ERROR_TEXT not in str(caught.value)


def test_shape_failure_does_not_expose_credential(bilibili_api_seam):
    """A malformed response surfacing as a shape error stays credential-free."""

    bilibili_api_seam.videos_response = {"list": {"vlist": [{}]}, "page": {"count": 1}}
    gateway = _load_gateway(sessdata=SESSDATA_BOUNDARY_VALUE)

    with pytest.raises(GatewayShapeError) as caught:
        asyncio.run(gateway.get_user_video_page(MID, page_number=1))

    assert SESSDATA_BOUNDARY_VALUE not in str(caught.value)


# ------------------------------------------------ completed summary gap-filling


def test_completed_summary_short_circuits_when_aid_present(bilibili_api_seam):
    """A summary that already carries aid is returned without any call."""

    gateway = _load_gateway()
    summary = _summary(aid=111)

    completed = asyncio.run(gateway.get_completed_video_summary(summary))

    assert completed is summary
    assert bilibili_api_seam.calls == []


def test_completed_summary_fills_only_missing_aid(bilibili_api_seam):
    """A missing aid is filled from get_info; other fields are preserved."""

    bilibili_api_seam.info_response = make_detail_response()
    gateway = _load_gateway()
    summary = _summary(aid=None)

    completed = asyncio.run(gateway.get_completed_video_summary(summary))

    assert completed is not summary
    assert completed.aid == 111
    assert completed.bvid == summary.bvid
    assert completed.title == summary.title
    assert completed.pubdate == summary.pubdate
    assert completed.mid == summary.mid
    assert bilibili_api_seam.calls == ["video.get_info"]


def test_completed_summary_rejects_foreign_detail_owner(bilibili_api_seam):
    """A detail response owned by another user is a bounded shape error."""

    bilibili_api_seam.info_response = make_detail_response(owner={"mid": MID + 1, "name": "别人"})
    gateway = _load_gateway()

    with pytest.raises(GatewayShapeError) as caught:
        asyncio.run(gateway.get_completed_video_summary(_summary(aid=None)))

    assert caught.value.code == "shape_error"


def test_completed_summary_rejects_detail_for_another_video(bilibili_api_seam):
    """A detail naming a different video cannot fill this summary's aid.

    The filled aid must provably belong to the video the summary names, so
    a detail body for another video is a bounded shape error.
    """

    bilibili_api_seam.info_response = make_detail_response(bvid="BV1OTHERVID")
    gateway = _load_gateway()

    with pytest.raises(GatewayShapeError) as caught:
        asyncio.run(gateway.get_completed_video_summary(_summary(aid=None)))

    assert caught.value.code == "shape_error"
    assert "bvid" in str(caught.value)
    assert bilibili_api_seam.calls == ["video.get_info"]


def test_completed_summary_rejects_detail_without_aid(bilibili_api_seam):
    """A detail response that still lacks aid cannot complete the summary."""

    bilibili_api_seam.info_response = {"bvid": BVID, "owner": {"mid": MID}}
    gateway = _load_gateway()

    with pytest.raises(GatewayShapeError):
        asyncio.run(gateway.get_completed_video_summary(_summary(aid=None)))


def test_completed_summary_rejects_non_mapping_detail(bilibili_api_seam):
    """A non-dictionary detail response is a shape error."""

    bilibili_api_seam.info_response = "ok"
    gateway = _load_gateway()

    with pytest.raises(GatewayShapeError):
        asyncio.run(gateway.get_completed_video_summary(_summary(aid=None)))


# ------------------------------------------------------------ package version


def test_package_version_falls_back_to_pinned_literal(bilibili_api_seam):
    """Without the installed distribution the pinned literal is returned."""

    gateway = _load_gateway()

    assert gateway.get_package_version() == PINNED_PACKAGE_VERSION


def test_package_version_reports_installed_distribution(bilibili_api_seam, monkeypatch):
    """When the distribution is installed its version wins over the literal.

    The mocked installed version differs from the pinned literal, so a pass
    proves the installed-distribution path, not the fallback constant.
    """

    monkeypatch.setattr(
        importlib.metadata, "version", lambda _name: "9.9.9", raising=True
    )
    gateway = _load_gateway()

    assert gateway.get_package_version() == "9.9.9"


# ------------------------------------------------------- runtime HTTP backend


def test_http_backend_declared_and_absent_from_pinned_package_requirements():
    """The declared HTTP backend cannot arrive transitively from the pin.

    ``bilibili-api-python==17.4.2`` publishes no HTTP client in
    ``Requires-Dist`` and no extra carrying one, yet every request raises
    ``ArgsException("尚未安装第三方请求库或未注册自定义第三方请求库")`` until
    ``curl_cffi``, ``httpx``, or ``aiohttp`` is installed.  The pin is
    spec-locked, so no version bump can supply the transport: the
    application must declare the backend itself, and a fresh install without
    that declaration can never reach the network.  This test fails if the
    declaration is dropped, and the installed distribution's own metadata is
    what proves the dependency is load-bearing rather than transitive.

    The installed distribution is asserted to *be* the pin before its
    requirements are read, so a drifted environment fails loudly here instead
    of silently drawing the conclusion from another release.

    Offline and deterministic: it reads this checkout's ``pyproject.toml``
    and the installed distributions' metadata only.
    """

    project_root = pathlib.Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads(
        (project_root / "pyproject.toml").read_text(encoding="utf-8")
    )
    declared_names = {
        canonicalize_name(Requirement(raw).name)
        for raw in pyproject["project"]["dependencies"]
    }
    assert HTTP_BACKEND_CANONICAL_NAME in declared_names, (
        "the runtime HTTP backend must stay declared in"
        f" [project].dependencies ({HTTP_BACKEND_CANONICAL_NAME} missing)"
    )

    try:
        pinned_distribution = importlib.metadata.distribution(
            PINNED_PACKAGE_DISTRIBUTION_NAME
        )
    except importlib.metadata.PackageNotFoundError as error:
        pytest.fail(
            "the packaging contract needs the pinned distribution installed to"
            f" read its Requires-Dist ({error}); run uv sync first"
        )

    assert pinned_distribution.version == PINNED_PACKAGE_VERSION, (
        "the installed distribution is not the pin this contract is about"
        f" ({pinned_distribution.version!r} != {PINNED_PACKAGE_VERSION!r});"
        " install the pinned release (uv sync) before re-reading Requires-Dist"
    )

    upstream_names = {
        canonicalize_name(Requirement(raw).name)
        for raw in pinned_distribution.requires or ()
    }
    transitive_clients = upstream_names & PACKAGE_HTTP_CLIENT_CANONICAL_NAMES
    assert not transitive_clients, (
        f"the pinned package now declares an HTTP client ({sorted(transitive_clients)});"
        " re-check whether the explicit backend declaration and the rationale"
        " above still hold"
    )


# --------------------------------------------- proxy resolution and application


@pytest.fixture
def empty_proxy_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every proxy variable the adapter consults, ambient ones included."""

    for name in PROXY_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("env_var", PROXY_ENV_VARS)
def test_resolve_proxy_reads_every_locked_environment_level(env_var):
    """Each variable of the locked chain resolves on its own."""

    assert resolve_proxy(None, {env_var: PROXY_BOUNDARY_VALUE}) == PROXY_BOUNDARY_VALUE


def test_resolve_proxy_follows_the_locked_precedence_ladder():
    """The first set variable wins, proven level by level down the chain."""

    environment = {
        name: f"http://{index}.example.com:7890"
        for index, name in enumerate(PROXY_ENV_VARS)
    }

    for higher_levels_cleared, expected_name in enumerate(PROXY_ENV_VARS):
        remaining = {
            name: value
            for name, value in environment.items()
            if PROXY_ENV_VARS.index(name) >= higher_levels_cleared
        }
        assert resolve_proxy(None, remaining) == environment[expected_name]


def test_resolve_proxy_argument_outranks_the_whole_environment_chain():
    """An explicit argument wins over every environment level."""

    environment = {name: PROXY_BOUNDARY_VALUE for name in PROXY_ENV_VARS}

    assert resolve_proxy("http://argument.example.com:7890", environment) == (
        "http://argument.example.com:7890"
    )


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_resolve_proxy_blank_values_are_unset_and_never_block_lower_levels(blank):
    """A blank or whitespace-only value resolves nothing and shadows nothing."""

    environment = {PROXY_ENV_VAR: blank, "HTTPS_PROXY": PROXY_BOUNDARY_VALUE}

    assert resolve_proxy(blank, {PROXY_ENV_VAR: blank}) is None
    assert resolve_proxy(blank, environment) == PROXY_BOUNDARY_VALUE


def test_resolve_proxy_strips_surrounding_whitespace():
    """A configured value is used without the whitespace around it."""

    assert resolve_proxy(f"  {PROXY_BOUNDARY_VALUE}  ", {}) == PROXY_BOUNDARY_VALUE
    assert (
        resolve_proxy(None, {"ALL_PROXY": f"\t{PROXY_BOUNDARY_VALUE}\n"})
        == PROXY_BOUNDARY_VALUE
    )


def test_resolve_proxy_without_any_setting_resolves_to_none():
    """Nothing configured means no proxy; only the locked chain is consulted."""

    assert resolve_proxy(None, {}) is None
    # ``HTTP_PROXY`` is deliberately not part of the locked chain: the two
    # upstream endpoints this adapter calls are HTTPS.
    assert resolve_proxy(None, {"HTTP_PROXY": PROXY_BOUNDARY_VALUE}) is None


def test_gateway_applies_the_resolved_proxy_once_before_the_first_call(
    bilibili_api_seam, empty_proxy_environment
):
    """The proxy reaches the package settings exactly once, at construction."""

    bilibili_api_seam.videos_response = make_videos_response(make_vlist_item(), count=1)
    gateway = _load_gateway(proxy=PROXY_BOUNDARY_VALUE)

    assert gateway.resolved_proxy == PROXY_BOUNDARY_VALUE
    assert bilibili_api_seam.applied_proxies == [PROXY_BOUNDARY_VALUE]
    assert bilibili_api_seam.calls == []

    asyncio.run(gateway.get_user_video_page(MID, page_number=1))

    assert bilibili_api_seam.calls == ["space.arc.search(pn=1, ps=30)"]
    # Apply-once: no request re-applies or re-reads the setting.
    assert bilibili_api_seam.applied_proxies == [PROXY_BOUNDARY_VALUE]


def test_gateway_resolves_the_proxy_from_the_environment_without_an_argument(
    bilibili_api_seam, empty_proxy_environment, monkeypatch
):
    """Without an argument the documented operator knob is applied."""

    monkeypatch.setenv(PROXY_ENV_VAR, PROXY_BOUNDARY_VALUE)
    gateway = _load_gateway()

    assert gateway.resolved_proxy == PROXY_BOUNDARY_VALUE
    assert bilibili_api_seam.applied_proxies == [PROXY_BOUNDARY_VALUE]


def test_gateway_argument_outranks_the_environment(
    bilibili_api_seam, empty_proxy_environment, monkeypatch
):
    """An explicit argument wins over the whole environment chain."""

    monkeypatch.setenv(PROXY_ENV_VAR, "http://environment.example.com:7890")
    monkeypatch.setenv("HTTPS_PROXY", "http://fallback.example.com:7890")
    gateway = _load_gateway(proxy=PROXY_BOUNDARY_VALUE)

    assert gateway.resolved_proxy == PROXY_BOUNDARY_VALUE
    assert bilibili_api_seam.applied_proxies == [PROXY_BOUNDARY_VALUE]


def test_gateway_skips_a_blank_environment_value(
    bilibili_api_seam, empty_proxy_environment, monkeypatch
):
    """A blank BILI_HTTP_PROXY falls through to the standard host variable."""

    monkeypatch.setenv(PROXY_ENV_VAR, "   ")
    monkeypatch.setenv("HTTPS_PROXY", PROXY_BOUNDARY_VALUE)
    gateway = _load_gateway()

    assert gateway.resolved_proxy == PROXY_BOUNDARY_VALUE
    assert bilibili_api_seam.applied_proxies == [PROXY_BOUNDARY_VALUE]


def test_gateway_leaves_the_package_setting_untouched_without_a_proxy(
    bilibili_api_seam, empty_proxy_environment
):
    """Nothing resolved means no call into the package's request settings."""

    bilibili_api_seam.videos_response = make_videos_response(make_vlist_item(), count=1)
    gateway = _load_gateway()

    assert gateway.resolved_proxy is None
    assert bilibili_api_seam.applied_proxies == []

    asyncio.run(gateway.get_user_video_page(MID, page_number=1))

    assert bilibili_api_seam.calls == ["space.arc.search(pn=1, ps=30)"]
    assert bilibili_api_seam.applied_proxies == []


def test_gateway_proxy_stays_out_of_dtos_and_mapped_errors(
    bilibili_api_seam, empty_proxy_environment
):
    """The resolved proxy never surfaces on a DTO or a mapped error."""

    bilibili_api_seam.videos_response = make_videos_response(make_vlist_item(), count=1)
    gateway = _load_gateway(
        sessdata=SESSDATA_BOUNDARY_VALUE, proxy=PROXY_BOUNDARY_VALUE
    )

    page = asyncio.run(gateway.get_user_video_page(MID, page_number=1))
    for surface in (repr(page), str(page)):
        assert PROXY_BOUNDARY_VALUE not in surface
        assert SESSDATA_BOUNDARY_VALUE not in surface
    # A debug render of the adapter must not dump its configuration either.
    assert PROXY_BOUNDARY_VALUE not in repr(gateway)
    assert SESSDATA_BOUNDARY_VALUE not in repr(gateway)

    bilibili_api_seam.videos_error = FakeNetworkException(503, UPSTREAM_ERROR_TEXT)
    with pytest.raises(GatewayTransportError) as caught:
        asyncio.run(gateway.get_user_video_page(MID, page_number=2))

    assert PROXY_BOUNDARY_VALUE not in str(caught.value)
    assert PROXY_BOUNDARY_VALUE not in repr(caught.value)


def test_gateway_proxy_stays_out_of_persisted_rows(
    bilibili_api_seam, empty_proxy_environment, tmp_root
):
    """A full collection run persists no proxy value and no credential."""

    bilibili_api_seam.videos_response = make_videos_response(
        make_vlist_item(aid=None, sessdata_note=SESSDATA_BOUNDARY_VALUE), count=1
    )
    bilibili_api_seam.info_response = make_detail_response()
    bilibili_api_seam.parts_response = [make_part_item()]
    gateway = _load_gateway(
        sessdata=SESSDATA_BOUNDARY_VALUE, proxy=PROXY_BOUNDARY_VALUE
    )
    connection = open_database(os.path.join(tmp_root, "proxy-hygiene.sqlite"))
    try:
        repository = MetadataRepository(connection)
        result = MetadataIngestor(gateway, repository).collect_user_pages(
            MID, start_page=1, page_limit=1
        )

        assert result.outcome == "limited"
        assert repository.list_pending_parts()
        persisted = persisted_row_text(connection)
    finally:
        connection.close()

    assert_leaks_no_markers(persisted, context="persisted rows")
    assert PROXY_BOUNDARY_VALUE not in persisted
    assert SESSDATA_BOUNDARY_VALUE not in persisted
    for surface in (repr(result), str(result)):
        assert PROXY_BOUNDARY_VALUE not in surface
        assert SESSDATA_BOUNDARY_VALUE not in surface


# ------------------------------------------------------- DTO self-validation


@pytest.mark.parametrize(
    "broken_kwargs",
    [
        {"bvid": ""},
        {"bvid": "   "},
        {"title": "  "},
        {"title": 5},
        {"aid": 0},
        {"aid": True},
        {"pubdate": -1},
        {"mid": 0},
    ],
)
def test_video_summary_rejects_invalid_fields(broken_kwargs):
    """The DTO itself enforces non-empty bvid/title and scalar ranges."""

    values = {"bvid": BVID, "aid": None, "title": "未明子讲座", "pubdate": PUBDATE, "mid": MID}
    values.update(broken_kwargs)

    with pytest.raises((TypeError, ValueError)):
        VideoSummary(**values)


def test_video_summary_accepts_missing_aid():
    """A summary without aid is valid: the field is nullable."""

    summary = _summary(aid=None)

    assert summary.aid is None


@pytest.mark.parametrize(
    "broken_kwargs",
    [
        {"page_index": -1},
        {"cid": 0},
        {"cid": True},
        {"title": " "},
        {"duration_ms": 0},
        {"bvid": ""},
    ],
)
def test_video_part_rejects_invalid_fields(broken_kwargs):
    """The DTO enforces non-negative index and positive cid/duration."""

    values = {
        "bvid": BVID,
        "page_index": 0,
        "cid": 2222,
        "title": "第一部分",
        "duration_ms": 12000,
    }
    values.update(broken_kwargs)

    with pytest.raises((TypeError, ValueError)):
        VideoPart(**values)


@pytest.mark.parametrize(
    "broken_kwargs",
    [
        {"mid": 0},
        {"page_number": 0},
        {"observed_total": -1},
        {"videos": [1, 2]},
    ],
)
def test_user_video_page_rejects_invalid_fields(broken_kwargs):
    """The page DTO enforces one-based numbering and summary members."""

    values = {
        "mid": MID,
        "page_number": 1,
        "videos": (_summary(aid=111),),
        "observed_total": 2,
    }
    values.update(broken_kwargs)

    with pytest.raises((TypeError, ValueError)):
        UserVideoPage(**values)


# -------------------------------------------------- subtitle DTO validation


def _track(**overrides: object) -> SubtitleTrack:
    """Build one validated subtitle-track DTO (an uploader/CC track)."""

    values: dict[str, object] = {
        "language": "zh-CN",
        "label": "中文（中国）",
        "is_ai": False,
        "track_id": "track-1",
    }
    values.update(overrides)
    return SubtitleTrack(**values)


def _segment(**overrides: object) -> SubtitleSegment:
    """Build one validated subtitle-segment DTO."""

    values: dict[str, object] = {"start_ms": 0, "end_ms": 1500, "text": "未明子"}
    values.update(overrides)
    return SubtitleSegment(**values)


def test_subtitle_dtos_carry_no_work_id_and_no_url_field():
    """The locked field sets: no storage identity and no URL in either DTO.

    A signed ``subtitle_url`` lives for the duration of one call and a part's
    storage identity never belongs to the gateway, so both DTOs must stay
    incapable of carrying either — the field sets are pinned exactly.
    """

    assert [field.name for field in dataclasses.fields(SubtitleTrack)] == [
        "language",
        "label",
        "is_ai",
        "track_id",
    ]
    assert [field.name for field in dataclasses.fields(SubtitleSegment)] == [
        "start_ms",
        "end_ms",
        "text",
    ]


@pytest.mark.parametrize(
    "broken_kwargs",
    [
        {"language": ""},
        {"language": "   "},
        {"language": 5},
        # The service derives the language family from the primary subtag, so a
        # vocabulary it cannot rank (`-zh`) is rejected, not silently kept.
        {"language": "-zh"},
        {"language": "  -zh"},
        {"label": ""},
        {"label": "   "},
        {"label": None},
        # The label is printed verbatim on the CLI's one-line-per-track shape, so
        # a value carrying a control character is rejected here (F-003) exactly as
        # the storage contract rejects one on every text field it holds.
        {"label": "中文\n伪造第二行"},
        {"label": "中文\r"},
        {"label": "中文\x00"},
        {"language": "zh-CN\n"},
        {"language": "zh-CN\r"},
        {"language": "zh-CN\x00"},
        {"track_id": "track\n1"},
        {"track_id": "track\x001"},
        {"is_ai": "ai"},
        {"is_ai": 1},
        {"is_ai": None},
        {"track_id": ""},
        {"track_id": "   "},
        {"track_id": 7},
    ],
)
def test_subtitle_track_rejects_invalid_fields(broken_kwargs):
    """The track DTO enforces printable scalars and the primary-subtag rule."""

    with pytest.raises((TypeError, ValueError)):
        _track(**broken_kwargs)


def test_subtitle_track_accepts_a_missing_track_id():
    """A track upstream did not identify is valid: ``track_id`` is nullable."""

    assert _track(track_id=None).track_id is None


def test_subtitle_track_accepts_a_region_or_script_subtag():
    """A language with a region/script subtag keeps that subtag intact."""

    assert _track(language="zh-Hans").language == "zh-Hans"


@pytest.mark.parametrize(
    "broken_kwargs",
    [
        {"start_ms": -1},
        {"start_ms": True},
        {"start_ms": "0"},
        {"start_ms": None},
        {"end_ms": 0},
        {"end_ms": -5},
        {"end_ms": True},
        {"end_ms": "1500"},
        {"start_ms": 1500, "end_ms": 1500},
        {"start_ms": 1500, "end_ms": 500},
        {"text": ""},
        {"text": "   "},
        {"text": 7},
    ],
)
def test_subtitle_segment_rejects_invalid_fields(broken_kwargs):
    """The segment DTO enforces ``end_ms > start_ms >= 0`` and non-empty text."""

    with pytest.raises((TypeError, ValueError)):
        _segment(**broken_kwargs)


def test_subtitle_dtos_are_frozen():
    """Both DTOs are immutable: a normalized result cannot be edited in place."""

    for subtitle_dto, field_name in ((_track(), "label"), (_segment(), "text")):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(subtitle_dto, field_name, "changed")


# ---------------------------------------------------- gateway protocol surface


def test_gateway_protocol_surface_is_locked():
    """The protocol declares exactly the locked six methods, signatures included.

    The four shipped signatures stay untouched — the shipped metadata service
    and the storage plan consume them — and the two subtitle methods are
    exactly the locked pair: ``get_subtitle_tracks(bvid, cid)`` answers a
    possibly empty tuple (an empty inventory is an observation, never a
    ``not_found`` failure), while ``fetch_subtitle_segments(track, bvid, cid)``
    answers a non-empty tuple or raises ``GatewayNotFound``.

    The declaration set is asserted exactly, not method by method: a seventh
    protocol method fails here instead of slipping through unread.
    """

    expected = {
        "get_user_video_page": ("self", "mid", "page_number", "page_size"),
        "get_video_parts": ("self", "bvid"),
        "get_completed_video_summary": ("self", "summary"),
        "get_package_version": ("self",),
        "get_subtitle_tracks": ("self", "bvid", "cid"),
        "fetch_subtitle_segments": ("self", "track", "bvid", "cid"),
    }

    declared = {
        name: tuple(inspect.signature(member).parameters)
        for name, member in vars(BilibiliGateway).items()
        if not name.startswith("_")
    }

    assert declared == expected


# ------------------------------------------------------- import boundary (AST)


def _package_source_files() -> list[pathlib.Path]:
    root = pathlib.Path(__file__).resolve().parent.parent / "src" / "bili_asr"
    return sorted(path for path in root.rglob("*.py"))


def _bilibili_api_usage(tree: ast.AST) -> bool:
    """Return True when the tree imports bilibili_api at all."""

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("bilibili_api"):
                return True
        elif isinstance(node, ast.Import):
            if any(alias.name.startswith("bilibili_api") for alias in node.names):
                return True
    return False


def test_only_the_gateway_module_imports_bilibili_api():
    """No module other than the adapter may import bilibili_api."""

    offenders = [
        path.name
        for path in _package_source_files()
        if _bilibili_api_usage(ast.parse(path.read_text(encoding="utf-8")))
    ]

    assert offenders == ["bilibili_api_gateway.py"]


def test_gateway_imports_stay_on_metadata_surface():
    """The adapter imports exactly the enforced allow-list, nothing broader.

    ``ALLOWED_PACKAGE_IMPORTS`` is compared exactly: ``Credential`` and the
    ``request_settings``/``user`` modules from the package root, the WBI-signed
    ``utils.network.Api``, the two ``video`` names the adapter uses (``API``,
    bound locally as ``VIDEO_API`` so it cannot be confused with ``Api``, and
    ``Video``), and the five exception names.  The page call reads
    ``user.API["info"]["video"]`` and the subtitle call reads the player
    endpoint description from the same surface, so ``utils.network.Api`` stays
    the one request path.  ``User`` is not an allow-listed name of its own,
    because the ``user`` module is bound whole: the adapter reaches the class
    through it (``user.User(uid=mid, credential=self._credential)``, whose
    ``get_access_id()`` serves the optional ``w_webid`` token route — the
    attribute the next test's positive control requires the scanned source to
    carry).  That
    module-wide binding — every other endpoint description reachable through
    ``user.get_api`` included — is residual R1, deferred to the next plan that
    touches this module.  The page call itself still goes through the ``user``
    module's endpoint description and the package ``Api``, never through that
    delegate.
    """

    gateway_path = (
        pathlib.Path(__file__).resolve().parent.parent
        / "src"
        / "bili_asr"
        / "sources"
        / "bilibili_api_gateway.py"
    )
    tree = ast.parse(gateway_path.read_text(encoding="utf-8"))

    imports: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("bilibili_api"):
            imports.setdefault(node.module, set()).update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("bilibili_api"):
                    imports.setdefault(alias.name, set()).add(alias.name)

    assert imports == ALLOWED_PACKAGE_IMPORTS


def test_gateway_source_never_names_forbidden_seam_methods():
    """The adapter source stays off every surface outside this plan's boundary.

    ``FORBIDDEN_SEAM_METHOD_TOKENS`` carries the media/playback family only:
    the authorized subtitle-acquisition tokens are ``subtitle`` and ``player``
    (``download`` is forbidden again, because this iteration acquires no
    media).  The second positive control below asserts that family's own
    attributes are present *and* that they still carry an allowed token:
    re-forbidding the removal fails there instead of letting the scan pass
    because the adapter has no subtitle code to see.
    """

    gateway_path = (
        pathlib.Path(__file__).resolve().parent.parent
        / "src"
        / "bili_asr"
        / "sources"
        / "bilibili_api_gateway.py"
    )
    tree = ast.parse(gateway_path.read_text(encoding="utf-8"))
    attribute_names = {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }

    forbidden_hits = sorted(
        name
        for name in attribute_names
        for token in FORBIDDEN_SEAM_METHOD_TOKENS
        if token in name.lower()
    )

    assert forbidden_hits == []
    # Positive control: the scan sees the documented metadata attribute calls.
    assert {"get_access_id", "update_params", "get_pages", "get_info"} <= (
        attribute_names
    )
    # Second positive control: the authorized subtitle surface is present, and
    # every asserted name is one the removed tokens would have flagged.
    assert set(AUTHORIZED_SUBTITLE_ATTRIBUTES) <= attribute_names
    for name in AUTHORIZED_SUBTITLE_ATTRIBUTES:
        assert any(token in name.lower() for token in AUTHORIZED_SEAM_METHOD_TOKENS), (
            f"{name!r} does not carry a removed token, so it cannot prove the"
            " authorized removal is load-bearing"
        )


def test_fake_seam_exposes_only_documented_metadata_surface():
    """The offline seam exposes exactly the documented metadata methods."""

    modules = build_fake_package(FakeUpstreamScript())
    package = modules["bilibili_api"]

    assert _public_names(modules["bilibili_api.user"]) == ["API", "User", "VideoOrder"]
    assert _public_names(modules["bilibili_api.video"]) == ["API", "Video"]
    assert _public_names(modules["bilibili_api.utils.network"]) == ["Api"]
    assert _public_names(modules["bilibili_api.exceptions"]) == sorted(
        ALLOWED_EXCEPTION_NAMES
    )
    assert _public_names(modules["bilibili_api.request_settings"]) == [
        "get_proxy",
        "set_proxy",
    ]
    assert _public_names(package) == [
        "Credential",
        "exceptions",
        "request_settings",
        "user",
        "video",
    ]
    assert _public_names(package.Credential) == []

    user = package.user.User(uid=MID)
    video = package.video.Video(bvid=BVID)
    for surface_name in (
        "get_subtitles",
        "get_subtitle",
        "get_play_url",
        "get_player_info",
        "get_download_url",
        "get_danmaku",
        "download",
        "get_audio",
    ):
        with pytest.raises(AttributeError):
            getattr(user, surface_name)
        with pytest.raises(AttributeError):
            getattr(video, surface_name)
    # The page delegate the risk-control-safe shape replaces is gone, so a
    # regression to it fails loudly instead of passing through the seam.
    with pytest.raises(AttributeError):
        user.get_videos


def test_gateway_dto_drops_unknown_upstream_payload_fields(bilibili_api_seam):
    """Unknown payload keys never surface on any gateway DTO string form."""

    bilibili_api_seam.videos_response = make_videos_response(
        make_vlist_item(
            aid=None,
            sessdata_note=SESSDATA_BOUNDARY_VALUE,
            frame_url=SIGNED_URL_MARKER,
            raw_note=RAW_JSON_BODY_MARKER,
        ),
        count=1,
    )
    bilibili_api_seam.parts_response = [make_part_item(player_note=SIGNED_URL_MARKER)]
    bilibili_api_seam.info_response = make_detail_response(raw_body=RAW_JSON_BODY_MARKER)
    gateway = _load_gateway(sessdata=SESSDATA_BOUNDARY_VALUE)

    page = asyncio.run(gateway.get_user_video_page(MID, page_number=1))
    completed = asyncio.run(gateway.get_completed_video_summary(page.videos[0]))
    parts = asyncio.run(gateway.get_video_parts(BVID))

    assert completed.aid == 111  # the get_info completion path ran
    for surface in (page, completed, parts):
        assert_leaks_no_markers(repr(surface), context="gateway DTO repr")
        assert_leaks_no_markers(str(surface), context="gateway DTO str")
    assert bilibili_api_seam.calls == [
        "space.arc.search(pn=1, ps=30)",
        "video.get_info",
        "video.get_pages",
    ]


# ---------------------------------------------------- subtitle seam scripting


def _seam_transport(script: FakeUpstreamScript):
    """Return the seam's ``Api`` mirror and ``Credential`` double for a script."""

    modules = build_fake_package(script)
    return modules["bilibili_api.utils.network"].Api, modules["bilibili_api"].Credential


def test_fake_seam_mirrors_the_player_endpoint_description():
    """The fake declares the player description where the pin declares it."""

    script = FakeUpstreamScript()
    modules = build_fake_package(script)

    assert modules["bilibili_api.video"].API == {
        "info": {"get_player_info": FAKE_PLAYER_ENDPOINT}
    }
    # The description is the script's own object, so a test can rewrite it
    # before the adapter module is imported against the seam.
    assert (
        modules["bilibili_api.video"].API["info"]["get_player_info"]
        is script.player_endpoint
    )


def test_fake_player_call_records_its_flags_and_parameter_set():
    """A player call is answered with the scripted payload and fully recorded."""

    script = FakeUpstreamScript()
    Api, Credential = _seam_transport(script)
    script.player_response = make_player_response(make_subtitle_track())

    document = asyncio.run(
        Api(
            url=FAKE_PLAYER_ENDPOINT["url"],
            method=FAKE_PLAYER_ENDPOINT["method"],
            verify=False,
            wbi=FAKE_PLAYER_ENDPOINT["wbi"],
            dm=False,
            credential=Credential(sessdata=SESSDATA_BOUNDARY_VALUE),
        )
        .update_params(
            bvid=BVID, cid=PART_CID, isGaiaAvoided=False, web_location=1315873
        )
        .result
    )

    assert document == make_player_response(make_subtitle_track())
    (request,) = script.api_requests
    assert (request.url, request.method, request.wbi, request.verify, request.dm) == (
        FAKE_PLAYER_ENDPOINT["url"],
        "GET",
        True,
        False,
        False,
    )
    assert request.params == {
        "bvid": BVID,
        "cid": PART_CID,
        "isGaiaAvoided": False,
        "web_location": 1315873,
    }
    # The API-host call carries the credential; the record keeps its presence
    # only, never the value.
    assert request.has_sessdata is True
    assert SESSDATA_BOUNDARY_VALUE not in repr(request)
    assert script.calls == [f"player.track_list(bvid={BVID}, cid={PART_CID})"]


def test_fake_player_call_follows_a_changed_package_endpoint():
    """No player transport field is hard-coded: the description decides."""

    script = FakeUpstreamScript()
    Api, Credential = _seam_transport(script)
    script.player_endpoint["url"] = CHANGED_PLAYER_ENDPOINT_URL
    script.player_response = make_player_response()

    asyncio.run(
        Api(
            url=CHANGED_PLAYER_ENDPOINT_URL,
            method="GET",
            verify=False,
            wbi=True,
            dm=False,
            credential=Credential(),
        )
        .update_params(bvid=BVID, cid=PART_CID)
        .result
    )

    (request,) = script.api_requests
    assert request.url == CHANGED_PLAYER_ENDPOINT_URL
    assert script.calls == [f"player.track_list(bvid={BVID}, cid={PART_CID})"]


def test_fake_player_call_adds_the_fingerprint_parameters_when_dm_is_on():
    """With ``dm`` on, the seam injects the parameters the pin would add.

    The risk-control assertion is only meaningful while this double can add
    the ``dm_*`` parameters a ``dm=True`` call carries upstream.
    """

    script = FakeUpstreamScript()
    Api, Credential = _seam_transport(script)
    script.player_response = make_player_response()

    asyncio.run(
        Api(
            url=FAKE_PLAYER_ENDPOINT["url"],
            method="GET",
            verify=False,
            wbi=True,
            dm=True,
            credential=Credential(),
        )
        .update_params(bvid=BVID, cid=PART_CID)
        .result
    )

    (request,) = script.api_requests
    assert request.dm is True
    assert sorted(key for key in request.params if key.startswith("dm_")) == [
        "dm_cover_img_str",
        "dm_img_inter",
        "dm_img_list",
        "dm_img_str",
    ]


def test_fake_subtitle_document_call_answers_a_scripted_body():
    """A signed-document fetch is answered with the scripted document and recorded."""

    script = FakeUpstreamScript()
    Api, Credential = _seam_transport(script)
    script.subtitle_bodies = {
        SIGNED_SUBTITLE_URL_MARKER: make_subtitle_document(make_subtitle_entry())
    }

    document = asyncio.run(
        Api(
            url=SIGNED_SUBTITLE_URL_MARKER,
            method="GET",
            verify=False,
            wbi=False,
            dm=False,
            credential=Credential(),
        ).request(raw=True)
    )

    assert document == make_subtitle_document(make_subtitle_entry())
    (request,) = script.api_requests
    assert request.url == SIGNED_SUBTITLE_URL_MARKER
    assert request.raw is True
    assert request.params == {}
    # The empty credential keeps SESSDATA off the CDN host; the seam records
    # that fact without ever comparing credential values.
    assert request.has_sessdata is False
    assert script.calls == ["subtitle.body"]


def test_fake_subtitle_document_call_scripts_a_transport_failure():
    """A scripted document failure is raised as scripted, after being recorded."""

    script = FakeUpstreamScript()
    Api, Credential = _seam_transport(script)
    script.subtitle_bodies = {
        SIGNED_SUBTITLE_URL_MARKER: FakeNetworkException(404, UPSTREAM_ERROR_TEXT)
    }

    with pytest.raises(FakeNetworkException):
        asyncio.run(
            Api(
                url=SIGNED_SUBTITLE_URL_MARKER,
                method="GET",
                verify=False,
                wbi=False,
                dm=False,
                credential=Credential(),
            ).request(raw=True)
        )

    assert script.calls == ["subtitle.body"]


def test_fake_subtitle_document_call_rejects_an_unscripted_url():
    """An unscripted document URL fails loudly instead of answering ``None``.

    The protocol-relative form is a different URL from the absolute one the
    seam scripts, so an adapter that forgot to normalize it fails here instead
    of fetching an unscripted location.
    """

    assert PROTOCOL_RELATIVE_SUBTITLE_URL.startswith("//")
    assert PROTOCOL_RELATIVE_SUBTITLE_URL.removeprefix("//") == (
        SIGNED_SUBTITLE_URL_MARKER.removeprefix("https://")
    )

    script = FakeUpstreamScript()
    Api, Credential = _seam_transport(script)
    script.subtitle_bodies = {SIGNED_SUBTITLE_URL_MARKER: make_subtitle_document()}

    with pytest.raises(AssertionError, match="unexpected subtitle-document fetch"):
        asyncio.run(
            Api(
                url=PROTOCOL_RELATIVE_SUBTITLE_URL,
                method="GET",
                verify=False,
                wbi=False,
                dm=False,
                credential=Credential(),
            ).request(raw=True)
        )


def test_fake_api_mirrors_the_pins_raw_request_argument():
    """The seam answers a document only when the call asks for the raw body.

    In the pin ``raw`` is a request argument, not a constructor field, and it
    decides whether the ``data``/``result`` envelope is unwrapped: the scripted
    metadata payloads are the unwrapped form, while a subtitle document has no
    envelope at all.
    """

    script = FakeUpstreamScript()
    Api, Credential = _seam_transport(script)

    page_call = Api(
        url=FAKE_USER_VIDEO_PAGE_ENDPOINT["url"],
        method="GET",
        verify=False,
        wbi=True,
        dm=False,
        credential=Credential(),
    )
    with pytest.raises(AssertionError, match="unwrapped payload"):
        asyncio.run(page_call.request(raw=True))

    document_call = Api(
        url=SIGNED_SUBTITLE_URL_MARKER,
        method="GET",
        verify=False,
        wbi=False,
        dm=False,
        credential=Credential(),
    )
    with pytest.raises(FakeResponseCodeException):
        asyncio.run(document_call.request(raw=False))


def test_fake_api_double_is_no_more_permissive_than_the_pin():
    """The seam accepts no call shape the pinned ``Api`` would reject.

    ``raw``/``byte`` are ``request`` arguments in the pin; a double that took
    them at construction would let such a call pass offline and raise
    ``TypeError`` live, which is exactly the drift this seam exists to prevent.

    Offline and deterministic: the pinned distribution is read for its call
    shape only, and the fake is built directly (no seam fixture).
    """

    pinned = _require_installed(_INSTALLED_API_CALL_SHAPE, "Api call shape")
    Api, _credential = _seam_transport(FakeUpstreamScript())

    mirrored_fields = set(inspect.signature(Api).parameters)
    assert mirrored_fields <= set(pinned["fields"]), (
        "the seam accepts a constructor argument the pin's Api does not"
    )
    assert "raw" not in mirrored_fields
    assert "byte" not in mirrored_fields

    mirrored_request = [
        (parameter.name, str(parameter.kind), parameter.default)
        for parameter in inspect.signature(Api.request).parameters.values()
    ]
    assert mirrored_request == pinned["request"]


def test_fake_player_endpoint_mirror_matches_the_installed_pinned_description():
    """The seam's player description is the installed pin's, field for field.

    ``FAKE_PLAYER_ENDPOINT`` is the sole offline oracle for the player call
    shape, so its claim to mirror
    ``bilibili_api.video.API["info"]["get_player_info"]`` literally is checked
    against the distribution it mirrors.  A pin bump that renames a key or
    flips ``verify``/``wbi``/``dm`` fails here instead of staying green offline
    and surfacing only live.
    """

    pinned_endpoint = _require_installed(
        _INSTALLED_PINNED_PLAYER_ENDPOINT, "player endpoint description"
    )

    assert FAKE_PLAYER_ENDPOINT == pinned_endpoint
    # The facts the adapter's two overrides turn on, stated where a pin bump
    # would flip them: this endpoint is described as credential-verified and
    # WBI-signed, and it declares its query fields under ``data`` — field
    # documentation, not a parameter mapping the adapter may forward verbatim.
    assert FAKE_PLAYER_ENDPOINT["verify"] is True
    assert FAKE_PLAYER_ENDPOINT["wbi"] is True
    assert FAKE_PLAYER_ENDPOINT["dm"] is True
    assert sorted(FAKE_PLAYER_ENDPOINT["data"]) == [
        "aid",
        "cid",
        "ep_id",
        "isGaiaAvoided",
        "web_location",
    ]


def test_the_subtitle_url_sentinel_is_scanned_like_every_other_secret():
    """The shipped no-secret scanner flags the scripted subtitle URL.

    The seam scripts every track with :data:`SIGNED_SUBTITLE_URL_MARKER`, so
    the scanner that guards DTOs, messages, and persisted rows must treat it
    exactly like the playback marker.  The protocol-relative form upstream also
    answers is scanned too, so a URL that skipped the adapter's ``https:``
    normalization cannot slip past the scan; together these are the control
    that keeps the downstream "no signed URL" assertions from passing
    vacuously.
    """

    with pytest.raises(AssertionError):
        assert_leaks_no_markers(
            SIGNED_SUBTITLE_URL_MARKER, context="sentinel positive control"
        )
    with pytest.raises(AssertionError):
        assert_leaks_no_markers(
            PROTOCOL_RELATIVE_SUBTITLE_URL, context="relative sentinel control"
        )
    assert PROTOCOL_RELATIVE_SUBTITLE_URL in NO_LEAK_MARKERS
    assert SIGNED_SUBTITLE_URL_MARKER in NO_LEAK_MARKERS


def test_sources_package_reexports_the_subtitle_dtos_only():
    """``bili_asr.sources`` re-exports the new DTOs, never the adapter.

    The package ``__init__`` is the models re-export surface — it must stay
    importable without the pinned package — so the two subtitle DTOs belong
    there while ``BilibiliApiGateway`` stays an explicit import, exactly as
    before.
    """

    import bili_asr.sources as sources

    assert sources.SubtitleTrack is SubtitleTrack
    assert sources.SubtitleSegment is SubtitleSegment
    assert "SubtitleTrack" in sources.__all__
    assert "SubtitleSegment" in sources.__all__
    assert not hasattr(sources, "BilibiliApiGateway")


def test_the_documented_call_allow_list_carries_exactly_the_authorized_routes():
    """The seam's call-name guard allows exactly the documented routes.

    The two subtitle-acquisition routes are authorized by this plan; the set
    stays exact, and a call outside it is still rejected by the shipped guard
    (the control that keeps the allow-list from passing vacuously).
    """

    assert DOCUMENTED_METADATA_CALLS == (
        "space.arc.search",
        "video.get_info",
        "video.get_pages",
        "player.track_list",
        "subtitle.body",
    )
    assert_only_documented_metadata_calls(list(DOCUMENTED_METADATA_CALLS))
    with pytest.raises(AssertionError):
        assert_only_documented_metadata_calls(["playurl.get"])


# ------------------------------------------------- adapter: subtitle listing


def _load_subtitle_gateway(seam, *tracks: object, sessdata: str | None = None):
    """Script one player inventory on the seam and build the adapter for it."""

    seam.player_response = make_player_response(*tracks)
    return _load_gateway(sessdata=sessdata)


def _seam_track(**overrides: object) -> SubtitleTrack:
    """Build the DTO the seam's default inventory entry lists as.

    The seam's default entry is an uploader/CC ``zh-CN`` track carrying
    ``id=1``, so this is exactly what the listing would have returned for it.
    """

    values: dict[str, object] = {
        "language": "zh-CN",
        "label": "中文（中国）",
        "is_ai": False,
        "track_id": "1",
    }
    values.update(overrides)
    return SubtitleTrack(**values)


def _listing_call(*, bvid: str = BVID, cid: int = PART_CID) -> str:
    """The call name the seam records for one player track listing."""

    return f"player.track_list(bvid={bvid}, cid={cid})"


def _subtitle_row(start: float, end: float, content: object, **extra: object) -> dict:
    """Build one caption row in the document's own seconds.

    ``from``/``to`` are Python keywords, so a row is assembled as a mapping
    rather than through keyword arguments.
    """

    row: dict = {"from": start, "to": end, "content": content}
    row.update(extra)
    return row


def test_get_subtitle_tracks_normalizes_ai_and_cc_tracks(bilibili_api_seam):
    """One bounded call maps ``lan``/``lan_doc`` and the AI marker into DTOs."""

    gateway = _load_subtitle_gateway(
        bilibili_api_seam,
        make_subtitle_track(
            id=7, lan="  ai-zh  ", lan_doc="  中文（自动生成）  ", ai_status=1
        ),
        make_subtitle_track(id=9, lan="zh-CN", lan_doc=" 中文（中国） ", type=0),
        sessdata=SESSDATA_BOUNDARY_VALUE,
    )

    tracks = asyncio.run(gateway.get_subtitle_tracks(BVID, PART_CID))

    assert tracks == (
        SubtitleTrack(
            language="ai-zh", label="中文（自动生成）", is_ai=True, track_id="7"
        ),
        SubtitleTrack(
            language="zh-CN", label="中文（中国）", is_ai=False, track_id="9"
        ),
    )
    assert bilibili_api_seam.calls == [_listing_call()]
    for rendered in (repr(tracks), str(tracks)):
        assert_leaks_no_markers(rendered, context="subtitle track DTO")
        assert SESSDATA_BOUNDARY_VALUE not in rendered


@pytest.mark.parametrize(
    ("entry_overrides", "expected_is_ai"),
    [
        ({"ai_status": 1}, True),
        ({"ai_status": 2}, True),
        ({"type": 1}, True),
        ({"ai_status": 0}, False),
        ({"type": 0}, False),
        ({"ai_status": 0, "type": 0}, False),
        ({}, False),
        # Neither marker is present, so the locked conservative reading reports
        # CC even when the language looks machine-generated.
        ({"lan": "ai-zh"}, False),
        ({"lan": "ai-zh", "type": 1}, True),
    ],
)
def test_get_subtitle_tracks_reads_the_upstream_ai_markers(
    bilibili_api_seam, entry_overrides, expected_is_ai
):
    """``is_ai`` comes from the entry's own markers, never from its language."""

    gateway = _load_subtitle_gateway(
        bilibili_api_seam, make_subtitle_track(**entry_overrides)
    )

    (track,) = asyncio.run(gateway.get_subtitle_tracks(BVID, PART_CID))

    assert track.is_ai is expected_is_ai


@pytest.mark.parametrize(
    "broken_marker",
    [
        {"ai_status": "1"},
        {"ai_status": True},
        {"ai_status": -1},
        {"ai_status": 1.0},
        {"type": "1"},
        {"type": True},
        {"type": -1},
    ],
)
def test_get_subtitle_tracks_rejects_a_malformed_ai_marker(
    bilibili_api_seam, broken_marker
):
    """A present marker must be the upstream integer: rejected, never coerced."""

    gateway = _load_subtitle_gateway(
        bilibili_api_seam, make_subtitle_track(**broken_marker)
    )

    with pytest.raises(GatewayShapeError) as caught:
        asyncio.run(gateway.get_subtitle_tracks(BVID, PART_CID))

    assert caught.value.code == "shape_error"


def test_get_subtitle_tracks_reads_the_optional_track_identity(bilibili_api_seam):
    """The upstream integer id becomes the DTO's identity string."""

    gateway = _load_subtitle_gateway(bilibili_api_seam, make_subtitle_track(id=42))

    (track,) = asyncio.run(gateway.get_subtitle_tracks(BVID, PART_CID))

    assert track.track_id == "42"


def test_get_subtitle_tracks_accepts_a_missing_track_identity(bilibili_api_seam):
    """An entry upstream did not identify keeps a null identity."""

    entry = make_subtitle_track()
    entry.pop("id")
    gateway = _load_subtitle_gateway(bilibili_api_seam, entry)

    (track,) = asyncio.run(gateway.get_subtitle_tracks(BVID, PART_CID))

    assert track.track_id is None


@pytest.mark.parametrize("broken_id", ["1", True, -1, 1.5, []])
def test_get_subtitle_tracks_rejects_a_malformed_track_identity(
    bilibili_api_seam, broken_id
):
    """A present id of another shape cannot identify a track."""

    gateway = _load_subtitle_gateway(
        bilibili_api_seam, make_subtitle_track(id=broken_id)
    )

    with pytest.raises(GatewayShapeError) as caught:
        asyncio.run(gateway.get_subtitle_tracks(BVID, PART_CID))

    assert caught.value.code == "shape_error"


@pytest.mark.parametrize(
    "empty_payload",
    [
        {},
        {"subtitle": None},
        {"subtitle": {}},
        {"subtitle": {"allow_submit": False}},
        {"subtitle": {"subtitles": None}},
        {"subtitle": {"subtitles": []}},
    ],
)
def test_get_subtitle_tracks_returns_an_empty_tuple_for_an_empty_inventory(
    bilibili_api_seam, empty_payload
):
    """An invisible inventory is an observation: an empty tuple, never not_found.

    The inventory is missing or empty, so the bounded answer is ``()``.  A
    ``not_found`` here would turn "nothing was visible under this credential"
    into a failure, and the call would raise instead of returning.
    """

    bilibili_api_seam.player_response = empty_payload
    gateway = _load_gateway()

    tracks = asyncio.run(gateway.get_subtitle_tracks(BVID, PART_CID))

    assert tracks == ()
    assert isinstance(tracks, tuple)
    assert bilibili_api_seam.calls == [_listing_call()]


@pytest.mark.parametrize(
    "broken_payload",
    [
        None,
        "no",
        [{"lan": "zh-CN"}],
        {"subtitle": "no"},
        {"subtitle": []},
        {"subtitle": {"subtitles": {}}},
        {"subtitle": {"subtitles": "no"}},
        {"subtitle": {"subtitles": [None]}},
        {"subtitle": {"subtitles": [7]}},
        {"subtitle": {"subtitles": [{}]}},
        {"subtitle": {"subtitles": [{"lan": "", "lan_doc": "中文"}]}},
        {"subtitle": {"subtitles": [{"lan": "   ", "lan_doc": "中文"}]}},
        {"subtitle": {"subtitles": [{"lan": 7, "lan_doc": "中文"}]}},
        {"subtitle": {"subtitles": [{"lan": "zh-CN"}]}},
        {"subtitle": {"subtitles": [{"lan": "zh-CN", "lan_doc": ""}]}},
        {"subtitle": {"subtitles": [{"lan": "zh-CN", "lan_doc": "   "}]}},
        {"subtitle": {"subtitles": [{"lan": "zh-CN", "lan_doc": None}]}},
        # The service derives the language family from the primary subtag, so a
        # vocabulary it could not rank is a shape error, not a silent keep.
        {"subtitle": {"subtitles": [{"lan": "-zh", "lan_doc": "中文"}]}},
        # A label carrying a control character cannot reach the CLI, whose track
        # line is locked to one line per track: it is a bounded shape error here
        # (F-003) rather than a value that splits the printed shape.  The
        # characters are interior on purpose — the adapter strips the outer
        # whitespace of ``lan``/``lan_doc`` before constructing the DTO, so only
        # an interior one survives to the DTO's own rule.
        {"subtitle": {"subtitles": [{"lan": "zh-CN", "lan_doc": "中文\n伪造第二行"}]}},
        {"subtitle": {"subtitles": [{"lan": "zh-CN", "lan_doc": "中文\r伪造"}]}},
        {"subtitle": {"subtitles": [{"lan": "zh-CN", "lan_doc": "中文\x00"}]}},
        {"subtitle": {"subtitles": [{"lan": "zh\n-CN", "lan_doc": "中文"}]}},
    ],
)
def test_get_subtitle_tracks_rejects_an_unreadable_inventory(
    bilibili_api_seam, broken_payload
):
    """A payload that cannot be read as an inventory is a bounded shape error."""

    bilibili_api_seam.player_response = broken_payload
    gateway = _load_gateway()

    with pytest.raises(GatewayShapeError) as caught:
        asyncio.run(gateway.get_subtitle_tracks(BVID, PART_CID))

    assert caught.value.code == "shape_error"
    assert bilibili_api_seam.calls == [_listing_call()]


@pytest.mark.parametrize(
    ("bvid", "cid"),
    [
        ("", PART_CID),
        ("BV1SHORT", PART_CID),
        (12345, PART_CID),
        (BVID, 0),
        (BVID, True),
        (BVID, "2222"),
    ],
)
def test_get_subtitle_tracks_rejects_invalid_arguments(bilibili_api_seam, bvid, cid):
    """Caller-argument violations raise ValueError before any upstream call."""

    gateway = _load_gateway()

    with pytest.raises(ValueError):
        asyncio.run(gateway.get_subtitle_tracks(bvid, cid))
    assert bilibili_api_seam.calls == []


def test_subtitle_listing_request_carries_the_locked_call_shape(bilibili_api_seam):
    """The listing is one player call with the description's declared parameters.

    ``bvid`` stands in for the declared ``aid`` alternative, so no extra
    aid-resolution call is paid; ``dm``/``verify`` are the adapter-owned
    overrides; and neither folklore parameter of this endpoint
    (``need_login_subtitle``, ``w_webid``) is invented, because the installed
    pin declares neither.
    """

    gateway = _load_subtitle_gateway(
        bilibili_api_seam, make_subtitle_track(), sessdata=SESSDATA_BOUNDARY_VALUE
    )

    asyncio.run(gateway.get_subtitle_tracks(BVID, PART_CID))

    (request,) = bilibili_api_seam.api_requests
    assert request.url == FAKE_PLAYER_ENDPOINT["url"]
    assert request.method == FAKE_PLAYER_ENDPOINT["method"]
    assert request.wbi is FAKE_PLAYER_ENDPOINT["wbi"]
    assert request.verify is False
    assert request.dm is False
    assert [key for key in request.params if key.startswith("dm_")] == []
    assert request.params == {
        "bvid": BVID,
        "cid": PART_CID,
        "isGaiaAvoided": False,
        "web_location": 1315873,
    }
    assert request.raw is False
    # The API-host call carries the credential; the seam records its presence
    # only, never the value.
    assert request.has_sessdata is True
    assert SESSDATA_BOUNDARY_VALUE not in repr(request)


def test_subtitle_listing_follows_a_changed_package_endpoint(bilibili_api_seam):
    """No player transport field is hard-coded: the description decides."""

    bilibili_api_seam.player_endpoint["url"] = CHANGED_PLAYER_ENDPOINT_URL
    bilibili_api_seam.player_endpoint["wbi"] = False
    gateway = _load_subtitle_gateway(bilibili_api_seam, make_subtitle_track())

    asyncio.run(gateway.get_subtitle_tracks(BVID, PART_CID))

    (request,) = bilibili_api_seam.api_requests
    assert request.url == CHANGED_PLAYER_ENDPOINT_URL
    assert request.wbi is False


def test_adapter_overrides_only_dm_and_verify_of_the_installed_pinned_player_endpoint(
    bilibili_api_seam,
):
    """``dm``/``verify`` are the only fields changed on the pin's own shape.

    The mirror-parity test above proves the seam's player description equals
    the installed pin's; this test scripts the seam with the pin's *own* values
    and runs the real adapter, so the issued call reproduces every transport
    field of the pinned distribution except those two overrides.  Together they
    pin the shipped call shape to the distribution the adapter actually drives.
    """

    pinned_endpoint = _require_installed(
        _INSTALLED_PINNED_PLAYER_ENDPOINT, "player endpoint description"
    )
    bilibili_api_seam.player_endpoint.update(pinned_endpoint)
    gateway = _load_subtitle_gateway(bilibili_api_seam, make_subtitle_track())

    asyncio.run(gateway.get_subtitle_tracks(BVID, PART_CID))

    (request,) = bilibili_api_seam.api_requests
    assert request.url == pinned_endpoint["url"]
    assert request.method == pinned_endpoint["method"]
    assert request.wbi == pinned_endpoint["wbi"]
    assert pinned_endpoint["verify"] is True
    assert request.verify is False
    assert pinned_endpoint["dm"] is True
    assert request.dm is False


@pytest.mark.parametrize(
    ("upstream_error", "expected"),
    [
        (FakeNetworkException(412, UPSTREAM_ERROR_TEXT), GatewayRateLimited),
        (FakeNetworkException(429, UPSTREAM_ERROR_TEXT), GatewayRateLimited),
        (FakeNetworkException(404, UPSTREAM_ERROR_TEXT), GatewayNotFound),
        (FakeNetworkException(503, UPSTREAM_ERROR_TEXT), GatewayTransportError),
        (FakeResponseCodeException(-412, UPSTREAM_ERROR_TEXT), GatewayRateLimited),
        (FakeResponseCodeException(-352, UPSTREAM_ERROR_TEXT), GatewayRateLimited),
        (FakeResponseCodeException(-799, UPSTREAM_ERROR_TEXT), GatewayRateLimited),
        (FakeResponseCodeException(-404, UPSTREAM_ERROR_TEXT), GatewayNotFound),
        (FakeResponseCodeException(-62002, UPSTREAM_ERROR_TEXT), GatewayNotFound),
        # The one divergence from the metadata path: ``-101`` means "nothing was
        # visible under this credential" on the subtitle calls.
        (FakeResponseCodeException(-101, UPSTREAM_ERROR_TEXT), GatewayNotFound),
        (FakeResponseCodeException(-1, UPSTREAM_ERROR_TEXT), GatewayResponseError),
        (FakeResponseException(UPSTREAM_ERROR_TEXT), GatewayResponseError),
        (FakeWbiRetryTimesExceedException(), GatewayRateLimited),
        (RuntimeError(UPSTREAM_ERROR_TEXT), GatewayTransportError),
    ],
)
def test_subtitle_listing_failures_map_onto_bounded_taxonomy(
    bilibili_api_seam, upstream_error, expected
):
    """The listing boundary maps upstream failures onto the shipped codes."""

    bilibili_api_seam.player_error = upstream_error
    gateway = _load_gateway()

    with pytest.raises(expected) as caught:
        asyncio.run(gateway.get_subtitle_tracks(BVID, PART_CID))

    assert caught.value.code == expected.default_code
    assert caught.value.detail == "get_subtitle_tracks"
    assert UPSTREAM_ERROR_TEXT not in str(caught.value)
    assert bilibili_api_seam.calls == [_listing_call()]


def test_not_logged_in_diverges_between_the_metadata_and_subtitle_paths(
    bilibili_api_seam,
):
    """``-101`` is "not visible" on the subtitle call, an error on the metadata one."""

    bilibili_api_seam.player_error = FakeResponseCodeException(
        -101, UPSTREAM_ERROR_TEXT
    )
    gateway = _load_gateway()

    with pytest.raises(GatewayNotFound) as caught:
        asyncio.run(gateway.get_subtitle_tracks(BVID, PART_CID))
    assert caught.value.code == "not_found"

    bilibili_api_seam.player_error = None
    bilibili_api_seam.videos_error = FakeResponseCodeException(
        -101, UPSTREAM_ERROR_TEXT
    )
    with pytest.raises(GatewayResponseError) as metadata_caught:
        asyncio.run(gateway.get_user_video_page(MID, page_number=1))

    assert metadata_caught.value.code == "response_error"
    assert UPSTREAM_ERROR_TEXT not in str(metadata_caught.value)


# --------------------------------------------- adapter: subtitle body fetch


def test_fetch_subtitle_segments_normalizes_the_document_and_drops_degenerate_rows(
    bilibili_api_seam,
):
    """Seconds become floored milliseconds; rows carrying nothing usable drop.

    The document holds one usable row in front of every drop trigger of the
    spec's section 3 boundary — a zero-length interval, an inverted one, a
    negative start, and content that is empty after stripping — followed by two
    more usable rows, so the surviving sequence proves the drops removed those
    rows and nothing else, in upstream order, with unknown keys tolerated.
    """

    gateway = _load_subtitle_gateway(bilibili_api_seam, make_subtitle_track())
    bilibili_api_seam.subtitle_bodies = {
        SIGNED_SUBTITLE_URL_MARKER: make_subtitle_document(
            _subtitle_row(0.0, 1.5, "  未明子  "),
            _subtitle_row(1.5, 1.5, "零长度"),
            _subtitle_row(3.0, 2.0, "倒置"),
            _subtitle_row(-1.0, 1.0, "负起点"),
            _subtitle_row(2.0, 2.5, "   "),
            _subtitle_row(2.5, 2.75, "第二条", unknown_key="ignored"),
            _subtitle_row(2.75, 3.0, "第三条"),
        )
    }

    segments = asyncio.run(
        gateway.fetch_subtitle_segments(_seam_track(), BVID, PART_CID)
    )

    assert segments == (
        SubtitleSegment(start_ms=0, end_ms=1500, text="未明子"),
        SubtitleSegment(start_ms=2500, end_ms=2750, text="第二条"),
        SubtitleSegment(start_ms=2750, end_ms=3000, text="第三条"),
    )
    assert bilibili_api_seam.calls == [_listing_call(), "subtitle.body"]


def test_caption_text_keeps_interior_control_characters_as_one_row(
    bilibili_api_seam,
):
    """A multi-line cue is a normal caption row, not a document-level failure.

    The storage contract splits its text rules on purpose: ``_caption_text``
    keeps control characters inside a caption body (a stored caption is verbatim
    apart from trimming), while every operator-facing field goes through
    ``_text``, which rejects them.  The gateway mirrors that split, so a cue
    spanning two lines survives as ONE row here.  Rejecting it in the DTO would
    raise a raw ``ValueError`` out of ``fetch_subtitle_segments`` — it is not a
    bounded ``GatewayError`` — and end a whole harvest run on ordinary upstream
    data.
    """

    gateway = _load_subtitle_gateway(bilibili_api_seam, make_subtitle_track())
    bilibili_api_seam.subtitle_bodies = {
        SIGNED_SUBTITLE_URL_MARKER: make_subtitle_document(
            _subtitle_row(0.0, 1.5, "  未明子讲座\n第一讲  "),
            _subtitle_row(1.5, 3.0, "第二行\r第三行"),
            _subtitle_row(3.0, 4.0, "末行"),
        )
    }

    segments = asyncio.run(
        gateway.fetch_subtitle_segments(_seam_track(), BVID, PART_CID)
    )

    assert segments == (
        SubtitleSegment(start_ms=0, end_ms=1500, text="未明子讲座\n第一讲"),
        SubtitleSegment(start_ms=1500, end_ms=3000, text="第二行\r第三行"),
        SubtitleSegment(start_ms=3000, end_ms=4000, text="末行"),
    )
    assert bilibili_api_seam.calls == [_listing_call(), "subtitle.body"]


def test_caption_seconds_are_floored_rather_than_rounded_to_milliseconds(
    bilibili_api_seam,
):
    """The suite's one conversion row that discriminates ``floor`` from ``round``.

    Spec section 3 locks ``floor(seconds * 1000)`` against the legacy
    ``subtitles.json_to_srt`` conversion, which rounds.  Every other
    conversion literal in this module — the drop matrix included — multiplies
    out exactly (``0.0``/``1.0``/``1.5``/``2.0``/``2.5``/``2.75``/``3.0``), so
    those rows pass under either conversion and a floor→round regression would
    leave the whole suite green.  This row is the discriminating one:
    ``3.14159 * 1000`` lands strictly between two integers, so ``floor``
    yields ``3141`` where ``round`` would yield ``3142``, and its end second
    discriminates the same way (``3241`` vs ``3242``).  Both endpoints are
    asserted, so the row discriminates at the start and at the end.
    """

    gateway = _load_subtitle_gateway(bilibili_api_seam, make_subtitle_track())
    bilibili_api_seam.subtitle_bodies = {
        SIGNED_SUBTITLE_URL_MARKER: make_subtitle_document(
            _subtitle_row(3.14159, 3.24159, "向下取整"),
        )
    }

    segments = asyncio.run(
        gateway.fetch_subtitle_segments(_seam_track(), BVID, PART_CID)
    )

    assert segments == (
        SubtitleSegment(start_ms=3141, end_ms=3241, text="向下取整"),
    )
    assert bilibili_api_seam.calls == [_listing_call(), "subtitle.body"]


def test_subtitle_document_request_carries_the_locked_transport_shape(
    bilibili_api_seam,
):
    """The body fetch is the locked raw call on an explicitly empty credential."""

    gateway = _load_subtitle_gateway(
        bilibili_api_seam, make_subtitle_track(), sessdata=SESSDATA_BOUNDARY_VALUE
    )
    bilibili_api_seam.subtitle_bodies = {
        SIGNED_SUBTITLE_URL_MARKER: make_subtitle_document(make_subtitle_entry())
    }

    asyncio.run(gateway.fetch_subtitle_segments(_seam_track(), BVID, PART_CID))

    body_request = bilibili_api_seam.api_requests[-1]
    assert body_request.url == SIGNED_SUBTITLE_URL_MARKER
    assert body_request.method == "GET"
    assert body_request.wbi is False
    assert body_request.dm is False
    assert body_request.verify is False
    assert body_request.params == {}
    assert body_request.raw is True
    # The empty credential keeps SESSDATA off the CDN host, while the API-host
    # listing call above still carries it.
    assert [request.has_sessdata for request in bilibili_api_seam.api_requests] == [
        True,
        False,
    ]


def test_fetch_subtitle_segments_normalizes_a_protocol_relative_document_url(
    bilibili_api_seam,
):
    """A ``//``-relative signed URL is fetched in its absolute ``https:`` form.

    The seam scripts only the absolute form, so fetching the un-normalized
    value would hit an unscripted location and fail loudly there.
    """

    gateway = _load_subtitle_gateway(
        bilibili_api_seam,
        make_subtitle_track(subtitle_url=PROTOCOL_RELATIVE_SUBTITLE_URL),
    )
    bilibili_api_seam.subtitle_bodies = {
        SIGNED_SUBTITLE_URL_MARKER: make_subtitle_document(make_subtitle_entry())
    }

    segments = asyncio.run(
        gateway.fetch_subtitle_segments(_seam_track(), BVID, PART_CID)
    )

    assert [segment.text for segment in segments] == ["未明子"]
    assert bilibili_api_seam.api_requests[-1].url == SIGNED_SUBTITLE_URL_MARKER
    assert bilibili_api_seam.calls == [_listing_call(), "subtitle.body"]


def test_fetch_subtitle_segments_upgrades_a_plain_http_document_url_to_https(
    bilibili_api_seam,
):
    """An absolute ``http:`` signed URL is fetched in its ``https:`` form.

    Upstream may answer the URL absolutely without TLS, and the signed URL is
    itself the document's capability token, so the adapter normalizes the
    scheme instead of forwarding the value as delivered: the request carries
    an explicitly empty credential, which is no reason to put the token in
    clear.  The seam scripts only the ``https:`` form, so an un-upgraded URL
    would hit an unscripted location and fail loudly there.  (The ``http:``
    twin still carries the protocol-relative marker as a substring, so the
    no-leak scanner covers this form too.)
    """

    plain_http_url = f"http://{SIGNED_SUBTITLE_URL_MARKER.removeprefix('https://')}"
    gateway = _load_subtitle_gateway(
        bilibili_api_seam, make_subtitle_track(subtitle_url=plain_http_url)
    )
    bilibili_api_seam.subtitle_bodies = {
        SIGNED_SUBTITLE_URL_MARKER: make_subtitle_document(make_subtitle_entry())
    }

    segments = asyncio.run(
        gateway.fetch_subtitle_segments(_seam_track(), BVID, PART_CID)
    )

    assert [segment.text for segment in segments] == ["未明子"]
    assert bilibili_api_seam.api_requests[-1].url == SIGNED_SUBTITLE_URL_MARKER
    assert bilibili_api_seam.calls == [_listing_call(), "subtitle.body"]


@pytest.mark.parametrize(
    "unreadable_url",
    [
        "ftp://aisubtitle.hdslb.com/subtitle.json?sig=1",
        "aisubtitle.hdslb.com/subtitle.json?sig=1",
    ],
)
def test_fetch_subtitle_segments_rejects_a_document_url_it_cannot_normalize(
    bilibili_api_seam, unreadable_url
):
    """A present ``subtitle_url`` outside the normalizable forms is a shape error.

    Only a protocol-relative, ``http:``, or ``https:`` value can be read as
    this document's URL, so every value the adapter puts on the wire is TLS;
    anything else is refused at the boundary rather than handed to a transport
    that might resolve another scheme.  The refusal happens before the request
    is built, which the exact call list proves (no document fetch), and the
    message carries the static bounded detail instead of the value.
    """

    gateway = _load_subtitle_gateway(
        bilibili_api_seam, make_subtitle_track(subtitle_url=unreadable_url)
    )

    with pytest.raises(GatewayShapeError) as caught:
        asyncio.run(gateway.fetch_subtitle_segments(_seam_track(), BVID, PART_CID))

    assert caught.value.code == "shape_error"
    assert caught.value.detail == "subtitle track has an unreadable document URL"
    assert unreadable_url not in str(caught.value)
    assert bilibili_api_seam.calls == [_listing_call()]


def test_fetch_subtitle_segments_resolves_the_requested_track_by_identity(
    bilibili_api_seam,
):
    """Two tracks matching language + AI are told apart by the requested id."""

    bilibili_api_seam.player_response = make_player_response(
        make_subtitle_track(id=1),
        make_subtitle_track(id=2, subtitle_url=SECOND_SUBTITLE_URL),
    )
    bilibili_api_seam.subtitle_bodies = {
        SIGNED_SUBTITLE_URL_MARKER: make_subtitle_document(
            make_subtitle_entry(content="第一条字幕")
        ),
        SECOND_SUBTITLE_URL: make_subtitle_document(
            make_subtitle_entry(content="第二条字幕")
        ),
    }
    gateway = _load_gateway()

    segments = asyncio.run(
        gateway.fetch_subtitle_segments(_seam_track(track_id="2"), BVID, PART_CID)
    )

    assert [segment.text for segment in segments] == ["第二条字幕"]
    assert bilibili_api_seam.api_requests[-1].url == SECOND_SUBTITLE_URL


@pytest.mark.parametrize("requested_id", [None, "9"])
def test_fetch_subtitle_segments_reports_an_ambiguous_listing(
    bilibili_api_seam, requested_id
):
    """An unresolvable match is a shape error, and no document is fetched.

    Two candidates match on language + AI: ``None`` means the request carries
    no identity to disambiguate with, and ``"9"`` names neither candidate.  The
    bounded outcome for "which track did you mean?" is a shape error, and the
    call list proves nothing was downloaded on a guess.
    """

    bilibili_api_seam.player_response = make_player_response(
        make_subtitle_track(id=1),
        make_subtitle_track(id=2, subtitle_url=SECOND_SUBTITLE_URL),
    )
    bilibili_api_seam.subtitle_bodies = {
        SIGNED_SUBTITLE_URL_MARKER: make_subtitle_document(make_subtitle_entry()),
        SECOND_SUBTITLE_URL: make_subtitle_document(make_subtitle_entry()),
    }
    gateway = _load_gateway()

    with pytest.raises(GatewayShapeError) as caught:
        asyncio.run(
            gateway.fetch_subtitle_segments(
                _seam_track(track_id=requested_id), BVID, PART_CID
            )
        )

    assert caught.value.code == "shape_error"
    assert bilibili_api_seam.calls == [_listing_call()]


def test_fetch_subtitle_segments_reports_a_track_that_is_not_visible(
    bilibili_api_seam,
):
    """A track the fresh listing no longer carries is a bounded ``not_found``.

    The fresh listing is authoritative: a track that disappeared between the
    caller's probe and the fetch, or that the credential can no longer see, is
    ``not_found`` — never an empty success, and never a download attempt.
    """

    gateway = _load_subtitle_gateway(
        bilibili_api_seam, make_subtitle_track(lan="en-US", lan_doc="English")
    )
    bilibili_api_seam.subtitle_bodies = {
        SIGNED_SUBTITLE_URL_MARKER: make_subtitle_document(make_subtitle_entry())
    }

    with pytest.raises(GatewayNotFound) as caught:
        asyncio.run(gateway.fetch_subtitle_segments(_seam_track(), BVID, PART_CID))

    assert caught.value.code == "not_found"
    assert bilibili_api_seam.calls == [_listing_call()]


def test_fetch_subtitle_segments_reads_not_logged_in_as_no_visible_track(
    bilibili_api_seam,
):
    """``-101`` on the fetch's own listing is ``not_found``, never an error."""

    bilibili_api_seam.player_error = FakeResponseCodeException(
        -101, UPSTREAM_ERROR_TEXT
    )
    gateway = _load_gateway()

    with pytest.raises(GatewayNotFound) as caught:
        asyncio.run(gateway.fetch_subtitle_segments(_seam_track(), BVID, PART_CID))

    assert caught.value.code == "not_found"
    assert UPSTREAM_ERROR_TEXT not in str(caught.value)
    assert bilibili_api_seam.calls == [_listing_call()]


@pytest.mark.parametrize(
    "listing_failure",
    [
        FakeNetworkException(503, UPSTREAM_ERROR_TEXT),
        # A transport-class exception the package does not wrap — the shape a
        # dead route or a library-level failure produces.
        RuntimeError(UPSTREAM_ERROR_TEXT),
    ],
)
def test_fetch_subtitle_segments_maps_a_transport_failure_on_its_own_listing(
    bilibili_api_seam, listing_failure
):
    """A transport failure on the fetch's *own* listing never arms the re-list.

    The bounded re-list exists for a body fetch whose signed URL stopped
    working; a listing that never answered is not an expiry, and re-listing
    into it would spend a second call on the same dead route.  The fetch's
    initial listing therefore stands outside the re-list, and this test pins
    that: one call, the mapped transport code, and the requested track's
    operation in the detail — never a second listing.
    """

    bilibili_api_seam.player_error = listing_failure
    gateway = _load_gateway()

    with pytest.raises(GatewayTransportError) as caught:
        asyncio.run(gateway.fetch_subtitle_segments(_seam_track(), BVID, PART_CID))

    assert caught.value.code == "transport_error"
    assert caught.value.detail == "fetch_subtitle_segments"
    assert UPSTREAM_ERROR_TEXT not in str(caught.value)
    assert bilibili_api_seam.calls == [_listing_call()]


@pytest.mark.parametrize(
    "unreadable_document",
    [
        None,
        "no",
        [],
        {},
        {"font_size": 0.4},
        {"body": None},
        {"body": {}},
        {"body": "no"},
        {"body": [None]},
        {"body": [7]},
        {"body": ["caption"]},
        {"body": [{"to": 1.0, "content": "未明子"}]},
        {"body": [{"from": None, "to": 1.0, "content": "未明子"}]},
        {"body": [{"from": "0.0", "to": 1.0, "content": "未明子"}]},
        {"body": [{"from": True, "to": 1.0, "content": "未明子"}]},
        {"body": [{"from": [0.0], "to": 1.0, "content": "未明子"}]},
        {"body": [{"from": 0.0, "to": "1.0", "content": "未明子"}]},
        {"body": [{"from": 0.0, "to": None, "content": "未明子"}]},
        {"body": [{"from": float("nan"), "to": 1.0, "content": "未明子"}]},
        {"body": [{"from": 0.0, "to": float("inf"), "content": "未明子"}]},
        # A finite value whose millisecond product leaves the float range is
        # equally unreadable; without that rule ``math.floor`` would escape as
        # an ``OverflowError`` instead of a bounded code.
        {"body": [{"from": 0.0, "to": 1e308, "content": "未明子"}]},
        {"body": [{"from": 0.0, "to": 1.5}]},
        {"body": [{"from": 0.0, "to": 1.5, "content": None}]},
        {"body": [{"from": 0.0, "to": 1.5, "content": 7}]},
        {"body": [{"from": 0.0, "to": 1.5, "content": ["未明子"]}]},
    ],
)
def test_fetch_subtitle_segments_rejects_an_unreadable_document(
    bilibili_api_seam, unreadable_document
):
    """An entry or document that cannot be read as segments is a shape error.

    ``NaN``/``Infinity`` are the values Python's ``json`` accepts as bare
    tokens, so scripting them directly is what the decoder would hand over.  An
    unreadable document is not an expiry, so the call list proves it is never
    re-fetched.
    """

    gateway = _load_subtitle_gateway(bilibili_api_seam, make_subtitle_track())
    bilibili_api_seam.subtitle_bodies = {
        SIGNED_SUBTITLE_URL_MARKER: unreadable_document
    }

    with pytest.raises(GatewayShapeError) as caught:
        asyncio.run(gateway.fetch_subtitle_segments(_seam_track(), BVID, PART_CID))

    assert caught.value.code == "shape_error"
    assert bilibili_api_seam.calls == [_listing_call(), "subtitle.body"]


def test_a_cancelled_document_fetch_propagates_instead_of_being_mapped(
    bilibili_api_seam,
):
    """``CancelledError`` is not an unexpected upstream failure.

    The mapper's broad ``except Exception`` is what turns every unmapped
    upstream failure into the bounded ``transport_error``, and that is the
    contract the sibling cases here pin.  Cancellation is not that kind of
    failure: ``asyncio.CancelledError`` derives from ``BaseException``, so it
    must reach the caller and stop the task instead of being rewritten into a
    bounded code — a rewrite would additionally arm the adapter's single
    re-list, i.e. a cancelled call would spend two more network requests.  The
    seam raises the scripted ``BaseException`` as-is, and the exact call list
    proves the document fetch was actually issued (so this cannot pass by
    never reaching the mapper) and that no re-list followed it.
    """

    gateway = _load_subtitle_gateway(bilibili_api_seam, make_subtitle_track())
    bilibili_api_seam.subtitle_bodies = {
        SIGNED_SUBTITLE_URL_MARKER: asyncio.CancelledError()
    }

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(gateway.fetch_subtitle_segments(_seam_track(), BVID, PART_CID))

    assert bilibili_api_seam.calls == [_listing_call(), "subtitle.body"]


@pytest.mark.parametrize(
    ("body_outcome", "expected", "attempts"),
    [
        # Expiry/transport class: one re-list + fetch pair, then the code.
        (FakeNetworkException(503, UPSTREAM_ERROR_TEXT), GatewayTransportError, 2),
        (RuntimeError(UPSTREAM_ERROR_TEXT), GatewayTransportError, 2),
        # Rate control never re-lists: re-listing into the same block only
        # spends the risk budget.
        (FakeNetworkException(412, UPSTREAM_ERROR_TEXT), GatewayRateLimited, 1),
        (FakeNetworkException(429, UPSTREAM_ERROR_TEXT), GatewayRateLimited, 1),
        (FakeResponseCodeException(-412, UPSTREAM_ERROR_TEXT), GatewayRateLimited, 1),
        (FakeWbiRetryTimesExceedException(), GatewayRateLimited, 1),
        # A document that is not there is not an expiry.
        (FakeNetworkException(404, UPSTREAM_ERROR_TEXT), GatewayNotFound, 1),
        # Error envelopes that are not transport failures.
        (FakeResponseCodeException(-1, UPSTREAM_ERROR_TEXT), GatewayResponseError, 1),
        (FakeResponseException(UPSTREAM_ERROR_TEXT), GatewayResponseError, 1),
    ],
)
def test_subtitle_document_failures_stay_bounded_and_never_loop(
    bilibili_api_seam, body_outcome, expected, attempts
):
    """Every body-fetch failure class maps to its code within the call bound.

    ``attempts`` is the number of listing + fetch pairs the class is allowed:
    one, or the single bounded re-list pair for the expiry/transport class.
    The exact call list is the evidence that there is no third attempt and no
    loop, whatever the failure was.
    """

    gateway = _load_subtitle_gateway(bilibili_api_seam, make_subtitle_track())
    bilibili_api_seam.subtitle_bodies = {
        SIGNED_SUBTITLE_URL_MARKER: body_outcome
    }

    with pytest.raises(expected) as caught:
        asyncio.run(gateway.fetch_subtitle_segments(_seam_track(), BVID, PART_CID))

    assert caught.value.code == expected.default_code
    assert caught.value.detail == "fetch_subtitle_segments"
    assert UPSTREAM_ERROR_TEXT not in str(caught.value)
    assert bilibili_api_seam.calls == [_listing_call(), "subtitle.body"] * attempts


def test_fetch_subtitle_segments_relists_for_a_fresh_signed_url(bilibili_api_seam):
    """The second attempt re-lists and uses the fresh URL, not the stale one."""

    listings: list[str] = []

    def player_response(bvid: str, cid: int) -> dict:
        listings.append(bvid)
        url = (
            SIGNED_SUBTITLE_URL_MARKER
            if len(listings) == 1
            else SECOND_SUBTITLE_URL
        )
        return make_player_response(make_subtitle_track(subtitle_url=url))

    bilibili_api_seam.player_response = player_response
    bilibili_api_seam.subtitle_bodies = {
        SIGNED_SUBTITLE_URL_MARKER: FakeNetworkException(503, UPSTREAM_ERROR_TEXT),
        SECOND_SUBTITLE_URL: make_subtitle_document(
            make_subtitle_entry(content="重新列取")
        ),
    }
    gateway = _load_gateway()

    segments = asyncio.run(
        gateway.fetch_subtitle_segments(_seam_track(), BVID, PART_CID)
    )

    assert [segment.text for segment in segments] == ["重新列取"]
    assert [request.url for request in bilibili_api_seam.api_requests] == [
        FAKE_PLAYER_ENDPOINT["url"],
        SIGNED_SUBTITLE_URL_MARKER,
        FAKE_PLAYER_ENDPOINT["url"],
        SECOND_SUBTITLE_URL,
    ]
    assert bilibili_api_seam.calls == [
        _listing_call(),
        "subtitle.body",
        _listing_call(),
        "subtitle.body",
    ]


def test_fetch_subtitle_segments_signals_not_found_when_nothing_survives(
    bilibili_api_seam,
):
    """An empty or fully degenerate document is ``not_found``, never a success.

    Both documents are the locked "nothing usable" cases: an empty ``body``
    array, and a document every one of whose rows is dropped.  Neither is a
    shape error — every row *was* readable — and the assignment below can stay
    ``None`` only because no empty tuple was ever returned.
    """

    gateway = _load_subtitle_gateway(bilibili_api_seam, make_subtitle_track())

    for nothing_usable in (
        make_subtitle_document(),
        make_subtitle_document(
            _subtitle_row(1.0, 1.0, "零长度"),
            _subtitle_row(2.0, 1.0, "倒置"),
            _subtitle_row(-1.0, 1.0, "负起点"),
            _subtitle_row(0.0, 1.0, "   "),
        ),
    ):
        bilibili_api_seam.subtitle_bodies = {
            SIGNED_SUBTITLE_URL_MARKER: nothing_usable
        }
        returned = None
        with pytest.raises(GatewayNotFound) as caught:
            returned = asyncio.run(
                gateway.fetch_subtitle_segments(_seam_track(), BVID, PART_CID)
            )
        assert caught.value.code == "not_found"
        assert returned is None
        assert bilibili_api_seam.calls == [_listing_call(), "subtitle.body"]
        bilibili_api_seam.calls.clear()


@pytest.mark.parametrize(
    ("track", "bvid", "cid"),
    [
        (None, BVID, PART_CID),
        ("zh-CN", BVID, PART_CID),
        ({}, BVID, PART_CID),
        (_seam_track(), "", PART_CID),
        (_seam_track(), "BV1SHORT", PART_CID),
        (_seam_track(), BVID, 0),
        (_seam_track(), BVID, True),
    ],
)
def test_fetch_subtitle_segments_rejects_invalid_arguments(
    bilibili_api_seam, track, bvid, cid
):
    """A non-DTO track and malformed arguments are rejected before any call."""

    gateway = _load_gateway()

    with pytest.raises((TypeError, ValueError)):
        asyncio.run(gateway.fetch_subtitle_segments(track, bvid, cid))
    assert bilibili_api_seam.calls == []


def test_subtitle_failure_messages_never_carry_the_upstream_text_or_the_url(
    bilibili_api_seam,
):
    """Every mapped body-fetch failure stays bounded to its code and operation."""

    gateway = _load_subtitle_gateway(
        bilibili_api_seam, make_subtitle_track(), sessdata=SESSDATA_BOUNDARY_VALUE
    )

    for body_outcome, expected, expected_detail in (
        (
            FakeNetworkException(503, UPSTREAM_ERROR_TEXT),
            GatewayTransportError,
            "fetch_subtitle_segments",
        ),
        (
            FakeNetworkException(412, UPSTREAM_ERROR_TEXT),
            GatewayRateLimited,
            "fetch_subtitle_segments",
        ),
        (
            FakeResponseException(UPSTREAM_ERROR_TEXT),
            GatewayResponseError,
            "fetch_subtitle_segments",
        ),
        # A shape failure carries its own bounded phrase instead, and never
        # anything the document said.
        ("no", GatewayShapeError, "subtitle document is not a mapping"),
    ):
        bilibili_api_seam.subtitle_bodies = {
            SIGNED_SUBTITLE_URL_MARKER: body_outcome
        }
        with pytest.raises(expected) as caught:
            asyncio.run(
                gateway.fetch_subtitle_segments(_seam_track(), BVID, PART_CID)
            )
        assert caught.value.detail == expected_detail
        for rendered in (str(caught.value), repr(caught.value)):
            assert UPSTREAM_ERROR_TEXT not in rendered
            assert_leaks_no_markers(rendered, context="mapped subtitle failure")
            assert SESSDATA_BOUNDARY_VALUE not in rendered


def test_the_subtitle_routes_stay_on_the_documented_call_surface(
    bilibili_api_seam,
):
    """Every call a listing plus a body fetch issues is a documented route."""

    gateway = _load_subtitle_gateway(bilibili_api_seam, make_subtitle_track())
    bilibili_api_seam.subtitle_bodies = {
        SIGNED_SUBTITLE_URL_MARKER: make_subtitle_document(make_subtitle_entry())
    }

    asyncio.run(gateway.get_subtitle_tracks(BVID, PART_CID))
    asyncio.run(gateway.fetch_subtitle_segments(_seam_track(), BVID, PART_CID))

    assert bilibili_api_seam.calls == [
        _listing_call(),
        _listing_call(),
        "subtitle.body",
    ]
    assert_only_documented_metadata_calls(bilibili_api_seam.calls)


# ------------------------------------------------------------- live smoke


LIVE_SMOKE_ENV = "BILI_LIVE_SMOKE"

#: Tokens that must never appear in the live smoke's persisted rows: cookie
#: names and playback-CDN signature markers indicate credential or playback
#: leakage rather than ordinary metadata.
LIVE_HYGIENE_TOKENS = ("sessdata", "pssign", "bilivideo.com")


def _live_smoke_requested() -> bool:
    """True only when the operator explicitly opts in via the environment."""

    return os.environ.get(LIVE_SMOKE_ENV, "") == "1"


def test_live_smoke_single_public_page_for_archive_owner(tmp_root):
    """Opt-in live probe: ONE public metadata page for UID 23191782.

    Skipped unless the operator sets ``BILI_LIVE_SMOKE=1``.  The probe
    requests exactly one bounded page (``ps=30``) for the archive owner
    through the real adapter, ingests it into a fresh temporary SQLite
    database, calls no subtitle/playback/audio/ASR/export endpoint,
    requires no credential, and keeps every raw upstream payload
    process-local.
    """

    if not _live_smoke_requested():
        pytest.skip(f"live smoke is opt-in: set {LIVE_SMOKE_ENV}=1 to request it")

    try:
        gateway = _load_gateway()
    except ImportError as error:
        pytest.fail(
            "live smoke was requested but the pinned package is not importable"
            f" in this environment ({error}); install bilibili-api-python=="
            f"{PINNED_PACKAGE_VERSION} (uv sync) first"
        )

    assert gateway.get_package_version() == PINNED_PACKAGE_VERSION
    connection = open_database(os.path.join(tmp_root, "live-smoke.sqlite"))
    try:
        repository = MetadataRepository(connection)
        result = MetadataIngestor(gateway, repository).collect_user_pages(
            MID, start_page=1, page_limit=1
        )

        # Bounded: exactly one requested page and one page-evidence row.
        assert result.page_count == 1
        if result.outcome in ("failed", "risk_interrupted"):
            pytest.fail(
                "live one-page smoke ended in a bounded upstream failure"
                f" (code={result.error_code!r}); rerun when upstream recovers"
            )
        assert result.outcome in ("complete", "limited")

        persisted = persisted_row_text(connection)
        scan_text = (persisted + repr(result)).lower()
        for token in LIVE_HYGIENE_TOKENS:
            assert token not in scan_text, f"live smoke persisted {token!r}"

        video_rows = connection.execute(
            "SELECT bvid, mid, title FROM videos ORDER BY bvid"
        ).fetchall()
        assert {row["mid"] for row in video_rows} <= {MID}
        for row in video_rows:
            assert row["bvid"].startswith("BV") and len(row["bvid"]) == 12
            assert row["title"].strip()
        for cid, duration_ms in (
            tuple(row)
            for row in connection.execute("SELECT cid, duration_ms FROM video_parts")
        ):
            assert cid >= 1 and duration_ms >= 1
    finally:
        connection.close()
