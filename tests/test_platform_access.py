"""Acquisition defaults to allowed; strict deployments require evidence."""
import asyncio

import pytest

from bili_asr.bili_client import RequestsTransport
from bili_asr.platform_access import PlatformAccessError, require_platform_access
from bili_asr.sources.bilibili_api_gateway import BilibiliApiGateway


@pytest.fixture
def no_permission(monkeypatch):
    monkeypatch.delenv('BILI_COMPLIANCE_ENABLED', raising=False)
    monkeypatch.setenv('BILI_PLATFORM_ACCESS_REQUIRE_EVIDENCE', '1')
    monkeypatch.delenv('BILI_PLATFORM_ACCESS_REFERENCE', raising=False)
    monkeypatch.delenv('BILI_CONTENT_PROCESSING_REFERENCE', raising=False)


def test_default_transport_allows_json_and_audio_without_evidence(monkeypatch):
    for name in ('BILI_COMPLIANCE_ENABLED', 'BILI_PLATFORM_ACCESS_REQUIRE_EVIDENCE', 'BILI_PLATFORM_ACCESS_REFERENCE',
                 'BILI_CONTENT_PROCESSING_REFERENCE', 'BILI_PUBLICATION_ENABLED'):
        monkeypatch.delenv(name, raising=False)
    calls = []

    class Response:
        status_code = 200

        def json(self):
            return {'code': 0}

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size):
            yield b'audio'

    class Session:
        def get(self, url, **kwargs):
            calls.append(url)
            return Response()

    transport = RequestsTransport()
    transport._session = Session()
    assert transport.get_json('https://api.bilibili.com/x/player/wbi/v2') == (200, {'code': 0})
    assert list(transport.get_stream('https://example.test/audio')) == [b'audio']
    assert len(calls) == 2


def test_default_gateway_allows_upstream_and_cached_optional_token(monkeypatch):
    for name in ('BILI_COMPLIANCE_ENABLED', 'BILI_PLATFORM_ACCESS_REQUIRE_EVIDENCE', 'BILI_PLATFORM_ACCESS_REFERENCE',
                 'BILI_CONTENT_PROCESSING_REFERENCE', 'BILI_PUBLICATION_ENABLED'):
        monkeypatch.delenv(name, raising=False)
    gateway = BilibiliApiGateway()

    async def upstream():
        return {'parts': []}

    assert asyncio.run(gateway._await_upstream('get_video_parts', upstream)) == {'parts': []}
    gateway._w_webid_by_mid[1] = 'cached-token'
    assert asyncio.run(gateway._resolve_w_webid(1)) == 'cached-token'


@pytest.mark.parametrize('value', ['', '0', 'true', ' 1'])
def test_only_exact_opt_in_requires_acquisition_evidence(monkeypatch, value):
    monkeypatch.delenv('BILI_COMPLIANCE_ENABLED', raising=False)
    monkeypatch.setenv('BILI_PLATFORM_ACCESS_REQUIRE_EVIDENCE', value)
    monkeypatch.delenv('BILI_PLATFORM_ACCESS_REFERENCE', raising=False)
    monkeypatch.delenv('BILI_CONTENT_PROCESSING_REFERENCE', raising=False)
    require_platform_access()


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


def test_compliance_policy_requires_evidence_without_separate_access_opt_in(monkeypatch):
    monkeypatch.setenv('BILI_COMPLIANCE_ENABLED', '1')
    monkeypatch.delenv('BILI_PLATFORM_ACCESS_REQUIRE_EVIDENCE', raising=False)
    monkeypatch.delenv('BILI_PLATFORM_ACCESS_REFERENCE', raising=False)
    with pytest.raises(PlatformAccessError):
        require_platform_access()
