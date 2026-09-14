# Plan: Core ASR Migration

**Plan ID**: 20260909-core-asr-migration  
**Iteration**: iter-2026-09-funasr-nano-7800xt  
**Owner**: fullstack-dev  
**Status**: Todo  
**Effort**: 2h

## Objective

Migrate the ASR module from SenseVoice-Small to FunAudioLLM/Fun-ASR-Nano-2512, enabling GPU acceleration on AMD 7800XT hardware with ROCm.

**User Value**: 50x+ realtime speedup (from 17x CPU to 50x GPU), reducing 2200-hour archive from ~130 hours to ~44 hours processing time.

**Measurable Outcome**: ASR transcription runs on CUDA device with FunASR-Nano model; clear error guidance when GPU unavailable; FunASR API compatibility ensured.

## Scope

### In Scope
- Update `DEFAULT_MODEL` constant in `src/bili_asr/asr.py`
- Change `ASRConfig.device` default from `"cpu"` to `"cuda"`
- Add ROCm availability check in `ASRRunner._get_model()`
- Provide clear error message when ROCm/CUDA unavailable
- Maintain backward compatibility of `ASRRunner` API

### Out of Scope
- Device auto-detection (no logic to detect AMD vs NVIDIA vs CPU-only; hardcode `cuda`)
- Keeping SenseVoice as fallback option (complete replacement, not additive)
- Model download optimization (rely on FunASR defaults for caching/download)
- Batch processing optimization for GPU (single-file processing unchanged)
- GPU memory management or multi-GPU support
- Changing ASRConfig schema (keep `offline` and `local_source` fields for backward compatibility, but don't pass them to FunASR API)

## Technical Design

### Key Technical Decisions

1. **ROCm CUDA Compatibility**: AMD ROCm uses HIP (CUDA-compatible layer), so `device="cuda"` is correct for both NVIDIA and AMD GPUs. PyTorch's `torch.cuda.is_available()` returns True for both CUDA and ROCm builds ([PyTorch HIP documentation](https://docs.pytorch.org/docs/main/notes/hip.html)).

2. **FunASR API Compatibility**: FunASR's `AutoModel` only accepts `model`, `device`, `trust_remote_code`, `model_revision`, and `hub` parameters ([FunASR API docs](https://modelscope.github.io/FunASR/api.html)). The current implementation incorrectly passes `offline` and `local_source`, which must be removed.

3. **Backward Compatibility**: Keep `offline` and `local_source` fields in `ASRConfig` dataclass to avoid breaking existing code, but don't pass them to `AutoModel`.

### File Changes

**`src/bili_asr/asr.py`**:

1. **Model constant** (line 15):
   ```python
   # Before:
   DEFAULT_MODEL = "iic/SenseVoiceSmall"
   
   # After:
   DEFAULT_MODEL = "FunAudioLLM/Fun-ASR-Nano-2512"
   ```

2. **Device default** (line 54):
   ```python
   # Before:
   device: str = "cpu"
   
   # After:
   device: str = "cuda"
   ```

3. **ROCm detection and API cleanup** (in `ASRRunner._get_model()`, replace lines 98-119):
   ```python
   def _get_model(self) -> Any:
       if self._model is not None:
           return self._model
       
       # Check CUDA availability if device is cuda (works for both NVIDIA CUDA and AMD ROCm)
       if self.config.device.startswith("cuda"):
           try:
               import torch
               if not torch.cuda.is_available():
                   raise ASRDependencyError(
                       "CUDA/ROCm is not available. For AMD 7800XT, install PyTorch with ROCm support: "
                       "pip install torch --index-url https://download.pytorch.org/whl/rocm6.0 "
                       "(see https://pytorch.org/get-started/locally/ for other GPU vendors)"
                   )
           except ImportError:
               raise ASRDependencyError(
                   "PyTorch is required for GPU inference but not installed. "
                   "Install with: pip install torch"
               ) from None
       
       factory = self._model_factory or _load_default_model
       # FunASR AutoModel only accepts: model, device, trust_remote_code, model_revision, hub
       kwargs: dict[str, Any] = {
           "model": self.config.model_name,
           "device": self.config.device,
           "trust_remote_code": False,
       }
       if self.config.model_revision is not None:
           kwargs["model_revision"] = self.config.model_revision
       # Note: offline/local_source removed - not supported by FunASR API
       
       try:
           self._model = factory(**kwargs)
       except ASRDependencyError:
           raise
       except Exception:
           raise ASRModelError(
               "FunASR model load/transcription failed; check configured local model."
           ) from None
       return self._model
   ```

4. **Error messages**: Update exception messages that mention "SenseVoice" to be model-agnostic or mention "FunASR-Nano"

### API Compatibility

No breaking changes:
- `ASRRunner` constructor signature unchanged
- `transcribe()` function still accepts `model_name` override
- Existing code using explicit `device="cpu"` continues to work
- Environment variable `BILI_ASR_MODEL` still overrides default

## Tasks

1. **Update model constant and device default** — 15min
   - Change `DEFAULT_MODEL`
   - Change `ASRConfig.device` default
   
2. **Add ROCm detection and clean up API** — 60min
   - Implement CUDA availability check (works for both NVIDIA and AMD ROCm)
   - Remove unsupported `offline` and `local_source` kwargs from AutoModel call
   - Write clear error messages with ROCm installation command
   - Handle torch import failure gracefully

3. **Update error messages** — 15min
   - Replace "SenseVoice" with generic "ASR model" or "FunASR"
   - Verify error message consistency

4. **Self-verification** — 45min
   - Run existing tests with mocked model
   - Verify error paths trigger correctly
   - Check that CPU override still works

## Acceptance Criteria

### Code Changes (verify by inspection)
- [ ] `DEFAULT_MODEL` constant equals `"FunAudioLLM/Fun-ASR-Nano-2512"` (line 15 of asr.py)
- [ ] `ASRConfig.device` default equals `"cuda"` (line 54 of asr.py)
- [ ] `_get_model()` calls `torch.cuda.is_available()` before model load when device starts with "cuda"
- [ ] Error message contains PyTorch ROCm installation command and reference to PyTorch installation guide for other GPU vendors
- [ ] `AutoModel()` kwargs only include `model`, `device`, `trust_remote_code`, and optionally `model_revision` (no `offline` or `local_source`)
- [ ] ASRConfig fields `offline` and `local_source` retained for backward compatibility but not passed to AutoModel

### Runtime Behavior (verify by execution)
- [ ] Running `python -c "from bili_asr.asr import DEFAULT_MODEL; print(DEFAULT_MODEL)"` prints `FunAudioLLM/Fun-ASR-Nano-2512`
- [ ] With CUDA available: model loads to GPU without error
- [ ] With CUDA unavailable: raises `ASRDependencyError` with AMD ROCm installation command and PyTorch guide reference
- [ ] Override with `ASRConfig(device="cpu")` works (no error, uses CPU)

### API Compatibility (verify by test)
- [ ] Existing unit tests pass with mocked model (`pytest tests/test_asr*.py -v`)
- [ ] `ASRRunner(config=ASRConfig(device="cpu"))` constructor works (backward compatibility)
- [ ] Environment variable `BILI_ASR_MODEL=custom/model` still overrides default

## Dependencies

None. This plan is standalone and can execute immediately.

**Why no dependencies:**
- Changes are isolated to `src/bili_asr/asr.py` (single module)
- No external API changes required
- Tests mock the model, so real GPU not needed for verification
- Documentation updates happen in parallel plan (20260909-documentation-sync)

## Blocked By

None.
