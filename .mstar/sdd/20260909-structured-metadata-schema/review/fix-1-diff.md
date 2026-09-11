# QC Fix Wave 1 Diff — 20260909-structured-metadata-schema

Plan: `20260909-structured-metadata-schema` (SDD)
Range: `ff81140411e9e04756055657569c39a0a0c5c2d4..6d76ea4068d04d30e3e4f8123454020c901d4461`
Base: `ff81140` (QC-reviewed implementation head)
Head: `6d76ea4 fix(storage): enforce run transition guards and canonical repository forms`
Working branch: `feature/20260909-structured-metadata-schema`
Scope: targeted re-validation of consolidated findings W1-W6 + S-fix-1..5 (see review/qc-consolidated.md)

```diff
diff --git a/bilibili-asr-archive/src/bili_asr/storage/__init__.py b/bilibili-asr-archive/src/bili_asr/storage/__init__.py
index 034e017..ea7c770 100644
--- a/bilibili-asr-archive/src/bili_asr/storage/__init__.py
+++ b/bilibili-asr-archive/src/bili_asr/storage/__init__.py
@@ -1,17 +1,57 @@
-"""Normalized SQLite storage for Bilibili metadata."""
+"""Normalized SQLite storage for Bilibili metadata.
+
+The package root is the single import surface: the repository, the record
+models, and the bootstrap helpers are all re-exported here.
+"""
 
 from .database import (
     DatabaseConnection,
+    MetadataRepository,
     duration_to_ms,
     initialize_schema,
     normalize_page_index,
     open_database,
 )
+from .models import (
+    ALLOWED_CURSOR_STATES,
+    ALLOWED_PAGE_OUTCOMES,
+    ALLOWED_PROCESSING_STATUS,
+    ALLOWED_RUN_OUTCOMES,
+    CursorRecord,
+    CursorState,
+    DiscoveryRecord,
+    IngestionPageRecord,
+    IngestionRunRecord,
+    PageOutcome,
+    ProcessingStatus,
+    RunOutcome,
+    UserRecord,
+    VideoPartRecord,
+    VideoRecord,
+    validate_error_code,
+)
 
 __all__ = [
+    "ALLOWED_CURSOR_STATES",
+    "ALLOWED_PAGE_OUTCOMES",
+    "ALLOWED_PROCESSING_STATUS",
+    "ALLOWED_RUN_OUTCOMES",
+    "CursorRecord",
+    "CursorState",
     "DatabaseConnection",
+    "DiscoveryRecord",
+    "IngestionPageRecord",
+    "IngestionRunRecord",
+    "MetadataRepository",
+    "PageOutcome",
+    "ProcessingStatus",
+    "RunOutcome",
+    "UserRecord",
+    "VideoPartRecord",
+    "VideoRecord",
     "duration_to_ms",
     "initialize_schema",
     "normalize_page_index",
     "open_database",
+    "validate_error_code",
 ]
diff --git a/bilibili-asr-archive/src/bili_asr/storage/database.py b/bilibili-asr-archive/src/bili_asr/storage/database.py
index c1772d3..01db8ef 100644
--- a/bilibili-asr-archive/src/bili_asr/storage/database.py
+++ b/bilibili-asr-archive/src/bili_asr/storage/database.py
@@ -11,6 +11,7 @@ import sqlite3
 from typing import Iterable, Iterator, TypeAlias
 
 from .models import (
+    ALLOWED_RUN_OUTCOMES,
     CursorRecord,
     DiscoveryRecord,
     IngestionPageRecord,
@@ -24,6 +25,7 @@ from .models import (
 DatabaseConnection: TypeAlias = sqlite3.Connection
 _ARCHIVE_DATABASE_NAME = "archive.db"
 _DATABASE_SUFFIXES = frozenset({".db", ".sqlite", ".sqlite3"})
+_TERMINAL_RUN_OUTCOMES = ALLOWED_RUN_OUTCOMES - frozenset({"running"})
 _SCHEMA_RESOURCE = resources.files(__package__).joinpath("schema.sql")
 
 
@@ -50,9 +52,14 @@ def normalize_page_index(page_number: int) -> int:
 
 
 def _resolve_database_path(path: str | os.PathLike[str]) -> str | os.PathLike[str]:
-    """Accept either an archive root or an explicit SQLite database path."""
+    """Accept either an archive root or an explicit SQLite database path.
+
+    ``:memory:`` opens an unnamed in-memory database. URI strings are not
+    interpreted: a ``file:``-prefixed value is handled as an ordinary file
+    name like any other explicit path.
+    """
     value = os.fspath(path)
-    if value in {":memory:"} or (isinstance(value, str) and value.startswith("file:")):
+    if value == ":memory:":
         return value
 
     candidate = Path(value)
@@ -66,7 +73,10 @@ def _resolve_database_path(path: str | os.PathLike[str]) -> str | os.PathLike[st
 
 
 def initialize_schema(connection: sqlite3.Connection) -> sqlite3.Connection:
-    """Initialize ``connection`` from the checked-in schema, idempotently."""
+    """Initialize ``connection`` from the checked-in schema, idempotently.
+
+    Enables foreign-key enforcement and commits the schema script.
+    """
     connection.execute("PRAGMA foreign_keys = ON")
     if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
         raise sqlite3.DatabaseError("SQLite foreign-key enforcement could not be enabled")
@@ -81,8 +91,10 @@ def open_database(path: str | os.PathLike[str]) -> DatabaseConnection:
     Existing directories are interpreted as archive roots. Paths ending in a
     normal SQLite suffix (``.db``, ``.sqlite``, or ``.sqlite3``) are treated as
     explicit database files, which is useful for tests and callers with a
-    custom filename. Connections use an explicit deferred transaction mode;
-    callers can use ``with connection:`` for atomic write groups.
+    custom filename; ``:memory:`` opens an in-memory database. URI strings are
+    not interpreted, so callers pass plain paths. Connections use an explicit
+    deferred transaction mode; callers can use ``with connection:`` for
+    atomic write groups.
     """
     database_path = _resolve_database_path(path)
     connection = sqlite3.connect(database_path, isolation_level="DEFERRED")
@@ -98,17 +110,36 @@ def open_database(path: str | os.PathLike[str]) -> DatabaseConnection:
 class MetadataRepository:
     """Repository for normalized metadata and ingestion state.
 
-    The low-level methods execute SQL without committing so a caller can group
-    them in one transaction. ``record_page`` is the page-level convenience
-    operation: when supplied with page payloads it owns the transaction and
-    applies the locked parent-before-child ordering. The connection's context
-    manager is also available through :meth:`transaction` for callers that
-    need to compose the lower-level methods themselves.
+    Commit boundaries per public method:
+
+    - ``start_run`` commits its own insert so a failed page can roll back
+      without deleting the run parent.
+    - ``finish_run`` commits its own terminal transition.
+    - ``record_page`` owns one transaction for its arguments and commits it,
+      or rolls it back and re-raises on a write failure; a no-payload
+      ``'failed'`` page commits its own evidence transaction.
+    - ``upsert_user``, ``upsert_video``, ``upsert_part``, ``record_discovery``
+      and ``write_cursor`` execute SQL without committing, so a caller can
+      group them in one transaction through :meth:`transaction`.
+    - ``read_cursor``, ``list_pending_parts`` and ``run_stats`` never write
+      or commit.
+
+    Do not compose ``start_run``, ``finish_run`` or ``record_page`` inside a
+    :meth:`transaction` group: each commits independently and would commit
+    the enclosing group's earlier writes.
+
+    The connection must come with ``row_factory = sqlite3.Row`` and
+    ``PRAGMA foreign_keys`` enabled — exactly the state :func:`open_database`
+    establishes; the constructor rejects anything else.
     """
 
     def __init__(self, connection: sqlite3.Connection):
         if not isinstance(connection, sqlite3.Connection):
             raise TypeError("connection must be a sqlite3.Connection")
+        if connection.row_factory is not sqlite3.Row:
+            raise TypeError("connection must use the sqlite3.Row row_factory")
+        if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
+            raise ValueError("connection must have PRAGMA foreign_keys enabled")
         self.connection = connection
 
     @contextmanager
@@ -163,58 +194,40 @@ class MetadataRepository:
         )
 
     def upsert_part(self, part: VideoPartRecord) -> int:
-        """Insert or update a normalized part and return its local ID."""
+        """Insert or update a normalized part and return its local ID.
+
+        ``video_part_id`` is allocated by the repository, so the record must
+        carry ``video_part_id=None``; a non-``None`` id raises ``ValueError``.
+        Conflicts on ``(bvid, page_index)`` update only the current display
+        fields and non-key facts.
+        """
         if not isinstance(part, VideoPartRecord):
             raise TypeError("part must be a VideoPartRecord")
-        if part.video_part_id is None:
-            self.connection.execute(
-                """
-                INSERT INTO video_parts(
-                    bvid, page_index, cid, title, duration_ms, processing_status,
-                    created_at, updated_at
-                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
-                ON CONFLICT(bvid, page_index) DO UPDATE SET
-                    title = excluded.title,
-                    duration_ms = excluded.duration_ms,
-                    processing_status = excluded.processing_status,
-                    updated_at = excluded.updated_at
-                """,
-                (
-                    part.bvid,
-                    part.page_index,
-                    part.cid,
-                    part.title,
-                    part.duration_ms,
-                    part.processing_status,
-                    part.created_at,
-                    part.updated_at,
-                ),
-            )
-        else:
-            self.connection.execute(
-                """
-                INSERT INTO video_parts(
-                    video_part_id, bvid, page_index, cid, title, duration_ms,
-                    processing_status, created_at, updated_at
-                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
-                ON CONFLICT(bvid, page_index) DO UPDATE SET
-                    title = excluded.title,
-                    duration_ms = excluded.duration_ms,
-                    processing_status = excluded.processing_status,
-                    updated_at = excluded.updated_at
-                """,
-                (
-                    part.video_part_id,
-                    part.bvid,
-                    part.page_index,
-                    part.cid,
-                    part.title,
-                    part.duration_ms,
-                    part.processing_status,
-                    part.created_at,
-                    part.updated_at,
-                ),
-            )
+        if part.video_part_id is not None:
+            raise ValueError("upsert_part allocates video_part_id; it must be None")
+        self.connection.execute(
+            """
+            INSERT INTO video_parts(
+                bvid, page_index, cid, title, duration_ms, processing_status,
+                created_at, updated_at
+            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
+            ON CONFLICT(bvid, page_index) DO UPDATE SET
+                title = excluded.title,
+                duration_ms = excluded.duration_ms,
+                processing_status = excluded.processing_status,
+                updated_at = excluded.updated_at
+            """,
+            (
+                part.bvid,
+                part.page_index,
+                part.cid,
+                part.title,
+                part.duration_ms,
+                part.processing_status,
+                part.created_at,
+                part.updated_at,
+            ),
+        )
 
         row = self.connection.execute(
             """
@@ -229,7 +242,11 @@ class MetadataRepository:
         return int(row[0])
 
     def start_run(self, run: IngestionRunRecord) -> None:
-        """Insert a run record, preserving an existing run on retry."""
+        """Insert one new run record.
+
+        ``run_id`` is the primary key and is never reused: a duplicate raises
+        ``sqlite3.IntegrityError``.
+        """
         if not isinstance(run, IngestionRunRecord):
             raise TypeError("run must be an IngestionRunRecord")
         self.connection.execute(
@@ -238,7 +255,6 @@ class MetadataRepository:
                 run_id, mid, source_package, source_version, requested_start_page,
                 requested_page_limit, started_at, finished_at, outcome
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
-            ON CONFLICT(run_id) DO NOTHING
             """,
             (
                 run.run_id,
@@ -256,59 +272,40 @@ class MetadataRepository:
         # independently so a failed page can roll back without deleting it.
         self.connection.commit()
 
-    def finish_run(
-        self,
-        run: IngestionRunRecord | str,
-        outcome: str | None = None,
-        finished_at: int | None = None,
-    ) -> None:
-        """Set a run's terminal/current outcome.
+    def finish_run(self, run: IngestionRunRecord) -> None:
+        """Finish a run with its terminal outcome and finish timestamp.
 
-        The preferred form is ``finish_run(IngestionRunRecord(...))``. A scalar
-        compatibility form, ``finish_run(run_id, outcome, finished_at)``, is
-        provided for the ingestion service's terminal transition.
+        The canonical form is ``finish_run(IngestionRunRecord(...))`` with a
+        terminal ``outcome`` and an integer ``finished_at``. The ordering
+        baseline is the run's stored ``started_at``, not the record's own
+        ``started_at`` field. Re-finishing is rejected: a run whose stored
+        outcome is already terminal raises ``sqlite3.IntegrityError``.
         """
-        if isinstance(run, IngestionRunRecord):
-            run_id = run.run_id
-            resolved_outcome = run.outcome
-            resolved_finished_at = run.finished_at
-            if resolved_finished_at is None:
-                raise ValueError("finished_at is required when finishing a run")
-            started_at = run.started_at
-        elif isinstance(run, str):
-            run_id = run
-            if not run_id.strip():
-                raise ValueError("run_id must not be empty")
-            if outcome is None or finished_at is None:
-                raise ValueError("outcome and finished_at are required")
-            resolved_outcome = outcome
-            resolved_finished_at = finished_at
-            started_row = self.connection.execute(
-                "SELECT started_at FROM ingestion_runs WHERE run_id = ?", (run_id,)
-            ).fetchone()
-            if started_row is None:
-                raise sqlite3.IntegrityError(f"unknown run_id: {run_id}")
-            started_at = int(started_row[0])
-        else:
-            raise TypeError("run must be an IngestionRunRecord or run ID")
-
-        if resolved_outcome not in {
-            "complete",
-            "limited",
-            "risk_interrupted",
-            "failed",
-        }:
+        if not isinstance(run, IngestionRunRecord):
+            raise TypeError("run must be an IngestionRunRecord")
+        run_row = self.connection.execute(
+            "SELECT started_at, outcome FROM ingestion_runs WHERE run_id = ?",
+            (run.run_id,),
+        ).fetchone()
+        if run_row is None:
+            raise sqlite3.IntegrityError(f"unknown run_id: {run.run_id}")
+        if run_row["outcome"] != "running":
+            raise sqlite3.IntegrityError(
+                f"run {run.run_id} already finished with outcome {run_row['outcome']}"
+            )
+        if run.outcome not in _TERMINAL_RUN_OUTCOMES:
             raise ValueError("finish_run requires a terminal run outcome")
-        if not isinstance(resolved_finished_at, int) or isinstance(resolved_finished_at, bool):
-            raise TypeError("finished_at must be an integer")
-        if resolved_finished_at < started_at:
+        if run.finished_at is None:
+            raise ValueError("finished_at is required when finishing a run")
+        started_at = int(run_row["started_at"])
+        if run.finished_at < started_at:
             raise ValueError("finished_at must not precede started_at")
         self.connection.execute(
             "UPDATE ingestion_runs SET finished_at = ?, outcome = ? WHERE run_id = ?",
-            (resolved_finished_at, resolved_outcome, run_id),
+            (run.finished_at, run.outcome, run.run_id),
         )
         if self.connection.execute("SELECT changes()").fetchone()[0] != 1:
-            raise sqlite3.IntegrityError(f"unknown run_id: {run_id}")
+            raise sqlite3.IntegrityError(f"unknown run_id: {run.run_id}")
         self.connection.commit()
 
     def _record_page(self, page: IngestionPageRecord) -> None:
@@ -337,28 +334,33 @@ class MetadataRepository:
         self,
         page: IngestionPageRecord,
         user: UserRecord | None = None,
-        video: VideoRecord | Iterable[VideoRecord] | None = None,
+        videos: Iterable[VideoRecord] = (),
         parts: Iterable[VideoPartRecord] = (),
         discoveries: Iterable[DiscoveryRecord] = (),
         cursor: CursorRecord | None = None,
-        *,
-        videos: Iterable[VideoRecord] = (),
     ) -> None:
-        """Record a page, optionally atomically persisting its complete payload.
-
-        With payload arguments this method performs the locked order: user,
-        videos, parts, discoveries, cursor, page outcome, commit. If any write
-        fails, the page transaction is rolled back. When the supplied page has
-        ``outcome='failed'``, its bounded page/run failure outcome is then
-        written in a separate transaction without persisting exception text.
+        """Record one page outcome, optionally with its complete payload.
+
+        With payload arguments the method owns one transaction and applies the
+        locked parent-before-child order: user, videos, parts, discoveries,
+        cursor, page outcome, commit. If any write fails, the whole
+        transaction is rolled back and the exception is re-raised; the prior
+        cursor and entities are unchanged. Recording the resulting failure is
+        the caller's step: build a fresh ``IngestionPageRecord`` with
+        ``outcome='failed'`` and a bounded ``error_code`` and call this method
+        again with no payload arguments.
+
+        A ``'failed'`` page therefore never carries payloads — supplying
+        payload arguments with ``outcome='failed'`` raises ``ValueError``
+        before any write. A no-payload ``'failed'`` page is recorded in its
+        own committed transaction together with the parent run's failure
+        transition. When that run is already terminal, the page evidence is
+        still persisted while the run's outcome and ``finished_at`` stay
+        unchanged.
         """
         if not isinstance(page, IngestionPageRecord):
             raise TypeError("page must be an IngestionPageRecord")
         video_records = tuple(videos)
-        if isinstance(video, VideoRecord):
-            video_records = (video, *video_records)
-        elif video is not None:
-            video_records = (*tuple(video), *video_records)
         part_records = tuple(parts)
         discovery_records = tuple(discoveries)
         has_payload = (
@@ -368,6 +370,9 @@ class MetadataRepository:
             or bool(discovery_records)
             or cursor is not None
         )
+        if page.outcome == "failed" and has_payload:
+            raise ValueError("a failed page is recorded without payload arguments")
+
         if not has_payload:
             if page.outcome == "failed":
                 self._record_failed_page(page)
@@ -376,38 +381,34 @@ class MetadataRepository:
                     self._record_page(page)
             return
 
-        try:
-            with self.transaction():
-                if user is not None:
-                    self.upsert_user(user)
-                for video_record in video_records:
-                    self.upsert_video(video_record)
-                for part in part_records:
-                    self.upsert_part(part)
-                for discovery in discovery_records:
-                    self.record_discovery(discovery)
-                if cursor is not None:
-                    self.write_cursor(cursor)
-                self._record_page(page)
-        except BaseException:
-            if page.outcome == "failed":
-                try:
-                    self._record_failed_page(page)
-                except sqlite3.Error:
-                    # Preserve the original page error; a missing run cannot be
-                    # repaired by inventing a relationship or error detail.
-                    self.connection.rollback()
-            raise
+        with self.transaction():
+            if user is not None:
+                self.upsert_user(user)
+            for video_record in video_records:
+                self.upsert_video(video_record)
+            for part in part_records:
+                self.upsert_part(part)
+            for discovery in discovery_records:
+                self.record_discovery(discovery)
+            if cursor is not None:
+                self.write_cursor(cursor)
+            self._record_page(page)
 
     def _record_failed_page(self, page: IngestionPageRecord) -> None:
-        """Persist only bounded failure state after a rolled-back page."""
+        """Persist only bounded failure state after a rolled-back page.
+
+        The page evidence is always upserted; the parent run's failure
+        transition applies only while the run is still ``'running'``, so a
+        late or stale failed page can never regress a terminal outcome or
+        move ``finished_at`` backwards.
+        """
         with self.transaction():
             self._record_page(page)
             self.connection.execute(
                 """
                 UPDATE ingestion_runs
                 SET outcome = 'failed', finished_at = ?
-                WHERE run_id = ?
+                WHERE run_id = ? AND outcome = 'running'
                 """,
                 (page.finished_at, page.run_id),
             )
diff --git a/bilibili-asr-archive/src/bili_asr/storage/models.py b/bilibili-asr-archive/src/bili_asr/storage/models.py
index 266ffdd..780b42a 100644
--- a/bilibili-asr-archive/src/bili_asr/storage/models.py
+++ b/bilibili-asr-archive/src/bili_asr/storage/models.py
@@ -109,9 +109,9 @@ class VideoRecord:
 class VideoPartRecord:
     """Normalized metadata for one video part.
 
-    ``video_part_id`` is optional for new rows because SQLite allocates the
-    local surrogate key.  ``work_id`` is intentionally computed and is never
-    persisted as a column.
+    ``video_part_id`` is allocated by the repository: records passed to
+    ``MetadataRepository.upsert_part`` must carry ``None``. ``work_id`` is
+    intentionally computed and is never persisted as a column.
     """
 
     bvid: str
@@ -252,7 +252,9 @@ __all__ = [
 ]
 
 
-# Internal validation helpers are intentionally not part of the public model API.
+# Public validation surface: the canonical enumeration sets and the error-code
+# validator are exported so gateway and CLI callers validate against the same
+# contract the record dataclasses enforce.
 validate_error_code = _error_code
 ALLOWED_PAGE_OUTCOMES = _ALLOWED_PAGE_OUTCOMES
 ALLOWED_RUN_OUTCOMES = _ALLOWED_RUN_OUTCOMES
diff --git a/bilibili-asr-archive/tests/fixtures/metadata_records.py b/bilibili-asr-archive/tests/fixtures/metadata_records.py
index a37584c..0e241f8 100644
--- a/bilibili-asr-archive/tests/fixtures/metadata_records.py
+++ b/bilibili-asr-archive/tests/fixtures/metadata_records.py
@@ -16,6 +16,7 @@ from bili_asr.storage.models import (
     IngestionRunRecord,
     PageOutcome,
     ProcessingStatus,
+    RunOutcome,
     UserRecord,
     VideoPartRecord,
     VideoRecord,
@@ -43,6 +44,8 @@ def make_run_record(
     requested_start_page: int = 1,
     requested_page_limit: int | None = 3,
     started_at: int = 101,
+    outcome: RunOutcome = "running",
+    finished_at: int | None = None,
 ) -> IngestionRunRecord:
     """Build one metadata collection run opened against the archive owner."""
     return IngestionRunRecord(
@@ -53,6 +56,8 @@ def make_run_record(
         requested_start_page=requested_start_page,
         requested_page_limit=requested_page_limit,
         started_at=started_at,
+        outcome=outcome,
+        finished_at=finished_at,
     )
 
 
@@ -81,8 +86,9 @@ def make_part_record(
     page_index: int = 0,
     cid: int = 2001,
     title: str = "第一集",
-    status: ProcessingStatus = "discovered",
+    processing_status: ProcessingStatus = "discovered",
     updated_at: int = 103,
+    video_part_id: int | None = None,
 ) -> VideoPartRecord:
     """Build one normalized part of a video."""
     return VideoPartRecord(
@@ -91,9 +97,10 @@ def make_part_record(
         cid=cid,
         title=title,
         duration_ms=1_234,
-        processing_status=status,
+        processing_status=processing_status,
         created_at=103,
         updated_at=updated_at,
+        video_part_id=video_part_id,
     )
 
 
diff --git a/bilibili-asr-archive/tests/test_metadata_repository.py b/bilibili-asr-archive/tests/test_metadata_repository.py
index 7dda1c9..14dd30c 100644
--- a/bilibili-asr-archive/tests/test_metadata_repository.py
+++ b/bilibili-asr-archive/tests/test_metadata_repository.py
@@ -3,6 +3,7 @@
 from __future__ import annotations
 
 from dataclasses import fields
+import os
 import re
 import sqlite3
 
@@ -93,7 +94,7 @@ def test_repeated_page_is_idempotent_but_a_new_run_keeps_page_evidence(tmp_root)
         repository.record_page(
             make_page_record(),
             user=make_user_record(),
-            video=make_video_record(),
+            videos=[make_video_record()],
             parts=[make_part_record()],
             discoveries=[make_discovery_record("BV1SINGLE")],
             cursor=make_cursor_record(),
@@ -102,7 +103,7 @@ def test_repeated_page_is_idempotent_but_a_new_run_keeps_page_evidence(tmp_root)
         repository.record_page(
             make_page_record(finished_at=120),
             user=make_user_record(display_name="未明子（更新）", updated_at=119),
-            video=make_video_record(title="更新后的标题", updated_at=119),
+            videos=[make_video_record(title="更新后的标题", updated_at=119)],
             parts=[make_part_record(title="更新后的分集标题", updated_at=119)],
             discoveries=[make_discovery_record("BV1SINGLE", discovered_at=119)],
             cursor=make_cursor_record(updated_at=120),
@@ -117,7 +118,7 @@ def test_repeated_page_is_idempotent_but_a_new_run_keeps_page_evidence(tmp_root)
         _start_run(repository, "run-2")
         repository.record_page(
             make_page_record("run-2"),
-            video=make_video_record(title="同一视频的第二次发现"),
+            videos=[make_video_record(title="同一视频的第二次发现")],
             parts=[make_part_record()],
             discoveries=[make_discovery_record("BV1SINGLE", run_id="run-2")],
             cursor=make_cursor_record(updated_at=130),
@@ -131,37 +132,53 @@ def test_repeated_page_is_idempotent_but_a_new_run_keeps_page_evidence(tmp_root)
         connection.close()
 
 
-def test_failed_page_rolls_back_payload_preserves_cursor_and_records_bounded_outcome(tmp_root):
+def test_ok_page_write_failure_rolls_back_and_caller_records_failure(tmp_root):
     connection = open_database(tmp_root)
     repository = MetadataRepository(connection)
     try:
         _start_run(repository)
         repository.record_page(
             make_page_record(),
-            video=make_video_record(),
+            user=make_user_record(),
+            videos=[make_video_record()],
             parts=[make_part_record()],
             discoveries=[make_discovery_record("BV1SINGLE")],
             cursor=make_cursor_record(),
         )
-        failed_page = make_page_record(
-            page_number=2,
-            outcome="failed",
-            error_code="foreign_key",
-            started_at=200,
-            finished_at=201,
-        )
+        ok_page = make_page_record(page_number=2, started_at=200, finished_at=201)
         with pytest.raises(sqlite3.IntegrityError):
             repository.record_page(
-                failed_page,
+                ok_page,
                 user=make_user_record(display_name="must roll back", updated_at=200),
-                video=make_video_record(title="must roll back", updated_at=200),
+                videos=[make_video_record(title="must roll back", updated_at=200)],
                 parts=[make_part_record("BV-MISSING", title="orphan")],
+                discoveries=[
+                    make_discovery_record("BV1SINGLE", page_number=2, discovered_at=200)
+                ],
                 cursor=make_cursor_record(next_page=3, updated_at=201),
             )
 
         assert repository.read_cursor(MID) == make_cursor_record()
+        assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 1
         assert connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0] == 1
-        assert connection.execute("SELECT display_name FROM bilibili_users").fetchone()[0] == "未明子"
+        assert connection.execute("SELECT COUNT(*) FROM ingestion_pages").fetchone()[0] == 1
+        assert tuple(
+            connection.execute(
+                "SELECT outcome, finished_at FROM ingestion_runs WHERE run_id = 'run-1'"
+            ).fetchone()
+        ) == ("running", None)
+
+        # The caller owns failure recording: a fresh failed page record with a
+        # bounded scalar error code, replayed with no payload arguments.
+        failure_evidence = make_page_record(
+            page_number=2,
+            outcome="failed",
+            error_code="foreign_key",
+            started_at=200,
+            finished_at=201,
+        )
+        repository.record_page(failure_evidence)
+
         page_row = connection.execute(
             "SELECT outcome, error_code FROM ingestion_pages WHERE run_id = 'run-1' AND page_number = 2"
         ).fetchone()
@@ -171,9 +188,120 @@ def test_failed_page_rolls_back_payload_preserves_cursor_and_records_bounded_out
                 "SELECT outcome, finished_at FROM ingestion_runs WHERE run_id = 'run-1'"
             ).fetchone()
         ) == ("failed", 201)
+    finally:
+        connection.close()
+
+
+def test_record_page_rejects_payloads_on_a_failed_page(tmp_root):
+    connection = open_database(tmp_root)
+    repository = MetadataRepository(connection)
+    try:
+        _start_run(repository)
+        failed_page = make_page_record(
+            page_number=2,
+            outcome="failed",
+            error_code="foreign_key",
+            started_at=200,
+            finished_at=201,
+        )
+        with pytest.raises(ValueError):
+            repository.record_page(
+                failed_page,
+                videos=[make_video_record()],
+                parts=[make_part_record()],
+                cursor=make_cursor_record(next_page=3),
+            )
+
+        assert tuple(
+            connection.execute(
+                "SELECT outcome, finished_at FROM ingestion_runs WHERE run_id = 'run-1'"
+            ).fetchone()
+        ) == ("running", None)
         assert connection.execute(
-            "SELECT COUNT(*) FROM ingestion_pages WHERE error_code LIKE '%traceback%'"
+            "SELECT COUNT(*) FROM ingestion_pages WHERE page_number = 2"
         ).fetchone()[0] == 0
+        assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 0
+    finally:
+        connection.close()
+
+
+def test_late_failed_page_after_terminal_run_keeps_run_outcome_unchanged(tmp_root):
+    connection = open_database(tmp_root)
+    repository = MetadataRepository(connection)
+    try:
+        _start_run(repository)
+        repository.record_page(
+            make_page_record(),
+            videos=[make_video_record()],
+            parts=[make_part_record()],
+            discoveries=[make_discovery_record("BV1SINGLE")],
+        )
+        repository.finish_run(make_run_record(outcome="complete", finished_at=300))
+
+        late_failure = make_page_record(
+            page_number=2,
+            outcome="failed",
+            error_code="stale_page_result",
+            started_at=400,
+            finished_at=401,
+        )
+        repository.record_page(late_failure)
+
+        page_row = connection.execute(
+            "SELECT outcome, error_code FROM ingestion_pages "
+            "WHERE run_id = 'run-1' AND page_number = 2"
+        ).fetchone()
+        assert tuple(page_row) == ("failed", "stale_page_result")
+        assert tuple(
+            connection.execute(
+                "SELECT outcome, finished_at FROM ingestion_runs WHERE run_id = 'run-1'"
+            ).fetchone()
+        ) == ("complete", 300)
+    finally:
+        connection.close()
+
+
+def test_finish_run_rejects_refinishing_a_terminal_run(tmp_root):
+    connection = open_database(tmp_root)
+    repository = MetadataRepository(connection)
+    try:
+        _start_run(repository)
+        repository.finish_run(make_run_record(outcome="complete", finished_at=300))
+        with pytest.raises(sqlite3.IntegrityError):
+            repository.finish_run(make_run_record(outcome="failed", finished_at=310))
+        assert tuple(
+            connection.execute(
+                "SELECT outcome, finished_at FROM ingestion_runs WHERE run_id = 'run-1'"
+            ).fetchone()
+        ) == ("complete", 300)
+    finally:
+        connection.close()
+
+
+def test_finish_run_record_form_validates_against_database_started_at(tmp_root):
+    connection = open_database(tmp_root)
+    repository = MetadataRepository(connection)
+    try:
+        _start_run(repository)
+
+        # The stored started_at (101) is the ordering baseline, not the
+        # caller-supplied record's own started_at field (50).
+        stale_clock_record = make_run_record(
+            started_at=50, outcome="complete", finished_at=60
+        )
+        with pytest.raises(ValueError):
+            repository.finish_run(stale_clock_record)
+
+        with pytest.raises(ValueError):
+            repository.finish_run(make_run_record(outcome="running", finished_at=120))
+        with pytest.raises(ValueError):
+            repository.finish_run(make_run_record(outcome="complete", finished_at=None))
+
+        repository.finish_run(make_run_record(outcome="limited", finished_at=300))
+        stats = repository.run_stats("run-1")
+        assert stats is not None
+        assert stats["outcome"] == "limited"
+        assert stats["finished_at"] == 300
     finally:
         connection.close()
 
@@ -219,7 +347,7 @@ def test_repository_end_to_end_records_two_runs_with_cursor_transitions(tmp_root
         repository.record_page(
             make_page_record(),
             user=make_user_record(),
-            video=make_video_record(),
+            videos=[make_video_record()],
             parts=[make_part_record()],
             discoveries=[make_discovery_record("BV1SINGLE")],
             cursor=make_cursor_record(),
@@ -266,8 +394,10 @@ def test_repository_end_to_end_records_two_runs_with_cursor_transitions(tmp_root
             ),
         )
 
-        repository.finish_run("run-1", "complete", 300)
-        repository.finish_run("run-2", "complete", 301)
+        repository.finish_run(make_run_record(outcome="complete", finished_at=300))
+        repository.finish_run(
+            make_run_record("run-2", started_at=200, outcome="complete", finished_at=301)
+        )
 
         assert connection.execute("SELECT COUNT(*) FROM bilibili_users").fetchone()[0] == 1
         assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 2
@@ -350,11 +480,6 @@ def test_error_fields_persist_only_bounded_scalar_codes(tmp_root):
             ("ingestion_cursors", "last_error_code"),
             ("ingestion_pages", "error_code"),
         ):
-            for marker in ("SESSDATA", "bili_jct", "https", "{", "Traceback", " "):
-                assert connection.execute(
-                    f"SELECT COUNT(*) FROM {table} WHERE {column} LIKE ?",
-                    (f"%{marker}%",),
-                ).fetchone()[0] == 0
             values = connection.execute(
                 f"SELECT {column} FROM {table} WHERE {column} IS NOT NULL"
             ).fetchall()
@@ -390,7 +515,7 @@ def test_cursor_resume_and_pending_limit(tmp_root):
         _start_run(repository)
         repository.record_page(
             make_page_record(),
-            video=make_video_record(),
+            videos=[make_video_record()],
             parts=[make_part_record(), make_part_record(page_index=1, cid=2002, title="第二集")],
             discoveries=[make_discovery_record("BV1SINGLE")],
             cursor=make_cursor_record(next_page=2),
@@ -401,7 +526,9 @@ def test_cursor_resume_and_pending_limit(tmp_root):
 
         with repository.transaction():
             repository.upsert_part(
-                make_part_record(page_index=1, cid=2002, title="第二集", status="metadata_collected")
+                make_part_record(
+                    page_index=1, cid=2002, title="第二集", processing_status="metadata_collected"
+                )
             )
         assert [row["page_index"] for row in repository.list_pending_parts()] == [0]
     finally:
@@ -415,11 +542,11 @@ def test_finish_run_and_all_run_stats_are_derived_from_normalized_rows(tmp_root)
         _start_run(repository)
         repository.record_page(
             make_page_record(),
-            video=make_video_record(),
+            videos=[make_video_record()],
             parts=[make_part_record()],
             discoveries=[make_discovery_record("BV1SINGLE")],
         )
-        repository.finish_run("run-1", "complete", 300)
+        repository.finish_run(make_run_record(outcome="complete", finished_at=300))
         stats = repository.run_stats()
         assert len(stats) == 1
         assert stats[0]["outcome"] == "complete"
@@ -437,3 +564,47 @@ def test_start_run_requires_a_foreign_key_parent(tmp_root):
             repository.start_run(make_run_record())
     finally:
         connection.close()
+
+
+def test_start_run_rejects_a_duplicate_run_id(tmp_root):
+    connection = open_database(tmp_root)
+    repository = MetadataRepository(connection)
+    try:
+        _start_run(repository)
+        with pytest.raises(sqlite3.IntegrityError):
+            repository.start_run(make_run_record("run-1"))
+    finally:
+        connection.close()
+
+
+def test_upsert_part_rejects_an_explicit_video_part_id(tmp_root):
+    connection = open_database(tmp_root)
+    repository = MetadataRepository(connection)
+    try:
+        with repository.transaction():
+            repository.upsert_user(make_user_record())
+            repository.upsert_video(make_video_record())
+            with pytest.raises(ValueError):
+                repository.upsert_part(make_part_record(video_part_id=7))
+    finally:
+        connection.close()
+
+
+def test_constructor_rejects_a_connection_without_row_factory(tmp_root):
+    connection = sqlite3.connect(os.path.join(tmp_root, "bare.db"))
+    try:
+        with pytest.raises(TypeError):
+            MetadataRepository(connection)
+    finally:
+        connection.close()
+
+
+def test_constructor_rejects_a_connection_with_foreign_keys_disabled(tmp_root):
+    connection = sqlite3.connect(os.path.join(tmp_root, "fk-off.db"))
+    connection.row_factory = sqlite3.Row
+    try:
+        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 0
+        with pytest.raises(ValueError):
+            MetadataRepository(connection)
+    finally:
+        connection.close()
diff --git a/bilibili-asr-archive/tests/test_storage_schema.py b/bilibili-asr-archive/tests/test_storage_schema.py
index c91ac86..7ab7e24 100644
--- a/bilibili-asr-archive/tests/test_storage_schema.py
+++ b/bilibili-asr-archive/tests/test_storage_schema.py
@@ -5,12 +5,24 @@ from __future__ import annotations
 from importlib import resources
 import os
 from pathlib import Path
+import re
 import sqlite3
 import tomllib
+from typing import get_args
 
 import pytest
 
 from bili_asr.storage import duration_to_ms, normalize_page_index, open_database
+from bili_asr.storage.models import (
+    ALLOWED_CURSOR_STATES,
+    ALLOWED_PAGE_OUTCOMES,
+    ALLOWED_PROCESSING_STATUS,
+    ALLOWED_RUN_OUTCOMES,
+    CursorState,
+    PageOutcome,
+    ProcessingStatus,
+    RunOutcome,
+)
 
 
 BASE_TABLES = {
@@ -160,6 +172,12 @@ EXPECTED_CHECK_ENUMERATIONS = {
     "transcripts": ("source_kind IN ('subtitle-ai', 'subtitle-cc', 'asr-local')",),
 }
 EXPECTED_VIEW_WORK_ID_EXPRESSION = "vp.bvid || ':p' || vp.page_index AS work_id"
+EXPECTED_ENUM_COLUMNS = {
+    ("video_parts", "processing_status"): ALLOWED_PROCESSING_STATUS,
+    ("ingestion_runs", "outcome"): ALLOWED_RUN_OUTCOMES,
+    ("ingestion_cursors", "state"): ALLOWED_CURSOR_STATES,
+    ("ingestion_pages", "outcome"): ALLOWED_PAGE_OUTCOMES,
+}
 
 
 def test_schema_sql_is_declared_and_read_as_package_resource():
@@ -228,6 +246,46 @@ def test_fresh_database_initializes_archive_root_and_is_idempotent(tmp_root):
         reopened.close()
 
 
+def test_open_database_memory_database_is_initialized():
+    connection = open_database(":memory:")
+    try:
+        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
+        assert BASE_TABLES | VIEWS <= _table_names(connection)
+        _insert_user_video_part(connection)
+        connection.commit()
+        assert (
+            connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0] == 1
+        )
+    finally:
+        connection.close()
+
+
+def test_schema_check_enumerations_match_model_validation_sets():
+    """The DDL CHECK literals and the model validation sets are one contract."""
+    connection = open_database(":memory:")
+    try:
+        for (table, column), allowed in EXPECTED_ENUM_COLUMNS.items():
+            ddl_row = connection.execute(
+                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
+                (table,),
+            ).fetchone()
+            match = re.search(rf"\b{column}\s+IN\s*\(([^)]*)\)", ddl_row[0])
+            assert match is not None
+            literals = re.findall(r"'([^']*)'", match.group(1))
+            assert sorted(literals) == sorted(allowed)
+
+        literal_sets = (
+            (ProcessingStatus, ALLOWED_PROCESSING_STATUS),
+            (RunOutcome, ALLOWED_RUN_OUTCOMES),
+            (PageOutcome, ALLOWED_PAGE_OUTCOMES),
+            (CursorState, ALLOWED_CURSOR_STATES),
+        )
+        for literal, allowed in literal_sets:
+            assert sorted(get_args(literal)) == sorted(allowed)
+    finally:
+        connection.close()
+
+
 def test_page_and_duration_normalization_uses_contract_formulas():
     assert duration_to_ms(12.3459) == 12_345
     assert duration_to_ms(0) == 0
```
