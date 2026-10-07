-- Fixed input and derived content. Execution ownership remains workflow_attempts.
CREATE TABLE IF NOT EXISTS editorial_inputs (
    input_id TEXT PRIMARY KEY,
    video_part_id INTEGER NOT NULL REFERENCES video_parts(video_part_id),
    base_transcript_id INTEGER NOT NULL REFERENCES transcripts(transcript_id),
    reference_transcript_id INTEGER REFERENCES transcripts(transcript_id),
    prepared_json TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS editorial_job_inputs (
    job_id TEXT PRIMARY KEY REFERENCES workflow_jobs(job_id),
    input_id TEXT NOT NULL REFERENCES editorial_inputs(input_id)
);

CREATE TABLE IF NOT EXISTS editorial_model_calls (
    call_id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL REFERENCES workflow_attempts(attempt_id),
    input_id TEXT NOT NULL REFERENCES editorial_inputs(input_id),
    chunk_id TEXT NOT NULL,
    request_json TEXT NOT NULL,
    response_json TEXT,
    error_code TEXT,
    started_at INTEGER NOT NULL,
    finished_at INTEGER,
    CHECK (response_json IS NULL OR finished_at IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS editorial_chunk_results (
    input_id TEXT NOT NULL REFERENCES editorial_inputs(input_id),
    chunk_id TEXT NOT NULL,
    call_id TEXT NOT NULL REFERENCES editorial_model_calls(call_id),
    blocks_json TEXT NOT NULL,
    PRIMARY KEY (input_id, chunk_id)
);

CREATE TABLE IF NOT EXISTS editorial_revisions (
    revision_id TEXT PRIMARY KEY,
    input_id TEXT NOT NULL UNIQUE REFERENCES editorial_inputs(input_id),
    job_id TEXT NOT NULL REFERENCES workflow_jobs(job_id),
    blocks_json TEXT NOT NULL,
    quality_status TEXT NOT NULL CHECK (quality_status IN ('ai-unreviewed', 'needs-review')),
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS document_artifacts (
    revision_id TEXT NOT NULL REFERENCES editorial_revisions(revision_id),
    template_version TEXT NOT NULL,
    artifact_name TEXT NOT NULL CHECK (artifact_name IN ('reading.md', 'review.md')),
    relative_path TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    PRIMARY KEY (revision_id, template_version, artifact_name)
);

CREATE TABLE IF NOT EXISTS reading_document_editions (
    edition_id TEXT PRIMARY KEY,
    revision_id TEXT NOT NULL REFERENCES editorial_revisions(revision_id),
    parent_edition_id TEXT REFERENCES reading_document_editions(edition_id),
    markdown_text TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS reading_publications (
    revision_id TEXT PRIMARY KEY REFERENCES editorial_revisions(revision_id),
    current_edition_id TEXT REFERENCES reading_document_editions(edition_id),
    status TEXT NOT NULL CHECK (status IN (
        'pending-review', 'in-review', 'changes-requested',
        'approved', 'published', 'rejected', 'withdrawn'
    )),
    issue_url TEXT,
    updated_at INTEGER NOT NULL,
    published_at INTEGER
);

CREATE TABLE IF NOT EXISTS reading_publication_events (
    event_id INTEGER PRIMARY KEY,
    revision_id TEXT NOT NULL REFERENCES editorial_revisions(revision_id),
    edition_id TEXT REFERENCES reading_document_editions(edition_id),
    from_status TEXT,
    to_status TEXT NOT NULL CHECK (to_status IN (
        'pending-review', 'in-review', 'changes-requested',
        'approved', 'published', 'rejected', 'withdrawn'
    )),
    issue_url TEXT,
    note TEXT NOT NULL DEFAULT '',
    changed_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reading_publication_events_revision
    ON reading_publication_events(revision_id, event_id);
