### Task 1: Subtitle ingest service and CLI commands

**Files:**
- Create: `bilibili-asr-archive/src/bili_asr/services/subtitle_ingest.py`
- Modify: `bilibili-asr-archive/src/bili_asr/cli.py`
- Test: `bilibili-asr-archive/tests/test_subtitle_cli.py`

**Interfaces:**
- Consumes: `TranscriptRepository`, `BilibiliGateway`, `MetadataIngestor`'s synchronous
  conventions, the shipped CLI helpers.
- Produces: `SubtitleIngestor` (enumeration + bounded per-part acquisition + outcome mapping +
  run lifecycle) and the two command handlers.

- [ ] Implement the service: select candidates (`list_selected_parts` for `--bvid`;
      `list_pending_subtitle_parts` otherwise), map `video_parts.cid` → gateway calls, select a
      track with the family/CC-before-AI rule (or the exact `--language` order), fetch segments,
      convert `SubtitleSegment` → `TranscriptSegmentRecord`, and write the transcript + attempt
      evidence through `record_acquired_transcript` / `record_subtitle_attempt` — one
      transaction per part; open and finish exactly one `acquisition_runs` row
      (`kind='subtitle'`, selector, bound, credential presence, derived outcome); write nothing
      at all on `probe`.
- [ ] Map outcomes exactly: empty listing or `GatewayNotFound` → `no-subtitle` (with
      `not_found` recorded when upstream signalled it); `GatewayRateLimited` /
      `GatewayTransportError` / `GatewayResponseError` / `GatewayShapeError` → `failed` with
      that code; a write with unchanged content → `unchanged`; else `stored`.
- [ ] Wire `probe-subs`: read-only, exactly one of `--bvid` / `--limit-parts`, missing database
      → the shipped read-command line and exit `1`, unknown `--bvid` (zero rows) → exit `1`,
      `bvid:pN` via `parse_work_id`, zero-track parts printed with their explicit marker, a
      part whose listing failed printed as `probe <work_id> failed <error_code>` (counted in
      `failed=`), no run/attempt/transcript write, and exit `2` only when every selected part
      failed or an internal error aborted the probe; remove `probe-subs` from
      `_ARCHIVE_WRITER_COMMANDS`.
- [ ] Wire `harvest-subs`: `--limit-parts` required unless a single `bvid:pN` is named;
      `--bvid` selects explicitly (already-stored parts included); a missing database → the
      shipped `<command>: no archive database at <root>; run fetch-meta to create it` line and
      exit `1`; `--language` parsed with empty entries rejected as usage errors; both commands
      call `require_subtitle_schema` after opening the database and print the fixed rebuild line
      with exit `1` on `SchemaContractError`.
- [ ] Print the locked output: `sessdata: <present|absent>`, one `probe`/`harvest` line per
      selected or attempted part in order (including `probe <work_id> tracks=0` with its
      explicit marker and `probe <work_id> failed <error_code>`), and the summary lines
      (`probe-subs: probed=… with_tracks=… without_tracks=… failed=…`,
      `harvest-subs: run_id=… attempted=… stored=… unchanged=… no-subtitle=… failed=… remaining_without_transcript=…`).
- [ ] Remove the legacy manifest reads/writes from these two commands only; leave every
      other command's behaviour untouched and disclose the semantic replacement in the report.
- [ ] Tests: parser/usage (bound required, exactly one probe selector, missing DB → exit `1`,
      unknown `--bvid` → exit `1`, empty `--language` entry → exit `1`, usage errors never exit
      `2`), preference selection (CC-before-AI property table, family ranking, exact
      `--language` match, unmatched valid preference → `no-subtitle`), explicit `--bvid`
      selection including an already-stored part, enumeration progress across two runs, summary
      content and line shapes, outcome mapping, exit codes, and no-old-file assertions.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_subtitle_cli.py -v`

