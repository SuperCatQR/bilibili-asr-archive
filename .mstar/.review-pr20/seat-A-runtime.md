# Seat A — ASR runtime (adversarial). Seats B and C: see their own files.

Claim verdicts: (1) bit-identical to ffmpeg f32le **confirmed** (max diff 0.0, array_equal True);
(2) soxr == librosa default res_type **confirmed with one exception** — identical on the common
prefix, but librosa's `fix=True` pads to `ceil`, so `n=144001` gives 48001 vs soxr's 48000 and the
corpus's own `n=89088@44100` gives 32323 vs 32322 (the extra tail is exactly 0.0), so "bit-identical"
holds sample-wise but not length-wise for arbitrary n; (3) stdin guards **confirmed** by an
independent mutation matrix (only removing both fails); (4) `-rf64 auto` **confirmed** end to end.

## Findings and dispositions

| # | Sev | Finding | Disposition |
|---|---|---|---|
| A1 | must-fix | Lock pulls torch 2.14.0 + 20 CUDA/NVIDIA packages (~3.3 GiB) and numpy 2.5.3 on the uv path, against `pyproject.toml:39-44` and `README:15-17`. **Independently found by seat C.** | **Fixed by reverting the lock commit** — see below |
| A2 | should-fix | `AudioDecodeError`'s docstring says it covers a "truncated" file, but a faststart `.m4a` cut to 30–90% decodes short with exit 0 and no error, so the class overstates its coverage | Docstring corrected |
| A3 | should-fix | Scratch WAV needs the whole decode in `TMPDIR` (220 MiB for 600 s; 4.15 GiB for the docstring's own 11 600 s example); fails cleanly on a small tmpfs | Documented |
| A4 | should-fix | `subprocess.run` has no `timeout=`, so a FIFO or stalled FUSE/WebDAV input blocks forever (measured >40 s, no return) | Documented as an open limit, not fixed |
| A5 | nit | `_materialize_input`'s comment says the child-ffmpeg reason is obsolete and the step "may be removable"; this branch reintroduced a child ffmpeg, and the seat demonstrated the descriptor cannot be handed to it (`close_fds=True`) | Comment corrected |
| A6 | nit | The temp file is passed by path rather than by fd, unlike the repo's own hardened convention in `audio.py` (`O_NOFOLLOW`, `pass_fds`) | Recorded, not changed |
| A7 | nit | `soxr` joined the eager guard but is only called on the non-16 kHz branch, so a 16 kHz-only host that used to work now cannot | Recorded, not changed |
| A8 | nit | `numpy` is imported by shipped code and declared nowhere (arrives transitively) | Recorded, not changed |

Verified fine: temp file always removed on every path (mode 0600, unpredictable name);
no caller value can become an ffmpeg flag; NUL/newline/373-char/leading-dash paths all behave and
none leaks into the message; error taxonomy consistent and `_safe_error_code` records the bare class
name; the reader guard covers everything `transcribe` imports; mono/stereo/6-channel all collapse
correctly before soxr; peak RSS is **lower** than the old path (256 vs 683 MiB for 600 s); the
`soxr>=0.5` floor is sound (0.5.0 output array-identical to 1.1.0).

## The convergence on A1/C1

Two seats working different domains — runtime code and dependency contract — each reached the
torch-in-lock defect independently, and both graded it must-fix. The driving session reproduced it
directly: the lock's `torch` entry carries `source = { registry = "https://pypi.org/simple" }` with
`files.pythonhosted.org` wheels, i.e. exactly the index-resolved build that `pyproject.toml:42-44`
and `README:16-17` exist to prevent, on the host whose ROCm recipe the whole GPU verification rests
on. The seat's arithmetic (3.3 GiB against 367 MiB, 20 CUDA/NVIDIA packages) is consistent with the
package list the session read out of the lock.
