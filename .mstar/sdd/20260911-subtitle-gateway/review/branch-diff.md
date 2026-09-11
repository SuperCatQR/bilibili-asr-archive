# Branch Review Package — 20260911-subtitle-gateway

Plan: `20260911-subtitle-gateway` (iteration `iter-2026-09-subtitle-transcript-sqlite`)
Range: `2bd333f..6002f99`
Base: `2bd333f` (integration branch at feature-branch cut)
Head: `6002f99` (QC-tri-time head; the QC fix wave `6002f99..9322239` is captured in `qc-fix-diff.md`)
Working branch: `feature/20260911-subtitle-gateway`
Commits: 73fdef0 (DTOs/protocol/seam), 7f7156a (adapter), c3d362c (live probe + tightenings), 6002f99 (probe fix wave)

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
index 0335948..27ebef8 100644
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
@@ -26,7 +32,7 @@ from bilibili_api.exceptions import (
     WbiRetryTimesExceedException,
 )
 from bilibili_api.utils.network import Api
-from bilibili_api.video import Video
+from bilibili_api.video import API as VIDEO_API, Video
 
 from bili_asr.config import resolve_proxy
 from bili_asr.sources.models import (
@@ -35,6 +41,8 @@ from bili_asr.sources.models import (
     GatewayResponseError,
     GatewayShapeError,
     GatewayTransportError,
+    SubtitleSegment,
+    SubtitleTrack,
     UserVideoPage,
     VideoPart,
     VideoSummary,
@@ -50,6 +58,12 @@ _NOT_FOUND_API_CODES = frozenset({-404, -62002})
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
 
@@ -60,6 +74,17 @@ _BVID_PATTERN = re.compile(r"^BV[a-zA-Z0-9]{10}$")
 # ``BilibiliApiGateway._fetch_user_video_page``).
 _USER_VIDEO_PAGE_ENDPOINT = user.API["info"]["video"]
 
+# The package's own endpoint description for the player call
+# (``bilibili_api.video.API["info"]["get_player_info"]``), whose unwrapped
+# payload carries the part's subtitle inventory.  ``url``/``method``/``wbi``
+# are read from it for the same reason; ``dm`` and ``verify`` are deliberately
+# overridden per call (see ``BilibiliApiGateway._fetch_subtitle_inventory``).
+# Only the endpoint description and ``Video`` are imported from the pin's
+# ``video`` module: binding the whole module would make its other names
+# (``Episode``, ``VideoOnlineMonitor``, ``get_api``, ``get_cid_info``,
+# ``get_client``) source-reachable here without the import boundary noticing.
+_PLAYER_INFO_ENDPOINT = VIDEO_API["info"]["get_player_info"]
+
 
 def _require_positive_argument(value: object, field: str) -> None:
     """Reject caller-argument violations before any upstream call."""
@@ -211,6 +236,219 @@ def _normalize_video_parts(pages: object, bvid: str) -> tuple[VideoPart, ...]:
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
@@ -322,10 +560,73 @@ class BilibiliApiGateway:
             return summary
         detail = await self._await_upstream(
             "get_completed_video_summary",
-            lambda: Video(bvid=summary.bvid, credential=self._credential).get_info(),
+            lambda: Video(
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
 
@@ -373,6 +674,82 @@ class BilibiliApiGateway:
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
 
@@ -399,13 +776,20 @@ class BilibiliApiGateway:
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
@@ -419,7 +803,7 @@ class BilibiliApiGateway:
         except ResponseCodeException as exc:
             if exc.code in _RATE_LIMITED_API_CODES:
                 raise GatewayRateLimited(detail=operation) from exc
-            if exc.code in _NOT_FOUND_API_CODES:
+            if exc.code in not_found_api_codes:
                 raise GatewayNotFound(detail=operation) from exc
             raise GatewayResponseError(detail=operation) from exc
         except WbiRetryTimesExceedException as exc:
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
index d0e308a..92dcbd1 100644
--- a/bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py
+++ b/bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py
@@ -11,31 +11,40 @@ Every package-seam test scripts these fakes instead of touching the pinned
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
@@ -89,13 +98,48 @@ FAKE_USER_VIDEO_PAGE_ENDPOINT = {
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
@@ -105,16 +149,34 @@ SIGNED_URL_MARKER = (
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
+    SIGNED_SUBTITLE_URL_MARKER,
+    PROTOCOL_RELATIVE_SUBTITLE_URL,
     RAW_JSON_BODY_MARKER,
     RAW_UPSTREAM_EXCEPTION_MARKER,
 )
@@ -191,7 +253,12 @@ class FakeApiRequest:
 
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
@@ -200,6 +267,8 @@ class FakeApiRequest:
     wbi: bool
     dm: bool
     params: dict
+    raw: bool = False
+    has_sessdata: bool = False
 
 
 @dataclasses.dataclass
@@ -214,12 +283,18 @@ class FakeUpstreamScript:
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
@@ -228,11 +303,17 @@ class FakeUpstreamScript:
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
@@ -362,16 +443,20 @@ def build_fake_package(script: FakeUpstreamScript) -> dict[str, types.ModuleType
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
@@ -399,13 +484,63 @@ def build_fake_package(script: FakeUpstreamScript) -> dict[str, types.ModuleType
 
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
@@ -414,9 +549,18 @@ def build_fake_package(script: FakeUpstreamScript) -> dict[str, types.ModuleType
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
@@ -424,6 +568,34 @@ def build_fake_package(script: FakeUpstreamScript) -> dict[str, types.ModuleType
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
@@ -457,6 +629,7 @@ def build_fake_package(script: FakeUpstreamScript) -> dict[str, types.ModuleType
             return response
 
     video_mod.Video = Video
+    video_mod.API = {"info": {"get_player_info": script.player_endpoint}}
 
     package.user = user_mod
     package.video = video_mod
@@ -542,6 +715,45 @@ def make_detail_response(**overrides: object) -> dict:
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
 
@@ -607,6 +819,7 @@ __all__ = [
     "BVID",
     "DOCUMENTED_METADATA_CALLS",
     "FAKE_PACKAGE_VERSION",
+    "FAKE_PLAYER_ENDPOINT",
     "FAKE_USER_VIDEO_PAGE_ENDPOINT",
     "FakeApiException",
     "FakeApiRequest",
@@ -620,10 +833,12 @@ __all__ = [
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
@@ -632,6 +847,10 @@ __all__ = [
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
index cf33c46..d7174cd 100644
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
@@ -50,12 +56,17 @@ from bili_asr.sources.models import (
 from bili_asr.storage.database import MetadataRepository, open_database
 from fixtures.fake_bilibili_gateway import (
     BVID,
+    DOCUMENTED_METADATA_CALLS,
+    FAKE_PLAYER_ENDPOINT,
     FAKE_USER_VIDEO_PAGE_ENDPOINT,
     MID,
     MIRRORED_ENDPOINT_FIELDS,
+    NO_LEAK_MARKERS,
+    PROTOCOL_RELATIVE_SUBTITLE_URL,
     PUBDATE,
     RAW_JSON_BODY_MARKER,
     SESSDATA_BOUNDARY_VALUE,
+    SIGNED_SUBTITLE_URL_MARKER,
     SIGNED_URL_MARKER,
     UPSTREAM_ERROR_TEXT,
     FakeNetworkException,
@@ -64,10 +75,15 @@ from fixtures.fake_bilibili_gateway import (
     FakeUpstreamScript,
     FakeWbiRetryTimesExceedException,
     assert_leaks_no_markers,
+    assert_only_documented_metadata_calls,
     bilibili_api_seam,
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
@@ -89,11 +105,17 @@ PACKAGE_HTTP_CLIENT_CANONICAL_NAMES = frozenset({"curl-cffi", "httpx", "aiohttp"
 
 #: The exact bilibili_api import surface the adapter is allowed to use.  The
 #: user-video page call is issued through ``user``'s own endpoint description
-#: and the WBI-signed ``utils.network.Api``, not through a ``user`` delegate.
+#: and the WBI-signed ``utils.network.Api``, not through a ``user`` delegate;
+#: the subtitle call reads its transport fields from the player endpoint
+#: description the same way.  The ``video`` module is deliberately bound to its
+#: two needed names instead of the whole module (only ``API``, locally aliased
+#: to ``VIDEO_API`` so it cannot be confused with the ``Api`` request class, and
+#: ``Video``), so ``Episode``, ``VideoOnlineMonitor``, ``get_api``,
+#: ``get_cid_info`` and ``get_client`` are not source-reachable here.
 ALLOWED_PACKAGE_IMPORTS = {
     "bilibili_api": {"Credential", "request_settings", "user"},
     "bilibili_api.utils.network": {"Api"},
-    "bilibili_api.video": {"Video"},
+    "bilibili_api.video": {"API", "Video"},
     "bilibili_api.exceptions": {
         "ApiException",
         "NetworkException",
@@ -116,6 +138,23 @@ ACCESS_ID_BOUNDARY_VALUE = "ACCESS-ID-THAT-MUST-NOT-LEAK"
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
+
+#: A second signed subtitle-document URL for one part.  It extends the seam's
+#: sentinel — so a leak of it is still caught by the no-secret scanner — and it
+#: lets a test prove the ``track_id`` tie-break fetched the entry the request
+#: named rather than the first match.
+SECOND_SUBTITLE_URL = SIGNED_SUBTITLE_URL_MARKER + "&second=1"
+
 
 def _probe_installed_pinned_endpoint() -> dict | str:
     """Read the pin's endpoint description, or the reason it could not be read.
@@ -144,6 +183,55 @@ def _probe_installed_pinned_endpoint() -> dict | str:
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
 
@@ -193,22 +281,43 @@ ALLOWED_EXCEPTION_NAMES = (
     "WbiRetryTimesExceedException",
 )
 
-#: Attribute names that would mark playback/subtitle/audio/ASR/export usage.
-#: Tokens are matched as plain substrings, so only unambiguous names belong
-#: here (``stream`` would false-positive on ``_await_upstream``).
+#: Attribute names that would mark playback/danmaku/audio/ASR/export/media
+#: usage — the surfaces outside this plan's boundary.  Tokens are matched as
+#: plain substrings, so only unambiguous names belong here (``stream`` would
+#: false-positive on ``_await_upstream``).  The PM-authorized Task-2 update
+#: removed only the subtitle/player half of the acquisition family on
+#: 2026-09-11: this plan legitimately issues the player and subtitle-document
+#: calls, and ``test_gateway_source_never_names_forbidden_seam_methods`` now
+#: positively asserts that surface instead (see
+#: ``AUTHORIZED_SUBTITLE_ATTRIBUTES``).  ``download`` came back the same day
+#: (Task-2 review tightening M2): this iteration acquires no media, and leaving
+#: it out would un-guard a future ``get_download_url``.
 FORBIDDEN_SEAM_METHOD_TOKENS = (
-    "subtitle",
     "playback",
     "playurl",
     "play_url",
     "download",
     "danmaku",
-    "player",
     "audio",
     "asr",
     "export",
 )
 
+#: The tokens the authorized update removed from the forbidden list and this
+#: plan still needs.  They are kept here only so the positive control below can
+#: prove the removal is load-bearing: each asserted attribute name still carries
+#: one of them.
+AUTHORIZED_SEAM_METHOD_TOKENS = ("subtitle", "player")
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
@@ -1404,6 +1513,159 @@ def test_user_video_page_rejects_invalid_fields(broken_kwargs):
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
+    """The protocol declares exactly the locked six methods, signatures included.
+
+    The four shipped signatures stay untouched — the shipped metadata service
+    and the storage plan consume them — and the two subtitle methods are
+    exactly the locked pair: ``get_subtitle_tracks(bvid, cid)`` answers a
+    possibly empty tuple (an empty inventory is an observation, never a
+    ``not_found`` failure), while ``fetch_subtitle_segments(track, bvid, cid)``
+    answers a non-empty tuple or raises ``GatewayNotFound``.
+
+    The declaration set is asserted exactly, not method by method: a seventh
+    protocol method fails here instead of slipping through unread.
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
+        name: tuple(inspect.signature(member).parameters)
+        for name, member in vars(BilibiliGateway).items()
+        if not name.startswith("_")
+    }
+
+    assert declared == expected
+
+
 # ------------------------------------------------------- import boundary (AST)
 
 
@@ -1441,11 +1703,15 @@ def test_gateway_imports_stay_on_metadata_surface():
     """The adapter imports exactly the enforced allow-list, nothing broader.
 
     ``ALLOWED_PACKAGE_IMPORTS`` is compared exactly: ``Credential`` and the
-    ``request_settings``/``user`` modules from the package root, the
-    WBI-signed ``utils.network.Api``, ``video.Video``, and the five exception
-    names.  ``User`` is deliberately not among them — the page call goes
-    through the ``user`` module's endpoint description and the package ``Api``,
-    never a ``user.User`` delegate.
+    ``request_settings``/``user`` modules from the package root, the WBI-signed
+    ``utils.network.Api``, the two ``video`` names the adapter uses (``API``,
+    bound locally as ``VIDEO_API`` so it cannot be confused with ``Api``, and
+    ``Video``), and the five exception names.  The page call reads
+    ``user.API["info"]["video"]`` and the subtitle call reads the player
+    endpoint description from the same surface, so ``utils.network.Api`` stays
+    the one request path.  ``User`` is deliberately not among them: the page
+    call goes through the ``user`` module's endpoint description and the
+    package ``Api``, never a ``user.User`` delegate.
     """
 
     gateway_path = (
@@ -1470,7 +1736,16 @@ def test_gateway_imports_stay_on_metadata_surface():
 
 
 def test_gateway_source_never_names_forbidden_seam_methods():
-    """The adapter source never references playback/subtitle/audio names."""
+    """The adapter source stays off every surface outside this plan's boundary.
+
+    ``FORBIDDEN_SEAM_METHOD_TOKENS`` carries the media/playback family only:
+    the authorized subtitle-acquisition tokens are ``subtitle`` and ``player``
+    (``download`` is forbidden again, because this iteration acquires no
+    media).  The second positive control below asserts that family's own
+    attributes are present *and* that they still carry an allowed token:
+    re-forbidding the removal fails there instead of letting the scan pass
+    because the adapter has no subtitle code to see.
+    """
 
     gateway_path = (
         pathlib.Path(__file__).resolve().parent.parent
@@ -1496,6 +1771,14 @@ def test_gateway_source_never_names_forbidden_seam_methods():
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
@@ -1505,7 +1788,7 @@ def test_fake_seam_exposes_only_documented_metadata_surface():
     package = modules["bilibili_api"]
 
     assert _public_names(modules["bilibili_api.user"]) == ["API", "User", "VideoOrder"]
-    assert _public_names(modules["bilibili_api.video"]) == ["Video"]
+    assert _public_names(modules["bilibili_api.video"]) == ["API", "Video"]
     assert _public_names(modules["bilibili_api.utils.network"]) == ["Api"]
     assert _public_names(modules["bilibili_api.exceptions"]) == sorted(
         ALLOWED_EXCEPTION_NAMES
@@ -1576,6 +1859,1280 @@ def test_gateway_dto_drops_unknown_upstream_payload_fields(bilibili_api_seam):
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
+    exactly like the playback marker.  The protocol-relative form upstream also
+    answers is scanned too, so a URL that skipped the adapter's ``https:``
+    normalization cannot slip past the scan; together these are the control
+    that keeps the downstream "no signed URL" assertions from passing
+    vacuously.
+    """
+
+    with pytest.raises(AssertionError):
+        assert_leaks_no_markers(
+            SIGNED_SUBTITLE_URL_MARKER, context="sentinel positive control"
+        )
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
+    "listing_failure",
+    [
+        FakeNetworkException(503, UPSTREAM_ERROR_TEXT),
+        # A transport-class exception the package does not wrap — the shape a
+        # dead route or a library-level failure produces.
+        RuntimeError(UPSTREAM_ERROR_TEXT),
+    ],
+)
+def test_fetch_subtitle_segments_maps_a_transport_failure_on_its_own_listing(
+    bilibili_api_seam, listing_failure
+):
+    """A transport failure on the fetch's *own* listing never arms the re-list.
+
+    The bounded re-list exists for a body fetch whose signed URL stopped
+    working; a listing that never answered is not an expiry, and re-listing
+    into it would spend a second call on the same dead route.  The fetch's
+    initial listing therefore stands outside the re-list, and this test pins
+    that: one call, the mapped transport code, and the requested track's
+    operation in the detail — never a second listing.
+    """
+
+    bilibili_api_seam.player_error = listing_failure
+    gateway = _load_gateway()
+
+    with pytest.raises(GatewayTransportError) as caught:
+        asyncio.run(gateway.fetch_subtitle_segments(_seam_track(), BVID, PART_CID))
+
+    assert caught.value.code == "transport_error"
+    assert caught.value.detail == "fetch_subtitle_segments"
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
+
+
 # ------------------------------------------------------------- live smoke
 
 
diff --git a/bilibili-asr-archive/tests/test_live_subtitle_smoke.py b/bilibili-asr-archive/tests/test_live_subtitle_smoke.py
new file mode 100644
index 0000000..5274bb2
--- /dev/null
+++ b/bilibili-asr-archive/tests/test_live_subtitle_smoke.py
@@ -0,0 +1,882 @@
+"""Opt-in bounded live probe: ONE real part's subtitle inventory and body.
+
+This module holds the only networked subtitle test.  It drives the real
+``BilibiliApiGateway`` adapter over the pinned ``bilibili-api-python``
+distribution for exactly one ``(bvid, cid)`` and records the bounded facts the
+gateway contract promises: the track inventory (count, language codes, AI
+versus CC) and, when a track is visible, the fetched document's segment count
+and millisecond timeline.  Nothing else leaves the run: no signed URL, no
+response body, no credential, and no label body is printed, and no database,
+sidecar, or fixture is written.
+
+Where the probed part comes from:
+
+- the operator's archive database is preferred, read through a read-only
+  SQLite URI (``mode=ro``): ``BILI_LIVE_ARCHIVE_DB`` when set, else
+  ``archive/archive.db`` below the package directory — the root the
+  ``fetch-meta`` command defaults to.  The newest part row (highest
+  ``video_part_id``) is the deterministic one probed, provided the archive has
+  not already marked it ``gone`` and its ``bvid`` is a BV id — two checks that
+  keep a part the archive has itself written off, or a foreign row, from
+  spending the probe's one live call or reaching the adapter's ``ValueError``.
+  A missing, unreadable, or part-less database is not a probe failure;
+- when no archived part is readable — a fresh checkout has no ``archive/``
+  root at all — the probe falls back to the fixed public sample instead
+  (:data:`SAMPLE_BVID` / :data:`SAMPLE_CID`): one part of the archive owner's
+  own public collection, discovered once through the delivered metadata
+  gateway while this probe was authored.  The fallback deliberately costs no
+  metadata call at run time, so the only live surfaces the probe touches are
+  the player endpoint and the signed document it lists — the routes under test.
+  The evidence line records which source answered (``part_source=archive-db``
+  or ``part_source=fixed-sample``) together with the probed ``bvid``/``cid``,
+  so a sample that upstream has since removed is visible rather than silent.
+
+Default pytest runs skip the probe; it executes only when the operator sets
+``BILI_LIVE_SMOKE=1``.  An opted-in probe fails loudly when the pinned
+distribution is missing.  Its documented bounded outcomes are:
+
+- the part exposes no track (``track_count=0``): a legitimate observation,
+  recorded together with the credential presence — never "this video has no
+  captions";
+- the listing itself answers the bounded ``not_found`` code
+  (``track_count=not_found``): the part is one upstream no longer serves, or one
+  the credential in effect cannot see — this boundary deliberately collapses
+  both into the one code the caller records as ``no-subtitle``.  The outcome is
+  recorded with the part that produced it and the probe skips, because a run
+  that obtained no listing at all must not read green; a sample upstream has
+  since removed lands here;
+- upstream risk control refuses the locked call shape (``rate_limited``): the
+  plan's recorded bounded blocker, reported as a skip carrying the bounded code
+  and the stage, because the locked shape must not be bent to make the call
+  pass;
+- a listed track whose body carries nothing usable (``not_found``): recorded
+  with the bounded code, so a run that obtained no segment evidence never reads
+  green;
+- every other bounded code — ``transport_error`` from a dead proxy,
+  ``response_error``, ``shape_error`` — fails loudly, because those mean the
+  environment or the adapter regressed rather than upstream refusing.
+
+Every branch of that ladder is rehearsed offline in this module — part
+selection, the two loud-fail guards, both evidence renderers, and all four
+record-and-skip branches — so a default (offline, non-opted-in) run exercises
+the whole control flow; only the two boundary calls themselves are live.
+
+Run it with::
+
+    cd bilibili-asr-archive && BILI_LIVE_SMOKE=1 \\
+        .venv/bin/python -m pytest tests/test_live_subtitle_smoke.py -v -s
+
+The probe adds no retry of its own — the single bounded re-list inside one
+fetch belongs to the delivered adapter — and never reaches playback, audio,
+download, or ASR code.
+"""
+
+from __future__ import annotations
+
+import asyncio
+import importlib.metadata
+import os
+import pathlib
+import re
+import sqlite3
+import sys
+from typing import NoReturn
+
+import pytest
+
+from bili_asr.cli import DEFAULT_ARCHIVE_ROOT
+from bili_asr.config import (
+    ARCHIVE_DATABASE_NAME,
+    SESSDATA_ENV_VAR,
+    redact_sessdata,
+    resolve_proxy,
+    resolve_sessdata,
+)
+from bili_asr.sources.models import (
+    BilibiliGateway,
+    GatewayNotFound,
+    GatewayRateLimited,
+    SubtitleSegment,
+    SubtitleTrack,
+)
+from bili_asr.storage.database import MetadataRepository, open_database
+from bili_asr.storage.models import ProcessingStatus, VideoPartRecord
+from fixtures.fake_bilibili_gateway import (
+    BVID,
+    RAW_JSON_BODY_MARKER,
+    SIGNED_SUBTITLE_URL_MARKER,
+    assert_leaks_no_markers,
+)
+from fixtures.metadata_records import (
+    make_part_record,
+    make_user_record,
+    make_video_record,
+)
+
+PINNED_PACKAGE_DISTRIBUTION_NAME = "bilibili-api-python"
+PINNED_PACKAGE_VERSION = "17.4.2"
+
+#: The opt-in switch, shared with the metadata smoke: the probe runs only when
+#: the operator sets it to ``1``.
+LIVE_SMOKE_ENV = "BILI_LIVE_SMOKE"
+
+#: The part cid the offline rehearsals seed and select.
+REHEARSAL_CID = 2222
+
+#: The part cid the offline rehearsals seed as already ``gone``.
+REHEARSAL_GONE_CID = 3333
+
+#: The BV-id shape the adapter requires before it issues a call
+#: (``^BV[a-zA-Z0-9]{10}$``).  Mirrored here rather than imported from the
+#: adapter, which imports the pinned distribution at module scope: this module
+#: must stay importable, and its rehearsals runnable, in an environment without
+#: that distribution.
+BVID_PATTERN = re.compile(r"^BV[a-zA-Z0-9]{10}$")
+
+#: The fixed public sample the probe probes when no archived part is readable:
+#: one part of the archive owner's own collection, discovered once through the
+#: delivered metadata gateway while this probe was authored (2026-09-11; first
+#: page of UID 23191782, first part of the first video).  A sample upstream has
+#: since removed surfaces in the evidence line as ``track_count=0`` or a
+#: bounded code; replacing these two identifiers is then a one-line change.
+SAMPLE_BVID = "BV1S8hA6MEvy"
+SAMPLE_CID = 41314223900
+
+#: Environment override for the operator's archive database, for a checkout
+#: whose own ``archive/`` root is elsewhere (a feature worktree, for instance).
+#: The database is opened read-only either way.
+ARCHIVE_DATABASE_PATH_ENV_VAR = "BILI_LIVE_ARCHIVE_DB"
+
+#: The archive database the CLI writes by default, resolved from this file so
+#: the probe follows the checkout it runs in.
+DEFAULT_ARCHIVE_DATABASE_PATH = str(
+    pathlib.Path(__file__).resolve().parent.parent
+    / DEFAULT_ARCHIVE_ROOT
+    / ARCHIVE_DATABASE_NAME
+)
+
+
+def _live_smoke_requested() -> bool:
+    """True only when the operator explicitly opts in via the environment."""
+
+    return os.environ.get(LIVE_SMOKE_ENV, "") == "1"
+
+
+def _pinned_package_version() -> str:
+    """Return the installed distribution version, or fail loudly.
+
+    Loud-fail guard (the metadata smoke's precedent): an opted-in probe in an
+    environment without the pinned distribution fails loudly with install
+    guidance instead of silently skipping.
+    """
+
+    try:
+        return importlib.metadata.version(PINNED_PACKAGE_DISTRIBUTION_NAME)
+    except importlib.metadata.PackageNotFoundError as error:
+        pytest.fail(
+            "live subtitle probe was requested but"
+            f" {PINNED_PACKAGE_DISTRIBUTION_NAME} is not installed in this"
+            f" environment ({error}); install the pinned"
+            f" {PINNED_PACKAGE_DISTRIBUTION_NAME}=={PINNED_PACKAGE_VERSION}"
+            " (uv sync) first"
+        )
+
+
+def _load_gateway(sessdata: str | None):
+    """Build the real adapter, failing loudly when the pin is not importable."""
+
+    try:
+        from bili_asr.sources.bilibili_api_gateway import BilibiliApiGateway
+    except ImportError as error:
+        pytest.fail(
+            "live subtitle probe was requested but the pinned package is not"
+            f" importable in this environment ({error}); install"
+            f" {PINNED_PACKAGE_DISTRIBUTION_NAME}=={PINNED_PACKAGE_VERSION}"
+            " (uv sync) first"
+        )
+    return BilibiliApiGateway(sessdata=sessdata)
+
+
+def _read_archive_part(database_path: str) -> tuple[str, int] | None:
+    """Read one part's ``(bvid, cid)`` from the archive, strictly read-only.
+
+    The database is opened through a ``mode=ro`` SQLite URI, so the probe can
+    neither create, migrate, nor write anything; the newest part row (highest
+    ``video_part_id``) is the deterministic one probed, provided the archive has
+    not already marked it ``gone`` — a part upstream no longer serves is exactly
+    the one the player endpoint answers ``not_found`` for, and the probe has one
+    live call to spend — and provided its ``bvid`` has the BV shape the adapter
+    requires, so a foreign or hand-edited row cannot turn into an adapter
+    ``ValueError``.  A database that does not exist, a file that is not a
+    readable SQLite database, a database without a usable part row, and a row
+    the adapter would reject all answer ``None`` and hand the probe to its
+    documented sample fallback.
+    """
+
+    path = pathlib.Path(database_path)
+    if not path.is_file():
+        return None
+    try:
+        connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
+    except sqlite3.Error:
+        return None
+    try:
+        row = connection.execute(
+            "SELECT bvid, cid FROM video_parts"
+            " WHERE cid > 0 AND processing_status != 'gone'"
+            " ORDER BY video_part_id DESC LIMIT 1"
+        ).fetchone()
+    except sqlite3.Error:
+        return None
+    finally:
+        connection.close()
+    if row is None:
+        return None
+    bvid, cid = row
+    if not isinstance(bvid, str) or BVID_PATTERN.fullmatch(bvid) is None:
+        return None
+    if isinstance(cid, bool) or not isinstance(cid, int):
+        return None
+    return bvid, cid
+
+
+def _resolve_probe_part() -> tuple[str, int, str]:
+    """Resolve the one ``(bvid, cid)`` the probe runs for, and its source.
+
+    The archived part wins when the operator's database carries one; otherwise
+    the fixed public sample answers.  The third element is the bounded source
+    label the evidence line records (``archive-db`` or ``fixed-sample``); the
+    probed ``bvid``/``cid`` travel with it, so the record always names what was
+    probed.
+    """
+
+    database_path = (
+        os.environ.get(ARCHIVE_DATABASE_PATH_ENV_VAR) or DEFAULT_ARCHIVE_DATABASE_PATH
+    )
+    archived = _read_archive_part(database_path)
+    if archived is not None:
+        return archived[0], archived[1], "archive-db"
+    return SAMPLE_BVID, SAMPLE_CID, "fixed-sample"
+
+
+def _track_evidence(tracks: tuple[SubtitleTrack, ...]) -> str:
+    """Assert the listing's shape and render its bounded, printable evidence.
+
+    The listing must be a tuple of track DTOs — never ``None``, never a raw
+    upstream mapping — and the rendered line carries the count, the language
+    codes, and AI versus CC only.  Display labels are deliberately left out:
+    the bounded facts this probe records do not need them, so no upstream
+    string reaches the probe's output at all.
+    """
+
+    assert isinstance(tracks, tuple), "the listing must answer a tuple"
+    assert all(isinstance(track, SubtitleTrack) for track in tracks), (
+        "every listed track must be a SubtitleTrack DTO"
+    )
+    inventory = ",".join(
+        f"{track.language}:{'ai' if track.is_ai else 'cc'}" for track in tracks
+    )
+    return f"track_count={len(tracks)} tracks={inventory or 'none'}"
+
+
+def _assert_bounded_segment_facts(segments: tuple[SubtitleSegment, ...]) -> str:
+    """Assert the fetched timeline and render its bounded evidence.
+
+    What the contract guarantees per row (``end_ms > start_ms >= 0`` with
+    non-empty text) is enforced by :class:`SubtitleSegment` itself and covered
+    by the offline suite; what this probe adds is the document-level fact no
+    offline test can see — that the real document's start timeline is
+    non-decreasing, which is the order the adapter preserves verbatim.  The
+    evidence line carries counts and milliseconds only.
+    """
+
+    assert segments, "a fetched document must answer at least one segment"
+    starts = [segment.start_ms for segment in segments]
+    assert starts == sorted(starts), (
+        "the probed document's start timeline is not non-decreasing; the"
+        " adapter preserves upstream order verbatim (spec section 3), so this"
+        " is an observation about the upstream document and needs a recorded"
+        " decision instead of a silent pass"
+    )
+    return (
+        f"segments={len(segments)} first_start_ms={starts[0]}"
+        f" last_end_ms={segments[-1].end_ms} timeline=non-decreasing"
+    )
+
+
+def _record_risk_control_refusal(
+    refusal: GatewayRateLimited, *, stage: str, part_source: str
+) -> NoReturn:
+    """Record one upstream risk-control refusal and skip the live probe.
+
+    The plan's STOP condition applies: the player endpoint refusing the locked
+    call shape is escalated with this bounded evidence, never answered by
+    enabling the fabricated fingerprint parameters or by adding undeclared
+    parameters.  The run therefore reports a skip carrying the bounded code and
+    the stage — not a pass (no call-shape evidence was obtained) and not a
+    failure (the adapter did exactly what it must).
+    """
+
+    print(
+        f"live subtitle probe evidence: part_source={part_source}"
+        f" stage={stage} refusal_code={refusal.code}"
+    )
+    pytest.skip(
+        "the player endpoint refused the locked call shape with the bounded"
+        f" risk-control code {refusal.code!r} at stage {stage!r}: the plan's"
+        " STOP condition applies, so this is a recorded bounded blocker — do"
+        " not enable the fabricated dm fingerprint parameters and do not add"
+        " undeclared parameters to make the call pass."
+    )
+
+
+def _probe_one_part(
+    gateway: BilibiliGateway, bvid: str, cid: int, part_source: str
+) -> None:
+    """Run the probe's two boundary calls for one part and record the evidence.
+
+    The listing is issued first, and the body only when a track is visible.  The
+    evidence lines and every record-and-skip branch live here rather than inline
+    in the live test so a default (offline) pytest run can drive all of them
+    through a scripted gateway: a branch only a live run can enter is a branch no
+    offline run has ever verified.
+    """
+
+    try:
+        tracks = asyncio.run(gateway.get_subtitle_tracks(bvid, cid))
+    except GatewayRateLimited as refusal:
+        _record_risk_control_refusal(
+            refusal, stage="track-listing", part_source=part_source
+        )
+    except GatewayNotFound:
+        # The part is not visible upstream: an inventory nothing answered for,
+        # which is what a sample upstream has since removed looks like — and
+        # what the boundary reports when the credential in effect cannot see
+        # the part at all (its ``-101`` signal).  Both are bounded outcomes the
+        # caller records as ``no-subtitle``, so the probe records them instead
+        # of dying with a traceback and no evidence line.
+        print(
+            "live subtitle probe evidence: part_source="
+            f"{part_source} stage=track-listing track_count=not_found"
+        )
+        pytest.skip(
+            "the player endpoint answered the bounded not_found code for this"
+            " part: upstream no longer serves it, or the credential in effect"
+            " cannot see it — the boundary collapses both into the code the"
+            " caller records as no-subtitle.  No listing evidence was obtained,"
+            " so the run must not read as green: probe another part, or refresh"
+            " the archive metadata when the part came from the archive"
+            " database."
+        )
+    print(
+        "live subtitle probe evidence: stage=track-listing"
+        f" {_track_evidence(tracks)}"
+    )
+    if not tracks:
+        # A legitimate bounded observation, never "this video has no captions":
+        # the credential presence printed above is part of the record.
+        print(
+            "live subtitle probe evidence: no usable track was visible for"
+            " this part under the credential in effect"
+        )
+        return
+
+    track = tracks[0]
+    try:
+        segments = asyncio.run(gateway.fetch_subtitle_segments(track, bvid, cid))
+    except GatewayRateLimited as refusal:
+        _record_risk_control_refusal(
+            refusal, stage="subtitle-body", part_source=part_source
+        )
+    except GatewayNotFound:
+        print(
+            "live subtitle probe evidence: stage=subtitle-body"
+            " segments=not_found"
+        )
+        pytest.skip(
+            "the listed track's document carried nothing usable (bounded"
+            " not_found): the outcome is recorded, but a run without segment"
+            " evidence must not read as green — rerun the probe later."
+        )
+    track_kind = "ai" if track.is_ai else "cc"
+    print(
+        "live subtitle probe evidence: stage=subtitle-body"
+        f" track={track.language}:{track_kind}"
+        f" {_assert_bounded_segment_facts(segments)}"
+    )
+
+
+def test_live_subtitle_probe_reports_one_real_part_inventory():
+    """Opt-in live probe: ONE real part's subtitle inventory and body.
+
+    Skipped unless the operator sets ``BILI_LIVE_SMOKE=1``.  The probe resolves
+    one part (the operator's archive first, the bounded sample fallback
+    second), lists its subtitle inventory through the real adapter in the
+    locked call shape, and — when a track is visible — fetches that track's
+    body and checks the document-level timeline.  It asserts and prints the
+    bounded facts only: counts, language codes, AI versus CC, segment count,
+    and milliseconds.
+    """
+
+    if not _live_smoke_requested():
+        pytest.skip(
+            f"live subtitle probe is opt-in: set {LIVE_SMOKE_ENV}=1 to request it"
+        )
+
+    assert _pinned_package_version() == PINNED_PACKAGE_VERSION
+
+    sessdata = resolve_sessdata(None, os.environ.get(SESSDATA_ENV_VAR))
+    gateway = _load_gateway(sessdata)
+    proxy = resolve_proxy(None, os.environ)
+    print(
+        "live subtitle probe environment:"
+        f" sessdata={redact_sessdata(sessdata)}"
+        f" proxy={'present' if proxy else 'absent'}"
+    )
+
+    bvid, cid, part_source = _resolve_probe_part()
+    print(
+        f"live subtitle probe part: source={part_source} bvid={bvid} cid={cid}"
+    )
+
+    _probe_one_part(gateway, bvid, cid, part_source)
+
+
+# ------------------------------------------------------------- rehearsals
+#
+# The rehearsals below run in every default (offline) pytest run and cover the
+# probe's own logic — part selection, the read-only archive query, both loud-fail
+# guards, the bounded evidence renderers, and every record-and-skip branch — so a
+# broken query or a loosened assertion fails offline instead of first surfacing
+# during a live run.  No live behaviour is claimed here, and no network call is
+# made: the live flow's two calls are driven through a scripted gateway.
+
+
+def _seed_archive(
+    database_path: str,
+    *,
+    bvid: str,
+    cid: int,
+    processing_status: ProcessingStatus = "discovered",
+    extra_parts: tuple[VideoPartRecord, ...] = (),
+) -> None:
+    """Seed one user, one video, and the given part rows into a real archive."""
+
+    connection = open_database(database_path)
+    repository = MetadataRepository(connection)
+    try:
+        with repository.transaction():
+            repository.upsert_user(make_user_record())
+            repository.upsert_video(make_video_record(bvid))
+            repository.upsert_part(
+                make_part_record(bvid, cid=cid, processing_status=processing_status)
+            )
+            for part in extra_parts:
+                repository.upsert_part(part)
+    finally:
+        connection.close()
+
+
+def test_archive_part_selection_reads_the_shipped_schema_and_stays_read_only(
+    tmp_root: str, monkeypatch: pytest.MonkeyPatch
+):
+    """The probe's archive query works on the shipped schema, read-only.
+
+    The archived part is selected from a database the real storage layer
+    created, through a connection whose URI is pinned to ``mode=ro``: the probe
+    has no code path that could create, migrate, or write the operator's
+    archive, and every unreadable case degrades to the sample fallback.
+    """
+
+    database_path = os.path.join(tmp_root, ARCHIVE_DATABASE_NAME)
+    _seed_archive(database_path, bvid=BVID, cid=REHEARSAL_CID)
+    requested_uris: list[str] = []
+    real_connect = sqlite3.connect
+
+    def recording_connect(database: str, **kwargs: object):
+        requested_uris.append(database)
+        return real_connect(database, **kwargs)
+
+    monkeypatch.setattr(sqlite3, "connect", recording_connect)
+
+    assert _read_archive_part(database_path) == (BVID, REHEARSAL_CID)
+    (requested_uri,) = requested_uris
+    assert requested_uri.startswith("file://")
+    assert requested_uri.endswith("?mode=ro")
+
+    assert _read_archive_part(
+        os.path.join(tmp_root, "absent", ARCHIVE_DATABASE_NAME)
+    ) is None
+    empty_dir = os.path.join(tmp_root, "empty")
+    os.makedirs(empty_dir, exist_ok=True)
+    assert _read_archive_part(os.path.join(empty_dir, ARCHIVE_DATABASE_NAME)) is None
+
+
+def test_probe_part_selection_prefers_the_archive_and_falls_back_to_the_sample(
+    tmp_root: str, monkeypatch: pytest.MonkeyPatch
+):
+    """An archived part wins; without one the fixed public sample answers.
+
+    The fallback must not depend on any live call: the second branch scripts
+    nothing at all, and the probe still resolves a part — the player endpoint
+    and the document it lists are the only live surfaces this probe touches.
+    """
+
+    database_path = os.path.join(tmp_root, ARCHIVE_DATABASE_NAME)
+    _seed_archive(database_path, bvid=BVID, cid=REHEARSAL_CID)
+    monkeypatch.setenv(ARCHIVE_DATABASE_PATH_ENV_VAR, database_path)
+
+    assert _resolve_probe_part() == (BVID, REHEARSAL_CID, "archive-db")
+
+    monkeypatch.setenv(
+        ARCHIVE_DATABASE_PATH_ENV_VAR,
+        os.path.join(tmp_root, "absent", ARCHIVE_DATABASE_NAME),
+    )
+    assert _resolve_probe_part() == (SAMPLE_BVID, SAMPLE_CID, "fixed-sample")
+
+
+def test_probe_part_selection_ignores_an_archive_without_a_part(
+    tmp_root: str, monkeypatch: pytest.MonkeyPatch
+):
+    """An archive that carries no part row hands the probe to the sample.
+
+    A database the real storage layer created — schema present, no part row —
+    is the shape an operator sees before the first collection, and it must not
+    fail the probe.
+    """
+
+    database_path = os.path.join(tmp_root, ARCHIVE_DATABASE_NAME)
+    connection = open_database(database_path)
+    connection.close()
+    monkeypatch.setenv(ARCHIVE_DATABASE_PATH_ENV_VAR, database_path)
+
+    assert _resolve_probe_part() == (SAMPLE_BVID, SAMPLE_CID, "fixed-sample")
+
+
+def test_probe_part_selection_skips_a_part_the_archive_marked_gone(
+    tmp_root: str, monkeypatch: pytest.MonkeyPatch
+):
+    """A part the archive knows is gone is never probed, even as the newest row.
+
+    ``gone`` is a first-class shipped part status, and a part upstream no longer
+    serves is exactly the one the player endpoint answers ``not_found`` for, so
+    selecting it would spend the probe's one live call on a bounded blocker its
+    own database could have predicted.  An archive whose every part is gone
+    lands on the sample fallback the way an empty one does.
+    """
+
+    database_path = os.path.join(tmp_root, ARCHIVE_DATABASE_NAME)
+    _seed_archive(
+        database_path,
+        bvid=BVID,
+        cid=REHEARSAL_CID,
+        extra_parts=(
+            make_part_record(
+                BVID,
+                page_index=1,
+                cid=REHEARSAL_GONE_CID,
+                processing_status="gone",
+            ),
+        ),
+    )
+    monkeypatch.setenv(ARCHIVE_DATABASE_PATH_ENV_VAR, database_path)
+
+    # The gone part carries the higher ``video_part_id``, so the ordering alone
+    # would select exactly the row the archive has already written off.
+    assert _read_archive_part(database_path) == (BVID, REHEARSAL_CID)
+    assert _resolve_probe_part() == (BVID, REHEARSAL_CID, "archive-db")
+
+    gone_only_path = os.path.join(tmp_root, "gone-only", ARCHIVE_DATABASE_NAME)
+    os.makedirs(os.path.dirname(gone_only_path), exist_ok=True)
+    _seed_archive(
+        gone_only_path,
+        bvid=BVID,
+        cid=REHEARSAL_GONE_CID,
+        processing_status="gone",
+    )
+    monkeypatch.setenv(ARCHIVE_DATABASE_PATH_ENV_VAR, gone_only_path)
+
+    assert _read_archive_part(gone_only_path) is None
+    assert _resolve_probe_part() == (SAMPLE_BVID, SAMPLE_CID, "fixed-sample")
+
+
+def test_probe_part_selection_ignores_a_row_that_is_not_a_bv_id(
+    tmp_root: str, monkeypatch: pytest.MonkeyPatch
+):
+    """A newest row the adapter would reject hands the probe to the sample.
+
+    The row is written with raw SQL rather than through the repository, which
+    validates the shape: this guard exists for the case the repository cannot
+    produce — a foreign or hand-edited row — whose ``bvid`` the adapter would
+    refuse with ``ValueError`` instead of the probe falling back to its sample.
+    """
+
+    database_path = os.path.join(tmp_root, ARCHIVE_DATABASE_NAME)
+    _seed_archive(database_path, bvid=BVID, cid=REHEARSAL_CID)
+    connection = sqlite3.connect(database_path)
+    try:
+        connection.execute(
+            "INSERT INTO video_parts("
+            " bvid, page_index, cid, title, duration_ms, processing_status,"
+            " created_at, updated_at"
+            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
+            ("not-a-bv-id", 9, 4444, "foreign row", 1_000, "discovered", 1, 1),
+        )
+        connection.commit()
+    finally:
+        connection.close()
+    monkeypatch.setenv(ARCHIVE_DATABASE_PATH_ENV_VAR, database_path)
+
+    # The foreign row is the newest one, so the shape check — not the ordering —
+    # is what keeps the adapter's ``ValueError`` out of the probe.
+    assert _read_archive_part(database_path) is None
+    assert _resolve_probe_part() == (SAMPLE_BVID, SAMPLE_CID, "fixed-sample")
+
+
+def test_missing_pinned_distribution_fails_loudly(monkeypatch: pytest.MonkeyPatch):
+    """An opted-in probe without the pin fails with guidance, not a skip."""
+
+    def missing_distribution(name: str) -> str:
+        raise importlib.metadata.PackageNotFoundError(name)
+
+    monkeypatch.setattr(importlib.metadata, "version", missing_distribution)
+
+    with pytest.raises(pytest.fail.Exception):
+        _pinned_package_version()
+
+
+def test_unimportable_pinned_module_fails_loudly(monkeypatch: pytest.MonkeyPatch):
+    """An opted-in probe that cannot import the adapter fails with guidance.
+
+    A module replaced by ``None`` on ``sys.modules`` is what an unimportable
+    adapter looks like to an ``import`` statement, so the guard is driven
+    offline rather than first by a live run in a half-installed environment.
+    """
+
+    monkeypatch.setitem(sys.modules, "bili_asr.sources.bilibili_api_gateway", None)
+
+    with pytest.raises(pytest.fail.Exception) as failure:
+        _load_gateway(None)
+
+    message = str(failure.value)
+    assert PINNED_PACKAGE_DISTRIBUTION_NAME in message
+    assert PINNED_PACKAGE_VERSION in message
+    assert "uv sync" in message
+
+
+def test_live_smoke_switch_is_opt_in(monkeypatch: pytest.MonkeyPatch):
+    """Only the documented ``1`` opts the probe in."""
+
+    monkeypatch.delenv(LIVE_SMOKE_ENV, raising=False)
+    assert _live_smoke_requested() is False
+    for value in ("", "0", "true", "yes", "2"):
+        monkeypatch.setenv(LIVE_SMOKE_ENV, value)
+        assert _live_smoke_requested() is False
+    monkeypatch.setenv(LIVE_SMOKE_ENV, "1")
+    assert _live_smoke_requested() is True
+
+
+def test_track_evidence_carries_counts_languages_and_ai_cc_only():
+    """The listing evidence is bounded: no label body, no URL, no body text."""
+
+    tracks = (
+        SubtitleTrack(
+            language="ai-zh",
+            label=f"自动生成 {SIGNED_SUBTITLE_URL_MARKER}",
+            is_ai=True,
+            track_id="1",
+        ),
+        SubtitleTrack(
+            language="zh-CN",
+            label=RAW_JSON_BODY_MARKER,
+            is_ai=False,
+            track_id=None,
+        ),
+    )
+
+    evidence = _track_evidence(tracks)
+
+    assert evidence == "track_count=2 tracks=ai-zh:ai,zh-CN:cc"
+    assert_leaks_no_markers(evidence, context="live subtitle track evidence")
+    assert RAW_JSON_BODY_MARKER not in evidence
+    assert _track_evidence(()) == "track_count=0 tracks=none"
+
+
+def test_segment_evidence_requires_a_non_decreasing_timeline():
+    """The document-level timeline fact is asserted, and an unordered one fails."""
+
+    forward = (
+        SubtitleSegment(start_ms=0, end_ms=1500, text="未明子"),
+        SubtitleSegment(start_ms=1500, end_ms=2600, text="讲座"),
+    )
+
+    assert _assert_bounded_segment_facts(forward) == (
+        "segments=2 first_start_ms=0 last_end_ms=2600 timeline=non-decreasing"
+    )
+    with pytest.raises(AssertionError):
+        _assert_bounded_segment_facts(tuple(reversed(forward)))
+    with pytest.raises(AssertionError):
+        _assert_bounded_segment_facts(())
+
+
+class _ScriptedGateway:
+    """The probe's two boundary calls, scripted, with no network at all.
+
+    ``_probe_one_part`` is driven through this double so the live flow's control
+    flow — every record-and-skip branch included — is entered by a default
+    (offline, non-opted-in) pytest run.  ``calls`` records which of the two calls
+    were made, in order, so a rehearsal can pin that a listing which never
+    answered is not followed by a body fetch.
+    """
+
+    def __init__(
+        self,
+        *,
+        tracks: tuple[SubtitleTrack, ...] = (),
+        segments: tuple[SubtitleSegment, ...] = (),
+        listing_failure: Exception | None = None,
+        body_failure: Exception | None = None,
+    ) -> None:
+        self._tracks = tracks
+        self._segments = segments
+        self._listing_failure = listing_failure
+        self._body_failure = body_failure
+        self.calls: list[str] = []
+
+    async def get_subtitle_tracks(
+        self, bvid: str, cid: int
+    ) -> tuple[SubtitleTrack, ...]:
+        self.calls.append("get_subtitle_tracks")
+        if self._listing_failure is not None:
+            raise self._listing_failure
+        return self._tracks
+
+    async def fetch_subtitle_segments(
+        self, track: SubtitleTrack, bvid: str, cid: int
+    ) -> tuple[SubtitleSegment, ...]:
+        self.calls.append("fetch_subtitle_segments")
+        if self._body_failure is not None:
+            raise self._body_failure
+        return self._segments
+
+
+def _rehearsal_track() -> SubtitleTrack:
+    """One track DTO whose display label carries both leak sentinels."""
+
+    return SubtitleTrack(
+        language="ai-zh",
+        label=f"自动生成 {SIGNED_SUBTITLE_URL_MARKER} {RAW_JSON_BODY_MARKER}",
+        is_ai=True,
+        track_id="1",
+    )
+
+
+def test_probe_records_an_empty_listing_and_stops_before_the_body(capsys):
+    """No visible track is a recorded observation, and the body is not fetched."""
+
+    gateway = _ScriptedGateway()
+
+    _probe_one_part(gateway, SAMPLE_BVID, SAMPLE_CID, "fixed-sample")
+
+    evidence = capsys.readouterr().out
+    assert "stage=track-listing track_count=0 tracks=none" in evidence
+    assert "no usable track was visible" in evidence
+    assert gateway.calls == ["get_subtitle_tracks"]
+
+
+@pytest.mark.parametrize(
+    (
+        "listing_failure",
+        "body_failure",
+        "expected_evidence",
+        "expected_skip",
+        "expected_calls",
+    ),
+    [
+        pytest.param(
+            GatewayRateLimited(detail="get_subtitle_tracks"),
+            None,
+            "part_source=fixed-sample stage=track-listing refusal_code=rate_limited",
+            "STOP condition",
+            ["get_subtitle_tracks"],
+            id="listing-risk-control-refusal",
+        ),
+        pytest.param(
+            GatewayNotFound(detail="get_subtitle_tracks"),
+            None,
+            "part_source=fixed-sample stage=track-listing track_count=not_found",
+            "must not read as green",
+            ["get_subtitle_tracks"],
+            id="listing-not-found",
+        ),
+        pytest.param(
+            None,
+            GatewayRateLimited(detail="fetch_subtitle_segments"),
+            "stage=subtitle-body refusal_code=rate_limited",
+            "STOP condition",
+            ["get_subtitle_tracks", "fetch_subtitle_segments"],
+            id="body-risk-control-refusal",
+        ),
+        pytest.param(
+            None,
+            GatewayNotFound(detail="fetch_subtitle_segments"),
+            "stage=subtitle-body segments=not_found",
+            "must not read as green",
+            ["get_subtitle_tracks", "fetch_subtitle_segments"],
+            id="body-not-found",
+        ),
+    ],
+)
+def test_probe_records_each_bounded_blocker_and_never_reads_green(
+    capsys,
+    listing_failure: Exception | None,
+    body_failure: Exception | None,
+    expected_evidence: str,
+    expected_skip: str,
+    expected_calls: list[str],
+):
+    """All four record-and-skip branches are rehearsed, and none of them passes.
+
+    Each line names the bounded code and the stage — the listing-side lines also
+    name the part that produced them; each branch skips instead of passing, which
+    is what keeps a run without evidence from reading green; and a listing that
+    never answered is never followed by a body fetch.
+    """
+
+    gateway = _ScriptedGateway(
+        tracks=(_rehearsal_track(),),
+        listing_failure=listing_failure,
+        body_failure=body_failure,
+    )
+
+    with pytest.raises(pytest.skip.Exception) as skipped:
+        _probe_one_part(gateway, SAMPLE_BVID, SAMPLE_CID, "fixed-sample")
+
+    evidence = capsys.readouterr().out
+    assert expected_evidence in evidence
+    assert expected_skip in str(skipped.value)
+    assert gateway.calls == expected_calls
+
+
+def test_probe_records_the_whole_evidence_chain_without_leaking_a_label(capsys):
+    """The visible-track path prints both bounded lines and no upstream text."""
+
+    gateway = _ScriptedGateway(
+        tracks=(_rehearsal_track(),),
+        segments=(
+            SubtitleSegment(start_ms=0, end_ms=1500, text="未明子"),
+            SubtitleSegment(start_ms=1500, end_ms=2600, text="讲座"),
+        ),
+    )
+
+    _probe_one_part(gateway, SAMPLE_BVID, SAMPLE_CID, "archive-db")
+
+    evidence = capsys.readouterr().out
+    assert "stage=track-listing track_count=1 tracks=ai-zh:ai" in evidence
+    assert (
+        "stage=subtitle-body track=ai-zh:ai segments=2 first_start_ms=0"
+        " last_end_ms=2600 timeline=non-decreasing"
+    ) in evidence
+    assert_leaks_no_markers(evidence, context="live subtitle probe rehearsal")
+    assert RAW_JSON_BODY_MARKER not in evidence
+    assert gateway.calls == ["get_subtitle_tracks", "fetch_subtitle_segments"]
```
