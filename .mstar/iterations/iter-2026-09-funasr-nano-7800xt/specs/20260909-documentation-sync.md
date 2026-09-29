# Plan: Documentation Sync

**Plan ID**: 20260909-documentation-sync  
**Iteration**: iter-2026-09-funasr-nano-7800xt  
**Owner**: writing-specialist  
**Status**: Todo  
**Effort**: 1h

## Objective

Update all user-facing documentation to reflect the FunASR-Nano GPU migration, ensuring users understand new hardware requirements, performance expectations, and API compatibility changes.

**User Value**: Clear installation guidance prevents "it doesn't work" issues; accurate performance estimates (44 hours vs 130 hours) help users plan archival runs; API compatibility notes prevent confusion.

**Measurable Outcome**: Zero "SenseVoice" references in user-facing docs; GPU requirements documented with explicit ROCm installation command; FunASR API usage clarified.

## Scope

### In Scope
- Update README.md with new model and GPU requirements
- Update PLAN.md ASR engine comparison
- Update pyproject.toml description
- Add ROCm installation prerequisites

### Out of Scope
- Detailed ROCm troubleshooting guide (beyond installation link)
- Performance benchmarking documentation (actual measured speeds on user's hardware)
- Multi-GPU setup instructions
- Alternative GPU vendor support (NVIDIA CUDA, Intel Arc)

## Technical Design

### File Changes

1. **`bilibili-asr-archive/pyproject.toml`** (line 8):
   ```toml
   # Before:
   description = "Bilibili ASR transcript archival CLI (AI/CC subtitles first, local SenseVoice fallback)"
   
   # After:
   description = "Bilibili ASR transcript archival CLI (AI/CC subtitles first, local FunASR-Nano GPU fallback)"
   ```

2. **`bilibili-asr-archive/README.md`**:
   - Search for "SenseVoice" → replace with "FunASR-Nano"
   - Add GPU requirements section (after installation):
     ```markdown
     ### GPU Requirements (AMD 7800XT with ROCm)
     
     The ASR fallback uses GPU acceleration and requires:
     - AMD 7800XT GPU with ROCm 5.7+ drivers
     - PyTorch with ROCm support: `pip install torch --index-url https://download.pytorch.org/whl/rocm6.0`
     - FunASR: `pip install -e "bilibili-asr-archive/[asr]"`
     
     **Note**: AMD ROCm uses a CUDA-compatible layer (HIP), so PyTorch still uses `device="cuda"`.
     
     For CPU-only mode, override device: `BILI_ASR_DEVICE=cpu` (slower, not recommended for large archives).
     
     For other GPU vendors (NVIDIA, Intel), see the [PyTorch installation guide](https://pytorch.org/get-started/locally/).
     ```

3. **`bilibili-asr-archive/PLAN.md`**:
   - Section 2.3 "ASR 引擎（CPU 环境）" → rename to "ASR 引擎"
   - Update table (lines 62-67):
     ```markdown
     | 模型 | 中文CER | GPU 速度 (7800XT) | 备注 |
     |---|---|---|---|
     | **FunASR-Nano-2512（首选）** | ~8% | **50x+ 实时** | 轻量高效，ROCm 6.0+ |
     | SenseVoice-Small | 7.81% | 17x (CPU) | 已弃用，见本次迁移 |
     | Paraformer-Large | 10.18% | 40x+ (GPU) | 备选，更大模型 |
     ```
   - Line 68: Update conclusion
     ```markdown
     **结论：FunASR-Nano-2512（GPU）**。2200h / 50x / AMD 7800XT → 约 44 小时，GPU 加速显著优于 CPU。
     ```
   - Section 4 (lines 92-100): Update cost estimates
     ```markdown
     | ASR（GPU 50x, 7800XT 单卡） | 约 2 天（按字幕覆盖率打折） |
     ```

4. **`bilibili-asr-archive/src/bili_asr/asr.py`** (docstring, line 1):
   ```python
   # Before:
   """Local SenseVoice ASR boundary.
   
   # After:
   """Local FunASR-Nano ASR boundary.
   ```

## Tasks

1. **Update pyproject.toml** — 5min
   - Change package description line 8
   - Verify: `grep description pyproject.toml` shows "FunASR-Nano GPU fallback"

2. **Update README.md** — 20min
   - Replace all "SenseVoice" model name references
   - Add GPU requirements section after installation
   - Include ROCm installation command with PyTorch index URL
   - Add reference to PyTorch installation guide for other GPU vendors
   - Verify: `grep -i sensevoice README.md` returns no matches in prose

3. **Update PLAN.md** — 25min
   - Rename section 2.3 from "ASR 引擎（CPU 环境）" to "ASR 引擎"
   - Update comparison table: FunASR-Nano as 首选, mark SenseVoice as 已弃用 with "见本次迁移"
   - Update time estimates: change "2200h / 17x = 130h" to "2200h / 50x = 44h"
   - Update section 4 cost table with GPU specs
   - Verify: Table shows FunASR-Nano with "50x+ 实时" and "已弃用" tag on SenseVoice

4. **Update source docstrings** — 10min
   - Update `src/bili_asr/asr.py` module docstring (line 1): "Local FunASR-Nano ASR boundary"
   - Add API compatibility note in docstring explaining that ASRConfig retains `offline`/`local_source` for backward compatibility but these aren't passed to FunASR
   - Scan inline comments for stale "SenseVoice" references
   - Verify: `grep -n SenseVoice src/bili_asr/asr.py` returns only comments explaining migration history (if any)

## Acceptance Criteria

### String References (verify by grep)
- [ ] No "SenseVoice" references remain in user-facing docs (`grep -i sensevoice README.md PLAN.md pyproject.toml` returns no matches in prose; code comments may remain)
- [ ] `pyproject.toml` description mentions "FunASR-Nano GPU fallback" (line 8)
- [ ] README.md contains "FunASR-Nano" in model description
- [ ] PLAN.md table shows FunASR-Nano as "首选" (preferred) with 50x+ speed

### GPU Requirements Documentation (verify by inspection)
- [ ] README.md contains dedicated "GPU Requirements" section with exact ROCm installation command
- [ ] ROCm installation command is: `pip install torch --index-url https://download.pytorch.org/whl/rocm6.0`
- [ ] Documentation explains that ROCm uses CUDA-compatible HIP layer (clarifies `device="cuda"` usage)
- [ ] CPU fallback documented with `BILI_ASR_DEVICE=cpu` environment variable
- [ ] GPU time estimates in PLAN.md reflect realistic 44-hour total (2200h / 50x)

### Deprecated Model Marking (verify by inspection)
- [ ] PLAN.md table marks SenseVoice-Small as "已弃用" (deprecated) with reference to "本次迁移" (this migration)

## Dependencies

- **Hard dependency**: 20260909-core-asr-migration must complete first
  - Reason: Documentation must reference actual implementation (model name, device defaults)
  - Verification: Cannot document GPU requirements until ROCm detection code exists
  - Impact: Wait for implementation before documenting behavior
  
- **Soft dependency**: 20260909-test-suite-update should complete first
  - Reason: Confirms model name string is correct before documenting it
  - Verification: Test provenance assertions prove correct model ID
  - Impact: Recommended sequencing, but not blocking (can proceed in parallel if needed)

## Blocked By

None.
