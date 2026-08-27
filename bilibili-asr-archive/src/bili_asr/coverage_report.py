"""Deterministic, read-only corpus coverage projection."""
from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "coverage-report-v1"
STATES = {"complete", "limited", "risk_interrupted", "incomplete", "unavailable"}
CSV_COLUMNS = (
    "schema_version", "scope", "denominator_unit", "denominator_count",
    "denominator_state", "denominator_source", "cumulative_unit",
    "cumulative_complete", "cumulative_total", "cumulative_state", "batch_unit",
    "batch_complete", "batch_total", "batch_state", "work_id", "category",
    "status", "artifact_present", "reclaimed_audio", "diagnostics",
)
MAX_DIAGNOSTICS = 100


@dataclass(frozen=True)
class CoverageReport:
    data: dict[str, Any]

    @classmethod
    def build(cls, archive_root: Path, *, scope: str | None = None) -> CoverageReport:
        root = Path(archive_root)
        diagnostics: list[dict[str, str]] = []
        manifest, manifest_ok = _manifest(root / "manifest" / "manifest.jsonl", diagnostics)
        attempts, attempts_ok = _attempts(root / "coordinator" / "attempts.jsonl", diagnostics)
        selected, scope_ok = _select(manifest, scope, attempts)
        if not scope_ok:
            diagnostics.append({"code": "scope_unavailable", "detail": "unknown_scope"})
        cursor, cursor_ok = _sidecar(root / "meta-cursor.json", diagnostics, "meta_cursor")
        scheduler, scheduler_ok = _sidecar(root / "scheduler.json", diagnostics, "scheduler")
        ledger, ledger_ok = _jsonl(root / "run-ledger.jsonl", diagnostics, "run_ledger")
        if not cursor_ok or not scheduler_ok or not ledger_ok or not attempts_ok:
            diagnostics.append({"code": "evidence_unavailable", "detail": "sidecar"})

        selected_ids = set(selected)
        scheduler_ids = _ids(scheduler, "processed_work_ids", diagnostics, "scheduler_invalid_batch")
        latest = ledger[-1] if ledger else {}
        ledger_ids = _ids(latest, "work_ids", diagnostics, "ledger_invalid_work_ids")
        if scheduler_ids != ledger_ids and (scheduler_ids or ledger_ids):
            diagnostics.append({"code": "sidecar_work_id_contradiction", "detail": "scheduler_run_ledger"})
        batch_ids = scheduler_ids & selected_ids
        if scheduler_ids - selected_ids:
            diagnostics.append({"code": "batch_outside_scope", "detail": "scheduler"})
        if cursor:
            if cursor.get("state") not in {"complete", "limited", "risk_interrupted"}:
                diagnostics.append({"code": "cursor_invalid_state", "detail": "meta_cursor"})
            if cursor.get("total") is not None and not isinstance(cursor.get("total"), int):
                diagnostics.append({"code": "cursor_invalid_total", "detail": "meta_cursor"})
            if cursor.get("next_page", 1) < 1:
                diagnostics.append({"code": "cursor_invalid_page", "detail": "meta_cursor"})
        if scheduler and scheduler.get("state") not in STATES:
            diagnostics.append({"code": "scheduler_invalid_state", "detail": "scheduler"})
        if scheduler and scheduler.get("state") in {"limited", "risk_interrupted"}:
            diagnostics.append({"code": "scheduler_limited", "detail": "state"})
        if cursor and cursor.get("state") in {"limited", "risk_interrupted"}:
            diagnostics.append({"code": "cursor_limited", "detail": "state"})

        rows: list[dict[str, Any]] = []
        for work_id, entry in sorted(selected.items()):
            status = str(entry.get("status") or "unknown")
            artifact, reclaimed = _artifact(root, entry)
            terminal = status == "gone" or (status == "archived" and artifact)
            if status == "archived" and not artifact:
                diagnostics.append({"code": "terminal_missing_artifact", "detail": "work_item"})
            relevant = [a for a in attempts if str(a.get("work_id")) == work_id]
            if len(relevant) > 1:
                diagnostics.append({"code": "duplicate_attempts", "detail": "work_item"})
            if relevant and any(a.get("outcome") in {"failed", "error", "retryable", "nonterminal"} for a in relevant):
                diagnostics.append({"code": "retryable_attempt", "detail": "work_item"})
            if relevant and any(a.get("stage") not in {"metadata", "subtitle", "audio", "asr", "archive", None} for a in relevant):
                diagnostics.append({"code": "attempt_invalid_stage", "detail": "work_item"})
            if relevant and work_id not in scheduler_ids:
                diagnostics.append({"code": "attempt_not_in_batch", "detail": "work_item"})
            rows.append({"work_id": work_id, "category": _category(status), "status": status,
                         "artifact_present": artifact, "reclaimed_audio": reclaimed,
                         "cumulative_complete": terminal, "batch_complete": work_id in batch_ids and terminal})

        denom_ok = manifest_ok and scope_ok
        cumulative_complete = sum(r["cumulative_complete"] for r in rows)
        batch_complete = sum(r["batch_complete"] for r in rows)
        clean = not diagnostics
        cumulative_state = "unavailable" if not denom_ok else ("complete" if cumulative_complete == len(rows) and clean else "incomplete")
        batch_state = scheduler.get("state") if scheduler else "unavailable"
        if batch_state not in STATES or not clean or batch_complete != len(batch_ids):
            batch_state = "incomplete" if denom_ok else "unavailable"
        data = {
            "schema_version": SCHEMA_VERSION, "scope": scope,
            "denominator": {"unit": "work_items", "count": len(rows) if denom_ok else None,
                            "state": "available" if denom_ok else "unavailable", "source": "manifest_snapshot"},
            "cumulative": {"unit": "work_items", "complete": cumulative_complete, "total": len(rows), "state": cumulative_state},
            "batch": {"unit": "work_items", "complete": batch_complete, "total": len(batch_ids), "state": batch_state},
            "evidence": {"manifest": {"state": "available" if manifest_ok else "malformed"},
                         "cursor": {"state": "available" if cursor_ok and cursor else "missing"},
                         "scheduler": {"state": "available" if scheduler_ok and scheduler else "missing"},
                         "run_ledger": {"state": "available" if ledger_ok and ledger else "missing"},
                         "attempts": {"state": "available" if attempts_ok and attempts else "missing"}},
            "rows": rows,
            "diagnostics": sorted(diagnostics, key=lambda x: (x["code"], x["detail"]))[:MAX_DIAGNOSTICS],
        }
        return cls(data)

    def to_json(self) -> str:
        return json.dumps(self.data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def to_csv(self) -> str:
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        diagnostic_codes = ",".join(item["code"] for item in self.data["diagnostics"])
        for row in self.data["rows"]:
            denominator = self.data["denominator"]
            cumulative = self.data["cumulative"]
            batch = self.data["batch"]
            values = {
                "schema_version": self.data["schema_version"],
                "scope": self.data["scope"] or "",
                "denominator_unit": denominator["unit"],
                "denominator_count": denominator["count"] if denominator["count"] is not None else "",
                "denominator_state": denominator["state"],
                "denominator_source": denominator["source"],
                "cumulative_unit": cumulative["unit"],
                "cumulative_complete": cumulative["complete"],
                "cumulative_total": cumulative["total"],
                "cumulative_state": cumulative["state"],
                "batch_unit": batch["unit"],
                "batch_complete": batch["complete"],
                "batch_total": batch["total"],
                "batch_state": batch["state"],
                "work_id": row["work_id"],
                "category": row["category"],
                "status": row["status"],
                "artifact_present": row["artifact_present"],
                "reclaimed_audio": row["reclaimed_audio"],
                "diagnostics": diagnostic_codes,
            }
            writer.writerow(values)
        return output.getvalue()


def _manifest(path: Path, diagnostics: list[dict[str, str]]) -> tuple[dict[str, dict[str, Any]], bool]:
    if not path.is_file():
        diagnostics.append({"code": "denominator_unavailable", "detail": "manifest_snapshot_missing"})
        return {}, False
    result: dict[str, dict[str, Any]] = {}
    valid = True
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        diagnostics.append({"code": "denominator_unavailable", "detail": "manifest_snapshot_unreadable"})
        return {}, False
    for number, line in enumerate(lines, 1):
        try:
            value = json.loads(line)
        except (ValueError, TypeError):
            diagnostics.append({"code": "manifest_malformed", "detail": f"line_{number}"})
            valid = False
            continue
        work_id = value.get("work_id") if isinstance(value, dict) else None
        if not isinstance(work_id, str) or not work_id or work_id in result:
            diagnostics.append({"code": "manifest_duplicate_work_id" if work_id in result else "manifest_invalid", "detail": f"line_{number}"})
            valid = False
            continue
        result[work_id] = value
    return result, valid


def _sidecar(path: Path, diagnostics: list[dict[str, str]], name: str) -> tuple[dict[str, Any] | None, bool]:
    if not path.exists():
        return None, True
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError):
        diagnostics.append({"code": "sidecar_malformed", "detail": name})
        return None, False
    if not isinstance(value, dict):
        diagnostics.append({"code": "sidecar_malformed", "detail": name})
        return None, False
    return value, True


def _jsonl(path: Path, diagnostics: list[dict[str, str]], name: str) -> tuple[list[dict[str, Any]], bool]:
    if not path.exists():
        return [], True
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        diagnostics.append({"code": "sidecar_malformed", "detail": name})
        return [], False
    result: list[dict[str, Any]] = []
    valid = True
    for number, line in enumerate(lines, 1):
        try:
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError
            result.append(value)
        except (ValueError, TypeError):
            diagnostics.append({"code": "sidecar_malformed", "detail": f"{name}_line_{number}"})
            valid = False
    return result, valid


def _attempts(path: Path, diagnostics: list[dict[str, str]]) -> tuple[list[dict[str, Any]], bool]:
    return _jsonl(path, diagnostics, "attempts")


def _ids(value: dict[str, Any] | None, key: str, diagnostics: list[dict[str, str]], code: str) -> set[str]:
    items = value.get(key) if value else None
    if items is None:
        return set()
    if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
        diagnostics.append({"code": code, "detail": key})
        return set()
    return set(items)


def _select(rows: dict[str, dict[str, Any]], scope: str | None, attempts: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], bool]:
    if scope is None:
        return rows, True
    if scope == "pending":
        return {key: value for key, value in rows.items() if value.get("status") not in {"archived", "gone"}}, True
    if scope == "failed":
        failed = {str(item.get("work_id")) for item in attempts if item.get("outcome") in {"failed", "error"}}
        return {key: value for key, value in rows.items() if key in failed}, True
    selected: dict[str, dict[str, Any]] = {}
    for token in scope.replace(",", " ").split():
        matches = {key: value for key, value in rows.items() if key == token or str(value.get("bvid")) == token}
        if not matches:
            return {}, False
        selected.update(matches)
    return selected, True


def _category(status: str) -> str:
    if status in {"archived", "subtitle_done", "asr_done"}:
        return "transcript"
    if status in {"needs_audio", "audio_ok"}:
        return "audio"
    if status == "gone":
        return "unavailable"
    return "metadata"


def _artifact(root: Path, entry: dict[str, Any]) -> tuple[bool, bool]:
    transcript = any(isinstance(path, str) and (root / path).is_file() for path in (entry.get("srt_path"), entry.get("txt_path"), entry.get("md_path")))
    if not transcript or entry.get("status") != "archived":
        return transcript, False
    audio = entry.get("audio_path")
    reclaimed = isinstance(audio, str) and not (root / audio).is_file()
    return transcript, reclaimed
