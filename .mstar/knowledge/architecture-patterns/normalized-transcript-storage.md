---
module: bili-asr transcript storage
date: 2026-09-11
last_updated: 2026-09-19
problem_type: architecture_pattern
category: architecture-patterns
severity: medium
plan_id: 20260911-transcript-storage
applies_when:
  - adding a transcript source (uploader CC, AI captions, local ASR) to the archive
  - changing the transcript schema, the acquisition process records, or the bootstrap
  - deciding where run and per-item acquisition evidence lives
  - enumerating the parts that still have no transcript
  - reviewing writes that must stay immutable, versioned, or content-idempotent
tags:
  - sqlite-transcripts
  - content-identity
  - versioning
  - process-records
  - schema-bootstrap
  - idempotency
  - work-queue
---

# Normalized transcript storage on the reserved tables

## Context

Captions are stored as normalized rows in `{archive_root}/archive.db`, not as sidecar files:
on the subtitle path, `transcripts` plus `transcript_segments` are the store and no JSONL
manifest file is read or written (the ASR/pilot chain still runs on the manifest, which the
subtitle path simply does not feed). The tables were reserved by the metadata iteration as empty
foreign-key boundaries; this contract fills them and settles the three decisions that
otherwise leak into every later consumer — what identifies a transcript, what identifies its
content, and where the *process* record of an acquisition lives. The same shape is meant to
carry local ASR rows later, so the caption-only parts of it are scoped deliberately.

## Guidance

### Transcript rows and their uniqueness

`transcripts` is one row per (part, source kind, language, version) with the language and the
content hash stored on the row:

```sql
transcripts(
    transcript_id   INTEGER PRIMARY KEY,
    video_part_id   INTEGER NOT NULL REFERENCES video_parts(video_part_id) ON DELETE RESTRICT,
    source_kind     TEXT NOT NULL CHECK (source_kind IN ('subtitle-ai','subtitle-cc','asr-local')),
    language        TEXT NOT NULL CHECK (length(trim(language)) > 0),
    model_id        INTEGER REFERENCES asr_models(model_id) ON DELETE RESTRICT,   -- NULL for captions
    version         INTEGER NOT NULL CHECK (version > 0),
    content_sha256  TEXT NOT NULL CHECK (length(content_sha256) = 64 AND content_sha256 = lower(content_sha256)),
    created_at      INTEGER NOT NULL,
    UNIQUE (video_part_id, source_kind, language, version)
)
```

- **Language is an attribute of the transcript, not of the part.** One part can carry
  `zh-CN`, `ai-zh`, and any further language upstream offers, each with its own version
  history, so the version key is `(video_part_id, source_kind, language, version)`. Keeping it
  in the row is what makes "the archive holds version 2 of the Chinese CC caption for this
  part" a single-row fact and keeps the table in 3NF.
- **Content identity is hashed only over the content.** `content_sha256` is SHA-256 over the
  canonical JSON of the normalized segment sequence:

  ```python
  canonical = json.dumps(
      [[segment.start_ms, segment.end_ms, segment.text] for segment in segments],
      ensure_ascii=False,
      separators=(",", ":"),
  )
  content_sha256 = hashlib.sha256(canonical.encode("utf-8")).hexdigest()  # 64 lowercase hex
  ```

  The part id, source kind, and language are the identity *key* and are deliberately not
  hashed: the hash answers "is this the same caption text?", not "is this the same slot?".
- **Uniqueness is widened, not replaced.** The base unique key stays
  `(video_part_id, source_kind, language, version)`; a partial unique index enforces content
  identity for the caption kinds only:

  ```sql
  CREATE UNIQUE INDEX ux_transcripts_subtitle_content
      ON transcripts(video_part_id, source_kind, language, content_sha256)
      WHERE source_kind IN ('subtitle-ai', 'subtitle-cc');
  ```

  The `WHERE` clause is load-bearing: `asr-local` versioning is per model/run, and that
  decision belongs to the ASR owner. A model-agnostic version key therefore does not pre-empt
  it — but it also means activating `asr-local` with more than one model requires *widening*
  the version key to carry the model identity.
- **Segments** are `(transcript_id, ordinal)` keyed, with `ordinal >= 0`, `start_ms >= 0`,
  `end_ms > start_ms`, `text` `NOT NULL`, and `ON DELETE RESTRICT` to `transcripts`. "Text is
  non-empty after trimming" is a repository rule, not a DDL `CHECK`.

### Immutability is structural, not a trigger

A version is never rewritten or deleted. Three independent mechanisms hold that, and none of
them is a database trigger:

1. no code path issues `UPDATE` or `DELETE` against `transcripts` / `transcript_segments`
   (enforced by inspection of the shipped source — it is the one mechanism not falsifiable by
   a test on its own);
2. `ON DELETE RESTRICT` from `transcript_segments` to `transcripts` makes deleting a
   transcript that has segments impossible, and a transcript is only ever written with a
   non-empty segment tuple, so a segment-less version cannot exist to delete;
3. tests assert that a re-acquisition with changed content leaves the earlier version's row
   and segments byte-identical, and that deleting a stored transcript is rejected.

Rejecting a trigger is deliberate: the constraint belongs to the data model, so a future
maintenance path cannot silently disable it by skipping a trigger.

### Process records: a `kind`-keyed run/attempt pair

Acquisition evidence lives in `acquisition_runs` + `acquisition_attempts`, keyed by
`kind ∈ {subtitle, audio, asr}` — **not** in the metadata-scoped `ingestion_runs`:

```sql
acquisition_runs(
    run_id TEXT PRIMARY KEY, kind, selector_kind CHECK (selector_kind IN ('pending','bvid')),
    selector_target, requested_limit CHECK (requested_limit IS NULL OR requested_limit > 0),
    credential_present INTEGER CHECK (credential_present IN (0,1)),
    started_at, finished_at, outcome CHECK (outcome IN ('running','complete','partial','failed')),
    CHECK ((selector_kind = 'pending' AND selector_target IS NULL)
        OR (selector_kind = 'bvid'    AND selector_target IS NOT NULL)),
    CHECK (finished_at IS NULL OR finished_at >= started_at)
)

acquisition_attempts(
    run_id, video_part_id,
    outcome CHECK (outcome IN ('stored','unchanged','no-subtitle','failed')),
    error_code CHECK (error_code IS NULL OR length(error_code) <= 64),
    transcript_id, started_at, finished_at,
    PRIMARY KEY (run_id, video_part_id),
    FOREIGN KEY (run_id)        REFERENCES acquisition_runs(run_id)         ON DELETE RESTRICT,
    FOREIGN KEY (video_part_id) REFERENCES video_parts(video_part_id)       ON DELETE RESTRICT,
    FOREIGN KEY (transcript_id) REFERENCES transcripts(transcript_id)       ON DELETE RESTRICT,
    CHECK ((outcome = 'failed'   AND error_code IS NOT NULL AND transcript_id IS NULL)
        OR (outcome = 'no-subtitle' AND (error_code IS NULL OR error_code = 'not_found')
                                    AND transcript_id IS NULL)
        OR (outcome IN ('stored','unchanged') AND error_code IS NULL
                                    AND transcript_id IS NOT NULL)),
    CHECK (finished_at >= started_at)
)
-- plus: CREATE INDEX ix_acquisition_attempts_part_time ON acquisition_attempts(video_part_id, finished_at);
```

Contract points that a consumer can rely on:

- **One outcome per attempted part per run**, enforced by `PRIMARY KEY (run_id,
  video_part_id)` rather than by convention.
- **The CHECK matrix is the vocabulary.** `failed` requires a bounded `error_code` and may
  not reference a transcript. `no-subtitle` carries `error_code IS NULL` (the listing was
  simply empty) or `'not_found'` (upstream signalled "not visible": `not_found`, `-101`,
  `-404`, `-62002`) and never a transcript. Only `stored` / `unchanged` may reference a
  transcript, and both must. Every other combination is rejected by the database.
- **No terminal per-part state.** Attempts are append-only evidence scoped to a run: there is
  no part-level status column and no upsert across runs, so a part recorded `no-subtitle` is
  re-attempted in a later run and can then store a transcript normally.
- **Credential presence is a run-scoped fact** (`acquisition_runs.credential_present`). It is
  not repeated per attempt, because the attempt belongs to the run; a `no-subtitle` attempt
  stays interpretable afterwards precisely because its run says whether a credential was in
  effect.
- **Run outcome is derived, not declared.** `finish_acquisition_run` computes `failed` when
  every attempt failed (or the service aborted abnormally), `partial` when failed and
  non-failed attempts coexist, and `complete` otherwise — including a run with zero attempts,
  which means the bounded work set was empty and nothing failed. A terminal outcome cannot be
  regressed.
- **`ingestion_runs` was deliberately not overloaded.** It is keyed by `mid` and carries
  cursor semantics (`requested_start_page`, `source_package`, `observed_total`) that say
  nothing true about a per-part caption probe; overloading it would need either a nullable
  metadata target or a second meaning for `outcome`. The unit of evidence differs too — one
  metadata page versus one part — which is why the child table is named for its unit
  (`acquisition_attempts`) instead of copying the `*_pages` metaphor. Reusing the same pair
  with a different `kind` is the intended extension path; adding a new table is not.

### Bootstrap split and the structural guard

The archive database is **rebuildable by policy**: there is no `ALTER TABLE`, no backfill, no
compatibility reader, and no migration reader planned. `CREATE TABLE IF NOT EXISTS` cannot
widen an existing unique constraint, so a database created before the transcript contract
would silently keep the old `transcripts` shape. The bootstrap therefore makes both outcomes
explicit instead of accidental:

- The schema is two checked-in resources:
  `bilibili-asr-archive/src/bili_asr/storage/schema.sql` (everything shipped before the
  contract, *minus* the transcript block) and
  `bilibili-asr-archive/src/bili_asr/storage/schema-transcripts.sql` (the transcript tables,
  the content index, `transcript_segments`, the run/attempt pair, and the pending view).
- `initialize_schema` executes the base resource, then executes the transcript script **only when**
  the database is fresh (`transcripts` absent) or already carries the contract columns
  (`language`, `content_sha256`). A pre-iteration database is left alone: the script is
  skipped entirely, nothing half-applies, no statement fails, and the metadata path keeps
  working on that same file.
- `require_subtitle_schema(connection)` is the capability guard. It is **structural**: the
  contract columns must be present in `pragma_table_info('transcripts')` *and*
  `acquisition_runs` / `acquisition_attempts` / `v_pending_subtitles` must exist. A version
  counter can lie; a missing column cannot. It raises `SchemaContractError`, and because it
  holds a connection and never an archive root, the operator-facing line is composed by the
  caller (see [bilibili-asr-archive-cli.md](bilibili-asr-archive-cli.md)).
- The guard does not test for `transcript_segments`: the shipped `open_database` path applies
  the idempotent script on every open, which heals a missing table, so the omission is
  unreachable through the shipped entrypoint. A caller that opens a raw connection and skips
  the bootstrap is outside that guarantee.

### Idempotency semantics

`record_acquired_transcript` owns **one** transaction: it validates that the part exists,
computes the content hash, writes the transcript row and its segments when the content is
new, writes the attempt row with the resulting outcome, and commits — or rolls back wholly.
The two content outcomes:

- **`unchanged`** — some version of `(video_part_id, source_kind, language)` already carries
  that hash. Nothing is written to `transcripts` / `transcript_segments`; the attempt row
  references that existing version, the one the operator already holds. Idempotency is
  therefore checkable without comparing segment rows.
- **`stored`** — otherwise the row is appended at
  `version = COALESCE(MAX(version), 0) + 1` for that key, with its segments.

Consequences worth knowing before writing a consumer:

- **Content that reverts to an older version is not stored twice.** The archive already holds
  it, so the new attempt is `unchanged` and points at the *older* matched version. The attempt
  row still records that the acquisition happened and when, and its run records credential
  presence.
- **That creates one deliberate ambiguity**: after a revert-to-older-content acquisition,
  `read_transcript(version=None)` returns `MAX(version)` while the newest attempt references
  the matched older version. Both facts are stored and both are true; a projection or export
  step must choose deliberately which one "the current caption" means rather than assuming
  they agree.
- **A stored transcript is never empty.** An empty segment tuple is rejected before insert, so
  "a transcript row exists" always means "there is caption text".
- `record_subtitle_attempt` owns one transaction for a `no-subtitle` / `failed` attempt and
  commits it; neither method touches the other's tables by side effect. Read paths never write
  or commit. None of these methods may be composed inside `MetadataRepository.transaction()`:
  each commits independently.

### The pending-work relation and its ordering

`v_pending_subtitles` is the work queue, and it carries the last-attempt evidence itself
rather than requiring a companion per-part query (one relation, one query, no per-part N+1).
It selects every part that is not `gone` and has no `transcripts` row, left-joined to the
newest attempt per part (`ROW_NUMBER() OVER (PARTITION BY video_part_id ORDER BY finished_at
DESC, run_id DESC)`, restricted to runs with `kind = 'subtitle'`), and exposes
`attempted`, `last_attempt_at`, `last_attempt_outcome`, `last_attempt_error_code`,
`last_attempt_credential_present` plus the work item (`video_part_id`, `work_id`, `bvid`,
`page_index`, `cid`, `part_title`, `duration_ms`).

- The view deliberately does **not** order; the repository imposes
  `attempted ASC, last_attempt_at ASC, bvid ASC, page_index ASC`. Never-attempted parts come
  first, then the oldest-attempted parts, so successive bounded runs rotate through the
  captionless backlog instead of re-attempting the same head forever. A bounded runner that
  changes this order reintroduces head-of-line stalling.
- A part recorded `no-subtitle` **does** appear, still counts as without a transcript, and
  brings its last outcome, code, timestamp, and credential presence with it. `attempted = 0`
  versus `attempted = 1` is what separates "never looked at" from "looked at and still
  captionless".
- `processing_status = 'gone'` parts are excluded from the pending enumeration. An explicit
  by-id selection is deliberately *not* status-filtered: explicit means explicit, and the
  resulting evidence records the truth.
- A read-only probe records nothing, so "previously attempted" always means "previously
  attempted by a run that persists evidence".
- The `cid` comes from `video_parts` through this relation, so the caption path never fetches
  a pagelist and never calls upstream for a part that is not in the database. `work_id` stays
  a view/computed value and is never stored on a base table.
- **Two selection sources, one work-item shape.** The pending relation carries `bvid` and
  `cid`; an explicit by-video selection over the parts view does not carry `bvid`. A consumer
  that offers both selects normalizes the two row shapes into one work item before calling the
  gateway, instead of branching on the source later.

### Normalization contracts at the storage boundary

- **Timeline ceiling.** `MAX_TIMELINE_MS = 10**12` (≈31.7 years) in
  `bilibili-asr-archive/src/bili_asr/storage/models.py`. A segment whose millisecond value
  exceeds it is rejected with the repository's bounded validation error, so an upstream JSON
  integer can never reach SQLite as an unbounded `OverflowError`. The DTO deliberately still
  accepts an unbounded integer, so moving the bound stays a visible change rather than a
  silent widening.
- **Trimming site.** Stored text is trimmed **at the repository boundary**, and stored text is
  hashed text — so content identity is whitespace-insensitive. Interior control characters
  stay verbatim: the store preserves upstream content, and the operator-facing label rules
  that reject control characters live at the gateway, not here.
- **Ordinals and intervals.** Ordinals are assigned by position (`0 .. len(segments) - 1`),
  and `end_ms > start_ms >= 0` is re-validated at the DB boundary (`ValueError`) rather than
  trusted from the caller. No ordering constraint is imposed on `start_ms`: upstream order is
  preserved verbatim, overlaps included — a "sort or de-overlap on write" regression is a
  contract break, not a tidy-up.
- **Clocks are caller-supplied.** `created_at` (and the run/attempt timestamps) come from the
  service's one clock read per run, never a database default: every timestamp in a run shares
  one clock source and tests stay deterministic.
- **Layering.** `storage` imports nothing from `sources`:
  `bilibili-asr-archive/src/bili_asr/storage/models.py` owns
  `TranscriptSegmentRecord`, `TranscriptWriteResult`, `AcquisitionRunRecord` and the
  vocabulary frozensets, and the service maps the gateway's segment DTO onto the storage
  record.

## Why this matters

- Captions become queryable facts about a part — source kind, language, version, creation
  time, millisecond timeline — instead of file names and manifest columns, and the audio/ASR
  iteration inherits one target to write into rather than inventing a second store.
- Content-hash idempotency is what makes re-running acquisition free and safe: an unchanged
  caption writes nothing, and no re-run can cost the operator a version they already hold.
- Recording "no caption was visible" as timestamped per-part evidence, with the credential
  presence of the attempt's run, is what keeps a captionless part from being silently skipped,
  silently assumed captionless, or turned into a terminal state.
- The structural guard plus rebuild-by-policy is what lets the metadata path keep working on
  an older database while the caption commands refuse to guess: an honest "rebuild this
  database" answer instead of a half-applied schema or a raw SQLite error.

## When to apply

- Adding a transcript source: reuse this row shape and the `kind`-keyed run/attempt pair; do
  not add a second evidence table and do not overload `ingestion_runs`.
- Changing the transcript schema or bootstrap: keep the two-resource split and the structural
  guard in step, and remember the rebuild stance — a schema change means a fresh database, not
  an upgrade path.
- Enumerating work over parts without a transcript: consume `v_pending_subtitles` through the
  repository and keep the locked ordering.
- Reviewing writes: a new path that updates or deletes a transcript row, or that writes a
  content-bearing row without the hash, breaks the contract.

## Examples

- `bilibili-asr-archive/src/bili_asr/storage/schema-transcripts.sql` — the contract in DDL,
  including the CHECK matrix and the pending view.
- `bilibili-asr-archive/src/bili_asr/storage/database.py` —
  `initialize_schema` / `require_subtitle_schema` / `SchemaContractError` and the
  `TranscriptRepository` commit matrix.
- `bilibili-asr-archive/src/bili_asr/storage/models.py` — `MAX_TIMELINE_MS`, the record
  dataclasses, and the acquisition vocabularies.
- `bilibili-asr-archive/tests/test_storage_schema.py` — column manifests, index and CHECK
  enumerations, and the fresh / current / pre-iteration bootstrap matrix.
- `bilibili-asr-archive/tests/test_transcript_repository.py` — transactional writes,
  idempotent replay, version append, immutability, and the pending-enumeration ordering.
- `bilibili-asr-archive/docs/metadata-storage.md` — the operator-facing description of the
  same tables and views.

## Known limits (as shipped)

- **Any `transcripts` row means "this part has a caption".** When ASR rows (`asr-local`)
  start landing, those parts leave the subtitle backlog. That is the locked behaviour, but the
  ASR iteration must decide explicitly whether it wants its own pending view or a
  `source_kind`-scoped predicate rather than inheriting this one. This relation now has a second
  named consumer, and its reading there is deliberate: `derive-manifest` reads it as the **audio
  queue** — "the part holds no text at all", so a stored ASR transcript correctly removes the part
  from that queue — while the *caption* backlog's label is what a source-kind-scoped view still has
  to repair, in the iteration that first writes `asr-local` rows (see
  [queue-derivation-bridge.md](queue-derivation-bridge.md)).
- **The write path verifies the run exists but not its `kind`.** An attempt recorded under an
  `audio`/`asr` run is invisible to `v_pending_subtitles` (which filters `kind = 'subtitle'`),
  so such a part would never rotate out of the subtitle backlog. The shipped caller passes
  `kind = 'subtitle'`; the ASR iteration must add a precondition or scope its own view.
- **Pending queries are O(attempts).** The `ROW_NUMBER()` CTE gets no predicate pushdown and
  `acquisition_attempts` is append-only with no pruning, so every pending query and count
  scans the attempt history. Fine at personal scale; recorded so a growth problem is
  recognized rather than rediscovered.
- **One immutability mechanism is inspection-only.** "No `UPDATE`/`DELETE` code path" is not
  falsifiable by a test today; a static source scan would make it one.
- **`asr-local`, `audio_objects`, `part_audio_objects`, and `asr_models` remain empty
  reservations.** No audio or ASR row is written by this contract, and the model-agnostic
  version key plus the caption-scoped content index hand the model-identity decision to the
  ASR iteration.

## See also

- [normalized-metadata-stack.md](normalized-metadata-stack.md) — the gateway → ingestor →
  repository layering, the reserved-table baseline, and the metadata-side cursor/run
  vocabulary this contract extends rather than replaces.
- [subtitle-acquisition-contract.md](subtitle-acquisition-contract.md) — the typed gateway
  that produces the segments stored here.
- [bilibili-asr-archive-cli.md](bilibili-asr-archive-cli.md) — the operator surface that fills
  these tables and the exit taxonomy around the schema guard.
- [queue-derivation-bridge.md](queue-derivation-bridge.md) — the command that reads this store's
  work relation as the audio queue and writes the chain's manifest rows from it, additively.
- [operational-sidecars.md](operational-sidecars.md) — the JSONL sidecars and the archival-flow
  state machine that this path does not use.
