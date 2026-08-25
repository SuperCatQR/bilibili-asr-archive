"""Export manifest metadata to JSON or CSV formats."""

from __future__ import annotations

import csv
import io
import json
import os
from typing import Any

from .manifest import ManifestStore
from .search_index import extract_transcript_text

STANDARD_CSV_COLUMNS: tuple[str, ...] = (
    "work_id",
    "bvid",
    "page_index",
    "cid",
    "page_label",
    "title",
    "status",
    "duration_s",
    "pubdate",
    "source",
    "srt_path",
    "txt_path",
    "md_path",
    "raw_path",
    "audio_path",
)

SENSITIVE_EXPORT_KEYS: frozenset[str] = frozenset(
    {
        "sessdata",
        "cookie",
        "cookies",
        "bili_sessdata",
        "url",
        "signed_url",
        "stream_url",
        "audio_url",
        "traceback",
        "exception",
        "error_trace",
    }
)


def sanitize_export_entry(
    entry: dict[str, Any],
    with_text: bool = False,
    archive_root: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Return a sanitized copy of a manifest entry without credentials/signed URLs.

    If with_text is True and archive_root is provided, transcript text is loaded
    and attached under 'transcript_text'. If with_text is False, transcript text
    is excluded.
    """
    sanitized: dict[str, Any] = {}
    for key, value in entry.items():
        if key.lower() in SENSITIVE_EXPORT_KEYS:
            continue
        # Exclude transcript_text by default unless explicitly requested
        if key in ("transcript_text", "text") and not with_text:
            continue
        sanitized[key] = value

    if with_text:
        if "transcript_text" not in sanitized:
            if archive_root is not None:
                text, _paths = extract_transcript_text(archive_root, entry)
                sanitized["transcript_text"] = text
            else:
                sanitized["transcript_text"] = ""

    return sanitized


def export_rows(
    store_or_entries: ManifestStore | dict[str, dict[str, Any]],
    status_filter: set[str] | list[str] | None = None,
    with_text: bool = False,
    archive_root: str | os.PathLike[str] | None = None,
) -> list[dict[str, Any]]:
    """Derive sanitized export rows from the manifest, optionally filtered by status."""
    if isinstance(store_or_entries, ManifestStore):
        entries = store_or_entries.load()
        root = archive_root if archive_root is not None else store_or_entries.root
    else:
        entries = store_or_entries
        root = archive_root

    filter_set = set(status_filter) if status_filter is not None else None

    def _sort_key(item: tuple[str, dict[str, Any]]) -> tuple[str, int, str]:
        key, entry = item
        bvid = str(entry.get("bvid") or key)
        page_idx = entry.get("page_index")
        page_num = (
            int(page_idx)
            if isinstance(page_idx, (int, str)) and str(page_idx).isdigit()
            else 0
        )
        work_id = str(entry.get("work_id") or key)
        return (bvid, page_num, work_id)

    sorted_entries = sorted(entries.items(), key=_sort_key)
    rows: list[dict[str, Any]] = []

    for _key, entry in sorted_entries:
        entry_status = str(entry.get("status") or "")
        if filter_set is not None and entry_status not in filter_set:
            continue
        sanitized = sanitize_export_entry(
            entry, with_text=with_text, archive_root=root
        )
        rows.append(sanitized)

    return rows


def format_json_export(rows: list[dict[str, Any]]) -> str:
    """Serialize exported rows to formatted JSON."""
    return json.dumps(rows, indent=2, ensure_ascii=False)


def format_csv_export(
    rows: list[dict[str, Any]],
    with_text: bool = False,
) -> str:
    """Serialize exported rows to CSV format."""
    seen_keys: set[str] = set()
    for row in rows:
        seen_keys.update(row.keys())

    fieldnames: list[str] = [col for col in STANDARD_CSV_COLUMNS if col in seen_keys or not rows]
    if with_text:
        fieldnames.append("transcript_text")

    # Add remaining custom columns deterministically
    extra_keys = sorted(k for k in seen_keys if k not in fieldnames and k != "transcript_text")
    fieldnames.extend(extra_keys)

    # Ensure fieldnames has standard columns if rows is empty
    if not fieldnames:
        fieldnames = list(STANDARD_CSV_COLUMNS)
        if with_text:
            fieldnames.append("transcript_text")

    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=fieldnames,
        lineterminator="\n",
        extrasaction="ignore",
    )
    writer.writeheader()

    for row in rows:
        formatted_row: dict[str, Any] = {}
        for k in fieldnames:
            val = row.get(k)
            if val is None:
                formatted_row[k] = ""
            elif isinstance(val, (dict, list)):
                formatted_row[k] = json.dumps(val, ensure_ascii=False)
            else:
                formatted_row[k] = str(val)
        writer.writerow(formatted_row)

    return buffer.getvalue()


def export_manifest(
    archive_root: str | os.PathLike[str],
    fmt: str,
    out_path: str | os.PathLike[str] | None = None,
    status_filter: set[str] | list[str] | None = None,
    with_text: bool = False,
) -> str:
    """Export manifest-derived rows to JSON or CSV format.

    Manifest remains SSOT and is never modified.
    """
    fmt_lower = fmt.lower().strip()
    if fmt_lower not in {"json", "csv"}:
        raise ValueError(f"unsupported export format: {fmt!r}; choose 'json' or 'csv'")

    store = ManifestStore(archive_root)
    entries = store.load()
    rows = export_rows(
        entries,
        status_filter=status_filter,
        with_text=with_text,
        archive_root=archive_root,
    )

    if fmt_lower == "json":
        content = format_json_export(rows)
    else:
        content = format_csv_export(rows, with_text=with_text)

    if out_path and str(out_path) != "-":
        out_str = os.fspath(out_path)
        parent = os.path.dirname(out_str)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(out_str, "w", encoding="utf-8") as fh:
            fh.write(content)
            if not content.endswith("\n"):
                fh.write("\n")

    return content
