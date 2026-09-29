# WSL PC Pilot Runbook (plan B task 2 owns the final committed version)

Target: DESKTOP-HHFROLO (192.168.1.21) · user `chosenecho` · product checkout + venv in WSL.
Budget: audio peak < 10 GiB (`--max-audio-gb` default 10) · no livestreams > 45 min (`--max-duration-min` default 45) · archived rows' m4a auto-deleted (reclaim).

## Stage 0 — sync + env (once per session)

Use a checkout already on `iteration/iter-2026-08-live-pc-pilot`; `git fetch` requires its normal GitHub credential configuration. Confirm the install and media toolchain before live work:

    cd /root/workspace/bilibili-asr-archive/bilibili-asr-archive
    git branch --show-current
    .venv/bin/bili-asr --help
    ffmpeg -version | head -1

In the WSL shell, paste the cookie **value** from the browser (never write it to any file):

    export BILI_SESSDATA='<cookie value>'

## Stage 1 — bounded smoke N=5

Use a fresh archive root. Five metadata pages are still bounded, but provide enough short candidates for the 45-minute selection policy.

    bili-asr fetch-meta --mid 23191782 --limit-pages 5 --archive-root ~/pilot-archive
    bili-asr harvest-subs --limit 20 --archive-root ~/pilot-archive
    du -sb ~/pilot-archive/audio || true
    bili-asr pilot --n 5 --max-audio-gb 10 --max-duration-min 45 --archive-root ~/pilot-archive
    bili-asr status --archive-root ~/pilot-archive
    bili-asr runs --limit 5 --archive-root ~/pilot-archive

**Gate**: successful output reports nonzero `pilot batch branches` for both subtitle and audio-ASR, `du` remains well below cap, and archived ASR rows have no m4a left. If no duration-eligible `needs_audio` row has been discovered, probe more short rows with `harvest-subs --bvid <work_id>` and repeat the smoke; do not raise the 45-minute limit just to satisfy branch coverage.

## Stage 2 — N=20

    bili-asr pilot --n 20 --max-audio-gb 10 --max-duration-min 45 --archive-root ~/pilot-archive
    du -sb ~/pilot-archive/audio
    bili-asr status --archive-root ~/pilot-archive
    bili-asr runs --limit 5 --archive-root ~/pilot-archive

**Gate**: 20 terminal rows when enough eligible rows exist, both batch branches present, and `du` < 10 GiB at every checkpoint. Exit 1 for missing branch coverage means expand short-candidate discovery and resume; exit 2 (risk) means wait and resume, never force.

## Evidence checklist (paste into the QA record)

- [ ] Stage-1 pilot summary output (both branch counts)
- [ ] `du -sb audio` before / after each stage
- [ ] `status` + `runs --limit 5` outputs
- [ ] 2–3 transcript file paths (one srt, one md) for spot check
- [ ] Confirmation no SESSDATA appears in any captured output
