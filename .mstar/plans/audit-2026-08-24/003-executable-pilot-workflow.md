# Executable Two-Branch Pilot Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `mstar-sdd` (recommended) or inline execution. This audit plan is a candidate for the normal Prepare -> Execute flow; it does not register or execute itself.

**Goal:** Make `bili-asr pilot --n N` perform and summarize the frozen MVP pilot, including at least one subtitle branch and one audio-to-ASR branch, rather than only selecting existing manifest rows.

**Architecture:** Keep `cli.py` as the composition layer. Reuse the existing `subtitles.harvest_subtitle`, `audio.download_audio`, `asr.transcribe`, and `archive.write_archive` seams; do not add network or ASR logic to helpers. The pilot should select candidates, automatically enumerate all `pagelist` parts when a selected bvid has more than one part, run only bounded work, persist every part-specific state transition, and stop with a nonzero actionable summary when branch coverage cannot be achieved.

**Tech Stack:** Python 3.12+, existing CLI modules, injectable `BiliClient` transport, pytest.

## Status
- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: plans/005-bilibili-api-contract-integrity.md
- **Category**: bug
- **Planned at**: commit `ab3cd97`, 2026-08-24

## Finding and current state

- The parser registers `pilot --n`, but no `--sessdata`, `--resume`, or other execution controls (`bilibili-asr-archive/src/bili_asr/cli.py:63-65`).
- `_cmd_pilot()` only loads the manifest, calls `_pilot_select()`, prints rows, and returns 1 if both branches are not already represented (`cli.py:448-461`). It never calls subtitle harvesting, audio download, ASR, or archive writing.
- `_pilot_select()` considers rows already in `subtitle_done`, `needs_audio`, or `audio_ok` (`cli.py:372-387`), so a fresh `meta_ok` manifest cannot be transformed into the required two-branch pilot.
- The README describes `pilot` as part of the workflow and states branch coverage requirements (`bilibili-asr-archive/README.md:23-38`), while the frozen spec requires an end-to-end pilot that leaves terminal states (`.mstar/specs/asr-archive-cli.md:12-22,35-42,133-137`).

## Interfaces

Retain these existing helpers and contracts:

- `_pilot_select(entries: dict[str, dict[str, object]], n: int) -> list[dict[str, object]]`
- `subtitles.harvest_subtitle(client, bvid, store, archive_root) -> str`
- `audio.download_audio(client, bvid, out_path, store=store) -> str`
- `asr.transcribe(audio_path) -> list[dict[str, Any]]`
- `archive.write_archive(root, entry, segments, source=..., raw=...) -> dict[str, str]`

Add only the pilot-specific orchestration and CLI arguments required to make the documented behavior explicit. Do not make `pilot` silently skip the ASR extra; missing `funasr` must produce the existing actionable dependency error and a nonzero result.

## In scope

- `bilibili-asr-archive/src/bili_asr/cli.py`
- `bilibili-asr-archive/src/bili_asr/manifest.py` only if a transition helper is needed
- `bilibili-asr-archive/README.md`
- `bilibili-asr-archive/tests/test_pilot_select.py`
- New focused `bilibili-asr-archive/tests/test_cli_pilot.py` if needed

## Out of scope

- Reimplementing HTTP, subtitle parsing, audio downloading, ASR normalization, or archive formatting.
- Expanding the pilot beyond the frozen bounded `N` and mixed-branch proof. Multi-part identity work belongs to plan 001; automatic all-part pilot coverage is required when pilot fixtures include a multi-part bvid, while the general orchestration contract remains independently testable.
- Full-corpus scheduling, search, diarization, LLM cleanup, or a GUI.

## Conventions and exemplars

- CLI commands catch expected per-video failures and print a summary, as in `cli.py:243-292` and `295-356`; preserve this style while making the pilot's partial result explicit.
- State is written through `ManifestStore.upsert()` (`manifest.py:72-86`), and artifact paths are merged into the entry as in `cli.py:431-435`.
- Tests use fake transport and workspace-local temporary roots (`tests/conftest.py:12-30`); no live network, model download, or real ffmpeg invocation is allowed.

## Tasks

### Task 1: Execute a bounded mixed pilot

**Files:** Modify `bilibili-asr-archive/src/bili_asr/cli.py`; test `bilibili-asr-archive/tests/test_pilot_select.py` and a new `tests/test_cli_pilot.py`; update `README.md`.

- [ ] Define selection behavior for a fresh `meta_ok` manifest. Selection must be deterministic and prefer short items, while reserving capacity for both branches when possible.
- [ ] For each selected item, probe/harvest subtitles first. Subtitle hits must become `subtitle_done` and then archive from subtitle data without invoking ASR.
- [ ] For selected no-subtitle items, download audio, invoke local ASR, write transcript artifacts, and persist `archived` with `audio_path` and archive paths.
- [ ] Persist and report per-item failures, branch counts, and final terminal states. A pilot with unavailable branch coverage must exit nonzero and identify what is missing.
- [ ] Pass `BILI_SESSDATA`/`--sessdata` only as a cookie path if the pilot accepts those options; never echo or persist it.

Run: `python -m pytest bilibili-asr-archive/tests/test_pilot_select.py bilibili-asr-archive/tests/test_cli_pilot.py -q` -> all pilot tests pass with fake transport and stubbed ASR.

### Task 2: Pin idempotent reruns and dependency errors

- [ ] Add a test that a completed pilot rerun skips archived rows or produces no duplicate artifacts/manifest rows.
- [ ] Add a test that missing optional ASR dependency returns a clear nonzero result and does not mark the row archived.
- [ ] Add a test that a subtitle branch never calls ASR, and an audio branch does call it exactly once.

Run: `python -m pytest bilibili-asr-archive/tests/test_pilot_select.py bilibili-asr-archive/tests/test_cli_pilot.py -q` -> all branch, rerun, and missing-dependency tests pass.

## STOP conditions

- If the frozen spec is interpreted as `pilot` being selection-only rather than execution, STOP and escalate the contradiction between `.mstar/specs/asr-archive-cli.md:12-22,133-137` and the current README before changing behavior.
- If the selected manifest model cannot distinguish a subtitle hit from an ASR result without changing state semantics, STOP and align with the state machine before implementation.
- If a fake ASR seam cannot be injected without importing FunASR at module import time, STOP; preserve the lazy import guarantee in `asr.py:86-121`.

## Drift check

Before execution run:

`git diff --stat ab3cd97..HEAD -- bilibili-asr-archive/src/bili_asr/cli.py bilibili-asr-archive/src/bili_asr/manifest.py bilibili-asr-archive/README.md bilibili-asr-archive/tests/test_pilot_select.py bilibili-asr-archive/tests/test_cli_pilot.py`

STOP on any mismatch in the current pilot call path.

## Done criteria

- [ ] A fresh `meta_ok` fixture can drive a bounded pilot to both branch outcomes under fakes.
- [ ] Subtitle-hit pilot rows are archived without an ASR call.
- [ ] Audio fallback pilot rows require ASR and are archived only after successful transcript writing.
- [ ] Missing ASR dependency leaves the row non-archived and returns a nonzero result with the install hint.
- [ ] `python -m pytest bilibili-asr-archive/tests/test_pilot_select.py bilibili-asr-archive/tests/test_cli_pilot.py -q` exits 0.
- [ ] `grep -n "pilot" bilibili-asr-archive/README.md` documents execution, branch coverage, rerun behavior, and optional-ASR failure.
- [ ] `git status --short` shows only in-scope files changed.

## Prepare -> Execute handoff

During Prepare, lock whether pilot may call network for subtitle/audio and how it chooses fresh candidates. During Execute, use a fake client plus monkeypatched ASR to prove both branches, then run the focused suite before plan 004 broadens entrypoint integration coverage.
