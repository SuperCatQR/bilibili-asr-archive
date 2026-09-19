"""Derive the manifest rows the audio/ASR chain needs, from recorded store facts.

One direction only: ``archive.db`` records what happened, the manifest states
what the chain is to do next.  This module is the mapping between them and
nothing else — it opens no connection, writes no file and touches no manifest.
The caller reads the queue rows (§2 of the iteration spec
``sqlite-queue-bridge-contract.md``) and ``ManifestStore.load()``'s mapping,
hands both to :func:`derive_rows`, and composes the write; ``cli.py`` owns that
composition because a service may not reach across layers to the store or the
manifest (spec §8).

The row is §3.1's nine fields and the milliseconds conversion is §3.2's floor
clamped to one.  The policy is §3.4's *additive* one — a ``work_id`` the chain
has already spoken about is left byte-for-byte as found, whatever state it
holds, and only a part with no effective row at all is appended — plus §3.6's
``identity_mismatch`` check for a store row whose SQL-computed ``work_id``
contradicts the Python identity rule.  That check is defence rather than a live
path: the view computes ``work_id`` in SQL exactly as
:func:`~bili_asr.page_identity.format_work_id` computes it in Python, over a
bvid the gateway validates and an integral ``page_index``, so the two forms agree
for every row a shipped writer can store and the branch is pinned by fabricated
input on purpose.  One store fact has no contract rule at all: ``duration_ms`` is
``INTEGER NOT NULL CHECK (duration_ms > 0)`` and §3.2 defines the floor and the
clamp for a positive value only, so an absent (``None``) duration is this
module's own decision — the smallest usable second, so the row stays
downloadable — not a reading of the contract.  Reading the manifest in order to
avoid regressing a row is not the forbidden direction: D4 forbids the opposite
one (reading the manifest *into* the store), and the store connection is opened
``mode=ro`` so that direction is structurally impossible (spec §10).
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Mapping, Sequence

from bili_asr.page_identity import format_work_id

#: The one manifest status this derivation ever writes (spec §3.3).
QUEUE_STATUS = "needs_audio"
#: The part's effective row is the ``needs_audio`` row a previous run derived.
SKIP_ALREADY_DERIVED = "already_derived"
#: The part's effective row is a state the chain owns; the bridge adds nothing.
SKIP_CHAIN_OWNED = "chain_owned"
#: The queue row's SQL-computed ``work_id`` contradicts the Python identity rule.
SKIP_IDENTITY_MISMATCH = "identity_mismatch"


def duration_s_from_ms(duration_ms: Any) -> int:
    """Return the whole seconds one stored duration covers, at least one.

    ``duration_ms // 1000`` inverts the gateway's own encoding of the source
    duration, so an integral source duration round-trips exactly, and the floor
    is deliberate rather than a rounding choice (spec §3.2).  The result is
    clamped to ``1`` because the audio budget reads ``0`` as *unknown* and
    fail-closes: the schema admits a sub-second part (``duration_ms > 0``), and an
    absent duration states the same thing, so either way the row is written with
    the smallest usable second and stays downloadable instead of silently
    skipping every download.  §3.2 defines the floor and the clamp for a positive
    ``duration_ms`` only, so the absent arm is this module's policy for a shape
    the store cannot deliver (``NOT NULL CHECK (duration_ms > 0)``), pinned by a
    fabricated input in the tests rather than derived from the contract.
    """

    if duration_ms is None:
        return 1
    return max(1, duration_ms // 1000)


def row_for_part(part: Mapping[str, Any], pubdate: int) -> dict[str, Any]:
    """Build the one manifest row a queue row maps onto (spec §3.1).

    Exactly the nine fields of §3.1 and no others.  ``cid`` travels with the row
    so the chain needs no pagelist — ``download-audio`` skips its live identity
    call — while the store's attempt-evidence columns deliberately stay behind:
    the manifest's duration vocabulary is seconds, and a second unit on the row
    is the trap §3.2 names.  ``work_id`` is built by
    :func:`~bili_asr.page_identity.format_work_id`, the Python identity
    ``ManifestStore.upsert`` re-validates, never copied from the store's
    SQL-computed value — §3.6 compares the two and skips the row when they
    disagree.
    """

    bvid = part["bvid"]
    page_index = part["page_index"]
    return {
        "work_id": format_work_id(bvid, page_index),
        "bvid": bvid,
        "page_index": page_index,
        "cid": part["cid"],
        "title": part["part_title"],
        "duration_s": duration_s_from_ms(part["duration_ms"]),
        "pubdate": pubdate,
        "pubdate_str": time.strftime("%Y-%m-%d", time.gmtime(pubdate)),
        "status": QUEUE_STATUS,
    }


@dataclass(frozen=True)
class DerivationOutcome:
    """What one derivation decided, per queue row and in the queue's order.

    ``appended`` holds the rows the caller must write, in the order the queue
    gave them, so the manifest's history reads in the order the chain will work.
    The three tuples name the skipped rows by the store's own ``work_id``
    spelling: ``already_derived`` and ``chain_owned`` are §3.4's two non-append
    answers, and ``identity_mismatch`` is §3.6's store self-contradiction — the
    one case where the store's form and the Python form differ, so the store's
    form is the row an operator has to go and look at.  No store the shipped
    writers produce can reach that third branch (the module docstring says why):
    it is defence, kept so a store that stopped agreeing with itself is named
    rather than crashed on.
    """

    appended: tuple[dict[str, Any], ...]
    already_derived: tuple[str, ...]
    chain_owned: tuple[str, ...]
    identity_mismatch: tuple[str, ...]


def derive_rows(
    parts: Sequence[Mapping[str, Any]],
    pubdates: Mapping[str, int],
    existing: Mapping[str, Mapping[str, Any]],
) -> DerivationOutcome:
    """Decide, per queue row, whether the manifest needs a derived row (spec §3.4).

    Additive, never authoritative: a ``work_id`` whose effective manifest row
    already exists is left alone — a row the chain advanced is not regressed and
    a row a previous run derived is not written twice — and only a part with no
    effective row is appended.  ``existing`` is read, never mutated.
    ``pubdate`` is looked up by the part's ``bvid``, the ``videos`` foreign key
    the store enforces with ``PRAGMA foreign_keys = ON``, so the lookup is total
    and a miss is a corrupt store: it stays a ``KeyError`` rather than becoming an
    invented publication date on a row nobody can correct afterwards.
    """

    appended: list[dict[str, Any]] = []
    already_derived: list[str] = []
    chain_owned: list[str] = []
    identity_mismatch: list[str] = []
    for part in parts:
        candidate = row_for_part(part, pubdates[part["bvid"]])
        stored_work_id = part["work_id"]
        if stored_work_id != candidate["work_id"]:
            identity_mismatch.append(stored_work_id)
            continue
        held = existing.get(candidate["work_id"])
        if held is None:
            appended.append(candidate)
        elif held.get("status") == QUEUE_STATUS:
            already_derived.append(candidate["work_id"])
        else:
            chain_owned.append(candidate["work_id"])
    return DerivationOutcome(
        appended=tuple(appended),
        already_derived=tuple(already_derived),
        chain_owned=tuple(chain_owned),
        identity_mismatch=tuple(identity_mismatch),
    )


__all__ = [
    "DerivationOutcome",
    "QUEUE_STATUS",
    "SKIP_ALREADY_DERIVED",
    "SKIP_CHAIN_OWNED",
    "SKIP_IDENTITY_MISMATCH",
    "derive_rows",
    "duration_s_from_ms",
    "row_for_part",
]
