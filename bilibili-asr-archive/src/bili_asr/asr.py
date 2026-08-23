"""Local SenseVoice ASR boundary.

The base CLI does not import FunASR. ``transcribe`` imports it lazily so
subtitle-only workflows stay lightweight and usable offline.
"""

from __future__ import annotations

import os
import re
from typing import Any

DEFAULT_MODEL = "iic/SenseVoiceSmall"
_INSTALL_HINT = 'pip install -e "bilibili-asr-archive/[asr]"'
_RICH_TAG = re.compile(r"<\|[^|>]+\|>")


class ASRDependencyError(RuntimeError):
    """The optional ASR dependency group is not installed."""


class ASRModelError(RuntimeError):
    """SenseVoice could not load or transcribe the supplied audio."""


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
                    segments.append({
                        "start": _seconds(sentence.get("start")),
                        "end": _seconds(sentence.get("end")),
                        "text": text,
                    })
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
        blocks.append(
            f"{index}\n{_fmt_srt_time(segment['start'])} --> "
            f"{_fmt_srt_time(segment['end'])}\n{segment['text']}\n"
        )
    return "\n".join(blocks)


def segments_to_txt(segments: list[dict[str, Any]]) -> str:
    return "\n".join(str(segment.get("text", "")).strip()
                     for segment in segments if str(segment.get("text", "")).strip())


def transcribe(audio_path: str, model_name: str | None = None) -> list[dict[str, Any]]:
    """Transcribe one audio file with SenseVoice-Small on CPU.

    Model weights are resolved by FunASR/ModelScope. Set ``BILI_ASR_MODEL`` to
    a local model directory for an offline run.
    """
    try:
        from funasr import AutoModel  # type: ignore
    except ImportError as exc:
        raise ASRDependencyError(
            f"SenseVoice support is not installed; run: {_INSTALL_HINT}"
        ) from exc

    selected_model = model_name or os.environ.get("BILI_ASR_MODEL") or DEFAULT_MODEL
    try:
        model = AutoModel(
            model=selected_model,
            trust_remote_code=True,
            device="cpu",
            vad_model="fsmn-vad",
            punc_model="ct-punc",
        )
        result = model.generate(
            input=audio_path,
            cache={},
            language="auto",
            use_itn=True,
            batch_size_s=60,
            merge_vad=True,
            merge_length_s=15,
        )
    except Exception as exc:
        raise ASRModelError(
            "SenseVoice model load/transcription failed. For offline use, "
            "set BILI_ASR_MODEL to a populated local model directory."
        ) from exc
    return normalize_result(result)
