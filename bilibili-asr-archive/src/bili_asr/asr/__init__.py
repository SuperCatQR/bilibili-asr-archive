"""ASR subsystem public boundary.

Implementation lives in focused modules; this file intentionally exposes the
small set of names consumed by the archive and CLI layers.
"""

import subprocess as subprocess
import sys
import types

from bili_asr.cues import _fmt_srt_time, segments_to_srt, segments_to_txt
from .alignment import _aligned_cues, _characters_from_pieces, _clean_text, _thread_text
from .audio import _decode_with_ffmpeg, _materialize_input, _read_audio, _split_audio
from .config import ASRConfig, default_config
from .constants import *  # noqa: F401,F403
from .coverage import (
    apply_coverage_evidence,
    characters_of,
    coverage_verdict,
    transcribed_coverage,
)
from .errors import ASRDependencyError, ASRModelError, AudioDecodeError
from .hotwords import evidence_guard_hotwords, filter_hotwords
from . import provenance as provenance
from .provenance import apply_provenance_evidence, provenance_language
from .runner import ASRRunner, transcribe, two_pass_transcribe
from . import runner as _runner_module

# Kept as a named import for callers that inspect the install hint while
# keeping the constant's owner in the constants module.
from .constants import _INSTALL_HINT


class _AsrModule(types.ModuleType):
    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        if name == "ASRRunner":
            _runner_module.ASRRunner = value


sys.modules[__name__].__class__ = _AsrModule

__all__ = [
    "ASRConfig", "ASRDependencyError", "ASRModelError", "ASRRunner",
    "AudioDecodeError", "apply_coverage_evidence", "apply_provenance_evidence",
    "characters_of", "coverage_verdict", "default_config", "evidence_guard_hotwords",
    "filter_hotwords", "provenance", "provenance_language", "segments_to_srt",
    "segments_to_txt", "transcribe", "transcribed_coverage", "two_pass_transcribe",
]
