### Task 2: Add offline metadata E2E verification

**Files:**
- Create: `bilibili-asr-archive/tests/test_metadata_e2e.py`
- Modify: `bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py`
- Modify: `bilibili-asr-archive/tests/test_metadata_ingest.py`

**Interfaces:**
- Consumes: CLI, ingestor, repository, and fake gateway.
- Produces: deterministic end-to-end evidence for the iteration acceptance gate.

- [ ] Script a single-part video and a multipart video returned by the fake gateway.
- [ ] Verify normalized user/video/part/discovery/run/page/cursor rows and the
  computed `work_id` view values.
- [ ] Re-run the same page and assert no duplicate entity or discovery rows.
- [ ] Script a failed page, assert cursor preservation and bounded error storage,
  then resume successfully from the prior cursor.
- [ ] Assert no old JSONL/cursor/ledger files are created in the temporary root.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_metadata_e2e.py -v`

