# A1 target-host verification — WSL2 + RX 7800 XT (2026-09-14)

Operator ran the iteration's own acceptance check on the box named by A1: **`192.168.3.21` /
`DESKTOP-HHFROLO`**, WSL2 kernel `6.18.33.2-microsoft-standard-WSL2`, venv `/root/gpu-venv`,
checkout `/root/workspace/bilibili-asr-archive` fast-forwarded to `main` @ **`234ed08`**.

## A1(i)/(ii) — PASS

```
$ cd /root/workspace/bilibili-asr-archive/bilibili-asr-archive
$ HSA_ENABLE_DXG_DETECTION=1 VENV=/root/gpu-venv /root/gpu-venv/bin/python scripts/check_asr_env.py
check: dxg-detection ok
check: rocm-loader-path ok
check: torch-present ok
check: hsa-runtime ok
check: device ok name=AMD Radeon RX 7800 XT arch=gfx1101 vram_gb=15.8 hip=7.2.26015-fc0010cf6a
asr-env: verified
EXIT=0
```

Five stages `ok`, device identified by name/arch/VRAM/HIP version, exit **0**. A1(i) (the check runs on
the target) and A1(ii) (it passes there) are therefore **proven on the real host**, not from this
workstation. The hint at `asr.py` points at `docs/wsl-rocm-gpu.md`, and the recipe's own prerequisites
are what the check verifies.

## A1(iii) — the failure path is loud, and diagnostic

With the DXG invariant removed (`env -u HSA_ENABLE_DXG_DETECTION`):

```
check: dxg-detection FAIL dxg_device=path-exists (not opened) HSA_ENABLE_DXG_DETECTION=unset
  cause: WSL2 has no usable DXG transport: the HIP runtime needs both the DXG device node and HSA_ENABLE_DXG_DETECTION=1
  fix: export HSA_ENABLE_DXG_DETECTION=1 …  ls -l /dev/dxg …  re-run with both invariants held
check: device-probe FAIL torch.cuda.is_available() == False hip=7.2.… hsa_runtime=/opt/rocm-7.2.1/lib/libhsa-runtime64.so.1.18.70201
asr-env: not verified (2 failed)
EXIT=1
```

Exit **1**, three `FAIL` lines, each naming device state, cause and the exact remediation. Running it
under the wrong interpreter (`/usr/bin/python3`, no torch) also exits **1** rather than reporting a
false pass — the "wrong environment" trap the recipe warns about is caught by the check itself.

**A rotted recipe fails loudly on the host instead of silently in the docs — the criterion A1(iii)
exists to defend.**

## A2/A4/A5 on the target — PASS (after the host volume was cleared)

The end-to-end probe ran against a **real 10-minute part** (`BV1UNPczkEkE.p0.m4a`, 6.1 MB) with the
checkpoint loaded from a local directory (`/root/e2e-asr/nano/master`), `EXIT=0`:

### A2 — one construction across items, and the counter survives release

```
item 1: segments=162  decode=185.30s  constructions=1     # includes the ~90 s load
item 2: segments=162  decode=118.99s  constructions=1     # reused — cost is visible in the delta
load attempts: 1
constructions after release: 1
```

The 66 s decode-time drop between item 1 and item 2 is *part* of the reuse effect, and the log lets it
be decomposed rather than asserted: the checkpoint load and VAD construction occupy the first **26 s** of
item 1 (`model is builded` +23.0 s, `Loading ckpt` +25.0 s, `Building VAD model` +25.9 s, all before item
1's output), so roughly 26 s of the drop is "no second load" and the remaining ~40 s is first-call warm-up
that a rebuilt model would also re-pay. The load-bearing evidence is the log, not the delta: all four
construction events occur **exactly once** and all precede item 1. The counter is monotonic across
`release()`.

### A4 — the declared identity, with no path leakage

```
ASRConfig.model_id : FunAudioLLM/Fun-ASR-Nano-2512      (via BILI_ASR_MODEL_ID)
provenance() keys  : 9
  model_name = FunAudioLLM/Fun-ASR-Nano-2512           # the declared id occupies the slot
  model_revision =                                      # unset in this probe
  device = cuda     local_source = configured-local      # the local *path* never appears
```

Nine keys, declared id in the `model_name` slot, and the local checkpoint path absent from the
serialized provenance — the redaction and slot-replacement rules hold on the real host.

### A5 — how much audio, and where the doubt is

On the run's own recorded sidecar (`BV1147c6sEKs.p0.json`, 162 cues):

```
asr_mean_confidence    = 0.789
asr_low_confidence_cues= 1
asr_low_confidence_at  = [311.11]      # count and list agree; recomputes exactly from raw.json
asr_vad_segments       = 65
asr_vad_captured_s     = 731.35        # unclamped
asr_vad_captured_ratio = 0.819 (manifest duration 893 s) / 0.820 (ffprobe 891.985 s)
                         omitted for "unknown", None, 0
```

The ratio is omitted rather than guessed when the duration is unusable, and the captured seconds stay
unclamped. The two operators the plan was scoped for are separable on real material — with the duration
held at the manifest's 893 s:

| scenario | segments | captured_s | ratio |
|----------|----------|-----------|-------|
| baseline | 65 | 731.35 | 0.819 |
| a **real 90 s speaker pause** inserted at t=400 s (everything after it shifted later) | 66 | 730.48 | 0.818 |
| **90 s of cues deleted** | 50 | 578.82 | 0.648 |

A pause adds one span boundary and captures essentially the same audio; a VAD miss removes spans and
audio together. Those two readings are different, which is what A5 asked for.

### Audit of this evidence (2026-09-14) — two defects found in the first draft, both fixed above

The first version of this section was wrong twice, and both errors are worth recording because they are
the kind this iteration spent four plans hunting:

1. **A mismatched duration.** The ratio was quoted as `0.98 / 0.821` because the probe paired
   `BV1147c6sEKs`'s sidecar with **`746.581`** — a figure belonging to a *different* video
   (`BV1UNPczkEkE`, whose `time_speech` appears in the probe log). The sidecar's own last cue ends at
   `891.04` and its manifest duration is `893`, so the true ratio is **0.819**. A duration taken from
   one item and applied to another produces a plausible, wrong number — exactly what the ratio's
   omission rule exists to prevent, applied to my own measurement instead of the code.
2. **A scenario experiment that tested nothing.** The "injected 90 s pause" shifted *every* cue by
   +90 s, which leaves all relative gaps untouched — it measured a rescaled duration, not a pause. The
   corrected experiment inserts the pause *between* cues (everything from t=400 s onward moves later)
   and shows the intended contrast: `66 / 730.48 / 0.818` versus `50 / 578.82 / 0.648`.

What survived the audit unchanged: the count/list agreement and its exact recomputation from
`raw.json` (`[311.11]`), the omission for unusable durations, the unclamped seconds, and every A1/A2/A4
result (the model-build events were verified to occur **once** each — `model is builded`, `Loading
ckpt`, `Loading pretrained params`, `Building VAD model` all count 1, and all precede item 1 in the log,
which is what makes the item-1→item-2 decode drop evidence of reuse rather than of warm caches).

### The host failure that delayed this (resolved)

The probe first failed with the WSL2 root filesystem remounted read-only (`emergency_ro`) because
Windows `C:` had fallen to **0.2 GB free**; the ext4 virtual disk lives on `C:`, so the exhausted host
volume surfaced inside the guest as an I/O error. After the operator cleared it (`C:` back to 29.7 GB) and
`wsl --shutdown` + restart, the filesystem returned `rw` and the probe completed. No product code was
implicated.

The end-to-end probe (transcribe a real part, then assert one construction across two items, the
declared identity in `provenance()`, and the VAD/low-confidence keys in a written archive) could not
complete because the **WSL2 root filesystem was remounted read-only by the kernel**:

```
/dev/sdd / ext4 rw,relatime,discard,errors=remount-ro,data=ordered,emergency_ro 0 0
touch /root/_wt  → Read-only file system   (also /tmp, also the checkout)
/usr/bin/df      → Input/output error
```

Cause, from the Windows side: **`C:` has 0.2 GB free of 931 GB** (`D:` has 413 GB free). WSL2's ext4
virtual disk lives on `C:`, so the exhausted host volume surfaced inside the guest as an I/O error and
the kernel took the filesystem read-only (`emergency_ro`). No product code is implicated: the check
above had already run to completion on that same host, and the failure mode is host-side capacity.

**Operator action to unblock:** free space on `C:` (or move the WSL2 distro to `D:` with
`wsl --export` / `wsl --import`), then `wsl --shutdown`, and re-run the end-to-end probe. Until then
A2/A4/A5 remain verified only from this workstation's fixtures, which is how the plans' QA gates
recorded them.
