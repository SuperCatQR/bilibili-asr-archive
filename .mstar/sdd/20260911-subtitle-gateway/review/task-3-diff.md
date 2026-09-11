# Task 3 Diff — 20260911-subtitle-gateway

Base: `7f7156a`
Head: `c3d362c`

```diff
diff --git a/bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py b/bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py
index 6134bcf..27ebef8 100644
--- a/bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py
+++ b/bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py
@@ -23,7 +23,7 @@ import re
 from collections.abc import Awaitable, Callable, Mapping
 from typing import Any
 
-from bilibili_api import Credential, request_settings, user, video
+from bilibili_api import Credential, request_settings, user
 from bilibili_api.exceptions import (
     ApiException,
     NetworkException,
@@ -32,6 +32,7 @@ from bilibili_api.exceptions import (
     WbiRetryTimesExceedException,
 )
 from bilibili_api.utils.network import Api
+from bilibili_api.video import API as VIDEO_API, Video
 
 from bili_asr.config import resolve_proxy
 from bili_asr.sources.models import (
@@ -78,7 +79,11 @@ _USER_VIDEO_PAGE_ENDPOINT = user.API["info"]["video"]
 # payload carries the part's subtitle inventory.  ``url``/``method``/``wbi``
 # are read from it for the same reason; ``dm`` and ``verify`` are deliberately
 # overridden per call (see ``BilibiliApiGateway._fetch_subtitle_inventory``).
-_PLAYER_INFO_ENDPOINT = video.API["info"]["get_player_info"]
+# Only the endpoint description and ``Video`` are imported from the pin's
+# ``video`` module: binding the whole module would make its other names
+# (``Episode``, ``VideoOnlineMonitor``, ``get_api``, ``get_cid_info``,
+# ``get_client``) source-reachable here without the import boundary noticing.
+_PLAYER_INFO_ENDPOINT = VIDEO_API["info"]["get_player_info"]
 
 
 def _require_positive_argument(value: object, field: str) -> None:
@@ -538,7 +543,7 @@ class BilibiliApiGateway:
             raise ValueError("bvid must be a BV-prefixed 10-character id")
         pages = await self._await_upstream(
             "get_video_parts",
-            lambda: video.Video(bvid=bvid, credential=self._credential).get_pages(),
+            lambda: Video(bvid=bvid, credential=self._credential).get_pages(),
         )
         return _normalize_video_parts(pages, bvid)
 
@@ -555,7 +560,7 @@ class BilibiliApiGateway:
             return summary
         detail = await self._await_upstream(
             "get_completed_video_summary",
-            lambda: video.Video(
+            lambda: Video(
                 bvid=summary.bvid, credential=self._credential
             ).get_info(),
         )
diff --git a/bilibili-asr-archive/tests/test_bilibili_api_gateway.py b/bilibili-asr-archive/tests/test_bilibili_api_gateway.py
index 9a5f88c..d7174cd 100644
--- a/bilibili-asr-archive/tests/test_bilibili_api_gateway.py
+++ b/bilibili-asr-archive/tests/test_bilibili_api_gateway.py
@@ -106,12 +106,16 @@ PACKAGE_HTTP_CLIENT_CANONICAL_NAMES = frozenset({"curl-cffi", "httpx", "aiohttp"
 #: The exact bilibili_api import surface the adapter is allowed to use.  The
 #: user-video page call is issued through ``user``'s own endpoint description
 #: and the WBI-signed ``utils.network.Api``, not through a ``user`` delegate;
-#: the subtitle call reads its transport fields from ``video``'s own player
-#: endpoint description the same way, so both endpoint-description modules come
-#: from the package root and the WBI-signed ``Api`` stays the one request path.
+#: the subtitle call reads its transport fields from the player endpoint
+#: description the same way.  The ``video`` module is deliberately bound to its
+#: two needed names instead of the whole module (only ``API``, locally aliased
+#: to ``VIDEO_API`` so it cannot be confused with the ``Api`` request class, and
+#: ``Video``), so ``Episode``, ``VideoOnlineMonitor``, ``get_api``,
+#: ``get_cid_info`` and ``get_client`` are not source-reachable here.
 ALLOWED_PACKAGE_IMPORTS = {
-    "bilibili_api": {"Credential", "request_settings", "user", "video"},
+    "bilibili_api": {"Credential", "request_settings", "user"},
     "bilibili_api.utils.network": {"Api"},
+    "bilibili_api.video": {"API", "Video"},
     "bilibili_api.exceptions": {
         "ApiException",
         "NetworkException",
@@ -277,29 +281,33 @@ ALLOWED_EXCEPTION_NAMES = (
     "WbiRetryTimesExceedException",
 )
 
-#: Attribute names that would mark playback/danmaku/audio/ASR/export usage —
-#: the surfaces outside this plan's boundary.  Tokens are matched as plain
-#: substrings, so only unambiguous names belong here (``stream`` would
-#: false-positive on ``_await_upstream``).  The subtitle-acquisition family
-#: (``subtitle``, ``player``, ``download``) was removed here on 2026-09-11 by
-#: the PM-authorized Task-2 update: this plan legitimately issues the player and
-#: subtitle-document calls, and
-#: ``test_gateway_source_never_names_forbidden_seam_methods`` now positively
-#: asserts that surface instead (see ``AUTHORIZED_SUBTITLE_ATTRIBUTES``).
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
     "playback",
     "playurl",
     "play_url",
+    "download",
     "danmaku",
     "audio",
     "asr",
     "export",
 )
 
-#: The tokens the authorized update removed from the forbidden list.  They are
-#: kept here only so the positive control below can prove the removal is
-#: load-bearing: each asserted attribute name still carries one of them.
-AUTHORIZED_SEAM_METHOD_TOKENS = ("subtitle", "player", "download")
+#: The tokens the authorized update removed from the forbidden list and this
+#: plan still needs.  They are kept here only so the positive control below can
+#: prove the removal is load-bearing: each asserted attribute name still carries
+#: one of them.
+AUTHORIZED_SEAM_METHOD_TOKENS = ("subtitle", "player")
 
 #: The adapter's own subtitle-surface attributes the token scan must be able to
 #: see.  Asserting them present keeps the forbidden-token check non-vacuous: it
@@ -1695,14 +1703,15 @@ def test_gateway_imports_stay_on_metadata_surface():
     """The adapter imports exactly the enforced allow-list, nothing broader.
 
     ``ALLOWED_PACKAGE_IMPORTS`` is compared exactly: ``Credential`` and the
-    ``request_settings``/``user``/``video`` modules from the package root, the
-    WBI-signed ``utils.network.Api``, and the five exception names.  Both
-    endpoint-description modules come from the package root — the subtitle call
-    reads ``video.API["info"]["get_player_info"]`` the way the page call reads
-    ``user.API["info"]["video"]``, and ``utils.network.Api`` stays the one
-    request path.  ``User`` is deliberately not among them: the page call goes
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
@@ -1729,11 +1738,13 @@ def test_gateway_imports_stay_on_metadata_surface():
 def test_gateway_source_never_names_forbidden_seam_methods():
     """The adapter source stays off every surface outside this plan's boundary.
 
-    ``FORBIDDEN_SEAM_METHOD_TOKENS`` no longer carries the authorized
-    subtitle-acquisition family, so the second positive control below asserts
-    that family's own attributes are present *and* that they still carry a
-    removed token: re-forbidding the removal fails there instead of letting the
-    scan pass because the adapter has no subtitle code to see.
+    ``FORBIDDEN_SEAM_METHOD_TOKENS`` carries the media/playback family only:
+    the authorized subtitle-acquisition tokens are ``subtitle`` and ``player``
+    (``download`` is forbidden again, because this iteration acquires no
+    media).  The second positive control below asserts that family's own
+    attributes are present *and* that they still carry an allowed token:
+    re-forbidding the removal fails there instead of letting the scan pass
+    because the adapter has no subtitle code to see.
     """
 
     gateway_path = (
@@ -2822,6 +2833,40 @@ def test_fetch_subtitle_segments_reads_not_logged_in_as_no_visible_track(
     assert bilibili_api_seam.calls == [_listing_call()]
 
 
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
 @pytest.mark.parametrize(
     "unreadable_document",
     [
diff --git a/bilibili-asr-archive/tests/test_live_subtitle_smoke.py b/bilibili-asr-archive/tests/test_live_subtitle_smoke.py
new file mode 100644
index 0000000..3b9bcb3
--- /dev/null
+++ b/bilibili-asr-archive/tests/test_live_subtitle_smoke.py
@@ -0,0 +1,535 @@
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
+  ``fetch-meta`` command defaults to.  A missing, unreadable, or part-less
+  database is not a probe failure;
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
+import sqlite3
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
+    GatewayNotFound,
+    GatewayRateLimited,
+    SubtitleSegment,
+    SubtitleTrack,
+)
+from bili_asr.storage.database import MetadataRepository, open_database
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
+    ``video_part_id``) is the deterministic one probed.  A database that does
+    not exist, a file that is not a readable SQLite database, and a database
+    without a part row all answer ``None`` and hand the probe to its documented
+    sample fallback.
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
+            " WHERE cid > 0 ORDER BY video_part_id DESC LIMIT 1"
+        ).fetchone()
+    except sqlite3.Error:
+        return None
+    finally:
+        connection.close()
+    if row is None:
+        return None
+    bvid, cid = row
+    if not isinstance(bvid, str) or isinstance(cid, bool) or not isinstance(cid, int):
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
+    try:
+        tracks = asyncio.run(gateway.get_subtitle_tracks(bvid, cid))
+    except GatewayRateLimited as refusal:
+        _record_risk_control_refusal(
+            refusal, stage="track-listing", part_source=part_source
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
+# ------------------------------------------------------------- rehearsals
+#
+# The rehearsals below run in every default (offline) pytest run and cover the
+# probe's own logic — part selection, the read-only archive query, the loud-fail
+# guard, and the bounded evidence renderers — so a broken query or a loosened
+# assertion fails offline instead of first surfacing during a live run.  No
+# live behaviour is claimed here, and no network call is made.
+
+
+def _seed_archive(database_path: str, *, bvid: str, cid: int) -> None:
+    """Seed one user, video, and part into a real archive database."""
+
+    connection = open_database(database_path)
+    repository = MetadataRepository(connection)
+    try:
+        with repository.transaction():
+            repository.upsert_user(make_user_record())
+            repository.upsert_video(make_video_record(bvid))
+            repository.upsert_part(make_part_record(bvid, cid=cid))
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
```
