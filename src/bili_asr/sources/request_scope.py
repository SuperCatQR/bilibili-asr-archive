"""Loop-neutral ownership of the upstream SDK's process-global settings."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import threading


_SETTINGS_LOCK = threading.Lock()
_OWNER = threading.local()


@asynccontextmanager
async def sdk_settings_scope(settings, proxy: str | None):
    """Serialize SDK settings during calls, restoring them on every exit.

    A threading lock is shared across event loops and threads. Nonblocking
    acquisition keeps the caller cancellable and cannot deadlock an event loop
    with another task that is holding the SDK call. Nested helper calls from
    the owning task reuse the same scope; other tasks wait.
    """
    task = asyncio.current_task()
    if getattr(_OWNER, "task", None) is task:
        yield
        return
    while not _SETTINGS_LOCK.acquire(blocking=False):
        await asyncio.sleep(0.005)
    _OWNER.task = task
    previous = None
    try:
        previous = settings.get_proxy()
        requested = proxy or ""
        if previous != requested:
            settings.set_proxy(requested)
        yield
    finally:
        try:
            if previous is not None and settings.get_proxy() != previous:
                settings.set_proxy(previous)
        finally:
            _OWNER.task = None
            _SETTINGS_LOCK.release()


__all__ = ["sdk_settings_scope"]
