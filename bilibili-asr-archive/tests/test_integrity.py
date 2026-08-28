from __future__ import annotations

import json
from pathlib import Path

from bili_asr.integrity import IntegrityVerifier, MISSING_TRANSCRIPT, TRUNCATED_ATTEMPTS_LINE


def _manifest(root: Path, rows: list[dict[str, object]]) -> None:
    path = root / "manifest" / "manifest.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_archived_transcripts_are_valid_without_audio(tmp_path: Path) -> None:
    _manifest(tmp_path, [{"work_id": "BV1x:p0", "bvid": "BV1x", "status": "archived"}])
    for directory in ("srt", "txt", "md"):
        path = tmp_path / "transcripts" / directory
        path.mkdir(parents=True)
        (path / f"BV1x.p0.{directory}").write_text("ok", encoding="utf-8")
    report = IntegrityVerifier().verify(tmp_path)
    assert report.defects == []


def test_missing_transcript_and_truncated_attempts(tmp_path: Path) -> None:
    _manifest(tmp_path, [{"work_id": "BV1x:p0", "bvid": "BV1x", "status": "archived"}])
    path = tmp_path / "coordinator" / "attempts.jsonl"
    path.parent.mkdir()
    path.write_text('{"work_id":"BV1x:p0"}\n{"broken"', encoding="utf-8")
    report = IntegrityVerifier().verify(tmp_path)
    assert any(d.code == MISSING_TRANSCRIPT for d in report.defects)
    assert TRUNCATED_ATTEMPTS_LINE in report.diagnostics
