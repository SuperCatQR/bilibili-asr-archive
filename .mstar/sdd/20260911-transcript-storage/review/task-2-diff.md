# Task 2 Diff — 20260911-transcript-storage

Base: `d4cae24`
Head: `f3cd735`

```diff
diff --git a/bilibili-asr-archive/src/bili_asr/storage/__init__.py b/bilibili-asr-archive/src/bili_asr/storage/__init__.py
index 9382ce8..5db3531 100644
--- a/bilibili-asr-archive/src/bili_asr/storage/__init__.py
+++ b/bilibili-asr-archive/src/bili_asr/storage/__init__.py
@@ -8,6 +8,7 @@ from .database import (
     DatabaseConnection,
     MetadataRepository,
     SchemaContractError,
+    TranscriptRepository,
     duration_to_ms,
     initialize_schema,
     normalize_page_index,
@@ -18,11 +19,13 @@ from .models import (
     ALLOWED_ACQUISITION_KINDS,
     ALLOWED_ACQUISITION_OUTCOMES,
     ALLOWED_ATTEMPT_OUTCOMES,
+    ALLOWED_CAPTION_SOURCE_KINDS,
     ALLOWED_CURSOR_STATES,
     ALLOWED_PAGE_OUTCOMES,
     ALLOWED_PROCESSING_STATUS,
     ALLOWED_RUN_OUTCOMES,
     ALLOWED_SOURCE_KINDS,
+    MAX_TIMELINE_MS,
     AcquisitionKind,
     AcquisitionOutcome,
     AcquisitionRunRecord,
@@ -48,6 +51,7 @@ __all__ = [
     "ALLOWED_ACQUISITION_KINDS",
     "ALLOWED_ACQUISITION_OUTCOMES",
     "ALLOWED_ATTEMPT_OUTCOMES",
+    "ALLOWED_CAPTION_SOURCE_KINDS",
     "ALLOWED_CURSOR_STATES",
     "ALLOWED_PAGE_OUTCOMES",
     "ALLOWED_PROCESSING_STATUS",
@@ -63,12 +67,14 @@ __all__ = [
     "DiscoveryRecord",
     "IngestionPageRecord",
     "IngestionRunRecord",
+    "MAX_TIMELINE_MS",
     "MetadataRepository",
     "PageOutcome",
     "ProcessingStatus",
     "RunOutcome",
     "SchemaContractError",
     "SourceKind",
+    "TranscriptRepository",
     "TranscriptSegmentRecord",
     "TranscriptWriteResult",
     "UserRecord",
diff --git a/bilibili-asr-archive/src/bili_asr/storage/database.py b/bilibili-asr-archive/src/bili_asr/storage/database.py
index e8b3873..d2a1f95 100644
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
@@ -11,14 +13,24 @@ import sqlite3
 from typing import Iterable, Iterator, TypeAlias
 
 from .models import (
+    ALLOWED_ATTEMPT_OUTCOMES,
+    ALLOWED_CAPTION_SOURCE_KINDS,
     ALLOWED_RUN_OUTCOMES,
+    MAX_TIMELINE_MS,
+    AcquisitionRunRecord,
     CursorRecord,
     DiscoveryRecord,
     IngestionPageRecord,
     IngestionRunRecord,
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
 
 
@@ -26,6 +38,11 @@ DatabaseConnection: TypeAlias = sqlite3.Connection
 _ARCHIVE_DATABASE_NAME = "archive.db"
 _DATABASE_SUFFIXES = frozenset({".db", ".sqlite", ".sqlite3"})
 _TERMINAL_RUN_OUTCOMES = ALLOWED_RUN_OUTCOMES - frozenset({"running"})
+_TERMINAL_ACQUISITION_OUTCOMES = frozenset({"complete", "partial", "failed"})
+# The attempt outcomes ``record_subtitle_attempt`` owns: evidence of an
+# attempt that produced no transcript.  ``stored`` and ``unchanged`` are the
+# write path's own outcomes and are derived from it, never accepted here.
+_NO_TRANSCRIPT_ATTEMPT_OUTCOMES = ALLOWED_ATTEMPT_OUTCOMES - {"stored", "unchanged"}
 _SCHEMA_RESOURCE = resources.files(__package__).joinpath("schema.sql")
 _TRANSCRIPT_SCHEMA_RESOURCE = resources.files(__package__).joinpath(
     "schema-transcripts.sql"
@@ -186,6 +203,38 @@ def open_database(path: str | os.PathLike[str]) -> DatabaseConnection:
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
 
@@ -223,24 +272,14 @@ class MetadataRepository:
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
@@ -651,10 +690,424 @@ class MetadataRepository:
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
+        """
+        if not isinstance(run_id, str):
+            raise TypeError("run_id must be a string")
+        if not run_id.strip():
+            raise ValueError("run_id must be a non-empty string")
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
     "SchemaContractError",
+    "TranscriptRepository",
     "duration_to_ms",
     "initialize_schema",
     "normalize_page_index",
diff --git a/bilibili-asr-archive/src/bili_asr/storage/models.py b/bilibili-asr-archive/src/bili_asr/storage/models.py
index c82cbe4..2961a2f 100644
--- a/bilibili-asr-archive/src/bili_asr/storage/models.py
+++ b/bilibili-asr-archive/src/bili_asr/storage/models.py
@@ -35,15 +35,30 @@ _ALLOWED_SELECTOR_KINDS = frozenset({"pending", "bvid"})
 # The two outcomes a transcript write can report; the other attempt outcomes
 # record an acquisition that produced no transcript at all.
 _ALLOWED_TRANSCRIPT_WRITE_OUTCOMES = frozenset({"stored", "unchanged"})
+# The largest millisecond position a stored caption timeline accepts: about 31
+# years, far beyond any caption and far below the 64-bit integer SQLite binds,
+# so an upstream value that cannot be a caption timestamp is rejected with a
+# bounded ``ValueError`` instead of an ``OverflowError``.  The storage
+# boundary enforces it (``TranscriptRepository.record_acquired_transcript``),
+# not the segment record below, which validates the shape of one row.
+MAX_TIMELINE_MS = 10**12
 _ERROR_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]+$")
 _SHA256_HEX_PATTERN = re.compile(r"^[0-9a-f]{64}$")
 
 
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
 
 
@@ -82,10 +97,13 @@ def _boolean(value: object, field: str) -> bool:
 
 
 def _caption_text(value: object, field: str = "text") -> str:
-    """Validate verbatim caption text: a string non-empty after stripping.
+    """Validate caption text: a string non-empty after stripping.
 
-    Unlike :func:`_text`, control characters are kept: a caption row is stored
-    as upstream returned it.
+    Unlike :func:`_text`, control characters inside the string are kept — the
+    stored caption is verbatim apart from trimming.  Trimming is the storage
+    boundary's job, not this validator's: ``TranscriptRepository`` stores and
+    hashes the stripped form, so a caption's content identity never depends on
+    the whitespace a caller happens to carry.
     """
     if not isinstance(value, str):
         raise TypeError(f"{field} must be a string")
@@ -286,6 +304,11 @@ class TranscriptSegmentRecord:
     maps one DTO onto the other field for field: ``end_ms > start_ms >= 0``
     and ``text`` non-empty after stripping.  ``ordinal`` is positional and is
     assigned by the repository, never carried here.
+
+    The record carries the text a caller supplies; the storage boundary stores
+    and hashes its trimmed form, and it rejects a millisecond value above
+    :data:`MAX_TIMELINE_MS` — the two normalization rules this record cannot
+    state on its own.
     """
 
     start_ms: int
@@ -377,6 +400,7 @@ __all__ = [
     "DiscoveryRecord",
     "IngestionPageRecord",
     "IngestionRunRecord",
+    "MAX_TIMELINE_MS",
     "PageOutcome",
     "ProcessingStatus",
     "RunOutcome",
@@ -401,11 +425,17 @@ ALLOWED_ACQUISITION_KINDS = _ALLOWED_ACQUISITION_KINDS
 ALLOWED_ACQUISITION_OUTCOMES = _ALLOWED_ACQUISITION_OUTCOMES
 ALLOWED_ATTEMPT_OUTCOMES = _ALLOWED_ATTEMPT_OUTCOMES
 ALLOWED_SOURCE_KINDS = _ALLOWED_SOURCE_KINDS
+# The two source kinds whose content identity the partial index
+# ``ux_transcripts_subtitle_content`` enforces.  ``asr-local`` keeps its own
+# (per model/run) identity rule and is owned by the audio/ASR iteration, so a
+# caption write never accepts it.
+ALLOWED_CAPTION_SOURCE_KINDS = _ALLOWED_SOURCE_KINDS - {"asr-local"}
 
 __all__ += [
     "ALLOWED_ACQUISITION_KINDS",
     "ALLOWED_ACQUISITION_OUTCOMES",
     "ALLOWED_ATTEMPT_OUTCOMES",
+    "ALLOWED_CAPTION_SOURCE_KINDS",
     "ALLOWED_CURSOR_STATES",
     "ALLOWED_PAGE_OUTCOMES",
     "ALLOWED_PROCESSING_STATUS",
diff --git a/bilibili-asr-archive/tests/test_transcript_repository.py b/bilibili-asr-archive/tests/test_transcript_repository.py
new file mode 100644
index 0000000..7a64f12
--- /dev/null
+++ b/bilibili-asr-archive/tests/test_transcript_repository.py
@@ -0,0 +1,1132 @@
+"""Offline repository contract tests for transcript and acquisition writes."""
+
+from __future__ import annotations
+
+import hashlib
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
```
