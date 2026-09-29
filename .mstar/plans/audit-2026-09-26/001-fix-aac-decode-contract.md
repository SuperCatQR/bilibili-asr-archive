---
plan_id: 20260927-aac-decode-contract
iteration: null
primary_spec: .mstar/specs/asr-archive-cli.md
blocked_by: []
qa_gate: mandatory
qa_mode: targeted
execution_mode: sdd
source_review: .mstar/projects/_default/reports/pr-review/2026-09-26-pr19.md
---

# Fix the `.m4a` decode contract so the fallback works on a fresh install, and pin it

**Status: `Done` 2026-09-27 — merged.** PR #20 merged as merge commit `d356e16` (`1f2dcd0..d356e16`
on `main`); branch `feat/20260927-aac-decode-contract`. All seven acceptance criteria (§3) verified on
the target host, including the two mutation checks, and re-verified after the merge against an archive
of the merged `main` (`1713 passed / 6 skipped / 0 failed`).

The delivered set is six commits, because two review rounds changed it after the first:
`f4c0ebb` (the repair) → `d4f57cb` (two decode defects found by an adversarial read of `f4c0ebb`) →
`b43234b` (a lock regeneration, **reverted** by `902879c` — it resolved a PyPI CUDA torch) →
`e766f23` (four coverage holes in this work's own tests) → `d6153b8` (four refuted claims). The net
diff on `main` therefore does not touch `uv.lock` at all.

Closed: `_default · R5` (this plan's subject), `20260924-qwen3-asr-transformers · R1` (its owed
real-`.m4a` fixture) and `· R2` (its owed `DEFAULT_HOTWORDS` pin). Opened: `· R6` (the stale lock,
reopened because its earlier closure wrongly credited the reverted regeneration) and `· R7` (the
torch-through-`accelerate` hazard, high).

**What was decided differently from §2 task 1, and why.** The task offered two options: bound the extra
(`librosa>=0.10,<1`) or move to an explicit backend. The second was chosen after measuring:
`ffmpeg` is already declared by `AGENTS.md:14` and already shelled out to at `audio.py:71-81`, so it
adds no new kind of dependency; `audioread`'s own ffmpeg path decodes to `s16le` (lossy) whereas the new
path is bit-identical to ffmpeg's `f32le` output (0.0 max diff over 236800×2 samples); and `soxr` — what
`librosa.resample` calls at its default `res_type="soxr_hq"` — measured **bit-identical** to
`librosa.resample`, is numpy-only, and is a ~200 KB wheel. Bounding `librosa` would have worked but keeps
a dependency whose only use here is to wrap two things the project already has.

**A risk this plan's title understated, found while deciding.** `librosa` 1.0.0 requires
`numpy>=2.1.0`; the verified ROCm recipe runs `numpy 1.26.4`. The unbounded extra would therefore have
dragged a numpy major version into a verified GPU environment — a bigger hazard than the failed AAC
decode that prompted the plan. Recorded in R5's closure note.

**Raised by**: deep PR review of #19 (verdict `blocked`). PR #19 repairs a real defect — the merged
boundary could not read the `.m4a` its own downloader writes — but the repair is **inert on any
environment built from the repo's own declarations**, and no test can see that.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `84e9767`, 2026-09-26

## 1. Problem

`pyproject.toml:36` declares `librosa>=0.10` with no upper bound. librosa 1.0.0 (2026-08-11, now the
default resolution) **dropped `audioread`** and its `load()` is a bare `__soundfile_load` call, so on an
`.m4a` it re-raises the same `soundfile.LibsndfileError` the primary reader raised. Measured on the
target host, same source, same file, two environments:

| environment | `asr._read_audio('x.m4a')` |
|---|---|
| `librosa 1.0.0` (a fresh `.[asr]` resolution) | raises `soundfile.LibsndfileError` |
| `librosa 0.11.0` (the host's venv) | `(89088,) rate 44100` |

The 4 new tests **pass under 1.0.0**, so the regression is silent. `asr.py:404` also imports `librosa`
outside the reader guard, so a host without it gets a bare `ImportError` instead of the documented
`ASRDependencyError`.

## 2. Tasks

1. **Decide the decoder and make it explicit.** Either (a) bound the extra `librosa>=0.10,<1` and refresh
   `uv.lock` (whose root block at `:93-95` still declares `funasr`), or (b) decode non-libsndfile
   containers through an explicit backend the project declares — `audioread` directly, or an `ffmpeg`
   subprocess, both of which the README already says are the real dependency. Option (b) removes the
   version coupling; option (a) is smaller and keeps the current code shape. **Decide and record why.**
2. **Move the `librosa` import inside the reader guard** at `asr.py:836-841` so every missing reader
   reports through `ASRDependencyError` (`cli.py:2280`, `:2667` depend on it).
3. **Add a test that decodes a real `.m4a`.** Generate ~2 s of AAC with `ffmpeg` at test time and skip
   when `ffmpeg` is absent (keep media out of the repo). Assert `_read_audio` returns samples. This is the
   test `20260924-qwen3-asr-transformers · R1` has owed since the codec repair.
4. **Cover the resample branch** (`asr.py:851-854`, 0 executions today): a fake reader yielding 48 kHz
   through `transcribe()`, asserting offsets in real seconds.
5. **Pin `DEFAULT_HOTWORDS`.** One test asserting the 33 entries (or comparing against the README). This is
   `20260924-qwen3-asr-transformers · R2`'s owed pin; without it the 33→26 class of silent rewrite repeats.
6. **Fix the tautological assertion** at `test_asr_qwen.py:630` — mirror the real signature in the stub
   (`sr=22050, mono=True`).
7. **Correct the claims.** `README.md:143-144` and the `asr.py:387-389` docstring must state what the
   pinned closure actually provides. Also: the restored comment at `asr.py:145-146` says `ITEM`/`AITEM`
   "are listed", which is false at HEAD (`asr.py:148-149` says they were removed); and the restore dropped
   11 comment lines the pre-rewrite block carried (`BV19hG56hEfV.p2`, the `raison d'être` of
   `BV1eGJ46mEHQ`) — restore them or state they were not carried back.
8. **Repoint the hotword doc's citations**: `related_components` → `archive.py (write_archive -> asr_* frontmatter)`
   (`hotword-list-measurement.md:29`); `L456-467` → `asr.py:316` (`:63`); "double restoration proof" →
   "byte-anchored restore proof" (`:191`); add `last_updated: 2026-09-26` to both refreshed docs.

## 3. Acceptance criteria

1. On a **clean venv** (`python3 -m venv` + `pip install -e ".[asr]"`), `asr._read_audio` returns samples
   for a real AAC `.m4a` — no `LibsndfileError`.
2. The new `.m4a` test **fails** when the fallback is made a no-op (prove the test can see it).
3. `asr.py:851-854` is executed by at least one test (a `sys.settrace` count > 0).
4. A test fails when a `DEFAULT_HOTWORDS` entry is removed.
5. A host with `soundfile` but no `librosa` raises `ASRDependencyError`, not `ImportError`.
6. `README.md` and the `asr.py` docstring name only what the resolved closure provides.
7. Register `R1` and `R2` may then be closed with this evidence.

## 4. Out of scope

- The `uv.lock` root block still declaring `funasr` is in scope only insofar as task 1 refreshes the lock.
- `_safe_error_code` returning a bare int for `LibsndfileError` (`coordinator.py:117-127`) is pre-existing
  and separately registered; not fixed here.
