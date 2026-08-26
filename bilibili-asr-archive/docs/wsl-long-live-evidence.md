# Long-live WSL evidence (redacted)

Fill this during the live Windows WSL acceptance run. Paste command output
with cookies, signed URLs, and stack traces removed. Never commit a cookie
value.

## Environment

- Host / WSL distro:
- Product checkout branch:
- Archive root (WSL path, not a Windows mount):
- Cookie supplied: `BILI_SESSDATA` or `--sessdata` in-shell only (value omitted)
- `--max-audio-gb`: 10 (must not be 0)
- `--allow-long-live`: yes
- `work_id` / `duration_s`:

## Disk (`du -sb "$ARCHIVE_ROOT/audio"`)

- Before schedule:
- After schedule (post-reclaim):

## Scheduler summary (redacted)

Paste the `schedule:` lines only:

- conservative `duration_s` / `estimated_bytes` / `would_exceed`:
- measured `peak audio/` bytes:
- measured `audio/ after` bytes:
- `batch=` state:
- `enumeration:`:
- exit code:

## Manifest / reclaim

- Final row status (`archived` / `needs_audio` / `audio_ok`):
- Audio file for this stem present after success? (expect no)
- Audio file retained after failure? (expect yes)

## Inspection

    bili-asr status --archive-root "$ARCHIVE_ROOT"
    bili-asr runs --limit 3 --archive-root "$ARCHIVE_ROOT"

Paste redacted output:

## No-secret scan

- [ ] Cookie value absent from stdout, stderr, and archive json/jsonl/md/txt/srt
- [ ] No signed stream URLs
- [ ] No stack traces
- [ ] `BILI_SESSDATA` unset after the run
