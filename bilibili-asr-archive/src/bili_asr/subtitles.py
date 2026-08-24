"""Subtitle harvest layer: probe → download → SRT, manifest transitions.

Pure conversion helpers plus one orchestrating `harvest_subtitle` that
follows the spec state machine:

    sub_checked -> {subtitle_done | needs_audio}

Subtitle probe URLs are short-lived signed URLs: the JSON is downloaded
immediately in the same run as the probe and the URL is never persisted
(plan 002 Global Constraints).
"""

from __future__ import annotations

import json
import os
from typing import Any

from .bili_client import BiliClient
from .manifest import ManifestStore

RAW_SUB_DIR = os.path.join("subtitles", "raw")
SRT_DIR = os.path.join("transcripts", "srt")

# preference order for subtitle language selection
_LAN_PREFERENCE = ("ai-zh", "zh-CN", "zh-Hans", "en")


def pick_subtitle(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Choose the best subtitle entry: AI-zh first, then CC, then any."""
    if not entries:
        return None
    for lan in _LAN_PREFERENCE:
        for e in entries:
            if e.get("lan") == lan:
                return e
    return entries[0]


def _fmt_srt_time(seconds: float) -> str:
    millis = int(round(seconds * 1000))
    h, rem = divmod(millis, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def json_to_srt(doc: dict[str, Any]) -> str:
    """Convert Bilibili subtitle JSON ({body:[{from,to,content}]}) to SRT."""
    lines: list[str] = []
    for i, item in enumerate(doc.get("body") or [], start=1):
        start = _fmt_srt_time(float(item.get("from", 0.0)))
        end = _fmt_srt_time(float(item.get("to", 0.0)))
        content = str(item.get("content", "")).strip()
        lines.append(f"{i}\n{start} --> {end}\n{content}\n")
    return "\n".join(lines)


def harvest_subtitle(
    client: BiliClient,
    bvid: str,
    store: ManifestStore,
    archive_root: str | os.PathLike[str],
) -> str:
    """Probe subtitles for bvid, download if present, update the manifest.

    Returns the resulting manifest status: "subtitle_done" when a
    subtitle was downloaded and converted, "needs_audio" when the probe
    returned an empty list (Path A — expected without SESSDATA).
    """
    entries = client.probe_subs(bvid)
    chosen = pick_subtitle(entries)
    if chosen is None or not chosen.get("subtitle_url"):
        # Path A: empty AI/CC list without login is expected, not an error
        entry = dict(store.get(bvid) or {"bvid": bvid})
        entry.pop("last_api_error_code", None)
        entry["status"] = "needs_audio"
        store.upsert(entry)
        return "needs_audio"

    # Short-lived signed URL: download immediately, never persist it
    doc = client.download_subtitle(chosen["subtitle_url"])

    root = os.fspath(archive_root)
    raw_dir = os.path.join(root, RAW_SUB_DIR)
    srt_dir = os.path.join(root, SRT_DIR)
    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(srt_dir, exist_ok=True)
    raw_path = os.path.join(raw_dir, f"{bvid}.json")
    srt_path = os.path.join(srt_dir, f"{bvid}.srt")
    with open(raw_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
    with open(srt_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json_to_srt(doc))

    entry = dict(store.get(bvid) or {"bvid": bvid})
    entry.pop("last_api_error_code", None)
    # record language + file path only; no short-lived URL in the manifest
    entry["sub_lan"] = chosen.get("lan")
    entry["sub_lan_doc"] = chosen.get("lan_doc")
    entry["srt_path"] = os.path.relpath(srt_path, root)
    entry["status"] = "subtitle_done"
    store.upsert(entry)
    return "subtitle_done"
