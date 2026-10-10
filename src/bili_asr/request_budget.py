"""Per-coordinator request budgets and pacing, without a second scheduler."""
from __future__ import annotations

import asyncio
from collections import Counter
from time import monotonic
from typing import Awaitable, Callable, TypeVar

from bili_asr.sources.models import GatewayError, GatewayRateLimited, GatewayTransportError

T = TypeVar("T")


class RequestScheduler:
    """Serialize one coordinator's requests and enforce a bounded deadline.

    One instance can be injected into gateways sharing an origin/access scope.
    It is deliberately process-local; distributed workers require separate
    deployment coordination. Retries belong to the caller and each consumes
    this same budget, so rate-control cannot multiply nested retry loops.
    """

    def __init__(self, *, max_requests: int = 10000, total_seconds: float = 14400,
                 request_seconds: float = 30, interval_seconds: float = 0,
                 clock: Callable[[], float] = monotonic,
                 sleeper: Callable[[float], Awaitable] | None = None):
        if type(max_requests) is not int or max_requests < 1:
            raise ValueError("request count must be positive")
        for value in (total_seconds, request_seconds):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value < float("inf"):
                raise ValueError("request deadlines must be finite and positive")
        if not 0 <= interval_seconds < float("inf"):
            raise ValueError("request interval must be finite and nonnegative")
        self.max_requests, self.request_seconds, self.interval = max_requests, request_seconds, interval_seconds
        self.clock, self.sleeper = clock, sleeper or asyncio.sleep
        self.started = clock()
        self.deadline = self.started + total_seconds
        self.next_allowed = self.started
        self.counts: Counter[str] = Counter()
        self.failures: Counter[str] = Counter()
        self.elapsed: Counter[str] = Counter()
        self._lock = asyncio.Lock()

    async def run(self, operation: str, call: Callable[[], Awaitable[T]]) -> T:
        async with self._lock:
            now = self.clock()
            wait = max(0.0, self.next_allowed - now)
            if sum(self.counts.values()) >= self.max_requests or now + wait >= self.deadline:
                raise GatewayTransportError(code="request_budget_exhausted")
            if wait:
                await self.sleeper(wait)
            self.counts[operation] += 1
            started = self.clock()
            try:
                return await asyncio.wait_for(call(), min(self.request_seconds, self.deadline - started))
            except asyncio.TimeoutError as error:
                self.failures[operation] += 1
                raise GatewayTransportError(code="request_timeout") from error
            except GatewayError as error:
                self.failures[operation] += 1
                if isinstance(error, GatewayRateLimited):
                    # All subsequent operations share the same risk cooldown.
                    self.next_allowed = self.clock() + 30
                raise
            finally:
                self.elapsed[operation] += self.clock() - started
                self.next_allowed = max(self.next_allowed, self.clock() + self.interval)

    def metrics(self) -> dict:
        return {"request_count": sum(self.counts.values()), "operations": dict(self.counts),
                "failures": dict(self.failures), "elapsed_seconds": dict(self.elapsed)}

    async def pause(self, seconds: float) -> None:
        """Coordinate application retry backoff with the same risk cooldown."""
        delay = max(seconds, self.next_allowed - self.clock())
        if self.clock() + delay >= self.deadline:
            raise GatewayTransportError(code="request_budget_exhausted")
        await self.sleeper(delay)
        self.next_allowed = self.clock()


__all__ = ["RequestScheduler"]
