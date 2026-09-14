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

## A2/A4/A5 on the target — NOT COMPLETED (host filesystem failure, not a product defect)

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
