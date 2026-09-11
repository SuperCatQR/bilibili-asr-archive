### Task 1: Execute a bounded mixed pilot

- [ ] Fresh `meta_ok` manifest: deterministic selection preferring short items, reserving both branches when possible.
- [ ] Selected items: probe/harvest subtitles first; subtitle hits → `subtitle_done` → archive from subtitle data without ASR.
- [ ] Selected no-subtitle items: download audio, invoke local ASR, write transcript artifacts, persist `archived` with `audio_path` + archive paths.
- [ ] Per-item failures, branch counts, final terminal states persisted and reported; unavailable branch coverage → nonzero exit identifying what is missing.
- [ ] Multi-part selected bvid: every pagelist `work_id` processed or reported failed (no page-1-only success).
- [ ] `BILI_SESSDATA`/`--sessdata` only as a cookie **value** (not a filesystem path); never echoed or persisted.

Run: `python -m pytest bilibili-asr-archive/tests/test_pilot_select.py bilibili-asr-archive/tests/test_cli_pilot.py -q` — all pass with fake transport and stubbed ASR.

