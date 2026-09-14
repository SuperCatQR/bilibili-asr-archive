# iter-2026-08-live-pc-pilot spec deltas

Status: locked (Phase 1, PM-only review chain per user waiver 2026-08-26 after 3/3 subagent dispatch failures)

## Delta 1 — post-archive audio reclaim

- When a work_id reaches `archived` (subtitle or ASR path), the CLI deletes that part's audio file under `{archive_root}/audio/` (helper `audio_reclaim.reclaim_audio`).
- Failed / `needs_audio` / `audio_ok` rows keep audio. Manifest may retain a relative `audio_path`; consumers must tolerate the file's absence (offline `run` already skips missing audio).
- No JSONL schema migration; no HTTP; no credential surface.

## Delta 2 — bounded audio budget + duration skip

- Flags on `pilot` (and `run` live stages): `--max-audio-gb` (default 10), `--max-duration-min` (default 45).
- Selection excludes rows over the duration threshold.
- Before each download: `audio/` usage + `duration_s` × 8000 B/s estimate vs cap → skip with named reason `audio_budget`; batch continues; nonzero only when a required branch ends with zero eligible items.
- Frozen MVP spec (`.mstar/specs/asr-archive-cli.md`) otherwise unchanged.

## Non-goals

Full-corpus scheduling, long-livestream proof (deferred; see compass Roadmap Position), schema migration, Meilisearch.
