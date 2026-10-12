"""Explicit, bounded failed-job maintenance independent of worker liveness."""

import time
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

from bili_asr.archive_session import ArchiveAccessMode, ArchiveSession, _checked_path
from bili_asr.services.retry_maintenance_io import (
    MaintenanceBusyError,
    maintenance_lock,
    read_json,
    update_health,
    write_json,
)
from bili_asr.storage.retry_maintenance import failed_candidates, requeue_exact_failure
from bili_asr.workflow_models import JobKind

# Unknown/source-quality/HTTP-payment/contract failures require investigation.
# A deployment may narrow this set; it cannot turn generic ValueError into a retry.
RETRYABLE_ERRORS = frozenset({
    "TimeoutError", "TimeoutException", "ConnectError", "ConnectTimeout", "ReadTimeout",
    "WriteTimeout", "PoolTimeout", "NetworkError", "RemoteProtocolError",
    "DeepSeekTransportError",
    "lease_expired", "worker_drain_timeout", "lease_renewal_failed",
    "RevisionValidationError",
})


def _integer(value, name, *, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"invalid maintenance {name}")
    return value


@dataclass(frozen=True)
class RetryPolicy:
    job_ids: tuple[str, ...]
    part_ids: tuple[int, ...]
    kinds: tuple[str, ...]
    retryable_errors: dict[str, tuple[str, ...]]
    max_retries: int
    delays_seconds: tuple[int, ...]
    interval_seconds: int

    @classmethod
    def load(cls, value: dict):
        expected = {"schema_version", "job_ids", "part_ids", "kinds", "retryable_errors",
                    "max_retries", "delays_seconds", "interval_seconds"}
        if set(value) != expected or type(value["schema_version"]) is not int or value["schema_version"] != 1:
            raise ValueError("unknown maintenance policy contract")
        for key in ("job_ids", "part_ids", "kinds", "delays_seconds"):
            if not isinstance(value[key], list) or len(value[key]) > 400:
                raise ValueError("invalid maintenance selector or delays")
        jobs, parts, kinds = value["job_ids"], value["part_ids"], value["kinds"]
        if not (jobs or parts) or not kinds:
            raise ValueError("maintenance requires exact jobs or parts and explicit kinds")
        if any(not isinstance(job, str) or not job or len(job) > 128 for job in jobs):
            raise ValueError("invalid maintenance job ID")
        for part in parts:
            _integer(part, "part ID", minimum=1)
        if any(not isinstance(kind, str) or kind not in {item.value for item in JobKind} for kind in kinds):
            raise ValueError("invalid maintenance kind")
        retries = _integer(value["max_retries"], "retry budget", minimum=1)
        if retries > 10 or len(value["delays_seconds"]) != retries:
            raise ValueError("maintenance retry budget requires one delay per retry, at most ten")
        for delay in value["delays_seconds"]:
            _integer(delay, "delay")
        interval = _integer(value["interval_seconds"], "interval", minimum=1)
        errors = value["retryable_errors"]
        if not isinstance(errors, dict) or set(errors) != set(kinds):
            raise ValueError("maintenance requires error allowlists for every selected kind")
        for kind, codes in errors.items():
            if not isinstance(codes, list) or not codes or any(not isinstance(code, str) or code not in RETRYABLE_ERRORS for code in codes):
                raise ValueError("unknown or unsafe maintenance retry error")
            if "RevisionValidationError" in codes and kind != "proofread":
                raise ValueError("editorial validation recovery is proofread only")
        return cls(tuple(jobs), tuple(parts), tuple(kinds),
                   {kind: tuple(codes) for kind, codes in errors.items()}, retries,
                   tuple(value["delays_seconds"]), interval)


def validate_state(state: dict) -> None:
    if not isinstance(state.get("retry_holds"), dict) or not isinstance(state.get("retry_ledger"), dict):
        raise ValueError("production retry state contract is incomplete")  # noqa: TRY004 - external JSON contract
    for entry in state["retry_ledger"].values():
        if not isinstance(entry, dict) or not {"retries", "last_retry_at"}.issubset(entry):
            raise ValueError("unknown production retry ledger entry")
        _integer(entry["retries"], "existing retries")
        _integer(entry["last_retry_at"], "existing retry time")


def _editorial_eligible(connection, candidate):
    if candidate["kind"] != "proofread":
        return True
    from bili_asr.storage.editorial import EditorialRepository
    status = EditorialRepository(connection).recovery_status_for_job(candidate["job_id"])
    # Persisted call budget, including unfinished calls, outranks the job budget.
    return bool(status["eligible"])


def retry_skip_reason(connection, policy: RetryPolicy, state: dict, candidate: dict, now: int) -> str | None:
    """The shared preview/dispatch guard; evaluating it never reserves a retry."""
    job_id, code = candidate["job_id"], candidate["last_error_code"]
    entry = state["retry_ledger"].get(job_id, {"retries": 0, "last_retry_at": 0})
    if job_id in state["retry_holds"]:
        return "held"
    if code not in policy.retryable_errors[candidate["kind"]]:
        return "error_not_allowlisted"
    if (candidate["outcome"] != "failed" or candidate["error_code"] != code
            or type(candidate["finished_at"]) is not int):
        return "attempt_mismatch"
    if entry["retries"] >= policy.max_retries:
        return "budget_exhausted"
    if (policy.delays_seconds[entry["retries"]] > 0
            and now < (candidate["finished_at"] if entry["retries"] == 0
                       else entry["last_retry_at"]) + policy.delays_seconds[entry["retries"]]):
        return "backoff"
    if not _editorial_eligible(connection, candidate):
        return "editorial_budget_or_policy"
    if entry.get("reserved_attempt_id") == candidate["attempt_id"]:
        return "reservation_requires_review"
    return None


def validate_maintenance_paths(archive_root, *, policy_path: Path, state_path: Path,
                               lock_path: Path, health_path: Path) -> None:
    """Refuse aliases before opening locks or replacing any operational file."""
    archive = Path(archive_root)
    database = (archive if archive.suffix.lower() in {".db", ".sqlite", ".sqlite3"}
                and not archive.is_dir() else archive / "archive.db")
    archive_directory = database.parent.resolve()
    archive_lock = archive_directory.parent / f".{archive_directory.name}.archive-maintenance.lock"
    targets = [policy_path, state_path, lock_path, health_path,
               health_path.with_suffix(health_path.suffix + ".lock"), database, archive_lock]
    for index, target in enumerate(targets):
        _checked_path(target.absolute())
        if target.is_dir():
            raise ValueError("maintenance files cannot be directories")
        for other in targets[:index]:
            if (str(target.resolve()).casefold() == str(other.resolve()).casefold()
                    or (target.exists() and other.exists() and target.samefile(other))):
                raise ValueError("maintenance files and archive database must differ")


def maintain_failed_jobs(connection, policy: RetryPolicy, state: dict, *, state_path: Path, now: int) -> list[dict]:
    validate_state(state)
    events = []
    for candidate in failed_candidates(connection, job_ids=policy.job_ids, part_ids=policy.part_ids, kinds=policy.kinds):
        job_id, code = candidate["job_id"], candidate["last_error_code"]
        reason = retry_skip_reason(connection, policy, state, candidate, now)
        entry = state["retry_ledger"].get(job_id, {"retries": 0, "last_retry_at": 0})
        if reason is not None:
            events.append({"job_id": job_id, "action": "skipped", "reason": reason})
            continue
        # File and SQLite cannot share a commit. Charge first and never refund an
        # uncertain dispatch; a crash can cost an allowance, never create one.
        entry.update(retries=entry["retries"] + 1, last_retry_at=now,
                     last_error_code=code, reserved_attempt_id=candidate["attempt_id"],
                     dispatch_outcome="reserved")
        state["retry_ledger"][job_id] = entry
        write_json(state_path, state)
        changed = requeue_exact_failure(connection, candidate, now,
                                       eligible=lambda candidate=candidate: _editorial_eligible(connection, candidate))
        entry["dispatch_outcome"] = "requeued" if changed else "stale"
        write_json(state_path, state)
        events.append({"job_id": job_id, "attempt_id": candidate["attempt_id"],
                       "action": entry["dispatch_outcome"], "retry": entry["retries"]})
    return events


def tick(*, archive_root, policy_path: Path, state_path: Path, lock_path: Path,
         health_path: Path, clock=time.time) -> dict:
    validate_maintenance_paths(archive_root, policy_path=policy_path, state_path=state_path,
                               lock_path=lock_path, health_path=health_path)
    now = int(clock())
    with ExitStack() as locks:
        try:
            locks.enter_context(maintenance_lock(lock_path))
        except MaintenanceBusyError:
            update_health(health_path, last_lock_skipped_at=now)
            return {"status": "lock_skipped", "events": []}
        else:
            update_health(health_path, last_started_at=now, status="running", next_due_at=None)
            try:
                policy = RetryPolicy.load(read_json(policy_path))
                update_health(health_path, next_due_at=now + policy.interval_seconds,
                              interval_seconds=policy.interval_seconds)
                state = read_json(state_path)
                validate_state(state)
                with ArchiveSession(archive_root, mode=ArchiveAccessMode.WRITE) as session:
                    events = maintain_failed_jobs(session.connection, policy, state, state_path=state_path, now=now)
                completed = int(clock())
                update_health(health_path, last_succeeded_at=completed, status="succeeded",
                              error_code=None, next_due_at=completed + policy.interval_seconds)
                return {"status": "succeeded", "events": events}
            except Exception as exc:
                # Exception text can include endpoint URLs or credentials.
                update_health(health_path, last_failed_at=int(clock()), status="failed",
                              error_code=type(exc).__name__)
                raise


def health(*, health_path: Path, stale_after_seconds: int, worker_health_path: Path | None = None,
           clock=time.time) -> dict:
    _integer(stale_after_seconds, "health age", minimum=1)
    now = int(clock())
    value = read_json(health_path) if health_path.exists() else {}
    success = value.get("last_succeeded_at")
    started, failed = value.get("last_started_at", 0), value.get("last_failed_at", 0)
    if value.get("status") == "failed":
        status = "failed"
    elif success is None:
        status = "never_succeeded"
    elif now - success > stale_after_seconds or (value.get("next_due_at") is not None
                                                and now > value["next_due_at"] + stale_after_seconds):
        status = "stale"
    elif started > success and value.get("status") == "running":
        status = "running"
    elif failed > success:
        status = "failed"
    else:
        status = "healthy"
    # Worker health is an independent producer snapshot; never implies retry health.
    worker = read_json(worker_health_path) if worker_health_path is not None else {"status": "not_supplied"}
    return {"maintenance": {**value, "health_status": status, "checked_at": now}, "workers": worker}
