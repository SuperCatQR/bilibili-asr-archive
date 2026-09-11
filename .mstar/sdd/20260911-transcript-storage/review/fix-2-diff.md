# Plan-2 Fix Wave 2 Diff — 20260911-transcript-storage

Base: `5f93e05`
Head: `4dcbf5d`
Scope: plan-QC QC3-001 (page_index falsifiability) + QC3-002 (repository guard)

```diff
diff --git a/bilibili-asr-archive/src/bili_asr/storage/database.py b/bilibili-asr-archive/src/bili_asr/storage/database.py
index 499164c..01399f5 100644
--- a/bilibili-asr-archive/src/bili_asr/storage/database.py
+++ b/bilibili-asr-archive/src/bili_asr/storage/database.py
@@ -743,11 +743,15 @@ class TranscriptRepository:
 
     The connection must come with ``row_factory = sqlite3.Row`` and
     ``PRAGMA foreign_keys`` enabled — exactly the state :func:`open_database`
-    establishes; the constructor rejects anything else.
+    establishes — and must carry the transcript-schema contract: the
+    constructor rejects anything else, so a caller that skipped
+    :func:`require_subtitle_schema` still meets the bounded rebuild error
+    instead of a raw ``sqlite3.OperationalError`` from its first query.
     """
 
     def __init__(self, connection: sqlite3.Connection):
         _validate_connection(connection)
+        require_subtitle_schema(connection)
         self.connection = connection
 
     def start_acquisition_run(self, run: AcquisitionRunRecord) -> None:
diff --git a/bilibili-asr-archive/tests/test_transcript_repository.py b/bilibili-asr-archive/tests/test_transcript_repository.py
index 64ce3b4..42b13a4 100644
--- a/bilibili-asr-archive/tests/test_transcript_repository.py
+++ b/bilibili-asr-archive/tests/test_transcript_repository.py
@@ -16,6 +16,7 @@ from bili_asr.storage import (
     MAX_TIMELINE_MS,
     AcquisitionRunRecord,
     MetadataRepository,
+    SchemaContractError,
     TranscriptRecord,
     TranscriptRepository,
     TranscriptSegmentRecord,
@@ -28,6 +29,7 @@ from fixtures.metadata_records import (
     make_video_record,
 )
 from test_metadata_e2e import LEGACY_SIDECAR_PATHS
+from test_storage_schema import _write_pre_iteration_database
 
 
 BODY = ((0, 1_200, "第一句"), (1_200, 2_400, "第二句"))
@@ -1139,6 +1141,32 @@ def test_constructor_requires_the_open_database_connection_state(tmp_root):
         connection.close()
 
 
+def test_constructor_refuses_a_legacy_database_with_the_bounded_error(tmp_root):
+    """The schema guard holds at the boundary, not only in the caller.
+
+    ``require_subtitle_schema`` is the CLI's obligation, but a caller that
+    skips it must not meet a raw ``OperationalError`` from the first query:
+    constructing the repository on a database that predates the transcript
+    contract raises the same bounded rebuild error the guard raises.
+    """
+    database_path = os.path.join(tmp_root, "archive.db")
+    _write_pre_iteration_database(database_path)
+
+    connection = open_database(database_path)
+    try:
+        with pytest.raises(SchemaContractError) as refused:
+            TranscriptRepository(connection)
+        message = str(refused.value)
+        assert "predates the transcript schema" in message
+        assert "delete archive.db and re-run fetch-meta" in message
+
+        # The metadata boundary on that same database is untouched: the guard
+        # belongs to the transcript repository, not to the archive.
+        assert MetadataRepository(connection) is not None
+    finally:
+        connection.close()
+
+
 def test_committed_writes_are_visible_outside_the_writing_connection(tmp_root):
     database_path = os.path.join(tmp_root, "archive.db")
     connection = open_database(database_path)
@@ -1370,6 +1398,24 @@ def test_pending_enumeration_orders_never_attempted_before_the_oldest_attempt(tm
         first_video = _video_with_parts(connection, "BV1A", (3001, 3002, 3003, 3004))
         _video_with_parts(connection, "BV0Z", (4001, 4002))
         _video_with_parts(connection, "BV1GONE", (5001,), processing_status="gone")
+        # Page 5 is stored *before* its page 4 sibling — ``_video_with_parts``
+        # writes one ascending page per position, so this pair goes through the
+        # parts write path directly. Insertion order and page order therefore
+        # disagree inside this bvid, which is what makes the final key
+        # falsifiable on its own: without ``page_index ASC`` this pair comes
+        # back as p5, p4 (rowid order) instead.
+        metadata = MetadataRepository(connection)
+        with metadata.transaction():
+            for page_index, cid in ((5, 3006), (4, 3005)):
+                metadata.upsert_part(
+                    make_part_record(
+                        "BV1A",
+                        page_index=page_index,
+                        cid=cid,
+                        title=f"第{page_index + 1}集",
+                        processing_status="metadata_collected",
+                    )
+                )
         _probe(repository, first_video[2], index=1, finished_at=500)
         _probe(repository, first_video[3], index=2, finished_at=300)
 
@@ -1377,16 +1423,18 @@ def test_pending_enumeration_orders_never_attempted_before_the_oldest_attempt(tm
 
         assert work_ids == [
             "BV0Z:p0",  # never attempted: lowest bvid, then lowest page index,
-            "BV0Z:p1",  # so this block is BV0Z's two pages and then BV1A's two;
+            "BV0Z:p1",  # so this block is BV0Z's two pages and then BV1A's four;
             "BV1A:p0",  # ordering by page_index first would interleave it as
-            "BV1A:p1",  # BV0Z:p0, BV1A:p0, BV0Z:p1, BV1A:p1 instead.
+            "BV1A:p1",  # BV0Z:p0, BV1A:p0, BV0Z:p1, BV1A:p1 instead, and
+            "BV1A:p4",  # dropping page_index ASC would return BV1A:p5 first.
+            "BV1A:p5",
             "BV1A:p3",  # oldest attempt first
             "BV1A:p2",
         ]
         # A part upstream reported as gone is not work: the enumeration is
         # bounded to what can still yield a caption.
         assert "BV1GONE:p0" not in work_ids
-        assert repository.count_pending_subtitle_parts() == len(work_ids) == 6
+        assert repository.count_pending_subtitle_parts() == len(work_ids) == 8
 
         # The bound takes the head of the locked order.
         assert [
@@ -1396,7 +1444,7 @@ def test_pending_enumeration_orders_never_attempted_before_the_oldest_attempt(tm
             row["work_id"] for row in repository.list_pending_subtitle_parts(limit=2)
         ] == ["BV0Z:p0", "BV0Z:p1"]
         assert [
-            row["work_id"] for row in repository.list_pending_subtitle_parts(limit=6)
+            row["work_id"] for row in repository.list_pending_subtitle_parts(limit=8)
         ] == work_ids
     finally:
         connection.close()
```
