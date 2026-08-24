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

### `fetch-meta --resume` and exit 2

`bili-asr fetch-meta` writes `{archive-root}/meta-cursor.json` after each
successful archive-list page merge. The sidecar holds only `mid`, `next_page`,
`total`, `state`, `last_api_error_code`, and `updated_at` — never cookies,
`SESSDATA`, signed URLs, or exception text.

| Exit | Meaning |
|------|---------|
| 0 | Run finished without risk exhaustion. Cursor `state` is `complete` (full visible archive) or `limited` (intentional `--limit-pages` cap). `--resume` does **not** auto-continue these. |
| 1 | Usage/config or unexpected error (no traceback). |
| 2 | Risk budget or terminal API failure. Cursor `state` is `risk_interrupted`; `next_page` is the 1-based `pn` that was **not** merged. Re-run `fetch-meta --resume` with the same `--mid` to start at that page. |

`--resume` auto-continues **only** an exit-2 `risk_interrupted` cursor whose
`mid` matches. `complete` and `limited` are not auto-resumable. JSONL upsert
stays last-write-wins per `work_id`; a failed page is never marked complete.
Without `--resume`, a new run starts at page 1, merges the existing JSONL
(does not shrink it to a page-1 prefix), and replaces a leftover cursor after
the first successful page. Mid-run sidecar writes stay `risk_interrupted`
with `next_page` = last merged `pn+1`; terminal `complete`/`limited` is
written only when the run finishes without exit 2.

Exit codes for other commands: 0 ok / 1 usage-config or per-video failure / 2
terminal API failure.

## Multipart pages and legacy rows

Automatic enumeration writes one manifest row per page (`work_id` =
`{bvid}:p{page_index}`). Filesystem names use `artifact_stem`
(`{bvid}.p{page_index}`) so raw/SRT/audio/transcripts never collide across
pages. Public URLs for `page_index` > 0 include `?p=` (1-based).

Legacy single-page rows migrate only when ownership is unambiguous. Ambiguous
bare-bvid rows stay `unresolved` / `excluded_from_page_processing`: they keep
their original key and files, stay visible in `bili-asr status`, and are never
auto-assigned a page. `download-audio --bvid` / `asr --bvid` STOP on those
rows instead of fabricating a `needs_audio` page. Resume is per `work_id`: a
completed or failed p0 does not skip p1.

No media redistribution; personal archival only.
