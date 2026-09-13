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


def _frontmatter(md_path):
    """The published frontmatter as a mapping, read from the artefact itself."""

    text = md_path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    block = text.split("\n---\n", 1)[0][len("---\n"):]
    return {line.split(": ", 1)[0]: json.loads(line.split(": ", 1)[1]) for line in block.splitlines()}


def _recomputed_capture(raw_segments, duration_s, gap=1.0):
    """Recompute the capture facts from ``raw.json`` alone, independently.

    Deliberately not the production helper: A5's claim is that a reader holding
    only the artefact can re-derive the numbers, so the merge is written out
    here the way that reader would.
    """

    spans = sorted((float(s["start"]), float(s["end"])) for s in raw_segments)
    merged = []
    for start, end in spans:
        if merged and start - merged[-1][1] <= gap:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    captured = round(sum(end - start for start, end in merged), 3)
    ratio = None if duration_s <= 0 else round(min(1.0, captured / duration_s), 3)
    return len(merged), captured, ratio


def test_write_archive_records_the_vad_capture_facts(tmp_root):
    """A speaker pause and a VAD miss must be distinguishable from the artefact."""

    tmp_path = __import__("pathlib").Path(tmp_root)
    ident = page_identity("BV1vad", 0, 11)
    entry = {"bvid": ident.bvid, "work_id": ident.work_id, "page_index": 0, "cid": 11,
             "title": "capture", "pubdate_str": "2026-01-02", "duration_s": 10}
    segments = [
        {"start": 0.0, "end": 2.0, "text": "第一句。"},
        {"start": 2.0, "end": 4.0, "text": "第二句。"},
        {"start": 8.0, "end": 9.0, "text": "第三句。"},
    ]

    paths = write_archive(tmp_path, entry, segments, source="asr")

    front = _frontmatter(tmp_path / paths["md_path"])
    raw = json.loads((tmp_path / paths["raw_path"]).read_text(encoding="utf-8"))
    count, captured, ratio = _recomputed_capture(raw["segments"], front["duration_s"])
    # The 4 s hole is a real capture gap; the touching cues are one span.
    assert (count, captured, ratio) == (2, 5.0, 0.5)
    assert front["asr_vad_segments"] == count
    assert front["asr_vad_captured_s"] == captured
    assert front["asr_vad_captured_ratio"] == ratio


def test_write_archive_without_vad_capture_keys_on_the_subtitle_path(tmp_root):
    """A subtitle row gained none of the three keys: only the ASR path has a VAD."""

    tmp_path = __import__("pathlib").Path(tmp_root)
    ident = page_identity("BV1subvad", 0, 12)
    entry = {"bvid": ident.bvid, "work_id": ident.work_id, "page_index": 0, "cid": 12,
             "title": "subtitle", "pubdate_str": "2026-01-02", "duration_s": 10}
    # Same segments the ASR case would have merged, so only the gate differs.
    segments = [{"start": 0.0, "end": 2.0, "text": "句子。"}, {"start": 8.0, "end": 9.0, "text": "另一句。"}]

    paths = write_archive(tmp_path, entry, segments, source="subtitle")

    front = _frontmatter(tmp_path / paths["md_path"])
    for key in ("asr_vad_segments", "asr_vad_captured_s", "asr_vad_captured_ratio"):
        assert key not in front


def test_capture_gap_seconds_follows_the_cue_shaper_threshold():
    """The local constant is the shaper's own pause threshold, and must not drift."""

    from bili_asr import asr as asr_module
    from bili_asr.archive import CAPTURE_GAP_SECONDS

    assert CAPTURE_GAP_SECONDS == asr_module._CUE_MAX_GAP_SECONDS


def test_capture_merges_only_gaps_within_the_threshold(tmp_root):
    """A gap the shaper would have split on stays a hole; one it tolerates does not."""

    tmp_path = __import__("pathlib").Path(tmp_root)
    from bili_asr.archive import CAPTURE_GAP_SECONDS

    def captured_for(gap):
        entry = {"bvid": "BV1gap", "work_id": "BV1gap:p0", "page_index": 0, "cid": 13,
                 "title": "gap", "pubdate_str": "2026-01-02", "duration_s": 100}
        segments = [{"start": 0.0, "end": 1.0, "text": "甲。"},
                    {"start": 1.0 + gap, "end": 2.0 + gap, "text": "乙。"}]
        paths = write_archive(tmp_path, entry, segments, source="asr")
        return _frontmatter(tmp_path / paths["md_path"])

    at_threshold = captured_for(CAPTURE_GAP_SECONDS)
    assert at_threshold["asr_vad_segments"] == 1
    assert at_threshold["asr_vad_captured_s"] == round(1.0 + CAPTURE_GAP_SECONDS + 1.0, 3)
    beyond = captured_for(CAPTURE_GAP_SECONDS + 0.001)
    assert beyond["asr_vad_segments"] == 2
    assert beyond["asr_vad_captured_s"] == 2.0

    # Stated in absolute seconds as well, so a wrong constant fails here rather
    # than only in the coupling test: a 1.0 s gap is one span, 1.001 s is two.
    assert captured_for(1.0)["asr_vad_segments"] == 1
    assert captured_for(1.0)["asr_vad_captured_s"] == 3.0
    assert captured_for(1.001)["asr_vad_segments"] == 2
    assert captured_for(1.001)["asr_vad_captured_s"] == 2.0


def test_capture_summary_edge_cases(tmp_root):
    """One cue, no cues, overlapping cues, and an unknown duration."""

    tmp_path = __import__("pathlib").Path(tmp_root)

    def front_for(bvid, segments, duration_s, source="asr"):
        entry = {"bvid": bvid, "work_id": f"{bvid}:p0", "page_index": 0, "cid": 14,
                 "title": "edge", "pubdate_str": "2026-01-02"}
        if duration_s is not None:
            entry["duration_s"] = duration_s
        paths = write_archive(tmp_path, entry, segments, source=source)
        return _frontmatter(tmp_path / paths["md_path"]), paths

    # A single cue is one span, and its own length is the captured audio.
    single, _ = front_for("BV1one", [{"start": 1.0, "end": 2.5, "text": "独。"}], 10)
    assert single["asr_vad_segments"] == 1
    assert single["asr_vad_captured_s"] == 1.5
    assert single["asr_vad_captured_ratio"] == 0.15

    # No cues at all: zero captured audio is a fact, not a hole in the record.
    empty, _ = front_for("BV1none", [], 10)
    assert empty["asr_vad_segments"] == 0
    assert empty["asr_vad_captured_s"] == 0.0
    assert empty["asr_vad_captured_ratio"] == 0.0

    # Overlapping cues count once: the union is the captured stretch.
    overlap, _ = front_for("BV1lap", [{"start": 0.0, "end": 3.0, "text": "甲。"},
                                      {"start": 1.0, "end": 2.0, "text": "乙。"}], 10)
    assert overlap["asr_vad_segments"] == 1
    assert overlap["asr_vad_captured_s"] == 3.0
    assert overlap["asr_vad_captured_ratio"] == 0.3

    # Unknown duration: the ratio has no denominator, so it is not claimed.
    # The row simply carries no ``duration_s``, as an unresolved row may not.
    unknown, unknown_paths = front_for("BV1nodur", [{"start": 0.0, "end": 2.0, "text": "甲。"}], None)
    assert unknown["asr_vad_segments"] == 1
    assert unknown["asr_vad_captured_s"] == 2.0
    assert "asr_vad_captured_ratio" not in unknown
    unknown_raw = json.loads((tmp_path / unknown_paths["raw_path"]).read_text(encoding="utf-8"))
    assert unknown_raw["segments"] == [{"start": 0.0, "end": 2.0, "text": "甲。"}]

    # The same rule for the shape this codebase actually publishes when a
    # duration cannot be parsed (``long_live`` writes the string ``unknown``):
    # the two absolute keys stand, and the ratio is still not invented.
    unparsed, _ = front_for("BV1unkstr", [{"start": 0.0, "end": 2.0, "text": "甲。"}], "unknown")
    assert unparsed["duration_s"] == "unknown"
    assert unparsed["asr_vad_segments"] == 1
    assert unparsed["asr_vad_captured_s"] == 2.0
    assert "asr_vad_captured_ratio" not in unparsed


def test_capture_ratio_is_clamped_while_seconds_are_not(tmp_root):
    """A duration/cue contradiction stays visible in the seconds, not in the ratio."""

    tmp_path = __import__("pathlib").Path(tmp_root)
    entry = {"bvid": "BV1clamp", "work_id": "BV1clamp:p0", "page_index": 0, "cid": 15,
             "title": "clamp", "pubdate_str": "2026-01-02", "duration_s": 10}
    segments = [{"start": 0.0, "end": 12.0, "text": "超过时长。"}]

    paths = write_archive(tmp_path, entry, segments, source="asr")

    front = _frontmatter(tmp_path / paths["md_path"])
    raw = json.loads((tmp_path / paths["raw_path"]).read_text(encoding="utf-8"))
    count, captured, ratio = _recomputed_capture(raw["segments"], front["duration_s"])
    assert captured == 12.0, "the seconds stay unclamped so the contradiction is visible"
    assert front["asr_vad_captured_s"] == 12.0
    assert ratio == 1.0
    assert front["asr_vad_captured_ratio"] == 1.0
    assert 0.0 <= front["asr_vad_captured_ratio"] <= 1.0
    assert front["asr_vad_segments"] == count


def test_capture_ratio_is_a_bound_across_shapes(tmp_root):
    """Whatever the cues look like, the published ratio is a proportion."""

    tmp_path = __import__("pathlib").Path(tmp_root)
    cases = [
        ([], 4),
        ([{"start": 0.0, "end": 4.0, "text": "甲。"}], 4),
        ([{"start": 3.9, "end": 40.0, "text": "甲。"}], 4),
        ([{"start": 0.5, "end": 0.5001, "text": "甲。"}], 4),
        ([{"start": 0.0, "end": 1.0, "text": "甲。"}, {"start": 5.0, "end": 6.0, "text": "乙。"}], 100),
    ]
    for index, (segments, duration_s) in enumerate(cases):
        bvid = f"BV1bound{index}"
        entry = {"bvid": bvid, "work_id": f"{bvid}:p0", "page_index": 0, "cid": 16,
                 "title": "bound", "pubdate_str": "2026-01-02", "duration_s": duration_s}
        paths = write_archive(tmp_path, entry, segments, source="asr")
        front = _frontmatter(tmp_path / paths["md_path"])
        assert 0.0 <= front["asr_vad_captured_ratio"] <= 1.0, (index, front)
        assert front["asr_vad_segments"] == len(segments)
        assert front["asr_vad_captured_s"] >= 0.0, (index, front)


def test_write_archive_summarizes_the_models_own_confidence(tmp_root):
    """A transcript states how sure the model was, so quality needs no re-run."""

    tmp_path = __import__("pathlib").Path(tmp_root)
    ident = page_identity("BV1conf", 0, 9)
    entry = {"bvid": ident.bvid, "work_id": ident.work_id, "page_index": 0, "cid": 9,
             "title": "confidence", "pubdate_str": "2026-01-02", "duration_s": 9}
    segments = [
        {"start": 0.0, "end": 2.0, "text": "第一句。", "confidence": 0.9},
        {"start": 2.0, "end": 4.0, "text": "第二句。", "confidence": 0.2},
        {"start": 4.0, "end": 6.0, "text": "第三句。"},
    ]

    paths = write_archive(tmp_path, entry, segments, source="asr")

    md = (tmp_path / paths["md_path"]).read_text(encoding="utf-8")
    assert 'asr_mean_confidence: 0.55' in md
    assert "asr_low_confidence_cues: 1" in md
    raw = json.loads((tmp_path / paths["raw_path"]).read_text(encoding="utf-8"))
    assert [segment.get("confidence") for segment in raw["segments"]] == [0.9, 0.2, None]


def test_write_archive_without_confidence_claims_nothing(tmp_root):
    tmp_path = __import__("pathlib").Path(tmp_root)
    ident = page_identity("BV1noconf", 0, 10)
    entry = {"bvid": ident.bvid, "work_id": ident.work_id, "page_index": 0, "cid": 10,
             "title": "plain subtitle", "pubdate_str": "2026-01-02", "duration_s": 2}

    paths = write_archive(tmp_path, entry, [{"start": 0, "end": 2, "text": "句子。"}], source="subtitle")

    md = (tmp_path / paths["md_path"]).read_text(encoding="utf-8")
    assert "confidence" not in md
