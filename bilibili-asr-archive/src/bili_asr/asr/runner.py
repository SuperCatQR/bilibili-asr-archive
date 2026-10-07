"""Runner implementation."""

from __future__ import annotations

import os
import sys
import types
import tempfile
from dataclasses import replace
from typing import Any, Callable, NamedTuple
import bili_asr.asr.alignment as _dependency_alignment
import bili_asr.asr.audio as _dependency_audio
import bili_asr.asr.config as _dependency_config
import bili_asr.asr.constants as _dependency_constants
import bili_asr.asr.coverage as _dependency_coverage
import bili_asr.asr.errors as _dependency_errors
import bili_asr.asr.hotwords as _dependency_hotwords
import bili_asr.asr.provenance as _dependency_provenance


_PROGRESS_HOOK: Callable[[str], None] | None = None


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


class _RunnerModule(types.ModuleType):
    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        if name == "ASRRunner":
            package = sys.modules.get("bili_asr.asr")
            if package is not None:
                types.ModuleType.__setattr__(package, name, value)


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

    processor = AutoProcessor.from_pretrained(model_name, revision=revision)
    model = AutoModelForMultimodalLM.from_pretrained(
        model_name, revision=revision, dtype=torch.bfloat16, device_map=device
    )
    aligner_processor = AutoProcessor.from_pretrained(aligner_name, revision=revision)
    aligner = AutoModelForTokenClassification.from_pretrained(
        aligner_name, revision=revision, dtype=torch.bfloat16, device_map=device
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
        }
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
        except Exception:
            raise _dependency_errors.ASRModelError(
                "Qwen3-ASR model load failed; check the configured local checkpoints."
            ) from None
        # Counted only here, after the factory returned a pair: a failed load paid no construction.
        self.model_constructions += 1
        return self._models

    # -- the pipeline ------------------------------------------------------------------

    def _transcribe_chunk(
        self, models: _ModelSet, audio_path: str, *, bust_cache: bool = False
    ) -> tuple[str, str]:
        """One chunk through the decoder: ``(text, detected_language)``.

        ``bust_cache`` is the per-pass cache control: ``True`` disables the transformers
        dynamic prefix cache for this decode (``use_cache=False``, the documented
        per-call argument on ``generate`` for the pinned ``transformers>=5.13``), so a
        re-decode with a re-seeded prompt — the two-pass hotword contract's pass 2 — starts
        from a clean model/cache state instead of being served pass 1's cached span, where
        the re-seeded vocabulary never reaches the prompt.  ``False`` keeps the default
        (cache-warm) behaviour for ordinary decodes.

        The decode format matters: ``decode(..., return_format=...)`` hard-sets
        ``skip_special_tokens``, and the decoded text is scrubbed of control markers as well — a
        caller that re-parses a *raw* decode instead would carry ``<|im_end|>`` into the archive.
        """

        import torch

        hotwords = self._prompt_hotwords()
        prompt = "Vocabulary: " + ", ".join(hotwords) if hotwords else None
        inputs = models.processor.apply_transcription_request(
            audio=audio_path, language=self.config.language, prompt=prompt
        )
        inputs = inputs.to(models.model.device, models.model.dtype)
        seconds = float(inputs["input_features_mask"].sum(-1).max()) / _dependency_constants._MEL_FRAMES_PER_SECOND
        budget = max(_dependency_constants._MIN_NEW_TOKENS, int(seconds * _dependency_constants._MAX_NEW_TOKENS_PER_AUDIO_SECOND))
        with torch.inference_mode():
            _progress("decode")
            generated = models.model.generate(**inputs, max_new_tokens=budget, **(
                {"use_cache": False} if bust_cache else {}
            ))
        tokens = generated[:, inputs["input_ids"].shape[1]:]
        text = _dependency_alignment._clean_text(models.processor.decode(tokens, return_format="transcription_only")[0])
        parsed = models.processor.decode(tokens, return_format="parsed")[0]
        return text, str(parsed.get("language") or "")

    def _align_chunk(self, models: _ModelSet, audio_path: str, text: str, language: str) -> list[dict[str, Any]]:
        """One chunk through the aligner: per-unit ``{text, start_time, end_time}`` in seconds."""

        import torch

        inputs, word_lists = models.aligner_processor.prepare_forced_aligner_inputs(
            audio=audio_path, transcript=text, language=language or "Chinese"
        )
        inputs = inputs.to(models.aligner.device, models.aligner.dtype)
        with torch.inference_mode():
            _progress("align")
            logits = models.aligner(**inputs).logits
        return list(models.aligner_processor.decode_forced_alignment(
            logits=logits,
            input_ids=inputs["input_ids"],
            word_lists=word_lists,
            timestamp_token_id=models.aligner.config.timestamp_token_id,
        )[0])

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

        ``bust_cache`` re-decodes from a clean model/cache state (the per-pass cache control,
        see :meth:`_transcribe_chunk`): it is the pass-2 knob of the two-pass hotword contract —
        the re-seeded prompt is only effective if the re-decode does not reuse pass 1's cache.

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
        # The model pair first: a host without the extra must fail with the documented
        # ``ASRDependencyError`` (which names the ``[asr]`` install), not with whatever the audio
        # reader happens to import first.  The readers are part of the same extra, so their absence
        # is reported the same way.
        models = self._get_models()
        try:
            import numpy as np
            import soundfile as sf
            import soxr
        except ImportError as exc:
            raise _dependency_errors.ASRDependencyError(
                f"the ASR audio readers are not installed; run: {_dependency_constants._INSTALL_HINT}"
            ) from exc

        path, temporary = _dependency_audio._materialize_input(audio_path)
        scratch: str | None = None
        try:
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

            chunks = _dependency_audio._split_audio(samples, _dependency_constants.SAMPLE_RATE, self.config.chunk_seconds)
            if not chunks:
                self._last_characters = None
                self._last_transcribed_segments = None
                self._last_coverage = None
                return []

            # The run's own decoded duration: the measured quantity the coverage comparison is
            # against, and — because ``_split_audio`` tiles the input exactly — exactly the number
            # of samples this run fed the model.  Taken before the loop so a chunk that decodes to
            # nothing (``if not text: continue`` below) still counts in the denominator: that
            # branch is where the measured defect's span went missing.
            decoded_seconds = sum(len(chunk) / _dependency_constants.SAMPLE_RATE for chunk, _offset in chunks)

            handle, scratch = tempfile.mkstemp(prefix="bili-asr-chunk-", suffix=".wav")
            os.close(handle)
            minimum = int(_dependency_constants._CHUNK_MIN_SECONDS * _dependency_constants.SAMPLE_RATE)
            pieces: list[dict[str, Any]] = []
            languages: set[str] = set()
            for chunk, offset in chunks:
                audio = np.asarray(chunk, dtype=np.float32)
                if audio.shape[0] < minimum:
                    # The aligner refuses a degenerate window.  The splitter deliberately does not
                    # pad — that would break its tiling promise — so the pad happens here, where the
                    # requirement comes from.
                    audio = np.pad(audio, (0, minimum - audio.shape[0]))
                sf.write(scratch, audio, _dependency_constants.SAMPLE_RATE)
                text, language = self._transcribe_chunk(models, scratch, bust_cache=bust_cache)
                if not text:
                    # The silent point the plan names: an empty-transcript chunk is dropped with
                    # no record of its own.  It is not tracked here either — the run-level
                    # comparison below is what makes the drop visible, and it does so without
                    # changing this branch's behaviour or aborting the run.
                    continue
                if language.strip():
                    languages.add(language.strip())
                units = [
                    {
                        "text": unit["text"],
                        "start_time": float(unit["start_time"]) + offset,
                        "end_time": float(unit["end_time"]) + offset,
                    }
                    for unit in self._align_chunk(models, scratch, text, language)
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
            # Preserve the engine's detected language for automatic-language
            # runs. Multiple languages are explicit; no evidence stays unset.
            if len(languages) == 1:
                self._last_language = next(iter(languages))
            elif languages:
                self._last_language = "mul"
            return cues
        finally:
            for leftover in (temporary, scratch):
                if leftover:
                    try:
                        os.unlink(leftover)
                    except OSError:
                        pass

    def release(self) -> None:
        """Drop the owned model pair.  The counters are monotonic and are **not** reset."""

        self._models = None

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
            "model_name": _dependency_provenance._redact(config.model_id or config.model_name),
            "aligner_model": _dependency_provenance._redact(config.aligner_name),
            "model_revision": _dependency_provenance._redact(config.model_revision or ""),
            "device": _dependency_provenance._redact(config.device),
            "language": _dependency_provenance._redact(self._last_language or config.language or ""),
            "hotwords": _dependency_provenance._redact(",".join(self._prompt_hotwords())),
            "chunk_seconds": f"{config.chunk_seconds:g}",
            "offline": str(config.offline),
            "local_source": _dependency_provenance._redact(config.local_source),
        }
        if self._hotwords_dropped:
            provenance["hotword_dropped_no_evidence"] = ",".join(
                _dependency_provenance._redact(term) for term in self._hotwords_dropped
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
    with ``bust_cache=True`` — the re-seeded vocabulary only reaches the model if
    the re-decode does not reuse pass 1's transformers prefix cache.  When the
    guard keeps nothing beyond pass 1's own output, pass 2 cannot change the
    transcript and its cost is skipped: pass 1's segments are the result.
    """

    runner.set_hotword_evidence(
        evidence_text=None, paired_subtitle_text=paired_subtitle_text
    )
    first_pass = runner.transcribe(audio_path)
    transcript_text = "".join(str(seg.get("text", "")) for seg in first_pass)
    if runner.rebuild_hotwords_from_first_pass(transcript_text):  # kept tokens
        return runner.transcribe(audio_path, bust_cache=True)
    return first_pass


def transcribe(audio_path: str, model_name: str | None = None) -> list[dict[str, Any]]:
    """Transcribe one file with a fresh runner (one-shot; batches should hold a runner)."""

    config = replace(_dependency_config.default_config(), model_name=model_name) if model_name else None
    return ASRRunner(config).transcribe(audio_path)


def provenance() -> dict[str, str]:
    """The provenance of the default configuration."""

    return ASRRunner(_dependency_config.default_config()).provenance()


sys.modules[__name__].__class__ = _RunnerModule
