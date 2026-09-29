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
seat: runtime-code
---

# Seat A — ASR runtime code (PR #20)

Pinned diff pack `diffpack-core.txt` (sha256 `b0f0eb1d515e39dd`), base `1f2dcd0`, head `b43234b`.
Read-only in the repository; experiments on the WSL target host.

## Claim verdicts

| Claim | Verdict |
|---|---|
| new path bit-identical to ffmpeg's f32le output | confirmed (max abs diff 0.0, `array_equal` True) |
| `soxr` bit-identical to `librosa.resample` default | confirmed on the common prefix; **length differs by 1** for non-integral ratios because librosa's `fix=True` pads to `ceil` (n=89088 gives 32323 vs 32322, the extra sample being exactly 0.0) |
| either stdin guard alone suffices | confirmed by independent mutation matrix; only removing both fails |
| `-rf64 auto` prevents the silent 4 GiB truncation | confirmed end to end |

## Findings

| # | Sev | Finding | Disposition |
|---|---|---|---|
| A1 | must-fix | lock pulls PyPI CUDA torch 2.14.0 + 20 NVIDIA packages (~3.3 GiB) and numpy 2.5.3, against `pyproject.toml:39-44` and `README:15-17` | **reverted** (`902879c`); hazard registered as `· R7` |
| A2 | should-fix | `AudioDecodeError` docstring promised "truncated" coverage; a faststart `.m4a` cut to 30–90 % decodes silently short (measured 53.9/41.6/29.4/17.1 s of 60 s, exit 0) | docstring corrected (`d6153b8`) |
| A3 | should-fix | scratch WAV needs the whole decode in `TMPDIR` (220 MiB for 600 s, 4.15 GiB for the docstring's own example) | documented; see also driving-session F1 |
| A4 | should-fix | `subprocess.run` has no `timeout=`, so a FIFO or stalled FUSE/WebDAV input blocks forever | recorded as an open limit |
| A5 | nit | `_materialize_input`'s comment says its child-ffmpeg reason is obsolete; this branch made it live again | comment corrected after reproducing the descriptor failure (`d6153b8`) |
| A6 | nit | temp file passed by path, unlike `audio.py`'s `O_NOFOLLOW`/`pass_fds` convention | recorded, not changed |
| A7 | nit | `soxr` is in the eager guard though only the non-16 kHz branch calls it | recorded, not changed |
| A8 | nit | `numpy` is imported by shipped code and declared nowhere | recorded, not changed |

## Verified sound by this seat

Temp file always removed on every path (mode 0600, unpredictable name); no caller value can become
an ffmpeg flag; NUL/newline/373-char/leading-dash paths behave and none leaks into the message;
taxonomy consistent, `_safe_error_code` records the bare class name; the reader guard covers
everything `transcribe` imports; mono/stereo/6-channel collapse correctly before `soxr`; peak RSS is
**lower** than the old path (256 vs 683 MiB for 600 s); the `soxr>=0.5` floor is sound (0.5.0 output
array-identical to 1.1.0).
