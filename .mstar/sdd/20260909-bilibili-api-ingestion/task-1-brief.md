### Task 1: Add the pinned dependency and typed gateway boundary

**Files:**
- Modify: `bilibili-asr-archive/pyproject.toml`
- Create: `bilibili-asr-archive/src/bili_asr/sources/__init__.py`
- Create: `bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py`
- Create: `bilibili-asr-archive/src/bili_asr/sources/models.py`
- Test: `bilibili-asr-archive/tests/test_bilibili_api_gateway.py`

**Interfaces:**
- Consumes: package objects and optional credential configuration.
- Produces: `UserVideoPage`, `VideoSummary`, `VideoPart`, `BilibiliGateway`,
  and bounded gateway exception classes.

- [ ] Pin `bilibili-api-python==17.4.2` and generate/update `uv.lock` without
  changing unrelated runtime dependencies.
- [ ] Implement credential construction without exposing SESSDATA to DTOs,
  logs, exception messages, or persistent records.
- [ ] Implement `get_package_version()` returning the pinned package version string
  for run metadata.
- [ ] Implement `get_user_video_page` using the documented `User.get_videos`
  page parameters and normalize required scalar fields. Return `observed_total`
  from the API response when present. Validate that all returned video `mid`
  values match the requested `mid`; reject with `GatewayShapeError` on mismatch.
- [ ] Implement `get_video_parts` using `Video.get_pages`; convert one-based
  `page` to zero-based `page_index` using `page - 1`, and convert `duration`
  seconds to `duration_ms` using `floor(seconds * 1000)`. Use `get_info` only
  when the video summary lacks `aid`; do not call it speculatively.
- [ ] Validate non-empty BVID/title, non-negative page index, positive CID and
  duration before returning DTOs.
- [ ] Test DTO normalization, duration/page-index conversion, owner-MID validation,
  malformed responses, bounded error mapping, and import-boundary inspection with
  a fake package seam.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_bilibili_api_gateway.py -v`

