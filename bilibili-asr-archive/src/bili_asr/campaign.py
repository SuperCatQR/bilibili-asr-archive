"""Bounded campaign audit projection over the sequential coordinator.

``campaign.json`` is intentionally an aggregate/audit sidecar.  Per-row
resume and stage ownership remain with ``scheduler.json`` and the manifest.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, TypeAlias

from .coordinator import RunCoordinator, RunSummary
from .manifest import ManifestStore
from .scheduler import SchedulerStore, settled_processed_ids, terminal_resume_ids

ScopeRows: TypeAlias = Callable[
    [ManifestStore, dict[str, dict[str, Any]], str],
    tuple[list[tuple[str, dict[str, Any]]] | None, str | None],
]

_FORBIDDEN_MARKERS = ("SESSDATA", "cookie", "http://", "https://", "Traceback")
_MARKER_RE = re.compile("|".join(re.escape(marker) for marker in _FORBIDDEN_MARKERS), re.IGNORECASE)
_MAX_CODE_LENGTH = 64
_MAX_REASON_CODES = 32
_SCHEMA_VERSION = 1
_VALID_STATES = frozenset({"complete", "limited", "risk_interrupted"})
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_SAFE_CODE_RE = re.compile(r"^[a-z0-9_:-]{1,64}$")
_TERMINAL_FINAL_STATUSES = frozenset({"archived", "gone"})


def _safe_id(value: object) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise ValueError("unsafe campaign identifier")
    return value


def _safe_code(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("unsafe campaign reason code")
    text = value.lower()
    if not _SAFE_CODE_RE.fullmatch(text) or len(text) > _MAX_CODE_LENGTH:
        raise ValueError("unsafe campaign reason code")
    return text


def _policy_hash(value: object) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


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
    return _safe_code(value)


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
        # coordinator_factory is a test-only injection seam; production uses RunCoordinator.
        coordinator_factory: Callable[..., RunCoordinator] = RunCoordinator,
    ) -> None:
        self.root = Path(archive_root)
        self.client = client
        self.offline = offline
        self.max_audio_bytes = max_audio_bytes
        self.sleep = sleep
        self.scope_rows = scope_rows
        self.policy_fingerprint = _policy_hash(policy_fingerprint)
        self.coordinator_factory = coordinator_factory

    @property
    def path(self) -> Path:
        return self.root / "campaign.json"

    def _atomic_checkpoint(self, payload: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f".{self.path.name}.tmp")
        previous = self.path.read_bytes() if self.path.exists() else None
        try:
            with tmp.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
            directory_fd = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            except BaseException:
                # Restore the previous valid projection (or remove this new one)
                # before surfacing the durability failure.
                if previous is None:
                    try:
                        self.path.unlink()
                    except OSError:
                        pass
                else:
                    restore_tmp = self.path.with_name(f".{self.path.name}.restore")
                    try:
                        restore_tmp.write_bytes(previous)
                        os.replace(restore_tmp, self.path)
                        restore_fd = os.open(self.path, os.O_RDONLY)
                        try:
                            os.fsync(restore_fd)
                        finally:
                            os.close(restore_fd)
                        rollback_dir_fd = os.open(self.root, os.O_RDONLY)
                        try:
                            os.fsync(rollback_dir_fd)
                        finally:
                            os.close(rollback_dir_fd)
                    finally:
                        try:
                            restore_tmp.unlink()
                        except OSError:
                            pass
                raise
            finally:
                os.close(directory_fd)
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
        batch_limit: int,
        state: str,
        reason_codes: list[str],
    ) -> dict[str, object]:
        if state not in _VALID_STATES:
            raise ValueError(f"unknown campaign state {state!r}")
        return {
            "schema_version": _SCHEMA_VERSION,
            "scope": _safe_id(scope),
            "batch_limit": batch_limit,
            "policy_fingerprint": self.policy_fingerprint,
            "selected_work_ids": [_safe_id(item) for item in selected],
            "processed_work_ids": [_safe_id(item) for item in processed],
            "skipped_work_ids": [],
            "failed_work_ids": [],
            "state": state,
            "reason_codes": [_safe_code(code) for code in _unique(reason_codes)[:_MAX_REASON_CODES]],
        }

    def _validate_projection(self, value: object, scope: str, batch_limit: int, selected_scope: set[str]) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("resume refused: campaign projection corrupt/mismatch")
        if value.get("policy_fingerprint") != self.policy_fingerprint:
            raise ValueError("resume refused: policy mismatch")
        if value.get("scope") != scope or value.get("batch_limit") != batch_limit or value.get("state") != "risk_interrupted":
            raise ValueError("resume refused: campaign projection mismatch")
        for key in ("selected_work_ids", "processed_work_ids"):
            raw = value.get(key)
            if not isinstance(raw, list) or len(raw) > batch_limit or len(set(raw)) != len(raw):
                raise ValueError("resume refused: campaign projection corrupt/mismatch")
            try:
                [_safe_id(item) for item in raw]
            except ValueError as exc:
                raise ValueError("resume refused: campaign projection corrupt/mismatch") from exc
        if not set(value["selected_work_ids"]).issubset(selected_scope) or not set(value["processed_work_ids"]).issubset(set(value["selected_work_ids"])):
            raise ValueError("resume refused: campaign projection corrupt/mismatch")
        codes = value.get("reason_codes", [])
        if not isinstance(codes, list) or len(codes) > _MAX_REASON_CODES:
            raise ValueError("resume refused: campaign projection corrupt/mismatch")
        try:
            [_safe_code(code) for code in codes]
        except ValueError as exc:
            raise ValueError("resume refused: campaign projection corrupt/mismatch") from exc
        return value
    def _resume_ids(
        self, scope: str, batch_limit: int, entries: dict[str, dict[str, Any]],
        selected_scope: set[str],
    ) -> list[str]:
        store = SchedulerStore(self.root)
        lookup = store.inspect_resume(scope, allow_long_live=False)
        if lookup.refuse or lookup.processed_ids is None:
            raise ValueError(lookup.diagnostic or "resume refused")
        record = store.load(warn=False)
        if not record or record.get("state") != "risk_interrupted":
            raise ValueError("resume refused: state is not risk_interrupted")
        if record.get("scope") != scope:
            raise ValueError("resume refused: scope mismatch")
        if record.get("limit") != batch_limit:
            raise ValueError("resume refused: limit mismatch")
        if record.get("allow_long_live") is not False:
            raise ValueError("resume refused: long-live policy mismatch")
        projection = self.path
        if not projection.exists():
            raise ValueError("resume refused: campaign projection missing")
        try:
            campaign = json.loads(projection.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("resume refused: campaign projection corrupt/mismatch") from exc
        campaign = self._validate_projection(campaign, scope, batch_limit, selected_scope)
        scheduler_ids = set(lookup.processed_ids)
        if set(campaign["processed_work_ids"]) != scheduler_ids:
            raise ValueError("resume refused: campaign projection drift")
        return terminal_resume_ids(lookup.processed_ids, entries)

    def run(self, scope: str, batch_limit: int, *, resume: bool = False) -> CampaignSummary:
        if not isinstance(scope, str) or not scope.strip():
            raise ValueError("scope must be a non-empty string")
        if isinstance(batch_limit, bool) or not isinstance(batch_limit, int) or batch_limit < 1:
            raise ValueError("batch_limit must be a positive integer")
        if self.scope_rows is None:
            raise ValueError("scope_rows is required for campaign execution")
        if not isinstance(self.max_audio_bytes, int) or self.max_audio_bytes < 0:
            raise ValueError("max_audio_bytes must be non-negative")

        store = ManifestStore(self.root)
        entries = store.load()
        rows, error = self.scope_rows(store, entries, scope)
        if error:
            raise ValueError(error)
        if rows is None:
            raise ValueError("scope selector returned no rows")

        processed_before: list[str] = []
        if resume:
            processed_before = self._resume_ids(scope, batch_limit, entries, {_work_id(k, e) for k, e in rows})
            done = set(processed_before)
            rows = [(key, entry) for key, entry in rows if _work_id(key, entry) not in done]

        matching = len(rows)
        selected_rows = rows[:batch_limit]
        existing = None
        if self.path.exists():
            try:
                existing = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError("campaign refused: existing projection corrupt/mismatch") from exc
            if not isinstance(existing, dict):
                raise ValueError("campaign refused: existing projection corrupt/mismatch")
            if existing.get("state") == "risk_interrupted" and not resume:
                raise ValueError("campaign refused: active risk checkpoint requires --resume")
            if existing.get("state") not in _VALID_STATES:
                raise ValueError("campaign refused: existing projection corrupt/mismatch")
        selected = [_safe_id(_work_id(key, entry)) for key, entry in selected_rows]
        coordinator = self.coordinator_factory(
            self.root, store, client=self.client, offline=self.offline,
            max_audio_bytes=self.max_audio_bytes, sleep=self.sleep,
        )
        run_summary: RunSummary = coordinator.run_batch(selected_rows)
        result_by_id = {result.work_id: result for result in run_summary.results}
        failed_or_skipped = bool(run_summary.failed or run_summary.skipped_rows)
        terminal_results = all(result.final_status in _TERMINAL_FINAL_STATUSES for result in run_summary.results)
        complete = (
            bool(selected_rows)
            and matching <= batch_limit
            and not run_summary.risk_interrupted
            and not failed_or_skipped
            and set(result_by_id) == set(selected)
            and len(run_summary.results) == len(selected)
            and terminal_results
        )
        state = "complete" if complete else ("risk_interrupted" if run_summary.risk_interrupted else "limited")
        processed = _unique(processed_before + settled_processed_ids(
            run_summary.results, risk_interrupted=run_summary.risk_interrupted))
        skipped = [_safe_id(result.work_id) for result in run_summary.skipped_rows]
        failed = [_safe_id(result.work_id) for result in run_summary.failed]
        reason_codes = _unique(
            [_redacted_code(result.skip_reason) for result in run_summary.skipped_rows if result.skip_reason]
            + [_redacted_code(code) for result in run_summary.failed for code in result.failure_codes]
        )
        exit_code = 2 if run_summary.risk_interrupted else (0 if complete else 1)
        self._atomic_checkpoint(self._projection(scope=scope, selected=selected, processed=processed,
                                                 batch_limit=batch_limit, state=state, reason_codes=reason_codes))
        return CampaignSummary(selected=selected, processed=processed, skipped=skipped, failed=failed,
                               checkpoint_state=state, reason_codes=reason_codes, exit_code=exit_code)


__all__ = ["CampaignRunner", "CampaignSummary", "ScopeRows"]
