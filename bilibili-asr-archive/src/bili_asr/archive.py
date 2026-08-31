"""Archive writers for timestamped transcript outputs."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import threading
from pathlib import Path
from typing import Any, Mapping

from .asr import segments_to_srt, segments_to_txt
from .page_identity import artifact_stem, page_identity, page_query_index

BUNDLE_MARKER_SUFFIX = ".bundle-ready"
_REQUIRED_ARTIFACT_KEYS = ("srt_path", "txt_path", "md_path", "raw_path")
_MARKER_MAX_BYTES = 8192
_BUNDLE_LOCKS: dict[str, threading.RLock] = {}
_BUNDLE_LOCKS_GUARD = threading.Lock()


def _bundle_lock(root: Path) -> threading.RLock:
    with _BUNDLE_LOCKS_GUARD:
        return _BUNDLE_LOCKS.setdefault(os.fspath(root), threading.RLock())


def _safe_name(value: str) -> str:
    value = "".join(ch for ch in value if ch not in '<>:"/\\|?*')
    return " ".join(value.split()).strip()[:120] or "untitled"


def archive_stem(entry: dict[str, Any]) -> str:
    bvid = str(entry["bvid"])
    if entry.get("unresolved") or not entry.get("work_id") or entry.get("cid") is None:
        return bvid
    return artifact_stem(page_identity(bvid, int(entry.get("page_index") or 0), int(entry["cid"]), page_label=str(entry.get("page_label") or "")))


def archive_url(entry: dict[str, Any]) -> str:
    url = f"https://www.bilibili.com/video/{entry['bvid']}"
    if not entry.get("unresolved") and entry.get("work_id") and int(entry.get("page_index") or 0) > 0:
        url += f"?p={page_query_index(int(entry['page_index']))}"
    return url


def bundle_marker_path(path: str | os.PathLike[str]) -> Path:
    return Path(os.fspath(path) + BUNDLE_MARKER_SUFFIX)


def _confined_regular(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root)
        info = path.lstat()
        return stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode)
    except (OSError, ValueError):
        return False


def _validate_publication_paths(root: Path, finals: Mapping[str, Path]) -> None:
    root = root.resolve()
    if not root.is_dir() or root.is_symlink():
        raise OSError("archive publication path is unsafe")
    for final in finals.values():
        relative = final.relative_to(root)
        current = root
        for component in relative.parts[:-1]:
            current /= component
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise OSError("archive publication path is unsafe")
        try:
            info = final.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise OSError("archive publication path is unsafe")


def _marker_payload(root: Path, finals: Mapping[str, Path], contents: Mapping[str, bytes]) -> bytes:
    artifacts = {key: {"path": finals[key].relative_to(root).as_posix(), "sha256": hashlib.sha256(contents[key]).hexdigest()} for key in _REQUIRED_ARTIFACT_KEYS}
    return (json.dumps({"schema": "archive-bundle-v1", "artifacts": artifacts}, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")


def _read_fd(fd: int, limit: int) -> bytes:
    data = bytearray()
    while len(data) <= limit:
        chunk = os.read(fd, min(65536, limit + 1 - len(data)))
        if not chunk:
            return bytes(data)
        data.extend(chunk)
    raise OSError("oversized archive file")


def archive_bundle_complete(archive_root: str | os.PathLike[str], paths: Mapping[str, str]) -> bool:
    try:
        root = Path(archive_root).resolve()
        if not root.is_dir() or root.is_symlink() or set(paths) != set(_REQUIRED_ARTIFACT_KEYS):
            return False
        with _bundle_lock(root):
            for key in _REQUIRED_ARTIFACT_KEYS:
                rel = Path(paths[key])
                if rel.is_absolute() or any(part in ("", ".", "..") for part in rel.parts) or not _confined_regular(root, root / rel):
                    return False
            marker = bundle_marker_path(root / paths["srt_path"])
            if not _confined_regular(root, marker) or len(marker.read_bytes()) > _MARKER_MAX_BYTES:
                return False
            document = json.loads(marker.read_text(encoding="ascii"))
            if not isinstance(document, dict) or document.get("schema") != "archive-bundle-v1":
                return False
            artifacts = document.get("artifacts")
            if not isinstance(artifacts, dict) or set(artifacts) != set(_REQUIRED_ARTIFACT_KEYS):
                return False
            for key in _REQUIRED_ARTIFACT_KEYS:
                item = artifacts[key]
                if not isinstance(item, dict) or set(item) != {"path", "sha256"} or item["path"] != paths[key] or not isinstance(item["sha256"], str) or len(item["sha256"]) != 64:
                    return False
                if hashlib.sha256((root / paths[key]).read_bytes()).hexdigest() != item["sha256"]:
                    return False
            return True
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return False


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW)
    try: os.fsync(fd)
    finally: os.close(fd)


def _write_staged(path: Path, content: bytes) -> None:
    with open(path, "wb") as handle:
        handle.write(content); handle.flush(); os.fsync(handle.fileno())


def _publish_bundle(finals: Mapping[str, Path], contents: Mapping[str, bytes]) -> None:
    root = next(iter(finals.values())).parents[2]
    with _bundle_lock(root):
        _validate_publication_paths(root, finals)
        parent = next(iter(finals.values())).parent
        stage = Path(tempfile.mkdtemp(prefix=".archive-bundle-", dir=parent))
        try:
            staged = {key: stage / finals[key].name for key in _REQUIRED_ARTIFACT_KEYS}
            for key in _REQUIRED_ARTIFACT_KEYS: _write_staged(staged[key], contents[key])
            _fsync_directory(stage)
            marker = stage / (finals["srt_path"].name + BUNDLE_MARKER_SUFFIX)
            _write_staged(marker, _marker_payload(root, finals, contents)); _fsync_directory(stage)
            marker_target = bundle_marker_path(finals["srt_path"])
            _validate_publication_paths(root, finals)
            if marker_target.exists():
                if not _confined_regular(root, marker_target): raise OSError("archive publication path is unsafe")
                marker_target.unlink()
            _fsync_directory(parent)
            for key in _REQUIRED_ARTIFACT_KEYS:
                _validate_publication_paths(root, finals); os.replace(staged[key], finals[key]); _fsync_directory(parent)
            _validate_publication_paths(root, finals); os.replace(marker, marker_target); _fsync_directory(parent)
        finally: shutil.rmtree(stage, ignore_errors=True)


def write_archive(archive_root: str | os.PathLike[str], entry: dict[str, Any], segments: list[dict[str, Any]], *, source: str, raw: Any | None = None) -> dict[str, str]:
    root = Path(os.fspath(archive_root)).resolve()
    if not root.exists() or root.is_symlink() or not root.is_dir(): raise OSError("archive publication path is unsafe")
    stem = archive_stem(entry); dirs = {name: root / "transcripts" / name for name in ("srt", "txt", "md", "raw")}
    with _bundle_lock(root):
        for directory in dirs.values():
            directory.mkdir(parents=True, exist_ok=True)
            if directory.is_symlink() or not directory.is_dir(): raise OSError("archive publication path is unsafe")
    bvid = str(entry["bvid"]); srt_path = dirs["srt"] / f"{stem}.srt"; txt_path = dirs["txt"] / f"{stem}.txt"
    md_path = dirs["md"] / f"{entry.get('pubdate_str', 'unknown')}_{stem}_{_safe_name(str(entry.get('title') or bvid))}.md"; raw_path = dirs["raw"] / f"{stem}.json"
    frontmatter = {"bvid": bvid, "title": entry.get("title", ""), "date": entry.get("pubdate_str", ""), "duration_s": entry.get("duration_s", 0), "source": source, "url": archive_url(entry)}
    if entry.get("work_id") and not entry.get("unresolved"): frontmatter.update({"work_id": entry["work_id"], "page_index": entry.get("page_index"), "cid": entry.get("cid")})
    md = ("---\n" + "".join(f"{k}: {json.dumps(v, ensure_ascii=False)}\n" for k, v in frontmatter.items()) + "---\n\n" + segments_to_txt(segments) + "\n").encode("utf-8")
    if raw is None: raw = {"segments": segments, "source": source}
    finals = {"srt_path": srt_path, "txt_path": txt_path, "md_path": md_path, "raw_path": raw_path}
    contents = {"srt_path": segments_to_srt(segments).encode(), "txt_path": (segments_to_txt(segments) + "\n").encode(), "md_path": md, "raw_path": (json.dumps(raw, ensure_ascii=False, indent=2) + "\n").encode()}
    _publish_bundle(finals, contents)
    return {key: os.path.relpath(path, root) for key, path in finals.items()}
