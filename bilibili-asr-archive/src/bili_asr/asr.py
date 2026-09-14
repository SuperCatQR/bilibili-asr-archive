"""Local FunASR ASR boundary.

FunASR is imported only when a runner first transcribes.  The runner is
explicitly configured, lazy, and scoped to one sequential batch; no model
cache or download orchestration lives here.

API Compatibility: ASRConfig retains `offline` and `local_source` fields for
backward compatibility with the legacy SenseVoice configuration surface, but
these parameters are not passed to the FunASR AutoModel API. They remain part
of the configuration schema and provenance surface only.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from dataclasses import asdict, dataclass, replace
from typing import Any, Callable

DEFAULT_MODEL = "FunAudioLLM/Fun-ASR-Nano-2512"


def _load_default_model(**kwargs: Any) -> Any:
    try:
        from funasr import AutoModel  # type: ignore
    except ImportError as exc:
        raise ASRDependencyError(
            f"FunASR support is not installed; run: {_INSTALL_HINT}"
        ) from exc
    return AutoModel(**kwargs)
_INSTALL_HINT = 'pip install -e "bilibili-asr-archive/[asr]"'
_RICH_TAG = re.compile(r"<\|[^|>]+\|>")
#: Credential markers open at the start of the value or after a letter-free
#: separator, and must not run into a following letter.  A trailing ``\b``
#: cannot do that job: ``_`` is a word character, so ``token_abc`` has no
#: boundary after the marker and the value would be published verbatim.  The
#: same separator-aware form is what ``quality._NAME_CREDENTIAL`` applies to
#: file names; an ordinary word such as ``tokenizer`` is still left alone in
#: both directions.
_FORBIDDEN_CREDENTIAL_MARKER = (
    r"(?:^|[^A-Za-z])(?:sessdata|cookie|token|password|secret|credential)(?![A-Za-z])"
)
#: Paths, URLs and credential-like values, in one definition.  The
#: ``local_source`` and provenance scans were byte-identical literals
#: (plan QC seat 1, S-2), so the weaker credential boundary lived in two
#: places; one definition is why it now lives in neither.
_FORBIDDEN_VALUE = re.compile(
    r"(?:[A-Za-z][A-Za-z0-9+.-]*://|\\\\|(?:^|[\\/])\\/|(?:^|[^A-Za-z])[A-Za-z]:[\\/]|"
    + _FORBIDDEN_CREDENTIAL_MARKER
    + r")",
    re.IGNORECASE,
)
_FORBIDDEN_LOCAL_SOURCE = _FORBIDDEN_VALUE
_FORBIDDEN_PROVENANCE = _FORBIDDEN_VALUE
_MODEL_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)*")


def _is_redaction_safe_model_identifier(value: str, *, hub_level: bool = False) -> bool:
    """The redaction rule for model identifiers, in one place.

    An identifier-shaped value with no forbidden marker is safe to serialize —
    that is the rule ``provenance()`` has always applied to ``model_name``.
    ``hub_level`` additionally demands a slash-qualified ``owner/name`` shape,
    which is what a declared producer identity must look like (D4.2).
    """

    if _MODEL_IDENTIFIER.fullmatch(value) is None:
        return False
    if _FORBIDDEN_PROVENANCE.search(value) is not None:
        return False
    return not hub_level or "/" in value


def _is_hub_level_model_name(value: str) -> bool:
    """Whether ``value`` names a hub repository rather than a local path (D4.3).

    ``hub_level`` above is ``"/" in value``, and that is deliberately all a
    *declaration* has to satisfy (D4.2): a shape-only rule cannot tell
    ``models/Fun-ASR-Nano-2512`` from ``Qwen/Qwen2.5-7B`` — both are two
    segments once.  The contradiction route needs the distinction the shape
    cannot carry, because it must not punish the relative-path form
    ``README.md`` documents.  Existence answers it on the machine that owns the
    layout: the trained checkpoint the operator points ``BILI_ASR_MODEL`` at is
    a directory that is *there*, and a hub id is a name that is not.  The probe
    resolves against the process working directory, exactly as the loader
    would.
    """

    if not _is_redaction_safe_model_identifier(value, hub_level=True):
        return False
    return not os.path.isdir(value)


class ASRDependencyError(RuntimeError):
    """The optional ASR dependency group is not installed."""


class ASRModelError(RuntimeError):
    """FunASR model could not load or transcribe the supplied audio."""


#: Environment knobs for the local ASR boundary.  ``BILI_ASR_MODEL`` accepts a
#: hub id (resolved to a pinned local snapshot) or a local checkpoint directory.
ASR_MODEL_ENV_VAR = "BILI_ASR_MODEL"
ASR_MODEL_REVISION_ENV_VAR = "BILI_ASR_MODEL_REVISION"
#: The operator's *declaration* of the hub-level identity behind the loaded
#: checkpoint.  ``BILI_ASR_MODEL`` may be a local directory, and a path is not a
#: redaction-safe identifier, so the archive is told what produced a transcript
#: through this variable instead.  It never changes the load and lands in the
#: ``model_name`` provenance slot rather than a key of its own.
ASR_MODEL_ID_ENV_VAR = "BILI_ASR_MODEL_ID"
ASR_DEVICE_ENV_VAR = "BILI_ASR_DEVICE"
ASR_LANGUAGE_ENV_VAR = "BILI_ASR_LANGUAGE"
ASR_VAD_MODEL_ENV_VAR = "BILI_ASR_VAD_MODEL"
ASR_HOTWORDS_ENV_VAR = "BILI_ASR_HOTWORDS"

#: Corpus vocabulary the decoder is biased towards.  Every entry has been
#: observed mis-recognised as a homophone on this archive's own audio
#: (``马鞍牌`` for 马恩牌, ``公式`` for 攻势, ``智力豆包`` for 智利豆包,
#: ``跟着苗红`` for 根正苗红) or is a recurring name of the corpus.  The list
#: stays short on purpose: the terms travel as one prompt line and a long list
#: dilutes the bias.
DEFAULT_HOTWORDS: tuple[str, ...] = (
    "未明子",
    "主义主义",
    "拟态论",
    "国际劳工仲裁",
    "国际劳联",
    "马恩牌",
    "攻势",
    "智利",
    "根正苗红",
    "亚美利坚",
    "黑格尔",
    "海德格尔",
    "拉康",
    "齐泽克",
    "德勒兹",
    "康德",
    "观念论",
    "本体论",
    "现象学",
    "辩证法",
    "定在",
    "自为",
    "理念性",
    # Latin-script terms the corpus actually speaks.  The Chinese-language model
    # fragments these into shards when they are missing from the prompt (measured
    # 2026-09-14 on the ten-video run: "International Employment Matters Tribunal"
    # came out as tryBUNAL / FOR EMP LOYMENT MAT TERS, and the ITEM/AITEM pair as
    # TEM / AITM / ITM).  They are listed as whole phrases as well as acronyms so
    # the decoder has both the spelled-out form and the initialisms.
    "ITEM",
    "AITEM",
    "International Employment Matters Tribunal",
    "International",
    "Employment",
    "Tribunal",
)

#: VAD component that segments long recordings before the ASR model sees them.
#: Measured 2026-09-11: without it a 448 s recording collapses to a single
#: ``。`` (the language model's decode overruns), while the same checkpoint
#: behind the VAD pipeline returns the full punctuated transcript with token
#: timestamps.  ``fsmn-vad`` is FunASR's own alias, resolved and cached by the
#: pinned package exactly like the checkpoint itself.
DEFAULT_VAD_MODEL = "fsmn-vad"

#: Cap on one VAD segment, in seconds.  Kept at FunASR's own example value:
#: measured 2026-09-12 on the archive's 448 s recording, lowering it to 15 s
#: changed nothing that matters (94 -> 95 cues, longest cue 14.5 -> 14.6 s,
#: transcripts 99 % identical), because the model's own punctuation splits
#: inside a VAD segment long before this cap binds.  The cap is therefore a
#: tunable safety bound, not a quality lever — and a smaller one only adds
#: chunk boundaries that can cut mid-word.
#:
#: What the VAD *does* control is how much audio reaches the model at all.  The
#: content-moving knobs stay at their library defaults: passing the
#: checkpoint's declared ``max_end_silence_time=800`` collapsed segmentation
#: from 92 to 58 segments and dropped 11 s of captured speech, and
#: ``speech_noise_thres=0.9`` dropped 31 s.
DEFAULT_VAD_MAX_SEGMENT_S = 30.0
VAD_MAX_SEGMENT_ENV_VAR = "BILI_ASR_VAD_MAX_SEGMENT_S"

#: A confined audio descriptor, as :func:`bili_asr.path_policy.confined_audio_file`
#: hands it over: ``/proc/self/fd/12`` or ``/dev/fd/12``.
_DESCRIPTOR_PATH = re.compile(r"^/(?:proc/(?:self|\d+)/fd|dev/fd)/\d+$")

#: A cue closes on one of these tokens, on a pause at least this long, or when
#: it reaches the character ceiling — whichever comes first.
_SENTENCE_ENDINGS = "。！？!?"
#: Marks that never open a cue: when one lands at a cue boundary it belongs to
#: the sentence that just ended, so the cue post-pass moves it back.
_CUE_CLOSING_MARKS = "。！？!?，、；：,;:"
_CUE_MAX_CHARS = 60
_CUE_MAX_GAP_SECONDS = 1.0
#: A cue below either bound is merged into its neighbour while the character
#: ceiling holds, so a pause in the middle of a thought no longer produces a
#: one-word subtitle.
_CUE_MIN_CHARS = 6
_CUE_MIN_SECONDS = 1.0


@dataclass(frozen=True)
class ASRConfig:
    """Deterministic, redaction-safe configuration for one ASR run.

    ``language`` is the spoken language passed to the model as documented
    (``中文``, ``英文``, ``日文``); ``None`` leaves the model's own generic
    transcription prompt in place.  It is never a free-form instruction.

    ``hotwords`` biases decoding towards this corpus's vocabulary.  An empty
    tuple sends no bias at all; the terms are recorded in provenance.

    ``model_id`` is the operator's **declaration** of the hub-level identity
    behind the loaded checkpoint (``BILI_ASR_MODEL_ID``).  ``model_name`` may be
    a local directory and a path is not a redaction-safe identifier, so the
    archive is told what produced a transcript here instead; the declaration
    never changes the load and lands in the ``model_name`` provenance slot, not
    in a key of its own.  It is appended **last** so existing positional
    construction is unaffected.
    """

    model_name: str
    model_revision: str | None = None
    device: str = "cuda"
    language: str | None = None
    vad_model: str | None = DEFAULT_VAD_MODEL
    vad_max_segment_s: float = DEFAULT_VAD_MAX_SEGMENT_S
    hotwords: tuple[str, ...] = ()
    offline: bool = True
    local_source: str = "configured-local"
    model_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.model_name, str) or not self.model_name.strip():
            raise ValueError("model_name must be a non-empty string")
        if self.model_revision is not None and (
            not isinstance(self.model_revision, str) or not self.model_revision.strip()
        ):
            raise ValueError("model_revision must be a non-empty string or null")
        if not isinstance(self.device, str) or not self.device.strip():
            raise ValueError("device must be a non-empty string")
        if self.language is not None and (
            not isinstance(self.language, str) or not self.language.strip()
        ):
            raise ValueError("language must be a non-empty string or null")
        if self.vad_model is not None and (
            not isinstance(self.vad_model, str) or not self.vad_model.strip()
        ):
            raise ValueError("vad_model must be a non-empty string or null")
        if isinstance(self.vad_max_segment_s, bool) or not isinstance(
            self.vad_max_segment_s, (int, float)
        ) or self.vad_max_segment_s <= 0:
            raise ValueError("vad_max_segment_s must be a positive number")
        if not isinstance(self.hotwords, tuple) or any(
            not isinstance(term, str) or not term.strip() for term in self.hotwords
        ):
            raise ValueError("hotwords must be a tuple of non-empty strings")
        if not isinstance(self.offline, bool):
            raise ValueError("offline must be a bool")
        if not isinstance(self.local_source, str) or not self.local_source.strip():
            raise ValueError("local_source must be a non-empty identifier")
        if _FORBIDDEN_LOCAL_SOURCE.search(self.local_source):
            raise ValueError("local_source must be an opaque local identifier")
        if self.model_id is not None:
            if not isinstance(self.model_id, str) or not self.model_id.strip():
                raise ValueError(
                    f"{ASR_MODEL_ID_ENV_VAR} must be a hub-level model identifier"
                )
            # Loud, not silent (D4.2): falling back to ``[redacted]`` would let
            # the operator believe the archive names its producer.
            if not _is_redaction_safe_model_identifier(self.model_id, hub_level=True):
                raise ValueError(
                    f"{ASR_MODEL_ID_ENV_VAR} must be a hub-level model identifier"
                )
            # A declaration that contradicts an already-safe load value would
            # make the archive lie about which model produced the transcript.
            # Hub-level only (D4.3 as amended at plan QC, F-002): a
            # relative-path-shaped ``BILI_ASR_MODEL`` that resolves to a real
            # directory is a local checkpoint, not a competing identity, and
            # refusing it would reject exactly the truthful declaration this
            # route exists to protect.
            if _is_hub_level_model_name(
                self.model_name
            ) and self.model_name != self.model_id:
                raise ValueError(
                    f"{ASR_MODEL_ID_ENV_VAR} contradicts {ASR_MODEL_ENV_VAR}: "
                    f"declared {self.model_id!r}, loaded {self.model_name!r}"
                )


def _materialize_input(audio_path: str) -> tuple[str, str | None]:
    """Return an input path the model's own components can reopen.

    The CLI hands this boundary a confined descriptor path so the audio never
    leaves the archive root.  FunASR's VAD component shells out to ``ffmpeg``,
    and a descriptor is closed on exec, so the child cannot open it: the input
    is copied to a temporary file instead, which the caller removes.  A plain
    path is returned untouched.
    """

    if not isinstance(audio_path, str) or not _DESCRIPTOR_PATH.match(audio_path):
        return audio_path, None
    handle, temporary = tempfile.mkstemp(prefix="bili-asr-asr-", suffix=".audio")
    try:
        with os.fdopen(handle, "wb") as target, open(audio_path, "rb") as source:
            shutil.copyfileobj(source, target)
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return temporary, temporary


def default_config() -> ASRConfig:
    """Build the runner configuration from the documented environment knobs.

    ``BILI_ASR_MODEL`` carries a **local checkpoint directory**.  A bare hub
    id cannot be loaded by the pinned package: the checkpoint is a
    remote-code model whose id has no FunASR alias, and its documented load
    route executes the checkpoint's own ``model.py``.  Materializing the
    snapshot (pinned revision) and pointing this variable at it keeps the
    boundary download-free and the pin real.

    ``BILI_ASR_MODEL_ID`` is the operator's *declaration* of the hub-level
    identity behind that checkpoint.  It is read for provenance only — it never
    reaches the loader — and an unset or blank value means "not declared", the
    same way the other knobs treat a blank as unset.

    A declaration that differs from a *hub-level* ``BILI_ASR_MODEL`` is refused
    (D4.3); a ``BILI_ASR_MODEL`` that resolves to a directory on this machine
    is a checkpoint path, whatever its spelling, so a truthful declaration
    beside it is accepted.
    """

    return ASRConfig(
        model_name=os.environ.get(ASR_MODEL_ENV_VAR) or DEFAULT_MODEL,
        model_revision=os.environ.get(ASR_MODEL_REVISION_ENV_VAR) or None,
        device=os.environ.get(ASR_DEVICE_ENV_VAR) or "cuda",
        language=os.environ.get(ASR_LANGUAGE_ENV_VAR) or None,
        vad_model=_resolve_vad_model(os.environ.get(ASR_VAD_MODEL_ENV_VAR)),
        vad_max_segment_s=_resolve_vad_max_segment(
            os.environ.get(VAD_MAX_SEGMENT_ENV_VAR)
        ),
        hotwords=DEFAULT_HOTWORDS + _extra_hotwords(os.environ.get(ASR_HOTWORDS_ENV_VAR)),
        # A blank declaration is "not declared", like the other knobs treat a
        # blank as unset — `BILI_ASR_MODEL_ID=` in a shell script must not turn
        # every run into a validation failure.
        model_id=(os.environ.get(ASR_MODEL_ID_ENV_VAR) or "").strip() or None,
    )


def _resolve_vad_max_segment(environment_value: str | None) -> float:
    """Return the configured VAD segment cap in seconds.

    Unset keeps the measured default; a blank value is treated as unset (it
    cannot silently disable the cap), and a non-numeric value is rejected
    loudly rather than ignored.
    """

    if environment_value is None or not environment_value.strip():
        return DEFAULT_VAD_MAX_SEGMENT_S
    try:
        value = float(environment_value.strip().rstrip("sS"))
    except ValueError:
        raise ValueError(
            f"{VAD_MAX_SEGMENT_ENV_VAR} must be a positive number of seconds"
        ) from None
    if value <= 0:
        raise ValueError(
            f"{VAD_MAX_SEGMENT_ENV_VAR} must be a positive number of seconds"
        )
    return value


def _extra_hotwords(environment_value: str | None) -> tuple[str, ...]:
    """Return the operator's extra hotwords, in order, without duplicates."""

    if not environment_value:
        return ()
    terms: list[str] = []
    for raw in environment_value.replace("，", ",").split(","):
        term = raw.strip()
        if term and term not in terms and term not in DEFAULT_HOTWORDS:
            terms.append(term)
    return tuple(terms)


def _resolve_vad_model(environment_value: str | None) -> str | None:
    """Return the configured VAD component: unset keeps the default, blank disables."""

    if environment_value is None:
        return DEFAULT_VAD_MODEL
    return environment_value.strip() or None


class ASRRunner:
    """Lazy model owner for sequential use within one run scope.

    ``model_constructions`` is a monotonic counter of the models this runner
    actually built (one per lazy construction, zero when the run never needed
    audio).  It is the observable form of the run-scoped reuse contract: a
    batch that reuses one runner reports one construction for N items.

    ``model_load_attempts`` is the attempt counter beside it (inherited
    residual R1 from ``20260912-batch-model-reuse``): a load the factory
    rejected is **retried once per row**, pays no construction, and is counted
    here instead.  Without it ``model_constructions == 0`` cannot be told
    apart between a runner that never needed a model and a runner whose N
    loads were all rejected.  The invariant is
    ``model_load_attempts >= model_constructions``, with equality when every
    load succeeded.

    This counter is recorded, not printed: the batch reuse line carries
    constructions only and is suppressed when no construction was paid and no
    item was transcribed, so a batch whose every load failed prints no line at
    all and states its N retries only through a caller that holds this runner.
    """

    def __init__(
        self,
        config: ASRConfig | str | None = None,
        *,
        model_factory: Callable[..., Any] | None = None,
        model_name: str | None = None,
    ) -> None:
        if config is None:
            config = ASRConfig(model_name=model_name or DEFAULT_MODEL)
        elif isinstance(config, str):
            if model_name is not None:
                raise TypeError("model_name cannot accompany a model name")
            config = ASRConfig(model_name=config)
        elif model_name is not None:
            raise TypeError("model_name is only accepted without a config")
        if not isinstance(config, ASRConfig):
            raise TypeError("config must be an ASRConfig")
        self.config = config
        self._model_factory = model_factory
        self._model: Any | None = None
        # Monotonic, never reset by release(): a runner that released and
        # rebuilt paid two constructions, and the count must say so.
        self.model_constructions = 0
        # Attempts, not successes (R1).  A failed load is retried once per row,
        # so ``attempts - constructions`` is exactly the number of load
        # failures this runner has paid for — the evidence the construction
        # count alone could not carry.
        self.model_load_attempts = 0

    def _get_model(self) -> Any:
        if self._model is not None:
            return self._model
        
        # Check CUDA availability if device is cuda (works for both NVIDIA CUDA and AMD ROCm)
        if self.config.device.startswith("cuda"):
            try:
                import torch
                if not torch.cuda.is_available():
                    raise ASRDependencyError(
                        "CUDA/ROCm is not available: no device is visible to PyTorch. "
                        "Run the environment check from the product directory with the "
                        "venv's interpreter (the one that has torch installed — "
                        '`"$VENV/bin/python" scripts/check_asr_env.py`); it names the stage '
                        "that fails and prints the fix, and `docs/wsl-rocm-gpu.md` carries "
                        "the verified AMD/WSL ROCm recipe. To transcribe without a device, "
                        "set `BILI_ASR_DEVICE=cpu`."
                    )
            except ImportError:
                raise ASRDependencyError(
                    "PyTorch is required for GPU inference but not installed. "
                    "Install with: pip install torch"
                ) from None
        
        factory = self._model_factory or _load_default_model
        # FunASR AutoModel accepts model, device, trust_remote_code,
        # model_revision, hub.  The checkpoint arrives as a local directory:
        # the pinned Nano checkpoint is a remote-code model without a FunASR
        # alias, so its snapshot must be materialized before the runner sees
        # it (see default_config).
        kwargs: dict[str, Any] = {
            "model": self.config.model_name,
            "device": self.config.device,
            "trust_remote_code": False,
        }
        if self.config.vad_model is not None:
            kwargs["vad_model"] = self.config.vad_model
            kwargs["vad_kwargs"] = {
                "max_single_segment_time": int(self.config.vad_max_segment_s * 1000)
            }
        if self.config.model_revision is not None:
            kwargs["model_revision"] = self.config.model_revision
        # Note: offline/local_source removed - not supported by FunASR API
        
        try:
            # Counted *before* the call, so every factory invocation is an
            # attempt whether it returned a model or raised (R1).  ``_model``
            # stays None on failure and the next row retries the same call,
            # which is why the attempt counter and the construction counter
            # must not be the same number.
            self.model_load_attempts += 1
            self._model = factory(**kwargs)
        except ASRDependencyError:
            raise
        except Exception:
            raise ASRModelError(
                "FunASR model load/transcription failed; check configured local model."
            ) from None
        # Counted only here, after the factory returned a model: a failed load
        # paid no construction, so it must not inflate the reported count.
        self.model_constructions += 1
        return self._model

    def transcribe(self, audio_path: str) -> list[dict[str, Any]]:
        """Transcribe one audio file with the parameters the pinned model reads.

        Fun-ASR-Nano reads ``itn`` (not ``use_itn``) and takes ``language`` and
        ``hotwords`` as prompt text, so only configured values are passed.
        ``batch_size_s`` / ``merge_vad`` / ``merge_length_s`` belong to a VAD
        pipeline this boundary configures at construction, not per call.
        """

        request: dict[str, Any] = {"input": audio_path, "cache": {}, "itn": True}
        if self.config.language is not None:
            request["language"] = self.config.language
        if self.config.hotwords:
            request["hotwords"] = list(self.config.hotwords)
        source, temporary = _materialize_input(audio_path)
        request["input"] = source
        try:
            result = self._get_model().generate(**request)
        except (ASRDependencyError, ASRModelError):
            raise
        except Exception as exc:
            raise ASRModelError(
                "FunASR model load/transcription failed; check configured local model."
            ) from exc
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
        return normalize_result(result)

    def release(self) -> None:
        """Dereference the model owned by this runner."""
        self._model = None

    def provenance(self) -> dict[str, str]:
        """Redaction-safe configuration; the declared id fills the name slot.

        Precedence (D4.3): the declared ``model_id``, else the configured
        ``model_name`` when it is itself redaction-safe, else ``[redacted]``.
        ``model_id`` is a **slot replacement, never a key** (D4.4): it is
        skipped while rendering and only substitutes into the ``model_name``
        slot, so the nine-key contract and its order are untouched.

        The re-scan applies the *validator's* strength to whichever value fills
        the slot (S-2): a declared id is re-checked at hub level, exactly as
        ``__post_init__`` checks it, while a configured ``model_name`` keeps the
        historical rule and may therefore be a bare safe identifier such as
        ``local-model``.  Rendering stays shape-only — it never probes the
        filesystem — so this is the same rule as validation, not the same
        predicate as the contradiction route.
        """

        values = asdict(self.config)
        declared_id = values.pop("model_id", None)
        safe_values: dict[str, str] = {}
        for key, value in values.items():
            rendered = (
                ",".join(value)
                if key == "hotwords" and isinstance(value, tuple)
                else "" if value is None else str(value)
            )
            if key == "model_name" and declared_id is not None:
                rendered = str(declared_id)
            is_safe_model_identifier = (
                key == "model_name"
                and _is_redaction_safe_model_identifier(
                    rendered, hub_level=declared_id is not None
                )
            )
            if _FORBIDDEN_PROVENANCE.search(rendered) or (
                key == "model_name" and not is_safe_model_identifier
            ):
                rendered = "[redacted]"
            safe_values[key] = rendered
        return safe_values


def _clean_text(text: str) -> str:
    return _RICH_TAG.sub("", text or "").strip()


def _body(text: str) -> str:
    """The part of a cue that carries meaning, without its closing marks."""

    return text.strip(_CUE_CLOSING_MARKS).strip()


def _join_text(left: str, right: str) -> str:
    """Join two cue texts, keeping a separator between Latin words.

    Nano emits an English phrase as several tokens and does not always carry
    the leading space, so absorbing a fragment into the cue before it must not
    glue the words together.  Chinese text is unaffected: the space is only
    added between two ASCII alphanumerics.
    """

    if (
        left
        and right
        and left[-1].isascii()
        and left[-1].isalnum()
        and right[0].isascii()
        and right[0].isalnum()
    ):
        return f"{left} {right}"
    return left + right


def _token_cues(tokens: Any) -> list[dict[str, Any]]:
    """Shape Fun-ASR-Nano token timestamps into subtitle cues, in one pass.

    Nano returns ``timestamps`` as ``{"token", "start_time", "end_time",
    "score"}`` entries whose times are **seconds** and whose punctuation
    arrives as its own token, so cue text stays the verbatim token text.  A cue
    closes on a sentence-ending token, at :data:`_CUE_MAX_CHARS` characters, or
    on a pause of at least :data:`_CUE_MAX_GAP_SECONDS` — but a pause only
    closes a cue that can already stand on its own, and a cue that is still
    only punctuation or below :data:`_CUE_MIN_CHARS` / :data:`_CUE_MIN_SECONDS`
    is absorbed by the cue before it.  Nothing shapes the text a second time
    afterwards, and nothing is dropped.

    ``confidence`` is the mean token score of the cue when the model reports
    scores; it is measurement, not a rewrite.
    """

    if not isinstance(tokens, list):
        return []
    cues: list[dict[str, Any]] = []
    parts: list[str] = []
    scores: list[float] = []
    start: float | None = None
    last_end: float | None = None
    pending = ""          # text the cue before it could not take

    def formed() -> bool:
        return (
            len(_body("".join(parts))) >= _CUE_MIN_CHARS
            and (last_end or 0.0) - (start or 0.0) >= _CUE_MIN_SECONDS
        )

    def reset() -> None:
        nonlocal parts, scores, start, last_end, pending
        parts, scores, start, last_end, pending = [], [], None, None, ""

    def hand_back(piece: str, end: float) -> None:
        """Give a closing mark to the cue it actually closes."""

        cues[-1]["text"] = _join_text(str(cues[-1]["text"]), piece)
        cues[-1]["end"] = max(float(cues[-1]["end"]), end)

    def close() -> None:
        nonlocal pending
        text = _clean_text(pending + "".join(parts))
        if not text:
            reset()
            return
        confidence = round(sum(scores) / len(scores), 3) if scores else None
        span = last_end or start or 0.0
        undersized = len(_body(text)) < _CUE_MIN_CHARS or (span - (start or 0.0)) < _CUE_MIN_SECONDS
        if cues and (undersized or not _body(text)):
            # a fragment joins the cue before it: the character ceiling is a
            # readability target, and losing text to it would be worse
            previous = cues[-1]
            previous["text"] = _join_text(str(previous["text"]), text)
            previous["end"] = max(float(previous["end"]), span)
            reset()
            return
        cue = {"start": start, "end": span, "text": text}
        if confidence is not None:
            cue["confidence"] = confidence
        cues.append(cue)
        reset()

    for token in tokens:
        if not isinstance(token, dict):
            continue
        piece = str(token.get("token") or "")
        begin = token.get("start_time")
        end = token.get("end_time")
        if not isinstance(begin, (int, float)) or not isinstance(end, (int, float)):
            continue
        begin, end = float(begin), float(end)
        mark = piece.strip()
        if start is None:
            # a closing mark never opens a cue: it belongs to the cue it closes
            if mark and mark[0] in _CUE_CLOSING_MARKS:
                # a mark is one character: it goes back, ceiling or not
                if cues:
                    hand_back(piece, end)
                else:
                    pending += piece
                continue
            start = begin
        elif begin - (last_end or begin) >= _CUE_MAX_GAP_SECONDS and formed():
            close()
            if mark and mark[0] in _CUE_CLOSING_MARKS and cues:
                hand_back(piece, end)
                continue
            start = begin
        parts.append(piece)
        last_end = end
        raw_score = token.get("score")
        if isinstance(raw_score, (int, float)) and not isinstance(raw_score, bool):
            scores.append(float(raw_score))
        if mark in _SENTENCE_ENDINGS or len(pending + "".join(parts)) >= _CUE_MAX_CHARS:
            close()
    close()
    return cues


def normalize_result(result: Any) -> list[dict[str, Any]]:
    """Turn one FunASR result into timestamped segments.

    The pinned model returns ``timestamps``: one entry per character, in
    seconds, punctuation included, so cue text is the recognised text verbatim.
    A result that carries text but no usable timings is kept as a single
    zero-length segment rather than dropped, so a transcript is never silently
    lost.
    """

    items = result if isinstance(result, list) else [result]
    segments: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        tokens = item.get("timestamps")
        if isinstance(tokens, list) and any(isinstance(token, dict) for token in tokens):
            cues = _token_cues(tokens)
            if cues:
                segments.extend(cues)
                continue
        text = _clean_text(str(item.get("text") or ""))
        if text:
            segments.append({"start": 0.0, "end": 0.0, "text": text})
    return segments


def _fmt_srt_time(seconds: float) -> str:
    milliseconds = max(0, round(float(seconds) * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def segments_to_srt(segments: list[dict[str, Any]]) -> str:
    blocks = []
    for index, segment in enumerate(segments, start=1):
        blocks.append(f"{index}\n{_fmt_srt_time(segment['start'])} --> {_fmt_srt_time(segment['end'])}\n{segment['text']}\n")
    return "\n".join(blocks)


def segments_to_txt(segments: list[dict[str, Any]]) -> str:
    return "\n".join(str(segment.get("text", "")).strip() for segment in segments if str(segment.get("text", "")).strip())


def transcribe(audio_path: str, model_name: str | None = None) -> list[dict[str, Any]]:
    """Compatibility wrapper: one short-lived runner using env/default selection.

    ``model_name`` overrides the load value through ``dataclasses.replace``,
    which re-runs ``ASRConfig.__post_init__``.  While ``BILI_ASR_MODEL_ID``
    declares an identity, a ``model_name`` override that contradicts it
    therefore raises ``ValueError`` (F-003) instead of silently producing
    segments the recorded producer would misdescribe — the same loud refusal
    D4.2 applies to a mis-declared environment.  An override that agrees with
    the declaration, or an environment with nothing declared, still returns the
    usual segments.
    """

    config = default_config()
    if model_name is not None:
        config = replace(config, model_name=model_name)
    return ASRRunner(config).transcribe(audio_path)


def provenance() -> dict[str, str]:
    """Return the redaction-safe configuration of the process-default runner.

    Reads no model and transcribes nothing, so a caller that produced segments
    through :func:`transcribe` can still record what produced them.
    """

    return ASRRunner(default_config()).provenance()
