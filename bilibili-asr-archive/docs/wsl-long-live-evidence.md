# Long-live WSL evidence (redacted)

Completed live Windows WSL acceptance on `DESKTOP-HHFROLO` / WSL2.

## Environment

- Host / WSL distro: `DESKTOP-HHFROLO` / WSL2 (`x86_64`)
- Product checkout branch: `plan/20260826-full-corpus-scheduler`
- Archive root (WSL path, not a Windows mount): `/root/bili-asr-live-test`
- Cookie supplied: `BILI_SESSDATA` in-shell only (value omitted)
- `--max-audio-gb`: 10
- `--allow-long-live`: yes
- `work_id` / `duration_s`: `BV1S8hA6MEvy:p0` / `7902`

## Disk

- Before schedule: audio directory absent; measured as 0 bytes before run
- After schedule (post-reclaim): audio directory absent; 0 bytes retained

## Scheduler summary (redacted)

- conservative `duration_s` / `estimated_bytes` / `would_exceed`: `7902` / `63216000` / `false`
- measured `peak audio/` bytes: `0`
- measured `audio/ after` bytes: `0`
- `batch=` state: `complete`
- `enumeration:` `limited (next_page 2, observed_total 1738)`
- exit code: `0`

## Manifest / reclaim

- Final row status: `archived`
- Audio file for this stem present after success? `no`
- Audio file retained after failure? `not applicable; run succeeded`

## Inspection

```text
archived: 1
meta_ok: 35
runs: 2
latest run: schedule, exit 0
latest cursor: limited (next_page 2, observed_total 1738)
latest coverage: archived: 1, meta_ok: 35
```

## No-secret scan

- [x] Cookie value absent from stdout, stderr, and archive json/jsonl/md/txt/srt
- [x] No signed stream URLs
- [x] No stack traces
- [x] `BILI_SESSDATA` unset after the run

## Notes

- The run used a real long-duration metadata row and the explicit opt-in scheduler path. No model download was required because the subtitle/archive path succeeded; no persistent audio remained after archive.
- `BILI_SESSDATA` was never written to this evidence file.
