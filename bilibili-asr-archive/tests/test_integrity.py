from __future__ import annotations

import json
from pathlib import Path

from bili_asr.integrity import (
    IntegrityReport, IntegrityVerifier, MALFORMED_ARTIFACT, MISSING_RAW_SUBTITLE,
    MISSING_TRANSCRIPT, RETRYABLE_INCOMPLETE, STRUCTURAL_INPUT_ERROR,
    TRUNCATED_ATTEMPTS_LINE,
)


def _manifest(root: Path, rows: list[dict[str, object]]) -> None:
    path = root / "manifest" / "manifest.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_archived_transcripts_are_valid_without_audio(tmp_path: Path) -> None:
    _manifest(tmp_path, [{"work_id": "BV1x:p0", "bvid": "BV1x", "status": "archived"}])
    for directory in ("srt", "txt", "md"):
        path = tmp_path / "transcripts" / directory
        path.mkdir(parents=True)
        content = "1\n00:00:00,000 --> 00:00:01,000\nok" if directory == "srt" else "ok"
        (path / f"BV1x.p0.{directory}").write_text(content, encoding="utf-8")
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


def _attempt(work_id: str, outcome: str = "failed") -> dict[str, object]:
    return {"stage": "asr", "work_id": work_id, "attempt": 1, "outcome": outcome,
            "error_code": "E_TEST", "artifact_paths": [],
            "started_at": "2026-01-01T00:00:00Z", "finished_at": "2026-01-01T00:00:01Z"}


def test_report_shape_is_sorted_and_idempotent(tmp_path: Path) -> None:
    _manifest(tmp_path, [{"work_id": "b", "status": "pending"}, {"work_id": "a", "status": "needs_audio"}])
    first = IntegrityVerifier().verify(tmp_path).to_dict()
    assert first == IntegrityVerifier().verify(tmp_path).to_dict()
    assert set(first) == {"checked", "defect_count", "defects", "diagnostics"}
    assert first["defects"] == sorted(first["defects"], key=lambda d: (d["work_id"], d["code"]))


def test_scope_uses_attempt_outcomes(tmp_path: Path) -> None:
    _manifest(tmp_path, [{"work_id": "pending", "status": "pending"}, {"work_id": "archived", "status": "archived"}, {"work_id": "running", "status": "running"}])
    path = tmp_path / "coordinator" / "attempts.jsonl"; path.parent.mkdir()
    path.write_text(json.dumps(_attempt("archived")) + "\n" + json.dumps(_attempt("running", "success")) + "\n", encoding="utf-8")
    assert IntegrityVerifier().verify(tmp_path, scope="pending").checked == 1
    assert IntegrityVerifier().verify(tmp_path, scope="failed").checked == 1
    assert IntegrityVerifier().verify(tmp_path, scope="running").checked == 1


def test_malformed_raw_is_reported(tmp_path: Path) -> None:
    _manifest(tmp_path, [{"work_id": "BV1x:p0", "bvid": "BV1x", "status": "subtitle_done"}])
    for directory in ("srt", "txt", "md"):
        path = tmp_path / "transcripts" / directory; path.mkdir(parents=True)
        (path / f"BV1x.p0.{directory}").write_text("bad", encoding="utf-8")
    raw = tmp_path / "subtitles" / "raw"; raw.mkdir(parents=True)
    (raw / "BV1x.p0.json").write_text("{broken", encoding="utf-8")
    assert MISSING_RAW_SUBTITLE not in {d.code for d in IntegrityVerifier().verify(tmp_path).defects}


def test_malformed_middle_attempt_is_structural(tmp_path: Path) -> None:
    _manifest(tmp_path, [{"work_id": "x", "status": "pending"}])
    path = tmp_path / "coordinator" / "attempts.jsonl"; path.parent.mkdir()
    path.write_text(json.dumps(_attempt("x")) + "\n{bad}\n" + json.dumps(_attempt("x", "success")) + "\n", encoding="utf-8")
    assert STRUCTURAL_INPUT_ERROR in IntegrityVerifier().verify(tmp_path).diagnostics
