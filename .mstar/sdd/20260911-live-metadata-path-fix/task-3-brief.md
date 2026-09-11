### Task 3: Issue the user-video page call in a risk-control-safe shape

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py`
- Modify: `bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py`
- Test: `bilibili-asr-archive/tests/test_bilibili_api_gateway.py`
- Modify: `.mstar/iterations/iter-2026-09-bilibili-api-sqlite/specs/bilibili-api-gateway.md`
  (PM-owned annotation; the task records the superseded transport clause — implementers
  must not edit the spec themselves)

**Interfaces:**
- Consumes: the pinned package's WBI-signed `Api`, the existing normalization helpers.
- Produces: an unchanged `UserVideoPage` result produced by a call shape that passes
  upstream risk control (`dm` disabled, `w_webid` present) with bounded error mapping
  preserved.

- [ ] Replace the `User.get_videos(...)` delegate with the WBI-signed `Api` call shape
  (`dm=False`; `w_webid` = the package's non-empty `access_id` when available, else `""`),
  forwarding the same parameter set and feeding the response into the existing
  normalization/validation path unchanged.
- [ ] Keep the bounded taxonomy mapping identical (412/429 and `-412`/`-352`/`-799` →
  `rate_limited`; `-404`/`-62002` → `not_found`; shape problems → `shape_error`; other
  upstream failures → `response_error`/`transport_error`), including the WBI-retry case.
- [ ] Extend the fake seam to assert the call shape: `dm` is disabled, `w_webid` is always
  present (empty allowed), and a non-empty `access_id` is preferred when the seam provides
  one; assert no `dm`-family parameters are sent.
- [ ] Keep DTO field ownership/validation and `observed_total` semantics unchanged; the
  existing Task-1/Task-2/Task-3 test suites must pass unmodified except for explicitly
  disclosed fixtures.
- [ ] PM annotates the pinned spec's "Required upstream calls #1" with the superseded
  transport clause and the reason (discovered 2026-09-11).

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_bilibili_api_gateway.py tests/test_metadata_ingest.py -v`

