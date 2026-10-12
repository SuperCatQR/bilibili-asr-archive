"""Static provider composition; unsupported platforms fail before a request."""
from __future__ import annotations

from collections.abc import Callable, Mapping
import os
from pathlib import Path

from bili_asr.platform_identity import ContentRef
from bili_asr.sources.protocols import AcquisitionSource, SourceFactory
from bili_asr.sources.caption_policy import CaptionPolicy, YOUTUBE_CAPTION_POLICY


class SourceRegistry:
    def __init__(self, *, youtube_factory: SourceFactory | None = None, cookie_file: Path | None = None,
                 factories: Mapping[str, SourceFactory] | None = None,
                 caption_policies: Mapping[str, CaptionPolicy] | None = None):
        self.cookie_file = cookie_file
        if youtube_factory is None:
            def youtube_factory(*, checkpoint=None, cookie_file=None) -> AcquisitionSource:
                from bili_asr.sources.youtube_source import YoutubeSource
                return YoutubeSource(checkpoint=checkpoint, cookie_file=cookie_file)
        self._factories: dict[str, SourceFactory] = {"youtube": youtube_factory}
        self._factories.update(factories or {})
        self._caption_policies = {"youtube": YOUTUBE_CAPTION_POLICY}
        self._caption_policies.update(caption_policies or {})

    def caption_policy(self, ref: ContentRef) -> CaptionPolicy:
        try:
            return self._caption_policies[ref.platform]
        except KeyError:
            raise ValueError("platform has no registered caption acquisition policy") from None

    def source(self, ref: ContentRef, *, checkpoint: Callable[[], None] | None = None) -> AcquisitionSource:
        if not isinstance(ref, ContentRef) or ref.platform not in self._factories:
            raise ValueError("platform is not registered for single-video source ingestion")
        cookie_file = self.cookie_file
        if cookie_file is None:
            configured = os.environ.get("BILI_YOUTUBE_COOKIES", "").strip()
            cookie_file = Path(configured) if configured else None
        # The operator's credential path belongs only to this runtime adapter;
        # source facts, workflow payloads and durable result evidence never own it.
        return self._factories[ref.platform](checkpoint=checkpoint, cookie_file=cookie_file)


def source_registry(*, cookie_file: Path | None = None) -> SourceRegistry:
    return SourceRegistry(cookie_file=cookie_file)
