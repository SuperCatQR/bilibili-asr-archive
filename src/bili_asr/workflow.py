"""Stateless workflow execution boundary.

Handlers are injected callables.  The executor does not know whether a job
uses Bilibili APIs, an object store, a GPU model, or a test double; it only
persists claims and outcomes through :class:`WorkflowRepository`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from bili_asr.storage.workflow import JobKind, LeaseLostError, WorkflowJob, WorkflowRepository


JobHandler = Callable[[WorkflowJob], Mapping[str, Any] | None]


@dataclass(frozen=True)
class ExecutionSummary:
    succeeded: int
    failed: int
    idle: bool


class WorkflowExecutor:
    """Claim jobs one at a time and invoke stateless handlers."""

    def __init__(
        self,
        repository: WorkflowRepository,
        *,
        worker_id: str,
        handlers: Mapping[JobKind, JobHandler],
        kinds: tuple[JobKind, ...] | None = None,
    ):
        self.repository = repository
        self.worker_id = worker_id
        self.handlers = dict(handlers)
        self.kinds = kinds

    def run(self, *, limit: int | None = None) -> ExecutionSummary:
        if limit is not None and limit < 1:
            raise ValueError("limit must be positive")
        succeeded = failed = 0
        while limit is None or succeeded + failed < limit:
            job = self.repository.claim(self.worker_id, kinds=self.kinds)
            if job is None:
                return ExecutionSummary(succeeded, failed, idle=succeeded + failed == 0)
            handler = self.handlers.get(job.kind)
            if handler is None:
                self._fail(job, "no_handler")
                failed += 1
                continue
            try:
                result = handler(job)
            except Exception as exc:  # Handler details stay out of durable control state.
                self._fail(job, type(exc).__name__[:64])
                failed += 1
            else:
                try:
                    self.repository.finish(job.job_id, worker_id=self.worker_id, result=result,
                                           expected_attempt_count=job.attempt_count)
                except LeaseLostError:
                    failed += 1
                else:
                    succeeded += 1
        return ExecutionSummary(succeeded, failed, idle=False)

    def _fail(self, job: WorkflowJob, error_code: str) -> None:
        try:
            self.repository.fail(job.job_id, worker_id=self.worker_id, error_code=error_code,
                                 expected_attempt_count=job.attempt_count)
        except LeaseLostError:
            # Reclamation records lease_expired. A stale worker must leave the
            # newer attempt's result and ownership untouched, even with a reused ID.
            pass
