"""Provenance implementation."""

from __future__ import annotations

from collections.abc import Mapping
import sys
import types
from typing import Any
import bili_asr.asr.constants as _dependency_constants
import bili_asr.asr.runner as _dependency_runner


def provenance_language(provenance: Any) -> str:
    """Return the persisted language with one shared implicit fallback."""
    if isinstance(provenance, Mapping):
        value = provenance.get("language")
        if value:
            return str(value)
    return _dependency_constants.DEFAULT_TRANSCRIPT_LANGUAGE


def apply_provenance_evidence(entry: dict[str, Any], runner: Any) -> None:
    """Carry the ASR branch's provenance on its resumable manifest row."""
    try:
        provenance = runner.provenance() or {}
    except Exception:
        provenance = {}
    entry["source"] = "asr"
    entry["language"] = provenance_language(provenance)


def _redact(value: str) -> str:
    """``[redacted]`` for a value that would publish a path, URL or credential."""

    return "[redacted]" if value and _dependency_constants._FORBIDDEN_PROVENANCE.search(value) else value


class _CallableModule(types.ModuleType):
    """Allow the package attribute to serve both module and one-shot API callers."""

    def __call__(self) -> dict[str, str]:
        return _dependency_runner.provenance()


sys.modules[__name__].__class__ = _CallableModule
