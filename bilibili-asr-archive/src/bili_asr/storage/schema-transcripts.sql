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

-- Queue views for the archive work queue: the three gaps and the converged
-- per-part pipeline state.  Each gap view exposes the same nine columns
-- (``video_part_id, work_id, bvid, page_index, cid, part_title, duration_ms,
-- video_title, pubdate``) so the repository can read any of them by name;
-- ``v_missing_audio`` adds its newest-attempt evidence, and ``v_part_pipeline``
-- carries the part's status and computed state instead of the projection.
-- ``cid`` rides the three gap views because the audio route needs it and a
-- frozen view can never be widened afterwards.  Ordering is a repository
-- concern (``pubdate DESC, bvid ASC, page_index ASC``), so none of these views
-- carries an ORDER BY.

-- 1) missing_subtitle: not gone, no stored transcript.  Same predicate as
-- ``v_pending_subtitles``; that view carries extra attempt columns the queue
-- does not need, but this one must be independently queryable.
CREATE VIEW IF NOT EXISTS v_missing_subtitle AS
SELECT
    vp.video_part_id,
    vp.bvid || ':p' || vp.page_index AS work_id,
    vp.bvid,
    vp.page_index,
    vp.cid,
    vp.title AS part_title,
    vp.duration_ms,
    v.title AS video_title,
    v.pubdate
FROM video_parts AS vp
JOIN videos AS v ON vp.bvid = v.bvid
WHERE vp.processing_status <> 'gone'
  AND NOT EXISTS (
      SELECT 1 FROM transcripts AS t WHERE t.video_part_id = vp.video_part_id
  );

-- 2) missing_audio: in the subtitle gap and the caption route is exhausted with
-- no audio evidence yet.  Exhaustion is attested, not inferred from one look.
-- The newest subtitle attempt admits the part when it is a ``'failed'`` outcome,
-- or when it is ``'no-subtitle'`` with a *definite* ``'not_found'`` error code.
-- An *indefinite* ``'no-subtitle'`` — ``error_code IS NULL``, i.e. the
-- inventory was empty but this credential may simply not have seen it — admits
-- only once two **independent** observations exist, where independent means a
-- distinct credentialed ``run_id``. Anonymous observations cannot establish
-- exhaustion: those parts stay off the paid branch until authenticated harvests
-- have actually seen the empty inventory. ``COUNT(DISTINCT run_id)`` is load-bearing: two probes
-- inside one run are ONE observation, so a retry loop cannot inflate the count.
-- (The table's PRIMARY KEY is ``(run_id, video_part_id)``, which makes a second
-- row for one part in one run unwritable in the first place; changing that key
-- would weaken this, so treat it as a review trigger.)
-- Measured 2026-10-03: a single empty inventory became a durable verdict and put
-- a part that did have subtitles into the paid branch; a genuinely caption-less
-- control part reports empty on every run, so it still reaches this queue — one
-- observation later than under the one-look predicate.
-- Audio evidence is a ``part_audio_objects`` row and nothing
-- else: an ``acquisition_attempts`` row under a ``kind = 'audio'`` run can only
-- ever record a *failed* download, since the attempt contract admits
-- ``stored`` / ``unchanged`` only with a ``transcript_id`` an audio acquisition
-- never produces.  Probing attempts here would invert the signal — a part with
-- audio on disk would be excluded while a part that failed to download would
-- enter the transcription queue — so this view does not.  Newest-attempt idiom
-- copied from ``v_pending_subtitles``.
CREATE VIEW IF NOT EXISTS v_missing_audio AS
WITH subtitle_attempts AS (
    SELECT
        aa.video_part_id,
        aa.outcome,
        aa.error_code,
        aa.run_id,
        ar.credential_present,
        ROW_NUMBER() OVER (
            PARTITION BY aa.video_part_id
            ORDER BY aa.finished_at DESC, aa.run_id DESC
        ) AS recency
    FROM acquisition_attempts AS aa
    JOIN acquisition_runs AS ar ON ar.run_id = aa.run_id
    WHERE ar.kind = 'subtitle'
)
, empty_inventory_confirmations AS (
    SELECT video_part_id, COUNT(DISTINCT run_id) AS confirmations
    FROM subtitle_attempts
    WHERE outcome = 'no-subtitle' AND error_code IS NULL AND credential_present = 1
    GROUP BY video_part_id
)
SELECT
    vp.video_part_id,
    vp.bvid || ':p' || vp.page_index AS work_id,
    vp.bvid,
    vp.page_index,
    vp.cid,
    vp.title AS part_title,
    vp.duration_ms,
    v.title AS video_title,
    v.pubdate,
    latest.outcome AS newest_outcome,
    latest.error_code AS newest_error_code
FROM video_parts AS vp
JOIN videos AS v ON vp.bvid = v.bvid
JOIN subtitle_attempts AS latest
    ON latest.video_part_id = vp.video_part_id AND latest.recency = 1
LEFT JOIN empty_inventory_confirmations AS eic
    ON eic.video_part_id = vp.video_part_id
WHERE vp.processing_status <> 'gone'
  AND NOT EXISTS (
      SELECT 1 FROM transcripts AS t WHERE t.video_part_id = vp.video_part_id
  )
  AND (
        latest.outcome = 'failed'
     OR (latest.outcome = 'no-subtitle'
         AND (  latest.error_code = 'not_found'
             OR COALESCE(eic.confirmations, 0) >= 2))
      )
  AND NOT EXISTS (
      SELECT 1 FROM part_audio_objects AS pao WHERE pao.video_part_id = vp.video_part_id
  );

-- 3) missing_transcript: has audio evidence and no stored transcript.  It
-- deliberately does not filter ``processing_status``: a 'gone' part with audio
-- and no transcript is still a transcribable gap.  Audio evidence is the same
-- single probe as ``v_missing_audio``'s.
CREATE VIEW IF NOT EXISTS v_missing_transcript AS
SELECT
    vp.video_part_id,
    vp.bvid || ':p' || vp.page_index AS work_id,
    vp.bvid,
    vp.page_index,
    vp.cid,
    vp.title AS part_title,
    vp.duration_ms,
    v.title AS video_title,
    v.pubdate
FROM video_parts AS vp
JOIN videos AS v ON vp.bvid = v.bvid
WHERE NOT EXISTS (
      SELECT 1 FROM transcripts AS t WHERE t.video_part_id = vp.video_part_id
  )
  AND EXISTS (
      SELECT 1 FROM part_audio_objects AS pao WHERE pao.video_part_id = vp.video_part_id
  );

-- 4) v_part_pipeline: the converged reachable pipeline state, one row per
-- part: 'transcribed' (a transcript exists), 'audio_ok' (audio evidence and no
-- transcript), 'audio_pending' (in ``v_missing_audio``), 'no_subtitle' (newest
-- subtitle attempt outcome is 'no-subtitle' with no audio evidence),
-- 'discovered' (otherwise).  'metadata_collected' is unreachable and is never
-- emitted.  The branches exclude in order, so ``audio_pending`` states its
-- residual predicate -- by the time it is reached the transcript and audio
-- evidence probes of ``v_missing_audio`` are already known absent.  ``audio_ok``
-- keys on the same single ``part_audio_objects`` probe: a failed audio attempt
-- is attempt history, not acquired bytes, so it renders ``audio_pending``.
CREATE VIEW IF NOT EXISTS v_part_pipeline AS
WITH subtitle_attempts AS (
    SELECT
        aa.video_part_id,
        aa.outcome,
        aa.error_code,
        aa.run_id,
        ar.credential_present,
        ROW_NUMBER() OVER (
            PARTITION BY aa.video_part_id
            ORDER BY aa.finished_at DESC, aa.run_id DESC
        ) AS recency
    FROM acquisition_attempts AS aa
    JOIN acquisition_runs AS ar ON ar.run_id = aa.run_id
    WHERE ar.kind = 'subtitle'
)
-- The same corroboration rule ``v_missing_audio`` applies, so the two views
-- never disagree about one row: an empty inventory with no error code is an
-- indefinite negative and needs two independent observations (distinct runs).
, empty_inventory_confirmations AS (
    SELECT video_part_id, COUNT(DISTINCT run_id) AS confirmations
    FROM subtitle_attempts
    WHERE outcome = 'no-subtitle' AND error_code IS NULL AND credential_present = 1
    GROUP BY video_part_id
)
SELECT
    vp.video_part_id,
    vp.bvid || ':p' || vp.page_index AS work_id,
    vp.bvid,
    vp.page_index,
    vp.processing_status,
    CASE
        WHEN EXISTS (
            SELECT 1 FROM transcripts AS t WHERE t.video_part_id = vp.video_part_id
        ) THEN 'transcribed'
        WHEN EXISTS (
            SELECT 1 FROM part_audio_objects AS pao WHERE pao.video_part_id = vp.video_part_id
        ) THEN 'audio_ok'
        WHEN vp.processing_status <> 'gone'
             AND (
                   latest.outcome = 'failed'
                OR (latest.outcome = 'no-subtitle'
                    AND (  latest.error_code = 'not_found'
                        OR COALESCE(eic.confirmations, 0) >= 2))
             ) THEN 'audio_pending'
        WHEN latest.outcome = 'no-subtitle' THEN 'no_subtitle'
        ELSE 'discovered'
    END AS pipeline_state
FROM video_parts AS vp
LEFT JOIN subtitle_attempts AS latest
    ON latest.video_part_id = vp.video_part_id AND latest.recency = 1
LEFT JOIN empty_inventory_confirmations AS eic
    ON eic.video_part_id = vp.video_part_id;
