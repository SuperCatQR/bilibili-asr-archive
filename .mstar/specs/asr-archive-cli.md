# Spec: Bilibili ASR Archive CLI (MVP)

**Status:** draft (Phase 1)  
**Primary consumers:** plans `001-cli-scaffold-meta`, `002-subtitle-audio`, `003-asr-archive`  
**UP mid default:** `23191782`

## Problem

Need a durable, resumable local tool to turn a Bilibili UP's public videos into searchable text. Manual download+ASR does not scale; B站 AI subtitles cover part of the corpus for free.

## Goals

1. Enumerate all visible archives for a mid into a local manifest (JSONL/SQLite).
2. Prefer existing AI/CC subtitles before any ASR.
3. Download audio-only streams when subtitles are missing.
4. Transcribe with local SenseVoice-Small (CPU-capable).
5. Emit `srt` / `txt` / `md` with metadata frontmatter; resume-safe.

## Non-goals (MVP)

Full-corpus finish, diarization, LLM polish, search UI, redistribution.

## CLI surface (MVP)

```text
bili-asr fetch-meta --mid <mid> [--resume]
bili-asr probe-subs [--limit N] [--sessdata ...]
bili-asr harvest-subs [--limit N]
bili-asr download-audio --bvid <bvid>|--missing-subs [--limit N]
bili-asr asr --bvid <bvid>|--pending [--limit N]
bili-asr pilot --n 20
bili-asr status
```

Entrypoint name may be `bili-asr` or `wmz-asr`; document in README.

## Manifest state machine

`pending → meta_ok → sub_checked → {subtitle_done | needs_audio} → audio_ok → asr_done → archived`

Idempotent: re-runs skip completed states.

## Auth / risk

- Optional `SESSDATA` (env or `--sessdata`) for AI subtitles and higher playurl quality.
- Obtain `buvid3`/`buvid4` via `x/frontend/finger/spi`.
- Backoff on HTTP 412 / code -412 / -352 / -799.

## Outputs

```text
archive/
  manifest/manifest.jsonl
  meta/{bvid}.json
  subtitles/raw/{bvid}.json
  transcripts/{srt,txt,md,raw}/
  audio/{bvid}.m4a   # optional retain
```

## Verification

- Unit: state transitions, subtitle JSON→SRT conversion
- Integration: fetch ≥1 page meta; probe 5 videos; end-to-end pilot ≤20 videos (may use short videos preferentially)
- Acceptance: README commands succeed on a clean install with ffmpeg + Python 3.12

## References

- `bilibili-asr-archive/PLAN.md`
- `bilibili-asr-archive/references/bilibili-API-collect/docs/video/player.md`
- `bilibili-asr-archive/references/bilibili-API-collect/docs/misc/risk-and-stream.md`
