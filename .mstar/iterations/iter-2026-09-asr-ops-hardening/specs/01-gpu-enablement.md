---
spec: 01-gpu-enablement
iteration: iter-2026-09-asr-ops-hardening
owner_plan: 20260912-gpu-enablement-truth
spec_point: 1 — Truthful GPU enablement
serves: A1 (guard: A6)
status: draft — iteration-scoped, promoted or dropped at iteration-close
---

# Contract 01 — Verified GPU recipe + one runtime self-check

## Contract

The repository stops publishing an unverified AMD path. The measured ROCm/ROCDXG recipe becomes a checked recipe:
`docs/wsl-rocm-gpu.md` carries it, `scripts/check_asr_env.py` asserts its invariants on the host, and `README.md`
names that one check as the answer to "is my GPU usable for ASR". `asr.py`'s device-unavailable hint points at both
and repeats no vendor index URL.

## Decisions

- **D1.1 Recipe home = `bilibili-asr-archive/docs/wsl-rocm-gpu.md` (new).** `README.md` L20–31 becomes a ~8-line
  block: verified target, the three invariants, the check command, the CPU fallback, and the doc link. *Rejected:*
  recipe inline in `README.md` — it is six steps of environment surgery and `docs/` already owns WSL environment
  detail (`docs/wsl-long-live.md`, `docs/audio-retention-policy.md`).
- **D1.2 Check = `bilibili-asr-archive/scripts/check_asr_env.py`**, run as `python3.12 scripts/check_asr_env.py`
  from the repository root. *Rejected:* extending `bili-asr verify` — `verify` is the archive-integrity reader
  (manifest/attempts/artifacts) and would conflate a host probe with an archive verdict. *Rejected:* a new
  `bili-asr` subcommand — the frozen CLI surface must stay as specified (`asr-archive-cli.md` L30–44), and the check
  must still run when the package itself cannot import torch.
- **D1.3 The check asserts five named stages, in this order:** `dxg-detection`
  (`os.environ["HSA_ENABLE_DXG_DETECTION"] == "1"`), `rocm-loader-path` (a ROCm userspace lib dir is discoverable by
  the dynamic loader: a `/opt/rocm-*/lib` entry in `LD_LIBRARY_PATH` **or** an `/etc/ld.so.conf.d/*rocm*` file
  naming one — glob, never a pinned version), `torch-present` (`importlib.util.find_spec("torch")`), `hsa-runtime`
  (a `libhsa-runtime64.so*` exists in `Path(torch.__file__).parent / "lib"`, i.e. torch's own bundled dir, and
  `/proc/self/maps` shows *that* copy loaded after the device probe), `device-probe` (D1.4). The HSA loader-path and
  DXG stages are the three measured invariants of guide §4.1 L88–93; `rocm-loader-path` deliberately asserts
  *discoverability*, not one machine's `/opt/rocm-7.2.1/lib` literal.
- **D1.4 The device probe runs in a subprocess** (`sys.executable -c …`, printing one JSON line), because the
  measured failure mode is a hard abort inside torch's bundled `librocprofiler-sdk` (`Found 0 rocprofiler agents and
  2 HSA agents`, guide L85–87), not a `False`. The parent classifies the child: exit 0 with `cuda.is_available() ==
  True` and a non-empty `gcnArchName` (`gfx1101`) = pass; non-zero = `device-probe FAIL` carrying the child's last
  stderr line, truncated and redacted to scalars.
- **D1.5 Exit contract.** `0` iff all five stages pass; `1` otherwise, with one `check: <stage> FAIL <observed>`
  line per failing stage and, printed once, the remediation taken from `docs/wsl-rocm-gpu.md` plus the doc path.
  Success prints `check: device ok name=<…> arch=<gfx1101> vram_gb=<…> hip=<…>` then `asr-env: verified`.
  *Rejected:* a third "unsupported host" exit code — nothing consumes it, and a missing torch is simply
  `torch-present FAIL`.
- **D1.6 `asr.py` hint rewrite** (asr.py L319–323). The replacement message carries exactly these stable tokens:
  `ROCm`, `scripts/check_asr_env.py`, `docs/wsl-rocm-gpu.md`, `BILI_ASR_DEVICE=cpu` — and no absolute path, no ROCm
  version, no index URL. *Rejected:* embedding the recipe in the hint — one machine's layout in source is the defect
  being removed.
- **D1.7 Negative rule, widened.** The string `download.pytorch.org/whl/rocm` appears in no file of the repository —
  concretely `README.md`, `src/`, and `docs/`. The compass check greps `README.md src/` (compass L112); this
  contract extends it to `docs/` because A1's sentence is "no document or error string still recommends the
  PyTorch.org ROCm wheel for WSL". Other vendors keep the generic PyTorch selector link, re-worded so an AMD reader
  is routed to `docs/wsl-rocm-gpu.md` first.
- **D1.8 README states A1(ii)'s verification**: the archived-field check `grep -n '^asr_device:'
  <archive>/transcripts/md/<work_id>.md` with the expected value `"cuda"`. No code change — `asr_device` already
  exists (`asr.py` L232 default + `archive.py` L321 `asr_` prefixing).
- **D1.9 The doc carries the measured recipe verbatim** (ROCm runtime + ROCDXG + the repo.radeon.com wheel family +
  userspace libs + loader path + WSL-compatible `libhsa-runtime64.so` in the venv's `torch/lib` +
  `HSA_ENABLE_DXG_DETECTION=1`, guide L88–93) and nothing the guide does not measure. The compass risk row "the
  recipe rots" (compass L203) is discharged by D1.3/D1.5, not by prose.

## Exact names and shapes

| Surface | Name |
|---|---|
| doc | `bilibili-asr-archive/docs/wsl-rocm-gpu.md` |
| check script | `bilibili-asr-archive/scripts/check_asr_env.py` |
| stage names | `dxg-detection`, `rocm-loader-path`, `torch-present`, `hsa-runtime`, `device-probe` |
| pass / fail lines | `check: <stage> ok` / `check: <stage> FAIL <observed>`; final `asr-env: verified` / `asr-env: not verified (<n> failed)` |
| device line | `check: device ok name=… arch=gfx1101 vram_gb=… hip=…` |
| env (existing) | `HSA_ENABLE_DXG_DETECTION`, `BILI_ASR_DEVICE` |
| rewritten test | `tests/test_asr_reproducibility.py::test_cuda_unavailable_raises_dependency_error_with_rocm_hint` (L338–351) asserts the D1.6 tokens and the absence of the index URL |
| new test | the doc path named in the hint resolves to an existing file (drift guard) |

## Boundaries — must not change

- The `[asr]`-extra message stays `pip install -e "bilibili-asr-archive/[asr]"` (`asr.py` L33; `asr-archive-cli.md`
  L67): A1 replaces only the device-unavailable branch.
- `asr.py` stays import-clean without the `[asr]` extra (`asr-archive-cli.md` L63); the check script must not be
  imported by `cli.py`.
- Device string stays `cuda` for ROCm/HIP (`README.md` L27 note) — A1(ii) reads `asr_device: "cuda"`.
- No ROCm installation, no device auto-detection, no NVIDIA/Intel recipe rewrite (compass Non-Goals L158–160).
- Cue shaping and transcript text: nothing in this contract touches `asr.py` L125–135 / L447–546,
  `tests/test_asr_cues.py`, or `tests/fixtures/asr-cues/` (A6).

## Traceability

| Decision | Forced by |
|---|---|
| D1.1–D1.3, D1.9 | guide §4.1 L78–93: ROCm 5.7 has no `gfx1101` (L84); the PyTorch.org wheel is `False`/aborts (L85–87); the verified recipe is L88–93 |
| D1.4 | guide L86–87 (in-process abort) + A1(iii) "exits non-zero, printing the verified remediation" |
| D1.6, D1.7 | A1 negative grep + `README.md` L20–24 and `asr.py` L319–323, the two published copies of the broken path |
| D1.8 | A1(ii); `archive.py` L321 is where the field is written today |
| D1.5 | design choice: three-valued is unnecessary because nothing consumes a third code; rationale recorded rather than deferred |

## Non-goals inherited

Accuracy re-tuning, model replacement, manifest compaction, ROCm auto-installation (compass L119–160) — none is opened
here.

## Check the plan must run

The five stages are asserted from this checkout only as *code*; the target host is not reachable here. P1 must
therefore run `check_asr_env.py` on the WSL2 + RX 7800 XT host and record its exit code plus the `device ok` line, and
run it once more with `HSA_ENABLE_DXG_DETECTION` unset to prove the failure text and exit `1`. If either run
contradicts D1.3/D1.5, the plan records an amendment request against this draft rather than widening the check.
