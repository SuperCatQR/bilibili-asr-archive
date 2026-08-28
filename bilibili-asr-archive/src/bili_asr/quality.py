"""Deterministic, read-only subtitle and transcript artifact quality signals."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

REASON_CODES = (
    "empty",
    "malformed",
    "non_monotonic",
    "overlap",
    "out_of_range",
    "identity_mismatch",
    "artifact_missing",
)
_MAX_BYTES = 8 * 1024 * 1024
_MAX_CUES = 10_000
_SRT_TIME = re.compile(
    r"^(?P<h>\d{1,3}):(?P<m>[0-5]\d):(?P<s>[0-5]\d)[,.](?P<ms>\d{1,3})$"
)


@dataclass(frozen=True)
class QualityResult:
    """Stable projection of quality observations for one manifest row."""

    source: str | None
    language: str | None
    status: str | None
    cue_count: int
    artifact_count: int
    reasons: tuple[str, ...]
    diagnostics: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "language": self.language,
            "status": self.status,
            "cue_count": self.cue_count,
            "artifact_count": self.artifact_count,
            "reasons": list(self.reasons),
            "diagnostics": list(self.diagnostics),
        }


class QualityAnalyzer:
    """Inspect local subtitle/archive artifacts without changing them."""

    def analyze(
        self, row: Mapping[str, object], archive_root: Path
    ) -> QualityResult:
        reasons: set[str] = set()
        diagnostics: set[str] = set()
        artifacts = _artifact_paths(row, archive_root)
        cue_count = 0
        valid_artifacts = 0
        if not artifacts:
            reasons.add("artifact_missing")
        for path in artifacts:
            if not _contained(path, archive_root) or not path.is_file():
                reasons.add("artifact_missing")
                continue
            try:
                if path.stat().st_size > _MAX_BYTES:
                    reasons.add("malformed")
                    diagnostics.add("file_too_large")
                    continue
                text = path.read_text(encoding="utf-8")
                cues, malformed, empty = _read_cues(path, text)
            except (OSError, UnicodeError):
                reasons.add("malformed")
                diagnostics.add("unreadable")
                continue
            valid_artifacts += 1
            cue_count = min(_MAX_CUES, cue_count + len(cues))
            if malformed:
                reasons.add("malformed")
            if empty:
                reasons.add("empty")
            _check_cues(cues, row, reasons)
            _check_identity(path, text, row, reasons)
        if valid_artifacts and cue_count == 0:
            reasons.add("empty")
        return QualityResult(
            source=_text_value(row, "source", "subtitle_source"),
            language=_text_value(row, "language", "sub_lan", "subtitle_language"),
            status=_text_value(row, "status"),
            cue_count=cue_count,
            artifact_count=valid_artifacts,
            reasons=tuple(sorted(reasons, key=REASON_CODES.index)),
            diagnostics=tuple(sorted(diagnostics)[:8]),
        )


def _text_value(row: Mapping[str, object], *keys: str) -> str | None:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return None


def _artifact_paths(row: Mapping[str, object], root: Path) -> list[Path]:
    values: list[object] = []
    for key in ("subtitle_path", "srt_path", "txt_path", "raw_path", "artifact_path"):
        if row.get(key) is not None:
            values.append(row[key])
    paths = row.get("artifact_paths")
    if isinstance(paths, (list, tuple)):
        values.extend(paths)
    inferred = not values
    if inferred:
        stem = _text_value(row, "work_id", "bvid")
        if stem:
            values.extend((Path("transcripts/srt") / f"{stem}.srt",
                           Path("transcripts/txt") / f"{stem}.txt",
                           Path("transcripts/raw") / f"{stem}.json"))
    result: list[Path] = []
    for value in values:
        if isinstance(value, (str, Path)) and value:
            path = Path(value)
            resolved = path if path.is_absolute() else root / path
            if inferred and not resolved.exists():
                continue
            result.append(resolved)
    if inferred and not result and values:
        result.append(root / values[0])
    return list(dict.fromkeys(result))


def _contained(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _read_cues(path: Path, text: str) -> tuple[list[tuple[float, float]], bool, bool]:
    if not text.strip():
        return [], False, True
    if path.suffix.lower() == ".srt":
        cues: list[tuple[float, float]] = []
        malformed = False
        blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n"))
        for block in blocks:
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            if not lines:
                continue
            timing = next((line for line in lines if "-->" in line), None)
            if timing is None:
                malformed = True
                continue
            parts = [part.strip() for part in timing.split("-->", 1)]
            if len(parts) != 2:
                malformed = True
                continue
            start, end = _parse_time(parts[0]), _parse_time(parts[1])
            if start is None or end is None:
                malformed = True
            else:
                cues.append((start, end))
        return cues[:_MAX_CUES], malformed, not cues
    if path.suffix.lower() == ".json":
        try:
            document = json.loads(text)
        except (ValueError, TypeError):
            return [], True, False
        items = document.get("body") if isinstance(document, dict) else document
        if not isinstance(items, list):
            return [], True, False
        cues = []
        malformed = False
        for item in items[:_MAX_CUES]:
            if not isinstance(item, dict):
                malformed = True
                continue
            try:
                start, end = float(item["from"]), float(item["to"])
            except (KeyError, TypeError, ValueError):
                malformed = True
                continue
            cues.append((start, end))
        return cues, malformed, not cues
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return [], False, not lines


def _parse_time(value: str) -> float | None:
    match = _SRT_TIME.match(value)
    if not match:
        return None
    return (int(match["h"]) * 3600 + int(match["m"]) * 60 + int(match["s"]) +
            int(match["ms"].ljust(3, "0")) / 1000)


def _check_cues(cues: list[tuple[float, float]], row: Mapping[str, object], reasons: set[str]) -> None:
    duration = row.get("duration_s")
    maximum = float(duration) if isinstance(duration, (int, float)) and duration >= 0 else None
    previous_start = -1.0
    previous_end = -1.0
    for start, end in cues:
        if start < 0 or end < 0 or end <= start:
            reasons.add("out_of_range")
        if start < previous_start:
            reasons.add("non_monotonic")
        if start < previous_end:
            reasons.add("overlap")
        if maximum is not None and end > maximum + 0.001:
            reasons.add("out_of_range")
        previous_start, previous_end = start, end


def _check_identity(path: Path, text: str, row: Mapping[str, object], reasons: set[str]) -> None:
    expected = _text_value(row, "work_id", "bvid")
    if not expected:
        return
    marker = None
    if path.suffix.lower() == ".md":
        match = re.search(r"^work_id:\s*[\"']?([^\"'\n]+)", text, re.MULTILINE)
        marker = match.group(1).strip() if match else None
    if marker and marker != expected and marker != str(row.get("bvid") or ""):
        reasons.add("identity_mismatch")
    if path.name and expected not in path.name and path.suffix.lower() in {".srt", ".json", ".txt"}:
        reasons.add("identity_mismatch")
