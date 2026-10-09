"""Bilibili acquisition adapters over the existing validated gateway/client.

The current schema is still Bilibili-only.  These adapters resolve real
provider extension ids at one boundary; they do not fabricate bvid/cid for a
different platform, write storage, or change any legacy artifact identity.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from bili_asr.artifact_root import ArtifactRoots
from bili_asr.page_identity import PageIdentity
from bili_asr.platform_identity import ContentRef, require_platform
from bili_asr.sources.models import (
    BilibiliGateway,
    GatewayShapeError,
    SubtitleSegment,
    SubtitleTrack,
    VideoPart,
)
from bili_asr.sources.protocols import SourceAccessObservation

if TYPE_CHECKING:
    from bili_asr.bili_client import BiliClient


class BilibiliMetadataSource:
    """MetadataSource implementation preserving the provider extension DTO."""

    def __init__(self, gateway: BilibiliGateway) -> None:
        self._gateway = gateway

    async def get_parts(
        self, ref: ContentRef, video_title_fallback: str = ""
    ) -> tuple[VideoPart, ...]:
        require_platform(ref, "bilibili")
        parts = await self._gateway.get_video_parts(
            ref.external_video_id, video_title_fallback=video_title_fallback
        )
        if any(part.bvid != ref.external_video_id for part in parts):
            raise GatewayShapeError()
        return parts


class BilibiliSubtitleSource:
    """SubtitleSource implementation with injected, existing part-id lookup."""

    def __init__(
        self,
        gateway: BilibiliGateway,
        resolve_cid: Callable[[ContentRef], int],
        *,
        credential_present: bool = False,
    ) -> None:
        self._gateway = gateway
        self._resolve_cid = resolve_cid
        self._credential_present = bool(credential_present)

    def _cid(self, ref: ContentRef) -> int:
        require_platform(ref, "bilibili")
        try:
            cid = self._resolve_cid(ref)
        except KeyError as exc:
            raise ValueError("source-identity: unresolved Bilibili part") from exc
        if type(cid) is not int or cid <= 0:
            raise ValueError("source-identity: Bilibili cid must be a positive integer")
        return cid

    async def list_tracks(self, ref: ContentRef) -> tuple[SubtitleTrack, ...]:
        cid = self._cid(ref)
        return await self._gateway.get_subtitle_tracks(ref.external_video_id, cid)

    async def fetch_segments(
        self, track: SubtitleTrack, ref: ContentRef
    ) -> tuple[SubtitleSegment, ...]:
        cid = self._cid(ref)
        return await self._gateway.fetch_subtitle_segments(track, ref.external_video_id, cid)

    async def verify_access(self, ref: ContentRef) -> SourceAccessObservation:
        self._cid(ref)
        if self._credential_present:
            await self._gateway.validate_subtitle_credentials()
            return SourceAccessObservation("credentialed", True)
        return SourceAccessObservation("anonymous", False)


class BilibiliAudioSource:
    """AudioSource implementation retaining the existing secure downloader."""

    def __init__(
        self,
        client: BiliClient,
        resolve_part: Callable[[ContentRef], PageIdentity],
    ) -> None:
        self._client = client
        self._resolve_part = resolve_part

    def download_audio(
        self, ref: ContentRef, target: Path, *, staging_root: Path
    ) -> Path:
        require_platform(ref, "bilibili")
        try:
            identity = self._resolve_part(ref)
        except KeyError as exc:
            raise ValueError("source-identity: unresolved Bilibili part") from exc
        if not isinstance(identity, PageIdentity) or identity.content_ref != ref:
            raise ValueError("source-identity: resolved Bilibili part does not match reference")
        if type(identity.cid) is not int or identity.cid <= 0:
            raise ValueError("source-identity: Bilibili cid must be a positive integer")
        # Importing the pure source protocols must not load client libraries.
        from bili_asr import audio

        return Path(audio.download_audio(
            self._client, identity, target, artifact_roots=ArtifactRoots.of(staging_root)
        ))


__all__ = ["BilibiliAudioSource", "BilibiliMetadataSource", "BilibiliSubtitleSource"]
