# PM Acceptance: 20260909-core-asr-migration

**Date**: 2026-09-09  
**Reviewer**: project-manager  
**Plan Status**: Todo → Done

## Acceptance Criteria Verification

### ✅ Code Changes
- [x] `DEFAULT_MODEL` is `"FunAudioLLM/Fun-ASR-Nano-2512"` (verified in commit ff084e8)
- [x] `ASRConfig` defaults to `device="cuda"` (verified in asr.py line 53)
- [x] ROCm unavailable triggers clear `ASRDependencyError` with installation hint (verified in asr.py lines 103-116)
- [x] Explicit `device="cpu"` config still works (verified by test_cpu_override_skips_gpu_check)
- [x] No breaking changes to public API (ASRRunner constructor, transcribe() unchanged)

### ✅ Runtime Behavior
- [x] CUDA check present and correct (`torch.cuda.is_available()`)
- [x] Error message includes ROCm installation command: `pip install torch --index-url https://download.pytorch.org/whl/rocm6.0`
- [x] PyTorch ImportError handled gracefully
- [x] Unsupported FunASR kwargs removed from AutoModel call (`offline`, `local_source`)

### ✅ API Compatibility
- [x] ASRConfig schema unchanged (offline/local_source fields retained)
- [x] Environment variable BILI_ASR_MODEL still works
- [x] CPU override via ASRConfig works

### ✅ Test Coverage
- [x] All existing tests pass (23 passed)
- [x] New error path tests added (CUDA unavailable, torch import, CPU override)
- [x] Test assertions updated for new kwargs

## QC Review
- **Initial**: CONDITIONAL (C1: test failures, C2: missing error tests)
- **Re-review**: PASS (all critical findings resolved)

## Decision
**Status**: Done  
**Verdict**: ACCEPT — all acceptance criteria met, QC PASS, tests green

Plan 20260909-core-asr-migration is complete and ready to merge to integration branch.
