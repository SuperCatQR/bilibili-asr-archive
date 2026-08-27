"""Bounded campaign audit projection over the sequential coordinator.

``campaign.json`` is intentionally an aggregate/audit sidecar.  Per-row
resume and stage ownership remain with ``scheduler.json`` and the manifest.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, TypeAlias

from .coordinator import RunCoordinator, RunSummary
from .manifest import ManifestStore
from .scheduler import SchedulerStore, classify_batch_state, settled_processed_ids, terminal_resume_ids

ScopeRows: TypeAlias = Callable[
    [ManifestStore, dict[str, dict[str, Any]], str],
    tuple[list[tuple[str, dict[str, Any]]] | None, str | None],
]

_FORBIDDEN_MARKERS = ("SESSDATA", "cookie", "http://", "https://", "Traceback")
_MARKER_RE = re.compile("|".join(re.escape(marker) for marker in _FORBIDDEN_MARKERS), re.IGNORECASE)
_MAX_CODE_LENGTH = 64
_VALID_STATES = frozenset({"complete", "limited", "risk_interrupted"})


@dataclass(frozen=True)
class CampaignSummary:
    selected: list[str] = field(default_factory=list)
    processed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    checkpoint_state: str = "complete"
    reason_codes: list[str] = field(default_factory=list)
    exit_code: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "selected": list(self.selected),
            "processed": list(self.processed),
            "skipped": list(self.skipped),
            "failed": list(self.failed),
            "checkpoint_state": self.checkpoint_state,
            "reason_codes": list(self.reason_codes),
            "exit_code": self.exit_code,
        }


def _work_id(key: str, entry: dict[str, Any]) -> str:
    return str(entry.get("work_id") or key)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _redacted_code(value: object) -> str:
    return _MARKER_RE.sub("", str(value))[:_MAX_CODE_LENGTH]


class CampaignRunner:
    """Run one bounded batch and atomically project aggregate evidence."""

    def __init__(
        self,
        archive_root: str | os.PathLike[str],
        *,
        client: Any = None,
        offline: bool = False,
        max_audio_bytes: int = 0,
        sleep: Callable[[float], None] | None = None,
        scope_rows: ScopeRows | None = None,
        policy_fingerprint: str = "default",
        coordinator_factory: Callable[..., RunCoordinator] = RunCoordinator,
    ) -> None:
        self.root = Path(archive_root)
        self.client = client
        self.offline = offline
        self.max_audio_bytes = max_audio_bytes
        self.sleep = sleep
        self.scope_rows = scope_rows
        self.policy_fingerprint = policy_fingerprint
        self.coordinator_factory = coordinator_factory

    @property
    def path(self) -> Path:
        return self.root / "campaign.json"

    def _atomic_checkpoint(self, payload: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f".{self.path.name}.tmp")
        try:
            with tmp.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
            try:
                directory_fd = os.open(self.root, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError:
                pass
        except BaseException:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise

    def _projection(
        self,
        *,
        scope: str,
        selected: list[str],
        processed: list[str],
        state: str,
        reason_codes: list[str],
    ) -> dict[str, object]:
        if state not in _VALID_STATES:
            raise ValueError(f"unknown campaign state {state!r}")
        return {
            "scope": scope,
            "policy_fingerprint": self.policy_fingerprint,
            "selected_work_ids": list(selected),
            "processed_work_ids": list(processed),
            "state": state,
            "reason_codes": list(reason_codes),
        }

    def run(self, scope: str, batch_limit: int, *, resume: bool = False) -> CampaignSummary:
        if not isinstance(scope, str) or not scope.strip():
            raise ValueError("scope must be a non-empty string")
        if isinstance(batch_limit, bool) or not isinstance(batch_limit, int) or batch_limit < 1:
            raise ValueError("batch_limit must be a positive integer")
        if self.scope_rows is None:
            raise ValueError("scope_rows is required for campaign execution")

        store = ManifestStore(self.root)
        entries = store.load()
        rows, error = self.scope_rows(store, entries, scope)
        if error:
            raise ValueError(error)
        if rows is None:
            raise ValueError("scope selector returned no rows")

        processed_before: list[str] = []
        if resume:
            lookup = SchedulerStore(self.root).inspect_resume(scope, allow_long_live=False)
            if lookup.refuse:
                raise ValueError(lookup.diagnostic or "resume refused")
            if lookup.processed_ids is None:
                raise ValueError(lookup.diagnostic or "resume refused")
            processed_before = terminal_resume_ids(lookup.processed_ids, entries)
            done = set(processed_before)
            rows = [(key, entry) for key, entry in rows if _work_id(key, entry) not in done]

        matching = len(rows)
        selected_rows = rows[:batch_limit]
        selected = [_work_id(key, entry) for key, entry in selected_rows]
        coordinator = self.coordinator_factory(
            self.root,
            store,
            client=self.client,
            offline=self.offline,
            max_audio_bytes=self.max_audio_bytes,
            sleep=self.sleep,
        )
        run_summary: RunSummary = coordinator.run_batch(selected_rows)
        state = classify_batch_state(
            risk_interrupted=run_summary.risk_interrupted,
            truncated=matching > batch_limit,
        )
        processed = _unique(
            processed_before
            + settled_processed_ids(
                run_summary.results, risk_interrupted=run_summary.risk_interrupted
            )
        )
        skipped = [result.work_id for result in run_summary.skipped_rows]
        failed = [result.work_id for result in run_summary.failed]
        reason_codes = _unique(
            [_redacted_code(result.skip_reason) for result in run_summary.skipped_rows if result.skip_reason]
            + [
                _redacted_code(code)
                for result in run_summary.failed
                for code in result.failure_codes
            ]
        )
        exit_code = 2 if run_summary.risk_interrupted else (0 if run_summary.fully_processed else 1)
        self._atomic_checkpoint(
            self._projection(
                scope=scope,
                selected=selected,
                processed=processed,
                state=state,
                reason_codes=reason_codes,
            )
        )
        return CampaignSummary(
            selected=selected,
            processed=processed,
            skipped=skipped,
            failed=failed,
            checkpoint_state=state,
            reason_codes=reason_codes,
            exit_code=exit_code,
        )


__all__ = ["CampaignRunner", "CampaignSummary", "ScopeRows"]
