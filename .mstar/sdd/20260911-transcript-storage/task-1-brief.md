### Task 1: Schema contract, bootstrap split, and structural guard

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/storage/schema.sql`
- Create: `bilibili-asr-archive/src/bili_asr/storage/schema-transcripts.sql`
- Modify: `bilibili-asr-archive/src/bili_asr/storage/database.py`
- Modify: `bilibili-asr-archive/src/bili_asr/storage/models.py`
- Test: `bilibili-asr-archive/tests/test_storage_schema.py`

**Interfaces:**
- Consumes: the reserved tables, the shipped `resources.files` loader, and the spec's DDL.
- Produces: the locked columns, widened uniqueness, partial content index,
  `transcript_segments`, `acquisition_runs`, `acquisition_attempts`,
  `ix_acquisition_attempts_part_time`, `v_pending_subtitles`, the conditional bootstrap, and
  `require_subtitle_schema` / `SchemaContractError`.

- [ ] Move the `transcripts` / `transcript_segments` block out of `schema.sql` into
      `schema-transcripts.sql` and add the locked DDL (language, content hash, widened unique
      key, partial content index, the run/attempt pair with their CHECK matrices, the attempt
      index, the pending view) exactly as specified.
- [ ] Make `initialize_schema` execute the transcript script only when `transcripts` is absent
      or already current, so a pre-iteration database is left untouched instead of
      half-applied; keep `PRAGMA foreign_keys = ON` enforcement unchanged.
- [ ] Add `require_subtitle_schema(connection)` as a structural capability check
      (`pragma_table_info('transcripts')` plus the new tables and view) raising
      `SchemaContractError`, and export it.
- [ ] Add the storage vocabulary (`AcquisitionKind`, `AcquisitionOutcome`, `AttemptOutcome`,
      `SourceKind` literals + `ALLOWED_*` frozensets) and the `TranscriptSegmentRecord`,
      `TranscriptWriteResult`, `AcquisitionRunRecord` dataclasses with validation.
- [ ] Extend the schema inspection tests: exact column manifests for `transcripts`,
      `acquisition_runs`, `acquisition_attempts`; FK pairs; unique/PK/index set including the
      partial index's `WHERE` clause; CHECK enumerations; the pending view's columns; and a
      "no derived duplicates" check over the new tables.
- [ ] Bootstrap matrix tests: fresh database (full contract), current database (idempotent
      re-open), pre-iteration database (metadata tables usable, transcript objects absent,
      `require_subtitle_schema` raising). No migration path is introduced.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_storage_schema.py -v`

