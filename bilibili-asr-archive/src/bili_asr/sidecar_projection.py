"""Shared, read-only streaming projections for archive sidecars."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterator, Mapping

from .coordinator import _validate_attempt
from .manifest import VALID_STATUSES
from .page_identity import parse_work_id


@dataclass(frozen=True)
class ReaderPolicy:
    """Reader limits for explicitly bounded input or trusted local archives."""

    mode: str = "bounded_input"
    max_records: int | None = 10_000
    max_bytes: int | None = 8 * 1024 * 1024
    max_line_bytes: int = 16 * 1024 * 1024
    max_object_bytes: int = 16 * 1024 * 1024
    tolerate_truncated_final: bool = True

    def __post_init__(self) -> None:
        if self.mode not in {"bounded_input", "trusted_archive"}:
            raise ValueError("mode must be bounded_input or trusted_archive")
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
            seen = 0
            while True:
                raw = handle.readline(policy.max_line_bytes + 1)
                if not raw:
                    break
                line = seen + 1
                if len(raw) > policy.max_line_bytes and not raw.endswith(b"\n"):
                    yield JsonlRecord(line, None, "line_limit")
                    return
                seen = line
                if policy.max_records is not None and line > policy.max_records:
                    yield JsonlRecord(line, None, f"{name}_record_limit")
                    return
                if not raw.strip():
                    continue
                final = not raw.endswith(b"\n")
                try:
                    if len(raw) > policy.max_object_bytes:
                        raise ValueError
                    value = json.loads(raw.decode("utf-8"))
                    if not isinstance(value, dict):
                        raise ValueError
                except (UnicodeError, ValueError, json.JSONDecodeError):
                    if final and policy.tolerate_truncated_final:
                        yield JsonlRecord(line, None, "truncated_final")
                    else:
                        yield JsonlRecord(line, None, "malformed_middle")
                    continue
                yield JsonlRecord(line, value, None)
    except OSError:
        yield JsonlRecord(0, None, "malformed")


def _valid_manifest(record: Mapping[str, Any]) -> bool:
    work_id, bvid, status = record.get("work_id"), record.get("bvid"), record.get("status")
    if not isinstance(work_id, str) or not work_id or not isinstance(bvid, str) or not bvid:
        return False
    if status not in VALID_STATUSES:
        return False
    try:
        parsed, _ = parse_work_id(work_id)
    except (TypeError, ValueError):
        return False
    return parsed == bvid


def project_manifest_records(
    path: str | Path, *, policy: ReaderPolicy | None = None,
) -> tuple[dict[str, dict[str, Any]], str, set[str]]:
    """Project latest valid manifest row, retaining duplicate diagnostics."""
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
                "line_limit": "manifest_malformed",
                "malformed": "manifest_malformed",
            }.get(item.diagnostic, "manifest_malformed"))
            continue
        assert item.value is not None
        if not _valid_manifest(item.value):
            state = "malformed"
            diagnostics.add("manifest_invalid")
            continue
        key = item.value["work_id"]
        if key in entries:
            diagnostics.add("manifest_duplicate_work_id")
        entries[key] = item.value
    if not Path(path).exists() or Path(path).is_symlink():
        state = "missing" if not Path(path).exists() else "malformed"
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
            state = "malformed"
            if item.diagnostic == "attempts_record_limit":
                diagnostics.add("attempts_row_limit_exceeded")
            elif item.diagnostic == "attempts_byte_limit":
                diagnostics.add("attempts_byte_limit_exceeded")
            elif item.diagnostic == "truncated_final":
                diagnostics.add("truncated_attempts_line")
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
    if not Path(path).exists() or Path(path).is_symlink():
        state = "missing" if not Path(path).exists() else "malformed"
    return list(latest.values()), state, diagnostics
