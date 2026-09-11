# Task 3 Diff — 20260911-live-metadata-path-fix

Base: `0a2e2f5`
Head: `3a96dd1`

```diff
diff --git a/bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py b/bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py
index f892c1e..f80d45e 100644
--- a/bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py
+++ b/bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py
@@ -17,7 +17,7 @@ import re
 from collections.abc import Awaitable, Callable, Mapping
 from typing import Any
 
-from bilibili_api import Credential, request_settings
+from bilibili_api import Credential, request_settings, user
 from bilibili_api.exceptions import (
     ApiException,
     NetworkException,
@@ -25,7 +25,7 @@ from bilibili_api.exceptions import (
     ResponseException,
     WbiRetryTimesExceedException,
 )
-from bilibili_api.user import User
+from bilibili_api.utils.network import Api
 from bilibili_api.video import Video
 
 from bili_asr.config import resolve_proxy
@@ -53,6 +53,13 @@ _NOT_FOUND_HTTP_STATUSES = frozenset({404})
 # Same shape check the package itself applies in Video.set_bvid.
 _BVID_PATTERN = re.compile(r"^BV[a-zA-Z0-9]{10}$")
 
+# The package's own endpoint description for the user-video page call
+# (``bilibili_api.user.API["info"]["video"]``).  ``url``/``method``/
+# ``verify``/``wbi`` are read from it so this adapter cannot drift from the
+# pinned package; ``dm`` is deliberately overridden per call (see
+# ``BilibiliApiGateway._fetch_user_video_page``).
+_USER_VIDEO_PAGE_ENDPOINT = user.API["info"]["video"]
+
 
 def _require_positive_argument(value: object, field: str) -> None:
     """Reject caller-argument violations before any upstream call."""
@@ -270,6 +277,7 @@ class BilibiliApiGateway:
         self.resolved_proxy = resolve_proxy(proxy, os.environ)
         if self.resolved_proxy is not None:
             request_settings.set_proxy(self.resolved_proxy)
+        self._w_webid_by_mid: dict[int, str] = {}
 
     async def get_user_video_page(
         self, mid: int, page_number: int, page_size: int = 100
@@ -281,9 +289,7 @@ class BilibiliApiGateway:
         _require_positive_argument(page_size, "page_size")
         response = await self._await_upstream(
             "get_user_video_page",
-            lambda: User(
-                uid=mid, credential=self._credential
-            ).get_videos(pn=page_number, ps=page_size),
+            lambda: self._fetch_user_video_page(mid, page_number, page_size),
         )
         return _normalize_user_video_page(response, requested_mid=mid, page_number=page_number)
 
@@ -323,6 +329,70 @@ class BilibiliApiGateway:
         except importlib.metadata.PackageNotFoundError:
             return PINNED_PACKAGE_VERSION
 
+    async def _fetch_user_video_page(
+        self, mid: int, page_number: int, page_size: int
+    ) -> Any:
+        """Issue one WBI-signed page request in the shape upstream accepts.
+
+        The request is built from the package's own endpoint description and
+        signed by the package's ``Api``.  Two fields are this adapter's:
+        ``dm`` is disabled, because the device-fingerprint parameters it would
+        add cannot be satisfied here and the endpoint answers HTTP 412 with
+        them; and ``w_webid`` is always sent as a present string, because the
+        endpoint answers HTTP 412 when the parameter is missing.  Every other
+        parameter name and value stays exactly the set the package's own page
+        call sends.
+        """
+
+        w_webid = await self._resolve_w_webid(mid)
+        return await (
+            Api(
+                url=_USER_VIDEO_PAGE_ENDPOINT["url"],
+                method=_USER_VIDEO_PAGE_ENDPOINT["method"],
+                verify=_USER_VIDEO_PAGE_ENDPOINT["verify"],
+                wbi=_USER_VIDEO_PAGE_ENDPOINT["wbi"],
+                dm=False,
+                credential=self._credential,
+            )
+            .update_params(
+                mid=mid,
+                ps=page_size,
+                tid=0,
+                pn=page_number,
+                keyword="",
+                order=user.VideoOrder.PUBDATE.value,
+                order_avoided=True,
+                platform="web",
+                w_webid=w_webid,
+            )
+            .result
+        )
+
+    async def _resolve_w_webid(self, mid: int) -> str:
+        """Resolve the page request's ``w_webid`` parameter for one user.
+
+        The package's ``User.get_access_id`` scrapes the user's dynamic page,
+        which no longer server-renders ``access_id``: the route costs one
+        extra page fetch and currently yields nothing.  The token is a request
+        parameter rather than a credential, and the endpoint requires it to be
+        present, so an unavailable token degrades to the empty string instead
+        of failing the page call.  Each user's outcome is remembered for this
+        adapter's lifetime, so at most one scrape attempt happens per user no
+        matter how many pages are collected.
+        """
+
+        if mid not in self._w_webid_by_mid:
+            try:
+                access_id: object = await user.User(
+                    uid=mid, credential=self._credential
+                ).get_access_id()
+            except Exception:
+                # Best effort only: this optional token route must never fail
+                # the metadata call it decorates.
+                access_id = None
+            self._w_webid_by_mid[mid] = access_id if isinstance(access_id, str) else ""
+        return self._w_webid_by_mid[mid]
+
     async def _await_upstream(
         self, operation: str, call: Callable[[], Awaitable[Any]]
     ) -> Any:
diff --git a/bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py b/bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py
index 30cf067..ce2364e 100644
--- a/bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py
+++ b/bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py
@@ -11,12 +11,22 @@ Every package-seam test scripts these fakes instead of touching the pinned
   install the fake ``bilibili_api`` package on ``sys.modules`` for the real
   adapter tests.  The fake mirrors only the documented import surface the
   adapter may use (``Credential``, ``request_settings.set_proxy`` /
-  ``get_proxy``, ``user.User.get_videos``, ``video.Video.get_info`` /
-  ``get_pages``, and the exceptions taxonomy) and exposes no playback,
-  subtitle, audio, or download method, so a silent switch to another package
-  API fails loudly instead of silently succeeding.  ``applied_proxies``
-  records every proxy the adapter hands to the package settings, so its
-  apply-once behavior is asserted without a network call.
+  ``get_proxy``, the ``user`` endpoint description and ``access_id`` route,
+  the WBI-signed ``utils.network.Api`` the user-video page call is issued
+  through, ``video.Video.get_info`` / ``get_pages``, and the exceptions
+  taxonomy) and exposes no playback, subtitle, audio, or download method, so
+  a silent switch to another package API fails loudly instead of silently
+  succeeding.  ``applied_proxies`` records every proxy the adapter hands to
+  the package settings, so its apply-once behavior is asserted without a
+  network call.
+- ``FakeApiRequest`` with ``script.api_requests`` records every page request
+  the adapter issues through the package's ``Api``: the transport flags it
+  took from the package endpoint description (device-fingerprint ``dm``
+  overridden) and the exact parameters it handed over, so the
+  risk-control-relevant call shape is assertable without a network call.
+  ``script.access_id_calls`` records the separate ``access_id`` token route
+  (kept out of ``calls``: it is a memoized, best-effort token fetch, not a
+  metadata call).
 - ``script_parts_by_bvid`` scripts one parts payload per requested ``bvid``
   for seam tests that collect a page holding several distinct videos.
 - ``DOCUMENTED_METADATA_CALLS`` with ``assert_only_documented_metadata_calls``
@@ -33,6 +43,7 @@ from __future__ import annotations
 import dataclasses
 import sys
 import types
+from enum import Enum
 
 import pytest
 
@@ -46,8 +57,35 @@ FAKE_PACKAGE_VERSION = "17.4.2"
 #: Adapter module the seam fixture reloads against the installed fake.
 GATEWAY_ADAPTER_MODULE = "bili_asr.sources.bilibili_api_gateway"
 
-#: The exact upstream call names the gateway adapter may issue.
-DOCUMENTED_METADATA_CALLS = ("user.get_videos", "video.get_info", "video.get_pages")
+#: The package's own endpoint description for the user-video page call
+#: (``bilibili_api.user.API["info"]["video"]``), mirroring the pinned
+#: distribution literally — including ``dm: True``.  The adapter must take
+#: ``url``/``method``/``verify``/``wbi`` from it and override ``dm``, so a
+#: package-side change to any of those fields stays visible here.
+FAKE_USER_VIDEO_PAGE_ENDPOINT = {
+    "url": "https://api.bilibili.com/x/space/wbi/arc/search",
+    "method": "GET",
+    "verify": False,
+    "wbi": True,
+    "dm": True,
+    "params": {
+        "mid": "int: uid",
+        "ps": "const int: 30",
+        "tid": "int: 分区 ID，0 表示全部",
+        "pn": "int: 页码",
+        "keyword": "str: 关键词，可为空",
+        "w_webid": "str: w_webid",
+    },
+    "comment": "搜索用户视频",
+}
+
+#: The exact upstream call names the gateway adapter may issue.  The page call
+#: is recorded as ``space.arc.search`` because the adapter issues that request
+#: itself through the package's ``Api``: the package's ``User.get_videos``
+#: delegate cannot pass upstream risk control (it injects device-fingerprint
+#: ``dm`` parameters and scrapes ``w_webid`` from a page that no longer
+#: server-renders it).
+DOCUMENTED_METADATA_CALLS = ("space.arc.search", "video.get_info", "video.get_pages")
 
 #: Realistic-looking SESSDATA value that must never leave the process.
 SESSDATA_BOUNDARY_VALUE = "SESSDATA-VALUE-THAT-MUST-NOT-LEAK"
@@ -120,16 +158,58 @@ class FakeWbiRetryTimesExceedException(FakeApiException):
         super().__init__("WBI 重试达到最大次数")
 
 
+def _device_fingerprint_params() -> dict:
+    """Mirror of the package's ``_enc_dm`` injection: the same parameter names.
+
+    A request built with ``dm`` enabled carries these parameters upstream, so
+    the fake adds them too: the "no device-fingerprint parameters are sent"
+    assertion then detects the real risk-control defect instead of merely
+    restating the recorded ``dm`` flag.
+    """
+
+    return {
+        "dm_img_list": "[]",
+        "dm_img_str": "AB",
+        "dm_cover_img_str": "AB",
+        "dm_img_inter": '{"ds":[],"wh":[0,0,0],"of":[0,0,0]}',
+    }
+
+
+@dataclasses.dataclass
+class FakeApiRequest:
+    """One recorded package-``Api`` request: the call shape that was issued.
+
+    ``params`` is the exact mapping the adapter handed to ``update_params``,
+    captured when the request was issued, with the package's
+    device-fingerprint injection mirrored when ``dm`` is on.
+    """
+
+    url: str
+    method: str
+    verify: bool
+    wbi: bool
+    dm: bool
+    params: dict
+
+
 @dataclasses.dataclass
 class FakeUpstreamScript:
     """Scripted upstream behavior; records every call the gateway makes.
 
-    A scripted response may be a plain value or a callable receiving the
+    A scripted page response may be a plain value or a callable receiving the
     documented page parameters (``pn``, ``ps``) so per-page behavior can be
     scripted for multi-page runs.  The scripted ``parts_response`` may
     likewise be a plain value or a callable receiving the requested
     ``bvid``, so each video's parts can be scripted independently (see
     :func:`script_parts_by_bvid`).
+
+    ``videos_response`` / ``videos_error`` script the user-video page request
+    the adapter issues through the package ``Api``; ``access_id`` /
+    ``access_id_error`` script the separate ``access_id`` token route
+    (``None`` by default, which is what the route currently yields in
+    production).  ``user_video_page_endpoint`` is the package-side endpoint
+    description the adapter must read its transport fields from; a test may
+    rewrite it before the adapter module is (re-)imported.
     """
 
     videos_response: object = None
@@ -138,7 +218,14 @@ class FakeUpstreamScript:
     parts_error: BaseException | None = None
     info_response: object = None
     info_error: BaseException | None = None
+    access_id: str | None = None
+    access_id_error: BaseException | None = None
+    user_video_page_endpoint: dict = dataclasses.field(
+        default_factory=lambda: dict(FAKE_USER_VIDEO_PAGE_ENDPOINT)
+    )
     calls: list[str] = dataclasses.field(default_factory=list)
+    access_id_calls: list[str] = dataclasses.field(default_factory=list)
+    api_requests: list[FakeApiRequest] = dataclasses.field(default_factory=list)
     applied_proxies: list[str] = dataclasses.field(default_factory=list)
 
 
@@ -229,30 +316,99 @@ def build_fake_package(script: FakeUpstreamScript) -> dict[str, types.ModuleType
 
     user_mod = types.ModuleType("bilibili_api.user")
 
+    class VideoOrder(Enum):
+        """Mirror of ``user.VideoOrder`` (only the default order is exposed)."""
+
+        PUBDATE = "pubdate"
+
     class User:
-        """Mirror of ``user.User(uid, credential)`` with only get_videos."""
+        """Mirror of ``user.User(uid, credential)`` with only the access_id route.
+
+        The user-video page data no longer flows through this class: the
+        adapter issues the endpoint description's request itself through the
+        package ``Api``.
+        """
 
         def __init__(self, uid: int, credential: object = None) -> None:
             self.uid = uid
             self.credential = credential
 
-        async def get_videos(
+        async def get_access_id(self) -> str | None:
+            script.access_id_calls.append(f"user.get_access_id(uid={self.uid})")
+            if script.access_id_error is not None:
+                raise script.access_id_error
+            return script.access_id
+
+    user_mod.API = {"info": {"video": script.user_video_page_endpoint}}
+    user_mod.User = User
+    user_mod.VideoOrder = VideoOrder
+
+    network_mod = types.ModuleType("bilibili_api.utils.network")
+
+    class Api:
+        """Mirror of ``utils.network.Api`` for the documented page request.
+
+        The package's ``Api`` is built from an endpoint description whose
+        ``url``/``method``/``verify``/``wbi`` the adapter must state and whose
+        ``dm`` it must override, so those fields are required here and are
+        recorded with the parameters of the issued request.  ``result``
+        answers with the scripted page payload or raises the scripted
+        failure.  Only the local request shaping under test is mirrored (the
+        ``dm`` parameter injection); signing, cookies, and retries are not,
+        because the adapter may not depend on them.
+        """
+
+        def __init__(
             self,
-            tid: int = 0,
-            pn: int = 1,
-            ps: int = 30,
-            keyword: str = "",
-            order: object = None,
-        ) -> dict:
-            script.calls.append(f"user.get_videos(pn={pn}, ps={ps})")
+            url: str,
+            method: str,
+            verify: bool,
+            wbi: bool,
+            dm: bool,
+            credential: object = None,
+        ) -> None:
+            self.url = url
+            self.method = method
+            self.verify = verify
+            self.wbi = wbi
+            self.dm = dm
+            self.credential = credential
+            self.params: dict = {}
+
+        def update_params(self, **kwargs: object) -> "Api":
+            """Mirror of ``Api.update_params`` (replaces the parameters)."""
+
+            self.params = dict(kwargs)
+            return self
+
+        @property
+        async def result(self) -> object:
+            """Mirror of ``Api.result``: record, then answer or fail."""
+
+            params = dict(self.params)
+            if self.dm:
+                params.update(_device_fingerprint_params())
+            page_number = params.get("pn")
+            page_size = params.get("ps")
+            script.api_requests.append(
+                FakeApiRequest(
+                    url=self.url,
+                    method=self.method,
+                    verify=self.verify,
+                    wbi=self.wbi,
+                    dm=self.dm,
+                    params=params,
+                )
+            )
+            script.calls.append(f"space.arc.search(pn={page_number}, ps={page_size})")
             if script.videos_error is not None:
                 raise script.videos_error
             response = script.videos_response
             if callable(response):
-                response = response(pn=pn, ps=ps)
+                response = response(pn=page_number, ps=page_size)
             return response
 
-    user_mod.User = User
+    network_mod.Api = Api
 
     video_mod = types.ModuleType("bilibili_api.video")
 
@@ -294,6 +450,7 @@ def build_fake_package(script: FakeUpstreamScript) -> dict[str, types.ModuleType
     return {
         "bilibili_api": package,
         "bilibili_api.user": user_mod,
+        "bilibili_api.utils.network": network_mod,
         "bilibili_api.video": video_mod,
         "bilibili_api.exceptions": exceptions_mod,
         "bilibili_api.request_settings": request_settings_mod,
@@ -434,7 +591,9 @@ __all__ = [
     "BVID",
     "DOCUMENTED_METADATA_CALLS",
     "FAKE_PACKAGE_VERSION",
+    "FAKE_USER_VIDEO_PAGE_ENDPOINT",
     "FakeApiException",
+    "FakeApiRequest",
     "FakeGateway",
     "FakeNetworkException",
     "FakeResponseCodeException",
diff --git a/bilibili-asr-archive/tests/test_bilibili_api_gateway.py b/bilibili-asr-archive/tests/test_bilibili_api_gateway.py
index ca6c37b..6ba4fe4 100644
--- a/bilibili-asr-archive/tests/test_bilibili_api_gateway.py
+++ b/bilibili-asr-archive/tests/test_bilibili_api_gateway.py
@@ -5,10 +5,12 @@ on ``sys.modules`` before the gateway module is (re-)imported, so neither the
 real package nor network access is ever required.  The fake package seam, the
 shared scripted protocol double, and the secret/raw-payload sentinels live in
 ``tests/fixtures/fake_bilibili_gateway.py``.  The fake mirrors only the
-documented import surface the gateway may use (``Credential``, ``user.User``,
-``video.Video``, and the exceptions taxonomy) and exposes no playback,
-subtitle, audio, or download methods, which makes silent use of other package
-APIs impossible.  The import boundary and the method surface itself are
+documented import surface the gateway may use (``Credential``, the ``user``
+endpoint description and ``access_id`` route, the WBI-signed
+``utils.network.Api``, ``video.Video``, and the exceptions taxonomy) and
+exposes no playback, subtitle, audio, or download methods, which makes silent
+use of other package APIs impossible.  The import boundary and the method
+surface itself are
 additionally inspected statically with AST over the package sources.  The
 only networked test is the opt-in live smoke, which skips unless
 ``BILI_LIVE_SMOKE=1`` is set.  The packaging-contract test is the one
@@ -46,6 +48,7 @@ from bili_asr.sources.models import (
 from bili_asr.storage.database import MetadataRepository, open_database
 from fixtures.fake_bilibili_gateway import (
     BVID,
+    FAKE_USER_VIDEO_PAGE_ENDPOINT,
     MID,
     PUBDATE,
     RAW_JSON_BODY_MARKER,
@@ -81,10 +84,12 @@ HTTP_BACKEND_CANONICAL_NAME = "curl-cffi"
 #: arrive through the application's dependency closure on its own.
 PACKAGE_HTTP_CLIENT_CANONICAL_NAMES = frozenset({"curl-cffi", "httpx", "aiohttp"})
 
-#: The exact bilibili_api import surface the adapter is allowed to use.
+#: The exact bilibili_api import surface the adapter is allowed to use.  The
+#: user-video page call is issued through ``user``'s own endpoint description
+#: and the WBI-signed ``utils.network.Api``, not through a ``user`` delegate.
 ALLOWED_PACKAGE_IMPORTS = {
-    "bilibili_api": {"Credential", "request_settings"},
-    "bilibili_api.user": {"User"},
+    "bilibili_api": {"Credential", "request_settings", "user"},
+    "bilibili_api.utils.network": {"Api"},
     "bilibili_api.video": {"Video"},
     "bilibili_api.exceptions": {
         "ApiException",
@@ -99,6 +104,15 @@ ALLOWED_PACKAGE_IMPORTS = {
 #: must still stay off DTOs, mapped errors, debug renders, and persisted rows.
 PROXY_BOUNDARY_VALUE = "http://PROXY-URL-THAT-MUST-NOT-LEAK:7890"
 
+#: Realistic-looking ``access_id`` token: a request parameter the package
+#: route may yield, which must stay off DTOs and mapped errors like every
+#: other upstream value.
+ACCESS_ID_BOUNDARY_VALUE = "ACCESS-ID-THAT-MUST-NOT-LEAK"
+
+#: Sentinel endpoint URL proving the transport fields are read from the
+#: package's own endpoint description instead of being hard-coded.
+CHANGED_ENDPOINT_URL = "https://changed-endpoint.example.invalid/x/space/wbi/arc/search"
+
 #: The complete documented exception surface the fake seam must mirror.
 ALLOWED_EXCEPTION_NAMES = (
     "ApiException",
@@ -180,7 +194,7 @@ def test_get_user_video_page_normalizes_documented_fields(bilibili_api_seam):
     assert summary.title == "未明子讲座"
     assert summary.pubdate == PUBDATE
     assert summary.mid == MID
-    assert bilibili_api_seam.calls == ["user.get_videos(pn=1, ps=100)"]
+    assert bilibili_api_seam.calls == ["space.arc.search(pn=1, ps=100)"]
     # The credential value must never surface on any DTO or page.
     assert SESSDATA_BOUNDARY_VALUE not in repr(page)
     assert SESSDATA_BOUNDARY_VALUE not in str(page)
@@ -194,7 +208,7 @@ def test_get_user_video_page_forwards_requested_page_and_size(bilibili_api_seam)
 
     asyncio.run(gateway.get_user_video_page(MID, page_number=4, page_size=50))
 
-    assert bilibili_api_seam.calls == ["user.get_videos(pn=4, ps=50)"]
+    assert bilibili_api_seam.calls == ["space.arc.search(pn=4, ps=50)"]
 
 
 def test_get_user_video_page_tolerates_plain_list_container(bilibili_api_seam):
@@ -380,7 +394,146 @@ def test_get_user_video_page_rejects_malformed_upstream_bvid(
 
     assert caught.value.code == "shape_error"
     assert "bvid" in str(caught.value)
-    assert bilibili_api_seam.calls == ["user.get_videos(pn=1, ps=100)"]
+    assert bilibili_api_seam.calls == ["space.arc.search(pn=1, ps=100)"]
+
+
+# ------------------------------------- user page: risk-control-safe request
+
+
+def test_user_video_page_request_carries_the_documented_parameter_set(
+    bilibili_api_seam,
+):
+    """The page request sends the package's parameters with ``dm`` disabled.
+
+    Device-fingerprint parameters cannot be satisfied here and make the
+    endpoint answer HTTP 412; the same endpoint answers ``code=0`` without
+    them, and the request must still carry ``w_webid`` (empty is the value
+    the unavailable token route degrades to).
+    """
+
+    bilibili_api_seam.videos_response = make_videos_response(make_vlist_item(), count=1)
+    gateway = _load_gateway()
+
+    asyncio.run(gateway.get_user_video_page(MID, page_number=2, page_size=50))
+
+    (request,) = bilibili_api_seam.api_requests
+    assert request.dm is False
+    assert [key for key in request.params if key.startswith("dm_")] == []
+    assert request.params == {
+        "mid": MID,
+        "ps": 50,
+        "tid": 0,
+        "pn": 2,
+        "keyword": "",
+        "order": "pubdate",
+        "order_avoided": True,
+        "platform": "web",
+        "w_webid": "",
+    }
+
+
+def test_user_video_page_request_prefers_the_package_access_id(bilibili_api_seam):
+    """A non-empty ``access_id`` from the package route is what gets sent."""
+
+    bilibili_api_seam.access_id = ACCESS_ID_BOUNDARY_VALUE
+    bilibili_api_seam.videos_response = make_videos_response(make_vlist_item(), count=1)
+    gateway = _load_gateway()
+
+    page = asyncio.run(gateway.get_user_video_page(MID, page_number=1))
+
+    assert bilibili_api_seam.access_id_calls == [f"user.get_access_id(uid={MID})"]
+    assert (
+        bilibili_api_seam.api_requests[0].params["w_webid"]
+        == ACCESS_ID_BOUNDARY_VALUE
+    )
+    # A request parameter still never surfaces on a DTO.
+    assert ACCESS_ID_BOUNDARY_VALUE not in repr(page)
+
+
+def test_user_video_page_request_falls_back_to_empty_w_webid_when_the_route_fails(
+    bilibili_api_seam,
+):
+    """A failing token scrape never fails the page call itself."""
+
+    bilibili_api_seam.access_id_error = FakeNetworkException(412, UPSTREAM_ERROR_TEXT)
+    bilibili_api_seam.videos_response = make_videos_response(make_vlist_item(), count=1)
+    gateway = _load_gateway()
+
+    page = asyncio.run(gateway.get_user_video_page(MID, page_number=1))
+
+    assert page.observed_total == 1
+    assert bilibili_api_seam.api_requests[0].params["w_webid"] == ""
+    assert UPSTREAM_ERROR_TEXT not in str(page)
+
+
+def test_user_video_page_resolves_the_access_id_once_per_user(bilibili_api_seam):
+    """Repeated pages of one user scrape the token route at most once."""
+
+    bilibili_api_seam.videos_response = make_videos_response(make_vlist_item(), count=1)
+    gateway = _load_gateway()
+
+    asyncio.run(gateway.get_user_video_page(MID, page_number=1))
+    asyncio.run(gateway.get_user_video_page(MID, page_number=2))
+
+    assert bilibili_api_seam.access_id_calls == [f"user.get_access_id(uid={MID})"]
+    assert len(bilibili_api_seam.api_requests) == 2
+
+
+def test_user_video_page_resolves_the_access_id_per_user(bilibili_api_seam):
+    """The memoized token is bound to the user it was scraped for."""
+
+    bilibili_api_seam.videos_response = make_videos_response(make_vlist_item(), count=1)
+    gateway = _load_gateway()
+
+    asyncio.run(gateway.get_user_video_page(MID, page_number=1))
+
+    bilibili_api_seam.videos_response = make_videos_response(
+        make_vlist_item(mid=MID + 1), count=1
+    )
+    asyncio.run(gateway.get_user_video_page(MID + 1, page_number=1))
+
+    assert bilibili_api_seam.access_id_calls == [
+        f"user.get_access_id(uid={MID})",
+        f"user.get_access_id(uid={MID + 1})",
+    ]
+
+
+def test_user_video_page_request_takes_its_transport_from_the_package_endpoint(
+    bilibili_api_seam,
+):
+    """``url``/``method``/``verify``/``wbi`` come from the package description."""
+
+    bilibili_api_seam.videos_response = make_videos_response(make_vlist_item(), count=1)
+    gateway = _load_gateway()
+
+    asyncio.run(gateway.get_user_video_page(MID, page_number=1))
+
+    (request,) = bilibili_api_seam.api_requests
+    assert request.url == FAKE_USER_VIDEO_PAGE_ENDPOINT["url"]
+    assert request.method == FAKE_USER_VIDEO_PAGE_ENDPOINT["method"]
+    assert request.wbi is FAKE_USER_VIDEO_PAGE_ENDPOINT["wbi"]
+    assert request.verify is FAKE_USER_VIDEO_PAGE_ENDPOINT["verify"]
+    # The package's own description carries ``dm: True``; the adapter turns
+    # that off itself.
+    assert FAKE_USER_VIDEO_PAGE_ENDPOINT["dm"] is True
+    assert request.dm is False
+
+
+def test_user_video_page_request_follows_a_changed_package_endpoint(
+    bilibili_api_seam,
+):
+    """No transport field is hard-coded: the package description decides."""
+
+    bilibili_api_seam.user_video_page_endpoint["url"] = CHANGED_ENDPOINT_URL
+    bilibili_api_seam.user_video_page_endpoint["wbi"] = False
+    bilibili_api_seam.videos_response = make_videos_response(make_vlist_item(), count=1)
+    gateway = _load_gateway()
+
+    asyncio.run(gateway.get_user_video_page(MID, page_number=1))
+
+    (request,) = bilibili_api_seam.api_requests
+    assert request.url == CHANGED_ENDPOINT_URL
+    assert request.wbi is False
 
 
 # -------------------------------------------------------------- video parts
@@ -825,7 +978,7 @@ def test_gateway_applies_the_resolved_proxy_once_before_the_first_call(
 
     asyncio.run(gateway.get_user_video_page(MID, page_number=1))
 
-    assert bilibili_api_seam.calls == ["user.get_videos(pn=1, ps=100)"]
+    assert bilibili_api_seam.calls == ["space.arc.search(pn=1, ps=100)"]
     # Apply-once: no request re-applies or re-reads the setting.
     assert bilibili_api_seam.applied_proxies == [PROXY_BOUNDARY_VALUE]
 
@@ -881,7 +1034,7 @@ def test_gateway_leaves_the_package_setting_untouched_without_a_proxy(
 
     asyncio.run(gateway.get_user_video_page(MID, page_number=1))
 
-    assert bilibili_api_seam.calls == ["user.get_videos(pn=1, ps=100)"]
+    assert bilibili_api_seam.calls == ["space.arc.search(pn=1, ps=100)"]
     assert bilibili_api_seam.applied_proxies == []
 
 
@@ -1111,7 +1264,9 @@ def test_gateway_source_never_names_forbidden_seam_methods():
 
     assert forbidden_hits == []
     # Positive control: the scan sees the documented metadata attribute calls.
-    assert {"get_videos", "get_pages", "get_info"} <= attribute_names
+    assert {"get_access_id", "update_params", "get_pages", "get_info"} <= (
+        attribute_names
+    )
 
 
 def test_fake_seam_exposes_only_documented_metadata_surface():
@@ -1120,8 +1275,9 @@ def test_fake_seam_exposes_only_documented_metadata_surface():
     modules = build_fake_package(FakeUpstreamScript())
     package = modules["bilibili_api"]
 
-    assert _public_names(modules["bilibili_api.user"]) == ["User"]
+    assert _public_names(modules["bilibili_api.user"]) == ["API", "User", "VideoOrder"]
     assert _public_names(modules["bilibili_api.video"]) == ["Video"]
+    assert _public_names(modules["bilibili_api.utils.network"]) == ["Api"]
     assert _public_names(modules["bilibili_api.exceptions"]) == sorted(
         ALLOWED_EXCEPTION_NAMES
     )
@@ -1154,6 +1310,10 @@ def test_fake_seam_exposes_only_documented_metadata_surface():
             getattr(user, surface_name)
         with pytest.raises(AttributeError):
             getattr(video, surface_name)
+    # The page delegate the risk-control-safe shape replaces is gone, so a
+    # regression to it fails loudly instead of passing through the seam.
+    with pytest.raises(AttributeError):
+        user.get_videos
 
 
 def test_gateway_dto_drops_unknown_upstream_payload_fields(bilibili_api_seam):
@@ -1181,7 +1341,7 @@ def test_gateway_dto_drops_unknown_upstream_payload_fields(bilibili_api_seam):
         assert_leaks_no_markers(repr(surface), context="gateway DTO repr")
         assert_leaks_no_markers(str(surface), context="gateway DTO str")
     assert bilibili_api_seam.calls == [
-        "user.get_videos(pn=1, ps=100)",
+        "space.arc.search(pn=1, ps=100)",
         "video.get_info",
         "video.get_pages",
     ]
diff --git a/bilibili-asr-archive/tests/test_metadata_cli.py b/bilibili-asr-archive/tests/test_metadata_cli.py
index 854fc5c..b0f3581 100644
--- a/bilibili-asr-archive/tests/test_metadata_cli.py
+++ b/bilibili-asr-archive/tests/test_metadata_cli.py
@@ -341,9 +341,9 @@ def test_fetch_meta_creates_fresh_database_and_completes(
     # page fetch, one parts fetch, one empty-page fetch (aid present, so no
     # detail call).
     assert bilibili_api_seam.calls == [
-        "user.get_videos(pn=1, ps=100)",
+        "space.arc.search(pn=1, ps=100)",
         "video.get_pages",
-        "user.get_videos(pn=2, ps=100)",
+        "space.arc.search(pn=2, ps=100)",
     ]
 
 
@@ -379,8 +379,8 @@ def test_fetch_meta_limit_pages_stops_limited_exit_zero(
     finally:
         connection.close()
     assert [
-        call for call in bilibili_api_seam.calls if call.startswith("user.get_videos")
-    ] == ["user.get_videos(pn=1, ps=100)"]
+        call for call in bilibili_api_seam.calls if call.startswith("space.arc.search")
+    ] == ["space.arc.search(pn=1, ps=100)"]
 
 
 def test_fetch_meta_start_page_overrides_cursor(
@@ -398,7 +398,7 @@ def test_fetch_meta_start_page_overrides_cursor(
     assert main(["fetch-meta", "--archive-root", tmp_root, "--start-page", "1"]) == 0
 
     # Page 1 was requested again even though the stored cursor pointed at 2.
-    assert bilibili_api_seam.calls.count("user.get_videos(pn=1, ps=100)") == 2
+    assert bilibili_api_seam.calls.count("space.arc.search(pn=1, ps=100)") == 2
     connection = open_database(tmp_root)
     try:
         start_pages = [
@@ -432,7 +432,7 @@ def test_fetch_meta_without_flags_resumes_from_stored_cursor(
 
     # Page 1 was not refetched: the run resumed at the cursor's page 2,
     # while run 1's own completion check already touched page 2.
-    assert bilibili_api_seam.calls.count("user.get_videos(pn=1, ps=100)") == 1
+    assert bilibili_api_seam.calls.count("space.arc.search(pn=1, ps=100)") == 1
     connection = open_database(tmp_root)
     try:
         start_pages = [
diff --git a/bilibili-asr-archive/tests/test_metadata_e2e.py b/bilibili-asr-archive/tests/test_metadata_e2e.py
index 781263a..a087f22 100644
--- a/bilibili-asr-archive/tests/test_metadata_e2e.py
+++ b/bilibili-asr-archive/tests/test_metadata_e2e.py
@@ -302,10 +302,10 @@ def test_fetch_meta_normalizes_single_part_and_multipart_videos_end_to_end(
     # page fetch, one parts fetch per distinct video, then the completing
     # empty-page fetch (aids present, so no detail calls).
     assert script.calls == [
-        "user.get_videos(pn=1, ps=100)",
+        "space.arc.search(pn=1, ps=100)",
         "video.get_pages",
         "video.get_pages",
-        "user.get_videos(pn=2, ps=100)",
+        "space.arc.search(pn=2, ps=100)",
     ]
     assert_only_documented_metadata_calls(script.calls)
 
@@ -440,7 +440,7 @@ def test_fetch_meta_rerun_of_same_page_stores_no_duplicate_rows(
     assert "sessdata: present" in out
     assert_leaks_no_markers(out + err, context="fetch-meta re-run output")
     # Page 1 was fetched exactly twice: once per run.
-    assert script.calls.count("user.get_videos(pn=1, ps=100)") == 2
+    assert script.calls.count("space.arc.search(pn=1, ps=100)") == 2
 
     for relative in LEGACY_SIDECAR_PATHS:
         assert not os.path.exists(os.path.join(tmp_root, relative))
@@ -572,11 +572,11 @@ def test_fetch_meta_failed_page_preserves_cursor_and_resume_succeeds(
     # The full call trace: bounded page fetches, one parts fetch per new
     # video, the failed resume page, then the successful resume.
     assert script.calls == [
-        "user.get_videos(pn=1, ps=100)",
+        "space.arc.search(pn=1, ps=100)",
         "video.get_pages",
-        "user.get_videos(pn=2, ps=100)",
-        "user.get_videos(pn=2, ps=100)",
+        "space.arc.search(pn=2, ps=100)",
+        "space.arc.search(pn=2, ps=100)",
         "video.get_pages",
-        "user.get_videos(pn=3, ps=100)",
+        "space.arc.search(pn=3, ps=100)",
     ]
     assert_only_documented_metadata_calls(script.calls)
diff --git a/bilibili-asr-archive/tests/test_metadata_ingest.py b/bilibili-asr-archive/tests/test_metadata_ingest.py
index 5a767ae..be1e5d9 100644
--- a/bilibili-asr-archive/tests/test_metadata_ingest.py
+++ b/bilibili-asr-archive/tests/test_metadata_ingest.py
@@ -701,7 +701,7 @@ def test_bilibili_api_gateway_run_persists_normalized_rows(tmp_root, bilibili_ap
         # The pinned adapter drove exactly the three documented upstream
         # calls: one page fetch, the aid completion, one parts fetch.
         assert script.calls == [
-            "user.get_videos(pn=1, ps=100)",
+            "space.arc.search(pn=1, ps=100)",
             "video.get_info",
             "video.get_pages",
         ]
@@ -849,7 +849,7 @@ def test_bilibili_api_gateway_foreign_owner_page_requests_no_parts(
         assert [tuple(row) for row in page_rows] == [(1, "failed", "shape_error")]
 
         # Exactly one page fetch: no parts, no detail, nothing else.
-        assert script.calls == ["user.get_videos(pn=1, ps=100)"]
+        assert script.calls == ["space.arc.search(pn=1, ps=100)"]
         assert_only_documented_metadata_calls(script.calls)
     finally:
         connection.close()
@@ -914,7 +914,7 @@ def test_malformed_upstream_bvid_page_fails_bounded_and_preserves_the_prior_curs
             (2, "failed", "shape_error")
         ]
         # The malformed bvid never reached the parts or detail fetches.
-        assert script.calls == calls_after_first + ["user.get_videos(pn=2, ps=100)"]
+        assert script.calls == calls_after_first + ["space.arc.search(pn=2, ps=100)"]
     finally:
         connection.close()
 
```
