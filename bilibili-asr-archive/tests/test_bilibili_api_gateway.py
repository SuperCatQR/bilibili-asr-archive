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
    FAKE_PLAYER_ENDPOINT,
    FAKE_USER_VIDEO_PAGE_ENDPOINT,
    MID,
    MIRRORED_ENDPOINT_FIELDS,
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
#: and the WBI-signed ``utils.network.Api``, not through a ``user`` delegate.
ALLOWED_PACKAGE_IMPORTS = {
    "bilibili_api": {"Credential", "request_settings", "user"},
    "bilibili_api.utils.network": {"Api"},
    "bilibili_api.video": {"Video"},
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

#: Attribute names that would mark playback/subtitle/audio/ASR/export usage.
#: Tokens are matched as plain substrings, so only unambiguous names belong
#: here (``stream`` would false-positive on ``_await_upstream``).
FORBIDDEN_SEAM_METHOD_TOKENS = (
    "subtitle",
    "playback",
    "playurl",
    "play_url",
    "download",
    "danmaku",
    "player",
    "audio",
    "asr",
    "export",
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
    """The protocol declares the locked six methods, signatures included.

    The four shipped signatures stay untouched — the shipped metadata service
    and the storage plan consume them — and the two subtitle methods are
    exactly the locked pair: ``get_subtitle_tracks(bvid, cid)`` answers a
    possibly empty tuple (an empty inventory is an observation, never a
    ``not_found`` failure), while ``fetch_subtitle_segments(track, bvid, cid)``
    answers a non-empty tuple or raises ``GatewayNotFound``.
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
        name: tuple(inspect.signature(getattr(BilibiliGateway, name)).parameters)
        for name in expected
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
    ``request_settings``/``user`` modules from the package root, the
    WBI-signed ``utils.network.Api``, ``video.Video``, and the five exception
    names.  ``User`` is deliberately not among them — the page call goes
    through the ``user`` module's endpoint description and the package ``Api``,
    never a ``user.User`` delegate.
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
    """The adapter source never references playback/subtitle/audio names."""

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
    exactly like the playback marker; this is the control that keeps the
    downstream "no signed URL" assertions from passing vacuously.
    """

    with pytest.raises(AssertionError):
        assert_leaks_no_markers(
            SIGNED_SUBTITLE_URL_MARKER, context="sentinel positive control"
        )


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
