---
module: bili-asr media queue (archive.db cutover)
date: "2026-09-27"
problem_type: architecture_pattern
category: architecture-patterns
severity: high
plan_id: 20260927-archive-db-queue-cutover
applies_when:
  - recording audio acquisition evidence in archive.db
  - deciding which table answers "does this part have audio?"
  - writing a view or query that probes audio evidence
  - reusing an audio object row across re-downloads or repairs
  - summing gap-group counts into a backlog total
tags:
  - audio-evidence
  - check-matrix
  - storage-key-identity
  - part-audio-objects
  - gap-views
  - media-queue
  - queue-cutover
---

# Audio evidence in the store: what the CHECK matrix forbids and where the evidence lives

## Context

The archive's SQLite store has two parallel vocabularies for acquisition evidence:
the caption-shaped `acquisition_runs` / `acquisition_attempts` pair (whose CHECK matrix
admits exactly three row shapes) and the media-object tables `audio_objects` /
`part_audio_objects` (reserved early, empty for months). The queue-cutover iteration
needed one honest answer to "does this part have audio?" and discovered, in sequence,
that the apparently natural place to record a successful audio download could not
express it, that the identity key a first implementation chose was wrong, and that a
view predicate built on the caption table was not merely loose but *inverted*. These
three rulings are recorded here so no later plan re-derives them.

## Guidance

### `acquisition_attempts` is caption-shaped; a successful audio download has no writable row

The `acquisition_attempts` CHECK matrix (`schema-transcripts.sql`, the
outcome↔code↔transcript CHECK) admits exactly three shapes:

| Shape | Required |
|-------|----------|
| `outcome = 'failed'` | `error_code NOT NULL` **and** `transcript_id IS NULL` |
| `outcome = 'no-subtitle'` | `error_code IS NULL or 'not_found'` **and** `transcript_id IS NULL` |
| `outcome IN ('stored','unchanged')` | `error_code IS NULL` **and** `transcript_id NOT NULL` |

An audio acquisition produces no transcript. The only branches with `transcript_id IS NULL`
therefore require `failed` (false — nothing failed) or `no-subtitle` (false — it is not a
caption outcome); `stored` with a NULL transcript violates the CHECK. The table records
subtitle outcomes, not audio ones, and **no instruction to "write the audio success into
`acquisition_attempts`" is implementable** — the brief can carry such a sentence forward
through any number of reviews without anyone noticing, because the schema's refusal happens
at INSERT time, not design time.

Consequences that are now the contract:

- A **successful** audio acquisition is recorded in `part_audio_objects` (the link table
  whose purpose is exactly this: `video_part_id, audio_id, acquired_at, acquisition_source`,
  PK `(video_part_id, audio_id)`), after resolving-or-creating the `audio_objects` row for
  the file. No `acquisition_attempts` row is written for the success case.
- `acquisition_attempts(kind='audio')` remains legal **only for a failed audio attempt**
  (`failed` + a bounded `error_code` satisfies the CHECK). Use it for that case; it is the
  attempt-history record, not the acquired-bytes record.
- A gap predicate that names `outcome='stored'` on an audio run describes a row shape the
  schema forbids. Treat any such sentence as a defect in the spec, not an implementation
  gap.

### `storage_key` IS the identity of an archived audio object

`audio_objects` has **two** UNIQUE constraints — `sha256` and `storage_key` — and the
first writer keyed reuse on `sha256` alone, so the case the contract itself names (the
same `audio_path` re-recorded with a different `sha256`, e.g. after a repaired decode)
raised `UNIQUE constraint failed: audio_objects.storage_key` from inside the transaction.

Ruling: **location is the identity of an archived audio object.** Rationale, in the order
that decides it:

1. The archive is a file archive. `audio_path` is the archive's own deterministic per-part
   naming; a re-download or repaired decode produces a new `sha256` for the *same*
   archived location. Treating that as a new object would grow `audio_objects` without
   bound and leave the path column's UNIQUE unsatisfiable.
2. Content hash is the wrong axis for re-acquisition. `sha256` answers "is this the same
   bytes?" — the *ingest* question `record_acquired_transcript` answers for transcripts.
   For audio the operator's question is "has this part's audio been acquired?", and the
   answer belongs to the part's path.
3. A writer that keys on `sha256` diverges from its own contract whenever the contract
   says "reuse an existing row when the same `audio_path` is already recorded"; the
   ruling restores that sentence rather than extending it.

Required behaviour of the audio-acquired writer:

- Resolve by `storage_key` (= the caller's `audio_path`) first. If the row exists, reuse
  its `audio_id` and refresh `sha256` / `byte_size` / `format` / `duration_ms` **only if
  they differ** — first-writer state is preserved when the values agree, so a re-run is a
  no-op.
- If no row matches the path but a different row already holds that `sha256`, the path
  column is what the caller asked to occupy. Reuse the `sha256`-holding row and repoint
  its `storage_key` to the new path (the chosen option: runtime schema introspection shows
  BOTH columns are UNIQUE, so two rows are unrepresentable and a bounded `ValueError`
  would make such a part permanently unrecordable). A silent third row is never allowed.
- `created_at` keeps first-writer semantics.
- Validate caller-supplied scalars with the module's `_text` / `_integer` helpers as every
  sibling write path does. Measured consequences of not doing so: `page_index=True`
  silently links the audio to a **different part**, and `byte_size=-1` / `format=None`
  surface as a raw `IntegrityError`. A caller-supplied `sha256` placeholder must also be
  validated as a content hash (`_content_sha256`), not free text — otherwise the
  repoint branch can rewrite an existing object's `storage_key` (the archive's file
  pointer) from unvalidated input.

### `part_audio_objects` is the SOLE positive audio-evidence probe

The first gap views expressed "has audio" as
`EXISTS(acquisition_attempts JOIN acquisition_runs … AND ar.kind='audio')` with **no
`outcome` predicate** — and, per the CHECK matrix above, a `kind='audio'` run has no
writable success shape at all: the arm's only reachable rows are **failed** downloads.
The predicate was not loose; it was inverted, and a part with no audio on disk would
report `audio_ok` and enter the transcription queue permanently (attempt rows are
append-only, so nothing would ever move it back out).

Ruling: in every gap view and pipeline probe, **`part_audio_objects` is the only positive
audio-evidence probe.** Remove the `acquisition_attempts` arm entirely — do not merely add
an `outcome` filter, because there is no audio-success outcome to filter for. Attempt rows
remain the record of *attempted* work (including failures); the rotation/retry policy
reads them at the **selection layer** via the exposed `attempt_count` (and later the newest
outcome). Membership is a question about acquired bytes; rotation is a question about
attempt history. Mixing them was the defect.

Old-database boundary, restated honestly: an old database holding downloaded audio but no
`part_audio_objects` rows over-selects into the missing-audio gap (the part is re-queued).
That is the **safe** direction — a re-download costs time, whereas the inverted reading
would put a part with no audio into the transcription queue permanently. It converges
when the operator rebuilds `archive.db` or the inventory backfill lands.

One-way-door mechanics: `CREATE VIEW IF NOT EXISTS` does not replace an existing view
body, so a view predicate is permanent once merged. These views existed only on an
unmerged feature branch, so the fix was an in-place body edit; a reader who meets a
shipped view with this predicate after the merge must treat it as frozen and ship a new
view name.

### The three gap groups overlap by design; never sum them

The three gap groups (`missing_subtitle`, `missing_audio`, `missing_transcript`) are **not
disjoint**: `v_missing_transcript` has no `NOT EXISTS` against the subtitle gap, so an
audio-attempted, transcriptless, non-gone part appears in both `missing_subtitle` and
`missing_transcript` (measured: `sum(count_queue_gaps()) == 2` for a fixture holding 1
distinct part). Consequences:

- **Never sum the three counts as a backlog total.** `count_queue_gaps()` answers per gap
  only; a "total distinct parts" figure needs its own distinct query, not an addition.
- The API's docstring is the only guard at that layer — the contract note lives under a
  non-published path — so the count method itself must warn that its values are not a
  partition.

## Why This Matters

Each ruling closed a failure that was invisible to the layer above it. The unimplementable
instruction passed author and reviewers because the schema's refusal happens at INSERT
time; the wrong identity key produced a clean rollback and a failed call rather than wrong
data, so it surfaced only when a reviewer ran the exact case the contract named; the
inverted evidence probe shipped with a test that pinned the wrong reading as intended,
because the brief's own sentence described the unwritable shape. The general form: **when
a table's CHECK matrix defines the vocabulary, any prose that names a shape outside the
matrix is a latent defect, and the cheapest verification is to try to write the row the
sentence describes.**

## When to Apply

- Recording audio acquisition evidence anywhere in this store: success goes to
  `part_audio_objects`; failures may use `acquisition_attempts(kind='audio')`.
- Writing or reviewing any view, predicate or probe that asks "does this part have audio?"
  — the answer is a `part_audio_objects` row, full stop.
- Reusing an `audio_objects` row: resolve by `storage_key`, refresh content columns only
  on difference, never create a second row for one path or one hash.
- Summing gap-group counts, or adding a new gap group: check disjointness first and pin
  the answer.
- Reviewing a brief that says to write a caption-shaped row for a non-caption outcome:
  check the CHECK matrix before dispatching.

## Examples

- `bilibili-asr-archive/src/bili_asr/storage/schema-transcripts.sql` — the
  `acquisition_attempts` CHECK matrix (three shapes) and the gap views whose
  audio-evidence arm is `part_audio_objects` alone.
- `bilibili-asr-archive/src/bili_asr/storage/database.py` — `mark_audio_acquired`
  (storage_key-first resolution, differ-only refresh, `_text`/`_integer` validation) and
  `MediaQueueRepository` (`list_queue_gaps` / `count_queue_gaps`, the non-disjointness
  docstring warning).
- `bilibili-asr-archive/src/bili_asr/storage/schema.sql` — the `audio_objects` /
  `part_audio_objects` DDL (both UNIQUE constraints on `audio_objects`, the
  `ON DELETE RESTRICT` link).

## Evidence

- Iteration `iter-2026-09-coverage-truth`; plan `20260927-archive-db-queue-cutover`.
- Rulings: `{ITERATION_DIR}/iter-2026-09-coverage-truth/specs/queue-cutover-contract.md`
  §4b (caption-shaped attempts table), §4c (storage_key identity), §4d (sole positive probe).
- The inversion found independently by two plan-QC seats:
  `{SDD_DIR}/20260927-archive-db-queue-cutover/review/qc-consolidated.md` (seat
  convergence on the same Important) and the fix round `425ada2..c068e36` (arm deleted,
  RED-before/GREEN-after recorded: pre-fix `missing_audio=[]` /
  `missing_transcript=[BV1TEST:p0]` / `audio_ok`, post-fix `[BV1TEST:p0]` / `[]` /
  `audio_pending`).
- The identity-key defect and its fix: `{SDD_DIR}/20260927-archive-db-queue-cutover/progress.md`
  (T1b-i review → §4c ruling → `63f4388..425ada2`).
- Prior iteration package (superseded for the audio-success case):
  `{ITERATION_DIR}/iter-2026-09-metadata-audio-layout/specs/audio-retention-contract.md`
  §3 (field semantics, including the both-UNIQUE constraint and the in-place UPDATE rule).

## See also

- [normalized-transcript-storage.md](normalized-transcript-storage.md) — the
  `acquisition_attempts` CHECK matrix and the run/attempt evidence pair this contract
  builds on.
- [queue-derivation-bridge.md](queue-derivation-bridge.md) — the manifest bridge this
  cutover replaces; its additive-never-authoritative rule and effective-key trap.
