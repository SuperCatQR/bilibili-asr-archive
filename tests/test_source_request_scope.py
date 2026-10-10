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
