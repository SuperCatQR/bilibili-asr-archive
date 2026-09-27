# bilibili-asr-archive

Personal archival CLI for Bilibili UP 未明子 (UID 23191782) ASR transcripts.

Enumerates videos, harvests AI/CC subtitles first, downloads audio only when
needed, runs local Qwen3-ASR, and archives `srt` / `txt` / `md` with a
resumable JSONL manifest.

## Install (editable)

Base metadata/subtitle/audio workflows (Linux or Windows WSL, Python 3.12+):

    python3.12 -m pip install -e ".[dev]"

`ffmpeg` is a **system requirement, not a pip one** — install it alongside Python
(`sudo apt install ffmpeg`, or the WSL equivalent). The download layer uses it to remux the explicit
FLAC streams, and the ASR reader uses it to decode the `.m4a`/AAC the downloader writes, which
`soundfile` cannot open. A host without it fails every `.m4a` with an `ASRDependencyError` naming
the binary; `scripts/check_asr_env.py` is not a substitute, since it checks the GPU stack and would
pass on a host with no `ffmpeg` at all.

Local ASR support is optional. It needs the two Qwen3-ASR checkpoints (next section) and a torch
build the recipe below provides — pip is deliberately told nothing about torch, because the wheel
that works on this host comes from `repo.radeon.com` and not from an index:

    python3.12 -m pip install -e ".[asr]"

### Where the ASR checkpoints live

Nothing is vendored and nothing is fetched at run time. Both checkpoints live in the product
directory, ignored by git:

    bilibili-asr-archive/models/Qwen3-ASR-1.7B-hf/           # the decoder: text, no timings
    bilibili-asr-archive/models/Qwen3-ForcedAligner-0.6B-hf/ # the aligner: per-character timings

    export BILI_ASR_MODEL=$PWD/models/Qwen3-ASR-1.7B-hf
    export BILI_ASR_ALIGNER_MODEL=$PWD/models/Qwen3-ForcedAligner-0.6B-hf

Fetch them once (~5.9 GB) and verify the digests before trusting them — `huggingface.co` is not
reachable from the ASR host, and `hf download` does not work against the mirror either:
huggingface_hub 1.x uses Xet storage, whose CAS endpoint rejects the mirror's authentication with
`HTTP 401`. Plain HTTP through the mirror is the working route:

    BASE=https://hf-mirror.com
    COMMON="config.json processor_config.json chat_template.jinja tokenizer.json tokenizer_config.json"
    for f in $COMMON generation_config.json model.safetensors; do
      curl -fL -C - --retry 5 -o "models/Qwen3-ASR-1.7B-hf/$f" \
        "$BASE/Qwen/Qwen3-ASR-1.7B-hf/resolve/main/$f"
    done
    for f in $COMMON model.safetensors; do
      curl -fL -C - --retry 5 -o "models/Qwen3-ForcedAligner-0.6B-hf/$f" \
        "$BASE/Qwen/Qwen3-ForcedAligner-0.6B-hf/resolve/main/$f"
    done
    sha256sum models/Qwen3-ASR-1.7B-hf/model.safetensors \
              models/Qwen3-ForcedAligner-0.6B-hf/model.safetensors
    # 2db53c7d81bd9b8cbc6a074e89be2c968a0d373fb4ee68bb1b1e14f7042dfee1  (4 076 193 080 bytes)  decoder
    # 00568245ceca5af1991d28562a75fe1ddc9bfeb041c27fda66947ea05c47fb86  (1 835 545 960 bytes)  aligner

`HF_HUB_DISABLE_XET=1` makes the CLI route work as well. ModelScope serves the same two checkpoints
with the same digests, but throttles large files to roughly 300 kB/s on this host.

### GPU Requirements (AMD 7800XT with ROCm)

Ask the host instead of trusting a command list. Run this from
`bilibili-asr-archive/` — the product directory, not the repository root above
it — with the **same interpreter that holds torch**, which is the venv the
recipe installs into (a `python3.12` probe of the system interpreter reports
`torch-present FAIL` on a correctly built host):

    export VENV=~/.venvs/bili-asr   # the venv that runs bili-asr
    "$VENV/bin/python" scripts/check_asr_env.py

It exits `0` iff all five stages of the verified AMD/WSL recipe hold together,
`1` when any stage fails (printing the fix for each), and `2` for a usage error
(an unrecognised argument; `-h`/`--help` exits `0`):

| # | Stage | Invariant it asserts |
|---|-------|----------------------|
| 1 | `dxg-detection` | `/dev/dxg` exists **and** `HSA_ENABLE_DXG_DETECTION=1` |
| 2 | `rocm-loader-path` | a `/opt/rocm-*/lib` directory is reachable by the dynamic loader |
| 3 | `torch-present` | torch is importable and is a ROCm build (`torch.version.hip`) |
| 4 | `hsa-runtime` | the `libhsa-runtime64.so` in the venv's `torch/lib` is the WSL-compatible system runtime |
| 5 | `device-probe` | a subprocess reports a visible device and its `gcnArchName` (`gfx1101`) |

That check is the only entry point named for "is my GPU usable for ASR". The
verified recipe it asserts — ROCm runtime, ROCDXG transport, the
**repo.radeon.com** torch wheel, the userspace libraries, the loader path, the
WSL-compatible HSA runtime, and `HSA_ENABLE_DXG_DETECTION=1` — plus the three
failure modes measured on 2026-09-12 are in
[docs/wsl-rocm-gpu.md](docs/wsl-rocm-gpu.md). This README deliberately does not
repeat the install commands: the recipe is environment surgery that `docs/`
owns.

**Note**: AMD ROCm uses a CUDA-compatible layer (HIP), so PyTorch still uses
`device="cuda"`. A transcript archived on such a host records that in its own
frontmatter — verify it with

    ARCHIVE=/path/to/your/archive    # the archive root you passed to --archive-root
    grep -n '^asr_device:' "$ARCHIVE"/transcripts/md/*.md

which prints `asr_device: "cuda"`. A glob is required: the markdown bundle is
named `{pubdate}_{bvid}.p{page}_<title>.md`, so there is no `<work_id>.md` to
open. Only `"$ARCHIVE"` is quoted — that keeps an archive root containing spaces
in one word — while `*.md` is left unquoted so the shell expands it into the
bundle filenames `grep` searches.

For CPU-only mode, override device: `BILI_ASR_DEVICE=cpu` (slower, not
recommended for large archives). CPU mode needs none of the five invariants.

For other GPU vendors (NVIDIA, Intel), see the
[PyTorch installation guide](https://pytorch.org/get-started/locally/).

The hardened archive/audio path requires POSIX descriptor operations
(`dir_fd`, `O_NOFOLLOW`, and `/proc/self/fd` or `/dev/fd`). Linux and a
WSL-native filesystem are supported. Native Windows `cmd.exe`/PowerShell paths
are not supported for hardened publication or reclaim; run the CLI inside WSL
and keep the archive on a WSL-native path, not `/mnt/c`.

Set `BILI_ASR_MODEL` and `BILI_ASR_ALIGNER_MODEL` to pre-populated local model directories for
offline use; the defaults are `Qwen/Qwen3-ASR-1.7B-hf` and
`Qwen/Qwen3-ForcedAligner-0.6B-hf`, and neither is fetched at run time. No model weights are
vendored. The optional ASR dependency is verified by fixture-only tests; installation and model
availability remain operator responsibilities.

ASR model construction is lazy and reused only within one sequential `run_batch`
scope. `ASRRunner` is not thread-safe and must not be shared by concurrent callers;
the coordinator releases runners it creates when the batch exits, while an injected
runner remains owned by its caller. `BILI_ASR_MODEL` may be a pre-populated local
path at runtime, but paths are never provenance identifiers. Safe slash-qualified
model identifiers such as `Qwen/Qwen3-ASR-1.7B-hf` are preserved; absolute paths,
URLs, and credential-like model values are redacted. `ASRRunner.provenance()`
exposes deterministic configuration identifiers and an optional declared revision.
It contains no model, media, transcript, or raw exception payloads. Provenance is a
configuration/report surface, not a ledger field and not a semantic-accuracy claim.
The fixture evidence lives in `tests/test_asr_qwen.py`: the cue rules, the chunker's tiling
promise, the runner's construction/attempt contract and the provenance slots, all against a canned
model set with no GPU. Run it directly with:

    python3.12 -m pytest -q tests/test_asr_qwen.py

This fixture does not establish hardware timing, model-weight pinning, network-free
runtime, or full-corpus coverage.

### Reading the audio the downloader writes

`download-audio` writes `.m4a` (AAC). **`soundfile` cannot decode AAC**, so the runner reads with
`soundfile` first and, on `LibsndfileError`, falls back to the **`ffmpeg` binary** — the same
dependency `download-audio` already uses to remux explicit FLAC streams. Practically:

- **`ffmpeg` is required**, and it is what decodes AAC here. It is a platform package rather than a
  pip one, so it cannot be expressed in the `[asr]` extra; a host without it fails on every `.m4a`
  with an `ASRDependencyError` naming the binary. `AGENTS.md` lists it as a requirement.
- The Python side is `soundfile` (reading) and `soxr` (resampling), both declared in the extra.
- A `.wav` or `.flac` archive decodes through `soundfile` and never reaches the fallback.

The fallback is exercised only for containers `libsndfile` cannot open, so a mistake in this path
cannot be caught by a `.wav` fixture. That is exactly how the first repair shipped broken: it routed
the fallback through `librosa.load` on the belief that it reaches `audioread` and then `ffmpeg`, but
`librosa` 1.0 dropped `audioread` and made `load` a bare `soundfile` call — so the fallback re-raised
the very error it existed to catch, on any host built from this repository's own declarations, while
every gate stayed green (residual `iter-2026-09-qwen3-asr-closeout · R5`).

The suite now decodes a **real** AAC file — generated with `ffmpeg` at test time — rather than
stubbing both readers, so a fallback that cannot decode fails the build instead of passing it. When
`ffmpeg` is absent the codec tests **fail** with a named prerequisite rather than skipping: a green
run on a host missing a declared requirement is the same false signal that let the first repair ship,
and this repository has already settled that question for its other prerequisites
(`tests/installed_cli.py`'s "never pytest.skip / xfail" policy).

### Naming the producer: three variables, three jobs

    BILI_ASR_MODEL=/srv/models/Qwen3-ASR-1.7B-hf      # what the loader receives
    BILI_ASR_MODEL_ID=Qwen/Qwen3-ASR-1.7B-hf   # what the archive records
    BILI_ASR_MODEL_REVISION=<pinned-revision>         # optional; loader kwarg + recorded

`BILI_ASR_MODEL` is the checkpoint the loader is given — a hub id or a local
directory — and it is **never** what a transcript records when it is a path.
`BILI_ASR_MODEL_ID` is the operator's *declaration* of the hub-level identity
behind that checkpoint: it never reaches the loader, and it fills the
`asr_model_name` frontmatter slot instead of a key of its own, so the provenance
key set does not change. The declaration is scanned by the same identifier rule
the `model_name` slot already passes, and must additionally be slash-qualified:
a bare name with no `/`, an
absolute path (`/srv/models/...`, `C:\models\...`), a URL, or a
credential-like value is rejected loudly with a non-zero exit rather than
silently recorded, so the archive cannot claim a producer the operator did not
name. The credential rule is separator-aware, not word-bounded: `token=x`,
`token-x` and `token_x` all redact (an underscore is a word character, so a
word-boundary rule would let the last form through), while an ordinary word such
as `tokenizer` is left alone. That rule is shape-based, not path-aware: a
*relative* path-shaped value such as `srv/models/Qwen3-ASR-1.7B-hf` satisfies
it and would be recorded verbatim, so declare the hub identity, not a relative
path.

### The corpus vocabulary, and which engine measured it

`BILI_ASR_HOTWORDS` appends operator-specific terms to the built-in list
(`DEFAULT_HOTWORDS`, comma-separated). The built-ins cover the corpus's Chinese
vocabulary plus the Latin-script terms it speaks — the decoder otherwise
shatters them (measured on the retired FunASR-Nano checkpoint: "International
Employment Matters Tribunal" came out `tryBUNAL` / `FOR EMP LOYMENT MAT TERS`).

**How the list reaches the model changed with the engine.** Qwen3-ASR takes it as free-form `prompt`
context, not as a decode-time bias, so **every measurement quoted below belongs to the FunASR era and
does not carry over unmeasured**: the 95 %-identical with-and-without comparison, the ITEM/AITEM
removal, and the homophone counts were all taken on the retired checkpoint. Re-measuring this list
under the new engine — with hotword *insertions* counted separately from recoveries — is a recorded
work item, and the register already says why it matters: `20260922-proofread-wave · R1` found a token
from the run's own hotword list written into a transcript where the speaker said something else.

The bare acronyms `ITEM` and `AITEM` were **removed on 2026-09-17**, because the
season run measured them doing harm of the kind they were added to prevent: they
pulled acoustically-close English shards onto themselves inside the Hegel quotes
the lectures read aloud (nine occurrences in the 14 archives, e.g. `THE
ITEMthat's the question is anITEM ONE`, `In accessible AITEM distance outside`).
The spelled-out phrase stayed — it appears three times and is genuine each time.
This is what "the list is a prompt bias to be watched" means in practice: the
same mechanism that fixes a shard can capture a neighbouring word, so an entry
earns its place by measurement, not by intent.

The list also carries six terms added 2026-09-17 for a different failure mode:
**exact homophones of common words**, where the decoder's prior beats the audio.
Each was measured wrong far more often than right on the season run's own output
(14 lectures, 25.2 h): `扬弃` 10 correct vs 89 wrong (`阳气`/`洋气` — the central
operation of Hegel's *Logic*, which those lectures read aloud), `自在` 40 vs 13,
`变易` 0 vs 7, `此在` 4 vs 3, `感性` 12 vs 3, `实存` 17 vs 3. The control that
makes this the right lever: the entries already in the list that are equally
homophone-prone are error-free on the same audio (`定在` 145/0, `自为` 34/0,
`理念性` 69/0). Their benefit is likewise **unverified until re-transcribed**.

**The two instruments divide the work, and neither covers the other's class.**
Per-cue confidence catches what the model *doubts*: unclear audio, a language
switch, and hotword interference — the low-confidence cues in that run carried a
median 42.9 % Latin characters against 0.0 % elsewhere, and eight of the nine
acronym captures above were below `LOW_CONFIDENCE`. The list is the only lever
for what the model does *not* doubt: a confident homophone substitution scored a
median 0.776 against 0.812 for the corpus, and only 1 of 78 such cues fell at or
below `LOW_CONFIDENCE`. So an operator hunting a doubtful passage reads
`asr_low_confidence_at` (or `bilibili-asr coverage --quality --format csv`, which
prints every low-confidence position on stderr), and a wrong-but-confident term
is only findable by looking for the term itself. (A transcript the Qwen3-ASR engine wrote carries
no scores at all, so it has no such list — see the provenance section below.)

path. Declaring an id that contradicts an already-safe hub-level `BILI_ASR_MODEL`
is also an error — one of the two would be a lie. A `BILI_ASR_MODEL` that
resolves to a directory on this machine is a checkpoint path whatever its
spelling, so the documented relative form beside a truthful declaration is
accepted rather than refused.

Re-run the D4.5 load check on another host with
`python3.12 scripts/probe_target_host_load.py`: it performs a real load twice
(with and without `BILI_ASR_MODEL_REVISION` declared), prints the loader kwargs
it observed, and exits non-zero unless both arms load. `BILI_ASR_PROBE_SOURCE`,
`BILI_ASR_PROBE_SLICE` and `BILI_ASR_PROBE_SECONDS` override its example inputs;
its default source path names the documented WSL2 ASR host's layout, not yours.

With no declaration, `asr_model_name` keeps a configured id only when that id is
itself redaction-safe, and is `[redacted]` otherwise: a local checkpoint
directory records `[redacted]`, because a path is not an identifier. Read back
what an archive recorded with

    ARCHIVE=/path/to/your/archive    # the archive root you passed to --archive-root
    grep -n '^asr_model_name:' "$ARCHIVE"/transcripts/md/*.md
    grep -n '^asr_model_revision:' "$ARCHIVE"/transcripts/md/*.md

The same glob rule as above applies: `"$ARCHIVE"` is quoted, `*.md` is not.

An ASR transcript also records what the run measured — how much audio the cues
cover, which aligner produced their timings, and how the audio was cut into
windows. Only the capture family is source-gated: a subtitle-sourced row records
none of these keys, exactly as it records no other `asr_*` key.

    grep -n '^asr_vad_' "$ARCHIVE"/transcripts/md/*.md
    grep -n '^asr_aligner_model:' "$ARCHIVE"/transcripts/md/*.md
    grep -n '^asr_chunk_seconds:' "$ARCHIVE"/transcripts/md/*.md
    grep -n '^asr_low_confidence_at:' "$ARCHIVE"/transcripts/md/*.md   # written by the old engine

`asr_vad_segments` (count), `asr_vad_captured_s` (seconds) and
`asr_vad_captured_ratio` (`captured_s / duration_s`, clamped to `[0, 1]`)
describe the stretches of audio the transcript actually covers; touching,
overlapping and cues at or below the cue builder's 1.0 s pause threshold count as one
stretch, so the numbers are an acoustic estimate rather than a punctuation
census. The seconds stay unclamped, and the ratio is omitted — not guessed —
when the row's own `duration_s` is not a positive finite number, which leaves a
duration/cue contradiction visible instead of smoothing it away.
Recompute them from the raw sidecar alone: sort the `segments` intervals larger
than zero length, fuse any two whose start is at or below the previous end plus
1.0 s, then take the span count, the summed duration (3 decimals) and
`min(1.0, captured_s / duration_s)` — a zero-length cue describes no captured
audio and is skipped, which is what makes the recompute exact.
`asr_aligner_model` names the checkpoint that produced the cue timings
(`Qwen/Qwen3-ForcedAligner-0.6B-hf` on this host), and `asr_chunk_seconds` is the window the audio
was cut into for decoding and alignment — 180 s by default, `BILI_ASR_CHUNK_SECONDS` to override.
The chunker cuts at a low-energy boundary and the chunks tile the recording exactly: no overlap, no
gap, nothing dropped. That is what lets a cue's timings be read as positions in the original audio,
and it is checked by `tests/test_asr_qwen.py` rather than asserted here.
`asr_low_confidence_at` is the JSON list of start seconds whose cue scored at or
below the archived low-confidence threshold, ascending, 3 decimals, duplicates
kept. It is emitted together with `asr_low_confidence_cues` under one rule: both
are present whenever the transcript carries any score — `0` and `[]` when no cue
is at or below the threshold — and neither is written when it carries none.
Because the list names where the doubts are, the count and the list cannot
disagree, and a reader can recompute both from the raw sidecar's `segments`.

**A transcript the Qwen3-ASR engine wrote carries no scores, so neither confidence key is written
for it.** That is the pre-existing rule — no score, no keys — not a new one, and it is why the
`raw` sidecar's segments have no `confidence` field on those rows. Transcripts archived before the
engine change still carry both keys, every reader in this repository keeps reading them, and
`coverage --quality` reports low-confidence positions whenever a row has them and stays silent when
it does not.
The list is one entry per low cue, so that single frontmatter line grows with
the cue count — linearly, and always smaller than the body it summarises,
which repeats every cue's text.

A per-item `bili-asr asr --bvid <bvid>` loop forfeits that reuse: it is one
process per video, and the run-scoped reuse above does not cross a process
boundary, so every invocation builds its own model before it transcribes
anything. For more than a couple of items, prefer one bounded batch command,
`bili-asr run --scope pending [--offline]`, which holds a single runner across
the items it processes; `schedule` and `campaign` are bounded wrappers that call
that same coordinator batch (`--limit N` is required on both). This is a
property of one process, not of one command: a single
`bili-asr asr --pending --limit N` invocation also holds one runner across its
whole selection, so it is the per-item loop above, not the `asr` command, that
forfeits the reuse.

A batch that paid for a model or transcribed an item states it once, on
**stderr**: `<command>: model constructions=<n> for <m> asr item(s)`, where
`<n>` is the model constructions that batch itself paid and `<m>` the items it
transcribed — for a three-item `run` that line is
`run: model constructions=1 for 3 asr item(s)`. `<command>` names the
invocation (`run`, `schedule`, `campaign`, `asr`, or `pilot`), because
`schedule` and `campaign` share the coordinator's batch entry. The line is a
diagnostic and never stdout: `campaign`'s stdout is a single JSON document that
downstream callers parse and `run`'s stdout is its row report, so piping stdout
to a file leaves this line on the terminal instead of in the file.

The rule is "nothing was paid", not "no items were transcribed": when a batch
built the model and then failed every transcription — the GPU, ROCm or
checkpoint failure the line exists to expose — it still prints, with a zero
denominator, as in `run: model constructions=1 for 0 asr item(s)`. A batch that
neither constructed a model nor transcribed anything may still print a
diagnostic: when every model load failed, stderr shows
`<command>: model load failed <n> time(s), 0 transcripts produced`, where `<n>`
is the number of failed attempts. This makes repeated configuration errors
(wrong path, missing checkpoint) visible instead of silent. A subtitle-only
batch (no ASR attempts at all) prints nothing. If stderr is closed, the line is
dropped rather than redirected, so `campaign`'s stdout stays one parseable JSON
document.

The printed count counts **successful constructions**, and a load the factory
rejected pays none of them. Such a load leaves no model behind, so the next row
retries the same load: an N-row batch whose every load fails performs up to N
attempts and prints the failure diagnostic above. The retry is **bounded**:
after `MAX_MODEL_LOAD_ATTEMPTS` failed loads a runner stops calling the loader
and raises instead, so a systematically broken configuration (a wrong path, a
missing checkpoint) costs at most that many attempts rather than one per
remaining row. The cap counts *attempts*, not rows, and no refused call
increments the counter — `model_load_attempts` still counts every loader
invocation, so `model_load_attempts - model_constructions` remains exactly the
number of failed loads the run paid for. Per-row failures are also reported
(`run: <work_id>: failed (ASRModelError)`, `<work_id>: archive
failed (ASRModelError)`), and both paths name the exception class beside the
row, so a failure an operator can act on is not just the words `archive failed`.

A malformed declaration is refused **before the first row** on the `asr` path:
the command reads the environment knobs once at entry, prints the `ValueError`'s
own message — the variable's name, and for a contradiction the two values — and
exits 1 without archiving anything. The per-row failure line above remains the
backstop for a row that fails later for another reason.

The attempt count is recorded on `ASRRunner.model_load_attempts`,
beside the construction counter. It counts every factory invocation, successful
or not, so `model_load_attempts - model_constructions` is exactly the number of
failed loads a run paid for, and `model_load_attempts >= model_constructions`
always holds (equal when every load succeeded). It is visible to the operator
through the failed-load diagnostic above, and to a caller that holds the runner
directly through the counter attribute. The reuse count and historical attempt
count are **real-time diagnostics only**: they are not recorded in
`campaign.json`, `run-ledger.jsonl`, or any persistent evidence. An operator
monitoring a long run sees them on stderr; historical analysis uses per-row
outcomes instead.

### An archive can hold two engines' text, and that is decided, not broken

Recorded 2026-09-26 for the reader who greps a transcript and finds an `asr_model_name`
they did not expect (decision D12, plan `20260924-qwen3-asr-transformers`).

The ASR engine is a hard switch: the boundary that ran FunASR was replaced by Qwen3-ASR
plus the forced aligner in one unit, and the archive was **not** re-transcribed. The three
parts already archived in `/mnt/e/asr-archive-20/` therefore still carry
`asr_model_name: FunAudioLLM/Fun-ASR-Nano-2512`, while every transcript produced after the
boundary rebuild carries `Qwen/Qwen3-ASR-1.7B-hf` — commit `2548ca9` (2026-09-24 23:27),
merged to `main` as `3b561ea` on 2026-09-25:

    grep -n '^asr_model_name:' /mnt/e/asr-archive-20/transcripts/md/*.md

These three — `BV1P8No6mEsB`, `BV1S8hA6MEvy`, `BV1fD3o69EiP` — are **accepted as they
stand**, by operator decision, and are not a defect and not a backlog item. Re-running
them would buy a newer model's text at the cost of transcripts that record what the
retired engine actually produced, and it would destroy the evidence that the two engines
can be told apart from the frontmatter alone.

They are not the only such files. The retired checkpoint's id appears in **22 transcript
files across the ASR host's seven archive roots** (checked 2026-09-26: 14 under
`/root/e2e-asr/e2e50`, three under `/mnt/e/asr-archive-20`, five under the
`ab-hotwords*` experiment roots) — most of them measurement arms from before the switch,
kept because they are the FunASR side of comparisons that have already been run. The rule
is the same for all of them: each records the engine that wrote it, so a reader is never
guessing, and none is scheduled for re-transcription. Nothing in this archive is
assembled from two engines' text inside one transcript.

What this costs, stated plainly: the two engines' outputs are **not comparable
token-for-token**, so any corpus-wide measurement that spans the boundary is measuring two
different decoders. The hotword list is the sharpest instance — every figure in
"The corpus vocabulary, and which engine measured it" above belongs to the retired
checkpoint, which is why that section says so and why re-measuring under the shipping
engine is its own work item rather than an assumption.

## Deterministic verification baseline

Run the supported baseline from `bilibili-asr-archive/` with Python 3.12. The
repository supplies a reviewed empty snapshot fixture; before an operator run,
prepare the reviewed, curated local wheel directory (`/path/to/reviewed-wheels`) containing exactly the complete dependency closure (one compatible wheel per distribution, including build, runtime, and `dev` requirements):

    python3.12 scripts/prepare_offline_baseline_fixture.py --wheel-source /path/to/reviewed-wheels --output .offline-baseline
    python3.12 scripts/verify_baseline.py --offline-packages .offline-baseline --advisory-snapshot tests/fixtures/advisories-empty.json

The baseline creates a disposable isolated virtual environment, installs the
local package with its declared `dev` extras using only the specified local
package source (`PIP_NO_INDEX=1`), runs the installed `bili-asr --help` proof,
then runs the complete product pytest suite from a staged test and documentation tree; installer self-tests (`test_cli_help.py`, `test_installed_cli.py`, and `test_verify_baseline.py`) are intentionally excluded because they provision the verifier and would recurse. During pytest it installs a process-level Python socket API deny guard: calls through `socket.create_connection`, `socket.socket.connect`, or `connect_ex` in that pytest interpreter raise before reaching the OS. This is not a host or kernel firewall, and it does not claim to block non-Python processes or every possible networking mechanism.
It also strips `PYTHONPATH`, proxy variables, and `BILI_SESSDATA`; it never
calls Bilibili, downloads a model, transfers media, or prints environment
values. Its compact machine-readable result is
written to `verification-results/baseline.json` and is deliberately gitignored.

### Security-audit policy

Security inspection is deliberately offline and fails closed. The baseline uses
only a reviewed, versioned local advisory snapshot; it does not invoke
`pip-audit` or query a live advisory database. Each advisory's PEP 440
`specifier` is checked against the installed distribution version. Unsupported
specifiers and missing required inputs return exit `2` with
`status: prerequisite_failed` in the JSON result. Audit findings fail the
baseline and must be evaluated in a separate remediation plan with evidence—this
baseline does not upgrade dependencies merely to silence an audit.

For a deterministic repository proof, the guarded developer command constructs
the disposable local offline package set and runs the exact command above:

    python3.12 scripts/prepare_offline_baseline_fixture.py --wheel-source /path/to/reviewed-wheels --output .offline-baseline --run

Generated output is redacted and bounded: no credentials, signed URLs, raw
exceptions, model artifacts, media, archive data, or environment dumps belong
in committed files or CI artifacts.

## Workflow

The ASR chain's data flow — audio → chunker → the two checkpoints → mark threading → cues →
products and the store — is drawn in [`docs/asr-pipeline.html`](docs/asr-pipeline.html), a
self-contained interactive diagram whose source is [`docs/asr-pipeline.dataflow.json`](docs/asr-pipeline.dataflow.json).

⚠️ **The `probe-subs` / `harvest-subs` pair writes to `archive.db`, not to the
manifest; `bili-asr derive-manifest` is what carries that store's audio queue
across.** The ASR/pilot chain
(`download-audio`, `asr`, `pilot`, `run`, `schedule`, `campaign`) is still driven
from `manifest/manifest.jsonl`, and `harvest-subs` still marks no rows
`needs_audio` itself: `derive-manifest` appends a `needs_audio` row for every
stored part that holds no transcript and is not `gone`, so
`download-audio --missing-subs` now does gain entries from the step above it —
additively, and without rewriting a row the chain already holds. What still does
not cross: `asr --pending` does not see the stored transcripts, and no SRT/TXT/MD
projection is rebuilt from them. Run the subtitle step and the derivation for the
SQLite archive itself; the legacy chain keeps its own harvest (see the boundary
bullet under
[Subtitle acquisition on SQLite](#subtitle-acquisition-on-sqlite-probe-subs--harvest-subs)
and the [derived audio queue](#derived-audio-queue-bili-asr-derive-manifest)).

    bili-asr fetch-meta --mid 23191782 --archive-root archive
    bili-asr probe-subs --limit-parts 5 --archive-root archive
    bili-asr harvest-subs --limit-parts 5 --archive-root archive
    bili-asr derive-manifest --archive-root archive
    bili-asr download-audio --missing-subs --archive-root archive [--artifact-root <path>]
    bili-asr asr --pending --archive-root archive [--artifact-root <path>] [--keep-audio | --no-keep-audio]
    bili-asr status --archive-root archive
    bili-asr runs --limit 10 --archive-root archive
    bili-asr pilot --n 20 --archive-root archive [--artifact-root <path>] [--keep-audio | --no-keep-audio]
    bili-asr search "黑格尔 辩证法" --archive-root archive [--artifact-root <path>]
    bili-asr export --format json --out archive/manifest.json --archive-root archive [--artifact-root <path>]
    bili-asr coverage --archive-root archive [--artifact-root <path>]
    bili-asr coverage --trusted-local --archive-root archive
    bili-asr coverage --quality --archive-root archive [--artifact-root <path>]
    bili-asr run --scope pending --archive-root archive [--artifact-root <path>] [--keep-audio | --no-keep-audio]
    bili-asr run --scope pending --offline --archive-root archive
    bili-asr run --scope failed --limit 5 --archive-root archive
    bili-asr schedule --scope pending --limit 20 --archive-root archive [--artifact-root <path>] [--keep-audio | --no-keep-audio]
    bili-asr schedule --scope pending --limit 20 --resume --archive-root archive
    bili-asr campaign --scope pending --limit 20 --archive-root archive [--artifact-root <path>] [--keep-audio | --no-keep-audio]
    bili-asr verify --archive-root archive [--artifact-root <path>]
    bili-asr verify --trusted-local --archive-root archive
    bili-asr recover --archive-root archive --work-id <work-id> [--artifact-root <path>]
    bili-asr evaluate-concurrency --evidence evidence.json --thresholds thresholds.json

Bracketed groups are the **optional** flags: `[--artifact-root <path>]` on the
eleven commands that resolve an artifact path, and `[--keep-audio |
--no-keep-audio]` on the five that archive rows and therefore reclaim audio
(see [Where the artifacts go](#where-the-artifacts-go) and
[Audio retain, reclaim and the disk cap](#audio-retain-reclaim-and-the-disk-cap)).
The seven commands without either bracket — `fetch-meta`, `status`, `runs`,
`probe-subs`, `harvest-subs`, `derive-manifest` — deliberately do not declare
them: each resolves no artifact path, and an accepted-but-ignored flag would be a
false statement in the interface.

Every `--bvid` command example in this README carries a real video id, so those
are paste-ready as they stand. The `<bvid>` placeholder survives in exactly one
place: the `bili-asr asr --bvid <bvid>` form quoted in the reuse note above,
written the way `scripts/check_asr_env.py` prints it. Usage synopsis lines (such
as `run --scope pending|failed|<work_id>...`) are argument grammar, not commands
to paste. A shell reads a bare `<word>` as redirection, so substitute your own
value before running any line that still carries one.

### Where the artifacts go

By default there is **one root**: `--archive-root`. Every product — audio,
transcript bundles, harvested caption documents — is written below it, and the
manifest's lines are exactly what they have always been.

`--artifact-root <path>` (or `BILI_ARTIFACT_ROOT`) names a **second root for the
products only**, so a mounted drive can hold the bytes while the state stays on
local disk:

```
--artifact-root <path>   (non-blank)  -> use it
else BILI_ARTIFACT_ROOT  (non-blank)  -> use it
else                                  -> the archive root (today's behaviour)
```

- **Products move; state does not.** `audio/`, `transcripts/{srt,txt,md,raw}/` and
  `subtitles/raw/` are written under the configured root. `manifest/`,
  `archive.db`, `coordinator/`, `meta-cursor.json`, `scheduler.json`,
  `run-ledger.jsonl`, `campaign.json` and `search.db` stay at the archive root —
  the manifest's per-append fsync pair and SQLite's locking are exactly what a
  FUSE/WebDAV mount cannot carry.
- **The configured root must already exist.** A missing root is refused with
  `artifact root does not exist (<path>)` and exit 1; it is never created. An
  unmounted FUSE mount point still exists as an empty directory, so auto-creating
  a missing one would publish products to the underlying filesystem instead of the
  mount. Whether the mount is actually up is the operator's check, not the
  pipeline's.
- **A blank value is unset** at either level (`export BILI_ARTIFACT_ROOT=` cannot
  shadow a real flag), `~` is expanded, a relative value resolves against the
  current directory, and the path is kept lexical — so a **symlinked root is
  refused**; pass the real path.
- **An existing archive keeps working, and nothing is migrated for you.** Reads
  probe the configured root and then the archive root, first hit wins, so rows
  written before the switch still resolve. Moving historical artifacts is your
  own `mv`/`rclone`; the tool never copies between roots. Recorded paths stay
  root-relative and the manifest is never rewritten.
- **One artifact root per archive root** is the supported configuration: the
  writer lock stays archive-root-scoped and no second lock is added.

The four refusal lines, the full validation table and the rollback path are in
[docs/artifact-root.md](docs/artifact-root.md).

### Concurrency safety evidence gate

`bili-asr evaluate-concurrency --evidence <json> --thresholds <json>` is a
read-only, pure evidence evaluation surface. Its public Python API is
`ConcurrencyGate.evaluate(evidence: Mapping[str, object], thresholds: Mapping[str, object]) -> GateResult`;
`GateResult.to_dict()` returns the report mapping. A `go` decision is evidence
only for a future, separately approved plan. Production remains
`sequential-no-daemon`: this command does not start or enable a worker, daemon,
service, automatic startup, concurrent manifest writer, or alternate scheduler.
It changes no manifest schema, status taxonomy, risk taxonomy, or default.

Both inputs must be JSON objects no larger than 1 MiB. The evidence object has
exactly these required fields:

- `schema_version`: `concurrency-gate-evidence-v1`.
- bounded, non-empty ASCII `campaign_snapshot_id`.
- positive integer `campaign_item_count`, `campaign_denominator`, and
  `reconciliation_denominator`; item count must not exceed the campaign
  denominator, and reconciliation denominator must equal it.
- nonnegative integer `age_seconds`, finite nonnegative
  `throughput_items_per_hour`, `[0,1]` finite `api_risk_rate`, nonnegative
  integer `peak_disk_bytes`, and `[0,1]` finite `reclaim_rate`.
- boolean `crash_restart_passed`, nonnegative integer
  `duplicate_work_count`, positive integer `max_owner_count`, boolean
  `checkpoint_reconciled`, and boolean `risk_taxonomy_unchanged`.
- `write_isolation`, an object containing exactly five keys, each strictly
  `true`: `manifest`, `sidecars`, `attempts`, `index`, and `artifacts`.

The threshold object has exactly these required fields:
`min_campaign_item_count` (positive integer), `max_evidence_age_seconds`
(nonnegative integer), `min_throughput_items_per_hour` (finite positive
number), `max_api_risk_rate` (`[0,1]` finite number),
`max_peak_disk_bytes` (nonnegative integer), `min_reclaim_rate` (`[0,1]`
finite number), `max_duplicate_work_count` (nonnegative integer), and
`max_owner_count` (positive integer). Operators supply measured, reviewed
thresholds; this project does not guess values from CPU, memory, or disk.

Safe fixture shapes (illustrative values only, not recommended production
thresholds) contain no credentials or real URLs:

```json
{"schema_version":"concurrency-gate-evidence-v1","campaign_snapshot_id":"fixture-campaign-001","campaign_item_count":10,"campaign_denominator":10,"reconciliation_denominator":10,"age_seconds":30,"throughput_items_per_hour":5.0,"api_risk_rate":0.01,"peak_disk_bytes":1000,"reclaim_rate":0.9,"crash_restart_passed":true,"duplicate_work_count":0,"max_owner_count":1,"checkpoint_reconciled":true,"risk_taxonomy_unchanged":true,"write_isolation":{"manifest":true,"sidecars":true,"attempts":true,"index":true,"artifacts":true}}
```

```json
{"min_campaign_item_count":10,"max_evidence_age_seconds":3600,"min_throughput_items_per_hour":4.0,"max_api_risk_rate":0.02,"max_peak_disk_bytes":2000,"min_reclaim_rate":0.8,"max_duplicate_work_count":0,"max_owner_count":1}
```

The report schema is `concurrency-gate-report-v1` with deterministic keys:
`decision` (`go` or `no-go`), `ok`, `operating_mode`
(`sequential-no-daemon`), sorted unique `reason_codes`, and `schema_version`.
Schema, field, contradiction, threshold-breach, isolation, sensitive-data, and
input-complexity failures are represented by stable reason codes. Exit `0`
means `go`; exit `1` means `no-go` or input/evaluation failure. CLI failures
are compact JSON on stderr with `operating_mode: sequential-no-daemon` and one
of: `input_file_missing`, `input_file_unreadable`,
`input_file_not_regular`, `input_file_oversized`, `input_invalid_utf8`,
`input_malformed_json`, `input_non_object_json`, or `evaluation_failure`.
Paths, exception text, and input values are never emitted.

### Archive writer isolation

Every archive-mutating command (`fetch-meta`, `recover`, `asr`, `pilot`,
`harvest-subs`, `derive-manifest`, `download-audio`, `run`, `campaign`, and
`schedule`) holds one archive-root writer lock from initial state load through
its final state/sidecar write. A second mutation exits `1` with
`<command>: archive_busy`; it does not wait or partially mutate the archive.
Read-only commands such as `status`, `coverage`, `verify`, `runs`, `search`,
`export`, `probe-subs`, and `evaluate-concurrency` do not claim this writer
lock: `probe-subs` writes nothing at all on the SQLite subtitle path.

### Audio retain, reclaim and the disk cap

Once a row reaches `archived`, its local audio file under `{artifact-root}/audio/`
is **kept**. That is the default: audio is the only copy of a recording Bilibili
may delete, and re-downloading it later is the expensive way to get it back.
(Failed and in-progress rows always kept their audio for retry; the manifest
records the relative `audio_path` either way.)

**Reclaiming is now the opt-in.** The five commands that archive rows — `asr`,
`pilot`, `run`, `schedule`, `campaign` — carry a retention pair, resolved once at
the command boundary and passed down as a value:

| Setting | Effect |
|---|---|
| *nothing set* | **keep** — the default |
| `--keep-audio` | keep |
| `--no-keep-audio` | reclaim: the row's audio is removed where it is, under either root |
| `BILI_KEEP_AUDIO=1` | keep |
| `BILI_KEEP_AUDIO=0` | reclaim |
| `BILI_KEEP_AUDIO=` anything else (including blank) | **keep** — the default |

The flag wins over the variable; the variable only matters when the flag is
absent. `BILI_KEEP_AUDIO=" 1 "` is *not* a literal `1`, so it means the default
(keep) — the shipped `== "1"` comparison it replaces would have read it as unset
and reclaimed. Reclaim runs only when the resolved policy asks for it, and it
looks for the row's audio under both roots: "do not keep this row's audio" means
the copy, wherever it is. Audio already reclaimed cannot be restored.

Download publication and reclaim are anchored to an opened `audio/` directory 
and use private random stage/quarantine entries; they never follow a swapped 
final-name symlink to an outside victim.

#### Transcript bundle publication

An archive generation is exactly four files: `transcripts/srt/<stem>.srt`,
`transcripts/txt/<stem>.txt`, one `transcripts/md/*.md`, and
`transcripts/raw/<stem>.json`. `<srt>.bundle-ready` is published last and names
those exact four relative paths with their SHA-256 digests. Readers accept only
a complete marker-matched generation; a partial or mixed generation remains
retryable and cannot justify `status=archived`.

Publication precedes the manifest transition. If all four files and the marker
are complete but the manifest append fails, the row stays at its prior status,
the complete bundle stays readable, and the next sequential run republishes or
commits it. Older `archived` rows without `raw_path` or a matching marker are
pre-marker evidence and must be re-archived before they count as complete.

`pilot`, `run`, `schedule` and `campaign` honor a bounded-disk campaign cap:

    bili-asr pilot --n 20 --max-audio-gb 10 --max-duration-min 45 --archive-root archive
    bili-asr run --scope pending --max-audio-gb 10 --archive-root archive
    bili-asr schedule --scope pending --limit 20 --max-audio-gb 10 --archive-root archive
    bili-asr campaign --scope pending --limit 20 --max-audio-gb 10 --archive-root archive

- `--max-audio-gb` (default 10, `0` = unlimited): before each audio
  download, the **configured root's** `audio/` usage plus a conservative estimate
  (`duration_s` × 64 kbps) is checked; a candidate that would breach the
  cap is **skipped with reason `audio_budget`** and the batch continues.
  Legacy audio still sitting at the archive root is not counted — the cap
  measures the configured root's `audio/`, which is where new bytes land.
- **The cap and retention interact.** Retained audio is never deleted, so
  `audio/` only grows and a long corpus run eventually reports every later row as
  a budget skip. That is the cap doing its job, not a failure, and the line that
  reports it names the flag that lifts it — on `run` and on `pilot`, which print
  the clause `audio-dir budget cap reached (--max-audio-gb 0 = unlimited)`.
  `schedule` prints the bare reason (`schedule: <work_id>: skipped
  (audio_budget)`) and `campaign` reports `audio_budget` only as a
  `reason_codes` entry, so an operator who means to keep the audio and keep
  downloading passes **`--max-audio-gb 0`** — except with
  `schedule --allow-long-live`, which requires a configured cap and refuses `0`.
  The shipped default is unchanged; the retention default is what moved.
- `--max-duration-min` (pilot only, default 45, `0` = unlimited):
  excludes long items (e.g. multi-hour livestreams) from selection.

Subtitle access that requires login can use `BILI_SESSDATA` or the
`--sessdata` flag (cookie **value**, not a file path). Credentials are sent as
API cookies only and are never echoed or written to the manifest or output
files.

`bili-asr pilot --n N` (default 20) selects a bounded mix from `meta_ok` (and
still-processable `subtitle_done` / `needs_audio` / `audio_ok` for resume),
preferring short `duration_s` and reserving both branches when those statuses
already exist. Each selected row harvests subtitles first: a subtitle hit is
archived with `source=subtitle` and no ASR; a miss downloads audio, runs local
Qwen3-ASR, and archives with `source=asr`. Multi-part bvids include every
pagelist `work_id`. The summary prints branch counts and terminal states.
Missing subtitle or audio-asr coverage exits 1 and names the missing branch.
A completed rerun skips work already `archived`. Missing optional ASR exits
non-zero with `pip install -e "bilibili-asr-archive/[asr]"` and does not mark
the row archived.

### Operational run ledger (`run-ledger.jsonl`)

Every `pilot` / `run` / `schedule` run atomically appends an inspectable run
record to `{archive-root}/run-ledger.jsonl`. The metadata and subtitle CLI
commands record their runs in the fresh SQLite database instead
(`{archive-root}/archive.db`, see
[the fresh-start SQLite archive](#fresh-start-sqlite-archive-fetch-meta--status--runs)).
The ledger is a sidecar file that records execution history and
coverage without altering manifest row schemas or the transport layer.

#### Ledger record schema

Each JSONL line represents one immutable record with the following schema:

| Field | Type | Description |
|-------|------|-------------|
| `run_id` | `str` | Opaque identifier (`run-YYYYMMDDHHMMSS-<token>`). |
| `command` | `str` | Command executed (`pilot`, `run`, `schedule`). |
| `started_at` | `str` | ISO-8601 UTC start timestamp. |
| `finished_at` | `str` | ISO-8601 UTC completion timestamp. |
| `exit_code` | `int` | Process exit code (`0`, `1`, or `2`; `128+signal` — `143` `SIGTERM` / `130` `SIGINT` — when the operator interrupted the run). |
| `mid` | `int \| null` | Target Bilibili mid (if applicable). |
| `work_ids` | `list[str] \| null` | Processed work identifiers (if applicable). |
| `pages_fetched` | `int \| null` | Number of pagination pages fetched. |
| `records_fetched` | `int \| null` | Number of records fetched in the run. |
| `records_existing` | `int \| null` | Number of pre-existing records before run. |
| `last_api_error_code` | `int \| str \| null` | Scalar API response code on failure (never exception text). |
| `coverage_summary` | `dict[str, int]` | Snapshot of manifest `status` counts (`archived`, `meta_ok`, etc.). |
| `cursor_snapshot` | `dict \| null` | Snapshot of `meta-cursor.json` state at run completion. |

Like `meta-cursor.json`, the ledger strictly forbids credentials (`SESSDATA`,
cookies), signed streaming URLs, and raw exception stack traces.

#### Operator inspection

- **`bili-asr status [--archive-root <root>]`** reads the fresh SQLite
  metadata database (`archive.db`): counts of collected users, videos, and
  parts, the `processing_status` breakdown, pending work ids from
  `v_pending_metadata`, and each user's stored enumeration cursor. It exits
  `1` when the database does not exist (`fetch-meta` creates it) and never
  reads the legacy manifest sidecar. For `limited` collection runs, it
  reports the cursor state honestly without claiming complete enumeration.
- **`bili-asr coverage [--quality]`** is a read-only reconciliation and artifact quality report over fixture/local archive evidence. Use a temporary local root and optional scope; it never performs network traffic, model invocation, audio transcoding, or writes to source sidecars:

      bili-asr coverage --archive-root /tmp/bili-asr-coverage-fixture --scope pending --format json
      bili-asr coverage --archive-root /tmp/bili-asr-coverage-fixture --format csv
      bili-asr coverage --archive-root /owned/archive --trusted-local --format json
      bili-asr coverage --archive-root /tmp/bili-asr-coverage-fixture --quality --format json
      bili-asr coverage --archive-root /owned/archive --quality --trusted-local --format json
      bili-asr coverage --archive-root /tmp/bili-asr-coverage-fixture --quality --format csv

  Default `coverage`, `coverage --quality`, and `verify` inspection is
  `bounded_input`: at most 10,000 nonblank JSONL records and 8 MiB total per
  sidecar, with 16 MiB line/object ceilings. Limit breaches are named and make
  the result non-authoritative. `--trusted-local` is an explicit assertion that
  the archive root is operator-owned; it removes only total record/byte ceilings
  and keeps per-record validation, semantic validation, and no-follow path
  checks. It does not make malformed or symlinked input authoritative.

  `bili-asr verify` is the deterministic, read-only integrity check. Recovery is
  an explicit bounded audit request (it does not requeue or execute work):
  `bili-asr recover --archive-root <root> --work-id <work-id>`
  requires an explicit bounded target and writes only redacted audit evidence.
  `--work-id` names exact rows; `--defect-code` selects every currently
  reported row in that defect class. `--limit N` is required to be positive
  and defaults to 100; expansion happens before enforcement, and no command
  may select more than 100 targets (excess selection fails without a write).
  Recovery only appends a bounded, atomically replaced audit sidecar while
  holding a cross-process `fcntl.flock` lock file; it never
  mutates the manifest, attempts, transcripts, or audio. Existing malformed,
  oversized, or full audit evidence fails closed. Exit code 0 means the audit
  was written; exit code 1 means missing/invalid targets, non-authoritative
  source evidence, or any audit-sidecar failure.

`verify`'s default `--format` is `json`, and the payload always carries both
classes — `defect_count` plus `backlog_count`, and a `defects` list whose every
entry is tagged `category: defect | backlog`. The human-readable `backlog:` section is
printed in `--format text` only, so the contract §2 headline ("exit 0 and print
the backlog section") holds on the default invocation through those counts: the
classification is always present in the output, only its rendering differs. Exit
`0` means no defect-class finding and no diagnostic; backlog never moves the exit
code, while `--strict` restores the pre-cutover gate where any finding does.

The denominator is the selected manifest snapshot in work-item units; if the manifest or scope is unavailable, the report says `unavailable` and does not infer a count. `cumulative` describes all selected manifest rows, while `batch` describes only the latest scheduler/ledger batch; they are not interchangeable. `limited` and `risk_interrupted` evidence remains non-complete. Named diagnostics (for example `denominator_unavailable`, `scheduler_ledger_mismatch`, `sidecar_malformed`, or `terminal_missing_artifact`) make contradictions explicit and produce exit `1`; usage/configuration errors also exit `1`. The one exception is `retryable_attempt` — "work not yet done, retryable" — which is **backlog** and is reported without moving the exit code (it still does under `--strict`). Reports redact credentials, signed URLs, media, models, and raw exceptions. Use only reviewed local fixtures or a disposable temporary archive root; coverage is an inspection projection and does not mutate any source sidecar.

  **Subtitle and transcript artifact quality signals (`--quality`)**:
  - Subtitle-first quality provides **deterministic artifact validation only**; it explicitly makes **no claim of semantic correctness**, grammar correctness, or language fluency.
  - **Defect reason codes** are bounded and frozen, and only these affect validity and the exit code: `empty` (empty artifact body/lines), `malformed` (unparseable SRT/JSON structure or non-finite timestamp), `non_monotonic` (out-of-order cue timestamps), `overlap` (overlapping cue intervals), `out_of_range` (negative time or cues exceeding known duration), `identity_mismatch` (work_id/bvid mismatch between manifest and artifact stem/frontmatter), `artifact_missing` (referenced or inferred transcript files missing on disk), `identity_unconfined` (a **declared** artifact path that escapes every read base), and `identity_invalid` (a declared identity field that is not schema-valid, e.g. a non-int `cid`). The last two are the *declaration* half of the identity family — a row that states an unusable path or identity is corrupt even while its status is still in flight — so they are defect-class rather than backlog. Only `artifact_missing` means "not there yet".
  - **Content reason codes** record what the archived transcript measures and are advisory — the coverage report lists them alongside the defect codes in each row's `reasons`, defect codes first and within each class in the fixed vocabulary order, and counts them in `summary`; they never change `valid_work_items` or the exit code: `low_confidence` (a cue scored at or below the archived low-confidence threshold), `leading_mark` (a cue opens on a closing mark), `fragment_cue` (a cue too short in both text and duration), `overlong_cue` (a cue longer than the shaper's maximum), `duplicate_cue` (consecutive identical cues), `repeated_ngram` (an 8-character window occurring three or more times), and `reference_disagreement` (a `--reference` transcript agreeing below `0.95`). Per-cue confidence comes from the raw sidecar only, so an artifact that records no score reports no `low_confidence`; it is not computed rather than fabricated. The cue-level codes (`low_confidence`, `leading_mark`, `fragment_cue`, `overlong_cue`, `duplicate_cue`, `repeated_ngram`) are read from cue structure, so a row whose artifacts are only `.txt`/`.md` — the plain-text arm yields no cues — reports none of them; `reference_disagreement` still applies, because the plain-text body is comparable text.
  - **`--reference <path>`** supplies a second transcript of the same audio (`.srt`/`.txt`/`.json`). It requires `--quality` and exactly one selected row (`--scope <work_id>`), and adds a top-level JSON `reference` block carrying `work_id`, the reference's **basename only**, `agreement`, `floor`, and the two compared character counts. CSV keeps its frozen columns and prints the ratio to stderr. An unreadable, oversized, or transcript-less reference is a usage error — `coverage: reference unreadable`, `coverage: reference too large`, `coverage: reference too large to compare`, `coverage: transcript too large to compare`, or `coverage: reference has no comparable text` on stderr, with exit `1` — never a traceback. (The comparison is bounded in work, not only in bytes: a flattened pair above the internal per-side ceiling is refused instead of hanging.) `.srt` and `.txt` references are read as plain text when they carry no cue structure, so a malformed file under those names is compared rather than refused; a cue-less or unparsable `.json` reference is always refused. The block is reported only when the row itself has comparable text: a row with none — no artifacts, unreadable ones, or artifacts whose cues carry no text — emits no `reference` block and no diagnostic for it, keeping whatever defect already describes it (often none), because a ratio that was never computed is not fabricated.
  - **Reclaimed audio acceptance**: When valid transcript artifacts (`.srt`, `.txt`, `.md`, or `.json`) exist on disk for an `archived` entry, absent audio files under `audio/` are recognized as expected post-archive reclaimed disk state and are **not reported as defects**.
  - **Read-only boundary**: Quality inspection never mutates manifest row status, risk tokens, sidecars, or transcript files. It executes zero live network requests and requires no ASR model.
  - **Exit semantics**: Exits `0` when all scoped artifacts pass validation without defects or diagnostics; exits `1` when any artifact defect reason or defect-class telemetry diagnostic is present, or on configuration/usage error. Content reasons alone never exit `1`. In-flight rows whose only finding is `artifact_missing` are **backlog** and never exit `1`; a `gone` row is **terminal-complete** and is neither backlog nor a defect, so it does not exit `1` either. `--strict` restores the pre-cutover gate — any finding of either class, including backlog, exits `1`. This two-class split (`defect` / `backlog`, plus the terminal-complete third case) is shared by `verify` and both `coverage` modes.


`bili-asr run` coordinates manifest rows through four stages — `harvest`
(probe + download subtitles), `download` (fetch audio), `asr` (local
Qwen3-ASR), `archive` (write `srt`/`txt`/`md`) — composing the same live
seams as the single-purpose commands. It **complements** the frozen
`bili-asr pilot` MVP-proof command; it does not replace it.

This chain is driven from the manifest state only: `run`, `pilot`, `asr`, and
`schedule` never read `archive.db`, so transcripts stored by the SQLite
`harvest-subs` do not feed them (and `harvest-subs` no longer marks rows
`needs_audio`; `bili-asr derive-manifest` is what carries this store's audio
queue across, by appending a `needs_audio` row per captionless part). See
[Subtitle acquisition on SQLite](#subtitle-acquisition-on-sqlite-probe-subs--harvest-subs)
for that boundary.

    bili-asr run --scope pending|failed|<work_id>... [--offline] [--limit N] [--archive-root <root>]
        [--artifact-root <path>] [--keep-audio | --no-keep-audio]

- **Scope**: `pending` selects all non-terminal processable rows; `failed`
  re-selects rows with a recorded failed stage attempt; otherwise one or
  more `work_id`/bvid selectors (comma- or space-separated). Reruns skip
  already-terminal rows (`archived` / `gone`).
- **Stage-attempt ledger**: every executed stage atomically appends a
  record to `{archive-root}/coordinator/attempts.jsonl` (sidecar JSONL;
  the manifest schema is untouched). Fields: `stage`, `work_id`,
  `attempt` (per work/stage counter), `outcome` (`ok` / `failed` /
  `skipped`), `error_code` (redacted scalar only), `artifact_paths`
  (relative), `started_at` / `finished_at`. Credentials, signed URLs, and
  raw exception text are never persisted; a crash leaves no partial line.
  Note: `skipped` records carry their skip reason in `error_code` (e.g.
  `offline`, `missing_audio`) — the field set is locked, so `error_code`
  doubles as the skip-reason channel.
- **Failure summary**: each run prints one line per failed row (with its
  redacted error code) to stderr and one `skipped (reason)` line per
  skipped row to stdout. Per-item CDN/ASR failures are recorded and the
  batch continues.
- **Exit codes**: 0 all selected rows processed; 1 scope-resolution error
  (printed before any batch output; no run-ledger record is written),
  per-item failure, or scope not fully processed (e.g. offline skip from
  missing on-disk input); 2 risk-control ceiling (re-run to resume).

#### Offline mode and the live-vs-deterministic boundary

`--offline` splits live-risk operations from deterministic local
processing. It **never issues HTTP**: the `harvest` and `download` stages
(always network) are not invoked. Only what already exists on disk is
reprocessed:

- a row with subtitle raw JSON at
  `{artifact-root}/subtitles/raw/{stem}.json` is re-archived with
  `source=subtitle` (no ASR);
- a row with audio at `{artifact-root}/audio/{stem}.m4a` (or a `.flac`
  sibling, or the manifest's `audio_path`) runs local `transcribe` and
  archives with `source=asr`;
- either product is also found at the archive root — when no artifact root is
  configured, and for every row written before one was: reads probe the
  configured root and then the archive root, first hit wins (see
  [Where the artifacts go](#where-the-artifacts-go));
- any other row is `skipped` with a reason (`offline` for rows that still
  need harvest, `missing_subtitle_raw` / `missing_audio` for rows whose
  artifact vanished) and the run exits 1 because the scope was not fully
  processed. Nothing is silently re-downloaded.

### Bounded corpus scheduler (`bili-asr schedule`)

`bili-asr schedule` walks the existing manifest sequentially in explicit
batches. It composes `RunCoordinator`, `ManifestStore`, `MetaCursorStore`,
and `RunLedger`; it does not open sockets itself and does not replace
`pilot` or `run`.

    bili-asr schedule --scope pending|failed|<work_id>... --limit N [--resume] [--max-audio-gb G] [--allow-long-live] [--archive-root <root>]
        [--artifact-root <path>] [--keep-audio | --no-keep-audio]

- **`--limit N` is required.** A bounded call never infers that the visible
  corpus is fully archived.
- **Scope** matches `run`: `pending` (non-terminal rows), `failed` (rows
  with a recorded failed stage attempt), or explicit `work_id`/bvid
  selectors. Terminal `archived` / `gone` selectors skip with
  `already_terminal` and exit 0.
- **Batch state** is persisted at `{archive-root}/scheduler.json` as
  `complete` (this call visited every currently matching scope row
  after the default duration filter), `limited` (the explicit limit
  **or** a default long-duration hold left matching rows unselected),
  or `risk_interrupted`. `complete` is requested-scope completion, not
  corpus completion; held multi-hour rows stay pending and keep the
  batch `limited` until `--allow-long-live`. The summary always prints
  the meta-cursor enumeration state so a `limited` crawl cannot
  masquerade as done.
- **`--resume`** consumes only a matching-scope `risk_interrupted`
  sidecar whose long-live policy matches. The sidecar stores
  `allow_long_live`; resume without that flag refuses and leaves a valid
  risk token untouched. Deliberate `limited` / `complete` states, a
  missing sidecar, or a corrupt sidecar are ignored with a stderr reason
  and are not auto-resumed. `processed_work_ids` keeps only `ok` /
  `already_terminal` rows so budget/offline/missing-artifact skips stay
  retryable. Persist failure prints a redacted error and does not tell
  the operator to `--resume`.
- **Exit codes** follow the mixed-outcome contract: 0 requested rows
  processed or already terminal; 1 usage/config, per-item failure, or
  non-risk skip; 2 risk/API interruption (re-run with `--resume`).
- **Long-live opt-in.** Default `pending` / `failed` selection keeps the
  same 45-minute short-video policy as `pilot`. A multi-hour row is
  processed only with `--allow-long-live` and a configured
  `--max-audio-gb` (default 10; `0` is refused on this path). The summary
  prints the conservative 64 kbps estimate, measured `audio/` peak, and
  post-archive usage after reclaim. Operator steps for Windows WSL,
  archive-root placement, cookie boundary, `du` measurement, and redacted
  evidence are in `docs/wsl-long-live.md` and
  `docs/wsl-long-live-evidence.md`. Do not raise `pilot --max-duration-min`
  to sneak livestreams into the short-video campaign.

### Controlled corpus campaign (`bili-asr campaign`)

`campaign` runs one explicitly bounded sequential coordinator batch and writes
`{archive-root}/campaign.json` as an aggregate audit projection. It does not own
per-row transitions: the manifest, stage-attempt ledger, and `scheduler.json`
remain authoritative for item state and risk-interruption resume.

    bili-asr campaign --scope pending|failed|<work_id>... --limit N [--resume] [--offline] [--max-audio-gb G] [--archive-root <root>]
        [--artifact-root <path>] [--keep-audio | --no-keep-audio]

- `--limit N` is mandatory and positive. The projection records only bounded,
  validated work IDs, a policy fingerprint, stable reason codes, and
  `complete`, `limited`, or `risk_interrupted`.
- `--resume` is accepted only when both the campaign projection and scheduler
  checkpoint describe the same scope, limit, policy, processed IDs, and risk
  interruption. Missing, malformed, mismatched, or deliberately completed or
  limited evidence fails closed rather than guessing work ownership.
- The checkpoint uses a same-directory atomic replace plus file and directory
  durability steps. Credentials, URLs, raw exceptions, request payloads,
  models, and media are forbidden from the projection and summary.
- Exit `0` means the selected bounded scope completed; exit `1` means a
  configuration error, limited/non-terminal outcome, skip, or per-item failure;
  exit `2` means risk interruption. A completed bounded campaign is not a claim
  that the visible corpus is fully archived.

### SQLite FTS5 full-text search and metadata export

The JSONL manifest (`{archive-root}/manifest/manifest.jsonl`) remains the single source of truth (SSOT). Both `search` and `export` are read-only commands that never modify or rewrite the manifest ledger.

#### Full-text search (`bili-asr search`)

`bili-asr search <query>` queries a lightweight local SQLite FTS5 read index (`{archive-root}/search.db`) built on demand from completed transcript metadata (`archived` or `subtitle_done` with archive paths present). Incomplete entries (`meta_ok`, `needs_audio`, `audio_ok`) are not searchable as complete transcripts.

    bili-asr search <query> [--limit N] [--rebuild] [--archive-root <root>] [--artifact-root <path>]

- **Ranking**: Matches are ranked by BM25 relevance score over `work_id`, `title`, `status`, and full transcript text.
- **Stale detection**: Automatically verifies whether `search.db` is missing, older than `manifest.jsonl`, or has row count mismatch, rebuilding on demand.
- **Idempotent rebuild**: `--rebuild` forces a clean atomic index rebuild.
- **No hits**: Exits `1` with a clear message when no matching records are found.
- **Environment**: Uses standard library `sqlite3` FTS5; fails with a clear message if SQLite in the environment lacks FTS5 extension support.

#### Metadata and transcript export (`bili-asr export`)

`bili-asr export` serializes manifest-derived records into structured JSON or CSV format without touching the manifest or calling external APIs.

    bili-asr export --format json|csv [--out <path>] [--status <status>] [--with-text] [--archive-root <root>]
        [--artifact-root <path>]

- **Deterministic read projection**: JSON and CSV output is 100% byte-stable across repeated invocations, sorting stably by `(bvid, page_index, work_id)` with standard column ordering (`STANDARD_CSV_COLUMNS`).
- **Formats**: `--format json` (formatted JSON array) or `--format csv` (standard CSV with UTF-8 encoding).
- **Transcript bodies**: By default, exported rows contain metadata only (no transcript bodies). Specify `--with-text` to include full transcript text bodies under `transcript_text`.
- **Status filtering & coverage explanation**: `--status <status>` filters records by manifest status (repeatable or comma-separated, e.g. `--status archived,subtitle_done`). Incomplete records (`meta_ok`, `needs_audio`, `audio_ok`, `pending`, `gone`) retain their honest manifest status and have empty `transcript_text` rather than claiming false completion or being silently omitted.
- **Output destination**: Writes to standard output by default, or to `--out <path>` (creating parent directories if needed and writing atomically).
- **Security & path safety**: Credentials (`SESSDATA`, cookies, auth tokens), signed streaming URLs, raw exceptions/tracebacks, and sensitive URL query parameters are strictly excluded and redacted. Filepath fields are validated against `archive_root` to prevent directory traversal or outside-root path exposure.
- **Vocabulary**: Consistently uses manifest `status` (never cursor `state`).
- **Decoupled from search index**: Export operates directly over the JSONL manifest SSOT and does not require, query, or mutate `search.db`.

### Fresh-start SQLite archive (`fetch-meta` / `status` / `runs`)

`bili-asr fetch-meta` collects video metadata through the pinned
`bilibili-api-python==17.4.2` gateway and writes it to a fresh normalized
SQLite database at `{archive-root}/archive.db`; the layout is described in
[docs/metadata-storage.md](docs/metadata-storage.md). The metadata commands
never read or write the legacy `manifest/manifest.jsonl`,
`meta-cursor.json`, or `run-ledger.jsonl` sidecars, and no command migrates
old archive data: a new database starts empty. Deleting `archive.db` is the
only restart path.

    bili-asr fetch-meta --mid 23191782 --archive-root archive
    bili-asr fetch-meta --mid 23191782 --limit-pages 1 --archive-root archive
    bili-asr status --archive-root archive
    bili-asr runs --limit 10 --archive-root archive

The subtitle commands work on that same fresh database and are described in
[Subtitle acquisition on SQLite](#subtitle-acquisition-on-sqlite-probe-subs--harvest-subs)
below; this subsection covers the metadata and read commands only.

- **Default page bound**: `--limit-pages` is optional and defaults to
  `DEFAULT_PAGE_LIMIT = 10`. The canonical command above therefore stops
  after 10 pages (the ingestor's page size is 30 — the upstream-accepted
  default, `ps=30`; larger page sizes are not guaranteed, and an explicit
  programmatic override is forwarded rather than clamped or rejected: there is
  no CLI flag for it), ends the run `limited`, and still exits 0 — a limited
  run is never claimed as complete. A full archive walk is a series of
  resumable runs: re-run the same command to continue from the stored cursor,
  or pass an explicit `--limit-pages` for a longer slice.
- **Resume semantics**: without `--resume` or `--start-page`, a run continues
  from the stored cursor when one exists and starts at page 1 otherwise.
  `--resume` requires a stored cursor and exits `1` when there is none;
  `--start-page` overrides the cursor. A failed page never advances the
  cursor, so resume is always safe.
- **Credential boundary**: optional SESSDATA comes from `--sessdata` or the
  `BILI_SESSDATA` environment variable (cookie **value**, not a file path).
  It is sent as an API cookie only and is never echoed, logged, persisted,
  or written to the database; CLI output shows presence only
  (`sessdata: present|absent`). Passing `--sessdata ""` explicitly forces
  anonymous access even when `BILI_SESSDATA` is set; a blank environment
  value likewise means anonymous.
- **Runtime HTTP backend**: the pinned
  `bilibili-api-python==17.4.2` distribution declares no HTTP client of its
  own, so `curl_cffi` is a declared runtime dependency of this package and a
  normal install (`pip install -e ".[dev]"` or `uv sync`) provides it.
  Without a backend, every request fails in-process before it leaves the
  process and surfaces as the bounded `response_error`.
- **HTTP proxy**: on a host that needs a proxy, set `BILI_HTTP_PROXY`
  (for example `BILI_HTTP_PROXY=http://127.0.0.1:7890`). The pinned client
  builds its session with an explicitly empty proxy, so the standard
  `HTTPS_PROXY` / `ALL_PROXY` variables alone are ignored by the package; the
  gateway resolves the knob itself in the order constructor argument →
  `BILI_HTTP_PROXY` → `HTTPS_PROXY`/`https_proxy` → `ALL_PROXY`/`all_proxy`,
  treats a blank value as unset, and forces no proxy when nothing resolves.
  The resolved value is applied to the package's process-global settings, and
  a blank value cannot override a host-level variable — forcing direct access
  means unsetting those variables for the process (there is no in-app switch).
  Details: [docs/metadata-storage.md](docs/metadata-storage.md).

| Exit | Meaning |
|------|---------|
| 0 | `fetch-meta`: successful collection — the empty page was reached, or the run stopped at a page bound (the explicit `--limit-pages` or the implicit default of 10 pages); the run row records `complete` or `limited` accordingly. `status` / `runs`: database read and displayed. |
| 1 | Usage/configuration error: bad page arguments, `--resume` without a stored cursor, or a missing/unreadable database for the read commands. Unexpected internal errors exit 2 (see below), not 1. |
| 2 | `fetch-meta` only: terminal failure — two variants, distinguishable by the failure line (see below). |

Exit 2 variants:

- **Gateway failure** (bounded scalar code, e.g. `response_error`,
  `rate_limited`): the gateway is fail-fast per page — one attempt per
  page, no retry. The failed page records its bounded scalar code, the
  cursor remains unchanged, and re-running `fetch-meta` resumes safely.
- **Unexpected internal error** (the fixed line `fetch-meta: unexpected
  error`, no scalar code, no traceback): the cursor may already hold the
  last committed page of the run and the run row may remain `running` —
  check `status` / `runs` before re-running. Re-running is safe: it
  resumes from the stored cursor.

#### Subtitle acquisition on SQLite (`probe-subs` / `harvest-subs`)

`bili-asr harvest-subs` acquires captions for parts already stored in
`archive.db` and keeps the normalized transcript **in that database**: no
`subtitles/raw/*.json` and no `transcripts/srt/*.srt` is written, and no JSONL
sidecar is read or written. `bili-asr probe-subs` lists the tracks the selected
parts expose and writes nothing at all — no database creation, no run or attempt
row, no lock file. The full contract, with the printed line shapes and the
observed live run, is in
[docs/metadata-storage.md](docs/metadata-storage.md).

    bili-asr probe-subs --limit-parts 5 --archive-root archive
    bili-asr probe-subs --bvid BV1S8hA6MEvy:p0 --archive-root archive
    bili-asr harvest-subs --limit-parts 5 --archive-root archive
    bili-asr harvest-subs --bvid BV1S8hA6MEvy:p0 --archive-root archive
    bili-asr harvest-subs --limit-parts 5 --language ai-zh --archive-root archive

- **Bounds**: no unbounded runs. `harvest-subs` requires `--limit-parts N`
  whenever the selection is not a single `bvid:pN` part; `probe-subs` requires
  exactly one of `--bvid` / `--limit-parts`. `--bvid BVID` selects every part of
  that video already in the database — for `harvest-subs` that includes parts
  that already have a transcript, which is how a video is re-checked after
  upstream revises a caption. Neither command fetches a pagelist, and neither
  calls upstream for a part that is not in the database.
- **Exit codes**: `0` the bounded run completed — including a probe whose parts
  exposed no track, and a selection that resolved to no part (`attempted=0`);
  `1` usage/configuration (missing database, unknown `--bvid`, missing or
  non-positive bound, neither/both `probe-subs` selectors, empty `--language`
  entry, or the schema guard below); `2` every attempted part failed, or an
  unexpected internal error (`<command>: unexpected error`, no traceback).
  Partial failure stays visible in the printed counts, not in the exit code.
- **Output shapes**: `probe-subs` prints `sessdata: present|absent`, then one
  line per selected part — `probe <work_id> tracks=<n>` with one
  `track <lan> <ai|cc> <label>` line each, `probe <work_id> tracks=0` with an
  explicit `(no subtitles visible)` marker, or `probe <work_id> failed <code>` —
  and closes with
  `probe-subs: probed=<n> with_tracks=<n> without_tracks=<n> failed=<n>`.
  `harvest-subs` prints one line per attempted part —
  `harvest <work_id> stored|unchanged <source_kind> <language> v<version>`,
  `harvest <work_id> no-subtitle`, or `harvest <work_id> failed <error_code>` —
  and closes with `harvest-subs: run_id=<id> attempted=<n> stored=<n>
  unchanged=<n> no-subtitle=<n> failed=<n>
  remaining_without_transcript=<n>`, carrying all four counts including the
  zeros. Nothing here is a claim about corpus or caption coverage.
- **Preference rule**: the default keeps the **uploader** caption
  (`subtitle-cc`) over the machine one (`subtitle-ai`), with families ranked
  `zh`, then `en`, then the rest in upstream order. That CC-before-AI term is
  family-blind on purpose: the remaining families share one rank, so between two
  **different** non-default families the uploader caption wins even when the
  machine track comes first upstream, and upstream order settles only a tie
  between tracks of the same family and the same kind. The family is derived
  from the `language` + `is_ai` facts the gateway
  already guarantees (strip an `ai-` prefix from a machine code, then take the
  primary subtag), so `zh-CN` / `zh-Hans` / `zh-Hant` / `ai-zh` all rank as
  `zh`: upstream uses different exact codes per caption kind, and a fixed code
  list would silently mis-rank codes upstream adds while a machine↔uploader
  equivalence table would need maintaining. `--language PREF[,PREF...]` matches
  a preference **exactly** against the code `probe-subs` prints, so
  `--language ai-zh` keeps the machine caption reachable. This replaces the
  legacy manifest harvest's AI-first order.
- **Credential**: `--sessdata` or `BILI_SESSDATA` (flag wins), with the same
  resolution and presence-only redaction as the metadata commands
  (`sessdata: present|absent`); the value reaches the gateway's cookie only and
  is never echoed, logged, or persisted. `harvest-subs` records the presence in
  its run row, so a part it recorded `no-subtitle` stays interpretable — an
  invisible caption may exist and simply be login-gated.
- **Schema guard and rebuild**: on a database that predates the transcript
  schema both commands print one line on stderr — `<command>: archive database
  predates the transcript schema; rebuild it (delete <archive-root>/archive.db
  and re-run fetch-meta)` — and exit `1`, while `fetch-meta` / `status` / `runs`
  keep working on it. There is no in-place migration: deleting `archive.db` and
  re-running `fetch-meta` is the rebuild, and a bare `fetch-meta` stops at the
  implicit `--limit-pages` bound (`DEFAULT_PAGE_LIMIT = 10`), so a corpus
  collected beyond page 10 needs `--limit-pages <n>` (or repeated `--resume`
  runs). The database is created from two checked-in
  resources, `src/bili_asr/storage/schema.sql` and
  `src/bili_asr/storage/schema-transcripts.sql`.
- **Legacy manifest boundary**: the ASR/pilot chain is untouched and still reads
  `manifest/manifest.jsonl`, so `asr --pending`, `pilot`, `run`, `schedule`, and
  `campaign` do not see transcripts stored here. `harvest-subs` itself still
  produces no manifest status `needs_audio`; `bili-asr derive-manifest` is what
  feeds `download-audio --missing-subs` from this path, by appending one
  `needs_audio` row per captionless part (see the
  [derived audio queue](#derived-audio-queue-bili-asr-derive-manifest)).
  Rebuilding the SRT/TXT/MD projections from the stored transcripts is still
  deferred work for a later iteration.
- **Writer lock**: `harvest-subs` is an archive-writer command and holds
  `{archive-root}/coordinator/archive-writer.lock` for the whole run, so a
  second mutating command exits `1` with `harvest-subs: archive_busy`. Apart
  from `archive.db`, that lock is the only file a bounded harvest leaves behind;
  `probe-subs` deliberately takes none. The lock is taken **before** the
  command's database check, so even a failed or mistyped harvest — a missing
  `--archive-root`, say — creates `<root>/coordinator/` and leaves the lock file
  there while exiting `1`; nothing reaches the database.

#### Derived audio queue (`bili-asr derive-manifest`)

`bili-asr derive-manifest` bridges the store to the chain's queue, and is the
only command that reads `archive.db` and writes `manifest/manifest.jsonl` in one
run. It appends one `needs_audio` row per stored part that holds no transcript
and is not `gone` — the relation `harvest-subs` reports as
`remaining_without_transcript`:

    bili-asr derive-manifest --archive-root archive

- **Command surface**: `--archive-root PATH` (default `archive`), nothing else —
  no selector, no `--limit`, no `--dry-run`.
- **Reads**: `{archive-root}/archive.db`, opened **read-only**. The queue is the
  parts that are not `gone` and hold no transcript, so a part recorded
  `no-subtitle` is in it and a part whose caption is already stored is not. A
  missing, unreadable, or pre-transcript-schema database is answered with the
  same bounded lines and exit `1` the other subtitle commands print; nothing is
  created and no live database is widened.
- **Writes**: appended rows in `manifest/manifest.jsonl`, and only appended.
  Each carries the page-qualified `work_id`, the part's stored duration as
  `duration_s`, and `status: needs_audio`. A row the chain already holds for that
  `work_id` is never rewritten, so a second run appends nothing and the effective
  state (the last row per `work_id`) is unchanged. Nothing is written to
  `archive.db` — the queue set is identical before and after — and no download or
  ASR work starts.
- **Does not do**: materialise a subtitle document, derive a `subtitle_done` (or
  `audio_ok` / `asr_done` / `archived` / `gone`) row, migrate or import anything
  in either direction, change or widen the store's schema, or rebuild the
  SRT/TXT/MD projections from the stored transcripts.
- **Output shapes**: one line per appended row
  `<work_id>: needs_audio (duration_s=<n>)`, then one `skip <work_id> <reason>`
  line for each row left to the chain (`chain_owned`) and each row whose stored
  `work_id` contradicts the identity rule (`identity_mismatch`), and closes with
  `derive-manifest: queue=<n> derived=<n> already_derived=<n> chain_owned=<n>
  identity_mismatch=<n>`, carrying every count including the zeros.
- **Exit codes**: `0` the derivation completed, an empty queue included; `1` the
  command could not run (missing or unreadable database, the transcript-schema
  guard, `archive_busy`, usage) **and** a derivation whose append loop failed
  part-way: the rows written before the failure stay, the summary is still
  printed with `derived` counting them, and one
  `derive-manifest: append failed after <k> row(s)` line on stderr names the
  count. No path of this command produces `2`.
- **Writer lock**: `derive-manifest` is an archive-writer command, so it holds
  `{archive-root}/coordinator/archive-writer.lock` and a second mutating command
  exits `1` with `derive-manifest: archive_busy`. As with `harvest-subs`, the
  lock is taken before the database check, so even a mistyped `--archive-root`
  creates `<root>/coordinator/` and exits `1` without touching the database.
- **What reads the rows**: `download-audio --missing-subs`, `pilot`, and
  `run` / `schedule` / `campaign --scope pending` select them. `asr --pending`
  reaches one only after `download-audio` has advanced it to `audio_ok`: that
  selector takes `subtitle_done` / `audio_ok` rows, never the appended
  `needs_audio` row itself. `coverage`, `coverage --quality`, `verify`, and
  `export` read them. This iteration adds the rows only; none of those readers
  changes. Their exit consequences follow from the rows, though: every derived
  row is a `retryable_incomplete` defect for `verify`, which therefore exits `1`
  until the chain advances it, and a corpus-scale append is what reaches the
  default reader's 10,000-record / 8 MiB ceiling first — past either ceiling the
  result is non-authoritative and `verify` / `coverage` exit `1` without
  `--trusted-local`.
- **Limits, stated**: the store records no per-part audio outcome, so a bounded
  run that keeps failing the same part re-selects it — rotation holds after a
  successful attempt, not after a failed one. The appended rows are selected
  *alongside* whatever `needs_audio` rows the manifest already held, legacy
  bare-`bvid` rows included, and in manifest file order, so a bounded
  `--limit 1` run can spend its single slot on a pre-existing row instead of on
  a row this command just derived. The other direction is a limit too: the
  derivation consults the manifest's *effective key*, so a legacy bare-`bvid`
  row is not consulted at all, and a part whose only record is one is appended
  as `needs_audio` whatever state that row holds — a terminal `archived` /
  `asr_done` row included, so a bounded run re-downloads and re-runs work the
  chain already finished. The row itself is never rewritten and the artifact
  lands at the page-qualified stem, so nothing is overwritten; the cost is
  repeated work, registered as `iter-2026-09-queue-bridge · R2`. And the
  SRT/TXT/MD projection rebuild stays out of this iteration: a stored caption
  keeps no `srt`/`txt`/`md` bundle until
  that rebuild lands, and it is not re-queued for audio either, because the
  derived queue is the no-transcript relation.
- **Append cost, bounded analytically (not measured)**: each appended row is one
  locked re-read of the whole ledger plus two `fsync` calls, and the whole
  derivation runs under the archive-writer lock, so appending `N` rows to an
  `L`-line ledger costs about `N·L + N(N−1)/2` line parses — at `N = L = 2,000`
  roughly 6M parses and 4,000 fsyncs. That is an analytic bound only: no runtime
  measurement was taken on a real archive, so a first full-queue derivation
  should be treated as holding the writer lock for a duration this iteration
  does not state.

#### Opt-in bounded live smokes

Four tests share the one switch (`BILI_LIVE_SMOKE=1`); every default pytest
run skips all four and makes no network call:

- `tests/test_live_metadata_smoke.py` — the real CLI against the real upstream:
  exactly one public metadata page for UID 23191782, into a temporary archive
  root, calling no subtitle/playback/audio/ASR code (detailed below);
- `tests/test_live_subtitle_smoke.py` — the real subtitle adapter against the
  real upstream: one part's track inventory and, when a track is visible, that
  track's caption document. It resolves the part from the operator's archive
  database when one is readable and falls back to a fixed public sample
  otherwise (`part_source=archive-db|fixed-sample`), and it prints bounded
  facts only — counts, language codes, `ai|cc`, segment count, milliseconds,
  and credential presence — never a URL, body, label, or credential. Run it
  from the package directory with the pinned distribution installed:
  `BILI_LIVE_SMOKE=1 .venv/bin/python -m pytest tests/test_live_subtitle_smoke.py -s -v`;
- `tests/test_live_subtitle_cli_smoke.py` — the real **CLI + storage** chain
  against the real upstream: one part through `probe-subs` and `harvest-subs`
  in a temporary archive root, asserting the printed line shapes, the stored
  transcript rows, and the archive root's file set. The part both commands
  address is authored into that temporary root — the fixed public sample
  `BV1S8hA6MEvy:p0`, recorded as `part_source=fixed-sample` — because the
  commands only ever address parts the database already stores. Zero visible
  tracks, a `not_found` listing, and a `rate_limited` refusal are recorded as
  bounded evidence and skipped rather than reading green; every other bounded
  code fails loudly. Once opted in it **requires a credential**: with no
  resolvable `BILI_SESSDATA` it fails with source-the-`.env` guidance instead of
  reporting an anonymous `sessdata=absent tracks=0` run as "nothing visible now"
  — an ambiguous reading, since a login-gated caption looks the same. Its one
  count-only evidence line names the seeded part,
  credential presence, both commands' counts, and the stored source
  kind/language/version. Run it from the package directory of the checkout
  under test (the package's `tests/conftest.py` puts that checkout's `src/`
  first on `sys.path`, ahead of the control `.venv`'s editable install):
  `BILI_LIVE_SMOKE=1 .venv/bin/python -m pytest tests/test_live_subtitle_cli_smoke.py -s -v`;
- `tests/test_bilibili_api_gateway.py::test_live_smoke_single_public_page_for_archive_owner`
  — the adapter-level ancestor of the CLI smoke: one real metadata page for UID
  23191782 ingested into a temporary database through the real gateway.

`tests/test_live_metadata_smoke.py` drives the real CLI against the real
upstream: exactly one public metadata page for UID 23191782
(`--start-page 1 --limit-pages 1`) into a temporary archive root, calling no
subtitle/playback/audio/ASR code. Default pytest runs skip it; the proxy is
part of the command on a proxied host:

    CONTROL=/root/workspace/bilibili-asr-archive   # the control checkout
    cd "$CONTROL/bilibili-asr-archive"
    set -a; source "$CONTROL/.env"; set +a          # gitignored; absent in a worktree
    export BILI_HTTP_PROXY=http://127.0.0.1:7890
    BILI_LIVE_SMOKE=1 "$CONTROL/bilibili-asr-archive/.venv/bin/python" \
      -m pytest tests/test_live_metadata_smoke.py -s -v

The control checkout owns the `.env` credential file and the `.venv`
interpreter, and a linked feature worktree has neither — a worktree run must
address them by absolute control-checkout path (as above) or provision its own
environment. Keep `-s` (or `-rP`) in the command on the first live attempt:
pytest captures the stdout of a *passing* test, so a plain `-v` run hides the
count-only evidence line on the happy path and would force a second page
request against a risk-controlled endpoint.

The smoke's credential signal is the `BILI_SESSDATA` environment variable alone
(sourced from `.env` above): it builds its own `fetch-meta` argv and passes no
`--sessdata`, so that CLI flag is not a smoke input. With that credential the
smoke requires the happy path: exit 0, `outcome=limited` on the page bound
(or `complete` on an empty first page), and the real normalized rows — user,
videos, their parts, one discovery row per video, a terminal run row, exactly
one page row, and a cursor advanced past the committed page — with no legacy
sidecar and no credential or playback marker in output or rows. It prints one
count-only evidence line (`live smoke evidence: outcome=… videos=… parts=…
discoveries=… page_rows=1 cursor_next_page=… cursor_state=…
observed_total=…`); a bounded failure with a credential present is a loud
failure. Without a credential the run is anonymous: if upstream rejects
anonymous metadata access the smoke verifies the bounded-failure evidence
(terminal run row, one scalar page row with a `rate_limited` /
`response_error` code, no entity or discovery growth, no cursor row) and
reports that bounded no-credential outcome as a reasoned skip rather than a
defect; any other bounded code fails the smoke loudly. Expectations and the
underlying transport/proxy requirements are documented in
[docs/metadata-storage.md](docs/metadata-storage.md).

### Mixed batch outcomes

On the legacy manifest path, when `download-audio`, `asr`, `pilot`, `run`, or
`schedule` processes more than one work item, the process exit code is an
aggregation of per-item outcomes — not a claim that the whole corpus is
complete. `pilot` remains the frozen two-branch proof command; `run` remains
complementary; `schedule` consumes this same taxonomy. The SQLite
`harvest-subs` follows its own bounded taxonomy instead (see
[Subtitle acquisition on SQLite](#subtitle-acquisition-on-sqlite-probe-subs--harvest-subs)).

| Exit | Meaning |
|------|---------|
| 0 | Requested work processed, or every selected row is already terminal (`archived` / `gone`). |
| 1 | Usage/config error, missing optional ASR, per-item failure, or incomplete scope from a non-risk skip (`offline`, `audio_budget`, missing on-disk input). |
| 2 | Risk/API terminal interruption. Successful rows and artifacts stay; retry the remaining work. |
| 143 / 130 | Operator interruption (`SIGTERM` / `SIGINT`, recorded as `128+signal`); successful rows and artifacts stay. |

Risk interruption takes precedence over per-item failure: a batch that
archived some rows and then hit the risk ceiling still exits 2.

Successful rows stay in their last stable status. Retryable failures remain
selectable by the same command or by `run --scope failed`. That recovery path
reads the stage-attempt ledger that the run coordinator behind `bili-asr run`,
`schedule` and `campaign` writes: work archived through the `pilot` entry point
leaves no attempt records, so no per-stage truth exists for pilot work and it is
not reachable by `--scope failed`. `pilot` is a bounded probe, not a corpus
path. Explicit `run --scope` work_id selectors of already-terminal rows skip
with `already_terminal` and exit 0; they are not duplicated.

An interrupted `run` exits `128+signal` — `143` for `SIGTERM`, `130` for
`SIGINT` — and records that code together with the counts it had already
persisted, so a stopped run is reconciled from `run-ledger.jsonl` and not from
its shell status alone.

`harvest-subs`, `download-audio`, and `asr` do not append `run-ledger.jsonl`
(that sidecar is `pilot` / `run` / `schedule`; `fetch-meta` records its runs
in `archive.db`). All operator
surfaces carry redacted scalar codes/reasons only.

### Corpus coverage evidence spine

The shipped sequential workflow now includes all six corpus-coverage slices: bounded `campaign` execution, cumulative `coverage` reconciliation, optional deterministic artifact quality signals, filtered local transcript search/export, read-only `verify` plus audit-only `recover`, and the `evaluate-concurrency` safety gate. The manifest remains SSOT; the campaign checkpoint, reports, index, and recovery audit are additive evidence or derived projections.

A bounded campaign never implies full-corpus completion. Coverage reports keep explicit denominators and distinguish cumulative rows from the latest batch. Reclaimed audio is valid after transcript archival, and quality checks make no semantic-correctness claim. `recover` records bounded redacted candidates only—it does not requeue work, change statuses, or execute repair. The concurrency gate remains a pure `go`/`no-go` evaluator whose operating mode is always `sequential-no-daemon`; even a `go` report requires a later separately approved implementation plan.

Future production expansion should consume measured campaign/reconciliation evidence and retain exact ownership, write-isolation, crash/restart, API-risk, disk, reclaim, and throughput thresholds. No worker, daemon, service, autostart, scheduler-default change, concurrent manifest writer, or schema/status/risk-taxonomy change is implied by these surfaces.

## Multipart pages and legacy rows

Automatic enumeration writes one manifest row per page (`work_id` =
`{bvid}:p{page_index}`). Filesystem names use `artifact_stem`
(`{bvid}.p{page_index}`) so raw/SRT/audio/transcripts never collide across
pages. Public URLs for `page_index` > 0 include `?p=` (1-based).

Legacy single-page rows migrate only when ownership is unambiguous. Ambiguous
bare-bvid rows stay `unresolved` / `excluded_from_page_processing`: they keep
their original key and files, stay visible in `bili-asr status`, and are never
auto-assigned a page. Bare-bvid rows remain a compatibility read/update
boundary only; new automatic rows require page-qualified `work_id` plus matching
`bvid`. `download-audio --bvid` / `asr --bvid` STOP on unresolved rows instead
of fabricating a `needs_audio` page. Resume is per `work_id`: a completed or
failed p0 does not skip p1.

No media redistribution; personal archival only.
