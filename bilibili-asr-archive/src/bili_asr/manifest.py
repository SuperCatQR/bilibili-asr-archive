"""JSONL manifest ledger keyed by work_id.

Status names are the SSOT shared by all plans (spec asr-archive-cli.md
"Manifest state machine"). No network; I/O limited to the manifest dir.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import json
import os
import re
import stat
from typing import Any, Callable, Mapping, Optional

from .page_identity import PageIdentity, format_work_id, parse_work_id
from .persistence import _json_line, file_lock

# Manifest state machine (spec SSOT):
# pending -> meta_ok -> sub_checked -> {subtitle_done | needs_audio -> audio_ok}
#          -> asr_done -> archived
# plus terminal-per-video `gone`.
VALID_STATUSES = frozenset(
    {
        "pending",
        "meta_ok",
        "sub_checked",
        "subtitle_done",
        "needs_audio",
        "audio_ok",
        "asr_done",
        "archived",
        "gone",
    }
)

DEFAULT_REL_PATH = os.path.join("manifest", "manifest.jsonl")

UNRESOLVED_REASON_AMBIGUOUS_BARE_BVID = "ambiguous_bare_bvid"

_STEM_PAGE_RE = re.compile(r"^(.+)\.p(\d+)$")


class ManifestMigrationCollision(ValueError):
    """Migration would overwrite an existing work_id row or page artifact."""


@dataclass
class LegacyMigrationReport:
    migrated: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)


def _entry_key(entry: dict[str, Any]) -> str:
    work_id = entry.get("work_id")
    if work_id:
        return str(work_id)
    bvid = entry.get("bvid")
    if not bvid:
        raise ValueError("manifest entry requires 'work_id' or 'bvid'")
    return str(bvid)


def validate_manifest_record(entry: Mapping[str, Any], *, allow_bare_bvid: bool = True) -> dict[str, Any]:
    """Validate one persisted row for authoritative replay.

    Bare ``bvid`` rows are accepted only for legacy reads; automatic writes
    still require a page-qualified ``work_id`` in :meth:`ManifestStore.upsert`.
    """
    if not isinstance(entry, dict):
        raise ValueError("manifest JSONL row must be an object")
    bvid = entry.get("bvid")
    work_id = entry.get("work_id")
    if work_id is not None:
        if not isinstance(work_id, str) or not work_id:
            raise ValueError("manifest work_id must be a non-empty string")
        if bvid is not None:
            if not isinstance(bvid, str) or not bvid:
                raise ValueError("manifest bvid must be a non-empty string")
            parsed_bvid, _ = parse_work_id(work_id)
            if parsed_bvid != bvid:
                raise ValueError("manifest work_id does not match bvid")
    elif not (allow_bare_bvid and isinstance(bvid, str) and bvid):
        raise ValueError("manifest entry requires work_id or bvid")
    if entry.get("status") not in VALID_STATUSES:
        raise ValueError(f"unknown status {entry.get('status')!r}")
    return dict(entry)

def _is_unresolved(entry: dict[str, Any]) -> bool:
    return bool(entry.get("unresolved"))


def _is_bare_legacy(entry: dict[str, Any]) -> bool:
    return not entry.get("work_id") and bool(entry.get("bvid"))


class ManifestStore:
    """Append-safe JSONL store of per-page records keyed by work_id."""

    def __init__(self, root: str | os.PathLike[str],
                 rel_path: str = DEFAULT_REL_PATH) -> None:
        self.root = os.fspath(root)
        self.path = os.path.join(self.root, rel_path)
        self._entries: dict[str, dict[str, Any]] = {}
        self._loaded = False

    def _open_manifest_dir(self, *, create: bool = False) -> int:
        nofollow = getattr(os, "O_NOFOLLOW", None)
        directory = getattr(os, "O_DIRECTORY", None)
        if nofollow is None or directory is None:
            raise OSError("safe manifest opening is unavailable")
        root_fd = os.open(self.root, os.O_RDONLY | directory | nofollow)
        try:
            if create:
                try:
                    os.mkdir("manifest", 0o755, dir_fd=root_fd)
                except FileExistsError:
                    pass
            manifest_fd = os.open(
                "manifest", os.O_RDONLY | directory | nofollow, dir_fd=root_fd,
            )
        finally:
            os.close(root_fd)
        return manifest_fd

    @staticmethod
    def _open_regular_at(directory_fd: int, name: str, flags: int) -> int:
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:
            raise OSError("safe manifest opening is unavailable")
        fd = os.open(name, flags | nofollow, 0o644, dir_fd=directory_fd)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise OSError("manifest is not regular")
        except Exception:
            os.close(fd)
            raise
        return fd

    @contextmanager
    def _manifest_lock(self, *, create: bool = False):
        directory_fd = self._open_manifest_dir(create=create)
        try:
            lock_path = f"/proc/self/fd/{directory_fd}/manifest.jsonl"
            with file_lock(lock_path):
                yield
        finally:
            os.close(directory_fd)
    def _read_latest(self) -> dict[str, dict[str, Any]]:
        entries: dict[str, dict[str, Any]] = {}
        try:
            directory_fd = self._open_manifest_dir()
        except FileNotFoundError:
            return entries
        try:
            try:
                fd = self._open_regular_at(directory_fd, "manifest.jsonl", os.O_RDONLY)
            except FileNotFoundError:
                return entries
            with os.fdopen(fd, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    entry = validate_manifest_record(json.loads(line))
                    entries[_entry_key(entry)] = entry
        finally:
            os.close(directory_fd)
        return entries

    def load(self) -> dict[str, dict[str, Any]]:
        """Read the JSONL file (if any) into memory; last write wins per key."""
        self._entries = self._read_latest()
        self._loaded = True
        return self._entries

    def _append_record(self, record: Mapping[str, Any]) -> None:
        directory_fd = self._open_manifest_dir(create=True)
        try:
            fd = self._open_regular_at(
                directory_fd, "manifest.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT,
            )
            try:
                os.write(fd, _json_line(dict(record)))
                os.fsync(fd)
            finally:
                os.close(fd)
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    def _replace_snapshot(self, entries: dict[str, dict[str, Any]]) -> None:
        directory_fd = self._open_manifest_dir(create=True)
        temporary = ""
        try:
            try:
                fd = self._open_regular_at(directory_fd, "manifest.jsonl", os.O_RDONLY)
            except FileNotFoundError:
                pass
            else:
                os.close(fd)
            temporary = f".manifest.jsonl.{os.getpid()}.{id(entries)}.tmp"
            fd = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory_fd,
            )
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(self._snapshot_bytes(entries))
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(
                    temporary, "manifest.jsonl",
                    src_dir_fd=directory_fd, dst_dir_fd=directory_fd,
                )
                temporary = ""
                os.fsync(directory_fd)
            finally:
                if temporary:
                    try:
                        os.unlink(temporary, dir_fd=directory_fd)
                    except FileNotFoundError:
                        pass
        finally:
            os.close(directory_fd)

    def _snapshot_bytes(self, entries: dict[str, dict[str, Any]]) -> bytes:
        return b"".join(
            (json.dumps(entries[key], ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
            for key in sorted(entries)
        )

    def save(self, entries: dict[str, dict[str, Any]] | None = None) -> None:
        """Durably publish a deterministic latest-row snapshot without stale loss."""
        requested = dict(entries) if entries is not None else None
        with self._manifest_lock(create=True):
            current = self._read_latest()
            if requested is not None:
                current.update(requested)
            if not current:
                self._entries = {}
                self._loaded = True
                return
            self._replace_snapshot(current)
            self._entries = current
            self._loaded = True

    def compact(self) -> None:
        """Replace journal history with the deterministic latest-row snapshot."""
        with self._manifest_lock(create=True):
            current = self._read_latest()
            if current:
                self._replace_snapshot(current)
            self._entries = current
            self._loaded = True

    def upsert(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Insert or replace one record and persist under a fresh-state lock."""
        validate_manifest_record(entry)
        bvid = entry.get("bvid")
        if not bvid:
            raise ValueError("manifest entry requires a non-empty 'bvid'")
        work_id = entry.get("work_id")
        if work_id:
            parsed_bvid, _page = parse_work_id(str(work_id))
            if parsed_bvid != bvid:
                raise ValueError(
                    f"work_id {work_id!r} does not match bvid {bvid!r}"
                )
        status = entry.get("status")
        if status not in VALID_STATUSES:
            raise ValueError(
                f"unknown status {status!r}; valid: {sorted(VALID_STATUSES)}"
            )
        with self._manifest_lock(create=True):
            self._entries = self._read_latest()
            self._loaded = True
            if not work_id:
                existing = self._entries.get(str(bvid))
                freeze = _is_unresolved(entry) or bool(
                    entry.get("excluded_from_page_processing")
                )
                legacy_update = (
                    existing is not None and not existing.get("work_id")
                )
                if not freeze and not legacy_update:
                    raise ValueError("new automatic row requires work_id")
            stored = dict(entry)
            key = _entry_key(stored)
            self._append_record(stored)
            self._entries[key] = stored
            return stored

    def get(self, work_id: str) -> Optional[dict[str, Any]]:
        """Return the record for an exact work_id (or legacy bare-bvid key)."""
        if not self._loaded:
            self.load()
        return self._entries.get(work_id)

    def get_compatible(self, bvid: str) -> Optional[dict[str, Any]]:
        """Lookup by bvid without guessing among multiple pages."""
        if not self._loaded:
            self.load()
        matching = [
            entry for entry in self._entries.values()
            if entry.get("bvid") == bvid
        ]
        processable = [e for e in matching if not _is_unresolved(e)]
        if len(processable) == 1:
            return processable[0]
        unresolved = [
            e for e in matching
            if _is_unresolved(e) and _is_bare_legacy(e)
        ]
        if unresolved:
            return unresolved[0]
        return None

    def unresolved_identifiers(self) -> list[str]:
        if not self._loaded:
            self.load()
        ids = [
            str(e.get("bvid"))
            for e in self._entries.values()
            if _is_unresolved(e)
        ]
        return sorted(ids)

    def migrate_legacy_rows(
        self,
        pages_for: Callable[[str], list[PageIdentity]],
        archive_root: str | os.PathLike[str] | None = None,
        only_bvid: str | None = None,
        *,
        coalesce_existing_page: bool = False,
    ) -> LegacyMigrationReport:
        """Migrate unambiguous bare-bvid rows; freeze the rest additively."""
        if not self._loaded:
            self.load()
        root = os.fspath(archive_root if archive_root is not None else self.root)
        report = LegacyMigrationReport()
        with self._manifest_lock(create=True):
            current = self._read_latest()
            self._entries = current
            self._loaded = True
            next_entries: dict[str, dict[str, Any]] = dict(current)

            bare_keys = sorted(
                key for key, entry in current.items()
                if _is_bare_legacy(entry)
                and (only_bvid is None or entry.get("bvid") == only_bvid)
            )
            for key in bare_keys:
                entry = dict(next_entries[key])
                bvid = str(entry["bvid"])
                pages = list(pages_for(bvid))
                colliding_stems = _foreign_page_stems(root, bvid)
                dest_work_id = format_work_id(bvid, 0)
                dest_occupied = dest_work_id in next_entries and dest_work_id != key
                missing_cid = bool(pages) and any(p.cid is None for p in pages)
                page_is_unambiguous = (
                    len(pages) == 1 and not colliding_stems
                    and not missing_cid and pages[0].page_index == 0
                    and pages[0].bvid == bvid
                )
                if dest_occupied:
                    destination = next_entries[dest_work_id]
                    destination_matches_page = (
                        page_is_unambiguous
                        and destination.get("bvid") == pages[0].bvid
                        and destination.get("page_index") == pages[0].page_index
                        and destination.get("cid") == pages[0].cid
                    )
                    if not coalesce_existing_page or not destination_matches_page:
                        raise ManifestMigrationCollision(
                            f"migration would overwrite existing work_id {dest_work_id}"
                        )
                    migrated = dict(entry)
                    migrated.update(next_entries[dest_work_id])
                    del next_entries[key]
                    next_entries[dest_work_id] = migrated
                    report.migrated.append(dest_work_id)
                    continue
                if page_is_unambiguous:
                    page = pages[0]
                    migrated = dict(entry)
                    migrated.update({"work_id": page.work_id, "page_index": page.page_index,
                                     "cid": page.cid, "page_label": page.page_label})
                    del next_entries[key]
                    next_entries[page.work_id] = migrated
                    report.migrated.append(page.work_id)
                else:
                    marked = dict(entry)
                    marked.setdefault("unresolved", True)
                    marked.setdefault("unresolved_reason", UNRESOLVED_REASON_AMBIGUOUS_BARE_BVID)
                    marked.setdefault("excluded_from_page_processing", True)
                    next_entries[key] = marked
                    report.unresolved.append(bvid)
            if next_entries != current:
                self._replace_snapshot(next_entries)
                self._entries = next_entries
        return report


_ARTIFACT_REL_DIRS = (
    "audio",
    os.path.join("subtitles", "raw"),
    os.path.join("transcripts", "srt"),
    os.path.join("transcripts", "txt"),
    os.path.join("transcripts", "md"),
    os.path.join("transcripts", "raw"),
)


def _foreign_page_stems(archive_root: str, bvid: str) -> set[str]:
    """Return artifact stems `{bvid}.pN` (including p0) in known dirs."""
    found: set[str] = set()
    prefix = f"{bvid}.p"
    for rel in _ARTIFACT_REL_DIRS:
        dirpath = os.path.join(archive_root, rel)
        if not os.path.isdir(dirpath):
            continue
        try:
            names = os.listdir(dirpath)
        except OSError:
            continue
        for name in names:
            stem, _ext = os.path.splitext(name)
            if not stem.startswith(prefix):
                continue
            if not _STEM_PAGE_RE.match(stem):
                continue
            found.add(stem)
    return found
