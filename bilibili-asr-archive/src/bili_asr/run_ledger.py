"""Operational run ledger (`run-ledger.jsonl`).

Filesystem ownership only. BiliClient must never import this module.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import secrets
import sys
from typing import Any

from .manifest import VALID_STATUSES
from .meta_cursor import VALID_STATES

LEDGER_FILENAME = "run-ledger.jsonl"

VALID_COMMANDS = frozenset(
    {
        "fetch-meta",
        "pilot",
        "run",
    }
)

_REQUIRED_KEYS = (
    "run_id",
    "command",
    "started_at",
    "finished_at",
    "exit_code",
)

_SCHEMA_KEYS = (
    "run_id",
    "command",
    "started_at",
    "finished_at",
    "exit_code",
    "mid",
    "work_ids",
    "pages_fetched",
    "records_fetched",
    "records_existing",
    "last_api_error_code",
    "coverage_summary",
    "cursor_snapshot",
)

_CURSOR_SCHEMA_KEYS = (
    "mid",
    "next_page",
    "total",
    "state",
    "last_api_error_code",
    "updated_at",
)

# Sidecar may hold only redacted scalar codes — never cookies, URLs, traces.
_FORBIDDEN_MARKERS = (
    "SESSDATA",
    "cookie",
    "Cookie",
    "http://",
    "https://",
    "Traceback",
)
_MAX_ERROR_CODE_LEN = 64


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def generate_run_id() -> str:
    """Generate an opaque timestamp + random token run_id."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    rand = secrets.token_hex(4)
    return f"run-{ts}-{rand}"


def compute_coverage_summary(entries_or_store: Any) -> dict[str, int]:
    """Compute manifest status counts (only statuses in VALID_STATUSES)."""
    if hasattr(entries_or_store, "load"):
        entries = entries_or_store.load()
    elif isinstance(entries_or_store, dict):
        entries = entries_or_store
    else:
        entries = {}
    counts: dict[str, int] = {}
    for item in entries.values():
        if not isinstance(item, dict):
            continue
        status = item.get("status", "pending")
        if status in VALID_STATUSES:
            counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def build_run_record(
    *,
    command: str,
    started_at: str,
    finished_at: str | None = None,
    exit_code: int,
    run_id: str | None = None,
    mid: int | None = None,
    work_ids: list[str] | None = None,
    pages_fetched: int | None = None,
    records_fetched: int | None = None,
    records_existing: int | None = None,
    last_api_error_code: int | str | None = None,
    coverage_summary: dict[str, int] | None = None,
    cursor_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construct a run record dictionary before validation."""
    if run_id is None:
        run_id = generate_run_id()
    if finished_at is None:
        finished_at = utc_now_iso()
    return {
        "run_id": run_id,
        "command": command,
        "started_at": started_at,
        "finished_at": finished_at,
        "exit_code": exit_code,
        "mid": mid,
        "work_ids": list(work_ids) if work_ids is not None else None,
        "pages_fetched": pages_fetched,
        "records_fetched": records_fetched,
        "records_existing": records_existing,
        "last_api_error_code": last_api_error_code,
        "coverage_summary": dict(coverage_summary) if coverage_summary is not None else {},
        "cursor_snapshot": dict(cursor_snapshot) if cursor_snapshot is not None else None,
    }


def _validate_cursor_snapshot(cursor: dict[str, Any]) -> dict[str, Any]:
    missing = [k for k in _CURSOR_SCHEMA_KEYS if k not in cursor]
    if missing:
        raise ValueError(f"cursor_snapshot missing fields: {missing}")
    state = cursor["state"]
    if state not in VALID_STATES:
        raise ValueError(f"unknown cursor state {state!r}")
    if state == "running":
        raise ValueError("cursor_snapshot state=running is in-memory only")
    mid = cursor["mid"]
    if not isinstance(mid, int) or isinstance(mid, bool):
        raise ValueError("cursor mid must be int")
    next_page = cursor["next_page"]
    if not isinstance(next_page, int) or isinstance(next_page, bool) or next_page < 1:
        raise ValueError("cursor next_page must be int >= 1")
    total = cursor["total"]
    if total is not None and (not isinstance(total, int) or isinstance(total, bool)):
        raise ValueError("cursor total must be int or null")
    code = cursor["last_api_error_code"]
    if code is not None and not isinstance(code, (int, str)):
        raise ValueError("cursor last_api_error_code must be int, str, or null")
    if isinstance(code, bool):
        raise ValueError("cursor last_api_error_code must not be bool")
    if isinstance(code, str) and len(code) > _MAX_ERROR_CODE_LEN:
        raise ValueError("cursor last_api_error_code is not a redacted code")
    if not isinstance(cursor["updated_at"], str) or not cursor["updated_at"]:
        raise ValueError("cursor updated_at must be a non-empty ISO-8601 string")
    return {k: cursor[k] for k in _CURSOR_SCHEMA_KEYS}


def _validate_record(record: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ValueError("run record must be a dict")
    for k in _REQUIRED_KEYS:
        if k not in record:
            raise ValueError(f"run record missing required field: {k!r}")

    run_id = record["run_id"]
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("run_id must be a non-empty str")

    command = record["command"]
    if not isinstance(command, str) or not command:
        raise ValueError("command must be a non-empty str")

    started_at = record["started_at"]
    if not isinstance(started_at, str) or not started_at:
        raise ValueError("started_at must be a non-empty ISO-8601 str")

    finished_at = record["finished_at"]
    if not isinstance(finished_at, str) or not finished_at:
        raise ValueError("finished_at must be a non-empty ISO-8601 str")

    exit_code = record["exit_code"]
    if not isinstance(exit_code, int) or isinstance(exit_code, bool):
        raise ValueError("exit_code must be an int")

    mid = record.get("mid")
    if mid is not None and (not isinstance(mid, int) or isinstance(mid, bool)):
        raise ValueError("mid must be int or null")

    work_ids = record.get("work_ids")
    if work_ids is not None:
        if not isinstance(work_ids, list) or not all(isinstance(w, str) for w in work_ids):
            raise ValueError("work_ids must be a list of str or null")

    pages_fetched = record.get("pages_fetched")
    if pages_fetched is not None and (not isinstance(pages_fetched, int) or isinstance(pages_fetched, bool)):
        raise ValueError("pages_fetched must be int or null")

    records_fetched = record.get("records_fetched")
    if records_fetched is not None and (not isinstance(records_fetched, int) or isinstance(records_fetched, bool)):
        raise ValueError("records_fetched must be int or null")

    records_existing = record.get("records_existing")
    if records_existing is not None and (not isinstance(records_existing, int) or isinstance(records_existing, bool)):
        raise ValueError("records_existing must be int or null")

    last_api_error_code = record.get("last_api_error_code")
    if last_api_error_code is not None:
        if isinstance(last_api_error_code, bool) or not isinstance(last_api_error_code, (int, str)):
            raise ValueError("last_api_error_code must be int, str, or null")
        if isinstance(last_api_error_code, str) and len(last_api_error_code) > _MAX_ERROR_CODE_LEN:
            raise ValueError("last_api_error_code is not a redacted code")

    coverage_summary = record.get("coverage_summary")
    if coverage_summary is not None:
        if not isinstance(coverage_summary, dict):
            raise ValueError("coverage_summary must be a dict")
        for k, v in coverage_summary.items():
            if k not in VALID_STATUSES:
                raise ValueError(f"coverage_summary invalid status key {k!r}")
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                raise ValueError(f"coverage_summary count for {k!r} must be int >= 0")
        coverage_summary = dict(sorted(coverage_summary.items()))
    else:
        coverage_summary = {}

    cursor_snapshot = record.get("cursor_snapshot")
    if cursor_snapshot is not None:
        cursor_snapshot = _validate_cursor_snapshot(cursor_snapshot)

    stored = {
        "run_id": run_id,
        "command": command,
        "started_at": started_at,
        "finished_at": finished_at,
        "exit_code": exit_code,
        "mid": mid,
        "work_ids": work_ids,
        "pages_fetched": pages_fetched,
        "records_fetched": records_fetched,
        "records_existing": records_existing,
        "last_api_error_code": last_api_error_code,
        "coverage_summary": coverage_summary,
        "cursor_snapshot": cursor_snapshot,
    }

    dumped = json.dumps(stored, ensure_ascii=False).lower()
    for marker in _FORBIDDEN_MARKERS:
        if marker.lower() in dumped:
            raise ValueError(f"record contains forbidden marker: {marker!r}")

    return stored


class RunLedger:
    """Append-only JSONL sidecar at `{archive_root}/run-ledger.jsonl`."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = os.fspath(root)
        self.path = os.path.join(self.root, LEDGER_FILENAME)

    def append(self, record: dict[str, Any]) -> dict[str, Any]:
        """Atomically append a validated run record line to run-ledger.jsonl."""
        stored = _validate_record(record)
        os.makedirs(self.root, exist_ok=True)
        existing_bytes = b""
        if os.path.exists(self.path):
            with open(self.path, "rb") as fh:
                existing_bytes = fh.read()
        line_bytes = (json.dumps(stored, ensure_ascii=False) + "\n").encode("utf-8")
        tmp = self.path + ".tmp"
        with open(tmp, "wb") as fh:
            if existing_bytes:
                fh.write(existing_bytes)
                if not existing_bytes.endswith(b"\n"):
                    fh.write(b"\n")
            fh.write(line_bytes)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)
        return stored

    def load(self) -> list[dict[str, Any]]:
        """Read all valid run records in chronological order."""
        if not os.path.exists(self.path):
            return []
        records: list[dict[str, Any]] = []
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        raw = json.loads(line)
                        if isinstance(raw, dict):
                            records.append(_validate_record(raw))
                    except (json.JSONDecodeError, ValueError):
                        print("run-ledger: ignoring corrupt line", file=sys.stderr)
                        continue
        except OSError:
            return []
        return records

    def latest(self) -> dict[str, Any] | None:
        """Return the latest run record, or None if empty."""
        records = self.load()
        return records[-1] if records else None
