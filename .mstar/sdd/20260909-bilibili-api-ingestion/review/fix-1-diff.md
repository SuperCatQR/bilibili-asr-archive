# QC Fix Wave Diff — 20260909-bilibili-api-ingestion

Plan: `20260909-bilibili-api-ingestion` (SDD)
Range: `783986a..3dcc51b`
Base: `783986a` (QC-reviewed implementation head)
Head: `3dcc51b fix(sources): enforce BVID shape at summary normalization (plan QC fix wave)`
Working branch: `feature/20260909-bilibili-api-ingestion`
Scope: targeted re-validation of consolidated findings W1 + S-fix-1..8 (see review/qc-consolidated.md)

```diff
diff --git a/bilibili-asr-archive/src/bili_asr/services/metadata_ingest.py b/bilibili-asr-archive/src/bili_asr/services/metadata_ingest.py
index 5efea0b..afddeb7 100644
--- a/bilibili-asr-archive/src/bili_asr/services/metadata_ingest.py
+++ b/bilibili-asr-archive/src/bili_asr/services/metadata_ingest.py
@@ -26,7 +26,6 @@ from bili_asr.sources.models import (
     GatewayError,
     GatewayRateLimited,
     GatewayShapeError,
-    UserVideoPage,
     VideoPart,
     VideoSummary,
 )
@@ -225,10 +224,17 @@ class MetadataIngestor:
                 page = await self._gateway.get_user_video_page(
                     mid, page_number, PAGE_SIZE
                 )
-                summaries = [
-                    await self._completed_summary(summary, mid)
-                    for summary in page.videos
-                ]
+                completed_by_video: dict[str, VideoSummary] = {}
+                summaries: list[VideoSummary] = []
+                for summary in page.videos:
+                    # One detail fetch per distinct video: a duplicated page
+                    # entry is the same video, so the identical fetch would
+                    # only repeat upstream work.
+                    if summary.bvid not in completed_by_video:
+                        completed_by_video[summary.bvid] = (
+                            await self._completed_summary(summary, mid)
+                        )
+                    summaries.append(completed_by_video[summary.bvid])
                 parts_by_video: dict[str, tuple[VideoPart, ...]] = {}
                 for summary in summaries:
                     # One parts fetch per distinct video: a duplicated page
@@ -387,7 +393,11 @@ class MetadataIngestor:
         The repository's ``record_page`` applies the Plan-1 order — user,
         videos, parts, discoveries, cursor, page outcome — inside one
         transaction and commits it.  Duplicate summary entries collapse into
-        their existing entity rows through the upsert keys.
+        their existing entity rows through the upsert keys, and a bvid
+        duplicated within one page keeps the last occurrence's
+        ``source_position``: the discovery primary key
+        ``(run_id, page_number, bvid)`` makes the later entry overwrite the
+        earlier one.
         """
 
         video_records = [
diff --git a/bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py b/bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py
index 6294700..3e83719 100644
--- a/bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py
+++ b/bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py
@@ -28,7 +28,6 @@ from bilibili_api.user import User
 from bilibili_api.video import Video
 
 from bili_asr.sources.models import (
-    GatewayError,
     GatewayNotFound,
     GatewayRateLimited,
     GatewayResponseError,
@@ -121,8 +120,8 @@ def _normalize_video_summary_item(item: object, requested_mid: int) -> VideoSumm
     if not isinstance(item, Mapping):
         raise GatewayShapeError(detail="video item is not a mapping")
     bvid = item.get("bvid")
-    if not isinstance(bvid, str) or not bvid.strip():
-        raise GatewayShapeError(detail="video item has no bvid")
+    if not isinstance(bvid, str) or _BVID_PATTERN.fullmatch(bvid) is None:
+        raise GatewayShapeError(detail="video item has no valid bvid")
     title = item.get("title")
     if not isinstance(title, str) or not title.strip():
         raise GatewayShapeError(detail="video item has no title")
@@ -209,8 +208,8 @@ def _complete_summary_from_detail(
     """Fill the summary's missing aid from its detail response.
 
     Only ``aid`` is taken from the detail; every other field stays exactly as
-    the list response delivered it.  A detail owned by another user is a
-    bounded shape error.
+    the list response delivered it.  A detail owned by another user, or one
+    naming another video, is a bounded shape error.
     """
 
     if not isinstance(detail, Mapping):
@@ -228,6 +227,9 @@ def _complete_summary_from_detail(
         raise GatewayShapeError(
             detail="detail owner mid does not match the summary"
         )
+    detail_bvid = detail.get("bvid")
+    if not isinstance(detail_bvid, str) or detail_bvid != summary.bvid:
+        raise GatewayShapeError(detail="detail bvid does not match the summary")
     return VideoSummary(
         bvid=summary.bvid,
         aid=detail_aid,
@@ -332,8 +334,6 @@ class BilibiliApiGateway:
             raise GatewayResponseError(detail=operation) from exc
         except ApiException as exc:
             raise GatewayResponseError(detail=operation) from exc
-        except GatewayError:
-            raise
         except Exception as exc:
             raise GatewayTransportError(detail=operation) from exc
 
diff --git a/bilibili-asr-archive/tests/test_bilibili_api_gateway.py b/bilibili-asr-archive/tests/test_bilibili_api_gateway.py
index c6fb7bc..50b21b0 100644
--- a/bilibili-asr-archive/tests/test_bilibili_api_gateway.py
+++ b/bilibili-asr-archive/tests/test_bilibili_api_gateway.py
@@ -44,7 +44,6 @@ from fixtures.fake_bilibili_gateway import (
     SESSDATA_BOUNDARY_VALUE,
     SIGNED_URL_MARKER,
     UPSTREAM_ERROR_TEXT,
-    FakeApiException,
     FakeNetworkException,
     FakeResponseCodeException,
     FakeResponseException,
@@ -329,6 +328,37 @@ def test_get_user_video_page_rejects_malformed_observed_total(bilibili_api_seam)
         asyncio.run(gateway.get_user_video_page(MID, page_number=1))
 
 
+@pytest.mark.parametrize(
+    ("malformed_bvid", "aid"),
+    [
+        ("BV1SHORT", 111),
+        ("BV1SHORT", None),
+        ("av170001", 111),
+    ],
+)
+def test_get_user_video_page_rejects_malformed_upstream_bvid(
+    bilibili_api_seam, malformed_bvid, aid
+):
+    """A non-empty but malformed upstream bvid is a bounded shape error.
+
+    The same shape defect stays bounded on both aid paths: the page
+    boundary rejects the item before any parts or detail call could
+    consume the malformed id downstream.
+    """
+
+    bilibili_api_seam.videos_response = make_videos_response(
+        make_vlist_item(bvid=malformed_bvid, aid=aid), count=1
+    )
+    gateway = _load_gateway()
+
+    with pytest.raises(GatewayShapeError) as caught:
+        asyncio.run(gateway.get_user_video_page(MID, page_number=1))
+
+    assert caught.value.code == "shape_error"
+    assert "bvid" in str(caught.value)
+    assert bilibili_api_seam.calls == ["user.get_videos(pn=1, ps=100)"]
+
+
 # -------------------------------------------------------------- video parts
 
 
@@ -564,6 +594,24 @@ def test_completed_summary_rejects_foreign_detail_owner(bilibili_api_seam):
     assert caught.value.code == "shape_error"
 
 
+def test_completed_summary_rejects_detail_for_another_video(bilibili_api_seam):
+    """A detail naming a different video cannot fill this summary's aid.
+
+    The filled aid must provably belong to the video the summary names, so
+    a detail body for another video is a bounded shape error.
+    """
+
+    bilibili_api_seam.info_response = make_detail_response(bvid="BV1OTHERVID")
+    gateway = _load_gateway()
+
+    with pytest.raises(GatewayShapeError) as caught:
+        asyncio.run(gateway.get_completed_video_summary(_summary(aid=None)))
+
+    assert caught.value.code == "shape_error"
+    assert "bvid" in str(caught.value)
+    assert bilibili_api_seam.calls == ["video.get_info"]
+
+
 def test_completed_summary_rejects_detail_without_aid(bilibili_api_seam):
     """A detail response that still lacks aid cannot complete the summary."""
 
@@ -596,14 +644,18 @@ def test_package_version_falls_back_to_pinned_literal(bilibili_api_seam):
 
 
 def test_package_version_reports_installed_distribution(bilibili_api_seam, monkeypatch):
-    """When the distribution is installed its version wins over the literal."""
+    """When the distribution is installed its version wins over the literal.
+
+    The mocked installed version differs from the pinned literal, so a pass
+    proves the installed-distribution path, not the fallback constant.
+    """
 
     monkeypatch.setattr(
-        importlib.metadata, "version", lambda _name: "17.4.2", raising=True
+        importlib.metadata, "version", lambda _name: "9.9.9", raising=True
     )
     gateway = _load_gateway()
 
-    assert gateway.get_package_version() == "17.4.2"
+    assert gateway.get_package_version() == "9.9.9"
 
 
 # ------------------------------------------------------- DTO self-validation
diff --git a/bilibili-asr-archive/tests/test_metadata_ingest.py b/bilibili-asr-archive/tests/test_metadata_ingest.py
index 287d4af..5a767ae 100644
--- a/bilibili-asr-archive/tests/test_metadata_ingest.py
+++ b/bilibili-asr-archive/tests/test_metadata_ingest.py
@@ -14,7 +14,6 @@ the same module's fake ``bilibili_api`` package seam, still fully offline.
 from __future__ import annotations
 
 import importlib
-import sqlite3
 
 import pytest
 
@@ -26,7 +25,6 @@ from bili_asr.services.metadata_ingest import (
 )
 from bili_asr.sources.models import (
     GatewayRateLimited,
-    GatewayShapeError,
     GatewayTransportError,
     UserVideoPage,
     VideoPart,
@@ -61,11 +59,9 @@ def _page(
     page_number: int,
     *summaries: VideoSummary,
     observed_total: int | None = None,
-    owner_mid: int | None = None,
 ) -> UserVideoPage:
-    """Build one validated page DTO; owner_mid overrides the requested mid."""
+    """Build one validated page DTO owned by the requested user."""
 
-    mid = MID if owner_mid is None else owner_mid
     return UserVideoPage(
         mid=MID, page_number=page_number, videos=summaries, observed_total=observed_total
     )
@@ -248,6 +244,44 @@ def test_duplicate_summaries_in_one_page_collapse_into_single_rows(tmp_root):
         connection.close()
 
 
+def test_within_page_duplicate_discovery_keeps_the_last_source_position(tmp_root):
+    """A bvid duplicated within one page keeps the last occurrence's position.
+
+    The discovery row's primary key is ``(run_id, page_number, bvid)``, so a
+    repeated summary upserts the same row and overwrites ``source_position``
+    with the later occurrence.  This pins the kept flavor: last wins.
+    """
+
+    gateway = FakeGateway()
+    gateway.script_page(
+        1,
+        _page(
+            1,
+            _summary("BV1DUPPOS", aid=441, title="重复条目"),
+            _summary("BV1INTERVAL", aid=442, title="间隔条目"),
+            _summary("BV1DUPPOS", aid=441, title="重复条目"),
+            observed_total=2,
+        ),
+    )
+    gateway.script_parts("BV1DUPPOS", (_part("BV1DUPPOS", 0, cid=4441),))
+    gateway.script_parts("BV1INTERVAL", (_part("BV1INTERVAL", 0, cid=4442),))
+    gateway.script_page(2, _page(2, observed_total=2))
+    connection = open_database(tmp_root)
+    repository = MetadataRepository(connection)
+    try:
+        result = _ingestor(gateway, repository).collect_user_pages(MID)
+
+        assert result.video_count == 2
+        positions = dict(
+            connection.execute(
+                "SELECT bvid, source_position FROM ingestion_discoveries"
+            ).fetchall()
+        )
+        assert positions == {"BV1DUPPOS": 2, "BV1INTERVAL": 1}
+    finally:
+        connection.close()
+
+
 def test_page_limit_ends_run_as_limited_and_resume_completes(tmp_root):
     gateway = FakeGateway()
     gateway.script_page(
@@ -339,7 +373,7 @@ def test_gateway_failure_rolls_back_page_and_preserves_cursor_for_resume(tmp_roo
     repository = MetadataRepository(connection)
     try:
         ingestor = _ingestor(gateway, repository)
-        first = ingestor.collect_user_pages(MID, page_limit=1)
+        ingestor.collect_user_pages(MID, page_limit=1)
         cursor_before_failure = repository.read_cursor(MID)
         assert cursor_before_failure is not None
 
@@ -404,7 +438,7 @@ def test_rate_limited_page_keeps_cursor_and_ends_run_risk_interrupted(tmp_root):
     repository = MetadataRepository(connection)
     try:
         ingestor = _ingestor(gateway, repository)
-        first = ingestor.collect_user_pages(MID, page_limit=1)
+        ingestor.collect_user_pages(MID, page_limit=1)
         cursor_before = repository.read_cursor(MID)
         assert cursor_before is not None
 
@@ -432,6 +466,55 @@ def test_rate_limited_page_keeps_cursor_and_ends_run_risk_interrupted(tmp_root):
         connection.close()
 
 
+def test_parts_stage_failure_persists_nothing_and_leaves_the_cursor_untouched(tmp_root):
+    """A parts-stage fetch failure is bounded with zero persisted payload.
+
+    The page and every summary fetch fine; only ``get_video_parts`` fails.
+    No page transaction has opened at that point, so nothing persists
+    except the bounded page/run failure evidence.
+    """
+
+    gateway = FakeGateway()
+    gateway.script_page(
+        1, _page(1, _summary("BV1PARTFAIL", aid=921), observed_total=2)
+    )
+    gateway.script_parts(
+        "BV1PARTFAIL", GatewayTransportError(detail="get_video_parts")
+    )
+    connection = open_database(tmp_root)
+    repository = MetadataRepository(connection)
+    try:
+        result = _ingestor(gateway, repository).collect_user_pages(MID)
+
+        assert result.outcome == "failed"
+        assert result.error_code == "transport_error"
+        assert result.page_count == 1
+        assert result.video_count == 0
+        assert result.part_count == 0
+        assert repository.read_cursor(MID) is None
+        assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 0
+        assert connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0] == 0
+        assert (
+            connection.execute("SELECT COUNT(*) FROM ingestion_discoveries").fetchone()[0]
+            == 0
+        )
+        page_row = connection.execute(
+            "SELECT page_number, outcome, error_code FROM ingestion_pages"
+            " WHERE run_id = ?",
+            (result.run_id,),
+        ).fetchone()
+        assert tuple(page_row) == (1, "failed", "transport_error")
+        run_row = connection.execute(
+            "SELECT outcome, finished_at FROM ingestion_runs WHERE run_id = ?",
+            (result.run_id,),
+        ).fetchone()
+        assert run_row["outcome"] == "failed"
+        assert run_row["finished_at"] is not None
+        assert gateway.parts_calls == ["BV1PARTFAIL"]
+    finally:
+        connection.close()
+
+
 def test_foreign_owner_summary_fails_the_page_before_parts_are_requested(tmp_root):
     """D3: part requests only target summaries owned by the requested mid."""
 
@@ -497,6 +580,41 @@ def test_missing_aid_is_completed_through_the_gateway_without_speculation(tmp_ro
         connection.close()
 
 
+def test_duplicate_aid_less_summaries_trigger_one_completion_call(tmp_root):
+    """A duplicated aid-less entry is one video: one detail fetch.
+
+    Same dedup principle as the parts fetches: the second entry reuses the
+    completed summary instead of repeating the upstream detail call.
+    """
+
+    gateway = FakeGateway()
+    gateway.script_completion("BV1DUPLICATE", _summary("BV1DUPLICATE", aid=555))
+    gateway.script_page(
+        1,
+        _page(
+            1,
+            _summary("BV1DUPLICATE", aid=None, title="无编号重复条目"),
+            _summary("BV1DUPLICATE", aid=None, title="无编号重复条目"),
+            observed_total=1,
+        ),
+    )
+    gateway.script_page(2, _page(2, observed_total=1))
+    gateway.script_parts("BV1DUPLICATE", (_part("BV1DUPLICATE", 0, cid=5556),))
+    connection = open_database(tmp_root)
+    repository = MetadataRepository(connection)
+    try:
+        result = _ingestor(gateway, repository).collect_user_pages(MID)
+
+        assert gateway.completion_calls == ["BV1DUPLICATE"]
+        assert gateway.parts_calls == ["BV1DUPLICATE"]
+        stored = dict(connection.execute("SELECT bvid, aid FROM videos").fetchall())
+        assert stored == {"BV1DUPLICATE": 555}
+        assert result.outcome == "complete"
+        assert result.video_count == 1
+    finally:
+        connection.close()
+
+
 @pytest.mark.parametrize(
     ("kwargs", "expected"),
     [
@@ -511,10 +629,14 @@ def test_missing_aid_is_completed_through_the_gateway_without_speculation(tmp_ro
     ],
 )
 def test_collect_arguments_are_validated(kwargs, expected):
-    with pytest.raises(expected):
-        MetadataIngestor(FakeGateway(), MetadataRepository(open_database(":memory:"))).collect_user_pages(
-            **kwargs
-        )
+    connection = open_database(":memory:")
+    try:
+        with pytest.raises(expected):
+            MetadataIngestor(
+                FakeGateway(), MetadataRepository(connection)
+            ).collect_user_pages(**kwargs)
+    finally:
+        connection.close()
 
 
 # ----------------------------------------- real adapter over the package seam
@@ -537,7 +659,7 @@ def test_bilibili_api_gateway_run_persists_normalized_rows(tmp_root, bilibili_ap
     script.parts_response = [
         make_part_item(cid=2222, page=1, part="  第一部分  ", duration=12)
     ]
-    script.info_response = make_detail_response()
+    script.info_response = make_detail_response(bvid="BV1SEAMRUNAA")
     connection = open_database(tmp_root)
     repository = MetadataRepository(connection)
     try:
@@ -609,7 +731,7 @@ def test_bilibili_api_gateway_run_persists_no_upstream_payload_markers(
         make_part_item(cid=2222, player_note=SESSDATA_BOUNDARY_VALUE)
     ]
     script.info_response = make_detail_response(
-        raw_body=RAW_JSON_BODY_MARKER, frame_url=SIGNED_URL_MARKER
+        bvid="BV1SEAMLEAKS", raw_body=RAW_JSON_BODY_MARKER, frame_url=SIGNED_URL_MARKER
     )
     connection = open_database(tmp_root)
     repository = MetadataRepository(connection)
@@ -733,6 +855,70 @@ def test_bilibili_api_gateway_foreign_owner_page_requests_no_parts(
         connection.close()
 
 
+@pytest.mark.parametrize("aid", [1001, None], ids=["aid-carrying", "aid-less"])
+def test_malformed_upstream_bvid_page_fails_bounded_and_preserves_the_prior_cursor(
+    tmp_root, bilibili_api_seam, aid
+):
+    """A malformed-but-nonempty upstream bvid stays inside the taxonomy.
+
+    The page boundary rejects the item as a bounded shape error on both aid
+    paths, records the page/run failure evidence, never reaches the parts
+    or detail fetches, and leaves the prior cursor byte-for-byte untouched.
+    """
+
+    script = bilibili_api_seam
+    script.videos_response = make_videos_response(
+        make_vlist_item(bvid="BV1KEPTPAGEX", aid=1001), count=2
+    )
+    script.parts_response = [make_part_item(cid=2222)]
+    connection = open_database(tmp_root)
+    repository = MetadataRepository(connection)
+    try:
+        ingestor = MetadataIngestor(_seam_gateway(), repository)
+        first = ingestor.collect_user_pages(MID, start_page=1, page_limit=1)
+        assert first.outcome == "limited"
+        cursor_before = repository.read_cursor(MID)
+        assert cursor_before is not None
+        calls_after_first = list(script.calls)
+
+        script.videos_response = make_videos_response(
+            make_vlist_item(bvid="BV1MALFORMD", aid=aid), count=2
+        )
+        failed = ingestor.collect_user_pages(MID)
+
+        assert failed.outcome == "failed"
+        assert failed.error_code == "shape_error"
+        assert failed.page_count == 1
+        assert failed.video_count == 0
+        assert failed.part_count == 0
+        # The prior cursor is preserved exactly across the failed page.
+        assert repository.read_cursor(MID) == cursor_before
+        assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 1
+        assert connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0] == 1
+        assert (
+            connection.execute("SELECT COUNT(*) FROM ingestion_discoveries").fetchone()[0]
+            == 1
+        )
+        failed_run = connection.execute(
+            "SELECT outcome, finished_at FROM ingestion_runs WHERE run_id = ?",
+            (failed.run_id,),
+        ).fetchone()
+        assert failed_run["outcome"] == "failed"
+        assert failed_run["finished_at"] is not None
+        failed_page_rows = connection.execute(
+            "SELECT page_number, outcome, error_code FROM ingestion_pages"
+            " WHERE run_id = ?",
+            (failed.run_id,),
+        ).fetchall()
+        assert [tuple(row) for row in failed_page_rows] == [
+            (2, "failed", "shape_error")
+        ]
+        # The malformed bvid never reached the parts or detail fetches.
+        assert script.calls == calls_after_first + ["user.get_videos(pn=2, ps=100)"]
+    finally:
+        connection.close()
+
+
 def test_no_leak_marker_scan_catches_contamination():
     """The persistence hygiene scanner is not vacuous."""
 
```
