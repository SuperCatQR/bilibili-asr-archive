"""Deterministic, read-only corpus coverage projection."""
from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "coverage-report-v1"
MAX_DIAGNOSTICS = 100
STATES = {"complete", "limited", "risk_interrupted", "incomplete", "unavailable"}
CSV_COLUMNS = (
    "schema_version", "scope", "denominator_unit", "denominator_count",
    "denominator_state", "denominator_source", "cumulative_unit",
    "cumulative_complete", "cumulative_total", "cumulative_state",
    "batch_unit", "batch_complete", "batch_total", "batch_state",
    "work_id", "category", "status", "artifact_present", "diagnostics",
)


@dataclass(frozen=True)
class CoverageReport:
    data: dict[str, Any]

    @classmethod
    def build(cls, archive_root: Path, *, scope: str | None = None) -> "CoverageReport":
        root = Path(archive_root)
        diagnostics: list[dict[str, str]] = []
        manifest_path = root / "manifest" / "manifest.jsonl"
        manifest: dict[str, dict[str, Any]] = {}
        denominator_valid = True
        if not manifest_path.is_file():
            diagnostics.append({"code": "denominator_unavailable", "detail": "manifest_snapshot_missing"})
            denominator_valid = False
        else:
            try:
                lines = manifest_path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeError):
                lines = []
                diagnostics.append({"code": "denominator_unavailable", "detail": "manifest_snapshot_unreadable"})
                denominator_valid = False
            for number, line in enumerate(lines, 1):
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except (TypeError, ValueError):
                    diagnostics.append({"code": "manifest_malformed", "detail": f"line_{number}"})
                    denominator_valid = False
                    continue
                if not isinstance(entry, dict):
                    diagnostics.append({"code": "manifest_invalid", "detail": f"line_{number}"})
                    denominator_valid = False
                    continue
                work_id = entry.get("work_id") or entry.get("bvid")
                if not isinstance(work_id, str) or not work_id:
                    diagnostics.append({"code": "manifest_invalid", "detail": f"line_{number}"})
                    denominator_valid = False
                    continue
                if work_id in manifest:
                    diagnostics.append({"code": "manifest_duplicate_work_id", "detail": work_id})
                    denominator_valid = False
                    continue
                manifest[work_id] = entry

        selected, scope_ok = _select(manifest, scope)
        if not scope_ok:
            diagnostics.append({"code": "scope_unavailable", "detail": "unknown_scope"})
            denominator_valid = False

        cursor, cursor_ok = _read_json(root / "meta-cursor.json", diagnostics, "meta_cursor")
        scheduler, scheduler_ok = _read_json(root / "scheduler.json", diagnostics, "scheduler")
        ledger, ledger_ok = _read_jsonl(root / "run-ledger.jsonl", diagnostics, "run_ledger")
        attempts, attempts_ok = _read_jsonl(root / "coordinator" / "attempts.jsonl", diagnostics, "attempts")
        del cursor, attempts
        if not cursor_ok or not scheduler_ok or not ledger_ok or not attempts_ok:
            diagnostics.append({"code": "evidence_unavailable", "detail": "sidecar"})

        batch_ids, batch_state = _batch_evidence(scheduler, ledger, diagnostics)
        rows: list[dict[str, Any]] = []
        for work_id, entry in sorted(selected.items()):
            status = str(entry.get("status") or "unknown")
            artifact = _artifact(root, entry)
            cumulative = status == "gone" or (status == "archived" and artifact)
            if status == "archived" and not artifact:
                diagnostics.append({"code": "terminal_missing_artifact", "detail": work_id})
            if work_id in batch_ids and status not in {"archived", "gone"}:
                diagnostics.append({"code": "batch_nonterminal", "detail": work_id})
            rows.append({
                "work_id": work_id,
                "category": _category(status),
                "status": status,
                "artifact_present": artifact,
                "cumulative_complete": cumulative,
                "batch_complete": work_id in batch_ids and cumulative,
            })

        diagnostics = sorted(diagnostics, key=lambda item: (item["code"], item["detail"]))[:MAX_DIAGNOSTICS]
        denominator_count = len(selected) if denominator_valid else None
        cumulative_complete = sum(bool(row["cumulative_complete"]) for row in rows)
        batch_complete = sum(bool(row["batch_complete"]) for row in rows)
        batch_total = len(batch_ids & set(selected))
        cumulative_state = "complete" if denominator_valid and not diagnostics and cumulative_complete == len(rows) else "incomplete"
        if not denominator_valid:
            cumulative_state = "unavailable"
        data = {
            "schema_version": SCHEMA_VERSION,
            "scope": scope,
            "denominator": {
                "unit": "work_items", "count": denominator_count,
                "state": "available" if denominator_valid else "unavailable",
                "source": "manifest_snapshot",
            },
            "cumulative": {
                "unit": "work_items", "complete": cumulative_complete,
                "total": len(rows), "state": cumulative_state,
            },
            "batch": {
                "unit": "work_items", "complete": batch_complete,
                "total": batch_total, "state": batch_state,
            },
            "rows": rows,
            "diagnostics": diagnostics,
        }
        return cls(data)

    def to_json(self) -> str:
        return json.dumps(self.data, ensure_ascii=False, sort_keys=False, separators=(",", ":"))

    def to_csv(self) -> str:
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        diagnostics = ",".join(item["code"] for item in self.data["diagnostics"])
        denominator = self.data["denominator"]
        cumulative = self.data["cumulative"]
        batch = self.data["batch"]
        for row in self.data["rows"]:
            writer.writerow({
                "schema_version": self.data["schema_version"], "scope": self.data["scope"] or "",
                "denominator_unit": denominator["unit"], "denominator_count": denominator["count"] if denominator["count"] is not None else "",
                "denominator_state": denominator["state"], "denominator_source": denominator["source"],
                "cumulative_unit": cumulative["unit"], "cumulative_complete": cumulative["complete"], "cumulative_total": cumulative["total"], "cumulative_state": cumulative["state"],
                "batch_unit": batch["unit"], "batch_complete": batch["complete"], "batch_total": batch["total"], "batch_state": batch["state"],
                "work_id": row["work_id"], "category": row["category"], "status": row["status"], "artifact_present": row["artifact_present"], "diagnostics": diagnostics,
            })
        return output.getvalue()


def _read_json(path: Path, diagnostics: list[dict[str, str]], name: str) -> tuple[dict[str, Any] | None, bool]:
    if not path.exists():
        return None, True
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, TypeError, ValueError):
        diagnostics.append({"code": "sidecar_malformed", "detail": name})
        return None, False
    if not isinstance(value, dict):
        diagnostics.append({"code": "sidecar_malformed", "detail": name})
        return None, False
    return value, True


def _read_jsonl(path: Path, diagnostics: list[dict[str, str]], name: str) -> tuple[list[dict[str, Any]], bool]:
    if not path.exists():
        return [], True
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        diagnostics.append({"code": "sidecar_malformed", "detail": name})
        return [], False
    records: list[dict[str, Any]] = []
    valid = True
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except (TypeError, ValueError):
            diagnostics.append({"code": "sidecar_malformed", "detail": f"{name}_line_{number}"})
            valid = False
            continue
        if not isinstance(value, dict):
            diagnostics.append({"code": "sidecar_malformed", "detail": f"{name}_line_{number}"})
            valid = False
            continue
        records.append(value)
    return records, valid


def _batch_evidence(scheduler: dict[str, Any] | None, ledger: list[dict[str, Any]], diagnostics: list[dict[str, str]]) -> tuple[set[str], str]:
    if scheduler is None:
        return set(), "unavailable"
    ids = scheduler.get("processed_work_ids")
    if not isinstance(ids, list) or any(not isinstance(item, str) for item in ids):
        diagnostics.append({"code": "scheduler_invalid_batch", "detail": "processed_work_ids"})
        return set(), "unavailable"
    batch_ids = set(ids)
    if ledger:
        latest = ledger[-1]
        ledger_ids = latest.get("work_ids")
        if isinstance(ledger_ids, list) and set(map(str, ledger_ids)) != batch_ids:
            diagnostics.append({"code": "sidecar_work_id_contradiction", "detail": "scheduler_run_ledger"})
    state = scheduler.get("state")
    if state not in STATES - {"incomplete", "unavailable"}:
        return batch_ids, "unavailable"
    return batch_ids, state


def _select(rows: dict[str, dict[str, Any]], scope: str | None) -> tuple[dict[str, dict[str, Any]], bool]:
    if scope is None:
        return rows, True
    tokens = [token for token in scope.replace(",", " ").split() if token]
    if not tokens:
        return {}, False
    if tokens == ["pending"]:
        return {key: value for key, value in rows.items() if value.get("status") not in {"archived", "gone"}}, True
    if tokens == ["failed"]:
        return {key: value for key, value in rows.items() if value.get("status") == "failed"}, True
    if all(token in rows or any(str(value.get("bvid")) == token for value in rows.values()) for token in tokens):
        selected: dict[str, dict[str, Any]] = {}
        for token in tokens:
            selected.update({key: value for key, value in rows.items() if key == token or str(value.get("bvid")) == token})
        return selected, True
    return {}, False


def _category(status: str) -> str:
    if status in {"archived", "subtitle_done", "asr_done"}:
        return "transcript"
    if status in {"needs_audio", "audio_ok"}:
        return "audio"
    if status == "gone":
        return "unavailable"
    return "metadata"


def _artifact(root: Path, entry: dict[str, Any]) -> bool:
    if entry.get("status") != "archived":
        return False
    try:
        from .archive import archive_stem
        stem = archive_stem(entry)
    except (KeyError, TypeError, ValueError):
        return False
    for relative in (entry.get("srt_path"), entry.get("txt_path"), entry.get("md_path")):
        if isinstance(relative, str) and (root / relative).is_file():
            return True
    return any((root / "transcripts" / directory / f"{stem}{suffix}").is_file() for directory, suffix in (("srt", ".srt"), ("txt", ".txt"), ("md", ".md")))
