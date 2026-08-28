from __future__ import annotations

import json
import os
from pathlib import Path

from bili_asr.quality import QualityAnalyzer


def row(**values: object) -> dict[str, object]:
    return {"bvid": "BV1demo", "work_id": "BV1demo:p0", "source": "subtitle", "sub_lan": "ai-zh", "status": "archived", "duration_s": 10, **values}


def write_srt(root: Path, name: str, body: str) -> str:
    path = root / "transcripts" / "srt" / name
    path.parent.mkdir(parents=True)
    path.write_text(body, encoding="utf-8")
    return "transcripts/srt/" + name


def test_valid_monotonic_srt_is_stable_and_read_only(tmp_path: Path) -> None:
    relative = write_srt(tmp_path, "BV1demo:p0.srt", "1\n00:00:00,000 --> 00:00:01,000\nhello\n")
    path = tmp_path / relative
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    analyzer = QualityAnalyzer()
    first = analyzer.analyze(row(srt_path=relative), tmp_path)
    second = analyzer.analyze(row(srt_path=relative), tmp_path)
    assert first.to_dict() == second.to_dict()
    assert first.reasons == ()
    assert first.cue_count == 1
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert json.dumps(first.to_dict(), sort_keys=True) == json.dumps(second.to_dict(), sort_keys=True)


def test_anomaly_reason_codes(tmp_path: Path) -> None:
    cases = {
        "empty": "",
        "malformed": "1\nnot timing\ntext\n",
        "non_monotonic": "1\n00:00:02,000 --> 00:00:03,000\na\n\n2\n00:00:01,000 --> 00:00:01,500\nb\n",
        "overlap": "1\n00:00:00,000 --> 00:00:02,000\na\n\n2\n00:00:01,000 --> 00:00:03,000\nb\n",
        "out_of_range": "1\n00:00:09,000 --> 00:00:11,000\na\n",
    }
    for reason, content in cases.items():
        relative = write_srt(tmp_path / reason, "BV1demo:p0.srt", content)
        result = QualityAnalyzer().analyze(row(srt_path=relative), tmp_path / reason)
        assert reason in result.reasons


def test_json_and_standard_archive_paths_are_supported(tmp_path: Path) -> None:
    raw = tmp_path / "transcripts" / "raw"
    raw.mkdir(parents=True)
    (raw / "BV1demo:p0.json").write_text(json.dumps({"body": [{"from": 0, "to": 1, "content": "x"}]}), encoding="utf-8")
    result = QualityAnalyzer().analyze(row(), tmp_path)
    assert result.reasons == ()
    assert result.artifact_count == 1


def test_missing_identity_and_traversal_are_redacted(tmp_path: Path) -> None:
    result = QualityAnalyzer().analyze(row(srt_path="../secret.srt"), tmp_path)
    payload = json.dumps(result.to_dict())
    assert result.reasons == ("artifact_missing",)
    assert "secret" not in payload
    assert "http" not in payload



def test_identity_mismatch_is_reported_without_leaking_path(tmp_path: Path) -> None:
    relative = write_srt(tmp_path, "BV1other:p0.srt", "1\n00:00:00,000 --> 00:00:01,000\nx\n")
    result = QualityAnalyzer().analyze(row(srt_path=relative), tmp_path)
    assert result.reasons == ("identity_mismatch",)


def test_reclaimed_audio_does_not_count_as_defect(tmp_path: Path) -> None:
    relative = write_srt(tmp_path, "BV1demo:p0.srt", "1\n00:00:00,000 --> 00:00:01,000\nx\n")
    result = QualityAnalyzer().analyze(row(srt_path=relative, audio_path="audio/BV1demo:p0.m4a"), tmp_path)
    assert result.reasons == ()
    assert result.status == "archived"
