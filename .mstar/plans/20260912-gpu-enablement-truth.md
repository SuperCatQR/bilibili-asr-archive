# Verified GPU enablement: recipe, runtime hint, environment self-check

> Iteration `iter-2026-09-asr-ops-hardening`, spec point 1 → acceptance **A1**.
> Primary spec: `.mstar/iterations/iter-2026-09-asr-ops-hardening/specs/01-gpu-enablement.md`.
> Execution mode: `sdd` (3 tasks).

## Status

- Priority: P0
- Task category: `ops` / documentation + environment diagnosis
- Status: Done
- Depends on: nothing (first plan of the iteration)
- Owner: fullstack-dev · QA gate: mandatory (environment contract; see QA gate reason below)
- Findings cleanup: zero-residual
- Evidence: `.mstar/iterations/iter-2026-09-asr-ops-hardening/guides/2026-09-12-ten-video-audit.md` §4.1

## Goal

The published GPU path produces a working device on the operator's actual target, and an
operator can tell in one command whether their environment satisfies it — instead of
following a recipe that ends in a hard abort.

## Specify (measured defects)

- **G1.** `bilibili-asr-archive/README.md` L20–31 publishes "AMD 7800XT GPU with ROCm 5.7+
  drivers" and `pip install torch --index-url https://download.pytorch.org/whl/rocm6.0`.
  ROCm 5.7 has no `gfx1101` support; the PyTorch.org ROCm wheel imports but
  `torch.cuda.is_available()` is `False`, and with `HSA_ENABLE_DXG_DETECTION=1` it aborts
  (`Found 0 rocprofiler agents and 2 HSA agents`, torch's bundled `librocprofiler-sdk`) —
  a WSL configuration AMD documents as unsupported for that wheel family.
- **G2.** `src/bili_asr/asr.py` repeats the same broken command in its runtime hint, so the
  error message a user sees when the device is missing points at the path that cannot work.
- **G3.** The verified path (audit guide §4.1) exists only as session knowledge: ROCm 7.2.1
  runtime + `rocdxg-roct` 1.2.2, the **repo.radeon.com** wheel
  `torch 2.9.1+rocm7.2.0.lw` installed with its matching `triton` wheel,
  `rocm-hip-libraries`/`miopen-hip`/`roctracer`/`rocprofiler-register`,
  `/opt/rocm-<ver>/lib` on the loader path, the WSL-compatible `libhsa-runtime64.so` inside
  the venv's `torch/lib`, and `HSA_ENABLE_DXG_DETECTION=1`. Nothing in the repository
  records it, and nothing checks it.

## Clarify (decisions — spec 01 owns the detail)

1. **Recipe location**: a new `bilibili-asr-archive/docs/wsl-rocm-gpu.md` holds the verified
   recipe; `README.md` shrinks to the invariants, one command, and a link.
2. **Self-check shape**: `bilibili-asr-archive/scripts/check_asr_env.py`, not a new CLI
   subcommand and not an extension of `verify` (the frozen CLI surface at
   `.mstar/specs/asr-archive-cli.md` L30–44 stays intact).
3. **Exit contract**: exit `0` iff all five stages pass (`dxg-detection`, `rocm-loader-path`,
   `torch-present`, `hsa-runtime`, `device-probe`); exit `1` otherwise, printing per-stage
   remediation. The device probe runs in a **subprocess** because the measured failure mode
   is a hard abort, not a `False`.
4. **No pinned machine layout**: the loader-path stage asserts discoverability of a
   `/opt/rocm-*/lib` directory (via `LD_LIBRARY_PATH` or `ld.so.conf.d`), never a version.
5. **Hint text**: `asr.py`'s hint names pointer tokens (`ROCm`, `scripts/check_asr_env.py`,
   `docs/wsl-rocm-gpu.md`, `BILI_ASR_DEVICE=cpu`) and carries no URL to the broken wheel.

## Non-goals

- Installing ROCm, ROCDXG, or drivers; auto-detecting a device; benchmarking GPU throughput.
- Changing `ASRConfig.device`'s default or the `BILI_ASR_DEVICE` override semantics.

## Architecture

| Surface | Change |
|---|---|
| `bilibili-asr-archive/docs/wsl-rocm-gpu.md` | New: verified recipe + invariants + failure modes |
| `bilibili-asr-archive/scripts/check_asr_env.py` | New: five-stage environment check, exit 0/1 |
| `bilibili-asr-archive/README.md` | GPU section shrinks to invariants + one command + link |
| `bilibili-asr-archive/src/bili_asr/asr.py` | Runtime hint → pointer tokens, no broken URL |
| `bilibili-asr-archive/tests/test_asr_reproducibility.py` | The hint test asserts the new tokens |

## Tasks

### Task 1: Environment self-check with five stages

**Files:**
- Create: `bilibili-asr-archive/scripts/check_asr_env.py`
- Test: `bilibili-asr-archive/tests/test_check_asr_env.py`

**Interfaces:**
- Consumes: `torch.cuda.is_available()` / `get_device_properties`, `/dev/dxg`, the loader search path, the venv's `torch/lib`.
- Produces: `main(argv) -> int`; stage results as `(name, ok, remediation)`; exit `0` iff every stage passes.

- [x] Implement the five stages in order: `dxg-detection` (`/dev/dxg` present), `rocm-loader-path` (a `/opt/rocm-*/lib` directory is discoverable via `LD_LIBRARY_PATH` or an `ld.so.conf.d` entry — never a pinned version), `torch-present` (importable, reports `torch.version.hip`), `hsa-runtime` (the `libhsa-runtime64.so` in the venv's `torch/lib` is the system one, not the bundled copy), `device-probe` (a **subprocess** runs `torch.cuda.is_available()` and prints the device name, because the measured failure is a hard abort rather than `False`).
- [x] On failure print, per failing stage, the verified remediation from `docs/wsl-rocm-gpu.md` (stage name, one-line cause, the commands that fix it) and exit `1`.
- [x] On success print one line naming the device (`gfx1101` / `AMD Radeon RX 7800 XT`) and exit `0`.
- [x] Make every probe injectable so the tests exercise pass/fail paths without a GPU or ROCm install.
- [x] Test: each stage's pass and fail path via injected probes; the subprocess contract (abort → failure, not a traceback leak); exit codes.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_check_asr_env.py -v`

### Task 2: The verified WSL/ROCm recipe document

**Files:**
- Create: `bilibili-asr-archive/docs/wsl-rocm-gpu.md`

**Interfaces:**
- Consumes: audit guide §4.1 (the measured recipe and the three failure modes); `docs/` house style (see `docs/wsl-long-live.md`).
- Produces: the single operator-facing source the self-check's remediation text points at.

- [x] Document the verified recipe end to end: ROCm 7.2.1 runtime, `rocdxg-roct` (ROCDXG), the **repo.radeon.com** wheel `torch 2.9.1+rocm7.2.0.lw` installed together with its matching `triton` wheel, `rocm-hip-libraries`/`miopen-hip`/`roctracer`/`rocprofiler-register`, `/opt/rocm-<ver>/lib` on the loader path, the WSL-compatible `libhsa-runtime64.so` inside the venv's `torch/lib`, and `HSA_ENABLE_DXG_DETECTION=1`.
- [x] Record the five invariants the self-check asserts, mapping each to its stage name.
- [x] Record the three failure modes measured on 2026-09-12 and what each one looks like: no `gfx1101` in ROCm 5.7; `is_available() == False` from the PyTorch.org wheel; the `Found 0 rocprofiler agents and 2 HSA agents` abort with `HSA_ENABLE_DXG_DETECTION=1`.
- [x] State the CPU fallback (`BILI_ASR_DEVICE=cpu`) and that this document installs nothing.
- [x] Every command must be paste-ready and copy-verified against the audit guide.

Run: `cd bilibili-asr-archive && grep -c 'rocdxg\|repo.radeon.com\|HSA_ENABLE_DXG_DETECTION' docs/wsl-rocm-gpu.md`

### Task 3: Published surfaces stop recommending the broken path

**Files:**
- Modify: `bilibili-asr-archive/README.md`
- Modify: `bilibili-asr-archive/src/bili_asr/asr.py`
- Modify: `bilibili-asr-archive/docs/wsl-rocm-gpu.md` (one line — Task 2 review M8)
- Test: `bilibili-asr-archive/tests/test_asr_reproducibility.py`

**PM decisions carried into this task (Task 1/2 review Minors):**
- **M7** — `check_asr_env.py`'s printed `--bvid <bvid>` token stays byte-identical (that script is outside this task's file list), and `README.md` keeps the literal `bili-asr asr --bvid <bvid>` inside prose so the A2 grep still matches, **while** every paste-ready example in the README uses a concrete bvid. `docs/wsl-rocm-gpu.md` must be consistent with that split.
- **M8** — fix the relative `cd` at `docs/wsl-rocm-gpu.md:279` so the recipe works in a same-shell run (the reproduced failure was `exit=1` before the check ever ran).

**Interfaces:**
- Consumes: the self-check path and the recipe document from Tasks 1–2.
- Produces: README invariants + one command + link; an `asr.py` hint that names pointer tokens only.

- [x] Shrink the README GPU section to the invariants, one command (`python3.12 scripts/check_asr_env.py`), and a link to `docs/wsl-rocm-gpu.md`; delete the "ROCm 5.7+" claim and the PyTorch.org wheel command.
- [x] Replace `asr.py`'s runtime hint with pointer tokens (`ROCm`, `scripts/check_asr_env.py`, `docs/wsl-rocm-gpu.md`, `BILI_ASR_DEVICE=cpu`) and no machine layout or broken URL.
- [x] Update the hint test to assert the new tokens and to fail if `download.pytorch.org/whl/rocm` reappears in the hint.
- [x] Confirm `grep -rn 'download.pytorch.org/whl/rocm' bilibili-asr-archive/README.md bilibili-asr-archive/src bilibili-asr-archive/docs` is empty.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_asr_reproducibility.py -v`

## Verification

- `python3.12 bilibili-asr-archive/scripts/check_asr_env.py` on the target exits `0` and
  names the device; on a host without a device it exits `1` with remediation.
- `grep -rn 'download.pytorch.org/whl/rocm' bilibili-asr-archive/README.md bilibili-asr-archive/src/ bilibili-asr-archive/docs/`
  returns nothing.
- `python -m pytest -q` green; `tests/test_asr_cues.py` unmodified (A6 guard).

## Evidence log

| Date | Evidence |
|------|----------|
| 2026-09-12 | T1 `89d9c15` — `scripts/check_asr_env.py` five stages + 40 tests; task review Approved with Minor (0C/0I/5M). |
| 2026-09-12 | T2 `4753b81` + fix `1e285ba` — `docs/wsl-rocm-gpu.md`; review Request Changes (doc asserted T3's outcome) → fix → re-review Approved with Minor. |
| 2026-09-12 | T3 `0e4e5b0` + fix `5cade0b` — published surfaces corrected; review Request Changes (`pilot` overclaim) → fix → re-review Approved with Minor. |
| 2026-09-12 | Plan QC tri (N=3, one batch): all three seats Request Changes, 0 Critical / 5 Important / 10 Warning; consolidated at `{SDD_DIR}/review/qc-consolidated.md`. |
| 2026-09-13 | QC fix wave 1 `77e3cc1` (5/5 Important, 9/10 Warning) → targeted re-review `Approve with residuals` (N-1 destructive `rm`, N-2 vacuous guard test, R-1 non-runnable evidence line). |
| 2026-09-13 | QC fix wave 2 `4b02245` (N-1/N-2/R-1) → final re-review **Approve** for `8c8f119..4b02245`. |
| 2026-09-13 | L4 QA gate (`review/qa-gate.md`): **Approve with residuals**; found N-1 (`asr.py` bare invocation). |
| 2026-09-13 | QA fix `a14d732` + `01a39f1` (hint names the venv interpreter in plain language) → QA re-verification: **N-1 CLOSED**, final **Approve with residuals**. |
| 2026-09-13 | Full suite at head `01a39f1`: **1402 passed / 4 skipped**. A1 negative empty from the worktree (exit 1, discriminated from exit 2). A6 guard byte-identical. |

## Review Gate Summary

| Gate | Decision | Notes |
|------|----------|-------|
| Task reviews | Approved with Minor ×3 | 0 Critical / 0 open Important across all three tasks after fix rounds |
| Plan QC | **Approve** | tri-review N=3 (one batch); 5 Important + 10 Warning closed over two fix waves; final re-review `review/qc-fix-2-review.md` |
| QA gate | **Approve with residuals** | L4 acceptance-only; A1(i)/(ii) target half unproven from this host; residuals R1 (medium), R2 (low), N-3 (low) |

**Unproven and who runs it:** A1(i)/(ii) require the WSL2 + RX 7800 XT target. The operator runs
`"$VENV/bin/python" scripts/check_asr_env.py` from `bilibili-asr-archive/` on that host and reads the
exit code plus the `device ok` line; a control-checkout run reports a false failure and must not be used.
