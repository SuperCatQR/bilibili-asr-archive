"""Deterministic, read-only corpus coverage projection."""
from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

COLUMNS = ("work_id", "category", "status", "cumulative_complete", "batch_complete", "artifact_present")
MAX_ROWS = 10000
MAX_DIAGNOSTICS = 1000
TERMINAL = {"archived"}

@dataclass(frozen=True)
class CoverageReport:
    data: dict[str, Any]

    @classmethod
    def build(cls, archive_root: Path, *, scope: str | None = None) -> "CoverageReport":
        root = Path(archive_root)
        diagnostics: list[dict[str, str]] = []
        manifest = root / "manifest" / "manifest.jsonl"
        rows: dict[str, dict[str, Any]] = {}
        valid = True
        if not manifest.is_file():
            diagnostics.append({"code": "denominator_unavailable", "detail": "manifest_snapshot_missing"})
            valid = False
        else:
            try:
                lines = manifest.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeError):
                lines = []
                diagnostics.append({"code": "denominator_unavailable", "detail": "manifest_snapshot_unavailable"})
                valid = False
            for number, line in enumerate(lines, 1):
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except (ValueError, TypeError):
                    diagnostics.append({"code": "manifest_malformed", "detail": f"line_{number}"})
                    valid = False
                    continue
                if not isinstance(entry, dict):
                    diagnostics.append({"code": "manifest_invalid_row", "detail": f"line_{number}"})
                    valid = False
                    continue
                key = str(entry.get("work_id") or entry.get("bvid") or "")
                if not key:
                    diagnostics.append({"code": "manifest_invalid_row", "detail": f"line_{number}"})
                    valid = False
                    continue
                if key in rows:
                    diagnostics.append({"code": "manifest_duplicate_work_id", "detail": key})
                    valid = False
                    continue
                rows[key] = entry
        selected, scope_ok = _select(rows, scope)
        if not scope_ok:
            diagnostics.append({"code": "scope_unavailable", "detail": "unknown_scope"})
            valid = False
        batch_ids = _latest_batch_ids(root, diagnostics)
        report_rows: list[dict[str, Any]] = []
        for key, entry in sorted(selected.items()):
            status = str(entry.get("status") or "unknown")
            artifact = _artifact_present(root, key, entry)
            cumulative = status in TERMINAL and artifact
            batch = key in batch_ids and cumulative
            if status in TERMINAL and not artifact:
                diagnostics.append({"code": "terminal_missing_artifact", "detail": key})
            report_rows.append({"work_id": key, "category": _category(status), "status": status,
                                "cumulative_complete": cumulative, "batch_complete": batch,
                                "artifact_present": artifact})
        if not valid:
            denominator_count: int | None = None
            denominator_state = "unavailable"
        else:
            denominator_count = len(report_rows)
            denominator_state = "available"
        cumulative_complete = sum(bool(row["cumulative_complete"]) for row in report_rows)
        batch_complete = sum(bool(row["batch_complete"]) for row in report_rows)
        cumulative_state = "complete" if denominator_state == "available" and cumulative_complete == len(report_rows) else "incomplete"
        batch_state = _batch_state(root, diagnostics, batch_ids, batch_complete, len(batch_ids))
        diagnostics = sorted(diagnostics, key=lambda item: (item["code"], item["detail"]))[:MAX_DIAGNOSTICS]
        return cls({"schema": "coverage-report-v1", "scope": scope, "denominator":
                     {"unit": "work_items", "count": denominator_count, "source": "manifest_snapshot", "state": denominator_state},
                     "cumulative": {"unit": "work_items", "complete": cumulative_complete, "total": len(report_rows), "state": cumulative_state},
                     "batch": {"unit": "work_items", "complete": batch_complete, "total": len(batch_ids), "state": batch_state},
                     "rows": report_rows[:MAX_ROWS], "diagnostics": diagnostics})

    def to_json(self) -> str:
        return json.dumps(self.data, ensure_ascii=False, sort_keys=False, separators=(",", ":"))

    def to_csv(self) -> str:
        out = io.StringIO(newline="")
        writer = csv.DictWriter(out, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in self.data["rows"]:
            writer.writerow({column: row.get(column, "") for column in COLUMNS})
        return out.getvalue()

def _select(rows: dict[str, dict[str, Any]], scope: str | None) -> tuple[dict[str, dict[str, Any]], bool]:
    if not scope:
        return rows, True
    tokens = {token for token in scope.replace(",", " ").split() if token}
    if tokens & {"pending", "failed"}:
        wanted = {"pending", "meta_ok", "sub_checked", "needs_audio", "audio_ok"} if "pending" in tokens else {"failed"}
        return {key: value for key, value in rows.items() if value.get("status") in wanted}, True
    selected = {key: value for key, value in rows.items() if key in tokens or str(value.get("bvid")) in tokens}
    return selected, bool(selected)

def _category(status: str) -> str:
    if status == "subtitle_done":
        return "subtitle"
    if status in {"needs_audio", "audio_ok"}:
        return "audio"
    if status in {"asr_done", "archived"}:
        return "transcript"
    if status == "gone":
        return "unavailable"
    return "metadata"

def _artifact_present(root: Path, key: str, entry: dict[str, Any]) -> bool:
    # Projection-only: artifact readers intentionally never repair or migrate archives.
    if entry.get("status") != "archived":
        return False
    references = [entry.get("md_path"), entry.get("txt_path"), entry.get("srt_path")]
    for reference in references:
        if isinstance(reference, str) and (root / reference).is_file():
            return True
    for directory in ("md", "txt", "srt"):
        if (root / "transcripts" / directory / f"{key}.{directory}").is_file():
            return True
    return any((root / "transcripts" / directory / f"{key}{suffix}").is_file()
               for directory in ("md", "txt", "srt") for suffix in (".md", ".txt", ".srt"))

def _latest_batch_ids(root: Path, diagnostics: list[dict[str, str]]) -> set[str]:
    for filename in ("scheduler.json", "run-ledger.jsonl"):
        path = root / filename
        if not path.is_file():
            continue
        try:
            if filename.endswith(".json"):
                record = json.loads(path.read_text(encoding="utf-8"))
            else:
                lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
                record = json.loads(lines[-1]) if lines else {}
            ids = record.get("work_ids") or record.get("selected_work_ids") or record.get("batch_work_ids") or []
            if isinstance(ids, list):
                return {str(item) for item in ids if isinstance(item, (str, int))}
        except (OSError, UnicodeError, ValueError, TypeError):
            diagnostics.append({"code": "sidecar_malformed", "detail": filename})
    return set()

def _batch_state(root: Path, diagnostics: list[dict[str, str]], ids: set[str], complete: int, total: int) -> str:
    for filename in ("scheduler.json", "run-ledger.jsonl"):
        path = root / filename
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
            record = json.loads(text) if filename.endswith(".json") else json.loads([line for line in text.splitlines() if line.strip()][-1])
            state = str(record.get("state") or record.get("status") or "")
            if state in {"limited", "risk_interrupted"}:
                return state
            if state in {"complete", "completed"} and complete == total:
                return "complete"
        except (OSError, UnicodeError, ValueError, TypeError, IndexError):
            pass
    return "incomplete" if ids else "unavailable"
