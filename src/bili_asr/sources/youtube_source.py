"""Bounded yt-dlp subprocess adapter for one YouTube processing unit.

Provider dictionaries, cookies and signed caption URLs stay inside this module.
The selected optional dependency and EJS solver are locked; invocation never
updates code, downloads remote JS components, or uses a download-archive ledger.
"""
from __future__ import annotations

from dataclasses import dataclass
import html
from importlib.metadata import PackageNotFoundError, version
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from typing import Callable

from bili_asr.artifact_inventory import require_no_links, require_regular_file
from bili_asr.platform_identity import ContentRef, require_platform
from bili_asr.source_identity import source_url
from bili_asr.sources.models import GatewayError, GatewayResponseError, GatewayShapeError, SubtitleTrack, SubtitleSegment, SubtitleBodyRead
from bili_asr.sources.protocols import SourceAccessObservation
from bili_asr.source_video import SourceVideoMetadata

YT_DLP_VERSION = "2026.8.19"
EJS_VERSION = "0.8.0"
_OUTPUT_LIMIT = 8 * 1024 * 1024


def youtube_runtime_requirements() -> tuple[dict, ...]:
    """Doctor consumes declarations; no installer or network runs here."""
    return ({"kind": "package", "name": "yt-dlp", "version": YT_DLP_VERSION},
            {"kind": "package", "name": "yt-dlp-ejs", "version": EJS_VERSION},
            {"kind": "executable", "name": "deno", "minimum_version": "2.3.0"},
            {"kind": "executable", "name": "ffmpeg"}, {"kind": "executable", "name": "ffprobe"})


def youtube_environment() -> dict:
    issues = []
    for name, expected in (("yt-dlp", YT_DLP_VERSION), ("yt-dlp-ejs", EJS_VERSION)):
        try:
            installed = version(name)
        except PackageNotFoundError:
            installed = None
        if installed != expected:
            issues.append(f"{name}: expected {expected}; installed {installed or 'missing'}")
    for executable in ("deno", "ffmpeg", "ffprobe"):
        if shutil.which(executable) is None:
            issues.append(f"{executable}: missing")
    if shutil.which("deno") is not None:
        try:
            result = subprocess.run(["deno", "--version"], capture_output=True, text=True, timeout=5, check=True)
            match = re.search(r"deno (\d+)\.(\d+)\.(\d+)", result.stdout)
            if match is None or tuple(map(int, match.groups())) < (2, 3, 0):
                issues.append("deno: version 2.3.0 or newer required")
        except (OSError, subprocess.SubprocessError):
            issues.append("deno: version could not be verified")
    return {"operation": "youtube-environment", "ready": not issues, "issues": issues,
            "requirements": list(youtube_runtime_requirements())}


def _kill(process: subprocess.Popen) -> None:
    if os.name == "nt":
        if process.poll() is None:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True, timeout=5, check=False)
    else:
        # An exited leader can leave a decoder in its owned process group.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=5)


def _failure(diagnostic: str) -> GatewayError:
    lowered = diagnostic.lower()
    mappings = (("sign in", "auth_failed"), ("private video", "auth_failed"),
                ("age-restricted", "auth_failed"), ("429", "rate_limited"),
                ("too many requests", "rate_limited"), ("timed out", "transport_failed"),
                ("network", "transport_failed"), ("unavailable", "youtube_unavailable"),
                ("removed", "youtube_unavailable"), ("javascript", "youtube_js_unavailable"))
    code = next((value for marker, value in mappings if marker in lowered), "youtube_extraction_failed")
    # Raw stderr often contains signed URLs or user paths. Expose only a code.
    return GatewayResponseError(code=code)


@dataclass(frozen=True, slots=True)
class YoutubeCaption:
    track: SubtitleTrack
    language: str
    original_language: str | None
    translated: bool | None
    extractor_version: str = YT_DLP_VERSION

    def provenance(self) -> dict:
        return {"track_id": self.track.track_id, "language": self.language,
                "original_language": self.original_language, "translated": self.translated,
                "extractor": "yt-dlp", "extractor_version": self.extractor_version,
                "normalization": "youtube-json3-incremental-v1"}


def normalize_json3(document: dict) -> tuple[SubtitleSegment, ...]:
    """Preserve each incremental caption event once, coalescing appends.

    YouTube json3 carries event durations and optional aAppend updates. A full
    repeated rolling window is collapsed only when the exact prefix and time
    overlap prove it repeats the prior event; evidence records this algorithm.
    """
    if not isinstance(document, dict) or not isinstance(document.get("events"), list):
        raise GatewayResponseError(code="youtube_caption_shape")
    result: list[SubtitleSegment] = []
    for event in document["events"]:
        if not isinstance(event, dict):
            raise GatewayResponseError(code="youtube_caption_shape")
        if "segs" not in event:  # Window positioning/format events are not cues.
            continue
        pieces = event["segs"]
        if not isinstance(pieces, list) or any(not isinstance(piece, dict) or not isinstance(piece.get("utf8"), str) for piece in pieces):
            raise GatewayResponseError(code="youtube_caption_shape")
        raw_text = html.unescape("".join(piece["utf8"] for piece in pieces))
        text = raw_text.strip()
        start, duration = event.get("tStartMs"), event.get("dDurationMs")
        if type(start) is not int or type(duration) is not int or start < 0 or duration <= 0:
            raise GatewayResponseError(code="youtube_caption_timeline")
        if not text:
            continue
        end = start + duration
        if result and event.get("aAppend") == 1 and start <= result[-1].end_ms:
            previous = result.pop()
            result.append(SubtitleSegment(previous.start_ms, max(end, previous.end_ms), (previous.text + raw_text).strip()))
            continue
        if result and start < result[-1].end_ms and text.startswith(result[-1].text):
            previous = result.pop()
            result.append(SubtitleSegment(previous.start_ms, max(end, previous.end_ms), text))
            continue
        result.append(SubtitleSegment(start, end, text))
    return tuple(result)


class YoutubeSource:
    def __init__(self, *, timeout_seconds: int = 120, checkpoint: Callable[[], None] | None = None,
                 cookie_file: Path | None = None, command: tuple[str, ...] | None = None):
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 1800:
            raise ValueError("YouTube timeout must be from 1 to 1800 seconds")
        self.timeout_seconds = timeout_seconds
        self.checkpoint = checkpoint
        self.cookie_file = cookie_file
        if cookie_file is not None:
            require_regular_file(cookie_file)
        self.command = command or (sys.executable, "-m", "yt_dlp")
        self._information: dict[ContentRef, dict] = {}
        self._captions: dict[ContentRef, tuple[YoutubeCaption, ...]] = {}

    def _run(self, arguments: list[str], ref: ContentRef, *, output_directory: Path) -> str:
        require_platform(ref, "youtube")
        url = source_url(ref)
        require_no_links(output_directory)
        if self.checkpoint:
            self.checkpoint()
        base = [*self.command, "--ignore-config", "--no-playlist", "--no-progress", "--no-warnings",
                "--socket-timeout", "15", "--retries", "2", "--fragment-retries", "2",
                "--js-runtimes", "deno", "--no-remote-components"]
        if self.cookie_file is not None:
            base += ["--cookies", os.fspath(self.cookie_file)]
        base += [*arguments, "--", url]
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as error:
            process = subprocess.Popen(base, cwd=output_directory, stdout=output, stderr=error,
                stdin=subprocess.DEVNULL, start_new_session=os.name != "nt",
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0)
            started = time.monotonic()
            try:
                while process.poll() is None:
                    if self.checkpoint:
                        self.checkpoint()
                    if time.monotonic() - started > self.timeout_seconds:
                        raise GatewayResponseError(code="youtube_timeout")
                    if os.fstat(output.fileno()).st_size > _OUTPUT_LIMIT or os.fstat(error.fileno()).st_size > _OUTPUT_LIMIT:
                        raise GatewayResponseError(code="youtube_output_budget")
                    time.sleep(.05)
                output.seek(0); error.seek(0)
                stdout = output.read(_OUTPUT_LIMIT + 1)
                stderr = error.read(_OUTPUT_LIMIT + 1)
                if len(stdout) > _OUTPUT_LIMIT or len(stderr) > _OUTPUT_LIMIT:
                    raise GatewayResponseError(code="youtube_output_budget")
                if process.returncode:
                    raise _failure(stderr.decode("utf-8", errors="replace"))
                if self.checkpoint:
                    self.checkpoint()
                return stdout.decode("utf-8")
            finally:
                _kill(process)

    def _info(self, ref: ContentRef) -> dict:
        if ref not in self._information:
            with tempfile.TemporaryDirectory(prefix="bili-asr-youtube-probe-") as name:
                try:
                    document = json.loads(self._run(["--dump-single-json", "--skip-download"], ref, output_directory=Path(name)))
                except (json.JSONDecodeError, UnicodeError):
                    raise GatewayResponseError(code="youtube_metadata_shape") from None
            if not isinstance(document, dict) or document.get("id") != ref.external_video_id or document.get("_type", "video") != "video":
                raise GatewayResponseError(code="youtube_identity_mismatch")
            if document.get("is_live") or document.get("live_status") in {"is_live", "is_upcoming"}:
                raise GatewayResponseError(code="youtube_live_unsupported")
            self._information[ref] = document
        return self._information[ref]

    def metadata(self, ref: ContentRef) -> SourceVideoMetadata:
        information = self._info(ref)
        duration = information.get("duration")
        if isinstance(duration, bool) or not isinstance(duration, (float, int)) or not math.isfinite(duration) or duration <= 0:
            raise GatewayResponseError(code="youtube_duration_invalid")
        # A missing/invalid release time must not suppress a valid upload
        # timestamp. A date-only upload_date remains private extractor evidence:
        # choosing midnight would fabricate a precision the provider did not give.
        timestamp = next((value for key in ("release_timestamp", "timestamp")
                          if type(value := information.get(key)) in (int, float)
                          and math.isfinite(value) and 0 < value <= 2**63 - 1), None)
        if timestamp is None and any(type(value := information.get(key)) in (int, float)
                and math.isfinite(value) and abs(value) > 2**63 - 1 for key in ("release_timestamp", "timestamp")):
            raise GatewayShapeError(code="youtube_metadata_shape")
        try:
            return SourceVideoMetadata(ref, information.get("title"), max(1, round(duration * 1000)),
                creator_external_id=information.get("channel_id"), creator_name=information.get("channel"),
                published_at=None if timestamp is None else int(timestamp), original_language=information.get("language"),
                observed_at=int(time.time()))
        except (ValueError, TypeError, OverflowError):
            raise GatewayShapeError(code="youtube_metadata_shape") from None

    async def get_parts(self, ref: ContentRef, video_title_fallback: str = ""):
        # Checkpoints belong to the caller's thread-owned archive connection.
        # The bounded external process performs IO; no SQLite callback is sent
        # to an asyncio worker thread.
        metadata = self.metadata(ref)
        return (YoutubePart(metadata),)

    def captions(self, ref: ContentRef) -> tuple[YoutubeCaption, ...]:
        if ref not in self._captions:
            information = self._info(ref)
            result = []
            for key, is_ai in (("subtitles", False), ("automatic_captions", True)):
                languages = information.get(key) or {}
                if not isinstance(languages, dict) or len(languages) > 512:
                    raise GatewayResponseError(code="youtube_caption_inventory_shape")
                for language, formats in languages.items():
                    if not isinstance(language, str) or not isinstance(formats, list):
                        raise GatewayResponseError(code="youtube_caption_inventory_shape")
                    candidate = next((item for item in formats if isinstance(item, dict) and item.get("ext") == "json3"), None)
                    if candidate is None:
                        if formats:
                            raise GatewayResponseError(code="youtube_caption_format_unsupported")
                        continue
                    track = SubtitleTrack(language, str(candidate.get("name") or language), is_ai,
                                          ("automatic:" if is_ai else "manual:") + language)
                    original_language = information.get("language")
                    translated = (None if original_language is None else
                                  language.split("-", 1)[0] != original_language.split("-", 1)[0])
                    result.append(YoutubeCaption(track, language, original_language, translated))
            self._captions[ref] = tuple(sorted(result, key=lambda item: (item.track.is_ai, item.translated is True, item.language)))
        return self._captions[ref]

    async def list_tracks(self, ref: ContentRef) -> tuple[SubtitleTrack, ...]:
        return tuple(item.track for item in self.captions(ref))

    async def verify_access(self, ref: ContentRef) -> SourceAccessObservation:
        self._info(ref)
        return SourceAccessObservation("credentialed" if self.cookie_file is not None else "anonymous", True)

    async def fetch_segments(self, track: SubtitleTrack, ref: ContentRef) -> tuple[SubtitleSegment, ...]:
        return (await self.read_body(track, ref)).segments

    async def read_body(self, track: SubtitleTrack, ref: ContentRef) -> SubtitleBodyRead:
        caption = next((item for item in self.captions(ref) if item.track == track), None)
        if caption is None:
            raise GatewayResponseError(code="youtube_caption_unlisted")
        def fetch():
            with tempfile.TemporaryDirectory(prefix="bili-asr-youtube-caption-") as name:
                root = Path(name)
                flags = ["--skip-download", "--sub-format", "json3", "--sub-langs", re.escape(caption.language),
                         "--output", "caption.%(ext)s", "--write-auto-subs" if track.is_ai else "--write-subs"]
                self._run(flags, ref, output_directory=root)
                files = list(root.glob("caption.*.json3"))
                if len(files) != 1:
                    raise GatewayResponseError(code="youtube_caption_body_unavailable")
                require_regular_file(files[0])
                if files[0].stat().st_size > _OUTPUT_LIMIT:
                    raise GatewayResponseError(code="youtube_caption_output_budget")
                try:
                    document = json.loads(files[0].read_text(encoding="utf-8"))
                except (UnicodeError, json.JSONDecodeError):
                    raise GatewayResponseError(code="youtube_caption_shape") from None
                segments = normalize_json3(document)
                count = sum("segs" in event for event in document["events"])
                return SubtitleBodyRead(segments,count,None if segments else "empty_body" if count == 0 else "empty_text")
        return fetch()

    def download_audio(self, ref: ContentRef, target: Path, *, staging_root: Path) -> Path:
        root = Path(staging_root).absolute()
        require_no_links(root)
        target = Path(target).absolute()
        if not target.is_relative_to(root):
            raise ValueError("YouTube audio target is outside caller staging")
        target.parent.mkdir(parents=True, exist_ok=True)
        output = self._run(["--no-simulate", "--format", "bestaudio/best", "--output", os.fspath(target) + ".%(ext)s",
                            "--print", "after_move:filepath"], ref, output_directory=root).strip().splitlines()
        if len(output) != 1:
            raise GatewayResponseError(code="youtube_audio_output_shape")
        result = Path(output[0]).absolute()
        if not result.is_relative_to(root) or result.stem != target.name or result.suffix.lower() not in {".webm", ".m4a", ".opus", ".ogg", ".mp4"}:
            raise GatewayResponseError(code="youtube_audio_output_path")
        require_no_links(result)
        require_regular_file(result)
        return result


@dataclass(frozen=True, slots=True)
class YoutubePart:
    metadata: SourceVideoMetadata

    @property
    def content_ref(self):
        return self.metadata.ref

    @property
    def title(self):
        return self.metadata.title

    @property
    def duration_ms(self):
        return self.metadata.duration_ms
