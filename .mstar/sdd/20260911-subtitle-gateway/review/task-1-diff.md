# Task 1 Diff — 20260911-subtitle-gateway

Base: `2bd333f`
Head: `73fdef0`

```diff
diff --git a/bilibili-asr-archive/src/bili_asr/sources/models.py b/bilibili-asr-archive/src/bili_asr/sources/models.py
index 8647147..1a8d9dd 100644
--- a/bilibili-asr-archive/src/bili_asr/sources/models.py
+++ b/bilibili-asr-archive/src/bili_asr/sources/models.py
@@ -92,6 +92,57 @@ class UserVideoPage:
             _integer(self.observed_total, "observed_total", minimum=0)
 
 
+@dataclass(frozen=True, slots=True)
+class SubtitleTrack:
+    """One subtitle inventory entry of one part, as upstream listed it.
+
+    ``language`` is the upstream ``lan`` code and ``label`` its human-readable
+    ``lan_doc``; both are printable as-is.  ``is_ai`` separates
+    machine-generated captions from uploader/human ones.  ``track_id`` is the
+    track's upstream identity when it carries one — never a URL: a signed
+    ``subtitle_url`` is process-local for the duration of one call and cannot
+    reach this DTO.
+    """
+
+    language: str
+    label: str
+    is_ai: bool
+    track_id: str | None
+
+    def __post_init__(self) -> None:
+        _text(self.language, "language")
+        # The service derives the language family from the primary subtag, so a
+        # vocabulary it could not rank (``-zh``) is rejected here.
+        if not self.language.split("-", 1)[0].strip():
+            raise ValueError("language must carry a non-empty primary subtag")
+        _text(self.label, "label")
+        if not isinstance(self.is_ai, bool):
+            raise TypeError("is_ai must be a boolean")
+        if self.track_id is not None:
+            _text(self.track_id, "track_id")
+
+
+@dataclass(frozen=True, slots=True)
+class SubtitleSegment:
+    """One normalized caption row in milliseconds.
+
+    ``end_ms > start_ms >= 0`` with ``text`` non-empty after stripping is the
+    invariant this DTO enforces on what a call returns.  It is not a filter:
+    the adapter drops a row carrying nothing usable before constructing it.
+    """
+
+    start_ms: int
+    end_ms: int
+    text: str
+
+    def __post_init__(self) -> None:
+        _integer(self.start_ms, "start_ms", minimum=0)
+        _integer(self.end_ms, "end_ms", minimum=1)
+        if self.end_ms <= self.start_ms:
+            raise ValueError("end_ms must be greater than start_ms")
+        _text(self.text, "text")
+
+
 class BilibiliGateway(Protocol):
     """Application-owned gateway protocol for the pinned package adapter."""
 
@@ -108,6 +159,20 @@ class BilibiliGateway(Protocol):
         self, summary: VideoSummary
     ) -> VideoSummary: ...
 
+    # A subtitle inventory is an observation, not a promise: an empty tuple
+    # means nothing usable was visible with the credentials in effect, and it
+    # is a legitimate result rather than a ``not_found`` failure.
+    async def get_subtitle_tracks(
+        self, bvid: str, cid: int
+    ) -> tuple[SubtitleTrack, ...]: ...
+
+    # The body fetch is the opposite signal, because an empty success would
+    # claim a subtitle it does not have: nothing usable raises
+    # ``GatewayNotFound`` and the return is never an empty tuple.
+    async def fetch_subtitle_segments(
+        self, track: SubtitleTrack, bvid: str, cid: int
+    ) -> tuple[SubtitleSegment, ...]: ...
+
     def get_package_version(self) -> str: ...
 
 
@@ -170,6 +235,8 @@ __all__ = [
     "GatewayResponseError",
     "GatewayShapeError",
     "GatewayTransportError",
+    "SubtitleSegment",
+    "SubtitleTrack",
     "UserVideoPage",
     "VideoPart",
     "VideoSummary",
diff --git a/bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py b/bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py
index d0e308a..d26ec2e 100644
--- a/bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py
+++ b/bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py
@@ -11,22 +11,29 @@ Every package-seam test scripts these fakes instead of touching the pinned
   install the fake ``bilibili_api`` package on ``sys.modules`` for the real
   adapter tests.  The fake mirrors only the documented import surface the
   adapter may use (``Credential``, ``request_settings.set_proxy`` /
-  ``get_proxy``, the ``user`` endpoint description and ``access_id`` route,
-  the WBI-signed ``utils.network.Api`` the user-video page call is issued
-  through, ``video.Video.get_info`` / ``get_pages``, and the exceptions
-  taxonomy) and exposes no playback, subtitle, audio, or download method, so
-  a silent switch to another package API fails loudly instead of silently
-  succeeding.  ``applied_proxies`` records every proxy the adapter hands to
-  the package settings, so its apply-once behavior is asserted without a
-  network call.
-- ``FakeApiRequest`` with ``script.api_requests`` records every page request
-  the adapter issues through the package's ``Api``: the transport flags it
-  took from the package endpoint description (device-fingerprint ``dm``
-  overridden) and the exact parameters it handed over, so the
-  risk-control-relevant call shape is assertable without a network call.
-  ``script.access_id_calls`` records the separate ``access_id`` token route
-  (kept out of ``calls``: it is a memoized, best-effort token fetch, not a
-  metadata call).
+  ``get_proxy``, the ``user`` and ``video`` endpoint descriptions and the
+  ``access_id`` route, the WBI-signed ``utils.network.Api`` every documented
+  request is issued through, ``video.Video.get_info`` / ``get_pages``, and the
+  exceptions taxonomy) and exposes no subtitle, playback, audio, or download
+  *method* on those classes, so a silent switch to another package API fails
+  loudly instead of silently succeeding.  ``applied_proxies`` records every
+  proxy the adapter hands to the package settings, so its apply-once behavior
+  is asserted without a network call.
+- ``FakeApiRequest`` with ``script.api_requests`` records every request the
+  adapter issues through the package's ``Api``, in issue order: the transport
+  flags it took from the package endpoint description (device-fingerprint
+  ``dm`` overridden), the ``raw`` request argument, whether the credential it
+  carried held a SESSDATA value, and the exact parameters it handed over, so
+  the risk-control-relevant and credential-boundary call shapes are assertable
+  without a network call.  ``script.access_id_calls`` records the separate
+  ``access_id`` token route (kept out of ``calls``: it is a memoized,
+  best-effort token fetch, not a metadata call).
+- ``script.player_response`` / ``script.player_error`` script the player call
+  (``video.API["info"]["get_player_info"]``, whose unwrapped payload carries
+  the subtitle inventory) and ``script.subtitle_bodies`` scripts the signed
+  subtitle documents by URL: a plain document, a ``BaseException`` to raise,
+  or a callable receiving the fetched URL.  An unscripted document URL fails
+  loudly, so an adapter that fetches somewhere it did not mean to is caught.
 - ``script_parts_by_bvid`` scripts one parts payload per requested ``bvid``
   for seam tests that collect a page holding several distinct videos.
 - ``DOCUMENTED_METADATA_CALLS`` with ``assert_only_documented_metadata_calls``
@@ -89,6 +96,33 @@ FAKE_USER_VIDEO_PAGE_ENDPOINT = {
 #: surfacing only live.
 MIRRORED_ENDPOINT_FIELDS = ("url", "method", "verify", "wbi")
 
+#: The package's own endpoint description for the player call
+#: (``bilibili_api.video.API["info"]["get_player_info"]``), mirroring the
+#: pinned distribution literally — including ``dm: True``.  The adapter must
+#: take ``url``/``method``/``wbi`` from it and override ``dm``/``verify``, so a
+#: package-side change to any of those fields stays visible here.  Unlike the
+#: user-video page description, this endpoint declares its query fields under
+#: ``data``; those are field documentation the adapter must not forward
+#: verbatim, and the player call's parameters are none of the values below.
+#: The mirror itself is not taken on trust: the offline parity test in
+#: ``tests/test_bilibili_api_gateway.py`` compares it against the installed
+#: pinned distribution it claims to mirror, field for field.
+FAKE_PLAYER_ENDPOINT = {
+    "url": "https://api.bilibili.com/x/player/wbi/v2",
+    "method": "GET",
+    "verify": True,
+    "wbi": True,
+    "dm": True,
+    "data": {
+        "aid": "int: av 号。与 bvid 任选其一",
+        "cid": "int: 分 P id",
+        "ep_id": "int: 番剧分集 id",
+        "isGaiaAvoided": "bool: false",
+        "web_location": "int: 1315873",
+    },
+    "comment": "获取视频上一次播放的记录，字幕和地区信息。需要 分集的 cid, 返回数据中含有json字幕的链接",
+}
+
 #: The exact upstream call names the gateway adapter may issue.  The page call
 #: is recorded as ``space.arc.search`` because the adapter issues that request
 #: itself through the package's ``Api``: the package's ``User.get_videos``
@@ -105,6 +139,19 @@ SIGNED_URL_MARKER = (
     "https://upos.example.com/upyun/ssl/part.m4s?sign=SIGNED-URL-THAT-MUST-NOT-LEAK"
 )
 
+#: Realistic-looking signed subtitle-document URL that must never leave the
+#: process: it is what a leaked ``subtitle_url`` would look like, and it is
+#: what the seam scripts every track with — so the shipped no-leak scanner
+#: catches a leaked subtitle URL the same way it catches a playback URL.
+SIGNED_SUBTITLE_URL_MARKER = (
+    "https://aisubtitle.example.com/bfs/subtitle/part.json"
+    "?sign=SIGNED-SUBTITLE-URL-THAT-MUST-NOT-LEAK"
+)
+
+#: The same signed document URL in the protocol-relative form upstream also
+#: returns, which the adapter must normalize to ``https:`` before fetching.
+PROTOCOL_RELATIVE_SUBTITLE_URL = SIGNED_SUBTITLE_URL_MARKER.removeprefix("https:")
+
 #: Realistic-looking raw JSON response body that must never be persisted.
 RAW_JSON_BODY_MARKER = '{"code":-412,"message":"RAW-JSON-BODY-THAT-MUST-NOT-LEAK"}'
 
@@ -115,6 +162,7 @@ RAW_UPSTREAM_EXCEPTION_MARKER = "RAW-UPSTREAM-EXCEPTION-THAT-MUST-NOT-LEAK"
 NO_LEAK_MARKERS = (
     SESSDATA_BOUNDARY_VALUE,
     SIGNED_URL_MARKER,
+    SIGNED_SUBTITLE_URL_MARKER,
     RAW_JSON_BODY_MARKER,
     RAW_UPSTREAM_EXCEPTION_MARKER,
 )
@@ -191,7 +239,12 @@ class FakeApiRequest:
 
     ``params`` is the exact mapping the adapter handed to ``update_params``,
     captured when the request was issued, with the package's
-    device-fingerprint injection mirrored when ``dm`` is on.
+    device-fingerprint injection mirrored when ``dm`` is on.  ``raw`` is the
+    ``Api.request(raw=...)`` argument the call carried (in the pinned package
+    the request argument decides whether the ``data``/``result`` envelope is
+    unwrapped).  ``has_sessdata`` records whether the credential the call
+    carried held a SESSDATA value, which is how the empty-credential document
+    fetch is assertable without ever comparing credential values.
     """
 
     url: str
@@ -200,6 +253,8 @@ class FakeApiRequest:
     wbi: bool
     dm: bool
     params: dict
+    raw: bool = False
+    has_sessdata: bool = False
 
 
 @dataclasses.dataclass
@@ -214,12 +269,18 @@ class FakeUpstreamScript:
     :func:`script_parts_by_bvid`).
 
     ``videos_response`` / ``videos_error`` script the user-video page request
-    the adapter issues through the package ``Api``; ``access_id`` /
+    the adapter issues through the package ``Api``; ``player_response`` /
+    ``player_error`` script the player request the same way (a plain value or
+    a callable receiving the requested ``bvid``/``cid``), whose unwrapped
+    payload carries the subtitle inventory; ``subtitle_bodies`` scripts the
+    signed subtitle documents by URL (a plain document, a ``BaseException`` to
+    raise, or a callable receiving the fetched URL).  ``access_id`` /
     ``access_id_error`` script the separate ``access_id`` token route
     (``None`` by default, which is what the route currently yields in
-    production).  ``user_video_page_endpoint`` is the package-side endpoint
-    description the adapter must read its transport fields from; a test may
-    rewrite it before the adapter module is (re-)imported.
+    production).  ``user_video_page_endpoint`` / ``player_endpoint`` are the
+    package-side endpoint descriptions the adapter must read its transport
+    fields from; a test may rewrite either before the adapter module is
+    (re-)imported.
     """
 
     videos_response: object = None
@@ -228,11 +289,17 @@ class FakeUpstreamScript:
     parts_error: BaseException | None = None
     info_response: object = None
     info_error: BaseException | None = None
+    player_response: object = None
+    player_error: BaseException | None = None
+    subtitle_bodies: dict[str, object] = dataclasses.field(default_factory=dict)
     access_id: str | None = None
     access_id_error: BaseException | None = None
     user_video_page_endpoint: dict = dataclasses.field(
         default_factory=lambda: dict(FAKE_USER_VIDEO_PAGE_ENDPOINT)
     )
+    player_endpoint: dict = dataclasses.field(
+        default_factory=lambda: dict(FAKE_PLAYER_ENDPOINT)
+    )
     calls: list[str] = dataclasses.field(default_factory=list)
     access_id_calls: list[str] = dataclasses.field(default_factory=list)
     api_requests: list[FakeApiRequest] = dataclasses.field(default_factory=list)
@@ -362,16 +429,20 @@ def build_fake_package(script: FakeUpstreamScript) -> dict[str, types.ModuleType
     network_mod = types.ModuleType("bilibili_api.utils.network")
 
     class Api:
-        """Mirror of ``utils.network.Api`` for the documented page request.
+        """Mirror of ``utils.network.Api`` for the documented requests.
 
         The package's ``Api`` is built from an endpoint description whose
         ``url``/``method``/``verify``/``wbi`` the adapter must state and whose
         ``dm`` it must override, so those fields are required here and are
-        recorded with the parameters of the issued request.  ``result``
-        answers with the scripted page payload or raises the scripted
-        failure.  Only the local request shaping under test is mirrored (the
-        ``dm`` parameter injection); signing, cookies, and retries are not,
-        because the adapter may not depend on them.
+        recorded with the parameters of the issued request.  Three routes are
+        mirrored: the user-video page call and the player call, both answered
+        with the scripted unwrapped payload exactly as the pin's ``raw=False``
+        result delivers it, and the signed subtitle-document fetch, which the
+        pin answers only to ``request(raw=True)`` because a subtitle document
+        has no ``code``/``data`` envelope to unwrap.  Only the local request
+        shaping under test is mirrored (the ``dm`` parameter injection and the
+        ``raw`` request argument); signing, cookies, retries, and byte
+        transport are not, because the adapter may not depend on them.
         """
 
         def __init__(
@@ -399,13 +470,63 @@ def build_fake_package(script: FakeUpstreamScript) -> dict[str, types.ModuleType
 
         @property
         async def result(self) -> object:
-            """Mirror of ``Api.result``: record, then answer or fail."""
+            """Mirror of ``Api.result``: the pin's ``request()`` with no args."""
+
+            return await self.request()
+
+        async def request(self, raw: bool = False, byte: bool = False) -> object:
+            """Mirror of ``Api.request``: record the call, then answer or fail.
+
+            ``raw`` selects which document is answered with: unless it is set
+            the pin unwraps the ``data``/``result`` envelope, which a subtitle
+            document does not have, so an unset ``raw`` on the signed-document
+            route is rejected the way the pin rejects it.
+            """
+
+            if byte:
+                raise AssertionError("the seam mirrors no byte transport")
+            if self._is_player_call():
+                if raw:
+                    raise AssertionError(
+                        "the pin answers the whole envelope to"
+                        " request(raw=True); the seam scripts the unwrapped"
+                        " player payload only"
+                    )
+                return self._player_result()
+            if self._is_user_video_page_call():
+                if raw:
+                    raise AssertionError(
+                        "the pin answers the whole envelope to"
+                        " request(raw=True); the seam scripts the unwrapped"
+                        " payload only"
+                    )
+                return self._user_video_page_result()
+            if not raw:
+                raise FakeResponseCodeException(-1, "API 返回数据未含 code 字段")
+            return self._subtitle_document_result()
+
+        def _is_player_call(self) -> bool:
+            """True for the player call, at the scripted or the mirrored URL."""
+
+            return self.url in (
+                script.player_endpoint["url"],
+                FAKE_PLAYER_ENDPOINT["url"],
+            )
+
+        def _is_user_video_page_call(self) -> bool:
+            """True for the page call, at the scripted or the mirrored URL."""
+
+            return self.url in (
+                script.user_video_page_endpoint["url"],
+                FAKE_USER_VIDEO_PAGE_ENDPOINT["url"],
+            )
+
+        def _record(self, call: str, *, raw: bool = False) -> None:
+            """Record one issued request with its flags and parameter set."""
 
             params = dict(self.params)
             if self.dm:
                 params.update(_device_fingerprint_params())
-            page_number = params.get("pn")
-            page_size = params.get("ps")
             script.api_requests.append(
                 FakeApiRequest(
                     url=self.url,
@@ -414,9 +535,18 @@ def build_fake_package(script: FakeUpstreamScript) -> dict[str, types.ModuleType
                     wbi=self.wbi,
                     dm=self.dm,
                     params=params,
+                    raw=raw,
+                    has_sessdata=bool(getattr(self.credential, "sessdata", None)),
                 )
             )
-            script.calls.append(f"space.arc.search(pn={page_number}, ps={page_size})")
+            script.calls.append(call)
+
+        def _user_video_page_result(self) -> object:
+            """Answer the user-video page call with the scripted payload."""
+
+            page_number = self.params.get("pn")
+            page_size = self.params.get("ps")
+            self._record(f"space.arc.search(pn={page_number}, ps={page_size})")
             if script.videos_error is not None:
                 raise script.videos_error
             response = script.videos_response
@@ -424,6 +554,34 @@ def build_fake_package(script: FakeUpstreamScript) -> dict[str, types.ModuleType
                 response = response(pn=page_number, ps=page_size)
             return response
 
+        def _player_result(self) -> object:
+            """Answer the player call with the scripted subtitle inventory."""
+
+            bvid = self.params.get("bvid")
+            cid = self.params.get("cid")
+            self._record(f"player.track_list(bvid={bvid}, cid={cid})")
+            if script.player_error is not None:
+                raise script.player_error
+            response = script.player_response
+            if callable(response):
+                response = response(bvid=bvid, cid=cid)
+            return response
+
+        def _subtitle_document_result(self) -> object:
+            """Answer the signed subtitle-document fetch with its scripted body."""
+
+            self._record("subtitle.body", raw=True)
+            if self.url not in script.subtitle_bodies:
+                raise AssertionError(
+                    f"unexpected subtitle-document fetch: {self.url!r}"
+                )
+            outcome = script.subtitle_bodies[self.url]
+            if callable(outcome):
+                outcome = outcome(self.url)
+            if isinstance(outcome, BaseException):
+                raise outcome
+            return outcome
+
     network_mod.Api = Api
 
     video_mod = types.ModuleType("bilibili_api.video")
@@ -457,6 +615,7 @@ def build_fake_package(script: FakeUpstreamScript) -> dict[str, types.ModuleType
             return response
 
     video_mod.Video = Video
+    video_mod.API = {"info": {"get_player_info": script.player_endpoint}}
 
     package.user = user_mod
     package.video = video_mod
@@ -542,6 +701,45 @@ def make_detail_response(**overrides: object) -> dict:
     return detail
 
 
+def make_subtitle_track(**overrides: object) -> dict:
+    """Build one documented ``data.subtitle.subtitles[]`` entry.
+
+    The default is an uploader/human (CC) track: it carries neither of the
+    upstream AI markers, which is the conservative reading.  Its
+    ``subtitle_url`` is the signed-document sentinel, so a leaked track URL is
+    caught by the same scanner as every other secret.
+    """
+
+    track = {
+        "id": 1,
+        "lan": "zh-CN",
+        "lan_doc": "中文（中国）",
+        "subtitle_url": SIGNED_SUBTITLE_URL_MARKER,
+    }
+    track.update(overrides)
+    return track
+
+
+def make_player_response(*tracks: object, allow_submit: bool = False) -> dict:
+    """Build the player call's unwrapped payload carrying subtitle tracks."""
+
+    return {"subtitle": {"allow_submit": allow_submit, "subtitles": list(tracks)}}
+
+
+def make_subtitle_entry(**overrides: object) -> dict:
+    """Build one documented subtitle-document ``body`` row, in seconds."""
+
+    entry = {"from": 0.0, "to": 1.5, "content": "未明子"}
+    entry.update(overrides)
+    return entry
+
+
+def make_subtitle_document(*entries: object) -> dict:
+    """Build one documented subtitle JSON document around the given rows."""
+
+    return {"font_size": 0.4, "body": list(entries)}
+
+
 def persisted_row_text(connection: object) -> str:
     """Render every persisted row of every table and view as one text blob.
 
@@ -607,6 +805,7 @@ __all__ = [
     "BVID",
     "DOCUMENTED_METADATA_CALLS",
     "FAKE_PACKAGE_VERSION",
+    "FAKE_PLAYER_ENDPOINT",
     "FAKE_USER_VIDEO_PAGE_ENDPOINT",
     "FakeApiException",
     "FakeApiRequest",
@@ -620,10 +819,12 @@ __all__ = [
     "MID",
     "MIRRORED_ENDPOINT_FIELDS",
     "NO_LEAK_MARKERS",
+    "PROTOCOL_RELATIVE_SUBTITLE_URL",
     "PUBDATE",
     "RAW_JSON_BODY_MARKER",
     "RAW_UPSTREAM_EXCEPTION_MARKER",
     "SESSDATA_BOUNDARY_VALUE",
+    "SIGNED_SUBTITLE_URL_MARKER",
     "SIGNED_URL_MARKER",
     "UPSTREAM_ERROR_TEXT",
     "assert_leaks_no_markers",
@@ -632,6 +833,10 @@ __all__ = [
     "build_fake_package",
     "make_detail_response",
     "make_part_item",
+    "make_player_response",
+    "make_subtitle_document",
+    "make_subtitle_entry",
+    "make_subtitle_track",
     "make_videos_response",
     "make_vlist_item",
     "persisted_row_text",
diff --git a/bilibili-asr-archive/tests/test_bilibili_api_gateway.py b/bilibili-asr-archive/tests/test_bilibili_api_gateway.py
index cf33c46..24cd7ed 100644
--- a/bilibili-asr-archive/tests/test_bilibili_api_gateway.py
+++ b/bilibili-asr-archive/tests/test_bilibili_api_gateway.py
@@ -7,9 +7,12 @@ shared scripted protocol double, and the secret/raw-payload sentinels live in
 ``tests/fixtures/fake_bilibili_gateway.py``.  The fake mirrors only the
 documented import surface the gateway may use (``Credential``, the ``user``
 endpoint description and ``access_id`` route, the WBI-signed
-``utils.network.Api``, ``video.Video``, and the exceptions taxonomy) and
-exposes no playback, subtitle, audio, or download methods, which makes silent
-use of other package APIs impossible.  The import boundary and the method
+``utils.network.Api``, the ``user``/``video`` endpoint descriptions,
+``video.Video``, and the exceptions taxonomy) and exposes no subtitle,
+playback, audio, or download *package method*, which makes silent use of other
+package APIs impossible: the player call and the signed subtitle-document
+fetch are issued through the package's own ``Api`` like the page call.  The
+import boundary and the method
 surface itself are
 additionally inspected statically with AST over the package sources.  The
 only networked test is the opt-in live smoke, which skips unless
@@ -23,6 +26,7 @@ from __future__ import annotations
 
 import ast
 import asyncio
+import dataclasses
 import importlib
 import importlib.metadata
 import inspect
@@ -43,6 +47,8 @@ from bili_asr.sources.models import (
     GatewayResponseError,
     GatewayShapeError,
     GatewayTransportError,
+    SubtitleSegment,
+    SubtitleTrack,
     UserVideoPage,
     VideoPart,
     VideoSummary,
@@ -50,12 +56,15 @@ from bili_asr.sources.models import (
 from bili_asr.storage.database import MetadataRepository, open_database
 from fixtures.fake_bilibili_gateway import (
     BVID,
+    FAKE_PLAYER_ENDPOINT,
     FAKE_USER_VIDEO_PAGE_ENDPOINT,
     MID,
     MIRRORED_ENDPOINT_FIELDS,
+    PROTOCOL_RELATIVE_SUBTITLE_URL,
     PUBDATE,
     RAW_JSON_BODY_MARKER,
     SESSDATA_BOUNDARY_VALUE,
+    SIGNED_SUBTITLE_URL_MARKER,
     SIGNED_URL_MARKER,
     UPSTREAM_ERROR_TEXT,
     FakeNetworkException,
@@ -68,6 +77,10 @@ from fixtures.fake_bilibili_gateway import (
     build_fake_package,
     make_detail_response,
     make_part_item,
+    make_player_response,
+    make_subtitle_document,
+    make_subtitle_entry,
+    make_subtitle_track,
     make_videos_response,
     make_vlist_item,
     persisted_row_text,
@@ -116,6 +129,16 @@ ACCESS_ID_BOUNDARY_VALUE = "ACCESS-ID-THAT-MUST-NOT-LEAK"
 #: package's own endpoint description instead of being hard-coded.
 CHANGED_ENDPOINT_URL = "https://changed-endpoint.example.invalid/x/space/wbi/arc/search"
 
+#: The part cid the scripted subtitle calls are issued for: a part identity,
+#: never a subtitle identity.
+PART_CID = 2222
+
+#: Sentinel player-endpoint URL proving the player call's transport fields are
+#: read from the package's own player description instead of being hard-coded.
+CHANGED_PLAYER_ENDPOINT_URL = (
+    "https://changed-player.example.invalid/x/player/wbi/v2"
+)
+
 
 def _probe_installed_pinned_endpoint() -> dict | str:
     """Read the pin's endpoint description, or the reason it could not be read.
@@ -144,6 +167,55 @@ def _probe_installed_pinned_endpoint() -> dict | str:
 _INSTALLED_PINNED_ENDPOINT = _probe_installed_pinned_endpoint()
 
 
+def _probe_installed_pinned_player_endpoint() -> dict | str:
+    """Read the pin's player endpoint description, or why it could not be read.
+
+    Captured at import time for the same reason as the user-video description:
+    a lazy import inside a seam test would return the fake.  The description is
+    pure package data, so this needs no network.
+    """
+
+    try:
+        module = importlib.import_module("bilibili_api.video")
+        endpoint = module.API["info"]["get_player_info"]
+    except (ImportError, KeyError, AttributeError, TypeError) as error:
+        return f"{type(error).__name__}: {error}"
+    if not isinstance(endpoint, dict):
+        return f"the description is not a mapping ({type(endpoint).__name__})"
+    return dict(endpoint)
+
+
+#: The installed pin's own player endpoint description, captured the same way.
+_INSTALLED_PINNED_PLAYER_ENDPOINT = _probe_installed_pinned_player_endpoint()
+
+
+def _probe_installed_api_call_shape() -> dict | str:
+    """Read the pin's ``Api`` constructor fields and ``request`` signature.
+
+    Captured at import time for the same reason as the endpoint descriptions.
+    The shape matters because the seam must not accept a call the pin would
+    reject: in the pin ``raw``/``byte`` are ``request`` arguments, not
+    constructor fields, so a double that took ``raw=True`` at construction
+    would pass offline and raise ``TypeError`` live.
+    """
+
+    try:
+        api = importlib.import_module("bilibili_api.utils.network").Api
+        return {
+            "fields": [field.name for field in dataclasses.fields(api)],
+            "request": [
+                (parameter.name, str(parameter.kind), parameter.default)
+                for parameter in inspect.signature(api.request).parameters.values()
+            ],
+        }
+    except (ImportError, AttributeError, TypeError, ValueError) as error:
+        return f"{type(error).__name__}: {error}"
+
+
+#: The installed pin's ``Api`` call shape, captured the same way.
+_INSTALLED_API_CALL_SHAPE = _probe_installed_api_call_shape()
+
+
 def _probe_installed_request_settings_parameters() -> dict | str:
     """Read the pin's request-settings parameter shapes, or why not.
 
@@ -1404,6 +1476,155 @@ def test_user_video_page_rejects_invalid_fields(broken_kwargs):
         UserVideoPage(**values)
 
 
+# -------------------------------------------------- subtitle DTO validation
+
+
+def _track(**overrides: object) -> SubtitleTrack:
+    """Build one validated subtitle-track DTO (an uploader/CC track)."""
+
+    values: dict[str, object] = {
+        "language": "zh-CN",
+        "label": "中文（中国）",
+        "is_ai": False,
+        "track_id": "track-1",
+    }
+    values.update(overrides)
+    return SubtitleTrack(**values)
+
+
+def _segment(**overrides: object) -> SubtitleSegment:
+    """Build one validated subtitle-segment DTO."""
+
+    values: dict[str, object] = {"start_ms": 0, "end_ms": 1500, "text": "未明子"}
+    values.update(overrides)
+    return SubtitleSegment(**values)
+
+
+def test_subtitle_dtos_carry_no_work_id_and_no_url_field():
+    """The locked field sets: no storage identity and no URL in either DTO.
+
+    A signed ``subtitle_url`` lives for the duration of one call and a part's
+    storage identity never belongs to the gateway, so both DTOs must stay
+    incapable of carrying either — the field sets are pinned exactly.
+    """
+
+    assert [field.name for field in dataclasses.fields(SubtitleTrack)] == [
+        "language",
+        "label",
+        "is_ai",
+        "track_id",
+    ]
+    assert [field.name for field in dataclasses.fields(SubtitleSegment)] == [
+        "start_ms",
+        "end_ms",
+        "text",
+    ]
+
+
+@pytest.mark.parametrize(
+    "broken_kwargs",
+    [
+        {"language": ""},
+        {"language": "   "},
+        {"language": 5},
+        # The service derives the language family from the primary subtag, so a
+        # vocabulary it cannot rank (`-zh`) is rejected, not silently kept.
+        {"language": "-zh"},
+        {"language": "  -zh"},
+        {"label": ""},
+        {"label": "   "},
+        {"label": None},
+        {"is_ai": "ai"},
+        {"is_ai": 1},
+        {"is_ai": None},
+        {"track_id": ""},
+        {"track_id": "   "},
+        {"track_id": 7},
+    ],
+)
+def test_subtitle_track_rejects_invalid_fields(broken_kwargs):
+    """The track DTO enforces printable scalars and the primary-subtag rule."""
+
+    with pytest.raises((TypeError, ValueError)):
+        _track(**broken_kwargs)
+
+
+def test_subtitle_track_accepts_a_missing_track_id():
+    """A track upstream did not identify is valid: ``track_id`` is nullable."""
+
+    assert _track(track_id=None).track_id is None
+
+
+def test_subtitle_track_accepts_a_region_or_script_subtag():
+    """A language with a region/script subtag keeps that subtag intact."""
+
+    assert _track(language="zh-Hans").language == "zh-Hans"
+
+
+@pytest.mark.parametrize(
+    "broken_kwargs",
+    [
+        {"start_ms": -1},
+        {"start_ms": True},
+        {"start_ms": "0"},
+        {"start_ms": None},
+        {"end_ms": 0},
+        {"end_ms": -5},
+        {"end_ms": True},
+        {"end_ms": "1500"},
+        {"start_ms": 1500, "end_ms": 1500},
+        {"start_ms": 1500, "end_ms": 500},
+        {"text": ""},
+        {"text": "   "},
+        {"text": 7},
+    ],
+)
+def test_subtitle_segment_rejects_invalid_fields(broken_kwargs):
+    """The segment DTO enforces ``end_ms > start_ms >= 0`` and non-empty text."""
+
+    with pytest.raises((TypeError, ValueError)):
+        _segment(**broken_kwargs)
+
+
+def test_subtitle_dtos_are_frozen():
+    """Both DTOs are immutable: a normalized result cannot be edited in place."""
+
+    for subtitle_dto, field_name in ((_track(), "label"), (_segment(), "text")):
+        with pytest.raises(dataclasses.FrozenInstanceError):
+            setattr(subtitle_dto, field_name, "changed")
+
+
+# ---------------------------------------------------- gateway protocol surface
+
+
+def test_gateway_protocol_surface_is_locked():
+    """The protocol declares the locked six methods, signatures included.
+
+    The four shipped signatures stay untouched — the shipped metadata service
+    and the storage plan consume them — and the two subtitle methods are
+    exactly the locked pair: ``get_subtitle_tracks(bvid, cid)`` answers a
+    possibly empty tuple (an empty inventory is an observation, never a
+    ``not_found`` failure), while ``fetch_subtitle_segments(track, bvid, cid)``
+    answers a non-empty tuple or raises ``GatewayNotFound``.
+    """
+
+    expected = {
+        "get_user_video_page": ("self", "mid", "page_number", "page_size"),
+        "get_video_parts": ("self", "bvid"),
+        "get_completed_video_summary": ("self", "summary"),
+        "get_package_version": ("self",),
+        "get_subtitle_tracks": ("self", "bvid", "cid"),
+        "fetch_subtitle_segments": ("self", "track", "bvid", "cid"),
+    }
+
+    declared = {
+        name: tuple(inspect.signature(getattr(BilibiliGateway, name)).parameters)
+        for name in expected
+    }
+
+    assert declared == expected
+
+
 # ------------------------------------------------------- import boundary (AST)
 
 
@@ -1505,7 +1726,7 @@ def test_fake_seam_exposes_only_documented_metadata_surface():
     package = modules["bilibili_api"]
 
     assert _public_names(modules["bilibili_api.user"]) == ["API", "User", "VideoOrder"]
-    assert _public_names(modules["bilibili_api.video"]) == ["Video"]
+    assert _public_names(modules["bilibili_api.video"]) == ["API", "Video"]
     assert _public_names(modules["bilibili_api.utils.network"]) == ["Api"]
     assert _public_names(modules["bilibili_api.exceptions"]) == sorted(
         ALLOWED_EXCEPTION_NAMES
@@ -1576,6 +1797,332 @@ def test_gateway_dto_drops_unknown_upstream_payload_fields(bilibili_api_seam):
     ]
 
 
+# ---------------------------------------------------- subtitle seam scripting
+
+
+def _seam_transport(script: FakeUpstreamScript):
+    """Return the seam's ``Api`` mirror and ``Credential`` double for a script."""
+
+    modules = build_fake_package(script)
+    return modules["bilibili_api.utils.network"].Api, modules["bilibili_api"].Credential
+
+
+def test_fake_seam_mirrors_the_player_endpoint_description():
+    """The fake declares the player description where the pin declares it."""
+
+    script = FakeUpstreamScript()
+    modules = build_fake_package(script)
+
+    assert modules["bilibili_api.video"].API == {
+        "info": {"get_player_info": FAKE_PLAYER_ENDPOINT}
+    }
+    # The description is the script's own object, so a test can rewrite it
+    # before the adapter module is imported against the seam.
+    assert (
+        modules["bilibili_api.video"].API["info"]["get_player_info"]
+        is script.player_endpoint
+    )
+
+
+def test_fake_player_call_records_its_flags_and_parameter_set():
+    """A player call is answered with the scripted payload and fully recorded."""
+
+    script = FakeUpstreamScript()
+    Api, Credential = _seam_transport(script)
+    script.player_response = make_player_response(make_subtitle_track())
+
+    document = asyncio.run(
+        Api(
+            url=FAKE_PLAYER_ENDPOINT["url"],
+            method=FAKE_PLAYER_ENDPOINT["method"],
+            verify=False,
+            wbi=FAKE_PLAYER_ENDPOINT["wbi"],
+            dm=False,
+            credential=Credential(sessdata=SESSDATA_BOUNDARY_VALUE),
+        )
+        .update_params(
+            bvid=BVID, cid=PART_CID, isGaiaAvoided=False, web_location=1315873
+        )
+        .result
+    )
+
+    assert document == make_player_response(make_subtitle_track())
+    (request,) = script.api_requests
+    assert (request.url, request.method, request.wbi, request.verify, request.dm) == (
+        FAKE_PLAYER_ENDPOINT["url"],
+        "GET",
+        True,
+        False,
+        False,
+    )
+    assert request.params == {
+        "bvid": BVID,
+        "cid": PART_CID,
+        "isGaiaAvoided": False,
+        "web_location": 1315873,
+    }
+    # The API-host call carries the credential; the record keeps its presence
+    # only, never the value.
+    assert request.has_sessdata is True
+    assert SESSDATA_BOUNDARY_VALUE not in repr(request)
+    assert script.calls == [f"player.track_list(bvid={BVID}, cid={PART_CID})"]
+
+
+def test_fake_player_call_follows_a_changed_package_endpoint():
+    """No player transport field is hard-coded: the description decides."""
+
+    script = FakeUpstreamScript()
+    Api, Credential = _seam_transport(script)
+    script.player_endpoint["url"] = CHANGED_PLAYER_ENDPOINT_URL
+    script.player_response = make_player_response()
+
+    asyncio.run(
+        Api(
+            url=CHANGED_PLAYER_ENDPOINT_URL,
+            method="GET",
+            verify=False,
+            wbi=True,
+            dm=False,
+            credential=Credential(),
+        )
+        .update_params(bvid=BVID, cid=PART_CID)
+        .result
+    )
+
+    (request,) = script.api_requests
+    assert request.url == CHANGED_PLAYER_ENDPOINT_URL
+    assert script.calls == [f"player.track_list(bvid={BVID}, cid={PART_CID})"]
+
+
+def test_fake_player_call_adds_the_fingerprint_parameters_when_dm_is_on():
+    """With ``dm`` on, the seam injects the parameters the pin would add.
+
+    The risk-control assertion is only meaningful while this double can add
+    the ``dm_*`` parameters a ``dm=True`` call carries upstream.
+    """
+
+    script = FakeUpstreamScript()
+    Api, Credential = _seam_transport(script)
+    script.player_response = make_player_response()
+
+    asyncio.run(
+        Api(
+            url=FAKE_PLAYER_ENDPOINT["url"],
+            method="GET",
+            verify=False,
+            wbi=True,
+            dm=True,
+            credential=Credential(),
+        )
+        .update_params(bvid=BVID, cid=PART_CID)
+        .result
+    )
+
+    (request,) = script.api_requests
+    assert request.dm is True
+    assert sorted(key for key in request.params if key.startswith("dm_")) == [
+        "dm_cover_img_str",
+        "dm_img_inter",
+        "dm_img_list",
+        "dm_img_str",
+    ]
+
+
+def test_fake_subtitle_document_call_answers_a_scripted_body():
+    """A signed-document fetch is answered with the scripted document and recorded."""
+
+    script = FakeUpstreamScript()
+    Api, Credential = _seam_transport(script)
+    script.subtitle_bodies = {
+        SIGNED_SUBTITLE_URL_MARKER: make_subtitle_document(make_subtitle_entry())
+    }
+
+    document = asyncio.run(
+        Api(
+            url=SIGNED_SUBTITLE_URL_MARKER,
+            method="GET",
+            verify=False,
+            wbi=False,
+            dm=False,
+            credential=Credential(),
+        ).request(raw=True)
+    )
+
+    assert document == make_subtitle_document(make_subtitle_entry())
+    (request,) = script.api_requests
+    assert request.url == SIGNED_SUBTITLE_URL_MARKER
+    assert request.raw is True
+    assert request.params == {}
+    # The empty credential keeps SESSDATA off the CDN host; the seam records
+    # that fact without ever comparing credential values.
+    assert request.has_sessdata is False
+    assert script.calls == ["subtitle.body"]
+
+
+def test_fake_subtitle_document_call_scripts_a_transport_failure():
+    """A scripted document failure is raised as scripted, after being recorded."""
+
+    script = FakeUpstreamScript()
+    Api, Credential = _seam_transport(script)
+    script.subtitle_bodies = {
+        SIGNED_SUBTITLE_URL_MARKER: FakeNetworkException(404, UPSTREAM_ERROR_TEXT)
+    }
+
+    with pytest.raises(FakeNetworkException):
+        asyncio.run(
+            Api(
+                url=SIGNED_SUBTITLE_URL_MARKER,
+                method="GET",
+                verify=False,
+                wbi=False,
+                dm=False,
+                credential=Credential(),
+            ).request(raw=True)
+        )
+
+    assert script.calls == ["subtitle.body"]
+
+
+def test_fake_subtitle_document_call_rejects_an_unscripted_url():
+    """An unscripted document URL fails loudly instead of answering ``None``.
+
+    The protocol-relative form is a different URL from the absolute one the
+    seam scripts, so an adapter that forgot to normalize it fails here instead
+    of fetching an unscripted location.
+    """
+
+    assert PROTOCOL_RELATIVE_SUBTITLE_URL.startswith("//")
+    assert PROTOCOL_RELATIVE_SUBTITLE_URL.removeprefix("//") == (
+        SIGNED_SUBTITLE_URL_MARKER.removeprefix("https://")
+    )
+
+    script = FakeUpstreamScript()
+    Api, Credential = _seam_transport(script)
+    script.subtitle_bodies = {SIGNED_SUBTITLE_URL_MARKER: make_subtitle_document()}
+
+    with pytest.raises(AssertionError, match="unexpected subtitle-document fetch"):
+        asyncio.run(
+            Api(
+                url=PROTOCOL_RELATIVE_SUBTITLE_URL,
+                method="GET",
+                verify=False,
+                wbi=False,
+                dm=False,
+                credential=Credential(),
+            ).request(raw=True)
+        )
+
+
+def test_fake_api_mirrors_the_pins_raw_request_argument():
+    """The seam answers a document only when the call asks for the raw body.
+
+    In the pin ``raw`` is a request argument, not a constructor field, and it
+    decides whether the ``data``/``result`` envelope is unwrapped: the scripted
+    metadata payloads are the unwrapped form, while a subtitle document has no
+    envelope at all.
+    """
+
+    script = FakeUpstreamScript()
+    Api, Credential = _seam_transport(script)
+
+    page_call = Api(
+        url=FAKE_USER_VIDEO_PAGE_ENDPOINT["url"],
+        method="GET",
+        verify=False,
+        wbi=True,
+        dm=False,
+        credential=Credential(),
+    )
+    with pytest.raises(AssertionError, match="unwrapped payload"):
+        asyncio.run(page_call.request(raw=True))
+
+    document_call = Api(
+        url=SIGNED_SUBTITLE_URL_MARKER,
+        method="GET",
+        verify=False,
+        wbi=False,
+        dm=False,
+        credential=Credential(),
+    )
+    with pytest.raises(FakeResponseCodeException):
+        asyncio.run(document_call.request(raw=False))
+
+
+def test_fake_api_double_is_no_more_permissive_than_the_pin():
+    """The seam accepts no call shape the pinned ``Api`` would reject.
+
+    ``raw``/``byte`` are ``request`` arguments in the pin; a double that took
+    them at construction would let such a call pass offline and raise
+    ``TypeError`` live, which is exactly the drift this seam exists to prevent.
+
+    Offline and deterministic: the pinned distribution is read for its call
+    shape only, and the fake is built directly (no seam fixture).
+    """
+
+    pinned = _require_installed(_INSTALLED_API_CALL_SHAPE, "Api call shape")
+    Api, _credential = _seam_transport(FakeUpstreamScript())
+
+    mirrored_fields = set(inspect.signature(Api).parameters)
+    assert mirrored_fields <= set(pinned["fields"]), (
+        "the seam accepts a constructor argument the pin's Api does not"
+    )
+    assert "raw" not in mirrored_fields
+    assert "byte" not in mirrored_fields
+
+    mirrored_request = [
+        (parameter.name, str(parameter.kind), parameter.default)
+        for parameter in inspect.signature(Api.request).parameters.values()
+    ]
+    assert mirrored_request == pinned["request"]
+
+
+def test_fake_player_endpoint_mirror_matches_the_installed_pinned_description():
+    """The seam's player description is the installed pin's, field for field.
+
+    ``FAKE_PLAYER_ENDPOINT`` is the sole offline oracle for the player call
+    shape, so its claim to mirror
+    ``bilibili_api.video.API["info"]["get_player_info"]`` literally is checked
+    against the distribution it mirrors.  A pin bump that renames a key or
+    flips ``verify``/``wbi``/``dm`` fails here instead of staying green offline
+    and surfacing only live.
+    """
+
+    pinned_endpoint = _require_installed(
+        _INSTALLED_PINNED_PLAYER_ENDPOINT, "player endpoint description"
+    )
+
+    assert FAKE_PLAYER_ENDPOINT == pinned_endpoint
+    # The facts the adapter's two overrides turn on, stated where a pin bump
+    # would flip them: this endpoint is described as credential-verified and
+    # WBI-signed, and it declares its query fields under ``data`` — field
+    # documentation, not a parameter mapping the adapter may forward verbatim.
+    assert FAKE_PLAYER_ENDPOINT["verify"] is True
+    assert FAKE_PLAYER_ENDPOINT["wbi"] is True
+    assert FAKE_PLAYER_ENDPOINT["dm"] is True
+    assert sorted(FAKE_PLAYER_ENDPOINT["data"]) == [
+        "aid",
+        "cid",
+        "ep_id",
+        "isGaiaAvoided",
+        "web_location",
+    ]
+
+
+def test_the_subtitle_url_sentinel_is_scanned_like_every_other_secret():
+    """The shipped no-secret scanner flags the scripted subtitle URL.
+
+    The seam scripts every track with :data:`SIGNED_SUBTITLE_URL_MARKER`, so
+    the scanner that guards DTOs, messages, and persisted rows must treat it
+    exactly like the playback marker; this is the control that keeps the
+    downstream "no signed URL" assertions from passing vacuously.
+    """
+
+    with pytest.raises(AssertionError):
+        assert_leaks_no_markers(
+            SIGNED_SUBTITLE_URL_MARKER, context="sentinel positive control"
+        )
+
+
 # ------------------------------------------------------------- live smoke
 
 
```
