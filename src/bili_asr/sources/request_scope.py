"""Loop-neutral ownership of the upstream SDK's process-global settings."""
from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager

_SETTINGS_LOCK = threading.Lock()
_OWNER = threading.local()


async def _close_owned_clients(loop, pools, existing, client_settings):
    """Release every owned transport even when one transport cannot close."""
    failures = []
    for name, pool in pools.items():
        client = pool.get(loop)
        if client is None or client is existing.get(name):
            continue
        pool.pop(loop, None)
        if client_settings is not None:
            client_settings.get(name, {}).pop(loop, None)
        try:
            await asyncio.wait_for(client.close(), timeout=10)
        except BaseException as exc:
            failures.append(exc)
    return failures


async def _finish_cleanup(loop, pools, existing, client_settings):
    # A second cancellation must not abandon cleanup on an event loop which is
    # about to disappear. Defer it until all transports have been visited.
    cleanup = asyncio.create_task(_close_owned_clients(loop, pools, existing, client_settings))
    cancelled = None
    while True:
        try:
            failures = await asyncio.shield(cleanup)
            break
        except asyncio.CancelledError as exc:
            cancelled = exc
    return cancelled or (failures[0] if failures else None)


@asynccontextmanager
async def sdk_settings_scope(settings, proxy: str | None, *, client_pools=None, client_settings=None):
    """Serialize SDK settings during calls, restoring them on every exit.

    A threading lock is shared across event loops and threads. Nonblocking
    acquisition keeps the caller cancellable and cannot deadlock an event loop
    with another task that is holding the SDK call. Nested helper calls from
    the owning task reuse the same scope; other tasks wait. Clients created
    inside this scope are closed before its event loop can be discarded.
    """
    task = asyncio.current_task()
    if getattr(_OWNER, "task", None) is task:
        yield
        return
    while not _SETTINGS_LOCK.acquire(blocking=False):
        await asyncio.sleep(0.005)
    _OWNER.task = task
    previous = None
    loop = asyncio.get_running_loop()
    pools = client_pools if client_pools is not None else {}
    existing = {}
    error = None
    try:
        existing = {name: pool.get(loop) for name, pool in pools.items()}
        previous = settings.get_proxy()
        requested = proxy or ""
        if previous != requested:
            settings.set_proxy(requested)
        yield
    except BaseException as exc:
        error = exc
        raise
    finally:
        try:
            cleanup_error = None
            try:
                cleanup_error = await _finish_cleanup(loop, pools, existing, client_settings)
            except BaseException as exc:
                cleanup_error = exc
            finally:
                try:
                    if previous is not None and settings.get_proxy() != previous:
                        settings.set_proxy(previous)
                except BaseException as exc:
                    cleanup_error = cleanup_error or exc
            if cleanup_error is not None:
                if error is None:
                    raise cleanup_error
                # Never replace the original provider failure/cancellation
                # with a cleanup failure, or attach upstream exception text.
                error.add_note("SDK transport cleanup also failed")
        finally:
            _OWNER.task = None
            _SETTINGS_LOCK.release()


__all__ = ["sdk_settings_scope"]
