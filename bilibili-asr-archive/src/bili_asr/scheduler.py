"""Bounded sequential scheduler sidecar (`scheduler.json`).

Filesystem ownership only. Distinguishes a bounded batch (`limited`) from
requested-scope completion (`complete`) and risk interruption
(`risk_interrupted`) without changing the JSONL manifest schema.
`BiliClient` must never import this module.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from .meta_cursor import utc_now_iso

SCHEDULER_FILENAME = "scheduler.json"

VALID_STATES = frozenset(
    {
        "running",
        "risk_interrupted",
        "limited",
        "complete",
    }
)

RESUME_STATE = "risk_interrupted"

_SCHEMA_KEYS = (
    "scope",
    "limit",
    "state",
    "processed_work_ids",
    "last_api_error_code",
    "updated_at",
)

_FORBIDDEN_MARKERS = (
    "SESSDATA",
    "cookie",
    "Cookie",
    "http://",
    "https://",
    "Traceback",
)
_MAX_ERROR_CODE_LEN = 64


def classify_batch_state(*, risk_interrupted: bool, truncated: bool) -> str:
    """Map one scheduler call onto the locked completion vocabulary.

    A truncated (``--limit``) call is ``limited`` even when every selected
    row succeeded. Risk always wins. ``complete`` means this call visited
    every currently matching scope row — never that the visible corpus is
    fully archived.
    """
    if risk_interrupted:
        return "risk_interrupted"
    if truncated:
        return "limited"
    return "complete"


def settled_processed_ids(results: list[Any], *, risk_interrupted: bool) -> list[str]:
    """Work ids that finished this call; the risk-stopped row stays retryable."""
    ids = [str(getattr(row, "work_id")) for row in results]
    if risk_interrupted and ids:
        return ids[:-1]
    return ids


def _validate(cursor: dict[str, Any]) -> dict[str, Any]:
    missing = [k for k in _SCHEMA_KEYS if k not in cursor]
    if missing:
        raise ValueError(f"scheduler missing fields: {missing}")
    state = cursor["state"]
    if state not in VALID_STATES:
        raise ValueError(f"unknown scheduler state {state!r}")
    if state == "running":
        raise ValueError("state=running is in-memory only and must not be persisted")
    scope = cursor["scope"]
    if not isinstance(scope, str) or not scope:
        raise ValueError("scheduler scope must be a non-empty str")
    limit = cursor["limit"]
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ValueError("scheduler limit must be int >= 1")
    processed = cursor["processed_work_ids"]
    if not isinstance(processed, list) or any(
        not isinstance(item, str) or not item for item in processed
    ):
        raise ValueError("scheduler processed_work_ids must be a list of non-empty str")
    code = cursor["last_api_error_code"]
    if code is not None and not isinstance(code, (int, str)):
        raise ValueError("scheduler last_api_error_code must be int, str, or null")
    if isinstance(code, str) and len(code) > _MAX_ERROR_CODE_LEN:
        raise ValueError("scheduler last_api_error_code is not a redacted code")
    if not isinstance(cursor["updated_at"], str) or not cursor["updated_at"]:
        raise ValueError("scheduler updated_at must be a non-empty ISO-8601 string")
    stored = {key: cursor[key] for key in _SCHEMA_KEYS}
    stored["processed_work_ids"] = list(processed)
    dumped = json.dumps(stored, ensure_ascii=False).lower()
    for marker in _FORBIDDEN_MARKERS:
        if marker.lower() in dumped:
            raise ValueError("scheduler must not contain credentials, URLs, or traces")
    return stored


class SchedulerStore:
    """Atomic sidecar at `{archive_root}/scheduler.json`."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = os.fspath(root)
        self.path = os.path.join(self.root, SCHEDULER_FILENAME)

    def load(self) -> dict[str, Any] | None:
        if not os.path.exists(self.path):
            return None
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, json.JSONDecodeError):
            print("scheduler: ignoring corrupt sidecar", file=sys.stderr)
            return None
        if not isinstance(raw, dict):
            print("scheduler: ignoring corrupt sidecar", file=sys.stderr)
            return None
        try:
            return _validate(raw)
        except (ValueError, KeyError, TypeError):
            print("scheduler: ignoring corrupt sidecar", file=sys.stderr)
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

    def resume_processed_ids(self, scope: str) -> list[str] | None:
        """Return processed ids only for a matching-scope risk_interrupted sidecar."""
        cursor = self.load()
        if cursor is None:
            return None
        if cursor["state"] != RESUME_STATE:
            return None
        if cursor["scope"] != scope:
            return None
        return list(cursor["processed_work_ids"])


__all__ = [
    "SCHEDULER_FILENAME",
    "SchedulerStore",
    "VALID_STATES",
    "classify_batch_state",
    "settled_processed_ids",
    "utc_now_iso",
]
