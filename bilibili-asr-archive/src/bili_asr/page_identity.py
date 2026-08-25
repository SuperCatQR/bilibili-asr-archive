"""Canonical per-page identity for the archive ledger and filesystem.

`work_id` uses `:` as identity punctuation and must never appear in paths.
Filesystem names use `artifact_stem` only.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

_WORK_ID_RE = re.compile(r"^(?P<bvid>[^:]+):p(?P<page_index>0|[1-9]\d*)$")


@dataclass(frozen=True)
class PageIdentity:
    work_id: str
    bvid: str
    page_index: int
    cid: int
    page_label: str = ""


def format_work_id(bvid: str, page_index: int) -> str:
    if not bvid:
        raise ValueError("bvid is required")
    if page_index < 0:
        raise ValueError(f"page_index must be >= 0, got {page_index}")
    if ":" in bvid:
        raise ValueError("bvid must not contain ':'")
    return f"{bvid}:p{page_index}"


def parse_work_id(work_id: str) -> tuple[str, int]:
    match = _WORK_ID_RE.match(work_id)
    if not match:
        raise ValueError(f"invalid work_id {work_id!r}")
    return match.group("bvid"), int(match.group("page_index"))


def artifact_stem(identity: PageIdentity) -> str:
    stem = f"{identity.bvid}.p{identity.page_index}"
    if ":" in stem:
        raise ValueError("artifact_stem must not contain ':'")
    return stem


def page_query_index(page_index: int) -> int:
    """1-based `?p=` query value for public Bilibili URLs."""
    if page_index < 0:
        raise ValueError(f"page_index must be >= 0, got {page_index}")
    return page_index + 1


def page_identity(
    bvid: str,
    page_index: int,
    cid: int,
    page_label: str = "",
) -> PageIdentity:
    return PageIdentity(
        work_id=format_work_id(bvid, page_index),
        bvid=bvid,
        page_index=page_index,
        cid=cid,
        page_label=page_label,
    )


def apply_identity(entry: dict, identity: PageIdentity) -> dict:
    """Copy canonical page fields onto a ledger row."""
    updated = dict(entry)
    updated["bvid"] = identity.bvid
    updated["work_id"] = identity.work_id
    updated["page_index"] = identity.page_index
    updated["cid"] = identity.cid
    if identity.page_label:
        updated["page_label"] = identity.page_label
    elif "page_label" not in updated:
        updated["page_label"] = ""
    return updated


def identity_from_entry(
    entry: dict, key: str
) -> "PageIdentity | str":
    """Identity for a ledger row: PageIdentity when the row is
    page-resolved, otherwise the bare bvid fallback string."""
    work_id = entry.get("work_id")
    cid = entry.get("cid")
    bvid = str(entry.get("bvid") or key)
    if work_id and cid is not None:
        return page_identity(
            bvid,
            int(entry.get("page_index") or 0),
            int(cid),
            page_label=str(entry.get("page_label") or ""),
        )
    return bvid
