### Task 2: Implement repository transactions and idempotent upserts

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/storage/database.py`
- Create: `bilibili-asr-archive/src/bili_asr/storage/models.py`
- Test: `bilibili-asr-archive/tests/test_metadata_repository.py`

**Interfaces:**
- Consumes: internal models `UserRecord`, `VideoRecord`, `VideoPartRecord`,
  `IngestionRunRecord`, `IngestionPageRecord`, and `CursorRecord`.
- Produces: `MetadataRepository.upsert_user`, `upsert_video`, `upsert_part`,
  `start_run`, `finish_run`, `record_page`, `record_discovery`,
  `read_cursor`, `write_cursor`, `list_pending_parts`, and `run_stats`.

- [ ] Add dataclasses with explicit fields and validation for the schema types;
  keep `work_id` as a computed property rather than a persisted field.
- [ ] Implement one-page transaction support using the explicit ordering from the
  primary spec: (1) upsert user, (2) upsert video, (3) upsert parts, (4) insert
  discoveries, (5) update cursor, (6) record page outcome, (7) commit. This order
  guarantees FK parents exist before FK children are inserted.
- [ ] Make repeated ingestion of the same page idempotent for entities and
  discovery relationships while allowing a new run to retain its own page
  record.
- [ ] Keep failure handling bounded: a failed page records a scalar error code,
  rolls back the entire transaction, leaves the previous cursor unchanged, and
  marks the run/page outcome in a separate transaction.
- [ ] Test single-part and multipart videos, repeated pages, cursor resume,
  failed-page rollback, missing foreign keys, FK delete restriction, and
  pending-part queries.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_metadata_repository.py -v`

