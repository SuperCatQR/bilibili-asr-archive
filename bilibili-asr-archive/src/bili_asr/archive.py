"""Archive writers for timestamped transcript outputs."""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
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


def _component_names(relative: str | os.PathLike[str]) -> tuple[str, ...] | None:
    try:
        path = Path(os.fspath(relative))
    except (TypeError, ValueError):
        return None
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        return None
    return path.parts


def _open_dir(parent_fd: int, name: str, *, create: bool = False) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW
    if create:
        try:
            os.mkdir(name, mode=0o755, dir_fd=parent_fd)
        except FileExistsError:
            pass
    return os.open(name, flags, dir_fd=parent_fd)


def _open_transcript_dirs(root: Path) -> dict[str, int]:
    root_fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW)
    try:
        transcripts_fd = _open_dir(root_fd, "transcripts", create=True)
    finally:
        os.close(root_fd)
    dirs: dict[str, int] = {}
    try:
        for name in ("srt", "txt", "md", "raw"):
            dirs[name] = _open_dir(transcripts_fd, name, create=True)
    except Exception:
        for fd in dirs.values():
            os.close(fd)
        os.close(transcripts_fd)
        raise
    dirs["_transcripts"] = transcripts_fd
    return dirs


def _fsync_fd(fd: int) -> None:
    os.fsync(fd)


def _write_at(directory_fd: int, name: str, content: bytes) -> None:
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=directory_fd)
    try:
        os.write(fd, content)
        _fsync_fd(fd)
    finally:
        os.close(fd)


def _replace_at(stage_fd: int, stage_name: str, target_fd: int, target_name: str) -> None:
    os.replace(stage_name, target_name, src_dir_fd=stage_fd, dst_dir_fd=target_fd)
    _fsync_fd(target_fd)


def _marker_payload(finals: Mapping[str, Path], root: Path, contents: Mapping[str, bytes]) -> bytes:
    artifacts = {
        key: {"path": finals[key].relative_to(root).as_posix(), "sha256": hashlib.sha256(contents[key]).hexdigest()}
        for key in _REQUIRED_ARTIFACT_KEYS
    }
    return (json.dumps({"schema": "archive-bundle-v1", "artifacts": artifacts}, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")


def _read_fd(fd: int, limit: int) -> bytes:
    data = bytearray()
    while len(data) <= limit:
        chunk = os.read(fd, min(65536, limit + 1 - len(data)))
        if not chunk:
            return bytes(data)
        data.extend(chunk)
    raise OSError("oversized archive file")


def _read_regular_at(directory_fd: int, name: str, limit: int | None = None) -> bytes:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise OSError("archive artifact is not regular")
        return _read_fd(fd, limit if limit is not None else max(info.st_size, 1) + 1)
    finally:
        os.close(fd)


def _open_declared(root: Path, relative: str) -> tuple[int, str] | None:
    parts = _component_names(relative)
    if not parts or len(parts) < 2:
        return None
    root_fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW)
    current = root_fd
    try:
        for part in parts[:-1]:
            nxt = _open_dir(current, part)
            os.close(current)
            current = nxt
        return current, parts[-1]
    except Exception:
        os.close(current)
        raise


def _owned_bundle_parts(paths: Mapping[str, str]) -> bool:
    expected_dirs = {"srt_path": "srt", "txt_path": "txt", "md_path": "md", "raw_path": "raw"}
    parsed: dict[str, str] = {}
    for key, directory in expected_dirs.items():
        parts = _component_names(paths[key])
        if parts is None or len(parts) != 3 or parts[:2] != ("transcripts", directory):
            return False
        parsed[key] = parts[2]
    if not parsed["srt_path"].endswith(".srt"):
        return False
    stem = parsed["srt_path"][:-4]
    if parsed["txt_path"] != stem + ".txt" or parsed["raw_path"] != stem + ".json":
        return False
    return parsed["md_path"].endswith(".md") and stem in parsed["md_path"][:-3]

def archive_bundle_complete(archive_root: str | os.PathLike[str], paths: Mapping[str, str]) -> bool:
    try:
        root = _lexical_archive_root(archive_root)
        if set(paths) != set(_REQUIRED_ARTIFACT_KEYS) or any(not isinstance(paths[key], str) for key in _REQUIRED_ARTIFACT_KEYS):
            return False
        if not _owned_bundle_parts(paths):
            return False
        with _bundle_lock(root):
            opened = {}
            marker_item = None
            try:
                for key in _REQUIRED_ARTIFACT_KEYS:
                    item = _open_declared(root, paths[key])
                    if item is None:
                        return False
                    opened[key] = item
                marker_item = _open_declared(root, paths["srt_path"] + BUNDLE_MARKER_SUFFIX)
                if marker_item is None:
                    return False
                document = json.loads(_read_regular_at(*marker_item, limit=_MARKER_MAX_BYTES).decode("ascii"))
                artifacts = document.get("artifacts") if isinstance(document, dict) and document.get("schema") == "archive-bundle-v1" else None
                if not isinstance(artifacts, dict) or set(artifacts) != set(_REQUIRED_ARTIFACT_KEYS):
                    return False
                for key in _REQUIRED_ARTIFACT_KEYS:
                    item = artifacts[key]
                    if not isinstance(item, dict) or set(item) != {"path", "sha256"} or item["path"] != paths[key] or not isinstance(item["sha256"], str) or len(item["sha256"]) != 64:
                        return False
                    if hashlib.sha256(_read_regular_at(*opened[key])).hexdigest() != item["sha256"]:
                        return False
                return True
            finally:
                for fd, _name in opened.values():
                    os.close(fd)
                if marker_item is not None:
                    os.close(marker_item[0])
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return False


def _invalidate_marker(directory_fd: int, marker_name: str) -> None:
    try:
        info = os.stat(marker_name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise OSError("archive bundle marker is not a regular file")
    os.unlink(marker_name, dir_fd=directory_fd)
    _fsync_fd(directory_fd)


def _publish_bundle(root: Path, finals: Mapping[str, Path], contents: Mapping[str, bytes]) -> None:
    with _bundle_lock(root):
        dirs = _open_transcript_dirs(root)
        stage_fd = None
        stage_name = ".archive-bundle-stage"
        try:
            transcripts_fd = dirs["_transcripts"]
            try:
                os.mkdir(stage_name, 0o700, dir_fd=transcripts_fd)
            except FileExistsError:
                raise OSError("archive staging directory already exists")
            stage_fd = _open_dir(transcripts_fd, stage_name)
            target_dirs = {key: dirs[{"srt_path": "srt", "txt_path": "txt", "md_path": "md", "raw_path": "raw"}[key]] for key in _REQUIRED_ARTIFACT_KEYS}
            names = {key: finals[key].name for key in _REQUIRED_ARTIFACT_KEYS}
            marker_name = names["srt_path"] + BUNDLE_MARKER_SUFFIX
            for key in _REQUIRED_ARTIFACT_KEYS:
                _write_at(stage_fd, names[key], contents[key])
            _write_at(stage_fd, marker_name, _marker_payload(finals, root, contents))
            _fsync_fd(stage_fd)
            _invalidate_marker(target_dirs["srt_path"], marker_name)
            for key in _REQUIRED_ARTIFACT_KEYS:
                _replace_at(stage_fd, names[key], target_dirs[key], names[key])
            _replace_at(stage_fd, marker_name, target_dirs["srt_path"], marker_name)
            _fsync_fd(transcripts_fd)
        finally:
            try:
                if stage_fd is not None:
                    for name in (*names.values(), marker_name):
                        try:
                            os.unlink(name, dir_fd=stage_fd)
                        except FileNotFoundError:
                            pass
                    os.close(stage_fd)
            finally:
                try:
                    os.rmdir(stage_name, dir_fd=transcripts_fd)
                except FileNotFoundError:
                    pass
            os.close(transcripts_fd)
            for name, fd in dirs.items():
                if name != "_transcripts":
                    os.close(fd)


def _lexical_archive_root(archive_root: str | os.PathLike[str]) -> Path:
    root = Path(os.path.abspath(os.fspath(archive_root)))
    fd = os.open(
        root,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        if not stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("archive publication path is unsafe")
    finally:
        os.close(fd)
    return root


#: A cue at or below this mean token score is worth a second look.
LOW_CONFIDENCE = 0.4

#: Two cue spans this close or closer are one captured stretch of audio.
#:
#: The model's result carries no VAD boundary list, so the transcript's own cue
#: intervals are the only capture evidence an artefact has; a cue boundary is a
#: punctuation or 60-character decision, not a capture boundary, so the spans
#: are merged back across pauses the shaper itself tolerates.  The value is
#: ``asr._CUE_MAX_GAP_SECONDS`` — the shaper's own pause threshold, so a gap it
#: would not have split on is not read back as a capture hole.
#:
#: Declared here rather than imported: the stated cross-layer rule is that
#: ``subtitles``/``audio``/``asr``/``archive`` never import each other, only
#: ``cli`` composing them (asr-archive-cli.md L61).  The two pure formatters
#: ``archive.py`` already imports from ``asr`` are the existing exception, so a
#: new coupling would widen it; the coupling is asserted by
#: ``test_capture_gap_seconds_follows_the_cue_shaper_threshold`` instead.
CAPTURE_GAP_SECONDS = 1.0


def _confidence_summary(segments: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize the model's own token confidence for one transcript.

    The values are the model's, not a judgement: they make quality measurable
    from the artefact alone, without a human reference transcript.
    """

    scores = [float(s["confidence"]) for s in segments
              if isinstance(s, dict) and isinstance(s.get("confidence"), (int, float))]
    if not scores:
        return {}
    return {
        "asr_mean_confidence": round(sum(scores) / len(scores), 3),
        "asr_low_confidence_cues": sum(1 for score in scores if score <= LOW_CONFIDENCE),
    }


def _merged_cue_spans(segments: list[dict[str, Any]]) -> list[tuple[float, float]]:
    """The transcript's cue intervals with adjacent ones fused into one span.

    Touching, overlapping and sub-:data:`CAPTURE_GAP_SECONDS`-adjacent intervals
    become a single span, which is what makes the result a *capture* estimate
    rather than a punctuation census.  Non-finite and reversed intervals are
    skipped: they cannot describe captured audio, and the quality checker
    already names them ``malformed``/``out_of_range``.

    **An interval of zero length (``end == start``) is skipped too.**  The rule
    is published here because A5 lets a reader recompute the capture facts from
    ``raw.json`` alone, and a zero-length cue is invisible audio either way it
    is read: counted, it inflates ``asr_vad_segments`` by a span that describes
    no captured stretch, and merged, it can bridge two real spans into one and
    inflate ``asr_vad_captured_s``.  Because the seconds of a zero-length span
    are ``0.0``, skipping it leaves the summed duration identical to counting
    it, so a recomputation that skips zero-length intervals reproduces every
    published value exactly.
    """

    spans: list[tuple[float, float]] = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        start, end = segment.get("start"), segment.get("end")
        if isinstance(start, bool) or isinstance(end, bool):
            continue
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            continue
        start, end = float(start), float(end)
        if not (math.isfinite(start) and math.isfinite(end)) or end <= start:
            continue
        spans.append((start, end))
    spans.sort()
    merged: list[tuple[float, float]] = []
    for start, end in spans:
        if merged and start - merged[-1][1] <= CAPTURE_GAP_SECONDS:
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end))
        else:
            merged.append((start, end))
    return merged


def _capture_summary(segments: list[dict[str, Any]], duration_s: Any) -> dict[str, Any]:
    """Record how much audio the VAD captured, as the cues testify.

    ``asr_vad_segments`` and ``asr_vad_captured_s`` describe the merged cue
    spans; the ratio divides them by the row's own ``duration_s`` and is clamped
    to ``[0, 1]`` because a ratio outside it is not a proportion of anything.
    The seconds stay **unclamped**, so a duration/cue contradiction remains
    visible in the artefact rather than being smoothed away here.

    The ratio divides the **published** ``asr_vad_captured_s`` — the 3-decimal
    value from the key above it, not the exact float sum — so a reader holding
    only the artefact reproduces it exactly.

    The ratio is omitted when ``duration_s`` is not positive and finite — a
    proportion of an unknown total is not a fact — or when it is a number too
    large to divide by, which the same rule covers.  The two absolute keys are
    still emitted, and an empty transcript legitimately reports zero of both.
    """

    merged = _merged_cue_spans(segments)
    captured_s = round(sum((end - start for start, end in merged), 0.0), 3)
    summary: dict[str, Any] = {
        "asr_vad_segments": len(merged),
        "asr_vad_captured_s": captured_s,
    }
    duration = duration_s
    if isinstance(duration, bool) or not isinstance(duration, (int, float)):
        return summary
    try:
        duration = float(duration)
    except OverflowError:
        # Arbitrary-precision ints beyond float range: an unusable denominator,
        # so the ratio is omitted rather than allowed to abort publication.
        return summary
    if not math.isfinite(duration) or duration <= 0:
        return summary
    summary["asr_vad_captured_ratio"] = round(min(1.0, max(0.0, captured_s / duration)), 3)
    return summary


def write_archive(archive_root: str | os.PathLike[str], entry: dict[str, Any], segments: list[dict[str, Any]], *, source: str, raw: Any | None = None, asr_provenance: Mapping[str, str] | None = None) -> dict[str, str]:
    """Publish one transcript bundle below the archive root.

    ``asr_provenance`` carries the ASR runner's redaction-safe configuration
    (model, revision, device, language, VAD, hotwords).  It is recorded in the
    raw sidecar and as ``asr_*`` frontmatter keys, so any transcript can be
    traced back to the model that produced it.  The subtitle path passes
    nothing and is unchanged.
    """
    try:
        root = _lexical_archive_root(archive_root)
    except OSError as exc:
        raise OSError("archive publication path is unsafe") from exc
    stem = archive_stem(entry)
    dirs = {name: root / "transcripts" / name for name in ("srt", "txt", "md", "raw")}
    bvid = str(entry["bvid"])
    srt_path = dirs["srt"] / f"{stem}.srt"
    txt_path = dirs["txt"] / f"{stem}.txt"
    md_path = dirs["md"] / f"{entry.get('pubdate_str', 'unknown')}_{stem}_{_safe_name(str(entry.get('title') or bvid))}.md"
    raw_path = dirs["raw"] / f"{stem}.json"
    frontmatter = {"bvid": bvid, "title": entry.get("title", ""), "date": entry.get("pubdate_str", ""), "duration_s": entry.get("duration_s", 0), "source": source, "url": archive_url(entry)}
    if source == "asr":
        frontmatter.update(_capture_summary(segments, frontmatter["duration_s"]))
    frontmatter.update(_confidence_summary(segments))
    if asr_provenance:
        frontmatter.update({f"asr_{key}": value for key, value in asr_provenance.items()})
    if entry.get("work_id") and not entry.get("unresolved"):
        frontmatter.update({"work_id": entry["work_id"], "page_index": entry.get("page_index"), "cid": entry.get("cid")})
    md = ("---\n" + "".join(f"{k}: {json.dumps(v, ensure_ascii=False)}\n" for k, v in frontmatter.items()) + "---\n\n" + segments_to_txt(segments) + "\n").encode("utf-8")
    if raw is None:
        raw = {"segments": segments, "source": source}
        if asr_provenance:
            raw["provenance"] = dict(asr_provenance)
    finals = {"srt_path": srt_path, "txt_path": txt_path, "md_path": md_path, "raw_path": raw_path}
    contents = {"srt_path": segments_to_srt(segments).encode(), "txt_path": (segments_to_txt(segments) + "\n").encode(), "md_path": md, "raw_path": (json.dumps(raw, ensure_ascii=False, indent=2) + "\n").encode()}
    _publish_bundle(root, finals, contents)
    return {key: os.path.relpath(path, root) for key, path in finals.items()}
