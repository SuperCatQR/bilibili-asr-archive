# AGENTS.md — wmz

## Identity

Personal tooling workspace for Bilibili UP 未明子 (UID 23191782) ASR transcript archival.

## Product

- Package root: `bilibili-asr-archive/`
- Goal: installable Python CLI that enumerates videos, harvests AI/CC subtitles first, downloads audio when needed, runs local Qwen3-ASR, and archives `srt`/`txt`/`md` with a resumable manifest.

## Tech boundary

- Python 3.12+, ffmpeg required
- Prefer thin wrappers over yutto/BBDown when useful; keep a pure-API fallback
- No redistribution of media; personal archival only

## Branch policy

- Default integration / PR target: `main` (greenfield bootstrap 2026-08-23)
- Feature work: plan branches merging into `iteration/<iteration-id>`

## Harness SSOT

See `.mstar/AGENTS.md` for path symbols and harness contracts.
