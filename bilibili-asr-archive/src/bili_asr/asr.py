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
_FORBIDDEN_LOCAL_SOURCE = re.compile(
    r"(?:[A-Za-z][A-Za-z0-9+.-]*://|\\\\|(?:^|[\\/])\\/|(?:^|[^A-Za-z])[A-Za-z]:[\\/]|\b(?:sessdata|cookie|token|password|secret|credential)\b)",
    re.IGNORECASE,
)
_FORBIDDEN_PROVENANCE = re.compile(
    r"(?:[A-Za-z][A-Za-z0-9+.-]*://|\\\\|(?:^|[\\/])\\/|(?:^|[^A-Za-z])[A-Za-z]:[\\/]|\b(?:sessdata|cookie|token|password|secret|credential)\b)",
    re.IGNORECASE,
)
_MODEL_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)*")


class ASRDependencyError(RuntimeError):
    """The optional ASR dependency group is not installed."""


class ASRModelError(RuntimeError):
    """FunASR model could not load or transcribe the supplied audio."""


#: Environment knobs for the local ASR boundary.  ``BILI_ASR_MODEL`` accepts a
#: hub id (resolved to a pinned local snapshot) or a local checkpoint directory.
ASR_MODEL_ENV_VAR = "BILI_ASR_MODEL"
ASR_MODEL_REVISION_ENV_VAR = "BILI_ASR_MODEL_REVISION"
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

#: Checkpoint revision used when a hub id is resolved and no revision is configured.
DEFAULT_MODEL_REVISION = "master"

_LOCAL_PATH_PREFIXES = ("./", "../", "/", "~/", ".\\", "..\\")
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")
#: A confined audio descriptor, as :func:`bili_asr.path_policy.confined_audio_file`
#: hands it over: ``/proc/self/fd/12`` or ``/dev/fd/12``.
_DESCRIPTOR_PATH = re.compile(r"^/(?:proc/(?:self|\d+)/fd|dev/fd)/\d+$")
#: A hub reference is ``owner/name``; any other spelling is handed to FunASR
#: unchanged so a caller's own naming keeps its previous behaviour.
_HUB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")

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


def _looks_like_local_path(value: str) -> bool:
    """Report whether a configured model reference names a local checkpoint."""

    if value.startswith(_LOCAL_PATH_PREFIXES) or _WINDOWS_DRIVE.match(value):
        return True
    return os.path.isdir(value)


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
    """Lazy model owner for sequential use within one run scope."""

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
            self._model = factory(**kwargs)
        except ASRDependencyError:
            raise
        except Exception:
            raise ASRModelError(
                "FunASR model load/transcription failed; check configured local model."
            ) from None
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
        values = asdict(self.config)
        safe_values: dict[str, str] = {}
        for key, value in values.items():
            rendered = (
                ",".join(value)
                if key == "hotwords" and isinstance(value, tuple)
                else "" if value is None else str(value)
            )
            is_safe_model_identifier = (
                key == "model_name" and _MODEL_IDENTIFIER.fullmatch(rendered) is not None
            )
            if _FORBIDDEN_PROVENANCE.search(rendered) or (
                key == "model_name" and not is_safe_model_identifier
            ):
                rendered = "[redacted]"
            safe_values[key] = rendered
        return safe_values


def _clean_text(text: str) -> str:
    return _RICH_TAG.sub("", text or "").strip()


def _seconds(value: Any) -> float:
    """FunASR sentence/timestamp values are milliseconds."""
    return float(value or 0) / 1000.0


def _has_body(text: str) -> bool:
    """Report whether a cue carries anything other than punctuation."""

    return bool(text.strip(_CUE_CLOSING_MARKS).strip())


def _is_undersized(cue: dict[str, Any]) -> bool:
    """Report whether a cue is too small to stand on its own in a subtitle."""

    body = str(cue["text"]).lstrip(_CUE_CLOSING_MARKS)
    return len(body) < _CUE_MIN_CHARS or (cue["end"] - cue["start"]) < _CUE_MIN_SECONDS


def _join_text(left: str, right: str) -> str:
    """Join two cue texts, keeping a separator between Latin words.

    Nano emits an English phrase as several tokens and does not always carry
    the leading space, so a merge that concatenated blindly produced
    ``laborlaborgang``.  Chinese text is unaffected: the space is only added
    between two ASCII alphanumerics.
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


def _absorb(target: dict[str, Any], cue: dict[str, Any]) -> None:
    """Append one cue's text and span to another, keeping the earlier start."""

    target["text"] = _join_text(str(target["text"]), str(cue["text"]))
    target["end"] = max(float(target["end"]), float(cue["end"]))


def _polish_cues(cues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Turn raw token groups into cues that read well as subtitles.

    A mark never opens a cue (it belongs to the sentence that just ended), a
    cue that is punctuation-only is absorbed, and a cue below the size floor is
    merged into a neighbour while the character ceiling holds.  Nothing is
    dropped and no timing is invented.
    """

    polished: list[dict[str, Any]] = []
    for cue in cues:
        text = str(cue["text"])
        if polished and text[:1] and text[0] in _CUE_CLOSING_MARKS:
            head, text = text[0], text[1:]
            if len(str(polished[-1]["text"])) + len(head) <= _CUE_MAX_CHARS:
                polished[-1]["text"] = str(polished[-1]["text"]) + head
            else:
                text = head + text
        merged = {"start": cue["start"], "end": cue["end"], "text": _clean_text(text)}
        if not merged["text"]:
            continue
        if not polished:
            polished.append(merged)
            continue
        previous = polished[-1]
        fits = len(str(previous["text"])) + len(merged["text"]) <= _CUE_MAX_CHARS
        if fits and (not _has_body(merged["text"]) or _is_undersized(merged)):
            _absorb(previous, merged)
            continue
        polished.append(merged)
    if len(polished) > 1 and not _has_body(str(polished[0]["text"])):
        head = polished.pop(0)
        _absorb_leading(polished[0], head)
    return polished


def _absorb_leading(target: dict[str, Any], cue: dict[str, Any]) -> None:
    """Fold a punctuation-only opening cue into the cue that follows it."""

    target["text"] = _join_text(str(cue["text"]), str(target["text"]))
    target["start"] = min(float(target["start"]), float(cue["start"]))


def _token_cues(tokens: Any) -> list[dict[str, Any]]:
    """Group Fun-ASR-Nano token timestamps into cue-sized segments.

    Nano returns ``timestamps`` as ``{"token", "start_time", "end_time"}``
    entries whose times are **seconds** and whose punctuation arrives as its
    own token, so cue text is the verbatim token text — punctuation included.
    A cue closes on a sentence-ending token, on a pause of at least
    :data:`_CUE_MAX_GAP_SECONDS`, or at :data:`_CUE_MAX_CHARS` characters; the
    groups are then polished by :func:`_polish_cues`.
    """

    if not isinstance(tokens, list):
        return []
    cues: list[dict[str, Any]] = []
    parts: list[str] = []
    start: float | None = None
    last_end: float | None = None

    def close() -> None:
        nonlocal parts, start, last_end
        if start is not None and parts:
            text = _clean_text("".join(parts))
            if text:
                cues.append({"start": start, "end": last_end or start, "text": text})
        parts = []
        start = None
        last_end = None

    for token in tokens:
        if not isinstance(token, dict):
            continue
        piece = str(token.get("token") or "")
        begin = token.get("start_time")
        end = token.get("end_time")
        if not isinstance(begin, (int, float)) or not isinstance(end, (int, float)):
            continue
        if start is None:
            start = float(begin)
        elif float(begin) - float(last_end or begin) >= _CUE_MAX_GAP_SECONDS:
            close()
            start = float(begin)
        parts.append(piece)
        last_end = float(end)
        if piece.strip() in _SENTENCE_ENDINGS or len("".join(parts)) >= _CUE_MAX_CHARS:
            close()
    close()
    return _polish_cues(cues)


def normalize_result(result: Any) -> list[dict[str, Any]]:
    """Normalize common FunASR result shapes into timestamped segments.

    Recognized shapes, in order: ``sentence_info``/``sentences`` (milliseconds),
    Fun-ASR-Nano token ``timestamps`` (seconds, punctuation tokens included),
    and the legacy ``timestamp`` integer pairs (milliseconds) carrying one
    ``text``.  A result with none of them is stored as a single zero-length
    segment rather than dropped, so a transcript is never silently lost.
    """

    items = result if isinstance(result, list) else [result]
    segments: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        sentences = item.get("sentence_info") or item.get("sentences") or []
        if sentences:
            for sentence in sentences:
                text = _clean_text(str(sentence.get("text") or ""))
                if text:
                    segments.append({"start": _seconds(sentence.get("start")), "end": _seconds(sentence.get("end")), "text": text})
            continue
        tokens = item.get("timestamps")
        if isinstance(tokens, list) and any(isinstance(token, dict) for token in tokens):
            cues = _token_cues(tokens)
            if cues:
                segments.extend(cues)
                continue
        text = _clean_text(str(item.get("text") or ""))
        if not text:
            continue
        timestamps = item.get("timestamp") or []
        start = _seconds(timestamps[0][0]) if timestamps else 0.0
        end = _seconds(timestamps[-1][1]) if timestamps else start
        segments.append({"start": start, "end": end, "text": text})
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
    """Compatibility wrapper: one short-lived runner using env/default selection."""
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
