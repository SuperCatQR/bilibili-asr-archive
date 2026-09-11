# Task 1 Diff — 20260911-transcript-storage

Base: `6ee7c6a`
Head: `d4cae24`

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
index ea7c770..9382ce8 100644
--- a/bilibili-asr-archive/src/bili_asr/storage/__init__.py
+++ b/bilibili-asr-archive/src/bili_asr/storage/__init__.py
@@ -7,16 +7,26 @@ models, and the bootstrap helpers are all re-exported here.
 from .database import (
     DatabaseConnection,
     MetadataRepository,
+    SchemaContractError,
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
     ALLOWED_CURSOR_STATES,
     ALLOWED_PAGE_OUTCOMES,
     ALLOWED_PROCESSING_STATUS,
     ALLOWED_RUN_OUTCOMES,
+    ALLOWED_SOURCE_KINDS,
+    AcquisitionKind,
+    AcquisitionOutcome,
+    AcquisitionRunRecord,
+    AttemptOutcome,
     CursorRecord,
     CursorState,
     DiscoveryRecord,
@@ -25,6 +35,9 @@ from .models import (
     PageOutcome,
     ProcessingStatus,
     RunOutcome,
+    SourceKind,
+    TranscriptSegmentRecord,
+    TranscriptWriteResult,
     UserRecord,
     VideoPartRecord,
     VideoRecord,
@@ -32,10 +45,18 @@ from .models import (
 )
 
 __all__ = [
+    "ALLOWED_ACQUISITION_KINDS",
+    "ALLOWED_ACQUISITION_OUTCOMES",
+    "ALLOWED_ATTEMPT_OUTCOMES",
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
@@ -46,6 +67,10 @@ __all__ = [
     "PageOutcome",
     "ProcessingStatus",
     "RunOutcome",
+    "SchemaContractError",
+    "SourceKind",
+    "TranscriptSegmentRecord",
+    "TranscriptWriteResult",
     "UserRecord",
     "VideoPartRecord",
     "VideoRecord",
@@ -53,5 +78,6 @@ __all__ = [
     "initialize_schema",
     "normalize_page_index",
     "open_database",
+    "require_subtitle_schema",
     "validate_error_code",
 ]
diff --git a/bilibili-asr-archive/src/bili_asr/storage/database.py b/bilibili-asr-archive/src/bili_asr/storage/database.py
index 2cd1bf0..e8b3873 100644
--- a/bilibili-asr-archive/src/bili_asr/storage/database.py
+++ b/bilibili-asr-archive/src/bili_asr/storage/database.py
@@ -27,6 +27,25 @@ _ARCHIVE_DATABASE_NAME = "archive.db"
 _DATABASE_SUFFIXES = frozenset({".db", ".sqlite", ".sqlite3"})
 _TERMINAL_RUN_OUTCOMES = ALLOWED_RUN_OUTCOMES - frozenset({"running"})
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
@@ -72,19 +91,79 @@ def _resolve_database_path(path: str | os.PathLike[str]) -> str | os.PathLike[st
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
 
@@ -575,8 +654,10 @@ class MetadataRepository:
 __all__ = [
     "DatabaseConnection",
     "MetadataRepository",
+    "SchemaContractError",
     "duration_to_ms",
     "initialize_schema",
     "normalize_page_index",
     "open_database",
+    "require_subtitle_schema",
 ]
diff --git a/bilibili-asr-archive/src/bili_asr/storage/models.py b/bilibili-asr-archive/src/bili_asr/storage/models.py
index 780b42a..c82cbe4 100644
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
@@ -23,7 +27,16 @@ _ALLOWED_RUN_OUTCOMES = frozenset(
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
 _ERROR_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]+$")
+_SHA256_HEX_PATTERN = re.compile(r"^[0-9a-f]{64}$")
 
 
 def _integer(value: object, field: str, *, minimum: int | None = None) -> int:
@@ -62,6 +75,33 @@ def _choice(value: object, field: str, allowed: frozenset[str]) -> str:
     return value
 
 
+def _boolean(value: object, field: str) -> bool:
+    if not isinstance(value, bool):
+        raise TypeError(f"{field} must be a boolean")
+    return value
+
+
+def _caption_text(value: object, field: str = "text") -> str:
+    """Validate verbatim caption text: a string non-empty after stripping.
+
+    Unlike :func:`_text`, control characters are kept: a caption row is stored
+    as upstream returned it.
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
@@ -238,7 +278,101 @@ class DiscoveryRecord:
         _integer(self.discovered_at, "discovered_at", minimum=0)
 
 
+@dataclass(frozen=True, slots=True)
+class TranscriptSegmentRecord:
+    """One caption row of one transcript, on the millisecond timeline.
+
+    The invariant mirrors the gateway's ``SubtitleSegment`` so the service
+    maps one DTO onto the other field for field: ``end_ms > start_ms >= 0``
+    and ``text`` non-empty after stripping.  ``ordinal`` is positional and is
+    assigned by the repository, never carried here.
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
@@ -246,6 +380,9 @@ __all__ = [
     "PageOutcome",
     "ProcessingStatus",
     "RunOutcome",
+    "SourceKind",
+    "TranscriptSegmentRecord",
+    "TranscriptWriteResult",
     "UserRecord",
     "VideoPartRecord",
     "VideoRecord",
@@ -260,11 +397,19 @@ ALLOWED_PAGE_OUTCOMES = _ALLOWED_PAGE_OUTCOMES
 ALLOWED_RUN_OUTCOMES = _ALLOWED_RUN_OUTCOMES
 ALLOWED_CURSOR_STATES = _ALLOWED_CURSOR_STATES
 ALLOWED_PROCESSING_STATUS = _ALLOWED_PROCESSING_STATUS
+ALLOWED_ACQUISITION_KINDS = _ALLOWED_ACQUISITION_KINDS
+ALLOWED_ACQUISITION_OUTCOMES = _ALLOWED_ACQUISITION_OUTCOMES
+ALLOWED_ATTEMPT_OUTCOMES = _ALLOWED_ATTEMPT_OUTCOMES
+ALLOWED_SOURCE_KINDS = _ALLOWED_SOURCE_KINDS
 
 __all__ += [
+    "ALLOWED_ACQUISITION_KINDS",
+    "ALLOWED_ACQUISITION_OUTCOMES",
+    "ALLOWED_ATTEMPT_OUTCOMES",
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
index 7ab7e24..2d3743c 100644
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
@@ -169,15 +247,115 @@ EXPECTED_CHECK_ENUMERATIONS = {
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
@@ -186,14 +364,23 @@ def test_schema_sql_is_declared_and_read_as_package_resource():
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
@@ -225,6 +412,151 @@ def _insert_user_video_part(connection: sqlite3.Connection) -> int:
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
@@ -274,12 +606,7 @@ def test_schema_check_enumerations_match_model_validation_sets():
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
@@ -444,6 +771,30 @@ def test_schema_constraints_cover_status_and_non_negative_values(tmp_root):
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
@@ -535,6 +886,31 @@ def test_schema_inspection_matches_the_declared_contract(tmp_root):
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
@@ -550,8 +926,13 @@ def test_schema_inspection_matches_the_declared_contract(tmp_root):
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
 
@@ -632,3 +1013,508 @@ def test_views_compute_derived_values_across_users_videos_and_runs(tmp_root):
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
```
