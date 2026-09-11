# Task 3 Diff — 20260909-bilibili-api-ingestion

Base: `0c2c379`
Head: `783986a` (task body 6359e7d + live-smoke guard fix 783986a)

```diff
diff --git a/bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py b/bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py
new file mode 100644
index 0000000..f54a88b
--- /dev/null
+++ b/bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py
@@ -0,0 +1,415 @@
+"""The single deterministic offline fake for the Bilibili package seam.
+
+Every package-seam test scripts these fakes instead of touching the pinned
+``bilibili-api-python`` distribution or the network:
+
+- ``FakeGateway`` is the plain ``BilibiliGateway`` protocol double used by
+  the ingestor tests: scripted pages, parts, and summary completions with
+  recorded fetch calls; unexpected fetches fail loudly instead of returning
+  script-free data.
+- ``FakeUpstreamScript`` / ``build_fake_package`` / ``bilibili_api_seam``
+  install the fake ``bilibili_api`` package on ``sys.modules`` for the real
+  adapter tests.  The fake mirrors only the documented import surface the
+  adapter may use (``Credential``, ``user.User.get_videos``,
+  ``video.Video.get_info``/``get_pages``, and the exceptions taxonomy) and
+  exposes no playback, subtitle, audio, or download method, so a silent
+  switch to another package API fails loudly instead of silently
+  succeeding.
+- ``DOCUMENTED_METADATA_CALLS`` with ``assert_only_documented_metadata_calls``
+  pins the upstream call names the gateway may issue.
+- ``NO_LEAK_MARKERS`` with ``assert_leaks_no_markers`` holds the
+  realistic-looking secret and raw-payload sentinel texts (a SESSDATA
+  value, a signed playback URL, a raw JSON response body, and raw upstream
+  exception text) plus the scanner behind the no-secret assertions, and
+  ``persisted_row_text`` renders persisted rows for those assertions.
+"""
+
+from __future__ import annotations
+
+import dataclasses
+import sys
+import types
+
+import pytest
+
+MID = 23191782
+BVID = "BV1AbCdEfGhJ"
+PUBDATE = 1725859200
+
+#: Package version the fake gateway reports for run metadata.
+FAKE_PACKAGE_VERSION = "17.4.2"
+
+#: Adapter module the seam fixture reloads against the installed fake.
+GATEWAY_ADAPTER_MODULE = "bili_asr.sources.bilibili_api_gateway"
+
+#: The exact upstream call names the gateway adapter may issue.
+DOCUMENTED_METADATA_CALLS = ("user.get_videos", "video.get_info", "video.get_pages")
+
+#: Realistic-looking SESSDATA value that must never leave the process.
+SESSDATA_BOUNDARY_VALUE = "SESSDATA-VALUE-THAT-MUST-NOT-LEAK"
+
+#: Realistic-looking signed playback URL that must never be persisted.
+SIGNED_URL_MARKER = (
+    "https://upos.example.com/upyun/ssl/part.m4s?sign=SIGNED-URL-THAT-MUST-NOT-LEAK"
+)
+
+#: Realistic-looking raw JSON response body that must never be persisted.
+RAW_JSON_BODY_MARKER = '{"code":-412,"message":"RAW-JSON-BODY-THAT-MUST-NOT-LEAK"}'
+
+#: Realistic-looking raw upstream exception text that must never be persisted.
+RAW_UPSTREAM_EXCEPTION_MARKER = "RAW-UPSTREAM-EXCEPTION-THAT-MUST-NOT-LEAK"
+
+#: All sentinels the no-secret assertions scan persisted surfaces for.
+NO_LEAK_MARKERS = (
+    SESSDATA_BOUNDARY_VALUE,
+    SIGNED_URL_MARKER,
+    RAW_JSON_BODY_MARKER,
+    RAW_UPSTREAM_EXCEPTION_MARKER,
+)
+
+#: One upstream failure message carrying every sentinel at once.
+UPSTREAM_ERROR_TEXT = " ".join(
+    (
+        "RISK-CHALLENGE-PAYLOAD",
+        SIGNED_URL_MARKER,
+        RAW_JSON_BODY_MARKER,
+        RAW_UPSTREAM_EXCEPTION_MARKER,
+    )
+)
+
+
+class FakeApiException(Exception):
+    """Mirror of ``bilibili_api.exceptions.ApiException``."""
+
+    def __init__(self, msg: str = "出现了错误，但是未说明具体原因。") -> None:
+        super().__init__(msg)
+        self.msg = msg
+
+
+class FakeNetworkException(FakeApiException):
+    """Mirror of ``NetworkException(status, msg)`` carrying the HTTP status."""
+
+    def __init__(self, status: int, msg: str) -> None:
+        super().__init__(msg)
+        self.status = status
+
+
+class FakeResponseCodeException(FakeApiException):
+    """Mirror of ``ResponseCodeException(code, msg, raw)`` carrying the code."""
+
+    def __init__(self, code: int, msg: str, raw: object = None) -> None:
+        super().__init__(msg)
+        self.code = code
+
+
+class FakeResponseException(FakeApiException):
+    """Mirror of ``ResponseException(msg)``."""
+
+    def __init__(self, msg: str) -> None:
+        super().__init__(msg)
+
+
+class FakeWbiRetryTimesExceedException(FakeApiException):
+    """Mirror of ``WbiRetryTimesExceedException()`` (WBI retry budget gone)."""
+
+    def __init__(self) -> None:
+        super().__init__("WBI 重试达到最大次数")
+
+
+@dataclasses.dataclass
+class FakeUpstreamScript:
+    """Scripted upstream behavior; records every call the gateway makes.
+
+    A scripted response may be a plain value or a callable receiving the
+    documented page parameters (``pn``, ``ps``) so per-page behavior can be
+    scripted for multi-page runs.
+    """
+
+    videos_response: object = None
+    videos_error: BaseException | None = None
+    parts_response: object = None
+    parts_error: BaseException | None = None
+    info_response: object = None
+    info_error: BaseException | None = None
+    calls: list[str] = dataclasses.field(default_factory=list)
+
+
+class FakeGateway:
+    """Scripted ``BilibiliGateway`` protocol double for ingestor tests.
+
+    Unexpected fetches fail loudly instead of returning script-free data;
+    a scripted ``BaseException`` value is raised as-is.
+    """
+
+    def __init__(self, package_version: str = FAKE_PACKAGE_VERSION) -> None:
+        self.package_version = package_version
+        self.page_calls: list[tuple[int, int, int]] = []
+        self.parts_calls: list[str] = []
+        self.completion_calls: list[str] = []
+        self._pages: dict[int, object] = {}
+        self._parts: dict[str, object] = {}
+        self._completions: dict[str, object] = {}
+
+    def script_page(self, page_number: int, page: object) -> None:
+        self._pages[page_number] = page
+
+    def script_parts(self, bvid: str, parts: object) -> None:
+        self._parts[bvid] = parts
+
+    def script_completion(self, bvid: str, completed: object) -> None:
+        self._completions[bvid] = completed
+
+    async def get_user_video_page(
+        self, mid: int, page_number: int, page_size: int = 100
+    ) -> UserVideoPage:
+        self.page_calls.append((mid, page_number, page_size))
+        return self._scripted(self._pages, page_number, "user-video-page")
+
+    async def get_video_parts(self, bvid: str) -> tuple[VideoPart, ...]:
+        self.parts_calls.append(bvid)
+        return self._scripted(self._parts, bvid, "video-parts")
+
+    async def get_completed_video_summary(self, summary: VideoSummary) -> VideoSummary:
+        self.completion_calls.append(summary.bvid)
+        return self._scripted(self._completions, summary.bvid, "completed-summary")
+
+    def get_package_version(self) -> str:
+        return self.package_version
+
+    @staticmethod
+    def _scripted(script: dict, key: object, what: str) -> object:
+        if key not in script:
+            raise AssertionError(f"unexpected {what} fetch: {key!r}")
+        value = script[key]
+        if isinstance(value, BaseException):
+            raise value
+        return value
+
+
+def build_fake_package(script: FakeUpstreamScript) -> dict[str, types.ModuleType]:
+    """Build the fake ``bilibili_api`` package with the documented surface."""
+
+    package = types.ModuleType("bilibili_api")
+
+    class Credential:
+        def __init__(self, sessdata: str | None = None) -> None:
+            self.sessdata = sessdata
+
+    package.Credential = Credential
+
+    exceptions_mod = types.ModuleType("bilibili_api.exceptions")
+    exceptions_mod.ApiException = FakeApiException
+    exceptions_mod.NetworkException = FakeNetworkException
+    exceptions_mod.ResponseCodeException = FakeResponseCodeException
+    exceptions_mod.ResponseException = FakeResponseException
+    exceptions_mod.WbiRetryTimesExceedException = FakeWbiRetryTimesExceedException
+
+    user_mod = types.ModuleType("bilibili_api.user")
+
+    class User:
+        """Mirror of ``user.User(uid, credential)`` with only get_videos."""
+
+        def __init__(self, uid: int, credential: object = None) -> None:
+            self.uid = uid
+            self.credential = credential
+
+        async def get_videos(
+            self,
+            tid: int = 0,
+            pn: int = 1,
+            ps: int = 30,
+            keyword: str = "",
+            order: object = None,
+        ) -> dict:
+            script.calls.append(f"user.get_videos(pn={pn}, ps={ps})")
+            if script.videos_error is not None:
+                raise script.videos_error
+            response = script.videos_response
+            if callable(response):
+                response = response(pn=pn, ps=ps)
+            return response
+
+    user_mod.User = User
+
+    video_mod = types.ModuleType("bilibili_api.video")
+
+    class Video:
+        """Mirror of ``video.Video(bvid, credential)`` with metadata calls only."""
+
+        def __init__(
+            self,
+            bvid: str | None = None,
+            aid: int | None = None,
+            credential: object = None,
+        ) -> None:
+            self.bvid = bvid
+            self.aid = aid
+            self.credential = credential
+
+        async def get_info(self) -> dict:
+            script.calls.append("video.get_info")
+            if script.info_error is not None:
+                raise script.info_error
+            return script.info_response
+
+        async def get_pages(self) -> list:
+            script.calls.append("video.get_pages")
+            if script.parts_error is not None:
+                raise script.parts_error
+            return script.parts_response
+
+    video_mod.Video = Video
+
+    package.user = user_mod
+    package.video = video_mod
+    package.exceptions = exceptions_mod
+
+    return {
+        "bilibili_api": package,
+        "bilibili_api.user": user_mod,
+        "bilibili_api.video": video_mod,
+        "bilibili_api.exceptions": exceptions_mod,
+    }
+
+
+def make_vlist_item(**overrides: object) -> dict:
+    """Build one documented arc/search vlist item with literal values."""
+
+    item = {
+        "aid": 111,
+        "bvid": BVID,
+        "title": "未明子讲座",
+        "created": PUBDATE,
+        "mid": MID,
+    }
+    item.update(overrides)
+    return item
+
+
+def make_videos_response(*items: object, count: int | None = 2) -> dict:
+    """Build the inner arc/search data: ``list.vlist`` plus ``page.count``."""
+
+    response: dict = {"list": {"vlist": list(items)}}
+    if count is not None:
+        response["page"] = {"pn": 1, "ps": 100, "count": count}
+    return response
+
+
+def make_part_item(**overrides: object) -> dict:
+    """Build one documented pagelist element with literal values."""
+
+    item = {
+        "cid": 2222,
+        "page": 1,
+        "part": "第一部分",
+        "duration": 12,
+    }
+    item.update(overrides)
+    return item
+
+
+def make_detail_response(**overrides: object) -> dict:
+    """Build the view-API detail body used to fill a missing aid."""
+
+    detail = {
+        "aid": 111,
+        "bvid": BVID,
+        "title": "未明子讲座",
+        "pubdate": PUBDATE,
+        "owner": {"mid": MID, "name": "未明子"},
+    }
+    detail.update(overrides)
+    return detail
+
+
+def persisted_row_text(connection: object) -> str:
+    """Render every persisted row of every table and view as one text blob.
+
+    The no-secret assertions scan this blob so a leaked sentinel anywhere in
+    the repository is caught, not only in one hand-picked table.
+    """
+
+    persisted_objects = connection.execute(
+        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
+        " AND name NOT LIKE 'sqlite_%' ORDER BY type, name"
+    ).fetchall()
+    lines = []
+    for persisted_object in persisted_objects:
+        object_name = persisted_object["name"]
+        for row in connection.execute(f"SELECT * FROM {object_name}"):
+            lines.append(f"{object_name}:{tuple(row)!r}")
+    return "\n".join(lines)
+
+
+def assert_only_documented_metadata_calls(
+    calls: object, *, context: str = "gateway calls"
+) -> None:
+    """Assert every recorded upstream call stays on the documented surface."""
+
+    unexpected = [
+        call for call in calls if not call.startswith(DOCUMENTED_METADATA_CALLS)
+    ]
+    if unexpected:
+        raise AssertionError(
+            f"{context} left the documented metadata surface: {unexpected}"
+        )
+
+
+def assert_leaks_no_markers(text: str, *, context: str) -> None:
+    """Assert the text carries none of the seam's secret/payload sentinels."""
+
+    leaked = [marker for marker in NO_LEAK_MARKERS if marker in text]
+    if leaked:
+        raise AssertionError(f"{context} leaked seam payload sentinels: {leaked}")
+
+
+@pytest.fixture
+def bilibili_api_seam(monkeypatch) -> FakeUpstreamScript:
+    """Install the fake ``bilibili_api`` package and yield its script.
+
+    Only the adapter module is dropped from the module cache, before and
+    after each test: it re-imports against the current seam, while every
+    other ``bili_asr`` module stays cached so class identity is preserved
+    between the test imports and the adapter imports.
+    """
+
+    script = FakeUpstreamScript()
+    for name, module in build_fake_package(script).items():
+        monkeypatch.setitem(sys.modules, name, module)
+    monkeypatch.delitem(sys.modules, GATEWAY_ADAPTER_MODULE, raising=False)
+    try:
+        yield script
+    finally:
+        sys.modules.pop(GATEWAY_ADAPTER_MODULE, None)
+
+
+__all__ = [
+    "BVID",
+    "DOCUMENTED_METADATA_CALLS",
+    "FAKE_PACKAGE_VERSION",
+    "FakeApiException",
+    "FakeGateway",
+    "FakeNetworkException",
+    "FakeResponseCodeException",
+    "FakeResponseException",
+    "FakeUpstreamScript",
+    "FakeWbiRetryTimesExceedException",
+    "GATEWAY_ADAPTER_MODULE",
+    "MID",
+    "NO_LEAK_MARKERS",
+    "PUBDATE",
+    "RAW_JSON_BODY_MARKER",
+    "RAW_UPSTREAM_EXCEPTION_MARKER",
+    "SESSDATA_BOUNDARY_VALUE",
+    "SIGNED_URL_MARKER",
+    "UPSTREAM_ERROR_TEXT",
+    "assert_leaks_no_markers",
+    "assert_only_documented_metadata_calls",
+    "bilibili_api_seam",
+    "build_fake_package",
+    "make_detail_response",
+    "make_part_item",
+    "make_videos_response",
+    "make_vlist_item",
+    "persisted_row_text",
+]
diff --git a/bilibili-asr-archive/tests/test_bilibili_api_gateway.py b/bilibili-asr-archive/tests/test_bilibili_api_gateway.py
index a749125..c6fb7bc 100644
--- a/bilibili-asr-archive/tests/test_bilibili_api_gateway.py
+++ b/bilibili-asr-archive/tests/test_bilibili_api_gateway.py
@@ -2,26 +2,29 @@
 
 Every functional test runs against a fake ``bilibili_api`` package installed
 on ``sys.modules`` before the gateway module is (re-)imported, so neither the
-real package nor network access is ever required.  The fake mirrors only the
+real package nor network access is ever required.  The fake package seam, the
+shared scripted protocol double, and the secret/raw-payload sentinels live in
+``tests/fixtures/fake_bilibili_gateway.py``.  The fake mirrors only the
 documented import surface the gateway may use (``Credential``, ``user.User``,
 ``video.Video``, and the exceptions taxonomy) and exposes no playback,
 subtitle, audio, or download methods, which makes silent use of other package
-APIs impossible.  The import boundary itself is additionally inspected
-statically with AST over the package sources.
+APIs impossible.  The import boundary and the method surface itself are
+additionally inspected statically with AST over the package sources.  The
+only networked test is the opt-in live smoke, which skips unless
+``BILI_LIVE_SMOKE=1`` is set.
 """
 
 from __future__ import annotations
 
 import ast
 import asyncio
-import dataclasses
 import importlib
+import os
 import pathlib
-import sys
-import types
 
 import pytest
 
+from bili_asr.services.metadata_ingest import MetadataIngestor
 from bili_asr.sources.models import (
     GatewayNotFound,
     GatewayRateLimited,
@@ -32,12 +35,32 @@ from bili_asr.sources.models import (
     VideoPart,
     VideoSummary,
 )
+from bili_asr.storage.database import MetadataRepository, open_database
+from fixtures.fake_bilibili_gateway import (
+    BVID,
+    MID,
+    PUBDATE,
+    RAW_JSON_BODY_MARKER,
+    SESSDATA_BOUNDARY_VALUE,
+    SIGNED_URL_MARKER,
+    UPSTREAM_ERROR_TEXT,
+    FakeApiException,
+    FakeNetworkException,
+    FakeResponseCodeException,
+    FakeResponseException,
+    FakeUpstreamScript,
+    FakeWbiRetryTimesExceedException,
+    assert_leaks_no_markers,
+    bilibili_api_seam,
+    build_fake_package,
+    make_detail_response,
+    make_part_item,
+    make_videos_response,
+    make_vlist_item,
+    persisted_row_text,
+)
 
-MID = 23191782
-BVID = "BV1AbCdEfGhJ"
-PUBDATE = 1725859200
 PINNED_PACKAGE_VERSION = "17.4.2"
-SESSDATA_BOUNDARY_VALUE = "SESSDATA-VALUE-THAT-MUST-NOT-LEAK"
 
 #: The exact bilibili_api import surface the adapter is allowed to use.
 ALLOWED_PACKAGE_IMPORTS = {
@@ -53,162 +76,36 @@ ALLOWED_PACKAGE_IMPORTS = {
     },
 }
 
-UPSTREAM_TEXT = "RISK-CHALLENGE-PAYLOAD http://api.bilibili.com/x/secret"
-
-
-# ----------------------------------------------------------- fake package seam
-
-
-class FakeApiException(Exception):
-    """Mirror of ``bilibili_api.exceptions.ApiException``."""
-
-    def __init__(self, msg: str = "出现了错误，但是未说明具体原因。") -> None:
-        super().__init__(msg)
-        self.msg = msg
-
-
-class FakeNetworkException(FakeApiException):
-    """Mirror of ``NetworkException(status, msg)`` carrying the HTTP status."""
-
-    def __init__(self, status: int, msg: str) -> None:
-        super().__init__(msg)
-        self.status = status
-
-
-class FakeResponseCodeException(FakeApiException):
-    """Mirror of ``ResponseCodeException(code, msg, raw)`` carrying the code."""
-
-    def __init__(self, code: int, msg: str, raw: object = None) -> None:
-        super().__init__(msg)
-        self.code = code
-
-
-class FakeResponseException(FakeApiException):
-    """Mirror of ``ResponseException(msg)``."""
-
-    def __init__(self, msg: str) -> None:
-        super().__init__(msg)
-
-
-class FakeWbiRetryTimesExceedException(FakeApiException):
-    """Mirror of ``WbiRetryTimesExceedException()`` (WBI retry budget gone)."""
-
-    def __init__(self) -> None:
-        super().__init__("WBI 重试达到最大次数")
-
-
-@dataclasses.dataclass
-class FakeUpstreamScript:
-    """Scripted upstream behavior; records every call the gateway makes."""
-
-    videos_response: object = None
-    videos_error: BaseException | None = None
-    parts_response: object = None
-    parts_error: BaseException | None = None
-    info_response: object = None
-    info_error: BaseException | None = None
-    calls: list[str] = dataclasses.field(default_factory=list)
-
-
-def _build_fake_package(script: FakeUpstreamScript) -> dict[str, types.ModuleType]:
-    """Build the fake ``bilibili_api`` package with the documented surface."""
-
-    package = types.ModuleType("bilibili_api")
-
-    class Credential:
-        def __init__(self, sessdata: str | None = None) -> None:
-            self.sessdata = sessdata
-
-    package.Credential = Credential
-
-    exceptions_mod = types.ModuleType("bilibili_api.exceptions")
-    exceptions_mod.ApiException = FakeApiException
-    exceptions_mod.NetworkException = FakeNetworkException
-    exceptions_mod.ResponseCodeException = FakeResponseCodeException
-    exceptions_mod.ResponseException = FakeResponseException
-    exceptions_mod.WbiRetryTimesExceedException = FakeWbiRetryTimesExceedException
-
-    user_mod = types.ModuleType("bilibili_api.user")
-
-    class User:
-        """Mirror of ``user.User(uid, credential)`` with only get_videos."""
-
-        def __init__(self, uid: int, credential: object = None) -> None:
-            self.uid = uid
-            self.credential = credential
-
-        async def get_videos(
-            self,
-            tid: int = 0,
-            pn: int = 1,
-            ps: int = 30,
-            keyword: str = "",
-            order: object = None,
-        ) -> dict:
-            script.calls.append(f"user.get_videos(pn={pn}, ps={ps})")
-            if script.videos_error is not None:
-                raise script.videos_error
-            return script.videos_response
-
-    user_mod.User = User
-
-    video_mod = types.ModuleType("bilibili_api.video")
-
-    class Video:
-        """Mirror of ``video.Video(bvid, credential)`` with metadata calls only."""
-
-        def __init__(
-            self,
-            bvid: str | None = None,
-            aid: int | None = None,
-            credential: object = None,
-        ) -> None:
-            self.bvid = bvid
-            self.aid = aid
-            self.credential = credential
-
-        async def get_info(self) -> dict:
-            script.calls.append("video.get_info")
-            if script.info_error is not None:
-                raise script.info_error
-            return script.info_response
-
-        async def get_pages(self) -> list:
-            script.calls.append("video.get_pages")
-            if script.parts_error is not None:
-                raise script.parts_error
-            return script.parts_response
-
-    video_mod.Video = Video
-
-    package.user = user_mod
-    package.video = video_mod
-    package.exceptions = exceptions_mod
-
-    return {
-        "bilibili_api": package,
-        "bilibili_api.user": user_mod,
-        "bilibili_api.video": video_mod,
-        "bilibili_api.exceptions": exceptions_mod,
-    }
+#: The complete documented exception surface the fake seam must mirror.
+ALLOWED_EXCEPTION_NAMES = (
+    "ApiException",
+    "NetworkException",
+    "ResponseCodeException",
+    "ResponseException",
+    "WbiRetryTimesExceedException",
+)
 
+#: Attribute names that would mark playback/subtitle/audio/ASR/export usage.
+#: Tokens are matched as plain substrings, so only unambiguous names belong
+#: here (``stream`` would false-positive on ``_await_upstream``).
+FORBIDDEN_SEAM_METHOD_TOKENS = (
+    "subtitle",
+    "playback",
+    "playurl",
+    "play_url",
+    "download",
+    "danmaku",
+    "player",
+    "audio",
+    "asr",
+    "export",
+)
 
-@pytest.fixture
-def bilibili_api_seam(monkeypatch) -> FakeUpstreamScript:
-    """Install the fake package and yield its script.
 
-    Only the adapter module is dropped from the module cache, before and
-    after each test: it re-imports against the current seam, while every
-    other ``bili_asr`` module stays cached so class identity is preserved
-    between the test imports and the adapter imports.
-    """
+def _public_names(obj: object) -> list[str]:
+    """List the public (non-dunder) names on a module or class."""
 
-    script = FakeUpstreamScript()
-    for name, module in _build_fake_package(script).items():
-        monkeypatch.setitem(sys.modules, name, module)
-    monkeypatch.delitem(sys.modules, "bili_asr.sources.bilibili_api_gateway", raising=False)
-    yield script
-    sys.modules.pop("bili_asr.sources.bilibili_api_gateway", None)
+    return sorted(name for name in vars(obj) if not name.startswith("_"))
 
 
 def _load_gateway(sessdata: str | None = None):
@@ -221,56 +118,6 @@ def _load_gateway(sessdata: str | None = None):
 # --------------------------------------------------- deterministic factories
 
 
-def _vlist_item(**overrides: object) -> dict:
-    """Build one documented arc/search vlist item with literal values."""
-
-    item = {
-        "aid": 111,
-        "bvid": BVID,
-        "title": "未明子讲座",
-        "created": PUBDATE,
-        "mid": MID,
-    }
-    item.update(overrides)
-    return item
-
-
-def _videos_response(*items: dict, count: int | None = 2) -> dict:
-    """Build the inner arc/search data: ``list.vlist`` plus ``page.count``."""
-
-    response: dict = {"list": {"vlist": list(items)}}
-    if count is not None:
-        response["page"] = {"pn": 1, "ps": 100, "count": count}
-    return response
-
-
-def _part_item(**overrides: object) -> dict:
-    """Build one documented pagelist element with literal values."""
-
-    item = {
-        "cid": 2222,
-        "page": 1,
-        "part": "第一部分",
-        "duration": 12,
-    }
-    item.update(overrides)
-    return item
-
-
-def _detail_response(**overrides: object) -> dict:
-    """Build the view-API detail body used to fill a missing aid."""
-
-    detail = {
-        "aid": 111,
-        "bvid": BVID,
-        "title": "未明子讲座",
-        "pubdate": PUBDATE,
-        "owner": {"mid": MID, "name": "未明子"},
-    }
-    detail.update(overrides)
-    return detail
-
-
 def _summary(**overrides: object) -> VideoSummary:
     """Build one validated summary DTO; aid is missing by default."""
 
@@ -291,8 +138,8 @@ def _summary(**overrides: object) -> VideoSummary:
 def test_get_user_video_page_normalizes_documented_fields(bilibili_api_seam):
     """One bounded call maps vlist scalars into validated DTO fields."""
 
-    bilibili_api_seam.videos_response = _videos_response(
-        _vlist_item(title="  未明子讲座  "), count=7
+    bilibili_api_seam.videos_response = make_videos_response(
+        make_vlist_item(title="  未明子讲座  "), count=7
     )
     gateway = _load_gateway(sessdata=SESSDATA_BOUNDARY_VALUE)
 
@@ -319,7 +166,7 @@ def test_get_user_video_page_normalizes_documented_fields(bilibili_api_seam):
 def test_get_user_video_page_forwards_requested_page_and_size(bilibili_api_seam):
     """The adapter passes the documented page parameters only."""
 
-    bilibili_api_seam.videos_response = _videos_response(_vlist_item(), count=1)
+    bilibili_api_seam.videos_response = make_videos_response(make_vlist_item(), count=1)
     gateway = _load_gateway()
 
     asyncio.run(gateway.get_user_video_page(MID, page_number=4, page_size=50))
@@ -330,7 +177,7 @@ def test_get_user_video_page_forwards_requested_page_and_size(bilibili_api_seam)
 def test_get_user_video_page_tolerates_plain_list_container(bilibili_api_seam):
     """A plain ``list`` array instead of ``list.vlist`` normalizes too."""
 
-    bilibili_api_seam.videos_response = {"list": [_vlist_item()], "page": {"count": 3}}
+    bilibili_api_seam.videos_response = {"list": [make_vlist_item()], "page": {"count": 3}}
     gateway = _load_gateway()
 
     page = asyncio.run(gateway.get_user_video_page(MID, page_number=2))
@@ -342,7 +189,7 @@ def test_get_user_video_page_tolerates_plain_list_container(bilibili_api_seam):
 def test_get_user_video_page_observed_total_absent_is_none(bilibili_api_seam):
     """A response without a total field yields ``observed_total=None``."""
 
-    bilibili_api_seam.videos_response = _videos_response(_vlist_item(), count=None)
+    bilibili_api_seam.videos_response = make_videos_response(make_vlist_item(), count=None)
     gateway = _load_gateway()
 
     page = asyncio.run(gateway.get_user_video_page(MID, page_number=1))
@@ -353,7 +200,7 @@ def test_get_user_video_page_observed_total_absent_is_none(bilibili_api_seam):
 def test_get_user_video_page_accepts_pubdate_fallback_field(bilibili_api_seam):
     """An item carrying ``pubdate`` instead of ``created`` still normalizes."""
 
-    bilibili_api_seam.videos_response = _videos_response(
+    bilibili_api_seam.videos_response = make_videos_response(
         {"bvid": BVID, "aid": 111, "title": "未明子讲座", "pubdate": PUBDATE, "mid": MID},
         count=1,
     )
@@ -367,7 +214,7 @@ def test_get_user_video_page_accepts_pubdate_fallback_field(bilibili_api_seam):
 def test_get_user_video_page_returns_empty_page(bilibili_api_seam):
     """An empty vlist is a valid empty page."""
 
-    bilibili_api_seam.videos_response = _videos_response()
+    bilibili_api_seam.videos_response = make_videos_response()
     gateway = _load_gateway()
 
     page = asyncio.run(gateway.get_user_video_page(MID, page_number=5))
@@ -418,7 +265,7 @@ def test_get_user_video_page_rejects_unknown_list_shape(bilibili_api_seam):
 def test_get_user_video_page_rejects_foreign_owner_mid(bilibili_api_seam):
     """Items owned by another user are rejected as a bounded shape error."""
 
-    bilibili_api_seam.videos_response = _videos_response(_vlist_item(mid=MID + 1))
+    bilibili_api_seam.videos_response = make_videos_response(make_vlist_item(mid=MID + 1))
     gateway = _load_gateway()
 
     with pytest.raises(GatewayShapeError) as caught:
@@ -431,7 +278,7 @@ def test_get_user_video_page_rejects_foreign_owner_mid(bilibili_api_seam):
 def test_get_user_video_page_rejects_missing_owner_mid(bilibili_api_seam):
     """An item without an owner mid cannot prove ownership."""
 
-    bilibili_api_seam.videos_response = _videos_response(
+    bilibili_api_seam.videos_response = make_videos_response(
         {"bvid": BVID, "aid": 111, "title": "未明子讲座", "created": PUBDATE}
     )
     gateway = _load_gateway()
@@ -456,13 +303,13 @@ def test_get_user_video_page_rejects_missing_owner_mid(bilibili_api_seam):
         {"bvid": BVID, "title": "未明子讲座", "created": PUBDATE, "aid": "111", "mid": MID},
         {"bvid": BVID, "title": "未明子讲座", "created": PUBDATE, "mid": True},
         {"bvid": BVID, "title": "未明子讲座", "created": PUBDATE, "mid": "23191782"},
-        [_vlist_item()],
+        [make_vlist_item()],
     ],
 )
 def test_get_user_video_page_rejects_malformed_items(bilibili_api_seam, broken_item):
     """Every required scalar is validated before a DTO is returned."""
 
-    bilibili_api_seam.videos_response = _videos_response(broken_item)
+    bilibili_api_seam.videos_response = make_videos_response(broken_item)
     gateway = _load_gateway()
 
     with pytest.raises(GatewayShapeError):
@@ -473,7 +320,7 @@ def test_get_user_video_page_rejects_malformed_observed_total(bilibili_api_seam)
     """A present but non-integer total is a shape error, not a silent None."""
 
     bilibili_api_seam.videos_response = {
-        "list": {"vlist": [_vlist_item()]},
+        "list": {"vlist": [make_vlist_item()]},
         "page": {"count": "many"},
     }
     gateway = _load_gateway()
@@ -489,8 +336,8 @@ def test_get_video_parts_converts_page_index_and_duration(bilibili_api_seam):
     """One-based ``page`` and seconds become zero-based index and ms."""
 
     bilibili_api_seam.parts_response = [
-        _part_item(cid=2222, page=1, part="  第一部分  ", duration=12),
-        _part_item(cid=3333, page=3, part="第三部分", duration=10.5),
+        make_part_item(cid=2222, page=1, part="  第一部分  ", duration=12),
+        make_part_item(cid=3333, page=3, part="第三部分", duration=10.5),
     ]
     gateway = _load_gateway()
 
@@ -526,7 +373,7 @@ def test_get_video_parts_rejects_invalid_bvid_argument(bilibili_api_seam):
 def test_get_video_parts_tolerates_unknown_keys(bilibili_api_seam):
     """Unknown extra keys on a part item are ignored, not rejected."""
 
-    bilibili_api_seam.parts_response = [_part_item(dimension={"width": 1})]
+    bilibili_api_seam.parts_response = [make_part_item(dimension={"width": 1})]
     gateway = _load_gateway()
 
     parts = asyncio.run(gateway.get_video_parts(BVID))
@@ -552,7 +399,7 @@ def test_get_video_parts_tolerates_unknown_keys(bilibili_api_seam):
         {"cid": 2222, "page": 1, "part": "第一部分", "duration": -3},
         {"cid": 2222, "page": 1, "part": "第一部分", "duration": "12"},
         {"cid": 2222, "page": 1, "part": "第一部分", "duration": True},
-        [_part_item()],
+        [make_part_item()],
         "第一部分",
     ],
 )
@@ -582,20 +429,20 @@ def test_get_video_parts_rejects_non_list_response(bilibili_api_seam):
 @pytest.mark.parametrize(
     ("upstream_error", "expected"),
     [
-        (FakeNetworkException(412, UPSTREAM_TEXT), GatewayRateLimited),
-        (FakeNetworkException(429, UPSTREAM_TEXT), GatewayRateLimited),
-        (FakeNetworkException(404, UPSTREAM_TEXT), GatewayNotFound),
-        (FakeNetworkException(503, UPSTREAM_TEXT), GatewayTransportError),
-        (FakeResponseCodeException(-412, UPSTREAM_TEXT), GatewayRateLimited),
-        (FakeResponseCodeException(-352, UPSTREAM_TEXT), GatewayRateLimited),
-        (FakeResponseCodeException(-799, UPSTREAM_TEXT), GatewayRateLimited),
-        (FakeResponseCodeException(-404, UPSTREAM_TEXT), GatewayNotFound),
-        (FakeResponseCodeException(-62002, UPSTREAM_TEXT), GatewayNotFound),
-        (FakeResponseCodeException(-101, UPSTREAM_TEXT), GatewayResponseError),
-        (FakeResponseCodeException(-1, UPSTREAM_TEXT), GatewayResponseError),
-        (FakeResponseException(UPSTREAM_TEXT), GatewayResponseError),
+        (FakeNetworkException(412, UPSTREAM_ERROR_TEXT), GatewayRateLimited),
+        (FakeNetworkException(429, UPSTREAM_ERROR_TEXT), GatewayRateLimited),
+        (FakeNetworkException(404, UPSTREAM_ERROR_TEXT), GatewayNotFound),
+        (FakeNetworkException(503, UPSTREAM_ERROR_TEXT), GatewayTransportError),
+        (FakeResponseCodeException(-412, UPSTREAM_ERROR_TEXT), GatewayRateLimited),
+        (FakeResponseCodeException(-352, UPSTREAM_ERROR_TEXT), GatewayRateLimited),
+        (FakeResponseCodeException(-799, UPSTREAM_ERROR_TEXT), GatewayRateLimited),
+        (FakeResponseCodeException(-404, UPSTREAM_ERROR_TEXT), GatewayNotFound),
+        (FakeResponseCodeException(-62002, UPSTREAM_ERROR_TEXT), GatewayNotFound),
+        (FakeResponseCodeException(-101, UPSTREAM_ERROR_TEXT), GatewayResponseError),
+        (FakeResponseCodeException(-1, UPSTREAM_ERROR_TEXT), GatewayResponseError),
+        (FakeResponseException(UPSTREAM_ERROR_TEXT), GatewayResponseError),
         (FakeWbiRetryTimesExceedException(), GatewayRateLimited),
-        (RuntimeError(UPSTREAM_TEXT), GatewayTransportError),
+        (RuntimeError(UPSTREAM_ERROR_TEXT), GatewayTransportError),
     ],
 )
 def test_user_page_failures_map_onto_bounded_taxonomy(
@@ -611,15 +458,15 @@ def test_user_page_failures_map_onto_bounded_taxonomy(
 
     assert caught.value.code == expected.default_code
     # Raw exception text and URLs stay process-local: never in the mapped error.
-    assert UPSTREAM_TEXT not in str(caught.value)
+    assert UPSTREAM_ERROR_TEXT not in str(caught.value)
 
 
 @pytest.mark.parametrize(
     ("upstream_error", "expected"),
     [
-        (FakeNetworkException(412, UPSTREAM_TEXT), GatewayRateLimited),
-        (FakeResponseCodeException(-404, UPSTREAM_TEXT), GatewayNotFound),
-        (RuntimeError(UPSTREAM_TEXT), GatewayTransportError),
+        (FakeNetworkException(412, UPSTREAM_ERROR_TEXT), GatewayRateLimited),
+        (FakeResponseCodeException(-404, UPSTREAM_ERROR_TEXT), GatewayNotFound),
+        (RuntimeError(UPSTREAM_ERROR_TEXT), GatewayTransportError),
     ],
 )
 def test_part_failures_map_onto_bounded_taxonomy(
@@ -634,15 +481,15 @@ def test_part_failures_map_onto_bounded_taxonomy(
         asyncio.run(gateway.get_video_parts(BVID))
 
     assert caught.value.code == expected.default_code
-    assert UPSTREAM_TEXT not in str(caught.value)
+    assert UPSTREAM_ERROR_TEXT not in str(caught.value)
 
 
 @pytest.mark.parametrize(
     ("upstream_error", "expected"),
     [
-        (FakeNetworkException(412, UPSTREAM_TEXT), GatewayRateLimited),
-        (FakeResponseCodeException(-404, UPSTREAM_TEXT), GatewayNotFound),
-        (RuntimeError(UPSTREAM_TEXT), GatewayTransportError),
+        (FakeNetworkException(412, UPSTREAM_ERROR_TEXT), GatewayRateLimited),
+        (FakeResponseCodeException(-404, UPSTREAM_ERROR_TEXT), GatewayNotFound),
+        (RuntimeError(UPSTREAM_ERROR_TEXT), GatewayTransportError),
     ],
 )
 def test_completed_summary_failures_map_onto_bounded_taxonomy(
@@ -657,7 +504,7 @@ def test_completed_summary_failures_map_onto_bounded_taxonomy(
         asyncio.run(gateway.get_completed_video_summary(_summary(aid=None)))
 
     assert caught.value.code == expected.default_code
-    assert UPSTREAM_TEXT not in str(caught.value)
+    assert UPSTREAM_ERROR_TEXT not in str(caught.value)
 
 
 def test_shape_failure_does_not_expose_credential(bilibili_api_seam):
@@ -690,7 +537,7 @@ def test_completed_summary_short_circuits_when_aid_present(bilibili_api_seam):
 def test_completed_summary_fills_only_missing_aid(bilibili_api_seam):
     """A missing aid is filled from get_info; other fields are preserved."""
 
-    bilibili_api_seam.info_response = _detail_response()
+    bilibili_api_seam.info_response = make_detail_response()
     gateway = _load_gateway()
     summary = _summary(aid=None)
 
@@ -708,7 +555,7 @@ def test_completed_summary_fills_only_missing_aid(bilibili_api_seam):
 def test_completed_summary_rejects_foreign_detail_owner(bilibili_api_seam):
     """A detail response owned by another user is a bounded shape error."""
 
-    bilibili_api_seam.info_response = _detail_response(owner={"mid": MID + 1, "name": "别人"})
+    bilibili_api_seam.info_response = make_detail_response(owner={"mid": MID + 1, "name": "别人"})
     gateway = _load_gateway()
 
     with pytest.raises(GatewayShapeError) as caught:
@@ -899,3 +746,171 @@ def test_gateway_imports_stay_on_metadata_surface():
                     imports.setdefault(alias.name, set()).add(alias.name)
 
     assert imports == ALLOWED_PACKAGE_IMPORTS
+
+
+def test_gateway_source_never_names_forbidden_seam_methods():
+    """The adapter source never references playback/subtitle/audio names."""
+
+    gateway_path = (
+        pathlib.Path(__file__).resolve().parent.parent
+        / "src"
+        / "bili_asr"
+        / "sources"
+        / "bilibili_api_gateway.py"
+    )
+    tree = ast.parse(gateway_path.read_text(encoding="utf-8"))
+    attribute_names = {
+        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
+    }
+
+    forbidden_hits = sorted(
+        name
+        for name in attribute_names
+        for token in FORBIDDEN_SEAM_METHOD_TOKENS
+        if token in name.lower()
+    )
+
+    assert forbidden_hits == []
+    # Positive control: the scan sees the documented metadata attribute calls.
+    assert {"get_videos", "get_pages", "get_info"} <= attribute_names
+
+
+def test_fake_seam_exposes_only_documented_metadata_surface():
+    """The offline seam exposes exactly the documented metadata methods."""
+
+    modules = build_fake_package(FakeUpstreamScript())
+    package = modules["bilibili_api"]
+
+    assert _public_names(modules["bilibili_api.user"]) == ["User"]
+    assert _public_names(modules["bilibili_api.video"]) == ["Video"]
+    assert _public_names(modules["bilibili_api.exceptions"]) == sorted(
+        ALLOWED_EXCEPTION_NAMES
+    )
+    assert _public_names(package) == ["Credential", "exceptions", "user", "video"]
+    assert _public_names(package.Credential) == []
+
+    user = package.user.User(uid=MID)
+    video = package.video.Video(bvid=BVID)
+    for surface_name in (
+        "get_subtitles",
+        "get_subtitle",
+        "get_play_url",
+        "get_player_info",
+        "get_download_url",
+        "get_danmaku",
+        "download",
+        "get_audio",
+    ):
+        with pytest.raises(AttributeError):
+            getattr(user, surface_name)
+        with pytest.raises(AttributeError):
+            getattr(video, surface_name)
+
+
+def test_gateway_dto_drops_unknown_upstream_payload_fields(bilibili_api_seam):
+    """Unknown payload keys never surface on any gateway DTO string form."""
+
+    bilibili_api_seam.videos_response = make_videos_response(
+        make_vlist_item(
+            aid=None,
+            sessdata_note=SESSDATA_BOUNDARY_VALUE,
+            frame_url=SIGNED_URL_MARKER,
+            raw_note=RAW_JSON_BODY_MARKER,
+        ),
+        count=1,
+    )
+    bilibili_api_seam.parts_response = [make_part_item(player_note=SIGNED_URL_MARKER)]
+    bilibili_api_seam.info_response = make_detail_response(raw_body=RAW_JSON_BODY_MARKER)
+    gateway = _load_gateway(sessdata=SESSDATA_BOUNDARY_VALUE)
+
+    page = asyncio.run(gateway.get_user_video_page(MID, page_number=1))
+    completed = asyncio.run(gateway.get_completed_video_summary(page.videos[0]))
+    parts = asyncio.run(gateway.get_video_parts(BVID))
+
+    assert completed.aid == 111  # the get_info completion path ran
+    for surface in (page, completed, parts):
+        assert_leaks_no_markers(repr(surface), context="gateway DTO repr")
+        assert_leaks_no_markers(str(surface), context="gateway DTO str")
+    assert bilibili_api_seam.calls == [
+        "user.get_videos(pn=1, ps=100)",
+        "video.get_info",
+        "video.get_pages",
+    ]
+
+
+# ------------------------------------------------------------- live smoke
+
+
+LIVE_SMOKE_ENV = "BILI_LIVE_SMOKE"
+
+#: Tokens that must never appear in the live smoke's persisted rows: cookie
+#: names and playback-CDN signature markers indicate credential or playback
+#: leakage rather than ordinary metadata.
+LIVE_HYGIENE_TOKENS = ("sessdata", "pssign", "bilivideo.com")
+
+
+def _live_smoke_requested() -> bool:
+    """True only when the operator explicitly opts in via the environment."""
+
+    return os.environ.get(LIVE_SMOKE_ENV, "") == "1"
+
+
+def test_live_smoke_single_public_page_for_archive_owner(tmp_root):
+    """Opt-in live probe: ONE public metadata page for UID 23191782.
+
+    Skipped unless the operator sets ``BILI_LIVE_SMOKE=1``.  The probe
+    requests exactly one bounded page (``ps=100``) for the archive owner
+    through the real adapter, ingests it into a fresh temporary SQLite
+    database, calls no subtitle/playback/audio/ASR/export endpoint,
+    requires no credential, and keeps every raw upstream payload
+    process-local.
+    """
+
+    if not _live_smoke_requested():
+        pytest.skip(f"live smoke is opt-in: set {LIVE_SMOKE_ENV}=1 to request it")
+
+    try:
+        gateway = _load_gateway()
+    except ImportError as error:
+        pytest.fail(
+            "live smoke was requested but the pinned package is not importable"
+            f" in this environment ({error}); install bilibili-api-python=="
+            f"{PINNED_PACKAGE_VERSION} (uv sync) first"
+        )
+
+    assert gateway.get_package_version() == PINNED_PACKAGE_VERSION
+    connection = open_database(os.path.join(tmp_root, "live-smoke.sqlite"))
+    try:
+        repository = MetadataRepository(connection)
+        result = MetadataIngestor(gateway, repository).collect_user_pages(
+            MID, start_page=1, page_limit=1
+        )
+
+        # Bounded: exactly one requested page and one page-evidence row.
+        assert result.page_count == 1
+        if result.outcome in ("failed", "risk_interrupted"):
+            pytest.fail(
+                "live one-page smoke ended in a bounded upstream failure"
+                f" (code={result.error_code!r}); rerun when upstream recovers"
+            )
+        assert result.outcome in ("complete", "limited")
+
+        persisted = persisted_row_text(connection)
+        scan_text = (persisted + repr(result)).lower()
+        for token in LIVE_HYGIENE_TOKENS:
+            assert token not in scan_text, f"live smoke persisted {token!r}"
+
+        video_rows = connection.execute(
+            "SELECT bvid, mid, title FROM videos ORDER BY bvid"
+        ).fetchall()
+        assert {row["mid"] for row in video_rows} <= {MID}
+        for row in video_rows:
+            assert row["bvid"].startswith("BV") and len(row["bvid"]) == 12
+            assert row["title"].strip()
+        for cid, duration_ms in (
+            tuple(row)
+            for row in connection.execute("SELECT cid, duration_ms FROM video_parts")
+        ):
+            assert cid >= 1 and duration_ms >= 1
+    finally:
+        connection.close()
diff --git a/bilibili-asr-archive/tests/test_metadata_ingest.py b/bilibili-asr-archive/tests/test_metadata_ingest.py
index 41c0fdc..287d4af 100644
--- a/bilibili-asr-archive/tests/test_metadata_ingest.py
+++ b/bilibili-asr-archive/tests/test_metadata_ingest.py
@@ -1,15 +1,21 @@
 """Offline ingestor contract tests: resumable normalized metadata collection.
 
-Every test runs :class:`MetadataIngestor` against a fake
-``BilibiliGateway`` protocol double (plain dataclasses, no ``bilibili_api``
-import, no network) and a real Plan-1 repository over a temporary SQLite
-database, so each test observes the normalized rows a collection run leaves
-behind.  Unexpected gateway fetches fail loudly instead of returning
-script-free data.
+Every test runs :class:`MetadataIngestor` against the shared fake
+``BilibiliGateway`` protocol double from ``tests/fixtures/fake_bilibili_gateway.py``
+(scripted pages, parts, and completions; no ``bilibili_api`` import, no
+network) and a real Plan-1 repository over a temporary SQLite database, so
+each test observes the normalized rows a collection run leaves behind.
+Unexpected gateway fetches fail loudly instead of returning script-free
+data.  The package-seam tests at the end drive the real product adapter
+(:class:`~bili_asr.sources.bilibili_api_gateway.BilibiliApiGateway`) over
+the same module's fake ``bilibili_api`` package seam, still fully offline.
 """
 
 from __future__ import annotations
 
+import importlib
+import sqlite3
+
 import pytest
 
 from bili_asr.services.metadata_ingest import (
@@ -27,60 +33,30 @@ from bili_asr.sources.models import (
     VideoSummary,
 )
 from bili_asr.storage.database import MetadataRepository, open_database
+from fixtures.fake_bilibili_gateway import (
+    NO_LEAK_MARKERS,
+    RAW_JSON_BODY_MARKER,
+    RAW_UPSTREAM_EXCEPTION_MARKER,
+    SESSDATA_BOUNDARY_VALUE,
+    SIGNED_URL_MARKER,
+    UPSTREAM_ERROR_TEXT,
+    FakeResponseCodeException,
+    FakeGateway,
+    assert_leaks_no_markers,
+    assert_only_documented_metadata_calls,
+    bilibili_api_seam,
+    make_detail_response,
+    make_part_item,
+    make_videos_response,
+    make_vlist_item,
+    persisted_row_text,
+)
 
 MID = 23191782
 PACKAGE_VERSION = "17.4.2"
 PUBDATE = 1_725_859_200
 
 
-class FakeGateway:
-    """Scripted protocol double; unexpected fetches fail the test loudly."""
-
-    def __init__(self) -> None:
-        self.package_version = PACKAGE_VERSION
-        self.page_calls: list[tuple[int, int, int]] = []
-        self.parts_calls: list[str] = []
-        self.completion_calls: list[str] = []
-        self._pages: dict[int, object] = {}
-        self._parts: dict[str, object] = {}
-        self._completions: dict[str, object] = {}
-
-    def script_page(self, page_number: int, page: object) -> None:
-        self._pages[page_number] = page
-
-    def script_parts(self, bvid: str, parts: object) -> None:
-        self._parts[bvid] = parts
-
-    def script_completion(self, bvid: str, completed: object) -> None:
-        self._completions[bvid] = completed
-
-    async def get_user_video_page(
-        self, mid: int, page_number: int, page_size: int = 100
-    ) -> UserVideoPage:
-        self.page_calls.append((mid, page_number, page_size))
-        return self._scripted(self._pages, page_number, "user-video-page")
-
-    async def get_video_parts(self, bvid: str) -> tuple[VideoPart, ...]:
-        self.parts_calls.append(bvid)
-        return self._scripted(self._parts, bvid, "video-parts")
-
-    async def get_completed_video_summary(self, summary: VideoSummary) -> VideoSummary:
-        self.completion_calls.append(summary.bvid)
-        return self._scripted(self._completions, summary.bvid, "completed-summary")
-
-    def get_package_version(self) -> str:
-        return self.package_version
-
-    @staticmethod
-    def _scripted(script: dict, key: object, what: str) -> object:
-        if key not in script:
-            raise AssertionError(f"unexpected {what} fetch: {key!r}")
-        value = script[key]
-        if isinstance(value, BaseException):
-            raise value
-        return value
-
-
 def _page(
     page_number: int,
     *summaries: VideoSummary,
@@ -539,3 +515,228 @@ def test_collect_arguments_are_validated(kwargs, expected):
         MetadataIngestor(FakeGateway(), MetadataRepository(open_database(":memory:"))).collect_user_pages(
             **kwargs
         )
+
+
+# ----------------------------------------- real adapter over the package seam
+
+
+def _seam_gateway(sessdata: str | None = None):
+    """Build the real product adapter against the installed offline seam."""
+
+    module = importlib.import_module("bili_asr.sources.bilibili_api_gateway")
+    return module.BilibiliApiGateway(sessdata=sessdata)
+
+
+def test_bilibili_api_gateway_run_persists_normalized_rows(tmp_root, bilibili_api_seam):
+    """One real-adapter page run lands the exact normalized repository rows."""
+
+    script = bilibili_api_seam
+    script.videos_response = make_videos_response(
+        make_vlist_item(bvid="BV1SEAMRUNAA", aid=None, title="  无编号视频  "), count=1
+    )
+    script.parts_response = [
+        make_part_item(cid=2222, page=1, part="  第一部分  ", duration=12)
+    ]
+    script.info_response = make_detail_response()
+    connection = open_database(tmp_root)
+    repository = MetadataRepository(connection)
+    try:
+        result = MetadataIngestor(_seam_gateway(), repository).collect_user_pages(
+            MID, start_page=1, page_limit=1
+        )
+
+        assert result.outcome == "limited"
+        assert result.error_code is None
+        assert (result.page_count, result.video_count, result.part_count) == (1, 1, 1)
+        assert result.next_cursor is not None
+        assert (result.next_cursor.next_page, result.next_cursor.state) == (2, "limited")
+        assert result.next_cursor.observed_total == 1
+        assert result.next_cursor.last_error_code is None
+
+        video_row = connection.execute(
+            "SELECT bvid, aid, mid, title FROM videos"
+        ).fetchone()
+        assert tuple(video_row) == ("BV1SEAMRUNAA", 111, MID, "无编号视频")
+        part_row = connection.execute(
+            "SELECT bvid, page_index, cid, title, duration_ms, processing_status"
+            " FROM video_parts"
+        ).fetchone()
+        assert tuple(part_row) == ("BV1SEAMRUNAA", 0, 2222, "第一部分", 12_000, "discovered")
+        assert [row["work_id"] for row in repository.list_pending_parts()] == [
+            "BV1SEAMRUNAA:p0"
+        ]
+        page_rows = connection.execute(
+            "SELECT page_number, outcome, error_code FROM ingestion_pages"
+            " WHERE run_id = ?",
+            (result.run_id,),
+        ).fetchall()
+        assert [tuple(row) for row in page_rows] == [(1, "ok", None)]
+        user_row = connection.execute(
+            "SELECT mid, display_name FROM bilibili_users"
+        ).fetchone()
+        assert tuple(user_row) == (MID, str(MID))
+
+        # The pinned adapter drove exactly the three documented upstream
+        # calls: one page fetch, the aid completion, one parts fetch.
+        assert script.calls == [
+            "user.get_videos(pn=1, ps=100)",
+            "video.get_info",
+            "video.get_pages",
+        ]
+        assert_only_documented_metadata_calls(script.calls)
+    finally:
+        connection.close()
+
+
+def test_bilibili_api_gateway_run_persists_no_upstream_payload_markers(
+    tmp_root, bilibili_api_seam, caplog
+):
+    """Realistic raw payloads normalize away before anything persists."""
+
+    script = bilibili_api_seam
+    script.videos_response = make_videos_response(
+        make_vlist_item(
+            bvid="BV1SEAMLEAKS",
+            aid=None,
+            sessdata_note=SESSDATA_BOUNDARY_VALUE,
+            frame_url=SIGNED_URL_MARKER,
+            raw_note=RAW_JSON_BODY_MARKER,
+            upstream_note=RAW_UPSTREAM_EXCEPTION_MARKER,
+        ),
+        count=1,
+    )
+    script.parts_response = [
+        make_part_item(cid=2222, player_note=SESSDATA_BOUNDARY_VALUE)
+    ]
+    script.info_response = make_detail_response(
+        raw_body=RAW_JSON_BODY_MARKER, frame_url=SIGNED_URL_MARKER
+    )
+    connection = open_database(tmp_root)
+    repository = MetadataRepository(connection)
+    try:
+        result = MetadataIngestor(_seam_gateway(), repository).collect_user_pages(
+            MID, start_page=1, page_limit=1
+        )
+
+        assert result.outcome == "limited"
+        # The scan is not vacuous: a normalized video row really persisted.
+        assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 1
+        assert "BV1SEAMLEAKS" in persisted_row_text(connection)
+
+        persisted = persisted_row_text(connection)
+        assert_leaks_no_markers(persisted, context="persisted rows")
+        assert_leaks_no_markers(repr(result) + str(result), context="run result")
+        assert_leaks_no_markers(caplog.text, context="captured logs")
+    finally:
+        connection.close()
+
+
+def test_bilibili_api_gateway_upstream_failure_persists_scalar_code_only(
+    tmp_root, bilibili_api_seam, caplog
+):
+    """Raw upstream failure text stays process-local; only the code persists."""
+
+    script = bilibili_api_seam
+
+    def scripted_page(pn: int, ps: int) -> object:
+        if pn == 1:
+            return make_videos_response(
+                make_vlist_item(bvid="BV1SEAMFAILA", aid=1001), count=2
+            )
+        return make_videos_response(count=2)
+
+    script.videos_response = scripted_page
+    script.parts_response = [make_part_item(cid=2222)]
+    connection = open_database(tmp_root)
+    repository = MetadataRepository(connection)
+    try:
+        ingestor = MetadataIngestor(_seam_gateway(), repository)
+        first = ingestor.collect_user_pages(MID, start_page=1, page_limit=1)
+        assert first.outcome == "limited"
+        cursor_before_failure = repository.read_cursor(MID)
+        assert cursor_before_failure is not None
+
+        script.videos_error = FakeResponseCodeException(-412, UPSTREAM_ERROR_TEXT)
+        interrupted = ingestor.collect_user_pages(MID)  # resumes page 2
+
+        assert interrupted.outcome == "risk_interrupted"
+        assert interrupted.error_code == "rate_limited"
+        assert interrupted.page_count == 1
+        assert interrupted.video_count == 0
+        assert interrupted.part_count == 0
+        # The prior cursor is preserved exactly across the failed page.
+        assert repository.read_cursor(MID) == cursor_before_failure
+        second_page_rows = connection.execute(
+            "SELECT page_number, outcome, error_code FROM ingestion_pages"
+            " WHERE run_id = ?",
+            (interrupted.run_id,),
+        ).fetchall()
+        assert [tuple(row) for row in second_page_rows] == [
+            (2, "risk_interrupted", "rate_limited")
+        ]
+
+        assert_leaks_no_markers(
+            persisted_row_text(connection), context="persisted rows"
+        )
+        assert_leaks_no_markers(
+            repr(interrupted) + str(interrupted), context="run result"
+        )
+        assert_leaks_no_markers(caplog.text, context="captured logs")
+    finally:
+        connection.close()
+
+
+def test_bilibili_api_gateway_foreign_owner_page_requests_no_parts(
+    tmp_root, bilibili_api_seam
+):
+    """D3 at the seam: a foreign-owner summary blocks parts and completion.
+
+    Echoes the Task-2 protocol-double pin with the real adapter: one owned
+    item plus one foreign item fail the whole page at the adapter's
+    normalization boundary, so no parts or detail call is ever issued even
+    for the owned summary on the same page.
+    """
+
+    script = bilibili_api_seam
+    script.videos_response = make_videos_response(
+        make_vlist_item(),
+        make_vlist_item(mid=MID + 1, aid=1002),
+        count=2,
+    )
+    connection = open_database(tmp_root)
+    repository = MetadataRepository(connection)
+    try:
+        result = MetadataIngestor(_seam_gateway(), repository).collect_user_pages(MID)
+
+        assert result.outcome == "failed"
+        assert result.error_code == "shape_error"
+        assert repository.read_cursor(MID) is None
+        assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 0
+        assert connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0] == 0
+        assert (
+            connection.execute(
+                "SELECT COUNT(*) FROM ingestion_discoveries"
+            ).fetchone()[0]
+            == 0
+        )
+        page_rows = connection.execute(
+            "SELECT page_number, outcome, error_code FROM ingestion_pages"
+            " WHERE run_id = ?",
+            (result.run_id,),
+        ).fetchall()
+        assert [tuple(row) for row in page_rows] == [(1, "failed", "shape_error")]
+
+        # Exactly one page fetch: no parts, no detail, nothing else.
+        assert script.calls == ["user.get_videos(pn=1, ps=100)"]
+        assert_only_documented_metadata_calls(script.calls)
+    finally:
+        connection.close()
+
+
+def test_no_leak_marker_scan_catches_contamination():
+    """The persistence hygiene scanner is not vacuous."""
+
+    for marker in NO_LEAK_MARKERS:
+        with pytest.raises(AssertionError) as caught:
+            assert_leaks_no_markers("persisted: " + marker, context="demo row")
+        assert marker in str(caught.value)
```
