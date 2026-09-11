# QC Fix Round 2 Diff — 20260909-structured-metadata-schema

Plan: `20260909-structured-metadata-schema` (SDD)
Range: `6d76ea4068d04d30e3e4f8123454020c901d4461..2063a1a`
Base: `6d76ea4` (round-1 re-reviewed head)
Head: `2063a1a fix(storage): guard failure-path run clock, read-path TypeError split, doc contract`
Working branch: `feature/20260909-structured-metadata-schema`
Scope: targeted re-validation of round-2 dispositions S-fix-6..9 (see review/qc-consolidated.md ## Revalidation round 1)

```diff
diff --git a/bilibili-asr-archive/src/bili_asr/storage/database.py b/bilibili-asr-archive/src/bili_asr/storage/database.py
index 01db8ef..2cd1bf0 100644
--- a/bilibili-asr-archive/src/bili_asr/storage/database.py
+++ b/bilibili-asr-archive/src/bili_asr/storage/database.py
@@ -116,14 +116,24 @@ class MetadataRepository:
       without deleting the run parent.
     - ``finish_run`` commits its own terminal transition.
     - ``record_page`` owns one transaction for its arguments and commits it,
-      or rolls it back and re-raises on a write failure; a no-payload
-      ``'failed'`` page commits its own evidence transaction.
+      or rolls it back and re-raises on a write failure; with no payload
+      arguments it still commits its own single-write transaction — either
+      the ``'failed'`` evidence transaction (page row plus the run's failure
+      transition) or the ok/empty/``risk_interrupted`` page-outcome write.
     - ``upsert_user``, ``upsert_video``, ``upsert_part``, ``record_discovery``
       and ``write_cursor`` execute SQL without committing, so a caller can
       group them in one transaction through :meth:`transaction`.
     - ``read_cursor``, ``list_pending_parts`` and ``run_stats`` never write
       or commit.
 
+    Read paths return two shapes: ``read_cursor`` converts its single row
+    into a typed ``CursorRecord`` (``None`` when absent), while
+    ``list_pending_parts`` and ``run_stats`` return raw ``sqlite3.Row``
+    view data — a list for the no-argument form, a single row or ``None``
+    for the keyed form. Read-path arguments follow the module-wide
+    validation discipline: type errors raise ``TypeError`` and value
+    errors raise ``ValueError``.
+
     Do not compose ``start_run``, ``finish_run`` or ``record_page`` inside a
     :meth:`transaction` group: each commits independently and would commit
     the enclosing group's earlier writes.
@@ -169,7 +179,12 @@ class MetadataRepository:
         )
 
     def upsert_video(self, video: VideoRecord) -> None:
-        """Insert or update a video's current canonical display fields."""
+        """Insert or update a video's current canonical display fields.
+
+        The stored ``aid`` is a stable identifier: the first non-``None``
+        ``aid`` wins — a stored ``NULL`` is backfilled from the incoming
+        record, and a known ``aid`` is never overwritten.
+        """
         if not isinstance(video, VideoRecord):
             raise TypeError("video must be a VideoRecord")
         self.connection.execute(
@@ -356,7 +371,15 @@ class MetadataRepository:
         own committed transaction together with the parent run's failure
         transition. When that run is already terminal, the page evidence is
         still persisted while the run's outcome and ``finished_at`` stay
-        unchanged.
+        unchanged. A no-payload page with a non-failed outcome (``ok``,
+        ``empty``, ``risk_interrupted``) likewise commits its own
+        single-write transaction for the page-outcome row.
+
+        The failure transition applies only while the run is still
+        ``running`` and uses the run's stored ``started_at`` as its ordering
+        baseline — the same DB baseline as :meth:`finish_run`: a failed page
+        whose ``finished_at`` precedes the run's stored ``started_at`` is
+        rejected with ``ValueError`` and nothing is persisted.
         """
         if not isinstance(page, IngestionPageRecord):
             raise TypeError("page must be an IngestionPageRecord")
@@ -397,12 +420,25 @@ class MetadataRepository:
     def _record_failed_page(self, page: IngestionPageRecord) -> None:
         """Persist only bounded failure state after a rolled-back page.
 
-        The page evidence is always upserted; the parent run's failure
-        transition applies only while the run is still ``'running'``, so a
-        late or stale failed page can never regress a terminal outcome or
-        move ``finished_at`` backwards.
+        The page evidence is upserted in the same committed transaction as
+        the parent run's failure transition, which applies only while the
+        run is still ``'running'`` — a late or stale failed page can never
+        regress a terminal outcome or move ``finished_at`` backwards. The
+        transition validates against the run's stored ``started_at`` (the
+        same DB baseline as :meth:`finish_run`): a page clock below the
+        run's start raises ``ValueError`` and nothing is persisted.
         """
         with self.transaction():
+            run_row = self.connection.execute(
+                "SELECT started_at, outcome FROM ingestion_runs WHERE run_id = ?",
+                (page.run_id,),
+            ).fetchone()
+            if (
+                run_row is not None
+                and run_row["outcome"] == "running"
+                and page.finished_at < int(run_row["started_at"])
+            ):
+                raise ValueError("finished_at must not precede started_at")
             self._record_page(page)
             self.connection.execute(
                 """
@@ -436,8 +472,14 @@ class MetadataRepository:
         )
 
     def read_cursor(self, mid: int) -> CursorRecord | None:
-        """Read the current one-based cursor for a user."""
-        if isinstance(mid, bool) or not isinstance(mid, int) or mid < 1:
+        """Read the current one-based cursor for a user.
+
+        Returns a typed ``CursorRecord`` or ``None`` when the user has no
+        cursor row.
+        """
+        if isinstance(mid, bool) or not isinstance(mid, int):
+            raise TypeError("mid must be an integer")
+        if mid < 1:
             raise ValueError("mid must be a positive integer")
         row = self.connection.execute(
             """
@@ -489,10 +531,15 @@ class MetadataRepository:
         )
 
     def list_pending_parts(self, limit: int | None = None) -> list[sqlite3.Row]:
-        """Return discovered parts in deterministic work order."""
+        """Return discovered parts in deterministic work order.
+
+        Rows come straight from the ``v_pending_metadata`` view.
+        """
         if limit is not None:
-            if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
-                raise ValueError("limit must be a positive integer or None")
+            if isinstance(limit, bool) or not isinstance(limit, int):
+                raise TypeError("limit must be an integer or None")
+            if limit < 1:
+                raise ValueError("limit must be a positive integer")
             query = (
                 "SELECT * FROM v_pending_metadata "
                 "ORDER BY bvid, page_index LIMIT ?"
@@ -505,15 +552,21 @@ class MetadataRepository:
         )
 
     def run_stats(self, run_id: str | None = None) -> sqlite3.Row | list[sqlite3.Row] | None:
-        """Read normalized run/page/video counts from the repository view."""
+        """Read normalized run/page/video counts from the repository view.
+
+        Returns one ``v_ingestion_run_stats`` row for a ``run_id``, or a
+        list of every run's rows when ``run_id`` is ``None``.
+        """
         if run_id is None:
             return list(
                 self.connection.execute(
                     "SELECT * FROM v_ingestion_run_stats ORDER BY run_id"
                 ).fetchall()
             )
-        if not isinstance(run_id, str) or not run_id.strip():
-            raise ValueError("run_id must be a non-empty string or None")
+        if not isinstance(run_id, str):
+            raise TypeError("run_id must be a string or None")
+        if not run_id.strip():
+            raise ValueError("run_id must be a non-empty string")
         return self.connection.execute(
             "SELECT * FROM v_ingestion_run_stats WHERE run_id = ?", (run_id,)
         ).fetchone()
diff --git a/bilibili-asr-archive/tests/test_metadata_repository.py b/bilibili-asr-archive/tests/test_metadata_repository.py
index 14dd30c..d864ba3 100644
--- a/bilibili-asr-archive/tests/test_metadata_repository.py
+++ b/bilibili-asr-archive/tests/test_metadata_repository.py
@@ -159,6 +159,12 @@ def test_ok_page_write_failure_rolls_back_and_caller_records_failure(tmp_root):
             )
 
         assert repository.read_cursor(MID) == make_cursor_record()
+        # The transaction head rolled back: the user label from page 1
+        # survives, and the failing call's user write is absent.
+        assert (
+            connection.execute("SELECT display_name FROM bilibili_users").fetchone()[0]
+            == "未明子"
+        )
         assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 1
         assert connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0] == 1
         assert connection.execute("SELECT COUNT(*) FROM ingestion_pages").fetchone()[0] == 1
@@ -261,6 +267,37 @@ def test_late_failed_page_after_terminal_run_keeps_run_outcome_unchanged(tmp_roo
         connection.close()
 
 
+def test_failed_page_clock_before_running_run_start_is_rejected_and_nothing_persisted(tmp_root):
+    connection = open_database(tmp_root)
+    repository = MetadataRepository(connection)
+    try:
+        _start_run(repository)
+
+        # The run's stored started_at (101) is the failure transition's
+        # ordering baseline, exactly as it is for finish_run: a valid page
+        # record whose clock lies below it is rejected and nothing persists.
+        stale_failure = make_page_record(
+            page_number=1,
+            outcome="failed",
+            error_code="stale_page_result",
+            started_at=50,
+            finished_at=51,
+        )
+        with pytest.raises(ValueError):
+            repository.record_page(stale_failure)
+
+        assert connection.execute(
+            "SELECT COUNT(*) FROM ingestion_pages WHERE run_id = 'run-1'"
+        ).fetchone()[0] == 0
+        assert tuple(
+            connection.execute(
+                "SELECT outcome, finished_at FROM ingestion_runs WHERE run_id = 'run-1'"
+            ).fetchone()
+        ) == ("running", None)
+    finally:
+        connection.close()
+
+
 def test_finish_run_rejects_refinishing_a_terminal_run(tmp_root):
     connection = open_database(tmp_root)
     repository = MetadataRepository(connection)
@@ -556,6 +593,32 @@ def test_finish_run_and_all_run_stats_are_derived_from_normalized_rows(tmp_root)
         connection.close()
 
 
+def test_read_path_validation_splits_type_errors_from_value_errors(tmp_root):
+    connection = open_database(tmp_root)
+    repository = MetadataRepository(connection)
+    try:
+        with pytest.raises(TypeError):
+            repository.read_cursor(True)
+        with pytest.raises(TypeError):
+            repository.read_cursor("23191782")
+        with pytest.raises(ValueError):
+            repository.read_cursor(0)
+
+        with pytest.raises(TypeError):
+            repository.run_stats(23191782)
+        with pytest.raises(ValueError):
+            repository.run_stats("   ")
+
+        with pytest.raises(TypeError):
+            repository.list_pending_parts(limit="1")
+        with pytest.raises(TypeError):
+            repository.list_pending_parts(limit=True)
+        with pytest.raises(ValueError):
+            repository.list_pending_parts(limit=0)
+    finally:
+        connection.close()
+
+
 def test_start_run_requires_a_foreign_key_parent(tmp_root):
     connection = open_database(tmp_root)
     repository = MetadataRepository(connection)
```
