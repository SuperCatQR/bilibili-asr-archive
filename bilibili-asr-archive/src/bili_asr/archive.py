"""Archive writers for timestamped transcript outputs."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Mapping

from .asr import segments_to_srt, segments_to_txt
from .page_identity import artifact_stem, page_identity, page_query_index


BUNDLE_MARKER_SUFFIX = ".bundle-ready"
_REQUIRED_ARTIFACT_KEYS = ("srt_path", "txt_path", "md_path", "raw_path")


def _safe_name(value: str) -> str:
    value = "".join(ch for ch in value if ch not in '<>:"/\\|?*')
    return " ".join(value.split()).strip()[:120] or "untitled"


def archive_stem(entry: dict[str, Any]) -> str:
    """Filesystem stem for transcript outputs.

    Page-aware rows use `artifact_stem`. Unresolved legacy rows keep the
    bare bvid so they are never assigned a `work_id` or `.pN` path.
    """
    bvid = str(entry["bvid"])
    if entry.get("unresolved") or not entry.get("work_id"):
        return bvid
    if entry.get("cid") is None:
        return bvid
    identity = page_identity(
        bvid,
        int(entry.get("page_index") or 0),
        int(entry["cid"]),
        page_label=str(entry.get("page_label") or ""),
    )
    return artifact_stem(identity)


def archive_url(entry: dict[str, Any]) -> str:
    bvid = str(entry["bvid"])
    url = f"https://www.bilibili.com/video/{bvid}"
    if entry.get("unresolved") or not entry.get("work_id"):
        return url
    page_index = int(entry.get("page_index") or 0)
    if page_index > 0:
        url += f"?p={page_query_index(page_index)}"
    return url


def bundle_marker_path(path: str | os.PathLike[str]) -> Path:
    """Return the marker path associated with one required archive artifact."""
    return Path(os.fspath(path) + BUNDLE_MARKER_SUFFIX)


def archive_bundle_complete(
    archive_root: str | os.PathLike[str], paths: Mapping[str, str]
) -> bool:
    """Whether all returned transcript artifacts and their marker are present."""
    root = Path(archive_root)
    if any(key not in paths for key in _REQUIRED_ARTIFACT_KEYS):
        return False
    artifacts = [root / paths[key] for key in _REQUIRED_ARTIFACT_KEYS]
    return all(path.is_file() and not path.is_symlink() for path in artifacts) and bundle_marker_path(artifacts[0]).is_file()


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_staged(path: Path, content: bytes) -> None:
    with open(path, "wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _publish_bundle(finals: Mapping[str, Path], contents: Mapping[str, bytes]) -> None:
    parent = next(iter(finals.values())).parent
    stage = Path(tempfile.mkdtemp(prefix=".archive-bundle-", dir=parent))
    try:
        staged: dict[str, Path] = {}
        for key in _REQUIRED_ARTIFACT_KEYS:
            target = finals[key]
            staged[key] = stage / target.name
            _write_staged(staged[key], contents[key])
        _fsync_directory(stage)
        for key in _REQUIRED_ARTIFACT_KEYS:
            os.replace(staged[key], finals[key])
        marker = stage / (finals["srt_path"].name + BUNDLE_MARKER_SUFFIX)
        _write_staged(marker, b"bundle-ready\n")
        os.replace(marker, bundle_marker_path(finals["srt_path"]))
        _fsync_directory(parent)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def write_archive(
    archive_root: str | os.PathLike[str],
    entry: dict[str, Any],
    segments: list[dict[str, Any]],
    *,
    source: str,
    raw: Any | None = None,
) -> dict[str, str]:
    root = os.fspath(archive_root)
    bvid = str(entry["bvid"])
    stem = archive_stem(entry)
    dirs = {name: Path(root) / "transcripts" / name for name in ("srt", "txt", "md", "raw")}
    for directory in dirs.values():
        directory.mkdir(parents=True, exist_ok=True)

    srt_path = dirs["srt"] / f"{stem}.srt"
    txt_path = dirs["txt"] / f"{stem}.txt"
    title = _safe_name(str(entry.get("title") or bvid))
    md_name = f"{entry.get('pubdate_str', 'unknown')}_{stem}_{title}.md"
    md_path = dirs["md"] / md_name
    raw_path = dirs["raw"] / f"{stem}.json"

    frontmatter = {
        "bvid": bvid,
        "title": entry.get("title", ""),
        "date": entry.get("pubdate_str", ""),
        "duration_s": entry.get("duration_s", 0),
        "source": source,
        "url": archive_url(entry),
    }
    if entry.get("work_id") and not entry.get("unresolved"):
        frontmatter["work_id"] = entry["work_id"]
        frontmatter["page_index"] = entry.get("page_index")
        frontmatter["cid"] = entry.get("cid")
    md_lines = ["---\n"] + [f"{key}: {json.dumps(value, ensure_ascii=False)}\n" for key, value in frontmatter.items()] + ["---\n\n", segments_to_txt(segments), "\n"]
    if raw is None:
        raw = {"segments": segments, "source": source}
    raw_text = json.dumps(raw, ensure_ascii=False, indent=2) + "\n"
    finals = {"srt_path": srt_path, "txt_path": txt_path, "md_path": md_path, "raw_path": raw_path}
    contents = {
        "srt_path": segments_to_srt(segments).encode("utf-8"),
        "txt_path": (segments_to_txt(segments) + "\n").encode("utf-8"),
        "md_path": "".join(md_lines).encode("utf-8"),
        "raw_path": raw_text.encode("utf-8"),
    }
    _publish_bundle(finals, contents)
    return {key: os.path.relpath(path, root) for key, path in finals.items()}
