# Findings from the driving session (NOT from a review seat)

Recorded here rather than applied to the tree, because the three review seats are reading that tree
right now and would have seen a moving target. Each entry states its evidence.

## F1 — the temp file needs up to ~2.75 GiB of scratch space, and nothing says so (medium)

`_decode_with_ffmpeg` decodes to a temp WAV before reading it. That is a **new** resource
requirement the old path did not have: `librosa.load` -> `audioread` -> `ffmpeg` streamed to a pipe
and never materialised the decoded audio on disk. The code comment justifies the temp file on
memory grounds ("a pipe would cost gigabytes in RAM") and is right about memory, but is silent on
the disk side.

Measured demand for this corpus at 48 kHz stereo float32 (8 bytes/frame pair):

| item | duration | temp WAV |
|---|---|---|
| BV1iddQYQE7D | 7682 s | 2.75 GiB |
| BV1BdtazGEBE | 6395 s | 2.29 GiB |
| BV1vNTqzFEve | 5112 s | 1.83 GiB |
| BV1zz5zzFENq | 3056 s | 1.09 GiB |

Where the temp file lands is decided by `TMPDIR`, which the code never sets or mentions. On the
target host `/tmp` is disk-backed (668 GiB free) so this corpus is fine, but `/tmp` is tmpfs on many
Linux hosts — including this session's own control host, where it is 3.7 GiB — and a RAM-backed
`/tmp` would put a 2.75 GiB file in memory, which is the exact outcome the docstring says it avoided.

**Failure mode is at least clean**, which is why this is medium and not high: verified by mounting a
64 MiB loopback filesystem and pointing `TMPDIR` at it —

    AudioDecodeError: ffmpeg could not decode the audio input:
      [out#0/wav @ ...] Error closing file: No space left on device

a typed error naming the real cause, not a silent truncation. And the `finally` cleanup still held:
no `bili-asr-decode-*.wav` was left behind on either filesystem after that failure.

Proposed (not applied): state the scratch-space requirement in the docstring — magnitude, that
`TMPDIR` decides the location, and that a tmpfs `/tmp` is the case to avoid — and optionally mention
it in the README's decode section. A code-side fallback (choose a disk-backed dir) is NOT proposed:
guessing a writable large directory the way `audio.py` does for its stage is possible, but that is a
design change with its own review, and the failure is legible as it stands.

## F2 — verified claims, for the record (no action)

Reproduced independently while the seats worked, on chosenecho@192.168.3.21:

* "the new path is bit-identical to ffmpeg's own f32le output" — **confirmed**: max abs diff
  `0.00000000` on the mono `probe.m4a` and on two real 48 kHz stereo corpus files
  (`BV1147c6sEKs.p0.m4a` over 42 814 464 frames, `BV1aRTA6mEGF.p0.m4a` over 27 402 240).
* "`soxr` is what `librosa.resample` calls at its default `res_type`" — **confirmed and stronger
  than claimed**: `res_type` defaults to `soxr_hq` in **both** 0.11.0 and 1.0.0, and the outputs are
  bit-identical in both (max abs diff `0.0` for 44.1k->16k and 48k->16k).
* The `-rf64` and `-nostdin` mechanisms were re-confirmed by removing each independently: either
  stdin guard alone suffices, and only removing both restores the failure.

## F3 — without ffmpeg the whole decode surface skips, and the run still looks green (low, but the same shape as R5)

Measured: with a `PATH` that has no `ffmpeg`,

    43 passed, 3 skipped

and the three that skipped are exactly the ones pinning the fallback this branch exists to fix
(`test_a_real_aac_file_is_decoded_through_the_fallback`, `test_a_non_16k_rate_is_resampled_by_the_runner`,
`test_the_ffmpeg_decode_survives_a_piped_quit_key`), each reported as
`SKIPPED ... ffmpeg is not on PATH`.

Skipping is **correct** — a test suite must not fail on a host that lacks an optional binary, and the
skip reason is printed. The risk is only in reading the summary: "43 passed" invites the conclusion
that the decode path is verified when nothing about it ran. That is the same shape as the defect this
branch fixes (R5 shipped with every gate green because no test exercised the real container), and the
same shape as the `uv.lock` defect (a green install path that installed the wrong closure).

Not a must-fix and not proposed as a code change: `ffmpeg` is a declared product requirement
(`AGENTS.md`), so a suite asserting its presence would fail on legitimate dev machines, and raising
the skip to an error would trade one wrong signal for another. The honest disposition is that the
**PR body must say it**, which it now does; and a future iteration's compound round could note the
general pattern — a skip is a third state between pass and fail, and a summary line of
"N passed, M skipped" hides which surface went dark.

Verified while checking this: with ffmpeg present the same suite reports **46 passed, 0 skipped**, so
the three tests genuinely run rather than silently skipping on the verified host.

## F4 — the decode error reports ffmpeg's LAST stderr line, which is the least specific one (low)

`_decode_with_ffmpeg` takes `detail[-1]` as the reason. Measured across real inputs, ffmpeg's last
line is the **generic wrapper** while its first line is the **cause**:

| input | ffmpeg stderr, in order | product reports |
|---|---|---|
| a media file with **no audio stream** | `[0] Output file does not contain any stream` / `[1] Error opening output file <tmp>...` / `[2] Error opening output files: Invalid argument` | `Error opening output files: Invalid argument` |
| a **zero-length** AAC | identical three lines | `Error opening output files: Invalid argument` |
| a missing file | one line: `Error opening input files: No such file or directory` | correct |
| a directory | one line: `Error opening input files: Is a directory` | correct |
| a non-audio file | one line: `Error opening output files: Invalid argument` (already generic) | generic but accurate |

So for the two no-audio cases the operator is told "Invalid argument" when ffmpeg had already said
"Output file does not contain any stream" — which is the difference between "your file is broken" and
"this item has no audio to transcribe", a distinction that matters for an archive whose download
stage can produce a container with only a video stream.

Note the good news in the same output: `[1]` contains the **temp path** and the product does not
report it, because only the last line is used. Changing to `detail[0]` would keep that property
(it also contains no path in every case measured) *and* name the cause. Joining every line would
leak the temp path, so that is the wrong fix.

Proposed (not applied — the review seats are reading this tree): report `detail[0]` rather than
`detail[-1]`, or scan for the first line beginning `Error opening input`. The single-line cases are
unaffected either way, which makes this a low-risk change with a clear before/after.
