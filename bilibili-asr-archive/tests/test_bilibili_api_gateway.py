"""Offline contract tests for the typed Bilibili gateway boundary.

Every functional test runs against a fake ``bilibili_api`` package installed
on ``sys.modules`` before the gateway module is (re-)imported, so neither the
real package nor network access is ever required.  The fake package seam, the
shared scripted protocol double, and the secret/raw-payload sentinels live in
``tests/fixtures/fake_bilibili_gateway.py``.  The fake mirrors only the
documented import surface the gateway may use (``Credential``, ``user.User``,
``video.Video``, and the exceptions taxonomy) and exposes no playback,
subtitle, audio, or download methods, which makes silent use of other package
APIs impossible.  The import boundary and the method surface itself are
additionally inspected statically with AST over the package sources.  The
only networked test is the opt-in live smoke, which skips unless
``BILI_LIVE_SMOKE=1`` is set.
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import os
import pathlib

import pytest

from bili_asr.services.metadata_ingest import MetadataIngestor
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
from bili_asr.storage.database import MetadataRepository, open_database
from fixtures.fake_bilibili_gateway import (
    BVID,
    MID,
    PUBDATE,
    RAW_JSON_BODY_MARKER,
    SESSDATA_BOUNDARY_VALUE,
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
    make_videos_response,
    make_vlist_item,
    persisted_row_text,
)

PINNED_PACKAGE_VERSION = "17.4.2"

#: The exact bilibili_api import surface the adapter is allowed to use.
ALLOWED_PACKAGE_IMPORTS = {
    "bilibili_api": {"Credential"},
    "bilibili_api.user": {"User"},
    "bilibili_api.video": {"Video"},
    "bilibili_api.exceptions": {
        "ApiException",
        "NetworkException",
        "ResponseCodeException",
        "ResponseException",
        "WbiRetryTimesExceedException",
    },
}

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


def _load_gateway(sessdata: str | None = None):
    """Import the adapter against the installed seam and build it."""

    module = importlib.import_module("bili_asr.sources.bilibili_api_gateway")
    return module.BilibiliApiGateway(sessdata=sessdata)


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
    assert bilibili_api_seam.calls == ["user.get_videos(pn=1, ps=100)"]
    # The credential value must never surface on any DTO or page.
    assert SESSDATA_BOUNDARY_VALUE not in repr(page)
    assert SESSDATA_BOUNDARY_VALUE not in str(page)


def test_get_user_video_page_forwards_requested_page_and_size(bilibili_api_seam):
    """The adapter passes the documented page parameters only."""

    bilibili_api_seam.videos_response = make_videos_response(make_vlist_item(), count=1)
    gateway = _load_gateway()

    asyncio.run(gateway.get_user_video_page(MID, page_number=4, page_size=50))

    assert bilibili_api_seam.calls == ["user.get_videos(pn=4, ps=50)"]


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
    assert bilibili_api_seam.calls == ["user.get_videos(pn=1, ps=100)"]


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
    """The adapter imports only Credential, User, Video, and exceptions."""

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
    assert {"get_videos", "get_pages", "get_info"} <= attribute_names


def test_fake_seam_exposes_only_documented_metadata_surface():
    """The offline seam exposes exactly the documented metadata methods."""

    modules = build_fake_package(FakeUpstreamScript())
    package = modules["bilibili_api"]

    assert _public_names(modules["bilibili_api.user"]) == ["User"]
    assert _public_names(modules["bilibili_api.video"]) == ["Video"]
    assert _public_names(modules["bilibili_api.exceptions"]) == sorted(
        ALLOWED_EXCEPTION_NAMES
    )
    assert _public_names(package) == ["Credential", "exceptions", "user", "video"]
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
        "user.get_videos(pn=1, ps=100)",
        "video.get_info",
        "video.get_pages",
    ]


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
    requests exactly one bounded page (``ps=100``) for the archive owner
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
