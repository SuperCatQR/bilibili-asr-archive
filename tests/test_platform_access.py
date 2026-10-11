"""No actual platform request without independent acquisition evidence."""
import asyncio

import pytest

from bili_asr.bili_client import RequestsTransport
from bili_asr.platform_access import PlatformAccessError, require_platform_access
from bili_asr.sources.bilibili_api_gateway import BilibiliApiGateway


@pytest.fixture
def no_permission(monkeypatch):
    monkeypatch.delenv('BILI_PLATFORM_ACCESS_REFERENCE', raising=False)
    monkeypatch.delenv('BILI_CONTENT_PROCESSING_REFERENCE', raising=False)


def test_http_transport_denies_before_contacting_session(no_permission):
    transport = RequestsTransport()
    class DenyNetwork:
        def get(self, *args, **kwargs):
            pytest.fail('No HTTP call may be built without authorization')
    transport._session = DenyNetwork()
    with pytest.raises(PlatformAccessError):
        transport.get_json('https://api.bilibili.com/x/player/wbi/v2')
    with pytest.raises(PlatformAccessError):
        list(transport.get_stream('https://example.test/audio'))


def test_gateway_denies_before_building_coroutine_or_optional_page_scrape(no_permission):
    gateway = BilibiliApiGateway()
    def forbidden_call():
        pytest.fail('Upstream coroutine must not be created')
    with pytest.raises(PlatformAccessError):
        asyncio.run(gateway._await_upstream('get_video_parts', forbidden_call))
    with pytest.raises(PlatformAccessError):
        asyncio.run(gateway._resolve_w_webid(1))


def test_access_and_content_processing_references_are_separate(no_permission, monkeypatch):
    monkeypatch.setenv('BILI_PLATFORM_ACCESS_REFERENCE', 'private-evidence:platform-001')
    with pytest.raises(PlatformAccessError, match='BILI_CONTENT_PROCESSING_REFERENCE'):
        require_platform_access()
    monkeypatch.setenv('BILI_CONTENT_PROCESSING_REFERENCE', 'private-evidence:content-001')
    require_platform_access()
    monkeypatch.setenv('BILI_PLATFORM_ACCESS_REFERENCE', 'https://example.test/?cookie=secret')
    with pytest.raises(PlatformAccessError) as error:
        require_platform_access()
    assert 'secret' not in str(error.value)
