"""Audio download layer (Task 3): playurl → preferred dash.audio stream → file.

Spec constraints (plan 002 / asr-archive-cli.md):
- Prefer dash.audio id 30216 (DTS/H.265 mux tier) then 30232 (Hi-Res flac),
  falling back to the highest remaining quality.
- The stream GET must carry Referer + UA headers or the CDN refuses it.
- Stream base URLs are short-lived signed URLs: used in the same run as the
  playurl probe, never persisted to the manifest.
- Manifest transition: needs_audio -> audio_ok.
- flac (30232) is remuxed to .m4a via ffmpeg when available; without
  ffmpeg the raw .flac is kept (pure-API fallback, AGENTS.md boundary).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any

from .bili_client import BiliClient
from .manifest import ManifestStore

AUDIO_DIR = os.path.join("audio")

# Spec preference order for dash.audio codec ids:
# 30216 DTS > 30232 Hi-Res flac > 30250 Dolby > (first listed: AAC et al.)
_AUDIO_ID_PREFERENCE = (30216, 30232, 30250)


class NoAudioStreamError(Exception):
    """Terminal: playurl returned no dash audio streams."""


class FFmpegUnavailable(Exception):
    """ffmpeg binary not found on PATH; caller keeps the raw container."""


def pick_audio_stream(
    streams: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    """Choose the best dash audio stream: 30216 first, then 30232, then
    the first remaining (Bilibili lists are already quality-descending)."""
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


def download_audio(
    client: BiliClient,
    bvid: str,
    out_path: str | os.PathLike[str],
    store: ManifestStore | None = None,
) -> str:
    """Download the preferred audio stream for bvid to out_path.

    Resumability: when out_path already exists the download is skipped and
    the manifest is still advanced. Returns the final file path (which may
    be a .flac sibling when 30232 was chosen and ffmpeg is unavailable).
    Raises NoAudioStreamError / RiskBudgetExhausted / GoneResponse.
    """
    root_of = lambda p: os.path.dirname(p) or "."
    audio_dir = root_of(out_path)
    os.makedirs(audio_dir, exist_ok=True)
    out_path = os.fspath(out_path)

    streams = client.fetch_playurl_audio(bvid)
    chosen = pick_audio_stream(streams)
    if chosen is None:
        raise NoAudioStreamError(f"{bvid}: playurl has no dash audio streams")

    url = _stream_url(chosen)
    is_flac = chosen.get("id") == 30232 or ".flac" in url

    final_path = out_path
    if os.path.exists(out_path):
        _mark_audio_ok(store, bvid, out_path)
        return out_path

    tmp_path = out_path + ".part"
    try:
        data = client.download_audio_stream(url)
        with open(tmp_path, "wb") as fh:
            fh.write(data)
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

    _mark_audio_ok(store, bvid, final_path)
    return final_path


def _mark_audio_ok(
    store: ManifestStore | None, bvid: str, final_path: str
) -> None:
    if store is None:
        return
    entry = dict(store.get(bvid) or {"bvid": bvid})
    entry["status"] = "audio_ok"
    # relative to the manifest root when the file lives under it
    root = store.root
    try:
        entry["audio_path"] = os.path.relpath(final_path, root)
    except ValueError:  # different drives (Windows)
        entry["audio_path"] = final_path
    store.upsert(entry)
