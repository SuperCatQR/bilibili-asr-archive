# Task 3 Diff

Base: `bf602b8620e8dc4cc630ababf17bfb10e0ade1b0`
Head: `ff81140`

```diff
diff --git a/bilibili-asr-archive/tests/fixtures/__init__.py b/bilibili-asr-archive/tests/fixtures/__init__.py
new file mode 100644
index 0000000..3a35c77
--- /dev/null
+++ b/bilibili-asr-archive/tests/fixtures/__init__.py
@@ -0,0 +1 @@
+"""Deterministic record factories for the offline metadata contract tests."""
diff --git a/bilibili-asr-archive/tests/fixtures/metadata_records.py b/bilibili-asr-archive/tests/fixtures/metadata_records.py
new file mode 100644
index 0000000..a37584c
--- /dev/null
+++ b/bilibili-asr-archive/tests/fixtures/metadata_records.py
@@ -0,0 +1,166 @@
+"""Deterministic record factories for the offline metadata contract tests.
+
+Every builder returns a validated internal record with fixed literal field
+values, so repeated runs observe identical rows.  Keyword arguments override
+single fields; no wall-clock time, randomness, network data, third-party
+response objects, or credentials are involved.
+"""
+
+from __future__ import annotations
+
+from bili_asr.storage.models import (
+    CursorRecord,
+    CursorState,
+    DiscoveryRecord,
+    IngestionPageRecord,
+    IngestionRunRecord,
+    PageOutcome,
+    ProcessingStatus,
+    UserRecord,
+    VideoPartRecord,
+    VideoRecord,
+)
+
+
+MID = 23191782
+
+
+def make_user_record(
+    *, display_name: str = "未明子", updated_at: int = 100
+) -> UserRecord:
+    """Build the archive owner's current user record."""
+    return UserRecord(
+        mid=MID,
+        display_name=display_name,
+        created_at=100,
+        updated_at=updated_at,
+    )
+
+
+def make_run_record(
+    run_id: str = "run-1",
+    *,
+    requested_start_page: int = 1,
+    requested_page_limit: int | None = 3,
+    started_at: int = 101,
+) -> IngestionRunRecord:
+    """Build one metadata collection run opened against the archive owner."""
+    return IngestionRunRecord(
+        run_id=run_id,
+        mid=MID,
+        source_package="bilibili-api-python",
+        source_version="17.4.2",
+        requested_start_page=requested_start_page,
+        requested_page_limit=requested_page_limit,
+        started_at=started_at,
+    )
+
+
+def make_video_record(
+    bvid: str = "BV1SINGLE",
+    *,
+    title: str = "单集视频",
+    aid: int | None = 1001,
+    updated_at: int = 102,
+) -> VideoRecord:
+    """Build a video owned by the archive owner."""
+    return VideoRecord(
+        bvid=bvid,
+        aid=aid,
+        mid=MID,
+        title=title,
+        pubdate=1_700_000_000,
+        created_at=102,
+        updated_at=updated_at,
+    )
+
+
+def make_part_record(
+    bvid: str = "BV1SINGLE",
+    *,
+    page_index: int = 0,
+    cid: int = 2001,
+    title: str = "第一集",
+    status: ProcessingStatus = "discovered",
+    updated_at: int = 103,
+) -> VideoPartRecord:
+    """Build one normalized part of a video."""
+    return VideoPartRecord(
+        bvid=bvid,
+        page_index=page_index,
+        cid=cid,
+        title=title,
+        duration_ms=1_234,
+        processing_status=status,
+        created_at=103,
+        updated_at=updated_at,
+    )
+
+
+def make_page_record(
+    run_id: str = "run-1",
+    *,
+    page_number: int = 1,
+    outcome: PageOutcome = "ok",
+    error_code: str | None = None,
+    started_at: int = 110,
+    finished_at: int = 111,
+) -> IngestionPageRecord:
+    """Build one page-outcome record for a run."""
+    return IngestionPageRecord(
+        run_id=run_id,
+        page_number=page_number,
+        outcome=outcome,
+        error_code=error_code,
+        started_at=started_at,
+        finished_at=finished_at,
+    )
+
+
+def make_cursor_record(
+    *,
+    next_page: int = 2,
+    observed_total: int | None = 2,
+    state: CursorState = "ready",
+    last_error_code: str | None = None,
+    updated_at: int = 112,
+) -> CursorRecord:
+    """Build the resumable cursor state for the archive owner."""
+    return CursorRecord(
+        mid=MID,
+        next_page=next_page,
+        observed_total=observed_total,
+        state=state,
+        last_error_code=last_error_code,
+        updated_at=updated_at,
+    )
+
+
+def make_discovery_record(
+    bvid: str,
+    *,
+    run_id: str = "run-1",
+    page_number: int = 1,
+    source_position: int | None = 0,
+    discovered_at: int = 104,
+) -> DiscoveryRecord:
+    """Build one run/page/video discovery relationship."""
+    return DiscoveryRecord(
+        run_id=run_id,
+        page_number=page_number,
+        bvid=bvid,
+        source_position=source_position,
+        discovered_at=discovered_at,
+    )
+
+
+__all__ = [
+    "MID",
+    "make_cursor_record",
+    "make_discovery_record",
+    "make_page_record",
+    "make_run_record",
+    "make_part_record",
+    "make_user_record",
+    "make_video_record",
+]
diff --git a/bilibili-asr-archive/tests/test_metadata_repository.py b/bilibili-asr-archive/tests/test_metadata_repository.py
index 6fdfda2..7dda1c9 100644
--- a/bilibili-asr-archive/tests/test_metadata_repository.py
+++ b/bilibili-asr-archive/tests/test_metadata_repository.py
@@ -3,143 +3,41 @@
 from __future__ import annotations
 
 from dataclasses import fields
+import re
 import sqlite3
 
 import pytest
 
 from bili_asr.storage.database import MetadataRepository, open_database
-from bili_asr.storage.models import (
-    CursorRecord,
-    DiscoveryRecord,
-    IngestionPageRecord,
-    IngestionRunRecord,
-    UserRecord,
-    VideoPartRecord,
-    VideoRecord,
+from bili_asr.storage.models import UserRecord, VideoPartRecord
+from fixtures.metadata_records import (
+    MID,
+    make_cursor_record,
+    make_discovery_record,
+    make_page_record,
+    make_run_record,
+    make_part_record,
+    make_user_record,
+    make_video_record,
 )
 
 
-MID = 23191782
-
-
-def _user(*, display_name: str = "未明子", updated_at: int = 100) -> UserRecord:
-    return UserRecord(mid=MID, display_name=display_name, created_at=100, updated_at=updated_at)
-
-
-def _run(run_id: str = "run-1") -> IngestionRunRecord:
-    return IngestionRunRecord(
-        run_id=run_id,
-        mid=MID,
-        source_package="bilibili-api-python",
-        source_version="17.4.2",
-        requested_start_page=1,
-        requested_page_limit=3,
-        started_at=101,
-    )
-
-
-def _video(
-    bvid: str = "BV1SINGLE",
-    *,
-    title: str = "单集视频",
-    aid: int | None = 1001,
-    updated_at: int = 102,
-) -> VideoRecord:
-    return VideoRecord(
-        bvid=bvid,
-        aid=aid,
-        mid=MID,
-        title=title,
-        pubdate=1_700_000_000,
-        created_at=102,
-        updated_at=updated_at,
-    )
-
-
-def _part(
-    bvid: str = "BV1SINGLE",
-    *,
-    page_index: int = 0,
-    cid: int = 2001,
-    title: str = "第一集",
-    status: str = "discovered",
-    updated_at: int = 103,
-) -> VideoPartRecord:
-    return VideoPartRecord(
-        bvid=bvid,
-        page_index=page_index,
-        cid=cid,
-        title=title,
-        duration_ms=1_234,
-        processing_status=status,
-        created_at=103,
-        updated_at=updated_at,
-    )
-
-
-def _page(
-    run_id: str = "run-1",
-    *,
-    page_number: int = 1,
-    outcome: str = "ok",
-    error_code: str | None = None,
-    started_at: int = 110,
-    finished_at: int = 111,
-) -> IngestionPageRecord:
-    return IngestionPageRecord(
-        run_id=run_id,
-        page_number=page_number,
-        outcome=outcome,
-        error_code=error_code,
-        started_at=started_at,
-        finished_at=finished_at,
-    )
-
-
-def _cursor(*, next_page: int = 2, updated_at: int = 112) -> CursorRecord:
-    return CursorRecord(
-        mid=MID,
-        next_page=next_page,
-        observed_total=2,
-        state="ready",
-        last_error_code=None,
-        updated_at=updated_at,
-    )
-
-
-def _discovery(
-    bvid: str,
-    *,
-    run_id: str = "run-1",
-    page_number: int = 1,
-    source_position: int = 0,
-    discovered_at: int = 104,
-) -> DiscoveryRecord:
-    return DiscoveryRecord(
-        run_id=run_id,
-        page_number=page_number,
-        bvid=bvid,
-        source_position=source_position,
-        discovered_at=discovered_at,
-    )
-
-
 def _start_run(repository: MetadataRepository, run_id: str = "run-1") -> None:
-    repository.upsert_user(_user())
-    repository.start_run(_run(run_id))
+    repository.upsert_user(make_user_record())
+    repository.start_run(make_run_record(run_id))
 
 
 def test_models_validate_scalars_and_compute_work_id_without_persisting_it():
-    part = _part()
+    part = make_part_record()
     assert part.work_id == "BV1SINGLE:p0"
     assert "work_id" not in {field.name for field in fields(VideoPartRecord)}
 
     with pytest.raises(ValueError):
-        _part(page_index=-1)
+        make_part_record(page_index=-1)
     with pytest.raises(ValueError):
-        _part(cid=0)
+        make_part_record(cid=0)
     with pytest.raises(ValueError):
-        _page(outcome="failed", error_code="raw traceback\n")
+        make_page_record(outcome="failed", error_code="raw traceback\n")
     with pytest.raises(ValueError):
         UserRecord(mid=MID, display_name="", created_at=1, updated_at=1)
 
@@ -149,29 +47,29 @@ def test_record_page_persists_single_and_multipart_entities_in_locked_order(tmp_
     repository = MetadataRepository(connection)
     try:
         _start_run(repository)
-        multipart = _video("BV1MULTI", title="多集视频", aid=1002)
-        page = _page()
+        multipart = make_video_record("BV1MULTI", title="多集视频", aid=1002)
+        page = make_page_record()
         repository.record_page(
             page,
-            user=_user(),
-            videos=[_video(), multipart],
+            user=make_user_record(),
+            videos=[make_video_record(), multipart],
             parts=[
-                _part(),
-                _part("BV1MULTI", page_index=0, cid=3001, title="上篇"),
-                _part("BV1MULTI", page_index=1, cid=3002, title="下篇"),
+                make_part_record(),
+                make_part_record("BV1MULTI", page_index=0, cid=3001, title="上篇"),
+                make_part_record("BV1MULTI", page_index=1, cid=3002, title="下篇"),
             ],
             discoveries=[
-                _discovery("BV1SINGLE"),
-                _discovery("BV1MULTI", source_position=1),
+                make_discovery_record("BV1SINGLE"),
+                make_discovery_record("BV1MULTI", source_position=1),
             ],
-            cursor=_cursor(),
+            cursor=make_cursor_record(),
         )
 
         assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 2
         assert connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0] == 3
         assert connection.execute("SELECT COUNT(*) FROM ingestion_discoveries").fetchone()[0] == 2
         assert connection.execute("SELECT COUNT(*) FROM ingestion_pages").fetchone()[0] == 1
-        assert repository.read_cursor(MID) == _cursor()
+        assert repository.read_cursor(MID) == make_cursor_record()
 
         pending = repository.list_pending_parts()
         assert [row["work_id"] for row in pending] == [
@@ -193,21 +91,21 @@ def test_repeated_page_is_idempotent_but_a_new_run_keeps_page_evidence(tmp_root)
     try:
         _start_run(repository)
         repository.record_page(
-            _page(),
-            user=_user(),
-            video=_video(),
-            parts=[_part()],
-            discoveries=[_discovery("BV1SINGLE")],
-            cursor=_cursor(),
+            make_page_record(),
+            user=make_user_record(),
+            video=make_video_record(),
+            parts=[make_part_record()],
+            discoveries=[make_discovery_record("BV1SINGLE")],
+            cursor=make_cursor_record(),
         )
 
         repository.record_page(
-            _page(finished_at=120),
-            user=_user(display_name="未明子（更新）", updated_at=119),
-            video=_video(title="更新后的标题", updated_at=119),
-            parts=[_part(title="更新后的分集标题", updated_at=119)],
-            discoveries=[_discovery("BV1SINGLE", discovered_at=119)],
-            cursor=_cursor(updated_at=120),
+            make_page_record(finished_at=120),
+            user=make_user_record(display_name="未明子（更新）", updated_at=119),
+            video=make_video_record(title="更新后的标题", updated_at=119),
+            parts=[make_part_record(title="更新后的分集标题", updated_at=119)],
+            discoveries=[make_discovery_record("BV1SINGLE", discovered_at=119)],
+            cursor=make_cursor_record(updated_at=120),
         )
         assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 1
         assert connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0] == 1
@@ -218,11 +116,11 @@ def test_repeated_page_is_idempotent_but_a_new_run_keeps_page_evidence(tmp_root)
 
         _start_run(repository, "run-2")
         repository.record_page(
-            _page("run-2"),
-            video=_video(title="同一视频的第二次发现"),
-            parts=[_part()],
-            discoveries=[_discovery("BV1SINGLE", run_id="run-2")],
-            cursor=_cursor(updated_at=130),
+            make_page_record("run-2"),
+            video=make_video_record(title="同一视频的第二次发现"),
+            parts=[make_part_record()],
+            discoveries=[make_discovery_record("BV1SINGLE", run_id="run-2")],
+            cursor=make_cursor_record(updated_at=130),
         )
         assert connection.execute("SELECT COUNT(*) FROM ingestion_pages").fetchone()[0] == 2
         assert connection.execute("SELECT COUNT(*) FROM ingestion_discoveries").fetchone()[0] == 2
@@ -239,13 +137,13 @@ def test_failed_page_rolls_back_payload_preserves_cursor_and_records_bounded_out
     try:
         _start_run(repository)
         repository.record_page(
-            _page(),
-            video=_video(),
-            parts=[_part()],
-            discoveries=[_discovery("BV1SINGLE")],
-            cursor=_cursor(),
+            make_page_record(),
+            video=make_video_record(),
+            parts=[make_part_record()],
+            discoveries=[make_discovery_record("BV1SINGLE")],
+            cursor=make_cursor_record(),
         )
-        failed_page = _page(
+        failed_page = make_page_record(
             page_number=2,
             outcome="failed",
             error_code="foreign_key",
@@ -255,13 +153,13 @@ def test_failed_page_rolls_back_payload_preserves_cursor_and_records_bounded_out
         with pytest.raises(sqlite3.IntegrityError):
             repository.record_page(
                 failed_page,
-                user=_user(display_name="must roll back", updated_at=200),
-                video=_video(title="must roll back", updated_at=200),
-                parts=[_part("BV-MISSING", title="orphan")],
-                cursor=_cursor(next_page=3, updated_at=201),
+                user=make_user_record(display_name="must roll back", updated_at=200),
+                video=make_video_record(title="must roll back", updated_at=200),
+                parts=[make_part_record("BV-MISSING", title="orphan")],
+                cursor=make_cursor_record(next_page=3, updated_at=201),
             )
 
-        assert repository.read_cursor(MID) == _cursor()
+        assert repository.read_cursor(MID) == make_cursor_record()
         assert connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0] == 1
         assert connection.execute("SELECT display_name FROM bilibili_users").fetchone()[0] == "未明子"
         page_row = connection.execute(
@@ -286,12 +184,18 @@ def test_fk_rejection_and_delete_restriction_apply_to_repository_writes(tmp_root
     try:
         with pytest.raises(sqlite3.IntegrityError):
             with repository.transaction():
-                repository.upsert_video(_video("BV-ORPHAN"))
+                repository.upsert_video(make_video_record("BV-ORPHAN"))
+        with pytest.raises(sqlite3.IntegrityError):
+            with repository.transaction():
+                repository.upsert_part(make_part_record("BV-MISSING"))
+        with pytest.raises(sqlite3.IntegrityError):
+            with repository.transaction():
+                repository.write_cursor(make_cursor_record())
 
         with repository.transaction():
-            repository.upsert_user(_user())
-            repository.upsert_video(_video())
-            repository.upsert_part(_part())
+            repository.upsert_user(make_user_record())
+            repository.upsert_video(make_video_record())
+            repository.upsert_part(make_part_record())
 
         with pytest.raises(sqlite3.IntegrityError):
             connection.execute("DELETE FROM bilibili_users WHERE mid = ?", (MID,))
@@ -301,24 +205,204 @@ def test_fk_rejection_and_delete_restriction_apply_to_repository_writes(tmp_root
         connection.close()
 
 
+def test_repository_end_to_end_records_two_runs_with_cursor_transitions(tmp_root):
+    """Full page flow: user, single-part video, multipart video, two runs."""
+    connection = open_database(tmp_root)
+    repository = MetadataRepository(connection)
+    try:
+        assert repository.read_cursor(MID) is None
+
+        _start_run(repository)
+
+        # Page 1 applies the locked order in one transaction:
+        # user -> video -> parts -> discoveries -> cursor -> page outcome.
+        repository.record_page(
+            make_page_record(),
+            user=make_user_record(),
+            video=make_video_record(),
+            parts=[make_part_record()],
+            discoveries=[make_discovery_record("BV1SINGLE")],
+            cursor=make_cursor_record(),
+        )
+        assert repository.read_cursor(MID) == make_cursor_record()
+
+        repository.start_run(
+            make_run_record("run-2", requested_start_page=2, started_at=200)
+        )
+        repository.record_page(
+            make_page_record(
+                "run-2", page_number=2, started_at=201, finished_at=202
+            ),
+            videos=[
+                make_video_record("BV1MULTI", title="多集视频", aid=1002, updated_at=203)
+            ],
+            parts=[
+                make_part_record(
+                    "BV1MULTI", page_index=0, cid=3001, title="上篇", updated_at=204
+                ),
+                make_part_record(
+                    "BV1MULTI", page_index=1, cid=3002, title="下篇", updated_at=204
+                ),
+            ],
+            discoveries=[
+                make_discovery_record(
+                    "BV1MULTI", run_id="run-2", page_number=2, discovered_at=205
+                )
+            ],
+            cursor=make_cursor_record(next_page=3, updated_at=206),
+        )
+
+        # Page 3 is empty: no payload rows, only the cursor state transition.
+        repository.record_page(
+            make_page_record(
+                "run-2",
+                page_number=3,
+                outcome="empty",
+                started_at=210,
+                finished_at=211,
+            ),
+            cursor=make_cursor_record(
+                next_page=3, state="complete", updated_at=211
+            ),
+        )
+
+        repository.finish_run("run-1", "complete", 300)
+        repository.finish_run("run-2", "complete", 301)
+
+        assert connection.execute("SELECT COUNT(*) FROM bilibili_users").fetchone()[0] == 1
+        assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 2
+        assert connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0] == 3
+        page_rows = connection.execute(
+            "SELECT run_id, page_number, outcome, error_code FROM ingestion_pages "
+            "ORDER BY run_id, page_number"
+        ).fetchall()
+        assert [tuple(row) for row in page_rows] == [
+            ("run-1", 1, "ok", None),
+            ("run-2", 2, "ok", None),
+            ("run-2", 3, "empty", None),
+        ]
+        assert repository.read_cursor(MID) == make_cursor_record(
+            next_page=3, state="complete", updated_at=211
+        )
+
+        pending = repository.list_pending_parts()
+        assert [row["work_id"] for row in pending] == [
+            "BV1MULTI:p0",
+            "BV1MULTI:p1",
+            "BV1SINGLE:p0",
+        ]
+
+        stats = repository.run_stats()
+        assert [row["run_id"] for row in stats] == ["run-1", "run-2"]
+        assert (stats[0]["page_count"], stats[0]["video_count"]) == (1, 1)
+        assert (stats[1]["page_count"], stats[1]["video_count"]) == (2, 1)
+        assert all(row["outcome"] == "complete" for row in stats)
+
+        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
+    finally:
+        connection.close()
+
+
+def test_error_fields_persist_only_bounded_scalar_codes(tmp_root):
+    """The repository accepts bounded scalar codes and never secret material."""
+    connection = open_database(tmp_root)
+    repository = MetadataRepository(connection)
+    try:
+        repository.upsert_user(make_user_record())
+        repository.start_run(make_run_record())
+        repository.write_cursor(
+            make_cursor_record(state="limited", last_error_code="rate_limited")
+        )
+        repository.record_page(
+            make_page_record(
+                page_number=2,
+                outcome="failed",
+                error_code="http_412",
+                started_at=120,
+                finished_at=121,
+            )
+        )
+        assert repository.read_cursor(MID).last_error_code == "rate_limited"
+        stored_page = connection.execute(
+            "SELECT outcome, error_code FROM ingestion_pages "
+            "WHERE run_id = 'run-1' AND page_number = 2"
+        ).fetchone()
+        assert tuple(stored_page) == ("failed", "http_412")
+
+        forbidden_codes = [
+            "SESSDATA=abc123; bili_jct=def456",  # cookie material
+            "https://upos.example.com/signed-url?token",  # signed URL
+            '{"code": -403, "message": "raw"}',  # raw JSON document
+            "Traceback (most recent call last):",  # exception text
+            "e" * 65,  # exceeds the 64-character bound
+        ]
+        for code in forbidden_codes:
+            with pytest.raises(ValueError):
+                make_cursor_record(state="limited", last_error_code=code)
+            with pytest.raises(ValueError):
+                make_page_record(outcome="failed", error_code=code)
+
+        expected_codes = {
+            ("ingestion_cursors", "last_error_code"): "rate_limited",
+            ("ingestion_pages", "error_code"): "http_412",
+        }
+        for table, column in (
+            ("ingestion_cursors", "last_error_code"),
+            ("ingestion_pages", "error_code"),
+        ):
+            for marker in ("SESSDATA", "bili_jct", "https", "{", "Traceback", " "):
+                assert connection.execute(
+                    f"SELECT COUNT(*) FROM {table} WHERE {column} LIKE ?",
+                    (f"%{marker}%",),
+                ).fetchone()[0] == 0
+            values = connection.execute(
+                f"SELECT {column} FROM {table} WHERE {column} IS NOT NULL"
+            ).fetchall()
+            assert [row[0] for row in values] == [expected_codes[(table, column)]]
+            for (value,) in values:
+                assert len(value) <= 64
+                assert re.fullmatch(r"[A-Za-z0-9_.:-]+", value)
+    finally:
+        connection.close()
+
+
+def test_re_upsert_backfills_missing_aid_and_keeps_existing_aid(tmp_root):
+    connection = open_database(tmp_root)
+    repository = MetadataRepository(connection)
+    try:
+        repository.upsert_user(make_user_record())
+        repository.upsert_video(make_video_record(aid=None))
+        assert connection.execute("SELECT aid FROM videos").fetchone()[0] is None
+
+        repository.upsert_video(make_video_record())
+        assert connection.execute("SELECT aid FROM videos").fetchone()[0] == 1001
+
+        repository.upsert_video(make_video_record(aid=9999))
+        assert connection.execute("SELECT aid FROM videos").fetchone()[0] == 1001
+    finally:
+        connection.close()
+
+
 def test_cursor_resume_and_pending_limit(tmp_root):
     connection = open_database(tmp_root)
     repository = MetadataRepository(connection)
     try:
         _start_run(repository)
         repository.record_page(
-            _page(),
-            video=_video(),
-            parts=[_part(), _part(page_index=1, cid=2002, title="第二集")],
-            discoveries=[_discovery("BV1SINGLE")],
-            cursor=_cursor(next_page=2),
+            make_page_record(),
+            video=make_video_record(),
+            parts=[make_part_record(), make_part_record(page_index=1, cid=2002, title="第二集")],
+            discoveries=[make_discovery_record("BV1SINGLE")],
+            cursor=make_cursor_record(next_page=2),
         )
-        repository.write_cursor(_cursor(next_page=3, updated_at=130))
+        repository.write_cursor(make_cursor_record(next_page=3, updated_at=130))
         assert repository.read_cursor(MID).next_page == 3
         assert [row["page_index"] for row in repository.list_pending_parts(limit=1)] == [0]
 
         with repository.transaction():
-            repository.upsert_part(_part(page_index=1, cid=2002, title="第二集", status="metadata_collected"))
+            repository.upsert_part(
+                make_part_record(page_index=1, cid=2002, title="第二集", status="metadata_collected")
+            )
         assert [row["page_index"] for row in repository.list_pending_parts()] == [0]
     finally:
         connection.close()
@@ -330,10 +414,10 @@ def test_finish_run_and_all_run_stats_are_derived_from_normalized_rows(tmp_root)
     try:
         _start_run(repository)
         repository.record_page(
-            _page(),
-            video=_video(),
-            parts=[_part()],
-            discoveries=[_discovery("BV1SINGLE")],
+            make_page_record(),
+            video=make_video_record(),
+            parts=[make_part_record()],
+            discoveries=[make_discovery_record("BV1SINGLE")],
         )
         repository.finish_run("run-1", "complete", 300)
         stats = repository.run_stats()
@@ -350,7 +434,6 @@ def test_start_run_requires_a_foreign_key_parent(tmp_root):
     repository = MetadataRepository(connection)
     try:
         with pytest.raises(sqlite3.IntegrityError):
-            repository.start_run(_run())
+            repository.start_run(make_run_record())
     finally:
         connection.close()
-
diff --git a/bilibili-asr-archive/tests/test_storage_schema.py b/bilibili-asr-archive/tests/test_storage_schema.py
index f372ec8..c91ac86 100644
--- a/bilibili-asr-archive/tests/test_storage_schema.py
+++ b/bilibili-asr-archive/tests/test_storage_schema.py
@@ -28,6 +28,138 @@ BASE_TABLES = {
     "transcript_segments",
 }
 VIEWS = {"v_video_parts", "v_ingestion_run_stats", "v_pending_metadata"}
+EXPECTED_TABLE_COLUMNS = {
+    "bilibili_users": ["mid", "display_name", "created_at", "updated_at"],
+    "videos": [
+        "bvid",
+        "aid",
+        "mid",
+        "title",
+        "pubdate",
+        "created_at",
+        "updated_at",
+    ],
+    "video_parts": [
+        "video_part_id",
+        "bvid",
+        "page_index",
+        "cid",
+        "title",
+        "duration_ms",
+        "processing_status",
+        "created_at",
+        "updated_at",
+    ],
+    "ingestion_runs": [
+        "run_id",
+        "mid",
+        "source_package",
+        "source_version",
+        "requested_start_page",
+        "requested_page_limit",
+        "started_at",
+        "finished_at",
+        "outcome",
+    ],
+    "ingestion_cursors": [
+        "mid",
+        "next_page",
+        "observed_total",
+        "state",
+        "last_error_code",
+        "updated_at",
+    ],
+    "ingestion_pages": [
+        "run_id",
+        "page_number",
+        "outcome",
+        "error_code",
+        "started_at",
+        "finished_at",
+    ],
+    "ingestion_discoveries": [
+        "run_id",
+        "page_number",
+        "bvid",
+        "source_position",
+        "discovered_at",
+    ],
+    "audio_objects": [
+        "audio_id",
+        "sha256",
+        "byte_size",
+        "format",
+        "duration_ms",
+        "storage_key",
+        "created_at",
+    ],
+    "part_audio_objects": [
+        "video_part_id",
+        "audio_id",
+        "acquired_at",
+        "acquisition_source",
+    ],
+    "asr_models": ["model_id", "model_name", "revision", "created_at"],
+    "transcripts": [
+        "transcript_id",
+        "video_part_id",
+        "source_kind",
+        "model_id",
+        "version",
+        "created_at",
+    ],
+    "transcript_segments": ["transcript_id", "ordinal", "start_ms", "end_ms", "text"],
+}
+EXPECTED_FOREIGN_KEYS = {
+    "videos": (("mid", "bilibili_users", "mid"),),
+    "video_parts": (("bvid", "videos", "bvid"),),
+    "ingestion_runs": (("mid", "bilibili_users", "mid"),),
+    "ingestion_cursors": (("mid", "bilibili_users", "mid"),),
+    "ingestion_pages": (("run_id", "ingestion_runs", "run_id"),),
+    "ingestion_discoveries": (
+        ("run_id", "ingestion_runs", "run_id"),
+        ("bvid", "videos", "bvid"),
+    ),
+    "part_audio_objects": (
+        ("video_part_id", "video_parts", "video_part_id"),
+        ("audio_id", "audio_objects", "audio_id"),
+    ),
+    "transcripts": (
+        ("video_part_id", "video_parts", "video_part_id"),
+        ("model_id", "asr_models", "model_id"),
+    ),
+    "transcript_segments": (("transcript_id", "transcripts", "transcript_id"),),
+}
+EXPECTED_UNIQUE_CONSTRAINTS = {
+    "videos": (("aid",),),
+    "video_parts": (("bvid", "page_index"),),
+    "audio_objects": (("sha256",), ("storage_key",)),
+    "asr_models": (("model_name", "revision"),),
+    "transcripts": (("video_part_id", "source_kind", "version"),),
+}
+EXPECTED_PRIMARY_KEY_INDEXES = {
+    "videos": (("bvid",),),
+    "ingestion_runs": (("run_id",),),
+    "ingestion_pages": (("run_id", "page_number"),),
+    "ingestion_discoveries": (("run_id", "page_number", "bvid"),),
+    "part_audio_objects": (("video_part_id", "audio_id"),),
+    "transcript_segments": (("transcript_id", "ordinal"),),
+}
+EXPECTED_CHECK_ENUMERATIONS = {
+    "video_parts": (
+        "processing_status IN ('discovered', 'metadata_collected', 'gone')",
+    ),
+    "ingestion_runs": (
+        "source_package = 'bilibili-api-python'",
+        "outcome IN ('running', 'complete', 'limited', 'risk_interrupted', 'failed')",
+    ),
+    "ingestion_cursors": (
+        "state IN ('ready', 'complete', 'limited', 'risk_interrupted')",
+    ),
+    "ingestion_pages": ("outcome IN ('ok', 'empty', 'risk_interrupted', 'failed')",),
+    "transcripts": ("source_kind IN ('subtitle-ai', 'subtitle-cc', 'asr-local')",),
+}
+EXPECTED_VIEW_WORK_ID_EXPRESSION = "vp.bvid || ':p' || vp.page_index AS work_id"
 
 
 def test_schema_sql_is_declared_and_read_as_package_resource():
@@ -125,7 +257,26 @@ def test_foreign_keys_reject_orphans_and_use_restrict(tmp_root):
                 """
             )
 
+        with pytest.raises(sqlite3.IntegrityError):
+            connection.execute(
+                "INSERT INTO ingestion_pages VALUES ('ghost-run', 1, 'ok', NULL, 1, 1)"
+            )
+        with pytest.raises(sqlite3.IntegrityError):
+            connection.execute(
+                "INSERT INTO ingestion_discoveries "
+                "VALUES ('ghost-run', 1, 'BVORPHAN', 0, 1)"
+            )
+
         _insert_user_video_part(connection)
+        connection.execute(
+            "INSERT INTO ingestion_runs VALUES "
+            "('run-1', 23191782, 'bilibili-api-python', '1.0', 1, NULL, 1, NULL, 'running')"
+        )
+        with pytest.raises(sqlite3.IntegrityError):
+            connection.execute(
+                "INSERT INTO ingestion_discoveries "
+                "VALUES ('run-1', 1, 'BVUNKNOWN', 0, 1)"
+            )
         with pytest.raises(sqlite3.IntegrityError):
             connection.execute("DELETE FROM bilibili_users WHERE mid = 23191782")
         with pytest.raises(sqlite3.IntegrityError):
@@ -232,6 +383,9 @@ def test_schema_constraints_cover_status_and_non_negative_values(tmp_root):
             "INSERT INTO ingestion_pages VALUES ('run', 0, 'ok', NULL, 1, 1)",
             "INSERT INTO ingestion_pages VALUES ('run', 1, 'unknown', NULL, 1, 1)",
             "INSERT INTO audio_objects VALUES (1, 'hash', -1, 'm4a', 1, 'audio', 1)",
+            f"INSERT INTO ingestion_cursors VALUES "
+            f"(23191782, 2, NULL, 'ready', '{'y' * 65}', 1)",
+            f"INSERT INTO ingestion_pages VALUES ('run', 3, 'failed', '{'x' * 65}', 1, 1)",
         ]
         for statement in invalid_statements:
             with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError)):
@@ -283,3 +437,140 @@ def test_transaction_order_parents_before_children(tmp_root):
         assert tuple(stats) == (1, 1)
     finally:
         connection.close()
+
+
+def test_schema_inspection_matches_the_declared_contract(tmp_root):
+    connection = open_database(tmp_root)
+    try:
+        assert _table_names(connection) == BASE_TABLES | VIEWS
+
+        for table in BASE_TABLES:
+            columns = [
+                row["name"] for row in connection.execute(f"PRAGMA table_info({table})")
+            ]
+            assert columns == EXPECTED_TABLE_COLUMNS[table]
+            assert "work_id" not in columns
+
+            foreign_keys = {
+                (row["from"], row["table"], row["to"])
+                for row in connection.execute(f"PRAGMA foreign_key_list({table})")
+            }
+            assert foreign_keys == set(EXPECTED_FOREIGN_KEYS.get(table, ()))
+            for row in connection.execute(f"PRAGMA foreign_key_list({table})"):
+                assert row["on_delete"] == "RESTRICT"
+
+            unique_constraints = set()
+            primary_key_indexes = set()
+            for index in connection.execute(f"PRAGMA index_list({table})"):
+                indexed_columns = tuple(
+                    info["name"]
+                    for info in connection.execute(f"PRAGMA index_info({index['name']})")
+                )
+                if index["origin"] == "u":
+                    unique_constraints.add(indexed_columns)
+                elif index["origin"] == "pk":
+                    primary_key_indexes.add(indexed_columns)
+            assert unique_constraints == set(
+                EXPECTED_UNIQUE_CONSTRAINTS.get(table, ())
+            )
+            assert primary_key_indexes == set(
+                EXPECTED_PRIMARY_KEY_INDEXES.get(table, ())
+            )
+
+        for table, fragments in EXPECTED_CHECK_ENUMERATIONS.items():
+            ddl_row = connection.execute(
+                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
+                (table,),
+            ).fetchone()
+            normalized_ddl = " ".join(ddl_row[0].split())
+            for fragment in fragments:
+                assert fragment in normalized_ddl
+
+        for view in VIEWS:
+            ddl_row = connection.execute(
+                "SELECT sql FROM sqlite_master WHERE type = 'view' AND name = ?",
+                (view,),
+            ).fetchone()
+            normalized_ddl = " ".join(ddl_row[0].split())
+            if view in {"v_video_parts", "v_pending_metadata"}:
+                assert EXPECTED_VIEW_WORK_ID_EXPRESSION in normalized_ddl
+    finally:
+        connection.close()
+
+
+def test_views_compute_derived_values_across_users_videos_and_runs(tmp_root):
+    connection = open_database(tmp_root)
+    try:
+        connection.executescript(
+            """
+            INSERT INTO bilibili_users VALUES (23191782, '未明子', 1, 1);
+            INSERT INTO bilibili_users VALUES (42, '第二位用户', 1, 1);
+            INSERT INTO videos VALUES
+                ('BV1SINGLE', 1001, 23191782, '单集视频', 1700000000, 1, 1);
+            INSERT INTO videos VALUES
+                ('BV1MULTI', 1002, 42, '多集视频', 1700000001, 1, 1);
+            INSERT INTO videos VALUES
+                ('BV1GONE', NULL, 42, '已下架视频', 1700000002, 1, 1);
+            INSERT INTO video_parts(
+                bvid, page_index, cid, title, duration_ms, processing_status,
+                created_at, updated_at
+            ) VALUES ('BV1SINGLE', 0, 2001, '第一集', 1000, 'discovered', 1, 1);
+            INSERT INTO video_parts(
+                bvid, page_index, cid, title, duration_ms, processing_status,
+                created_at, updated_at
+            ) VALUES ('BV1MULTI', 0, 3001, '上篇', 2000, 'discovered', 1, 1);
+            INSERT INTO video_parts(
+                bvid, page_index, cid, title, duration_ms, processing_status,
+                created_at, updated_at
+            ) VALUES ('BV1MULTI', 1, 3002, '下篇', 3000, 'metadata_collected', 1, 1);
+            INSERT INTO video_parts(
+                bvid, page_index, cid, title, duration_ms, processing_status,
+                created_at, updated_at
+            ) VALUES ('BV1GONE', 0, 4001, '残片', 4000, 'gone', 1, 1);
+            INSERT INTO ingestion_runs VALUES
+                ('run-1', 23191782, 'bilibili-api-python', '1.0', 1, NULL, 1, NULL, 'running');
+            INSERT INTO ingestion_runs VALUES
+                ('run-2', 42, 'bilibili-api-python', '1.0', 1, NULL, 1, NULL, 'running');
+            INSERT INTO ingestion_pages VALUES ('run-1', 1, 'ok', NULL, 1, 2);
+            INSERT INTO ingestion_pages VALUES ('run-1', 2, 'empty', NULL, 3, 4);
+            INSERT INTO ingestion_discoveries VALUES ('run-1', 1, 'BV1SINGLE', 0, 5);
+            INSERT INTO ingestion_discoveries VALUES ('run-1', 2, 'BV1SINGLE', 0, 6);
+            INSERT INTO ingestion_discoveries VALUES ('run-1', 2, 'BV1MULTI', 1, 6);
+            """
+        )
+
+        part_rows = connection.execute(
+            "SELECT work_id, user_name, video_title, page_index, cid, part_title, "
+            "processing_status FROM v_video_parts ORDER BY work_id"
+        ).fetchall()
+        assert [row["work_id"] for row in part_rows] == [
+            "BV1GONE:p0",
+            "BV1MULTI:p0",
+            "BV1MULTI:p1",
+            "BV1SINGLE:p0",
+        ]
+        single = part_rows[3]
+        assert single["user_name"] == "未明子"
+        assert single["video_title"] == "单集视频"
+        multi = part_rows[2]
+        assert multi["user_name"] == "第二位用户"
+        assert multi["part_title"] == "下篇"
+        assert multi["processing_status"] == "metadata_collected"
+
+        stats = {
+            row["run_id"]: (row["page_count"], row["video_count"])
+            for row in connection.execute("SELECT * FROM v_ingestion_run_stats")
+        }
+        # run-1 has three discovery rows but only two distinct videos; run-2
+        # has neither pages nor discoveries and still reports zero counts.
+        assert stats == {"run-1": (2, 2), "run-2": (0, 0)}
+
+        pending = [
+            row["work_id"]
+            for row in connection.execute(
+                "SELECT work_id FROM v_pending_metadata ORDER BY work_id"
+            )
+        ]
+        assert pending == ["BV1MULTI:p0", "BV1SINGLE:p0"]
+    finally:
+        connection.close()
```
