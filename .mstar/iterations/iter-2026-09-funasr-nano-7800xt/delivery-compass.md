---
iteration_id: iter-2026-09-funasr-nano-7800xt
title: "Migrate ASR to FunASR-Nano on AMD 7800XT GPU"
status: completed
start_date: 2026-09-09
end_date: 2026-09-09
iteration_base_branch: main
spec_integration_branch: iteration/iter-2026-09-funasr-nano-7800xt
target_branch: main
effort_scale: S
---

# Iteration: Migrate ASR to FunASR-Nano on AMD 7800XT GPU

## Direction Lock

**User Request**: Replace SenseVoice-Small with FunAudioLLM/Fun-ASR-Nano-2512, running on AMD 7800XT GPU.

**Grill-me Decisions**:
1. Model: `FunAudioLLM/Fun-ASR-Nano-2512` (verified HuggingFace model ID)
2. Device: Change default from `device="cpu"` to `device="cuda"` (AMD ROCm uses CUDA-compatible HIP layer)
3. ROCm support: `torch.cuda.is_available()` returns True for both NVIDIA CUDA and AMD ROCm PyTorch builds; add runtime check with AMD-specific installation command
4. API compatibility: Remove unsupported `offline`/`local_source` kwargs from FunASR AutoModel call (retain in ASRConfig for backward compatibility)
5. Migration scope: Complete migration (code + all tests + documentation)

**Success Criteria**:
- ASR runs on AMD 7800XT GPU using FunASR-Nano model (verify: `torch.cuda.is_available()` returns True, model loads to CUDA device)
- FunASR AutoModel called with correct API parameters only: `model`, `device`, `trust_remote_code`, `model_revision` (verify: no `offline` or `local_source` in kwargs)
- All tests pass with new model references (verify: `pytest tests/ -v` returns 0 exit code)
- Documentation reflects FunASR-Nano in README.md, PLAN.md, pyproject.toml (verify: `grep -r "SenseVoice" *.md pyproject.toml` returns no matches in user-facing text)
- Runtime detection provides clear error with specific ROCm installation command when CUDA unavailable (verify: error contains `pip install torch --index-url https://download.pytorch.org/whl/rocm6.0`)
- No breaking changes to CLI interface or ASRRunner API (verify: existing user code examples in docs run without modification)

**Non-Goals**:
- Dual-model support (SenseVoice removal is intentional; users cannot choose between models)
- Automatic ROCm installation (users must install ROCm + PyTorch-ROCm manually)
- Device auto-detection logic (device hardcoded to `cuda`; users must explicitly override with `BILI_ASR_DEVICE=cpu` if needed)
- Performance benchmarking or GPU profiling
- Migration path for existing SenseVoice model weights or caches

## Scope

### In Scope
- Update `DEFAULT_MODEL` to FunAudioLLM/Fun-ASR-Nano-2512
- Change `ASRConfig` default `device` to `"cuda"`
- Add ROCm/CUDA availability check at model load time with specific installation command
- Remove unsupported `offline` and `local_source` parameters from FunASR AutoModel API call
- Update all test fixtures and model references
- Sync documentation (README.md, PLAN.md, pyproject.toml description)

### Out of Scope
- Keeping SenseVoice as fallback option
- CPU performance optimization
- Model download automation beyond FunASR defaults

## Plans

### Execution Sequence
**Sequential order (hard dependencies):**
1. Plan 1 (Core ASR Migration) → executes first, blocks Plans 2 & 3
2. Plan 2 (Test Suite Update) → executes after Plan 1 completes
3. Plan 3 (Documentation Sync) → executes after Plans 1 & 2 complete

**Rationale:** Tests assert against implementation constants; documentation describes tested behavior.

### Plan 1: Core ASR Migration
**File**: `20260909-core-asr-migration.md`
**Owner**: fullstack-dev
**Estimate**: 2h

Modify `src/bili_asr/asr.py`:
- Change `DEFAULT_MODEL` constant
- Change `ASRConfig.device` default to `"cuda"`
- Add ROCm detection in `ASRRunner._get_model()` with clear error message
- Remove `offline` and `local_source` from AutoModel kwargs (FunASR API doesn't support them)
- Retain ASRConfig fields for backward compatibility

### Plan 2: Test Suite Update
**File**: `20260909-test-suite-update.md`
**Owner**: fullstack-dev
**Estimate**: 1.5h

Update all test files referencing model name:
- `test_asr_reproducibility.py` (provenance tests)
- `test_cli_pilot.py`, `test_cli_asr.py` (error message assertions)
- `test_mixed_outcome_contract.py` (stub references)
- Any test that hardcodes "SenseVoice" strings

### Plan 3: Documentation Sync
**File**: `20260909-documentation-sync.md`
**Owner**: writing-specialist
**Estimate**: 1h

Update all documentation:
- `README.md` — replace SenseVoice with FunASR-Nano, add ROCm prerequisite
- `PLAN.md` — update ASR engine comparison table, note GPU requirement
- `pyproject.toml` — update package description
- Add GPU/ROCm setup notes

## Delivery Branch Policy
- **Base**: `main` (current HEAD at iteration start)
- **Integration**: `iteration/iter-2026-09-funasr-nano-7800xt`
- **Target**: `main` (PR after iteration-close)

## Definition of Done

The iteration is complete when:
1. All three plans marked "Done" in workflow snapshot
2. Full test suite passes: `pytest tests/ -v` returns exit code 0
3. No "SenseVoice" references in user-facing documentation (verified by grep)
4. PR to `main` is merge-ready (all CI checks green, QC complete)
5. Integration branch contains all commits from completed plans

## Risks & Mitigation
- **Risk**: FunASR-Nano output format differs from SenseVoice, breaking downstream transcript processing
  - **Likelihood**: Low (both use FunASR library with compatible API)
  - **Mitigation**: `normalize_result()` already handles multiple FunASR shapes; verify with unit test against real FunASR-Nano output
  - **Verification**: Run test_asr_reproducibility.py with actual model, inspect transcript structure
- **Risk**: ROCm not installed in CI/test environment, blocking automated test execution
  - **Likelihood**: Medium (CI likely CPU-only)
  - **Mitigation**: Tests already mock model via `model_factory` injection; GPU-specific tests remain mocked (no real GPU needed)
  - **Verification**: Tests pass in CPU-only environment with mocked model
- **Risk**: User attempts to run on unsupported GPU (older AMD cards without ROCm support)
  - **Likelihood**: Medium
  - **Mitigation**: Error message provides AMD ROCm 6.0 installation command; NVIDIA CUDA users can use standard PyTorch
  - **Verification**: Manual test with `torch.cuda.is_available()=False` triggers expected error with installation guidance
- **Risk**: FunASR API parameter mismatch breaks model loading
  - **Likelihood**: Low (now verified against official API documentation)
  - **Mitigation**: Only pass supported parameters (`model`, `device`, `trust_remote_code`, `model_revision`) to AutoModel
  - **Verification**: Review FunASR source code and test with actual AutoModel instantiation

## Blocked By
None.

## Dependencies
None (standalone iteration).
