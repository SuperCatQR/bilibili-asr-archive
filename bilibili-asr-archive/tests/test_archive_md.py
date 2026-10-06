from __future__ import annotations

import json
import os

import pytest

from bili_asr.archive import archive_bundle_complete, bundle_marker_path, bundle_paths, write_archive
from bili_asr.page_identity import artifact_stem, page_identity
from bili_asr.services.manifest_derivation import QUEUE_STATUS


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
    assert paths["srt_path"].endswith("BV1legacy/bundle.srt")
    assert ".p" not in paths["srt_path"]
    md = (tmp_path / paths["md_path"]).read_text(encoding="utf-8")
    assert "work_id:" not in md
    assert "page_index:" not in md


def test_bundle_paths_names_the_four_families_and_the_derived_md_name(tmp_root):
    """``bundle_paths`` names the four families; the writer publishes those names."""
    from pathlib import Path

    root = Path(tmp_root)
    ident = page_identity("BV1paths", 0, 77)
    entry = {
        "bvid": ident.bvid,
        "work_id": ident.work_id,
        "page_index": 0,
        "cid": 77,
        "title": 'A/B: "quoted"  title',
        "pubdate_str": "2026-01-02",
    }
    stem = artifact_stem(ident)
    paths = bundle_paths(root, entry)
    assert set(paths) == {"srt_path", "txt_path", "md_path", "raw_path"}
    assert paths["srt_path"] == root / "transcripts" / f"{stem}" / "bundle.srt"
    assert paths["txt_path"] == root / "transcripts" / f"{stem}" / "bundle.txt"
    assert paths["raw_path"] == root / "transcripts" / f"{stem}" / "bundle.raw.json"
    assert paths["md_path"] == root / "transcripts" / f"{stem}" / "bundle.md"
    assert all(path.is_absolute() for path in paths.values())

    written = write_archive(root, entry, [{"start": 0, "end": 1, "text": "x"}], source="asr")
    assert set(written) == set(paths)
    assert all(root / written[key] == paths[key] for key in paths)

    unresolved = bundle_paths(
        root,
        {"bvid": "BV1legacy", "title": "legacy", "pubdate_str": "2026-01-02", "unresolved": True},
    )
    no_cid = bundle_paths(
        root,
        {"bvid": "BV1nocid", "work_id": "BV1nocid:p0", "page_index": 0, "title": "legacy", "pubdate_str": "2026-01-02"},
    )
    assert unresolved["srt_path"] == root / "transcripts" / "BV1legacy" / "bundle.srt"
    assert unresolved["md_path"] == root / "transcripts" / "BV1legacy" / "bundle.md"
    assert no_cid["srt_path"] == root / "transcripts" / "BV1nocid" / "bundle.srt"
    assert no_cid["raw_path"] == root / "transcripts" / "BV1nocid" / "bundle.raw.json"



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
    try:
        marker.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
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
    assert not list((tmp_path / "transcripts").glob(".archive-bundle-stage-*"))


def test_failed_stage_cleanup_does_not_block_later_publication(tmp_root, monkeypatch):
    from pathlib import Path
    import os

    tmp_path = Path(tmp_root)
    if os.name == "nt":
        pytest.skip("the native Windows publisher uses file replacement without POSIX stage directories")
    entry = {"bvid": "BVcleanup", "work_id": "BVcleanup:p0", "page_index": 0, "cid": 1}
    original_rmdir = os.rmdir
    failed = False

    def fail_once_for_stage(name, *, dir_fd=None):
        nonlocal failed
        if not failed and str(name).startswith(".archive-bundle-stage-"):
            failed = True
            raise OSError("injected stage cleanup failure")
        return original_rmdir(name, dir_fd=dir_fd)

    monkeypatch.setattr("bili_asr.archive.os.rmdir", fail_once_for_stage)
    with pytest.raises(OSError, match="injected stage cleanup failure"):
        write_archive(
            tmp_path, entry, [{"start": 0, "end": 1, "text": "first"}], source="asr"
        )

    stale_stages = list((tmp_path / "transcripts").glob(".archive-bundle-stage-*"))
    assert failed
    assert len(stale_stages) == 1

    monkeypatch.setattr("bili_asr.archive.os.rmdir", original_rmdir)
    paths = write_archive(
        tmp_path, entry, [{"start": 0, "end": 1, "text": "second"}], source="asr"
    )
    assert archive_bundle_complete(tmp_path, paths)
    assert stale_stages[0].is_dir()


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


def test_write_archive_publishes_the_exact_asr_key_set(tmp_root):
    """S-1: the whole published key set is pinned, not only the nine provenance keys.

    The block is assembled by three independent producers (``_capture_summary``,
    ``_confidence_summary``, the provenance mapping) through successive
    ``dict.update`` calls, and only the nine-key provenance sub-contract had a
    test.  A reader who greps a row meets **25 keys, 15 of them ``asr_*``**: seven
    row-identity keys, a measurement family whose capture half is source-gated
    and whose confidence half is score-gated, then the configuration family.
    Pinned as an exact list so a key that appears, disappears or is reordered
    fails here rather than silently changing what the archive says.

    **The 25th key is the deliberate format revision of compass D4/D5**
    (``video_title``, added 2026-09-26 beside ``title`` rather than replacing
    it): the entry gained the video's own title so a part named ``哲学课3`` can
    still name its collection, and this list is where that revision is recorded.
    It sits directly after ``title`` so every key that existed before keeps its
    index.
    """

    tmp_path = __import__("pathlib").Path(tmp_root)
    ident = page_identity("BV1keys", 0, 21)
    entry = {"bvid": ident.bvid, "work_id": ident.work_id, "page_index": 0, "cid": 21,
             "title": "keys", "video_title": "密钥视频", "pubdate_str": "2026-01-02",
             "duration_s": 10}
    provenance = {
        "model_name": "FunAudioLLM/Fun-ASR-Nano-2512", "model_revision": "master",
        "device": "cpu", "language": "中文", "vad_model": "fsmn-vad",
        "vad_max_segment_s": "30.0", "hotwords": "", "offline": "True",
        "local_source": "configured-local",
    }
    segments = [{"start": 0.0, "end": 2.0, "text": "甲。", "confidence": 0.9},
                {"start": 2.0, "end": 4.0, "text": "乙。", "confidence": 0.2}]

    paths = write_archive(tmp_path, entry, segments, source="asr",
                          asr_provenance=provenance)

    front = _frontmatter(tmp_path / paths["md_path"])
    assert list(front) == [
        "bvid", "title", "video_title", "date", "duration_s", "source", "url",
        "asr_vad_segments", "asr_vad_captured_s", "asr_vad_captured_ratio",
        "asr_mean_confidence", "asr_low_confidence_cues", "asr_low_confidence_at",
        "asr_model_name", "asr_model_revision", "asr_device", "asr_language",
        "asr_vad_model", "asr_vad_max_segment_s", "asr_hotwords", "asr_offline",
        "asr_local_source", "work_id", "page_index", "cid",
    ]
    assert len(front) == 25
    assert len([key for key in front if key.startswith("asr_")]) == 15
    # The declared identity is a slot replacement, never a tenth provenance key.
    assert "asr_model_id" not in front
    # Additive, never a redefinition: the part title still says what was archived.
    assert front["title"] == "keys"
    assert front["video_title"] == "密钥视频"


def test_write_archive_names_the_video_title_beside_the_part_title(tmp_root):
    """``video_title`` is additive: ``title`` keeps meaning the part title.

    The two are the measured pair, not a fabricated one — ``BV18XXcBnEz6``'s
    part is titled ``哲学课3`` while its video is titled ``【哲学进阶】现代哲学
    《第一哲学沉思录》第二讲 第二个沉思（上）``.  10 of the 63 stored parts
    diverge this way, and conflating them is exactly what compass **D5**
    forbids: ``title`` is the specific thing archived, ``video_title`` the
    collection it came from.  Both are asserted on the same published block, so
    an implementation that redefines ``title`` instead of adding a sibling key
    fails here.
    """

    tmp_path = __import__("pathlib").Path(tmp_root)
    ident = page_identity("BV1vtitle", 0, 7)
    entry = {"bvid": ident.bvid, "work_id": ident.work_id, "page_index": 0, "cid": 7,
             "title": "哲学课3", "video_title": "【哲学进阶】现代哲学 第二讲",
             "pubdate_str": "2026-01-02", "duration_s": 10}
    paths = write_archive(tmp_path, entry,
                          [{"start": 0.0, "end": 2.0, "text": "甲。"}], source="subtitle")
    front = _frontmatter(tmp_path / paths["md_path"])
    assert front["title"] == "哲学课3"          # unchanged meaning
    assert front["video_title"] == "【哲学进阶】现代哲学 第二讲"


def test_write_archive_publishes_a_uniform_key_set_without_a_video_title(tmp_root):
    """D4: the key set does not vary with the writer input that supplied it.

    Only the stored-transcript projection can hand ``write_archive`` a
    ``video_title``.  The chain/ASR path reaches it with a
    ``row_for_part`` row — the nine fields of §3.1 and **no** ``video_title``
    key (``cli.py:2266``/``:2371``/``:2473``, ``coordinator.py:492``/``:593``) —
    and the key is published with an empty default there **by decision**, not by
    accident of ``.get``.  Omitting it on that arm is refused because both pins
    of the published key set are equality-based (the ordered list below and
    ``FRONTMATTER_KEYS`` in ``tests/test_published_projection_readers.py``): an
    artifact missing the key would be a *different* published shape rather than
    a cheaper one, and a reader parsing a fixed key set would have to branch.
    ``title``/``date``/``duration_s`` on the same line emit their empty default
    the same way, and the enriched-entry case above pins the identical list, so
    the two arms can only move together.

    **Known reader-visible gap, not a completed delivery:** a chain-produced
    artifact says ``video_title: ""`` until the manifest half
    (``row_for_part``/``projection_row``) lands and gives the row a real value.
    This test pins the shape, not the value.
    """

    tmp_path = __import__("pathlib").Path(tmp_root)
    ident = page_identity("BV1chain", 0, 21)
    # ``row_for_part``'s nine fields, verbatim — including ``status``, taken from the constant
    # the deriver itself writes rather than hand-copied, so this fixture cannot drift away
    # from the row it claims to reproduce.
    entry = {"bvid": ident.bvid, "work_id": ident.work_id, "page_index": 0, "cid": 21,
             "title": "哲学课3", "duration_s": 10, "pubdate": 1_767_312_000,
             "pubdate_str": "2026-01-02", "status": QUEUE_STATUS}
    assert "video_title" not in entry
    provenance = {
        "model_name": "FunAudioLLM/Fun-ASR-Nano-2512", "model_revision": "master",
        "device": "cpu", "language": "中文", "vad_model": "fsmn-vad",
        "vad_max_segment_s": "30.0", "hotwords": "", "offline": "True",
        "local_source": "configured-local",
    }
    segments = [{"start": 0.0, "end": 2.0, "text": "甲。", "confidence": 0.9},
                {"start": 2.0, "end": 4.0, "text": "乙。", "confidence": 0.2}]

    paths = write_archive(tmp_path, entry, segments, source="asr",
                          asr_provenance=provenance)

    front = _frontmatter(tmp_path / paths["md_path"])
    # The 25 keys in order, ``video_title`` directly after ``title``: the same
    # list the enriched-entry case pins, so the two arms cannot drift apart.
    assert list(front) == [
        "bvid", "title", "video_title", "date", "duration_s", "source", "url",
        "asr_vad_segments", "asr_vad_captured_s", "asr_vad_captured_ratio",
        "asr_mean_confidence", "asr_low_confidence_cues", "asr_low_confidence_at",
        "asr_model_name", "asr_model_revision", "asr_device", "asr_language",
        "asr_vad_model", "asr_vad_max_segment_s", "asr_hotwords", "asr_offline",
        "asr_local_source", "work_id", "page_index", "cid",
    ]
    assert front["video_title"] == ""
    assert front["title"] == "哲学课3"


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

    ``end == start`` intervals are dropped before merging, which is the rule the
    published keys follow: a zero-length cue describes no captured audio, and
    leaving it in would both count a span for it and let it bridge two real
    spans into one.  Its own duration is ``0.0`` either way, so the summed
    seconds are unaffected by the skip.
    """

    spans = sorted((float(s["start"]), float(s["end"])) for s in raw_segments
                   if float(s["end"]) > float(s["start"]))
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


def test_the_shaper_and_the_merger_meet_at_the_threshold_from_opposite_sides():
    """S-4: the coupling test pins the value; this one pins the *semantics*.

    The equality above cannot notice a future change to either operator.  The
    shaper splits a formed-cue pause at ``gap >= _CUE_MAX_GAP_SECONDS``, the
    merger fuses at ``gap <= CAPTURE_GAP_SECONDS``, so a pause of exactly the
    threshold is two cues in the transcript and one captured stretch here — the
    deliberate, wider reading.  Both sides of that boundary are asserted on the
    real shaper and the real published keys, so changing either operator fails.
    """

    from bili_asr import asr as asr_module
    from bili_asr.archive import CAPTURE_GAP_SECONDS

    threshold = CAPTURE_GAP_SECONDS

    def cues_for(gap):
        """The cue builder's own output for a pause of ``gap`` between two sentences.

        Ten half-second pieces either side, so both candidate cues are already
        ``formed()`` — a pause only closes a cue that can stand on its own, and
        an undersized one is absorbed by the cue before it.
        """

        pieces = [
            {"text": ch, "start": i * 0.5, "end": i * 0.5 + 0.5}
            for i, ch in enumerate("甲乙丙丁戊己庚辛壬癸")
        ]
        base = 10 * 0.5
        pieces += [
            {"text": ch, "start": base + gap + i * 0.5,
             "end": base + gap + i * 0.5 + 0.5}
            for i, ch in enumerate("子丑寅卯辰巳午未申酉")
        ]
        return asr_module._aligned_cues(pieces)

    # The shaper splits exactly at the threshold...
    assert len(cues_for(threshold)) == 2
    assert len(cues_for(threshold - 0.001)) == 1

    # ...and the merger fuses the split it just made back into one stretch.
    tmp_path = __import__("pathlib").Path(__import__("tempfile").mkdtemp())
    entry = {"bvid": "BV1bound", "work_id": "BV1bound:p0", "page_index": 0, "cid": 14,
             "title": "boundary", "pubdate_str": "2026-01-02", "duration_s": 100}
    paths = write_archive(
        tmp_path, entry,
        [{"start": 0.0, "end": 5.0, "text": "甲。"},
         {"start": 5.0 + threshold, "end": 10.0 + threshold, "text": "乙。"}],
        source="asr",
    )
    at_threshold = _frontmatter(tmp_path / paths["md_path"])

    assert at_threshold["asr_vad_segments"] == 1
    assert at_threshold["asr_vad_captured_s"] == round(10.0 + threshold, 3)


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

    # The same rule for a duration that cannot be parsed: the two absolute keys
    # stand, and the ratio is still not invented.  The shape is synthetic — the
    # campaign plan's ``"unknown"`` duration is printed, never persisted into a
    # row — but a string duration is within the row contract, since
    # ``parse_duration_s`` tolerates strings and ``is_long_live`` accepts one.
    unparsed, _ = front_for("BV1unkstr", [{"start": 0.0, "end": 2.0, "text": "甲。"}], "unknown")
    assert unparsed["duration_s"] == "unknown"
    assert unparsed["asr_vad_segments"] == 1
    assert unparsed["asr_vad_captured_s"] == 2.0
    assert "asr_vad_captured_ratio" not in unparsed


def test_capture_ratio_is_omitted_when_the_duration_is_not_finite(tmp_root):
    """D4.6 omits the ratio for a non-finite duration, not only a non-positive one.

    ``duration <= 0`` is ``False`` for both infinities and ``nan``, so a guard
    that checked only for non-positive values would publish a **claimed ratio**
    where the spec claims nothing — ``2.0 / inf`` and ``max(0.0, nan)`` both
    land on a fabricated ``0.0``.
    """

    tmp_path = __import__("pathlib").Path(tmp_root)

    def front_for(bvid, duration_s):
        entry = {"bvid": bvid, "work_id": f"{bvid}:p0", "page_index": 0, "cid": 16,
                 "title": "non-finite", "pubdate_str": "2026-01-02", "duration_s": duration_s}
        paths = write_archive(tmp_path, entry, [{"start": 0.0, "end": 2.0, "text": "甲。"}], source="asr")
        return _frontmatter(tmp_path / paths["md_path"])

    for label, bad in (("inf", float("inf")), ("-inf", float("-inf")), ("nan", float("nan"))):
        front = front_for(f"BV1nf{label}", bad)
        # The absolute keys are still facts about the transcript.
        assert front["asr_vad_segments"] == 1, label
        assert front["asr_vad_captured_s"] == 2.0, label
        # The ratio is not one: its denominator is not a finite total.
        assert "asr_vad_captured_ratio" not in front, label


def test_capture_summary_survives_a_duration_beyond_float_range(tmp_root):
    """A corrupt duration omits the ratio; it never aborts publication.

    ``validate_manifest_record`` does not range-check ``duration_s``, and the
    row is still publishable — base archives it with the integer rendered into
    the frontmatter.  Converting it to ``float`` overflows, so the guard has to
    be total: the ratio is omitted exactly as D4.6 prescribes for a duration it
    cannot divide by, and the rest of the bundle is written as before.
    """

    tmp_path = __import__("pathlib").Path(tmp_root)
    huge = 10 ** 400
    entry = {"bvid": "BV1huge", "work_id": "BV1huge:p0", "page_index": 0, "cid": 17,
             "title": "huge", "pubdate_str": "2026-01-02", "duration_s": huge}
    segments = [{"start": 0.0, "end": 2.0, "text": "甲。"}]

    paths = write_archive(tmp_path, entry, segments, source="asr")

    front = _frontmatter(tmp_path / paths["md_path"])
    assert front["duration_s"] == huge
    assert front["asr_vad_segments"] == 1
    assert front["asr_vad_captured_s"] == 2.0
    assert "asr_vad_captured_ratio" not in front


def test_capture_ignores_degenerate_zero_length_cues_like_the_recompute(tmp_root):
    """A zero-length cue is skipped, and the published triple stays recomputable.

    The shaper emits one whenever a result carries text but no usable timings:
    ``normalize_result`` keeps it as a single zero-length segment on purpose
    ("a transcript is never silently lost"), so this is a shape real ASR output
    produces.  A reader deriving the keys from ``raw.json`` must reach the same
    answer, and does: the skip cannot move the summed seconds, because ``0.0``
    is all a zero-length span contributes.
    """

    tmp_path = __import__("pathlib").Path(tmp_root)

    def published(bvid, segments, cid):
        entry = {"bvid": bvid, "work_id": f"{bvid}:p0", "page_index": 0, "cid": cid,
                 "title": "degenerate", "pubdate_str": "2026-01-02", "duration_s": 100}
        paths = write_archive(tmp_path, entry, segments, source="asr")
        front = _frontmatter(tmp_path / paths["md_path"])
        raw = json.loads((tmp_path / paths["raw_path"]).read_text(encoding="utf-8"))
        return front, raw

    # Text the aligner cannot time is still kept, never dropped: the mark threading anchors every
    # character at the only instant it has.
    from bili_asr import asr as asr_module

    text_only = asr_module._aligned_cues(
        asr_module._thread_text("没有时间戳的一段话", [])
    )
    assert text_only[0]["text"] == "没有时间戳的一段话"
    assert [(s["start"], s["end"]) for s in text_only] == [(0.0, 0.0)]
    front, raw = published("BV1degtext", text_only, 18)
    # No captured audio is *located*, so zero spans is the fact recorded.
    assert (front["asr_vad_segments"], front["asr_vad_captured_s"]) == (0, 0.0)
    assert _recomputed_capture(raw["segments"], front["duration_s"]) == (0, 0.0, 0.0)

    # ... and one sitting in a gap: merging it would bridge two real spans into
    # one and inflate both the count and the seconds.
    front, raw = published("BV1degbridge", [{"start": 0.0, "end": 1.0, "text": "甲。"},
                                            {"start": 1.5, "end": 1.5, "text": "乙。"},
                                            {"start": 2.5, "end": 3.0, "text": "丙。"}], 19)
    assert (front["asr_vad_segments"], front["asr_vad_captured_s"]) == (2, 1.5)
    assert _recomputed_capture(raw["segments"], front["duration_s"]) == (2, 1.5, 0.015)


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


def _recomputed_low_confidence(raw_segments):
    """Recompute the location list from ``raw.json`` alone, independently.

    Deliberately not the production helper: A5's claim is that a reader holding
    only the artefact can re-derive where the doubt is, so the filter and the
    sort are written out here the way that reader would.  The threshold is read
    from ``archive.LOW_CONFIDENCE`` so the identity of the cut is pinned once
    rather than copied.
    """

    from bili_asr.archive import LOW_CONFIDENCE

    starts = [
        round(float(s["start"]), 3)
        for s in raw_segments
        if isinstance(s.get("confidence"), (int, float))
        and float(s["confidence"]) <= LOW_CONFIDENCE
    ]
    return sorted(starts)


def _confidence_entry(bvid, duration_s=900):
    ident = page_identity(bvid, 0, 13)
    return {"bvid": ident.bvid, "work_id": ident.work_id, "page_index": 0, "cid": 13,
            "title": "low confidence", "pubdate_str": "2026-01-02", "duration_s": duration_s}


def test_write_archive_records_where_the_low_confidence_cues_are(tmp_root):
    """A5: the count names how many doubts; the list names where they are.

    The cues arrive out of order and two of them share a start, so the published
    list is genuinely sorted and duplicate-preserving rather than an echo of the
    input: one entry per counted cue, ascending.  A start that needs rounding is
    published rounded, which is what makes the reader's recompute exact.
    """

    tmp_path = __import__("pathlib").Path(tmp_root)
    entry = _confidence_entry("BV1at")
    segments = [
        {"start": 812.4, "end": 815.0, "text": "稍后的一句。", "confidence": 0.31},
        {"start": 240.0, "end": 242.0, "text": "清楚的一句。", "confidence": 0.8},
        {"start": 580.6434, "end": 583.0, "text": "中段的一句。", "confidence": 0.4},
        {"start": 100.5004, "end": 103.0, "text": "开头的一句。", "confidence": 0.05},
        {"start": 100.5004, "end": 103.0, "text": "同一处的另一句。", "confidence": 0.29},
        {"start": 100.5, "end": 103.0, "text": "又一句清楚的。", "confidence": 0.95},
    ]

    paths = write_archive(tmp_path, entry, segments, source="asr")

    front = _frontmatter(tmp_path / paths["md_path"])
    raw = json.loads((tmp_path / paths["raw_path"]).read_text(encoding="utf-8"))
    # 0.05, 0.29, 0.31 and 0.40 (the threshold is inclusive); 0.8 and 0.95 are not.
    assert front["asr_low_confidence_cues"] == 4
    assert front["asr_low_confidence_at"] == [100.5, 100.5, 580.643, 812.4]
    assert front["asr_mean_confidence"] == 0.467
    # A reader with only the artefact re-derives the same list.
    assert front["asr_low_confidence_at"] == _recomputed_low_confidence(raw["segments"])
    assert len(front["asr_low_confidence_at"]) == front["asr_low_confidence_cues"]


def test_low_confidence_locations_are_three_decimal_ascending_seconds(tmp_root):
    """D4.8's format: ascending start seconds, 3 decimals, rendered as JSON."""

    tmp_path = __import__("pathlib").Path(tmp_root)
    entry = _confidence_entry("BV1fmt")
    segments = [
        {"start": 2.0004, "end": 4.0, "text": "甲。", "confidence": 0.1},
        {"start": 1.23456, "end": 3.0, "text": "乙。", "confidence": 0.2},
        {"start": 100.5, "end": 102.0, "text": "丙。", "confidence": 0.3},
    ]

    paths = write_archive(tmp_path, entry, segments, source="asr")

    md = (tmp_path / paths["md_path"]).read_text(encoding="utf-8")
    front = _frontmatter(tmp_path / paths["md_path"])
    # The exact rendered shape, so the key is greppable as a JSON list.
    assert "asr_low_confidence_at: [1.235, 2.0, 100.5]" in md
    located = front["asr_low_confidence_at"]
    assert located == sorted(located), "ascending"
    assert all(value == round(value, 3) for value in located), "3 decimals"


def test_low_confidence_locations_and_count_share_one_presence(tmp_root):
    """One filtered list, two renderings: they cannot disagree, shape by shape.

    Both keys are present exactly when the transcript carries scores — zero low
    cues is a real answer (``0`` and ``[]``), no scores is no answer (neither
    key) — and the count is the length of the same list the locations render,
    so no shape can publish a count its list does not match.
    """

    tmp_path = __import__("pathlib").Path(tmp_root)
    shapes = {
        "no scores": [{"start": 0.0, "end": 1.0, "text": "甲。"}],
        "zero low": [{"start": 0.0, "end": 1.0, "text": "甲。", "confidence": 0.9}],
        "one": [{"start": 5.0, "end": 6.0, "text": "甲。", "confidence": 0.2}],
        "several out of order": [
            {"start": 90.0, "end": 91.0, "text": "甲。", "confidence": 0.1},
            {"start": 3.0, "end": 4.0, "text": "乙。", "confidence": 0.9},
            {"start": 40.0, "end": 41.0, "text": "丙。", "confidence": 0.4},
        ],
        "duplicates": [
            {"start": 7.0, "end": 8.0, "text": "甲。", "confidence": 0.1},
            {"start": 7.0, "end": 8.0, "text": "乙。", "confidence": 0.2},
        ],
    }
    for index, (label, segments) in enumerate(shapes.items()):
        paths = write_archive(
            tmp_path, _confidence_entry(f"BV1shape{index}"), segments, source="asr"
        )
        front = _frontmatter(tmp_path / paths["md_path"])

        if label == "no scores":
            assert "asr_low_confidence_cues" not in front, label
            assert "asr_low_confidence_at" not in front, label
            continue
        # The two keys are one answer: same presence, same size, every shape.
        assert "asr_low_confidence_cues" in front, label
        assert "asr_low_confidence_at" in front, label
        assert len(front["asr_low_confidence_at"]) == front["asr_low_confidence_cues"], label
    # Zero is a real answer, not a missing one.
    zero = _frontmatter(tmp_path / (
        write_archive(
            tmp_path, _confidence_entry("BV1shape-zero"),
            shapes["zero low"], source="asr",
        )["md_path"]
    ))
    assert zero["asr_low_confidence_cues"] == 0
    assert zero["asr_low_confidence_at"] == []


@pytest.mark.parametrize(
    ("start", "expected"),
    [
        pytest.param("ABSENT", KeyError, id="missing"),
        pytest.param(None, TypeError, id="none"),
        pytest.param("not a time", ValueError, id="garbage"),
        pytest.param(float("nan"), ValueError, id="nan"),
        pytest.param(10 ** 400, OverflowError, id="huge-int"),
    ],
)
def test_locating_the_doubt_adds_no_new_way_to_fail_a_row(tmp_root, start, expected):
    """A lone unreadable start must not newly abort a row that already aborted.

    Each of these inputs already fails ``write_archive`` at base through
    ``segments_to_srt``; the location key reads the same field with the same
    ``float``/``round``, and with only one cue there is only one field to reach,
    so it raises the *same* exception type one step earlier rather than
    inventing a new failure mode.  The exact types are pinned so a future
    defensive branch cannot silently turn an unlocatable cue into a published
    ``null`` that no reader could recompute from ``raw.json``.

    The type is pinned only because this transcript has a single cue; see
    ``test_two_unreadable_starts_may_swap_the_exception_type_but_never_publish``
    for the many-cue case, where the type is explicitly *not* the guarantee.
    """

    tmp_path = __import__("pathlib").Path(tmp_root)
    segment = {"end": 1.0, "text": "甲。", "confidence": 0.1}
    if start != "ABSENT":
        segment["start"] = start

    with pytest.raises(expected):
        write_archive(
            tmp_path, _confidence_entry("BV1hostile"), [segment], source="asr"
        )


def test_two_unreadable_starts_may_swap_the_exception_type_but_never_publish(tmp_root):
    """The claim's real boundary: the *set* of failing rows, not the type.

    ``_confidence_summary`` reads only the **low** cues in filtered order; the
    formatter reads every cue in document order; and frontmatter is assembled
    before the srt, so the location read now runs first.  With two unreadable
    starts of different kinds the row therefore fails on whichever one *this*
    read reaches first, and the type can differ from the formatter's alone —
    measured: a non-low missing ``start`` behind a low ``"nope"`` raised
    ``KeyError`` at base and raises ``ValueError`` here.

    That is acceptable because the type is not what A5 promises: the row still
    fails, publishes nothing, and ``coordinator._safe_error_code`` records a
    stage code, not a contract.  Pinned so a later "let us catch it and emit
    ``null``" edit cannot pass by quietly changing which rows fail.
    """

    tmp_path = __import__("pathlib").Path(tmp_root)
    # Each failing write gets its own root below ``tmp_root``, so the assertion
    # is about *this row's* publication rather than about the fixture directory:
    # a whole-root scan passes only while the failing write is the first thing
    # in a fresh root, and fails for an unrelated reason as soon as any other
    # row has published there.
    first_root = tmp_path / "swap-first"
    first_root.mkdir()
    # Document order puts the non-low missing start first; low-filter order puts
    # the low malformed start first, which is what swaps KeyError -> ValueError.
    segments = [
        {"end": 2.0, "text": "乙。", "confidence": 0.9},
        {"start": "nope", "end": 1.0, "text": "甲。", "confidence": 0.1},
    ]

    with pytest.raises(ValueError):
        write_archive(
            first_root, _confidence_entry("BV1swap"), segments, source="asr"
        )
    assert not [
        path for path in first_root.rglob("*") if path.is_file()
    ], "a row that fails must publish nothing, whichever start it failed on"

    # The other order: the same two bad starts, and it is still a failure that
    # publishes nothing — the row's fate does not depend on which came first.
    second_root = tmp_path / "swap-second"
    second_root.mkdir()
    swapped = [
        {"start": "nope", "end": 1.0, "text": "甲。", "confidence": 0.1},
        {"end": 2.0, "text": "乙。", "confidence": 0.9},
    ]
    with pytest.raises(ValueError):
        write_archive(
            second_root, _confidence_entry("BV1swap2"), swapped, source="asr"
        )
    assert not [
        path for path in second_root.rglob("*") if path.is_file()
    ], "still publishes nothing"


@pytest.mark.parametrize(
    ("start", "expected"),
    [
        pytest.param(float("nan"), ValueError, id="nan"),
        pytest.param(float("inf"), OverflowError, id="inf"),
        pytest.param(-float("inf"), OverflowError, id="negative-inf"),
        pytest.param(1e308, OverflowError, id="finite-but-unscalable"),
    ],
)
def test_a_non_finite_start_is_rejected_by_rounding_to_milliseconds(tmp_root, start, expected):
    """The other half of "no new way to fail": what ``round(..., 3)`` lets through.

    ``float('nan')`` and both infinities pass the location read untouched, so
    the docstring's claim rests on a *later* guard: ``_fmt_srt_time`` multiplies
    by 1000 before rounding, and that is where they die.  The boundary is
    sharp — ``1e305`` scales and publishes, ``1e308`` does not — so the test
    pins both sides and the exception each raises, which is what makes "no path
    can publish them" a checked statement rather than an assumption about
    ``segments_to_srt`` surviving a future edit.
    """

    tmp_path = __import__("pathlib").Path(tmp_root)
    # The failing row publishes into its own root, so "nothing was published"
    # is a statement about this row rather than about the fixture directory
    # (the successful boundary row below shares ``tmp_root``).
    rejected_root = tmp_path / "unscalable"
    rejected_root.mkdir()
    segment = {"start": start, "end": 2.0, "text": "甲。", "confidence": 0.1}

    with pytest.raises(expected):
        write_archive(
            rejected_root, _confidence_entry("BV1unscalable"), [segment], source="asr"
        )
    assert not [
        path for path in rejected_root.rglob("*") if path.is_file()
    ], "nothing may be published for an unrepresentable start"

    # The near side of the boundary: large, still scalable, still publishes.
    ok = _confidence_entry("BV1scalable")
    segment = {"start": 1e305, "end": 2.0, "text": "甲。", "confidence": 0.1}
    paths = write_archive(tmp_path, ok, [segment], source="asr")
    assert _frontmatter(tmp_path / paths["md_path"])["asr_low_confidence_at"] == [1e305]


def test_write_archive_locates_nothing_without_scores(tmp_root):
    """The ASR-only gate: a subtitle row gains neither the count nor the list.

    The gate is the scores, not the source label — the subtitle path builds its
    segments with no ``confidence``, so the location key is absent for the same
    reason the count key already was (D4.8), and neither appears without the
    other.
    """

    tmp_path = __import__("pathlib").Path(tmp_root)
    ident = page_identity("BV1subat", 0, 14)
    entry = {"bvid": ident.bvid, "work_id": ident.work_id, "page_index": 0, "cid": 14,
             "title": "subtitle", "pubdate_str": "2026-01-02", "duration_s": 10}
    # The kind of segment the subtitle path actually publishes: no scores.
    segments = [
        {"start": 0.0, "end": 2.0, "text": "第一句。"},
        {"start": 8.0, "end": 9.0, "text": "第二句。"},
    ]

    paths = write_archive(tmp_path, entry, segments, source="subtitle")

    front = _frontmatter(tmp_path / paths["md_path"])
    for key in ("asr_low_confidence_at", "asr_low_confidence_cues", "asr_mean_confidence"):
        assert key not in front, key
