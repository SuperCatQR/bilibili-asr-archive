# Delivery — iter-2026-09-asr-ops-hardening

**Status:** completed · **started** 2026-09-12 · **ended** 2026-09-13 · **merge** `9aa1013` → `main`
**Origin:** the 2026-09-12 ten-video GPU run's measured defects (`guides/2026-09-12-ten-video-audit.md`)

## What changed, by spec point

| # | Acceptance | Delivered |
|---|-----------|-----------|
| 1 | **A1** GPU enablement is *checked*, not asserted | `scripts/check_asr_env.py` (five stages — dxg-detection, rocm-loader-path, torch-present, hsa-runtime, device-probe — exit 0/1/2) and `docs/wsl-rocm-gpu.md`; the README's GPU section now points at a runnable self-check. **A1(i)/(ii)/(iii) verified on the target box 2026-09-14** — five stages `ok`, `AMD Radeon RX 7800 XT arch=gfx1101 vram_gb=15.8`, exit 0; with the DXG invariant removed, exit 1 with cause and fix per stage (`guides/2026-09-13-target-host-verification.md`) |
| 2 | **A2** batch model reuse is real and visible | `ASRRunner.model_constructions` (monotonic) + `RunSummary.model_constructions`/`.asr_items`; one line per batch on **stderr** — `<command>: model constructions=<n> for <m> asr item(s)` — labelled per command, printed whenever a construction was paid **or** ASR items ran; `_cmd_asr`/`_pilot_archive_asr` hold one runner per invocation; `run_batch` refuses re-entry |
| 3 | **A3** one quality surface | content reasons folded into `coverage --quality`: `DEFECT_REASON_CODES` decide validity while `CONTENT_REASON_CODES` are advisory, `--reference` agreement with a basename-only JSON block, bounded comparison, separator-aware redaction; `scripts/asr_quality.py` retired with its map verified signal-by-signal |
| 4 | **A4** the archive names its producer | `BILI_ASR_MODEL_ID` → the `model_name` slot (never a new key, so the nine-key contract holds); a path can never be an identifier; a declaration contradicting the load value raises. Reproducible from the README alone |
| 5 | **A5** how much audio, and where the doubt is | `asr_vad_segments` / `asr_vad_captured_s` / `asr_vad_captured_ratio` (ASR rows only) and `asr_low_confidence_at` (ascending 3-decimal starts, rendered from the same filtered list as the count) |
| 6 | **A6** the cue text held still | `tests/test_asr_cues.py` and `tests/fixtures/asr-cues/` byte-identical across every plan's diff |

## Gates

| plan | QC (tri N=3, one batch) | QA gate | suite |
|------|------------------------|---------|-------|
| `20260912-gpu-enablement-truth` | Approve with residuals — 0 Critical / 5 Important / 10 Warning, two fix waves | Approve with residuals | 1402 |
| `20260912-batch-model-reuse` | Approve with residuals — 0 Critical; three seats found the same Important independently | Approve with residuals | 1432 |
| `20260912-quality-signal-merge` | Approve with residuals — 0 Critical / 6 Important, one fix wave | Approve with residuals | 1491 |
| `20260912-asr-provenance-identity` | Approve with residuals — 0 Critical / 1 Important / 2 Warning / 8 Suggestion | Approve with residuals | 1565 |

**Zero Critical across all four tri-reviews.** Every Important was closed and re-reviewed; every residual was registered with an owner and a target (`projects/_default/residuals.json`).

## Knowledge promoted

- **New** `{KNOWLEDGE_DIR}/architecture-patterns/wsl-rocm-gpu-asr.md` — the WSL2/AMD GPU recipe: the working wheel pairing (the upstream ROCm wheel aborts inside the profiler), the HSA runtime and DXG detection that make the device visible, and the failure chain each symptom maps to.
- **Refreshed** `run-scoped-asr-provenance.md` (reuse line, declared identity, redaction rule, VAD capture facts, located doubt) and `operational-sidecars.md` (two-class quality vocabulary, the retired script, the bounded `--reference`).

## Carried forward

1. **R1 (medium, inherited)** — `scripts/verify_baseline.py`'s staged tree still cannot collect `tests/test_check_asr_env.py` (`rc=2`, zero tests); the fix is ~2 lines in a file no plan here owned.
2. **R1 (low)** — the model-load attempt count is recorded but printed nowhere an operator can see (needs an A2-aware amendment of spec 02 D2.6).
3. **R2 (low)** — model-load retries stay unbounded per row.
4. **R1/R2 (low, quality)** — the retirement map's `asr_low_confidence_at` row predates this iteration's surface work; the repeated-ngram scan is bounded only by the artefact byte cap.
5. **DONE (2026-09-14)** — A1(i)/(ii)/(iii) verified on the target box; see `guides/2026-09-13-target-host-verification.md`.
6. **Operator action (host capacity)** — that box's Windows `C:` is down to **0.2 GB free**, which remounted the WSL2 root filesystem read-only (`emergency_ro`) and blocked the A2/A4/A5 end-to-end probe. Free space on `C:` or move the distro to `D:` (413 GB free), then re-run the probe.
