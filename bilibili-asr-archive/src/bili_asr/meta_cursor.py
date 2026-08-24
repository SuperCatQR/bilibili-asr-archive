"""Archive-root metadata crawl cursor (`meta-cursor.json`).

Filesystem ownership only. BiliClient must never import this module.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import sys
from typing import Any

CURSOR_FILENAME = "meta-cursor.json"

VALID_STATES = frozenset(
    {
        "running",
        "risk_interrupted",
        "limited",
        "complete",
    }
)

# --resume consumes only this persisted terminal.
RESUME_STATE = "risk_interrupted"

_SCHEMA_KEYS = (
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


def _validate(cursor: dict[str, Any]) -> dict[str, Any]:
    missing = [k for k in _SCHEMA_KEYS if k not in cursor]
    if missing:
        raise ValueError(f"cursor missing fields: {missing}")
    state = cursor["state"]
    if state not in VALID_STATES:
        raise ValueError(f"unknown cursor state {state!r}")
    if state == "running":
        raise ValueError("state=running is in-memory only and must not be persisted")
    mid = cursor["mid"]
    if not isinstance(mid, int):
        raise ValueError("cursor mid must be int")
    next_page = cursor["next_page"]
    if not isinstance(next_page, int) or next_page < 1:
        raise ValueError("cursor next_page must be int >= 1")
    total = cursor["total"]
    if total is not None and not isinstance(total, int):
        raise ValueError("cursor total must be int or null")
    code = cursor["last_api_error_code"]
    if code is not None and not isinstance(code, (int, str)):
        raise ValueError("cursor last_api_error_code must be int, str, or null")
    if isinstance(code, str) and len(code) > _MAX_ERROR_CODE_LEN:
        raise ValueError("cursor last_api_error_code is not a redacted code")
    if not isinstance(cursor["updated_at"], str) or not cursor["updated_at"]:
        raise ValueError("cursor updated_at must be a non-empty ISO-8601 string")
    stored = {key: cursor[key] for key in _SCHEMA_KEYS}
    dumped = json.dumps(stored, ensure_ascii=False).lower()
    for marker in _FORBIDDEN_MARKERS:
        if marker.lower() in dumped:
            raise ValueError("cursor must not contain credentials, URLs, or traces")
    return stored


class MetaCursorStore:
    """Atomic sidecar at `{archive_root}/meta-cursor.json`."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = os.fspath(root)
        self.path = os.path.join(self.root, CURSOR_FILENAME)

    def load(self) -> dict[str, Any] | None:
        if not os.path.exists(self.path):
            return None
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, json.JSONDecodeError):
            print("meta-cursor: ignoring corrupt sidecar", file=sys.stderr)
            return None
        if not isinstance(raw, dict):
            print("meta-cursor: ignoring corrupt sidecar", file=sys.stderr)
            return None
        try:
            return _validate(raw)
        except (ValueError, KeyError, TypeError):
            print("meta-cursor: ignoring corrupt sidecar", file=sys.stderr)
            return None

    def replace_atomic(self, cursor: dict[str, Any]) -> dict[str, Any]:
        stored = _validate(dict(cursor))
        os.makedirs(self.root, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(stored, fh, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, self.path)
        return stored

    def resume_start_page(self, mid: int) -> int | None:
        """Return next_page only for a matching-mid risk_interrupted cursor."""
        cursor = self.load()
        if cursor is None:
            return None
        if cursor["state"] != RESUME_STATE:
            return None
        if cursor["mid"] != mid:
            return None
        return int(cursor["next_page"])
