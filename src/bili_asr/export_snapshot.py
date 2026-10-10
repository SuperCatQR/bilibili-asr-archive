"""Locked, recoverable replacement of a complete managed export directory."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import stat
from typing import Iterator, Mapping
import uuid


class ExportSnapshotError(ValueError):
    """The output is unsafe, unmanaged, or inconsistent with its manifest."""


_ARTICLE_FIELDS = frozenset({
    "manuscriptType", "slug", "title", "summary", "tags", "attribution", "editorNote",
    "releaseId", "editionId", "aiRevisionId", "videoPartId", "bvid", "pageIndex", "sourceUrl",
    "contentSha256", "artifactSha256", "templateVersion", "publishedAt", "file",
    "reviewFile", "reviewArtifactSha256",
})
_DRAFT_FIELDS = (_ARTICLE_FIELDS - {"releaseId", "templateVersion", "publishedAt"}) | {"reviewStatus", "createdAt"}
_REVIEW_STATUSES = frozenset({"pending-review", "in-review", "changes-requested", "approved", "rejected"})
_REVIEW_FILES = frozenset({"ai-draft.md", "review.md", "edition.md", "edition.json", "review.json", "differences/ai.patch", "differences/parent.patch"})


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _unique_object(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise ExportSnapshotError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def read_json(path: Path) -> object:
    try:
        return json.loads(path.read_bytes().decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ExportSnapshotError(f"invalid export JSON: {path.name}") from exc


def checked_path(path: Path) -> Path:
    """Check lexical ancestors before resolution, including Windows junctions."""
    absolute = Path(os.path.abspath(path))
    for current in (*reversed(absolute.parents), absolute):
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ExportSnapshotError(f"export path contains a link or reparse point: {current}")
    return absolute


def guard_output(connection: sqlite3.Connection, output: Path, artifact_roots: tuple[Path, ...]) -> Path:
    output = checked_path(output)
    if output.parent == output or not output.name:
        raise ExportSnapshotError("export output cannot be a filesystem root")
    sources = [checked_path(root) for root in artifact_roots]
    sources.extend(checked_path(Path(row[2]).parent) for row in connection.execute("PRAGMA database_list") if row[2])
    for source in sources:
        if output == source or output.is_relative_to(source) or source.is_relative_to(output):
            raise ExportSnapshotError(f"export output overlaps a source archive or artifact root: {source}")
    if output.exists() and not output.is_dir():
        raise ExportSnapshotError("export output must be a directory")
    return output


def _allowed_file(name: str, kind: str) -> bool:
    if kind == "publication-export":
        return name in {"catalog.json", "series.json"} or re.fullmatch(r"articles/part-[1-9][0-9]*/(?:publish|review)\.md", name) is not None
    if kind == "publication-draft-export":
        return name in {"catalog.json", "series.json"} or re.fullmatch(r"drafts/edition-[0-9a-f]{32}/(?:preview|review)\.md", name) is not None
    return name in _REVIEW_FILES


def _validate_article(article: object, *, draft: bool = False, catalog_version: int = 2) -> dict:
    fields = _DRAFT_FIELDS if draft else _ARTICLE_FIELDS
    universal = catalog_version == 3 and isinstance(article, dict) and article.get("contentVersion") == 2
    if universal:
        fields = (fields - {"bvid", "pageIndex"}) | {"platform", "externalVideoId", "partIndex", "sourceMetadata",
                                                   "sourcePublishedAt", "pubdateUnix", "contentVersion"}
    if not isinstance(article, dict) or set(article) != fields:
        raise ExportSnapshotError("public article fields differ from the contract")
    hashes = ("aiRevisionId", "contentSha256", "artifactSha256", "reviewArtifactSha256") if draft else ("releaseId", "aiRevisionId", "contentSha256", "artifactSha256", "reviewArtifactSha256")
    for key in hashes:
        if not isinstance(article[key], str) or not re.fullmatch(r"[0-9a-f]{64}", article[key]):
            raise ExportSnapshotError(f"invalid public article hash: {key}")
    if not isinstance(article["editionId"], str) or not re.fullmatch(r"[0-9a-f]{32}", article["editionId"]):
        raise ExportSnapshotError("invalid public edition ID")
    for key, minimum in (("videoPartId", 1), ("partIndex" if universal else "pageIndex", 0), ("createdAt" if draft else "publishedAt", 0)):
        if type(article[key]) is not int or article[key] < minimum:
            raise ExportSnapshotError(f"invalid public article integer: {key}")
    for key in ("title", "summary", "attribution", "editorNote", "externalVideoId" if universal else "bvid"):
        if not isinstance(article[key], str):
            raise ExportSnapshotError(f"invalid public article text: {key}")
    if not article["title"].strip() or not article["attribution"].strip():
        raise ExportSnapshotError("invalid public article title, attribution, or source")
    if universal:
        from bili_asr.platform_identity import ContentRef
        from bili_asr.source_identity import source_url
        from bili_asr.source_metadata import SourceMetadataSnapshot
        try:
            ref = ContentRef(article["platform"], article["externalVideoId"], article["partIndex"])
            metadata = SourceMetadataSnapshot.from_dict(article["sourceMetadata"])
            if (type(article["contentVersion"]) is not int or metadata.ref != ref
                    or article["sourcePublishedAt"] != metadata.to_dict()["sourcePublishedAt"]
                    or article["pubdateUnix"] != metadata.pubdate):
                raise ValueError("source snapshot mismatch")
            expected_url = source_url(ref)
        except (ValueError, TypeError, KeyError) as exc:
            raise ExportSnapshotError("invalid universal public source") from exc
    else:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", article["bvid"]):
            raise ExportSnapshotError("invalid public article source")
        expected_url = f"https://www.bilibili.com/video/{article['bvid']}/?p={article['pageIndex'] + 1}"
    tags = article["tags"]
    if not isinstance(tags, list) or any(not isinstance(tag, str) or not tag.strip() for tag in tags) or len(set(tags)) != len(tags):
        raise ExportSnapshotError("invalid public article tags")
    slug = f"edition-{article['editionId']}" if draft else f"part-{article['videoPartId']}"
    manuscript_type = "publication-draft" if draft else "publication"
    filename = f"drafts/{slug}/preview.md" if draft else f"articles/{slug}/publish.md"
    review_filename = f"drafts/{slug}/review.md" if draft else f"articles/{slug}/review.md"
    if draft:
        if not isinstance(article["reviewStatus"], str) or article["reviewStatus"] not in _REVIEW_STATUSES:
            raise ExportSnapshotError("invalid draft review status")
    elif article["templateVersion"] != ("publish-v2" if universal else "publish-v1"):
        raise ExportSnapshotError("invalid public article template")
    if (article["manuscriptType"] != manuscript_type
            or article["slug"] != slug or article["file"] != filename or article["reviewFile"] != review_filename
            or article["sourceUrl"] != expected_url):
        raise ExportSnapshotError("public article identity or source URL mismatch")
    return article


def _file_parts(name: str, kind: str) -> tuple[str, ...]:
    parts = PurePosixPath(name).parts
    if not _allowed_file(name, kind) or PurePosixPath(name).as_posix() != name or any(part in {".", ".."} for part in parts):
        raise ExportSnapshotError(f"unmanaged export file: {name}")
    return parts


def _snapshot_id(files: list[dict[str, str]]) -> str:
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _scan(directory: Path) -> tuple[set[str], set[str]]:
    files: set[str] = set()
    directories: set[str] = set()
    checked_path(directory)
    if not directory.is_dir():
        raise ExportSnapshotError("export snapshot is not a directory")
    for current, children, names in os.walk(directory, followlinks=False):
        for name in (*children, *names):
            path = Path(current) / name
            checked_path(path)
            info = path.lstat()
            relative = path.relative_to(directory).as_posix()
            if stat.S_ISDIR(info.st_mode):
                directories.add(relative)
            elif stat.S_ISREG(info.st_mode):
                files.add(relative)
            else:
                raise ExportSnapshotError(f"export contains a nonregular file: {relative}")
    return files, directories


def _validate_snapshot(directory: Path, kind: str, *, allow_empty: bool = False) -> str | None:
    actual_files, actual_directories = _scan(directory)
    if not actual_files and not actual_directories and allow_empty:
        return None
    manifest_name = f"{kind}-manifest.json"
    if manifest_name not in actual_files:
        raise ExportSnapshotError(f"output is not a managed {kind} snapshot; legacy exports and manual files are refused")
    manifest = read_json(directory / manifest_name)
    if not isinstance(manifest, dict) or set(manifest) != {"schemaVersion", "manuscriptType", "snapshotId", "files"}:
        raise ExportSnapshotError("invalid export manifest fields")
    if type(manifest["schemaVersion"]) is not int or manifest["schemaVersion"] != 1 or manifest["manuscriptType"] != kind:
        raise ExportSnapshotError("unsupported export manifest contract")
    records = manifest["files"]
    if not isinstance(records, list) or not records:
        raise ExportSnapshotError("invalid export manifest file list")
    expected_files = {manifest_name}
    expected_directories: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != {"path", "sha256"}:
            raise ExportSnapshotError("invalid export manifest file record")
        name, digest = record["path"], record["sha256"]
        if not isinstance(name, str) or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ExportSnapshotError("invalid export file identity")
        _file_parts(name, kind)
        if name in expected_files:
            raise ExportSnapshotError("duplicate export manifest file")
        expected_files.add(name)
        expected_directories.update(parent.as_posix() for parent in PurePosixPath(name).parents if parent != PurePosixPath("."))
        path = directory / name
        if name not in actual_files or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ExportSnapshotError(f"export file is missing or modified: {name}")
    if records != sorted(records, key=lambda item: item["path"]) or manifest["snapshotId"] != _snapshot_id(records):
        raise ExportSnapshotError("export snapshot identity mismatch")
    if actual_files != expected_files or actual_directories != expected_directories:
        raise ExportSnapshotError("export contains unmanaged files or directories")
    if kind in {"publication-export", "publication-draft-export"}:
        if "catalog.json" not in expected_files:
            raise ExportSnapshotError("public snapshot has no catalog")
        catalog = read_json(directory / "catalog.json")
        draft = kind == "publication-draft-export"
        manuscript_type = "publication-draft" if draft else "publication"
        if not isinstance(catalog, dict) or set(catalog) != {"schemaVersion", "manuscriptType", "articles"} or type(catalog["schemaVersion"]) is not int or catalog["schemaVersion"] not in {2, 3} or catalog["manuscriptType"] != manuscript_type or not isinstance(catalog["articles"], list):
            raise ExportSnapshotError("unsupported public catalog contract")
        article_files: set[str] = set()
        for article in catalog["articles"]:
            article = _validate_article(article, draft=draft, catalog_version=catalog["schemaVersion"])
            for file_field, hash_field in (("file", "artifactSha256"), ("reviewFile", "reviewArtifactSha256")):
                if article[file_field] in article_files:
                    raise ExportSnapshotError("invalid public catalog article file")
                article_files.add(article[file_field])
                record = next((record for record in records if record["path"] == article[file_field]), None)
                if record is None or record["sha256"] != article[hash_field]:
                    raise ExportSnapshotError("public article and manifest hashes differ")
        if article_files != expected_files - {manifest_name, "catalog.json", "series.json"}:
            raise ExportSnapshotError("catalog and manifest file sets differ")
        if "series.json" in expected_files:
            from bili_asr.publication_series import validate_public_series
            validate_public_series(read_json(directory / "series.json"), catalog["articles"], manuscript_type)
    elif expected_files != _REVIEW_FILES | {manifest_name}:
        raise ExportSnapshotError("private editorial snapshot is incomplete")
    return str(manifest["snapshotId"])


def _fsync_directory(path: Path) -> None:
    if os.name == "posix":
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _write_file(path: Path, content: bytes) -> None:
    checked_path(path)
    stream = path.open("xb")
    try:
        with stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        # The exclusive create succeeded, so this partial file belongs to us.
        # Close it before unlinking to support Windows file sharing rules.
        path.unlink(missing_ok=True)
        raise


def _remove_private(directory: Path) -> None:
    """Only used for privately generated directories after an ownership check."""
    if not directory.exists():
        return
    files, directories = _scan(directory)
    for name in sorted(files):
        (directory / name).unlink()
    for name in sorted(directories, key=lambda value: value.count("/"), reverse=True):
        (directory / name).rmdir()
    directory.rmdir()


@contextmanager
def _exclusive_lock(output: Path) -> Iterator[None]:
    path = output.parent / f".{output.name}.export.lock"
    checked_path(path)
    flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    marker = b"bili-asr-export-lock-v1\n"
    descriptor = None
    created = initialized = False
    try:
        try:
            descriptor = os.open(path, flags | os.O_CREAT | os.O_EXCL, 0o600)
            created = True
        except FileExistsError:
            descriptor = os.open(path, flags)
        if created:
            written = 0
            while written < len(marker):
                count = os.write(descriptor, marker[written:])
                if count <= 0:
                    raise OSError("cannot initialize export lock")
                written += count
            os.fsync(descriptor)
        initialized = True
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ExportSnapshotError("export lock is not a regular file")
        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            actual_marker = os.read(descriptor, len(marker) + 1)
        except PermissionError as exc:
            # Windows byte-range locks reject even reading the locked marker.
            raise ExportSnapshotError("another export holds the output lock") from exc
        if actual_marker != marker:
            raise ExportSnapshotError("export lock file is unmanaged or damaged")
        try:
            if os.name == "nt":
                import msvcrt

                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ExportSnapshotError("another export holds the output lock") from exc
        yield
    finally:
        if descriptor is not None:
            # Initialization can fail before lock acquisition. Close even then,
            # and remove only the incomplete file created by this attempt.
            try:
                incomplete = os.fstat(descriptor) if created and not initialized else None
            finally:
                os.close(descriptor)
            if incomplete is not None:
                try:
                    current = path.lstat()
                except FileNotFoundError:
                    pass
                else:
                    if (current.st_dev, current.st_ino) == (incomplete.st_dev, incomplete.st_ino):
                        path.unlink()


def _journal_path(output: Path) -> Path:
    return output.parent / f".{output.name}.export-recovery.json"


def _private_paths(output: Path, token: str) -> tuple[Path, Path]:
    prefix = f".{output.name}.export-{token}"
    return output.parent / f"{prefix}.stage", output.parent / f"{prefix}.backup"


def _recover(output: Path, kind: str) -> None:
    journal_path = checked_path(_journal_path(output))
    if not journal_path.exists():
        return
    journal = read_json(journal_path)
    if not isinstance(journal, dict) or set(journal) != {"schemaVersion", "manuscriptType", "token", "snapshotId", "previousSnapshotId", "hadOutput"} or type(journal["schemaVersion"]) is not int or journal["schemaVersion"] != 1 or journal["manuscriptType"] != kind or not isinstance(journal["token"], str) or not re.fullmatch(r"[0-9a-f]{32}", journal["token"]) or type(journal["hadOutput"]) is not bool:
        raise ExportSnapshotError("invalid export recovery journal")
    for key in ("snapshotId", "previousSnapshotId"):
        if journal[key] is None and key == "previousSnapshotId":
            continue
        if not isinstance(journal[key], str) or not re.fullmatch(r"[0-9a-f]{64}", journal[key]):
            raise ExportSnapshotError("invalid export recovery identity")
    stage, backup = _private_paths(output, journal["token"])
    checked_path(stage)
    checked_path(backup)
    if stage.exists() and _validate_snapshot(stage, kind) != journal["snapshotId"]:
        raise ExportSnapshotError("staged export identity mismatch")
    if backup.exists() and (not journal["hadOutput"] or _validate_snapshot(backup, kind, allow_empty=True) != journal["previousSnapshotId"]):
        raise ExportSnapshotError("previous export identity mismatch")
    if output.exists():
        current = _validate_snapshot(output, kind, allow_empty=True)
        if stage.exists() and current == journal["previousSnapshotId"] and not backup.exists() and journal["hadOutput"]:
            _remove_private(stage)
        elif not stage.exists() and current == journal["snapshotId"]:
            if journal["hadOutput"] and not backup.exists():
                # A crash may occur after backup cleanup and before journal removal.
                pass
            # The installed snapshot is already complete. Finalize recovery
            # before cleanup so an interrupted cleanup cannot block retries.
            journal_path.unlink()
            _fsync_directory(output.parent)
            _remove_private(backup)
            return
        else:
            raise ExportSnapshotError("ambiguous export recovery state; preserving all files")
    elif backup.exists():
        os.replace(backup, output)
        _remove_private(stage)
    elif stage.exists() and not journal["hadOutput"]:
        _remove_private(stage)
    else:
        raise ExportSnapshotError("incomplete export recovery state; preserving all files")
    journal_path.unlink()
    _fsync_directory(output.parent)


def replace_snapshot(output: Path, *, kind: str, files: Mapping[str, bytes]) -> str:
    """Install one exact snapshot, or restore the previous directory on failure.

    Recovery artifacts are siblings of the public directory. OS advisory locks
    are released on process exit, so an interrupted exporter can be retried.
    """
    if kind not in {"publication-export", "publication-draft-export", "editorial-export"} or not files:
        raise ExportSnapshotError("unsupported or empty export snapshot")
    output = checked_path(output)
    for name, content in files.items():
        _file_parts(name, kind)
        if not isinstance(content, bytes):
            raise ExportSnapshotError("export content must be bytes")
    records = [{"path": name, "sha256": hashlib.sha256(files[name]).hexdigest()} for name in sorted(files)]
    snapshot_id = _snapshot_id(records)
    manifest = {"schemaVersion": 1, "manuscriptType": kind, "snapshotId": snapshot_id, "files": records}
    output.parent.mkdir(parents=True, exist_ok=True)
    checked_path(output.parent)
    with _exclusive_lock(output):
        _recover(output, kind)
        had_output = output.exists()
        previous_id = _validate_snapshot(output, kind, allow_empty=True) if had_output else None
        token = uuid.uuid4().hex
        stage, backup = _private_paths(output, token)
        stage.mkdir(mode=0o700)
        journal_path = _journal_path(output)
        installed = moved_old = journal_written = False
        try:
            for name, content in files.items():
                target = stage.joinpath(*_file_parts(name, kind))
                target.parent.mkdir(parents=True, exist_ok=True)
                _write_file(target, content)
            _write_file(stage / f"{kind}-manifest.json", json_bytes(manifest))
            _validate_snapshot(stage, kind)
            for current, _, _ in os.walk(stage, topdown=False):
                _fsync_directory(Path(current))
            journal = {"schemaVersion": 1, "manuscriptType": kind, "token": token, "snapshotId": snapshot_id, "previousSnapshotId": previous_id, "hadOutput": had_output}
            journal_temporary = stage / ".recovery-journal.tmp"
            _write_file(journal_temporary, json_bytes(journal))
            os.replace(journal_temporary, journal_path)
            journal_written = True
            _fsync_directory(output.parent)
            if had_output:
                if _validate_snapshot(output, kind, allow_empty=True) != previous_id:
                    raise ExportSnapshotError("output changed while the export was prepared")
                os.replace(output, backup)
                moved_old = True
            os.replace(stage, output)
            installed = True
            _fsync_directory(output.parent)
            _validate_snapshot(output, kind)
        except BaseException:
            # Crash-like interruptions leave the journal for the next run.
            import sys

            # An interruption immediately after atomic journal installation
            # must keep the complete stage available for recovery.
            journal_written = journal_written or journal_path.exists()
            if not isinstance(sys.exc_info()[1], Exception) and journal_written:
                raise
            if installed:
                os.replace(output, stage)
            if moved_old:
                os.replace(backup, output)
            _remove_private(stage)
            if journal_written:
                journal_path.unlink()
            _fsync_directory(output.parent)
            raise
        if backup.exists():
            if _validate_snapshot(backup, kind, allow_empty=True) != previous_id:
                raise ExportSnapshotError("previous snapshot changed; preserving recovery files")
        journal_path.unlink()
        _fsync_directory(output.parent)
        # Backups are outside the served output. Once commit is durable, a
        # cleanup interruption may leave a private orphan, never a mixed export.
        _remove_private(backup)
    return snapshot_id
