# WSL2 + ROCm GPU recipe (verified 2026-09-12)

The one AMD path that was **measured** to produce a usable device for ASR on Windows WSL2.
Every command below is taken from the session that ran on the target described in the next
section — the measured session ran as root, so the `sudo` prefixes here are the only addition.
Nothing here is inferred from vendor documentation, and nothing here is a recommendation for
other platforms (NVIDIA and Intel are out of scope — see the
[PyTorch installation guide](https://pytorch.org/get-started/locally/)).

`scripts/check_asr_env.py` asserts the five invariants of this recipe on your host and prints
the fix for whichever one is missing. That check is the answer to "is my GPU usable for ASR";
this document is the answer to "make it usable".

**Scope.** This document installs nothing by itself. No code in this repository runs any
command below, no installer downloads ROCm or ROCDXG, no device is auto-detected, and no ROCm
version is asserted by the check. These are steps an operator runs by hand, once, on the WSL2
machine.

## Verified target

| | |
|---|---|
| OS | Ubuntu 24.04 on WSL2 |
| GPU | AMD Radeon RX 7800 XT — `gfx1101`, 15.8 GB visible |
| Transport | ROCDXG (`rocdxg-roct` 1.2.2) |
| Result | `torch.cuda.is_available()` is `True`, `hip=7.2.0`, matmul runs on the device |

The verified combination, in one line: ROCm 7.2.1 runtime + `rocdxg-roct` 1.2.2 (ROCDXG) + the
**repo.radeon.com** `torch 2.9.1+rocm7.2.0.lw` wheel installed together with its matching
`triton` wheel + `rocm-hip-libraries`/`miopen-hip`/`roctracer`/`rocprofiler-register` +
`/opt/rocm-7.2.1/lib` on the loader path + the WSL-compatible `libhsa-runtime64.so` inside the
venv's `torch/lib` + `HSA_ENABLE_DXG_DETECTION=1`.

Evidence: the 2026-09-12 ten-video audit, §4.1. The device appears with this combination; the
cheaper combinations measured the same day did not (see
[the three measured failure modes](#the-three-measured-failure-modes)).

## The five invariants, and the stage that asserts each

Run the check from the repository root, with no arguments:

```bash
cd bilibili-asr-archive
python3.12 scripts/check_asr_env.py; echo "exit=$?"
```

Exit status is `0` iff all five stages pass, `1` otherwise. On failure each failing stage adds
its own `cause:` line and the commands that clear it, then this document is named once.

| # | Stage name | Invariant the stage asserts |
|---|---|---|
| 1 | `dxg-detection` | `/dev/dxg` exists **and** `HSA_ENABLE_DXG_DETECTION=1` — one invariant with two halves, both required together |
| 2 | `rocm-loader-path` | a `/opt/rocm-*/lib` directory is reachable by the dynamic loader, via `LD_LIBRARY_PATH` or an `/etc/ld.so.conf.d/*rocm*` entry |
| 3 | `torch-present` | torch is importable **and** is a ROCm build (`torch.version.hip` is non-empty) |
| 4 | `hsa-runtime` | the `libhsa-runtime64.so*` in the venv's `torch/lib` is the WSL-compatible system runtime, not the wheel-bundled copy |
| 5 | `device-probe` | a **subprocess** reports `torch.cuda.is_available() == True` and a non-empty `gcnArchName` |

Four of the five need a word of explanation, because each is deliberately narrower or wider
than it looks:

- **`dxg-detection` is a conjunction, not a choice.** The DXG device node *and* the environment
  variable are checked as one invariant, and both must hold. Without the node there is no DXG
  transport; without `HSA_ENABLE_DXG_DETECTION=1` the HIP runtime never looks for it and never
  sees the WSL GPU. A missing half is named in the failure text
  (`dxg_device=missing …` or `… HSA_ENABLE_DXG_DETECTION=unset`). In a container, the node has
  to be passed in (`--device /dev/dxg`).
- **`rocm-loader-path` asserts discoverability, never a version.** The version is globbed
  (`/opt/rocm-*/lib`), so no single machine's `/opt/rocm-7.2.1/lib` becomes the contract.
  Either source — an `LD_LIBRARY_PATH` entry or an `/etc/ld.so.conf.d/*rocm*` line — is enough.
- **`hsa-runtime` decides identity from the filesystem.** It passes when the entry in
  `torch/lib` resolves outside `torch/lib`, or when its bytes match a system copy found in the
  discovered ROCm directories (`/usr/lib*`, `/usr/local/lib`). It fails when `torch/lib` still
  holds the wheel-bundled copy that aborts on WSL.
- **`device-probe` runs in a child process on purpose.** The measured failure is a hard abort,
  not a clean `False`; an abort inside the check's own process would be a crash instead of a
  verdict. The parent classifies the child: exit `0` with a device and a `gcnArchName` passes,
  anything else (non-zero exit, timeout, no payload) fails with the child's last stderr line.

A passing run prints exactly this shape — the four `check: <stage> ok` lines, then the one
stage that carries a detail line, then the verdict. The device values are the measured
target's:

```text
check: dxg-detection ok
check: rocm-loader-path ok
check: torch-present ok
check: hsa-runtime ok
check: device ok name=AMD Radeon RX 7800 XT arch=gfx1101 vram_gb=15.8 hip=7.2.0
asr-env: verified
```

Note the asymmetry that the check's format fixes: the passing device line reads
`check: device ok …`, while the *failing* line for the same stage reads
`check: device-probe FAIL …`.

On a host with no working device, the same command exits `1` and prints, per failing stage:

```text
check: dxg-detection FAIL dxg_device=missing HSA_ENABLE_DXG_DETECTION=unset
  cause: WSL2 has no usable DXG transport: the HIP runtime needs both the DXG device node and HSA_ENABLE_DXG_DETECTION=1
  fix:
    export HSA_ENABLE_DXG_DETECTION=1   # persist it in ~/.bashrc for later shells
    ls -l /dev/dxg   # absent: install the Windows AMD driver with WSL support, run "wsl --update", then "wsl --shutdown"; in a container pass --device /dev/dxg
    HSA_ENABLE_DXG_DETECTION=1 python3.12 scripts/check_asr_env.py   # re-run with both invariants held
check: rocm-loader-path FAIL …   # then one cause:/fix: block per failing stage
  recipe: docs/wsl-rocm-gpu.md
asr-env: not verified (5 failed)
```

(`…` marks output elided here; the lines above the elision are the real transcript from a host
with no GPU and no ROCm, one `cause:`/`fix:` block per failing stage.)

## The recipe

The steps are ordered as the stages that depend on them. Two conventions for the commands
below: `<venv>` is the virtual environment that runs `bili-asr` (steps 6–7 write into it, so
create and activate it first), and the measured session ran as root, so its transcript carries
no `sudo` — the prefixes added here are only privilege, never a different command.

### 1. Add the ROCm 7.2.1 apt repository

```bash
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://repo.radeon.com/rocm/rocm.gpg.key | sudo gpg --dearmor -o /etc/apt/keyrings/rocm.gpg
echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/rocm.gpg] https://repo.radeon.com/rocm/apt/7.2.1 noble main" \
  | sudo tee /etc/apt/sources.list.d/rocm.list
printf 'Package: *\nPin: origin repo.radeon.com\nPin-Priority: 1001\n' | sudo tee /etc/apt/preferences.d/rocm.pref
sudo apt-get update
```

### 2. Install the ROCm 7.2.1 runtime

```bash
sudo apt-get install -y --no-install-recommends rocminfo rocm-core rocm-hip-runtime rocm-smi-lib
```

### 3. Install ROCDXG — the WSL GPU transport (`rocdxg-roct` 1.2.2)

```bash
cd /tmp
curl -sSL -o rocdxg.deb \
  https://github.com/ROCm/librocdxg/releases/download/v1.2.2/rocdxg-roct_1.2.2_amd64.deb
sudo dpkg -i rocdxg.deb
ls -la /opt/rocm/lib/librocdxg.so /usr/lib/librocdxg.so 2>/dev/null
```

### 4. Install the ROCm userspace libraries

```bash
sudo apt-get install -y --no-install-recommends rocm-hip-libraries miopen-hip roctracer rocprofiler-register
```

Check that the libraries landed next to the runtime (the measured session verified these five):

```bash
for l in libMIOpen.so.1 libhipblas.so.2 libhipsparse.so.1 libroctx64.so.4 librocprofiler-register.so.0; do
  find /opt/rocm-7.2.1/lib -maxdepth 1 -name "$l*" | head -1
done
```

### 5. Put `/opt/rocm-7.2.1/lib` on the loader path

```bash
echo /opt/rocm-7.2.1/lib | sudo tee /etc/ld.so.conf.d/rocm-7.2.1.conf
sudo ldconfig
ldconfig -p | grep -cE 'libroctx64|libMIOpen'
```

The check prints a version-agnostic form of the same step, which is what to use when the ROCm
version is not 7.2.1:

```bash
ROCM_LIB=$(ls -d /opt/rocm-*/lib | sort -V | tail -1); echo "$ROCM_LIB" | sudo tee /etc/ld.so.conf.d/rocm.conf; sudo ldconfig
```

An `export LD_LIBRARY_PATH="$ROCM_LIB:$LD_LIBRARY_PATH"` in the shell that runs ASR satisfies
`rocm-loader-path` too, but the `ld.so.conf.d` file is what survives into every later shell.

### 6. Install the repo.radeon.com torch and triton wheels into the venv

This step is the sharp edge of the whole recipe: the wheel has to come from **repo.radeon.com**,
and `triton` has to go in with it, in the same command. The download is pinned to the pair
measured on 2026-09-12:

```bash
mkdir -p ~/amd-whl && cd ~/amd-whl
BASE=https://repo.radeon.com/rocm/manylinux/rocm-rel-7.2
for f in \
  "torch-2.9.1%2Brocm7.2.0.lw.git7e1940d4-cp312-cp312-linux_x86_64.whl" \
  "triton-3.5.1%2Brocm7.2.0.gita272dfa8-cp312-cp312-linux_x86_64.whl"; do
  out=$(printf '%s' "$f" | sed 's/%2B/+/')
  curl -sSL -o "$out" "$BASE/$f"
done
ls -l ~/amd-whl
```

Then install both files in **one** command, into the venv that runs `bili-asr`:

```bash
<venv>/bin/python -m pip install \
  ~/amd-whl/torch-2.9.1+rocm7.2.0.lw.git7e1940d4-cp312-cp312-linux_x86_64.whl \
  ~/amd-whl/triton-3.5.1+rocm7.2.0.gita272dfa8-cp312-cp312-linux_x86_64.whl
<venv>/bin/python -c "import torch; print(torch.__version__, torch.version.hip)"
```

Expect `2.9.1+rocm7.2.0.lw` and a non-empty `hip` (the measured target reported `hip=7.2.0`).
Two notes:

- The measured session passed a third wheel in the same command,
  `torchaudio-2.9.0+rocm7.2.0.gite3c6ee2b-cp312-cp312-linux_x86_64.whl` from the same index;
  add it to the same command if your stack imports `torchaudio`. The `torch` + `triton` pair
  above is the part that was measured to matter.
- `scripts/check_asr_env.py` prints the unpinned form of this step —
  `pip install --index-url https://repo.radeon.com/rocm/manylinux/rocm-rel-7.2/ torch triton` —
  which resolves the same wheel family from the same index and installs whatever version that
  index currently serves. It is the right form when the pinned filenames above have rotated off
  the index; the pins are the measured pair. Note that `--index-url` replaces PyPI for that one
  command, whereas installing the downloaded files leaves ordinary dependency resolution on PyPI.

### 7. Replace the HSA runtime inside the venv's `torch/lib`

The wheel ships its own `libhsa-runtime64.so`, and that bundled copy is the one that aborts on
WSL. It must be the system runtime instead:

```bash
TORCH_LIB=$(<venv>/bin/python -c 'import pathlib, torch; print(pathlib.Path(torch.__file__).parent / "lib")')
cd "$TORCH_LIB"
ls libhsa-runtime64.so*                                   # the wheel-bundled copy
rm -f libhsa-runtime64.so*
cp -v /opt/rocm-7.2.1/lib/libhsa-runtime64.so.1.18.70201 libhsa-runtime64.so
ls -l libhsa-runtime64.so*
```

On a different ROCm version the copy source is the same file with that version's suffix
(`/opt/rocm-<version>/lib/libhsa-runtime64.so.1.*`). The check prints an equivalent form that
copies every `libhsa-runtime64.so*` from the discovered ROCm lib directory.

### 8. Hold `HSA_ENABLE_DXG_DETECTION=1`, and prove the device

```bash
export HSA_ENABLE_DXG_DETECTION=1
echo 'export HSA_ENABLE_DXG_DETECTION=1' >> ~/.bashrc
```

Then run the measured proof — import, device properties, and a matmul on the device:

```bash
HSA_ENABLE_DXG_DETECTION=1 <venv>/bin/python - <<'PY'
import torch, time
print("torch:", torch.__version__, "| hip:", torch.version.hip, "| cuda:", torch.cuda.is_available())
if torch.cuda.is_available():
    p = torch.cuda.get_device_properties(0)
    print("device:", torch.cuda.get_device_name(0), "| arch:", p.gcnArchName,
          "| vram:", round(p.total_memory / 2**30, 1), "GB")
    a = torch.randn(4096, 4096, device="cuda"); t = time.time()
    for _ in range(20):
        a = a @ a * 0.001
    torch.cuda.synchronize(); print(f"GPU 4096² matmul x20: {time.time() - t:.2f}s")
PY
```

On the measured target this printed `cuda: True`, `arch: gfx1101`, `vram: 15.8 GB`, and
completed the matmul on the device. Finally, the check should now agree:

```bash
cd bilibili-asr-archive && python3.12 scripts/check_asr_env.py; echo "exit=$?"
```

## The three measured failure modes

All three were measured on 2026-09-12 while looking for a working path. They are listed here so
that a failure on your host can be recognised for what it is instead of re-diagnosed from
scratch.

### 1. ROCm 5.7 — the GPU is not in the runtime's support list

ROCm 5.7 has no `gfx1101` support at all. The RX 7800 XT is therefore not a device the runtime
can target, and no amount of device configuration downstream changes that: the arch is missing
from the support list itself. This is the defect that the removed README line
("ROCm 5.7+ drivers") published. The fix is the 7.2.1 runtime of steps 1–2.

### 2. The PyTorch.org ROCm wheel — imports cleanly, then reports no device

The ROCm wheel published on PyTorch's own index installs and imports, sets
`torch.version.hip`, and then `torch.cuda.is_available()` is `False`. There is no exception and
no traceback, so it reads like "this machine has no GPU" rather than "this wheel cannot work
here" — which is how it stayed published. This is the measured dead end on WSL: it is *not* a
path to try before this document, and the repository no longer recommends it anywhere. What
fixes it is step 6 (the repo.radeon.com pins), on top of steps 1–5.

### 3. Forcing DXG detection on that wheel — a hard abort

With the same wheel and `HSA_ENABLE_DXG_DETECTION=1`, the process dies instead of returning
`False`, aborting inside torch's bundled `librocprofiler-sdk` with:

```text
Found 0 rocprofiler agents and 2 HSA agents
```

That bundled profiler stack is documented by AMD as unsupported on WSL. Two consequences run
through the rest of this document: the failure is a `SIGABRT` rather than a return value —
which is why `check_asr_env.py` probes the device in a subprocess and why a
`check: device-probe FAIL exit -6: …` line is a normal verdict and not a crash — and the
verified recipe therefore carries both the userspace libraries (step 4) and the replacement of
the bundled HSA runtime (step 7) rather than the wheel's own copy.

## CPU fallback

The device string stays `cuda` even on AMD, because ROCm is reached through the CUDA-compatible
HIP layer. When the device cannot be enabled, run without it:

```bash
BILI_ASR_DEVICE=cpu bili-asr asr --bvid <bvid>
```

CPU mode needs none of the invariants above — no `/dev/dxg`, no ROCm, no ROCm build of torch —
and is the same line the check prints with its `device-probe` fix. Replace `<bvid>` with a video
id, as in the other `docs/` runbooks (`--bvid BV1eiPczHEqg` is one of the videos in the measured
run). It is slower; for a large archive, fix the device instead.

For the multi-hour livestream campaign on the same WSL host, see `docs/wsl-long-live.md`.
