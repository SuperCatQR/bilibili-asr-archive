# bilibili-asr-archive

Personal archival CLI for Bilibili UP 未明子 (UID 23191782) ASR transcripts.

Enumerates videos, harvests AI/CC subtitles first, downloads audio only when
needed, runs local SenseVoice ASR, and archives `srt` / `txt` / `md` with a
resumable JSONL manifest.

## Install (editable)

Base metadata/subtitle/audio workflows:

    py -3.12 -m pip install -e ".[dev]"

Local SenseVoice support is optional because it downloads model weights on first
use:

    py -3.12 -m pip install -e ".[asr]"

Set `BILI_ASR_MODEL` to a pre-populated local model directory for offline use;
the default is `iic/SenseVoiceSmall`. No model weights are vendored.

## Workflow

    bili-asr fetch-meta --mid 23191782 --resume
    bili-asr harvest-subs --archive-root archive
    bili-asr download-audio --missing-subs --archive-root archive
    bili-asr asr --pending --archive-root archive
    bili-asr status --archive-root archive
    bili-asr pilot --n 20 --archive-root archive

Subtitle access that requires login can use `BILI_SESSDATA` or the
`--sessdata` flag. Credentials are sent as API cookies only and are never put
in the manifest or output files. The pilot requires at least one
`subtitle_done` entry and one `needs_audio`/`audio_ok` entry; it reports branch
coverage without starting a full-corpus run.

Exit codes: 0 ok / 1 usage-config or per-video failure / 2 terminal API failure.

No media redistribution; personal archival only.
