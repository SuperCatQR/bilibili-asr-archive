"""JSONL manifest ledger keyed by bvid.

Status names are the SSOT shared by all plans (spec asr-archive-cli.md
"Manifest state machine"). No network; I/O limited to the manifest dir.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

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


class ManifestStore:
    """Append-safe JSONL store of per-video records keyed by bvid."""

    def __init__(self, root: str | os.PathLike[str],
                 rel_path: str = DEFAULT_REL_PATH) -> None:
        self.root = os.fspath(root)
        self.path = os.path.join(self.root, rel_path)
        self._entries: dict[str, dict[str, Any]] = {}
        self._loaded = False

    def load(self) -> dict[str, dict[str, Any]]:
        """Read the JSONL file (if any) into memory; returns bvid -> entry."""
        self._entries = {}
        if os.path.exists(self.path):
            with open(self.path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    entry = json.loads(line)
                    # last write wins; resume re-reads may contain dupes
                    self._entries[entry["bvid"]] = entry
        self._loaded = True
        return self._entries

    def save(self, entries: dict[str, dict[str, Any]] | None = None) -> None:
        """Atomically rewrite the JSONL file, one line per bvid."""
        if entries is not None:
            self._entries = dict(entries)
        if not self._entries:
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            for entry in self._entries.values():
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        os.replace(tmp, self.path)

    def upsert(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Insert or replace one bvid record and persist (deduped)."""
        bvid = entry.get("bvid")
        if not bvid:
            raise ValueError("manifest entry requires a non-empty 'bvid'")
        status = entry.get("status")
        if status not in VALID_STATUSES:
            raise ValueError(
                f"unknown status {status!r}; valid: {sorted(VALID_STATUSES)}"
            )
        if not self._loaded:
            self.load()
        self._entries[bvid] = dict(entry)
        self.save()
        return self._entries[bvid]

    def get(self, bvid: str) -> Optional[dict[str, Any]]:
        """Return the record for bvid, or None."""
        if not self._loaded:
            self.load()
        return self._entries.get(bvid)
