"""Reconcile the audio store with what the archive actually holds.

The two tables ``audio_objects`` / ``part_audio_objects`` are written as audio is
acquired (``MediaQueueRepository.mark_audio_acquired``); nothing could *read*
them back as an inventory.  :func:`reconcile_audio_inventory` is that read.

The four counters are **product rulings**, not naming choices — they are defined
in ``specs/audio-retention-contract.md`` §3.1, and the plan that owns this module
says to implement them as written rather than redefining one locally.  They are
reproduced here so a reader of the code does not have to hold the spec open:

``recorded``
    A manifest candidate that had **no** ``audio_objects`` row and now has one.
    Never invented when the file was absent.
``already``
    A candidate whose object row was already present and matched.  A re-run
    converges; it does not accumulate, and never writes a second row for one
    ``sha256``.
``missing``
    A manifest row that **names** an ``audio_path`` and the file is not there —
    the shipped reclaim path and a manual delete both produce it.  Never deleted,
    never re-created, never silently skipped.
``unlinked``
    An observed audio object that **no** ``part_audio_objects`` row attributes to
    a part.  The store can see the object but cannot tie it to a work.

**The command is additive and read-only over the audio tree.**  No counter
authorises a write to the filesystem: this module reads bytes to digest a file
and it never unlinks, re-creates or moves one.

Digesting is **not** optional.  ``audio_objects.sha256`` is ``NOT NULL UNIQUE``
(``schema.sql:94``), so a row without one is a row the store cannot deduplicate,
and ``mark_audio_acquired`` refuses a bare hash outright.  The single streamed
pass below is therefore the same read the size probe already pays for.  ``--deep``
is not a "hash or don't" switch; it *re-verifies* the digest of an object whose
row is already present.
"""

from __future__ import annotations

import hashlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from ..artifact_root import ArtifactRoots, resolve_audio_path
from ..audio_reclaim import _candidate_paths
from ..page_identity import parse_work_id

#: The route name recorded in ``part_audio_objects.acquisition_source``.  A
#: bounded scalar, per contract §3 — free-form prose is not allowed there.
ACQUISITION_SOURCE = "derive-audio-inventory"

#: Chunk size for the streamed digest read.  1 MiB keeps the documented
#: "one streamed read per newly recorded file" true without holding a whole
#: 200 MB audio file in memory.
_READ_CHUNK_BYTES = 1 << 20


@dataclass(frozen=True)
class AudioInventoryOutcome:
    """One reconciliation's four counters (``specs/…contract.md`` §3.1)."""

    recorded: int
    already: int
    missing: int
    unlinked: int

    def summary_line(self) -> str:
        """§3.1's single summary line, in its fixed field order."""
        return (
            f"derive-audio-inventory: recorded={self.recorded} "
            f"already={self.already} missing={self.missing} unlinked={self.unlinked}"
        )


def _digest_and_size(path: Path) -> tuple[str, int]:
    """One streamed pass yielding the content hash and the on-disk size.

    A single read, so the digest costs no more I/O than the size probe would on
    its own.  ``sha256`` is the store's deduplication identity, so this is not
    skippable: see the module docstring.
    """
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(_READ_CHUNK_BYTES)
            if not chunk:
                break
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


def _resolve_existing(
    roots: ArtifactRoots, entry: Mapping[str, Any]
) -> Path | None:
    """The first candidate path that actually holds a file, or ``None``.

    ``require_exists=True`` is the mode ``missing`` needs: it walks the ordered
    bases and hits one only when the *file* is there, so a row whose named file
    is absent at every base answers ``None`` rather than a plausible-looking path
    (``resolve_audio_path`` returns a non-existent path under the other mode).
    """
    for declared in _candidate_paths(entry):
        resolved = resolve_audio_path(roots, declared, require_exists=True)
        if resolved is not None:
            return resolved
    return None


def reconcile_audio_inventory(
    *,
    roots: ArtifactRoots,
    entries: Mapping[str, Mapping[str, Any]],
    known_storage_keys: Iterable[str],
    known_audio_ids: Iterable[int],
    linked_audio_ids: Iterable[int],
    record: Callable[..., int],
    moment: int,
    deep: bool = False,
) -> AudioInventoryOutcome:
    """Reconcile ``entries`` (the manifest) against the audio store and the disk.

    The **manifest is the candidate set** — this function never enumerates a
    directory to decide what should exist.  The filesystem is consulted for one
    question only: "is the file this row names actually there?".  A directory
    scan would invent candidates the archive never declared, which is precisely
    what ``missing`` is forbidden to do.

    ``known_storage_keys`` is the ``audio_objects.storage_key`` set,
    ``known_audio_ids`` the ``audio_objects.audio_id`` set and
    ``linked_audio_ids`` the ``part_audio_objects.audio_id`` set; all three are
    read by the caller through the store's own API.  ``record`` is
    ``MediaQueueRepository.mark_audio_acquired``, called with keyword arguments —
    this module does not open a transaction of its own, so the store keeps
    owning its writes.

    ``deep`` re-verifies the digest of a candidate whose row already exists.  It
    is not required to *obtain* a digest; see the module docstring.
    """
    keys = set(known_storage_keys)
    objects = set(known_audio_ids)
    linked = set(linked_audio_ids)
    recorded = already = missing = 0

    for work_id in sorted(entries):
        entry = entries[work_id]
        if not isinstance(entry, Mapping):
            continue
        declared = entry.get("audio_path")
        if not declared:
            # A row that names no audio_path is not an audio candidate at all --
            # neither recorded nor missing.  `missing` counts rows that *name* a
            # file (contract §3.1), so silence here is the definition, not a skip.
            continue

        resolved = _resolve_existing(roots, entry)
        if resolved is None:
            # named-but-absent: reported, never invented, never deleted.
            missing += 1
            continue

        storage_key = str(declared)
        existed = storage_key in keys
        if existed and not deep:
            # The plan's cost model is explicit: **zero file reads** for a
            # candidate whose `storage_key` already has a row and is not passed to
            # `--deep`.  So the row check comes *before* the digest, not after.
            # Resolving the path above is `stat`-shaped and reads no bytes, which
            # is what keeps a re-run over an unchanged corpus cheap.  Measured:
            # digesting first cost one read per known row where the plan requires
            # none.
            already += 1
            continue

        try:
            bvid, page_index = parse_work_id(str(work_id))
        except ValueError:
            # A manifest key that is not a work id cannot be attributed to a
            # part, so it can be recorded as nothing.  It is still an observed
            # file: `missing` is for absence, and this is present.
            continue

        try:
            sha256, byte_size = _digest_and_size(resolved)
        except OSError as exc:
            # A present-but-unreadable file.  It is **not** `missing` — the file
            # is there, and §3.1 defines that counter as the file being absent —
            # and it cannot be recorded, because `sha256` is `NOT NULL UNIQUE` and
            # a row without one cannot be deduplicated.  It is therefore counted
            # as neither, and named on stderr so the operator is not left with a
            # silently smaller number.  This is the one branch where no counter of
            # §3.1 fits; it is disclosed in the report rather than folded into
            # `missing`, which would be the local redefinition §3.1 forbids.
            print(
                f"derive-audio-inventory: unreadable: {declared} ({exc})",
                file=sys.stderr,
            )
            continue

        audio_id = record(
            bvid=bvid,
            page_index=page_index,
            audio_path=storage_key,
            sha256=sha256,
            byte_size=byte_size,
            format=resolved.suffix.lstrip("."),
            duration_ms=_duration_ms(entry),
            acquisition_source=ACQUISITION_SOURCE,
            acquired_at=moment,
        )
        keys.add(storage_key)
        if existed:
            already += 1
        else:
            recorded += 1
        objects.add(int(audio_id))
        # `record` inserts the part link with ON CONFLICT DO NOTHING, so the
        # object is attributed to its part from here on.
        linked.add(int(audio_id))

    # `unlinked` is a *store* observation, not a manifest one: an object row that
    # no part link attributes to a work, so an operator can see that the store
    # holds audio it cannot tie to any archived part.  It is the object set --
    # the rows that existed before this run plus the ones it recorded -- minus
    # everything a `part_audio_objects` row attributes to a part.
    unlinked = len(objects - linked)

    return AudioInventoryOutcome(
        recorded=recorded,
        already=already,
        missing=missing,
        unlinked=unlinked,
    )


def _duration_ms(entry: Mapping[str, Any]) -> int:
    """The part's duration as the store already knows it; ``0`` means unknown.

    ``audio_objects.duration_ms`` permits ``0`` (``CHECK (duration_ms >= 0)``)
    and §3 says it means "unknown", not "empty" -- so a manifest row that does
    not carry the part's duration is recorded as ``0`` rather than refused.
    """
    value = entry.get("duration_ms")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


__all__ = [
    "ACQUISITION_SOURCE",
    "AudioInventoryOutcome",
    "reconcile_audio_inventory",
]
