"""The single deterministic offline fake for the Bilibili package seam.

Every package-seam test scripts these fakes instead of touching the pinned
``bilibili-api-python`` distribution or the network:

- ``FakeGateway`` is the plain ``BilibiliGateway`` protocol double used by
  the ingestor tests: scripted pages, parts, and summary completions with
  recorded fetch calls; unexpected fetches fail loudly instead of returning
  script-free data.
- ``FakeUpstreamScript`` / ``build_fake_package`` / ``bilibili_api_seam``
  install the fake ``bilibili_api`` package on ``sys.modules`` for the real
  adapter tests.  The fake mirrors only the documented import surface the
  adapter may use (``Credential``, ``request_settings.set_proxy`` /
  ``get_proxy``, the ``user`` endpoint description and ``access_id`` route,
  the WBI-signed ``utils.network.Api`` the user-video page call is issued
  through, ``video.Video.get_info`` / ``get_pages``, and the exceptions
  taxonomy) and exposes no playback, subtitle, audio, or download method, so
  a silent switch to another package API fails loudly instead of silently
  succeeding.  ``applied_proxies`` records every proxy the adapter hands to
  the package settings, so its apply-once behavior is asserted without a
  network call.
- ``FakeApiRequest`` with ``script.api_requests`` records every page request
  the adapter issues through the package's ``Api``: the transport flags it
  took from the package endpoint description (device-fingerprint ``dm``
  overridden) and the exact parameters it handed over, so the
  risk-control-relevant call shape is assertable without a network call.
  ``script.access_id_calls`` records the separate ``access_id`` token route
  (kept out of ``calls``: it is a memoized, best-effort token fetch, not a
  metadata call).
- ``script_parts_by_bvid`` scripts one parts payload per requested ``bvid``
  for seam tests that collect a page holding several distinct videos.
- ``DOCUMENTED_METADATA_CALLS`` with ``assert_only_documented_metadata_calls``
  pins the upstream call names the gateway may issue.
- ``NO_LEAK_MARKERS`` with ``assert_leaks_no_markers`` holds the
  realistic-looking secret and raw-payload sentinel texts (a SESSDATA
  value, a signed playback URL, a raw JSON response body, and raw upstream
  exception text) plus the scanner behind the no-secret assertions, and
  ``persisted_row_text`` renders persisted rows for those assertions.
"""

from __future__ import annotations

import dataclasses
import sys
import types
from enum import Enum

import pytest

MID = 23191782
BVID = "BV1AbCdEfGhJ"
PUBDATE = 1725859200

#: Package version the fake gateway reports for run metadata.
FAKE_PACKAGE_VERSION = "17.4.2"

#: Adapter module the seam fixture reloads against the installed fake.
GATEWAY_ADAPTER_MODULE = "bili_asr.sources.bilibili_api_gateway"

#: The package's own endpoint description for the user-video page call
#: (``bilibili_api.user.API["info"]["video"]``), mirroring the pinned
#: distribution literally — including ``dm: True``.  The adapter must take
#: ``url``/``method``/``verify``/``wbi`` from it and override ``dm``, so a
#: package-side change to any of those fields stays visible here.
FAKE_USER_VIDEO_PAGE_ENDPOINT = {
    "url": "https://api.bilibili.com/x/space/wbi/arc/search",
    "method": "GET",
    "verify": False,
    "wbi": True,
    "dm": True,
    "params": {
        "mid": "int: uid",
        "ps": "const int: 30",
        "tid": "int: 分区 ID，0 表示全部",
        "pn": "int: 页码",
        "keyword": "str: 关键词，可为空",
        "w_webid": "str: w_webid",
    },
    "comment": "搜索用户视频",
}

#: The exact upstream call names the gateway adapter may issue.  The page call
#: is recorded as ``space.arc.search`` because the adapter issues that request
#: itself through the package's ``Api``: the package's ``User.get_videos``
#: delegate cannot pass upstream risk control (it injects device-fingerprint
#: ``dm`` parameters and scrapes ``w_webid`` from a page that no longer
#: server-renders it).
DOCUMENTED_METADATA_CALLS = ("space.arc.search", "video.get_info", "video.get_pages")

#: Realistic-looking SESSDATA value that must never leave the process.
SESSDATA_BOUNDARY_VALUE = "SESSDATA-VALUE-THAT-MUST-NOT-LEAK"

#: Realistic-looking signed playback URL that must never be persisted.
SIGNED_URL_MARKER = (
    "https://upos.example.com/upyun/ssl/part.m4s?sign=SIGNED-URL-THAT-MUST-NOT-LEAK"
)

#: Realistic-looking raw JSON response body that must never be persisted.
RAW_JSON_BODY_MARKER = '{"code":-412,"message":"RAW-JSON-BODY-THAT-MUST-NOT-LEAK"}'

#: Realistic-looking raw upstream exception text that must never be persisted.
RAW_UPSTREAM_EXCEPTION_MARKER = "RAW-UPSTREAM-EXCEPTION-THAT-MUST-NOT-LEAK"

#: All sentinels the no-secret assertions scan persisted surfaces for.
NO_LEAK_MARKERS = (
    SESSDATA_BOUNDARY_VALUE,
    SIGNED_URL_MARKER,
    RAW_JSON_BODY_MARKER,
    RAW_UPSTREAM_EXCEPTION_MARKER,
)

#: One upstream failure message carrying every sentinel at once.
UPSTREAM_ERROR_TEXT = " ".join(
    (
        "RISK-CHALLENGE-PAYLOAD",
        SIGNED_URL_MARKER,
        RAW_JSON_BODY_MARKER,
        RAW_UPSTREAM_EXCEPTION_MARKER,
    )
)


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


def _device_fingerprint_params() -> dict:
    """Mirror of the package's ``_enc_dm`` injection: the same parameter names.

    A request built with ``dm`` enabled carries these parameters upstream, so
    the fake adds them too: the "no device-fingerprint parameters are sent"
    assertion then detects the real risk-control defect instead of merely
    restating the recorded ``dm`` flag.
    """

    return {
        "dm_img_list": "[]",
        "dm_img_str": "AB",
        "dm_cover_img_str": "AB",
        "dm_img_inter": '{"ds":[],"wh":[0,0,0],"of":[0,0,0]}',
    }


@dataclasses.dataclass
class FakeApiRequest:
    """One recorded package-``Api`` request: the call shape that was issued.

    ``params`` is the exact mapping the adapter handed to ``update_params``,
    captured when the request was issued, with the package's
    device-fingerprint injection mirrored when ``dm`` is on.
    """

    url: str
    method: str
    verify: bool
    wbi: bool
    dm: bool
    params: dict


@dataclasses.dataclass
class FakeUpstreamScript:
    """Scripted upstream behavior; records every call the gateway makes.

    A scripted page response may be a plain value or a callable receiving the
    documented page parameters (``pn``, ``ps``) so per-page behavior can be
    scripted for multi-page runs.  The scripted ``parts_response`` may
    likewise be a plain value or a callable receiving the requested
    ``bvid``, so each video's parts can be scripted independently (see
    :func:`script_parts_by_bvid`).

    ``videos_response`` / ``videos_error`` script the user-video page request
    the adapter issues through the package ``Api``; ``access_id`` /
    ``access_id_error`` script the separate ``access_id`` token route
    (``None`` by default, which is what the route currently yields in
    production).  ``user_video_page_endpoint`` is the package-side endpoint
    description the adapter must read its transport fields from; a test may
    rewrite it before the adapter module is (re-)imported.
    """

    videos_response: object = None
    videos_error: BaseException | None = None
    parts_response: object = None
    parts_error: BaseException | None = None
    info_response: object = None
    info_error: BaseException | None = None
    access_id: str | None = None
    access_id_error: BaseException | None = None
    user_video_page_endpoint: dict = dataclasses.field(
        default_factory=lambda: dict(FAKE_USER_VIDEO_PAGE_ENDPOINT)
    )
    calls: list[str] = dataclasses.field(default_factory=list)
    access_id_calls: list[str] = dataclasses.field(default_factory=list)
    api_requests: list[FakeApiRequest] = dataclasses.field(default_factory=list)
    applied_proxies: list[str] = dataclasses.field(default_factory=list)


class FakeGateway:
    """Scripted ``BilibiliGateway`` protocol double for ingestor tests.

    Unexpected fetches fail loudly instead of returning script-free data;
    a scripted ``BaseException`` value is raised as-is.
    """

    def __init__(self, package_version: str = FAKE_PACKAGE_VERSION) -> None:
        self.package_version = package_version
        self.page_calls: list[tuple[int, int, int]] = []
        self.parts_calls: list[str] = []
        self.completion_calls: list[str] = []
        self._pages: dict[int, object] = {}
        self._parts: dict[str, object] = {}
        self._completions: dict[str, object] = {}

    def script_page(self, page_number: int, page: object) -> None:
        self._pages[page_number] = page

    def script_parts(self, bvid: str, parts: object) -> None:
        self._parts[bvid] = parts

    def script_completion(self, bvid: str, completed: object) -> None:
        self._completions[bvid] = completed

    async def get_user_video_page(
        self, mid: int, page_number: int, page_size: int = 30
    ) -> UserVideoPage:
        self.page_calls.append((mid, page_number, page_size))
        return self._scripted(self._pages, page_number, "user-video-page")

    async def get_video_parts(self, bvid: str) -> tuple[VideoPart, ...]:
        self.parts_calls.append(bvid)
        return self._scripted(self._parts, bvid, "video-parts")

    async def get_completed_video_summary(self, summary: VideoSummary) -> VideoSummary:
        self.completion_calls.append(summary.bvid)
        return self._scripted(self._completions, summary.bvid, "completed-summary")

    def get_package_version(self) -> str:
        return self.package_version

    @staticmethod
    def _scripted(script: dict, key: object, what: str) -> object:
        if key not in script:
            raise AssertionError(f"unexpected {what} fetch: {key!r}")
        value = script[key]
        if isinstance(value, BaseException):
            raise value
        return value


def build_fake_package(script: FakeUpstreamScript) -> dict[str, types.ModuleType]:
    """Build the fake ``bilibili_api`` package with the documented surface."""

    package = types.ModuleType("bilibili_api")

    class Credential:
        def __init__(self, sessdata: str | None = None) -> None:
            self.sessdata = sessdata

    package.Credential = Credential

    request_settings_mod = types.ModuleType("bilibili_api.request_settings")

    def set_proxy(proxy: str = "") -> None:
        """Mirror of ``request_settings.set_proxy``; records the applied value."""

        script.applied_proxies.append(proxy)

    def get_proxy() -> str:
        """Mirror of ``request_settings.get_proxy`` (``""`` before any set)."""

        return script.applied_proxies[-1] if script.applied_proxies else ""

    request_settings_mod.set_proxy = set_proxy
    request_settings_mod.get_proxy = get_proxy

    exceptions_mod = types.ModuleType("bilibili_api.exceptions")
    exceptions_mod.ApiException = FakeApiException
    exceptions_mod.NetworkException = FakeNetworkException
    exceptions_mod.ResponseCodeException = FakeResponseCodeException
    exceptions_mod.ResponseException = FakeResponseException
    exceptions_mod.WbiRetryTimesExceedException = FakeWbiRetryTimesExceedException

    user_mod = types.ModuleType("bilibili_api.user")

    class VideoOrder(Enum):
        """Mirror of ``user.VideoOrder`` (only the default order is exposed)."""

        PUBDATE = "pubdate"

    class User:
        """Mirror of ``user.User(uid, credential)`` with only the access_id route.

        The user-video page data no longer flows through this class: the
        adapter issues the endpoint description's request itself through the
        package ``Api``.
        """

        def __init__(self, uid: int, credential: object = None) -> None:
            self.uid = uid
            self.credential = credential

        async def get_access_id(self) -> str | None:
            script.access_id_calls.append(f"user.get_access_id(uid={self.uid})")
            if script.access_id_error is not None:
                raise script.access_id_error
            return script.access_id

    user_mod.API = {"info": {"video": script.user_video_page_endpoint}}
    user_mod.User = User
    user_mod.VideoOrder = VideoOrder

    network_mod = types.ModuleType("bilibili_api.utils.network")

    class Api:
        """Mirror of ``utils.network.Api`` for the documented page request.

        The package's ``Api`` is built from an endpoint description whose
        ``url``/``method``/``verify``/``wbi`` the adapter must state and whose
        ``dm`` it must override, so those fields are required here and are
        recorded with the parameters of the issued request.  ``result``
        answers with the scripted page payload or raises the scripted
        failure.  Only the local request shaping under test is mirrored (the
        ``dm`` parameter injection); signing, cookies, and retries are not,
        because the adapter may not depend on them.
        """

        def __init__(
            self,
            url: str,
            method: str,
            verify: bool,
            wbi: bool,
            dm: bool,
            credential: object = None,
        ) -> None:
            self.url = url
            self.method = method
            self.verify = verify
            self.wbi = wbi
            self.dm = dm
            self.credential = credential
            self.params: dict = {}

        def update_params(self, **kwargs: object) -> "Api":
            """Mirror of ``Api.update_params`` (replaces the parameters)."""

            self.params = dict(kwargs)
            return self

        @property
        async def result(self) -> object:
            """Mirror of ``Api.result``: record, then answer or fail."""

            params = dict(self.params)
            if self.dm:
                params.update(_device_fingerprint_params())
            page_number = params.get("pn")
            page_size = params.get("ps")
            script.api_requests.append(
                FakeApiRequest(
                    url=self.url,
                    method=self.method,
                    verify=self.verify,
                    wbi=self.wbi,
                    dm=self.dm,
                    params=params,
                )
            )
            script.calls.append(f"space.arc.search(pn={page_number}, ps={page_size})")
            if script.videos_error is not None:
                raise script.videos_error
            response = script.videos_response
            if callable(response):
                response = response(pn=page_number, ps=page_size)
            return response

    network_mod.Api = Api

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
            response = script.parts_response
            if callable(response):
                response = response(bvid=self.bvid)
            return response

    video_mod.Video = Video

    package.user = user_mod
    package.video = video_mod
    package.exceptions = exceptions_mod
    package.request_settings = request_settings_mod

    return {
        "bilibili_api": package,
        "bilibili_api.user": user_mod,
        "bilibili_api.utils.network": network_mod,
        "bilibili_api.video": video_mod,
        "bilibili_api.exceptions": exceptions_mod,
        "bilibili_api.request_settings": request_settings_mod,
    }


def make_vlist_item(**overrides: object) -> dict:
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


def make_videos_response(*items: object, count: int | None = 2) -> dict:
    """Build the inner arc/search data: ``list.vlist`` plus ``page.count``."""

    response: dict = {"list": {"vlist": list(items)}}
    if count is not None:
        response["page"] = {"pn": 1, "ps": 30, "count": count}
    return response


def make_part_item(**overrides: object) -> dict:
    """Build one documented pagelist element with literal values."""

    item = {
        "cid": 2222,
        "page": 1,
        "part": "第一部分",
        "duration": 12,
    }
    item.update(overrides)
    return item


def script_parts_by_bvid(
    script: FakeUpstreamScript, parts_by_bvid: dict[str, object]
) -> None:
    """Script one parts payload per requested ``bvid`` on the package seam.

    ``video.Video.get_pages`` answers with the scripted entry for its own
    ``bvid``; an unexpected bvid fails loudly like every other unscripted
    fetch.  A plain ``parts_response`` value keeps the previous behavior of
    answering every video with the same list.
    """

    def parts_response(bvid: str) -> object:
        if bvid not in parts_by_bvid:
            raise AssertionError(f"unexpected video-parts fetch: {bvid!r}")
        return parts_by_bvid[bvid]

    script.parts_response = parts_response


def make_detail_response(**overrides: object) -> dict:
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


def persisted_row_text(connection: object) -> str:
    """Render every persisted row of every table and view as one text blob.

    The no-secret assertions scan this blob so a leaked sentinel anywhere in
    the repository is caught, not only in one hand-picked table.
    """

    persisted_objects = connection.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
        " AND name NOT LIKE 'sqlite_%' ORDER BY type, name"
    ).fetchall()
    lines = []
    for persisted_object in persisted_objects:
        object_name = persisted_object["name"]
        for row in connection.execute(f"SELECT * FROM {object_name}"):
            lines.append(f"{object_name}:{tuple(row)!r}")
    return "\n".join(lines)


def assert_only_documented_metadata_calls(
    calls: object, *, context: str = "gateway calls"
) -> None:
    """Assert every recorded upstream call stays on the documented surface."""

    unexpected = [
        call for call in calls if not call.startswith(DOCUMENTED_METADATA_CALLS)
    ]
    if unexpected:
        raise AssertionError(
            f"{context} left the documented metadata surface: {unexpected}"
        )


def assert_leaks_no_markers(text: str, *, context: str) -> None:
    """Assert the text carries none of the seam's secret/payload sentinels."""

    leaked = [marker for marker in NO_LEAK_MARKERS if marker in text]
    if leaked:
        raise AssertionError(f"{context} leaked seam payload sentinels: {leaked}")


@pytest.fixture
def bilibili_api_seam(monkeypatch) -> FakeUpstreamScript:
    """Install the fake ``bilibili_api`` package and yield its script.

    Only the adapter module is dropped from the module cache, before and
    after each test: it re-imports against the current seam, while every
    other ``bili_asr`` module stays cached so class identity is preserved
    between the test imports and the adapter imports.
    """

    script = FakeUpstreamScript()
    for name, module in build_fake_package(script).items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.delitem(sys.modules, GATEWAY_ADAPTER_MODULE, raising=False)
    try:
        yield script
    finally:
        sys.modules.pop(GATEWAY_ADAPTER_MODULE, None)


__all__ = [
    "BVID",
    "DOCUMENTED_METADATA_CALLS",
    "FAKE_PACKAGE_VERSION",
    "FAKE_USER_VIDEO_PAGE_ENDPOINT",
    "FakeApiException",
    "FakeApiRequest",
    "FakeGateway",
    "FakeNetworkException",
    "FakeResponseCodeException",
    "FakeResponseException",
    "FakeUpstreamScript",
    "FakeWbiRetryTimesExceedException",
    "GATEWAY_ADAPTER_MODULE",
    "MID",
    "NO_LEAK_MARKERS",
    "PUBDATE",
    "RAW_JSON_BODY_MARKER",
    "RAW_UPSTREAM_EXCEPTION_MARKER",
    "SESSDATA_BOUNDARY_VALUE",
    "SIGNED_URL_MARKER",
    "UPSTREAM_ERROR_TEXT",
    "assert_leaks_no_markers",
    "assert_only_documented_metadata_calls",
    "bilibili_api_seam",
    "build_fake_package",
    "make_detail_response",
    "make_part_item",
    "make_videos_response",
    "make_vlist_item",
    "persisted_row_text",
    "script_parts_by_bvid",
]
