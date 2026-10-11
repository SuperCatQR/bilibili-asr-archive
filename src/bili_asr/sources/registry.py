"""Static provider composition; unsupported platforms fail before a request."""
from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path
from typing import Any

from bili_asr.platform_identity import ContentRef


class SourceRegistry:
    def __init__(self, *, youtube_factory: Callable[..., Any] | None = None, cookie_file: Path | None = None):
        self.cookie_file = cookie_file
        if youtube_factory is None:
            from bili_asr.sources.youtube_source import YoutubeSource
            youtube_factory = YoutubeSource
        self._factories = {"youtube": youtube_factory}

    def source(self, ref: ContentRef, *, checkpoint: Callable[[], None] | None = None):
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
