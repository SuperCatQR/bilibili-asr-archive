# Branch Review Package — 20260911-transcript-storage

Plan: `20260911-transcript-storage` (iteration `iter-2026-09-subtitle-transcript-sqlite`)
Range: `6ee7c6a..5f93e05`
Base: `6ee7c6a` (integration branch at feature-branch cut)
Head: `5f93e05`
Working branch: `feature/20260911-transcript-storage`
Commits: d4cae24 (schema contract), f3cd735 (write path), 1019000 (reads/enumeration, resumed), 5f93e05 (Minor-1 test strength)

```diff
diff --git a/bilibili-asr-archive/pyproject.toml b/bilibili-asr-archive/pyproject.toml
index 1b35307..c8ae951 100644
--- a/bilibili-asr-archive/pyproject.toml
+++ b/bilibili-asr-archive/pyproject.toml
@@ -32,7 +32,7 @@ asr = [
 where = ["src"]
 
 [tool.setuptools.package-data]
-"bili_asr.storage" = ["schema.sql"]
+"bili_asr.storage" = ["schema.sql", "schema-transcripts.sql"]
 
 [tool.pytest.ini_options]
 testpaths = ["tests"]
diff --git a/bilibili-asr-archive/src/bili_asr/storage/__init__.py b/bilibili-asr-archive/src/bili_asr/storage/__init__.py
index ea7c770..87461a4 100644
--- a/bilibili-asr-archive/src/bili_asr/storage/__init__.py
+++ b/bilibili-asr-archive/src/bili_asr/storage/__init__.py
@@ -7,16 +7,29 @@ models, and the bootstrap helpers are all re-exported here.
 from .database import (
     DatabaseConnection,
     MetadataRepository,
+    SchemaContractError,
+    TranscriptRepository,
     duration_to_ms,
     initialize_schema,
     normalize_page_index,
     open_database,
+    require_subtitle_schema,
 )
 from .models import (
+    ALLOWED_ACQUISITION_KINDS,
+    ALLOWED_ACQUISITION_OUTCOMES,
+    ALLOWED_ATTEMPT_OUTCOMES,
+    ALLOWED_CAPTION_SOURCE_KINDS,
     ALLOWED_CURSOR_STATES,
     ALLOWED_PAGE_OUTCOMES,
     ALLOWED_PROCESSING_STATUS,
     ALLOWED_RUN_OUTCOMES,
+    ALLOWED_SOURCE_KINDS,
+    MAX_TIMELINE_MS,
+    AcquisitionKind,
+    AcquisitionOutcome,
+    AcquisitionRunRecord,
+    AttemptOutcome,
     CursorRecord,
     CursorState,
     DiscoveryRecord,
@@ -25,6 +38,10 @@ from .models import (
     PageOutcome,
     ProcessingStatus,
     RunOutcome,
+    SourceKind,
+    TranscriptRecord,
+    TranscriptSegmentRecord,
+    TranscriptWriteResult,
     UserRecord,
     VideoPartRecord,
     VideoRecord,
@@ -32,20 +49,36 @@ from .models import (
 )
 
 __all__ = [
+    "ALLOWED_ACQUISITION_KINDS",
+    "ALLOWED_ACQUISITION_OUTCOMES",
+    "ALLOWED_ATTEMPT_OUTCOMES",
+    "ALLOWED_CAPTION_SOURCE_KINDS",
     "ALLOWED_CURSOR_STATES",
     "ALLOWED_PAGE_OUTCOMES",
     "ALLOWED_PROCESSING_STATUS",
     "ALLOWED_RUN_OUTCOMES",
+    "ALLOWED_SOURCE_KINDS",
+    "AcquisitionKind",
+    "AcquisitionOutcome",
+    "AcquisitionRunRecord",
+    "AttemptOutcome",
     "CursorRecord",
     "CursorState",
     "DatabaseConnection",
     "DiscoveryRecord",
     "IngestionPageRecord",
     "IngestionRunRecord",
+    "MAX_TIMELINE_MS",
     "MetadataRepository",
     "PageOutcome",
     "ProcessingStatus",
     "RunOutcome",
+    "SchemaContractError",
+    "SourceKind",
+    "TranscriptRecord",
+    "TranscriptRepository",
+    "TranscriptSegmentRecord",
+    "TranscriptWriteResult",
     "UserRecord",
     "VideoPartRecord",
     "VideoRecord",
@@ -53,5 +86,6 @@ __all__ = [
     "initialize_schema",
     "normalize_page_index",
     "open_database",
+    "require_subtitle_schema",
     "validate_error_code",
 ]
diff --git a/bilibili-asr-archive/src/bili_asr/storage/database.py b/bilibili-asr-archive/src/bili_asr/storage/database.py
index 2cd1bf0..499164c 100644
--- a/bilibili-asr-archive/src/bili_asr/storage/database.py
+++ b/bilibili-asr-archive/src/bili_asr/storage/database.py
@@ -1,9 +1,11 @@
-"""SQLite bootstrap and normalized metadata repository."""
+"""SQLite bootstrap and the normalized metadata and transcript repositories."""
 
 from __future__ import annotations
 
 from contextlib import contextmanager
+import hashlib
 from importlib import resources
+import json
 import math
 import os
 from pathlib import Path
@@ -11,14 +13,26 @@ import sqlite3
 from typing import Iterable, Iterator, TypeAlias
 
 from .models import (
+    ALLOWED_ATTEMPT_OUTCOMES,
+    ALLOWED_CAPTION_SOURCE_KINDS,
     ALLOWED_RUN_OUTCOMES,
+    ALLOWED_SOURCE_KINDS,
+    MAX_TIMELINE_MS,
+    AcquisitionRunRecord,
     CursorRecord,
     DiscoveryRecord,
     IngestionPageRecord,
     IngestionRunRecord,
+    TranscriptRecord,
+    TranscriptSegmentRecord,
+    TranscriptWriteResult,
     UserRecord,
     VideoPartRecord,
     VideoRecord,
+    _choice,
+    _error_code,
+    _integer,
+    _text,
 )
 
 
@@ -26,7 +40,31 @@ DatabaseConnection: TypeAlias = sqlite3.Connection
 _ARCHIVE_DATABASE_NAME = "archive.db"
 _DATABASE_SUFFIXES = frozenset({".db", ".sqlite", ".sqlite3"})
 _TERMINAL_RUN_OUTCOMES = ALLOWED_RUN_OUTCOMES - frozenset({"running"})
+_TERMINAL_ACQUISITION_OUTCOMES = frozenset({"complete", "partial", "failed"})
+# The attempt outcomes ``record_subtitle_attempt`` owns: evidence of an
+# attempt that produced no transcript.  ``stored`` and ``unchanged`` are the
+# write path's own outcomes and are derived from it, never accepted here.
+_NO_TRANSCRIPT_ATTEMPT_OUTCOMES = ALLOWED_ATTEMPT_OUTCOMES - {"stored", "unchanged"}
 _SCHEMA_RESOURCE = resources.files(__package__).joinpath("schema.sql")
+_TRANSCRIPT_SCHEMA_RESOURCE = resources.files(__package__).joinpath(
+    "schema-transcripts.sql"
+)
+# The columns and objects only the transcript contract has: the bootstrap
+# decision reads the columns, the capability guard reads both.
+_TRANSCRIPT_CONTRACT_COLUMNS = frozenset({"language", "content_sha256"})
+_SUBTITLE_SCHEMA_OBJECTS = (
+    "acquisition_attempts",
+    "acquisition_runs",
+    "v_pending_subtitles",
+)
+
+
+class SchemaContractError(RuntimeError):
+    """Raised when a database does not carry the transcript-schema contract.
+
+    The archive database is rebuildable by policy, so there is no migration
+    path: callers report the rebuild procedure instead of upgrading in place.
+    """
 
 
 def duration_to_ms(seconds: int | float) -> int:
@@ -72,19 +110,79 @@ def _resolve_database_path(path: str | os.PathLike[str]) -> str | os.PathLike[st
     return candidate
 
 
+def _transcripts_columns(connection: sqlite3.Connection) -> frozenset[str]:
+    """Return the column names of ``transcripts``; empty when it is absent."""
+    return frozenset(
+        row[1] for row in connection.execute("PRAGMA table_info(transcripts)")
+    )
+
+
+def _schema_object_names(connection: sqlite3.Connection) -> frozenset[str]:
+    """Return every table and view name the database declares."""
+    return frozenset(
+        row[0]
+        for row in connection.execute(
+            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
+        )
+    )
+
+
+def _accepts_transcript_script(connection: sqlite3.Connection) -> bool:
+    """Report whether the transcript schema script belongs in this database.
+
+    True for a fresh database (``transcripts`` absent) and for a database that
+    already carries the transcript columns; False for a database created
+    before this contract, which keeps the shape it has.
+    """
+    columns = _transcripts_columns(connection)
+    return not columns or _TRANSCRIPT_CONTRACT_COLUMNS <= columns
+
+
+def _has_subtitle_schema(connection: sqlite3.Connection) -> bool:
+    """Report whether the transcript-schema contract is present."""
+    if not _TRANSCRIPT_CONTRACT_COLUMNS <= _transcripts_columns(connection):
+        return False
+    return set(_SUBTITLE_SCHEMA_OBJECTS) <= _schema_object_names(connection)
+
+
 def initialize_schema(connection: sqlite3.Connection) -> sqlite3.Connection:
-    """Initialize ``connection`` from the checked-in schema, idempotently.
+    """Initialize ``connection`` from the checked-in schema scripts, idempotently.
 
-    Enables foreign-key enforcement and commits the schema script.
+    Enables foreign-key enforcement, executes ``schema.sql``, and then applies
+    ``schema-transcripts.sql`` only when ``transcripts`` is absent or already
+    carries the transcript columns.  A database created before that contract
+    keeps the shape it has: the transcript script is skipped, so nothing
+    half-applies and the metadata path keeps working.  Commits the scripts.
     """
     connection.execute("PRAGMA foreign_keys = ON")
     if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
         raise sqlite3.DatabaseError("SQLite foreign-key enforcement could not be enabled")
     connection.executescript(_SCHEMA_RESOURCE.read_text(encoding="utf-8"))
+    if _accepts_transcript_script(connection):
+        connection.executescript(
+            _TRANSCRIPT_SCHEMA_RESOURCE.read_text(encoding="utf-8")
+        )
     connection.commit()
     return connection
 
 
+def require_subtitle_schema(connection: sqlite3.Connection) -> None:
+    """Require the transcript-schema contract on ``connection``.
+
+    The check is structural — the ``transcripts`` columns only this contract
+    has, plus the process-record tables and the pending view — because a stale
+    version stamp can lie and a missing column cannot.  A database that
+    predates the contract raises :class:`SchemaContractError`; the caller
+    reports the rebuild procedure and stops.
+    """
+    if _has_subtitle_schema(connection):
+        return
+    raise SchemaContractError(
+        "archive database predates the transcript schema; rebuild it "
+        "(delete archive.db and re-run fetch-meta)"
+    )
+
+
 def open_database(path: str | os.PathLike[str]) -> DatabaseConnection:
     """Open and initialize ``archive.db`` below an archive root.
 
@@ -107,6 +205,38 @@ def open_database(path: str | os.PathLike[str]) -> DatabaseConnection:
     return connection
 
 
+def _validate_connection(connection: sqlite3.Connection) -> None:
+    """Require the connection state every repository in this module is built on.
+
+    The connection must come with ``row_factory = sqlite3.Row`` and
+    ``PRAGMA foreign_keys`` enabled — exactly the state :func:`open_database`
+    establishes.
+    """
+    if not isinstance(connection, sqlite3.Connection):
+        raise TypeError("connection must be a sqlite3.Connection")
+    if connection.row_factory is not sqlite3.Row:
+        raise TypeError("connection must use the sqlite3.Row row_factory")
+    if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
+        raise ValueError("connection must have PRAGMA foreign_keys enabled")
+
+
+@contextmanager
+def _transaction(connection: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
+    """Serve this module's one transaction discipline for a write group.
+
+    The enclosed writes are committed together on success; any exception rolls
+    the whole group back and is re-raised, so a caller never observes half of a
+    write group.
+    """
+    try:
+        yield connection
+    except BaseException:
+        connection.rollback()
+        raise
+    else:
+        connection.commit()
+
+
 class MetadataRepository:
     """Repository for normalized metadata and ingestion state.
 
@@ -144,24 +274,14 @@ class MetadataRepository:
     """
 
     def __init__(self, connection: sqlite3.Connection):
-        if not isinstance(connection, sqlite3.Connection):
-            raise TypeError("connection must be a sqlite3.Connection")
-        if connection.row_factory is not sqlite3.Row:
-            raise TypeError("connection must use the sqlite3.Row row_factory")
-        if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
-            raise ValueError("connection must have PRAGMA foreign_keys enabled")
+        _validate_connection(connection)
         self.connection = connection
 
     @contextmanager
     def transaction(self) -> Iterator[sqlite3.Connection]:
         """Commit the enclosed repository operations or roll them back."""
-        try:
-            yield self.connection
-        except BaseException:
-            self.connection.rollback()
-            raise
-        else:
-            self.connection.commit()
+        with _transaction(self.connection) as connection:
+            yield connection
 
     def upsert_user(self, user: UserRecord) -> None:
         """Insert or update the current display label for a user."""
@@ -572,11 +692,601 @@ class MetadataRepository:
         ).fetchone()
 
 
+def _language_code(value: object) -> str:
+    """Return the trimmed caption language code ``value`` carries.
+
+    The stored language is the upstream ``lan`` the gateway already normalized,
+    trimmed and non-empty.  Trimming happens here as well so ``' zh-CN '`` and
+    ``'zh-CN'`` name one transcript identity.
+    """
+    return _text(value, "language").strip()
+
+
+def _segment_content_sha256(triples: list[list[int | str]]) -> str:
+    """Digest the canonical segment JSON exactly as the contract defines it."""
+    canonical = json.dumps(triples, ensure_ascii=False, separators=(",", ":"))
+    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
+
+
+class TranscriptRepository:
+    """Repository for acquired transcripts and their acquisition process records.
+
+    Commit boundaries per public method:
+
+    - ``start_acquisition_run`` commits its own insert so a part that fails
+      later can roll back without losing the run parent.
+    - ``finish_acquisition_run`` commits its own terminal transition.
+    - ``record_acquired_transcript`` owns one transaction: it validates the
+      part and the arguments, computes the content hash, appends a version with
+      its segments only when the content is new, writes the attempt row with
+      the resulting ``'stored'``/``'unchanged'`` outcome, and commits — or
+      rolls back wholly, so a version is never stored without the attempt
+      evidence that produced it.
+    - ``record_subtitle_attempt`` owns one transaction for one ``'no-subtitle'``
+      or ``'failed'`` attempt and commits it.
+    - ``read_transcript``, ``list_transcript_versions``,
+      ``list_pending_subtitle_parts``, ``count_pending_subtitle_parts`` and
+      ``list_selected_parts`` never write and never commit: they return the
+      stored rows as they are — a typed ``TranscriptRecord`` for one stored
+      version, ``sqlite3.Row`` view data otherwise.
+
+    Versions are immutable: no method rewrites or deletes a transcript row, a
+    segment row, or an attempt row, and no method recomputes the outcome of a
+    run that already finished.  Attempt evidence is append-only per
+    ``(run_id, video_part_id)`` and is never a terminal per-part state, so a
+    part recorded without a caption stays re-attemptable in a later run.
+
+    Do not compose ``start_acquisition_run``, ``finish_acquisition_run``,
+    ``record_acquired_transcript`` or ``record_subtitle_attempt`` inside a
+    :meth:`MetadataRepository.transaction` group: each commits independently
+    and would commit the enclosing group's earlier writes.
+
+    The connection must come with ``row_factory = sqlite3.Row`` and
+    ``PRAGMA foreign_keys`` enabled — exactly the state :func:`open_database`
+    establishes; the constructor rejects anything else.
+    """
+
+    def __init__(self, connection: sqlite3.Connection):
+        _validate_connection(connection)
+        self.connection = connection
+
+    def start_acquisition_run(self, run: AcquisitionRunRecord) -> None:
+        """Insert one new acquisition run.
+
+        ``run_id`` is the primary key and is never reused: a duplicate raises
+        ``sqlite3.IntegrityError``.  The run is committed on its own so a
+        failed part can roll back without deleting its parent.
+        """
+        if not isinstance(run, AcquisitionRunRecord):
+            raise TypeError("run must be an AcquisitionRunRecord")
+        self.connection.execute(
+            """
+            INSERT INTO acquisition_runs(
+                run_id, kind, selector_kind, selector_target, requested_limit,
+                credential_present, started_at, finished_at, outcome
+            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
+            """,
+            (
+                run.run_id,
+                run.kind,
+                run.selector_kind,
+                run.selector_target,
+                run.requested_limit,
+                int(run.credential_present),
+                run.started_at,
+                run.finished_at,
+                run.outcome,
+            ),
+        )
+        # A run is a lifecycle parent for attempt transactions. Commit its
+        # start independently so a failed part can roll back without it.
+        self.connection.commit()
+
+    def finish_acquisition_run(
+        self, run_id: str, finished_at: int, *, outcome: str | None = None
+    ) -> str:
+        """Finish a run with its outcome and finish timestamp; return the outcome.
+
+        The outcome is the explicit ``outcome`` when given, otherwise it is
+        derived from the run's attempt rows: ``'failed'`` when every attempt of
+        a non-empty set failed, ``'partial'`` when failed and non-failed
+        attempts coexist, and ``'complete'`` otherwise — including a run with
+        no attempts, which means the bounded work set was empty and nothing
+        failed.  The ordering baseline is the run's stored ``started_at``, not
+        a caller-supplied clock.  Re-finishing is rejected: a run whose stored
+        outcome is already terminal raises ``sqlite3.IntegrityError`` and keeps
+        both its outcome and its ``finished_at``.
+
+        ``run_id`` is validated by the same helper every other identifier in
+        this class goes through, so a malformed one is answered with the same
+        bounded message its siblings produce.
+        """
+        run_id = _text(run_id, "run_id")
+        _integer(finished_at, "finished_at", minimum=0)
+        if outcome is not None:
+            _choice(outcome, "outcome", _TERMINAL_ACQUISITION_OUTCOMES)
+        run_row = self.connection.execute(
+            "SELECT started_at, outcome FROM acquisition_runs WHERE run_id = ?",
+            (run_id,),
+        ).fetchone()
+        if run_row is None:
+            raise sqlite3.IntegrityError(f"unknown run_id: {run_id}")
+        if run_row["outcome"] != "running":
+            raise sqlite3.IntegrityError(
+                f"run {run_id} already finished with outcome {run_row['outcome']}"
+            )
+        if finished_at < int(run_row["started_at"]):
+            raise ValueError("finished_at must not precede started_at")
+        resolved = (
+            outcome if outcome is not None else self._run_outcome_from_attempts(run_id)
+        )
+        self.connection.execute(
+            """
+            UPDATE acquisition_runs
+            SET finished_at = ?, outcome = ?
+            WHERE run_id = ? AND outcome = 'running'
+            """,
+            (finished_at, resolved, run_id),
+        )
+        if self.connection.execute("SELECT changes()").fetchone()[0] != 1:
+            raise sqlite3.IntegrityError(f"run {run_id} is no longer running")
+        self.connection.commit()
+        return resolved
+
+    def record_acquired_transcript(
+        self,
+        *,
+        run_id: str,
+        video_part_id: int,
+        source_kind: str,
+        language: str,
+        segments: tuple[TranscriptSegmentRecord, ...],
+        started_at: int,
+        finished_at: int,
+        created_at: int,
+    ) -> TranscriptWriteResult:
+        """Store one acquired caption body as a transcript version, idempotently.
+
+        One transaction: the part and the arguments are validated, the content
+        hash is computed over the canonical segment JSON, and then either
+        nothing is written — when a version of ``(video_part_id, source_kind,
+        language)`` already carries that hash, in which case the attempt is
+        recorded ``'unchanged'`` and points at the version the operator already
+        holds — or the next version is appended with its segments and the
+        attempt is recorded ``'stored'``.  Either way the attempt row is
+        written last and the transaction is committed; any failure — a write
+        violation as much as an attempt row the key ``(run_id,
+        video_part_id)`` already holds — rolls the whole call back, so no
+        version is stored without its attempt evidence.
+
+        Normalization at this boundary, not in the caller: the text of every
+        segment is stored and hashed trimmed, the language is stored trimmed,
+        and a millisecond value above :data:`MAX_TIMELINE_MS` is rejected with
+        ``ValueError`` rather than reaching SQLite as an unrepresentable
+        integer.  ``source_kind`` is one of the two caption kinds; an empty
+        ``segments`` tuple, a non-positive ``video_part_id``, and an
+        ``end_ms``/``start_ms`` violation are rejected with ``ValueError``.
+        The run's outcome is left alone: a finished run is never recomputed.
+        """
+        run_id = _text(run_id, "run_id")
+        video_part_id = _integer(video_part_id, "video_part_id", minimum=1)
+        source_kind = _choice(
+            source_kind, "source_kind", ALLOWED_CAPTION_SOURCE_KINDS
+        )
+        language = _language_code(language)
+        segment_records = tuple(segments)
+        if not segment_records:
+            raise ValueError("a transcript requires at least one segment")
+        started_at = _integer(started_at, "started_at", minimum=0)
+        finished_at = _integer(finished_at, "finished_at", minimum=0)
+        created_at = _integer(created_at, "created_at", minimum=0)
+        if finished_at < started_at:
+            raise ValueError("finished_at must not precede started_at")
+        canonical = self._canonical_segments(segment_records)
+        content_sha256 = _segment_content_sha256(canonical)
+
+        with _transaction(self.connection):
+            self._require_video_part(video_part_id)
+            self._require_acquisition_run(run_id)
+            existing_row = self.connection.execute(
+                """
+                SELECT transcript_id, version
+                FROM transcripts
+                WHERE video_part_id = ? AND source_kind = ? AND language = ?
+                  AND content_sha256 = ?
+                """,
+                (video_part_id, source_kind, language, content_sha256),
+            ).fetchone()
+            if existing_row is None:
+                version = self._next_transcript_version(
+                    video_part_id, source_kind, language
+                )
+                cursor = self.connection.execute(
+                    """
+                    INSERT INTO transcripts(
+                        video_part_id, source_kind, language, model_id, version,
+                        content_sha256, created_at
+                    ) VALUES (?, ?, ?, NULL, ?, ?, ?)
+                    """,
+                    (
+                        video_part_id,
+                        source_kind,
+                        language,
+                        version,
+                        content_sha256,
+                        created_at,
+                    ),
+                )
+                transcript_id = int(cursor.lastrowid)
+                self.connection.executemany(
+                    """
+                    INSERT INTO transcript_segments(
+                        transcript_id, ordinal, start_ms, end_ms, text
+                    ) VALUES (?, ?, ?, ?, ?)
+                    """,
+                    [
+                        (transcript_id, ordinal, start_ms, end_ms, text)
+                        for ordinal, (start_ms, end_ms, text) in enumerate(canonical)
+                    ],
+                )
+                outcome = "stored"
+            else:
+                transcript_id = int(existing_row["transcript_id"])
+                version = int(existing_row["version"])
+                outcome = "unchanged"
+            self.connection.execute(
+                """
+                INSERT INTO acquisition_attempts(
+                    run_id, video_part_id, outcome, error_code, transcript_id,
+                    started_at, finished_at
+                ) VALUES (?, ?, ?, NULL, ?, ?, ?)
+                """,
+                (
+                    run_id,
+                    video_part_id,
+                    outcome,
+                    transcript_id,
+                    started_at,
+                    finished_at,
+                ),
+            )
+
+        return TranscriptWriteResult(
+            outcome=outcome,
+            transcript_id=transcript_id,
+            version=version,
+            content_sha256=content_sha256,
+        )
+
+    def record_subtitle_attempt(
+        self,
+        *,
+        run_id: str,
+        video_part_id: int,
+        outcome: str,
+        error_code: str | None,
+        started_at: int,
+        finished_at: int,
+    ) -> None:
+        """Record one attempt that produced no transcript.
+
+        One transaction for one ``'no-subtitle'``/``'failed'`` attempt.  The
+        attempt table's CHECK matrix is enforced here as well: a ``'failed'``
+        attempt requires a bounded ``error_code``, a ``'no-subtitle'`` attempt
+        carries either no code (upstream listed nothing) or exactly
+        ``'not_found'`` (upstream signalled "not visible"), and neither outcome
+        may reference a transcript.  The attempt row is therefore the whole
+        evidence — append-only per ``(run_id, video_part_id)`` and never a
+        terminal per-part state, so a part recorded here is re-attemptable in a
+        later run.
+        """
+        run_id = _text(run_id, "run_id")
+        video_part_id = _integer(video_part_id, "video_part_id", minimum=1)
+        outcome = _choice(outcome, "outcome", _NO_TRANSCRIPT_ATTEMPT_OUTCOMES)
+        error_code = _error_code(error_code)
+        if outcome == "failed" and error_code is None:
+            raise ValueError("a failed attempt requires a bounded error_code")
+        if outcome == "no-subtitle" and error_code not in (None, "not_found"):
+            raise ValueError(
+                "a no-subtitle attempt carries no error_code or not_found"
+            )
+        started_at = _integer(started_at, "started_at", minimum=0)
+        finished_at = _integer(finished_at, "finished_at", minimum=0)
+        if finished_at < started_at:
+            raise ValueError("finished_at must not precede started_at")
+
+        with _transaction(self.connection):
+            self._require_video_part(video_part_id)
+            self._require_acquisition_run(run_id)
+            self.connection.execute(
+                """
+                INSERT INTO acquisition_attempts(
+                    run_id, video_part_id, outcome, error_code, transcript_id,
+                    started_at, finished_at
+                ) VALUES (?, ?, ?, ?, NULL, ?, ?)
+                """,
+                (run_id, video_part_id, outcome, error_code, started_at, finished_at),
+            )
+
+    def read_transcript(
+        self,
+        video_part_id: int,
+        source_kind: str,
+        language: str,
+        version: int | None = None,
+    ) -> TranscriptRecord | None:
+        """Read one stored transcript version with its segment timeline.
+
+        ``version=None`` reads the latest version of the identity; an explicit
+        ``version`` reads that one, which stays readable after a newer version
+        is written.  ``None`` means the archive holds no such version.  The
+        language is trimmed exactly as the write path trims it, so the identity
+        a caller names here is the identity the store holds, and ``source_kind``
+        is validated against the whole vocabulary the column's CHECK accepts —
+        the ``asr-local`` reservation simply has no rows yet.  Read-only: no
+        write, no commit.
+        """
+        video_part_id = _integer(video_part_id, "video_part_id", minimum=1)
+        source_kind = _choice(source_kind, "source_kind", ALLOWED_SOURCE_KINDS)
+        language = _language_code(language)
+        if version is None:
+            query = (
+                "SELECT * FROM transcripts WHERE video_part_id = ? "
+                "AND source_kind = ? AND language = ? ORDER BY version DESC LIMIT 1"
+            )
+            parameters: tuple[object, ...] = (video_part_id, source_kind, language)
+        else:
+            query = (
+                "SELECT * FROM transcripts WHERE video_part_id = ? "
+                "AND source_kind = ? AND language = ? AND version = ?"
+            )
+            parameters = (
+                video_part_id,
+                source_kind,
+                language,
+                _integer(version, "version", minimum=1),
+            )
+        row = self.connection.execute(query, parameters).fetchone()
+        if row is None:
+            return None
+        transcript_id = int(row["transcript_id"])
+        return TranscriptRecord(
+            transcript_id=transcript_id,
+            video_part_id=int(row["video_part_id"]),
+            source_kind=str(row["source_kind"]),
+            language=str(row["language"]),
+            model_id=None if row["model_id"] is None else int(row["model_id"]),
+            version=int(row["version"]),
+            content_sha256=str(row["content_sha256"]),
+            created_at=int(row["created_at"]),
+            segments=self._stored_segments(transcript_id),
+        )
+
+    def list_transcript_versions(
+        self, video_part_id: int, source_kind: str, language: str
+    ) -> list[sqlite3.Row]:
+        """List one transcript identity's stored versions, oldest first.
+
+        Rows come straight from ``transcripts`` and carry every stored column;
+        an identity the archive does not hold yields an empty list.  Read-only.
+        """
+        video_part_id = _integer(video_part_id, "video_part_id", minimum=1)
+        source_kind = _choice(source_kind, "source_kind", ALLOWED_SOURCE_KINDS)
+        language = _language_code(language)
+        return list(
+            self.connection.execute(
+                """
+                SELECT * FROM transcripts
+                WHERE video_part_id = ? AND source_kind = ? AND language = ?
+                ORDER BY version
+                """,
+                (video_part_id, source_kind, language),
+            ).fetchall()
+        )
+
+    def list_pending_subtitle_parts(
+        self, limit: int | None = None
+    ) -> list[sqlite3.Row]:
+        """Return the captionless parts in the locked work order.
+
+        Rows come straight from the ``v_pending_subtitles`` view, which carries
+        the newest attempt's evidence for every part that holds no transcript.
+        The repository — not the view — imposes the order
+        ``attempted ASC, last_attempt_at ASC, bvid ASC, page_index ASC``, so
+        never-attempted parts come before previously attempted ones and the
+        oldest attempt comes first: successive bounded runs rotate through the
+        captionless backlog instead of re-attempting the same head.  The key
+        list stays verbatim even though ``attempted`` is implied by
+        ``last_attempt_at IS NULL`` (which SQLite sorts first): it is the locked
+        contract the CLI reads, not a query to be shortened.  Read-only.
+        """
+        if limit is not None:
+            if isinstance(limit, bool) or not isinstance(limit, int):
+                raise TypeError("limit must be an integer or None")
+            if limit < 1:
+                raise ValueError("limit must be a positive integer")
+            query = (
+                "SELECT * FROM v_pending_subtitles "
+                "ORDER BY attempted ASC, last_attempt_at ASC, bvid ASC, page_index ASC "
+                "LIMIT ?"
+            )
+            return list(self.connection.execute(query, (limit,)).fetchall())
+        return list(
+            self.connection.execute(
+                "SELECT * FROM v_pending_subtitles "
+                "ORDER BY attempted ASC, last_attempt_at ASC, bvid ASC, page_index ASC"
+            ).fetchall()
+        )
+
+    def count_pending_subtitle_parts(self) -> int:
+        """Count the parts the pending relation holds. Read-only."""
+        return int(
+            self.connection.execute(
+                "SELECT COUNT(*) FROM v_pending_subtitles"
+            ).fetchone()[0]
+        )
+
+    def list_selected_parts(
+        self, bvid: str, page_index: int | None = None
+    ) -> list[sqlite3.Row]:
+        """Return the stored parts of one explicit selection, or no rows.
+
+        Rows come straight from the ``v_video_parts`` view — the view carries the
+        ``work_id``, the user and video context, but not the ``bvid`` itself, so
+        the selector joins the part's own row to reach it — ordered by
+        ``page_index``.  An unknown ``bvid`` — or an unknown ``bvid:pN`` —
+        yields an empty list rather than an invented row, the honest answer the
+        caller reports as a usage error.  An explicit selection is not filtered
+        by ``processing_status``: explicit means explicit, and the evidence a
+        run writes then records what upstream really returned.  Read-only.
+        """
+        bvid = _text(bvid, "bvid")
+        if page_index is None:
+            query = (
+                "SELECT vvp.* FROM v_video_parts AS vvp "
+                "JOIN video_parts AS vp ON vp.video_part_id = vvp.video_part_id "
+                "WHERE vp.bvid = ? ORDER BY vvp.page_index"
+            )
+            parameters: tuple[object, ...] = (bvid,)
+        else:
+            query = (
+                "SELECT vvp.* FROM v_video_parts AS vvp "
+                "JOIN video_parts AS vp ON vp.video_part_id = vvp.video_part_id "
+                "WHERE vp.bvid = ? AND vvp.page_index = ?"
+            )
+            parameters = (bvid, _integer(page_index, "page_index", minimum=0))
+        return list(self.connection.execute(query, parameters).fetchall())
+
+    def _stored_segments(
+        self, transcript_id: int
+    ) -> tuple[TranscriptSegmentRecord, ...]:
+        """Return one version's segments in ordinal order, verbatim as stored."""
+        return tuple(
+            TranscriptSegmentRecord(
+                start_ms=int(row["start_ms"]),
+                end_ms=int(row["end_ms"]),
+                text=str(row["text"]),
+            )
+            for row in self.connection.execute(
+                """
+                SELECT start_ms, end_ms, text FROM transcript_segments
+                WHERE transcript_id = ? ORDER BY ordinal
+                """,
+                (transcript_id,),
+            ).fetchall()
+        )
+
+    def _require_video_part(self, video_part_id: int) -> None:
+        """Require that ``video_part_id`` names a part the archive already holds.
+
+        Bounded, named evidence instead of the raw foreign-key message: both
+        write paths reference the part, so an unknown one fails the whole call
+        before anything is written.
+        """
+        row = self.connection.execute(
+            "SELECT 1 FROM video_parts WHERE video_part_id = ?", (video_part_id,)
+        ).fetchone()
+        if row is None:
+            raise sqlite3.IntegrityError(f"unknown video_part_id: {video_part_id}")
+
+    def _require_acquisition_run(self, run_id: str) -> None:
+        """Require that ``run_id`` names an acquisition run.
+
+        The attempt row that references the run is written last, so an unknown
+        run leaves no transcript version or segment behind.
+        """
+        row = self.connection.execute(
+            "SELECT 1 FROM acquisition_runs WHERE run_id = ?", (run_id,)
+        ).fetchone()
+        if row is None:
+            raise sqlite3.IntegrityError(f"unknown run_id: {run_id}")
+
+    def _canonical_segments(
+        self, segments: tuple[TranscriptSegmentRecord, ...]
+    ) -> list[list[int | str]]:
+        """Return the ordered ``[start_ms, end_ms, text]`` triples to store.
+
+        The storage boundary re-validates the timeline instead of trusting the
+        caller: a segment below zero, an ``end_ms`` that does not exceed its
+        ``start_ms``, a millisecond value above :data:`MAX_TIMELINE_MS`, or
+        text that is empty once trimmed raises ``ValueError``.  The text of
+        each triple is its trimmed form — what the row stores and what the
+        content hash covers — and the ordinal is the position, so upstream
+        order is preserved verbatim, overlaps included.
+        """
+        canonical: list[list[int | str]] = []
+        for index, segment in enumerate(segments):
+            if not isinstance(segment, TranscriptSegmentRecord):
+                raise TypeError(
+                    f"segments[{index}] must be a TranscriptSegmentRecord"
+                )
+            start_ms = _integer(
+                segment.start_ms,
+                f"segments[{index}].start_ms",
+                minimum=0,
+                maximum=MAX_TIMELINE_MS,
+            )
+            end_ms = _integer(
+                segment.end_ms,
+                f"segments[{index}].end_ms",
+                minimum=1,
+                maximum=MAX_TIMELINE_MS,
+            )
+            if end_ms <= start_ms:
+                raise ValueError(
+                    f"segments[{index}].end_ms must be greater than start_ms"
+                )
+            text = segment.text.strip()
+            if not text:
+                raise ValueError(f"segments[{index}].text must not be empty")
+            canonical.append([start_ms, end_ms, text])
+        return canonical
+
+    def _next_transcript_version(
+        self, video_part_id: int, source_kind: str, language: str
+    ) -> int:
+        """Return the next version number of one transcript identity."""
+        row = self.connection.execute(
+            """
+            SELECT COALESCE(MAX(version), 0) + 1 AS next_version
+            FROM transcripts
+            WHERE video_part_id = ? AND source_kind = ? AND language = ?
+            """,
+            (video_part_id, source_kind, language),
+        ).fetchone()
+        return int(row["next_version"])
+
+    def _run_outcome_from_attempts(self, run_id: str) -> str:
+        """Derive a run's outcome from the attempt rows it holds."""
+        counts = {
+            str(row["outcome"]): int(row["attempts"])
+            for row in self.connection.execute(
+                """
+                SELECT outcome, COUNT(*) AS attempts
+                FROM acquisition_attempts
+                WHERE run_id = ?
+                GROUP BY outcome
+                """,
+                (run_id,),
+            ).fetchall()
+        }
+        attempts = sum(counts.values())
+        failed = counts.get("failed", 0)
+        if failed and failed == attempts:
+            return "failed"
+        if failed:
+            return "partial"
+        return "complete"
+
+
 __all__ = [
     "DatabaseConnection",
     "MetadataRepository",
+    "SchemaContractError",
+    "TranscriptRepository",
     "duration_to_ms",
     "initialize_schema",
     "normalize_page_index",
     "open_database",
+    "require_subtitle_schema",
 ]
diff --git a/bilibili-asr-archive/src/bili_asr/storage/models.py b/bilibili-asr-archive/src/bili_asr/storage/models.py
index 780b42a..a4c3e08 100644
--- a/bilibili-asr-archive/src/bili_asr/storage/models.py
+++ b/bilibili-asr-archive/src/bili_asr/storage/models.py
@@ -16,6 +16,10 @@ ProcessingStatus = Literal["discovered", "metadata_collected", "gone"]
 RunOutcome = Literal["running", "complete", "limited", "risk_interrupted", "failed"]
 PageOutcome = Literal["ok", "empty", "risk_interrupted", "failed"]
 CursorState = Literal["ready", "complete", "limited", "risk_interrupted"]
+AcquisitionKind = Literal["subtitle", "audio", "asr"]
+AcquisitionOutcome = Literal["running", "complete", "partial", "failed"]
+AttemptOutcome = Literal["stored", "unchanged", "no-subtitle", "failed"]
+SourceKind = Literal["subtitle-ai", "subtitle-cc", "asr-local"]
 
 _ALLOWED_PROCESSING_STATUS = frozenset({"discovered", "metadata_collected", "gone"})
 _ALLOWED_RUN_OUTCOMES = frozenset(
@@ -23,14 +27,38 @@ _ALLOWED_RUN_OUTCOMES = frozenset(
 )
 _ALLOWED_PAGE_OUTCOMES = frozenset({"ok", "empty", "risk_interrupted", "failed"})
 _ALLOWED_CURSOR_STATES = frozenset({"ready", "complete", "limited", "risk_interrupted"})
+_ALLOWED_ACQUISITION_KINDS = frozenset({"subtitle", "audio", "asr"})
+_ALLOWED_ACQUISITION_OUTCOMES = frozenset({"running", "complete", "partial", "failed"})
+_ALLOWED_ATTEMPT_OUTCOMES = frozenset({"stored", "unchanged", "no-subtitle", "failed"})
+_ALLOWED_SOURCE_KINDS = frozenset({"subtitle-ai", "subtitle-cc", "asr-local"})
+_ALLOWED_SELECTOR_KINDS = frozenset({"pending", "bvid"})
+# The two outcomes a transcript write can report; the other attempt outcomes
+# record an acquisition that produced no transcript at all.
+_ALLOWED_TRANSCRIPT_WRITE_OUTCOMES = frozenset({"stored", "unchanged"})
+# The largest millisecond position a stored caption timeline accepts: about 31
+# years, far beyond any caption and far below the 64-bit integer SQLite binds,
+# so an upstream value that cannot be a caption timestamp is rejected with a
+# bounded ``ValueError`` instead of an ``OverflowError``.  The storage
+# boundary enforces it (``TranscriptRepository.record_acquired_transcript``),
+# not the segment record below, which validates the shape of one row.
+MAX_TIMELINE_MS = 10**12
 _ERROR_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]+$")
+_SHA256_HEX_PATTERN = re.compile(r"^[0-9a-f]{64}$")
 
 
-def _integer(value: object, field: str, *, minimum: int | None = None) -> int:
+def _integer(
+    value: object,
+    field: str,
+    *,
+    minimum: int | None = None,
+    maximum: int | None = None,
+) -> int:
     if isinstance(value, bool) or not isinstance(value, int):
         raise TypeError(f"{field} must be an integer")
     if minimum is not None and value < minimum:
         raise ValueError(f"{field} must be at least {minimum}")
+    if maximum is not None and value > maximum:
+        raise ValueError(f"{field} must be at most {maximum}")
     return value
 
 
@@ -62,6 +90,36 @@ def _choice(value: object, field: str, allowed: frozenset[str]) -> str:
     return value
 
 
+def _boolean(value: object, field: str) -> bool:
+    if not isinstance(value, bool):
+        raise TypeError(f"{field} must be a boolean")
+    return value
+
+
+def _caption_text(value: object, field: str = "text") -> str:
+    """Validate caption text: a string non-empty after stripping.
+
+    Unlike :func:`_text`, control characters inside the string are kept — the
+    stored caption is verbatim apart from trimming.  Trimming is the storage
+    boundary's job, not this validator's: ``TranscriptRepository`` stores and
+    hashes the stripped form, so a caption's content identity never depends on
+    the whitespace a caller happens to carry.
+    """
+    if not isinstance(value, str):
+        raise TypeError(f"{field} must be a string")
+    if not value.strip():
+        raise ValueError(f"{field} must not be empty")
+    return value
+
+
+def _content_sha256(value: object, field: str = "content_sha256") -> str:
+    if not isinstance(value, str):
+        raise TypeError(f"{field} must be a string")
+    if _SHA256_HEX_PATTERN.fullmatch(value) is None:
+        raise ValueError(f"{field} must be 64 lowercase hexadecimal characters")
+    return value
+
+
 @dataclass(frozen=True, slots=True)
 class UserRecord:
     """Current operational metadata for one Bilibili user."""
@@ -238,14 +296,161 @@ class DiscoveryRecord:
         _integer(self.discovered_at, "discovered_at", minimum=0)
 
 
+@dataclass(frozen=True, slots=True)
+class TranscriptSegmentRecord:
+    """One caption row of one transcript, on the millisecond timeline.
+
+    The invariant mirrors the gateway's ``SubtitleSegment`` so the service
+    maps one DTO onto the other field for field: ``end_ms > start_ms >= 0``
+    and ``text`` non-empty after stripping.  ``ordinal`` is positional and is
+    assigned by the repository, never carried here.
+
+    The record carries the text a caller supplies; the storage boundary stores
+    and hashes its trimmed form, and it rejects a millisecond value above
+    :data:`MAX_TIMELINE_MS` — the two normalization rules this record cannot
+    state on its own.
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
+        _caption_text(self.text)
+
+
+@dataclass(frozen=True, slots=True)
+class TranscriptWriteResult:
+    """What one transcript write did to the store.
+
+    ``outcome`` is ``'stored'`` when the call appended a version and
+    ``'unchanged'`` when the store already held that content; either way
+    ``transcript_id``, ``version`` and ``content_sha256`` describe the version
+    the operator now holds.
+    """
+
+    outcome: str
+    transcript_id: int
+    version: int
+    content_sha256: str
+
+    def __post_init__(self) -> None:
+        _choice(self.outcome, "outcome", _ALLOWED_TRANSCRIPT_WRITE_OUTCOMES)
+        _integer(self.transcript_id, "transcript_id", minimum=1)
+        _integer(self.version, "version", minimum=1)
+        _content_sha256(self.content_sha256)
+
+
+@dataclass(frozen=True, slots=True)
+class TranscriptRecord:
+    """One stored transcript version together with its segment timeline.
+
+    What a default read of a transcript answers: the whole ``transcripts`` row
+    — identity, language, version, content hash, creation time — plus its
+    segments in ordinal order, which is the caller order the write path stored,
+    never re-sorted and never de-overlapped.  ``model_id`` is ``NULL`` for
+    caption rows, and ``segments`` is never empty, because a transcript is only
+    ever written with at least one segment.
+    """
+
+    transcript_id: int
+    video_part_id: int
+    source_kind: SourceKind
+    language: str
+    model_id: int | None
+    version: int
+    content_sha256: str
+    created_at: int
+    segments: tuple[TranscriptSegmentRecord, ...]
+
+    def __post_init__(self) -> None:
+        _integer(self.transcript_id, "transcript_id", minimum=1)
+        _integer(self.video_part_id, "video_part_id", minimum=1)
+        _choice(self.source_kind, "source_kind", _ALLOWED_SOURCE_KINDS)
+        _text(self.language, "language")
+        if self.model_id is not None:
+            _integer(self.model_id, "model_id", minimum=1)
+        _integer(self.version, "version", minimum=1)
+        _content_sha256(self.content_sha256)
+        _integer(self.created_at, "created_at", minimum=0)
+        if not isinstance(self.segments, tuple):
+            raise TypeError("segments must be a tuple")
+        if not self.segments:
+            raise ValueError("a stored transcript carries at least one segment")
+        for index, segment in enumerate(self.segments):
+            if not isinstance(segment, TranscriptSegmentRecord):
+                raise TypeError(
+                    f"segments[{index}] must be a TranscriptSegmentRecord"
+                )
+
+
+@dataclass(frozen=True, slots=True)
+class AcquisitionRunRecord:
+    """One acquisition run of one kind.
+
+    ``selector_kind`` and ``selector_target`` are one fact: a bounded
+    ``pending`` run carries no target, an explicit ``bvid`` run must carry
+    one.  ``credential_present`` is run-scoped, so an attempt recorded without
+    a caption stays interpretable afterwards.
+    """
+
+    run_id: str
+    kind: AcquisitionKind
+    selector_kind: str
+    selector_target: str | None
+    requested_limit: int | None
+    credential_present: bool
+    started_at: int
+    finished_at: int | None = None
+    outcome: AcquisitionOutcome = "running"
+
+    def __post_init__(self) -> None:
+        _text(self.run_id, "run_id")
+        _choice(self.kind, "kind", _ALLOWED_ACQUISITION_KINDS)
+        selector_kind = _choice(
+            self.selector_kind, "selector_kind", _ALLOWED_SELECTOR_KINDS
+        )
+        if selector_kind == "pending":
+            if self.selector_target is not None:
+                raise ValueError("a pending selector carries no selector_target")
+        elif self.selector_target is None:
+            raise ValueError("a bvid selector requires a selector_target")
+        else:
+            _text(self.selector_target, "selector_target")
+        if self.requested_limit is not None:
+            _integer(self.requested_limit, "requested_limit", minimum=1)
+        _boolean(self.credential_present, "credential_present")
+        _integer(self.started_at, "started_at", minimum=0)
+        if self.finished_at is not None:
+            _integer(self.finished_at, "finished_at", minimum=0)
+            if self.finished_at < self.started_at:
+                raise ValueError("finished_at must not precede started_at")
+        outcome = _choice(self.outcome, "outcome", _ALLOWED_ACQUISITION_OUTCOMES)
+        if outcome != "running" and self.finished_at is None:
+            raise ValueError("a terminal run outcome requires finished_at")
+
+
 __all__ = [
+    "AcquisitionKind",
+    "AcquisitionOutcome",
+    "AcquisitionRunRecord",
+    "AttemptOutcome",
     "CursorRecord",
     "DiscoveryRecord",
     "IngestionPageRecord",
     "IngestionRunRecord",
+    "MAX_TIMELINE_MS",
     "PageOutcome",
     "ProcessingStatus",
     "RunOutcome",
+    "SourceKind",
+    "TranscriptRecord",
+    "TranscriptSegmentRecord",
+    "TranscriptWriteResult",
     "UserRecord",
     "VideoPartRecord",
     "VideoRecord",
@@ -260,11 +465,25 @@ ALLOWED_PAGE_OUTCOMES = _ALLOWED_PAGE_OUTCOMES
 ALLOWED_RUN_OUTCOMES = _ALLOWED_RUN_OUTCOMES
 ALLOWED_CURSOR_STATES = _ALLOWED_CURSOR_STATES
 ALLOWED_PROCESSING_STATUS = _ALLOWED_PROCESSING_STATUS
+ALLOWED_ACQUISITION_KINDS = _ALLOWED_ACQUISITION_KINDS
+ALLOWED_ACQUISITION_OUTCOMES = _ALLOWED_ACQUISITION_OUTCOMES
+ALLOWED_ATTEMPT_OUTCOMES = _ALLOWED_ATTEMPT_OUTCOMES
+ALLOWED_SOURCE_KINDS = _ALLOWED_SOURCE_KINDS
+# The two source kinds whose content identity the partial index
+# ``ux_transcripts_subtitle_content`` enforces.  ``asr-local`` keeps its own
+# (per model/run) identity rule and is owned by the audio/ASR iteration, so a
+# caption write never accepts it.
+ALLOWED_CAPTION_SOURCE_KINDS = _ALLOWED_SOURCE_KINDS - {"asr-local"}
 
 __all__ += [
+    "ALLOWED_ACQUISITION_KINDS",
+    "ALLOWED_ACQUISITION_OUTCOMES",
+    "ALLOWED_ATTEMPT_OUTCOMES",
+    "ALLOWED_CAPTION_SOURCE_KINDS",
     "ALLOWED_CURSOR_STATES",
     "ALLOWED_PAGE_OUTCOMES",
     "ALLOWED_PROCESSING_STATUS",
     "ALLOWED_RUN_OUTCOMES",
+    "ALLOWED_SOURCE_KINDS",
     "validate_error_code",
 ]
diff --git a/bilibili-asr-archive/src/bili_asr/storage/schema-transcripts.sql b/bilibili-asr-archive/src/bili_asr/storage/schema-transcripts.sql
new file mode 100644
index 0000000..3cb00d5
--- /dev/null
+++ b/bilibili-asr-archive/src/bili_asr/storage/schema-transcripts.sql
@@ -0,0 +1,141 @@
+-- Transcript and acquisition process-record contract.
+--
+-- Applied by ``initialize_schema`` only to a database that is fresh
+-- (``transcripts`` absent) or already carries this contract; a database
+-- created before it keeps the shape it has, because ``CREATE TABLE IF NOT
+-- EXISTS`` cannot widen an existing unique constraint.  The archive database
+-- is rebuildable by policy: there is no migration, no backfill, and no
+-- compatibility reader.  Foreign-key enforcement is a connection property
+-- owned by ``initialize_schema`` (``PRAGMA foreign_keys = ON``, verified),
+-- so this script declares no pragma of its own.
+
+CREATE TABLE IF NOT EXISTS transcripts (
+    transcript_id INTEGER PRIMARY KEY,
+    video_part_id INTEGER NOT NULL,
+    source_kind TEXT NOT NULL CHECK (
+        source_kind IN ('subtitle-ai', 'subtitle-cc', 'asr-local')
+    ),
+    language TEXT NOT NULL CHECK (length(trim(language)) > 0),
+    model_id INTEGER,
+    version INTEGER NOT NULL CHECK (version > 0),
+    content_sha256 TEXT NOT NULL CHECK (
+        length(content_sha256) = 64 AND content_sha256 = lower(content_sha256)
+    ),
+    created_at INTEGER NOT NULL,
+    UNIQUE (video_part_id, source_kind, language, version),
+    FOREIGN KEY (video_part_id) REFERENCES video_parts(video_part_id) ON DELETE RESTRICT,
+    FOREIGN KEY (model_id) REFERENCES asr_models(model_id) ON DELETE RESTRICT
+);
+
+-- Content identity for the caption kinds only.  ``asr-local`` keeps its own
+-- (per model/run) identity rule; that decision belongs to the audio/ASR
+-- iteration, so this index does not pre-empt it.
+CREATE UNIQUE INDEX IF NOT EXISTS ux_transcripts_subtitle_content
+    ON transcripts(video_part_id, source_kind, language, content_sha256)
+    WHERE source_kind IN ('subtitle-ai', 'subtitle-cc');
+
+CREATE TABLE IF NOT EXISTS transcript_segments (
+    transcript_id INTEGER NOT NULL,
+    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
+    start_ms INTEGER NOT NULL CHECK (start_ms >= 0),
+    end_ms INTEGER NOT NULL CHECK (end_ms > start_ms),
+    text TEXT NOT NULL,
+    PRIMARY KEY (transcript_id, ordinal),
+    FOREIGN KEY (transcript_id) REFERENCES transcripts(transcript_id) ON DELETE RESTRICT
+);
+
+-- One row per acquisition run of one kind.  Subtitle/transcript process
+-- records live here rather than in the metadata-scoped ``ingestion_runs``,
+-- whose cursor semantics say nothing true about a per-part caption probe.
+CREATE TABLE IF NOT EXISTS acquisition_runs (
+    run_id TEXT PRIMARY KEY,
+    kind TEXT NOT NULL CHECK (kind IN ('subtitle', 'audio', 'asr')),
+    selector_kind TEXT NOT NULL CHECK (selector_kind IN ('pending', 'bvid')),
+    selector_target TEXT,
+    requested_limit INTEGER CHECK (requested_limit IS NULL OR requested_limit > 0),
+    credential_present INTEGER NOT NULL CHECK (credential_present IN (0, 1)),
+    started_at INTEGER NOT NULL,
+    finished_at INTEGER,
+    outcome TEXT NOT NULL CHECK (
+        outcome IN ('running', 'complete', 'partial', 'failed')
+    ),
+    CHECK (
+        (selector_kind = 'pending' AND selector_target IS NULL)
+        OR (selector_kind = 'bvid' AND selector_target IS NOT NULL)
+    ),
+    CHECK (finished_at IS NULL OR finished_at >= started_at)
+);
+
+-- One evidence row per attempted part, scoped to its run: append-only, and
+-- never a terminal per-part state, so a part recorded without a caption stays
+-- re-attemptable.
+CREATE TABLE IF NOT EXISTS acquisition_attempts (
+    run_id TEXT NOT NULL,
+    video_part_id INTEGER NOT NULL,
+    outcome TEXT NOT NULL CHECK (
+        outcome IN ('stored', 'unchanged', 'no-subtitle', 'failed')
+    ),
+    error_code TEXT CHECK (error_code IS NULL OR length(error_code) <= 64),
+    transcript_id INTEGER,
+    started_at INTEGER NOT NULL,
+    finished_at INTEGER NOT NULL,
+    PRIMARY KEY (run_id, video_part_id),
+    FOREIGN KEY (run_id) REFERENCES acquisition_runs(run_id) ON DELETE RESTRICT,
+    FOREIGN KEY (video_part_id) REFERENCES video_parts(video_part_id) ON DELETE RESTRICT,
+    FOREIGN KEY (transcript_id) REFERENCES transcripts(transcript_id) ON DELETE RESTRICT,
+    CHECK (
+        (outcome = 'failed'
+            AND error_code IS NOT NULL AND transcript_id IS NULL)
+        OR (outcome = 'no-subtitle'
+            AND (error_code IS NULL OR error_code = 'not_found')
+            AND transcript_id IS NULL)
+        OR (outcome IN ('stored', 'unchanged')
+            AND error_code IS NULL AND transcript_id IS NOT NULL)
+    ),
+    CHECK (finished_at >= started_at)
+);
+
+CREATE INDEX IF NOT EXISTS ix_acquisition_attempts_part_time
+    ON acquisition_attempts(video_part_id, finished_at);
+
+-- The pending-work relation: one query, no per-part N+1.  Parts that hold a
+-- transcript, and parts upstream reported as gone, are not pending.  A part
+-- attempted without a caption stays pending and brings its newest attempt's
+-- evidence with it, so "never attempted" (attempted = 0) is distinguishable
+-- from "attempted and still captionless" (attempted = 1).
+CREATE VIEW IF NOT EXISTS v_pending_subtitles AS
+WITH subtitle_attempts AS (
+    SELECT
+        aa.video_part_id,
+        aa.finished_at,
+        aa.outcome,
+        aa.error_code,
+        ar.credential_present,
+        ROW_NUMBER() OVER (
+            PARTITION BY aa.video_part_id
+            ORDER BY aa.finished_at DESC, aa.run_id DESC
+        ) AS recency
+    FROM acquisition_attempts AS aa
+    JOIN acquisition_runs AS ar ON ar.run_id = aa.run_id
+    WHERE ar.kind = 'subtitle'
+)
+SELECT
+    vp.video_part_id,
+    vp.bvid || ':p' || vp.page_index AS work_id,
+    vp.bvid,
+    vp.page_index,
+    vp.cid,
+    vp.title AS part_title,
+    vp.duration_ms,
+    CASE WHEN latest.video_part_id IS NULL THEN 0 ELSE 1 END AS attempted,
+    latest.finished_at AS last_attempt_at,
+    latest.outcome AS last_attempt_outcome,
+    latest.error_code AS last_attempt_error_code,
+    latest.credential_present AS last_attempt_credential_present
+FROM video_parts AS vp
+LEFT JOIN subtitle_attempts AS latest
+    ON latest.video_part_id = vp.video_part_id AND latest.recency = 1
+WHERE vp.processing_status <> 'gone'
+  AND NOT EXISTS (
+      SELECT 1 FROM transcripts AS t WHERE t.video_part_id = vp.video_part_id
+  );
diff --git a/bilibili-asr-archive/src/bili_asr/storage/schema.sql b/bilibili-asr-archive/src/bili_asr/storage/schema.sql
index d83e669..675d9e8 100644
--- a/bilibili-asr-archive/src/bili_asr/storage/schema.sql
+++ b/bilibili-asr-archive/src/bili_asr/storage/schema.sql
@@ -117,29 +117,10 @@ CREATE TABLE IF NOT EXISTS asr_models (
     UNIQUE (model_name, revision)
 );
 
-CREATE TABLE IF NOT EXISTS transcripts (
-    transcript_id INTEGER PRIMARY KEY,
-    video_part_id INTEGER NOT NULL,
-    source_kind TEXT NOT NULL CHECK (
-        source_kind IN ('subtitle-ai', 'subtitle-cc', 'asr-local')
-    ),
-    model_id INTEGER,
-    version INTEGER NOT NULL CHECK (version > 0),
-    created_at INTEGER NOT NULL,
-    UNIQUE (video_part_id, source_kind, version),
-    FOREIGN KEY (video_part_id) REFERENCES video_parts(video_part_id) ON DELETE RESTRICT,
-    FOREIGN KEY (model_id) REFERENCES asr_models(model_id) ON DELETE RESTRICT
-);
-
-CREATE TABLE IF NOT EXISTS transcript_segments (
-    transcript_id INTEGER NOT NULL,
-    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
-    start_ms INTEGER NOT NULL CHECK (start_ms >= 0),
-    end_ms INTEGER NOT NULL CHECK (end_ms > start_ms),
-    text TEXT NOT NULL,
-    PRIMARY KEY (transcript_id, ordinal),
-    FOREIGN KEY (transcript_id) REFERENCES transcripts(transcript_id) ON DELETE RESTRICT
-);
+-- The transcript and acquisition process-record tables live in their own
+-- resource (``schema-transcripts.sql``): ``initialize_schema`` applies them
+-- only to a database that is fresh or already carries that contract, so a
+-- database created before it keeps the shape it has.
 
 CREATE VIEW IF NOT EXISTS v_video_parts AS
 SELECT
diff --git a/bilibili-asr-archive/tests/test_storage_schema.py b/bilibili-asr-archive/tests/test_storage_schema.py
index 7ab7e24..1621515 100644
--- a/bilibili-asr-archive/tests/test_storage_schema.py
+++ b/bilibili-asr-archive/tests/test_storage_schema.py
@@ -12,16 +12,35 @@ from typing import get_args
 
 import pytest
 
-from bili_asr.storage import duration_to_ms, normalize_page_index, open_database
+from bili_asr.storage import (
+    MetadataRepository,
+    SchemaContractError,
+    duration_to_ms,
+    normalize_page_index,
+    open_database,
+    require_subtitle_schema,
+)
 from bili_asr.storage.models import (
+    ALLOWED_ACQUISITION_KINDS,
+    ALLOWED_ACQUISITION_OUTCOMES,
+    ALLOWED_ATTEMPT_OUTCOMES,
     ALLOWED_CURSOR_STATES,
     ALLOWED_PAGE_OUTCOMES,
     ALLOWED_PROCESSING_STATUS,
     ALLOWED_RUN_OUTCOMES,
+    ALLOWED_SOURCE_KINDS,
+    AcquisitionKind,
+    AcquisitionOutcome,
+    AcquisitionRunRecord,
+    AttemptOutcome,
+    CursorRecord,
     CursorState,
     PageOutcome,
     ProcessingStatus,
     RunOutcome,
+    SourceKind,
+    TranscriptSegmentRecord,
+    TranscriptWriteResult,
 )
 
 
@@ -38,8 +57,15 @@ BASE_TABLES = {
     "asr_models",
     "transcripts",
     "transcript_segments",
+    "acquisition_runs",
+    "acquisition_attempts",
+}
+VIEWS = {
+    "v_video_parts",
+    "v_ingestion_run_stats",
+    "v_pending_metadata",
+    "v_pending_subtitles",
 }
-VIEWS = {"v_video_parts", "v_ingestion_run_stats", "v_pending_metadata"}
 EXPECTED_TABLE_COLUMNS = {
     "bilibili_users": ["mid", "display_name", "created_at", "updated_at"],
     "videos": [
@@ -116,11 +142,33 @@ EXPECTED_TABLE_COLUMNS = {
         "transcript_id",
         "video_part_id",
         "source_kind",
+        "language",
         "model_id",
         "version",
+        "content_sha256",
         "created_at",
     ],
     "transcript_segments": ["transcript_id", "ordinal", "start_ms", "end_ms", "text"],
+    "acquisition_runs": [
+        "run_id",
+        "kind",
+        "selector_kind",
+        "selector_target",
+        "requested_limit",
+        "credential_present",
+        "started_at",
+        "finished_at",
+        "outcome",
+    ],
+    "acquisition_attempts": [
+        "run_id",
+        "video_part_id",
+        "outcome",
+        "error_code",
+        "transcript_id",
+        "started_at",
+        "finished_at",
+    ],
 }
 EXPECTED_FOREIGN_KEYS = {
     "videos": (("mid", "bilibili_users", "mid"),),
@@ -141,13 +189,18 @@ EXPECTED_FOREIGN_KEYS = {
         ("model_id", "asr_models", "model_id"),
     ),
     "transcript_segments": (("transcript_id", "transcripts", "transcript_id"),),
+    "acquisition_attempts": (
+        ("run_id", "acquisition_runs", "run_id"),
+        ("video_part_id", "video_parts", "video_part_id"),
+        ("transcript_id", "transcripts", "transcript_id"),
+    ),
 }
 EXPECTED_UNIQUE_CONSTRAINTS = {
     "videos": (("aid",),),
     "video_parts": (("bvid", "page_index"),),
     "audio_objects": (("sha256",), ("storage_key",)),
     "asr_models": (("model_name", "revision"),),
-    "transcripts": (("video_part_id", "source_kind", "version"),),
+    "transcripts": (("video_part_id", "source_kind", "language", "version"),),
 }
 EXPECTED_PRIMARY_KEY_INDEXES = {
     "videos": (("bvid",),),
@@ -156,6 +209,31 @@ EXPECTED_PRIMARY_KEY_INDEXES = {
     "ingestion_discoveries": (("run_id", "page_number", "bvid"),),
     "part_audio_objects": (("video_part_id", "audio_id"),),
     "transcript_segments": (("transcript_id", "ordinal"),),
+    "acquisition_runs": (("run_id",),),
+    "acquisition_attempts": (("run_id", "video_part_id"),),
+}
+EXPECTED_INDEXES = {
+    "transcripts": (
+        (
+            "ux_transcripts_subtitle_content",
+            ("video_part_id", "source_kind", "language", "content_sha256"),
+            True,
+            True,
+        ),
+    ),
+    "acquisition_attempts": (
+        (
+            "ix_acquisition_attempts_part_time",
+            ("video_part_id", "finished_at"),
+            False,
+            False,
+        ),
+    ),
+}
+EXPECTED_PARTIAL_INDEX_CLAUSES = {
+    "ux_transcripts_subtitle_content": (
+        "WHERE source_kind IN ('subtitle-ai', 'subtitle-cc')"
+    ),
 }
 EXPECTED_CHECK_ENUMERATIONS = {
     "video_parts": (
@@ -169,15 +247,120 @@ EXPECTED_CHECK_ENUMERATIONS = {
         "state IN ('ready', 'complete', 'limited', 'risk_interrupted')",
     ),
     "ingestion_pages": ("outcome IN ('ok', 'empty', 'risk_interrupted', 'failed')",),
-    "transcripts": ("source_kind IN ('subtitle-ai', 'subtitle-cc', 'asr-local')",),
+    "transcripts": (
+        "source_kind IN ('subtitle-ai', 'subtitle-cc', 'asr-local')",
+        "length(trim(language)) > 0",
+        "length(content_sha256) = 64 AND content_sha256 = lower(content_sha256)",
+        "UNIQUE (video_part_id, source_kind, language, version)",
+    ),
+    "transcript_segments": (
+        "ordinal >= 0",
+        "start_ms >= 0",
+        "end_ms > start_ms",
+    ),
+    "acquisition_runs": (
+        "kind IN ('subtitle', 'audio', 'asr')",
+        "selector_kind IN ('pending', 'bvid')",
+        "requested_limit IS NULL OR requested_limit > 0",
+        "credential_present IN (0, 1)",
+        "outcome IN ('running', 'complete', 'partial', 'failed')",
+        "(selector_kind = 'pending' AND selector_target IS NULL) "
+        "OR (selector_kind = 'bvid' AND selector_target IS NOT NULL)",
+        "finished_at IS NULL OR finished_at >= started_at",
+    ),
+    "acquisition_attempts": (
+        "outcome IN ('stored', 'unchanged', 'no-subtitle', 'failed')",
+        "error_code IS NULL OR length(error_code) <= 64",
+        "PRIMARY KEY (run_id, video_part_id)",
+        "outcome = 'failed' AND error_code IS NOT NULL AND transcript_id IS NULL",
+        "(error_code IS NULL OR error_code = 'not_found') AND transcript_id IS NULL",
+        "outcome IN ('stored', 'unchanged') AND error_code IS NULL "
+        "AND transcript_id IS NOT NULL",
+        "CHECK (finished_at >= started_at)",
+    ),
 }
 EXPECTED_VIEW_WORK_ID_EXPRESSION = "vp.bvid || ':p' || vp.page_index AS work_id"
+EXPECTED_VIEW_COLUMNS = {
+    "v_pending_subtitles": [
+        "video_part_id",
+        "work_id",
+        "bvid",
+        "page_index",
+        "cid",
+        "part_title",
+        "duration_ms",
+        "attempted",
+        "last_attempt_at",
+        "last_attempt_outcome",
+        "last_attempt_error_code",
+        "last_attempt_credential_present",
+    ],
+}
 EXPECTED_ENUM_COLUMNS = {
     ("video_parts", "processing_status"): ALLOWED_PROCESSING_STATUS,
     ("ingestion_runs", "outcome"): ALLOWED_RUN_OUTCOMES,
     ("ingestion_cursors", "state"): ALLOWED_CURSOR_STATES,
     ("ingestion_pages", "outcome"): ALLOWED_PAGE_OUTCOMES,
+    ("transcripts", "source_kind"): ALLOWED_SOURCE_KINDS,
+    ("acquisition_runs", "kind"): ALLOWED_ACQUISITION_KINDS,
+    ("acquisition_runs", "outcome"): ALLOWED_ACQUISITION_OUTCOMES,
+    ("acquisition_attempts", "outcome"): ALLOWED_ATTEMPT_OUTCOMES,
 }
+EXPECTED_LITERAL_SETS = (
+    (ProcessingStatus, ALLOWED_PROCESSING_STATUS),
+    (RunOutcome, ALLOWED_RUN_OUTCOMES),
+    (PageOutcome, ALLOWED_PAGE_OUTCOMES),
+    (CursorState, ALLOWED_CURSOR_STATES),
+    (SourceKind, ALLOWED_SOURCE_KINDS),
+    (AcquisitionKind, ALLOWED_ACQUISITION_KINDS),
+    (AcquisitionOutcome, ALLOWED_ACQUISITION_OUTCOMES),
+    (AttemptOutcome, ALLOWED_ATTEMPT_OUTCOMES),
+)
+# The pre-iteration shape of the transcript block, exactly as iteration
+# `20260909-structured-metadata-schema` shipped it. It is what the bootstrap
+# must leave untouched on an existing database (there is no migration path).
+LEGACY_TRANSCRIPT_TABLES_DDL = """
+CREATE TABLE IF NOT EXISTS transcripts (
+    transcript_id INTEGER PRIMARY KEY,
+    video_part_id INTEGER NOT NULL,
+    source_kind TEXT NOT NULL CHECK (
+        source_kind IN ('subtitle-ai', 'subtitle-cc', 'asr-local')
+    ),
+    model_id INTEGER,
+    version INTEGER NOT NULL CHECK (version > 0),
+    created_at INTEGER NOT NULL,
+    UNIQUE (video_part_id, source_kind, version),
+    FOREIGN KEY (video_part_id) REFERENCES video_parts(video_part_id) ON DELETE RESTRICT,
+    FOREIGN KEY (model_id) REFERENCES asr_models(model_id) ON DELETE RESTRICT
+);
+
+CREATE TABLE IF NOT EXISTS transcript_segments (
+    transcript_id INTEGER NOT NULL,
+    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
+    start_ms INTEGER NOT NULL CHECK (start_ms >= 0),
+    end_ms INTEGER NOT NULL CHECK (end_ms > start_ms),
+    text TEXT NOT NULL,
+    PRIMARY KEY (transcript_id, ordinal),
+    FOREIGN KEY (transcript_id) REFERENCES transcripts(transcript_id) ON DELETE RESTRICT
+);
+"""
+LEGAL_ATTEMPTS = (
+    ("stored", None, 1),
+    ("unchanged", None, 1),
+    ("no-subtitle", None, None),
+    ("no-subtitle", "not_found", None),
+    ("failed", "timeout", None),
+)
+ILLEGAL_ATTEMPTS = (
+    ("stored", None, None),
+    ("stored", "timeout", 1),
+    ("unchanged", None, None),
+    ("failed", None, None),
+    ("failed", "timeout", 1),
+    ("no-subtitle", "timeout", None),
+    ("no-subtitle", None, 1),
+    ("unknown", None, None),
+)
 
 
 def test_schema_sql_is_declared_and_read_as_package_resource():
@@ -186,14 +369,23 @@ def test_schema_sql_is_declared_and_read_as_package_resource():
         (project_root / "pyproject.toml").read_text(encoding="utf-8")
     )
     package_data = pyproject["tool"]["setuptools"]["package-data"]
-    assert "schema.sql" in package_data["bili_asr.storage"]
-
-    schema_resource = resources.files("bili_asr.storage").joinpath("schema.sql")
-    assert schema_resource.is_file()
-    assert "CREATE TABLE IF NOT EXISTS videos" in schema_resource.read_text(
-        encoding="utf-8"
+    assert {"schema.sql", "schema-transcripts.sql"} <= set(
+        package_data["bili_asr.storage"]
     )
 
+    resources_root = resources.files("bili_asr.storage")
+    schema_text = resources_root.joinpath("schema.sql").read_text(encoding="utf-8")
+    assert "CREATE TABLE IF NOT EXISTS videos" in schema_text
+
+    transcript_resource = resources_root.joinpath("schema-transcripts.sql")
+    assert transcript_resource.is_file()
+    transcript_text = transcript_resource.read_text(encoding="utf-8")
+    assert "CREATE TABLE IF NOT EXISTS transcripts (" in transcript_text
+    # The bootstrap split is what keeps a pre-iteration database usable: the
+    # metadata script no longer declares the transcript block.
+    assert "CREATE TABLE IF NOT EXISTS transcripts (" not in schema_text
+    assert "CREATE TABLE IF NOT EXISTS transcript_segments" not in schema_text
+
 
 def _table_names(connection: sqlite3.Connection) -> set[str]:
     rows = connection.execute(
@@ -225,6 +417,151 @@ def _insert_user_video_part(connection: sqlite3.Connection) -> int:
     return int(cursor.lastrowid)
 
 
+def _stored_ddl(connection: sqlite3.Connection, name: str) -> str:
+    """Return the DDL SQLite recorded for one table or view."""
+    row = connection.execute(
+        "SELECT sql FROM sqlite_master WHERE name = ?", (name,)
+    ).fetchone()
+    assert row is not None, name
+    return str(row[0])
+
+
+def _insert_transcript(
+    connection: sqlite3.Connection,
+    *,
+    transcript_id: int,
+    source_kind: str,
+    language: str,
+    version: int,
+    content_sha256: str,
+    video_part_id: int = 1,
+    model_id: int | None = None,
+    created_at: int = 200,
+) -> None:
+    connection.execute(
+        """
+        INSERT INTO transcripts(
+            transcript_id, video_part_id, source_kind, language, model_id,
+            version, content_sha256, created_at
+        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
+        """,
+        (
+            transcript_id,
+            video_part_id,
+            source_kind,
+            language,
+            model_id,
+            version,
+            content_sha256,
+            created_at,
+        ),
+    )
+
+
+def _insert_subtitle_acquisition_run(
+    connection: sqlite3.Connection,
+    *,
+    run_id: str = "run-subs",
+    credential_present: int = 0,
+    finished_at: int | None = None,
+    outcome: str = "running",
+) -> None:
+    connection.execute(
+        """
+        INSERT INTO acquisition_runs(
+            run_id, kind, selector_kind, selector_target, requested_limit,
+            credential_present, started_at, finished_at, outcome
+        ) VALUES (?, 'subtitle', 'pending', NULL, NULL, ?, 100, ?, ?)
+        """,
+        (run_id, credential_present, finished_at, outcome),
+    )
+
+
+def _insert_attempt(
+    connection: sqlite3.Connection,
+    *,
+    outcome: str,
+    error_code: str | None,
+    transcript_id: int | None,
+    run_id: str = "run-subs",
+    video_part_id: int = 1,
+    started_at: int = 100,
+    finished_at: int = 200,
+) -> None:
+    connection.execute(
+        """
+        INSERT INTO acquisition_attempts(
+            run_id, video_part_id, outcome, error_code, transcript_id,
+            started_at, finished_at
+        ) VALUES (?, ?, ?, ?, ?, ?, ?)
+        """,
+        (
+            run_id,
+            video_part_id,
+            outcome,
+            error_code,
+            transcript_id,
+            started_at,
+            finished_at,
+        ),
+    )
+
+
+def _insert_attempt_parents(connection: sqlite3.Connection) -> None:
+    """Insert the parents one attempt row needs: a part, a run, a transcript."""
+    part_id = _insert_user_video_part(connection)
+    _insert_subtitle_acquisition_run(connection)
+    _insert_transcript(
+        connection,
+        transcript_id=1,
+        video_part_id=part_id,
+        source_kind="subtitle-ai",
+        language="zh-CN",
+        version=1,
+        content_sha256="a" * 64,
+    )
+
+
+def _write_pre_iteration_database(database_path: str) -> dict[str, str]:
+    """Build the previous iteration's database and return its transcript DDL.
+
+    The metadata script is the shipped one; the transcript block is the shape
+    iteration ``20260909-structured-metadata-schema`` created, which
+    ``CREATE TABLE IF NOT EXISTS`` cannot widen.
+    """
+    metadata_schema = (
+        resources.files("bili_asr.storage").joinpath("schema.sql").read_text("utf-8")
+    )
+    connection = sqlite3.connect(database_path)
+    try:
+        connection.executescript(metadata_schema)
+        connection.executescript(LEGACY_TRANSCRIPT_TABLES_DDL)
+        part_id = _insert_user_video_part(connection)
+        connection.execute(
+            """
+            INSERT INTO transcripts(
+                transcript_id, video_part_id, source_kind, model_id, version,
+                created_at
+            ) VALUES (1, ?, 'subtitle-ai', NULL, 1, 500)
+            """,
+            (part_id,),
+        )
+        connection.execute(
+            """
+            INSERT INTO transcript_segments(
+                transcript_id, ordinal, start_ms, end_ms, text
+            ) VALUES (1, 0, 0, 1200, '旧字幕')
+            """
+        )
+        connection.commit()
+        return {
+            name: _stored_ddl(connection, name)
+            for name in ("transcripts", "transcript_segments")
+        }
+    finally:
+        connection.close()
+
+
 def test_fresh_database_initializes_archive_root_and_is_idempotent(tmp_root):
     connection = open_database(tmp_root)
     try:
@@ -274,12 +611,7 @@ def test_schema_check_enumerations_match_model_validation_sets():
             literals = re.findall(r"'([^']*)'", match.group(1))
             assert sorted(literals) == sorted(allowed)
 
-        literal_sets = (
-            (ProcessingStatus, ALLOWED_PROCESSING_STATUS),
-            (RunOutcome, ALLOWED_RUN_OUTCOMES),
-            (PageOutcome, ALLOWED_PAGE_OUTCOMES),
-            (CursorState, ALLOWED_CURSOR_STATES),
-        )
+        literal_sets = EXPECTED_LITERAL_SETS
         for literal, allowed in literal_sets:
             assert sorted(get_args(literal)) == sorted(allowed)
     finally:
@@ -444,6 +776,30 @@ def test_schema_constraints_cover_status_and_non_negative_values(tmp_root):
             f"INSERT INTO ingestion_cursors VALUES "
             f"(23191782, 2, NULL, 'ready', '{'y' * 65}', 1)",
             f"INSERT INTO ingestion_pages VALUES ('run', 3, 'failed', '{'x' * 65}', 1, 1)",
+            f"INSERT INTO transcripts VALUES "
+            f"(1, 1, 'subtitle-ai', '   ', NULL, 1, '{'a' * 64}', 1)",
+            f"INSERT INTO transcripts VALUES "
+            f"(1, 1, 'subtitle-ai', 'zh-CN', NULL, 1, '{'A' * 64}', 1)",
+            f"INSERT INTO transcripts VALUES "
+            f"(1, 1, 'subtitle-ai', 'zh-CN', NULL, 1, '{'a' * 63}', 1)",
+            f"INSERT INTO transcripts VALUES "
+            f"(1, 1, 'subtitle-ai', 'zh-CN', NULL, 0, '{'a' * 64}', 1)",
+            f"INSERT INTO transcripts VALUES "
+            f"(1, 1, 'asr-remote', 'zh-CN', NULL, 1, '{'a' * 64}', 1)",
+            "INSERT INTO acquisition_runs VALUES "
+            "('run', 'video', 'pending', NULL, NULL, 0, 1, NULL, 'running')",
+            "INSERT INTO acquisition_runs VALUES "
+            "('run', 'subtitle', 'bvid', NULL, NULL, 0, 1, NULL, 'running')",
+            "INSERT INTO acquisition_runs VALUES "
+            "('run', 'subtitle', 'pending', 'BV1TEST', NULL, 0, 1, NULL, 'running')",
+            "INSERT INTO acquisition_runs VALUES "
+            "('run', 'subtitle', 'pending', NULL, 0, 0, 1, NULL, 'running')",
+            "INSERT INTO acquisition_runs VALUES "
+            "('run', 'subtitle', 'pending', NULL, NULL, 2, 1, NULL, 'running')",
+            "INSERT INTO acquisition_runs VALUES "
+            "('run', 'subtitle', 'pending', NULL, NULL, 0, 1, NULL, 'limited')",
+            "INSERT INTO acquisition_runs VALUES "
+            "('run', 'subtitle', 'pending', NULL, NULL, 0, 100, 50, 'complete')",
         ]
         for statement in invalid_statements:
             with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError)):
@@ -535,6 +891,31 @@ def test_schema_inspection_matches_the_declared_contract(tmp_root):
                 EXPECTED_PRIMARY_KEY_INDEXES.get(table, ())
             )
 
+            declared_indexes = {
+                index["name"]: index
+                for index in connection.execute(f"PRAGMA index_list({table})")
+                if index["origin"] == "c"
+            }
+            expected_indexes = EXPECTED_INDEXES.get(table, ())
+            assert set(declared_indexes) == {
+                name for name, _, _, _ in expected_indexes
+            }
+            for name, columns, is_unique, is_partial in expected_indexes:
+                assert bool(declared_indexes[name]["unique"]) is is_unique
+                assert bool(declared_indexes[name]["partial"]) is is_partial
+                assert (
+                    tuple(
+                        info["name"]
+                        for info in connection.execute(f"PRAGMA index_info({name})")
+                    )
+                    == columns
+                )
+                clause = EXPECTED_PARTIAL_INDEX_CLAUSES.get(name)
+                if clause is not None:
+                    # A partial index is only content identity if its WHERE
+                    # clause scopes it to the caption kinds.
+                    assert _stored_ddl(connection, name).endswith(clause)
+
         for table, fragments in EXPECTED_CHECK_ENUMERATIONS.items():
             ddl_row = connection.execute(
                 "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
@@ -550,8 +931,13 @@ def test_schema_inspection_matches_the_declared_contract(tmp_root):
                 (view,),
             ).fetchone()
             normalized_ddl = " ".join(ddl_row[0].split())
-            if view in {"v_video_parts", "v_pending_metadata"}:
+            if view in {"v_video_parts", "v_pending_metadata", "v_pending_subtitles"}:
                 assert EXPECTED_VIEW_WORK_ID_EXPRESSION in normalized_ddl
+
+        for view, columns in EXPECTED_VIEW_COLUMNS.items():
+            assert [
+                row["name"] for row in connection.execute(f"PRAGMA table_info({view})")
+            ] == columns
     finally:
         connection.close()
 
@@ -632,3 +1018,572 @@ def test_views_compute_derived_values_across_users_videos_and_runs(tmp_root):
         assert pending == ["BV1MULTI:p0", "BV1SINGLE:p0"]
     finally:
         connection.close()
+
+
+def test_bootstrap_creates_the_full_contract_on_a_fresh_database(tmp_root):
+    connection = open_database(tmp_root)
+    try:
+        assert require_subtitle_schema(connection) is None
+        assert BASE_TABLES | VIEWS <= _table_names(connection)
+        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
+    finally:
+        connection.close()
+
+
+def test_bootstrap_reapplies_the_contract_to_a_current_database(tmp_root):
+    database_path = os.path.join(tmp_root, "archive.db")
+    connection = open_database(database_path)
+    try:
+        part_id = _insert_user_video_part(connection)
+        _insert_transcript(
+            connection,
+            transcript_id=1,
+            video_part_id=part_id,
+            source_kind="subtitle-ai",
+            language="zh-CN",
+            version=1,
+            content_sha256="a" * 64,
+        )
+        connection.execute(
+            "INSERT INTO transcript_segments("
+            "transcript_id, ordinal, start_ms, end_ms, text"
+            ") VALUES (1, 0, 0, 1200, '第一句')"
+        )
+        connection.commit()
+        declared_ddl = {
+            name: _stored_ddl(connection, name)
+            for name in ("transcripts", "transcript_segments", "v_pending_subtitles")
+        }
+    finally:
+        connection.close()
+
+    reopened = open_database(database_path)
+    try:
+        assert require_subtitle_schema(reopened) is None
+        # Re-applying the script is a no-op: every statement is IF NOT EXISTS,
+        # so the declared DDL and the rows are untouched.
+        assert {
+            name: _stored_ddl(reopened, name) for name in declared_ddl
+        } == declared_ddl
+        assert (
+            reopened.execute("SELECT text FROM transcript_segments").fetchone()[0]
+            == "第一句"
+        )
+        # A capability check is structural: a missing object is a broken
+        # contract even while the columns look current.
+        reopened.execute("DROP VIEW v_pending_subtitles")
+        with pytest.raises(SchemaContractError):
+            require_subtitle_schema(reopened)
+    finally:
+        reopened.close()
+
+    repaired = open_database(database_path)
+    try:
+        assert require_subtitle_schema(repaired) is None
+    finally:
+        repaired.close()
+
+
+def test_bootstrap_leaves_a_pre_iteration_database_untouched(tmp_root):
+    database_path = os.path.join(tmp_root, "archive.db")
+    legacy_ddl = _write_pre_iteration_database(database_path)
+
+    connection = open_database(database_path)
+    try:
+        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
+        names = _table_names(connection)
+        assert "acquisition_runs" not in names
+        assert "acquisition_attempts" not in names
+        assert "v_pending_subtitles" not in names
+        # Nothing half-applies: the pre-iteration transcript shape is exactly
+        # the shape the previous iteration wrote, and its rows are readable.
+        assert {
+            name: _stored_ddl(connection, name) for name in legacy_ddl
+        } == legacy_ddl
+        assert [
+            row["name"] for row in connection.execute("PRAGMA table_info(transcripts)")
+        ] == [
+            "transcript_id",
+            "video_part_id",
+            "source_kind",
+            "model_id",
+            "version",
+            "created_at",
+        ]
+        assert (
+            connection.execute("SELECT text FROM transcript_segments").fetchone()[0]
+            == "旧字幕"
+        )
+
+        # The metadata path keeps working on that database, reads and writes.
+        repository = MetadataRepository(connection)
+        assert [row["work_id"] for row in repository.list_pending_parts()] == [
+            "BV1TEST:p0"
+        ]
+        with repository.transaction():
+            repository.write_cursor(
+                CursorRecord(
+                    mid=23191782,
+                    next_page=2,
+                    observed_total=1,
+                    state="ready",
+                    last_error_code=None,
+                    updated_at=600,
+                )
+            )
+        cursor = repository.read_cursor(23191782)
+        assert cursor is not None and cursor.next_page == 2
+
+        # The subtitle path is refused with the bounded rebuild error, and the
+        # rebuild is the only offered remedy (no migration path).
+        with pytest.raises(SchemaContractError) as refused:
+            require_subtitle_schema(connection)
+        assert "predates the transcript schema" in str(refused.value)
+    finally:
+        connection.close()
+
+
+def test_require_subtitle_schema_requires_the_process_record_objects(tmp_root):
+    connection = open_database(tmp_root)
+    try:
+        connection.execute("DROP TABLE acquisition_attempts")
+        with pytest.raises(SchemaContractError):
+            require_subtitle_schema(connection)
+    finally:
+        connection.close()
+
+
+def test_subtitle_content_index_is_partial_over_the_caption_kinds(tmp_root):
+    connection = open_database(tmp_root)
+    try:
+        part_id = _insert_user_video_part(connection)
+        digest = "a" * 64
+        _insert_transcript(
+            connection,
+            transcript_id=1,
+            video_part_id=part_id,
+            source_kind="subtitle-ai",
+            language="zh-CN",
+            version=1,
+            content_sha256=digest,
+        )
+        # Content identity: the same caption never lands twice for one part,
+        # source kind and language.
+        with pytest.raises(sqlite3.IntegrityError):
+            _insert_transcript(
+                connection,
+                transcript_id=2,
+                video_part_id=part_id,
+                source_kind="subtitle-ai",
+                language="zh-CN",
+                version=2,
+                content_sha256=digest,
+            )
+        # A different language or source kind is a different fact.
+        _insert_transcript(
+            connection,
+            transcript_id=3,
+            video_part_id=part_id,
+            source_kind="subtitle-cc",
+            language="en-US",
+            version=1,
+            content_sha256=digest,
+        )
+        # asr-local keeps its own model-scoped identity rule: outside the index,
+        # so a repeated hash appends a version instead of colliding.
+        _insert_transcript(
+            connection,
+            transcript_id=4,
+            video_part_id=part_id,
+            source_kind="asr-local",
+            language="zh-CN",
+            version=1,
+            content_sha256=digest,
+        )
+        _insert_transcript(
+            connection,
+            transcript_id=5,
+            video_part_id=part_id,
+            source_kind="asr-local",
+            language="zh-CN",
+            version=2,
+            content_sha256=digest,
+        )
+        # The widened version key still rejects a repeated version.
+        with pytest.raises(sqlite3.IntegrityError):
+            _insert_transcript(
+                connection,
+                transcript_id=6,
+                video_part_id=part_id,
+                source_kind="subtitle-ai",
+                language="zh-CN",
+                version=1,
+                content_sha256="b" * 64,
+            )
+    finally:
+        connection.close()
+
+
+def test_transcript_base_tables_store_no_derived_values(tmp_root):
+    connection = open_database(tmp_root)
+    try:
+        view_columns = {
+            row["name"]
+            for row in connection.execute("PRAGMA table_info(v_pending_subtitles)")
+        }
+        assert {"work_id", "attempted", "last_attempt_at"} <= view_columns
+
+        forbidden = {
+            "work_id",
+            "attempted",
+            "attempt_count",
+            "segment_count",
+            "transcript_count",
+            "is_pending",
+            "last_attempt_at",
+            "last_attempt_outcome",
+            "last_attempt_error_code",
+            "last_attempt_credential_present",
+        }
+        for table in (
+            "transcripts",
+            "transcript_segments",
+            "acquisition_runs",
+            "acquisition_attempts",
+        ):
+            columns = {
+                row["name"] for row in connection.execute(f"PRAGMA table_info({table})")
+            }
+            assert columns.isdisjoint(forbidden), table
+    finally:
+        connection.close()
+
+
+def test_pending_subtitles_view_carries_the_newest_attempt_evidence(tmp_root):
+    connection = open_database(tmp_root)
+    try:
+        _insert_user_video_part(connection)
+        connection.execute(
+            "INSERT INTO videos(bvid, aid, mid, title, pubdate, created_at, updated_at) "
+            "VALUES ('BV1GONE', NULL, 23191782, '已下架', 1, 1, 1)"
+        )
+        connection.execute(
+            """
+            INSERT INTO video_parts(
+                bvid, page_index, cid, title, duration_ms, processing_status,
+                created_at, updated_at
+            ) VALUES ('BV1GONE', 0, 2001, '残片', 1000, 'gone', 1, 1)
+            """
+        )
+        connection.execute(
+            """
+            INSERT INTO video_parts(
+                bvid, page_index, cid, title, duration_ms, processing_status,
+                created_at, updated_at
+            ) VALUES ('BV1TEST', 1, 2002, '第二段', 2000, 'discovered', 1, 1)
+            """
+        )
+        transcribed = int(
+            connection.execute(
+                """
+                INSERT INTO video_parts(
+                    bvid, page_index, cid, title, duration_ms, processing_status,
+                    created_at, updated_at
+                ) VALUES ('BV1TEST', 2, 2003, '第三段', 3000, 'discovered', 1, 1)
+                """
+            ).lastrowid
+        )
+        attempted = 3
+        _insert_subtitle_acquisition_run(
+            connection,
+            run_id="run-1",
+            credential_present=1,
+            finished_at=300,
+            outcome="complete",
+        )
+        _insert_subtitle_acquisition_run(
+            connection,
+            run_id="run-2",
+            credential_present=0,
+            finished_at=500,
+            outcome="partial",
+        )
+        _insert_attempt(
+            connection,
+            run_id="run-1",
+            video_part_id=attempted,
+            outcome="no-subtitle",
+            error_code="not_found",
+            transcript_id=None,
+            started_at=200,
+            finished_at=300,
+        )
+        _insert_attempt(
+            connection,
+            run_id="run-2",
+            video_part_id=attempted,
+            outcome="failed",
+            error_code="timeout",
+            transcript_id=None,
+            started_at=400,
+            finished_at=500,
+        )
+        _insert_transcript(
+            connection,
+            transcript_id=1,
+            video_part_id=transcribed,
+            source_kind="subtitle-cc",
+            language="zh-CN",
+            version=1,
+            content_sha256="c" * 64,
+        )
+
+        rows = connection.execute(
+            "SELECT work_id, cid, attempted, last_attempt_at, last_attempt_outcome, "
+            "last_attempt_error_code, last_attempt_credential_present "
+            "FROM v_pending_subtitles ORDER BY work_id"
+        ).fetchall()
+        assert [row["work_id"] for row in rows] == ["BV1TEST:p0", "BV1TEST:p1"]
+
+        fresh = rows[0]
+        assert fresh["cid"] == 2001
+        assert fresh["attempted"] == 0
+        assert fresh["last_attempt_at"] is None
+        assert fresh["last_attempt_outcome"] is None
+        assert fresh["last_attempt_error_code"] is None
+        assert fresh["last_attempt_credential_present"] is None
+
+        retried = rows[1]
+        assert retried["cid"] == 2002
+        assert retried["attempted"] == 1
+        assert retried["last_attempt_at"] == 500
+        assert retried["last_attempt_outcome"] == "failed"
+        assert retried["last_attempt_error_code"] == "timeout"
+        assert retried["last_attempt_credential_present"] == 0
+    finally:
+        connection.close()
+
+
+def test_pending_subtitles_view_is_scoped_to_subtitle_attempts(tmp_root):
+    """The backlog is subtitle evidence; the audio/ASR kinds reuse the pair."""
+    connection = open_database(tmp_root)
+    try:
+        part_id = _insert_user_video_part(connection)
+        # The next iteration probes the same part under ``kind='audio'``: that
+        # is process evidence, but not subtitle backlog evidence.
+        connection.execute(
+            """
+            INSERT INTO acquisition_runs(
+                run_id, kind, selector_kind, selector_target, requested_limit,
+                credential_present, started_at, finished_at, outcome
+            ) VALUES ('run-audio', 'audio', 'pending', NULL, NULL, 0, 100, 200, 'complete')
+            """
+        )
+        _insert_attempt(
+            connection,
+            run_id="run-audio",
+            video_part_id=part_id,
+            outcome="failed",
+            error_code="timeout",
+            transcript_id=None,
+            started_at=100,
+            finished_at=200,
+        )
+        assert tuple(
+            connection.execute(
+                "SELECT attempted, last_attempt_at, last_attempt_outcome "
+                "FROM v_pending_subtitles WHERE video_part_id = ?",
+                (part_id,),
+            ).fetchone()
+        ) == (0, None, None)
+
+        # A subtitle attempt on the same part is what makes it attempted; the
+        # audio attempt neither hides it nor is reported as its evidence.
+        _insert_subtitle_acquisition_run(
+            connection,
+            run_id="run-subs",
+            credential_present=1,
+            finished_at=400,
+            outcome="complete",
+        )
+        _insert_attempt(
+            connection,
+            run_id="run-subs",
+            video_part_id=part_id,
+            outcome="no-subtitle",
+            error_code=None,
+            transcript_id=None,
+            started_at=300,
+            finished_at=400,
+        )
+        assert tuple(
+            connection.execute(
+                "SELECT attempted, last_attempt_at, last_attempt_outcome, "
+                "last_attempt_credential_present FROM v_pending_subtitles "
+                "WHERE video_part_id = ?",
+                (part_id,),
+            ).fetchone()
+        ) == (1, 400, "no-subtitle", 1)
+    finally:
+        connection.close()
+
+
+@pytest.mark.parametrize(("outcome", "error_code", "transcript_id"), LEGAL_ATTEMPTS)
+def test_attempt_check_matrix_accepts_legal_evidence(
+    tmp_root, outcome, error_code, transcript_id
+):
+    connection = open_database(tmp_root)
+    try:
+        _insert_attempt_parents(connection)
+        _insert_attempt(
+            connection,
+            outcome=outcome,
+            error_code=error_code,
+            transcript_id=transcript_id,
+        )
+        row = connection.execute(
+            "SELECT outcome, error_code, transcript_id FROM acquisition_attempts"
+        ).fetchone()
+        assert tuple(row) == (outcome, error_code, transcript_id)
+    finally:
+        connection.close()
+
+
+@pytest.mark.parametrize(("outcome", "error_code", "transcript_id"), ILLEGAL_ATTEMPTS)
+def test_attempt_check_matrix_rejects_illegal_evidence(
+    tmp_root, outcome, error_code, transcript_id
+):
+    connection = open_database(tmp_root)
+    try:
+        _insert_attempt_parents(connection)
+        with pytest.raises(sqlite3.IntegrityError):
+            _insert_attempt(
+                connection,
+                outcome=outcome,
+                error_code=error_code,
+                transcript_id=transcript_id,
+            )
+    finally:
+        connection.close()
+
+
+def test_one_outcome_per_attempted_part_per_run(tmp_root):
+    connection = open_database(tmp_root)
+    try:
+        _insert_attempt_parents(connection)
+        _insert_attempt(
+            connection, outcome="no-subtitle", error_code=None, transcript_id=None
+        )
+        with pytest.raises(sqlite3.IntegrityError):
+            _insert_attempt(
+                connection, outcome="failed", error_code="timeout", transcript_id=None
+            )
+        # Attempts are append-only evidence scoped to their run: the same part
+        # is recorded again by a later run, and that is not a conflict.
+        _insert_subtitle_acquisition_run(connection, run_id="run-subs-2")
+        _insert_attempt(
+            connection,
+            run_id="run-subs-2",
+            outcome="stored",
+            error_code=None,
+            transcript_id=1,
+        )
+        assert connection.execute(
+            "SELECT COUNT(*) FROM acquisition_attempts"
+        ).fetchone()[0] == 2
+    finally:
+        connection.close()
+
+
+def test_transcript_segment_record_mirrors_the_segment_invariant():
+    segment = TranscriptSegmentRecord(start_ms=0, end_ms=1200, text="第一句")
+    assert (segment.start_ms, segment.end_ms, segment.text) == (0, 1200, "第一句")
+    # Caption text is verbatim: control characters survive, unlike the
+    # metadata records' short code fields.
+    assert TranscriptSegmentRecord(
+        start_ms=0, end_ms=1, text=" 多行\n文本 "
+    ).text == " 多行\n文本 "
+
+    for invalid in (
+        {"start_ms": -1, "end_ms": 10, "text": "x"},
+        {"start_ms": 10, "end_ms": 10, "text": "x"},
+        {"start_ms": 10, "end_ms": 9, "text": "x"},
+        {"start_ms": 0, "end_ms": 10, "text": "   "},
+    ):
+        with pytest.raises(ValueError):
+            TranscriptSegmentRecord(**invalid)
+    with pytest.raises(TypeError):
+        TranscriptSegmentRecord(start_ms=0, end_ms=10, text=1)
+
+
+def test_transcript_write_result_validates_the_locked_shape():
+    result = TranscriptWriteResult(
+        outcome="stored", transcript_id=7, version=2, content_sha256="a" * 64
+    )
+    assert (result.outcome, result.transcript_id, result.version) == ("stored", 7, 2)
+
+    for invalid in (
+        {"outcome": "no-subtitle", "transcript_id": 1, "version": 1,
+         "content_sha256": "a" * 64},
+        {"outcome": "failed", "transcript_id": 1, "version": 1,
+         "content_sha256": "a" * 64},
+        {"outcome": "stored", "transcript_id": 0, "version": 1,
+         "content_sha256": "a" * 64},
+        {"outcome": "stored", "transcript_id": 1, "version": 0,
+         "content_sha256": "a" * 64},
+        {"outcome": "stored", "transcript_id": 1, "version": 1,
+         "content_sha256": "A" * 64},
+        {"outcome": "stored", "transcript_id": 1, "version": 1,
+         "content_sha256": "a" * 63},
+    ):
+        with pytest.raises(ValueError):
+            TranscriptWriteResult(**invalid)
+    with pytest.raises(TypeError):
+        TranscriptWriteResult(
+            outcome="stored", transcript_id=1, version=1, content_sha256=None
+        )
+
+
+def _acquisition_run(**overrides):
+    values = {
+        "run_id": "run-subs-1",
+        "kind": "subtitle",
+        "selector_kind": "pending",
+        "selector_target": None,
+        "requested_limit": 25,
+        "credential_present": False,
+        "started_at": 100,
+    }
+    values.update(overrides)
+    return AcquisitionRunRecord(**values)
+
+
+def test_acquisition_run_record_validates_the_locked_shape():
+    assert _acquisition_run().outcome == "running"
+    assert _acquisition_run().finished_at is None
+    assert (
+        _acquisition_run(selector_kind="bvid", selector_target="BV1TEST:p0")
+        .selector_target
+        == "BV1TEST:p0"
+    )
+    assert _acquisition_run(outcome="complete", finished_at=200).outcome == "complete"
+
+    for invalid in (
+        {"run_id": "   "},
+        {"kind": "video"},
+        {"selector_kind": "pending", "selector_target": "BV1TEST"},
+        {"selector_kind": "bvid", "selector_target": None},
+        {"selector_kind": "bvid", "selector_target": "   "},
+        {"requested_limit": 0},
+        {"outcome": "limited"},
+        # A terminal outcome without its finish time would store a run that
+        # claims to be over and cannot say when.
+        {"outcome": "complete"},
+        {"finished_at": 99},
+    ):
+        with pytest.raises(ValueError):
+            _acquisition_run(**invalid)
+    with pytest.raises(TypeError):
+        _acquisition_run(credential_present=1)
+    with pytest.raises(TypeError):
+        _acquisition_run(started_at="100")
diff --git a/bilibili-asr-archive/tests/test_transcript_repository.py b/bilibili-asr-archive/tests/test_transcript_repository.py
new file mode 100644
index 0000000..64ce3b4
--- /dev/null
+++ b/bilibili-asr-archive/tests/test_transcript_repository.py
@@ -0,0 +1,1930 @@
+"""Offline repository contract tests for transcript and acquisition writes."""
+
+from __future__ import annotations
+
+import builtins
+import hashlib
+import io
+import json
+import os
+import re
+import sqlite3
+
+import pytest
+
+from bili_asr.storage import (
+    MAX_TIMELINE_MS,
+    AcquisitionRunRecord,
+    MetadataRepository,
+    TranscriptRecord,
+    TranscriptRepository,
+    TranscriptSegmentRecord,
+    TranscriptWriteResult,
+    open_database,
+)
+from fixtures.metadata_records import (
+    make_part_record,
+    make_user_record,
+    make_video_record,
+)
+from test_metadata_e2e import LEGACY_SIDECAR_PATHS
+
+
+BODY = ((0, 1_200, "第一句"), (1_200, 2_400, "第二句"))
+CHANGED_BODY = ((0, 1_200, "第一句"), (1_200, 2_400, "改写后的第二句"))
+
+
+def _captioned_part(connection: sqlite3.Connection, bvid: str = "BV1CAPTION") -> int:
+    """Store one video part through the metadata repository and return its id."""
+    metadata = MetadataRepository(connection)
+    with metadata.transaction():
+        metadata.upsert_user(make_user_record())
+        # ``aid`` stays NULL: the schema keeps aids unique and these fixtures
+        # only need the part the transcript contract hangs from.
+        metadata.upsert_video(
+            make_video_record(bvid, aid=None, title="字幕测试视频")
+        )
+        metadata.upsert_part(
+            make_part_record(
+                bvid, cid=2001, title="第一集", processing_status="metadata_collected"
+            )
+        )
+    row = connection.execute(
+        "SELECT video_part_id FROM video_parts WHERE bvid = ? AND page_index = 0",
+        (bvid,),
+    ).fetchone()
+    return int(row["video_part_id"])
+
+
+def _video_with_parts(
+    connection: sqlite3.Connection,
+    bvid: str,
+    cids: tuple[int, ...],
+    *,
+    processing_status: str = "metadata_collected",
+) -> dict[int, int]:
+    """Store one video with one part per page index; return ``page → part id``.
+
+    ``cids`` is positional: the cid at position *i* belongs to page index *i*,
+    so a selection test can name the part it expects by its cid.
+    """
+    metadata = MetadataRepository(connection)
+    with metadata.transaction():
+        metadata.upsert_user(make_user_record())
+        # ``aid`` stays NULL: the schema keeps aids unique and these fixtures
+        # only need the parts the transcript contract hangs from.
+        metadata.upsert_video(make_video_record(bvid, aid=None, title="字幕测试视频"))
+        for page_index, cid in enumerate(cids):
+            metadata.upsert_part(
+                make_part_record(
+                    bvid,
+                    page_index=page_index,
+                    cid=cid,
+                    title=f"第{page_index + 1}集",
+                    processing_status=processing_status,
+                )
+            )
+    return {
+        int(row["page_index"]): int(row["video_part_id"])
+        for row in connection.execute(
+            "SELECT video_part_id, page_index FROM video_parts WHERE bvid = ?",
+            (bvid,),
+        ).fetchall()
+    }
+
+
+def _caption_run(
+    run_id: str = "caption-run-1",
+    *,
+    selector_kind: str = "pending",
+    selector_target: str | None = None,
+    requested_limit: int | None = None,
+    credential_present: bool = False,
+    started_at: int = 101,
+    outcome: str = "running",
+    finished_at: int | None = None,
+) -> AcquisitionRunRecord:
+    """Build one acquisition run record for the caption path."""
+    return AcquisitionRunRecord(
+        run_id=run_id,
+        kind="subtitle",
+        selector_kind=selector_kind,
+        selector_target=selector_target,
+        requested_limit=requested_limit,
+        credential_present=credential_present,
+        started_at=started_at,
+        outcome=outcome,
+        finished_at=finished_at,
+    )
+
+
+def _run(repository: TranscriptRepository, index: int, **overrides) -> str:
+    """Start one numbered acquisition run and return its id."""
+    run_id = f"caption-run-{index}"
+    fields: dict[str, object] = {"started_at": 100 + index}
+    fields.update(overrides)
+    repository.start_acquisition_run(_caption_run(run_id, **fields))
+    return run_id
+
+
+def _probe(
+    repository: TranscriptRepository,
+    video_part_id: int,
+    *,
+    index: int,
+    finished_at: int,
+    error_code: str | None = None,
+    credential_present: bool = False,
+) -> str:
+    """Record one ``no-subtitle`` probe of a part in its own acquisition run."""
+    run_id = _run(
+        repository,
+        index,
+        credential_present=credential_present,
+        started_at=finished_at - 10,
+    )
+    repository.record_subtitle_attempt(
+        run_id=run_id,
+        video_part_id=video_part_id,
+        outcome="no-subtitle",
+        error_code=error_code,
+        started_at=finished_at - 10,
+        finished_at=finished_at,
+    )
+    return run_id
+
+
+def _segments(body=BODY) -> tuple[TranscriptSegmentRecord, ...]:
+    """Build the segment tuple for one caption body of ``(start, end, text)``."""
+    return tuple(TranscriptSegmentRecord(*triple) for triple in body)
+
+
+def _write_kwargs(video_part_id: int, *, body=BODY, **overrides) -> dict:
+    """Build one valid ``record_acquired_transcript`` argument set."""
+    kwargs: dict[str, object] = {
+        "run_id": "caption-run-1",
+        "video_part_id": video_part_id,
+        "source_kind": "subtitle-cc",
+        "language": "zh-CN",
+        "segments": _segments(body),
+        "started_at": 200,
+        "finished_at": 300,
+        "created_at": 400,
+    }
+    kwargs.update(overrides)
+    return kwargs
+
+
+def _record(
+    repository: TranscriptRepository, video_part_id: int, **overrides
+) -> TranscriptWriteResult:
+    """Record one caption body and return what the write did."""
+    return repository.record_acquired_transcript(
+        **_write_kwargs(video_part_id, **overrides)
+    )
+
+
+def _expected_content_sha256(body) -> str:
+    """Compute the contract's content hash independently of the repository."""
+    canonical = json.dumps(
+        [[start_ms, end_ms, text] for start_ms, end_ms, text in body],
+        ensure_ascii=False,
+        separators=(",", ":"),
+    )
+    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
+
+
+def _triples(segments) -> list[tuple[int, int, str]]:
+    """Return a stored record's segments as plain ``(start_ms, end_ms, text)``."""
+    return [(segment.start_ms, segment.end_ms, segment.text) for segment in segments]
+
+
+def _transcript_rows(connection: sqlite3.Connection, video_part_id: int) -> list[tuple]:
+    """Return the stored versions of one part, oldest first."""
+    return [
+        tuple(row)
+        for row in connection.execute(
+            """
+            SELECT version, source_kind, language, model_id, content_sha256, created_at
+            FROM transcripts WHERE video_part_id = ? ORDER BY version
+            """,
+            (video_part_id,),
+        ).fetchall()
+    ]
+
+
+def _segment_rows(connection: sqlite3.Connection, transcript_id: int) -> list[tuple]:
+    """Return the stored segments of one version, in ordinal order."""
+    return [
+        tuple(row)
+        for row in connection.execute(
+            """
+            SELECT ordinal, start_ms, end_ms, text FROM transcript_segments
+            WHERE transcript_id = ? ORDER BY ordinal
+            """,
+            (transcript_id,),
+        ).fetchall()
+    ]
+
+
+def _attempt_rows(
+    connection: sqlite3.Connection, run_id: str | None = None
+) -> list[tuple]:
+    """Return the attempt evidence rows, optionally restricted to one run."""
+    query = (
+        "SELECT run_id, video_part_id, outcome, error_code, transcript_id, "
+        "started_at, finished_at FROM acquisition_attempts"
+    )
+    if run_id is None:
+        return [
+            tuple(row)
+            for row in connection.execute(
+                query + " ORDER BY run_id, video_part_id"
+            ).fetchall()
+        ]
+    return [
+        tuple(row)
+        for row in connection.execute(
+            query + " WHERE run_id = ? ORDER BY video_part_id", (run_id,)
+        ).fetchall()
+    ]
+
+
+def _empty_store(connection: sqlite3.Connection) -> tuple[int, int, int]:
+    """Return the transcript, segment, and attempt counts of the store."""
+    return (
+        connection.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0],
+        connection.execute("SELECT COUNT(*) FROM transcript_segments").fetchone()[0],
+        connection.execute("SELECT COUNT(*) FROM acquisition_attempts").fetchone()[0],
+    )
+
+
+def test_first_write_stores_version_one_with_ordinal_segments_and_its_attempt(tmp_root):
+    connection = open_database(tmp_root)
+    repository = TranscriptRepository(connection)
+    try:
+        part_id = _captioned_part(connection)
+        run_id = _run(repository, 1)
+
+        result = _record(repository, part_id)
+
+        assert result.outcome == "stored"
+        assert result.version == 1
+        assert result.transcript_id >= 1
+        assert result.content_sha256 == _expected_content_sha256(BODY)
+        assert _transcript_rows(connection, part_id) == [
+            (1, "subtitle-cc", "zh-CN", None, result.content_sha256, 400)
+        ]
+        assert _segment_rows(connection, result.transcript_id) == [
+            (0, 0, 1_200, "第一句"),
+            (1, 1_200, 2_400, "第二句"),
+        ]
+        assert _attempt_rows(connection) == [
+            (run_id, part_id, "stored", None, result.transcript_id, 200, 300)
+        ]
+        # Subtitle process records live beside the metadata-scoped run tables,
+        # never inside them.
+        assert connection.execute("SELECT COUNT(*) FROM ingestion_runs").fetchone()[0] == 0
+        assert connection.execute("SELECT COUNT(*) FROM ingestion_pages").fetchone()[0] == 0
+        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
+    finally:
+        connection.close()
+
+
+def test_repeat_with_identical_content_writes_nothing_and_reports_unchanged(tmp_root):
+    connection = open_database(tmp_root)
+    repository = TranscriptRepository(connection)
+    try:
+        part_id = _captioned_part(connection)
+        first_run = _run(repository, 1)
+        first = _record(repository, part_id, run_id=first_run)
+
+        second_run = _run(repository, 2)
+        second = _record(
+            repository, part_id, run_id=second_run, started_at=210, finished_at=310
+        )
+
+        assert second.outcome == "unchanged"
+        assert second.transcript_id == first.transcript_id
+        assert second.version == 1
+        assert second.content_sha256 == first.content_sha256
+        assert len(_transcript_rows(connection, part_id)) == 1
+        assert _segment_rows(connection, first.transcript_id) == [
+            (0, 0, 1_200, "第一句"),
+            (1, 1_200, 2_400, "第二句"),
+        ]
+        # The acquisition itself is still recorded, and it points at the
+        # version the operator already holds.
+        assert _attempt_rows(connection) == [
+            (first_run, part_id, "stored", None, first.transcript_id, 200, 300),
+            (second_run, part_id, "unchanged", None, first.transcript_id, 210, 310),
+        ]
+    finally:
+        connection.close()
+
+
+def test_text_is_stored_and_hashed_trimmed_but_kept_verbatim_inside(tmp_root):
+    """M1: trimming happens at the storage boundary, not only in the gateway."""
+    connection = open_database(tmp_root)
+    repository = TranscriptRepository(connection)
+    try:
+        part_id = _captioned_part(connection)
+        padded_body = ((0, 1_200, "  第一句\t"), (1_200, 2_400, "\n第二句  "))
+        run_id = _run(repository, 1)
+
+        padded = _record(repository, part_id, run_id=run_id, body=padded_body)
+
+        assert padded.outcome == "stored"
+        assert _segment_rows(connection, padded.transcript_id) == [
+            (0, 0, 1_200, "第一句"),
+            (1, 1_200, 2_400, "第二句"),
+        ]
+        # The hash covers the trimmed text, so the caller's whitespace cannot
+        # invent a second version of a caption the archive already holds.
+        assert padded.content_sha256 == _expected_content_sha256(BODY)
+
+        trimmed_run = _run(repository, 2)
+        trimmed = _record(
+            repository, part_id, run_id=trimmed_run, body=BODY
+        )
+        assert trimmed.outcome == "unchanged"
+        assert trimmed.version == 1
+        assert trimmed.transcript_id == padded.transcript_id
+    finally:
+        connection.close()
+
+
+def test_content_hash_is_the_sha256_of_the_canonical_segment_json(tmp_root):
+    connection = open_database(tmp_root)
+    repository = TranscriptRepository(connection)
+    try:
+        part_id = _captioned_part(connection)
+        run_id = _run(repository, 1)
+
+        result = _record(repository, part_id, run_id=run_id)
+
+        assert result.content_sha256 == _expected_content_sha256(BODY)
+        assert re.fullmatch(r"[0-9a-f]{64}", result.content_sha256) is not None
+        assert (
+            connection.execute(
+                "SELECT content_sha256 FROM transcripts WHERE transcript_id = ?",
+                (result.transcript_id,),
+            ).fetchone()[0]
+            == result.content_sha256
+        )
+        # The canonical form is part of the contract: looser JSON spellings of
+        # the same caption are a different digest, so the hash is not a
+        # coincidental match of a nearby encoding.
+        triples = [[0, 1_200, "第一句"], [1_200, 2_400, "第二句"]]
+        looser_encodings = {
+            hashlib.sha256(
+                json.dumps(triples, ensure_ascii=False).encode("utf-8")
+            ).hexdigest(),
+            hashlib.sha256(
+                json.dumps(triples, separators=(",", ":")).encode("utf-8")
+            ).hexdigest(),
+            hashlib.sha256(
+                json.dumps(
+                    triples, ensure_ascii=False, separators=(", ", ": ")
+                ).encode("utf-8")
+            ).hexdigest(),
+        }
+        assert result.content_sha256 not in looser_encodings
+
+        # The identity key is not hashed: the same caption on another part
+        # carries the same content hash.
+        other_part_id = _captioned_part(connection, "BV1SAMEBODY")
+        other_run = _run(repository, 2)
+        other = _record(repository, other_part_id, run_id=other_run)
+        assert other.content_sha256 == result.content_sha256
+        assert other.version == 1
+    finally:
+        connection.close()
+
+
+def test_changed_content_appends_version_two_and_leaves_version_one_untouched(tmp_root):
+    connection = open_database(tmp_root)
+    repository = TranscriptRepository(connection)
+    try:
+        part_id = _captioned_part(connection)
+        first_run = _run(repository, 1)
+        first = _record(repository, part_id, run_id=first_run)
+        version_one_rows = _transcript_rows(connection, part_id)
+        version_one_segments = _segment_rows(connection, first.transcript_id)
+
+        second_run = _run(repository, 2)
+        second = _record(
+            repository,
+            part_id,
+            run_id=second_run,
+            body=CHANGED_BODY,
+            started_at=210,
+            finished_at=310,
+            created_at=410,
+        )
+
+        assert second.outcome == "stored"
+        assert second.version == 2
+        assert second.transcript_id != first.transcript_id
+        assert second.content_sha256 == _expected_content_sha256(CHANGED_BODY)
+        # Version 1 is byte-identical: nothing was rewritten or deleted.
+        assert _transcript_rows(connection, part_id)[:1] == version_one_rows
+        assert _segment_rows(connection, first.transcript_id) == version_one_segments
+        assert _segment_rows(connection, second.transcript_id) == [
+            (0, 0, 1_200, "第一句"),
+            (1, 1_200, 2_400, "改写后的第二句"),
+        ]
+        assert _transcript_rows(connection, part_id)[1] == (
+            2,
+            "subtitle-cc",
+            "zh-CN",
+            None,
+            second.content_sha256,
+            410,
+        )
+        assert _attempt_rows(connection, second_run) == [
+            (second_run, part_id, "stored", None, second.transcript_id, 210, 310)
+        ]
+    finally:
+        connection.close()
+
+
+def test_content_that_reverts_to_an_earlier_version_is_unchanged_and_points_at_it(
+    tmp_root,
+):
+    connection = open_database(tmp_root)
+    repository = TranscriptRepository(connection)
+    try:
+        part_id = _captioned_part(connection)
+        first_run = _run(repository, 1)
+        first = _record(repository, part_id, run_id=first_run)
+        second_run = _run(repository, 2)
+        second = _record(repository, part_id, run_id=second_run, body=CHANGED_BODY)
+
+        revert_run = _run(repository, 3)
+        reverted = _record(
+            repository, part_id, run_id=revert_run, started_at=220, finished_at=320
+        )
+
+        assert reverted.outcome == "unchanged"
+        assert reverted.version == 1
+        assert reverted.transcript_id == first.transcript_id
+        assert len(_transcript_rows(connection, part_id)) == 2
+        assert _segment_rows(connection, second.transcript_id) == [
+            (0, 0, 1_200, "第一句"),
+            (1, 1_200, 2_400, "改写后的第二句"),
+        ]
+        # Reverting to the newest content is equally a no-op.
+        newest_run = _run(repository, 4)
+        newest = _record(
+            repository,
+            part_id,
+            run_id=newest_run,
+            body=CHANGED_BODY,
+            started_at=230,
+            finished_at=330,
+        )
+        assert newest.outcome == "unchanged"
+        assert newest.version == 2
+        assert newest.transcript_id == second.transcript_id
+        assert _attempt_rows(connection, revert_run) == [
+            (revert_run, part_id, "unchanged", None, first.transcript_id, 220, 320)
+        ]
+    finally:
+        connection.close()
+
+
+def test_content_identity_is_scoped_to_the_identity_key(tmp_root):
+    connection = open_database(tmp_root)
+    repository = TranscriptRepository(connection)
+    try:
+        part_id = _captioned_part(connection)
+        cc_run = _run(repository, 1)
+        cc = _record(repository, part_id, run_id=cc_run, language=" zh-CN ")
+
+        # The stored language is the trimmed one, and it is the identity.
+        assert _transcript_rows(connection, part_id) == [
+            (1, "subtitle-cc", "zh-CN", None, cc.content_sha256, 400)
+        ]
+
+        # The same content under another source kind and language is a
+        # different transcript identity with its own version history.
+        ai_run = _run(repository, 2)
+        ai = _record(
+            repository,
+            part_id,
+            run_id=ai_run,
+            source_kind="subtitle-ai",
+            language="ai-zh",
+        )
+        assert ai.outcome == "stored"
+        assert ai.version == 1
+        assert ai.content_sha256 == cc.content_sha256
+
+        # A padded language names the same identity as the trimmed stored one.
+        repeat_run = _run(repository, 3)
+        repeat = _record(repository, part_id, run_id=repeat_run, language="zh-CN")
+        assert repeat.outcome == "unchanged"
+        assert repeat.version == 1
+        assert repeat.transcript_id == cc.transcript_id
+
+        # A changed body advances only its own identity.
+        changed_run = _run(repository, 4)
+        changed = _record(
+            repository,
+            part_id,
+            run_id=changed_run,
+            language="zh-CN",
+            body=CHANGED_BODY,
+        )
+        assert changed.version == 2
+        assert changed.transcript_id != cc.transcript_id
+        assert len(_transcript_rows(connection, part_id)) == 3
+    finally:
+        connection.close()
+
+
+@pytest.mark.parametrize(
+    ("override", "error"),
+    [
+        ({"segments": ()}, ValueError),
+        ({"segments": (TranscriptSegmentRecord(0, 1_200, "ok"), "not-a-record")}, TypeError),
+        ({"video_part_id": 0}, ValueError),
+        ({"video_part_id": True}, TypeError),
+        ({"source_kind": "asr-local"}, ValueError),
+        ({"source_kind": "unknown"}, ValueError),
+        ({"language": "   "}, ValueError),
+        ({"language": None}, TypeError),
+        ({"run_id": "   "}, ValueError),
+        ({"started_at": 301, "finished_at": 300}, ValueError),
+        ({"created_at": -1}, ValueError),
+    ],
+)
+def test_invalid_write_arguments_are_rejected_without_writing(
+    tmp_root, override, error
+):
+    connection = open_database(tmp_root)
+    repository = TranscriptRepository(connection)
+    try:
+        part_id = _captioned_part(connection)
+        _run(repository, 1)
+        kwargs = _write_kwargs(part_id)
+        kwargs.update(override)
+
+        with pytest.raises(error):
+            repository.record_acquired_transcript(**kwargs)
+
+        assert _empty_store(connection) == (0, 0, 0)
+    finally:
+        connection.close()
+
+
+def test_unknown_part_and_unknown_run_fail_the_whole_write(tmp_root):
+    connection = open_database(tmp_root)
+    repository = TranscriptRepository(connection)
+    try:
+        part_id = _captioned_part(connection)
+        _run(repository, 1)
+
+        with pytest.raises(sqlite3.IntegrityError, match="unknown video_part_id"):
+            _record(repository, 9_999)
+        assert _empty_store(connection) == (0, 0, 0)
+
+        with pytest.raises(sqlite3.IntegrityError, match="unknown run_id"):
+            _record(repository, part_id, run_id="caption-run-missing")
+        assert _empty_store(connection) == (0, 0, 0)
+
+        # The run parent committed on its own survives both failures.
+        assert tuple(
+            connection.execute(
+                "SELECT outcome, finished_at FROM acquisition_runs "
+                "WHERE run_id = 'caption-run-1'"
+            ).fetchone()
+        ) == ("running", None)
+    finally:
+        connection.close()
+
+
+def test_attempt_conflict_rolls_back_the_version_it_would_have_stored(tmp_root):
+    connection = open_database(tmp_root)
+    repository = TranscriptRepository(connection)
+    try:
+        part_id = _captioned_part(connection)
+        run_id = _run(repository, 1)
+        stored = _record(repository, part_id, run_id=run_id)
+
+        # One outcome per attempted part per run: the attempt row is written
+        # last, so its rejection must take the new version down with it.
+        with pytest.raises(sqlite3.IntegrityError):
+            _record(
+                repository,
+                part_id,
+                run_id=run_id,
+                body=CHANGED_BODY,
+                started_at=210,
+                finished_at=310,
+            )
+
+        assert _transcript_rows(connection, part_id) == [
+            (1, "subtitle-cc", "zh-CN", None, stored.content_sha256, 400)
+        ]
+        assert _segment_rows(connection, stored.transcript_id) == [
+            (0, 0, 1_200, "第一句"),
+            (1, 1_200, 2_400, "第二句"),
+        ]
+        assert _attempt_rows(connection, run_id) == [
+            (run_id, part_id, "stored", None, stored.transcript_id, 200, 300)
+        ]
+
+        # The rolled-back call leaves no poisoned state behind: the same
+        # content lands as version 2 under the next run.
+        next_run = _run(repository, 2)
+        appended = _record(
+            repository, part_id, run_id=next_run, body=CHANGED_BODY
+        )
+        assert appended.outcome == "stored"
+        assert appended.version == 2
+    finally:
+        connection.close()
+
+
+def test_schema_foreign_keys_reject_orphans_and_restrict_deletes(tmp_root):
+    connection = open_database(tmp_root)
+    repository = TranscriptRepository(connection)
+    try:
+        part_id = _captioned_part(connection)
+        run_id = _run(repository, 1)
+        stored = _record(repository, part_id, run_id=run_id)
+
+        # An attempt cannot reference a transcript that does not exist.
+        with pytest.raises(sqlite3.IntegrityError):
+            connection.execute(
+                """
+                INSERT INTO acquisition_attempts(
+                    run_id, video_part_id, outcome, error_code, transcript_id,
+                    started_at, finished_at
+                ) VALUES (?, ?, 'stored', NULL, 9999, 200, 300)
+                """,
+                (run_id, part_id),
+            )
+
+        # A stored version is held by its segments and its attempt evidence.
+        with pytest.raises(sqlite3.IntegrityError):
+            connection.execute(
+                "DELETE FROM transcripts WHERE transcript_id = ?",
+                (stored.transcript_id,),
+            )
+        with pytest.raises(sqlite3.IntegrityError):
+            connection.execute(
+                "DELETE FROM video_parts WHERE video_part_id = ?", (part_id,)
+            )
+        with pytest.raises(sqlite3.IntegrityError):
+            connection.execute(
+                "DELETE FROM acquisition_runs WHERE run_id = ?", (run_id,)
+            )
+
+        assert _transcript_rows(connection, part_id) == [
+            (1, "subtitle-cc", "zh-CN", None, stored.content_sha256, 400)
+        ]
+        assert _segment_rows(connection, stored.transcript_id) == [
+            (0, 0, 1_200, "第一句"),
+            (1, 1_200, 2_400, "第二句"),
+        ]
+        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
+    finally:
+        connection.close()
+
+
+@pytest.mark.parametrize(
+    ("attempt_outcomes", "expected"),
+    [
+        ((), "complete"),
+        (("stored",), "complete"),
+        (("no-subtitle",), "complete"),
+        (("stored", "no-subtitle"), "complete"),
+        (("stored", "failed"), "partial"),
+        (("no-subtitle", "failed"), "partial"),
+        (("failed", "failed"), "failed"),
+    ],
+)
+def test_finish_derives_the_run_outcome_from_its_attempts(
+    tmp_root, attempt_outcomes, expected
+):
+    connection = open_database(tmp_root)
+    repository = TranscriptRepository(connection)
+    try:
+        run_id = _run(repository, 1)
+        for index, attempt_outcome in enumerate(attempt_outcomes):
+            part_id = _captioned_part(connection, f"BV1ATTEMPT{index}")
+            if attempt_outcome == "stored":
+                _record(
+                    repository,
+                    part_id,
+                    run_id=run_id,
+                    started_at=200 + index,
+                    finished_at=300 + index,
+                    created_at=400 + index,
+                )
+            else:
+                repository.record_subtitle_attempt(
+                    run_id=run_id,
+                    video_part_id=part_id,
+                    outcome=attempt_outcome,
+                    error_code="timeout" if attempt_outcome == "failed" else None,
+                    started_at=200 + index,
+                    finished_at=300 + index,
+                )
+
+        assert repository.finish_acquisition_run(run_id, 500) == expected
+        assert tuple(
+            connection.execute(
+                "SELECT outcome, finished_at FROM acquisition_runs WHERE run_id = ?",
+                (run_id,),
+            ).fetchone()
+        ) == (expected, 500)
+    finally:
+        connection.close()
+
+
+def test_finish_honours_an_explicit_outcome_and_never_regresses_a_terminal_one(tmp_root):
+    connection = open_database(tmp_root)
+    repository = TranscriptRepository(connection)
+    try:
+        part_id = _captioned_part(connection)
+        run_id = _run(repository, 1)
+        repository.record_subtitle_attempt(
+            run_id=run_id,
+            video_part_id=part_id,
+            outcome="failed",
+            error_code="timeout",
+            started_at=200,
+            finished_at=300,
+        )
+
+        # The explicit outcome is the operator's call; the derivation is only
+        # the default.
+        assert repository.finish_acquisition_run(run_id, 500, outcome="complete") == (
+            "complete"
+        )
+        assert tuple(
+            connection.execute(
+                "SELECT outcome, finished_at FROM acquisition_runs WHERE run_id = ?",
+                (run_id,),
+            ).fetchone()
+        ) == ("complete", 500)
+
+        with pytest.raises(sqlite3.IntegrityError, match="already finished"):
+            repository.finish_acquisition_run(run_id, 600, outcome="failed")
+        with pytest.raises(sqlite3.IntegrityError, match="already finished"):
+            repository.finish_acquisition_run(run_id, 600)
+        assert tuple(
+            connection.execute(
+                "SELECT outcome, finished_at FROM acquisition_runs WHERE run_id = ?",
+                (run_id,),
+            ).fetchone()
+        ) == ("complete", 500)
+    finally:
+        connection.close()
+
+
+def test_run_outcome_derivation_reads_only_its_own_attempts(tmp_root):
+    connection = open_database(tmp_root)
+    repository = TranscriptRepository(connection)
+    try:
+        failing_part = _captioned_part(connection, "BV1FAILING")
+        empty_run = _run(repository, 1)
+        failing_run = _run(repository, 2)
+        repository.record_subtitle_attempt(
+            run_id=failing_run,
+            video_part_id=failing_part,
+            outcome="failed",
+            error_code="timeout",
+            started_at=200,
+            finished_at=300,
+        )
+
+        assert repository.finish_acquisition_run(empty_run, 500) == "complete"
+        assert repository.finish_acquisition_run(failing_run, 501) == "failed"
+    finally:
+        connection.close()
+
+
+def test_finish_records_an_abnormal_failure_without_recomputing_it(tmp_root):
+    connection = open_database(tmp_root)
+    repository = TranscriptRepository(connection)
+    try:
+        part_id = _captioned_part(connection)
+        run_id = _run(repository, 1)
+
+        # A run the service aborts before a single part was probed: the
+        # operator's `failed` is the recorded truth, not the `complete` the
+        # attempt derivation would have produced.
+        assert repository.finish_acquisition_run(run_id, 500, outcome="failed") == (
+            "failed"
+        )
+        stored = _record(
+            repository, part_id, run_id=run_id, started_at=510, finished_at=520
+        )
+        assert stored.outcome == "stored"
+        assert tuple(
+            connection.execute(
+                "SELECT outcome, finished_at FROM acquisition_runs WHERE run_id = ?",
+                (run_id,),
+            ).fetchone()
+        ) == ("failed", 500)
+    finally:
+        connection.close()
+
+
+def test_finish_validates_its_arguments_and_the_run_it_targets(tmp_root):
+    connection = open_database(tmp_root)
+    repository = TranscriptRepository(connection)
+    try:
+        run_id = _run(repository, 1, started_at=100)
+
+        with pytest.raises(sqlite3.IntegrityError, match="unknown run_id"):
+            repository.finish_acquisition_run("caption-run-missing", 500)
+        with pytest.raises(ValueError):
+            repository.finish_acquisition_run(run_id, 500, outcome="running")
+        with pytest.raises(ValueError):
+            repository.finish_acquisition_run(run_id, 500, outcome="unknown")
+        with pytest.raises(TypeError):
+            repository.finish_acquisition_run(run_id, True)
+        with pytest.raises(ValueError):
+            repository.finish_acquisition_run("   ", 500)
+        with pytest.raises(ValueError):
+            repository.finish_acquisition_run(run_id, 99)
+
+        assert tuple(
+            connection.execute(
+                "SELECT outcome, finished_at FROM acquisition_runs WHERE run_id = ?",
+                (run_id,),
+            ).fetchone()
+        ) == ("running", None)
+
+        # The stored started_at is the ordering baseline, and a run with no
+        # attempts at all is a complete run of an empty work set.
+        assert repository.finish_acquisition_run(run_id, 100) == "complete"
+    finally:
+        connection.close()
+
+
+def test_start_acquisition_run_rejects_a_duplicate_run_id(tmp_root):
+    connection = open_database(tmp_root)
+    repository = TranscriptRepository(connection)
+    try:
+        _run(repository, 1, selector_kind="bvid", selector_target="BV1CAPTION")
+
+        with pytest.raises(sqlite3.IntegrityError):
+            repository.start_acquisition_run(
+                _caption_run("caption-run-1", started_at=999)
+            )
+
+        assert [
+            tuple(row)
+            for row in connection.execute(
+                "SELECT run_id, kind, selector_kind, selector_target, requested_limit, "
+                "credential_present, started_at, finished_at, outcome "
+                "FROM acquisition_runs"
+            ).fetchall()
+        ] == [
+            (
+                "caption-run-1",
+                "subtitle",
+                "bvid",
+                "BV1CAPTION",
+                None,
+                0,
+                101,
+                None,
+                "running",
+            )
+        ]
+    finally:
+        connection.close()
+
+
+def test_no_subtitle_is_evidence_and_the_part_stays_reattemptable(tmp_root):
+    connection = open_database(tmp_root)
+    repository = TranscriptRepository(connection)
+    try:
+        part_id = _captioned_part(connection)
+        first_run = _run(repository, 1, credential_present=False)
+        repository.record_subtitle_attempt(
+            run_id=first_run,
+            video_part_id=part_id,
+            outcome="no-subtitle",
+            error_code=None,
+            started_at=200,
+            finished_at=300,
+        )
+        assert _attempt_rows(connection, first_run) == [
+            (first_run, part_id, "no-subtitle", None, None, 200, 300)
+        ]
+        assert connection.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0] == 0
+        assert tuple(
+            connection.execute(
+                "SELECT attempted, last_attempt_at, last_attempt_outcome, "
+                "last_attempt_error_code, last_attempt_credential_present "
+                "FROM v_pending_subtitles WHERE video_part_id = ?",
+                (part_id,),
+            ).fetchone()
+        ) == (1, 300, "no-subtitle", None, 0)
+
+        # Upstream signalled "not visible" on the next probe: the run's
+        # credential flag travels with the recorded code.
+        second_run = _run(repository, 2, credential_present=True, started_at=310)
+        repository.record_subtitle_attempt(
+            run_id=second_run,
+            video_part_id=part_id,
+            outcome="no-subtitle",
+            error_code="not_found",
+            started_at=320,
+            finished_at=330,
+        )
+        assert _attempt_rows(connection, second_run) == [
+            (second_run, part_id, "no-subtitle", "not_found", None, 320, 330)
+        ]
+        assert tuple(
+            connection.execute(
+                "SELECT attempted, last_attempt_outcome, last_attempt_error_code, "
+                "last_attempt_credential_present FROM v_pending_subtitles "
+                "WHERE video_part_id = ?",
+                (part_id,),
+            ).fetchone()
+        ) == (1, "no-subtitle", "not_found", 1)
+
+        # Nothing was ever terminal: a later successful acquisition of the
+        # same part stores a transcript normally.
+        third_run = _run(repository, 3, started_at=340)
+        stored = _record(
+            repository,
+            part_id,
+            run_id=third_run,
+            started_at=350,
+            finished_at=360,
+            created_at=370,
+        )
+        assert stored.outcome == "stored"
+        assert stored.version == 1
+        assert _attempt_rows(connection) == [
+            (first_run, part_id, "no-subtitle", None, None, 200, 300),
+            (second_run, part_id, "no-subtitle", "not_found", None, 320, 330),
+            (third_run, part_id, "stored", None, stored.transcript_id, 350, 360),
+        ]
+        assert connection.execute(
+            "SELECT COUNT(*) FROM v_pending_subtitles WHERE video_part_id = ?",
+            (part_id,),
+        ).fetchone()[0] == 0
+    finally:
+        connection.close()
+
+
+@pytest.mark.parametrize(
+    ("override", "error"),
+    [
+        ({"outcome": "stored"}, ValueError),
+        ({"outcome": "unchanged"}, ValueError),
+        ({"outcome": "unknown"}, ValueError),
+        ({"outcome": "failed", "error_code": None}, ValueError),
+        ({"outcome": "failed", "error_code": "e" * 65}, ValueError),
+        ({"outcome": "failed", "error_code": '{"code": -403}'}, ValueError),
+        ({"outcome": "no-subtitle", "error_code": "timeout"}, ValueError),
+        ({"outcome": "no-subtitle", "error_code": 101}, TypeError),
+        ({"video_part_id": 0}, ValueError),
+        ({"started_at": 301, "finished_at": 300}, ValueError),
+    ],
+)
+def test_subtitle_attempt_rejects_every_illegal_outcome_and_code(
+    tmp_root, override, error
+):
+    connection = open_database(tmp_root)
+    repository = TranscriptRepository(connection)
+    try:
+        part_id = _captioned_part(connection)
+        run_id = _run(repository, 1)
+        kwargs: dict = {
+            "run_id": run_id,
+            "video_part_id": part_id,
+            "outcome": "failed",
+            "error_code": "timeout",
+            "started_at": 200,
+            "finished_at": 300,
+        }
+        kwargs.update(override)
+
+        with pytest.raises(error):
+            repository.record_subtitle_attempt(**kwargs)
+
+        assert _attempt_rows(connection) == []
+    finally:
+        connection.close()
+
+
+def test_subtitle_attempt_is_append_only_per_part_and_run(tmp_root):
+    connection = open_database(tmp_root)
+    repository = TranscriptRepository(connection)
+    try:
+        part_id = _captioned_part(connection)
+        first_run = _run(repository, 1)
+        repository.record_subtitle_attempt(
+            run_id=first_run,
+            video_part_id=part_id,
+            outcome="failed",
+            error_code="timeout",
+            started_at=200,
+            finished_at=300,
+        )
+
+        with pytest.raises(sqlite3.IntegrityError):
+            repository.record_subtitle_attempt(
+                run_id=first_run,
+                video_part_id=part_id,
+                outcome="no-subtitle",
+                error_code=None,
+                started_at=310,
+                finished_at=320,
+            )
+        assert _attempt_rows(connection, first_run) == [
+            (first_run, part_id, "failed", "timeout", None, 200, 300)
+        ]
+
+        # A later run records its own evidence for the same part.
+        second_run = _run(repository, 2, started_at=330)
+        repository.record_subtitle_attempt(
+            run_id=second_run,
+            video_part_id=part_id,
+            outcome="no-subtitle",
+            error_code=None,
+            started_at=340,
+            finished_at=350,
+        )
+        assert _attempt_rows(connection) == [
+            (first_run, part_id, "failed", "timeout", None, 200, 300),
+            (second_run, part_id, "no-subtitle", None, None, 340, 350),
+        ]
+    finally:
+        connection.close()
+
+
+def test_timeline_ceiling_is_the_storage_boundarys_rejection(tmp_root):
+    """S11: an unrepresentable millisecond value is a bounded ValueError."""
+    connection = open_database(tmp_root)
+    repository = TranscriptRepository(connection)
+    try:
+        assert MAX_TIMELINE_MS == 10**12
+        # The bound belongs to the storage boundary, not to the segment
+        # record, which validates the shape of one row.
+        assert (
+            TranscriptSegmentRecord(start_ms=0, end_ms=10**19, text="越界").end_ms
+            == 10**19
+        )
+
+        boundary_part = _captioned_part(connection, "BV1BOUNDARY")
+        beyond_part = _captioned_part(connection, "BV1BEYOND")
+        boundary_run = _run(repository, 1)
+        beyond_run = _run(repository, 2)
+
+        at_ceiling = _record(
+            repository,
+            boundary_part,
+            run_id=boundary_run,
+            body=((0, MAX_TIMELINE_MS, "边界"),),
+        )
+        assert at_ceiling.outcome == "stored"
+        assert _segment_rows(connection, at_ceiling.transcript_id) == [
+            (0, 0, MAX_TIMELINE_MS, "边界")
+        ]
+
+        with pytest.raises(
+            ValueError, match=f"segments\\[0\\]\\.end_ms must be at most {MAX_TIMELINE_MS}"
+        ):
+            _record(
+                repository,
+                beyond_part,
+                run_id=beyond_run,
+                body=((0, MAX_TIMELINE_MS + 1, "越界"),),
+            )
+        # A start above the ceiling is rejected as well, and so is a value
+        # beyond the 64-bit integer SQLite binds: the guard is the only thing
+        # between an upstream JSON integer and an OverflowError.
+        for beyond_body in (
+            ((MAX_TIMELINE_MS + 1, MAX_TIMELINE_MS + 2, "越界"),),
+            ((0, 10**19, "越界"),),
+        ):
+            with pytest.raises(ValueError):
+                _record(
+                    repository, beyond_part, run_id=beyond_run, body=beyond_body
+                )
+
+        assert _transcript_rows(connection, beyond_part) == []
+        assert _attempt_rows(connection, beyond_run) == []
+    finally:
+        connection.close()
+
+
+def test_constructor_requires_the_open_database_connection_state(tmp_root):
+    with pytest.raises(TypeError):
+        TranscriptRepository("not a connection")
+
+    connection = sqlite3.connect(os.path.join(tmp_root, "bare.db"))
+    try:
+        with pytest.raises(TypeError):
+            TranscriptRepository(connection)
+        connection.row_factory = sqlite3.Row
+        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 0
+        with pytest.raises(ValueError):
+            TranscriptRepository(connection)
+    finally:
+        connection.close()
+
+
+def test_committed_writes_are_visible_outside_the_writing_connection(tmp_root):
+    database_path = os.path.join(tmp_root, "archive.db")
+    connection = open_database(database_path)
+    observer = sqlite3.connect(database_path)
+    observer.row_factory = sqlite3.Row
+    try:
+        repository = TranscriptRepository(connection)
+        part_id = _captioned_part(connection)
+        assert observer.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0] == 1
+
+        # start_acquisition_run commits its own insert.
+        run_id = _run(repository, 1)
+        assert (
+            observer.execute("SELECT COUNT(*) FROM acquisition_runs").fetchone()[0]
+            == 1
+        )
+
+        # record_acquired_transcript commits the version, its segments, and its
+        # attempt row as one transaction.
+        stored = _record(repository, part_id, run_id=run_id)
+        assert tuple(
+            observer.execute(
+                "SELECT version, content_sha256 FROM transcripts"
+            ).fetchone()
+        ) == (1, stored.content_sha256)
+        assert (
+            observer.execute("SELECT COUNT(*) FROM transcript_segments").fetchone()[0]
+            == 2
+        )
+        assert (
+            observer.execute("SELECT COUNT(*) FROM acquisition_attempts").fetchone()[0]
+            == 1
+        )
+
+        # record_subtitle_attempt commits its own evidence transaction.
+        other_part = _captioned_part(connection, "BV1PROBED")
+        empty_run = _run(repository, 2)
+        repository.record_subtitle_attempt(
+            run_id=empty_run,
+            video_part_id=other_part,
+            outcome="no-subtitle",
+            error_code=None,
+            started_at=200,
+            finished_at=300,
+        )
+        assert tuple(
+            observer.execute(
+                "SELECT outcome, transcript_id FROM acquisition_attempts "
+                "WHERE run_id = ?",
+                (empty_run,),
+            ).fetchone()
+        ) == ("no-subtitle", None)
+
+        # finish_acquisition_run commits its own terminal transition.
+        assert repository.finish_acquisition_run(empty_run, 400) == "complete"
+        assert tuple(
+            observer.execute(
+                "SELECT outcome, finished_at FROM acquisition_runs WHERE run_id = ?",
+                (empty_run,),
+            ).fetchone()
+        ) == ("complete", 400)
+    finally:
+        observer.close()
+        connection.close()
+
+
+def test_read_transcript_returns_the_latest_version_and_keeps_an_older_one_readable(
+    tmp_root,
+):
+    connection = open_database(tmp_root)
+    repository = TranscriptRepository(connection)
+    try:
+        part_id = _captioned_part(connection)
+        cc_v1 = _record(repository, part_id, run_id=_run(repository, 1))
+        cc_v2 = _record(
+            repository,
+            part_id,
+            run_id=_run(repository, 2),
+            body=CHANGED_BODY,
+            started_at=210,
+            finished_at=310,
+            created_at=410,
+        )
+        ai_v1 = _record(
+            repository,
+            part_id,
+            run_id=_run(repository, 3),
+            source_kind="subtitle-ai",
+            language="ai-zh",
+            started_at=220,
+            finished_at=320,
+            created_at=420,
+        )
+        stored_counts = _empty_store(connection)
+
+        latest = repository.read_transcript(part_id, "subtitle-cc", "zh-CN")
+
+        assert isinstance(latest, TranscriptRecord)
+        assert latest.transcript_id == cc_v2.transcript_id
+        assert latest.version == 2
+        assert latest.video_part_id == part_id
+        assert latest.source_kind == "subtitle-cc"
+        assert latest.language == "zh-CN"
+        assert latest.model_id is None
+        assert latest.content_sha256 == cc_v2.content_sha256
+        assert latest.created_at == 410
+        assert _triples(latest.segments) == list(CHANGED_BODY)
+
+        # One part carries several languages, each with its own version history.
+        ai = repository.read_transcript(part_id, "subtitle-ai", "ai-zh")
+        assert ai is not None
+        assert (ai.transcript_id, ai.version) == (ai_v1.transcript_id, 1)
+        assert ai.content_sha256 == ai_v1.content_sha256
+        assert _triples(ai.segments) == list(BODY)
+
+        # An explicit older version stays readable after the newer one landed.
+        first = repository.read_transcript(part_id, "subtitle-cc", "zh-CN", 1)
+        assert first is not None
+        assert (first.transcript_id, first.version) == (cc_v1.transcript_id, 1)
+        assert first.content_sha256 == cc_v1.content_sha256
+        assert first.created_at == 400
+        assert _triples(first.segments) == list(BODY)
+
+        # The read names the identity the write stored: the same trimming.
+        padded = repository.read_transcript(part_id, "subtitle-cc", " zh-CN ")
+        assert padded is not None and padded.version == 2
+
+        # Read paths never write and never commit.
+        assert _empty_store(connection) == stored_counts
+        assert connection.in_transaction is False
+    finally:
+        connection.close()
+
+
+def test_list_transcript_versions_lists_one_identitys_versions_oldest_first(tmp_root):
+    connection = open_database(tmp_root)
+    repository = TranscriptRepository(connection)
+    try:
+        part_id = _captioned_part(connection)
+        cc_v1 = _record(repository, part_id, run_id=_run(repository, 1))
+        cc_v2 = _record(
+            repository,
+            part_id,
+            run_id=_run(repository, 2),
+            body=CHANGED_BODY,
+            created_at=410,
+        )
+        _record(
+            repository,
+            part_id,
+            run_id=_run(repository, 3),
+            source_kind="subtitle-ai",
+            language="ai-zh",
+        )
+
+        versions = repository.list_transcript_versions(part_id, "subtitle-cc", "zh-CN")
+
+        assert [row["version"] for row in versions] == [1, 2]
+        assert [row["transcript_id"] for row in versions] == [
+            cc_v1.transcript_id,
+            cc_v2.transcript_id,
+        ]
+        assert [row["content_sha256"] for row in versions] == [
+            cc_v1.content_sha256,
+            cc_v2.content_sha256,
+        ]
+        assert [row["created_at"] for row in versions] == [400, 410]
+        assert {row["source_kind"] for row in versions} == {"subtitle-cc"}
+        assert {row["language"] for row in versions} == {"zh-CN"}
+        # The rows are the stored rows: every transcript column is readable.
+        assert {
+            "transcript_id",
+            "video_part_id",
+            "source_kind",
+            "language",
+            "model_id",
+            "version",
+            "content_sha256",
+            "created_at",
+        } <= set(versions[0].keys())
+
+        # Another identity's versions are not mixed in, and the language is
+        # trimmed before the lookup exactly as the write path trims it.
+        other = repository.list_transcript_versions(part_id, "subtitle-ai", " ai-zh ")
+        assert [row["version"] for row in other] == [1]
+        assert connection.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0] == 3
+    finally:
+        connection.close()
+
+
+def test_reads_of_absent_versions_identities_and_parts_are_empty(tmp_root):
+    connection = open_database(tmp_root)
+    repository = TranscriptRepository(connection)
+    try:
+        part_id = _captioned_part(connection)
+        stored = _record(repository, part_id, run_id=_run(repository, 1))
+
+        assert repository.read_transcript(part_id, "subtitle-cc", "zh-CN", 2) is None
+        assert repository.read_transcript(part_id, "subtitle-cc", "en-US") is None
+        assert repository.read_transcript(part_id, "subtitle-ai", "zh-CN") is None
+        assert repository.read_transcript(9_999, "subtitle-cc", "zh-CN") is None
+        assert repository.list_transcript_versions(part_id, "subtitle-cc", "en-US") == []
+        assert repository.list_transcript_versions(part_id, "subtitle-ai", "zh-CN") == []
+
+        # The asr-local reservation is a legal read that holds no row yet: the
+        # read accepts the vocabulary the column's CHECK accepts.
+        assert repository.read_transcript(part_id, "asr-local", "zh-CN") is None
+        assert repository.list_transcript_versions(part_id, "asr-local", "zh-CN") == []
+
+        versions = repository.list_transcript_versions(part_id, "subtitle-cc", "zh-CN")
+        assert [row["version"] for row in versions] == [1]
+        assert versions[0]["transcript_id"] == stored.transcript_id
+        assert versions[0]["content_sha256"] == stored.content_sha256
+        assert _empty_store(connection) == (1, 2, 1)
+    finally:
+        connection.close()
+
+
+def test_pending_enumeration_orders_never_attempted_before_the_oldest_attempt(tmp_root):
+    """The locked order: attempted ASC, last_attempt_at ASC, bvid ASC, page_index ASC."""
+    connection = open_database(tmp_root)
+    repository = TranscriptRepository(connection)
+    try:
+        # Insertion order deliberately differs from the work order, so a
+        # missing ORDER BY cannot pass by accident. Both captionless videos
+        # hold page 0 and page 1, so the never-attempted set is a case where
+        # ``bvid`` first and ``page_index`` first interleave differently: the
+        # lock's last two keys are falsifiable, not merely spelled out.
+        first_video = _video_with_parts(connection, "BV1A", (3001, 3002, 3003, 3004))
+        _video_with_parts(connection, "BV0Z", (4001, 4002))
+        _video_with_parts(connection, "BV1GONE", (5001,), processing_status="gone")
+        _probe(repository, first_video[2], index=1, finished_at=500)
+        _probe(repository, first_video[3], index=2, finished_at=300)
+
+        work_ids = [row["work_id"] for row in repository.list_pending_subtitle_parts()]
+
+        assert work_ids == [
+            "BV0Z:p0",  # never attempted: lowest bvid, then lowest page index,
+            "BV0Z:p1",  # so this block is BV0Z's two pages and then BV1A's two;
+            "BV1A:p0",  # ordering by page_index first would interleave it as
+            "BV1A:p1",  # BV0Z:p0, BV1A:p0, BV0Z:p1, BV1A:p1 instead.
+            "BV1A:p3",  # oldest attempt first
+            "BV1A:p2",
+        ]
+        # A part upstream reported as gone is not work: the enumeration is
+        # bounded to what can still yield a caption.
+        assert "BV1GONE:p0" not in work_ids
+        assert repository.count_pending_subtitle_parts() == len(work_ids) == 6
+
+        # The bound takes the head of the locked order.
+        assert [
+            row["work_id"] for row in repository.list_pending_subtitle_parts(limit=1)
+        ] == ["BV0Z:p0"]
+        assert [
+            row["work_id"] for row in repository.list_pending_subtitle_parts(limit=2)
+        ] == ["BV0Z:p0", "BV0Z:p1"]
+        assert [
+            row["work_id"] for row in repository.list_pending_subtitle_parts(limit=6)
+        ] == work_ids
+    finally:
+        connection.close()
+
+
+def test_pending_enumeration_carries_the_last_attempt_evidence_and_excludes_stored_parts(
+    tmp_root,
+):
+    connection = open_database(tmp_root)
+    repository = TranscriptRepository(connection)
+    try:
+        parts = _video_with_parts(connection, "BV1EVID", (6001, 6002, 6003))
+        metadata_only, probed, captioned = parts[0], parts[1], parts[2]
+        stored = _record(repository, captioned, run_id=_run(repository, 1))
+        _probe(repository, probed, index=2, finished_at=300)
+        _probe(
+            repository,
+            probed,
+            index=3,
+            finished_at=500,
+            error_code="not_found",
+            credential_present=True,
+        )
+
+        rows = repository.list_pending_subtitle_parts()
+
+        # The part holding a transcript is not pending work any more; the part
+        # with metadata only and the probed part both are.
+        assert [row["work_id"] for row in rows] == ["BV1EVID:p0", "BV1EVID:p1"]
+        assert {row["video_part_id"] for row in rows}.isdisjoint({captioned})
+        assert repository.count_pending_subtitle_parts() == len(rows) == 2
+        assert stored.version == 1
+
+        # The work item is complete: the gateway call needs the cid, and the
+        # subtitle path never re-fetches a pagelist.
+        assert set(rows[0].keys()) == {
+            "video_part_id",
+            "work_id",
+            "bvid",
+            "page_index",
+            "cid",
+            "part_title",
+            "duration_ms",
+            "attempted",
+            "last_attempt_at",
+            "last_attempt_outcome",
+            "last_attempt_error_code",
+            "last_attempt_credential_present",
+        }
+
+        fresh = rows[0]
+        assert fresh["video_part_id"] == metadata_only
+        assert fresh["bvid"] == "BV1EVID"
+        assert fresh["page_index"] == 0
+        assert fresh["cid"] == 6001
+        assert fresh["part_title"] == "第1集"
+        assert fresh["duration_ms"] == 1_234
+        assert fresh["attempted"] == 0
+        assert fresh["last_attempt_at"] is None
+        assert fresh["last_attempt_outcome"] is None
+        assert fresh["last_attempt_error_code"] is None
+        assert fresh["last_attempt_credential_present"] is None
+
+        # "No caption was visible" is evidence, not a terminal state: the part
+        # stays in the backlog with its newest attempt, its code, and the
+        # credential presence of the run that probed it.
+        retried = rows[1]
+        assert retried["video_part_id"] == probed
+        assert retried["cid"] == 6002
+        assert retried["attempted"] == 1
+        assert retried["last_attempt_at"] == 500
+        assert retried["last_attempt_outcome"] == "no-subtitle"
+        assert retried["last_attempt_error_code"] == "not_found"
+        assert retried["last_attempt_credential_present"] == 1
+    finally:
+        connection.close()
+
+
+def test_a_part_recorded_no_subtitle_leaves_the_pending_set_when_a_later_run_stores_it(
+    tmp_root,
+):
+    connection = open_database(tmp_root)
+    repository = TranscriptRepository(connection)
+    try:
+        parts = _video_with_parts(connection, "BV1RETRY", (7001, 7002, 7003))
+        probed, untouched, failing = parts[0], parts[1], parts[2]
+        probe_run = _probe(
+            repository,
+            probed,
+            index=1,
+            finished_at=300,
+            error_code="not_found",
+            credential_present=True,
+        )
+        failed_run = _run(repository, 2, started_at=340)
+        repository.record_subtitle_attempt(
+            run_id=failed_run,
+            video_part_id=failing,
+            outcome="failed",
+            error_code="timeout",
+            started_at=340,
+            finished_at=350,
+        )
+        assert repository.finish_acquisition_run(probe_run, 310) == "complete"
+        assert repository.finish_acquisition_run(failed_run, 360) == "failed"
+
+        # Both kinds of evidence keep their part in the backlog, and the
+        # never-attempted part is enumerated before both.
+        assert [row["work_id"] for row in repository.list_pending_subtitle_parts()] == [
+            "BV1RETRY:p1",
+            "BV1RETRY:p0",
+            "BV1RETRY:p2",
+        ]
+
+        harvest_run = _run(repository, 3, started_at=400)
+        stored = _record(
+            repository,
+            probed,
+            run_id=harvest_run,
+            started_at=410,
+            finished_at=420,
+            created_at=430,
+        )
+
+        assert stored.outcome == "stored"
+        assert stored.version == 1
+        # The run is finished after its part loop, so the outcome stays a
+        # function of the attempts it holds.
+        assert repository.finish_acquisition_run(harvest_run, 440) == "complete"
+        assert [row["work_id"] for row in repository.list_pending_subtitle_parts()] == [
+            "BV1RETRY:p1",
+            "BV1RETRY:p2",
+        ]
+        assert repository.count_pending_subtitle_parts() == 2
+
+        # Every probe stays readable as run-scoped evidence.
+        assert _attempt_rows(connection, probe_run) == [
+            (probe_run, probed, "no-subtitle", "not_found", None, 290, 300)
+        ]
+        assert _attempt_rows(connection, failed_run) == [
+            (failed_run, failing, "failed", "timeout", None, 340, 350)
+        ]
+        assert _attempt_rows(connection, harvest_run) == [
+            (harvest_run, probed, "stored", None, stored.transcript_id, 410, 420)
+        ]
+        reread = repository.read_transcript(probed, "subtitle-cc", "zh-CN")
+        assert reread is not None and reread.version == 1
+    finally:
+        connection.close()
+
+
+def test_list_selected_parts_selects_explicitly_or_returns_no_rows(tmp_root):
+    connection = open_database(tmp_root)
+    repository = TranscriptRepository(connection)
+    try:
+        parts = _video_with_parts(connection, "BV1SELECT", (8001, 8002))
+        stored = _record(repository, parts[0], run_id=_run(repository, 1))
+        _video_with_parts(connection, "BV1GONEVID", (8101,), processing_status="gone")
+
+        rows = repository.list_selected_parts("BV1SELECT")
+
+        assert [row["work_id"] for row in rows] == ["BV1SELECT:p0", "BV1SELECT:p1"]
+        assert [row["cid"] for row in rows] == [8001, 8002]
+        assert set(rows[0].keys()) == {
+            "video_part_id",
+            "work_id",
+            "user_name",
+            "video_title",
+            "page_index",
+            "cid",
+            "part_title",
+            "duration_ms",
+            "processing_status",
+            "created_at",
+            "updated_at",
+        }
+        # Explicit means explicit: the part that already holds a transcript is
+        # selected, which is how the operator re-checks a video.
+        assert rows[0]["video_part_id"] == parts[0]
+        assert rows[0]["work_id"] == f"BV1SELECT:p{rows[0]['page_index']}"
+        assert stored.version == 1
+        assert repository.read_transcript(parts[0], "subtitle-cc", "zh-CN") is not None
+
+        one = repository.list_selected_parts("BV1SELECT", 1)
+        assert [row["work_id"] for row in one] == ["BV1SELECT:p1"]
+        assert one[0]["video_part_id"] == parts[1]
+
+        # An explicit selection is not filtered by status, while the pending
+        # enumeration leaves a gone part out.
+        assert [
+            row["work_id"] for row in repository.list_selected_parts("BV1GONEVID")
+        ] == ["BV1GONEVID:p0"]
+        assert repository.list_selected_parts("BV1GONEVID")[0]["processing_status"] == (
+            "gone"
+        )
+        assert [row["work_id"] for row in repository.list_pending_subtitle_parts()] == [
+            "BV1SELECT:p1"
+        ]
+
+        # An unknown selector yields no rows rather than an invented selection.
+        assert repository.list_selected_parts("BV1UNKNOWN") == []
+        assert repository.list_selected_parts("BV1UNKNOWN", 0) == []
+        assert repository.list_selected_parts("BV1SELECT", 9) == []
+    finally:
+        connection.close()
+
+
+def test_pending_enumeration_reuses_the_shipped_limit_validation(tmp_root):
+    """The bound is validated exactly like ``MetadataRepository.list_pending_parts``."""
+    connection = open_database(tmp_root)
+    try:
+        metadata = MetadataRepository(connection)
+        transcripts = TranscriptRepository(connection)
+
+        for bad_limit in (0, -1, True, "2", 1.5):
+            with pytest.raises((TypeError, ValueError)) as shipped:
+                metadata.list_pending_parts(bad_limit)
+            with pytest.raises(type(shipped.value)) as pending:
+                transcripts.list_pending_subtitle_parts(bad_limit)
+            assert str(pending.value) == str(shipped.value)
+        assert transcripts.list_pending_subtitle_parts(None) == []
+    finally:
+        connection.close()
+
+
+def test_read_paths_consume_the_views_instead_of_re_deriving_them(tmp_root):
+    """The backlog and the explicit selection are view reads, not re-derivations.
+
+    Dropping the relation a method claims to read is the cheapest way to prove
+    the claim: a re-derived query over the base tables would keep answering.
+    """
+    connection = open_database(tmp_root)
+    repository = TranscriptRepository(connection)
+    try:
+        _video_with_parts(connection, "BV1VIEW", (9001,))
+        assert [row["work_id"] for row in repository.list_pending_subtitle_parts()] == [
+            "BV1VIEW:p0"
+        ]
+        assert repository.count_pending_subtitle_parts() == 1
+        assert [row["work_id"] for row in repository.list_selected_parts("BV1VIEW")] == [
+            "BV1VIEW:p0"
+        ]
+
+        connection.execute("DROP VIEW v_pending_subtitles")
+        with pytest.raises(sqlite3.OperationalError, match="v_pending_subtitles"):
+            repository.list_pending_subtitle_parts()
+        with pytest.raises(sqlite3.OperationalError, match="v_pending_subtitles"):
+            repository.count_pending_subtitle_parts()
+
+        connection.execute("DROP VIEW v_video_parts")
+        with pytest.raises(sqlite3.OperationalError, match="v_video_parts"):
+            repository.list_selected_parts("BV1VIEW")
+    finally:
+        connection.close()
+
+
+@pytest.mark.parametrize(
+    ("method", "kwargs", "error"),
+    [
+        (
+            "read_transcript",
+            {"video_part_id": 0, "source_kind": "subtitle-cc", "language": "zh-CN"},
+            ValueError,
+        ),
+        (
+            "read_transcript",
+            {"video_part_id": True, "source_kind": "subtitle-cc", "language": "zh-CN"},
+            TypeError,
+        ),
+        (
+            "read_transcript",
+            {"video_part_id": 1, "source_kind": "unknown", "language": "zh-CN"},
+            ValueError,
+        ),
+        (
+            "read_transcript",
+            {"video_part_id": 1, "source_kind": "subtitle-cc", "language": "   "},
+            ValueError,
+        ),
+        (
+            "read_transcript",
+            {"video_part_id": 1, "source_kind": "subtitle-cc", "language": None},
+            TypeError,
+        ),
+        (
+            "read_transcript",
+            {
+                "video_part_id": 1,
+                "source_kind": "subtitle-cc",
+                "language": "zh-CN",
+                "version": 0,
+            },
+            ValueError,
+        ),
+        (
+            "list_transcript_versions",
+            {"video_part_id": 0, "source_kind": "x", "language": "y"},
+            ValueError,
+        ),
+        ("list_selected_parts", {"bvid": "   "}, ValueError),
+        ("list_selected_parts", {"bvid": None}, TypeError),
+        ("list_selected_parts", {"bvid": "BV1SELECT", "page_index": -1}, ValueError),
+        ("list_selected_parts", {"bvid": "BV1SELECT", "page_index": True}, TypeError),
+        ("list_pending_subtitle_parts", {"limit": 0}, ValueError),
+        ("list_pending_subtitle_parts", {"limit": True}, TypeError),
+        ("list_pending_subtitle_parts", {"limit": "2"}, TypeError),
+    ],
+)
+def test_read_arguments_follow_the_module_validation_discipline(
+    tmp_root, method, kwargs, error
+):
+    """Read-path arguments raise ``TypeError``/``ValueError`` as the writes do."""
+    connection = open_database(tmp_root)
+    repository = TranscriptRepository(connection)
+    try:
+        with pytest.raises(error):
+            getattr(repository, method)(**kwargs)
+    finally:
+        connection.close()
+
+
+def test_work_id_is_computed_by_the_views_and_never_stored(tmp_root):
+    connection = open_database(tmp_root)
+    repository = TranscriptRepository(connection)
+    try:
+        part_id = _captioned_part(connection)
+        _run(repository, 1)
+
+        # The read rows carry the work identifier the views compute; the
+        # transcript contract stores no such column.
+        assert [
+            row["work_id"] for row in repository.list_pending_subtitle_parts()
+        ] == ["BV1CAPTION:p0"]
+        assert [
+            row["work_id"] for row in repository.list_selected_parts("BV1CAPTION")
+        ] == ["BV1CAPTION:p0"]
+        assert connection.execute(
+            "SELECT work_id FROM v_video_parts WHERE video_part_id = ?", (part_id,)
+        ).fetchone()[0] == "BV1CAPTION:p0"
+
+        for table in (
+            "transcripts",
+            "transcript_segments",
+            "acquisition_runs",
+            "acquisition_attempts",
+        ):
+            with pytest.raises(
+                sqlite3.OperationalError, match="no such column: work_id"
+            ):
+                connection.execute(f"UPDATE {table} SET work_id = 'BV1CAPTION:p0'")
+    finally:
+        connection.close()
+
+
+def test_segments_keep_the_callers_order_and_overlaps_verbatim(tmp_root):
+    """§5: upstream order is preserved verbatim, overlaps included."""
+    connection = open_database(tmp_root)
+    repository = TranscriptRepository(connection)
+    try:
+        part_id = _captioned_part(connection)
+        # Reversed and overlapping on purpose: the write must neither sort the
+        # body nor reject an interval that starts before the previous one ends.
+        body = (
+            (1_200, 2_400, "第二句"),
+            (600, 1_800, "与第二句重叠"),
+            (0, 1_200, "第一句"),
+        )
+
+        result = _record(repository, part_id, run_id=_run(repository, 1), body=body)
+
+        assert result.outcome == "stored"
+        assert result.content_sha256 == _expected_content_sha256(body)
+        assert _segment_rows(connection, result.transcript_id) == [
+            (0, 1_200, 2_400, "第二句"),
+            (1, 600, 1_800, "与第二句重叠"),
+            (2, 0, 1_200, "第一句"),
+        ]
+
+        # Sorting or de-overlapping the body on write would change the digest as
+        # well as the ordinals, so either regression fails here.
+        sorted_body = tuple(sorted(body, key=lambda triple: triple[0]))
+        assert sorted_body != body
+        assert result.content_sha256 != _expected_content_sha256(sorted_body)
+
+        # The same body is still content-identical, and the read path answers
+        # the order the caller supplied.
+        repeat_run = _run(repository, 2)
+        repeat = _record(repository, part_id, run_id=repeat_run, body=body)
+        assert repeat.outcome == "unchanged"
+        assert repeat.version == 1
+        stored = repository.read_transcript(part_id, "subtitle-cc", "zh-CN")
+        assert stored is not None
+        assert _triples(stored.segments) == list(body)
+    finally:
+        connection.close()
+
+
+@pytest.mark.parametrize(
+    ("bad_run_id", "error", "message"),
+    [
+        ("", ValueError, "run_id must not be empty"),
+        ("   ", ValueError, "run_id must not be empty"),
+        ("r\n1", ValueError, "run_id contains invalid control characters"),
+        ("r\x001", ValueError, "run_id contains invalid control characters"),
+        (None, TypeError, "run_id must be a string"),
+        (7, TypeError, "run_id must be a string"),
+    ],
+)
+def test_run_id_is_validated_by_one_shared_path_across_the_class(
+    tmp_root, bad_run_id, error, message
+):
+    """M2: every method answers a malformed ``run_id`` with the same message."""
+    connection = open_database(tmp_root)
+    repository = TranscriptRepository(connection)
+    try:
+        part_id = _captioned_part(connection)
+        run_id = _run(repository, 1)
+        stored_counts = _empty_store(connection)
+
+        calls = {
+            "start_acquisition_run": lambda: repository.start_acquisition_run(
+                _caption_run(bad_run_id)
+            ),
+            "finish_acquisition_run": lambda: repository.finish_acquisition_run(
+                bad_run_id, 500
+            ),
+            "record_acquired_transcript": lambda: _record(
+                repository, part_id, run_id=bad_run_id
+            ),
+            "record_subtitle_attempt": lambda: repository.record_subtitle_attempt(
+                run_id=bad_run_id,
+                video_part_id=part_id,
+                outcome="no-subtitle",
+                error_code=None,
+                started_at=200,
+                finished_at=300,
+            ),
+        }
+        for name, call in calls.items():
+            with pytest.raises(error) as raised:
+                call()
+            assert str(raised.value) == message, name
+
+        # A rejected identifier never reaches a write.
+        assert _empty_store(connection) == stored_counts
+        assert tuple(
+            connection.execute(
+                "SELECT outcome, finished_at FROM acquisition_runs WHERE run_id = ?",
+                (run_id,),
+            ).fetchone()
+        ) == ("running", None)
+    finally:
+        connection.close()
+
+
+def test_storage_paths_never_read_or_write_a_legacy_sidecar(tmp_root, monkeypatch):
+    """No storage path opens or creates a file in the archive root but ``archive.db``.
+
+    The legacy sidecars are planted with content no reader could accept, so a
+    path that consulted one would change its outcome or rewrite the file.  Every
+    Python-level open below the archive root is intercepted and recorded as well,
+    and the intercept is proven armed inside the test before it is trusted: SQLite
+    reaches the database through its own C library, so without that proof the
+    recorded list could stay empty and prove nothing about reads.
+    """
+    poison = {
+        os.path.join("manifest", "manifest.jsonl"): "poison: manifest\n",
+        "meta-cursor.json": "poison: cursor\n",
+        "run-ledger.jsonl": "poison: ledger\n",
+    }
+    assert set(poison) == set(LEGACY_SIDECAR_PATHS)
+    for relative, payload in poison.items():
+        path = os.path.join(tmp_root, relative)
+        os.makedirs(os.path.dirname(path), exist_ok=True)
+        with open(path, "w", encoding="utf-8") as handle:
+            handle.write(payload)
+
+    archive_root = os.path.realpath(tmp_root)
+    real_open = io.open
+    opened: list[str] = []
+
+    def guarded_open(file, *args, **kwargs):
+        target = os.path.realpath(os.fspath(file))
+        if target.startswith(archive_root + os.sep):
+            opened.append(target)
+            if os.path.basename(target) not in {"archive.db", "archive.db-journal"}:
+                raise AssertionError(f"a storage path opened the sidecar {target}")
+        return real_open(file, *args, **kwargs)
+
+    monkeypatch.setattr(io, "open", guarded_open)
+    monkeypatch.setattr(builtins, "open", guarded_open)
+
+    # The intercept fires on exactly the opens it must reject, so an empty
+    # record below is evidence and not an unarmed guard.
+    with pytest.raises(AssertionError, match="opened the sidecar"):
+        open(os.path.join(tmp_root, "meta-cursor.json"), encoding="utf-8")
+    assert [os.path.basename(path) for path in opened] == ["meta-cursor.json"]
+    opened.clear()
+
+    connection = open_database(tmp_root)
+    try:
+        repository = TranscriptRepository(connection)
+        part_id = _captioned_part(connection)
+        run_id = _run(repository, 1)
+        stored = _record(repository, part_id, run_id=run_id)
+
+        # Every read path runs too, so nothing is proven only about the writes.
+        assert repository.read_transcript(part_id, "subtitle-cc", "zh-CN") is not None
+        assert repository.list_transcript_versions(part_id, "subtitle-cc", "zh-CN")
+        assert repository.list_pending_subtitle_parts() == []
+        assert repository.count_pending_subtitle_parts() == 0
+        assert repository.list_selected_parts("BV1CAPTION")
+        assert repository.finish_acquisition_run(run_id, 500) == "complete"
+        assert stored.outcome == "stored"
+    finally:
+        connection.close()
+
+    # No storage path opened anything below the archive root through Python:
+    # the database itself is reached by SQLite's C library, so a sidecar read
+    # could only have come through this intercept, and it recorded nothing.
+    assert opened == []
+    # The archive root holds the database and exactly the files already there.
+    discovered = sorted(
+        os.path.relpath(os.path.join(folder, name), tmp_root)
+        for folder, _, names in os.walk(tmp_root)
+        for name in names
+    )
+    assert discovered == sorted(["archive.db", *poison])
+    for relative, payload in poison.items():
+        with real_open(os.path.join(tmp_root, relative), encoding="utf-8") as handle:
+            assert handle.read() == payload
```
