"""Audio download layer (Task 3): playurl → preferred dash.audio stream → file.

Spec constraints (plan 002 / asr-archive-cli.md):
- Prefer dash.audio id 30216 (64K) then 30232 (132K), falling back to
  the highest remaining quality.
- The stream GET must carry Referer + UA headers or the CDN refuses it.
- Stream base URLs are short-lived signed URLs: used in the same run as the
  playurl probe, never persisted to the manifest.
- Manifest transition: needs_audio -> audio_ok.
- Explicit FLAC streams are remuxed to .m4a via ffmpeg when available;
  without ffmpeg the raw .flac is kept (pure-API fallback, AGENTS.md boundary).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .bili_client import BiliClient
from .manifest import ManifestStore
from .page_identity import PageIdentity, apply_identity
from .subtitles import resolve_page_identity
from .path_policy import confined_audio_path

AUDIO_DIR = os.path.join("audio")

# Spec preference order for dash.audio quality ids:
# 30216 (64K) > 30232 (132K) > 30250 (Dolby) > first listed.
_AUDIO_ID_PREFERENCE = (30216, 30232, 30250)


class NoAudioStreamError(Exception):
    """Terminal: playurl returned no dash audio streams."""


class FFmpegUnavailable(Exception):
    """ffmpeg binary not found on PATH; caller keeps the raw container."""


def pick_audio_stream(
    streams: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    """Choose the best dash audio stream by the explicit quality order."""
    if not streams:
        return None
    for preferred in _AUDIO_ID_PREFERENCE:
        for s in streams:
            if s.get("id") == preferred:
                return s
    return streams[0]


def _stream_url(stream: dict[str, Any]) -> str:
    url = stream.get("baseUrl") or stream.get("base_url") or ""
    if url.startswith("//"):
        url = "https:" + url
    return url


def _run_ffmpeg(src: str, dst: str) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise FFmpegUnavailable("ffmpeg not found on PATH")
    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-i", src, "-c", "copy", dst],
        check=True,
    )


def _existing_audio(out_path: str) -> str | None:
    """Return an existing confined, non-empty audio path."""
    root = Path(out_path).resolve().parents[1]
    candidates = [out_path, os.path.splitext(out_path)[0] + ".flac"]
    for path in candidates:
        try:
            relative = os.path.relpath(path, root)
            confined = confined_audio_path(root, relative, require_exists=True)
            if confined is not None and confined.stat().st_size > 0:
                return str(confined)
        except OSError:
            continue
    return None


def _archive_root_for_download(
    out_path: str | os.PathLike[str], store: ManifestStore | None,
) -> tuple[Path, Path]:
    requested = os.fspath(out_path)
    if store is not None:
        root = Path(os.path.abspath(os.fspath(store.root)))
        relative = os.path.relpath(requested, root)
    else:
        candidate = Path(requested)
        if not candidate.is_absolute():
            candidate = Path(os.path.abspath(candidate))
        parts = candidate.parts
        try:
            audio_index = parts.index("audio")
        except ValueError:
            raise OSError("invalid audio path")
        if audio_index == 0:
            raise OSError("invalid archive root")
        if audio_index + 1 >= len(parts):
            raise OSError("invalid audio path")
        root = Path(os.path.join(*parts[:audio_index]))
        relative = os.path.join("audio", *parts[audio_index + 1 :])
    root_fd = os.open(
        os.fspath(root),
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        try:
            audio_fd = os.open(
                "audio",
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=root_fd,
            )
        except FileNotFoundError:
            os.mkdir("audio", mode=0o755, dir_fd=root_fd)
            audio_fd = os.open(
                "audio",
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=root_fd,
            )
        os.close(audio_fd)
    finally:
        os.close(root_fd)
    confined = confined_audio_path(root, relative, require_exists=False)
    if confined is None:
        raise OSError("invalid audio path")
    return root, confined

def download_audio(
    client: BiliClient,
    target: PageIdentity | str,
    out_path: str | os.PathLike[str],
    store: ManifestStore | None = None,
) -> str:
    """Download the preferred audio stream for one page to out_path.

    Resumability: when .m4a or .flac already exists (size>0), skip BEFORE any
    playurl/pagelist network call. Returns the final file path (which may be
    a .flac sibling when an explicit FLAC stream is selected and ffmpeg is
    unavailable).
    Raises NoAudioStreamError / StreamDownloadError / GoneResponse.
    """
    out_path = os.fspath(out_path)
    archive_root, confined_out = _archive_root_for_download(out_path, store)
    out_path = os.fspath(confined_out)
    if isinstance(target, PageIdentity):
        existing = _existing_audio(out_path)
        if existing is not None:
            _mark_audio_ok(store, target, existing)
            return existing
        identity = target
    else:
        identity = resolve_page_identity(client, target)
        existing = _existing_audio(out_path)
        if existing is not None:
            _mark_audio_ok(store, identity, existing)
            return existing

    audio_dir = os.path.dirname(out_path)
    if audio_dir != os.fspath(archive_root / "audio"):
        raise OSError("invalid audio path")

    streams = client.fetch_playurl_audio(identity.bvid, cid=identity.cid)
    chosen = pick_audio_stream(streams)
    if chosen is None:
        raise NoAudioStreamError(
            f"{identity.work_id}: playurl has no dash audio streams"
        )

    url = _stream_url(chosen)
    mime_type = str(chosen.get("mimeType") or chosen.get("mime_type") or "")
    is_flac = url.lower().split("?", 1)[0].endswith(".flac") or "flac" in mime_type.lower()

    final_path = out_path
    tmp_path = out_path + ".part"
    try:
        client.download_audio_stream(url, tmp_path)
        if is_flac:
            try:
                _run_ffmpeg(tmp_path, out_path)
                os.remove(tmp_path)
            except FFmpegUnavailable:
                final_path = os.path.splitext(out_path)[0] + ".flac"
                os.replace(tmp_path, final_path)
        else:
            os.replace(tmp_path, out_path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    _mark_audio_ok(store, identity, final_path)
    return final_path

def _mark_audio_ok(
    store: ManifestStore | None, identity: PageIdentity, final_path: str
) -> None:
    if store is None:
        return
    existing = (
        store.get(identity.work_id)
        or store.get_compatible(identity.bvid)
        or store.get(identity.bvid)
        or {}
    )
    entry = apply_identity(existing, identity)
    entry.pop("last_api_error_code", None)
    entry["status"] = "audio_ok"
    root = Path(store.root).resolve()
    try:
        final_rel = os.path.relpath(final_path, root)
    except ValueError:
        return
    confined = confined_audio_path(root, final_rel, require_exists=True)
    if confined is None:
        return
    entry["audio_path"] = final_rel
    store.upsert(entry)
