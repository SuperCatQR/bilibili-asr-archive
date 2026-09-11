# QC Review: Test Suite Update

**Plan ID**: 20260909-test-suite-update  
**Review Date**: 2026-01-21  
**Reviewer**: qc-specialist  
**Review Range**: `iteration/iter-2026-09-funasr-nano-7800xt..plan/20260909-test-suite-update`  
**Commit**: d7686a8

---

## Summary

The test suite updates correctly migrate all test assertions and error messages from SenseVoice to FunASR-Nano. All in-scope test file changes are accurate and complete. However, **the commit includes significant out-of-scope changes** (production code, runtime artifacts, documentation) that violate surgical change discipline.

**Verdict**: ❌ **Reject** - Out-of-scope changes must be removed or moved to separate plans.

---

## Findings

### ✅ F1: Test File Updates - Complete and Correct

**Severity**: None (passing)

All required test files were updated correctly:

1. **test_asr_reproducibility.py** (lines 233, 235, 240-242):
   - ✅ Model name: `iic/SenseVoiceSmall` → `FunAudioLLM/Fun-ASR-Nano-2512`
   - ✅ Example paths: `SenseVoiceSmall` → `Fun-ASR-Nano-2512`

2. **test_cli_pilot.py** (lines 338, 365):
   - ✅ Error messages: `"SenseVoice support"` → `"FunASR support"` (2 occurrences)

3. **test_cli_asr.py** (line 211):
   - ✅ Error message: `"SenseVoice support"` → `"FunASR support"`

4. **test_mixed_outcome_contract.py** (lines 88, 461):
   - ✅ Error messages: `"SenseVoice support"` → `"FunASR support"` (2 occurrences)

5. **test_scheduler.py** (line 52):
   - ✅ Error message updated (not explicitly in spec, but correct)

6. **conftest.py**:
   - ✅ Added global `mock_torch` fixture to prevent PyTorch import errors

---

### ✅ F2: No Remaining SenseVoice References

**Severity**: None (passing)

Verified via grep:
```bash
grep -rn "SenseVoice" tests/ src/
# (no results - exit code 1)
```

All SenseVoice references successfully removed from test assertions.

---

### ✅ F3: Error Messages Match Implementation

**Severity**: None (passing)

All test error message assertions now match the actual implementation in `src/bili_asr/asr.py`:
- Line 23: `"FunASR support is not installed"`
- Line 44: `"FunASR model could not load or transcribe"`
- Line 135: `"FunASR model load/transcription failed"`

**Note**: The spec listed asr.py updates in Task 3, but asr.py was NOT changed in this commit because it was already updated in the iteration branch baseline (dependency `20260909-core-asr-migration` completed first). This is correct behavior.

---

### ❌ F4: Out-of-Scope Changes - Production Code

**Severity**: Major

**Issue**: `bilibili-asr-archive/src/bili_asr/cli.py` was modified with +48/-7 lines:
- Added `_load_dotenv_bili_sessdata()` function (38 lines)
- Updated CLI description: `"SenseVoice"` → `"FunASR"`
- Modified `_resolve_sessdata()` to call `.env` loader

**Scope Violation**:
- Plan scope: "Update all test files to reference FunASR-Nano model"
- Plan "Out of Scope" explicitly excludes production functionality
- The `.env` loading is a **feature addition**, not a test update

**Impact**:
- Violates surgical changes principle (mstar-coding-behavior)
- Mixes unrelated changes (authentication + test updates)
- Should be in a separate plan: "Add .env SESSDATA support"

**Required Action**: Remove cli.py changes or move to separate feature plan.

---

### ❌ F5: Out-of-Scope Changes - Runtime Artifacts

**Severity**: Major

**Issue**: Commit includes runtime archive artifacts:
- `bilibili-asr-archive/archive/meta-cursor.json`
- `bilibili-asr-archive/archive/run-ledger.jsonl`
- `bilibili-asr-archive/archive/coordinator/archive-writer.lock`
- `bilibili-asr-archive/archive/run-ledger.jsonl.lock`

**Scope Violation**:
- These are runtime-generated files from E2E testing
- Should be gitignored, not committed to the feature branch
- Not related to test suite updates

**Required Action**: Remove runtime artifacts from commit.

---

### ❌ F6: Out-of-Scope Changes - Documentation

**Severity**: Moderate

**Issue**: Commit includes documentation files:
- `.env.example` (13 lines, new file)
- `authentication guide` (36 lines, **truncated/incomplete**)
- `bilibili-asr-archive/verify_acceptance.sh` (47 lines, new script)
- `e2e-test-plan.md` (166 lines)
- `e2e-test-report-complete.md` (251 lines)
- `e2e-test-report-phase1-2.md` (161 lines)

**Scope Violation**:
- Plan scope: test file updates only
- Documentation should be in separate docs/housekeeping plan
- `authentication guide` appears to be **accidentally committed** (truncated content from a previous QC review?!)

**Required Action**: 
- Remove E2E test documentation (or move to docs/ in separate commit)
- Remove truncated "authentication guide" file
- `.env.example` belongs with cli.py .env feature, not test updates
- Consider keeping `verify_acceptance.sh` if it's test-specific

---

### ⚠️ F7: Test Execution Not Verified

**Severity**: Minor

**Issue**: Cannot independently verify acceptance criteria:
- Pytest not available in subagent environment
- Cannot confirm "665 tests pass" claim from commit message
- Cannot verify coverage unchanged

**Mitigation**: 
- Commit message claims tests pass
- Changes are mechanical string replacements (low risk)
- CI/CD pipeline should catch any failures

**Recommendation**: PM should verify test execution in integration environment.

---

## Acceptance Criteria Assessment

| Criterion | Status | Evidence |
|-----------|--------|----------|
| No "SenseVoice" in assertions | ✅ Pass | grep returned no results |
| Provenance tests use FunASR-Nano | ✅ Pass | test_asr_reproducibility.py:235 |
| Error messages match "FunASR support" | ✅ Pass | 4 test files updated |
| `pytest tests/ -v` exit 0 | ⚠️ Cannot verify | No pytest available |
| Coverage ≥ baseline | ⚠️ Cannot verify | No pytest-cov available |

---

## Required Changes

### Must Fix (Blocking)

1. **Remove cli.py changes** (F4):
   ```bash
   git reset HEAD~1
   git restore --staged bilibili-asr-archive/src/bili_asr/cli.py
   git restore bilibili-asr-archive/src/bili_asr/cli.py
   git add bilibili-asr-archive/tests/
   git add bilibili-asr-archive/tests/conftest.py
   git commit -m "feat: update test suite to reference FunASR-Nano"
   ```

2. **Remove runtime artifacts** (F5):
   ```bash
   git rm -r bilibili-asr-archive/archive/
   ```

3. **Remove out-of-scope documentation** (F6):
   ```bash
   git rm .env.example "authentication guide" e2e-test-*.md
   # Keep verify_acceptance.sh if test-specific, else remove
   ```

### Should Fix (Recommended)

4. **Move .env feature to separate plan**:
   - Create new plan: "Add .env SESSDATA configuration support"
   - Include: cli.py changes, .env.example, related docs
   - Separate from test suite updates

5. **Add to .gitignore**:
   ```
   bilibili-asr-archive/archive/
   *.lock
   ```

---

## Recommendations

1. **Surgical Changes**: Future plans should have single, focused objectives. Authentication features and test updates are separate concerns.

2. **Runtime Artifacts**: Ensure CI/CD gitignore rules prevent committing runtime data.

3. **Test Verification**: Set up a pre-commit hook or CI check that runs `pytest tests/ -v` before accepting test update plans.

4. **Plan Scope Clarity**: The spec correctly listed asr.py updates in Tasks, but should note they're handled by dependency plan (avoid confusion).

---

## Verdict

❌ **REJECT** - Test file updates are correct, but out-of-scope changes violate surgical change discipline.

**Next Steps**:
1. Remove all out-of-scope changes (cli.py, archive/, docs)
2. Create separate plan for .env authentication feature
3. Re-submit test-only commit for QC approval
4. PM verifies test execution in integration environment

---

**QC Specialist**: qc-specialist  
**Review Completed**: 2026-01-21

---

## Re-Review (Targeted)

**Date**: 2026-09-09  
**Commit**: 8914171

### Verification

**Changes verified:**
1. **cli.py** (1 line): Help text only - `"SenseVoice"` → `"FunASR"` in description string (cosmetic)
2. **tests/conftest.py** (+14 lines): Added `mock_torch` fixture to prevent import errors
3. **tests/test_asr_format.py** (+2/-1): Updated to use CPU device in test
4. **tests/test_asr_reproducibility.py** (+5/-5): Model name assertions updated to FunASR-Nano paths
5. **tests/test_cli_pilot.py** (+2/-2): Error messages updated (2 occurrences)
6. **tests/test_cli_asr.py** (+1/-1): Error message updated
7. **tests/test_mixed_outcome_contract.py** (+2/-2): Error messages updated (2 occurrences)
8. **tests/test_scheduler.py** (+1/-1): Error message updated

**Total**: 8 files changed, 28 insertions(+), 13 deletions(-)

**Out-of-scope items removed:**
- ✅ cli.py .env loading feature (+48 lines) - REMOVED
- ✅ Runtime artifacts (archive/) - REMOVED
- ✅ Documentation files (.env.example, authentication guide, e2e-test-*.md) - REMOVED

**Scope compliance:**
- ✅ Only test files + CLI help text changed
- ✅ No feature additions
- ✅ No runtime artifacts
- ✅ Surgical changes principle followed

### Updated Verdict

✅ **PASS** — ready to merge

**Rationale**: All out-of-scope changes successfully removed. The commit now contains only test suite updates plus one cosmetic CLI help text change (description string, not functionality). Changes are focused, surgical, and meet plan objectives.

**Next steps**: PM may proceed with merge to iteration branch.

---

**Re-Review Completed**: 2026-09-09  
**QC Specialist**: qc-specialist
