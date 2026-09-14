---
module: WSL2 AMD GPU ASR environment
date: 2026-09-13
problem_type: architecture_pattern
category: architecture-patterns
severity: medium
plan_id: 20260912-gpu-enablement-truth
applies_when:
  - enabling an AMD GPU for local ASR on WSL2 through the ROCDXG transport
  - torch imports but torch.cuda.is_available() is False, or the process aborts inside librocprofiler-sdk
  - ImportError for libroctx64.so.4 or libMIOpen.so.1 while importing torch
  - deciding whether a missing device is a runtime, wheel, or Windows-driver problem
  - adding or running a host-level "is my GPU usable" pre-flight check
tags:
  - wsl2-rocm
  - amd-gpu
  - rocdxg
  - dxg-detection
  - hsa-runtime
  - repo-radeon-wheel
  - environment-self-check
---

# Enabling GPU ASR on WSL2 with an AMD ROCm GPU

## Context

Under WSL2 an AMD GPU is reached through ROCDXG, not the Linux kernel driver. Only one specific
runtime + transport + wheel + loader-path + HSA-runtime + environment-variable combination yields a
visible device, and each missing piece surfaces as a different symptom — most of them reading as "this
machine has no GPU" rather than "this combination cannot work here". The two published shortcuts
(ROCm 5.7, the pytorch.org ROCm wheel) are dead ends that do not announce themselves.

## Guidance

**1. The working combination (verified on the target host).** ROCm **7.2.1** runtime + `rocdxg-roct`
**1.2.2** (ROCDXG) + the **repo.radeon.com** wheel `torch 2.9.1+rocm7.2.0.lw` installed **in one pip
command together with its matching `triton`** wheel + `rocm-hip-libraries`, `miopen-hip`, `roctracer`,
`rocprofiler-register` + `/opt/rocm-7.2.1/lib` on the loader path (an `/etc/ld.so.conf.d/` file, so it
survives into later shells) + the WSL-compatible `libhsa-runtime64.so` in the venv's torch library
directory + `HSA_ENABLE_DXG_DETECTION=1`.

**2. Two steps carry most of the failure modes.** (a) That `libhsa-runtime64.so` must be the **system**
runtime, not the wheel-bundled copy that aborts on WSL: remove the bundled copies *first*, then copy the
system file — a bare `cp -f` can leave a differently-suffixed bundled `.so.1` beside it. (b)
`HSA_ENABLE_DXG_DETECTION=1` is what makes the device visible through the Windows driver; without it the
HIP runtime never looks for the DXG node and never sees the WSL GPU. That is the least obvious step in
the stack, and it is one invariant with two halves — the `/dev/dxg` path **and** the variable.

**3. Symptom → cause chain.** Each symptom's real cause differs from what it looks like:

| Symptom | Real cause | What clears it |
|---|---|---|
| `ImportError: librocctx64.so.4` / `libMIOpen.so.1` on `import torch` | the ROCm userspace libraries are absent, or the loader cannot resolve them | install `roctracer`/`miopen-hip`, re-run `ldconfig`, confirm `ldconfig -p` finds them |
| hard abort inside torch's bundled `librocprofiler-sdk` (`Found 0 rocprofiler agents and 2 HSA agents`) | the **wrong wheel** — the pytorch.org ROCm wheel, whose bundle cannot work under WSL | install the repo.radeon.com `torch` + matching `triton` in one command |
| a clean import that still reports no device | DXG detection off, the bundled HSA runtime still in place, or a runtime with no `gfx1101` support | steps 1–2; a runtime predating `gfx1101` cannot be fixed downstream |

Row 2's abort (not a `False`) is why a device probe belongs in a **subprocess**: in-process it would crash
the checker instead of producing a verdict.

**4. The Windows driver was not the fix.** The working session left the Windows driver **unchanged**; the
fix was entirely userspace. On the version string: `32.0.31035.1003` is backed by no retained evidence
file in this repository, so treat "the driver was left unchanged, upgrading it is not the fix" as the
load-bearing claim and the number as unverified. A missing `/dev/dxg` is a driver or `wsl --update`
matter (in a container, pass `--device /dev/dxg`); a device that exists but stays invisible is a userspace
matter.

**5. Run the five-stage self-check instead of trusting the recipe.** From the product directory, with the
interpreter that holds torch — a bare `python`/`python3.12` picks the wrong environment and reports
`torch-present FAIL` on a correctly built host:

```bash
cd bilibili-asr-archive && export VENV=~/.venvs/bili-asr
"$VENV/bin/python" scripts/check_asr_env.py; echo "exit=$?"
```

| # | Stage | Invariant asserted | A failure means |
|---|---|---|---|
| 1 | `dxg-detection` | `/dev/dxg` exists **and** `HSA_ENABLE_DXG_DETECTION=1` | no WSL GPU transport, or detection is off |
| 2 | `rocm-loader-path` | a `/opt/rocm-*/lib` holding `libhsa-runtime64.so*` is reachable via `LD_LIBRARY_PATH` or an `/etc/ld.so.conf.d/*rocm*` entry (version globbed, never pinned) | libs missing or undiscoverable |
| 3 | `torch-present` | torch is importable **in the running interpreter** and is a ROCm build (`torch.version.hip` non-empty) | wrong interpreter, or a missing/non-ROCm wheel |
| 4 | `hsa-runtime` | the `libhsa-runtime64.so*` in the venv's torch library directory is the system runtime (resolves out of `torch/lib` into a discovered system lib dir, or the bytes match) | the wheel-bundled copy is still in place |
| 5 | `device-probe` | a **subprocess** reports a usable device with a non-empty `gcnArchName` | the abort above, a timeout, or a clean `False` |

Exit is `0` iff all five pass, `1` when any fails (each failing stage prints its own `cause:` and fix
commands), `2` for a usage error (`-h`/`--help` exits `0`). A `2` can also mean the script was not found —
an unset or wrong product path — so check the directory before reading it as a verdict.

## Why This Matters

ROCm 5.7 has no `gfx1101` in its support list, and the pytorch.org ROCm wheel imports cleanly, sets
`torch.version.hip`, and then reports no device — or dies with `SIGABRT` under DXG detection. The
symptom→cause mapping turns either into a five-minute diagnosis, and a *checked* recipe keeps itself
honest as versions rotate: the host re-asserts the invariants at run time and fails loudly with
remediation.

## When to Apply

- Standing up or repairing GPU ASR on a WSL2 host with an AMD GPU (measured on an RX 7800 XT /
  `gfx1101`; the ROCDXG and DXG-detection invariants are WSL-wide, the wheel and version pins are not).
- Any "torch imports but the device is missing or the process aborts" report, before touching drivers.
- Building a pre-flight check for a host environment contract: assert invariants by name, run the risky
  probe out of process, and let the failure output carry the fix.
- Not for NVIDIA/Intel hosts; no substitute for a CPU run (`BILI_ASR_DEVICE=cpu`).

## Examples

```bash
# Both measured dead ends: ROCm 5.7 has no gfx1101 in its support list; the pytorch.org ROCm wheel
# imports and then reports no device, or aborts under DXG detection.
# The working userspace pieces (docs/wsl-rocm-gpu.md carries the full, ordered recipe):
"$VENV/bin/python" -m pip install --index-url https://repo.radeon.com/rocm/manylinux/rocm-rel-7.2/ torch triton
ROCM_LIB=$(ls -d /opt/rocm-*/lib | sort -V | tail -1)
TORCH_LIB=$("$VENV/bin/python" -c 'import pathlib, torch; print(pathlib.Path(torch.__file__).parent / "lib")')
rm -f "$TORCH_LIB"/libhsa-runtime64.so* && cp -f "$ROCM_LIB"/libhsa-runtime64.so* "$TORCH_LIB"/
export HSA_ENABLE_DXG_DETECTION=1          # persist it in ~/.bashrc
```

A passing check prints the five stage lines, this device line and the verdict. The same run measured ten
archived parts / 125 min of audio at decode `rtf_avg` **0.097–0.150**, 21.8 min wall (≈ 16.3 min decode
+ ≈ 5.6 min per-item overhead — that overhead belongs to `run-scoped-asr-provenance.md`, not to setup):

```text
check: device ok name=AMD Radeon RX 7800 XT arch=gfx1101 vram_gb=15.8 hip=7.2.0
asr-env: verified
```

## Evidence

- Iteration spec: `.mstar/iterations/iter-2026-09-asr-ops-hardening/specs/01-gpu-enablement.md`
  (D1.1–D1.9: stage names, exit contract, the subprocess device probe, the widened negative rule).
  Plan `20260912-gpu-enablement-truth`; SDD package `{SDD_DIR}/20260912-gpu-enablement-truth/`.
- Measurement: `.mstar/iterations/iter-2026-09-asr-ops-hardening/guides/2026-09-12-ten-video-audit.md`
  §4.1 (the three failure modes, the verified combination) and §1 (10 videos / 125 min / `rtf_avg`
  0.097–0.150 / 21.8 min wall); the driver version was dropped as unsourced in `scope-rationale.md` §2.
- Implementation: `bilibili-asr-archive/docs/wsl-rocm-gpu.md` (shipped operator recipe),
  `bilibili-asr-archive/scripts/check_asr_env.py` (five stages + remediation text),
  `bilibili-asr-archive/README.md` GPU section, `bilibili-asr-archive/src/bili_asr/asr.py` device hint.
- Verification status: the **device itself** was measured on the target (`gfx1101`, 15.8 GB, matmul on
  device). The check's own exit-`0` run against a real device is **not** evidenced here — plan QA
  exercised the pass path with injected probes from a non-GPU checkout and marked A1(i)/(ii)'s target
  half `NOT VERIFIED FROM THIS HOST` (`{SDD_DIR}/20260912-gpu-enablement-truth/review/qa-gate.md`).
