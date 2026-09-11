-- Transcript and acquisition process-record contract.
--
-- Applied by ``initialize_schema`` only to a database that is fresh
-- (``transcripts`` absent) or already carries this contract; a database
-- created before it keeps the shape it has, because ``CREATE TABLE IF NOT
-- EXISTS`` cannot widen an existing unique constraint.  The archive database
-- is rebuildable by policy: there is no migration, no backfill, and no
-- compatibility reader.  Foreign-key enforcement is a connection property
-- owned by ``initialize_schema`` (``PRAGMA foreign_keys = ON``, verified),
-- so this script declares no pragma of its own.

CREATE TABLE IF NOT EXISTS transcripts (
    transcript_id INTEGER PRIMARY KEY,
    video_part_id INTEGER NOT NULL,
    source_kind TEXT NOT NULL CHECK (
        source_kind IN ('subtitle-ai', 'subtitle-cc', 'asr-local')
    ),
    language TEXT NOT NULL CHECK (length(trim(language)) > 0),
    model_id INTEGER,
    version INTEGER NOT NULL CHECK (version > 0),
    content_sha256 TEXT NOT NULL CHECK (
        length(content_sha256) = 64 AND content_sha256 = lower(content_sha256)
    ),
    created_at INTEGER NOT NULL,
    UNIQUE (video_part_id, source_kind, language, version),
    FOREIGN KEY (video_part_id) REFERENCES video_parts(video_part_id) ON DELETE RESTRICT,
    FOREIGN KEY (model_id) REFERENCES asr_models(model_id) ON DELETE RESTRICT
);

-- Content identity for the caption kinds only.  ``asr-local`` keeps its own
-- (per model/run) identity rule; that decision belongs to the audio/ASR
-- iteration, so this index does not pre-empt it.
CREATE UNIQUE INDEX IF NOT EXISTS ux_transcripts_subtitle_content
    ON transcripts(video_part_id, source_kind, language, content_sha256)
    WHERE source_kind IN ('subtitle-ai', 'subtitle-cc');

CREATE TABLE IF NOT EXISTS transcript_segments (
    transcript_id INTEGER NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    start_ms INTEGER NOT NULL CHECK (start_ms >= 0),
    end_ms INTEGER NOT NULL CHECK (end_ms > start_ms),
    text TEXT NOT NULL,
    PRIMARY KEY (transcript_id, ordinal),
    FOREIGN KEY (transcript_id) REFERENCES transcripts(transcript_id) ON DELETE RESTRICT
);

-- One row per acquisition run of one kind.  Subtitle/transcript process
-- records live here rather than in the metadata-scoped ``ingestion_runs``,
-- whose cursor semantics say nothing true about a per-part caption probe.
CREATE TABLE IF NOT EXISTS acquisition_runs (
    run_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('subtitle', 'audio', 'asr')),
    selector_kind TEXT NOT NULL CHECK (selector_kind IN ('pending', 'bvid')),
    selector_target TEXT,
    requested_limit INTEGER CHECK (requested_limit IS NULL OR requested_limit > 0),
    credential_present INTEGER NOT NULL CHECK (credential_present IN (0, 1)),
    started_at INTEGER NOT NULL,
    finished_at INTEGER,
    outcome TEXT NOT NULL CHECK (
        outcome IN ('running', 'complete', 'partial', 'failed')
    ),
    CHECK (
        (selector_kind = 'pending' AND selector_target IS NULL)
        OR (selector_kind = 'bvid' AND selector_target IS NOT NULL)
    ),
    CHECK (finished_at IS NULL OR finished_at >= started_at)
);

-- One evidence row per attempted part, scoped to its run: append-only, and
-- never a terminal per-part state, so a part recorded without a caption stays
-- re-attemptable.
CREATE TABLE IF NOT EXISTS acquisition_attempts (
    run_id TEXT NOT NULL,
    video_part_id INTEGER NOT NULL,
    outcome TEXT NOT NULL CHECK (
        outcome IN ('stored', 'unchanged', 'no-subtitle', 'failed')
    ),
    error_code TEXT CHECK (error_code IS NULL OR length(error_code) <= 64),
    transcript_id INTEGER,
    started_at INTEGER NOT NULL,
    finished_at INTEGER NOT NULL,
    PRIMARY KEY (run_id, video_part_id),
    FOREIGN KEY (run_id) REFERENCES acquisition_runs(run_id) ON DELETE RESTRICT,
    FOREIGN KEY (video_part_id) REFERENCES video_parts(video_part_id) ON DELETE RESTRICT,
    FOREIGN KEY (transcript_id) REFERENCES transcripts(transcript_id) ON DELETE RESTRICT,
    CHECK (
        (outcome = 'failed'
            AND error_code IS NOT NULL AND transcript_id IS NULL)
        OR (outcome = 'no-subtitle'
            AND (error_code IS NULL OR error_code = 'not_found')
            AND transcript_id IS NULL)
        OR (outcome IN ('stored', 'unchanged')
            AND error_code IS NULL AND transcript_id IS NOT NULL)
    ),
    CHECK (finished_at >= started_at)
);

CREATE INDEX IF NOT EXISTS ix_acquisition_attempts_part_time
    ON acquisition_attempts(video_part_id, finished_at);

-- The pending-work relation: one query, no per-part N+1.  Parts that hold a
-- transcript, and parts upstream reported as gone, are not pending.  A part
-- attempted without a caption stays pending and brings its newest attempt's
-- evidence with it, so "never attempted" (attempted = 0) is distinguishable
-- from "attempted and still captionless" (attempted = 1).
CREATE VIEW IF NOT EXISTS v_pending_subtitles AS
WITH subtitle_attempts AS (
    SELECT
        aa.video_part_id,
        aa.finished_at,
        aa.outcome,
        aa.error_code,
        ar.credential_present,
        ROW_NUMBER() OVER (
            PARTITION BY aa.video_part_id
            ORDER BY aa.finished_at DESC, aa.run_id DESC
        ) AS recency
    FROM acquisition_attempts AS aa
    JOIN acquisition_runs AS ar ON ar.run_id = aa.run_id
    WHERE ar.kind = 'subtitle'
)
SELECT
    vp.video_part_id,
    vp.bvid || ':p' || vp.page_index AS work_id,
    vp.bvid,
    vp.page_index,
    vp.cid,
    vp.title AS part_title,
    vp.duration_ms,
    CASE WHEN latest.video_part_id IS NULL THEN 0 ELSE 1 END AS attempted,
    latest.finished_at AS last_attempt_at,
    latest.outcome AS last_attempt_outcome,
    latest.error_code AS last_attempt_error_code,
    latest.credential_present AS last_attempt_credential_present
FROM video_parts AS vp
LEFT JOIN subtitle_attempts AS latest
    ON latest.video_part_id = vp.video_part_id AND latest.recency = 1
WHERE vp.processing_status <> 'gone'
  AND NOT EXISTS (
      SELECT 1 FROM transcripts AS t WHERE t.video_part_id = vp.video_part_id
  );
