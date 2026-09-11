### Task 3: Validate schema and repository against the contract

**Files:**
- Modify: `bilibili-asr-archive/tests/test_storage_schema.py`
- Modify: `bilibili-asr-archive/tests/test_metadata_repository.py`
- Create: `bilibili-asr-archive/tests/fixtures/metadata_records.py`

**Interfaces:**
- Consumes: repository and schema from Tasks 1–2.
- Produces: deterministic contract evidence for the gateway and CLI plans.

- [ ] Add a schema inspection test that checks required tables, views, foreign
  keys with `ON DELETE RESTRICT`, unique constraints, status checks, and the
  absence of `work_id` as a base-table column. Verify the three views compute
  derived values correctly.
- [ ] Add a repository E2E test that inserts one user, one single-part video,
  one multipart video, two runs, page records, and cursor transitions using the
  explicit transaction ordering (user → video → parts → discoveries → cursor →
  page outcome).
- [ ] Add FK constraint tests: attempt to insert a video without its user,
  attempt to insert a part without its video, and verify `ON DELETE RESTRICT`
  prevents orphaning.
- [ ] Add a no-secret persistence test that attempts forbidden fields and proves
  the repository accepts only bounded scalar error codes.
- [ ] Keep all tests offline and independent of `bilibili_api`.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_storage_schema.py tests/test_metadata_repository.py -v`
