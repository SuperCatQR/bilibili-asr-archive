# Post-archive audio reclaim

> Iteration: `iter-2026-08-live-pc-pilot`.
> Execution mode: `sdd`.
> primary_spec: `.mstar/specs/asr-archive-cli.md` (frozen MVP) + iteration delta in `{ITERATION_DIR}/iter-2026-08-live-pc-pilot/specs/`.

## Status

- Priority: P1
- Category: logic
- Status: Todo
- Depends on: none
- Findings cleanup: zero-residual

## Goal

When a `work_id` reaches `archived`, delete that part's local audio file so a PC pilot can keep `{archive-root}/audio` well under 10 GiB. Failed and in-progress rows keep their m4a for retry.

## Specify

Operator on Windows WSL archives mixed subtitle/ASR rows. ASR downloads 64 kbps m4a. Keeping every file toward 60–80 GiB corpus is unacceptable for this iteration (cap 10 GiB peak). Success path must reclaim disk immediately after transcripts exist.

## Clarify

- Delete only after `archived` (subtitle-sourced rows may never have had audio — no-op).
- Do not delete on `needs_audio` / `audio_ok` / failed stage.
- Manifest may still mention a relative `audio_path`; after reclaim the file is absent; readers must tolerate missing file (offline `run` already skips missing audio).
- No JSONL schema migration; no SESSDATA in logs.

## Architecture

Hook reclaim in the same composition path that sets `archived` (`pilot`, `asr` CLI, coordinator `archive` stage). Shared helper in a filesystem-only module (not `bili_client`). Tests: temp dirs + fake transport; never live HTTP.

## Global Constraints

- `bili_client` remains sole HTTP owner.
- No live HTTP/model download in tests.
- Never echo or persist SESSDATA / signed URLs.
- JSONL last-write-wins; `VALID_STATUSES` unchanged.
- `work_id` / `artifact_stem` page identity unchanged.

## Tasks

### Task 1: Reclaim helper + archive-path wiring

**Files:**

- Create: `bilibili-asr-archive/src/bili_asr/audio_reclaim.py` (final name; unambiguous: audio reclaim on archive)
- Modify: `bilibili-asr-archive/src/bili_asr/archive.py` and/or `cli.py` / `coordinator.py` at the `archived` write
- Test: `bilibili-asr-archive/tests/test_audio_reclaim.py`

**Interfaces (locked):**

- `audio_reclaim.reclaim_audio(archive_root: str | os.PathLike[str], entry: Mapping[str, object]) -> bool` — filesystem-only module `bilibili-asr-archive/src/bili_asr/audio_reclaim.py`; returns True iff an audio file was removed. Candidate path: entry `audio_path` if present, else `{archive_root}/audio/{artifact_stem}.m4a` (also `.flac`). Missing file → False (no-op success). Rejects resolved paths outside `{archive_root}/audio/` (ValueError; never unlink).
- Wiring: called exactly once per work_id immediately after the row is set `archived`, in (a) `cli.py` pilot loop, (b) `cli.py` `asr` command, (c) `coordinator.py` `archive` stage (live and `--offline`).
- Reclaim OSError is per-item non-fatal: row stays `archived`, failure counted in the command summary; no HTTP retry.

- [ ] Failing tests: archived ASR row deletes m4a; archived subtitle-only row no-ops; failed row keeps file; path traversal rejected
- [ ] Minimal implementation
- [ ] Tests pass

### Task 2: Wire pilot, asr command, and coordinator archive stage

**Files:**

- Modify: `bilibili-asr-archive/src/bili_asr/cli.py`, `coordinator.py`
- Test: existing `test_cli_pilot.py` / `test_coordinator.py` plus reclaim assertions

- [ ] After successful archive write, reclaim runs once
- [ ] Coordinator `--offline` archive success also reclaims
- [ ] pytest subset green; no credential leakage

## Plan self-review

1. Spec coverage: reclaim-on-archived maps to T1–T2
2. No TBD placeholders
3. Names: helper + tests share stem path rules
