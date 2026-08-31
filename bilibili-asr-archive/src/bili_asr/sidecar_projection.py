"""Shared, read-only streaming projections for archive sidecars."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterator, Literal, Mapping

from .coordinator import _validate_attempt
from .manifest import VALID_STATUSES
from .page_identity import parse_work_id


@dataclass(frozen=True)
class ReaderPolicy:
    """Reader limits for explicitly bounded input or trusted local archives."""

    mode: Literal["bounded_input", "trusted_archive"] = "bounded_input"
    max_records: int | None = 10_000
    max_bytes: int | None = 8 * 1024 * 1024
    max_line_bytes: int = 16 * 1024 * 1024
    max_object_bytes: int = 16 * 1024 * 1024
    tolerate_truncated_final: bool = True

    def __post_init__(self) -> None:
        if self.mode not in {"bounded_input", "trusted_archive"}:
            raise ValueError("mode must be bounded_input or trusted_archive")
        if self.mode == "trusted_archive":
            object.__setattr__(self, "max_records", None)
            object.__setattr__(self, "max_bytes", None)
        for value in (self.max_records, self.max_bytes, self.max_line_bytes, self.max_object_bytes):
            if value is not None and value < 1:
                raise ValueError("reader limits must be positive")
        if self.mode == "trusted_archive":
            if self.max_records is not None or self.max_bytes is not None:
                raise ValueError("trusted_archive cannot use total record or byte limits")

    @property
    def trusted(self) -> bool:
        return self.mode == "trusted_archive"


@dataclass(frozen=True)
class JsonlRecord:
    line: int
    value: dict[str, Any] | None
    diagnostic: str | None


def iter_jsonl_records(
    path: str | Path,
    *,
    policy: ReaderPolicy | None = None,
    name: str = "sidecar",
) -> Iterator[JsonlRecord]:
    """Stream safe JSON objects and classify malformed middle/final lines."""
    policy = policy or ReaderPolicy()
    source = Path(path)
    try:
        if source.is_symlink() or not source.is_file():
            yield JsonlRecord(0, None, "symlink" if source.is_symlink() else "missing")
            return
        if policy.max_bytes is not None and source.stat().st_size > policy.max_bytes:
            yield JsonlRecord(0, None, f"{name}_byte_limit")
            return
        with source.open("rb") as handle:
            pending: tuple[int, bytes] | None = None
            record_count = 0
            physical_line = 0
            while True:
                raw = handle.readline(policy.max_line_bytes + 1)
                if not raw:
                    if pending is not None:
                        yield _decode_jsonl_record(*pending, final=True, policy=policy)
                    break
                physical_line += 1
                line = physical_line
                if len(raw) > policy.max_line_bytes and not raw.endswith(b"\n"):
                    yield JsonlRecord(line, None, "line_limit")
                    return
                if not raw.strip():
                    continue
                record_count += 1
                if policy.max_records is not None and record_count > policy.max_records:
                    yield JsonlRecord(line, None, f"{name}_record_limit")
                    return
                if pending is not None:
                    yield _decode_jsonl_record(*pending, final=False, policy=policy)
                pending = (line, raw)
    except OSError:
        yield JsonlRecord(0, None, "malformed")


def _decode_jsonl_record(
    line: int, raw: bytes, *, final: bool, policy: ReaderPolicy,
) -> JsonlRecord:
    try:
        if len(raw) > policy.max_object_bytes:
            raise ValueError
        text = raw.decode("utf-8")
        value = json.loads(text)
        if not isinstance(value, dict):
            raise ValueError
    except UnicodeError:
        return JsonlRecord(line, None, "invalid_utf8")
    except (ValueError, json.JSONDecodeError):
        return JsonlRecord(
            line,
            None,
            "truncated_final" if final and policy.tolerate_truncated_final else "malformed_middle",
        )
    return JsonlRecord(line, value, None)




def _valid_manifest(record: Mapping[str, Any]) -> bool:
    work_id, status = record.get("work_id"), record.get("status")
    return isinstance(work_id, str) and bool(work_id) and status is not None and bool(str(status))


def _manifest_semantic_diagnostics(record: Mapping[str, Any]) -> set[str]:
    diagnostics: set[str] = set()
    if "status" in record and record.get("status") not in VALID_STATUSES:
        diagnostics.add("manifest_invalid_status")
    if "bvid" in record:
        bvid = record.get("bvid")
        work_id = record.get("work_id")
        if not isinstance(bvid, str) or not bvid:
            diagnostics.add("manifest_invalid_bvid")
        else:
            try:
                parsed, _ = parse_work_id(str(work_id))
            except (TypeError, ValueError):
                diagnostics.add("manifest_invalid_bvid")
            else:
                if parsed != bvid:
                    diagnostics.add("manifest_invalid_bvid")
    return diagnostics


def project_manifest_records(
    path: str | Path, *, policy: ReaderPolicy | None = None,
) -> tuple[dict[str, dict[str, Any]], str, set[str]]:
    """Project latest valid manifest rows and retain semantic diagnostics."""
    entries: dict[str, dict[str, Any]] = {}
    diagnostics: set[str] = set()
    state = "available"
    for item in iter_jsonl_records(path, policy=policy, name="manifest"):
        if item.diagnostic:
            state = "malformed"
            diagnostics.add({
                "manifest_record_limit": "manifest_row_limit_exceeded",
                "manifest_byte_limit": "manifest_byte_limit_exceeded",
                "symlink": "manifest_malformed",
                "missing": "manifest_malformed",
                "malformed_middle": "manifest_malformed",
                "truncated_final": "manifest_malformed",
                "invalid_utf8": "manifest_malformed",
                "line_limit": "manifest_malformed",
                "malformed": "manifest_malformed",
            }.get(item.diagnostic, "manifest_malformed"))
            continue
        assert item.value is not None
        if not _valid_manifest(item.value):
            state = "malformed"
            diagnostics.add("manifest_invalid")
            continue
        diagnostics.update(_manifest_semantic_diagnostics(item.value))
        key = item.value["work_id"]
        if key in entries:
            diagnostics.add("manifest_duplicate_work_id")
        entries[key] = item.value
    if not Path(path).exists():
        state = "missing"
    elif Path(path).is_symlink():
        state = "malformed"
    return entries, state, diagnostics


def project_attempt_records(
    path: str | Path, *, policy: ReaderPolicy | None = None,
) -> tuple[list[dict[str, Any]], str, set[str]]:
    """Project latest valid attempt for each ``(work_id, stage)`` key."""
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    diagnostics: set[str] = set()
    state = "available"
    for item in iter_jsonl_records(path, policy=policy, name="attempts"):
        if item.diagnostic:
            if item.diagnostic == "truncated_final":
                diagnostics.add("truncated_attempts_line")
                continue
            state = "malformed"
            if item.diagnostic == "attempts_record_limit":
                diagnostics.add("attempts_row_limit_exceeded")
            elif item.diagnostic == "attempts_byte_limit":
                diagnostics.add("attempts_byte_limit_exceeded")
            else:
                diagnostics.add("structural_input_error")
            continue
        assert item.value is not None
        try:
            valid = _validate_attempt(item.value)
        except (TypeError, ValueError, KeyError):
            state = "malformed"
            diagnostics.add("structural_input_error")
            continue
        key = (valid["work_id"], valid["stage"])
        prior = latest.get(key)
        if prior is not None and valid["attempt"] == prior["attempt"]:
            diagnostics.add("duplicate_attempt")
        if prior is None or valid["attempt"] > prior["attempt"]:
            latest[key] = valid
    if not Path(path).exists():
        state = "missing"
    elif Path(path).is_symlink():
        state = "malformed"
    return list(latest.values()), state, diagnostics
