"""Two-class finding classification in the integrity report (exit-code contract §2).

``backlog`` is work the chain has not reached yet (``retryable_incomplete``);
``defect`` is archive corruption.  Only defect-class findings contribute to
``defect_count``; backlog is counted separately as ``backlog_count``.
"""
from __future__ import annotations

import json
from pathlib import Path

from bili_asr.integrity import (
    BACKLOG_CATEGORY, BACKLOG_CODES, DEFECT_CATEGORY, RETRYABLE_INCOMPLETE,
    STRUCTURAL_INPUT_ERROR, TRUNCATED_ATTEMPTS_LINE, IntegrityDefect,
    IntegrityReport, IntegrityVerifier,
)


def _manifest(root: Path, rows: list[dict[str, object]]) -> None:
    path = root / "manifest" / "manifest.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_only_retryable_incomplete_is_backlog_class() -> None:
    assert BACKLOG_CODES == frozenset({RETRYABLE_INCOMPLETE})
    assert IntegrityDefect("w", RETRYABLE_INCOMPLETE).category == BACKLOG_CATEGORY
    for code in ("malformed_artifact", "identity_path_mismatch", "missing_raw_subtitle",
                 "truncated_attempts_line", "manifest_row_limit_exceeded",
                 "manifest_invalid_status", "manifest_invalid_bvid", "missing_attempts_sidecar",
                 "attempts_row_limit_exceeded", "attempts_byte_limit_exceeded",
                 "structural_input_error", "recovery_requires_explicit_target",
                 "recovery_target_not_found", "recovery_target_limit_exceeded",
                 "recovery_not_authoritative", "recovery_malformed_sidecar",
                 "recovery_invalid_selector"):
        assert IntegrityDefect("w", code).category == DEFECT_CATEGORY, code


def test_defect_dict_carries_its_category() -> None:
    assert IntegrityDefect("w", "malformed_artifact").to_dict() == {
        "work_id": "w", "code": "malformed_artifact", "category": DEFECT_CATEGORY,
    }
    assert IntegrityDefect("w", RETRYABLE_INCOMPLETE).to_dict()["category"] == BACKLOG_CATEGORY


def test_report_counts_split_by_class_and_keep_existing_keys() -> None:
    report = IntegrityReport(checked=3, defects=[
        IntegrityDefect("a", RETRYABLE_INCOMPLETE),
        IntegrityDefect("b", RETRYABLE_INCOMPLETE),
        IntegrityDefect("c", "identity_path_mismatch"),
    ])
    payload = report.to_dict()
    assert payload["defect_count"] == 1
    assert payload["backlog_count"] == 2
    assert payload["checked"] == 3
    # no existing key removed or renamed
    assert {"checked", "defect_count", "defects", "diagnostics", "authoritative"} <= set(payload)
    assert [entry["category"] for entry in payload["defects"]] == [
        BACKLOG_CATEGORY, BACKLOG_CATEGORY, DEFECT_CATEGORY,
    ]
    assert report.defect_count == 1 and report.backlog_count == 2


def test_backlog_only_archive_is_zero_defects(tmp_path: Path) -> None:
    """The measured pain: a healthy archive holding only unprocessed rows."""
    _manifest(tmp_path, [{"work_id": "BV1x:p0", "bvid": "BV1x", "cid": 1, "page_index": 0,
                          "status": "needs_audio", "pubdate_str": "20260828", "title": "t"}])
    report = IntegrityVerifier().verify(tmp_path)
    payload = report.to_dict()
    assert payload["defect_count"] == 0
    assert payload["backlog_count"] == len(report.defects) == 1
    assert all(entry["category"] == BACKLOG_CATEGORY for entry in payload["defects"])
    assert all(entry["code"] == RETRYABLE_INCOMPLETE for entry in payload["defects"])


def test_unparseable_manifest_is_never_backlog(tmp_path: Path) -> None:
    """Malformed input is defect-class: non-authoritative, and never a backlog row (§2).

    ``verify`` deliberately drops ``manifest_malformed`` from ``diagnostics``
    (``integrity.py:306-307``); that diagnostic is the coverage side's signal, so the
    verify-side assertion is the non-authoritative verdict.
    """
    (tmp_path / "manifest").mkdir()
    (tmp_path / "manifest" / "manifest.jsonl").write_text("{not json}\n", encoding="utf-8")
    report = IntegrityVerifier().verify(tmp_path)
    assert report.authoritative is False
    payload = report.to_dict()
    assert payload["defect_count"] == 0
    assert payload["backlog_count"] == 0
    assert payload["defects"] == []


def test_defect_class_diagnostic_is_reported_and_counted(tmp_path: Path) -> None:
    """A missing attempts sidecar is defect-class evidence, not backlog (§2 A8)."""
    _manifest(tmp_path, [{"work_id": "BV1x:p0", "bvid": "BV1x", "cid": 1, "page_index": 0,
                          "status": "archived", "pubdate_str": "20260828", "title": "t"}])
    report = IntegrityVerifier().verify(tmp_path)
    assert report.authoritative is False
    assert STRUCTURAL_INPUT_ERROR not in report.diagnostics
    assert TRUNCATED_ATTEMPTS_LINE not in report.diagnostics
    payload = report.to_dict()
    assert payload["backlog_count"] == 0
    assert payload["defect_count"] == len(report.defects) >= 1
    assert all(entry["category"] == DEFECT_CATEGORY for entry in payload["defects"])


def test_mixed_report_categories_agree_with_class_sets(tmp_path: Path) -> None:
    """One backlog row plus one defect row: counts and per-entry categories agree."""
    _manifest(tmp_path, [
        {"work_id": "BV1x:p0", "bvid": "BV1x", "cid": 7, "page_index": 0,
         "pubdate_str": "20260828", "title": "A", "status": "needs_audio"},
        {"work_id": "BV2x:p0", "bvid": "BV2x", "cid": 8, "page_index": 0,
         "pubdate_str": "20260828", "title": "B", "status": "archived",
         "srt_path": "../../escape.srt", "txt_path": "transcripts/txt/BV2x.p0.txt",
         "md_path": "transcripts/md/BV2x.p0.md", "raw_path": "subtitles/raw/BV2x.p0.json"},
    ])
    payload = IntegrityVerifier().verify(tmp_path).to_dict()
    categories = [entry["category"] for entry in payload["defects"]]
    assert payload["defect_count"] == sum(1 for c in categories if c == DEFECT_CATEGORY)
    assert payload["backlog_count"] == sum(1 for c in categories if c == BACKLOG_CATEGORY)
    assert payload["backlog_count"] >= 1
    assert payload["defect_count"] >= 1
    assert all(entry["code"] in BACKLOG_CODES for entry in payload["defects"]
               if entry["category"] == BACKLOG_CATEGORY)
