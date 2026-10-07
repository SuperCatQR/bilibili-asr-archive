"""Malformed raw sidecars must be refused without corrupting a whole reader run."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bili_asr.cues import CueParseError, read_route_ms
from bili_asr.search_index.manifest import SearchIndex
from bili_asr.search_index.readers import extract_transcript_text


def _raw_sidecar(tmp_path: Path, document: object) -> tuple[Path, dict]:
    relative = "transcripts/BV1rawreader.p0/bundle.raw.json"
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    return path, {
        "bvid": "BV1rawreader",
        "work_id": "BV1rawreader:p0",
        "page_index": 0,
        "cid": 123,
        "status": "archived",
        "source": "asr",
        "raw_path": relative,
    }


@pytest.mark.parametrize("document", [[], None, 7, "another document"])
def test_asr_route_refuses_non_object_documents(tmp_path: Path, document: object) -> None:
    path, _ = _raw_sidecar(tmp_path, document)
    with pytest.raises(CueParseError, match="ASR route is not an object"):
        read_route_ms(path, require_source="asr", label="BV1rawreader:p0")


@pytest.mark.parametrize(
    "segment",
    [
        7,
        {"start": 0, "end": float("inf"), "text": "words"},
        {"start": float("nan"), "end": 1, "text": "words"},
        {"start": 0, "end": 1e308, "text": "words"},
        {"start": -1, "end": 1, "text": "words"},
        {"start": 2, "end": 1, "text": "words"},
        {"start": True, "end": 1, "text": "words"},
        {"start": 0, "end": 1, "text": None},
    ],
)
def test_asr_route_refuses_invalid_segments(tmp_path: Path, segment: object) -> None:
    path, _ = _raw_sidecar(tmp_path, {"source": "asr", "segments": [segment]})
    with pytest.raises(CueParseError, match="ASR segment 1 is malformed"):
        read_route_ms(path, require_source="asr", label="BV1rawreader:p0")


def test_asr_route_invalid_utf8_is_a_route_refusal(tmp_path: Path) -> None:
    path, _ = _raw_sidecar(tmp_path, {})
    path.write_bytes(b'{"source":"asr","segments":[{"text":"\xff"}]}')
    with pytest.raises(CueParseError, match="unreadable ASR route"):
        read_route_ms(path, require_source="asr", label="BV1rawreader:p0")


def test_proofread_cli_reports_malformed_route(tmp_path: Path, capsys) -> None:
    from bili_asr.cli.main import main

    _raw_sidecar(tmp_path, [])
    assert main([
        "proofread", "--bvid", "BV1rawreader:p0",
        "--archive-root", str(tmp_path), "--artifact-root", str(tmp_path),
    ]) == 1
    captured = capsys.readouterr()
    assert "ASR route is not an object" in captured.err
    assert "written" not in captured.out
    assert not (tmp_path / ".tmp" / "proofread-work").exists()


@pytest.mark.parametrize(
    "document",
    [
        [],
        {"source": "asr", "segments": [7]},
        {"source": "asr", "segments": [{"text": None}]},
        {"source": "asr", "body": [{"content": ["words"]}]},
    ],
)
def test_search_refuses_malformed_raw_shapes(tmp_path: Path, document: object) -> None:
    _, entry = _raw_sidecar(tmp_path, document)
    assert extract_transcript_text(tmp_path, entry)[0] == ""


@pytest.mark.parametrize("source", ["subtitle-ai", "subtitle", "proofread", None])
def test_search_asr_row_refuses_other_raw_sources(tmp_path: Path, source: object) -> None:
    _, entry = _raw_sidecar(tmp_path, {
        "source": source, "segments": [{"start": 0, "end": 1, "text": "wrong route"}],
    })
    assert extract_transcript_text(tmp_path, entry)[0] == ""


@pytest.mark.parametrize("source", ["subtitle", None])
def test_search_keeps_legacy_caption_body_without_source(tmp_path: Path, source: object) -> None:
    _, entry = _raw_sidecar(tmp_path, {"body": [{"content": "caption words"}]})
    entry["source"] = source
    assert extract_transcript_text(tmp_path, entry)[0] == "caption words"


def test_search_keeps_valid_asr_segments(tmp_path: Path) -> None:
    _, entry = _raw_sidecar(tmp_path, {
        "source": "asr", "segments": [{"start": 0, "end": 1, "text": "asr words"}],
    })
    assert extract_transcript_text(tmp_path, entry)[0] == "asr words"


def test_search_invalid_raw_utf8_does_not_abort_index(tmp_path: Path) -> None:
    path, entry = _raw_sidecar(tmp_path, {})
    path.write_bytes(b'{"source":"asr","segments":[{"text":"\xff"}]}')
    good_relative = "transcripts/BV1goodreader.p0/bundle.txt"
    good_path = tmp_path / good_relative
    good_path.parent.mkdir(parents=True)
    good_path.write_text("Searchable valid transcript", encoding="utf-8")
    good_entry = {
        "bvid": "BV1goodreader", "work_id": "BV1goodreader:p0",
        "page_index": 0, "cid": 124, "status": "archived", "source": "asr",
        "txt_path": good_relative,
    }
    index = SearchIndex(root=tmp_path)
    assert extract_transcript_text(tmp_path, entry)[0] == ""
    # Legacy search still indexes a completed row's metadata when its body is
    # unreadable; the valid sibling must remain searchable in the same build.
    assert index.build({entry["work_id"]: entry, good_entry["work_id"]: good_entry}) == 2
    assert [hit.work_id for hit in index.search("Searchable", auto_build=False)] == [
        good_entry["work_id"]
    ]
