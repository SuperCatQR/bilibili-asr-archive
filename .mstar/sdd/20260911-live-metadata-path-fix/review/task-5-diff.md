# Task 5 Diff — 20260911-live-metadata-path-fix

Base: `f4af1aa`
Head: `f44066c`

```diff
diff --git a/bilibili-asr-archive/README.md b/bilibili-asr-archive/README.md
index aba7276..cb270d0 100644
--- a/bilibili-asr-archive/README.md
+++ b/bilibili-asr-archive/README.md
@@ -506,7 +506,7 @@ only restart path.
 
 - **Default page bound**: `--limit-pages` is optional and defaults to
   `DEFAULT_PAGE_LIMIT = 10`. The canonical command above therefore stops
-  after 10 pages (the ingestor's page size is 100), ends the run `limited`,
+  after 10 pages (the ingestor's page size is 30), ends the run `limited`,
   and still exits 0 — a limited run is never claimed as complete. A full
   archive walk is a series of resumable runs: re-run the same command to
   continue from the stored cursor, or pass an explicit `--limit-pages` for
diff --git a/bilibili-asr-archive/src/bili_asr/services/metadata_ingest.py b/bilibili-asr-archive/src/bili_asr/services/metadata_ingest.py
index afddeb7..0f98fc5 100644
--- a/bilibili-asr-archive/src/bili_asr/services/metadata_ingest.py
+++ b/bilibili-asr-archive/src/bili_asr/services/metadata_ingest.py
@@ -43,7 +43,11 @@ from bili_asr.storage.models import (
 )
 
 SOURCE_PACKAGE = "bilibili-api-python"
-PAGE_SIZE = 100
+#: Shipped page size of the user-video page call.  Upstream answers ``ps=100``
+#: with its bounded ``-400``/HTTP 412 rejection while 30 — the pinned
+#: package's own documented value — returns ``code=0``, so the shipped default
+#: stays inside the bound upstream accepts.
+PAGE_SIZE = 30
 
 
 def _now() -> int:
diff --git a/bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py b/bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py
index f80d45e..0335948 100644
--- a/bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py
+++ b/bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py
@@ -280,9 +280,14 @@ class BilibiliApiGateway:
         self._w_webid_by_mid: dict[int, str] = {}
 
     async def get_user_video_page(
-        self, mid: int, page_number: int, page_size: int = 100
+        self, mid: int, page_number: int, page_size: int = 30
     ) -> UserVideoPage:
-        """Fetch and normalize exactly one bounded user-video page."""
+        """Fetch and normalize exactly one bounded user-video page.
+
+        The default is the upstream-accepted page size declared by the
+        :class:`~bili_asr.sources.models.BilibiliGateway` protocol; an
+        explicit ``page_size`` still overrides it.
+        """
 
         _require_positive_argument(mid, "mid")
         _require_positive_argument(page_number, "page_number")
diff --git a/bilibili-asr-archive/src/bili_asr/sources/models.py b/bilibili-asr-archive/src/bili_asr/sources/models.py
index d81415c..8647147 100644
--- a/bilibili-asr-archive/src/bili_asr/sources/models.py
+++ b/bilibili-asr-archive/src/bili_asr/sources/models.py
@@ -95,8 +95,11 @@ class UserVideoPage:
 class BilibiliGateway(Protocol):
     """Application-owned gateway protocol for the pinned package adapter."""
 
+    # 30 is the page size the user-video endpoint accepts: the pinned package
+    # documents ``ps`` as ``const int: 30`` and upstream answers ``ps=100``
+    # with its bounded ``-400``/HTTP 412 rejection.
     async def get_user_video_page(
-        self, mid: int, page_number: int, page_size: int = 100
+        self, mid: int, page_number: int, page_size: int = 30
     ) -> UserVideoPage: ...
 
     async def get_video_parts(self, bvid: str) -> tuple[VideoPart, ...]: ...
diff --git a/bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py b/bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py
index ce2364e..4829d2b 100644
--- a/bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py
+++ b/bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py
@@ -255,7 +255,7 @@ class FakeGateway:
         self._completions[bvid] = completed
 
     async def get_user_video_page(
-        self, mid: int, page_number: int, page_size: int = 100
+        self, mid: int, page_number: int, page_size: int = 30
     ) -> UserVideoPage:
         self.page_calls.append((mid, page_number, page_size))
         return self._scripted(self._pages, page_number, "user-video-page")
diff --git a/bilibili-asr-archive/tests/test_bilibili_api_gateway.py b/bilibili-asr-archive/tests/test_bilibili_api_gateway.py
index 6ba4fe4..f759143 100644
--- a/bilibili-asr-archive/tests/test_bilibili_api_gateway.py
+++ b/bilibili-asr-archive/tests/test_bilibili_api_gateway.py
@@ -25,6 +25,7 @@ import ast
 import asyncio
 import importlib
 import importlib.metadata
+import inspect
 import os
 import pathlib
 import tomllib
@@ -36,6 +37,7 @@ from packaging.utils import canonicalize_name
 from bili_asr.config import PROXY_ENV_VAR, PROXY_ENV_VARS, resolve_proxy
 from bili_asr.services.metadata_ingest import MetadataIngestor
 from bili_asr.sources.models import (
+    BilibiliGateway,
     GatewayNotFound,
     GatewayRateLimited,
     GatewayResponseError,
@@ -194,7 +196,7 @@ def test_get_user_video_page_normalizes_documented_fields(bilibili_api_seam):
     assert summary.title == "未明子讲座"
     assert summary.pubdate == PUBDATE
     assert summary.mid == MID
-    assert bilibili_api_seam.calls == ["space.arc.search(pn=1, ps=100)"]
+    assert bilibili_api_seam.calls == ["space.arc.search(pn=1, ps=30)"]
     # The credential value must never surface on any DTO or page.
     assert SESSDATA_BOUNDARY_VALUE not in repr(page)
     assert SESSDATA_BOUNDARY_VALUE not in str(page)
@@ -211,6 +213,51 @@ def test_get_user_video_page_forwards_requested_page_and_size(bilibili_api_seam)
     assert bilibili_api_seam.calls == ["space.arc.search(pn=4, ps=50)"]
 
 
+def test_get_user_video_page_defaults_to_upstream_accepted_size(bilibili_api_seam):
+    """An omitted page size issues the upstream-accepted ``ps=30``.
+
+    The endpoint answers the former ``ps=100`` default with its bounded
+    ``-400``/HTTP 412 rejection, so the protocol declaration and the adapter
+    both default to 30 — reverting either to 100 fails this test.
+    """
+
+    bilibili_api_seam.videos_response = make_videos_response(make_vlist_item(), count=1)
+    gateway = _load_gateway()
+
+    asyncio.run(gateway.get_user_video_page(MID, page_number=1))
+
+    assert bilibili_api_seam.calls == ["space.arc.search(pn=1, ps=30)"]
+    declared = inspect.signature(BilibiliGateway.get_user_video_page)
+    assert declared.parameters["page_size"].default == 30
+
+
+def test_get_user_video_page_explicit_size_override_keeps_normalization(
+    bilibili_api_seam,
+):
+    """An explicit page size still flows through and normalizes the page."""
+
+    bilibili_api_seam.videos_response = make_videos_response(
+        make_vlist_item(title="  未明子讲座  "), count=7
+    )
+    gateway = _load_gateway()
+
+    page = asyncio.run(gateway.get_user_video_page(MID, page_number=2, page_size=50))
+
+    assert bilibili_api_seam.calls == ["space.arc.search(pn=2, ps=50)"]
+    assert isinstance(page, UserVideoPage)
+    assert (page.mid, page.page_number, page.observed_total) == (MID, 2, 7)
+    assert isinstance(page.videos, tuple)
+    (summary,) = page.videos
+    assert isinstance(summary, VideoSummary)
+    assert (summary.bvid, summary.aid, summary.title, summary.pubdate, summary.mid) == (
+        BVID,
+        111,
+        "未明子讲座",
+        PUBDATE,
+        MID,
+    )
+
+
 def test_get_user_video_page_tolerates_plain_list_container(bilibili_api_seam):
     """A plain ``list`` array instead of ``list.vlist`` normalizes too."""
 
@@ -394,7 +441,7 @@ def test_get_user_video_page_rejects_malformed_upstream_bvid(
 
     assert caught.value.code == "shape_error"
     assert "bvid" in str(caught.value)
-    assert bilibili_api_seam.calls == ["space.arc.search(pn=1, ps=100)"]
+    assert bilibili_api_seam.calls == ["space.arc.search(pn=1, ps=30)"]
 
 
 # ------------------------------------- user page: risk-control-safe request
@@ -978,7 +1025,7 @@ def test_gateway_applies_the_resolved_proxy_once_before_the_first_call(
 
     asyncio.run(gateway.get_user_video_page(MID, page_number=1))
 
-    assert bilibili_api_seam.calls == ["space.arc.search(pn=1, ps=100)"]
+    assert bilibili_api_seam.calls == ["space.arc.search(pn=1, ps=30)"]
     # Apply-once: no request re-applies or re-reads the setting.
     assert bilibili_api_seam.applied_proxies == [PROXY_BOUNDARY_VALUE]
 
@@ -1034,7 +1081,7 @@ def test_gateway_leaves_the_package_setting_untouched_without_a_proxy(
 
     asyncio.run(gateway.get_user_video_page(MID, page_number=1))
 
-    assert bilibili_api_seam.calls == ["space.arc.search(pn=1, ps=100)"]
+    assert bilibili_api_seam.calls == ["space.arc.search(pn=1, ps=30)"]
     assert bilibili_api_seam.applied_proxies == []
 
 
@@ -1341,7 +1388,7 @@ def test_gateway_dto_drops_unknown_upstream_payload_fields(bilibili_api_seam):
         assert_leaks_no_markers(repr(surface), context="gateway DTO repr")
         assert_leaks_no_markers(str(surface), context="gateway DTO str")
     assert bilibili_api_seam.calls == [
-        "space.arc.search(pn=1, ps=100)",
+        "space.arc.search(pn=1, ps=30)",
         "video.get_info",
         "video.get_pages",
     ]
@@ -1368,7 +1415,7 @@ def test_live_smoke_single_public_page_for_archive_owner(tmp_root):
     """Opt-in live probe: ONE public metadata page for UID 23191782.
 
     Skipped unless the operator sets ``BILI_LIVE_SMOKE=1``.  The probe
-    requests exactly one bounded page (``ps=100``) for the archive owner
+    requests exactly one bounded page (``ps=30``) for the archive owner
     through the real adapter, ingests it into a fresh temporary SQLite
     database, calls no subtitle/playback/audio/ASR/export endpoint,
     requires no credential, and keeps every raw upstream payload
diff --git a/bilibili-asr-archive/tests/test_metadata_cli.py b/bilibili-asr-archive/tests/test_metadata_cli.py
index b0f3581..4564e8d 100644
--- a/bilibili-asr-archive/tests/test_metadata_cli.py
+++ b/bilibili-asr-archive/tests/test_metadata_cli.py
@@ -341,9 +341,9 @@ def test_fetch_meta_creates_fresh_database_and_completes(
     # page fetch, one parts fetch, one empty-page fetch (aid present, so no
     # detail call).
     assert bilibili_api_seam.calls == [
-        "space.arc.search(pn=1, ps=100)",
+        "space.arc.search(pn=1, ps=30)",
         "video.get_pages",
-        "space.arc.search(pn=2, ps=100)",
+        "space.arc.search(pn=2, ps=30)",
     ]
 
 
@@ -380,7 +380,7 @@ def test_fetch_meta_limit_pages_stops_limited_exit_zero(
         connection.close()
     assert [
         call for call in bilibili_api_seam.calls if call.startswith("space.arc.search")
-    ] == ["space.arc.search(pn=1, ps=100)"]
+    ] == ["space.arc.search(pn=1, ps=30)"]
 
 
 def test_fetch_meta_start_page_overrides_cursor(
@@ -398,7 +398,7 @@ def test_fetch_meta_start_page_overrides_cursor(
     assert main(["fetch-meta", "--archive-root", tmp_root, "--start-page", "1"]) == 0
 
     # Page 1 was requested again even though the stored cursor pointed at 2.
-    assert bilibili_api_seam.calls.count("space.arc.search(pn=1, ps=100)") == 2
+    assert bilibili_api_seam.calls.count("space.arc.search(pn=1, ps=30)") == 2
     connection = open_database(tmp_root)
     try:
         start_pages = [
@@ -432,7 +432,7 @@ def test_fetch_meta_without_flags_resumes_from_stored_cursor(
 
     # Page 1 was not refetched: the run resumed at the cursor's page 2,
     # while run 1's own completion check already touched page 2.
-    assert bilibili_api_seam.calls.count("space.arc.search(pn=1, ps=100)") == 1
+    assert bilibili_api_seam.calls.count("space.arc.search(pn=1, ps=30)") == 1
     connection = open_database(tmp_root)
     try:
         start_pages = [
diff --git a/bilibili-asr-archive/tests/test_metadata_e2e.py b/bilibili-asr-archive/tests/test_metadata_e2e.py
index a087f22..4cf068d 100644
--- a/bilibili-asr-archive/tests/test_metadata_e2e.py
+++ b/bilibili-asr-archive/tests/test_metadata_e2e.py
@@ -302,10 +302,10 @@ def test_fetch_meta_normalizes_single_part_and_multipart_videos_end_to_end(
     # page fetch, one parts fetch per distinct video, then the completing
     # empty-page fetch (aids present, so no detail calls).
     assert script.calls == [
-        "space.arc.search(pn=1, ps=100)",
+        "space.arc.search(pn=1, ps=30)",
         "video.get_pages",
         "video.get_pages",
-        "space.arc.search(pn=2, ps=100)",
+        "space.arc.search(pn=2, ps=30)",
     ]
     assert_only_documented_metadata_calls(script.calls)
 
@@ -440,7 +440,7 @@ def test_fetch_meta_rerun_of_same_page_stores_no_duplicate_rows(
     assert "sessdata: present" in out
     assert_leaks_no_markers(out + err, context="fetch-meta re-run output")
     # Page 1 was fetched exactly twice: once per run.
-    assert script.calls.count("space.arc.search(pn=1, ps=100)") == 2
+    assert script.calls.count("space.arc.search(pn=1, ps=30)") == 2
 
     for relative in LEGACY_SIDECAR_PATHS:
         assert not os.path.exists(os.path.join(tmp_root, relative))
@@ -572,11 +572,11 @@ def test_fetch_meta_failed_page_preserves_cursor_and_resume_succeeds(
     # The full call trace: bounded page fetches, one parts fetch per new
     # video, the failed resume page, then the successful resume.
     assert script.calls == [
-        "space.arc.search(pn=1, ps=100)",
+        "space.arc.search(pn=1, ps=30)",
         "video.get_pages",
-        "space.arc.search(pn=2, ps=100)",
-        "space.arc.search(pn=2, ps=100)",
+        "space.arc.search(pn=2, ps=30)",
+        "space.arc.search(pn=2, ps=30)",
         "video.get_pages",
-        "space.arc.search(pn=3, ps=100)",
+        "space.arc.search(pn=3, ps=30)",
     ]
     assert_only_documented_metadata_calls(script.calls)
diff --git a/bilibili-asr-archive/tests/test_metadata_ingest.py b/bilibili-asr-archive/tests/test_metadata_ingest.py
index be1e5d9..a89bf8f 100644
--- a/bilibili-asr-archive/tests/test_metadata_ingest.py
+++ b/bilibili-asr-archive/tests/test_metadata_ingest.py
@@ -701,7 +701,7 @@ def test_bilibili_api_gateway_run_persists_normalized_rows(tmp_root, bilibili_ap
         # The pinned adapter drove exactly the three documented upstream
         # calls: one page fetch, the aid completion, one parts fetch.
         assert script.calls == [
-            "space.arc.search(pn=1, ps=100)",
+            "space.arc.search(pn=1, ps=30)",
             "video.get_info",
             "video.get_pages",
         ]
@@ -849,7 +849,7 @@ def test_bilibili_api_gateway_foreign_owner_page_requests_no_parts(
         assert [tuple(row) for row in page_rows] == [(1, "failed", "shape_error")]
 
         # Exactly one page fetch: no parts, no detail, nothing else.
-        assert script.calls == ["space.arc.search(pn=1, ps=100)"]
+        assert script.calls == ["space.arc.search(pn=1, ps=30)"]
         assert_only_documented_metadata_calls(script.calls)
     finally:
         connection.close()
@@ -914,7 +914,7 @@ def test_malformed_upstream_bvid_page_fails_bounded_and_preserves_the_prior_curs
             (2, "failed", "shape_error")
         ]
         # The malformed bvid never reached the parts or detail fetches.
-        assert script.calls == calls_after_first + ["space.arc.search(pn=2, ps=100)"]
+        assert script.calls == calls_after_first + ["space.arc.search(pn=2, ps=30)"]
     finally:
         connection.close()
 
```
