"""Read-only projections of the SQLite workflow data plane.

The workflow database is the source for current operational facts.  This module
keeps query and export code from reaching into scheduling tables ad hoc while
leaving the durable transcript and publication records owned by their storage
repositories.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from bili_asr.archive import archive_bundle_complete, bundle_relpaths_for_stem
from bili_asr.artifact_root import ArtifactRoots
from bili_asr.formatting import pubdate_utc
from bili_asr.page_identity import PageIdentity, artifact_stem

WORKFLOW_STATUSES = frozenset({"meta_ok", "subtitle_done", "asr_done", "archived"})


def _source_rank(value: str) -> int:
    return {"subtitle-cc": 0, "subtitle-ai": 1, "asr-local": 2}.get(value, 9)


def _choose_transcript(rows: list[sqlite3.Row]) -> sqlite3.Row | None:
    if not rows:
        return None
    return min(
        rows,
        key=lambda row: (
            _source_rank(str(row["source_kind"])),
            0 if str(row["language"]).lower().startswith(("zh", "ai-zh")) else 1,
            -int(row["version"]),
            -int(row["created_at"]),
            -int(row["transcript_id"]),
        ),
    )


def _part_rows(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT vp.video_part_id, vp.bvid, vp.page_index, vp.cid, vp.title AS part_title,
               vp.duration_ms, v.title AS video_title, v.pubdate
        FROM video_parts AS vp JOIN videos AS v ON v.bvid = vp.bvid
        WHERE vp.processing_status <> 'gone'
        ORDER BY v.pubdate DESC, vp.bvid, vp.page_index
        """
    ).fetchall()


def workflow_records(
    archive_root: str | Path, *, with_text: bool = False, artifact_roots: ArtifactRoots | None = None
) -> dict[str, dict[str, Any]]:
    """Project one row per active video part from SQLite workflow facts."""
    roots = artifact_roots or ArtifactRoots.of(archive_root)
    root = roots.archive_root
    database = root / "archive.db"
    if not database.is_file():
        return {}
    connection = sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        records: dict[str, dict[str, Any]] = {}
        for part in _part_rows(connection):
            identity = PageIdentity(
                work_id=f"{part['bvid']}:p{part['page_index']}",
                bvid=str(part["bvid"]),
                page_index=int(part["page_index"]),
                cid=int(part["cid"]),
                page_label=str(part["part_title"]),
            )
            work_id = identity.work_id
            transcript_rows = connection.execute(
                "SELECT * FROM transcripts WHERE video_part_id = ?",
                (int(part["video_part_id"]),),
            ).fetchall()
            transcript = _choose_transcript(transcript_rows)
            publication = None
            if transcript is not None:
                publication = connection.execute(
                    """
                    SELECT artifact_json FROM workflow_publications
                    WHERE video_part_id = ? AND transcript_id = ?
                    """,
                    (int(part["video_part_id"]), int(transcript["transcript_id"])),
                ).fetchone()
            entry: dict[str, Any] = {
                "work_id": work_id,
                "bvid": str(part["bvid"]),
                "page_index": int(part["page_index"]),
                "cid": int(part["cid"]),
                "title": str(part["part_title"]),
                "video_title": str(part["video_title"]),
                "duration_s": max(0.001, int(part["duration_ms"]) / 1000),
                "pubdate_str": pubdate_utc(int(part["pubdate"])),
                "source": None,
                "language": None,
                "version": None,
                "transcript_id": None,
            }
            if transcript is None:
                entry["status"] = "meta_ok"
                entry.update(bundle_relpaths_for_stem(artifact_stem(identity)))
                records[work_id] = entry
                continue
            entry.update(
                {
                    "source": str(transcript["source_kind"]),
                    "language": str(transcript["language"]),
                    "version": int(transcript["version"]),
                    "transcript_id": int(transcript["transcript_id"]),
                }
            )
            stem = artifact_stem(identity)
            paths = bundle_relpaths_for_stem(stem)
            entry.update(paths)
            if with_text:
                segments = connection.execute(
                    """
                    SELECT start_ms, end_ms, text FROM transcript_segments
                    WHERE transcript_id = ? ORDER BY ordinal
                    """,
                    (int(transcript["transcript_id"]),),
                ).fetchall()
                entry["transcript_text"] = "\n".join(str(row["text"]) for row in segments)
            published = False
            if publication is not None:
                try:
                    stored_paths = json.loads(str(publication["artifact_json"]))
                    if isinstance(stored_paths, dict):
                        paths = {
                            key: str(stored_paths.get(key, value))
                            for key, value in paths.items()
                        }
                        entry.update(paths)
                    published = any(archive_bundle_complete(base, paths) for base in roots.read_bases())
                except (OSError, TypeError, ValueError, json.JSONDecodeError):
                    published = False
            entry["status"] = "archived" if published else (
                "asr_done" if str(transcript["source_kind"]) == "asr-local" else "subtitle_done"
            )
            records[work_id] = entry
        return records
    finally:
        connection.close()


def workflow_has_data(archive_root: str | Path) -> bool:
    path = Path(archive_root) / "archive.db"
    return path.is_file()
