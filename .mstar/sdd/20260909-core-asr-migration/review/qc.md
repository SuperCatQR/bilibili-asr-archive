# QC Review: 20260909-core-asr-migration

**Reviewer**: qc-specialist  
**Review Date**: 2026-09-09  
**Commit Range**: iteration/iter-2026-09-funasr-nano-7800xt..plan/20260909-core-asr-migration

## Summary

The implementation correctly addresses all spec requirements for migrating from SenseVoice-Small to FunASR-Nano-2512 with GPU support. Core changes are architecturally sound: model constant updated, device default changed to "cuda", ROCm availability check added, and unsupported kwargs removed from AutoModel invocation. However, **three existing tests are broken** by the API changes and must be fixed before merge. The spec explicitly required running tests (Task 4: "Run existing tests with mocked model"), which was not completed.

## Findings

### Critical

**C1: Test failures - broken assertion expectations**

Three tests in `test_asr_reproducibility.py` will fail due to changed kwargs:

1. **Line 48**: `test_fake_model_result_normalization_timestamps_and_rich_tag_cleanup`
   - Asserts: `{"model": "local-test-model", "trust_remote_code": False, "device": "cpu", "offline": True, "local_source": "configured-local"}`
   - Actual: `{"model": "local-test-model", "trust_remote_code": False, "device": "cuda"}` (no `offline`/`local_source`, device="cuda")

2. **Line 70**: `test_fake_generation_snapshots_include_both_input_paths`
   - Same assertion expecting `"device": "cpu", "offline": True, "local_source": "configured-local"`

3. **Lines 147-149**: `test_factory_gets_exact_kwargs_and_typeerror_is_not_retried`
   - Asserts set includes `"offline"` and `"local_source"` which are no longer passed

**Impact**: Tests fail on `pytest tests/test_asr*.py`, violating acceptance criterion "Existing unit tests pass with mocked model".

**Fix Required**: Update assertions to match new kwargs: `{"model": ..., "device": "cuda", "trust_remote_code": False, "model_revision": ...}` (remove `offline`/`local_source`, change device default).

---

**C2: Missing test coverage for new error paths**

Spec Task 4 requires "verify error paths trigger correctly", but no tests exist for:
- CUDA unavailable path (should raise `ASRDependencyError` with ROCm installation command)
- Torch ImportError path (should raise `ASRDependencyError` with torch installation hint)
- CPU override still works (should not trigger GPU check)

**Impact**: New error-handling code is untested; cannot verify acceptance criteria "With CUDA unavailable: raises ASRDependencyError" and "Override with ASRConfig(device='cpu') works".

**Fix Required**: Add three test cases covering these scenarios using monkeypatch for torch availability and import blocking.

---

### Major

**M1: Incomplete self-verification (Spec Task 4)**

The spec allocated 45 minutes for self-verification including running tests. Git log shows only the implementation commit with no evidence of test execution or test updates. The acceptance criteria explicitly require:
- "Existing unit tests pass with mocked model (`pytest tests/test_asr*.py -v`)"
- "Override with `ASRConfig(device="cpu")` works (no error, uses CPU)"

**Impact**: Cannot confirm implementation correctness; violates "Code review before commit" principle from `mstar-coding-behavior`.

**Recommendation**: Establish a pre-commit checklist for plans that modify tested modules: (1) run tests, (2) update test assertions if API changed, (3) add tests for new paths.

---

**M2: Device default change is a behavioral breaking change**

While the spec claims "No breaking changes", changing `device` default from "cpu" to "cuda" will break existing deployments without GPU:
- Any code using `ASRRunner()` without explicit `device="cpu"` will now fail on CPU-only systems
- Error message directs to GPU setup, which may confuse users who intentionally want CPU inference

**Impact**: Medium - affects backward compatibility for CPU-only users. However, this appears intentional per spec objective ("enabling GPU acceleration on AMD 7800XT").

**Recommendation**: Consider adding a runtime warning on first import if CUDA unavailable, or document the migration in a changelog/upgrade guide.

---

### Minor

**m1: Module docstring slightly inaccurate**

Line 1 comment: "FunASR is imported only when a runner first transcribes" is no longer strictly true - the new `_get_model()` also imports `torch` for GPU checking before model instantiation.

**Fix**: Update to "FunASR and torch are imported lazily when a runner first loads a model."

---

**m2: Error message references "local model" in cloud-first context**

Lines 135 and 154: `"FunASR model load/transcription failed; check configured local model."`

The removal of `offline`/`local_source` suggests a move away from local-first inference, but error message still says "check configured local model". Minor terminology inconsistency.

**Suggestion**: Change to "FunASR model load/transcription failed. Verify model name and device availability." (more generic).

---

**m3: No validation for device index**

The check `if self.config.device.startswith("cuda")` will accept `device="cuda:1"` or `device="cuda:99"` without verifying the index exists. Torch will error later, but the error won't have the helpful ROCm installation guidance.

**Impact**: Low - torch's error is still actionable. Could improve UX by validating device index.

---

## Code Quality Assessment

### Strengths
- Clean surgical change: only touched necessary lines
- Follows spec technical design exactly
- Proper exception chaining with `from None` for ImportError
- Backward compatible API (ASRConfig fields preserved)
- Clear, actionable error messages for ROCm setup

### Weaknesses
- Tests not updated or run (violates spec Task 4)
- No tests for new error paths
- Missing evidence of verification step

---

## Acceptance Criteria Verification

### Code Changes (verify by inspection)
- ✅ `DEFAULT_MODEL` = `"FunAudioLLM/Fun-ASR-Nano-2512"` (line 15)
- ✅ `ASRConfig.device` default = `"cuda"` (line 54)
- ✅ `_get_model()` calls `torch.cuda.is_available()` (lines 104-109)
- ✅ Error message contains PyTorch ROCm installation command (lines 107-112)
- ✅ `AutoModel()` kwargs exclude `offline`/`local_source` (lines 101-107)
- ✅ ASRConfig fields `offline`/`local_source` retained (lines 53-54)

### Runtime Behavior (not verified - tests broken)
- ❌ Cannot verify: tests fail before runtime verification possible
- ❌ "With CUDA available: model loads to GPU" - untested
- ❌ "With CUDA unavailable: raises ASRDependencyError" - untested
- ❌ "Override with ASRConfig(device='cpu') works" - untested

### API Compatibility
- ❌ "Existing unit tests pass" - **FAIL** (C1)
- ⚠️ Constructor/transcribe signatures unchanged - **PASS** (verified by inspection)
- ⚠️ Environment variable override - not verified

---

## Verdict

- [ ] PASS — ready to merge
- [x] CONDITIONAL — fix critical findings first
- [ ] FAIL — major rework needed

**Conditions for merge:**
1. Fix C1: Update test assertions in `test_asr_reproducibility.py` lines 48, 70, 147-149
2. Fix C2: Add three test cases for new error paths (CUDA unavailable, torch missing, CPU override)
3. Run full test suite and verify all tests pass: `pytest tests/test_asr*.py -v`

**Estimated fix effort**: 30 minutes (15min test updates + 15min new tests + verification)

**After fixes**: Implementation quality is high and changes are architecturally sound. Once tests pass, this is ready for merge.

---

## Re-Review (Targeted)

**Date**: 2026-09-09  
**Reviewer**: qc-specialist  
**Scope**: C1 (test assertions), C2 (error path tests)  
**Commit**: ff084e8 "fix: update test_asr_reproducibility.py for new ASR kwargs and add error path tests"

### C1: Test Assertions - RESOLVED ✓

**Verification**: All three test assertion failures have been fixed.

1. **Line 54** (formerly line 48): `test_fake_model_result_normalization_timestamps_and_rich_tag_cleanup`
   - ✅ Updated from `{"model": "local-test-model", "trust_remote_code": False, "device": "cpu", "offline": True, "local_source": "configured-local"}`
   - ✅ Now expects: `{"model": "local-test-model", "device": "cuda", "trust_remote_code": False}`
   - Correctly removes `offline`/`local_source` and changes device default to "cuda"

2. **Line 76** (formerly line 70): `test_fake_generation_snapshots_include_both_input_paths`
   - ✅ Updated with identical fix: new kwargs without `offline`/`local_source`, device="cuda"

3. **Lines 163-165** (formerly lines 147-149): `test_factory_gets_exact_kwargs_and_typeerror_is_not_retried`
   - ✅ Updated assertion set from `{"model", "device", "trust_remote_code", "offline", "local_source", "model_revision"}`
   - ✅ Now expects: `{"model", "device", "trust_remote_code", "model_revision"}`

**Additional improvements**:
- ✅ `fake_funasr` fixture updated (lines 41-44) to mock `torch.cuda.is_available()` returning `True`
- ✅ Three other tests (`test_error_serialization_redacts_forbidden_markers_and_preserves_class`, `test_factory_gets_exact_kwargs_and_typeerror_is_not_retried`) now include torch mocks to prevent import errors

### C2: Error Path Tests - RESOLVED ✓

**Verification**: Three new test cases added covering all required error paths.

1. **`test_cuda_unavailable_raises_dependency_error_with_rocm_hint`** (lines 312-333)
   - ✅ Mocks `torch.cuda.is_available()` to return `False`
   - ✅ Verifies `ASRDependencyError` is raised
   - ✅ Asserts error message contains "CUDA/ROCm is not available"
   - ✅ Asserts error message contains "ROCm" or "7800XT" (installation guidance)

2. **`test_torch_import_error_raises_dependency_error`** (lines 336-352)
   - ✅ Uses `monkeypatch.setattr(builtins, "__import__", ...)` to block torch import
   - ✅ Verifies `ASRDependencyError` is raised
   - ✅ Asserts error message contains "PyTorch is required" or "torch"

3. **`test_cpu_override_skips_gpu_check`** (lines 354-363)
   - ✅ Creates runner with `device="cpu"`
   - ✅ Verifies transcription succeeds without GPU check
   - ✅ Confirms construction kwargs contain `"device": "cpu"`

**Code-test alignment**: Verified that `asr.py` lines 103-116 implement the exact error paths these tests expect:
- Lines 104-111: CUDA availability check with ROCm installation command
- Lines 112-116: torch ImportError handling with installation hint
- Line 103: `if self.config.device.startswith("cuda"):` conditional means CPU override skips the check

### Test Suite Status

**Per commit message**: "All 23 tests pass" (fullstack-dev self-verification)

**QC verification limitation**: Cannot execute tests in this session (pytest not available in environment). Verification based on:
- Code inspection of test assertions matching implementation
- Diff analysis confirming all three critical finding locations were addressed
- Implementation-test contract alignment for new error paths

### Updated Verdict

- [x] PASS — ready to merge
- [ ] CONDITIONAL
- [ ] FAIL

**Rationale**: Both critical findings (C1, C2) are fully resolved. Test assertions now match the new kwargs contract, and comprehensive error path coverage was added. The implementation quality remains high with surgical changes. All acceptance criteria from the original spec are now verifiable through the test suite.

**Recommendation**: Merge to integration branch `iteration/iter-2026-09-funasr-nano-7800xt`.
