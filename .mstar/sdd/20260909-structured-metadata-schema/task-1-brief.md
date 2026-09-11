### Task 1: Implement the normalized schema bootstrap

**Files:**
- Create: `bilibili-asr-archive/src/bili_asr/storage/__init__.py`
- Create: `bilibili-asr-archive/src/bili_asr/storage/schema.sql`
- Create: `bilibili-asr-archive/src/bili_asr/storage/database.py`
- Test: `bilibili-asr-archive/tests/test_storage_schema.py`

**Interfaces:**
- Consumes: archive root path and schema SQL.
- Produces: `open_database(path)`, foreign-key-enabled connection, schema tables,
  constraints, and views.

- [ ] Define tables `bilibili_users`, `videos`, `video_parts`,
  `ingestion_runs`, `ingestion_cursors`, `ingestion_pages`,
  `ingestion_discoveries`, plus the reserved audio/transcript tables from the
  primary spec with explicit FK constraints using `ON DELETE RESTRICT`.
- [ ] Define primary keys, candidate-key unique constraints, foreign keys,
  status checks, non-negative checks, and the three required views.
- [ ] Implement duration conversion as `floor(seconds * 1000)` and page-index
  normalization as `page - 1` per the spec's normalization rules.
- [ ] Configure SQLite with foreign keys enabled and a transaction-safe default;
  do not add an ORM or a second database library.
- [ ] Test a fresh database, foreign-key rejection, duplicate-key rejection,
  derived work ID view, the absence of duplicate aggregate columns, and the
  explicit transaction ordering that prevents FK violations.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_storage_schema.py -v`

