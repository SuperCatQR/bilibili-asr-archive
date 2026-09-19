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

from .artifact_root import ArtifactRoots
from .bili_client import AmbiguousPageError, BiliClient
from .manifest import ManifestStore
from .page_identity import PageIdentity, apply_identity, artifact_stem, page_identity

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


def resolve_page_identity(
    client: BiliClient, target: PageIdentity | str
) -> PageIdentity:
    """Accept PageIdentity, or a bare bvid when pagelist length is 1."""
    if isinstance(target, PageIdentity):
        return target
    pages = client.list_pages(target)
    if len(pages) != 1:
        raise AmbiguousPageError(target, len(pages))
    return pages[0]


def _ledger_entry(store: ManifestStore, identity: PageIdentity) -> dict[str, Any]:
    existing = (
        store.get(identity.work_id)
        or store.get_compatible(identity.bvid)
        or store.get(identity.bvid)
        or {}
    )
    return apply_identity(existing, identity)


def harvest_subtitle(
    client: BiliClient,
    target: PageIdentity | str,
    store: ManifestStore,
    archive_root: str | os.PathLike[str],
    *,
    artifact_roots: ArtifactRoots | None = None,
) -> str:
    """Probe subtitles for one page, download if present, update the manifest.

    Returns the resulting manifest status: "subtitle_done" when a
    subtitle was downloaded and converted, "needs_audio" when the probe
    returned an empty list (Path A — expected without SESSDATA).

    Both harvested products (``subtitles/raw/{stem}.json`` and
    ``transcripts/srt/{stem}.srt``) are written under the artifact root when one
    is configured (contract §2.1/§4); the recorded ``srt_path`` stays the shipped
    root-relative string (D7).
    """
    if isinstance(target, str):
        existing = store.get_compatible(target) or store.get(target)
        if existing and (
            existing.get("unresolved")
            or existing.get("excluded_from_page_processing")
        ):
            raise ValueError(f"{target}: unresolved; not assigned to a page")
        store.migrate_legacy_rows(
            client.list_pages,
            artifact_roots,
            only_bvid=target,
        )
        migrated = store.get_compatible(target)
        if (
            migrated
            and migrated.get("work_id")
            and migrated.get("cid") is not None
            and not migrated.get("unresolved")
        ):
            identity = page_identity(
                str(migrated["bvid"]),
                int(migrated.get("page_index") or 0),
                int(migrated["cid"]),
                page_label=str(migrated.get("page_label") or ""),
            )
        else:
            identity = resolve_page_identity(client, target)
    else:
        identity = target
    entries = client.probe_subs(identity.bvid, cid=identity.cid)
    chosen = pick_subtitle(entries)
    if chosen is None or not chosen.get("subtitle_url"):
        # Path A: empty AI/CC list without login is expected, not an error
        entry = _ledger_entry(store, identity)
        entry.pop("last_api_error_code", None)
        entry["status"] = "needs_audio"
        store.upsert(entry)
        return "needs_audio"

    # Short-lived signed URL: download immediately, never persist it
    doc = client.download_subtitle(chosen["subtitle_url"])

    root = os.fspath(
        artifact_roots.write_base if artifact_roots is not None else archive_root
    )
    raw_dir = os.path.join(root, RAW_SUB_DIR)
    srt_dir = os.path.join(root, SRT_DIR)
    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(srt_dir, exist_ok=True)
    stem = artifact_stem(identity)
    raw_path = os.path.join(raw_dir, f"{stem}.json")
    srt_path = os.path.join(srt_dir, f"{stem}.srt")
    with open(raw_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
    with open(srt_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json_to_srt(doc))

    entry = _ledger_entry(store, identity)
    entry.pop("last_api_error_code", None)
    # record language + file path only; no short-lived URL in the manifest
    entry["sub_lan"] = chosen.get("lan")
    entry["sub_lan_doc"] = chosen.get("lan_doc")
    entry["srt_path"] = os.path.relpath(srt_path, root)
    entry["status"] = "subtitle_done"
    store.upsert(entry)
    return "subtitle_done"
