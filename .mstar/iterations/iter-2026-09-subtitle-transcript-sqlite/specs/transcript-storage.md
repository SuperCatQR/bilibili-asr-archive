# Normalized Transcript Storage (iteration spec)

> Promoted to: `.mstar/knowledge/architecture-patterns/normalized-transcript-storage.md` (2026-09-11)
> Iteration `iter-2026-09-subtitle-transcript-sqlite`, spec point 2.
> Status: architecture locked (2026-09-11); product intent reviewed (product-manager,
> 2026-09-11); writing/corpus hygiene reviewed (writing-specialist, 2026-09-11);
> PM lock: locked (project-manager, 2026-09-11).
> Every shipped shape below was read out of `src/bili_asr/storage/schema.sql` as delivered by
> `20260909-structured-metadata-schema`; the deltas are stated as exact DDL.

## Goal

Persist acquired subtitles as **normalized transcript rows** in `{archive_root}/archive.db`,
using the FK boundaries reserved by `20260909-structured-metadata-schema`, with explicit
versioning and provenance — and decide, explicitly, where subtitle/transcript **process
records** live (carry F-010: `ingestion_runs` is metadata-scoped).

Product framing — what the operator can do with the stored state once this exists:

- Ask, per part, what captions the archive holds: source kind (AI or CC), language, version,
  creation time, and the millisecond timeline with its verbatim text.
- Re-run acquisition without fear: identical content writes nothing, a changed caption
  appends a version, and no earlier version is ever rewritten or deleted.
- See "no caption was visible" as a recorded, timestamped per-part fact instead of an
  absence, so a part is never silently skipped and never silently assumed captionless.
- Hand the next iteration (audio/ASR) a work queue it can trust: parts with no transcript,
  separated into never-attempted and already-attempted-without-caption.

Nothing here claims caption quality or corpus coverage: the store keeps what upstream
returned, verbatim, for a given source at a given time.

## 1. Reserved tables as shipped (baseline)

Section 2 records the deltas to `transcripts`; every other shipped shape below stays as it is.

`transcripts(transcript_id, video_part_id, source_kind ∈ {subtitle-ai, subtitle-cc,
asr-local}, model_id NULL, version > 0, created_at, UNIQUE(video_part_id, source_kind,
version))`; `transcript_segments(transcript_id, ordinal, start_ms, end_ms > start_ms, text,
PK(transcript_id, ordinal))`. Both carry `ON DELETE RESTRICT` FKs to `video_parts` /
`transcripts`. `audio_objects`, `part_audio_objects`, `asr_models` stay empty reservations.

## 2. Locked decisions

### 2.1 Language storage — confirmed, with the uniqueness widened

`transcripts` gains `language TEXT NOT NULL` (the upstream `lan` exactly as the gateway
normalized it, trimmed and non-empty) and the version key is widened to
`(video_part_id, source_kind, language, version)`. Language is an attribute of the transcript
and is not derivable from the part: one part can carry `zh-CN`, `ai-zh`, and any further
language the uploader provides, each with its own version history. Keeping it in the row keeps
the table in 3NF and makes "the archive holds version 2 of the Chinese CC caption for this
part" a single-row fact.

### 2.2 Content identity and idempotency — confirmed, with the hash defined and pinned

`transcripts` gains `content_sha256 TEXT NOT NULL`, computed over the normalized segment
sequence only:

```python
canonical = json.dumps(
    [[segment.start_ms, segment.end_ms, segment.text] for segment in segments],
    ensure_ascii=False,
    separators=(",", ":"),
)
content_sha256 = hashlib.sha256(canonical.encode("utf-8")).hexdigest()  # 64 lowercase hex
```

The part id, source kind, and language are **not** hashed: they are the identity key, not the
content. Consequences, all testable:

- `record_acquired_transcript` writes nothing when any version of
  `(video_part_id, source_kind, language)` already carries that hash — the attempt is recorded
  as `unchanged` and references that existing version, the one the operator already holds;
- otherwise it appends `version = COALESCE(MAX(version), 0) + 1` for that same key, with the
  segments, and the attempt is recorded as `stored`;
- idempotency is therefore checkable without comparing segment rows, and content that reverts
  to an earlier version is *not* stored twice (the archive already holds it) — the attempt row
  still records that the acquisition happened and when, and the run it belongs to records
  whether a credential was in effect.

### 2.3 Process records — a generic `kind`-keyed pair, not `ingestion_runs`

Subtitle/transcript acquisition gets its own run/attempt pair
(`acquisition_runs` + `acquisition_attempts`), keyed by `kind ∈ {subtitle, audio, asr}`.
Rationale: the metadata-scoped `ingestion_runs` is keyed by `mid` and carries cursor
semantics (`requested_start_page`, `source_package`, `observed_total`) that say nothing true
about a per-part caption probe; overloading it would either force a nullable metadata target
or a second meaning for `outcome`. The unit of evidence is also different — a metadata page
versus one part — so the child table is named for its unit (`acquisition_attempts`) instead of
copying the `*_pages` metaphor.

The shape satisfies every product constraint carried by F-010:

| Product constraint | How the shape satisfies it |
|---|---|
| per-part probed / when / outcome / code evidence | one `acquisition_attempts` row per attempted part, with `outcome`, optional bounded `error_code`, `started_at`, `finished_at`, and the transcript version it produced (`transcript_id`) |
| no terminal "unavailable" state | attempts are append-only evidence scoped to a run; there is no part-level status column and no upsert across runs, so a part recorded `no-subtitle` is simply re-attempted in a later run |
| must not overload metadata-scoped `ingestion_runs` | separate tables, separate vocabulary; `ingestion_runs` and its views are untouched |
| reusable by the next (audio/ASR) iteration | `kind='audio'` / `kind='asr'` reuse the identical pair and the identical outcome vocabulary; nothing structural has to be added later |
| "never-probed parts before previously probed ones" | the latest attempt per part is derivable (index `ix_acquisition_attempts_part_time`), so section 2.4's view can rank never-attempted parts first |

Credential presence is recorded once per **run** (`credential_present`), not per attempt: the
attempt belongs to the run, so repeating the run's credential flag on every attempt row would
duplicate a run-scoped fact. A `no-subtitle` attempt stays interpretable after the fact
because its run says whether a credential was in effect.

### 2.4 Exact DDL deltas

All statements below are the new/changed content of the transcript schema script (section 3).
Every other statement keeps the DDL shipped before this iteration unchanged; the
`transcript_segments` block moves between the two scripts, but not a character of its DDL
changes (section 3).

```sql
-- CHANGED: transcripts gains language + content_sha256, and the version key widens.
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

-- NEW: content identity for the caption kinds only; asr-local keeps its identity rule
-- (per model/run) to the audio/ASR iteration.
CREATE UNIQUE INDEX IF NOT EXISTS ux_transcripts_subtitle_content
    ON transcripts(video_part_id, source_kind, language, content_sha256)
    WHERE source_kind IN ('subtitle-ai', 'subtitle-cc');

-- UNCHANGED: transcript_segments moves to the transcript script verbatim.

-- NEW: one row per acquisition run of one kind.
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

-- NEW: one evidence row per attempted part, scoped to its run.
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

-- NEW: the pending-work view, v_pending_subtitles (full DDL in section 2.5).
```

Vocabulary (added to `storage/models.py` as frozensets plus `Literal` aliases, mirroring the
shipped `_ALLOWED_*` style):

| Name | Values |
|---|---|
| `AcquisitionKind` | `subtitle`, `audio`, `asr` |
| `AcquisitionOutcome` | `running`, `complete`, `partial`, `failed` |
| `AttemptOutcome` | `stored`, `unchanged`, `no-subtitle`, `failed` |
| `SourceKind` | `subtitle-ai`, `subtitle-cc`, `asr-local` |

Attempt semantics, pinned by the CHECK above and by the repository:

- `PRIMARY KEY (run_id, video_part_id)` is the product rule "exactly one outcome per attempted
  part per run", enforced by the database rather than by convention.
- `stored` / `unchanged` require `transcript_id`, require `error_code IS NULL`, and are the
  only outcomes that may reference a transcript.
- `failed` requires a bounded `error_code`.
- `no-subtitle` carries `error_code IS NULL` when the listing was simply empty, and
  `error_code = 'not_found'` when upstream signalled "not visible" (`not_found`, `-101`,
  `-404`, `-62002`); nothing else is accepted.
- Run outcome is a function of its attempts, computed by the repository on
  `finish_acquisition_run`: `failed` when every attempt failed (or when the service aborts
  abnormally), `partial` when failed and non-failed attempts coexist, `complete` otherwise —
  including a run with zero attempts, which means the bounded work set was empty and nothing
  failed.

### 2.5 Pending-work view (locked name, columns, and source of last-attempt data)

The last-attempt facts come **from the view**, not from a companion query: one relation, one
query, no per-part N+1. The view is:

```sql
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
```

| Column | Meaning |
|---|---|
| `video_part_id`, `work_id`, `bvid`, `page_index`, `cid`, `part_title`, `duration_ms` | the work item, including the `cid` the gateway call needs (the subtitle path never re-fetches a pagelist) |
| `attempted` | `0` = no subtitle acquisition attempt recorded, `1` = previously attempted |
| `last_attempt_at`, `last_attempt_outcome`, `last_attempt_error_code`, `last_attempt_credential_present` | the newest attempt's evidence, `NULL` when `attempted = 0` |

Rules the view and its consumers pin:

- a part with any `transcripts` row does not appear (it has a caption);
- a part recorded `no-subtitle` **does** appear, is still "without a transcript", and brings
  its last outcome, code, timestamp, and credential presence with it;
- a part never attempted has `attempted = 0` and no last-attempt columns, so it is
  distinguishable from — and enumerated before — a previously attempted part;
- parts with `processing_status = 'gone'` do not appear in the pending enumeration; an
  explicit `--bvid`/`bvid:pN` selection is not filtered by status (explicit means explicit,
  and the resulting evidence records the truth);
- the repository — not the view — imposes order:
  `ORDER BY attempted ASC, last_attempt_at ASC, bvid ASC, page_index ASC`. Never-attempted
  parts come first, then the oldest-attempted parts, so successive bounded runs rotate through
  the captionless backlog instead of re-attempting the same head forever.
- `probe-subs` records nothing (it is read-only), so "previously attempted" always means
  "previously attempted by `harvest-subs`"; the CLI docs say so in those words.

### 2.6 Version semantics and immutability — confirmed

Versions are immutable: a new version inserts a new `transcripts` row plus its segments;
existing rows are never rewritten or deleted. Enforced by three independent mechanisms, none
of which is a trigger:

1. no code path issues `UPDATE` or `DELETE` against `transcripts` / `transcript_segments`;
2. `ON DELETE RESTRICT` from `transcript_segments` to `transcripts` makes deleting a transcript
   that has segments impossible, and a version without segments cannot be written (a
   transcript is only ever written with a non-empty segment tuple);
3. tests assert that a re-acquisition with changed content leaves version 1's row and segments
   byte-identical, and that deleting a stored transcript is rejected.

### 2.7 Out-of-scope source kinds — confirmed

`source_kind = 'asr-local'` and its `asr_models` FK stay unused in this iteration; no audio or
ASR row is written, and no view pretends otherwise. One handoff is recorded explicitly so the
next iteration does not inherit a trap: the version key
`(video_part_id, source_kind, language, version)` is model-agnostic (it was model-agnostic as
shipped, and `model_id` is `NULL` for caption rows). Activating `asr-local` with more than one
model requires widening that key to include the model identity; that decision and its DDL are
owned by the audio/ASR iteration, and the content-identity index is deliberately scoped to the
caption kinds so it does not pre-empt it.

## 3. Rebuild stance and the schema bootstrap (locked)

The archive database is rebuildable by policy: **no migration, no `ALTER TABLE`, no backfill,
no compatibility reader** exists or is planned. A database created by the previous iteration
has the old `transcripts` shape, and `CREATE TABLE IF NOT EXISTS` cannot change it — so the
bootstrap and the guards are explicit instead of accidental:

1. The schema is split into two checked-in resources:
   - `src/bili_asr/storage/schema.sql` — everything shipped before this iteration (entity
     tables, ingestion tables, the reserved media boundary, the existing views) **minus** the
     `transcripts` / `transcript_segments` block;
   - `src/bili_asr/storage/schema-transcripts.sql` — the transcript/process-record contract of
     section 2.4 plus `transcript_segments` and `v_pending_subtitles`.
2. `initialize_schema` keeps executing `schema.sql` first, then inspects the database:
   - `transcripts` absent, or present with `language` + `content_sha256` ⇒ execute
     `schema-transcripts.sql` (idempotent: every statement is `IF NOT EXISTS`);
   - `transcripts` present **without** those columns ⇒ skip the transcript script entirely, so
     nothing half-applies and no statement fails. The metadata path keeps working on that
     database exactly as before.
3. `require_subtitle_schema(connection) -> None` (module-level, beside `initialize_schema`)
   raises `SchemaContractError` unless the transcript contract is present. Both subtitle
   commands call it after opening the database and before any work; the CLI prints one fixed
   bounded line and exits `1`:

   ```text
   <command>: archive database predates the transcript schema; rebuild it
   (delete {archive_root}/archive.db and re-run fetch-meta)
   ```

   The check is structural (`pragma_table_info('transcripts')` must contain `language` and
   `content_sha256`, and `acquisition_runs` / `acquisition_attempts` / `v_pending_subtitles`
   must exist), not a version counter: a stale stamp can lie, a missing column cannot.
4. The metadata commands (`fetch-meta`, `status`, `runs`, `recover`) keep their current
   behaviour on both a fresh and a pre-iteration database; this iteration does not change
   their semantics and does not require them to upgrade anything.

## 4. Repository contract

A sibling repository class `TranscriptRepository` in `src/bili_asr/storage/database.py`,
constructed on the same connection as `MetadataRepository` (one connection, one transaction
discipline, same validation helpers). It is a separate class because the transcript/process
aggregate has its own commit-boundary matrix; the metadata repository's documented matrix
stays exactly true.

```python
start_acquisition_run(run: AcquisitionRunRecord) -> None
finish_acquisition_run(run_id: str, finished_at: int, *, outcome: str | None = None) -> str
record_acquired_transcript(
    *,
    run_id: str,
    video_part_id: int,
    source_kind: str,
    language: str,
    segments: tuple[TranscriptSegmentRecord, ...],
    started_at: int,
    finished_at: int,
    created_at: int,
) -> TranscriptWriteResult
record_subtitle_attempt(
    *,
    run_id: str,
    video_part_id: int,
    outcome: str,                 # 'no-subtitle' | 'failed' only
    error_code: str | None,
    started_at: int,
    finished_at: int,
) -> None
read_transcript(
    video_part_id: int, source_kind: str, language: str, version: int | None = None
) -> TranscriptRecord | None
list_transcript_versions(
    video_part_id: int, source_kind: str, language: str
) -> list[sqlite3.Row]
list_pending_subtitle_parts(limit: int | None = None) -> list[sqlite3.Row]
count_pending_subtitle_parts() -> int
list_selected_parts(bvid: str, page_index: int | None = None) -> list[sqlite3.Row]
```

Commit boundaries (documented in the class docstring exactly as `MetadataRepository` documents
its own):

- `start_acquisition_run` and `finish_acquisition_run` commit their own single write, so a
  failed part can roll back without losing the run parent — the shipped `start_run` /
  `finish_run` discipline. `finish_acquisition_run` refuses to move a run out of a terminal
  outcome, returns the resulting outcome, and derives `complete | partial | failed` from the
  attempt rows when no explicit outcome is given.
- `record_acquired_transcript` owns **one** transaction: it validates the part exists,
  computes the content hash, writes the transcript row and its segments when the content is
  new, writes the attempt row with the resulting `stored`/`unchanged` outcome, and commits —
  or rolls back wholly. It returns `TranscriptWriteResult(outcome, transcript_id, version,
  content_sha256)`.
- `record_subtitle_attempt` owns one transaction for a `no-subtitle`/`failed` attempt and
  commits it. Neither method touches the other's tables by side effect.
- Read paths never write or commit (`read_transcript`, `list_transcript_versions`,
  `list_pending_subtitle_parts`, `count_pending_subtitle_parts`, `list_selected_parts`).
- Do not compose these methods inside `MetadataRepository.transaction()`: each commits
  independently.

Validation rules: writes are transactional; `work_id` stays a view/computed value and is never
stored; no derived duplicates in base tables; bounded scalar codes only
(`validate_error_code`); a `transcript_id` in an argument or result always refers to a row the
same connection can read.

DTOs added to `storage/models.py` (independent of third-party or `sources` types, so the
storage layer never imports the gateway layer). Dated PM note (2026-09-11, Task-3 review
disclosure (a)): this list originally omitted **`TranscriptRecord`**, the return type the
section-4 signatures already name — it ships as a storage DTO and belongs to this list; the
note corrects the omission rather than re-reading the signatures.

```python
@dataclass(frozen=True, slots=True)
class TranscriptSegmentRecord:
    start_ms: int          # >= 0
    end_ms: int            # > start_ms
    text: str              # non-empty after strip

@dataclass(frozen=True, slots=True)
class TranscriptWriteResult:
    outcome: str           # 'stored' | 'unchanged'
    transcript_id: int
    version: int
    content_sha256: str

@dataclass(frozen=True, slots=True)
class AcquisitionRunRecord:
    run_id: str
    kind: str              # 'subtitle'
    selector_kind: str     # 'pending' | 'bvid'
    selector_target: str | None
    requested_limit: int | None
    credential_present: bool
    started_at: int
    finished_at: int | None = None
    outcome: str = "running"
```

The service layer converts gateway `SubtitleSegment` DTOs into `TranscriptSegmentRecord`s; the
storage layer imports nothing from `bili_asr.sources`.

## 5. Normalization rules

- `start_ms`/`end_ms` arrive from the gateway already converted with
  `floor(seconds * 1000)`; the repository re-validates `end_ms > start_ms >= 0` at the DB
  boundary and rejects a violation with `ValueError` rather than trusting the caller.
- Ordinals are assigned by position: `ordinal = 0 .. len(segments) - 1`. A stored transcript
  is never empty (an empty segment tuple is rejected before insert), so "a transcript exists"
  always means "there is caption text". No ordering constraint is imposed on `start_ms`:
  upstream order is preserved verbatim, overlaps included.
- `text` is stored trimmed; empty text is rejected.
- **Timeline ceiling (dated PM note 2026-09-11, carried from plan `20260911-subtitle-gateway` QC S11 /
  QC3-008 and implemented in this plan's Task 2):** a segment whose millisecond value exceeds
  `MAX_TIMELINE_MS = 10**12` (≈31.7 years) is rejected with the bounded validation error at the SQL
  boundary, so an upstream JSON integer can never reach SQLite as an unbounded `OverflowError`. The
  DTO deliberately still accepts an unbounded integer (so moving the bound stays a visible change).
- **Trimming site (dated PM note 2026-09-11, Task-1 review M1):** stored text is trimmed **at the
  repository boundary** — stored text is hashed text, so content identity is whitespace-insensitive;
  control characters inside the string stay verbatim.
- `source_kind` derives from `SubtitleTrack.is_ai` (`subtitle-ai` vs `subtitle-cc`), and
  `language` is the track's upstream `lan`; `model_id` stays `NULL` for caption rows.
- `created_at` is the caller-supplied clock (the service's one `int(time.time())` per run),
  never a database default: every stored timestamp in a run shares one clock source, and the
  tests stay deterministic.

## 6. Acceptance

- A fresh database accepts one transcript with N segments in a single transaction; a repeat
  with identical content writes nothing new and records `unchanged`; a changed body appends
  version 2 while version 1 and its segments stay readable and unchanged — so a re-harvest can
  never cost the operator data they already hold.
- A stored transcript answers, per part: source kind (AI/CC), language, version, creation
  time, and millisecond segments; the default read returns the latest version and an explicit
  older version stays readable.
- A part attempted with no usable caption leaves exactly one timestamped attempt row carrying
  `no-subtitle` (and `not_found` when upstream signalled "not visible"), holds no transcript
  row, is still enumerated by `v_pending_subtitles` with `attempted = 1`, and a later
  successful acquisition of the same part stores a transcript normally under a new run.
- The pending enumeration shows a never-attempted part ahead of a previously attempted one,
  and a part with a stored transcript does not appear at all.
- Subtitle/transcript process records never touch `ingestion_runs` (carry F-010 resolved
  explicitly, pinned by schema and repository tests); the audio/ASR reservations stay empty.
- FK enforcement holds (a segment without its transcript and a transcript without its part are
  rejected; deletes are RESTRICTed), and the `acquisition_attempts` CHECK matrix rejects every
  illegal outcome/code/transcript combination.
- Schema bootstrap behaves on all three database states: fresh (full contract created),
  current-iteration (idempotent no-op), pre-iteration (metadata commands keep working, the
  transcript script is skipped, `require_subtitle_schema` raises).
- No sidecar file is read or written by any of the new code paths.

## 7. Promotion and handoff

This file is the plans' primary spec (`{PLAN_DIR}/20260911-transcript-storage.md`). The
transcript/process-record contract here is the part of this iteration's work that the next
(audio/ASR) iteration consumes; its promotion to `{SPECS_DIR}` or `{KNOWLEDGE_DIR}` is decided
at iteration-close (owner `project-manager`, trigger "this iteration delivered") through
`mstar-compound`, so that the frozen copy is written only once the code and the tests have
confirmed it — not ahead of them in this Prepare pass.
