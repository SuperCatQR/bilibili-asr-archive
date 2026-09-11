### Task 2: Adapter subtitle acquisition in the locked call shape

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py`
- Test: `bilibili-asr-archive/tests/test_bilibili_api_gateway.py`

**Interfaces:**
- Consumes: the Task-1 DTOs/protocol and the pin's player endpoint description.
- Produces: normalized `SubtitleTrack` tuples (possibly empty) and non-empty
  `SubtitleSegment` tuples with the bounded taxonomy and no URL leakage.

- [ ] Implement `get_subtitle_tracks`: `Api` built from the description's
      `url`/`method`/`wbi` with `dm=False`, `verify=False`, credential attached, params exactly
      `{bvid, cid, isGaiaAvoided: False, web_location: 1315873}`; normalize `lan`/`lan_doc`/AI
      marker into DTOs; return an empty tuple when upstream lists nothing.
- [ ] Implement `fetch_subtitle_segments`: re-list, resolve the track by `language` + `is_ai`
      (`track_id` breaks a tie, ambiguity is `shape_error`, absence is `not_found`), normalize
      protocol-relative URLs to `https:` internally, fetch with
      `Api(url=..., method="GET", wbi=False, dm=False, verify=False,
      credential=Credential())` called as `await api.request(raw=True)`, and convert
      `from`/`to`/`content` with `floor(seconds*1000)`.
- [ ] Implement the bounded re-list: at most one extra listing + fetch pair on an
      expiry/transport-class body-fetch failure; never on `rate_limited`; no loop.
- [ ] Extend the not-found mapping for the two subtitle methods with `{-101}` while leaving the
      metadata path's mapping untouched.
- [ ] Preserve the taxonomy mapping for every failure path (HTTP statuses, malformed payloads,
      rate control) and keep the endpoint parity tests green: the seam's description must equal
      the installed pin's field for field, and the adapter's only overrides must be `dm`/`verify`.
- [ ] Tests: normalization (AI vs CC, labels, primary-subtag rejection), conversion, every
      drop trigger of the spec's section 3 boundary (inverted/zero-length interval, negative
      start, empty-after-strip `content`) with the surviving rows asserted, every `shape_error`
      trigger (non-numeric/non-finite `from`/`to`, absent/`null`/non-string `content`, `body`
      absent/`null`/not an array, an entry not readable as a segment), each taxonomy row, the
      recorded call shape, the single re-list call list, the `-101` divergence between subtitle
      and metadata paths, the empty-tuple vs `not_found` distinction (an all-degenerate document
      is `not_found`, never `shape_error`), and no-leak scans (URL/cookie sentinels absent from
      DTOs, messages, rows).

**PM-authorized test/contract updates (2026-09-11, from the Task-1 L2 review).** These are
deliberate, recorded changes — not silent relaxations:

- [ ] `FORBIDDEN_SEAM_METHOD_TOKENS`: remove **only** the subtitle-acquisition family
  (`subtitle`, `player`, `download`) — this plan legitimately issues the player/subtitle calls.
  Keep `playback`, `playurl`, `play_url`, `danmaku`, `audio`, `asr`, `export` forbidden (the
  iteration boundary), and strengthen the test so the authorized subtitle/player attributes are
  **positively asserted** to be present, not merely un-banned.
- [ ] Extend the seam's documented-call allow-list (`DOCUMENTED_METADATA_CALLS`) with the new
  routes (`player.track_list`, `subtitle.body`) so
  `assert_only_documented_metadata_calls` accepts exactly the new surface; keep it an exact set.
- [ ] Add the protocol-relative subtitle-URL form to the no-leak sentinel set (`NO_LEAK_MARKERS`),
  so an un-normalized URL leak cannot slip past the scanner.
- [ ] Strengthen `test_gateway_protocol_surface_is_locked` to an exact method-set assertion
  (today a seventh protocol method would pass) and correct its over-claiming docstring.
- [ ] Re-export `SubtitleTrack` / `SubtitleSegment` from `sources/__init__.py` (the models
  re-export surface), leaving the adapter deliberately un-re-exported as before.
- [ ] Pin the locked no-track signalling with executable assertions: empty inventory → empty
  tuple from `get_subtitle_tracks`; all-degenerate document → `GatewayNotFound` (never
  `shape_error`, never an empty success) from `fetch_subtitle_segments`.
- [ ] Trim `language`/`label` (and segment `text`) in the adapter to the printable form the spec
  promises, matching the metadata path's field-trimming precedent.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_bilibili_api_gateway.py -v`

