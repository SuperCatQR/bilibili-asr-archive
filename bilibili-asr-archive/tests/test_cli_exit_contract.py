"""CLI exit contract for ``verify`` / ``coverage`` (exit-code contract §2, §6).

Default invocation: backlog is work-not-yet-done and contributes nothing to the
exit code; defect-class findings and diagnostics exit 1.  ``--strict`` restores
the pre-cutover gate — any finding of either class exits 1.

Fixtures are built here rather than in ``test_integrity.py``: the subject is the
*command's* exit code and printed sections, not the report layer that T1a
already pinned in ``test_integrity_finding_classes.py``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bili_asr import cli


def _fixture(root: Path, rows: list[dict[str, object]]) -> None:
    path = root / "manifest" / "manifest.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    # An absent attempts sidecar is its own diagnostic (`missing_attempts_sidecar`)
    # and would keep the exit at 1 for a reason unrelated to the class split.
    attempts = root / "coordinator" / "attempts.jsonl"
    attempts.parent.mkdir(parents=True, exist_ok=True)
    attempts.write_text("", encoding="utf-8")


def _row(work_id: str, status: str) -> dict[str, object]:
    return {
        "work_id": work_id, "bvid": work_id.split(":")[0], "cid": 1,
        "page_index": 0, "pubdate_str": "20260101", "title": "t",
        "status": status,
    }


@pytest.fixture()
def backlog_only(tmp_path: Path) -> Path:
    """A healthy archive holding only unprocessed rows — the §2 headline case."""
    _fixture(tmp_path, [
        _row("BV1a:p0", "needs_audio"),
        _row("BV1b:p0", "pending"),
    ])
    return tmp_path


@pytest.fixture()
def with_defect(tmp_path: Path) -> Path:
    """One backlog row plus one archived row whose transcript never landed."""
    _fixture(tmp_path, [
        _row("BV1a:p0", "needs_audio"),
        _row("BV1c:p0", "archived"),
    ])
    return tmp_path


def test_verify_backlog_only_exits_zero_and_prints_backlog_section(
    backlog_only: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["verify", "--archive-root", str(backlog_only),
                     "--format", "text"]) == 0
    out = capsys.readouterr().out
    assert "defects: 0" in out
    # The backlog section names the rows in the same `work_id: code` shape,
    # under its own header, so a cron reader never has to guess the class.
    assert "backlog: 2" in out
    assert "BV1a:p0: retryable_incomplete" in out
    assert "BV1b:p0: retryable_incomplete" in out


def test_verify_strict_on_the_same_backlog_only_input_exits_one(
    backlog_only: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """§6.1: `--strict` restores the pre-cutover gate on the same archive."""
    assert cli.main(["verify", "--archive-root", str(backlog_only),
                     "--format", "text", "--strict"]) == 1
    assert "backlog: 2" in capsys.readouterr().out


def test_verify_defect_class_exits_one_in_both_modes(
    with_defect: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A defect does not become exit-0 just because backlog shares the run."""
    assert cli.main(["verify", "--archive-root", str(with_defect),
                     "--format", "text"]) == 1
    out = capsys.readouterr().out
    assert "defects: 1" in out
    assert "backlog: 1" in out
    assert "BV1c:p0: missing_transcript" in out

    assert cli.main(["verify", "--archive-root", str(with_defect),
                     "--format", "text", "--strict"]) == 1
    capsys.readouterr()


def test_verify_backlog_only_json_payload_reports_both_counts(
    backlog_only: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["verify", "--archive-root", str(backlog_only),
                     "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["defect_count"] == 0
    assert payload["backlog_count"] == 2
    assert payload["diagnostics"] == []


def test_coverage_quality_backlog_only_exits_zero_and_strict_exits_one(
    backlog_only: Path,
) -> None:
    """§6.1 on the coverage reader: an in-flight row is not damage."""
    assert cli.main(["coverage", "--archive-root", str(backlog_only),
                     "--quality", "--format", "json"]) == 0
    assert cli.main(["coverage", "--archive-root", str(backlog_only),
                     "--quality", "--format", "json", "--strict"]) == 1


def test_coverage_quality_defect_class_exits_one_in_both_modes(
    with_defect: Path,
) -> None:
    """The archived row's missing transcript is damage in either mode."""
    assert cli.main(["coverage", "--archive-root", str(with_defect),
                     "--quality", "--format", "json"]) == 1
    assert cli.main(["coverage", "--archive-root", str(with_defect),
                     "--quality", "--format", "json", "--strict"]) == 1


def test_coverage_quality_backlog_row_with_broken_artifact_stays_a_defect(
    backlog_only: Path,
) -> None:
    """A status in flight must not hide damage (contract §2, malformed rule).

    The row's status is `needs_audio` — backlog — but its declared artifact
    exists and is unreadable (`malformed`/`empty`).  Backlog means "the artifact
    is not there yet", never "the artifact is there and broken", so this still
    exits 1 without `--strict`.
    """
    row = _row("BV1m:p0", "needs_audio")
    row.update({
        "srt_path": "transcripts/srt/BV1m.p0.srt",
        "txt_path": "transcripts/txt/BV1m.p0.txt",
        "md_path": "transcripts/md/x_BV1m.p0_t.md",
        "raw_path": "transcripts/raw/BV1m.p0.json",
    })
    _fixture(backlog_only, [row])
    corrupt = {
        "transcripts/txt/BV1m.p0.txt": "",
        "transcripts/srt/BV1m.p0.srt": "NOT A CUE\n",
        "transcripts/raw/BV1m.p0.json": "{not json",
    }
    for relative, text in corrupt.items():
        path = backlog_only / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    assert cli.main(["coverage", "--archive-root", str(backlog_only),
                     "--quality", "--format", "json"]) == 1
