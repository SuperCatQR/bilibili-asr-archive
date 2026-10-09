"""Shared vocabulary for complete transcript bundles."""

from collections.abc import Mapping
from pathlib import PurePosixPath
from types import MappingProxyType

REQUIRED_ARTIFACT_KEYS = ("srt_path", "vtt_path", "txt_path", "md_path", "raw_path")

# A v2 bundle always carries WebVTT; four-product bundles need republishing.
BUNDLE_SCHEMA = "archive-bundle-v2"

BUNDLE_MARKER_NAME = ".bundle-ready"
BUNDLE_BASENAMES = MappingProxyType({
    "srt_path": "bundle.srt", "vtt_path": "bundle.vtt", "txt_path": "bundle.txt",
    "md_path": "bundle.md", "raw_path": "bundle.raw.json",
})


def owns_bundle_paths(paths: Mapping[str, str]) -> bool:
    """Require five canonical paths in exactly one transcripts/<identity>/ directory."""
    if set(paths) != set(REQUIRED_ARTIFACT_KEYS):
        return False
    directories = set()
    for key, basename in BUNDLE_BASENAMES.items():
        value = paths[key]
        if not isinstance(value, str) or "\\" in value:
            return False
        parts = tuple(value.split("/"))
        if (len(parts) != 3 or parts[0] != "transcripts" or parts[1] in {"", ".", ".."}
                or parts[2] != basename or PurePosixPath(value).as_posix() != value):
            return False
        directories.add(parts[:2])
    return len(directories) == 1
