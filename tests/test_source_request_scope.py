"""SDK globals remain isolated across cancellation, threads and event loops."""
import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest

from bili_asr.sources.request_scope import sdk_settings_scope


class Settings:
    def __init__(self):
        self.proxy = "original"

    def get_proxy(self):
        return self.proxy

    def set_proxy(self, value):
        self.proxy = value


def test_settings_scope_serializes_threads_with_independent_event_loops():
    settings = Settings()

    async def request(proxy):
        async with sdk_settings_scope(settings, proxy):
            assert settings.get_proxy() == proxy
            await asyncio.sleep(0.01)
            assert settings.get_proxy() == proxy
            async with sdk_settings_scope(settings, proxy):
                assert settings.get_proxy() == proxy

    with ThreadPoolExecutor(max_workers=3) as executor:
        results = [executor.submit(asyncio.run, request(f"proxy{index}")) for index in range(3)]
        for result in results:
            result.result(timeout=3)
    assert settings.get_proxy() == "original"


def test_cancelled_owner_restores_settings_and_releases_waiters():
    settings = Settings()

    async def verify():
        entered = asyncio.Event()
        async def owner():
            async with sdk_settings_scope(settings, "first"):
                entered.set()
                await asyncio.sleep(60)
        task = asyncio.create_task(owner())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        async with sdk_settings_scope(settings, "second"):
            assert settings.get_proxy() == "second"
        assert settings.get_proxy() == "original"
    asyncio.run(verify())


def test_settings_read_failure_does_not_leak_global_lock():
    class FailingSettings(Settings):
        def get_proxy(self):
            raise RuntimeError("settings unavailable")
    async def verify():
        with pytest.raises(RuntimeError):
            async with sdk_settings_scope(FailingSettings(), "first"):
                pytest.fail("unreachable")
        settings = Settings()
        async with sdk_settings_scope(settings, "second"):
            assert settings.get_proxy() == "second"
    asyncio.run(asyncio.wait_for(verify(), 1))


@pytest.mark.parametrize("outcome", ["success", "failure", "cancelled"])
def test_request_clients_are_closed_before_each_event_loop_exits(outcome):
    pools = {"transport": {}}
    pending_settings = {"transport": {}}
    settings = Settings()
    clients = []

    class Client:
        closed = False

        async def close(self):
            assert not asyncio.get_running_loop().is_closed()
            assert settings.get_proxy() == "request"
            self.closed = True

    async def request():
        loop = asyncio.get_running_loop()
        client = Client()
        clients.append(client)
        try:
            async with sdk_settings_scope(
                settings, "request", client_pools=pools,
                client_settings=pending_settings,
            ):
                pools["transport"][loop] = client
                pending_settings["transport"][loop] = {}
                async with sdk_settings_scope(
                    settings, "request", client_pools=pools,
                    client_settings=pending_settings,
                ):
                    assert not client.closed
                assert not client.closed
                if outcome == "failure":
                    raise ValueError("upstream failed")
                if outcome == "cancelled":
                    raise asyncio.CancelledError
        finally:
            assert client.closed
            assert pools == {"transport": {}}
            assert pending_settings == {"transport": {}}
            assert settings.get_proxy() == "original"

    for _ in range(20):
        if outcome == "failure":
            with pytest.raises(ValueError, match="upstream failed"):
                asyncio.run(request())
        elif outcome == "cancelled":
            with pytest.raises(asyncio.CancelledError):
                asyncio.run(request())
        else:
            asyncio.run(request())
    assert all(client.closed for client in clients)


def test_scope_does_not_close_clients_created_by_another_owner():
    pools = {"transport": {}}
    settings = Settings()

    class Client:
        async def close(self):
            pytest.fail("preexisting client belongs to its creator")

    async def verify():
        loop = asyncio.get_running_loop()
        client = Client()
        pools["transport"][loop] = client
        async with sdk_settings_scope(settings, "request", client_pools=pools):
            pass
        assert pools["transport"][loop] is client

    asyncio.run(verify())


@pytest.mark.parametrize("upstream_failure", [False, True])
def test_all_transports_close_and_original_error_wins(upstream_failure):
    closed = []
    settings = Settings()
    pools = {"first": {}, "second": {}}
    pending = {"first": {}, "second": {}}

    class Client:
        def __init__(self, name):
            self.name = name

        async def close(self):
            closed.append(self.name)
            if self.name == "first":
                raise OSError("private transport detail")

    async def request():
        async with sdk_settings_scope(settings, "request", client_pools=pools, client_settings=pending):
            loop = asyncio.get_running_loop()
            for name in pools:
                pools[name][loop] = Client(name)
                pending[name][loop] = {}
            if upstream_failure:
                raise ValueError("original provider error")

    expected = ValueError if upstream_failure else OSError
    with pytest.raises(expected):
        asyncio.run(request())
    assert closed == ["first", "second"]
    assert all(not pool for pool in pools.values())
    assert all(not pool for pool in pending.values())
    assert settings.get_proxy() == "original"


def test_repeated_cancellation_waits_for_transport_cleanup():
    settings = Settings()
    pools = {"transport": {}}

    async def verify():
        closing = asyncio.Event()
        finish = asyncio.Event()
        closed = asyncio.Event()

        class Client:
            async def close(self):
                closing.set()
                await finish.wait()
                closed.set()

        async def request():
            async with sdk_settings_scope(settings, "request", client_pools=pools):
                pools["transport"][asyncio.get_running_loop()] = Client()

        task = asyncio.create_task(request())
        await closing.wait()
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed.is_set()
        assert pools == {"transport": {}}
        async with sdk_settings_scope(settings, None):
            assert settings.get_proxy() == ""

    asyncio.run(asyncio.wait_for(verify(), 2))


def test_real_sdk_client_pool_does_not_retain_discarded_loops():
    from bilibili_api.utils.network import get_client, lazy_settings, request_settings, session_pool

    previous = request_settings.get_proxy()

    async def request():
        async with sdk_settings_scope(request_settings, previous, client_pools=session_pool,
                                      client_settings=lazy_settings):
            client = get_client()
            assert client is not None  # Construction only; no HTTP request.

    for _ in range(20):
        asyncio.run(request())
    assert all(not pool for pool in session_pool.values())
    assert all(not pool for pool in lazy_settings.values())
    assert request_settings.get_proxy() == previous
