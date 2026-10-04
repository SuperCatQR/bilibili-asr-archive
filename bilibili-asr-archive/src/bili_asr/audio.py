"""Audio download layer (Task 3): playurl → preferred dash.audio stream → file.

Spec constraints (plan 002 / asr-archive-cli.md):
- Prefer dash.audio id 30216 (64K) then 30232 (132K), falling back to
  the highest remaining quality.
- The stream GET must carry Referer + UA headers or the CDN refuses it.
- Stream base URLs are short-lived signed URLs: used in the same run as the
  playurl probe, never persisted to the manifest.
- Manifest transition: needs_audio -> audio_ok.
- Explicit FLAC streams are converted losslessly to ALAC in .m4a when ffmpeg is available;
  without ffmpeg the raw .flac is kept (pure-API fallback, AGENTS.md boundary).
"""

from __future__ import annotations

import os
import secrets
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any

from .artifact_root import ArtifactRoots, iter_audio_paths
from .bili_client import BiliClient, StreamDownloadError
from .manifest import ManifestStore
from .page_identity import PageIdentity, apply_identity
from .subtitles import resolve_page_identity
from .path_policy import (
    confined_audio_file,
    confined_audio_path,
    descriptor_path,
    open_audio_directory,
)

AUDIO_DIR = os.path.join("audio")

# Spec preference order for dash.audio quality ids:
# 30216 (64K) > 30232 (132K) > 30250 (Dolby) > first listed.
_AUDIO_ID_PREFERENCE = (30216, 30232, 30250)


class NoAudioStreamError(Exception):
    """Terminal: playurl returned no dash audio streams."""


class FFmpegUnavailable(Exception):
    """ffmpeg binary not found on PATH; caller keeps the raw container."""


class AudioConversionError(RuntimeError):
    """The downloaded audio could not be converted to its archive container."""


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


def _stream_urls(stream: dict[str, Any]) -> tuple[str, ...]:
    """Primary and backup CDN addresses, normalized and deduplicated in order."""
    candidates = [stream.get("baseUrl"), stream.get("base_url")]
    for key in ("backupUrl", "backup_url"):
        backups = stream.get(key)
        if isinstance(backups, (list, tuple)):
            candidates.extend(backups)
    urls = []
    for value in candidates:
        if not isinstance(value, str):
            continue
        url = value.strip()
        if url.startswith("//"):
            url = "https:" + url
        if url.startswith(("https://", "http://")) and url not in urls:
            urls.append(url)
    return tuple(urls)


def _run_ffmpeg(src: str, dst: str) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise FFmpegUnavailable("ffmpeg not found on PATH")
    pass_fds = tuple(
        int(path.rsplit("/", 1)[-1])
        for path in (src, dst)
        if path.startswith(("/proc/self/fd/", "/dev/fd/"))
    )
    completed = subprocess.run(
        [ffmpeg, "-nostdin", "-y", "-loglevel", "error", "-i", src,
         "-map", "0:a:0", "-vn", "-c:a", "alac", "-f", "ipod", dst],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False,
        pass_fds=pass_fds,
    )
    if completed.returncode:
        # ffmpeg diagnostics can contain signed URLs or descriptor paths.
        raise AudioConversionError("ffmpeg audio conversion failed")


def _create_audio_stage(audio_fd: int, suffix: str) -> tuple[str, int]:
    """Create one unpredictable, process-owned stage entry."""
    for _ in range(8):
        name = f".audio-stage-{secrets.token_hex(16)}{suffix}"
        try:
            fd = os.open(
                name,
                os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=audio_fd,
            )
        except FileExistsError:
            continue
        return name, fd
    raise OSError("unable to allocate audio stage")


def _stage_is_regular(stage_fd: int) -> None:
    info = os.fstat(stage_fd)
    if not stat.S_ISREG(info.st_mode):
        raise OSError("audio stage is not regular")
    if info.st_size == 0:
        raise StreamDownloadError("audio stream produced an empty file")


def _existing_audio(out_path: str, roots: ArtifactRoots) -> str | None:
    """Return an existing confined, non-empty audio path.

    The recorded form is root-relative, so the candidates are derived once from
    the requested target and then validated at **each** base in order
    (contract §5, D6/D8): a copy written before the root was configured still
    lives at the archive root.
    """
    relative_out = os.path.relpath(out_path, roots.write_base)
    candidates = [relative_out, os.path.splitext(relative_out)[0] + ".flac"]
    for base, relative, confined in iter_audio_paths(roots, candidates):
        try:
            with confined_audio_file(base, relative) as safe_audio:
                if os.stat(safe_audio).st_size > 0:
                    return os.fspath(confined)
        except OSError:
            continue
    return None


def _archive_root_for_download(
    out_path: str | os.PathLike[str],
    store: ManifestStore | None,
    artifact_roots: ArtifactRoots | None = None,
) -> tuple[Path, Path]:
    """Return the base this download writes under and its confined target.

    A configured artifact root is the base outright (contract §4: a write resolves
    on ``write_base`` alone, never on which ``audio/`` directory happens to exist).
    Otherwise the base is today's derivation — the store's root, or the ``audio/``
    component of the requested path.
    """
    requested = os.fspath(out_path)
    if artifact_roots is not None:
        root = Path(os.path.abspath(os.fspath(artifact_roots.write_base)))
        relative = os.path.relpath(requested, root)
    elif store is not None:
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
    audio_fd = open_audio_directory(root, create=True)
    os.close(audio_fd)
    confined = confined_audio_path(root, relative, require_exists=False)
    if confined is None:
        raise OSError("invalid audio path")
    return root, confined

def download_audio(
    client: BiliClient,
    target: PageIdentity | str,
    out_path: str | os.PathLike[str],
    store: ManifestStore | None = None,
    *,
    artifact_roots: ArtifactRoots | None = None,
) -> str:
    """Download the preferred audio stream for one page to out_path.

    Resumability: when .m4a or .flac already exists (size>0), skip BEFORE any
    playurl/pagelist network call. Returns the final file path (which may be
    a .flac sibling when an explicit FLAC stream is selected and ffmpeg is
    unavailable).
    Raises NoAudioStreamError / StreamDownloadError / GoneResponse.

    ``artifact_roots`` names the root the product belongs to when it is not the
    archive root (contract §4); the recorded ``audio_path`` stays the shipped
    root-relative ``audio/<name>.<ext>`` string either way (D7).
    """
    out_path = os.fspath(out_path)
    archive_root, confined_out = _archive_root_for_download(
        out_path, store, artifact_roots
    )
    roots = artifact_roots if artifact_roots is not None else ArtifactRoots.of(archive_root)
    out_path = os.fspath(confined_out)
    if isinstance(target, PageIdentity):
        existing = _existing_audio(out_path, roots)
        if existing is not None:
            _mark_audio_ok(store, target, existing, artifact_roots)
            return existing
        identity = target
    else:
        identity = resolve_page_identity(client, target)
        existing = _existing_audio(out_path, roots)
        if existing is not None:
            _mark_audio_ok(store, identity, existing, artifact_roots)
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

    urls = _stream_urls(chosen)
    if not urls:
        raise NoAudioStreamError(f"{identity.work_id}: audio stream has no usable URL")
    url = urls[0]
    mime_type = str(chosen.get("mimeType") or chosen.get("mime_type") or "")
    is_flac = url.lower().split("?", 1)[0].endswith(".flac") or "flac" in mime_type.lower()

    final_name = confined_out.name
    final_path = os.fspath(archive_root / "audio" / final_name)
    audio_fd = open_audio_directory(archive_root)
    stage_name = ""
    stage_fd: int | None = None
    converted_name = ""
    converted_fd: int | None = None
    try:
        stage_name, stage_fd = _create_audio_stage(audio_fd, ".download")
        for url in urls:
            # A failed CDN can leave a prefix; each attempt starts from zero.
            os.ftruncate(stage_fd, 0)
            os.lseek(stage_fd, 0, os.SEEK_SET)
            try:
                client.download_audio_stream(url, descriptor_path(stage_fd))
                _stage_is_regular(stage_fd)
            except StreamDownloadError:
                if url == urls[-1]:
                    raise StreamDownloadError("all audio CDN addresses failed") from None
            else:
                break
        os.fsync(stage_fd)

        if is_flac:
            try:
                converted_name, converted_fd = _create_audio_stage(audio_fd, ".m4a")
                os.lseek(stage_fd, 0, os.SEEK_SET)
                _run_ffmpeg(descriptor_path(stage_fd), descriptor_path(converted_fd))
                _stage_is_regular(converted_fd)
                os.fsync(converted_fd)
                os.replace(
                    converted_name, final_name,
                    src_dir_fd=audio_fd, dst_dir_fd=audio_fd,
                )
                converted_name = ""
            except FFmpegUnavailable:
                flac_name = os.path.splitext(final_name)[0] + ".flac"
                os.replace(
                    stage_name, flac_name,
                    src_dir_fd=audio_fd, dst_dir_fd=audio_fd,
                )
                stage_name = ""
                final_path = os.fspath(archive_root / "audio" / flac_name)
        else:
            os.replace(
                stage_name, final_name,
                src_dir_fd=audio_fd, dst_dir_fd=audio_fd,
            )
            stage_name = ""
        os.fsync(audio_fd)
    finally:
        for owned_name in (converted_name, stage_name):
            if owned_name:
                try:
                    os.unlink(owned_name, dir_fd=audio_fd)
                except FileNotFoundError:
                    pass
        if converted_fd is not None:
            os.close(converted_fd)
        if stage_fd is not None:
            os.close(stage_fd)
        os.close(audio_fd)

    _mark_audio_ok(store, identity, final_path, artifact_roots)
    return final_path

def _mark_audio_ok(
    store: ManifestStore | None,
    identity: PageIdentity,
    final_path: str,
    artifact_roots: ArtifactRoots | None = None,
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
    # The value is recorded relative to the base that holds the file: the
    # configured root's bases when one was resolved (the write base first — it is
    # where a fresh download lands — then the archive root for a legacy copy),
    # else `store.root` exactly as before.  Computing it against the wrong base
    # is the silent failure of contract §15 correction 7: `os.path.relpath`
    # succeeds with `..` components, `confined_audio_path` refuses the shape, and
    # the row never reaches `audio_ok`. Reject that wiring error explicitly.
    bases = (
        artifact_roots.read_bases()
        if artifact_roots is not None
        else (Path(store.root).resolve(),)
    )
    for base in bases:
        try:
            final_rel = os.path.relpath(final_path, base)
        except ValueError:  # Windows across drives
            continue
        if confined_audio_path(base, final_rel, require_exists=True) is None:
            continue
        entry["audio_path"] = final_rel
        store.upsert(entry)
        return
    raise OSError("audio path outside archive")
