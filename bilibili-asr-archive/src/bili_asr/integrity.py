"""Deterministic, read-only archive integrity verification."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from .archive import archive_stem
from .manifest import ManifestStore
from .quality import QualityAnalyzer

# Stable public defect vocabulary.
MISSING_RAW_SUBTITLE = "missing_raw_subtitle"
MISSING_TRANSCRIPT = "missing_transcript"
MALFORMED_ARTIFACT = "malformed_artifact"
IDENTITY_PATH_MISMATCH = "identity_path_mismatch"
TRUNCATED_ATTEMPTS_LINE = "truncated_attempts_line"
RETRYABLE_INCOMPLETE = "retryable_incomplete"
STRUCTURAL_INPUT_ERROR = "structural_input_error"

_MAX_ROWS = 10000

@dataclass(frozen=True)
class IntegrityDefect:
    work_id: str
    code: str

    def to_dict(self) -> dict[str, object]:
        return {"work_id": self.work_id, "code": self.code}

@dataclass
class IntegrityReport:
    checked: int = 0
    defects: list[IntegrityDefect] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "checked": self.checked,
            "defect_count": len(self.defects),
            "defects": [d.to_dict() for d in self.defects],
            "diagnostics": list(self.diagnostics),
        }

class IntegrityVerifier:
    """Inspect manifest, attempts, and archive artifacts without writing."""

    def verify(self, archive_root: Path, *, scope: str | None = None) -> IntegrityReport:
        root = Path(archive_root).resolve()
        report = IntegrityReport()
        entries = self._read_manifest(root, report)
        selected = self._select(entries, scope)
        report.checked = len(selected)
        attempts = self._read_attempts(root, report)
        analyzer = QualityAnalyzer()
        for key, row in selected:
            work_id = str(row.get("work_id") or key)
            defects: set[str] = set()
            status = str(row.get("status") or "")
            if status in {"subtitle_done", "sub_checked"}:
                defects.add(MISSING_RAW_SUBTITLE)
            expected = self._required_paths(row, root)
            present = 0
            for path in expected:
                if not self._safe_path(path, root):
                    defects.add(IDENTITY_PATH_MISMATCH)
                elif path.is_file():
                    present += 1
            if status in {"archived", "asr_done", "subtitle_done"} and present == 0:
                defects.add(MISSING_TRANSCRIPT)
            quality = analyzer.analyze(row, root)
            if "malformed" in quality.reasons and any(
                path.suffix.lower() not in {".txt", ".md"} for path in expected
            ) and any(path.suffix.lower() == ".json" for path in expected):
                defects.add(MALFORMED_ARTIFACT)
            if "identity_mismatch" in quality.reasons:
                defects.add(IDENTITY_PATH_MISMATCH)
            if status in {"pending", "meta_ok", "sub_checked", "needs_audio", "audio_ok"}:
                defects.add(RETRYABLE_INCOMPLETE)
            for code in sorted(defects):
                report.defects.append(IntegrityDefect(work_id, code))
        if attempts[1]:
            report.diagnostics.append(TRUNCATED_ATTEMPTS_LINE)
        report.defects.sort(key=lambda d: (d.work_id, d.code))
        return report

    @staticmethod
    def _read_manifest(root: Path, report: IntegrityReport) -> dict[str, dict[str, Any]]:
        path = root / "manifest" / "manifest.jsonl"
        if not path.is_file():
            return {}
        entries: dict[str, dict[str, Any]] = {}
        try:
            with path.open(encoding="utf-8") as fh:
                for number, line in enumerate(fh):
                    if number >= _MAX_ROWS:
                        break
                    if not line.strip():
                        continue
                    value = json.loads(line)
                    if not isinstance(value, dict):
                        raise ValueError("manifest record is not an object")
                    key = str(value.get("work_id") or value.get("bvid") or "")
                    if not key:
                        raise ValueError("manifest record has no identity")
                    entries[key] = value
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            report.diagnostics.append(STRUCTURAL_INPUT_ERROR)
        return entries

    @staticmethod
    def _read_attempts(root: Path, report: IntegrityReport) -> tuple[list[dict[str, Any]], bool]:
        path = root / "coordinator" / "attempts.jsonl"
        if not path.is_file():
            return [], False
        records: list[dict[str, Any]] = []
        truncated = False
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            for index, line in enumerate(lines):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                    if not isinstance(value, dict):
                        raise ValueError
                    records.append(value)
                except (json.JSONDecodeError, ValueError):
                    if index == len(lines) - 1:
                        truncated = True
                    else:
                        report.diagnostics.append(STRUCTURAL_INPUT_ERROR)
                        return records, False
        except (OSError, UnicodeError):
            report.diagnostics.append(STRUCTURAL_INPUT_ERROR)
        return records, truncated

    @staticmethod
    def _select(entries: dict[str, dict[str, Any]], scope: str | None) -> list[tuple[str, dict[str, Any]]]:
        if not scope:
            return sorted(entries.items())
        tokens = {part for part in scope.replace(",", " ").split() if part}
        if "pending" in tokens:
            return sorted((k, v) for k, v in entries.items() if v.get("status") == "pending")
        if "failed" in tokens:
            return sorted((k, v) for k, v in entries.items() if v.get("status") not in {"archived", "gone"})
        return sorted((k, v) for k, v in entries.items() if k in tokens or str(v.get("bvid")) in tokens)

    @staticmethod
    def _required_paths(row: dict[str, Any], root: Path) -> list[Path]:
        values = [row.get(name) for name in ("srt_path", "txt_path", "md_path") if row.get(name)]
        if not values:
            stem = archive_stem(row)
            values = [f"transcripts/srt/{stem}.srt", f"transcripts/txt/{stem}.txt", f"transcripts/md/{stem}.md"]
        return [Path(value) if Path(value).is_absolute() else root / value for value in values]

    @staticmethod
    def _safe_path(path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root)
            return True
        except ValueError:
            return False
