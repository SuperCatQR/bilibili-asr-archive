# Task 2 Diff — 20260911-subtitle-gateway

Base: `73fdef0`
Head: `7f7156a`

```diff
diff --git a/bilibili-asr-archive/src/bili_asr/sources/__init__.py b/bilibili-asr-archive/src/bili_asr/sources/__init__.py
index 7cc40e7..8203a69 100644
--- a/bilibili-asr-archive/src/bili_asr/sources/__init__.py
+++ b/bilibili-asr-archive/src/bili_asr/sources/__init__.py
@@ -15,6 +15,8 @@ from bili_asr.sources.models import (
     GatewayResponseError,
     GatewayShapeError,
     GatewayTransportError,
+    SubtitleSegment,
+    SubtitleTrack,
     UserVideoPage,
     VideoPart,
     VideoSummary,
@@ -28,6 +30,8 @@ __all__ = [
     "GatewayResponseError",
     "GatewayShapeError",
     "GatewayTransportError",
+    "SubtitleSegment",
+    "SubtitleTrack",
     "UserVideoPage",
     "VideoPart",
     "VideoSummary",
diff --git a/bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py b/bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py
index 0335948..6134bcf 100644
--- a/bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py
+++ b/bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py
@@ -6,6 +6,12 @@ converts one upstream response into validated application DTOs and never
 retains, logs, or returns the response dictionary, credentials, or raw
 exception text.  Upstream failures map onto the bounded exception taxonomy in
 ``bili_asr.sources.models``; only the scalar ``code`` may leave the process.
+
+A signed subtitle URL exists for the duration of one call only: it is resolved
+here — normalized to ``https:`` when upstream answers it protocol-relative —
+handed to the package transport, and never stored on a DTO, a message, or a
+record.  The subtitle-body fetch carries an explicitly empty credential, so the
+API credential never reaches the CDN host.
 """
 
 from __future__ import annotations
@@ -17,7 +23,7 @@ import re
 from collections.abc import Awaitable, Callable, Mapping
 from typing import Any
 
-from bilibili_api import Credential, request_settings, user
+from bilibili_api import Credential, request_settings, user, video
 from bilibili_api.exceptions import (
     ApiException,
     NetworkException,
@@ -26,7 +32,6 @@ from bilibili_api.exceptions import (
     WbiRetryTimesExceedException,
 )
 from bilibili_api.utils.network import Api
-from bilibili_api.video import Video
 
 from bili_asr.config import resolve_proxy
 from bili_asr.sources.models import (
@@ -35,6 +40,8 @@ from bili_asr.sources.models import (
     GatewayResponseError,
     GatewayShapeError,
     GatewayTransportError,
+    SubtitleSegment,
+    SubtitleTrack,
     UserVideoPage,
     VideoPart,
     VideoSummary,
@@ -50,6 +57,12 @@ _NOT_FOUND_API_CODES = frozenset({-404, -62002})
 _RATE_LIMITED_HTTP_STATUSES = frozenset({412, 429})
 _NOT_FOUND_HTTP_STATUSES = frozenset({404})
 
+# The subtitle calls add the login signal to the shipped not-found set: ``-101``
+# means the credential in effect saw nothing for this part, which the caller
+# records as ``no-subtitle``.  The metadata path keeps the shipped set, where
+# ``-101`` stays a generic response error.
+_SUBTITLE_NOT_FOUND_API_CODES = _NOT_FOUND_API_CODES | {-101}
+
 # Same shape check the package itself applies in Video.set_bvid.
 _BVID_PATTERN = re.compile(r"^BV[a-zA-Z0-9]{10}$")
 
@@ -60,6 +73,13 @@ _BVID_PATTERN = re.compile(r"^BV[a-zA-Z0-9]{10}$")
 # ``BilibiliApiGateway._fetch_user_video_page``).
 _USER_VIDEO_PAGE_ENDPOINT = user.API["info"]["video"]
 
+# The package's own endpoint description for the player call
+# (``bilibili_api.video.API["info"]["get_player_info"]``), whose unwrapped
+# payload carries the part's subtitle inventory.  ``url``/``method``/``wbi``
+# are read from it for the same reason; ``dm`` and ``verify`` are deliberately
+# overridden per call (see ``BilibiliApiGateway._fetch_subtitle_inventory``).
+_PLAYER_INFO_ENDPOINT = video.API["info"]["get_player_info"]
+
 
 def _require_positive_argument(value: object, field: str) -> None:
     """Reject caller-argument violations before any upstream call."""
@@ -211,6 +231,219 @@ def _normalize_video_parts(pages: object, bvid: str) -> tuple[VideoPart, ...]:
     return tuple(_normalize_video_part_item(item, bvid) for item in pages)
 
 
+def _extract_subtitle_entries(response: object) -> list:
+    """Extract the player payload's ``subtitle.subtitles`` inventory array.
+
+    A payload that carries no subtitle container, and a container that carries
+    no ``subtitles`` list at all, are an empty inventory — the honest reading of
+    a probe whose credential saw nothing, and a legitimate result rather than a
+    failure.  A present container of another shape cannot be read as an
+    inventory at all and is a bounded shape error.
+    """
+
+    if not isinstance(response, Mapping):
+        raise GatewayShapeError(detail="player response is not a mapping")
+    subtitle = response.get("subtitle")
+    if subtitle is None:
+        return []
+    if not isinstance(subtitle, Mapping):
+        raise GatewayShapeError(detail="player subtitle is not a mapping")
+    entries = subtitle.get("subtitles")
+    if entries is None:
+        return []
+    if not isinstance(entries, list):
+        raise GatewayShapeError(detail="player subtitles is not an array")
+    return entries
+
+
+def _normalize_subtitle_tracks(entries: object) -> tuple[SubtitleTrack, ...]:
+    """Convert the inventory array into validated track DTOs."""
+
+    if not isinstance(entries, list):
+        raise GatewayShapeError(detail="subtitle inventory is not an array")
+    return tuple(_normalize_subtitle_track(entry) for entry in entries)
+
+
+def _normalize_subtitle_track(entry: object) -> SubtitleTrack:
+    """Convert one inventory entry into a validated, trimmed track DTO.
+
+    ``lan``/``lan_doc`` are trimmed here so the caller can print them as-is,
+    and the entry's own AI marker decides ``is_ai``.  The signed
+    ``subtitle_url`` the entry also carries is deliberately not read: it never
+    crosses the gateway boundary.
+    """
+
+    if not isinstance(entry, Mapping):
+        raise GatewayShapeError(detail="subtitle track is not a mapping")
+    language = entry.get("lan")
+    if not isinstance(language, str) or not language.strip():
+        raise GatewayShapeError(detail="subtitle track has no language")
+    label = entry.get("lan_doc")
+    if not isinstance(label, str) or not label.strip():
+        raise GatewayShapeError(detail="subtitle track has no label")
+    try:
+        return SubtitleTrack(
+            language=language.strip(),
+            label=label.strip(),
+            is_ai=_read_track_is_ai(entry),
+            track_id=_read_optional_track_id(entry.get("id")),
+        )
+    except (TypeError, ValueError) as exc:
+        raise GatewayShapeError(detail="subtitle track is not normalizable") from exc
+
+
+def _read_optional_track_id(value: object) -> str | None:
+    """Read an entry's ``id`` as the track-identity string, when present.
+
+    Absent stays absent; a present value must be the upstream integer id, which
+    is rendered as the string the DTO carries.
+    """
+
+    if value is None:
+        return None
+    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
+        raise GatewayShapeError(detail="subtitle track has no valid id")
+    return str(value)
+
+
+def _read_track_is_ai(entry: Mapping) -> bool:
+    """Derive ``is_ai`` from the entry's own upstream AI markers.
+
+    ``ai_status`` is ``0`` for a track that never touched machine processing and
+    positive once it did; ``type`` is ``1`` for a machine-generated caption.  A
+    track carrying neither marker is reported as CC — the conservative reading
+    the product semantics lock — and the ``lan`` prefix is deliberately not
+    consulted, because the marker is the locked signal.
+    """
+
+    ai_status = _read_ai_marker(entry, "ai_status")
+    caption_type = _read_ai_marker(entry, "type")
+    return (ai_status is not None and ai_status > 0) or caption_type == 1
+
+
+def _read_ai_marker(entry: Mapping, field: str) -> int | None:
+    """Read one optional non-negative integer AI marker from an entry."""
+
+    value = entry.get(field)
+    if value is None:
+        return None
+    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
+        raise GatewayShapeError(
+            detail=f"subtitle track has an invalid {field} marker"
+        )
+    return value
+
+
+def _resolve_subtitle_document_url(track: SubtitleTrack, entries: list) -> str:
+    """Resolve one requested track's signed document URL from a fresh listing.
+
+    A track is matched on ``language`` + ``is_ai``.  Several matches are broken
+    by the requested ``track_id`` when the request carries one; otherwise the
+    listing is ambiguous and the call fails as a bounded shape error.  No match
+    at all means the track is not visible any more (``not_found``).  The
+    resolved URL is returned for the duration of one call only and never
+    reaches a DTO or an error message.
+    """
+
+    listed = [(_normalize_subtitle_track(entry), entry) for entry in entries]
+    candidates = [
+        (candidate, entry)
+        for candidate, entry in listed
+        if candidate.language == track.language and candidate.is_ai == track.is_ai
+    ]
+    if not candidates:
+        raise GatewayNotFound(detail="fetch_subtitle_segments")
+    if len(candidates) > 1 and track.track_id is not None:
+        identified = [
+            (candidate, entry)
+            for candidate, entry in candidates
+            if candidate.track_id == track.track_id
+        ]
+        if len(identified) == 1:
+            candidates = identified
+    if len(candidates) > 1:
+        raise GatewayShapeError(detail="subtitle track match is ambiguous")
+    return _read_subtitle_document_url(candidates[0][1])
+
+
+def _read_subtitle_document_url(entry: Mapping) -> str:
+    """Read one entry's signed document URL, normalized to ``https:``.
+
+    Upstream answers the URL sometimes absolutely and sometimes
+    protocol-relative; the normalized absolute form is what the package
+    transport is handed, and it stays process-local.
+    """
+
+    url = entry.get("subtitle_url")
+    if not isinstance(url, str) or not url.strip():
+        raise GatewayShapeError(detail="subtitle track has no document URL")
+    normalized = url.strip()
+    if normalized.startswith("//"):
+        normalized = f"https:{normalized}"
+    return normalized
+
+
+def _normalize_subtitle_document(document: object) -> tuple[SubtitleSegment, ...]:
+    """Convert one subtitle document into the caption rows that survive.
+
+    A document that cannot be read as a subtitle document at all raises a
+    bounded shape error; a row that reads as a segment but carries nothing
+    usable is dropped, so every other row of the document stays usable.
+    """
+
+    if not isinstance(document, Mapping):
+        raise GatewayShapeError(detail="subtitle document is not a mapping")
+    body = document.get("body")
+    if not isinstance(body, list):
+        raise GatewayShapeError(detail="subtitle document has no body array")
+    return tuple(
+        segment
+        for segment in (_normalize_subtitle_segment(entry) for entry in body)
+        if segment is not None
+    )
+
+
+def _normalize_subtitle_segment(entry: object) -> SubtitleSegment | None:
+    """Convert one caption row, or drop it when it carries nothing usable.
+
+    The conversion is the metadata path's ``floor(seconds * 1000)``, and the
+    drop rules are evaluated on the converted milliseconds: a row survives
+    exactly when ``end_ms > start_ms >= 0`` with text non-empty after
+    stripping.  ``None`` marks a dropped row — a per-row tolerance, never a
+    document-level failure.
+    """
+
+    if not isinstance(entry, Mapping):
+        raise GatewayShapeError(detail="subtitle entry is not a mapping")
+    start_ms = _read_caption_milliseconds(entry, "from")
+    end_ms = _read_caption_milliseconds(entry, "to")
+    content = entry.get("content")
+    if not isinstance(content, str):
+        raise GatewayShapeError(detail="subtitle entry has no content")
+    text = content.strip()
+    if start_ms < 0 or end_ms <= start_ms or not text:
+        return None
+    return SubtitleSegment(start_ms=start_ms, end_ms=end_ms, text=text)
+
+
+def _read_caption_milliseconds(entry: Mapping, field: str) -> int:
+    """Read one caption timestamp as milliseconds, using ``floor``.
+
+    A missing, non-numeric, boolean, or non-finite value cannot be read as a
+    segment at all, and neither can a finite value whose millisecond product
+    leaves the float range: both stay bounded shape errors instead of escaping
+    as ``ValueError``/``OverflowError`` out of ``math.floor``.
+    """
+
+    seconds = entry.get(field)
+    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
+        raise GatewayShapeError(detail=f"subtitle entry has no numeric {field}")
+    milliseconds = seconds * 1000
+    if isinstance(milliseconds, float) and not math.isfinite(milliseconds):
+        raise GatewayShapeError(detail=f"subtitle entry has an unreadable {field}")
+    return math.floor(milliseconds)
+
+
 def _complete_summary_from_detail(
     summary: VideoSummary, detail: object
 ) -> VideoSummary:
@@ -305,7 +538,7 @@ class BilibiliApiGateway:
             raise ValueError("bvid must be a BV-prefixed 10-character id")
         pages = await self._await_upstream(
             "get_video_parts",
-            lambda: Video(bvid=bvid, credential=self._credential).get_pages(),
+            lambda: video.Video(bvid=bvid, credential=self._credential).get_pages(),
         )
         return _normalize_video_parts(pages, bvid)
 
@@ -322,10 +555,73 @@ class BilibiliApiGateway:
             return summary
         detail = await self._await_upstream(
             "get_completed_video_summary",
-            lambda: Video(bvid=summary.bvid, credential=self._credential).get_info(),
+            lambda: video.Video(
+                bvid=summary.bvid, credential=self._credential
+            ).get_info(),
         )
         return _complete_summary_from_detail(summary, detail)
 
+    async def get_subtitle_tracks(
+        self, bvid: str, cid: int
+    ) -> tuple[SubtitleTrack, ...]:
+        """List the subtitle inventory one part exposes right now.
+
+        One WBI-signed player call in the locked shape (section 1.2 of the
+        gateway spec) and one normalized track per inventory entry, in upstream
+        order.  An inventory the credential in effect could not see is an empty
+        tuple — never a ``not_found`` failure and never a placeholder track.
+        """
+
+        if not isinstance(bvid, str) or _BVID_PATTERN.fullmatch(bvid) is None:
+            raise ValueError("bvid must be a BV-prefixed 10-character id")
+        _require_positive_argument(cid, "cid")
+        entries = await self._list_subtitle_entries(
+            bvid, cid, operation="get_subtitle_tracks"
+        )
+        return _normalize_subtitle_tracks(entries)
+
+    async def fetch_subtitle_segments(
+        self, track: SubtitleTrack, bvid: str, cid: int
+    ) -> tuple[SubtitleSegment, ...]:
+        """Fetch and normalize one requested track's caption document.
+
+        The signed URL never crosses the boundary, so the requested track is
+        resolved through a fresh listing of the part.  A body fetch that fails
+        in the expiry/transport class gets exactly one more listing + fetch
+        pair; rate control and every other classified failure propagate as they
+        are.  Nothing usable — an empty document included — is
+        ``GatewayNotFound``, and the return is never an empty tuple.
+        """
+
+        if not isinstance(track, SubtitleTrack):
+            raise TypeError("track must be a SubtitleTrack")
+        if not isinstance(bvid, str) or _BVID_PATTERN.fullmatch(bvid) is None:
+            raise ValueError("bvid must be a BV-prefixed 10-character id")
+        _require_positive_argument(cid, "cid")
+
+        entries = await self._list_subtitle_entries(
+            bvid, cid, operation="fetch_subtitle_segments"
+        )
+        try:
+            document = await self._fetch_subtitle_document(
+                _resolve_subtitle_document_url(track, entries)
+            )
+            segments = _normalize_subtitle_document(document)
+        except GatewayTransportError:
+            # A signature that no longer works is the one failure class worth a
+            # second attempt: re-list once for a fresh URL and fetch once more.
+            # There is no third attempt and no loop.
+            entries = await self._list_subtitle_entries(
+                bvid, cid, operation="fetch_subtitle_segments"
+            )
+            document = await self._fetch_subtitle_document(
+                _resolve_subtitle_document_url(track, entries)
+            )
+            segments = _normalize_subtitle_document(document)
+        if not segments:
+            raise GatewayNotFound(detail="fetch_subtitle_segments")
+        return segments
+
     def get_package_version(self) -> str:
         """Return the pinned package version for run metadata."""
 
@@ -373,6 +669,82 @@ class BilibiliApiGateway:
             .result
         )
 
+    async def _fetch_subtitle_inventory(self, bvid: str, cid: int) -> Any:
+        """Issue one WBI-signed player request in the locked call shape.
+
+        ``url``/``method``/``wbi`` are read from the package's own endpoint
+        description, and the parameters are that description's declared set
+        with ``bvid`` substituted for the declared ``aid`` alternative, so one
+        request per part is paid and no aid-resolution call is added.  Two
+        fields are this adapter's: ``verify`` is turned off, because the pin's
+        ``verify=True`` performs no upstream check at all — it only raises
+        locally when no SESSDATA is configured, which would turn an honest
+        anonymous probe into an exception — and ``dm`` is turned off, because
+        the device-fingerprint parameters it would add cannot be supplied
+        truthfully and the sibling WBI endpoint in the same risk-control family
+        answered HTTP 412 with them.  Neither ``need_login_subtitle`` nor
+        ``w_webid`` is sent: the installed pin declares neither for this
+        endpoint, and the package's own player call sends neither.
+        """
+
+        return await (
+            Api(
+                url=_PLAYER_INFO_ENDPOINT["url"],
+                method=_PLAYER_INFO_ENDPOINT["method"],
+                verify=False,
+                wbi=_PLAYER_INFO_ENDPOINT["wbi"],
+                dm=False,
+                credential=self._credential,
+            )
+            .update_params(
+                bvid=bvid,
+                cid=cid,
+                isGaiaAvoided=False,
+                web_location=1315873,
+            )
+            .result
+        )
+
+    async def _list_subtitle_entries(
+        self, bvid: str, cid: int, *, operation: str
+    ) -> list:
+        """List one part's subtitle inventory entries through the taxonomy.
+
+        ``operation`` is the public method this listing serves, so a mapped
+        failure names the boundary the caller invoked.  The subtitle calls pass
+        the extended not-found set, where ``-101`` means "nothing visible under
+        this credential" rather than a generic response error.
+        """
+
+        response = await self._await_upstream(
+            operation,
+            lambda: self._fetch_subtitle_inventory(bvid, cid),
+            not_found_api_codes=_SUBTITLE_NOT_FOUND_API_CODES,
+        )
+        return _extract_subtitle_entries(response)
+
+    async def _fetch_subtitle_document(self, url: str) -> Any:
+        """Fetch one signed subtitle document through the package transport.
+
+        The call is built with an explicitly empty ``Credential()``, so the API
+        credential never reaches the CDN host, and it is issued as
+        ``request(raw=True)``: a subtitle document carries no ``code``/``data``
+        envelope for the pin's default unwrapping to strip.  The URL is a
+        parameter of this call only and is never stored anywhere.
+        """
+
+        return await self._await_upstream(
+            "fetch_subtitle_segments",
+            lambda: Api(
+                url=url,
+                method="GET",
+                wbi=False,
+                dm=False,
+                verify=False,
+                credential=Credential(),
+            ).request(raw=True),
+        )
+
     async def _resolve_w_webid(self, mid: int) -> str:
         """Resolve the page request's ``w_webid`` parameter for one user.
 
@@ -399,13 +771,20 @@ class BilibiliApiGateway:
         return self._w_webid_by_mid[mid]
 
     async def _await_upstream(
-        self, operation: str, call: Callable[[], Awaitable[Any]]
+        self,
+        operation: str,
+        call: Callable[[], Awaitable[Any]],
+        *,
+        not_found_api_codes: frozenset[int] = _NOT_FOUND_API_CODES,
     ) -> Any:
         """Await one upstream call and map its failures onto the taxonomy.
 
         The mapped exception message carries the bounded code and the
         operation name only; upstream text, URLs, and payload content stay
-        process-local.
+        process-local.  ``not_found_api_codes`` is the not-found set of the
+        boundary being served: the metadata path keeps the shipped one, where
+        ``-101`` is a response error, while the subtitle calls extend it so the
+        login signal reads as "not visible".
         """
 
         try:
@@ -419,7 +798,7 @@ class BilibiliApiGateway:
         except ResponseCodeException as exc:
             if exc.code in _RATE_LIMITED_API_CODES:
                 raise GatewayRateLimited(detail=operation) from exc
-            if exc.code in _NOT_FOUND_API_CODES:
+            if exc.code in not_found_api_codes:
                 raise GatewayNotFound(detail=operation) from exc
             raise GatewayResponseError(detail=operation) from exc
         except WbiRetryTimesExceedException as exc:
diff --git a/bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py b/bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py
index d26ec2e..92dcbd1 100644
--- a/bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py
+++ b/bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py
@@ -40,9 +40,11 @@ Every package-seam test scripts these fakes instead of touching the pinned
   pins the upstream call names the gateway may issue.
 - ``NO_LEAK_MARKERS`` with ``assert_leaks_no_markers`` holds the
   realistic-looking secret and raw-payload sentinel texts (a SESSDATA
-  value, a signed playback URL, a raw JSON response body, and raw upstream
-  exception text) plus the scanner behind the no-secret assertions, and
-  ``persisted_row_text`` renders persisted rows for those assertions.
+  value, a signed playback URL, the signed subtitle-document URL in both the
+  absolute and the protocol-relative form upstream answers, a raw JSON
+  response body, and raw upstream exception text) plus the scanner behind the
+  no-secret assertions, and ``persisted_row_text`` renders persisted rows for
+  those assertions.
 """
 
 from __future__ import annotations
@@ -128,8 +130,16 @@ FAKE_PLAYER_ENDPOINT = {
 #: itself through the package's ``Api``: the package's ``User.get_videos``
 #: delegate cannot pass upstream risk control (it injects device-fingerprint
 #: ``dm`` parameters and scrapes ``w_webid`` from a page that no longer
-#: server-renders it).
-DOCUMENTED_METADATA_CALLS = ("space.arc.search", "video.get_info", "video.get_pages")
+#: server-renders it).  The two subtitle-acquisition routes are the plan's own
+#: authorized surface: the player track listing and the signed subtitle
+#: document.  The set is exact — nothing else may appear.
+DOCUMENTED_METADATA_CALLS = (
+    "space.arc.search",
+    "video.get_info",
+    "video.get_pages",
+    "player.track_list",
+    "subtitle.body",
+)
 
 #: Realistic-looking SESSDATA value that must never leave the process.
 SESSDATA_BOUNDARY_VALUE = "SESSDATA-VALUE-THAT-MUST-NOT-LEAK"
@@ -158,11 +168,15 @@ RAW_JSON_BODY_MARKER = '{"code":-412,"message":"RAW-JSON-BODY-THAT-MUST-NOT-LEAK
 #: Realistic-looking raw upstream exception text that must never be persisted.
 RAW_UPSTREAM_EXCEPTION_MARKER = "RAW-UPSTREAM-EXCEPTION-THAT-MUST-NOT-LEAK"
 
-#: All sentinels the no-secret assertions scan persisted surfaces for.
+#: All sentinels the no-secret assertions scan persisted surfaces for.  The
+#: subtitle-document URL is held in both forms upstream answers it in — the
+#: absolute one and the protocol-relative one — so a URL that skipped the
+#: adapter's ``https:`` normalization is still caught by the scanner.
 NO_LEAK_MARKERS = (
     SESSDATA_BOUNDARY_VALUE,
     SIGNED_URL_MARKER,
     SIGNED_SUBTITLE_URL_MARKER,
+    PROTOCOL_RELATIVE_SUBTITLE_URL,
     RAW_JSON_BODY_MARKER,
     RAW_UPSTREAM_EXCEPTION_MARKER,
 )
diff --git a/bilibili-asr-archive/tests/test_bilibili_api_gateway.py b/bilibili-asr-archive/tests/test_bilibili_api_gateway.py
index 24cd7ed..9a5f88c 100644
--- a/bilibili-asr-archive/tests/test_bilibili_api_gateway.py
+++ b/bilibili-asr-archive/tests/test_bilibili_api_gateway.py
@@ -56,10 +56,12 @@ from bili_asr.sources.models import (
 from bili_asr.storage.database import MetadataRepository, open_database
 from fixtures.fake_bilibili_gateway import (
     BVID,
+    DOCUMENTED_METADATA_CALLS,
     FAKE_PLAYER_ENDPOINT,
     FAKE_USER_VIDEO_PAGE_ENDPOINT,
     MID,
     MIRRORED_ENDPOINT_FIELDS,
+    NO_LEAK_MARKERS,
     PROTOCOL_RELATIVE_SUBTITLE_URL,
     PUBDATE,
     RAW_JSON_BODY_MARKER,
@@ -73,6 +75,7 @@ from fixtures.fake_bilibili_gateway import (
     FakeUpstreamScript,
     FakeWbiRetryTimesExceedException,
     assert_leaks_no_markers,
+    assert_only_documented_metadata_calls,
     bilibili_api_seam,
     build_fake_package,
     make_detail_response,
@@ -102,11 +105,13 @@ PACKAGE_HTTP_CLIENT_CANONICAL_NAMES = frozenset({"curl-cffi", "httpx", "aiohttp"
 
 #: The exact bilibili_api import surface the adapter is allowed to use.  The
 #: user-video page call is issued through ``user``'s own endpoint description
-#: and the WBI-signed ``utils.network.Api``, not through a ``user`` delegate.
+#: and the WBI-signed ``utils.network.Api``, not through a ``user`` delegate;
+#: the subtitle call reads its transport fields from ``video``'s own player
+#: endpoint description the same way, so both endpoint-description modules come
+#: from the package root and the WBI-signed ``Api`` stays the one request path.
 ALLOWED_PACKAGE_IMPORTS = {
-    "bilibili_api": {"Credential", "request_settings", "user"},
+    "bilibili_api": {"Credential", "request_settings", "user", "video"},
     "bilibili_api.utils.network": {"Api"},
-    "bilibili_api.video": {"Video"},
     "bilibili_api.exceptions": {
         "ApiException",
         "NetworkException",
@@ -140,6 +145,13 @@ CHANGED_PLAYER_ENDPOINT_URL = (
 )
 
 
+#: A second signed subtitle-document URL for one part.  It extends the seam's
+#: sentinel — so a leak of it is still caught by the no-secret scanner — and it
+#: lets a test prove the ``track_id`` tie-break fetched the entry the request
+#: named rather than the first match.
+SECOND_SUBTITLE_URL = SIGNED_SUBTITLE_URL_MARKER + "&second=1"
+
+
 def _probe_installed_pinned_endpoint() -> dict | str:
     """Read the pin's endpoint description, or the reason it could not be read.
 
@@ -265,22 +277,39 @@ ALLOWED_EXCEPTION_NAMES = (
     "WbiRetryTimesExceedException",
 )
 
-#: Attribute names that would mark playback/subtitle/audio/ASR/export usage.
-#: Tokens are matched as plain substrings, so only unambiguous names belong
-#: here (``stream`` would false-positive on ``_await_upstream``).
+#: Attribute names that would mark playback/danmaku/audio/ASR/export usage —
+#: the surfaces outside this plan's boundary.  Tokens are matched as plain
+#: substrings, so only unambiguous names belong here (``stream`` would
+#: false-positive on ``_await_upstream``).  The subtitle-acquisition family
+#: (``subtitle``, ``player``, ``download``) was removed here on 2026-09-11 by
+#: the PM-authorized Task-2 update: this plan legitimately issues the player and
+#: subtitle-document calls, and
+#: ``test_gateway_source_never_names_forbidden_seam_methods`` now positively
+#: asserts that surface instead (see ``AUTHORIZED_SUBTITLE_ATTRIBUTES``).
 FORBIDDEN_SEAM_METHOD_TOKENS = (
-    "subtitle",
     "playback",
     "playurl",
     "play_url",
-    "download",
     "danmaku",
-    "player",
     "audio",
     "asr",
     "export",
 )
 
+#: The tokens the authorized update removed from the forbidden list.  They are
+#: kept here only so the positive control below can prove the removal is
+#: load-bearing: each asserted attribute name still carries one of them.
+AUTHORIZED_SEAM_METHOD_TOKENS = ("subtitle", "player", "download")
+
+#: The adapter's own subtitle-surface attributes the token scan must be able to
+#: see.  Asserting them present keeps the forbidden-token check non-vacuous: it
+#: cannot pass merely because the adapter carries no subtitle code at all.
+AUTHORIZED_SUBTITLE_ATTRIBUTES = (
+    "_fetch_subtitle_document",
+    "_fetch_subtitle_inventory",
+    "_list_subtitle_entries",
+)
+
 
 def _public_names(obj: object) -> list[str]:
     """List the public (non-dunder) names on a module or class."""
@@ -1598,7 +1627,7 @@ def test_subtitle_dtos_are_frozen():
 
 
 def test_gateway_protocol_surface_is_locked():
-    """The protocol declares the locked six methods, signatures included.
+    """The protocol declares exactly the locked six methods, signatures included.
 
     The four shipped signatures stay untouched — the shipped metadata service
     and the storage plan consume them — and the two subtitle methods are
@@ -1606,6 +1635,9 @@ def test_gateway_protocol_surface_is_locked():
     possibly empty tuple (an empty inventory is an observation, never a
     ``not_found`` failure), while ``fetch_subtitle_segments(track, bvid, cid)``
     answers a non-empty tuple or raises ``GatewayNotFound``.
+
+    The declaration set is asserted exactly, not method by method: a seventh
+    protocol method fails here instead of slipping through unread.
     """
 
     expected = {
@@ -1618,8 +1650,9 @@ def test_gateway_protocol_surface_is_locked():
     }
 
     declared = {
-        name: tuple(inspect.signature(getattr(BilibiliGateway, name)).parameters)
-        for name in expected
+        name: tuple(inspect.signature(member).parameters)
+        for name, member in vars(BilibiliGateway).items()
+        if not name.startswith("_")
     }
 
     assert declared == expected
@@ -1662,9 +1695,12 @@ def test_gateway_imports_stay_on_metadata_surface():
     """The adapter imports exactly the enforced allow-list, nothing broader.
 
     ``ALLOWED_PACKAGE_IMPORTS`` is compared exactly: ``Credential`` and the
-    ``request_settings``/``user`` modules from the package root, the
-    WBI-signed ``utils.network.Api``, ``video.Video``, and the five exception
-    names.  ``User`` is deliberately not among them — the page call goes
+    ``request_settings``/``user``/``video`` modules from the package root, the
+    WBI-signed ``utils.network.Api``, and the five exception names.  Both
+    endpoint-description modules come from the package root — the subtitle call
+    reads ``video.API["info"]["get_player_info"]`` the way the page call reads
+    ``user.API["info"]["video"]``, and ``utils.network.Api`` stays the one
+    request path.  ``User`` is deliberately not among them: the page call goes
     through the ``user`` module's endpoint description and the package ``Api``,
     never a ``user.User`` delegate.
     """
@@ -1691,7 +1727,14 @@ def test_gateway_imports_stay_on_metadata_surface():
 
 
 def test_gateway_source_never_names_forbidden_seam_methods():
-    """The adapter source never references playback/subtitle/audio names."""
+    """The adapter source stays off every surface outside this plan's boundary.
+
+    ``FORBIDDEN_SEAM_METHOD_TOKENS`` no longer carries the authorized
+    subtitle-acquisition family, so the second positive control below asserts
+    that family's own attributes are present *and* that they still carry a
+    removed token: re-forbidding the removal fails there instead of letting the
+    scan pass because the adapter has no subtitle code to see.
+    """
 
     gateway_path = (
         pathlib.Path(__file__).resolve().parent.parent
@@ -1717,6 +1760,14 @@ def test_gateway_source_never_names_forbidden_seam_methods():
     assert {"get_access_id", "update_params", "get_pages", "get_info"} <= (
         attribute_names
     )
+    # Second positive control: the authorized subtitle surface is present, and
+    # every asserted name is one the removed tokens would have flagged.
+    assert set(AUTHORIZED_SUBTITLE_ATTRIBUTES) <= attribute_names
+    for name in AUTHORIZED_SUBTITLE_ATTRIBUTES:
+        assert any(token in name.lower() for token in AUTHORIZED_SEAM_METHOD_TOKENS), (
+            f"{name!r} does not carry a removed token, so it cannot prove the"
+            " authorized removal is load-bearing"
+        )
 
 
 def test_fake_seam_exposes_only_documented_metadata_surface():
@@ -2113,14 +2164,928 @@ def test_the_subtitle_url_sentinel_is_scanned_like_every_other_secret():
 
     The seam scripts every track with :data:`SIGNED_SUBTITLE_URL_MARKER`, so
     the scanner that guards DTOs, messages, and persisted rows must treat it
-    exactly like the playback marker; this is the control that keeps the
-    downstream "no signed URL" assertions from passing vacuously.
+    exactly like the playback marker.  The protocol-relative form upstream also
+    answers is scanned too, so a URL that skipped the adapter's ``https:``
+    normalization cannot slip past the scan; together these are the control
+    that keeps the downstream "no signed URL" assertions from passing
+    vacuously.
     """
 
     with pytest.raises(AssertionError):
         assert_leaks_no_markers(
             SIGNED_SUBTITLE_URL_MARKER, context="sentinel positive control"
         )
+    with pytest.raises(AssertionError):
+        assert_leaks_no_markers(
+            PROTOCOL_RELATIVE_SUBTITLE_URL, context="relative sentinel control"
+        )
+    assert PROTOCOL_RELATIVE_SUBTITLE_URL in NO_LEAK_MARKERS
+    assert SIGNED_SUBTITLE_URL_MARKER in NO_LEAK_MARKERS
+
+
+def test_sources_package_reexports_the_subtitle_dtos_only():
+    """``bili_asr.sources`` re-exports the new DTOs, never the adapter.
+
+    The package ``__init__`` is the models re-export surface — it must stay
+    importable without the pinned package — so the two subtitle DTOs belong
+    there while ``BilibiliApiGateway`` stays an explicit import, exactly as
+    before.
+    """
+
+    import bili_asr.sources as sources
+
+    assert sources.SubtitleTrack is SubtitleTrack
+    assert sources.SubtitleSegment is SubtitleSegment
+    assert "SubtitleTrack" in sources.__all__
+    assert "SubtitleSegment" in sources.__all__
+    assert not hasattr(sources, "BilibiliApiGateway")
+
+
+def test_the_documented_call_allow_list_carries_exactly_the_authorized_routes():
+    """The seam's call-name guard allows exactly the documented routes.
+
+    The two subtitle-acquisition routes are authorized by this plan; the set
+    stays exact, and a call outside it is still rejected by the shipped guard
+    (the control that keeps the allow-list from passing vacuously).
+    """
+
+    assert DOCUMENTED_METADATA_CALLS == (
+        "space.arc.search",
+        "video.get_info",
+        "video.get_pages",
+        "player.track_list",
+        "subtitle.body",
+    )
+    assert_only_documented_metadata_calls(list(DOCUMENTED_METADATA_CALLS))
+    with pytest.raises(AssertionError):
+        assert_only_documented_metadata_calls(["playurl.get"])
+
+
+# ------------------------------------------------- adapter: subtitle listing
+
+
+def _load_subtitle_gateway(seam, *tracks: object, sessdata: str | None = None):
+    """Script one player inventory on the seam and build the adapter for it."""
+
+    seam.player_response = make_player_response(*tracks)
+    return _load_gateway(sessdata=sessdata)
+
+
+def _seam_track(**overrides: object) -> SubtitleTrack:
+    """Build the DTO the seam's default inventory entry lists as.
+
+    The seam's default entry is an uploader/CC ``zh-CN`` track carrying
+    ``id=1``, so this is exactly what the listing would have returned for it.
+    """
+
+    values: dict[str, object] = {
+        "language": "zh-CN",
+        "label": "中文（中国）",
+        "is_ai": False,
+        "track_id": "1",
+    }
+    values.update(overrides)
+    return SubtitleTrack(**values)
+
+
+def _listing_call(*, bvid: str = BVID, cid: int = PART_CID) -> str:
+    """The call name the seam records for one player track listing."""
+
+    return f"player.track_list(bvid={bvid}, cid={cid})"
+
+
+def _subtitle_row(start: float, end: float, content: object, **extra: object) -> dict:
+    """Build one caption row in the document's own seconds.
+
+    ``from``/``to`` are Python keywords, so a row is assembled as a mapping
+    rather than through keyword arguments.
+    """
+
+    row: dict = {"from": start, "to": end, "content": content}
+    row.update(extra)
+    return row
+
+
+def test_get_subtitle_tracks_normalizes_ai_and_cc_tracks(bilibili_api_seam):
+    """One bounded call maps ``lan``/``lan_doc`` and the AI marker into DTOs."""
+
+    gateway = _load_subtitle_gateway(
+        bilibili_api_seam,
+        make_subtitle_track(
+            id=7, lan="  ai-zh  ", lan_doc="  中文（自动生成）  ", ai_status=1
+        ),
+        make_subtitle_track(id=9, lan="zh-CN", lan_doc=" 中文（中国） ", type=0),
+        sessdata=SESSDATA_BOUNDARY_VALUE,
+    )
+
+    tracks = asyncio.run(gateway.get_subtitle_tracks(BVID, PART_CID))
+
+    assert tracks == (
+        SubtitleTrack(
+            language="ai-zh", label="中文（自动生成）", is_ai=True, track_id="7"
+        ),
+        SubtitleTrack(
+            language="zh-CN", label="中文（中国）", is_ai=False, track_id="9"
+        ),
+    )
+    assert bilibili_api_seam.calls == [_listing_call()]
+    for rendered in (repr(tracks), str(tracks)):
+        assert_leaks_no_markers(rendered, context="subtitle track DTO")
+        assert SESSDATA_BOUNDARY_VALUE not in rendered
+
+
+@pytest.mark.parametrize(
+    ("entry_overrides", "expected_is_ai"),
+    [
+        ({"ai_status": 1}, True),
+        ({"ai_status": 2}, True),
+        ({"type": 1}, True),
+        ({"ai_status": 0}, False),
+        ({"type": 0}, False),
+        ({"ai_status": 0, "type": 0}, False),
+        ({}, False),
+        # Neither marker is present, so the locked conservative reading reports
+        # CC even when the language looks machine-generated.
+        ({"lan": "ai-zh"}, False),
+        ({"lan": "ai-zh", "type": 1}, True),
+    ],
+)
+def test_get_subtitle_tracks_reads_the_upstream_ai_markers(
+    bilibili_api_seam, entry_overrides, expected_is_ai
+):
+    """``is_ai`` comes from the entry's own markers, never from its language."""
+
+    gateway = _load_subtitle_gateway(
+        bilibili_api_seam, make_subtitle_track(**entry_overrides)
+    )
+
+    (track,) = asyncio.run(gateway.get_subtitle_tracks(BVID, PART_CID))
+
+    assert track.is_ai is expected_is_ai
+
+
+@pytest.mark.parametrize(
+    "broken_marker",
+    [
+        {"ai_status": "1"},
+        {"ai_status": True},
+        {"ai_status": -1},
+        {"ai_status": 1.0},
+        {"type": "1"},
+        {"type": True},
+        {"type": -1},
+    ],
+)
+def test_get_subtitle_tracks_rejects_a_malformed_ai_marker(
+    bilibili_api_seam, broken_marker
+):
+    """A present marker must be the upstream integer: rejected, never coerced."""
+
+    gateway = _load_subtitle_gateway(
+        bilibili_api_seam, make_subtitle_track(**broken_marker)
+    )
+
+    with pytest.raises(GatewayShapeError) as caught:
+        asyncio.run(gateway.get_subtitle_tracks(BVID, PART_CID))
+
+    assert caught.value.code == "shape_error"
+
+
+def test_get_subtitle_tracks_reads_the_optional_track_identity(bilibili_api_seam):
+    """The upstream integer id becomes the DTO's identity string."""
+
+    gateway = _load_subtitle_gateway(bilibili_api_seam, make_subtitle_track(id=42))
+
+    (track,) = asyncio.run(gateway.get_subtitle_tracks(BVID, PART_CID))
+
+    assert track.track_id == "42"
+
+
+def test_get_subtitle_tracks_accepts_a_missing_track_identity(bilibili_api_seam):
+    """An entry upstream did not identify keeps a null identity."""
+
+    entry = make_subtitle_track()
+    entry.pop("id")
+    gateway = _load_subtitle_gateway(bilibili_api_seam, entry)
+
+    (track,) = asyncio.run(gateway.get_subtitle_tracks(BVID, PART_CID))
+
+    assert track.track_id is None
+
+
+@pytest.mark.parametrize("broken_id", ["1", True, -1, 1.5, []])
+def test_get_subtitle_tracks_rejects_a_malformed_track_identity(
+    bilibili_api_seam, broken_id
+):
+    """A present id of another shape cannot identify a track."""
+
+    gateway = _load_subtitle_gateway(
+        bilibili_api_seam, make_subtitle_track(id=broken_id)
+    )
+
+    with pytest.raises(GatewayShapeError) as caught:
+        asyncio.run(gateway.get_subtitle_tracks(BVID, PART_CID))
+
+    assert caught.value.code == "shape_error"
+
+
+@pytest.mark.parametrize(
+    "empty_payload",
+    [
+        {},
+        {"subtitle": None},
+        {"subtitle": {}},
+        {"subtitle": {"allow_submit": False}},
+        {"subtitle": {"subtitles": None}},
+        {"subtitle": {"subtitles": []}},
+    ],
+)
+def test_get_subtitle_tracks_returns_an_empty_tuple_for_an_empty_inventory(
+    bilibili_api_seam, empty_payload
+):
+    """An invisible inventory is an observation: an empty tuple, never not_found.
+
+    The inventory is missing or empty, so the bounded answer is ``()``.  A
+    ``not_found`` here would turn "nothing was visible under this credential"
+    into a failure, and the call would raise instead of returning.
+    """
+
+    bilibili_api_seam.player_response = empty_payload
+    gateway = _load_gateway()
+
+    tracks = asyncio.run(gateway.get_subtitle_tracks(BVID, PART_CID))
+
+    assert tracks == ()
+    assert isinstance(tracks, tuple)
+    assert bilibili_api_seam.calls == [_listing_call()]
+
+
+@pytest.mark.parametrize(
+    "broken_payload",
+    [
+        None,
+        "no",
+        [{"lan": "zh-CN"}],
+        {"subtitle": "no"},
+        {"subtitle": []},
+        {"subtitle": {"subtitles": {}}},
+        {"subtitle": {"subtitles": "no"}},
+        {"subtitle": {"subtitles": [None]}},
+        {"subtitle": {"subtitles": [7]}},
+        {"subtitle": {"subtitles": [{}]}},
+        {"subtitle": {"subtitles": [{"lan": "", "lan_doc": "中文"}]}},
+        {"subtitle": {"subtitles": [{"lan": "   ", "lan_doc": "中文"}]}},
+        {"subtitle": {"subtitles": [{"lan": 7, "lan_doc": "中文"}]}},
+        {"subtitle": {"subtitles": [{"lan": "zh-CN"}]}},
+        {"subtitle": {"subtitles": [{"lan": "zh-CN", "lan_doc": ""}]}},
+        {"subtitle": {"subtitles": [{"lan": "zh-CN", "lan_doc": "   "}]}},
+        {"subtitle": {"subtitles": [{"lan": "zh-CN", "lan_doc": None}]}},
+        # The service derives the language family from the primary subtag, so a
+        # vocabulary it could not rank is a shape error, not a silent keep.
+        {"subtitle": {"subtitles": [{"lan": "-zh", "lan_doc": "中文"}]}},
+    ],
+)
+def test_get_subtitle_tracks_rejects_an_unreadable_inventory(
+    bilibili_api_seam, broken_payload
+):
+    """A payload that cannot be read as an inventory is a bounded shape error."""
+
+    bilibili_api_seam.player_response = broken_payload
+    gateway = _load_gateway()
+
+    with pytest.raises(GatewayShapeError) as caught:
+        asyncio.run(gateway.get_subtitle_tracks(BVID, PART_CID))
+
+    assert caught.value.code == "shape_error"
+    assert bilibili_api_seam.calls == [_listing_call()]
+
+
+@pytest.mark.parametrize(
+    ("bvid", "cid"),
+    [
+        ("", PART_CID),
+        ("BV1SHORT", PART_CID),
+        (12345, PART_CID),
+        (BVID, 0),
+        (BVID, True),
+        (BVID, "2222"),
+    ],
+)
+def test_get_subtitle_tracks_rejects_invalid_arguments(bilibili_api_seam, bvid, cid):
+    """Caller-argument violations raise ValueError before any upstream call."""
+
+    gateway = _load_gateway()
+
+    with pytest.raises(ValueError):
+        asyncio.run(gateway.get_subtitle_tracks(bvid, cid))
+    assert bilibili_api_seam.calls == []
+
+
+def test_subtitle_listing_request_carries_the_locked_call_shape(bilibili_api_seam):
+    """The listing is one player call with the description's declared parameters.
+
+    ``bvid`` stands in for the declared ``aid`` alternative, so no extra
+    aid-resolution call is paid; ``dm``/``verify`` are the adapter-owned
+    overrides; and neither folklore parameter of this endpoint
+    (``need_login_subtitle``, ``w_webid``) is invented, because the installed
+    pin declares neither.
+    """
+
+    gateway = _load_subtitle_gateway(
+        bilibili_api_seam, make_subtitle_track(), sessdata=SESSDATA_BOUNDARY_VALUE
+    )
+
+    asyncio.run(gateway.get_subtitle_tracks(BVID, PART_CID))
+
+    (request,) = bilibili_api_seam.api_requests
+    assert request.url == FAKE_PLAYER_ENDPOINT["url"]
+    assert request.method == FAKE_PLAYER_ENDPOINT["method"]
+    assert request.wbi is FAKE_PLAYER_ENDPOINT["wbi"]
+    assert request.verify is False
+    assert request.dm is False
+    assert [key for key in request.params if key.startswith("dm_")] == []
+    assert request.params == {
+        "bvid": BVID,
+        "cid": PART_CID,
+        "isGaiaAvoided": False,
+        "web_location": 1315873,
+    }
+    assert request.raw is False
+    # The API-host call carries the credential; the seam records its presence
+    # only, never the value.
+    assert request.has_sessdata is True
+    assert SESSDATA_BOUNDARY_VALUE not in repr(request)
+
+
+def test_subtitle_listing_follows_a_changed_package_endpoint(bilibili_api_seam):
+    """No player transport field is hard-coded: the description decides."""
+
+    bilibili_api_seam.player_endpoint["url"] = CHANGED_PLAYER_ENDPOINT_URL
+    bilibili_api_seam.player_endpoint["wbi"] = False
+    gateway = _load_subtitle_gateway(bilibili_api_seam, make_subtitle_track())
+
+    asyncio.run(gateway.get_subtitle_tracks(BVID, PART_CID))
+
+    (request,) = bilibili_api_seam.api_requests
+    assert request.url == CHANGED_PLAYER_ENDPOINT_URL
+    assert request.wbi is False
+
+
+def test_adapter_overrides_only_dm_and_verify_of_the_installed_pinned_player_endpoint(
+    bilibili_api_seam,
+):
+    """``dm``/``verify`` are the only fields changed on the pin's own shape.
+
+    The mirror-parity test above proves the seam's player description equals
+    the installed pin's; this test scripts the seam with the pin's *own* values
+    and runs the real adapter, so the issued call reproduces every transport
+    field of the pinned distribution except those two overrides.  Together they
+    pin the shipped call shape to the distribution the adapter actually drives.
+    """
+
+    pinned_endpoint = _require_installed(
+        _INSTALLED_PINNED_PLAYER_ENDPOINT, "player endpoint description"
+    )
+    bilibili_api_seam.player_endpoint.update(pinned_endpoint)
+    gateway = _load_subtitle_gateway(bilibili_api_seam, make_subtitle_track())
+
+    asyncio.run(gateway.get_subtitle_tracks(BVID, PART_CID))
+
+    (request,) = bilibili_api_seam.api_requests
+    assert request.url == pinned_endpoint["url"]
+    assert request.method == pinned_endpoint["method"]
+    assert request.wbi == pinned_endpoint["wbi"]
+    assert pinned_endpoint["verify"] is True
+    assert request.verify is False
+    assert pinned_endpoint["dm"] is True
+    assert request.dm is False
+
+
+@pytest.mark.parametrize(
+    ("upstream_error", "expected"),
+    [
+        (FakeNetworkException(412, UPSTREAM_ERROR_TEXT), GatewayRateLimited),
+        (FakeNetworkException(429, UPSTREAM_ERROR_TEXT), GatewayRateLimited),
+        (FakeNetworkException(404, UPSTREAM_ERROR_TEXT), GatewayNotFound),
+        (FakeNetworkException(503, UPSTREAM_ERROR_TEXT), GatewayTransportError),
+        (FakeResponseCodeException(-412, UPSTREAM_ERROR_TEXT), GatewayRateLimited),
+        (FakeResponseCodeException(-352, UPSTREAM_ERROR_TEXT), GatewayRateLimited),
+        (FakeResponseCodeException(-799, UPSTREAM_ERROR_TEXT), GatewayRateLimited),
+        (FakeResponseCodeException(-404, UPSTREAM_ERROR_TEXT), GatewayNotFound),
+        (FakeResponseCodeException(-62002, UPSTREAM_ERROR_TEXT), GatewayNotFound),
+        # The one divergence from the metadata path: ``-101`` means "nothing was
+        # visible under this credential" on the subtitle calls.
+        (FakeResponseCodeException(-101, UPSTREAM_ERROR_TEXT), GatewayNotFound),
+        (FakeResponseCodeException(-1, UPSTREAM_ERROR_TEXT), GatewayResponseError),
+        (FakeResponseException(UPSTREAM_ERROR_TEXT), GatewayResponseError),
+        (FakeWbiRetryTimesExceedException(), GatewayRateLimited),
+        (RuntimeError(UPSTREAM_ERROR_TEXT), GatewayTransportError),
+    ],
+)
+def test_subtitle_listing_failures_map_onto_bounded_taxonomy(
+    bilibili_api_seam, upstream_error, expected
+):
+    """The listing boundary maps upstream failures onto the shipped codes."""
+
+    bilibili_api_seam.player_error = upstream_error
+    gateway = _load_gateway()
+
+    with pytest.raises(expected) as caught:
+        asyncio.run(gateway.get_subtitle_tracks(BVID, PART_CID))
+
+    assert caught.value.code == expected.default_code
+    assert caught.value.detail == "get_subtitle_tracks"
+    assert UPSTREAM_ERROR_TEXT not in str(caught.value)
+    assert bilibili_api_seam.calls == [_listing_call()]
+
+
+def test_not_logged_in_diverges_between_the_metadata_and_subtitle_paths(
+    bilibili_api_seam,
+):
+    """``-101`` is "not visible" on the subtitle call, an error on the metadata one."""
+
+    bilibili_api_seam.player_error = FakeResponseCodeException(
+        -101, UPSTREAM_ERROR_TEXT
+    )
+    gateway = _load_gateway()
+
+    with pytest.raises(GatewayNotFound) as caught:
+        asyncio.run(gateway.get_subtitle_tracks(BVID, PART_CID))
+    assert caught.value.code == "not_found"
+
+    bilibili_api_seam.player_error = None
+    bilibili_api_seam.videos_error = FakeResponseCodeException(
+        -101, UPSTREAM_ERROR_TEXT
+    )
+    with pytest.raises(GatewayResponseError) as metadata_caught:
+        asyncio.run(gateway.get_user_video_page(MID, page_number=1))
+
+    assert metadata_caught.value.code == "response_error"
+    assert UPSTREAM_ERROR_TEXT not in str(metadata_caught.value)
+
+
+# --------------------------------------------- adapter: subtitle body fetch
+
+
+def test_fetch_subtitle_segments_normalizes_the_document_and_drops_degenerate_rows(
+    bilibili_api_seam,
+):
+    """Seconds become floored milliseconds; rows carrying nothing usable drop.
+
+    The document holds one usable row in front of every drop trigger of the
+    spec's section 3 boundary — a zero-length interval, an inverted one, a
+    negative start, and content that is empty after stripping — followed by two
+    more usable rows, so the surviving sequence proves the drops removed those
+    rows and nothing else, in upstream order, with unknown keys tolerated.
+    """
+
+    gateway = _load_subtitle_gateway(bilibili_api_seam, make_subtitle_track())
+    bilibili_api_seam.subtitle_bodies = {
+        SIGNED_SUBTITLE_URL_MARKER: make_subtitle_document(
+            _subtitle_row(0.0, 1.5, "  未明子  "),
+            _subtitle_row(1.5, 1.5, "零长度"),
+            _subtitle_row(3.0, 2.0, "倒置"),
+            _subtitle_row(-1.0, 1.0, "负起点"),
+            _subtitle_row(2.0, 2.5, "   "),
+            _subtitle_row(2.5, 2.75, "第二条", unknown_key="ignored"),
+            _subtitle_row(2.75, 3.0, "第三条"),
+        )
+    }
+
+    segments = asyncio.run(
+        gateway.fetch_subtitle_segments(_seam_track(), BVID, PART_CID)
+    )
+
+    assert segments == (
+        SubtitleSegment(start_ms=0, end_ms=1500, text="未明子"),
+        SubtitleSegment(start_ms=2500, end_ms=2750, text="第二条"),
+        SubtitleSegment(start_ms=2750, end_ms=3000, text="第三条"),
+    )
+    assert bilibili_api_seam.calls == [_listing_call(), "subtitle.body"]
+
+
+def test_subtitle_document_request_carries_the_locked_transport_shape(
+    bilibili_api_seam,
+):
+    """The body fetch is the locked raw call on an explicitly empty credential."""
+
+    gateway = _load_subtitle_gateway(
+        bilibili_api_seam, make_subtitle_track(), sessdata=SESSDATA_BOUNDARY_VALUE
+    )
+    bilibili_api_seam.subtitle_bodies = {
+        SIGNED_SUBTITLE_URL_MARKER: make_subtitle_document(make_subtitle_entry())
+    }
+
+    asyncio.run(gateway.fetch_subtitle_segments(_seam_track(), BVID, PART_CID))
+
+    body_request = bilibili_api_seam.api_requests[-1]
+    assert body_request.url == SIGNED_SUBTITLE_URL_MARKER
+    assert body_request.method == "GET"
+    assert body_request.wbi is False
+    assert body_request.dm is False
+    assert body_request.verify is False
+    assert body_request.params == {}
+    assert body_request.raw is True
+    # The empty credential keeps SESSDATA off the CDN host, while the API-host
+    # listing call above still carries it.
+    assert [request.has_sessdata for request in bilibili_api_seam.api_requests] == [
+        True,
+        False,
+    ]
+
+
+def test_fetch_subtitle_segments_normalizes_a_protocol_relative_document_url(
+    bilibili_api_seam,
+):
+    """A ``//``-relative signed URL is fetched in its absolute ``https:`` form.
+
+    The seam scripts only the absolute form, so fetching the un-normalized
+    value would hit an unscripted location and fail loudly there.
+    """
+
+    gateway = _load_subtitle_gateway(
+        bilibili_api_seam,
+        make_subtitle_track(subtitle_url=PROTOCOL_RELATIVE_SUBTITLE_URL),
+    )
+    bilibili_api_seam.subtitle_bodies = {
+        SIGNED_SUBTITLE_URL_MARKER: make_subtitle_document(make_subtitle_entry())
+    }
+
+    segments = asyncio.run(
+        gateway.fetch_subtitle_segments(_seam_track(), BVID, PART_CID)
+    )
+
+    assert [segment.text for segment in segments] == ["未明子"]
+    assert bilibili_api_seam.api_requests[-1].url == SIGNED_SUBTITLE_URL_MARKER
+    assert bilibili_api_seam.calls == [_listing_call(), "subtitle.body"]
+
+
+def test_fetch_subtitle_segments_resolves_the_requested_track_by_identity(
+    bilibili_api_seam,
+):
+    """Two tracks matching language + AI are told apart by the requested id."""
+
+    bilibili_api_seam.player_response = make_player_response(
+        make_subtitle_track(id=1),
+        make_subtitle_track(id=2, subtitle_url=SECOND_SUBTITLE_URL),
+    )
+    bilibili_api_seam.subtitle_bodies = {
+        SIGNED_SUBTITLE_URL_MARKER: make_subtitle_document(
+            make_subtitle_entry(content="第一条字幕")
+        ),
+        SECOND_SUBTITLE_URL: make_subtitle_document(
+            make_subtitle_entry(content="第二条字幕")
+        ),
+    }
+    gateway = _load_gateway()
+
+    segments = asyncio.run(
+        gateway.fetch_subtitle_segments(_seam_track(track_id="2"), BVID, PART_CID)
+    )
+
+    assert [segment.text for segment in segments] == ["第二条字幕"]
+    assert bilibili_api_seam.api_requests[-1].url == SECOND_SUBTITLE_URL
+
+
+@pytest.mark.parametrize("requested_id", [None, "9"])
+def test_fetch_subtitle_segments_reports_an_ambiguous_listing(
+    bilibili_api_seam, requested_id
+):
+    """An unresolvable match is a shape error, and no document is fetched.
+
+    Two candidates match on language + AI: ``None`` means the request carries
+    no identity to disambiguate with, and ``"9"`` names neither candidate.  The
+    bounded outcome for "which track did you mean?" is a shape error, and the
+    call list proves nothing was downloaded on a guess.
+    """
+
+    bilibili_api_seam.player_response = make_player_response(
+        make_subtitle_track(id=1),
+        make_subtitle_track(id=2, subtitle_url=SECOND_SUBTITLE_URL),
+    )
+    bilibili_api_seam.subtitle_bodies = {
+        SIGNED_SUBTITLE_URL_MARKER: make_subtitle_document(make_subtitle_entry()),
+        SECOND_SUBTITLE_URL: make_subtitle_document(make_subtitle_entry()),
+    }
+    gateway = _load_gateway()
+
+    with pytest.raises(GatewayShapeError) as caught:
+        asyncio.run(
+            gateway.fetch_subtitle_segments(
+                _seam_track(track_id=requested_id), BVID, PART_CID
+            )
+        )
+
+    assert caught.value.code == "shape_error"
+    assert bilibili_api_seam.calls == [_listing_call()]
+
+
+def test_fetch_subtitle_segments_reports_a_track_that_is_not_visible(
+    bilibili_api_seam,
+):
+    """A track the fresh listing no longer carries is a bounded ``not_found``.
+
+    The fresh listing is authoritative: a track that disappeared between the
+    caller's probe and the fetch, or that the credential can no longer see, is
+    ``not_found`` — never an empty success, and never a download attempt.
+    """
+
+    gateway = _load_subtitle_gateway(
+        bilibili_api_seam, make_subtitle_track(lan="en-US", lan_doc="English")
+    )
+    bilibili_api_seam.subtitle_bodies = {
+        SIGNED_SUBTITLE_URL_MARKER: make_subtitle_document(make_subtitle_entry())
+    }
+
+    with pytest.raises(GatewayNotFound) as caught:
+        asyncio.run(gateway.fetch_subtitle_segments(_seam_track(), BVID, PART_CID))
+
+    assert caught.value.code == "not_found"
+    assert bilibili_api_seam.calls == [_listing_call()]
+
+
+def test_fetch_subtitle_segments_reads_not_logged_in_as_no_visible_track(
+    bilibili_api_seam,
+):
+    """``-101`` on the fetch's own listing is ``not_found``, never an error."""
+
+    bilibili_api_seam.player_error = FakeResponseCodeException(
+        -101, UPSTREAM_ERROR_TEXT
+    )
+    gateway = _load_gateway()
+
+    with pytest.raises(GatewayNotFound) as caught:
+        asyncio.run(gateway.fetch_subtitle_segments(_seam_track(), BVID, PART_CID))
+
+    assert caught.value.code == "not_found"
+    assert UPSTREAM_ERROR_TEXT not in str(caught.value)
+    assert bilibili_api_seam.calls == [_listing_call()]
+
+
+@pytest.mark.parametrize(
+    "unreadable_document",
+    [
+        None,
+        "no",
+        [],
+        {},
+        {"font_size": 0.4},
+        {"body": None},
+        {"body": {}},
+        {"body": "no"},
+        {"body": [None]},
+        {"body": [7]},
+        {"body": ["caption"]},
+        {"body": [{"to": 1.0, "content": "未明子"}]},
+        {"body": [{"from": None, "to": 1.0, "content": "未明子"}]},
+        {"body": [{"from": "0.0", "to": 1.0, "content": "未明子"}]},
+        {"body": [{"from": True, "to": 1.0, "content": "未明子"}]},
+        {"body": [{"from": [0.0], "to": 1.0, "content": "未明子"}]},
+        {"body": [{"from": 0.0, "to": "1.0", "content": "未明子"}]},
+        {"body": [{"from": 0.0, "to": None, "content": "未明子"}]},
+        {"body": [{"from": float("nan"), "to": 1.0, "content": "未明子"}]},
+        {"body": [{"from": 0.0, "to": float("inf"), "content": "未明子"}]},
+        # A finite value whose millisecond product leaves the float range is
+        # equally unreadable; without that rule ``math.floor`` would escape as
+        # an ``OverflowError`` instead of a bounded code.
+        {"body": [{"from": 0.0, "to": 1e308, "content": "未明子"}]},
+        {"body": [{"from": 0.0, "to": 1.5}]},
+        {"body": [{"from": 0.0, "to": 1.5, "content": None}]},
+        {"body": [{"from": 0.0, "to": 1.5, "content": 7}]},
+        {"body": [{"from": 0.0, "to": 1.5, "content": ["未明子"]}]},
+    ],
+)
+def test_fetch_subtitle_segments_rejects_an_unreadable_document(
+    bilibili_api_seam, unreadable_document
+):
+    """An entry or document that cannot be read as segments is a shape error.
+
+    ``NaN``/``Infinity`` are the values Python's ``json`` accepts as bare
+    tokens, so scripting them directly is what the decoder would hand over.  An
+    unreadable document is not an expiry, so the call list proves it is never
+    re-fetched.
+    """
+
+    gateway = _load_subtitle_gateway(bilibili_api_seam, make_subtitle_track())
+    bilibili_api_seam.subtitle_bodies = {
+        SIGNED_SUBTITLE_URL_MARKER: unreadable_document
+    }
+
+    with pytest.raises(GatewayShapeError) as caught:
+        asyncio.run(gateway.fetch_subtitle_segments(_seam_track(), BVID, PART_CID))
+
+    assert caught.value.code == "shape_error"
+    assert bilibili_api_seam.calls == [_listing_call(), "subtitle.body"]
+
+
+@pytest.mark.parametrize(
+    ("body_outcome", "expected", "attempts"),
+    [
+        # Expiry/transport class: one re-list + fetch pair, then the code.
+        (FakeNetworkException(503, UPSTREAM_ERROR_TEXT), GatewayTransportError, 2),
+        (RuntimeError(UPSTREAM_ERROR_TEXT), GatewayTransportError, 2),
+        # Rate control never re-lists: re-listing into the same block only
+        # spends the risk budget.
+        (FakeNetworkException(412, UPSTREAM_ERROR_TEXT), GatewayRateLimited, 1),
+        (FakeNetworkException(429, UPSTREAM_ERROR_TEXT), GatewayRateLimited, 1),
+        (FakeResponseCodeException(-412, UPSTREAM_ERROR_TEXT), GatewayRateLimited, 1),
+        (FakeWbiRetryTimesExceedException(), GatewayRateLimited, 1),
+        # A document that is not there is not an expiry.
+        (FakeNetworkException(404, UPSTREAM_ERROR_TEXT), GatewayNotFound, 1),
+        # Error envelopes that are not transport failures.
+        (FakeResponseCodeException(-1, UPSTREAM_ERROR_TEXT), GatewayResponseError, 1),
+        (FakeResponseException(UPSTREAM_ERROR_TEXT), GatewayResponseError, 1),
+    ],
+)
+def test_subtitle_document_failures_stay_bounded_and_never_loop(
+    bilibili_api_seam, body_outcome, expected, attempts
+):
+    """Every body-fetch failure class maps to its code within the call bound.
+
+    ``attempts`` is the number of listing + fetch pairs the class is allowed:
+    one, or the single bounded re-list pair for the expiry/transport class.
+    The exact call list is the evidence that there is no third attempt and no
+    loop, whatever the failure was.
+    """
+
+    gateway = _load_subtitle_gateway(bilibili_api_seam, make_subtitle_track())
+    bilibili_api_seam.subtitle_bodies = {
+        SIGNED_SUBTITLE_URL_MARKER: body_outcome
+    }
+
+    with pytest.raises(expected) as caught:
+        asyncio.run(gateway.fetch_subtitle_segments(_seam_track(), BVID, PART_CID))
+
+    assert caught.value.code == expected.default_code
+    assert caught.value.detail == "fetch_subtitle_segments"
+    assert UPSTREAM_ERROR_TEXT not in str(caught.value)
+    assert bilibili_api_seam.calls == [_listing_call(), "subtitle.body"] * attempts
+
+
+def test_fetch_subtitle_segments_relists_for_a_fresh_signed_url(bilibili_api_seam):
+    """The second attempt re-lists and uses the fresh URL, not the stale one."""
+
+    listings: list[str] = []
+
+    def player_response(bvid: str, cid: int) -> dict:
+        listings.append(bvid)
+        url = (
+            SIGNED_SUBTITLE_URL_MARKER
+            if len(listings) == 1
+            else SECOND_SUBTITLE_URL
+        )
+        return make_player_response(make_subtitle_track(subtitle_url=url))
+
+    bilibili_api_seam.player_response = player_response
+    bilibili_api_seam.subtitle_bodies = {
+        SIGNED_SUBTITLE_URL_MARKER: FakeNetworkException(503, UPSTREAM_ERROR_TEXT),
+        SECOND_SUBTITLE_URL: make_subtitle_document(
+            make_subtitle_entry(content="重新列取")
+        ),
+    }
+    gateway = _load_gateway()
+
+    segments = asyncio.run(
+        gateway.fetch_subtitle_segments(_seam_track(), BVID, PART_CID)
+    )
+
+    assert [segment.text for segment in segments] == ["重新列取"]
+    assert [request.url for request in bilibili_api_seam.api_requests] == [
+        FAKE_PLAYER_ENDPOINT["url"],
+        SIGNED_SUBTITLE_URL_MARKER,
+        FAKE_PLAYER_ENDPOINT["url"],
+        SECOND_SUBTITLE_URL,
+    ]
+    assert bilibili_api_seam.calls == [
+        _listing_call(),
+        "subtitle.body",
+        _listing_call(),
+        "subtitle.body",
+    ]
+
+
+def test_fetch_subtitle_segments_signals_not_found_when_nothing_survives(
+    bilibili_api_seam,
+):
+    """An empty or fully degenerate document is ``not_found``, never a success.
+
+    Both documents are the locked "nothing usable" cases: an empty ``body``
+    array, and a document every one of whose rows is dropped.  Neither is a
+    shape error — every row *was* readable — and the assignment below can stay
+    ``None`` only because no empty tuple was ever returned.
+    """
+
+    gateway = _load_subtitle_gateway(bilibili_api_seam, make_subtitle_track())
+
+    for nothing_usable in (
+        make_subtitle_document(),
+        make_subtitle_document(
+            _subtitle_row(1.0, 1.0, "零长度"),
+            _subtitle_row(2.0, 1.0, "倒置"),
+            _subtitle_row(-1.0, 1.0, "负起点"),
+            _subtitle_row(0.0, 1.0, "   "),
+        ),
+    ):
+        bilibili_api_seam.subtitle_bodies = {
+            SIGNED_SUBTITLE_URL_MARKER: nothing_usable
+        }
+        returned = None
+        with pytest.raises(GatewayNotFound) as caught:
+            returned = asyncio.run(
+                gateway.fetch_subtitle_segments(_seam_track(), BVID, PART_CID)
+            )
+        assert caught.value.code == "not_found"
+        assert returned is None
+        assert bilibili_api_seam.calls == [_listing_call(), "subtitle.body"]
+        bilibili_api_seam.calls.clear()
+
+
+@pytest.mark.parametrize(
+    ("track", "bvid", "cid"),
+    [
+        (None, BVID, PART_CID),
+        ("zh-CN", BVID, PART_CID),
+        ({}, BVID, PART_CID),
+        (_seam_track(), "", PART_CID),
+        (_seam_track(), "BV1SHORT", PART_CID),
+        (_seam_track(), BVID, 0),
+        (_seam_track(), BVID, True),
+    ],
+)
+def test_fetch_subtitle_segments_rejects_invalid_arguments(
+    bilibili_api_seam, track, bvid, cid
+):
+    """A non-DTO track and malformed arguments are rejected before any call."""
+
+    gateway = _load_gateway()
+
+    with pytest.raises((TypeError, ValueError)):
+        asyncio.run(gateway.fetch_subtitle_segments(track, bvid, cid))
+    assert bilibili_api_seam.calls == []
+
+
+def test_subtitle_failure_messages_never_carry_the_upstream_text_or_the_url(
+    bilibili_api_seam,
+):
+    """Every mapped body-fetch failure stays bounded to its code and operation."""
+
+    gateway = _load_subtitle_gateway(
+        bilibili_api_seam, make_subtitle_track(), sessdata=SESSDATA_BOUNDARY_VALUE
+    )
+
+    for body_outcome, expected, expected_detail in (
+        (
+            FakeNetworkException(503, UPSTREAM_ERROR_TEXT),
+            GatewayTransportError,
+            "fetch_subtitle_segments",
+        ),
+        (
+            FakeNetworkException(412, UPSTREAM_ERROR_TEXT),
+            GatewayRateLimited,
+            "fetch_subtitle_segments",
+        ),
+        (
+            FakeResponseException(UPSTREAM_ERROR_TEXT),
+            GatewayResponseError,
+            "fetch_subtitle_segments",
+        ),
+        # A shape failure carries its own bounded phrase instead, and never
+        # anything the document said.
+        ("no", GatewayShapeError, "subtitle document is not a mapping"),
+    ):
+        bilibili_api_seam.subtitle_bodies = {
+            SIGNED_SUBTITLE_URL_MARKER: body_outcome
+        }
+        with pytest.raises(expected) as caught:
+            asyncio.run(
+                gateway.fetch_subtitle_segments(_seam_track(), BVID, PART_CID)
+            )
+        assert caught.value.detail == expected_detail
+        for rendered in (str(caught.value), repr(caught.value)):
+            assert UPSTREAM_ERROR_TEXT not in rendered
+            assert_leaks_no_markers(rendered, context="mapped subtitle failure")
+            assert SESSDATA_BOUNDARY_VALUE not in rendered
+
+
+def test_the_subtitle_routes_stay_on_the_documented_call_surface(
+    bilibili_api_seam,
+):
+    """Every call a listing plus a body fetch issues is a documented route."""
+
+    gateway = _load_subtitle_gateway(bilibili_api_seam, make_subtitle_track())
+    bilibili_api_seam.subtitle_bodies = {
+        SIGNED_SUBTITLE_URL_MARKER: make_subtitle_document(make_subtitle_entry())
+    }
+
+    asyncio.run(gateway.get_subtitle_tracks(BVID, PART_CID))
+    asyncio.run(gateway.fetch_subtitle_segments(_seam_track(), BVID, PART_CID))
+
+    assert bilibili_api_seam.calls == [
+        _listing_call(),
+        _listing_call(),
+        "subtitle.body",
+    ]
+    assert_only_documented_metadata_calls(bilibili_api_seam.calls)
 
 
 # ------------------------------------------------------------- live smoke
```
