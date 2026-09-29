---
type: pr-review-stage2
verdict: findings-answered
score_pct: 0
tally: {must_fix: 1, should_fix: 5, nit: 3, unverified: 0}
comments: 9
review_url: https://github.com/SuperCatQR/bilibili-asr-archive/pull/20
generated_at: 2026-09-27
tier: deep
pr: 20
head: d6153b8011f2d297b6fefdbad72e68fd0d442193
base: 1f2dcd0a62d1963f125b93107c3f3d0e1973e30f
seat: docs-and-dependency-contract
---

# Seat C — documentation accuracy and dependency contract (PR #20)

Packs `diffpack-core.txt` + `diffpack-uvlock.txt`. Read-only in the repository.

## Claim verdicts

1. README states ffmpeg required and names the Python side as soundfile + soxr — **confirmed**; the
   only surviving librosa/audioread prose is explicitly historical.
2. No librosa declaration remains — **confirmed**. The numpy rationale is **stronger than the
   repository supports**: nothing pins numpy anywhere, and `docs/wsl-rocm-gpu.md` never mentions it.
3. Lock regenerated to 85 packages, extra = accelerate/soundfile/soxr/transformers, no funasr, no
   librosa, closure complete — **confirmed**.
4. The citation fixes — **refuted in part**: `asr.py:316` was correct at the *base* commit, not at
   head, where `_extra_hotwords` is at `:343` and the `DEFAULT_HOTWORDS` skip at `:351`. Of the
   "three stale citations", only two are citations; the third is a prose phrase.
5. Two claims stronger than evidence — see findings 1, 2, 5.

## Findings

| # | Sev | Finding | Disposition |
|---|---|---|---|
| C1 | must-fix | regenerated lock installs PyPI CUDA torch + 18 nvidia packages | **reverted** (`902879c`); `· R7` |
| C2 | should-fix | the numpy claim is false for the path this branch fixes (the new lock selected numpy 2.5.3) | scoped per install path (`d6153b8`) |
| C3 | should-fix | `hotword-list-measurement.md:64` cited `asr.py:316` for `_extra_hotwords` | corrected to `:351` before this seat reported; independently confirmed |
| C4 | should-fix | "ffmpeg's stderr does not echo the path" — **refuted**: its middle line does (`Error opening input file /tmp/…m4a.`) | comment corrected to state that `detail[-1]` is what keeps the path out (`d6153b8`) |
| C5 | should-fix | the commit claimed "a path the README documents" for `uv sync --extra asr`; no tracked file contains `--extra` | claim dropped; the lock is reverted rather than fixed, so the path is no longer offered |
| C6 | should-fix | ffmpeg absent from the README install section and from `check_asr_env.py`, which README:78 calls the only "is my GPU usable" entry point | README install section now names it and says the check script is not a substitute (`d6153b8`) |
| C7 | nit | the hotword comment read as though `BV19hG56hEfV.p2`'s audio were gone; the plan's D3 says that is `BV1eGJ46mEHQ` | corrected, naming both and the asymmetry (`d6153b8`) |
| C8 | nit | other unbounded specifiers carry the same class of risk (`transformers>=5.13`, `soundfile>=0.12`, …) | recorded |
| C9 | nit | README said the codec tests are "skipped where ffmpeg is absent"; the branch now fails instead | corrected (`d6153b8`) |

## Verified sound by this seat

README install syntax matches the extras; lock format version/revision/requires-python consistent
with the base and with `pyproject.toml`; lock closure complete (no dangling deps); `soxr` vs
`librosa.resample` bit-identical on a real 115.5 M-sample corpus `.m4a`; `-rf64 auto` reproduced
exactly (plain WAV capped at 536 870 911 of 556 800 000 frames with ffmpeg exiting 0; RF64 reads
back); decode byte-identical to ffmpeg's f32le output; missing-ffmpeg raises `ASRDependencyError`
naming the binary; hotword list is 33 entries and matches the doc's claims; no `funasr` in tracked
prose except history.
