# Bounded live PC pilot (10 GiB audio peak)

> Iteration: `iter-2026-08-live-pc-pilot`.
> Execution mode: `sdd`.
> Depends on: `20260826-audio-reclaim-on-archive`.

## Status

- Priority: P1
- Category: ops / logic
- Status: Todo
- Depends on: 20260826-audio-reclaim-on-archive
- Findings cleanup: zero-residual

## Goal

Make `bili-asr pilot` (and `run` download stage) honor a **10 GiB default audio-directory peak**, skip long livestreams for this campaign, and leave a WSL operator runbook so smoke N=3–5 then N=20 can be executed on DESKTOP-HHFROLO without filling the disk.

## Specify

PLAN M2 wants ~20 items including long lives; this iteration **explicitly excludes** multi-hour livestreams. 64 kbps × 10 GiB ≈ 35 h of audio if nothing is deleted; with reclaim, peak is in-flight files only. Operator needs a hard stop before download.

## Clarify

- Budget flag `--max-audio-gb` default **10**; per-item **skip** semantics: candidate item estimated to breach the cap is skipped with named reason `audio_budget`, batch continues; nonzero exit only if a required branch ends with zero eligible items (existing missing-branch contract).
- Duration skip: rows with `duration_s` above **45 min** (default, `--max-duration-min` configurable) are excluded from this campaign's selection; long-live proof is explicitly deferred to the full-corpus iteration (see compass Roadmap Position).
- Live proof is **operator evidence on WSL**, not pytest hitting Bilibili.
- SESSDATA only via env on that machine.

## Architecture

Budget check is filesystem-only (`du` of `{archive-root}/audio` plus planned file size if known). No extra HTTP. Runbook lives in iteration `guides/` until compound; README gets a short pointer.

## Global Constraints

Same HTTP / credential / schema constraints as plan A.
Windows WSL product venv: `/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/pytest` on the PC (via `wsl -e bash -lc`).

## Tasks

### Task 1: Duration skip + audio-dir budget gate

**Files:**

- Modify: `bilibili-asr-archive/src/bili_asr/cli.py` (pilot select + download/run)
- Test: `bilibili-asr-archive/tests/test_audio_budget.py`

**Interfaces:**

- `cli.py` pilot/run selection: exclude rows with `duration_s` > `max_duration_min * 60` (flag `--max-duration-min`, default 45)
- Budget helper (filesystem-only): `audio_dir_usage_bytes(archive_root)` + `estimate_audio_bytes(duration_s)` (duration_s × 8000 B/s ceiling); before `download_audio`, if `usage + estimate > max_audio_gb * 1024**3`, skip item with recorded reason `audio_budget`; batch continues; nonzero only when a required branch has zero eligible items (reuse existing missing-branch exit contract)

- [ ] Failing tests with temp dirs (pre-fill audio/ to just below/above cap)
- [ ] Implementation
- [ ] Tests pass without network

### Task 2: WSL operator runbook + README pointer

**Files:**

- Create: `.mstar/iterations/iter-2026-08-live-pc-pilot/guides/wsl-pc-pilot.md`
- Modify: `bilibili-asr-archive/README.md` (short workflow note, no secrets)

- [ ] Steps: export BILI_SESSDATA; fetch-meta limit-pages; pilot --n 3; du; then --n 20
- [ ] Explicit: archive root on WSL disk; measure `du -sb audio`
- [ ] No cookie values in files

Live N=3–5 / N=20 execution is **QA / ops evidence** after merge to integration, not a pytest task.

## Plan self-review

1. Budget + skip + runbook covered
2. No live HTTP in unit tests
3. Depends on reclaim so peak is in-flight only
