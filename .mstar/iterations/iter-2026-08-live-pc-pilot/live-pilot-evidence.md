---
iteration_id: iter-2026-08-live-pc-pilot
recorded_at: 2026-08-26
host: DESKTOP-HHFROLO (Windows WSL2)
archive_root: /root/pilot-archive-20260826
source_revision: 4e00fb3
credential_policy: transient BILI_SESSDATA only; scanned pilot records clean
---

# Live PC Pilot Evidence

## Scope

This is a bounded live validation on the Windows WSL compute PC. It is not a full-corpus crawl. The pilot archive root is isolated from the existing checkout and the source was deployed from the integration branch revision cited above.

## Environment

- WSL Python: 3.12.3
- ffmpeg: available at `/usr/bin/ffmpeg`
- Runtime: FunASR 1.4.3, CPU-only PyTorch 2.5.1+cpu and torchaudio 2.5.1+cpu
- WSL free space before pilot: 750 GiB
- Source test suite after pilot-related fixes: `298 passed in 5.02s`

## Live Evidence

1. The initial one-page probe completed with 37 page-aware rows and cursor `limited`, `next_page=2`, `observed_total=1737`.
2. An initial 3-row subtitle probe yielded two subtitle rows and one `needs_audio` row. The audio row downloaded to 55,845,684 bytes and became `audio_ok`; it was retained after an intentional dependency-unavailable retry, then successfully transcribed and reclaimed once CPU SenseVoice was installed.
3. The named budget guard was independently forced with `run --max-audio-gb 0.001`. The attempts ledger recorded `outcome=skipped`, `error_code=audio_budget` before any new download.
4. Final staged acceptance used a clean archive root and the deployed revision `4e00fb3`:
   - `fetch-meta --limit-pages 5` produced 156 page-aware rows; cursor remained bounded at `next_page=6`.
   - Initial N=5 attempts containing only subtitle rows returned the deliberate missing-audio-branch failure. This validated that branch coverage is not inferred from successful subtitles.
   - A targeted subtitle probe found a 374-second `needs_audio` candidate. The subsequent mixed smoke `pilot --n 5 --max-audio-gb 10 --max-duration-min 45` exited 0 with `pilot batch branches: subtitle=3, audio-asr=2`.
   - The staged final `pilot --n 20 --max-audio-gb 10 --max-duration-min 45` exited 0 with `pilot batch branches: subtitle=19, audio-asr=1` and `pilot coverage branches: subtitle=32, audio-asr=3`.
5. The live model used FunASR 1.4.3 with CPU-only PyTorch 2.5.1+cpu and torchaudio 2.5.1+cpu. ASR output was written in `srt`, `txt`, and `md`; audio was reclaimed after every successful ASR archive.

## Final Measurements

- `status`: archived=35, meta_ok=106, needs_audio=3, subtitle_done=12.
- Latest `pilot` run ledger row: exit 0, coverage `archived=35, meta_ok=106, needs_audio=3, subtitle_done=12`; cursor remains bounded at `next_page=6`.
- Final `audio/`: 0 bytes. Observed active-ASR sample usage was 5,768,297 bytes, far below the 10 GiB cap.
- Whole staged pilot archive: 9,941,530 bytes.
- Transcript artifacts: 47 SRT, 35 TXT, and 35 Markdown files.
- Credential scan of the staged archive: clean; no cookie label or value persisted.

## Acceptance Verdict

Pass for the iteration's bounded PC pilot: staged N=5 and N=20 succeeded on Windows WSL, both subtitle and ASR branches were observed in each successful stage, ASR reclaim was observed, the named pre-download budget skip was observed, and final audio usage was below 10 GiB. Long livestream proof remains deferred under the Delivery Compass roadmap.
