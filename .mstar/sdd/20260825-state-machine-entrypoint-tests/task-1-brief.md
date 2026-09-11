### Task 1: Cover command-level state transitions

- [ ] `meta_ok -> needs_audio -> audio_ok -> archived` with fake audio stream + stubbed ASR.
- [ ] `meta_ok -> subtitle_done -> archived`; ASR not called.
- [ ] Risk exhaustion → exit 2, last stable manifest `status` preserved, resumable summary.
- [ ] Missing optional ASR → exit 1, record non-archived.
- [ ] Reruns idempotent; no duplicate JSONL lines; unrelated rows untouched.

Run: `python -m pytest bilibili-asr-archive/tests/test_cli_asr.py bilibili-asr-archive/tests/test_cli_pilot.py bilibili-asr-archive/tests/test_manifest.py -q` exits 0.

