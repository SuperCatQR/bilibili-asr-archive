"""Archive writers for timestamped transcript outputs."""

from __future__ import annotations

import json
import os
from typing import Any

from .asr import segments_to_srt, segments_to_txt


def _safe_name(value: str) -> str:
    value = "".join(ch for ch in value if ch not in '<>:"/\\|?*')
    return " ".join(value.split()).strip()[:120] or "untitled"


def write_archive(
    archive_root: str | os.PathLike[str],
    entry: dict[str, Any],
    segments: list[dict[str, Any]],
    *,
    source: str,
    raw: Any | None = None,
) -> dict[str, str]:
    root = os.fspath(archive_root)
    bvid = str(entry["bvid"])
    dirs = {name: os.path.join(root, "transcripts", name)
            for name in ("srt", "txt", "md", "raw")}
    for directory in dirs.values():
        os.makedirs(directory, exist_ok=True)

    srt_path = os.path.join(dirs["srt"], f"{bvid}.srt")
    txt_path = os.path.join(dirs["txt"], f"{bvid}.txt")
    title = _safe_name(str(entry.get("title") or bvid))
    md_path = os.path.join(dirs["md"], f"{entry.get('pubdate_str', 'unknown')}_{bvid}_{title}.md")
    raw_path = os.path.join(dirs["raw"], f"{bvid}.json")

    with open(srt_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(segments_to_srt(segments))
    with open(txt_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(segments_to_txt(segments) + "\n")
    frontmatter = {
        "bvid": bvid,
        "title": entry.get("title", ""),
        "date": entry.get("pubdate_str", ""),
        "duration_s": entry.get("duration_s", 0),
        "source": source,
        "url": f"https://www.bilibili.com/video/{bvid}",
    }
    with open(md_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("---\n")
        for key, value in frontmatter.items():
            fh.write(f"{key}: {json.dumps(value, ensure_ascii=False)}\n")
        fh.write("---\n\n")
        fh.write(segments_to_txt(segments))
        fh.write("\n")
    if raw is None:
        raw = {"segments": segments, "source": source}
    with open(raw_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(raw, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return {
        "srt_path": os.path.relpath(srt_path, root),
        "txt_path": os.path.relpath(txt_path, root),
        "md_path": os.path.relpath(md_path, root),
        "raw_path": os.path.relpath(raw_path, root),
    }
