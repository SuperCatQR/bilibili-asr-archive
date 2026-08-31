"""JSONL manifest ledger keyed by work_id.

Status names are the SSOT shared by all plans (spec asr-archive-cli.md
"Manifest state machine"). No network; I/O limited to the manifest dir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import re
from typing import Any, Callable, Optional

from .page_identity import PageIdentity, format_work_id, parse_work_id
from .persistence import append_jsonl_record, file_lock, replace_file_atomically

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

    def _read_latest(self) -> dict[str, dict[str, Any]]:
        entries: dict[str, dict[str, Any]] = {}
        if os.path.exists(self.path):
            with open(self.path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    entry = json.loads(line)
                    if not isinstance(entry, dict):
                        raise ValueError("manifest JSONL row must be an object")
                    entries[_entry_key(entry)] = entry
        return entries

    def load(self) -> dict[str, dict[str, Any]]:
        """Read the JSONL file (if any) into memory; last write wins per key."""
        self._entries = self._read_latest()
        self._loaded = True
        return self._entries

    def _snapshot_bytes(self, entries: dict[str, dict[str, Any]]) -> bytes:
        return b"".join(
            (json.dumps(entries[key], ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
            for key in sorted(entries)
        )

    def save(self, entries: dict[str, dict[str, Any]] | None = None) -> None:
        """Durably publish a deterministic latest-row snapshot without stale loss."""
        requested = dict(entries) if entries is not None else None
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with file_lock(self.path):
            current = self._read_latest()
            if requested is not None:
                current.update(requested)
            if not current:
                self._entries = {}
                self._loaded = True
                return
            replace_file_atomically(self.path, self._snapshot_bytes(current))
            self._entries = current
            self._loaded = True

    def compact(self) -> None:
        """Replace journal history with the deterministic latest-row snapshot."""
        with file_lock(self.path):
            current = self._read_latest()
            if current:
                replace_file_atomically(self.path, self._snapshot_bytes(current))
            self._entries = current
            self._loaded = True

    def upsert(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Insert or replace one record and persist under a fresh-state lock."""
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
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with file_lock(self.path):
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
            append_jsonl_record(self.path, stored)
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
    ) -> LegacyMigrationReport:
        """Migrate unambiguous bare-bvid rows; freeze the rest additively."""
        if not self._loaded:
            self.load()
        root = os.fspath(archive_root if archive_root is not None else self.root)
        report = LegacyMigrationReport()
        with file_lock(self.path):
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
                unambiguous = (
                    len(pages) == 1 and not colliding_stems and not dest_occupied
                    and not missing_cid and pages[0].page_index == 0
                    and pages[0].bvid == bvid
                )
                if dest_occupied:
                    raise ManifestMigrationCollision(
                        f"migration would overwrite existing work_id {dest_work_id}"
                    )
                if unambiguous:
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
                replace_file_atomically(self.path, self._snapshot_bytes(next_entries))
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
