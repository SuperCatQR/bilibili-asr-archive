"""Typed gateway boundary for external Bilibili metadata sources.

Re-exports the application-owned DTOs, the gateway protocol, and the bounded
gateway exceptions.  The concrete adapter is imported explicitly from
``bili_asr.sources.bilibili_api_gateway`` because importing it requires the
pinned third-party package; this package ``__init__`` must stay importable
without ``bilibili_api``.
"""

from bili_asr.sources.models import (
    BilibiliGateway,
    GatewayError,
    GatewayNotFound,
    GatewayRateLimited,
    GatewayResponseError,
    GatewayShapeError,
    GatewayTransportError,
    SubtitleSegment,
    SubtitleTrack,
    UserVideoPage,
    VideoPart,
    VideoSummary,
    VideoTag,
)

__all__ = [
    "BilibiliGateway",
    "GatewayError",
    "GatewayNotFound",
    "GatewayRateLimited",
    "GatewayResponseError",
    "GatewayShapeError",
    "GatewayTransportError",
    "SubtitleSegment",
    "SubtitleTrack",
    "UserVideoPage",
    "VideoPart",
    "VideoSummary",
    "VideoTag",
]
