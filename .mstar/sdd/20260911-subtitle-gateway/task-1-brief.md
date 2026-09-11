### Task 1: Subtitle DTOs, protocol methods, and seam extension

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/sources/models.py`
- Modify: `bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py`
- Test: `bilibili-asr-archive/tests/test_bilibili_api_gateway.py`

**Interfaces:**
- Consumes: existing DTO/validation style and the fake seam's recorder.
- Produces: frozen `SubtitleTrack` / `SubtitleSegment` with `__post_init__` validation and two
  protocol methods; seam scripting for the player endpoint and subtitle bodies.

- [ ] Add `SubtitleTrack(language, label, is_ai, track_id)` with validation (language/label
      non-empty after trim; primary subtag non-empty; `track_id` a non-empty string or `None`)
      and `SubtitleSegment(start_ms, end_ms, text)` with validation (`start_ms >= 0`,
      `end_ms > start_ms`, text non-empty after trim); keep `work_id` and URLs out of both.
- [ ] Add the two protocol methods; keep the existing four methods' signatures untouched.
- [ ] Extend the seam with `FAKE_PLAYER_ENDPOINT` (a literal mirror of
      `video.API["info"]["get_player_info"]`, `dm: True` included), scripted `subtitles[]`
      payloads, scripted subtitle bodies (absolute and protocol-relative URLs), and a recorded
      call list that captures the flags and parameter set of every issued call; preserve every
      existing exact call-list assertion.
- [ ] Test DTO validation and the seam's new scripting without importing the real package.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_bilibili_api_gateway.py -v`

