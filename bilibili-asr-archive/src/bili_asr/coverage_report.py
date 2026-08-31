"""Deterministic, read-only corpus coverage projection."""
from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .archive import archive_stem, archive_bundle_complete
from .path_policy import confined_audio_path
from .manifest import VALID_STATUSES
from .meta_cursor import _validate as validate_cursor
from .scheduler import _validate as validate_scheduler
from .run_ledger import _validate_record as validate_run_ledger_record
from .sidecar_projection import ReaderPolicy, iter_jsonl_records, project_attempt_records, project_manifest_records

SCHEMA_VERSION = "coverage-report-v1"
TERMINAL_STATUSES = frozenset({"archived", "gone"})
RETRYABLE_OUTCOMES = frozenset({"failed", "skipped"})
ATTEMPT_STAGES = frozenset({"harvest", "download", "asr", "archive"})
ATTEMPT_OUTCOMES = frozenset({"ok", "failed", "skipped"})
CSV_COLUMNS = (
    "schema_version",
    "scope",
    "denominator_unit",
    "denominator_count",
    "denominator_state",
    "denominator_source",
    "cumulative_unit",
    "cumulative_complete",
    "cumulative_total",
    "cumulative_state",
    "batch_unit",
    "batch_complete",
    "batch_total",
    "batch_state",
    "work_id",
    "category",
    "status",
    "artifact_present",
    "reclaimed_audio",
    "evidence_summary",
    "diagnostic_summary",
)


@dataclass(frozen=True)
class CoverageReport:
    """A stable report assembled without changing archive evidence."""

    data: dict[str, Any]

    @classmethod
    def build(
        cls,
        archive_root: str | Path,
        *,
        scope: str | None = None,
        policy: ReaderPolicy | None = None,
    ) -> CoverageReport:
        root = Path(archive_root).resolve()
        diagnostics: set[tuple[str, str]] = set()
        manifest, manifest_state, manifest_diagnostics = project_manifest_records(
            root / "manifest" / "manifest.jsonl", policy=policy
        )
        diagnostics.update(
            (
                "sidecar_record_limit" if code.endswith("row_limit_exceeded") else
                "sidecar_byte_limit" if code.endswith("byte_limit_exceeded") else code,
                "manifest",
            )
            for code in manifest_diagnostics
        )
        if "manifest_duplicate_work_id" in manifest_diagnostics:
            manifest_state = "malformed"
        cursor, cursor_state = _read_validated_sidecar(
            root / "meta-cursor.json", "meta_cursor", validate_cursor, diagnostics
        )
        scheduler, scheduler_state = _read_validated_sidecar(
            root / "scheduler.json", "scheduler", validate_scheduler, diagnostics
        )
        run_ledger, ledger_state = _read_jsonl(root / "run-ledger.jsonl", "run_ledger", diagnostics, policy)
        attempts, attempts_state, attempt_diagnostics = project_attempt_records(
            root / "coordinator" / "attempts.jsonl", policy=policy
        )
        diagnostics.update(
            (
                "sidecar_record_limit" if code.endswith("row_limit_exceeded") else
                "sidecar_byte_limit" if code.endswith("byte_limit_exceeded") else code,
                "attempt",
            )
            for code in attempt_diagnostics
        )
        if "attempt_not_in_manifest" in {"attempt_not_in_manifest" if r.get("work_id") not in manifest else "" for r in attempts}:
            diagnostics.add(("attempt_not_in_manifest", "attempt"))

        selected, scope_state = _select_scope(manifest, attempts, scope)
        if scope_state == "unavailable":
            diagnostics.add(("unknown_scope", "scope"))

        scheduler_ids = _string_ids(
            scheduler, "processed_work_ids", "scheduler_invalid_processed_ids", diagnostics
        )
        latest_persisted_ledger = run_ledger[-1] if run_ledger else None
        latest_ledger = next(
            (record for record in reversed(run_ledger) if _valid_ledger(record)), None
        )
        if latest_persisted_ledger is not None and latest_ledger is not latest_persisted_ledger:
            diagnostics.add(("run_ledger_latest_invalid", "run_ledger"))
        if latest_ledger is not None:
            if latest_ledger.get("exit_code") != 0:
                diagnostics.add(("run_ledger_failed", "run_ledger"))
            if latest_ledger.get("command") != "schedule":
                diagnostics.add(("run_ledger_non_schedule", "run_ledger"))
        elif ledger_state != "missing":
            diagnostics.add(("run_ledger_latest_unavailable", "run_ledger"))
        ledger_ids = _string_ids(
            latest_ledger, "work_ids", "run_ledger_invalid_work_ids", diagnostics
        )
        if scheduler_ids and ledger_ids and scheduler_ids != ledger_ids:
            diagnostics.add(("scheduler_ledger_mismatch", "batch"))
        for work_id in sorted((scheduler_ids | ledger_ids) - set(manifest)):
            del work_id
            diagnostics.add(("stale_evidence", "sidecar"))

        batch_ids = (scheduler_ids | ledger_ids) & set(selected)
        if scheduler is None and latest_ledger is None:
            batch_state = "unavailable"
        else:
            batch_state = "incomplete"
        if scheduler is not None:
            scheduler_status = scheduler["state"]
            if scheduler_status in {"limited", "risk_interrupted"}:
                diagnostics.add(("scheduler_noncomplete", scheduler_status))
        if cursor is not None:
            cursor_status = cursor["state"]
            if cursor_status in {"limited", "risk_interrupted"}:
                diagnostics.add(("cursor_noncomplete", cursor_status))
        if scheduler is not None and cursor is not None:
            if scheduler["state"] != cursor["state"]:
                diagnostics.add(("scheduler_cursor_mismatch", "state"))

        if latest_ledger is not None and selected:
            expected = ledger_ids & set(selected)
            missing_batch = expected - batch_ids
            if missing_batch:
                diagnostics.add(("missing_batch_evidence", "batch"))

        rows: list[dict[str, Any]] = []
        retryable_ids = _retryable_ids(attempts)
        for work_id, entry in sorted(selected.items()):
            status = str(entry.get("status") or "unknown")
            artifact_present, reclaimed_audio = _transcript_evidence(root, entry)
            terminal = status == "gone" or (status == "archived" and artifact_present)
            if status == "archived" and not artifact_present:
                diagnostics.add(("terminal_missing_artifact", "transcript"))
            if work_id in retryable_ids:
                diagnostics.add(("retryable_attempt", "attempt"))
            rows.append(
                {
                    "work_id": work_id,
                    "category": _category(status),
                    "status": status,
                    "artifact_present": artifact_present,
                    "reclaimed_audio": reclaimed_audio,
                    "cumulative_complete": terminal,
                    "batch_complete": work_id in batch_ids and terminal,
                }
            )

        # A complete-looking manifest without operational evidence is not
        # proof of a completed campaign.
        if any(row["cumulative_complete"] for row in rows):
            for state, name in (
                (cursor_state, "cursor"),
                (scheduler_state, "scheduler"),
                (ledger_state, "run_ledger"),
                (attempts_state, "attempts"),
            ):
                if state != "available":
                    diagnostics.add(("evidence_missing", name))

        evidence = {
            "manifest": {"state": manifest_state},
            "cursor": {"state": cursor_state},
            "scheduler": {"state": scheduler_state},
            "run_ledger": {"state": ledger_state},
            "attempts": {"state": attempts_state},
        }
        denominator_available = manifest_state == "available" and scope_state == "available"
        cumulative_total = len(rows) if denominator_available else 0
        cumulative_complete = sum(row["cumulative_complete"] for row in rows)
        batch_total = len(batch_ids) if denominator_available else 0
        batch_complete = sum(row["batch_complete"] for row in rows)
        diagnostic_rows = _diagnostic_rows(diagnostics)
        has_defect = bool(diagnostic_rows)
        cumulative_state = "unavailable" if not denominator_available else "incomplete"
        if cumulative_complete == cumulative_total and not has_defect:
            cumulative_state = "complete"
        if not denominator_available:
            batch_state = "unavailable"
        elif batch_state != "unavailable":
            if batch_complete == batch_total and not has_defect and _batch_evidence_complete(
                scheduler, latest_ledger
            ):
                batch_state = "complete"
            else:
                batch_state = "incomplete"

        data = {
            "schema_version": SCHEMA_VERSION,
            "scope": scope,
            "denominator": {
                "unit": "work_items",
                "count": len(rows) if denominator_available else None,
                "state": "available" if denominator_available else "unavailable",
                "source": "manifest_snapshot",
            },
            "cumulative": {
                "unit": "work_items",
                "complete": cumulative_complete,
                "total": cumulative_total,
                "state": cumulative_state,
            },
            "batch": {
                "unit": "work_items",
                "complete": batch_complete,
                "total": batch_total,
                "state": batch_state,
            },
            "evidence": evidence,
            "rows": rows,
            "diagnostics": diagnostic_rows,
        }
        return cls(data)

    def to_json(self) -> str:
        """Return compact stable JSON with lexically sorted object keys."""
        return json.dumps(self.data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def to_csv(self) -> str:
        """Return a stable flat projection, including a summary row when empty."""
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        rows = self.data["rows"] or [{"work_id": "", "category": "summary", "status": ""}]
        for row in rows:
            writer.writerow(self._csv_row(row))
        return output.getvalue()

    def _csv_row(self, row: Mapping[str, Any]) -> dict[str, Any]:
        denominator = self.data["denominator"]
        cumulative = self.data["cumulative"]
        batch = self.data["batch"]
        return {
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
            "work_id": row.get("work_id", ""),
            "category": row.get("category", "summary"),
            "status": row.get("status", ""),
            "artifact_present": row.get("artifact_present", ""),
            "reclaimed_audio": row.get("reclaimed_audio", ""),
            "evidence_summary": _evidence_summary(self.data["evidence"]),
            "diagnostic_summary": _diagnostic_summary(self.data["diagnostics"]),
        }


def _read_manifest(
    root: Path, diagnostics: set[tuple[str, str]]
) -> tuple[dict[str, dict[str, Any]], str]:
    path = root / "manifest" / "manifest.jsonl"
    if not path.is_file():
        diagnostics.add(("denominator_unavailable", "manifest"))
        return {}, "missing"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        diagnostics.add(("denominator_unavailable", "manifest"))
        return {}, "malformed"
    entries: dict[str, dict[str, Any]] = {}
    valid = True
    for line in lines:
        try:
            record = json.loads(line)
        except (TypeError, ValueError):
            diagnostics.add(("manifest_malformed", "record"))
            valid = False
            continue
        work_id = record.get("work_id") if isinstance(record, dict) else None
        bvid = record.get("bvid") if isinstance(record, dict) else None
        status = record.get("status") if isinstance(record, dict) else None
        row_valid = isinstance(record, dict) and isinstance(work_id, str) and bool(work_id)
        row_valid = row_valid and isinstance(bvid, str) and bool(bvid)
        row_valid = row_valid and status in VALID_STATUSES
        if row_valid:
            try:
                parsed_bvid, _page = parse_work_id(work_id)
                row_valid = parsed_bvid == bvid
            except (TypeError, ValueError):
                row_valid = False
        if not row_valid:
            diagnostics.add(("manifest_invalid", "record"))
            valid = False
        elif work_id in entries:
            diagnostics.add(("manifest_duplicate_work_id", "record"))
            valid = False
        else:
            entries[work_id] = record
    return entries, "available" if valid else "malformed"


def _read_validated_sidecar(
    path: Path,
    name: str,
    validator: Any,
    diagnostics: set[tuple[str, str]],
) -> tuple[dict[str, Any] | None, str]:
    if not path.is_file():
        return None, "missing"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError
        # Read-only direct validation avoids store loaders that emit to stderr.
        return validator(raw), "available"
    except (OSError, TypeError, ValueError, json.JSONDecodeError, KeyError):
        diagnostics.add(("sidecar_malformed", name))
        return None, "malformed"


def _read_jsonl(
    path: Path, name: str, diagnostics: set[tuple[str, str]],
    policy: ReaderPolicy | None = None,
) -> tuple[list[dict[str, Any]], str]:
    records: list[dict[str, Any]] = []
    valid = True
    for item in iter_jsonl_records(path, policy=policy, name=name):
        if item.diagnostic:
            if item.diagnostic == f"{name}_record_limit":
                diagnostics.add(("sidecar_record_limit", name))
            elif item.diagnostic == f"{name}_byte_limit":
                diagnostics.add(("sidecar_byte_limit", name))
            else:
                diagnostics.add(("sidecar_malformed", name))
            valid = False
        elif item.value is not None:
            records.append(item.value)
    return records, "available" if valid else "malformed"


def _valid_ledger(record: Mapping[str, Any]) -> bool:
    try:
        validate_run_ledger_record(dict(record))
    except (TypeError, ValueError, KeyError):
        return False
    work_ids = record.get("work_ids")
    return isinstance(work_ids, list) and all(
        isinstance(value, str) and bool(value) for value in work_ids
    )


def _string_ids(
    record: Mapping[str, Any] | None,
    key: str,
    code: str,
    diagnostics: set[tuple[str, str]],
) -> set[str]:
    if record is None or record.get(key) is None:
        return set()
    values = record.get(key)
    if not isinstance(values, list) or any(not isinstance(value, str) or not value for value in values):
        diagnostics.add((code, "sidecar"))
        return set()
    return set(values)


def _select_scope(
    entries: dict[str, dict[str, Any]], attempts: list[dict[str, Any]], scope: str | None
) -> tuple[dict[str, dict[str, Any]], str]:
    if scope is None:
        return entries, "available"
    if scope == "pending":
        return {
            work_id: entry
            for work_id, entry in entries.items()
            if entry.get("status") not in TERMINAL_STATUSES
        }, "available"
    if scope == "failed":
        failed = {
            record.get("work_id")
            for record in attempts
            if record.get("outcome") == "failed" and isinstance(record.get("work_id"), str)
        }
        return {work_id: entry for work_id, entry in entries.items() if work_id in failed}, "available"
    selected: dict[str, dict[str, Any]] = {}
    tokens = scope.replace(",", " ").split()
    if not tokens:
        return {}, "unavailable"
    for token in tokens:
        matches = {
            work_id: entry
            for work_id, entry in entries.items()
            if work_id == token or entry.get("bvid") == token
        }
        if not matches:
            return {}, "unavailable"
        selected.update(matches)
    return selected, "available"


def _retryable_ids(attempts: list[dict[str, Any]]) -> set[str]:
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for record in attempts:
        work_id = record.get("work_id")
        stage = record.get("stage")
        number = record.get("attempt")
        if isinstance(work_id, str) and isinstance(stage, str) and isinstance(number, int):
            key = (work_id, stage)
            if number >= latest.get(key, {}).get("attempt", 0):
                latest[key] = record
    return {
        work_id
        for (work_id, _stage), record in latest.items()
        if record.get("outcome") in RETRYABLE_OUTCOMES
    }


def _transcript_evidence(root: Path, entry: Mapping[str, Any]) -> tuple[bool, bool]:
    paths: list[Path] = []
    for key in ("srt_path", "txt_path", "md_path"):
        value = entry.get(key)
        if isinstance(value, str):
            candidate = _contained_path(root, value)
            if candidate is not None:
                paths.append(candidate)
    try:
        stem = archive_stem(dict(entry))
    except (KeyError, TypeError, ValueError):
        stem = ""
    if stem:
        paths.extend(root / "transcripts" / kind / f"{stem}.{kind}" for kind in ("srt", "txt"))
        md_dir = root / "transcripts" / "md"
        exact_md = md_dir / f"{stem}.md"
        paths.append(exact_md)
        pubdate = str(entry.get("pubdate_str") or "")
        if pubdate and md_dir.is_dir():
            matches = sorted(md_dir.glob(f"{pubdate}_{stem}_*.md"))
            if len(matches) == 1:
                paths.append(matches[0])
    bundle_paths = {}
    for key in ("srt_path", "txt_path", "md_path", "raw_path"):
        value = entry.get(key)
        if not isinstance(value, str):
            return False, False
        candidate = _contained_path(root, value)
        if candidate is None:
            return False, False
        bundle_paths[key] = value
    transcript = archive_bundle_complete(root, bundle_paths)
    if not transcript or entry.get("status") != "archived":
        return transcript, False
    audio_value = entry.get("audio_path")
    audio_missing = False
    if isinstance(audio_value, str):
        audio = confined_audio_path(root, audio_value, require_exists=True)
        audio_missing = audio is None
    elif stem:
        audio_missing = all(confined_audio_path(root, f"audio/{stem}{suffix}", require_exists=True) is None
                            for suffix in (".m4a", ".flac"))
    return transcript, audio_missing


def _contained_path(root: Path, relative: str) -> Path | None:
    candidate = (root / relative).resolve()
    root_real = root.resolve()
    try:
        candidate.relative_to(root_real)
    except ValueError:
        return None
    return candidate


def _batch_evidence_complete(
    scheduler: Mapping[str, Any] | None, ledger: Mapping[str, Any] | None
) -> bool:
    return bool(
        scheduler
        and ledger
        and scheduler.get("state") == "complete"
        and scheduler.get("processed_work_ids") == ledger.get("work_ids")
    )


def _category(status: str) -> str:
    if status in {"archived", "subtitle_done", "asr_done"}:
        return "transcript"
    if status in {"needs_audio", "audio_ok"}:
        return "audio"
    if status == "gone":
        return "unavailable"
    return "metadata"


def _diagnostic_rows(diagnostics: set[tuple[str, str]]) -> list[dict[str, str]]:
    return [
        {"code": code, "category": category}
        for code, category in sorted(diagnostics)
    ]


def _evidence_summary(evidence: Mapping[str, Mapping[str, str]]) -> str:
    return ";".join(f"{name}:{evidence[name]['state']}" for name in sorted(evidence))


def _diagnostic_summary(diagnostics: list[Mapping[str, str]]) -> str:
    return ";".join(f"{item['code']}:{item['category']}" for item in diagnostics)
