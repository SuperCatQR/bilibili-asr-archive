from __future__ import annotations

import json
from pathlib import Path

from bili_asr.archive import write_archive
from bili_asr.integrity import (
    IntegrityReport, IntegrityVerifier, MALFORMED_ARTIFACT, MISSING_RAW_SUBTITLE,
    MISSING_TRANSCRIPT, RETRYABLE_INCOMPLETE, STRUCTURAL_INPUT_ERROR,
    TRUNCATED_ATTEMPTS_LINE, MISSING_ATTEMPTS, ATTEMPTS_BYTE_LIMIT_EXCEEDED,
    ATTEMPTS_ROW_LIMIT_EXCEEDED,
)


def _manifest(root: Path, rows: list[dict[str, object]]) -> None:
    path = root / "manifest" / "manifest.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_production_archive_layout_verifies_cleanly(tmp_path: Path) -> None:
    row = {"work_id": "BV1x:p0", "bvid": "BV1x", "cid": 7, "page_index": 0,
           "pubdate_str": "20260828", "title": "A safe/title", "status": "archived"}
    paths = write_archive(tmp_path, row, [{"start": 0, "end": 1, "text": "ok"}], source="cc")
    row.update(paths)
    _manifest(tmp_path, [row])
    assert IntegrityVerifier().verify(tmp_path).defects == []


def test_symlinked_manifest_is_not_read(tmp_path: Path) -> None:
    outside = tmp_path / "outside.jsonl"
    outside.write_text(json.dumps({"work_id": "outside", "status": "pending"}) + "\n", encoding="utf-8")
    (tmp_path / "manifest").mkdir()
    (tmp_path / "manifest" / "manifest.jsonl").symlink_to(outside)
    report = IntegrityVerifier().verify(tmp_path)
    assert report.authoritative is False
    assert STRUCTURAL_INPUT_ERROR in report.diagnostics


def test_symlinked_attempts_are_not_read(tmp_path: Path) -> None:
    _manifest(tmp_path, [{"work_id": "BV1x:p0", "bvid": "BV1x", "status": "pending"}])
    outside = tmp_path / "outside.jsonl"
    outside.write_text(json.dumps(_attempt("BV1x:p0")) + "\n", encoding="utf-8")
    (tmp_path / "coordinator").mkdir()
    (tmp_path / "coordinator" / "attempts.jsonl").symlink_to(outside)
    report = IntegrityVerifier().verify(tmp_path)
    assert report.authoritative is False
    assert MISSING_ATTEMPTS in report.diagnostics


    row = {"work_id": "BV1x:p0", "bvid": "BV1x", "status": "archived"}
    _manifest(tmp_path, [row])
    transcript_dir = tmp_path / "transcripts"
    for kind in ("srt", "txt", "md"):
        (transcript_dir / kind).mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("valid evidence\n", encoding="utf-8")
    (transcript_dir / "srt" / "BV1x.p0.srt").symlink_to(outside)
    (transcript_dir / "txt" / "BV1x.p0.txt").write_text("valid evidence\n", encoding="utf-8")
    (transcript_dir / "md" / "BV1x.p0.md").write_text("valid evidence\n", encoding="utf-8")
    report = IntegrityVerifier().verify(tmp_path)
    assert MISSING_TRANSCRIPT in {defect.code for defect in report.defects}


def test_malformed_identity_containers_fail_closed(tmp_path: Path) -> None:
    for malformed in ({}, []):
        root = tmp_path / ("dict" if isinstance(malformed, dict) else "list")
        _manifest(root, [{"work_id": "x", "bvid": "x", "cid": malformed, "status": "pending"}])
        report = IntegrityVerifier().verify(root)
        assert report.authoritative is False
        assert STRUCTURAL_INPUT_ERROR in report.diagnostics


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
    path.write_text(json.dumps(_attempt("BV1x:p0")) + "\n{broken'", encoding="utf-8")
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
    assert set(first) == {"checked", "defect_count", "defects", "diagnostics", "authoritative"}
    assert first["defects"] == sorted(first["defects"], key=lambda d: (d["work_id"], d["code"]))


def test_scope_uses_attempt_outcomes(tmp_path: Path) -> None:
    _manifest(tmp_path, [{"work_id": "pending", "status": "pending"}, {"work_id": "archived", "status": "archived"}, {"work_id": "running", "status": "running"}])
    path = tmp_path / "coordinator" / "attempts.jsonl"; path.parent.mkdir()
    path.write_text(json.dumps(_attempt("archived")) + "\n" + json.dumps(_attempt("running", "ok")) + "\n", encoding="utf-8")
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
    result = IntegrityVerifier().verify(tmp_path)
    assert MALFORMED_ARTIFACT in {d.code for d in result.defects}


def test_malformed_middle_attempt_is_structural(tmp_path: Path) -> None:
    _manifest(tmp_path, [{"work_id": "x", "status": "pending"}])
    path = tmp_path / "coordinator" / "attempts.jsonl"; path.parent.mkdir()
    path.write_text(json.dumps(_attempt("x")) + "\n{bad}\n" + json.dumps(_attempt("x", "success")) + "\n", encoding="utf-8")
    assert STRUCTURAL_INPUT_ERROR in IntegrityVerifier().verify(tmp_path).diagnostics


def test_retryable_status_matrix_and_scope_selectors(tmp_path: Path) -> None:
    statuses = ["pending", "meta_ok", "sub_checked", "needs_audio", "audio_ok"]
    rows = [{"work_id": f"BV{i}:p0", "bvid": f"BV{i}", "status": status} for i, status in enumerate(statuses)]
    rows += [{"work_id": "failed:p0", "bvid": "failed", "status": "archived"}, {"work_id": "live:p0", "bvid": "live", "status": "meta_ok"}]
    _manifest(tmp_path, rows)
    attempts = tmp_path / "coordinator" / "attempts.jsonl"
    attempts.parent.mkdir()
    attempts.write_text(json.dumps(_attempt("failed:p0")) + "\n" + json.dumps(_attempt("live:p0", "ok")) + "\n", encoding="utf-8")
    report = IntegrityVerifier().verify(tmp_path)
    retryable = {d.work_id for d in report.defects if d.code == RETRYABLE_INCOMPLETE}
    assert retryable == {f"BV{i}:p0" for i in range(5)} | {"live:p0"}
    assert {d.work_id for d in IntegrityVerifier().verify(tmp_path, scope="failed").defects} == {"failed:p0"}
    assert IntegrityVerifier().verify(tmp_path, scope="BV1").checked == 1
    assert IntegrityVerifier().verify(tmp_path, scope="BV1:p0").checked == 1


def test_missing_each_transcript_artifact_is_missing_transcript(tmp_path: Path) -> None:
    _manifest(tmp_path, [{"work_id": "BV1:p0", "bvid": "BV1", "status": "archived"}])
    for directory, suffix, content in (("srt", "srt", "1\n00:00:00,000 --> 00:00:01,000\nok"), ("txt", "txt", "ok"), ("md", "md", "ok")):
        path = tmp_path / "transcripts" / directory; path.mkdir(parents=True)
        (path / f"BV1.p0.{suffix}").write_text(content, encoding="utf-8")
        report = IntegrityVerifier().verify(tmp_path)
        assert any(d.code == MISSING_TRANSCRIPT for d in report.defects)
        (path / f"BV1.p0.{suffix}").unlink()


def test_path_safety_redaction_and_read_only(tmp_path: Path) -> None:
    _manifest(tmp_path, [{"work_id": "BV1:p0", "bvid": "BV1", "status": "archived", "srt_path": "../secret.srt"}])
    outside = tmp_path.parent / "secret.srt"; outside.write_text("secret", encoding="utf-8")
    before = outside.stat().st_mtime_ns
    report = IntegrityVerifier().verify(tmp_path)
    payload = json.dumps(report.to_dict())
    assert any(d.code == "identity_path_mismatch" for d in report.defects)
    assert str(tmp_path) not in payload and "secret" not in payload and "http" not in payload and "Traceback" not in payload
    assert outside.stat().st_mtime_ns == before


def test_malformed_manifest_and_bad_middle_attempt_are_diagnostics(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest" / "manifest.jsonl"; manifest.parent.mkdir()
    manifest.write_text('{"work_id":"ok:p0","status":"pending"}\nnot-json\n', encoding="utf-8")
    attempts = tmp_path / "coordinator" / "attempts.jsonl"; attempts.parent.mkdir()
    attempts.write_text(json.dumps(_attempt("ok:p0")) + "\n{bad}\n" + json.dumps(_attempt("ok:p0")) + "\n", encoding="utf-8")
    report = IntegrityVerifier().verify(tmp_path)
    assert STRUCTURAL_INPUT_ERROR in report.diagnostics


def test_trailing_blank_after_truncated_attempt_is_tolerated(tmp_path: Path) -> None:
    _manifest(tmp_path, [{"work_id": "x", "status": "pending"}])
    path = tmp_path / "coordinator" / "attempts.jsonl"; path.parent.mkdir()
    path.write_text(json.dumps(_attempt("x")) + "\n{broken\n\n", encoding="utf-8")
    report = IntegrityVerifier().verify(tmp_path)
    assert report.authoritative is True
    assert TRUNCATED_ATTEMPTS_LINE in report.diagnostics
    assert STRUCTURAL_INPUT_ERROR not in report.diagnostics


def test_manifest_overflow_is_non_authoritative(tmp_path: Path) -> None:
    _manifest(tmp_path, [{"work_id": str(i), "status": "pending"} for i in range(10001)])
    report = IntegrityVerifier().verify(tmp_path)
    assert report.authoritative is False
    assert report.diagnostics == ["manifest_row_limit_exceeded"]




def test_attempts_row_limit_fails_closed(tmp_path: Path) -> None:
    _manifest(tmp_path, [{"work_id": "x", "status": "pending"}])
    attempts = tmp_path / "coordinator" / "attempts.jsonl"
    attempts.parent.mkdir()
    attempts.write_text("{}\n" * 10001, encoding="utf-8")
    report = IntegrityVerifier().verify(tmp_path)
    assert report.authoritative is False
    assert ATTEMPTS_ROW_LIMIT_EXCEEDED in report.diagnostics


def test_malformed_manifest_field_type_is_structural(tmp_path: Path) -> None:
    _manifest(tmp_path, [{"work_id": "x", "bvid": "x", "cid": {}}])
    report = IntegrityVerifier().verify(tmp_path)
    assert report.authoritative is False
    assert STRUCTURAL_INPUT_ERROR in report.diagnostics


def test_missing_attempts_is_diagnostic_but_rows_are_checked(tmp_path: Path) -> None:
    _manifest(tmp_path, [{"work_id": "x", "status": "pending"}])
    report = IntegrityVerifier().verify(tmp_path)
    assert report.authoritative is False
    assert report.checked == 1
    assert MISSING_ATTEMPTS in report.diagnostics


def test_attempts_byte_limit_fails_closed(tmp_path: Path) -> None:
    _manifest(tmp_path, [{"work_id": "x", "status": "pending"}])
    attempts = tmp_path / "coordinator" / "attempts.jsonl"
    attempts.parent.mkdir()
    attempts.write_text("x" * (8 * 1024 * 1024 + 1), encoding="utf-8")
    report = IntegrityVerifier().verify(tmp_path)
    assert report.authoritative is False
    assert ATTEMPTS_BYTE_LIMIT_EXCEEDED in report.diagnostics


def test_declared_raw_path_mismatch_does_not_mask_canonical_raw(tmp_path: Path) -> None:
    _manifest(tmp_path, [{"work_id": "BV1:p0", "bvid": "BV1", "status": "subtitle_done",
                          "raw_path": "../escape.json"}])
    raw = tmp_path / "subtitles" / "raw"
    raw.mkdir(parents=True)
    (raw / "BV1.p0.json").write_text(json.dumps({"segments": []}), encoding="utf-8")
    report = IntegrityVerifier().verify(tmp_path)
    assert any(d.code == "identity_path_mismatch" for d in report.defects)


def test_invalid_utf8_attempts_fail_closed(tmp_path: Path) -> None:
    _manifest(tmp_path, [{"work_id": "BV1x:p0", "bvid": "BV1x", "status": "pending"}])
    path = tmp_path / "coordinator" / "attempts.jsonl"
    path.parent.mkdir()
    path.write_bytes(bytes([0xFF, 0xFE]))
    report = IntegrityVerifier().verify(tmp_path)
    assert report.authoritative is False
    assert STRUCTURAL_INPUT_ERROR in report.diagnostics
