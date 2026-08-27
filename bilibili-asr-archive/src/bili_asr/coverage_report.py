"""Deterministic, read-only corpus coverage projection."""
from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

COLUMNS = ("work_id", "category", "status", "cumulative_complete", "batch_complete", "artifact_present")
_COMPLETE = {"archived"}

@dataclass(frozen=True)
class CoverageReport:
    data: dict[str, Any]

    @classmethod
    def build(cls, archive_root: Path, *, scope: str | None = None) -> "CoverageReport":
        root = Path(archive_root)
        diagnostics: list[dict[str, str]] = []
        path = root / "manifest" / "manifest.jsonl"
        rows: dict[str, dict[str, Any]] = {}
        if not path.is_file():
            diagnostics.append({"code": "denominator_unavailable", "detail": "manifest_snapshot_missing"})
        else:
            try:
                for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                    if not line.strip(): continue
                    try: entry = json.loads(line)
                    except (ValueError, TypeError):
                        diagnostics.append({"code": "manifest_malformed", "detail": f"line_{number}"}); continue
                    key = str(entry.get("work_id") or entry.get("bvid") or "")
                    if not key:
                        diagnostics.append({"code": "manifest_invalid_row", "detail": f"line_{number}"}); continue
                    if key in rows: diagnostics.append({"code": "manifest_duplicate_work_id", "detail": key})
                    rows[key] = entry
            except (OSError, UnicodeError):
                diagnostics.append({"code": "manifest_snapshot_unavailable", "detail": "read_failed"})
        selected = _select(rows, scope)
        report_rows = []
        for key, entry in sorted(selected.items()):
            status = str(entry.get("status") or "unknown")
            artifact = _artifact_present(root, key, entry)
            report_rows.append({"work_id": key, "category": _category(status), "status": status,
                                "cumulative_complete": status in _COMPLETE and artifact,
                                "batch_complete": status in _COMPLETE and artifact,
                                "artifact_present": artifact})
            if status == "archived" and not artifact:
                diagnostics.append({"code": "terminal_missing_artifact", "detail": key})
        cumulative_complete = sum(r["cumulative_complete"] for r in report_rows)
        batch_complete = sum(r["batch_complete"] for r in report_rows)
        return cls({"schema": "coverage-report-v1", "scope": scope, "denominator": {"unit": "work_items", "count": len(report_rows), "source": "manifest_snapshot"},
                     "cumulative": {"unit": "work_items", "complete": cumulative_complete, "total": len(report_rows)},
                     "batch": {"unit": "work_items", "complete": batch_complete, "total": len(report_rows)},
                     "rows": report_rows, "diagnostics": sorted(diagnostics, key=lambda d: (d["code"], d["detail"]))})

    def to_json(self) -> str:
        return json.dumps(self.data, ensure_ascii=False, sort_keys=False, separators=(",", ":"))

    def to_csv(self) -> str:
        out = io.StringIO(newline="")
        writer = csv.DictWriter(out, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in self.data["rows"]:
            writer.writerow(row)
        return out.getvalue()

def _select(rows: dict[str, dict[str, Any]], scope: str | None) -> dict[str, dict[str, Any]]:
    if not scope: return rows
    tokens = {x for x in scope.replace(",", " ").split() if x}
    if tokens & {"pending", "failed"}:
        wanted = {"pending", "meta_ok", "sub_checked", "needs_audio", "audio_ok"} if "pending" in tokens else {"failed"}
        return {k: v for k, v in rows.items() if v.get("status") in wanted}
    return {k: v for k, v in rows.items() if k in tokens or str(v.get("bvid")) in tokens}

def _category(status: str) -> str:
    if status in {"subtitle_done"}: return "subtitle"
    if status in {"needs_audio", "audio_ok"}: return "audio"
    if status in {"asr_done", "archived"}: return "transcript"
    if status == "gone": return "unavailable"
    return "metadata"

def _artifact_present(root: Path, key: str, entry: dict[str, Any]) -> bool:
    if entry.get("status") != "archived": return False
    for suffix in (".md", ".txt", ".srt"):
        if any(p.is_file() for p in (root / "transcripts" / "md", root / "transcripts" / "txt", root / "transcripts" / "srt") for _ in [0] if (p / f"{key}{suffix}").is_file()): return True
    return False
