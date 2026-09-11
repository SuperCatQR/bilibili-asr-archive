# Task 3 Diff — 20260911-transcript-storage

Base: `f3cd735`
Head: `1019000`
Note: includes the audit fixes applied to the interrupted run’s WIP (D1-D5).

```diff
diff --git a/bilibili-asr-archive/src/bili_asr/storage/__init__.py b/bilibili-asr-archive/src/bili_asr/storage/__init__.py
index 5db3531..87461a4 100644
--- a/bilibili-asr-archive/src/bili_asr/storage/__init__.py
+++ b/bilibili-asr-archive/src/bili_asr/storage/__init__.py
@@ -39,6 +39,7 @@ from .models import (
     ProcessingStatus,
     RunOutcome,
     SourceKind,
+    TranscriptRecord,
     TranscriptSegmentRecord,
     TranscriptWriteResult,
     UserRecord,
@@ -74,6 +75,7 @@ __all__ = [
     "RunOutcome",
     "SchemaContractError",
     "SourceKind",
+    "TranscriptRecord",
     "TranscriptRepository",
     "TranscriptSegmentRecord",
     "TranscriptWriteResult",
diff --git a/bilibili-asr-archive/src/bili_asr/storage/database.py b/bilibili-asr-archive/src/bili_asr/storage/database.py
index d2a1f95..499164c 100644
--- a/bilibili-asr-archive/src/bili_asr/storage/database.py
+++ b/bilibili-asr-archive/src/bili_asr/storage/database.py
@@ -16,12 +16,14 @@ from .models import (
     ALLOWED_ATTEMPT_OUTCOMES,
     ALLOWED_CAPTION_SOURCE_KINDS,
     ALLOWED_RUN_OUTCOMES,
+    ALLOWED_SOURCE_KINDS,
     MAX_TIMELINE_MS,
     AcquisitionRunRecord,
     CursorRecord,
     DiscoveryRecord,
     IngestionPageRecord,
     IngestionRunRecord,
+    TranscriptRecord,
     TranscriptSegmentRecord,
     TranscriptWriteResult,
     UserRecord,
@@ -722,6 +724,11 @@ class TranscriptRepository:
       evidence that produced it.
     - ``record_subtitle_attempt`` owns one transaction for one ``'no-subtitle'``
       or ``'failed'`` attempt and commits it.
+    - ``read_transcript``, ``list_transcript_versions``,
+      ``list_pending_subtitle_parts``, ``count_pending_subtitle_parts`` and
+      ``list_selected_parts`` never write and never commit: they return the
+      stored rows as they are — a typed ``TranscriptRecord`` for one stored
+      version, ``sqlite3.Row`` view data otherwise.
 
     Versions are immutable: no method rewrites or deletes a transcript row, a
     segment row, or an attempt row, and no method recomputes the outcome of a
@@ -789,11 +796,12 @@ class TranscriptRepository:
         a caller-supplied clock.  Re-finishing is rejected: a run whose stored
         outcome is already terminal raises ``sqlite3.IntegrityError`` and keeps
         both its outcome and its ``finished_at``.
+
+        ``run_id`` is validated by the same helper every other identifier in
+        this class goes through, so a malformed one is answered with the same
+        bounded message its siblings produce.
         """
-        if not isinstance(run_id, str):
-            raise TypeError("run_id must be a string")
-        if not run_id.strip():
-            raise ValueError("run_id must be a non-empty string")
+        run_id = _text(run_id, "run_id")
         _integer(finished_at, "finished_at", minimum=0)
         if outcome is not None:
             _choice(outcome, "outcome", _TERMINAL_ACQUISITION_OUTCOMES)
@@ -1000,6 +1008,174 @@ class TranscriptRepository:
                 (run_id, video_part_id, outcome, error_code, started_at, finished_at),
             )
 
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
     def _require_video_part(self, video_part_id: int) -> None:
         """Require that ``video_part_id`` names a part the archive already holds.
 
diff --git a/bilibili-asr-archive/src/bili_asr/storage/models.py b/bilibili-asr-archive/src/bili_asr/storage/models.py
index 2961a2f..a4c3e08 100644
--- a/bilibili-asr-archive/src/bili_asr/storage/models.py
+++ b/bilibili-asr-archive/src/bili_asr/storage/models.py
@@ -345,6 +345,49 @@ class TranscriptWriteResult:
         _content_sha256(self.content_sha256)
 
 
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
 @dataclass(frozen=True, slots=True)
 class AcquisitionRunRecord:
     """One acquisition run of one kind.
@@ -405,6 +448,7 @@ __all__ = [
     "ProcessingStatus",
     "RunOutcome",
     "SourceKind",
+    "TranscriptRecord",
     "TranscriptSegmentRecord",
     "TranscriptWriteResult",
     "UserRecord",
diff --git a/bilibili-asr-archive/tests/test_storage_schema.py b/bilibili-asr-archive/tests/test_storage_schema.py
index 2d3743c..1621515 100644
--- a/bilibili-asr-archive/tests/test_storage_schema.py
+++ b/bilibili-asr-archive/tests/test_storage_schema.py
@@ -253,6 +253,11 @@ EXPECTED_CHECK_ENUMERATIONS = {
         "length(content_sha256) = 64 AND content_sha256 = lower(content_sha256)",
         "UNIQUE (video_part_id, source_kind, language, version)",
     ),
+    "transcript_segments": (
+        "ordinal >= 0",
+        "start_ms >= 0",
+        "end_ms > start_ms",
+    ),
     "acquisition_runs": (
         "kind IN ('subtitle', 'audio', 'asr')",
         "selector_kind IN ('pending', 'bvid')",
@@ -1359,6 +1364,70 @@ def test_pending_subtitles_view_carries_the_newest_attempt_evidence(tmp_root):
         connection.close()
 
 
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
 @pytest.mark.parametrize(("outcome", "error_code", "transcript_id"), LEGAL_ATTEMPTS)
 def test_attempt_check_matrix_accepts_legal_evidence(
     tmp_root, outcome, error_code, transcript_id
diff --git a/bilibili-asr-archive/tests/test_transcript_repository.py b/bilibili-asr-archive/tests/test_transcript_repository.py
index 7a64f12..28db546 100644
--- a/bilibili-asr-archive/tests/test_transcript_repository.py
+++ b/bilibili-asr-archive/tests/test_transcript_repository.py
@@ -2,7 +2,9 @@
 
 from __future__ import annotations
 
+import builtins
 import hashlib
+import io
 import json
 import os
 import re
@@ -14,6 +16,7 @@ from bili_asr.storage import (
     MAX_TIMELINE_MS,
     AcquisitionRunRecord,
     MetadataRepository,
+    TranscriptRecord,
     TranscriptRepository,
     TranscriptSegmentRecord,
     TranscriptWriteResult,
@@ -24,6 +27,7 @@ from fixtures.metadata_records import (
     make_user_record,
     make_video_record,
 )
+from test_metadata_e2e import LEGACY_SIDECAR_PATHS
 
 
 BODY = ((0, 1_200, "第一句"), (1_200, 2_400, "第二句"))
@@ -52,6 +56,43 @@ def _captioned_part(connection: sqlite3.Connection, bvid: str = "BV1CAPTION") ->
     return int(row["video_part_id"])
 
 
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
 def _caption_run(
     run_id: str = "caption-run-1",
     *,
@@ -86,6 +127,33 @@ def _run(repository: TranscriptRepository, index: int, **overrides) -> str:
     return run_id
 
 
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
 def _segments(body=BODY) -> tuple[TranscriptSegmentRecord, ...]:
     """Build the segment tuple for one caption body of ``(start, end, text)``."""
     return tuple(TranscriptSegmentRecord(*triple) for triple in body)
@@ -126,6 +194,11 @@ def _expected_content_sha256(body) -> str:
     return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
 
 
+def _triples(segments) -> list[tuple[int, int, str]]:
+    """Return a stored record's segments as plain ``(start_ms, end_ms, text)``."""
+    return [(segment.start_ms, segment.end_ms, segment.text) for segment in segments]
+
+
 def _transcript_rows(connection: sqlite3.Connection, video_part_id: int) -> list[tuple]:
     """Return the stored versions of one part, oldest first."""
     return [
@@ -1130,3 +1203,724 @@ def test_committed_writes_are_visible_outside_the_writing_connection(tmp_root):
     finally:
         observer.close()
         connection.close()
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
+        # missing ORDER BY cannot pass by accident.
+        first_video = _video_with_parts(connection, "BV1A", (3001, 3002, 3003, 3004))
+        _video_with_parts(connection, "BV0Z", (4001,))
+        _video_with_parts(connection, "BV1GONE", (5001,), processing_status="gone")
+        _probe(repository, first_video[2], index=1, finished_at=500)
+        _probe(repository, first_video[3], index=2, finished_at=300)
+
+        work_ids = [row["work_id"] for row in repository.list_pending_subtitle_parts()]
+
+        assert work_ids == [
+            "BV0Z:p0",  # never attempted, lowest bvid
+            "BV1A:p0",  # never attempted, then lowest page index
+            "BV1A:p1",
+            "BV1A:p3",  # oldest attempt first
+            "BV1A:p2",
+        ]
+        # A part upstream reported as gone is not work: the enumeration is
+        # bounded to what can still yield a caption.
+        assert "BV1GONE:p0" not in work_ids
+        assert repository.count_pending_subtitle_parts() == len(work_ids) == 5
+
+        # The bound takes the head of the locked order.
+        assert [
+            row["work_id"] for row in repository.list_pending_subtitle_parts(limit=1)
+        ] == ["BV0Z:p0"]
+        assert [
+            row["work_id"] for row in repository.list_pending_subtitle_parts(limit=2)
+        ] == ["BV0Z:p0", "BV1A:p0"]
+        assert [
+            row["work_id"] for row in repository.list_pending_subtitle_parts(limit=5)
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
