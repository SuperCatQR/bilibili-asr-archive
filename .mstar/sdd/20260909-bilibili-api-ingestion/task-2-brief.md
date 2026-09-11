### Task 2: Implement resumable normalized metadata ingestion

**Files:**
- Create: `bilibili-asr-archive/src/bili_asr/services/__init__.py`
- Create: `bilibili-asr-archive/src/bili_asr/services/metadata_ingest.py`
- Modify: `bilibili-asr-archive/src/bili_asr/storage/database.py`
- Test: `bilibili-asr-archive/tests/test_metadata_ingest.py`

**Interfaces:**
- Consumes: the gateway protocol and Plan 1 repository.
- Produces: run result with outcome, next cursor, and derived counts; all
  persisted data is normalized repository data.

- [ ] Start an `ingestion_run` with requested bounds and package version.
- [ ] For each page, fetch summaries, fetch parts, and persist user/video/part
  records plus discovery relationships in one transaction using the explicit
  ordering from Plan 1: (1) upsert user, (2) upsert video, (3) upsert parts,
  (4) insert discoveries, (5) update cursor on success only, (6) record page
  outcome, (7) commit atomically.
- [ ] Make repeated pages idempotent for entity and discovery keys while keeping
  separate run/page evidence for each collection run. Entity upserts use
  `INSERT ... ON CONFLICT DO UPDATE` on primary/unique keys.
- [ ] Persist `complete`, `limited`, `risk_interrupted`, or `failed` outcomes;
  never claim completion when an explicit page limit stops collection.
- [ ] Preserve the previous cursor on gateway failure: rollback the entire page
  transaction and store only the scalar error code in a separate page/run
  outcome transaction.
- [ ] Test one single-part video, one multipart video, duplicate page results,
  empty page completion, explicit page limit, transaction rollback on failure,
  and cursor preservation/resume behavior.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_metadata_ingest.py -v`

