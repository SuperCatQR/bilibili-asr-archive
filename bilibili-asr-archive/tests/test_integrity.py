from __future__ import annotations

import json
from pathlib import Path

from bili_asr.archive import archive_stem, write_archive
from bili_asr.artifact_root import ArtifactRoots
from bili_asr.integrity import (
    IntegrityReport, IntegrityVerifier, MALFORMED_ARTIFACT, MISSING_RAW_SUBTITLE,
    MISSING_TRANSCRIPT, RECOVERY_TARGET_NOT_FOUND, RETRYABLE_INCOMPLETE,
    STRUCTURAL_INPUT_ERROR, TRUNCATED_ATTEMPTS_LINE, MISSING_ATTEMPTS,
    ATTEMPTS_BYTE_LIMIT_EXCEEDED, ATTEMPTS_ROW_LIMIT_EXCEEDED,
)


def _manifest(root: Path, rows: list[dict[str, object]]) -> None:
    path = root / "manifest" / "manifest.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_bvid_only_legacy_manifest_row_remains_checkable(tmp_path: Path) -> None:
    row = {"bvid": "BVlegacy", "status": "pending"}
    _manifest(tmp_path, [row])

    report = IntegrityVerifier().verify(tmp_path)

    assert report.authoritative is False
    assert report.checked == 1
    assert any(defect.work_id == "BVlegacy" for defect in report.defects)
    assert "manifest_invalid_bvid" not in report.diagnostics


def test_production_archive_layout_verifies_cleanly(tmp_path: Path) -> None:
    row = {"work_id": "BV1x:p0", "bvid": "BV1x", "cid": 7, "page_index": 0,
           "pubdate_str": "20260828", "title": "A safe/title", "status": "archived"}
    paths = write_archive(tmp_path, row, [{"start": 0, "end": 1, "text": "ok"}], source="cc")
    row.update(paths)
    _manifest(tmp_path, [row])
    assert IntegrityVerifier().verify(tmp_path).defects == []




def test_declared_complete_bundle_paths_are_used_exactly(tmp_path: Path) -> None:
    row = {"work_id": "BV1x:p0", "bvid": "BV1x", "cid": 7, "page_index": 0,
           "pubdate_str": "20260828", "title": "A", "status": "archived"}
    paths = write_archive(tmp_path, row, [{"start": 0, "end": 1, "text": "ok"}], source="cc")
    row.update(paths)
    _manifest(tmp_path, [row])
    row["md_path"] = "transcripts/md/not-the-marker.md"
    _manifest(tmp_path, [row])
    report = IntegrityVerifier().verify(tmp_path)
    assert any(d.code == "identity_path_mismatch" for d in report.defects)


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


def test_symlinked_artifact_is_not_read(tmp_path: Path) -> None:
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
    row = {"work_id": "BV1x:p0", "bvid": "BV1x", "cid": 7, "page_index": 0,
           "status": "archived", "title": "", "pubdate_str": ""}
    paths = write_archive(tmp_path, row, [{"start": 0, "end": 1, "text": "ok"}], source="asr")
    manifest_row = {**row, **paths}
    _manifest(tmp_path, [manifest_row])
    report = IntegrityVerifier().verify(tmp_path)
    assert report.defects == []


def _attempt(work_id: str, outcome: str = "failed") -> dict[str, object]:
    return {"stage": "asr", "work_id": work_id, "attempt": 1, "outcome": outcome,
            "error_code": "E_TEST", "artifact_paths": [],
            "started_at": "2026-01-01T00:00:00Z", "finished_at": "2026-01-01T00:00:01Z"}


def test_report_shape_is_sorted_and_idempotent(tmp_path: Path) -> None:
    _manifest(tmp_path, [{"work_id": "b", "status": "pending"}, {"work_id": "a", "status": "needs_audio"}])
    first = IntegrityVerifier().verify(tmp_path).to_dict()
    assert first == IntegrityVerifier().verify(tmp_path).to_dict()
    assert set(first) == {"checked", "defect_count", "backlog_count", "defects", "diagnostics", "authoritative"}
    assert first["defects"] == sorted(first["defects"], key=lambda d: (d["work_id"], d["code"]))


def test_scope_uses_attempt_outcomes(tmp_path: Path) -> None:
    _manifest(tmp_path, [{"work_id": "pending", "status": "pending"}, {"work_id": "archived", "status": "archived"}, {"work_id": "running", "status": "running"}])
    path = tmp_path / "coordinator" / "attempts.jsonl"; path.parent.mkdir()
    path.write_text(json.dumps(_attempt("archived")) + "\n" + json.dumps(_attempt("running", "ok")) + "\n", encoding="utf-8")
    assert IntegrityVerifier().verify(tmp_path, scope="pending").checked == 1
    assert IntegrityVerifier().verify(tmp_path, scope="failed").checked == 1
    invalid = IntegrityVerifier().verify(tmp_path, scope="running")
    assert invalid.checked == 0
    assert invalid.authoritative is False
    assert "manifest_invalid_status" in invalid.diagnostics


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


def test_append_only_history_is_not_a_structural_error(tmp_path: Path) -> None:
    """One work_id with a real state history is ordinary, not malformed."""
    row = {"work_id": "BV1x:p0", "bvid": "BV1x", "cid": 7, "page_index": 0,
           "pubdate_str": "20260828", "title": "A", "status": "needs_audio"}
    paths = write_archive(tmp_path, {**row, "status": "archived"},
                          [{"start": 0, "end": 1, "text": "ok"}], source="cc")
    _manifest(tmp_path, [row, {**row, "status": "audio_ok"},
                         {**row, "status": "archived", **paths}])
    # The attempts sidecar must exist: without it integrity.py L238-241 files
    # `missing_attempts_sidecar` and the exit stays 1 for an unrelated reason.
    attempts = tmp_path / "coordinator" / "attempts.jsonl"
    attempts.parent.mkdir()
    attempts.write_text(json.dumps(_attempt("BV1x:p0", "ok")) + "\n", encoding="utf-8")
    report = IntegrityVerifier().verify(tmp_path)
    assert report.defects == []
    assert report.diagnostics == []          # -> cli.py L2800 then returns 0


def test_verify_exits_zero_on_history_and_non_zero_on_real_damage(tmp_path: Path) -> None:
    """The exit contract, pinned in both directions through `cli.main`.

    `cli.py`'s `_cmd_verify` now has two gates (exit-code contract §2). The
    default one returns `1 if payload["defect_count"] or payload["diagnostics"]
    else 0` — backlog rows are printed in their own `backlog:` section and never
    move the exit code. The `--strict` branch keeps the pre-cutover rule, `0 if
    not payload["defects"] and not payload["diagnostics"] else 1`, so *any*
    finding of either class still fails it. This test drives the default gate;
    the healthy half needs `coordinator/attempts.jsonl`, without which
    `missing_attempts_sidecar` keeps the exit at 1 for an unrelated reason.
    """
    from bili_asr import cli

    row = {"work_id": "BV1x:p0", "bvid": "BV1x", "cid": 7, "page_index": 0,
           "pubdate_str": "20260828", "title": "A", "status": "needs_audio"}
    paths = write_archive(tmp_path, {**row, "status": "archived"},
                          [{"start": 0, "end": 1, "text": "ok"}], source="cc")
    healthy = [{**row, "status": "audio_ok"}, {**row, "status": "archived", **paths}]
    _manifest(tmp_path, [row, *healthy])
    attempts = tmp_path / "coordinator" / "attempts.jsonl"
    attempts.parent.mkdir()
    attempts.write_text(json.dumps(_attempt("BV1x:p0", "ok")) + "\n", encoding="utf-8")
    assert cli.main(["verify", "--archive-root", str(tmp_path), "--format", "json"]) == 0

    # A status outside VALID_STATUSES still reaches the else-branch and still
    # fails the same command closed — the fix is bidirectional.
    _manifest(tmp_path, [row, *healthy, {**row, "work_id": "BV1broken:p0",
                                        "bvid": "BV1broken", "status": "no_such_status"}])
    assert cli.main(["verify", "--archive-root", str(tmp_path), "--format", "json"]) == 1

    # The same input still reaches the command as a defect list, not a silence.
    from io import StringIO
    import contextlib

    buffer = StringIO()
    with contextlib.redirect_stdout(buffer):
        cli.main(["verify", "--archive-root", str(tmp_path), "--format", "json"])
    assert STRUCTURAL_INPUT_ERROR in json.loads(buffer.getvalue())["diagnostics"]


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


def test_invalid_manifest_semantics_are_named_and_non_authoritative(tmp_path: Path) -> None:
    _manifest(tmp_path, [{"work_id": "BV1x:p0", "bvid": "BVother", "status": "not-a-status"}])
    report = IntegrityVerifier().verify(tmp_path)
    assert report.authoritative is False
    assert {"manifest_invalid_status", "manifest_invalid_bvid"} <= set(report.diagnostics)


def _two_roots(tmp_path: Path, row: dict[str, object]) -> tuple[Path, Path, ArtifactRoots]:
    """An archive root holding only state, and an artifact root holding the bundle."""
    archive = tmp_path / "state"
    artifact = tmp_path / "artifacts"
    artifact.mkdir(parents=True, exist_ok=True)
    row.update(write_archive(artifact, dict(row), [{"start": 0, "end": 1, "text": "ok"}], source="cc"))
    return archive, artifact, ArtifactRoots.of(archive, artifact)


def test_verify_grades_artifacts_at_the_artifact_root(tmp_path: Path) -> None:
    """`verify` probes the ordered bases; `authoritative` stays a state-only judgement."""
    row: dict[str, object] = {"work_id": "BV1x:p0", "bvid": "BV1x", "cid": 7, "page_index": 0,
                              "pubdate_str": "20260828", "title": "A safe/title", "status": "archived"}
    archive, _artifact, roots = _two_roots(tmp_path, row)
    _manifest(archive, [row])

    report = IntegrityVerifier().verify(archive, artifact_roots=roots)

    assert report.defects == []
    assert report.checked == 1
    # Spec §10: the authoritative judgement is a function of the state reads. The
    # absent attempts sidecar still makes the report non-authoritative, exactly as
    # before, and no artifact-root condition flips it either way.
    assert report.authoritative is False
    assert MISSING_ATTEMPTS in report.diagnostics

    # Control: the archive root alone is what today's call grades, and the bundle is
    # not there — the row reads as missing its transcript.
    assert MISSING_TRANSCRIPT in {
        defect.code for defect in IntegrityVerifier().verify(archive).defects
    }


def test_recover_forwards_the_artifact_root_into_its_verification(tmp_path: Path) -> None:
    """`recover` hides a second `verify` call; it must grade the same bases."""
    row: dict[str, object] = {"work_id": "BV1x:p0", "bvid": "BV1x", "cid": 7, "page_index": 0,
                              "pubdate_str": "20260828", "title": "A", "status": "archived"}
    archive, _artifact, roots = _two_roots(tmp_path, row)
    _manifest(archive, [row])
    attempts = archive / "coordinator" / "attempts.jsonl"
    attempts.parent.mkdir(parents=True)
    attempts.write_text(json.dumps(_attempt(str(row["work_id"]), outcome="ok")) + "\n", encoding="utf-8")

    # The row is graded clean at its own base, so it has no defect to select.
    assert IntegrityVerifier.recover(
        archive, work_ids=[str(row["work_id"])], artifact_roots=roots
    ) == {"ok": False, "code": RECOVERY_TARGET_NOT_FOUND, "selected": []}

    # Omitting the roots grades against the archive root, where the bundle is absent:
    # the same target is then reported defective — the silent mis-grading that
    # forwarding exists to remove.
    assert IntegrityVerifier.recover(archive, work_ids=[str(row["work_id"])])["ok"] is True
    # The audit sidecar is state and stays at the archive root (D13, spec §10).
    assert (archive / "coordinator" / "recovery-audit.jsonl").is_file()


#: A transcript that `_valid_artifact` accepts; the empty string is the defect.
_CAPTION_SRT = "1\n00:00:00,000 --> 00:00:01,000\ncaption\n"


def _caption_copy(root: Path, row: dict[str, object], srt_text: str) -> str:
    """One harvested-caption copy below ``root``; returns the recorded ``srt_path``.

    `harvest_subtitle` writes the caption document under ``subtitles/raw/`` and the srt
    under ``transcripts/srt/``, records ``srt_path`` alone and marks the row
    ``subtitle_done`` (`subtitles.py:143-165`) — no txt, no md, no bundle marker, so no
    base holds a bundle this row's completeness could be read from.
    """
    stem = archive_stem(row)
    srt = root / "transcripts" / "srt" / f"{stem}.srt"
    srt.parent.mkdir(parents=True, exist_ok=True)
    srt.write_text(srt_text, encoding="utf-8")
    document = root / "subtitles" / "raw" / f"{stem}.json"
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_text(json.dumps({"body": [{"from": 0, "to": 1, "content": "caption"}]}),
                        encoding="utf-8")
    return f"transcripts/srt/{stem}.srt"


def _defect_codes(report: IntegrityReport) -> dict[str, set[str]]:
    codes: dict[str, set[str]] = {}
    for defect in report.defects:
        codes.setdefault(defect.work_id, set()).add(defect.code)
    return codes


def _inflight_row(work_id: str, **extra: object) -> dict[str, object]:
    """One in-flight row: a row `verify` reads while the chain is still running."""
    return {"work_id": work_id, "bvid": work_id.split(":")[0], "cid": 7, "page_index": 0,
            "pubdate_str": "20260101", "title": "t", "status": "needs_audio", **extra}


def _attempts_sidecar(root: Path, ids: list[str]) -> None:
    """The sidecar an authoritative report needs; absent it the report files
    `missing_attempts_sidecar` and the exit moves for an unrelated reason."""
    path = root / "coordinator" / "attempts.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(_attempt(work_id, "ok")) + "\n" for work_id in ids),
                    encoding="utf-8")


def _verify_payload(root: Path) -> tuple[int, dict[str, object]]:
    """The command's exit code and JSON payload — the two-class gate in situ."""
    from io import StringIO
    import contextlib

    from bili_asr import cli

    buffer = StringIO()
    with contextlib.redirect_stdout(buffer):
        code = cli.main(["verify", "--archive-root", str(root), "--format", "json"])
    return code, json.loads(buffer.getvalue())


def test_inflight_declared_raw_path_escaping_every_base_is_a_defect(tmp_path: Path) -> None:
    """§2d: `verify` probes a declared `raw_path` for in-flight rows too.

    Pre-fix `verify` exited 0 here (it probed `raw_path` only for
    `subtitle_done`), while `coverage --quality` reported the escape and exited 1
    — the fail-closed disagreement §2d closes by widening `verify`.
    """
    _manifest(tmp_path, [_inflight_row("BVesc:p0", raw_path="../../evil/x.json")])
    _attempts_sidecar(tmp_path, ["BVesc:p0"])

    report = IntegrityVerifier().verify(tmp_path)

    assert any(d.code == "identity_path_mismatch" and d.work_id == "BVesc:p0"
               for d in report.defects)
    assert report.defect_count >= 1
    code, payload = _verify_payload(tmp_path)
    assert code == 1
    assert payload["defect_count"] >= 1


def test_inflight_declared_artifact_path_escaping_every_base_is_a_defect(tmp_path: Path) -> None:
    """§2d: the second declared candidate set — `artifact_path`.

    Pre-fix `verify` probed `artifact_path` never, so this row was silent to it
    while `coverage --quality` flagged it.
    """
    _manifest(tmp_path, [_inflight_row("BVesc2:p0", artifact_path="../../evil/y.srt")])
    _attempts_sidecar(tmp_path, ["BVesc2:p0"])

    report = IntegrityVerifier().verify(tmp_path)

    assert any(d.code == "identity_path_mismatch" and d.work_id == "BVesc2:p0"
               for d in report.defects)
    code, payload = _verify_payload(tmp_path)
    assert code == 1
    assert payload["defect_count"] >= 1


def test_inflight_declared_artifact_paths_list_escaping_every_base_is_a_defect(tmp_path: Path) -> None:
    """§2d: the list form, probed value by value.  Silent to `verify` pre-fix."""
    _manifest(tmp_path, [_inflight_row("BVesc3:p0", artifact_paths=["../../evil/a.srt"])])
    _attempts_sidecar(tmp_path, ["BVesc3:p0"])

    report = IntegrityVerifier().verify(tmp_path)

    assert any(d.code == "identity_path_mismatch" and d.work_id == "BVesc3:p0"
               for d in report.defects)
    code, payload = _verify_payload(tmp_path)
    assert code == 1
    assert payload["defect_count"] >= 1


def test_inflight_absent_canonical_path_is_not_an_identity_mismatch(tmp_path: Path) -> None:
    """The no-op control: absence is never this finding (§2d item 2).

    The widened probe must stay inert on the shipped shape — a canonical
    relative path whose artifact the chain has not written yet.  It passed
    pre-fix and must still pass: if the new probe answered "not there" with
    `identity_path_mismatch` it would convert the §2 headline backlog case into a
    defect and the fix would fail its own DoD.
    """
    _manifest(tmp_path, [_inflight_row("BVabsent:p0", raw_path="subtitles/raw/BVabsent.p0.json")])
    _attempts_sidecar(tmp_path, ["BVabsent:p0"])

    report = IntegrityVerifier().verify(tmp_path)

    assert not any(d.code == "identity_path_mismatch" for d in report.defects)
    assert report.defect_count == 0
    code, payload = _verify_payload(tmp_path)
    assert code == 0
    assert payload["defect_count"] == 0


def test_inflight_string_artifact_paths_is_one_value_not_characters(tmp_path: Path) -> None:
    """§2d fix: a bare string is a single path, not an iterable of characters.

    Pre-fix the widened probe iterated the *string*, so every one-character candidate
    (`base/"t"`, `base/"r"`, …) was judged unconfined and the row was reported
    `identity_path_mismatch` — an innocent canonical value graded hostile, and `verify`
    exited 1.  A bare string now reads like `subtitle_path`/`artifact_path` do: one value.
    """
    _manifest(tmp_path, [_inflight_row("BVstr:p0", artifact_paths="transcripts/srt/BVstr.p0.srt")])
    _attempts_sidecar(tmp_path, ["BVstr:p0"])

    report = IntegrityVerifier().verify(tmp_path)

    assert not any(d.code == "identity_path_mismatch" for d in report.defects)
    assert report.defect_count == 0
    code, payload = _verify_payload(tmp_path)
    assert code == 0
    assert payload["defect_count"] == 0


def test_inflight_non_string_artifact_paths_neither_crashes_nor_is_a_path(tmp_path: Path) -> None:
    """§2d fix: a non-iterable `artifact_paths` is skipped, not fatal.

    Pre-fix `for value in row.get("artifact_paths") or ():` raised
    `TypeError: 'int' object is not iterable` out of `verify`, so one hand-edited field
    killed the whole report.  A non-string cannot be a path, so it is not this finding.
    """
    _manifest(tmp_path, [_inflight_row("BVint:p0", artifact_paths=5)])
    _attempts_sidecar(tmp_path, ["BVint:p0"])

    report = IntegrityVerifier().verify(tmp_path)

    assert not any(d.code == "identity_path_mismatch" for d in report.defects)
    assert report.defect_count == 0
    code, payload = _verify_payload(tmp_path)
    assert code == 0
    assert payload["defect_count"] == 0


def test_inflight_escaping_symlink_at_the_inferred_raw_path_is_not_a_mismatch(tmp_path: Path) -> None:
    """Open question settled: an escaping symlink at the *inferred* raw path.

    `raw_path` is undeclared and the row is `needs_audio`, so the inferred candidate
    `subtitles/raw/<stem>.json` is never probed for containment — §2d asks that question
    for `subtitle_done` only.  Measured: the escaping link is silent to this finding; the
    row carries exactly one `retryable_incomplete` backlog entry and no defect, so `verify`
    still exits 0.  The link is confined, if at all, by the readers that open the file.
    """
    row = _inflight_row("BVraw:p0")
    _manifest(tmp_path, [row])
    _attempts_sidecar(tmp_path, ["BVraw:p0"])
    outside = tmp_path.parent / f"{tmp_path.name}-outside.json"
    outside.write_text("{}", encoding="utf-8")
    link = tmp_path / "subtitles" / "raw" / f"{archive_stem(row)}.json"
    link.parent.mkdir(parents=True)
    link.symlink_to(outside)
    assert not link.resolve().is_relative_to(tmp_path.resolve())  # the fixture really escapes

    report = IntegrityVerifier().verify(tmp_path)

    assert _defect_codes(report) == {"BVraw:p0": {RETRYABLE_INCOMPLETE}}
    assert report.defect_count == 0
    code, payload = _verify_payload(tmp_path)
    assert code == 0
    assert payload["defect_count"] == 0


def test_malformed_manifest_line_reaches_the_report_as_a_defect(tmp_path: Path) -> None:
    """§6 assertion 2: a malformed JSONL line is a defect, not swallowed history.

    Pre-fix the `manifest_malformed` branch hit `continue`, so this manifest gave
    `defects: []` *and* `diagnostics: []` and `verify` exited 0, while `coverage`
    reported the same line.  The line is a *diagnostic* of defect class, so it
    must not appear in the backlog section either.
    """
    manifest = tmp_path / "manifest" / "manifest.jsonl"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("not-json\n", encoding="utf-8")
    _attempts_sidecar(tmp_path, [])

    report = IntegrityVerifier().verify(tmp_path)

    assert report.defect_count + len(report.diagnostics) > 0
    assert len(report.diagnostics) > 0
    code, payload = _verify_payload(tmp_path)
    assert code != 0
    # The backlog section reads `defects` entries of category `backlog`; a
    # diagnostic is outside it, and a malformed line names no work_id to list.
    assert payload["backlog_count"] == 0


def test_verify_reads_each_recorded_path_at_the_first_base_that_holds_it(tmp_path: Path) -> None:
    """§5/§10: the ordered probe decides *which* copy answers — content included.

    Both rows are the legacy harvested-caption shape and both bases hold a file at the
    recorded ``srt_path``, so the two copies disagree about the row.  The first base
    that holds a path answers for it: a union over the bases would mark both rows
    malformed, and falling through to a copy that parses would clear both.  Only the
    ordered probe reports the defect that is really there, at the base it is in.
    """
    archive = tmp_path / "state"
    artifact = tmp_path / "artifacts"
    archive.mkdir(parents=True)
    artifact.mkdir(parents=True)
    broken = {"work_id": "BVbroken:p0", "bvid": "BVbroken", "cid": 11, "page_index": 0}
    intact = {"work_id": "BVok:p0", "bvid": "BVok", "cid": 12, "page_index": 0}

    rows: list[dict[str, object]] = []
    for row, at_artifact, at_archive in (
        (broken, "", _CAPTION_SRT),          # the defect is real at the configured root
        (intact, _CAPTION_SRT, ""),          # here the legacy copy is the broken one
    ):
        recorded = _caption_copy(artifact, row, at_artifact)
        assert _caption_copy(archive, row, at_archive) == recorded
        rows.append({**row, "status": "subtitle_done", "srt_path": recorded})
    _manifest(archive, rows)

    configured = IntegrityVerifier().verify(
        archive, artifact_roots=ArtifactRoots.of(archive, artifact)
    )
    assert _defect_codes(configured) == {
        "BVbroken:p0": {MALFORMED_ARTIFACT, MISSING_TRANSCRIPT},
        "BVok:p0": {MISSING_TRANSCRIPT},
    }

    # The fixture is symmetric — each row is broken at exactly one base — so the
    # single-base view mirrors those verdicts from the copy at the archive root.
    assert _defect_codes(IntegrityVerifier().verify(archive)) == {
        "BVbroken:p0": {MISSING_TRANSCRIPT},
        "BVok:p0": {MALFORMED_ARTIFACT, MISSING_TRANSCRIPT},
    }
