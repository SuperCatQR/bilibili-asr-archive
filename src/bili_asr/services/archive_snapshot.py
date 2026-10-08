"""Portable, validated snapshots of the database and its external artifacts."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import errno
import hashlib
import json
import lzma
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile
import time
from typing import BinaryIO, Iterator
import unicodedata
import uuid
import zipfile
import zlib

from bili_asr import __version__
from bili_asr.archive import BUNDLE_MARKER_NAME, _BUNDLE_BASENAMES as _BUNDLE_NAMES
from bili_asr.archive_maintenance import archive_access
from bili_asr.artifacts import BUNDLE_SCHEMA
from bili_asr.storage.snapshots import (
    create_database_snapshot,
    recover_interrupted_jobs,
    required_artifacts,
    validate_snapshot_database,
)


_FORMAT = "bili-asr-snapshot"
_FORMAT_VERSION = 1
_MANIFEST_NAME = "snapshot.json"
_ARTIFACT_DIRECTORIES = frozenset({"audio", "transcripts", "documents", "subtitles"})
_CHUNK_SIZE = 1024 * 1024
_MANIFEST_LIMIT = 16 * 1024 * 1024
_MARKER_LIMIT = 8192
_HASH_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_RESERVED_PATTERN = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9\u00b9\u00b2\u00b3]|LPT[1-9\u00b9\u00b2\u00b3])\Z", re.IGNORECASE)
_TEMP_SUFFIXES = frozenset({".tmp", ".temp", ".partial", ".part", ".download"})


class SnapshotError(ValueError):
    """The archive cannot be safely saved, checked or restored."""


@contextmanager
def _snapshot_errors() -> Iterator[None]:
    try:
        yield
    except SnapshotError:
        raise
    except (OSError, ValueError, sqlite3.Error, zipfile.BadZipFile,
            zipfile.LargeZipFile, RuntimeError, EOFError, zlib.error, lzma.LZMAError) as exc:
        raise SnapshotError(str(exc)) from exc


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(path))


def _no_links(path: Path) -> None:
    for component in (path, *path.parents):
        if component.is_symlink() or (
            hasattr(component, "is_junction") and component.is_junction()
        ):
            raise SnapshotError(f"snapshot paths cannot use symlinks or junctions: {component}")


def _path_key(path: str) -> tuple[str, ...]:
    if not isinstance(path, str) or not path or "\\" in path:
        raise SnapshotError(f"unsafe snapshot path: {path!r}")
    parts = tuple(path.split("/"))
    for part in parts:
        if (not part or part in {".", ".."} or part.endswith((".", " "))
                or any(ord(char) < 32 or ord(char) == 127 or char in '<>:"|?*' for char in part)
                or len(part.encode("utf-8")) > 255
                or _RESERVED_PATTERN.fullmatch(part.split(".", 1)[0].rstrip(" "))):
            raise SnapshotError(f"unsafe or non-portable snapshot path: {path!r}")
    if path != "archive.db" and (len(parts) < 2 or parts[0] not in _ARTIFACT_DIRECTORIES):
        raise SnapshotError(f"unsupported snapshot artifact path: {path!r}")
    return parts


def _canonical(path: str) -> str:
    return unicodedata.normalize("NFC", path).casefold()


def _check_path_collisions(paths: list[str]) -> None:
    files: set[str] = set()
    prefixes: dict[str, str] = {}
    for path in paths:
        parts = _path_key(path)
        canonical = _canonical(path)
        if canonical in files:
            raise SnapshotError(f"duplicate or colliding snapshot path: {path}")
        files.add(canonical)
        for length in range(1, len(parts) + 1):
            prefix = "/".join(parts[:length])
            key = _canonical(prefix)
            previous = prefixes.setdefault(key, prefix)
            if previous != prefix:
                raise SnapshotError(f"case or Unicode collision: {previous!r} and {prefix!r}")
    for path in paths:
        parts = path.split("/")
        if any(_canonical("/".join(parts[:length])) in files
               for length in range(1, len(parts))):
            raise SnapshotError(f"snapshot file is also a parent directory: {path}")


def _regular_file(path: Path) -> os.stat_result:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise SnapshotError(f"snapshot source is not a regular file: {path}")
    _no_links(path)
    return info


def _temporary_component(name: str) -> bool:
    return (name.startswith((".audio-stage-", ".archive-bundle-stage-", ".bili-asr-probe-", ".render-", ".import-"))
            or name == ".tmp"
            or Path(name).suffix.lower() in _TEMP_SUFFIXES)


def _collect_artifacts(bases: tuple[Path, ...]) -> dict[str, Path]:
    found: dict[str, Path] = {}

    def unreadable(error: OSError) -> None:
        raise SnapshotError(f"artifact directory cannot be fully read: {error.filename}") from error

    for base in bases:
        _no_links(base)
        if not base.is_dir():
            raise SnapshotError(f"archive or artifact root is not a directory: {base}")
        for name in sorted(_ARTIFACT_DIRECTORIES):
            directory = base / name
            if not directory.exists() and not directory.is_symlink():
                continue
            if directory.is_symlink() or not directory.is_dir():
                raise SnapshotError(f"artifact directory is unsafe: {directory}")
            for current, directories, files in os.walk(directory, followlinks=False, onerror=unreadable):
                current_path = Path(current)
                for entry in sorted(directories + files):
                    path = current_path / entry
                    if _temporary_component(entry):
                        raise SnapshotError(f"unfinished temporary artifact must be resolved before saving: {path}")
                    _no_links(path)
                for entry in sorted(files):
                    path = current_path / entry
                    _regular_file(path)
                    key = path.relative_to(base).as_posix()
                    _path_key(key)
                    found.setdefault(key, path)
    _check_path_collisions(list(found))
    return found


def _sync_file(stream: BinaryIO) -> None:
    stream.flush()
    os.fsync(stream.fileno())


def _sync_directory(path: Path) -> None:
    if os.name != "posix" or not hasattr(os, "O_DIRECTORY"):
        return
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        try:
            os.fsync(descriptor)
        except OSError as exc:
            if exc.errno not in {errno.EINVAL, errno.ENOTSUP}:
                raise
    finally:
        os.close(descriptor)


def _stream_hash(source: BinaryIO, destination: BinaryIO | None = None) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    while chunk := source.read(_CHUNK_SIZE):
        digest.update(chunk)
        size += len(chunk)
        if destination is not None:
            destination.write(chunk)
    return size, digest.hexdigest()


def _check_references(database: Path, files: dict[str, dict[str, object]]) -> None:
    for path, expected_hash in required_artifacts(database).items():
        _path_key(path)
        actual = files.get(path)
        if actual is None:
            raise SnapshotError(f"database references a missing artifact: {path}")
        if expected_hash is not None and actual["sha256"] != expected_hash:
            raise SnapshotError(f"database artifact hash mismatch: {path}")


def _check_bundle_markers(bundle: zipfile.ZipFile, files: dict[str, dict[str, object]]) -> None:
    for marker_path in files:
        parts = marker_path.split("/")
        if parts[-1] != BUNDLE_MARKER_NAME:
            continue
        if len(parts) != 3 or parts[0] != "transcripts":
            raise SnapshotError(f"invalid transcript bundle marker path: {marker_path}")
        member = bundle.getinfo(marker_path)
        if member.file_size > _MARKER_LIMIT:
            raise SnapshotError(f"oversized transcript bundle marker: {marker_path}")
        try:
            with bundle.open(member) as source:
                encoded = source.read(_MARKER_LIMIT + 1)
            if len(encoded) > _MARKER_LIMIT:
                raise SnapshotError(f"oversized transcript bundle marker: {marker_path}")
            document = json.loads(encoded.decode("ascii"), object_pairs_hook=_manifest_object)
        except (UnicodeError, ValueError, RecursionError) as exc:
            raise SnapshotError(f"invalid transcript bundle marker: {marker_path}") from exc
        if (not isinstance(document, dict) or document.get("schema") != BUNDLE_SCHEMA
                or not isinstance(document.get("artifacts"), dict)
                or set(document["artifacts"]) != set(_BUNDLE_NAMES)):
            raise SnapshotError(f"invalid transcript bundle marker: {marker_path}")
        directory = "/".join(parts[:-1])
        for key, basename in _BUNDLE_NAMES.items():
            item = document["artifacts"][key]
            path = f"{directory}/{basename}"
            entry = files.get(path)
            if (not isinstance(item, dict) or set(item) != {"path", "sha256"}
                    or item.get("path") != path or entry is None
                    or item.get("sha256") != entry["sha256"]):
                raise SnapshotError(f"transcript bundle marker hash or path mismatch: {marker_path}")


def _refuse_active_jobs(database: Path) -> None:
    connection = sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)
    try:
        row = connection.execute(
            "SELECT job_id FROM workflow_jobs WHERE status = 'running' "
            "AND lease_expires_at > ? LIMIT 1", (int(time.time()),)
        ).fetchone()
        if row is not None:
            raise SnapshotError(f"workflow job is still running; stop its worker before saving: {row[0]}")
    finally:
        connection.close()


def _summary(manifest: dict[str, object]) -> dict[str, object]:
    files = manifest["files"]
    return {
        "snapshot_id": manifest["snapshot_id"],
        "created_at": manifest["created_at"],
        "database_contract": manifest["database_contract"],
        "file_count": len(files),
        "total_bytes": sum(file["size"] for file in files),
    }


def save_snapshot(archive_root: Path, out: Path, *, artifact_root: Path | None = None) -> dict:
    """Save one consistent portable ZIP without changing its source archive."""
    with _snapshot_errors():
        root, output = _absolute(archive_root), _absolute(out)
        bases = (root,) if artifact_root is None else tuple(dict.fromkeys((_absolute(artifact_root), root)))
        for base in bases:
            _no_links(base)
            if output.resolve().is_relative_to(base.resolve()):
                raise SnapshotError(f"snapshot output must be outside archive and artifact roots: {output}")
        _no_links(output)
        if output.exists():
            raise SnapshotError(f"snapshot output already exists: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        with archive_access(root, exclusive=True, create_root=False):
            source_database = root / "archive.db"
            _regular_file(source_database)
            validate_snapshot_database(source_database)
            _refuse_active_jobs(source_database)
            artifacts = _collect_artifacts(bases)
            with tempfile.TemporaryDirectory(prefix=f".{output.name}.snapshot-stage-", dir=output.parent) as temporary:
                stage = Path(temporary)
                database = stage / "archive.db"
                contract = create_database_snapshot(source_database, database)
                _refuse_active_jobs(database)
                archive = stage / "snapshot.zip"
                files: list[dict[str, object]] = []
                with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as bundle:
                    for key, source_path in sorted({"archive.db": database, **artifacts}.items()):
                        before = _regular_file(source_path)
                        with source_path.open("rb") as source, bundle.open(key, "w", force_zip64=True) as destination:
                            opened = os.fstat(source.fileno())
                            if (not stat.S_ISREG(opened.st_mode) or opened.st_ino != before.st_ino
                                    or opened.st_dev != before.st_dev):
                                raise SnapshotError(f"artifact changed before reading: {source_path}")
                            size, digest = _stream_hash(source, destination)
                        after = _regular_file(source_path)
                        if (before.st_size != size or before.st_size != after.st_size
                                or before.st_mtime_ns != after.st_mtime_ns or before.st_ino != after.st_ino):
                            raise SnapshotError(f"artifact changed while saving: {source_path}")
                        files.append({"path": key, "size": size, "sha256": digest})
                    _check_references(database, {file["path"]: file for file in files})
                    manifest: dict[str, object] = {
                        "format": _FORMAT,
                        "format_version": _FORMAT_VERSION,
                        "snapshot_id": str(uuid.uuid4()),
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "producer_version": __version__,
                        "database_contract": contract,
                        "files": files,
                    }
                    encoded = json.dumps(manifest, ensure_ascii=True, indent=2).encode("utf-8")
                    if len(encoded) > _MANIFEST_LIMIT:
                        raise SnapshotError("snapshot file manifest exceeds 16 MiB")
                    bundle.writestr(_MANIFEST_NAME, encoded)
                with zipfile.ZipFile(archive, "r") as bundle:
                    _check_bundle_markers(bundle, {file["path"]: file for file in files})
                with archive.open("r+b") as source:
                    os.fsync(source.fileno())
                # Both primitives atomically refuse a concurrently created output.
                if os.name == "nt":
                    os.rename(archive, output)
                else:
                    os.link(archive, output)
                _sync_directory(output.parent)
                return {"operation": "save", "snapshot": str(output), **_summary(manifest)}


def _manifest_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SnapshotError(f"duplicate manifest JSON key: {key}")
        result[key] = value
    return result


def _read_manifest(bundle: zipfile.ZipFile) -> dict[str, object]:
    members = bundle.infolist()
    manifests = [member for member in members if member.filename == _MANIFEST_NAME]
    if len(manifests) != 1 or manifests[0].file_size > _MANIFEST_LIMIT:
        raise SnapshotError("snapshot must contain one manifest of at most 16 MiB")
    with bundle.open(manifests[0]) as source:
        encoded = source.read(_MANIFEST_LIMIT + 1)
    if len(encoded) > _MANIFEST_LIMIT:
        raise SnapshotError("snapshot manifest exceeds 16 MiB")
    try:
        manifest = json.loads(encoded, object_pairs_hook=_manifest_object)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise SnapshotError("snapshot manifest is not valid JSON") from exc
    required = {"format", "format_version", "snapshot_id", "created_at", "producer_version", "database_contract", "files"}
    if not isinstance(manifest, dict) or set(manifest) != required:
        raise SnapshotError("snapshot manifest has invalid fields")
    if manifest["format"] != _FORMAT or type(manifest["format_version"]) is not int or manifest["format_version"] != _FORMAT_VERSION:
        raise SnapshotError("unsupported snapshot format or version")
    try:
        if not isinstance(manifest["snapshot_id"], str) or str(uuid.UUID(manifest["snapshot_id"])) != manifest["snapshot_id"]:
            raise ValueError
        created = datetime.fromisoformat(manifest["created_at"])
        if created.tzinfo is None or created.utcoffset().total_seconds() != 0:
            raise ValueError
    except (ValueError, TypeError, AttributeError) as exc:
        raise SnapshotError("snapshot UUID or UTC creation time is invalid") from exc
    for key in ("producer_version", "database_contract"):
        if not isinstance(manifest[key], str) or not manifest[key] or len(manifest[key]) > 256:
            raise SnapshotError(f"snapshot {key} is invalid")
    entries = manifest["files"]
    if not isinstance(entries, list) or not entries:
        raise SnapshotError("snapshot files must be a nonempty list")
    paths: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "size", "sha256"}:
            raise SnapshotError("invalid snapshot file entry")
        _path_key(entry["path"])
        if type(entry["size"]) is not int or entry["size"] < 0 or not isinstance(entry["sha256"], str) or not _HASH_PATTERN.fullmatch(entry["sha256"]):
            raise SnapshotError(f"invalid size or hash for snapshot file: {entry['path']}")
        paths.append(entry["path"])
    _check_path_collisions(paths)
    if "archive.db" not in paths:
        raise SnapshotError("snapshot is missing archive.db")
    expected = {*paths, _MANIFEST_NAME}
    names: set[str] = set()
    for member in members:
        mode = member.external_attr >> 16
        if (member.orig_filename != member.filename or member.filename in names
                or member.filename not in expected or member.is_dir()
                or stat.S_IFMT(mode) not in {0, stat.S_IFREG}
                or member.flag_bits & 1):
            raise SnapshotError(f"unsafe, duplicate or unlisted ZIP member: {member.filename!r}")
        names.add(member.filename)
    if names != expected:
        raise SnapshotError("snapshot ZIP is missing files listed in its manifest")
    return manifest


def _validate_into(snapshot: Path, stage: Path, *, extract_artifacts: bool = True) -> dict[str, object]:
    _regular_file(snapshot)
    with zipfile.ZipFile(snapshot, "r") as bundle:
        manifest = _read_manifest(bundle)
        files = {entry["path"]: entry for entry in manifest["files"]}
        for key, entry in files.items():
            member = bundle.getinfo(key)
            if member.file_size != entry["size"]:
                raise SnapshotError(f"snapshot file size mismatch: {key}")
            with bundle.open(member) as source:
                if extract_artifacts or key == "archive.db":
                    target = stage.joinpath(*_path_key(key))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open("xb") as destination:
                        size, digest = _stream_hash(source, destination)
                        _sync_file(destination)
                else:
                    size, digest = _stream_hash(source)
            if size != entry["size"] or digest != entry["sha256"]:
                raise SnapshotError(f"snapshot file hash mismatch: {key}")
        _check_bundle_markers(bundle, files)
    validate_snapshot_database(stage / "archive.db", expected_contract=manifest["database_contract"])
    _check_references(stage / "archive.db", files)
    return manifest


def check_snapshot(snapshot: Path) -> dict:
    """Stream and check every file, database contract and database reference."""
    with _snapshot_errors():
        path = _absolute(snapshot)
        with tempfile.TemporaryDirectory(prefix="bili-asr-snapshot-check-") as temporary:
            manifest = _validate_into(path, Path(temporary), extract_artifacts=False)
        return {"operation": "check", "snapshot": str(path), "valid": True, **_summary(manifest)}


def _empty_destination(root: Path) -> bool:
    _no_links(root)
    if not root.exists():
        return False
    if not root.is_dir() or any(root.iterdir()):
        raise SnapshotError(f"restore target must be nonexistent or empty: {root}")
    return True


def restore_snapshot(snapshot: Path, archive_root: Path) -> dict:
    """Validate a complete staged archive, recover interrupted work and publish it."""
    with _snapshot_errors():
        path, root = _absolute(snapshot), _absolute(archive_root)
        _no_links(root)
        if path.resolve().is_relative_to(root.resolve()):
            raise SnapshotError("restore target cannot contain the source snapshot")
        root.parent.mkdir(parents=True, exist_ok=True)
        with archive_access(root, exclusive=True, create_root=True):
            _empty_destination(root)
            with tempfile.TemporaryDirectory(prefix=f".{root.name}.restore-stage-", dir=root.parent) as temporary:
                temporary_root = Path(temporary)
                stage = temporary_root / "archive"
                stage.mkdir()
                manifest = _validate_into(path, stage)
                recovered = recover_interrupted_jobs(stage / "archive.db", manifest["snapshot_id"])
                validate_snapshot_database(stage / "archive.db", expected_contract=manifest["database_contract"])
                with (stage / "archive.db").open("r+b") as database:
                    os.fsync(database.fileno())
                for directory, _children, _files in os.walk(stage, topdown=False):
                    _sync_directory(Path(directory))
                if _empty_destination(root):
                    root.rmdir()
                stage.rename(root)
                _sync_directory(root.parent)
                return {"operation": "restore", "archive_root": str(root), "recovered": recovered, **_summary(manifest)}


__all__ = ["SnapshotError", "save_snapshot", "check_snapshot", "restore_snapshot"]
