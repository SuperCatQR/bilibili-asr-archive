"""CLI exit contract for ``verify`` / ``coverage`` (exit-code contract §2, §6).

Default invocation: backlog is work-not-yet-done and contributes nothing to the
exit code; defect-class findings and diagnostics exit 1.  ``--strict`` restores
the pre-cutover gate — any finding of either class exits 1.

Three classes are in play, not two: ``gone`` is **neither** — terminal-complete,
so an absent artifact is expected and never damage (§2b R2).  And a row the
readers call corrupt (unconfined declared path, schema violation) stays
defect-class even while its status is in flight (§2b R3), on both commands.

Fixtures are built here rather than in ``test_integrity.py``: the subject is the
*command's* exit code and printed sections, not the report layer that T1a
already pinned in ``test_integrity_finding_classes.py``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bili_asr import cli
from bili_asr.manifest import VALID_STATUSES


def _fixture(
    root: Path,
    rows: list[dict[str, object]],
    *,
    attempts: list[dict[str, object]] | None = None,
) -> None:
    path = root / "manifest" / "manifest.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    # An absent attempts sidecar is its own diagnostic (`missing_attempts_sidecar`)
    # and would keep the exit at 1 for a reason unrelated to the class split.
    attempts_path = root / "coordinator" / "attempts.jsonl"
    attempts_path.parent.mkdir(parents=True, exist_ok=True)
    attempts_path.write_text(
        "".join(json.dumps(record) + "\n" for record in (attempts or [])),
        encoding="utf-8",
    )


def _sidecars(root: Path, ids: list[str]) -> None:
    """The valid cursor/scheduler/run-ledger a terminal row needs for `evidence_missing`.

    A row that is cumulative-complete is only *evidence-complete* when all four
    sidecars can be read, so the `gone` shape needs these or the exit code would
    move for a reason unrelated to the class split.
    """
    now = "2026-08-28T12:00:00Z"
    cursor = {
        "mid": 23191782, "next_page": 3, "total": len(ids), "state": "complete",
        "last_api_error_code": None, "updated_at": now,
    }
    (root / "meta-cursor.json").write_text(json.dumps(cursor), encoding="utf-8")
    (root / "scheduler.json").write_text(
        json.dumps({
            "scope": "all", "limit": 20, "state": "complete",
            "processed_work_ids": ids, "last_api_error_code": None,
            "allow_long_live": False, "updated_at": now,
        }),
        encoding="utf-8",
    )
    (root / "run-ledger.jsonl").write_text(
        json.dumps({
            "run_id": "run-1", "command": "schedule", "started_at": now,
            "finished_at": now, "exit_code": 0, "mid": 23191782, "work_ids": ids,
            "pages_fetched": 1, "records_fetched": len(ids), "records_existing": 0,
            "last_api_error_code": None, "coverage_summary": {},
            "cursor_snapshot": cursor,
        }) + "\n",
        encoding="utf-8",
    )


def _attempt(work_id: str, outcome: str = "ok") -> dict[str, object]:
    return {
        "stage": "archive", "work_id": work_id, "attempt": 1, "outcome": outcome,
        "error_code": None, "artifact_paths": [],
        "started_at": "2026-08-28T12:00:00Z", "finished_at": "2026-08-28T12:00:01Z",
    }


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
        "srt_path": "transcripts/BV1m.p0/bundle.srt",
        "txt_path": "transcripts/BV1m.p0/bundle.txt",
        "md_path": "transcripts/BV1m.p0/bundle.md",
        "raw_path": "transcripts/BV1m.p0/bundle.raw.json",
    })
    _fixture(backlog_only, [row])
    corrupt = {
        "transcripts/BV1m.p0/bundle.txt": "",
        "transcripts/BV1m.p0/bundle.srt": "NOT A CUE\n",
        "transcripts/BV1m.p0/bundle.raw.json": "{not json",
    }
    for relative, text in corrupt.items():
        path = backlog_only / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    assert cli.main(["coverage", "--archive-root", str(backlog_only),
                     "--quality", "--format", "json"]) == 1


# --- §2b R3: a corrupt row stays a defect while its status is in flight ------


def test_unconfined_declared_path_is_a_defect_on_both_commands(tmp_path: Path) -> None:
    """§2b R3: an escaping declared path is damage, not "not there yet".

    `verify` says `identity_path_mismatch`; `coverage --quality` used to collapse
    it into `artifact_missing` — the backlog reason — and exit 0 on an archive
    that is genuinely corrupt. The two commands must agree, and the only way to
    agree is a distinct defect-class reason (`identity_unconfined`), never a
    loosened `_BACKLOG_REASONS`.
    """
    _fixture(tmp_path, [
        _row("BVesc:p0", "needs_audio"),
    ])
    row = _row("BVesc:p0", "needs_audio")
    row["srt_path"] = "../../evil/BVx.p0.srt"
    _fixture(tmp_path, [row])

    assert cli.main(["verify", "--archive-root", str(tmp_path),
                     "--format", "json"]) == 1
    assert cli.main(["coverage", "--archive-root", str(tmp_path),
                     "--quality", "--format", "json"]) == 1
    # `--strict` was already 1 on both; it is the default gate that regressed.
    assert cli.main(["verify", "--archive-root", str(tmp_path),
                     "--format", "json", "--strict"]) == 1
    assert cli.main(["coverage", "--archive-root", str(tmp_path),
                     "--quality", "--format", "json", "--strict"]) == 1


def test_unconfined_declared_path_reports_its_own_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The exit code moves because a *distinct* reason exists, not by accident."""
    from bili_asr.quality import DEFECT_REASON_CODES

    row = _row("BVesc2:p0", "needs_audio")
    row["srt_path"] = "../../evil/BVx.p0.srt"
    _fixture(tmp_path, [row])

    assert cli.main(["coverage", "--archive-root", str(tmp_path),
                     "--quality", "--format", "json"]) == 1
    payload = json.loads(capsys.readouterr().out)

    reasons = payload["rows"][0]["reasons"]
    assert "identity_unconfined" in reasons
    assert "identity_unconfined" in DEFECT_REASON_CODES
    # The reason is in the defect class, so the summary counts it and the row is
    # not merely carrying an advisory code.
    assert payload["summary"]["identity_unconfined"] == 1
    assert payload["summary"]["valid_work_items"] == 0


def test_unconfined_reason_leaves_genuinely_absent_artifacts_as_backlog(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The new reason does not swallow the case `artifact_missing` exists for.

    A row that declares nothing and has nothing on disk is still simply not
    there yet: `artifact_missing`, backlog, exit 0. If the fix had collapsed the
    two the §2 headline case would have regressed in the other direction.
    """
    _fixture(tmp_path, [_row("BVabs:p0", "needs_audio")])

    assert cli.main(["coverage", "--archive-root", str(tmp_path),
                     "--quality", "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["rows"][0]["reasons"] == ["artifact_missing"]
    assert "identity_unconfined" not in payload["rows"][0]["reasons"]


def test_non_int_cid_is_a_defect_on_both_commands(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """§2b R3 (F4 half): the coverage reader validates `cid` too.

    A schema-violating `cid` is `structural_input_error` to `verify`. F4's probe
    showed the same row flowing straight through the coverage reader, so it is
    *not* unreachable and cannot be dismissed as such — `coverage --quality`
    reports it under its own defect reason. `identity_invalid` is separate from
    `identity_unconfined` because the two need different fixes: one row escaped
    its read bases, the other names a `cid` that is not an int.
    """
    from bili_asr.quality import DEFECT_REASON_CODES

    row = _row("BVcid:p0", "needs_audio")
    row["cid"] = "not-an-int"
    _fixture(tmp_path, [row])

    assert cli.main(["verify", "--archive-root", str(tmp_path),
                     "--format", "json"]) == 1
    capsys.readouterr()
    assert cli.main(["coverage", "--archive-root", str(tmp_path),
                     "--quality", "--format", "json"]) == 1
    payload = json.loads(capsys.readouterr().out)

    reasons = payload["rows"][0]["reasons"]
    assert reasons == ["identity_invalid"], reasons
    assert "identity_invalid" in DEFECT_REASON_CODES
    assert payload["summary"]["identity_invalid"] == 1
    assert payload["summary"]["valid_work_items"] == 0

    assert cli.main(["coverage", "--archive-root", str(tmp_path),
                     "--quality", "--format", "json", "--strict"]) == 1


# --- §2b R1: `retryable_attempt` is backlog, never exit-bearing --------------


def test_plain_coverage_on_pending_and_failed_attempt_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """§2b R1: the non-quality path gates on classes, not on `diagnostics`.

    `coverage` gated on `report.data["diagnostics"]`, which carries
    `retryable_attempt` — "work not yet done, retryable" by §2's own definition.
    The measured archive shape is a `pending` row with a failed attempt, and it
    must reach exit 0 while `verify` already does.
    """
    _fixture(tmp_path, [_row("BVret:p0", "pending")],
             attempts=[_attempt("BVret:p0", "failed")])

    assert cli.main(["verify", "--archive-root", str(tmp_path),
                     "--format", "json"]) == 0
    capsys.readouterr()
    assert cli.main(["coverage", "--archive-root", str(tmp_path),
                     "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    # The diagnostic is still reported — reclassified, not hidden.
    assert "retryable_attempt" in {item["code"] for item in payload["diagnostics"]}
    assert payload["denominator"]["count"] == 1

    # `--strict` is the pre-cutover gate and still sees it.
    assert cli.main(["coverage", "--archive-root", str(tmp_path),
                     "--format", "json", "--strict"]) == 1


def test_plain_coverage_still_exits_one_on_real_diagnostics(tmp_path: Path) -> None:
    """R1's negative control: a genuinely malformed row is not backlog.

    Without this, "drop `retryable_attempt` from the gate" and "drop the gate"
    are indistinguishable.
    """
    manifest = tmp_path / "manifest" / "manifest.jsonl"
    _fixture(tmp_path, [_row("BVok:p0", "pending")])
    row = _row("BVbad:p0", "pending")
    row["status"] = "no_such_status"
    manifest.write_text(manifest.read_text() + json.dumps(row) + "\n", encoding="utf-8")

    assert cli.main(["coverage", "--archive-root", str(tmp_path),
                     "--format", "json"]) == 1


# --- §2b R2: `gone` is terminal-complete, neither class ----------------------


def test_gone_only_archive_exits_zero_on_all_three_commands(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """§2b R2: `gone` is terminal-complete, so its absent artifacts are expected.

    `coverage_report.py` already treats `gone` as complete, and `verify` has no
    rule for it; §2's backlog set is a positive enumeration that omits it, so
    `coverage --quality` alone used to land the row in defect by omission — in
    both modes. It is neither work-not-yet-done nor damage.

    `--strict` is included on the coverage side deliberately: §2 defines it as
    "any finding **of either class**", and a row in neither class is not a
    finding for that gate. `verify --strict` already exits 0 here, and the two
    readers disagreeing on one input is the whole defect family T1c closes, so
    pinning only the default mode would leave half the R2 promise untested.
    """
    _fixture(tmp_path, [_row("BVgone:p0", "gone")], attempts=[_attempt("BVgone:p0")])
    _sidecars(tmp_path, ["BVgone:p0"])

    assert cli.main(["verify", "--archive-root", str(tmp_path),
                     "--format", "json"]) == 0
    assert cli.main(["verify", "--archive-root", str(tmp_path),
                     "--format", "json", "--strict"]) == 0
    assert cli.main(["coverage", "--archive-root", str(tmp_path),
                     "--format", "json"]) == 0
    assert cli.main(["coverage", "--archive-root", str(tmp_path),
                     "--format", "json", "--strict"]) == 0
    capsys.readouterr()
    assert cli.main(["coverage", "--archive-root", str(tmp_path),
                     "--quality", "--format", "json"]) == 0
    capsys.readouterr()
    assert cli.main(["coverage", "--archive-root", str(tmp_path),
                     "--quality", "--format", "json", "--strict"]) == 0
    payload = json.loads(capsys.readouterr().out)
    # The reason still reaches the operator — the ruling reclassifies the row,
    # it does not hide it: nothing is installed for `gone`, so the inferred
    # transcript candidates are simply not there.
    assert payload["rows"][0]["status"] == "gone"
    assert payload["rows"][0]["reasons"] == ["artifact_missing"]
    assert payload["summary"]["artifact_missing"] == 1


def test_gone_row_with_a_real_defect_still_fails_both_commands(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """R2's negative control: terminal-complete is not a blanket exemption.

    `gone` means "no transcript was ever going to exist", not "this row is
    exempt from validation". A row whose artifact *is* present and broken is
    damage on any status, and both readers must still say so — otherwise the
    ruling would be a way to smuggle corruption past the exit code.
    """
    row = _row("BVgonebad:p0", "gone")
    row["srt_path"] = "transcripts/BVgonebad.p0/bundle.srt"
    _fixture(tmp_path, [row], attempts=[_attempt("BVgonebad:p0")])
    _sidecars(tmp_path, ["BVgonebad:p0"])
    broken = tmp_path / "transcripts" / "srt" / "BVgonebad.p0.srt"
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_text("NOT A CUE\n", encoding="utf-8")

    assert cli.main(["verify", "--archive-root", str(tmp_path),
                     "--format", "json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert [defect["code"] for defect in payload["defects"]] == ["malformed_artifact"]

    assert cli.main(["coverage", "--archive-root", str(tmp_path),
                     "--quality", "--format", "json"]) == 1
    assert cli.main(["coverage", "--archive-root", str(tmp_path),
                     "--quality", "--format", "json", "--strict"]) == 1


def test_gone_row_is_counted_complete_by_the_coverage_reader(tmp_path: Path) -> None:
    """The row stays cumulative-complete; the exit change is not a count change."""
    from bili_asr.coverage_report import CoverageReport

    _fixture(tmp_path, [_row("BVgone2:p0", "gone")], attempts=[_attempt("BVgone2:p0")])
    _sidecars(tmp_path, ["BVgone2:p0"])
    report = CoverageReport.build(tmp_path)

    row = report.data["rows"][0]
    assert row["status"] == "gone"
    assert row["cumulative_complete"] is True
    assert report.data["diagnostics"] == []


def test_gone_is_not_a_backlog_status_and_not_a_defect() -> None:
    """Pinned against the §2b R2 reading: `gone` is in neither enumerated set."""
    from bili_asr.cli import _BACKLOG_STATUSES

    assert "gone" in VALID_STATUSES
    assert "gone" not in _BACKLOG_STATUSES


def test_verify_is_unaffected_by_the_gone_ruling(tmp_path: Path) -> None:
    """`gone` passes `verify` in both modes already; the ruling must not move it."""
    _fixture(tmp_path, [_row("BVgone3:p0", "gone")], attempts=[_attempt("BVgone3:p0")])
    _sidecars(tmp_path, ["BVgone3:p0"])

    assert cli.main(["verify", "--archive-root", str(tmp_path),
                     "--format", "json", "--strict"]) == 0


# --- Minors ------------------------------------------------------------------


def test_backlog_status_set_matches_the_integrity_reader(tmp_path: Path) -> None:
    """F9: the in-flight status set is duplicated, so pin the two together.

    `cli.py`'s `_BACKLOG_STATUSES` and `integrity.py`'s inline
    `if status in {"pending", "meta_ok", ...}: defects.add(RETRYABLE_INCOMPLETE)`
    encode the same rule, and the duplication is **unavoidable as an import**:
    `integrity.py` exports no constant for it (only the inline literal at the
    `RETRYABLE_INCOMPLETE` site), the brief forbids editing `integrity.py`, and
    moving the set into a third module would relocate the duplication rather
    than remove it.  Rather than leave two literals free to drift, the
    equivalence is asserted *behaviorally*: the verifier is asked which statuses
    it calls retryable, and the CLI set must match that answer exactly.  A future
    edit to either side fails here instead of silently reclassifying rows.
    """
    from bili_asr.cli import _BACKLOG_STATUSES
    from bili_asr.integrity import RETRYABLE_INCOMPLETE, IntegrityVerifier

    statuses = sorted(VALID_STATUSES)
    manifest = tmp_path / "manifest" / "manifest.jsonl"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        "".join(
            json.dumps(_row(f"BV{index}:p0", status)) + "\n"
            for index, status in enumerate(statuses)
        ),
        encoding="utf-8",
    )
    attempts = tmp_path / "coordinator" / "attempts.jsonl"
    attempts.parent.mkdir(parents=True, exist_ok=True)
    attempts.write_text("", encoding="utf-8")

    report = IntegrityVerifier().verify(tmp_path)
    retryable_bvids = {
        str(defect.work_id).split(":")[0]
        for defect in report.defects
        if defect.code == RETRYABLE_INCOMPLETE
    }
    called_retryable = {
        status
        for index, status in enumerate(statuses)
        if f"BV{index}" in retryable_bvids
    }

    assert called_retryable == set(_BACKLOG_STATUSES)
    # `gone` is terminal-complete (§2b R2) and `archived` is terminal, so neither
    # is in the in-flight set the CLI classifies backlog with.
    assert "gone" in VALID_STATUSES
    assert "gone" not in _BACKLOG_STATUSES
    assert "archived" not in _BACKLOG_STATUSES


def test_backlog_reason_set_matches_the_coverage_reader(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """§2e residual: `_BACKLOG_REASONS` is hand-maintained, so pin it behaviourally.

    Same class as the pinned `_BACKLOG_STATUSES` above: the set decides plain and
    quality `coverage`'s exit code, and a silent drift re-fails the command on a
    healthy-but-backlogged archive — the pain §2 exists to remove.  A member is
    proven by a fixture that exits 0 carrying that reason, a non-member by one
    that exits 1; the literal set contents are never compared.
    """
    from bili_asr.cli import _BACKLOG_REASONS

    # Member: the artifact is not there yet — §2's backlog definition.
    _fixture(tmp_path, [_row("BVwhy1:p0", "needs_audio")])
    assert cli.main(["coverage", "--archive-root", str(tmp_path),
                     "--quality", "--format", "json"]) == 0
    member = json.loads(capsys.readouterr().out)["rows"][0]["reasons"]
    assert member == ["artifact_missing"]
    assert set(member) <= _BACKLOG_REASONS

    # Non-member: the artifact is there and broken, so damage never hides behind
    # the row's in-flight status even though that status is a backlog status.
    broken = tmp_path / "transcripts" / "txt" / "BVwhy1.p0.txt"
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_text("", encoding="utf-8")
    assert cli.main(["coverage", "--archive-root", str(tmp_path),
                     "--quality", "--format", "json"]) == 1
    non_member = json.loads(capsys.readouterr().out)["rows"][0]["reasons"]
    assert non_member == ["empty"]
    assert not set(non_member) & _BACKLOG_REASONS


def test_backlog_diagnostic_set_matches_the_coverage_reader(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """§2e residual: `_BACKLOG_DIAGNOSTICS` is the other unpinned mirror set.

    §2b R1's plain-`coverage` gate reclassifies rather than hides: a member
    diagnostic is still reported and still exits 0, while every other diagnostic
    keeps the command failing closed.  Pinned by behaviour for the same reason as
    the reason set above — a silent drift here moves the plain gate.
    """
    from bili_asr.cli import _BACKLOG_DIAGNOSTICS

    _fixture(tmp_path, [_row("BVwhy2:p0", "pending")],
             attempts=[_attempt("BVwhy2:p0", "failed")])
    assert cli.main(["coverage", "--archive-root", str(tmp_path),
                     "--format", "json"]) == 0
    member = {item["code"] for item in json.loads(capsys.readouterr().out)["diagnostics"]}
    assert member == {"retryable_attempt"}
    assert member <= _BACKLOG_DIAGNOSTICS

    # Non-member: a malformed manifest line is defect-class, so it is exit-bearing
    # even alongside the backlog member above.
    manifest = tmp_path / "manifest" / "manifest.jsonl"
    manifest.write_text(manifest.read_text() + "not-json\n", encoding="utf-8")
    assert cli.main(["coverage", "--archive-root", str(tmp_path),
                     "--format", "json"]) == 1
    non_member = {item["code"] for item in json.loads(capsys.readouterr().out)["diagnostics"]}
    assert non_member == {"manifest_malformed", "retryable_attempt"}
    assert "manifest_malformed" not in _BACKLOG_DIAGNOSTICS
