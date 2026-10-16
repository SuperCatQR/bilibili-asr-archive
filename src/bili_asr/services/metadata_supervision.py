"""Durable, bounded supervision of the existing metadata ingestion service.

This is a single-cycle admission gate, not another queue or request client.
Pagination evidence remains authoritative in MetadataRepository. Supervision
records only the clocks and retry budget that cannot be recovered from it.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from pathlib import Path

from bili_asr.canonical_json import digest
from bili_asr.error_codes import validate_error_code
from bili_asr.services.retry_maintenance_io import maintenance_lock, read_json, write_json

FORMAT = "metadata-supervision/v1"
RETRYABLE_CODES = frozenset({"rate_limited", "transport_error", "request_budget_exhausted"})


@dataclass(frozen=True)
class MetadataSupervisionPolicy:
    version: int = 1
    maximum_consecutive_no_progress: int = 6
    maximum_no_progress_seconds: int = 21600
    maximum_wait_seconds: int = 14400
    initial_backoff_seconds: int = 900
    maximum_backoff_seconds: int = 3600
    maximum_pages_per_cycle: int = 3

    def __post_init__(self):
        if self.version != 1 or type(self.version) is not int:
            raise ValueError("unsupported metadata supervision policy version")
        for name, value in asdict(self).items():
            if type(value) is not int or value <= 0:
                raise ValueError("metadata supervision policy requires positive integers: " + name)
        if self.initial_backoff_seconds > self.maximum_backoff_seconds:
            raise ValueError("metadata supervision backoff bounds are inverted")
        if self.maximum_pages_per_cycle > 100 or self.maximum_consecutive_no_progress > 100:
            raise ValueError("metadata supervision cycle/retry bound exceeds 100")

    @classmethod
    def from_file(cls, path):
        value = read_json(Path(path))
        if set(value) - set(cls.__dataclass_fields__):
            raise ValueError("unknown metadata supervision policy field")
        return cls(**value)


@dataclass(frozen=True)
class SupervisedCollection:
    supervision: dict
    result: object | None = None


class MetadataSupervisor:
    def __init__(self, repository, *, archive_root, state_path, policy=None, clock=time.time):
        self.repository = repository
        self.archive_root = str(Path(archive_root).resolve())
        self.state_path = Path(state_path)
        self.policy = policy or MetadataSupervisionPolicy()
        self.clock = clock

    def _snapshot(self, mid):
        cursor = self.repository.read_cursor(mid)
        connection = self.repository.connection
        videos = connection.execute("SELECT COUNT(*) FROM videos WHERE mid=?", (mid,)).fetchone()[0]
        parts = connection.execute("SELECT COUNT(*) FROM video_parts p JOIN videos v USING(bvid) WHERE v.mid=?", (mid,)).fetchone()[0]
        page = cursor.next_page if cursor else 1
        boundary = connection.execute(
            "SELECT p.run_id FROM ingestion_pages p JOIN ingestion_runs r USING(run_id) "
            "WHERE r.mid=? AND p.page_number=? AND p.outcome='ok' ORDER BY p.finished_at DESC,p.rowid DESC LIMIT 1",
            (mid, page - 1)).fetchone()
        identities = [] if boundary is None else [row[0] for row in connection.execute(
            "SELECT bvid FROM ingestion_discoveries WHERE run_id=? AND page_number=? ORDER BY source_position,bvid",
            (boundary[0], page - 1))]
        return {"next_page": page, "cursor_state": cursor.state if cursor else None,
            "observed_total": cursor.observed_total if cursor else None,
            "videos": videos, "parts": parts, "boundary_page": page - 1,
            "boundary_sha256": digest(identities)}

    def _new_state(self, mid, now):
        observed = self._snapshot(mid)
        return {"format": FORMAT, "archive_root": self.archive_root, "mid": mid,
            "policy": asdict(self.policy), "policy_sha256": digest(asdict(self.policy)),
            "state": "ready", "monitoring_started_at": now, "last_progress_at": None,
            "last_progress": None, "high_watermark": observed, "observed": observed,
            "consecutive_no_progress": 0, "accumulated_wait_seconds": 0,
            "no_progress_wait_seconds": 0, "wait_accounted_at": None,
            "next_action_at": now, "last_run_id": None, "last_outcome": None,
            "error_code": None, "reason": None, "active_attempt": None, "updated_at": now}

    def _read(self, mid, now):
        if type(mid) is not int or mid <= 0:
            raise ValueError("metadata supervision mid must be positive")
        state = read_json(self.state_path) if self.state_path.exists() else self._new_state(mid, now)
        if set(state) != set(self._new_state(mid, now)) or state["format"] != FORMAT:
            raise ValueError("unsupported metadata supervision state")
        if state["mid"] != mid or state["archive_root"] != self.archive_root:
            raise ValueError("metadata supervision state belongs to another archive or creator")
        if state["policy"] != asdict(self.policy) or state["policy_sha256"] != digest(state["policy"]):
            raise ValueError("metadata supervision policy changed; preserve evidence and review before starting a new supervision state")
        if state["state"] not in {"ready", "running", "backoff", "complete", "needs_attention"}:
            raise ValueError("invalid metadata supervision state")
        for key in ("monitoring_started_at", "updated_at", "next_action_at", "accumulated_wait_seconds", "no_progress_wait_seconds"):
            if type(state[key]) not in {int, float} or not 0 <= state[key] < float("inf"):
                raise ValueError("invalid metadata supervision clock: " + key)
        if type(state["consecutive_no_progress"]) is not int or state["consecutive_no_progress"] < 0:
            raise ValueError("invalid metadata supervision counter")
        for key in ("last_progress_at", "wait_accounted_at"):
            if state[key] is not None and (type(state[key]) not in {int, float} or not 0 <= state[key] < float("inf")):
                raise ValueError("invalid metadata supervision clock: " + key)
        if now < state["updated_at"]:
            raise ValueError("metadata supervision clock moved backwards")
        validate_error_code(state["error_code"])
        return state

    @staticmethod
    def _advanced(observed, prior):
        return any(observed[key] > prior[key] for key in ("next_page", "videos", "parts"))

    def _budget(self, state, now):
        if state["state"] in {"complete", "needs_attention"}:
            return
        elapsed = now - (state["last_progress_at"] if state["last_progress_at"] is not None else state["monitoring_started_at"])
        reason = ("consecutive_no_progress_budget" if state["consecutive_no_progress"] >= self.policy.maximum_consecutive_no_progress else
                  "no_progress_time_budget" if elapsed >= self.policy.maximum_no_progress_seconds else
                  "no_progress_wait_budget" if state["no_progress_wait_seconds"] >= self.policy.maximum_wait_seconds else None)
        if reason:
            state.update(state="needs_attention", reason=reason, wait_accounted_at=None)

    def _finish(self, state, *, now, outcome, error_code, run_id, progress_observed_at=None):
        observed = self._snapshot(state["mid"])
        progress = self._advanced(observed, state["high_watermark"])
        if progress:
            progress_at = now if progress_observed_at is None else max(
                state["last_progress_at"] or state["monitoring_started_at"], min(now, progress_observed_at))
            state.update(last_progress_at=progress_at, last_progress=observed, consecutive_no_progress=0, no_progress_wait_seconds=0)
            state["high_watermark"] = {**observed, **{
                key: max(observed[key], state["high_watermark"][key]) for key in ("next_page", "videos", "parts")}}
        elif outcome != "complete":
            state["consecutive_no_progress"] += 1
        state.update(observed=observed, last_run_id=run_id, last_outcome=outcome,
            error_code=validate_error_code(error_code), active_attempt=None, reason=None)
        if outcome == "complete" and observed["cursor_state"] == "complete":
            state.update(state="complete", next_action_at=now, wait_accounted_at=None)
        elif outcome == "limited" and progress:
            state.update(state="ready", next_action_at=now, wait_accounted_at=None)
        elif error_code not in RETRYABLE_CODES and outcome != "limited":
            state.update(state="needs_attention", reason=error_code or "collection_interrupted", wait_accounted_at=None)
        else:
            exponent = max(0, min(state["consecutive_no_progress"] - 1, 30))
            delay = min(self.policy.initial_backoff_seconds * 2**exponent, self.policy.maximum_backoff_seconds)
            state.update(state="backoff", next_action_at=now + delay, wait_accounted_at=now,
                reason="resumable_incomplete")
        self._budget(state, now)

    def _prepare(self, mid, now):
        state = self._read(mid, now)
        if state["state"] == "running":
            # A crashed process may have committed pages or even completion.
            # Reconcile repository evidence; never invent a historical wait.
            active = state["active_attempt"]
            row = self.repository.connection.execute(
                "SELECT r.run_id,r.outcome,(SELECT p.error_code FROM ingestion_pages p WHERE p.run_id=r.run_id "
                "AND p.error_code IS NOT NULL ORDER BY p.finished_at DESC,p.rowid DESC LIMIT 1) AS error_code "
                "FROM ingestion_runs r WHERE r.mid=? AND r.rowid>? ORDER BY r.rowid DESC LIMIT 1",
                (mid, active["previous_run_rowid"])).fetchone()
            progress_at = self.repository.connection.execute(
                "SELECT MAX(p.finished_at) FROM ingestion_pages p JOIN ingestion_runs r USING(run_id) "
                "WHERE r.mid=? AND r.rowid>? AND p.outcome='ok'", (mid, active["previous_run_rowid"])).fetchone()[0]
            self._finish(state, now=now, outcome=row["outcome"] if row else "failed",
                error_code=row["error_code"] if row and row["outcome"] != "running" else "supervision_interrupted",
                run_id=row["run_id"] if row else None, progress_observed_at=progress_at)
            if state["error_code"] == "supervision_interrupted":
                state["reason"] = "previous_process_interrupted"
        if state["wait_accounted_at"] is not None:
            elapsed = max(0, min(now, state["next_action_at"]) - state["wait_accounted_at"])
            state["accumulated_wait_seconds"] += elapsed
            state["no_progress_wait_seconds"] += elapsed
            state["wait_accounted_at"] = min(now, state["next_action_at"])
        self._budget(state, now)
        state["updated_at"] = now
        return state

    def inspect(self, mid):
        with maintenance_lock(self.state_path.with_suffix(self.state_path.suffix + ".lock")):
            state = self._prepare(mid, self.clock())
            write_json(self.state_path, state)
            return state

    def collect(self, ingestor, *, mid, **options):
        if options.get("start_page") is not None or options.get("incremental") or options.get("skip_failed_page"):
            raise ValueError("supervised collection cannot rewind or skip pages; investigate and re-enumerate explicitly")
        limit = options.get("page_limit")
        if limit is not None and (type(limit) is not int or limit < 1):
            raise ValueError("invalid supervised page limit")
        options["page_limit"] = min(limit or self.policy.maximum_pages_per_cycle, self.policy.maximum_pages_per_cycle)
        with maintenance_lock(self.state_path.with_suffix(self.state_path.suffix + ".lock")):
            now = self.clock()
            state = self._prepare(mid, now)
            if state["state"] in {"complete", "needs_attention"} or now < state["next_action_at"]:
                write_json(self.state_path, state)
                return SupervisedCollection(state)
            previous = self.repository.connection.execute("SELECT COALESCE(MAX(rowid),0) FROM ingestion_runs WHERE mid=?", (mid,)).fetchone()[0]
            state.update(state="running", active_attempt={"started_at": now, "previous_run_rowid": previous},
                wait_accounted_at=None, updated_at=now)
            write_json(self.state_path, state)
            try:
                result = ingestor.collect_user_pages(mid=mid, **options)
            except BaseException:
                self._finish(state, now=self.clock(), outcome="failed", error_code="supervision_interrupted", run_id=None)
                state["updated_at"] = self.clock()
                write_json(self.state_path, state)
                raise
            if result.mid != mid:
                raise ValueError("metadata supervision result scope mismatch")
            self._finish(state, now=self.clock(), outcome=result.outcome, error_code=result.error_code, run_id=result.run_id)
            state["updated_at"] = self.clock()
            write_json(self.state_path, state)
            return SupervisedCollection(state, result)
