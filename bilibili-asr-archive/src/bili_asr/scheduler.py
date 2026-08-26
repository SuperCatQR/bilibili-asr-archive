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
from dataclasses import dataclass
from typing import Any, Mapping

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
_DURABLE_SKIP_REASONS = frozenset({"already_terminal"})
_TERMINAL_STATUSES = frozenset({"archived", "gone"})


@dataclass(frozen=True)
class ResumeLookup:
    """Outcome of ``--resume`` against one sidecar.

    ``processed_ids`` is set only for a matching-scope risk token.
    ``refuse`` means a still-valid risk token must not be overwritten.
    """

    processed_ids: list[str] | None
    diagnostic: str | None
    refuse: bool


_SCHEMA_KEYS = (
    "scope",
    "limit",
    "state",
    "processed_work_ids",
    "last_api_error_code",
    "allow_long_live",
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

    A truncated call (``--limit`` leftover or default long-duration hold)
    is ``limited`` even when every selected row succeeded. Risk always
    wins. ``complete`` means this call visited every currently matching
    scope row after duration policy — never that the visible corpus is
    fully archived.
    """
    if risk_interrupted:
        return "risk_interrupted"
    if truncated:
        return "limited"
    return "complete"


def settled_processed_ids(results: list[Any], *, risk_interrupted: bool) -> list[str]:
    """Durable ids from this call; retryable incomplete rows stay off the skip list.

    Only ``ok`` and ``already_terminal`` rows are persisted. Budget / offline /
    missing-artifact skips and failed rows remain retryable. The risk-stopped
    tail is omitted even if it were misclassified.
    """
    rows = list(results)
    if risk_interrupted and rows:
        rows = rows[:-1]
    ids: list[str] = []
    for row in rows:
        if getattr(row, "ok", False) or getattr(row, "skip_reason", "") in _DURABLE_SKIP_REASONS:
            ids.append(str(getattr(row, "work_id")))
    return ids


def terminal_resume_ids(
    processed: list[str],
    entries: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """Keep skip ids that are still terminal in the manifest."""
    kept: list[str] = []
    for work_id in processed:
        entry = entries.get(work_id)
        if not isinstance(entry, Mapping):
            continue
        if entry.get("status") in _TERMINAL_STATUSES:
            kept.append(work_id)
    return kept


def _validate(cursor: dict[str, Any]) -> dict[str, Any]:
    if "allow_long_live" not in cursor:
        cursor = dict(cursor)
        cursor["allow_long_live"] = False
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
    allow_long_live = cursor["allow_long_live"]
    if not isinstance(allow_long_live, bool):
        raise ValueError("scheduler allow_long_live must be a bool")
    stored = {key: cursor[key] for key in _SCHEMA_KEYS}
    stored["processed_work_ids"] = list(processed)
    stored["allow_long_live"] = allow_long_live
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

    def inspect_resume(
        self, scope: str, *, allow_long_live: bool
    ) -> ResumeLookup:
        """Diagnose ``--resume`` against the sidecar without mutating it."""
        cursor = self.load()
        if cursor is None:
            if os.path.exists(self.path):
                return ResumeLookup(None, "sidecar corrupt", False)
            return ResumeLookup(None, "sidecar missing", False)
        if cursor["state"] != RESUME_STATE:
            return ResumeLookup(
                None, f"state is {cursor['state']}, not risk_interrupted", False
            )
        if cursor["scope"] != scope:
            return ResumeLookup(
                None, f"scope mismatch ({cursor['scope']} vs {scope})", True
            )
        if cursor.get("allow_long_live") and not allow_long_live:
            return ResumeLookup(
                None,
                "long-live policy mismatch; pass --allow-long-live",
                True,
            )
        return ResumeLookup(list(cursor["processed_work_ids"]), None, False)

    def resume_processed_ids(self, scope: str) -> list[str] | None:
        """Return processed ids only for a matching-scope risk_interrupted sidecar."""
        lookup = self.inspect_resume(scope, allow_long_live=True)
        if lookup.refuse or lookup.processed_ids is None:
            return None
        return lookup.processed_ids


__all__ = [
    "SCHEDULER_FILENAME",
    "SchedulerStore",
    "VALID_STATES",
    "ResumeLookup",
    "classify_batch_state",
    "settled_processed_ids",
    "terminal_resume_ids",
    "utc_now_iso",
]
