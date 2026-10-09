"""Source ports exercise real provider ids without changing legacy contracts."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import asdict

import pytest

from bili_asr.page_identity import artifact_stem, page_identity
from bili_asr.platform_identity import ContentRef
from bili_asr.services.subtitle_ingest import SubtitleIngestor, SubtitleSelection
from bili_asr.sources.bilibili_identity import (
    bilibili_source_url,
    legacy_bilibili_source_ref,
)
from bili_asr.sources.bilibili_source import (
    BilibiliAudioSource,
    BilibiliMetadataSource,
    BilibiliSubtitleSource,
)
from bili_asr.sources.models import (
    GatewayAuthenticationError,
    GatewayShapeError,
    SubtitleSegment,
    SubtitleTrack,
    VideoPart,
)
from bili_asr.sources.protocols import SourceAccessObservation
from bili_asr.storage import TranscriptRepository, open_database


def test_content_ref_preserves_opaque_case_sensitive_identity() -> None:
    ref = ContentRef("example", "AbC:/opaque", 2)
    assert ref != ContentRef("example", "abc:/opaque", 2)
    assert ref != ContentRef("other", ref.external_video_id, 2)
    assert ref != ContentRef("example", ref.external_video_id, 3)
    assert {ref: 7}[ContentRef("example", "AbC:/opaque", 2)] == 7


@pytest.mark.parametrize("fields", [
    {"platform": "Bilibili"}, {"platform": "with space"}, {"platform": ""},
    {"platform": 1}, {"external_video_id": ""}, {"external_video_id": "   "},
    {"external_video_id": "BVtest\n"}, {"external_video_id": "BVtest\x00"},
    {"external_video_id": "\ud800"}, {"external_video_id": 1},
    {"part_index": -1}, {"part_index": True}, {"part_index": 1.0},
])
def test_content_ref_rejects_unrepresentable_identity(fields) -> None:
    values = {"platform": "bilibili", "external_video_id": "BVtest", "part_index": 0}
    values.update(fields)
    with pytest.raises((TypeError, ValueError)):
        ContentRef(**values)


def test_runtime_ref_does_not_add_legacy_identity_or_dto_fields() -> None:
    identity = page_identity("BVtest", 2, 99, "第三分 P")
    assert identity.content_ref == ContentRef("bilibili", "BVtest", 2)
    assert identity.work_id == "BVtest:p2"
    assert artifact_stem(identity) == "BVtest.p2"
    assert asdict(identity) == {
        "work_id": "BVtest:p2", "bvid": "BVtest", "page_index": 2,
        "cid": 99, "page_label": "第三分 P",
    }
    part = VideoPart("BVtest", 2, 99, "第三分 P", 1000)
    assert part.content_ref == identity.content_ref
    assert asdict(part) == {
        "bvid": "BVtest", "page_index": 2, "cid": 99,
        "title": "第三分 P", "duration_ms": 1000,
    }


def _legacy_source() -> dict:
    return {"bvid": "BVtest", "pageIndex": 2, "videoPartId": 7,
            "url": "https://www.bilibili.com/video/BVtest/?p=3"}


def test_legacy_source_conversion_preserves_frozen_object() -> None:
    source = _legacy_source()
    before = deepcopy(source)
    ref = legacy_bilibili_source_ref(source)
    assert ref == ContentRef("bilibili", "BVtest", 2)
    assert bilibili_source_url(ref) == source["url"]
    assert source == before
    assert "platform" not in source


@pytest.mark.parametrize("fields", [
    {"platform": "bilibili"}, {"bvid": "BVtest\n"}, {"bvid": "BVtest\x00"},
    {"bvid": ""}, {"bvid": "../video"}, {"bvid": "\ud800"},
    {"pageIndex": True}, {"pageIndex": -1}, {"videoPartId": False},
    {"videoPartId": 0}, {"url": "https://www.bilibili.com/video/BVtest/?p=2"},
])
def test_legacy_source_conversion_refuses_invalid_or_new_contract(fields) -> None:
    source = _legacy_source()
    source.update(fields)
    with pytest.raises(ValueError, match="publication-content"):
        legacy_bilibili_source_ref(source)


class _Gateway:
    def __init__(self) -> None:
        self.calls = []
        self.parts = (VideoPart("BVtest", 2, 99, "第三分 P", 1000),)
        self.tracks = (SubtitleTrack("zh-CN", "中文", False, "track-1"),)
        self.segments = (SubtitleSegment(0, 1000, "测试字幕"),)
        self.access_error = None

    async def get_video_parts(self, bvid, video_title_fallback=""):
        self.calls.append(("parts", bvid, video_title_fallback))
        return self.parts

    async def get_subtitle_tracks(self, bvid, cid):
        self.calls.append(("tracks", bvid, cid))
        return self.tracks

    async def fetch_subtitle_segments(self, track, bvid, cid):
        self.calls.append(("body", track.track_id, bvid, cid))
        return self.segments

    async def validate_subtitle_credentials(self):
        self.calls.append(("access",))
        if self.access_error is not None:
            raise self.access_error


def test_metadata_adapter_preserves_real_provider_extension_fields() -> None:
    gateway = _Gateway()
    parts = asyncio.run(BilibiliMetadataSource(gateway).get_parts(
        ContentRef("bilibili", "BVtest"), video_title_fallback="视频标题"
    ))
    assert parts == gateway.parts
    assert parts[0].cid == 99
    assert parts[0].content_ref.part_index == 2
    assert gateway.calls == [("parts", "BVtest", "视频标题")]


def test_metadata_adapter_refuses_another_videos_parts() -> None:
    gateway = _Gateway()
    gateway.parts = (VideoPart("BVother", 0, 55, "错误视频", 1000),)
    with pytest.raises(GatewayShapeError):
        asyncio.run(BilibiliMetadataSource(gateway).get_parts(ContentRef("bilibili", "BVtest")))


def test_subtitle_adapter_resolves_real_cid_from_content_ref() -> None:
    gateway = _Gateway()
    ref = ContentRef("bilibili", "BVtest", 2)
    source = BilibiliSubtitleSource(gateway, {ref: 99}.__getitem__, credential_present=True)
    assert asyncio.run(source.list_tracks(ref)) == gateway.tracks
    assert asyncio.run(source.fetch_segments(gateway.tracks[0], ref)) == gateway.segments
    assert asyncio.run(source.verify_access(ref)) == SourceAccessObservation("credentialed", True)
    assert gateway.calls == [("tracks", "BVtest", 99), ("body", "track-1", "BVtest", 99), ("access",)]


def test_anonymous_empty_inventory_is_not_verified_login() -> None:
    gateway = _Gateway()
    ref = ContentRef("bilibili", "BVtest", 2)
    source = BilibiliSubtitleSource(gateway, {ref: 99}.__getitem__)
    assert asyncio.run(source.verify_access(ref)) == SourceAccessObservation("anonymous", False)
    assert gateway.calls == []


@pytest.mark.parametrize("cid", [0, -1, True, "99"])
def test_subtitle_adapter_refuses_missing_or_fabricated_cid(cid) -> None:
    gateway = _Gateway()
    source = BilibiliSubtitleSource(gateway, lambda ref: cid)
    with pytest.raises(ValueError, match="cid must be a positive integer"):
        asyncio.run(source.list_tracks(ContentRef("bilibili", "BVtest")))
    assert gateway.calls == []


def test_subtitle_adapter_rejects_unresolved_part_and_wrong_platform_before_network() -> None:
    gateway = _Gateway()
    source = BilibiliSubtitleSource(gateway, {}.__getitem__)
    with pytest.raises(ValueError, match="unresolved Bilibili part"):
        asyncio.run(source.list_tracks(ContentRef("bilibili", "BVtest")))
    with pytest.raises(ValueError, match="only supports bilibili"):
        asyncio.run(source.list_tracks(ContentRef("example", "BVtest")))
    with pytest.raises(ValueError, match="only supports bilibili"):
        asyncio.run(BilibiliMetadataSource(gateway).get_parts(ContentRef("example", "BVtest")))
    assert gateway.calls == []


def test_audio_source_keeps_actual_container_path_and_staging_root(tmp_path, monkeypatch) -> None:
    from bili_asr import audio

    identity = page_identity("BVtest", 2, 99)
    staging = tmp_path / "stage"
    requested = staging / "audio" / "BVtest.p2.m4a"
    actual = requested.with_suffix(".flac")
    client = object()
    calls = []

    def download(given_client, given_identity, target, *, artifact_roots):
        calls.append((given_client, given_identity, target, artifact_roots.write_base))
        return str(actual)

    monkeypatch.setattr(audio, "download_audio", download)
    source = BilibiliAudioSource(client, {identity.content_ref: identity}.__getitem__)
    assert source.download_audio(identity.content_ref, requested, staging_root=staging) == actual
    assert calls == [(client, identity, requested, staging)]
    with pytest.raises(ValueError, match="only supports bilibili"):
        source.download_audio(ContentRef("example", "BVtest", 2), requested, staging_root=staging)
    assert len(calls) == 1


def test_audio_source_refuses_resolver_identity_mismatch_before_downloading(tmp_path) -> None:
    source = BilibiliAudioSource(object(), lambda ref: page_identity("BVother", 2, 99))
    with pytest.raises(ValueError, match="does not match reference"):
        source.download_audio(ContentRef("bilibili", "BVtest", 2), tmp_path / "audio.m4a", staging_root=tmp_path)


def _seed_part(connection) -> None:
    with connection:
        connection.execute("INSERT INTO bilibili_users VALUES (1, 'test', 1, 1)")
        connection.execute("INSERT INTO videos VALUES ('BVtest', 1, 1, 'test', 1, 1, 1)")
        connection.execute(
            "INSERT INTO video_parts VALUES (7, 'BVtest', 2, 99, '第三分 P', 1000, 'metadata_collected', 1, 1)"
        )


def test_subtitle_ingestor_uses_explicit_source_and_preserves_storage_identity(tmp_path) -> None:
    connection = open_database(tmp_path)
    try:
        _seed_part(connection)
        gateway = _Gateway()
        ref = ContentRef("bilibili", "BVtest", 2)
        source = BilibiliSubtitleSource(gateway, {ref: 99}.__getitem__)
        result = SubtitleIngestor(None, TranscriptRepository(connection), source=source).harvest(
            SubtitleSelection(bvid="BVtest", page_index=2, limit=1)
        )
        assert result.stored == 1
        assert result.parts[0].work_id == "BVtest:p2"
        row = connection.execute("SELECT video_part_id, source_kind, language FROM transcripts").fetchone()
        assert tuple(row) == (7, "subtitle-cc", "zh-CN")
        assert gateway.calls == [("tracks", "BVtest", 99), ("body", "track-1", "BVtest", 99)]
    finally:
        connection.close()


@pytest.mark.parametrize("access_error, expected", [
    (None, ("no-subtitle", None, 1)),
    (GatewayAuthenticationError(), ("failed", "auth_error", 0)),
])
def test_legacy_gateway_injection_preserves_authenticated_empty_evidence(tmp_path, access_error, expected) -> None:
    connection = open_database(tmp_path)
    try:
        _seed_part(connection)
        gateway = _Gateway()
        gateway.tracks = ()
        gateway.access_error = access_error
        result = SubtitleIngestor(gateway, TranscriptRepository(connection), credential_present=True).harvest(
            SubtitleSelection(bvid="BVtest", page_index=2, limit=1)
        )
        row = connection.execute("SELECT outcome, error_code, credential_verified FROM acquisition_attempts").fetchone()
        assert tuple(row) == expected
        assert result.parts[0].outcome == expected[0]
        assert gateway.calls == [("tracks", "BVtest", 99), ("access",)]
    finally:
        connection.close()


def test_verified_anonymous_source_does_not_create_bilibili_login_evidence(tmp_path) -> None:
    class AnonymousSource:
        async def list_tracks(self, ref):
            return ()

        async def verify_access(self, ref):
            return SourceAccessObservation("anonymous", True)

    connection = open_database(tmp_path)
    try:
        _seed_part(connection)
        result = SubtitleIngestor(
            None, TranscriptRepository(connection), source=AnonymousSource(), credential_present=True,
        ).harvest(SubtitleSelection(bvid="BVtest", page_index=2, limit=1))
        assert result.no_subtitle == 1
        row = connection.execute("SELECT credential_verified, absence_verified FROM acquisition_attempts").fetchone()
        assert tuple(row) == (0, 0)
    finally:
        connection.close()
