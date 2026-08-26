# Windows WSL long-live campaign

Opt-in proof for one multi-hour livestream on the Windows WSL PC. This does
**not** change `pilot --max-duration-min` (default 45) and must **not** set
`--max-audio-gb 0`. Live execution is an operator/QA action; automated tests
use a fake fixture only.

## Archive root

Use a WSL-native directory, not a `/mnt/c/...` path (NTFS I/O is slow for
audio peaks):

    export ARCHIVE_ROOT="$HOME/bili-asr-long-live"
    mkdir -p "$ARCHIVE_ROOT"

Keep this root off the product git checkout. Transcripts stay under
`$ARCHIVE_ROOT`; downloaded audio is transient under `$ARCHIVE_ROOT/audio`.

## Cookie boundary

Login is optional Path B for harvest/download. Supply the cookie **value**
only, in the current WSL shell:

Assign the cookie value to the BILI_SESSDATA environment variable in this
WSL shell only (interactive `read` / `export BILI_SESSDATA`, not a file).

Rules:

- Value via `BILI_SESSDATA` or `--sessdata`. Never a file path.
- Do not echo the variable, write it to disk, or paste it into git, chat, or
  the evidence template.
- Unset it when the campaign ends: `unset BILI_SESSDATA`.
- Sidecars (`manifest`, `scheduler.json`, `run-ledger.jsonl`, coordinator
  attempts) must stay free of cookies, signed URLs, and stack traces.

## Discover a long row without weakening the short-video pilot

    bili-asr fetch-meta --mid 23191782 --archive-root "$ARCHIVE_ROOT"
    bili-asr status --archive-root "$ARCHIVE_ROOT"

Pick one `work_id` whose `duration_s` is greater than 45 minutes. Do **not**
raise `pilot --max-duration-min` or disable the audio cap.

## Campaign (opt-in schedule)

Measure `audio/` before the download:

    du -sb "$ARCHIVE_ROOT/audio" || true

Run the bounded scheduler for that single id:

    bili-asr schedule \
      --scope <work_id> \
      --limit 1 \
      --allow-long-live \
      --max-audio-gb 10 \
      --archive-root "$ARCHIVE_ROOT"

The summary prints conservative `estimated_bytes` (`duration_s` × 64 kbps),
`would_exceed`, then measured `peak audio/` and `audio/ after`. A candidate
whose projected peak would breach the cap is skipped with `audio_budget` and
stays `needs_audio`.

Re-measure after archive:

    du -sb "$ARCHIVE_ROOT/audio" || true
    bili-asr status --archive-root "$ARCHIVE_ROOT"
    bili-asr runs --limit 3 --archive-root "$ARCHIVE_ROOT"

**Pass:** row is `archived`, peak stayed under 10 GiB, `du` after is below the
peak (reclaim removed that part's audio), and captured text has no cookie
value, signed URL, or stack trace.

**Fail / retry:** per-item failure keeps `audio_ok` / `needs_audio` plus the
local audio file. Re-run the same `--scope` after fixing the cause. Risk exit
2: wait, then `schedule --resume` with the same scope. If the interrupted
row is multi-hour, pass `--allow-long-live` again; omitting it refuses
resume and keeps `scheduler.json` as `risk_interrupted`.

Copy redacted stdout/stderr, `du` lines, and `status`/`runs` into
`docs/wsl-long-live-evidence.md`. QA records the live WSL run; do not check in
credentials.
