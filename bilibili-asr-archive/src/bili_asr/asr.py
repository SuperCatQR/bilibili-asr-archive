"""Local SenseVoice ASR boundary.

FunASR is imported only when a runner first transcribes.  The runner is
explicitly configured, lazy, and scoped to one sequential batch; no model
cache or download orchestration lives here.
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from typing import Any, Callable

DEFAULT_MODEL = "iic/SenseVoiceSmall"


def _load_default_model(**kwargs: Any) -> Any:
    try:
        from funasr import AutoModel  # type: ignore
    except ImportError as exc:
        raise ASRDependencyError(
            f"SenseVoice support is not installed; run: {_INSTALL_HINT}"
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


class ASRDependencyError(RuntimeError):
    """The optional ASR dependency group is not installed."""


class ASRModelError(RuntimeError):
    """SenseVoice could not load or transcribe the supplied audio."""


@dataclass(frozen=True)
class ASRConfig:
    """Deterministic, redaction-safe configuration for one ASR run."""

    model_name: str
    model_revision: str | None = None
    device: str = "cpu"
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
        if not isinstance(self.offline, bool):
            raise ValueError("offline must be a bool")
        if not isinstance(self.local_source, str) or not self.local_source.strip():
            raise ValueError("local_source must be a non-empty identifier")
        if _FORBIDDEN_LOCAL_SOURCE.search(self.local_source):
            raise ValueError("local_source must be an opaque local identifier")


class ASRRunner:
    """Lazy, run-scoped model owner."""

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
        factory = self._model_factory or _load_default_model
        kwargs: dict[str, Any] = {
            "model": self.config.model_name,
            "device": self.config.device,
            "trust_remote_code": False,
            "vad_model": "fsmn-vad",
            "punc_model": "ct-punc",
            "offline": self.config.offline,
            "local_source": self.config.local_source,
        }
        if self.config.model_revision is not None:
            kwargs["model_revision"] = self.config.model_revision
        try:
            self._model = factory(**kwargs)
        except Exception:
            raise ASRModelError(
                "SenseVoice model load/transcription failed; check configured local model."
            ) from None
        return self._model

    def transcribe(self, audio_path: str) -> list[dict[str, Any]]:
        try:
            result = self._get_model().generate(
                input=audio_path,
                cache={},
                language="auto",
                use_itn=True,
                batch_size_s=60,
                merge_vad=True,
                merge_length_s=15,
            )
        except (ASRDependencyError, ASRModelError):
            raise
        except Exception as exc:
            raise ASRModelError(
                "SenseVoice model load/transcription failed; check configured local model."
            ) from exc
        return normalize_result(result)

    def transcribe_many(self, audio_paths: list[str]) -> list[list[dict[str, Any]]]:
        return [self.transcribe(audio_path) for audio_path in audio_paths]

    def provenance(self) -> dict[str, str]:
        values = asdict(self.config)
        safe_values: dict[str, str] = {}
        for key, value in values.items():
            rendered = str(value)
            if _FORBIDDEN_PROVENANCE.search(rendered) or (
                key == "model_name" and ("/" in rendered or "\\" in rendered)
            ):
                rendered = "[redacted]"
            safe_values[key] = rendered
        return safe_values


def _clean_text(text: str) -> str:
    return _RICH_TAG.sub("", text or "").strip()


def _seconds(value: Any) -> float:
    """FunASR sentence/timestamp values are milliseconds."""
    return float(value or 0) / 1000.0


def normalize_result(result: Any) -> list[dict[str, Any]]:
    """Normalize common FunASR result shapes into timestamped segments."""
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
    selected_model = model_name or os.environ.get("BILI_ASR_MODEL") or DEFAULT_MODEL
    return ASRRunner(ASRConfig(model_name=selected_model)).transcribe(audio_path)
