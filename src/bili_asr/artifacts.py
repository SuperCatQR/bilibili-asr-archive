"""Shared vocabulary for complete transcript bundles."""

REQUIRED_ARTIFACT_KEYS = ("srt_path", "vtt_path", "txt_path", "md_path", "raw_path")

# A v2 bundle always carries WebVTT; four-product bundles need republishing.
BUNDLE_SCHEMA = "archive-bundle-v2"
