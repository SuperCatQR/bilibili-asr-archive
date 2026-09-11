### Task 2: Offline subtitle E2E over the fake seam

**Files:**
- Create: `bilibili-asr-archive/tests/test_subtitle_e2e.py`
- Modify: `bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py` — scripting only, **plus**
  the deferred Task-1 finding F3: add the two subtitle methods to the shared `FakeGateway`
  protocol double (absent today) so this plan can script subtitle calls through it
- Modify: `bilibili-asr-archive/tests/test_subtitle_cli.py`

**Interfaces:**
- Consumes: the Task-1 CLI/service, the storage plan's repository, the fake seam.
- Produces: deterministic E2E evidence for the iteration acceptance gate.

- [ ] Script a part with a CC track and a part with only an AI track; assert normalized
      `transcripts`/`transcript_segments` rows, language, `source_kind`, version 1, the content
      hash, and the acquisition-run/attempt evidence.
- [ ] Re-run the same bounded harvest and assert `unchanged`, no new version, and no duplicate
      segments; then change the scripted body and assert version 2 with version 1 and its
      segments still readable.
- [ ] Script a part with no subtitles and a part whose body fetch fails; assert bounded evidence
      rows (`no-subtitle`, and `failed` with the mapped code), that the run does not claim
      success for them, and that the printed counts make the partial failure visible while the
      exit code stays `0`.
- [ ] Assert honesty and progress: a part left `no-subtitle` in one run can store a transcript
      in a later run once the caption is available; with both a never-attempted and a previously
      attempted part in the candidate set, the never-attempted part is attempted first.
- [ ] Assert the printed run summary: all four outcome counts including zeros, the run id,
      credential presence, and the remaining count of parts without a transcript; assert the
      `attempted=0` empty-selection run exits `0`.
- [ ] Assert the probe surface: the `probe`/`track`/`tracks=0` line shapes, the per-part
      `failed <code>` line, the `probe-subs: probed=… with_tracks=… without_tracks=… failed=…`
      summary, and that a probe leaves no database, no run row, and no file behind.
- [ ] Assert no legacy sidecar file appears in the temporary archive root, that `probe-subs`
      leaves no new file (including no writer lock) and does not create a missing database, and
      run no-leak scans over output and all persisted rows (credential + signed-URL sentinels).

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_subtitle_e2e.py -v`

**PM-authorized follow-up (2026-09-11, from the Task-1 L2 review M3):** the env-sourced credential path for
these commands lost its direct assertion when the legacy tests were replaced (only the shared helper in
`test_metadata_cli.py` covers it). Add the assertion here — an E2E case where `BILI_SESSDATA` is present in the
environment (and one where it is absent) must exercise the composition of `credential_present` into the run row
and the printed `sessdata: <present|absent>` line.

