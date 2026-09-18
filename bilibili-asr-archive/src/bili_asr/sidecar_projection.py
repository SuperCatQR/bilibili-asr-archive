"""Shared, read-only streaming projections for archive sidecars."""
from __future__ import annotations

from dataclasses import dataclass
import errno
import json
import os
from pathlib import Path
import stat
from typing import Any, Iterator, Literal, Mapping

from .coordinator import _validate_attempt
from .manifest import VALID_STATUSES, validate_manifest_record
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


def _open_regular_jsonl(path: str | Path) -> int:
    flags = os.O_RDONLY
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise OSError("safe sidecar opening is unavailable")
    try:
        fd = os.open(os.fspath(path), flags | nofollow)
    except FileNotFoundError:
        raise
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.EMLINK}:
            raise OSError("sidecar is a symlink") from exc
        raise
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("sidecar is not regular")
    except Exception:
        os.close(fd)
        raise
    return fd


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
        fd = _open_regular_jsonl(source)
    except FileNotFoundError:
        yield JsonlRecord(0, None, "missing")
        return
    except OSError:
        yield JsonlRecord(0, None, "symlink" if source.is_symlink() else "malformed")
        return
    try:
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            if policy.max_bytes is not None and info.st_size > policy.max_bytes:
                yield JsonlRecord(0, None, f"{name}_byte_limit")
                return
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
    try:
        validate_manifest_record(record)
    except (TypeError, ValueError, KeyError):
        return False
    return True


def _manifest_key(record: Mapping[str, Any]) -> str:
    work_id = record.get("work_id")
    if isinstance(work_id, str) and work_id:
        return work_id
    bvid = record.get("bvid")
    assert isinstance(bvid, str) and bvid
    return bvid


def _manifest_semantic_diagnostics(record: Mapping[str, Any]) -> set[str]:
    diagnostics: set[str] = set()
    if "status" in record and record.get("status") not in VALID_STATUSES:
        diagnostics.add("manifest_invalid_status")
    if "bvid" in record and "work_id" in record:
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


# Codes that describe the append-only store's normal shape, not a defect.
#
# A ``work_id`` appearing on several manifest lines is how a state transition
# sequence (``needs_audio`` -> ``audio_ok`` -> ``archived``) is encoded, so the
# projection still reports what it saw while every reader subtracts this set.
ORDINARY_HISTORY_DIAGNOSTICS = frozenset({"manifest_duplicate_work_id"})


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
                "invalid_utf8": "structural_input_error",
                "line_limit": "manifest_malformed",
                "malformed": "manifest_malformed",
            }.get(item.diagnostic, "manifest_malformed"))
            continue
        assert item.value is not None
        semantic = _manifest_semantic_diagnostics(item.value)
        diagnostics.update(semantic)
        if semantic or not _valid_manifest(item.value):
            state = "malformed"
            diagnostics.add("manifest_invalid")
            continue
        key = _manifest_key(item.value)
        if key in entries:
            diagnostics.add("manifest_duplicate_work_id")
        entries[key] = item.value
    if not Path(path).exists():
        state = "missing"
    elif Path(path).is_symlink():
        state = "malformed"
    return entries, state, diagnostics


def project_latest_run_record(
    path: str | Path, *, policy: ReaderPolicy | None = None,
) -> tuple[dict[str, Any] | None, str, set[str]]:
    """Stream a run ledger, retaining only the latest valid record."""
    latest = None
    diagnostics: set[str] = set()
    state = "available"
    for item in iter_jsonl_records(path, policy=policy, name="run_ledger"):
        if item.diagnostic:
            if item.diagnostic == "missing":
                state = "missing"
                continue
            state = "malformed"
            diagnostics.add(item.diagnostic)
            continue
        try:
            from .run_ledger import _validate_record
            latest = _validate_record(item.value or {})
        except (TypeError, ValueError, KeyError):
            state = "malformed"
            diagnostics.add("run_ledger_invalid_record")
    if not Path(path).exists():
        state = "missing"
    return latest, state, diagnostics


def project_attempt_records(
    path: str | Path, *, policy: ReaderPolicy | None = None,
) -> tuple[list[dict[str, Any]], str, set[str]]:
    """Project latest valid attempt for each ``(work_id, stage)`` key."""
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    diagnostics: set[str] = set()
    state = "available"
    for item in iter_jsonl_records(path, policy=policy, name="attempts"):
        if item.diagnostic:
            if item.diagnostic == "missing":
                state = "missing"
                continue
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
