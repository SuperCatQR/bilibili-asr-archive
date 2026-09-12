from __future__ import annotations

import json

from bili_asr.archive import archive_bundle_complete, bundle_marker_path, write_archive
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
    assert 'work_id: "BV1demo:p0"' in md
    assert "page_index: 0" in md
    assert "cid: 99" in md
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
    assert 'work_id: "BV1multi:p0"' in md0
    assert "page_index: 0" in md0
    assert "cid: 111" in md0
    assert 'work_id: "BV1multi:p1"' in md1
    assert "page_index: 1" in md1
    assert "cid: 222" in md1
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
    md = (tmp_path / paths["md_path"]).read_text(encoding="utf-8")
    assert "work_id:" not in md
    assert "page_index:" not in md



def test_archive_bundle_rejects_unrelated_in_root_artifacts(tmp_root):
    from pathlib import Path
    import hashlib

    root = Path(tmp_root)
    unrelated = root / "unrelated"
    unrelated.mkdir()
    files = {
        "srt_path": unrelated / "wrong.srt",
        "txt_path": unrelated / "wrong.txt",
        "md_path": unrelated / "wrong.md",
        "raw_path": unrelated / "wrong.json",
    }
    contents = {
        key: f"{key}\n".encode() for key in files
    }
    for key, path in files.items():
        path.write_bytes(contents[key])
    marker = files["srt_path"].with_name(files["srt_path"].name + ".bundle-ready")
    marker.write_text(json.dumps({
        "schema": "archive-bundle-v1",
        "artifacts": {
            key: {"path": str(path.relative_to(root)),
                  "sha256": hashlib.sha256(contents[key]).hexdigest()}
            for key, path in files.items()
        },
    }), encoding="ascii")
    paths = {key: str(path.relative_to(root)) for key, path in files.items()}
    assert not archive_bundle_complete(root, paths)

    from pathlib import Path
    tmp_path = Path(tmp_root)
    entry = {"bvid": "BVmarker", "work_id": "BVmarker:p0", "page_index": 0, "cid": 1}
    paths = write_archive(tmp_path, entry, [{"start": 0, "end": 1, "text": "x"}], source="asr")
    assert archive_bundle_complete(tmp_path, paths)
    marker = bundle_marker_path(tmp_path / paths["srt_path"])
    marker.unlink()
    assert not archive_bundle_complete(tmp_path, paths)
    marker.write_text("bundle-ready\n", encoding="utf-8")
    (tmp_path / paths["raw_path"]).unlink()
    assert not archive_bundle_complete(tmp_path, paths)


def test_write_archive_rejects_marker_symlink_and_nonregular_without_touching_target(tmp_root):
    from pathlib import Path
    import os
    import pytest
    tmp_path = Path(tmp_root)
    row = {"bvid": "BVmarker-type", "work_id": "BVmarker-type:p0", "page_index": 0, "cid": 1}
    paths = write_archive(tmp_path, row, [{"start": 0, "end": 1, "text": "old"}], source="asr")
    marker = bundle_marker_path(tmp_path / paths["srt_path"])
    outside = tmp_path / "outside-marker"
    outside.write_text("keep", encoding="utf-8")
    marker.unlink()
    marker.symlink_to(outside)
    with pytest.raises(OSError, match="marker is not a regular file"):
        write_archive(tmp_path, row, [{"start": 0, "end": 1, "text": "new"}], source="asr")
    assert outside.read_text(encoding="utf-8") == "keep"
    assert marker.is_symlink()
    marker.unlink()
    marker.mkdir()
    with pytest.raises(OSError, match="marker is not a regular file"):
        write_archive(tmp_path, row, [{"start": 0, "end": 1, "text": "new"}], source="asr")
    assert marker.is_dir()


def test_pre_marker_archived_evidence_is_incomplete(tmp_root):
    from pathlib import Path
    tmp_path = Path(tmp_root)
    row = {"bvid": "BVlegacy-marker", "work_id": "BVlegacy-marker:p0", "page_index": 0, "cid": 1}
    paths = write_archive(tmp_path, row, [{"start": 0, "end": 1, "text": "old"}], source="asr")
    bundle_marker_path(tmp_path / paths["srt_path"]).unlink()
    assert not archive_bundle_complete(tmp_path, paths)


def test_archive_bundle_complete_does_not_leak_descriptors(tmp_path):
    import os

    if not os.path.isdir("/proc/self/fd"):
        return
    row = {"bvid": "BVfd", "work_id": "BVfd:p0", "page_index": 0, "cid": 1}
    paths = write_archive(tmp_path, row, [{"start": 0, "end": 1, "text": "x"}], source="asr")
    before = len(os.listdir("/proc/self/fd"))
    for _ in range(100):
        assert archive_bundle_complete(tmp_path, paths)
    after = len(os.listdir("/proc/self/fd"))
    assert after <= before + 1


def test_archive_failure_cleans_only_owned_staging(tmp_root, monkeypatch):
    from pathlib import Path
    tmp_path = Path(tmp_root)
    unrelated = tmp_path / "unrelated.txt"
    unrelated.write_text("keep", encoding="utf-8")
    original_replace = __import__("os").replace
    calls = []
    def fail_after_first(src, dst, **kwargs):
        calls.append((src, dst))
        if len(calls) == 2:
            raise OSError("injected replace")
        return original_replace(src, dst)
    monkeypatch.setattr("bili_asr.archive.os.replace", fail_after_first)
    entry = {"bvid": "BVfail", "work_id": "BVfail:p0", "page_index": 0, "cid": 1}
    import pytest
    with pytest.raises(OSError):
        write_archive(tmp_path, entry, [{"start": 0, "end": 1, "text": "x"}], source="asr")
    assert unrelated.read_text(encoding="utf-8") == "keep"
    assert not list((tmp_path / "transcripts" / "srt").glob(".archive-bundle-*"))


def test_write_archive_records_asr_provenance_in_both_sinks(tmp_root):
    """A transcript must say which model produced it, in the sidecar and the MD."""

    tmp_path = __import__("pathlib").Path(tmp_root)
    ident = page_identity("BV1prov", 0, 7)
    entry = {
        "bvid": ident.bvid,
        "work_id": ident.work_id,
        "page_index": 0,
        "cid": 7,
        "title": "provenance",
        "pubdate_str": "2026-01-02",
        "duration_s": 12,
    }
    provenance = {
        "model_name": "[redacted]",
        "model_revision": "master",
        "device": "cpu",
        "language": "中文",
        "vad_model": "fsmn-vad",
        "hotwords": "未明子,马恩牌",
        "offline": "True",
        "local_source": "configured-local",
    }

    paths = write_archive(
        tmp_path,
        entry,
        [{"start": 0, "end": 1, "text": "你好。"}],
        source="asr",
        asr_provenance=provenance,
    )

    md = (tmp_path / paths["md_path"]).read_text(encoding="utf-8")
    assert 'asr_vad_model: "fsmn-vad"' in md
    assert 'asr_hotwords: "未明子,马恩牌"' in md
    raw = json.loads((tmp_path / paths["raw_path"]).read_text(encoding="utf-8"))
    assert raw["provenance"] == provenance
    assert raw["source"] == "asr"


def test_write_archive_without_provenance_adds_no_asr_keys(tmp_root):
    """The subtitle path records nothing about an ASR model."""

    tmp_path = __import__("pathlib").Path(tmp_root)
    ident = page_identity("BV1noprov", 0, 8)
    entry = {"bvid": ident.bvid, "work_id": ident.work_id, "page_index": 0, "cid": 8,
             "title": "no provenance", "pubdate_str": "2026-01-02", "duration_s": 5}

    paths = write_archive(tmp_path, entry, [{"start": 0, "end": 1, "text": "hi"}], source="subtitle")

    md = (tmp_path / paths["md_path"]).read_text(encoding="utf-8")
    assert "asr_" not in md
    raw = json.loads((tmp_path / paths["raw_path"]).read_text(encoding="utf-8"))
    assert "provenance" not in raw
