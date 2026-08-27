"""Durable bounded campaign wrapper over the sequential scheduler."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .coordinator import RunCoordinator, RunSummary
from .manifest import ManifestStore
from .scheduler import SchedulerStore, classify_batch_state, settled_processed_ids, terminal_resume_ids


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


class CampaignRunner:
    """Run one bounded campaign using the existing coordinator."""

    def __init__(
        self,
        archive_root: str | os.PathLike[str],
        *,
        coordinator_factory: Callable[..., RunCoordinator] = RunCoordinator,
        scope_rows: Callable[[ManifestStore, dict[str, dict[str, Any]], str], tuple[list[tuple[str, dict[str, Any]]], str | None]] | None = None,
        policy_fingerprint: str = "default",
    ) -> None:
        self.root = Path(archive_root)
        self.coordinator_factory = coordinator_factory
        self.scope_rows = scope_rows
        self.policy_fingerprint = policy_fingerprint

    def _fingerprint(self, scope: str) -> str:
        return hashlib.sha256(f"{scope}\0{self.policy_fingerprint}".encode()).hexdigest()

    def _atomic_checkpoint(self, payload: dict[str, Any]) -> None:
        path = self.root / "campaign.json"
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        try:
            fd = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            pass

    def run(self, scope: str, batch_limit: int, *, resume: bool = False) -> CampaignSummary:
        if not isinstance(scope, str) or not scope:
            raise ValueError("scope must be a non-empty string")
        if isinstance(batch_limit, bool) or not isinstance(batch_limit, int) or batch_limit < 1:
            raise ValueError("batch_limit must be a positive integer")
        store = ManifestStore(self.root)
        entries = store.load()
        if self.scope_rows is None:
            raise ValueError("scope_rows is required for campaign execution")
        rows, error = self.scope_rows(store, entries, scope)
        if error:
            raise ValueError(error)
        selected = [str(entry.get("work_id") or key) for key, entry in rows]
        previous: list[str] = []
        scheduler = SchedulerStore(self.root)
        if resume:
            lookup = scheduler.inspect_resume(scope, allow_long_live=False)
            if lookup.refuse:
                raise ValueError(lookup.diagnostic or "resume refused")
            if lookup.processed_ids is not None:
                previous = terminal_resume_ids(lookup.processed_ids, entries)
                rows = [(key, entry) for key, entry in rows if str(entry.get("work_id") or key) not in set(previous)]
        rows = rows[:batch_limit]
        coordinator = self.coordinator_factory(self.root, store, offline=True)
        summary: RunSummary = coordinator.run_batch(rows)
        state = classify_batch_state(
            risk_interrupted=summary.risk_interrupted,
            truncated=len(selected) > batch_limit,
        )
        settled = previous + settled_processed_ids(summary.results, risk_interrupted=summary.risk_interrupted)
        processed = list(dict.fromkeys(settled))
        skipped = [r.work_id for r in summary.skipped_rows]
        failed = [r.work_id for r in summary.failed]
        reasons = [str(r.skip_reason) for r in summary.skipped_rows if r.skip_reason]
        for result in summary.failed:
            reasons.extend(str(code) for code in result.failure_codes)
        exit_code = 2 if summary.risk_interrupted else (1 if not summary.fully_processed else 0)
        self._atomic_checkpoint({
            "scope": scope,
            "policy_fingerprint": self._fingerprint(scope),
            "selected_work_ids": selected,
            "processed_work_ids": processed,
            "state": state,
            "reason_codes": sorted(set(reasons)),
        })
        return CampaignSummary(selected, processed, skipped, failed, state, sorted(set(reasons)), exit_code)


__all__ = ["CampaignRunner", "CampaignSummary"]
