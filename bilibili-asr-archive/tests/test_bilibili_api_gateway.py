"""Offline contract tests for the typed Bilibili gateway boundary.

Every functional test runs against a fake ``bilibili_api`` package installed
on ``sys.modules`` before the gateway module is (re-)imported, so neither the
real package nor network access is ever required.  The fake mirrors only the
documented import surface the gateway may use (``Credential``, ``user.User``,
``video.Video``, and the exceptions taxonomy) and exposes no playback,
subtitle, audio, or download methods, which makes silent use of other package
APIs impossible.  The import boundary itself is additionally inspected
statically with AST over the package sources.
"""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import importlib
import pathlib
import sys
import types

import pytest

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

MID = 23191782
BVID = "BV1AbCdEfGhJ"
PUBDATE = 1725859200
PINNED_PACKAGE_VERSION = "17.4.2"
SESSDATA_BOUNDARY_VALUE = "SESSDATA-VALUE-THAT-MUST-NOT-LEAK"

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

UPSTREAM_TEXT = "RISK-CHALLENGE-PAYLOAD http://api.bilibili.com/x/secret"


# ----------------------------------------------------------- fake package seam


class FakeApiException(Exception):
    """Mirror of ``bilibili_api.exceptions.ApiException``."""

    def __init__(self, msg: str = "出现了错误，但是未说明具体原因。") -> None:
        super().__init__(msg)
        self.msg = msg


class FakeNetworkException(FakeApiException):
    """Mirror of ``NetworkException(status, msg)`` carrying the HTTP status."""

    def __init__(self, status: int, msg: str) -> None:
        super().__init__(msg)
        self.status = status


class FakeResponseCodeException(FakeApiException):
    """Mirror of ``ResponseCodeException(code, msg, raw)`` carrying the code."""

    def __init__(self, code: int, msg: str, raw: object = None) -> None:
        super().__init__(msg)
        self.code = code


class FakeResponseException(FakeApiException):
    """Mirror of ``ResponseException(msg)``."""

    def __init__(self, msg: str) -> None:
        super().__init__(msg)


class FakeWbiRetryTimesExceedException(FakeApiException):
    """Mirror of ``WbiRetryTimesExceedException()`` (WBI retry budget gone)."""

    def __init__(self) -> None:
        super().__init__("WBI 重试达到最大次数")


@dataclasses.dataclass
class FakeUpstreamScript:
    """Scripted upstream behavior; records every call the gateway makes."""

    videos_response: object = None
    videos_error: BaseException | None = None
    parts_response: object = None
    parts_error: BaseException | None = None
    info_response: object = None
    info_error: BaseException | None = None
    calls: list[str] = dataclasses.field(default_factory=list)


def _build_fake_package(script: FakeUpstreamScript) -> dict[str, types.ModuleType]:
    """Build the fake ``bilibili_api`` package with the documented surface."""

    package = types.ModuleType("bilibili_api")

    class Credential:
        def __init__(self, sessdata: str | None = None) -> None:
            self.sessdata = sessdata

    package.Credential = Credential

    exceptions_mod = types.ModuleType("bilibili_api.exceptions")
    exceptions_mod.ApiException = FakeApiException
    exceptions_mod.NetworkException = FakeNetworkException
    exceptions_mod.ResponseCodeException = FakeResponseCodeException
    exceptions_mod.ResponseException = FakeResponseException
    exceptions_mod.WbiRetryTimesExceedException = FakeWbiRetryTimesExceedException

    user_mod = types.ModuleType("bilibili_api.user")

    class User:
        """Mirror of ``user.User(uid, credential)`` with only get_videos."""

        def __init__(self, uid: int, credential: object = None) -> None:
            self.uid = uid
            self.credential = credential

        async def get_videos(
            self,
            tid: int = 0,
            pn: int = 1,
            ps: int = 30,
            keyword: str = "",
            order: object = None,
        ) -> dict:
            script.calls.append(f"user.get_videos(pn={pn}, ps={ps})")
            if script.videos_error is not None:
                raise script.videos_error
            return script.videos_response

    user_mod.User = User

    video_mod = types.ModuleType("bilibili_api.video")

    class Video:
        """Mirror of ``video.Video(bvid, credential)`` with metadata calls only."""

        def __init__(
            self,
            bvid: str | None = None,
            aid: int | None = None,
            credential: object = None,
        ) -> None:
            self.bvid = bvid
            self.aid = aid
            self.credential = credential

        async def get_info(self) -> dict:
            script.calls.append("video.get_info")
            if script.info_error is not None:
                raise script.info_error
            return script.info_response

        async def get_pages(self) -> list:
            script.calls.append("video.get_pages")
            if script.parts_error is not None:
                raise script.parts_error
            return script.parts_response

    video_mod.Video = Video

    package.user = user_mod
    package.video = video_mod
    package.exceptions = exceptions_mod

    return {
        "bilibili_api": package,
        "bilibili_api.user": user_mod,
        "bilibili_api.video": video_mod,
        "bilibili_api.exceptions": exceptions_mod,
    }


@pytest.fixture
def bilibili_api_seam(monkeypatch) -> FakeUpstreamScript:
    """Install the fake package and yield its script.

    Only the adapter module is dropped from the module cache, before and
    after each test: it re-imports against the current seam, while every
    other ``bili_asr`` module stays cached so class identity is preserved
    between the test imports and the adapter imports.
    """

    script = FakeUpstreamScript()
    for name, module in _build_fake_package(script).items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.delitem(sys.modules, "bili_asr.sources.bilibili_api_gateway", raising=False)
    yield script
    sys.modules.pop("bili_asr.sources.bilibili_api_gateway", None)


def _load_gateway(sessdata: str | None = None):
    """Import the adapter against the installed seam and build it."""

    module = importlib.import_module("bili_asr.sources.bilibili_api_gateway")
    return module.BilibiliApiGateway(sessdata=sessdata)


# --------------------------------------------------- deterministic factories


def _vlist_item(**overrides: object) -> dict:
    """Build one documented arc/search vlist item with literal values."""

    item = {
        "aid": 111,
        "bvid": BVID,
        "title": "未明子讲座",
        "created": PUBDATE,
        "mid": MID,
    }
    item.update(overrides)
    return item


def _videos_response(*items: dict, count: int | None = 2) -> dict:
    """Build the inner arc/search data: ``list.vlist`` plus ``page.count``."""

    response: dict = {"list": {"vlist": list(items)}}
    if count is not None:
        response["page"] = {"pn": 1, "ps": 100, "count": count}
    return response


def _part_item(**overrides: object) -> dict:
    """Build one documented pagelist element with literal values."""

    item = {
        "cid": 2222,
        "page": 1,
        "part": "第一部分",
        "duration": 12,
    }
    item.update(overrides)
    return item


def _detail_response(**overrides: object) -> dict:
    """Build the view-API detail body used to fill a missing aid."""

    detail = {
        "aid": 111,
        "bvid": BVID,
        "title": "未明子讲座",
        "pubdate": PUBDATE,
        "owner": {"mid": MID, "name": "未明子"},
    }
    detail.update(overrides)
    return detail


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

    bilibili_api_seam.videos_response = _videos_response(
        _vlist_item(title="  未明子讲座  "), count=7
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

    bilibili_api_seam.videos_response = _videos_response(_vlist_item(), count=1)
    gateway = _load_gateway()

    asyncio.run(gateway.get_user_video_page(MID, page_number=4, page_size=50))

    assert bilibili_api_seam.calls == ["user.get_videos(pn=4, ps=50)"]


def test_get_user_video_page_tolerates_plain_list_container(bilibili_api_seam):
    """A plain ``list`` array instead of ``list.vlist`` normalizes too."""

    bilibili_api_seam.videos_response = {"list": [_vlist_item()], "page": {"count": 3}}
    gateway = _load_gateway()

    page = asyncio.run(gateway.get_user_video_page(MID, page_number=2))

    assert page.observed_total == 3
    assert [summary.bvid for summary in page.videos] == [BVID]


def test_get_user_video_page_observed_total_absent_is_none(bilibili_api_seam):
    """A response without a total field yields ``observed_total=None``."""

    bilibili_api_seam.videos_response = _videos_response(_vlist_item(), count=None)
    gateway = _load_gateway()

    page = asyncio.run(gateway.get_user_video_page(MID, page_number=1))

    assert page.observed_total is None


def test_get_user_video_page_accepts_pubdate_fallback_field(bilibili_api_seam):
    """An item carrying ``pubdate`` instead of ``created`` still normalizes."""

    bilibili_api_seam.videos_response = _videos_response(
        {"bvid": BVID, "aid": 111, "title": "未明子讲座", "pubdate": PUBDATE, "mid": MID},
        count=1,
    )
    gateway = _load_gateway()

    page = asyncio.run(gateway.get_user_video_page(MID, page_number=1))

    assert page.videos[0].pubdate == PUBDATE


def test_get_user_video_page_returns_empty_page(bilibili_api_seam):
    """An empty vlist is a valid empty page."""

    bilibili_api_seam.videos_response = _videos_response()
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

    bilibili_api_seam.videos_response = _videos_response(_vlist_item(mid=MID + 1))
    gateway = _load_gateway()

    with pytest.raises(GatewayShapeError) as caught:
        asyncio.run(gateway.get_user_video_page(MID, page_number=1))

    assert caught.value.code == "shape_error"
    assert "mid" in str(caught.value)


def test_get_user_video_page_rejects_missing_owner_mid(bilibili_api_seam):
    """An item without an owner mid cannot prove ownership."""

    bilibili_api_seam.videos_response = _videos_response(
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
        [_vlist_item()],
    ],
)
def test_get_user_video_page_rejects_malformed_items(bilibili_api_seam, broken_item):
    """Every required scalar is validated before a DTO is returned."""

    bilibili_api_seam.videos_response = _videos_response(broken_item)
    gateway = _load_gateway()

    with pytest.raises(GatewayShapeError):
        asyncio.run(gateway.get_user_video_page(MID, page_number=1))


def test_get_user_video_page_rejects_malformed_observed_total(bilibili_api_seam):
    """A present but non-integer total is a shape error, not a silent None."""

    bilibili_api_seam.videos_response = {
        "list": {"vlist": [_vlist_item()]},
        "page": {"count": "many"},
    }
    gateway = _load_gateway()

    with pytest.raises(GatewayShapeError):
        asyncio.run(gateway.get_user_video_page(MID, page_number=1))


# -------------------------------------------------------------- video parts


def test_get_video_parts_converts_page_index_and_duration(bilibili_api_seam):
    """One-based ``page`` and seconds become zero-based index and ms."""

    bilibili_api_seam.parts_response = [
        _part_item(cid=2222, page=1, part="  第一部分  ", duration=12),
        _part_item(cid=3333, page=3, part="第三部分", duration=10.5),
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

    bilibili_api_seam.parts_response = [_part_item(dimension={"width": 1})]
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
        [_part_item()],
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
        (FakeNetworkException(412, UPSTREAM_TEXT), GatewayRateLimited),
        (FakeNetworkException(429, UPSTREAM_TEXT), GatewayRateLimited),
        (FakeNetworkException(404, UPSTREAM_TEXT), GatewayNotFound),
        (FakeNetworkException(503, UPSTREAM_TEXT), GatewayTransportError),
        (FakeResponseCodeException(-412, UPSTREAM_TEXT), GatewayRateLimited),
        (FakeResponseCodeException(-352, UPSTREAM_TEXT), GatewayRateLimited),
        (FakeResponseCodeException(-799, UPSTREAM_TEXT), GatewayRateLimited),
        (FakeResponseCodeException(-404, UPSTREAM_TEXT), GatewayNotFound),
        (FakeResponseCodeException(-62002, UPSTREAM_TEXT), GatewayNotFound),
        (FakeResponseCodeException(-101, UPSTREAM_TEXT), GatewayResponseError),
        (FakeResponseCodeException(-1, UPSTREAM_TEXT), GatewayResponseError),
        (FakeResponseException(UPSTREAM_TEXT), GatewayResponseError),
        (FakeWbiRetryTimesExceedException(), GatewayRateLimited),
        (RuntimeError(UPSTREAM_TEXT), GatewayTransportError),
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
    assert UPSTREAM_TEXT not in str(caught.value)


@pytest.mark.parametrize(
    ("upstream_error", "expected"),
    [
        (FakeNetworkException(412, UPSTREAM_TEXT), GatewayRateLimited),
        (FakeResponseCodeException(-404, UPSTREAM_TEXT), GatewayNotFound),
        (RuntimeError(UPSTREAM_TEXT), GatewayTransportError),
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
    assert UPSTREAM_TEXT not in str(caught.value)


@pytest.mark.parametrize(
    ("upstream_error", "expected"),
    [
        (FakeNetworkException(412, UPSTREAM_TEXT), GatewayRateLimited),
        (FakeResponseCodeException(-404, UPSTREAM_TEXT), GatewayNotFound),
        (RuntimeError(UPSTREAM_TEXT), GatewayTransportError),
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
    assert UPSTREAM_TEXT not in str(caught.value)


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

    bilibili_api_seam.info_response = _detail_response()
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

    bilibili_api_seam.info_response = _detail_response(owner={"mid": MID + 1, "name": "别人"})
    gateway = _load_gateway()

    with pytest.raises(GatewayShapeError) as caught:
        asyncio.run(gateway.get_completed_video_summary(_summary(aid=None)))

    assert caught.value.code == "shape_error"


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
    """When the distribution is installed its version wins over the literal."""

    monkeypatch.setattr(
        importlib.metadata, "version", lambda _name: "17.4.2", raising=True
    )
    gateway = _load_gateway()

    assert gateway.get_package_version() == "17.4.2"


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
