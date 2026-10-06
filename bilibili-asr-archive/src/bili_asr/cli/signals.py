"""Signals implementation."""

from __future__ import annotations

import signal
import threading
from contextlib import contextmanager
from typing import Any, Iterator


class _RunInterrupted(BaseException):
    """Raised by a batch command's one-shot interruption disposition.

    A ``BaseException`` and not an ``Exception``: the coordinator's per-stage
    ``except Exception`` handlers would otherwise swallow the interruption and
    let the batch continue past it.
    """

    def __init__(self, signum: int) -> None:
        super().__init__(f"interrupted by signal {signum}")
        self.signum = signum


def _restore_signal_handlers(previous: dict[int, Any]) -> None:
    """Put back the dispositions a swap captured (empty mapping = nothing to do)."""
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def _ignore_interruption_signals() -> dict[int, Any]:
    """Leave ``SIGTERM``/``SIGINT`` ignored, and report what they were.

    The pair is swapped as a unit because the ignored state has to cover the
    whole unwind after the first delivery and the record write at its end, and
    that unwind is reached through ``SIGTERM`` *or* ``SIGINT``.  ``signal.signal``
    is main-thread only, so elsewhere nothing is swapped and the empty mapping
    reads as "nothing to restore".
    """
    if threading.current_thread() is not threading.main_thread():
        return {}
    return {
        signum: signal.signal(signum, signal.SIG_IGN)
        for signum in (signal.SIGTERM, signal.SIGINT)
    }


@contextmanager
def _interruptible_run() -> Iterator[None]:
    """Deliver the first SIGTERM/SIGINT as ``_RunInterrupted``.

    One-shot: the exception is raised once, and the true previous dispositions
    -- ``SIGTERM`` *and* ``SIGINT`` -- come back in this context manager's
    ``finally``, after the record write.  Delivery therefore leaves both signals
    **ignored** instead of restoring the captured disposition: the ignored
    state, not the default, is what must hold across the coordinator's unwind
    (runner release, batch-evidence stderr write), because a repeated
    ``SIGTERM`` landing there at the default disposition would kill the process
    before the write site with no record at all. SIGINT uses the same one-shot
    handler, so repeated Ctrl-C is ignored at first delivery, before exception
    matching or coordinator cleanup runs. ``signal.signal`` is main-thread only, so
    elsewhere the run body keeps the dispositions the process already had.
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    previous: dict[int, Any] = {}

    delivered = False

    def _on_interruption(signum: int, _frame: Any) -> None:
        nonlocal delivered
        # A second Python invocation between the disposition swaps must return.
        if delivered:
            return
        delivered = True
        # The swapped-out dispositions are deliberately dropped: the ignored
        # state, not the disposition at delivery, is what must hold until the
        # write site has run.
        _ignore_interruption_signals()
        raise _RunInterrupted(signum)

    previous[signal.SIGTERM] = signal.signal(signal.SIGTERM, _on_interruption)
    previous[signal.SIGINT] = signal.signal(signal.SIGINT, _on_interruption)
    try:
        yield
    finally:
        _restore_signal_handlers(previous)


@contextmanager
def _signals_ignored() -> Iterator[None]:
    """Ignore ``SIGTERM``/``SIGINT`` for the duration of the record write."""
    previous = _ignore_interruption_signals()
    try:
        yield
    finally:
        _restore_signal_handlers(previous)
