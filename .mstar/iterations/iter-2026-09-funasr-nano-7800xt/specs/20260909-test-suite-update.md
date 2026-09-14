# Plan: Test Suite Update

**Plan ID**: 20260909-test-suite-update  
**Iteration**: iter-2026-09-funasr-nano-7800xt  
**Owner**: fullstack-dev  
**Status**: Todo  
**Effort**: 1.5h

## Objective

Update all test files to reference FunASR-Nano model, ensuring test suite validates the migrated ASR implementation.

**User Value**: Prevents regression; ensures the 50x GPU speedup works correctly without breaking existing CLI/API behavior.

**Measurable Outcome**: Full test suite passes (`pytest tests/ -v` returns exit code 0) with zero "SenseVoice" references in assertions.

## Scope

### In Scope
- Update hardcoded model references in tests
- Update error message assertions
- Update provenance test expectations
- Verify all mocked model interactions still work

### Out of Scope
- Adding new GPU-specific integration tests (tests remain mocked)
- Performance benchmarking or speed regression tests
- Testing actual FunASR-Nano model behavior (only test mocks and string references)
- Updating test fixtures for different GPU environments (AMD vs NVIDIA)
- Adding pytest markers for GPU-required tests (mocking makes this unnecessary)

## Technical Design

### Files to Update

1. **`tests/test_asr_reproducibility.py`**:
   - Line 217: Change provenance assertion
     ```python
     # Before:
     assert provenance["model_name"] == "iic/SenseVoiceSmall"
     
     # After:
     assert provenance["model_name"] == "FunAudioLLM/Fun-ASR-Nano-2512"
     ```
   - Lines 225-227: Update example paths
     ```python
     # Before:
     "/opt/models/SenseVoiceSmall",
     "C:\\models\\SenseVoiceSmall",
     
     # After:
     "/opt/models/Fun-ASR-Nano-2512",
     "C:\\models\\Fun-ASR-Nano-2512",
     ```

2. **`tests/test_cli_pilot.py`**:
   - Line 338-339: Update error message in `missing_asr` stub
     ```python
     # Before:
     f"SenseVoice support is not installed; run: {hint}"
     
     # After:
     f"FunASR support is not installed; run: {hint}"
     ```
   - Line 365: Update `ASRDependencyError` message
     ```python
     # Before:
     raise ASRDependencyError("SenseVoice support is not installed")
     
     # After:
     raise ASRDependencyError("FunASR support is not installed")
     ```

3. **`tests/test_mixed_outcome_contract.py`**:
   - Line 88: Update error message constant
     ```python
     # Before:
     "SenseVoice support is not installed",
     
     # After:
     "FunASR support is not installed",
     ```
   - Line 461: Update `ASRDependencyError` message
     ```python
     # Before:
     raise asr_mod.ASRDependencyError("SenseVoice support is not installed")
     
     # After:
     raise asr_mod.ASRDependencyError("FunASR support is not installed")
     ```

4. **`tests/test_cli_asr.py`**:
   - Line 211: Update error message in `missing_asr` stub
     ```python
     # Before:
     f"SenseVoice support is not installed; run: {hint}"
     
     # After:
     f"FunASR support is not installed; run: {hint}"
     ```

5. **`src/bili_asr/asr.py`**:
   - Line 23: Update main error message
     ```python
     # Before:
     f"SenseVoice support is not installed; run: {_INSTALL_HINT}"
     
     # After:
     f"FunASR support is not installed; run: {_INSTALL_HINT}"
     ```
   - Line 44: Update exception docstring
     ```python
     # Before:
     """SenseVoice could not load or transcribe the supplied audio."""
     
     # After:
     """FunASR model could not load or transcribe the supplied audio."""
     ```
   - Line 117, 136: Update error messages
     ```python
     # Before:
     "SenseVoice model load/transcription failed; check configured local model."
     
     # After:
     "FunASR model load/transcription failed; check configured local model."
     ```

### Device Default Impact

Tests should continue to pass because:
- Mocked `fake_funasr` fixture doesn't actually load model
- Tests use `model_factory` injection, bypassing real model load
- Device parameter is only used at actual `AutoModel` construction
- Removal of `offline` and `local_source` from AutoModel kwargs doesn't affect mocked tests

## Tasks

1. **Update test_asr_reproducibility.py** — 20min
   - Update provenance assertions
   - Update example model paths

2. **Update error message tests** — 30min
   - test_cli_pilot.py stub messages
   - test_mixed_outcome_contract.py stubs
   - test_cli_asr.py stubs

3. **Update asr.py error messages** — 15min
   - Main import error
   - Exception docstrings
   - Load/transcription errors

4. **Run test suite** — 25min
   - Execute full test suite
   - Fix any unexpected failures
   - Verify coverage unchanged

## Acceptance Criteria

### String References (verify by grep)
- [ ] No "SenseVoice" strings remain in test assertions (`grep -r "SenseVoice" tests/` returns only comments/docstrings, not assertions)
- [ ] Provenance tests assert `"FunAudioLLM/Fun-ASR-Nano-2512"` (test_asr_reproducibility.py line 217)
- [ ] Error message tests match "FunASR support is not installed" (grep confirms 4 files updated)

### Test Execution (verify by running pytest)
- [ ] `pytest tests/ -v` returns exit code 0 (all tests pass)
- [ ] `pytest tests/test_asr_reproducibility.py -v` passes with updated provenance assertions
- [ ] `pytest tests/test_cli_pilot.py tests/test_cli_asr.py -v` passes with updated error message assertions
- [ ] `pytest tests/test_mixed_outcome_contract.py -v` passes with updated stub references

### Coverage (verify by pytest-cov)
- [ ] Test coverage remains ≥ baseline (run `pytest --cov=bili_asr tests/` and compare to pre-migration coverage report)

## Dependencies

- **Hard dependency**: 20260909-core-asr-migration must complete first
  - Reason: Tests assert against `DEFAULT_MODEL` constant and error messages defined in asr.py
  - Verification: Cannot run updated tests until asr.py constants are changed
  - Impact: This plan is blocked until core migration completes

## Blocked By

None.
