# Plan-2 Fix Wave 1 Diff — 20260911-transcript-storage

Base: `1019000`
Head: `5f93e05`
Scope: Task-3 review Minor-1 (pending-order test strength)

```diff
diff --git a/bilibili-asr-archive/tests/test_transcript_repository.py b/bilibili-asr-archive/tests/test_transcript_repository.py
index 28db546..64ce3b4 100644
--- a/bilibili-asr-archive/tests/test_transcript_repository.py
+++ b/bilibili-asr-archive/tests/test_transcript_repository.py
@@ -1363,9 +1363,12 @@ def test_pending_enumeration_orders_never_attempted_before_the_oldest_attempt(tm
     repository = TranscriptRepository(connection)
     try:
         # Insertion order deliberately differs from the work order, so a
-        # missing ORDER BY cannot pass by accident.
+        # missing ORDER BY cannot pass by accident. Both captionless videos
+        # hold page 0 and page 1, so the never-attempted set is a case where
+        # ``bvid`` first and ``page_index`` first interleave differently: the
+        # lock's last two keys are falsifiable, not merely spelled out.
         first_video = _video_with_parts(connection, "BV1A", (3001, 3002, 3003, 3004))
-        _video_with_parts(connection, "BV0Z", (4001,))
+        _video_with_parts(connection, "BV0Z", (4001, 4002))
         _video_with_parts(connection, "BV1GONE", (5001,), processing_status="gone")
         _probe(repository, first_video[2], index=1, finished_at=500)
         _probe(repository, first_video[3], index=2, finished_at=300)
@@ -1373,16 +1376,17 @@ def test_pending_enumeration_orders_never_attempted_before_the_oldest_attempt(tm
         work_ids = [row["work_id"] for row in repository.list_pending_subtitle_parts()]
 
         assert work_ids == [
-            "BV0Z:p0",  # never attempted, lowest bvid
-            "BV1A:p0",  # never attempted, then lowest page index
-            "BV1A:p1",
+            "BV0Z:p0",  # never attempted: lowest bvid, then lowest page index,
+            "BV0Z:p1",  # so this block is BV0Z's two pages and then BV1A's two;
+            "BV1A:p0",  # ordering by page_index first would interleave it as
+            "BV1A:p1",  # BV0Z:p0, BV1A:p0, BV0Z:p1, BV1A:p1 instead.
             "BV1A:p3",  # oldest attempt first
             "BV1A:p2",
         ]
         # A part upstream reported as gone is not work: the enumeration is
         # bounded to what can still yield a caption.
         assert "BV1GONE:p0" not in work_ids
-        assert repository.count_pending_subtitle_parts() == len(work_ids) == 5
+        assert repository.count_pending_subtitle_parts() == len(work_ids) == 6
 
         # The bound takes the head of the locked order.
         assert [
@@ -1390,9 +1394,9 @@ def test_pending_enumeration_orders_never_attempted_before_the_oldest_attempt(tm
         ] == ["BV0Z:p0"]
         assert [
             row["work_id"] for row in repository.list_pending_subtitle_parts(limit=2)
-        ] == ["BV0Z:p0", "BV1A:p0"]
+        ] == ["BV0Z:p0", "BV0Z:p1"]
         assert [
-            row["work_id"] for row in repository.list_pending_subtitle_parts(limit=5)
+            row["work_id"] for row in repository.list_pending_subtitle_parts(limit=6)
         ] == work_ids
     finally:
         connection.close()
```
