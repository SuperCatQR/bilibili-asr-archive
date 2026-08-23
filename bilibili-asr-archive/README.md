# bilibili-asr-archive

Personal archival CLI for Bilibili UP 未明子 (UID 23191782) ASR transcripts.

Enumerates videos, harvests AI/CC subtitles first, downloads audio only when
needed, runs local SenseVoice ASR, and archives `srt` / `txt` / `md` with a
resumable JSONL manifest.

## Install (editable)

    py -3.12 -m pip install -e ".[dev]"

## Usage

    bili-asr --help
    bili-asr fetch-meta --mid 23191782 --resume
    bili-asr status

Exit codes: 0 ok / 1 usage-config / 2 terminal API failure.

No media redistribution; personal archival only.
