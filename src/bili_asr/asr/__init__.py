"""ASR subsystem public boundary.

Implementation lives in focused modules; this file intentionally exposes the
small set of names consumed by the archive and CLI layers.
"""

from __future__ import annotations

import subprocess as subprocess
from collections.abc import Callable
from typing import Any

from bili_asr.cues import _fmt_srt_time as _fmt_srt_time
from bili_asr.cues import segments_to_srt, segments_to_txt

from . import runner as _runner_module
from .alignment import _aligned_cues as _aligned_cues
from .alignment import _characters_from_pieces as _characters_from_pieces
from .alignment import _clean_text as _clean_text
from .alignment import _thread_text as _thread_text
from .audio import _decode_with_ffmpeg as _decode_with_ffmpeg
from .audio import _materialize_input as _materialize_input
from .audio import _read_audio as _read_audio
from .audio import _split_audio as _split_audio
from .config import ASRConfig, default_config
from .constants import *

# Kept as a named import for callers that inspect the install hint while
# keeping the constant's owner in the constants module.
from .constants import _INSTALL_HINT as _INSTALL_HINT
from .coverage import (
    apply_coverage_evidence,
    characters_of,
    coverage_verdict,
    transcribed_coverage,
)
from .errors import ASRDependencyError, ASRModelError, AudioDecodeError
from .hotwords import evidence_guard_hotwords, filter_hotwords
from .provenance import apply_provenance_evidence, provenance_language
from .runner import (
    ASRInferenceTimeoutError,
    ASRRunner,
    transcribe_with_timeout,
    two_pass_transcribe,
)


def transcribe(
    audio_path: str,
    model_name: str | None = None,
    *,
    runner_factory: Callable[[ASRConfig | None], ASRRunner] | None = None,
) -> list[dict[str, Any]]:
    """Transcribe through the runner configured at this public boundary."""

    factory = ASRRunner if runner_factory is None else runner_factory
    return _runner_module.transcribe(audio_path, model_name, runner_factory=factory)


def provenance(
    *, runner_factory: Callable[[ASRConfig | None], ASRRunner] | None = None
) -> dict[str, str]:
    """Read default provenance without loading models or changing module state."""

    factory = ASRRunner if runner_factory is None else runner_factory
    return _runner_module.provenance(runner_factory=factory)


__all__ = [
    "ASRConfig", "ASRDependencyError", "ASRInferenceTimeoutError", "ASRModelError", "ASRRunner",
    "AudioDecodeError", "apply_coverage_evidence", "apply_provenance_evidence",
    "characters_of", "coverage_verdict", "default_config", "evidence_guard_hotwords",
    "filter_hotwords", "provenance", "provenance_language", "segments_to_srt",
    "segments_to_txt", "transcribe", "transcribe_with_timeout", "transcribed_coverage",
    "two_pass_transcribe",
]
