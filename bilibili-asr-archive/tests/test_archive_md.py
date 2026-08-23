from __future__ import annotations

import json

from bili_asr.archive import write_archive


def test_write_archive_layout_and_frontmatter(tmp_root):
    tmp_path = __import__("pathlib").Path(tmp_root)
    entry = {"bvid": "BV1demo", "title": "标题", "pubdate_str": "2026-01-02", "duration_s": 12}
    paths = write_archive(tmp_path, entry, [{"start": 0, "end": 1, "text": "你好"}], source="asr")
    md = (tmp_path / paths["md_path"]).read_text(encoding="utf-8")
    assert md.startswith("---\nbvid: \"BV1demo\"\n")
    assert 'source: "asr"' in md
    assert (tmp_path / paths["srt_path"]).exists()
    assert json.loads((tmp_path / paths["raw_path"]).read_text(encoding="utf-8"))["source"] == "asr"
