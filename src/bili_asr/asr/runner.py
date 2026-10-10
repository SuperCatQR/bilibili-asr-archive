"""Runner implementation."""

from __future__ import annotations

import hashlib
import multiprocessing as _multiprocessing
import os
import queue as _queue
import time
from collections.abc import Callable
from contextlib import contextmanager, nullcontext
from dataclasses import replace
from typing import Any, NamedTuple

import bili_asr.asr.alignment as _dependency_alignment
import bili_asr.asr.audio as _dependency_audio
import bili_asr.asr.config as _dependency_config
import bili_asr.asr.constants as _dependency_constants
import bili_asr.asr.coverage as _dependency_coverage
import bili_asr.asr.diagnostics as _dependency_diagnostics
import bili_asr.asr.errors as _dependency_errors
import bili_asr.asr.hotwords as _dependency_hotwords
from bili_asr.asr.provenance import _redact
from bili_asr.asr.preparation import DecodeInputs, InputPrefetch, ProcessorReuse
from bili_asr.asr.execution import clock_anchor, execution_policy, hardware_evidence
from bili_asr.asr.backend import HuggingFaceBackend, InferenceBackend

_PROGRESS_HOOK: Callable[[str], None] | None = None


class ASRInferenceTimeoutError(TimeoutError):
    """A child process exceeded the hard inference deadline."""

    error_code = "inference_timeout"


def _isolated_transcribe_worker(config: Any, audio_path: str, paired_subtitle_text: str | None, result_queue: Any) -> None:
    """Run model loading, decoding, and forced alignment outside the worker process."""

    try:
        runner = ASRRunner(config)
        segments = two_pass_transcribe(
            runner, audio_path, paired_subtitle_text=paired_subtitle_text
        )
        result_queue.put(
            {
                "ok": True,
                "segments": segments,
                "provenance": runner.provenance(),
                "coverage": runner.transcribed_coverage(),
                "diagnostics": runner.diagnostics(),
            }
        )
    # The process boundary reports even SystemExit/KeyboardInterrupt so the
    # supervisor does not wait for the full inference deadline after exit.
    except BaseException as exc:  # noqa: BLE001
        result_queue.put(
            {"ok": False, "error_type": type(exc).__name__, "error": str(exc)[:512]}
        )


def transcribe_with_timeout(
    config: Any,
    audio_path: str,
    *,
    paired_subtitle_text: str | None,
    timeout_seconds: float,
    diagnostics_sink: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, str], dict[str, Any] | None]:
    """Run one ASR attempt in a killable child process.

    A Python thread cannot interrupt a blocked ROCm kernel.  The workflow
    worker therefore uses this boundary for CUDA/ROCm profiles: the parent
    waits for a bounded result, terminates the child on timeout, and lets the
    normal workflow failure path persist a retryable ``inference_timeout``.
    """

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    context = _multiprocessing.get_context("spawn")
    result_queue = context.Queue(maxsize=1)
    process = context.Process(
        target=_isolated_transcribe_worker,
        args=(config, audio_path, paired_subtitle_text, result_queue),
        name="bili-asr-inference",
    )
    process.start()
    deadline = time.monotonic() + timeout_seconds
    result: dict[str, Any] | None = None
    timed_out = False
    try:
        # Drain while the child is alive.  Joining first can deadlock when a
        # large segment list is still flushing through multiprocessing.Queue.
        exit_deadline: float | None = None
        while result is None:
            try:
                result = result_queue.get(timeout=0.05)
                break
            except _queue.Empty:
                alive = process.is_alive()
                now = time.monotonic()
                if alive and now >= deadline:
                    timed_out = True
                    break
                if not alive:
                    exit_deadline = exit_deadline or now + 1.0
                    if now >= exit_deadline:
                        break
        if timed_out:
            process.terminate()
            process.join(timeout=5)
            if process.is_alive():
                process.kill()
                process.join()
            raise ASRInferenceTimeoutError(
                f"ASR inference exceeded {timeout_seconds:g}s and the child process was terminated"
            )
        process.join(timeout=1)
        if result is None:
            raise RuntimeError(
                f"isolated ASR worker exited without a result (exit code {process.exitcode})"
            )
    finally:
        result_queue.close()
        result_queue.join_thread()
    if not result.get("ok"):
        error_type = str(result.get("error_type") or "ASRModelError")
        message = str(result.get("error") or "isolated ASR worker failed")
        raise RuntimeError(f"{error_type}: {message}")
    if diagnostics_sink is not None:
        diagnostics_sink.clear()
        diagnostics_sink.update(result.get("diagnostics") or {})
    return (
        list(result["segments"]),
        dict(result["provenance"]),
        result.get("coverage"),
    )


def set_progress_hook(hook: Callable[[str], None] | None) -> None:
    """Install the optional process-supervisor heartbeat callback."""

    global _PROGRESS_HOOK
    _PROGRESS_HOOK = hook


def _progress(phase: str) -> None:
    hook = _PROGRESS_HOOK
    if hook is None:
        return
    try:
        hook(phase)
    except OSError:
        # The parent may have stopped supervising after a worker failure.  The
        # inference path must still fail normally instead of masking its error.
        set_progress_hook(None)


class _ModelSet(NamedTuple):
    """The two processors and two models one runner owns."""

    processor: Any
    model: Any
    aligner_processor: Any
    aligner: Any


def _load_qwen_models(**kwargs: Any) -> _ModelSet:
    """Build the ASR + aligner pair, lazily and once per runner.

    This is the one place transformers is imported.  The two checkpoints are loaded together so that
    a runner either has a working pair or none — a half-loaded pair would report a construction the
    run cannot use.
    """

    try:
        import torch
        from transformers import (
            AutoModelForMultimodalLM,
            AutoModelForTokenClassification,
            AutoProcessor,
        )
    except ImportError as exc:
        raise _dependency_errors.ASRDependencyError(
            f"Qwen3-ASR support is not installed; run: {_dependency_constants._INSTALL_HINT}"
        ) from exc

    model_name = kwargs["model_name"]
    aligner_name = kwargs["aligner_name"]
    device = kwargs.get("device") or "cuda"
    revision = kwargs.get("model_revision")
    aligner_revision = kwargs.get("aligner_revision")
    local_files_only = kwargs.get("offline", True)

    processor = AutoProcessor.from_pretrained(model_name, revision=revision, local_files_only=local_files_only)
    model = AutoModelForMultimodalLM.from_pretrained(
        model_name, revision=revision, dtype=getattr(torch, kwargs.get("model_dtype", "bfloat16")),
        device_map=device, local_files_only=local_files_only
    )
    aligner_processor = AutoProcessor.from_pretrained(aligner_name, revision=aligner_revision, local_files_only=local_files_only)
    aligner = AutoModelForTokenClassification.from_pretrained(
        aligner_name, revision=aligner_revision, dtype=getattr(torch, kwargs.get("aligner_dtype", "bfloat16")),
        device_map=device, local_files_only=local_files_only
    )
    model.eval()
    aligner.eval()
    return _ModelSet(processor, model, aligner_processor, aligner)


class ASRRunner:
    """Lazy owner of the model pair for sequential use within one run scope.

    ``model_constructions`` counts the **model sets** this runner built — one per lazy construction,
    zero when the run never needed audio.  That keeps the observable run-scoped reuse contract
    unchanged after the two-model switch: a batch that reuses one runner reports **one** construction
    for N items, because the aligner rides in the same set.

    ``model_load_attempts`` is the attempt counter beside it: a load the factory rejected is retried
    once per row — bounded by :data:`MAX_MODEL_LOAD_ATTEMPTS` — pays no construction, and is counted
    here instead.  The invariant is ``model_load_attempts >= model_constructions``, with equality when
    every load succeeded.
    """

    def __init__(
        self,
        config: _dependency_config.ASRConfig | str | None = None,
        *,
        model_factory: Callable[..., Any] | None = None,
        model_name: str | None = None,
        backend: InferenceBackend | None = None,
    ) -> None:
        if config is None:
            config = _dependency_config.ASRConfig(model_name=model_name or _dependency_constants.DEFAULT_MODEL)
        elif isinstance(config, str):
            if model_name is not None:
                raise TypeError("model_name cannot accompany a model name")
            config = _dependency_config.ASRConfig(model_name=config)
        elif model_name is not None:
            raise TypeError("model_name is only accepted without a config")
        if not isinstance(config, _dependency_config.ASRConfig):
            raise TypeError("config must be an ASRConfig")
        self.config = config
        self.backend = backend if backend is not None else HuggingFaceBackend()
        if any(dtype not in self.backend.capabilities.precisions for dtype in (config.model_dtype, config.aligner_dtype)):
            raise ValueError("selected inference backend does not support the requested precision")
        self._model_factory = model_factory
        self._models: _ModelSet | None = None
        # Monotonic, never reset by release(): a runner that released and rebuilt paid two
        # constructions, and the count must say so.
        self.model_constructions = 0
        # Attempts, not successes: a failed load is retried once per row, so
        # ``attempts - constructions`` is exactly the number of load failures this runner paid for.
        self.model_load_attempts = 0
        # Run-scoped hotword state (governance ruling 2026-09-28).  ``None`` means
        # "no evidence supplied yet": no guard has run, so the configured list is
        # used verbatim — the state of every caller that predates the guard.  Once
        # evidence arrives, ``_hotwords_effective`` is exactly what the guard admitted
        # and ``_hotwords_dropped`` is ledger-visible.
        self._hotwords_effective: tuple[str, ...] | None = None
        self._hotwords_dropped: tuple[str, ...] = ()
        self._hotwords_evidence_text: str | None = None
        self._hotwords_subtitle_text: str | None = None
        # The character-level record of the last successful ``transcribe`` (see ``characters()``).
        self._last_characters: dict[str, Any] | None = None
        # The cue list of the last successful ``transcribe`` (see
        # ``transcribed_segments()``).  The store write-back converts these
        # into transcript segments; it is cleared on failure like the character
        # record, so a caller never stores a stale transcript.
        self._last_transcribed_segments: list[dict[str, Any]] | None = None
        # The coverage measurement of the same run (see ``transcribed_coverage()``).  ``None``
        # means "no measurement to offer": the run never transcribed, or it decoded nothing.
        self._last_coverage: dict[str, Any] | None = None
        self._last_language: str | None = None
        self._diagnostic_passes: list[dict[str, Any]] = []
        self._last_generation: dict[str, Any] = {}
        self._audio_reuse_scope = False
        self._prepared_audio = None
        self._prefetch_enabled = False
        self._prefetch_bytes = 64 * 1024 * 1024
        self._prefetch_processor_reuse = None
        self._trace: list[dict[str, Any]] | None = None
        self._trace_origin = 0.0
        self._trace_chunk_index = None

    def configure_prefetch(self, *, enabled: bool, max_bytes: int = 64 * 1024 * 1024) -> None:
        """Experimental depth-one CPU input preparation; no concurrent GPU calls."""
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
            raise ValueError("max_bytes must be a positive integer")
        self._prefetch_enabled, self._prefetch_bytes = bool(enabled), max_bytes

    @contextmanager
    def audio_reuse(self):
        """Keep audio and an isolated CPU processor only for this two-pass task."""
        if self._audio_reuse_scope:
            raise RuntimeError("two-pass reuse scope is already active")
        self._audio_reuse_scope = True
        self._prepared_audio = None
        processor_reuse = ProcessorReuse()
        self._prefetch_processor_reuse = processor_reuse
        try:
            yield
        finally:
            processor_reuse.close()
            self._prefetch_processor_reuse = None
            self._prepared_audio = None
            self._audio_reuse_scope = False

    def _audio_identity(self, path: str) -> tuple | None:
        digest = hashlib.sha256()
        try:
            with open(path, "rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
        except OSError:
            # An injected decoder may support a virtual path. No identity means no
            # reuse; the real reader remains responsible for its ordinary error.
            return None
        return (digest.hexdigest(), _dependency_constants.SAMPLE_RATE, self.config.chunk_seconds)

    def _trace_stage(self, phase: str, started: float, *, chunk_index: int | None = None) -> None:
        if self._trace is not None:
            self._trace.append({"phase": phase, "start_s": started - self._trace_origin,
                "end_s": time.perf_counter() - self._trace_origin,
                "chunk_index": self._trace_chunk_index if chunk_index is None else chunk_index,
                "clock": "process_perf_counter", "measurement": "wall"})

    def _prepare_decode_inputs(self, processor: Any, audio: Any, *, record_trace: bool = True):
        hotwords = self._prompt_hotwords()
        prompt = "Vocabulary: " + ", ".join(hotwords) if hotwords else None
        started = time.perf_counter()
        result = processor.apply_transcription_request(audio=audio, language=self.config.language, prompt=prompt)
        prepared = self._decode_input_budget(result)
        if record_trace:
            self._trace_stage("cpu_input_prepare", started)
        return prepared

    def _decode_input_budget(self, inputs: Any) -> DecodeInputs:
        # Preserve the original mask formula, including padding and the minimum.
        # Native processors return CPU tensors here: evaluating the scalar before
        # .to() avoids a device-to-host synchronization solely for token budgeting.
        seconds = float(inputs["input_features_mask"].sum(-1).max()) / _dependency_constants._MEL_FRAMES_PER_SECOND
        budget = max(self.config.min_new_tokens, int(seconds * self.config.tokens_per_second))
        return DecodeInputs(inputs, budget, seconds)

    def _get_models(self) -> _ModelSet:
        if self._models is not None:
            return self._models

        if self.config.device.startswith("cuda"):
            try:
                import torch
            except ImportError:
                raise _dependency_errors.ASRDependencyError(
                    "PyTorch is required for GPU inference but not installed. "
                    "Install with: pip install torch"
                ) from None
            if not torch.cuda.is_available():
                raise _dependency_errors.ASRDependencyError(
                    "CUDA/ROCm is not available: no device is visible to PyTorch. "
                    "Run the environment check from the product directory with the venv's "
                    'interpreter (`"$VENV/bin/python" scripts/check_asr_env.py`); it names the '
                    "stage that fails and prints the fix, and `docs/wsl-rocm-gpu.md` carries the "
                    "verified AMD/WSL ROCm recipe. To transcribe without a device, set "
                    "`BILI_ASR_DEVICE=cpu`."
                )

        factory = self._model_factory or _load_qwen_models
        kwargs: dict[str, Any] = {
            "model_name": self.config.model_name,
            "aligner_name": self.config.aligner_name,
            "device": self.config.device,
            "aligner_revision": self.config.aligner_revision,
            "offline": self.config.offline,
        }
        if self.config.model_dtype != "bfloat16" or self.config.aligner_dtype != "bfloat16":
            kwargs.update(model_dtype=self.config.model_dtype, aligner_dtype=self.config.aligner_dtype)
        if self.config.model_revision is not None:
            kwargs["model_revision"] = self.config.model_revision

        try:
            # Counted *before* the call, so every factory invocation is an attempt whether it
            # returned a pair or raised.  ``_models`` stays None on failure and the next row retries
            # the same call, which is why the attempt counter and the construction counter must not
            # be the same number.
            if self.model_load_attempts >= _dependency_constants.MAX_MODEL_LOAD_ATTEMPTS:
                raise _dependency_errors.ASRModelError(
                    "Qwen3-ASR model load failed; check the configured local checkpoints. "
                    f"Gave up after {_dependency_constants.MAX_MODEL_LOAD_ATTEMPTS} failed load attempt(s)."
                )
            self.model_load_attempts += 1
            _progress("load")
            self._models = factory(**kwargs)
        except (_dependency_errors.ASRDependencyError, _dependency_errors.ASRModelError):
            raise
        # Third-party loaders expose many exception classes.  Keep their
        # paths/tokens out of archive errors while retaining one bounded code.
        except Exception:  # noqa: BLE001
            raise _dependency_errors.ASRModelError(
                "Qwen3-ASR model load failed; check the configured local checkpoints."
            ) from None
        # Counted only here, after the factory returned a pair: a failed load paid no construction.
        self.model_constructions += 1
        return self._models

    # -- the pipeline ------------------------------------------------------------------

    def _transcribe_chunk(
        self, models: _ModelSet, audio: Any, *, bust_cache: bool = False, prepared_inputs: Any = None
    ) -> tuple[str, str]:
        """One chunk through the decoder: ``(text, detected_language)``.

        ``bust_cache`` selects the second-pass cache policy. Historically that pass
        disables within-generation KV reuse; no past_key_values are passed between
        calls. The frozen second_pass_use_cache option allows a measured comparison
        while preserving the existing default until a real-model benchmark justifies it.

        The decode format matters: ``decode(..., return_format=...)`` hard-sets
        ``skip_special_tokens``, and the decoded text is scrubbed of control markers as well — a
        caller that re-parses a *raw* decode instead would carry ``<|im_end|>`` into the archive.
        """

        import torch

        # Decoded chunks already contain mono 16 kHz audio.
        prepared = prepared_inputs if prepared_inputs is not None else self._prepare_decode_inputs(models.processor, audio)
        # Custom/injected processors can still supply the historical mapping.
        if not isinstance(prepared, DecodeInputs):
            prepared = self._decode_input_budget(prepared)
        inputs, budget = prepared.inputs, prepared.max_new_tokens
        transfer_clock = time.perf_counter()
        inputs = inputs.to(models.model.device, models.model.dtype)
        self._trace_stage("device_transfer", transfer_clock)
        with torch.inference_mode():
            _progress("decode")
            generate_clock = time.perf_counter()
            generated = self.backend.generate(models.model, inputs, max_new_tokens=budget,
                disable_cache=bust_cache and not self.config.second_pass_use_cache)
            self._trace_stage("model_generate", generate_clock)
        post_clock = time.perf_counter()
        tokens = generated[:, inputs["input_ids"].shape[1]:]
        self._last_generation = _dependency_diagnostics.generation_evidence(tokens, models.model, budget)
        self._last_generation["budget_metadata"] = {
            "source": "processor_mask_before_transfer", "feature_seconds": prepared.feature_seconds,
        }
        text = _dependency_alignment._clean_text(models.processor.decode(tokens, return_format="transcription_only")[0])
        parsed = models.processor.decode(tokens, return_format="parsed")[0]
        self._trace_stage("decode_postprocess", post_clock)
        return text, str(parsed.get("language") or "")

    def _align_chunk(self, models: _ModelSet, audio: Any, text: str, language: str) -> list[dict[str, Any]]:
        """One chunk through the aligner: per-unit ``{text, start_time, end_time}`` in seconds."""

        import torch

        started = time.perf_counter()
        inputs, word_lists = models.aligner_processor.prepare_forced_aligner_inputs(
            audio=audio, transcript=text, language=language or "Chinese"
        )
        self._trace_stage("align_prepare", started)
        started = time.perf_counter()
        inputs = inputs.to(models.aligner.device, models.aligner.dtype)
        self._trace_stage("align_transfer", started)
        with torch.inference_mode():
            _progress("align")
            started = time.perf_counter()
            logits = self.backend.align(models.aligner, inputs)
            self._trace_stage("align_forward", started)
        started = time.perf_counter()
        units = list(models.aligner_processor.decode_forced_alignment(
            logits=logits,
            input_ids=inputs["input_ids"],
            word_lists=word_lists,
            timestamp_token_id=models.aligner.config.timestamp_token_id,
        )[0])
        self._trace_stage("align_postprocess", started)
        return units

    def characters(self) -> dict[str, Any] | None:
        """The character-level record for the **last** :meth:`transcribe`, or ``None``.

        A by-product of the same run rather than a second pass: :meth:`transcribe` already holds
        the threaded pieces (the last step that knows each character's instant) and the cues it
        built from them, so the record costs one walk over the transcript and no model call.
        ``None`` means no transcription has run — the record is not invented for audio the
        runner never read.
        """

        return self._last_characters

    def transcribed_segments(self) -> list[dict[str, Any]] | None:
        """The cue list for the **last** :meth:`transcribe`, or ``None``.

        The store write-back converts these into transcript segments; the list
        is the same object :meth:`transcribe` returned, so the caller archives
        and stores one transcript.  ``None`` means no transcription has run.
        """

        return self._last_transcribed_segments

    def transcribed_coverage(self) -> dict[str, Any] | None:
        """The coverage evidence for the **last** :meth:`transcribe`, or ``None``.

        ``None`` means the run has no measurement to offer — it never transcribed, or it decoded
        nothing (``decoded_s == 0``), in which case no coverage claim is made at all.  The shape is
        the record :func:`_coverage_record` builds; :func:`apply_coverage_evidence` is the one
        place that carries it onto a manifest row.

        Not to be confused with the record of an *earlier* run: the pair is cleared together with
        the other ``_last_*`` state, so a failed call leaves no stale measurement behind.
        """

        return self._last_coverage

    def transcribe(self, audio_path: str, *, bust_cache: bool = False) -> list[dict[str, Any]]:
        """Transcribe one audio file into timestamped cues.

        Every cue the caller receives traces to an aligner call over the audio that produced its
        text: chunk boundaries are ours, the timings are the aligner's, and nothing is interpolated.
        An empty recording yields no cues rather than a fabricated one.

        ``bust_cache`` selects the configured second-pass cache policy.
        Each pass starts a separate generation call with its own prompt.

        The character-level record of the same run is left for :meth:`characters`; callers that
        publish it read it right after this returns.  The coverage measurement of the same run is
        left for :meth:`transcribed_coverage`, on the same rule — a by-product of the run, not a
        second pass, and not part of the returned cue list.
        """

        # The record describes one run: a call that fails leaves no stale one behind for a caller
        # that reads ``characters()`` after a later, unrelated failure.  The coverage measurement
        # is part of that record, so it is cleared with it.
        self._last_characters = None
        self._last_transcribed_segments = None
        self._last_coverage = None
        self._last_language = None
        self._diagnostic_passes = []
        report: dict[str, Any] = {"chunks": [], "timings_s": {}, "completed": False}
        self._diagnostic_passes.append(report)
        run_clock = time.perf_counter()
        self._trace_origin = run_clock
        report["clock"] = clock_anchor(monotonic=run_clock)
        report["pass_kind"] = "hotword_second" if bust_cache else "first"
        self._trace_chunk_index = None
        self._trace = report["trace"] = []
        load_clock = time.perf_counter()
        report["model_reused"] = self._models is not None
        # The model pair first: a host without the extra must fail with the documented
        # ``ASRDependencyError`` (which names the ``[asr]`` install), not with whatever the audio
        # reader happens to import first.  The readers are part of the same extra, so their absence
        # is reported the same way.
        models = self._get_models()
        report["timings_s"]["model_load"] = time.perf_counter() - load_clock
        self._trace_stage("model_load", load_clock)
        report["environment"] = _dependency_diagnostics.runtime_environment()
        report["execution_policy"] = execution_policy(self.config, models,
            prefetch=self._prefetch_enabled, prefetch_bytes=self._prefetch_bytes)
        report["execution_policy"]["backend"] = {
            "requested": self.backend.capabilities.name, "resolved": self.backend.capabilities.name,
            "capabilities": self.backend.capabilities.evidence(),
        }
        report["hardware"] = hardware_evidence(models.model.device)
        report["execution_policy"]["runtime"] = {
            "environment": report["environment"], "hardware": report["hardware"], "source_commit": None,
        }
        report["resource_observation"] = {
            "cpu_rss_peak_bytes": None, "gpu_allocator_peak_bytes": None,
            "gpu_sampled_peak_bytes": None, "sampling": "disabled",
        }
        report["model_dtype"] = str(models.model.dtype)
        report["aligner_dtype"] = str(models.aligner.dtype)
        for key, model in (("resolved_model_revision", models.model), ("resolved_aligner_revision", models.aligner)):
            revision = getattr(getattr(model, "config", None), "_commit_hash", None)
            report[key] = _redact(str(revision)) if revision else None
        try:
            import numpy as np
            import soxr
        except ImportError as exc:
            raise _dependency_errors.ASRDependencyError(
                f"the ASR audio readers are not installed; run: {_dependency_constants._INSTALL_HINT}"
            ) from exc

        audio_clock = time.perf_counter()
        path, temporary = _dependency_audio._materialize_input(audio_path)
        prefetch = None
        try:
            audio_key = self._audio_identity(path) if self._audio_reuse_scope else None
            cached = self._prepared_audio if self._audio_reuse_scope else None
            if cached is not None and cached[0] != audio_key:
                raise _dependency_errors.AudioDecodeError("audio input changed between transcription passes")
            report["waveform_reused"] = bool(audio_key is not None and cached is not None and cached[0] == audio_key)
            if report["waveform_reused"]:
                samples = cached[1]
            else:
                samples, rate = _dependency_audio._read_audio(path)
                samples = np.asarray(samples, dtype=np.float32)
                if samples.ndim > 1:
                    samples = samples.mean(-1).astype(np.float32)
                if int(rate) != _dependency_constants.SAMPLE_RATE:
                # ``soxr`` is what ``librosa.resample`` calls underneath at its default
                # ``res_type="soxr_hq"``; measured bit-identical on this corpus, and it drops a
                # dependency whose version range could change the resampler silently.
                    samples = soxr.resample(samples, int(rate), _dependency_constants.SAMPLE_RATE)
                    samples = np.asarray(samples, dtype=np.float32)
                if self._audio_reuse_scope and audio_key is not None:
                    if self._audio_identity(path) != audio_key:
                        raise _dependency_errors.AudioDecodeError("audio input changed during preparation")
                    self._prepared_audio = (audio_key, samples)

            report["timings_s"]["audio_prepare"] = time.perf_counter() - audio_clock
            self._trace_stage("audio_prepare", audio_clock)
            split_clock = time.perf_counter()
            chunks = _dependency_audio._split_audio(samples, _dependency_constants.SAMPLE_RATE, self.config.chunk_seconds)
            report["timings_s"]["split"] = time.perf_counter() - split_clock
            self._trace_stage("split", split_clock)
            if not chunks:
                self._last_characters = None
                self._last_transcribed_segments = None
                self._last_coverage = None
                report["decoded_s"] = 0.0
                report["completed"] = True
                return []

            # The run's own decoded duration: the measured quantity the coverage comparison is
            # against, and — because ``_split_audio`` tiles the input exactly — exactly the number
            # of samples this run fed the model.  Taken before the loop so a chunk that decodes to
            # nothing (``if not text: continue`` below) still counts in the denominator: that
            # branch is where the measured defect's span went missing.
            decoded_seconds = sum(len(chunk) / _dependency_constants.SAMPLE_RATE for chunk, _offset in chunks)
            report["decoded_s"] = decoded_seconds

            minimum = int(_dependency_constants._CHUNK_MIN_SECONDS * _dependency_constants.SAMPLE_RATE)
            pieces: list[dict[str, Any]] = []
            languages: set[str] = set()
            prefetch = InputPrefetch(models.processor if self._prefetch_enabled else None,
                lambda processor, audio: self._prepare_decode_inputs(processor, audio, record_trace=False),
                enabled=self._prefetch_enabled, budget_bytes=self._prefetch_bytes,
                processor_reuse=self._prefetch_processor_reuse)
            report["prefetch"] = prefetch.report
            report["resources"] = {"decoded_waveform_bytes": int(samples.nbytes),
                                   "prefetch_input_peak_bytes": 0, "prefetch_memory_bound": "reservation_and_observed_input"}

            def padded_audio(chunk):
                value = np.asarray(chunk, dtype=np.float32)
                return np.pad(value, (0, minimum - value.shape[0])) if value.shape[0] < minimum else value

            for chunk_index, (chunk, offset) in enumerate(chunks):
                self._trace_chunk_index = chunk_index
                chunk_report: dict[str, Any] = {
                    "chunk_index": chunk_index, "start_s": offset,
                    "end_s": offset + len(chunk) / _dependency_constants.SAMPLE_RATE,
                    "flags": [],
                }
                report["chunks"].append(chunk_report)
                audio = padded_audio(chunk)
                if prefetch.pending is not None:
                    wait_clock = time.perf_counter()
                    prepared_inputs, prepared = prefetch.consume()
                    self._trace_stage("cpu_input_wait", wait_clock, chunk_index=chunk_index)
                    if prepared is not None:
                        self._trace.append({"phase": "cpu_input_prepare",
                            "start_s": prepared.started - self._trace_origin,
                            "end_s": prepared.finished - self._trace_origin, "chunk_index": chunk_index,
                            "clock": "process_perf_counter", "measurement": "wall"})
                else:
                    prepared_inputs = None
                if chunk_index + 1 < len(chunks):
                    prefetch.submit(chunk_index + 1, chunks[chunk_index + 1][0], minimum_samples=minimum)
                self._last_generation = {}
                decode_clock = time.perf_counter()
                # Processors accept decoded arrays. Paths would invoke their
                # optional decoder backend and repeat our own audio preparation.
                decode_kwargs = {} if prepared_inputs is None else {"prepared_inputs": prepared_inputs}
                text, language = self._transcribe_chunk(models, audio, bust_cache=bust_cache, **decode_kwargs)
                prepared_inputs = None
                decode_kwargs.clear()
                chunk_report["decode_s"] = time.perf_counter() - decode_clock
                self._trace_stage("decode", decode_clock, chunk_index=chunk_index)
                chunk_report["text"] = text
                chunk_report["language"] = language
                chunk_report["generation"] = dict(self._last_generation)
                if self._last_generation.get("token_limit_reached") and self._last_generation.get("ended_with_eos") is not True:
                    chunk_report["flags"].append("token-limit-reached")
                if not text:
                    # Preserve an explicit empty-output observation. It may be
                    # silence or missing speech; no VAD evidence is fabricated.
                    chunk_report["flags"].append("empty-output")
                    continue
                if language.strip():
                    languages.add(language.strip())
                align_clock = time.perf_counter()
                raw_units = self._align_chunk(models, audio, text, language)
                chunk_report["align_s"] = time.perf_counter() - align_clock
                self._trace_stage("align", align_clock, chunk_index=chunk_index)
                chunk_report["alignment"] = _dependency_diagnostics.alignment_evidence(
                    raw_units, len(audio) / _dependency_constants.SAMPLE_RATE
                )
                if not raw_units:
                    chunk_report["flags"].append("empty-alignment")
                if chunk_report["alignment"]["invalid_alignment_units"]:
                    chunk_report["flags"].append("invalid-alignment")
                units = [
                    {
                        "text": unit["text"],
                        "start_time": float(unit["start_time"]) + offset,
                        "end_time": float(unit["end_time"]) + offset,
                    }
                    for unit in raw_units
                ]
                pieces.extend(_dependency_alignment._thread_text(text, units))
            cues = _dependency_alignment._aligned_cues(pieces)
            # The pieces are the character-level truth and the cues are the published text; the
            # record is the former projected onto the latter, so the two cannot disagree.
            self._last_characters = _dependency_alignment._characters_from_pieces(pieces, cues)
            self._last_transcribed_segments = list(cues)
            # The run's coverage evidence, measured from what this run decoded and what it
            # produced.  It rides the manifest row (D11 carrier); the return shape of this method
            # is deliberately unchanged.
            self._last_coverage = _dependency_coverage._coverage_record(decoded_seconds, cues)
            report["span_coverage_short"] = bool(self._last_coverage and self._last_coverage["coverage_short"])
            report["timings_s"]["decode"] = sum(c.get("decode_s", 0.0) for c in report["chunks"])
            report["timings_s"]["align"] = sum(c.get("align_s", 0.0) for c in report["chunks"])
            report["completed"] = True
            # Preserve the engine's detected language for automatic-language
            # runs. Multiple languages are explicit; no evidence stays unset.
            if len(languages) == 1:
                self._last_language = next(iter(languages))
            elif languages:
                self._last_language = "mul"
            return cues
        finally:
            if prefetch is not None:
                prefetch.close()
                report["resources"]["prefetch_input_peak_bytes"] = prefetch.peak_bytes
            report["timings_s"]["total"] = time.perf_counter() - run_clock
            self._trace = None
            self._trace_chunk_index = None
            for leftover in (temporary,):
                if leftover:
                    try:
                        os.unlink(leftover)
                    except OSError:
                        pass

    def diagnostics(self) -> dict[str, Any]:
        """A detached record; final-pass quality remains explicitly unreviewed."""
        return _dependency_diagnostics.assemble_diagnostics(self._diagnostic_passes)

    def release(self) -> None:
        """Drop the owned model pair.  The counters are monotonic and are **not** reset."""

        self._models = None
        self._prepared_audio = None
        if self._prefetch_processor_reuse is not None:
            self._prefetch_processor_reuse.close()

    def prepare(self, audio_path: str | None = None) -> dict[str, Any]:
        """Load both models and optionally run an explicit, non-business sentinel."""
        started = time.perf_counter()
        models = self._get_models()
        result = {"state": "loaded", "model_dtype": str(models.model.dtype),
                  "aligner_dtype": str(models.aligner.dtype)}
        if audio_path is not None:
            try:
                cues = self.transcribe(audio_path)
                if not cues or not self.characters():
                    raise _dependency_errors.ASRModelError("warmup sample produced no aligned transcript")
                result["state"] = "ready"
            finally:
                # Warmup output and hotword evidence must never enter a business request.
                self._diagnostic_passes.clear()
                self._last_characters = self._last_transcribed_segments = self._last_coverage = None
                self._last_language = None
                self._last_generation = {}
                self._hotwords_effective = None
                self._hotwords_dropped = ()
                self._hotwords_evidence_text = self._hotwords_subtitle_text = None
        result["wall_s"] = time.perf_counter() - started
        return result

    def _prompt_hotwords(self) -> tuple[str, ...]:
        """The vocabulary that may reach the prompt for the next chunk.

        ``self.config.hotwords`` is the operator's configured list; the effective
        list is what the evidence guard admitted once evidence was supplied.  A
        runner that never received evidence keeps its configured list verbatim.
        """

        return (
            self.config.hotwords
            if self._hotwords_effective is None
            else self._hotwords_effective
        )

    @property
    def hotwords_dropped(self) -> tuple[str, ...]:
        """Terms the evidence guard refused for this run (ledger-visible)."""

        return self._hotwords_dropped

    def set_hotword_evidence(
        self,
        *,
        evidence_text: str | None,
        paired_subtitle_text: str | None,
    ) -> None:
        """Run the evidence guard over the configured list and remember the verdict.

        ``evidence_text`` is the run's own first-pass transcript; ``paired_subtitle_text``
        is the AI-subtitle text for the same part (``None`` when the part has no
        subtitle route).  Both are evidence — a token occurring in either survives.
        Idempotent for the same evidence: the guard is pure string logic, so the
        same input yields the same verdict and re-setting is a no-op.
        """

        admitted, dropped = _dependency_hotwords.filter_hotwords(
            self.config.hotwords,
            evidence_text=evidence_text,
            paired_subtitle_text=paired_subtitle_text,
        )
        # Idempotence: re-applying the *same* evidence is a no-op (the guard is
        # pure string logic, so the same input yields the same verdict).  A
        # genuinely different evidence — a real first-pass transcript versus a
        # later, fuller one — re-seeds and the recorded fact is replaced.
        if (
            self._hotwords_effective is not None
            and (evidence_text, paired_subtitle_text)
            == (self._hotwords_evidence_text, self._hotwords_subtitle_text)
        ):
            return
        self._hotwords_effective = admitted
        self._hotwords_dropped = dropped
        self._hotwords_evidence_text = evidence_text
        self._hotwords_subtitle_text = paired_subtitle_text

    def rebuild_hotwords_from_first_pass(self, transcript_text: str) -> list[str]:
        """Reseed the prompt vocabulary from the run's own first-pass transcript.

        The two-pass contract (plan 20260928-hotword-injection-governance, Task 1):
        a first pass over the audio with the guard's *configured* list produces a
        transcript; only tokens that transcript itself contains are admitted for the
        second pass — evidence-based seeding replacing speculative seeding.  Tokens
        without an occurrence are recorded under ``hotword_dropped_no_evidence`` in
        :meth:`provenance`.

        Returns the KEPT tokens — the reseeded vocabulary that will bias the
        second pass.  (An earlier shape returned the dropped list, which made
        every caller run pass 2 unconditionally: a pass-1 transcript never
        equals the pre-pass-1 paired-subtitle evidence, so the dropped list is
        always non-empty whenever any token was subtitle-admitted.  QC F2,
        2026-09-28.)

        Pass 2 is worth its decode cost only when the kept list is non-empty:
        an empty kept list means the guard admits nothing beyond what pass 1
        already produced, and a second decode cannot change the output.
        """

        self.set_hotword_evidence(
            evidence_text=transcript_text, paired_subtitle_text=None
        )
        return [term for term in (self._hotwords_effective or ())]

    def provenance(self) -> dict[str, str]:
        """Redacted configuration and the last successful transcription's language."""

        config = self.config
        provenance = {
            "model_name": _redact(config.model_id or config.model_name),
            "aligner_model": _redact(config.aligner_name),
            "model_revision": _redact(config.model_revision or ""),
            "aligner_revision": _redact(config.aligner_revision or ""),
            "device": _redact(config.device),
            "language": _redact(self._last_language or config.language or ""),
            "hotwords": _redact(",".join(self._prompt_hotwords())),
            "chunk_seconds": f"{config.chunk_seconds:g}",
            "tokens_per_second": f"{config.tokens_per_second:g}",
            "min_new_tokens": str(config.min_new_tokens),
            "second_pass_use_cache": str(config.second_pass_use_cache),
            "offline": str(config.offline),
            "local_source": _redact(config.local_source),
        }
        if config.model_dtype != "bfloat16" or config.aligner_dtype != "bfloat16":
            provenance.update(model_dtype=config.model_dtype, aligner_dtype=config.aligner_dtype)
        if self._hotwords_dropped:
            provenance["hotword_dropped_no_evidence"] = ",".join(
                _redact(term) for term in self._hotwords_dropped
            )
        return provenance


def two_pass_transcribe(
    runner: ASRRunner, audio_path: str, *, paired_subtitle_text: str | None
) -> list[dict[str, Any]]:
    """The two-pass hotword decode, shared by every production caller.

    ``paired_subtitle_text`` is the AI-subtitle text for the same part (``None``
    when the part has no subtitle route).  The contract (plan
    20260928-hotword-injection-governance): pass 1 decodes unguarded, the prompt
    is re-seeded with the tokens pass 1 itself produced, and pass 2 re-decodes
    with a new generation call and the configured second-pass cache policy.
    Transformers KV cache accelerates tokens within that call; this runner
    does not pass a prefix cache from pass 1 to pass 2. When the guard keeps
    no candidate terms, pass 2 is skipped and pass 1's segments are the result.
    """

    reuse = getattr(runner, "audio_reuse", None)
    with reuse() if callable(reuse) else nullcontext():
        return _two_pass_transcribe(runner, audio_path, paired_subtitle_text=paired_subtitle_text)


def _two_pass_transcribe(runner, audio_path, *, paired_subtitle_text):
    runner.set_hotword_evidence(
        evidence_text=None, paired_subtitle_text=paired_subtitle_text
    )
    first_pass = runner.transcribe(audio_path)
    transcript_text = "".join(str(seg.get("text", "")) for seg in first_pass)
    if runner.rebuild_hotwords_from_first_pass(transcript_text):  # kept tokens
        first_diagnostics = getattr(runner, "_diagnostic_passes", [])
        result = runner.transcribe(audio_path, bust_cache=True)
        if hasattr(runner, "_diagnostic_passes"):
            runner._diagnostic_passes = first_diagnostics + runner._diagnostic_passes
        return result
    return first_pass


def transcribe(
    audio_path: str,
    model_name: str | None = None,
    *,
    runner_factory: Callable[[_dependency_config.ASRConfig | None], ASRRunner] | None = None,
) -> list[dict[str, Any]]:
    """Transcribe one file with a fresh runner (one-shot; batches should hold a runner)."""

    config = replace(_dependency_config.default_config(), model_name=model_name) if model_name else None
    factory = ASRRunner if runner_factory is None else runner_factory
    return factory(config).transcribe(audio_path)


def provenance(
    *,
    runner_factory: Callable[[_dependency_config.ASRConfig | None], ASRRunner] | None = None,
) -> dict[str, str]:
    """The provenance of the default configuration."""

    factory = ASRRunner if runner_factory is None else runner_factory
    return factory(_dependency_config.default_config()).provenance()
