from __future__ import annotations

import json

from bili_asr.archive import write_archive
from bili_asr.page_identity import artifact_stem, page_identity


def test_write_archive_layout_and_frontmatter(tmp_root):
    tmp_path = __import__("pathlib").Path(tmp_root)
    ident = page_identity("BV1demo", 0, 99)
    entry = {
        "bvid": ident.bvid,
        "work_id": ident.work_id,
        "page_index": 0,
        "cid": 99,
        "title": "标题",
        "pubdate_str": "2026-01-02",
        "duration_s": 12,
    }
    paths = write_archive(tmp_path, entry, [{"start": 0, "end": 1, "text": "你好"}], source="asr")
    md = (tmp_path / paths["md_path"]).read_text(encoding="utf-8")
    assert md.startswith("---\nbvid: \"BV1demo\"\n")
    assert 'source: "asr"' in md
    assert artifact_stem(ident) in paths["srt_path"]
    assert (tmp_path / paths["srt_path"]).exists()
    assert json.loads((tmp_path / paths["raw_path"]).read_text(encoding="utf-8"))["source"] == "asr"


def test_write_archive_pages_do_not_collide_and_rerun_is_stable(tmp_root):
    tmp_path = __import__("pathlib").Path(tmp_root)
    p0 = page_identity("BV1multi", 0, 111)
    p1 = page_identity("BV1multi", 1, 222)
    segs = [{"start": 0, "end": 1, "text": "x"}]
    e0 = {
        "bvid": p0.bvid, "work_id": p0.work_id, "page_index": 0, "cid": 111,
        "title": "multi", "pubdate_str": "2026-01-02",
    }
    e1 = {
        "bvid": p1.bvid, "work_id": p1.work_id, "page_index": 1, "cid": 222,
        "title": "multi", "pubdate_str": "2026-01-02",
    }
    first0 = write_archive(tmp_path, e0, segs, source="asr")
    first1 = write_archive(tmp_path, e1, segs, source="asr")
    assert first0["srt_path"] != first1["srt_path"]
    assert first0["txt_path"] != first1["txt_path"]
    assert first0["md_path"] != first1["md_path"]
    assert first0["raw_path"] != first1["raw_path"]
    md1 = (tmp_path / first1["md_path"]).read_text(encoding="utf-8")
    assert "?p=2" in md1
    md0 = (tmp_path / first0["md_path"]).read_text(encoding="utf-8")
    assert "?p=" not in md0
    second0 = write_archive(tmp_path, e0, segs, source="asr")
    second1 = write_archive(tmp_path, e1, segs, source="asr")
    assert second0 == first0
    assert second1 == first1


def test_write_archive_unresolved_keeps_bare_bvid_stem(tmp_root):
    tmp_path = __import__("pathlib").Path(tmp_root)
    entry = {
        "bvid": "BV1legacy",
        "title": "legacy",
        "pubdate_str": "2026-01-02",
        "unresolved": True,
        "unresolved_reason": "ambiguous_bare_bvid",
    }
    paths = write_archive(tmp_path, entry, [{"start": 0, "end": 1, "text": "x"}], source="asr")
    assert paths["srt_path"].endswith("BV1legacy.srt")
    assert ".p" not in paths["srt_path"]
