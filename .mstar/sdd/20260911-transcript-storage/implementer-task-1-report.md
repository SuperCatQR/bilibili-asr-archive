# Task 1 report — Schema contract, bootstrap split, and structural guard

- Plan: `.mstar/plans/20260911-transcript-storage.md` (task 1 of 3)
- Working branch: `feature/20260911-transcript-storage`
- Worktree: `/root/workspace/bilibili-asr-archive/.worktrees/20260911-transcript-storage`
- Commit: `d4cae24` — `feat(storage): lock the transcript schema contract and split the bootstrap`
- Status: **DONE**

## Implemented

1. **Bootstrap split.** `schema.sql` keeps everything shipped before this iteration minus
   the `transcripts` / `transcript_segments` block (replaced by a three-line pointer
   comment). The transcript contract moved to the new resource
   `src/bili_asr/storage/schema-transcripts.sql`, declared in `pyproject.toml`
   `[tool.setuptools.package-data]["bili_asr.storage"]` so it ships with the wheel.
2. **Locked DDL** in `schema-transcripts.sql` (statement-for-statement identical to spec
   §2.4 / §2.5 — verified mechanically, see *Self-review*).
3. **Conditional bootstrap** in `initialize_schema`: `PRAGMA foreign_keys = ON` enforcement
   unchanged, then `schema.sql`, then `schema-transcripts.sql` only when `transcripts` is
   absent *or* already carries `language` + `content_sha256`.
4. **Structural guard** `require_subtitle_schema(connection)` raising
   `SchemaContractError` (a `RuntimeError`): `pragma_table_info('transcripts')` must contain
   `language` and `content_sha256`, and `acquisition_runs` / `acquisition_attempts` /
   `v_pending_subtitles` must exist. Both names exported from
   `bili_asr.storage.database` and re-exported from the `bili_asr.storage` package root.
5. **Storage vocabulary + DTOs** in `storage/models.py`: `AcquisitionKind`,
   `AcquisitionOutcome`, `AttemptOutcome`, `SourceKind` (`Literal` + `ALLOWED_*` frozensets)
   and `TranscriptSegmentRecord`, `TranscriptWriteResult`, `AcquisitionRunRecord` with
   validation; all re-exported from the package root.
6. **Schema inspection tests** extended (see *Tests*).

## Exact DDL deltas

### `transcripts` (changed)

| Element | Before (shipped) | After (locked) |
|---|---|---|
| columns | `transcript_id, video_part_id, source_kind, model_id, version, created_at` | `transcript_id, video_part_id, source_kind, language, model_id, version, content_sha256, created_at` |
| new column check | — | `language TEXT NOT NULL CHECK (length(trim(language)) > 0)`; `content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64 AND content_sha256 = lower(content_sha256))` |
| unique key | `UNIQUE (video_part_id, source_kind, version)` | `UNIQUE (video_part_id, source_kind, language, version)` |
| FKs | `video_part_id → video_parts` RESTRICT, `model_id → asr_models` RESTRICT | unchanged (both `ON DELETE RESTRICT`) |
| new index | — | `CREATE UNIQUE INDEX ux_transcripts_subtitle_content ON transcripts(video_part_id, source_kind, language, content_sha256) WHERE source_kind IN ('subtitle-ai', 'subtitle-cc')` — partial: `asr-local`'s model identity stays with the audio/ASR iteration |
| other checks | `source_kind IN ('subtitle-ai','subtitle-cc','asr-local')`, `version > 0` | unchanged |

`transcript_segments` is byte-identical to the shipped block (verified against
`HEAD:schema.sql`) — it only changed file.

### `acquisition_runs` (new)

Columns: `run_id TEXT PRIMARY KEY`, `kind TEXT NOT NULL CHECK (kind IN ('subtitle','audio','asr'))`,
`selector_kind TEXT NOT NULL CHECK (selector_kind IN ('pending','bvid'))`,
`selector_target TEXT`, `requested_limit INTEGER CHECK (requested_limit IS NULL OR requested_limit > 0)`,
`credential_present INTEGER NOT NULL CHECK (credential_present IN (0, 1))`,
`started_at INTEGER NOT NULL`, `finished_at INTEGER`,
`outcome TEXT NOT NULL CHECK (outcome IN ('running','complete','partial','failed'))`.
Table CHECKs: `(selector_kind = 'pending' AND selector_target IS NULL) OR (selector_kind = 'bvid' AND selector_target IS NOT NULL)`;
`finished_at IS NULL OR finished_at >= started_at`. No FK (a run is not owned by a metadata
target); `ingestion_runs` untouched.

### `acquisition_attempts` (new)

Columns: `run_id TEXT NOT NULL`, `video_part_id INTEGER NOT NULL`,
`outcome TEXT NOT NULL CHECK (outcome IN ('stored','unchanged','no-subtitle','failed'))`,
`error_code TEXT CHECK (error_code IS NULL OR length(error_code) <= 64)`,
`transcript_id INTEGER`, `started_at INTEGER NOT NULL`, `finished_at INTEGER NOT NULL`.
`PRIMARY KEY (run_id, video_part_id)` — one outcome per attempted part per run.
FKs (all `ON DELETE RESTRICT`): `run_id → acquisition_runs`, `video_part_id → video_parts`,
`transcript_id → transcripts`. CHECK matrix:
`(failed AND error_code IS NOT NULL AND transcript_id IS NULL) OR (no-subtitle AND (error_code IS NULL OR error_code = 'not_found') AND transcript_id IS NULL) OR (outcome IN ('stored','unchanged') AND error_code IS NULL AND transcript_id IS NOT NULL)`;
`CHECK (finished_at >= started_at)`.
Index: `ix_acquisition_attempts_part_time ON acquisition_attempts(video_part_id, finished_at)`.

### `v_pending_subtitles` (new view)

Verbatim from spec §2.5 (`ROW_NUMBER()` CTE over subtitle attempts joined to their runs,
`LEFT JOIN` for the newest attempt, exclusion of `processing_status = 'gone'` and of parts
holding any `transcripts` row). Columns: `video_part_id, work_id, bvid, page_index, cid,
part_title, duration_ms, attempted, last_attempt_at, last_attempt_outcome,
last_attempt_error_code, last_attempt_credential_present`.

### Bootstrap behaviour

| Database state | `initialize_schema` | `require_subtitle_schema` |
|---|---|---|
| fresh | metadata script then transcript script → full contract | passes |
| current-iteration | transcript script re-applied; every statement is `IF NOT EXISTS`, so declared DDL and rows are untouched (a dropped view is recreated) | passes |
| pre-iteration (`transcripts` exists without `language`/`content_sha256`) | transcript script **skipped**; the legacy `transcripts`/`transcript_segments` DDL is byte-identical after the call, legacy rows stay readable, and the metadata path (read + cursor write) keeps working | raises `SchemaContractError("archive database predates the transcript schema; rebuild it (delete archive.db and re-run fetch-meta)")` |

No `ALTER TABLE`, no backfill, no migration reader was added.

## Tests

Command:

```
cd bilibili-asr-archive && /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_storage_schema.py -v
```

Focused output (green):

```
36 passed in 0.99s
```

Full offline suite (same interpreter, worktree):

```
1120 passed, 3 skipped in 44.85s
```

Baseline was `1096 passed, 3 skipped` → **+24 tests**, all in `tests/test_storage_schema.py`.

New tests: `test_bootstrap_creates_the_full_contract_on_a_fresh_database`,
`test_bootstrap_reapplies_the_contract_to_a_current_database`,
`test_bootstrap_leaves_a_pre_iteration_database_untouched`,
`test_require_subtitle_schema_requires_the_process_record_objects`,
`test_subtitle_content_index_is_partial_over_the_caption_kinds`,
`test_transcript_base_tables_store_no_derived_values`,
`test_pending_subtitles_view_carries_the_newest_attempt_evidence`,
`test_attempt_check_matrix_accepts_legal_evidence` (5 cases),
`test_attempt_check_matrix_rejects_illegal_evidence` (8 cases),
`test_one_outcome_per_attempted_part_per_run`,
`test_transcript_segment_record_mirrors_the_segment_invariant`,
`test_transcript_write_result_validates_the_locked_shape`,
`test_acquisition_run_record_validates_the_locked_shape`.
Extended: the package-resource test (both scripts + package-data), `BASE_TABLES`/`VIEWS`,
`EXPECTED_TABLE_COLUMNS` / `_FOREIGN_KEYS` / `_UNIQUE_CONSTRAINTS` / `_PRIMARY_KEY_INDEXES` /
`_CHECK_ENUMERATIONS` / `_ENUM_COLUMNS` / new `_INDEXES`, `_PARTIAL_INDEX_CLAUSES`,
`_VIEW_COLUMNS`, `_LITERAL_SETS`, the constraint-coverage violation list, and the view loop
of `test_schema_inspection_matches_the_declared_contract`.

Red evidence (three deliberate mutations, each reverted immediately; focused suite run each
time):

1. Remove the partial index's `WHERE` clause → `2 failed, 34 passed`
   (`test_schema_inspection_matches_the_declared_contract`,
   `test_subtitle_content_index_is_partial_over_the_caption_kinds`).
2. Execute the transcript script unconditionally → `1 failed, 35 passed`, and the failure is
   exactly the half-apply the split prevents:
   `sqlite3.OperationalError: no such column: language` from `CREATE UNIQUE INDEX ... ON
   transcripts(..., language, ...)` against the legacy table.
3. Drop the `no-subtitle` arm of the attempt CHECK matrix → `5 failed, 31 passed`
   (`test_attempt_check_matrix_accepts_legal_evidence[no-subtitle-*]`,
   `test_one_outcome_per_attempted_part_per_run`, the inspection test, the view test).

After revert: `36 passed`, `git status` clean, `git diff --check` clean.

## Files changed

- `bilibili-asr-archive/src/bili_asr/storage/schema.sql` (transcript block removed, pointer comment added)
- `bilibili-asr-archive/src/bili_asr/storage/schema-transcripts.sql` (new, 141 lines)
- `bilibili-asr-archive/src/bili_asr/storage/database.py` (+85/-9)
- `bilibili-asr-archive/src/bili_asr/storage/models.py` (+145)
- `bilibili-asr-archive/src/bili_asr/storage/__init__.py` (+26)
- `bilibili-asr-archive/pyproject.toml` (package-data)
- `bilibili-asr-archive/tests/test_storage_schema.py` (+920/-…)

## Self-review notes

- **Spec fidelity is mechanical, not eyeballed.** I extracted every ```` ```sql ```` block
  from spec §2.4/§2.5, normalised whitespace statement-by-statement, and asserted each one
  appears in `schema-transcripts.sql`: 6/6 spec statements covered, the only extra statement
  being the spec-mandated verbatim move of `transcript_segments` (also compared against
  `HEAD:schema.sql`). No statement was reworded or added.
- **`pyproject.toml` is an intentional addition** beyond the brief's file list: without
  `schema-transcripts.sql` in `package-data` the new resource would be missing from an
  installed wheel. The resource test now pins both entries.
- **One Python-only invariant beyond the DDL**: `AcquisitionRunRecord` rejects a terminal
  `outcome` without `finished_at` ("a terminal run outcome requires finished_at"). The locked
  DDL was kept byte-exact (no extra table CHECK was added), so the coherence rule lives in
  the DTO. Flagged for the reviewer rather than silently omitted.
- **`TranscriptSegmentRecord.__post_init__` deliberately uses a new private
  `_caption_text`** that preserves control characters instead of the shipped `_text`. A
  caption row is stored verbatim (multi-line text survives; only "non-empty after strip" is
  required), and the invariant matches the gateway's `SubtitleSegment` exactly so the service
  maps field-for-field without a second, stricter rule at the storage boundary.
- **`SchemaContractError` subclasses `RuntimeError`** — a bounded message with no path
  interpolation; the CLI plan formats `<command>: … (delete {archive_root}/archive.db …)`
  itself. Nothing else in the codebase catches it today.
- **Small deliberate behavioural coverage** of schema artifacts whose later consumers are
  Tasks 2–3 (the CHECK matrix, `PRIMARY KEY (run_id, video_part_id)`, the partial index, and
  a four-part smoke of the view). Kept at SQL level and deliberately short: the repository
  level evidence (idempotency, versions, rollback, enumeration order) stays with Tasks 2–3.
- **Handoff, not a residual**: `docs/metadata-storage.md` still describes the bootstrap as
  "the checked-in schema (`src/bili_asr/storage/schema.sql`)" and has no rebuild wording.
  Its update is explicitly owned by plan `20260911-subtitle-cli-cutover` (Files:
  `docs/metadata-storage.md`, `README.md`), so I left it untouched rather than editing
  another plan's deliverable. The plan's drift check asked for exactly this confirmation.
- **Naming**: every public name is spec-locked. Before adding anything I ran the
  `naming-analyzer` check over the new names; the only new names are private helpers in the
  shipped `_`-prefix style (`_transcripts_columns`, `_schema_object_names`,
  `_accepts_transcript_script`, `_has_subtitle_schema`, `_boolean`, `_caption_text`,
  `_content_sha256`, `_ALLOWED_SELECTOR_KINDS`, `_ALLOWED_TRANSCRIPT_WRITE_OUTCOMES`,
  `_SHA256_HEX_PATTERN`) — no abbreviation, no ambiguity, and each mirrors an existing
  sibling (`_choice`, `_error_code`, `_SCHEMA_RESOURCE`).
- **STOP conditions**: none triggered. The single-transaction transcript write is not in this
  task; the process-record shape records bounded evidence without touching `ingestion_runs`;
  no raw payload is stored; the pre-iteration database stays usable for the metadata
  commands (proved by test); all pre-existing metadata tests are green.
- **Scope discipline**: no sidecar, docs, harness, plan, snapshot or status file was written;
  the only file outside the worktree that I wrote is this report.
