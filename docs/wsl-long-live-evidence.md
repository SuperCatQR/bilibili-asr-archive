# Long-live WSL evidence (redacted historical record)

> This file records one completed acceptance run from an earlier checkout. It
> is evidence of that run, not a current branch, dependency, coverage, or
> performance claim. Use [wsl-long-live.md](wsl-long-live.md) for the current
> procedure and rerun it before treating the numbers as current.

Completed live Windows WSL acceptance on `DESKTOP-HHFROLO` / WSL2.

Live operation provenance is recorded by the checkout branch and verified feature tip in the QA report; the live campaign itself ran before this evidence document was committed. The documented product changes were already present at live execution; later commits only record redacted evidence.

## Provenance

- Live checkout branch: historical branch recorded by the original run
- Live product fixes present before campaign: `01835b6` (fetch-meta SESSDATA propagation), `b321d84` (archive SESSDATA propagation), `3b054f2` (buvid browser context)
- Live campaign provenance: the WSL operator ran the product checkout at the branch containing `01835b6`, `b321d84`, and `3b054f2`; evidence-only commits were added afterward.

- Host / WSL distro: `DESKTOP-HHFROLO` / WSL2 (`x86_64`)
- Product checkout branch: historical branch recorded by the original run
- Archive root (WSL path, not a Windows mount): `/root/bili-asr-live-test`
- Cookie supplied: `BILI_SESSDATA` in-shell only (value omitted)
- `--max-audio-gb`: 10
- `--allow-long-live`: yes
- `work_id` / `duration_s`: `BV1S8hA6MEvy:p0` / `7902`

## Disk

Commands executed:

```text
du -sb "/root/bili-asr-live-audio/audio" || true
55845684	/root/bili-asr-live-audio/audio
```

- Before schedule: `du -sb "/root/bili-asr-live-audio/audio" || true` reported no directory; measured as 0 bytes before the audio preparation run
- After the successful subtitle-only schedule run: `du -sb "/root/bili-asr-live-audio/audio" || true` reported no directory; 0 bytes retained
- Audio-path preparation run: the real long-live row was downloaded to `/root/bili-asr-live-audio/audio/BV1RGN462EBs.p0.m4a`; the measured audio directory size was `55845684` bytes before the ASR/archive attempt

## Scheduler summary (redacted)

- conservative `duration_s` / `estimated_bytes` / `would_exceed`: `7902` / `63216000` / `false`
- measured `peak audio/` bytes: `55845684` (audio-path preparation run)
- measured `audio/ after`: `0` (successful subtitle-only archive run)
- audio-cap guard check: with existing audio usage `55845684` and `--max-audio-gb 0.01`, scheduler reported `would_exceed=true` and skipped with `audio_budget` (exit 1), preserving the audio row/file
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
live product tip: fixes `01835b6`, `b321d84`, `3b054f2`; evidence was committed afterward
```

## No-secret scan

- [x] Cookie value absent from stdout, stderr, and archive json/jsonl/md/txt/srt
- [x] No signed stream URLs
- [x] No stack traces
- [x] `BILI_SESSDATA` unset after the run

## Notes

- The run used a real long-duration metadata row and the explicit opt-in scheduler path. No model download was required because the subtitle/archive path succeeded; no persistent audio remained after archive.
- `BILI_SESSDATA` was never written to this evidence file.
