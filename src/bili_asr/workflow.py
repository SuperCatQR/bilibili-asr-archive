"""Stateless workflow execution boundary.

Handlers are injected callables.  The executor does not know whether a job
uses Bilibili APIs, an object store, a GPU model, or a test double; it only
persists claims and outcomes through :class:`WorkflowRepository`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import threading
from typing import Any, Protocol

from bili_asr.workflow_models import JobKind, JobCancelledError, LeaseLostError, WorkflowJob


JobHandler = Callable[[WorkflowJob], Mapping[str, Any] | None]


class LeaseRepository(Protocol):
    def renew_lease(self, job: WorkflowJob, *, lease_seconds: int) -> None: ...
    def close(self) -> None: ...


class WorkflowControl(Protocol):
    """The executor's durable port; storage owns its transaction semantics."""

    def claim(self, worker_id: str, *, lease_seconds: int,
              kinds: tuple[JobKind, ...] | None) -> WorkflowJob | None: ...
    def finish(self, job_id: str, *, worker_id: str, result: Mapping[str, Any] | None,
               expected_attempt_count: int) -> None: ...
    def fail(self, job_id: str, *, worker_id: str, error_code: str,
             expected_attempt_count: int) -> None: ...
    def open_lease_repository(self) -> LeaseRepository | None: ...


@dataclass(frozen=True)
class ExecutionSummary:
    succeeded: int
    failed: int
    idle: bool
    cancelled: int = 0


class WorkflowExecutor:
    """Claim jobs one at a time and invoke stateless handlers."""

    def __init__(
        self,
        repository: WorkflowControl,
        *,
        worker_id: str,
        handlers: Mapping[JobKind, JobHandler],
        kinds: tuple[JobKind, ...] | None = None,
        lease_seconds: int = 900,
        heartbeat_interval_seconds: float | None = None,
    ):
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        if heartbeat_interval_seconds is not None and heartbeat_interval_seconds <= 0:
            raise ValueError("heartbeat_interval_seconds must be positive")
        self.repository = repository
        self.worker_id = worker_id
        self.handlers = dict(handlers)
        self.kinds = kinds
        self.lease_seconds = lease_seconds
        self.heartbeat_interval_seconds = heartbeat_interval_seconds or max(1.0, lease_seconds / 3)

    def run(self, *, limit: int | None = None) -> ExecutionSummary:
        if limit is not None and limit < 1:
            raise ValueError("limit must be positive")
        succeeded = failed = cancelled = 0
        while limit is None or succeeded + failed + cancelled < limit:
            job = self.repository.claim(
                self.worker_id, lease_seconds=self.lease_seconds, kinds=self.kinds
            )
            if job is None:
                return ExecutionSummary(succeeded, failed, idle=succeeded + failed + cancelled == 0,
                                        cancelled=cancelled)
            handler = self.handlers.get(job.kind)
            if handler is None:
                if self._fail(job, "no_handler"):
                    cancelled += 1
                else:
                    failed += 1
                continue
            heartbeat = _LeaseHeartbeat(
                self.repository,
                job,
                lease_seconds=self.lease_seconds,
                interval_seconds=self.heartbeat_interval_seconds,
            )
            heartbeat.start()
            try:
                result = handler(job)
            except Exception as exc:  # Handler details stay out of durable control state.
                if self._fail(job, str(getattr(exc, "error_code", ""))[:64] or type(exc).__name__[:64]):
                    cancelled += 1
                else:
                    failed += 1
            else:
                try:
                    self.repository.finish(job.job_id, worker_id=self.worker_id, result=result,
                                           expected_attempt_count=job.attempt_count)
                except JobCancelledError:
                    cancelled += 1
                except LeaseLostError:
                    failed += 1
                else:
                    succeeded += 1
            finally:
                heartbeat.stop()
        return ExecutionSummary(succeeded, failed, idle=False, cancelled=cancelled)

    def _fail(self, job: WorkflowJob, error_code: str) -> bool:
        """Return whether the terminal write observed authoritative cancellation."""
        try:
            self.repository.fail(job.job_id, worker_id=self.worker_id, error_code=error_code,
                                 expected_attempt_count=job.attempt_count)
        except JobCancelledError:
            return True
        except LeaseLostError:
            # Reclamation records lease_expired. A stale worker must leave the
            # newer attempt's result and ownership untouched, even with a reused ID.
            pass
        return False


class _LeaseHeartbeat:
    """Renew one exact attempt from a connection owned by a daemon thread."""

    def __init__(
        self,
        repository: WorkflowControl,
        job: WorkflowJob,
        *,
        lease_seconds: int,
        interval_seconds: float,
    ) -> None:
        self.repository = repository
        self.job = job
        self.lease_seconds = lease_seconds
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run,
            name=f"workflow-lease-{self.job.job_id[:8]}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.interval_seconds + 1.0))
        self._thread = None

    def _run(self) -> None:
        # Open the connection inside the heartbeat thread so sqlite's default
        # thread-affinity check is satisfied.
        lease_repository = self.repository.open_lease_repository()
        if lease_repository is None:
            return
        try:
            # Renew once before the first wait.  Claim timestamps are stored at
            # second precision; waiting for the first interval can otherwise
            # lose a one-second test lease at a wall-clock boundary.
            while not self._stop.is_set():
                try:
                    lease_repository.renew_lease(self.job, lease_seconds=self.lease_seconds)
                except LeaseLostError:
                    # The terminal write will be fenced by the same attempt tuple.
                    return
                except Exception:
                    # A transient SQLite lock or I/O error must not turn a healthy
                    # handler into a false success.  Retry at the next interval;
                    # terminal writes still enforce the exact lease fence.
                    if self._stop.wait(self.interval_seconds):
                        return
                    continue
                if self._stop.wait(self.interval_seconds):
                    return
        finally:
            lease_repository.close()
