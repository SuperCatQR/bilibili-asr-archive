"""Tests for the pure proofread verifier.

The load-bearing properties here are the ones the 2026-09-23 measurement wave
established against the six real finished transcripts. The previous seat's three
route-dependent checks were written from a prose annex and refused **all six**
real candidates, mostly on artifacts: every candidate's body is a reflowed prose
edition of the routes, so a contiguity test rejects 43%-92% of its paragraphs,
and the record table is a whole proofreading log (68-194 rows) of which only the
marked rows can pair with a body mark.

These fixtures are inline and self-contained on purpose: the ``/mnt/123pan``
corpus is a measurement artifact, not a test dependency, so the suite must pass
on a machine that has never seen it. A corpus-gated test lives at the bottom.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

import bili_asr.services.editorial_verify as verify_module
from bili_asr import archive as archive_module
from bili_asr.cli import main
from bili_asr.services.editorial_verify import (
    ADVISORY_RULE_IDS,
    ERROR_RULE_IDS,
    E_RULE_IDS,
    CandidateFacts,
    Verdict,
    Violation,
    check_change_evidence,
    check_containment,
    check_hotword_screen,
    check_marker_record_parity,
    check_marker_vocabulary,
    closing_line,
    parse_candidate,
    verdict_line,
    verify_candidate,
)
from bili_asr.storage import (
    AcquisitionRunRecord,
    MetadataRepository,
    TranscriptRepository,
    TranscriptSegmentRecord,
    open_database,
)
from fixtures.metadata_records import (
    make_part_record,
    make_user_record,
    make_video_record,
)

# --- fixtures, inline by design (no shared fixtures) -------------------------

FRONTMATTER = '---\nwork_id: "BV1:p0"\nbvid: "BV1"\n---\n'
PROLOGUE = "# t\n\n> legend\n\n"
RECORD_HEADING = "## 校对记录\n\n"

HEADER_ROW = "| # | 时间 | 原 ASR | AI 字幕 | 定稿 | 依据 |\n"
SEPARATOR_ROW = "| --- | --- | --- | --- | --- | --- |\n"


def record_row(asr: str, caption: str, final: str, evidence: str,
               ordinal: str = "1", timestamp: str = "00:00:00") -> str:
    """One six-cell 校对记录 row, in the real corpus's column order."""
    return f"| {ordinal} | {timestamp} | {asr} | {caption} | {final} | {evidence} |\n"


def candidate(body: str, rows: str = "") -> str:
    """A candidate whose body and record table are the two supplied halves."""
    return FRONTMATTER + PROLOGUE + body + "\n" + RECORD_HEADING + HEADER_ROW + SEPARATOR_ROW + rows


def table(rows: str) -> str:
    """A record table on its own, header and separator included."""
    return HEADER_ROW + SEPARATOR_ROW + rows


# --- R1: the record table is found through blank lines and a prose budget -----


def test_record_table_after_a_blank_line_is_parsed() -> None:
    """Two of the six real candidates put a blank line between heading and table."""
    text = FRONTMATTER + PROLOGUE + RECORD_HEADING + "\n" + table(record_row("a", "b", "c", "d"))
    facts = parse_candidate(text)

    assert len(facts.record_rows) == 1
    assert facts.fail_closed is False


def test_record_table_after_a_prose_paragraph_is_parsed() -> None:
    """``BV1vNTqzFEve.p0.md`` has a paragraph of prose between heading and table."""
    prose = "本节记录本次校对的判定口径，以及三处存疑的处理方式。\n还有一行散文说明。\n\n"
    text = FRONTMATTER + PROLOGUE + RECORD_HEADING + prose + table(record_row("a", "b", "c", "d"))
    facts = parse_candidate(text)

    assert len(facts.record_rows) == 1
    assert facts.fail_closed is False


def test_record_table_stops_at_the_first_non_table_line() -> None:
    """Rows after the table ends are not rows; prose after it is not a row either."""
    rows = record_row("a", "b", "c", "d") + record_row("e", "f", "g", "h")
    text = FRONTMATTER + PROLOGUE + RECORD_HEADING + table(rows) + "\n表格之后的散文。\n"
    facts = parse_candidate(text)

    assert len(facts.record_rows) == 2


def test_record_table_not_found_within_the_prose_budget_fails_closed() -> None:
    """An unreadable record must not masquerade as a candidate with no changes."""
    prose = "".join(f"散文第{index}行。\n" for index in range(12))
    text = FRONTMATTER + PROLOGUE + RECORD_HEADING + prose + table(record_row("a", "b", "c", "d"))
    facts = parse_candidate(text)

    assert facts.record_rows == ()
    assert facts.fail_closed is True


def test_frontmatter_survives_a_leading_blank_line() -> None:
    """``BV1iddQYQE7D.p0.md`` opens with a blank line before the opening fence."""
    facts = parse_candidate("\n" + candidate("hello world\n"))

    assert (facts.work_id, facts.bvid) == ("BV1:p0", "BV1")


def test_identity_holds_for_a_candidate_with_a_leading_blank_line() -> None:
    """A leading blank line must not turn into two spurious ``identity_mismatch`` refusals."""
    text = "\n" + FRONTMATTER + PROLOGUE + "hello world\n"
    verdict = verify_candidate(
        text, work_id="BV1:p0", bvid="BV1", reference="BV1:p0",
        asr_text="hello world", caption_text="hello world", hotwords=["hello"],
    )

    assert not any(v.rule == "identity_mismatch" for v in verdict.violations)


# --- R3: only a row that contradicts both routes asserts a change -------------


def test_row_matching_one_route_asserts_no_change() -> None:
    """``定稿`` equal to either route cell is a retained reading, not a change."""
    rows = record_row("原样一句话", "字幕一句话", "原样一句话", "")
    facts = parse_candidate(candidate("body text\n", rows))

    assert check_change_evidence(facts) == ()


def test_row_differing_from_both_routes_without_evidence_refuses() -> None:
    """A genuine change with a blank ``依据`` is the defect this rule exists for."""
    rows = record_row("原样一句话", "字幕一句话", "改写后另一句话", "")
    facts = parse_candidate(candidate("body text\n", rows))
    violations = check_change_evidence(facts)

    assert [v.rule for v in violations] == ["evidence_missing"]
    assert violations[0].advisory is False


def test_row_naming_only_the_evidence_column_is_accepted() -> None:
    """``依据`` is the only evidence column.

    Scanning the whole row would make the rule unfalsifiable: 感性 is a coincidental
    substring of 为/的 rows, and 为/的 match in *every* row of the real corpus.
    """
    rows = record_row("原样一句话", "字幕一句话", "改写后另一句话", "asr 00:01:02")
    facts = parse_candidate(candidate("body text\n", rows))

    assert check_change_evidence(facts) == ()


def test_evidence_in_an_unrelated_column_does_not_count() -> None:
    """Evidence parked in 备注 is not evidence; the row still refuses."""
    rows = record_row("原样一句话", "字幕一句话", "改写后另一句话", "", "asr 00:01:02")
    facts = parse_candidate(candidate("body text\n", rows))

    assert [v.rule for v in check_change_evidence(facts)] == ["evidence_missing"]


# --- R4: containment is per-character membership, never contiguity ------------


def test_reflowed_body_belonging_to_the_routes_does_not_refuse() -> None:
    """The body is a reflowed prose edition; contiguity would reject it, membership must not."""
    asr = "第一句话在这里。第二句话在那里。"
    caption = "第一句话在这里。第二句话在那里。"
    body = "第一句话在这里。\n\n第二句话\n在那里。\n"
    facts = parse_candidate(candidate(body))

    assert check_containment(facts, asr, caption) == ()


def test_invented_character_refuses_and_names_itself() -> None:
    """A character in neither route is a genuine editorial insertion."""
    asr = "第一句话在这里"
    caption = "第一句话在这里"
    facts = parse_candidate(candidate("第一句话在泓这里\n"))
    violations = check_containment(facts, asr, caption)

    assert [v.rule for v in violations] == ["char_outside_routes"]
    assert "char '泓'" in violations[0].location
    assert ":1 " in violations[0].location


def test_each_occurrence_of_an_out_of_route_character_refuses_separately() -> None:
    """The corpus counts are per occurrence: ``BV1vNTqzFEve`` has 12 for 10 sites."""
    facts = parse_candidate(candidate("XYXY\n"))
    violations = check_containment(facts, "bodyonly", "bodyonly")

    assert [v.location.split("char ")[1][:3] for v in violations] == ["'X'", "'Y'", "'X'", "'Y'"]


# --- R5: the hotword screen compares local windows, not whole routes ----------


def test_hotword_with_agreeing_windows_does_not_refuse() -> None:
    shared = "关于拉康的理论我们稍后再讲一遍"
    facts = parse_candidate(candidate(shared + "\n"))
    violations = check_hotword_screen(facts, shared, shared, ["拉康"])

    assert [v for v in violations if v.rule == "hotword_disagreement"] == []


def test_hotword_with_disagreeing_windows_refuses() -> None:
    facts = parse_candidate(candidate("关于拉康的理论我们稍后再讲一遍\n"))
    violations = check_hotword_screen(
        facts, "关于拉康的理论我们稍后再讲一遍", "关于拉康的学说我们稍后再讲一遍", ["拉康"],
    )

    assert [v.rule for v in violations] == ["hotword_disagreement"]
    assert "拉康" in violations[0].location
    assert "ratio=" in violations[0].location


def test_hotword_present_in_only_one_route_does_not_refuse() -> None:
    """Zero of the six candidates has a token in both routes *and* a disagreeing window.

    A token the caption route never transcribed is a route-coverage fact, not a
    disagreement, so it takes the advisory path instead.
    """
    body = "此在是一个关键术语\n"
    facts = parse_candidate(candidate(body))
    violations = check_hotword_screen(facts, body, "完全不同的字幕文本在这里", ["此在"])

    assert [v for v in violations if v.rule == "hotword_disagreement"] == []


def test_hotword_screen_is_vacuous_for_an_empty_list() -> None:
    facts = parse_candidate(candidate("hello world\n"))
    violations = check_hotword_screen(facts, "hello world", "hello world", [])

    assert [v.rule for v in violations] == ["hotword_screen_vacuous"]
    assert violations[0].advisory is True


def test_hotword_screen_accepts_a_bare_comma_separated_string() -> None:
    """Callers split on commas (R5/R7); the guard against a bare string is defensive."""
    shared = "关于拉康的理论我们稍后再讲一遍"
    facts = parse_candidate(candidate(shared + "\n"))

    assert [v for v in check_hotword_screen(facts, shared, shared, "拉康,此在")
            if v.rule == "hotword_disagreement"] == []


# --- parity counts marked rows, not the whole log ----------------------------


def test_unmarked_record_rows_do_not_break_marker_parity() -> None:
    """The log is 68-194 rows while a candidate has 7-16 marks.

    Counting raw rows against body marks made this rule refuse all six real
    candidates: every row past the mark count that happened to carry a mark in some
    cell was reported. Only *marked* rows can pair with a body mark.
    """
    rows = "".join(record_row(f"asr{i}", f"cap{i}", f"final{i}", "ev") for i in range(30))
    facts = parse_candidate(candidate("hello world\n", rows))

    assert check_marker_record_parity(facts) == ()


def test_marked_row_without_a_body_mark_is_unpaired() -> None:
    rows = record_row("a", "b", "c‹?›", "ev")
    facts = parse_candidate(candidate("hello world\n", rows))
    violations = check_marker_record_parity(facts)

    assert [v.rule for v in violations] == ["marker_parity"]
    assert "marked_rows=1" in violations[0].location


def test_body_mark_without_a_marked_row_is_unpaired() -> None:
    facts = parse_candidate(candidate("hello‹?› world\n", record_row("a", "b", "c", "ev")))
    violations = check_marker_record_parity(facts)

    assert [v.rule for v in violations] == ["marker_parity"]
    assert "body_marks=1" in violations[0].location


# --- the verdict and its report lines ---------------------------------------


def test_verify_candidate_ok_iff_no_error_is_present() -> None:
    """An advisory never flips the verdict; an error always does."""
    shared = "hello world"
    ok = verify_candidate(candidate(shared + "\n"), work_id="BV1:p0", bvid="BV1",
                          reference="BV1:p0", asr_text=shared, caption_text=shared, hotwords=[])
    assert ok.ok is True

    refused = verify_candidate(candidate("hello 泓 world\n"), work_id="BV1:p0", bvid="BV1",
                               reference="BV1:p0", asr_text=shared, caption_text=shared,
                               hotwords=[])
    assert refused.ok is False


def test_verdict_line_prints_ok_summary_alongside_advisories() -> None:
    """R2: keying the ok summary on violations rather than on ok hid the advisory."""
    shared = "hello world"
    verdict = verify_candidate(candidate(shared + "\n"), work_id="BV1:p0", bvid="BV1",
                               reference="BV1:p0", asr_text=shared, caption_text=shared,
                               hotwords=[])
    lines = verdict_line("BV1:p0", verdict).splitlines()

    assert lines[0].startswith("BV1:p0: ok (")
    assert any(line.startswith("BV1:p0: warning (hotword_screen_vacuous)") for line in lines)


def test_verdict_line_refuses_without_an_ok_summary() -> None:
    """A candidate with errors prints no ok summary, only its refusals."""
    verdict = Verdict(
        ok=False,
        violations=(Violation("char_outside_routes", "BV1:p0:1 char '泓'", False),),
        body_chars=3, marks=0, record_rows=0,
    )
    lines = verdict_line("BV1:p0", verdict).splitlines()

    assert lines == ["BV1:p0: refused (char_outside_routes) at BV1:p0:1 char '泓'"]


def test_closing_line_counts_candidates() -> None:
    assert closing_line("verify-proofread", 3, 2, 1) == "verify-proofread: candidates=3 ok=2 refused=1"


def test_parse_candidate_never_raises_on_junk() -> None:
    facts = parse_candidate(None)  # type: ignore[arg-type]

    assert isinstance(facts, CandidateFacts)
    assert facts.record_rows == ()


# --- the annex's own heredoc self-check, pinned -------------------------------


def test_annex_self_check_first_case_refuses_char_outside_routes() -> None:
    body = "---\nwork_id: \"BV1:p0\"\nbvid: \"BV1\"\n---\n# t\n\n> legend\n\n"
    verdict = verify_candidate(body + "this line is nowhere in the routes\n", work_id="BV1:p0",
                               bvid="BV1", reference="BV1:p0", asr_text="totally different text",
                               caption_text="also different", hotwords=[])

    assert verdict_line("BV1:p0", verdict).splitlines()[0].startswith(
        "BV1:p0: refused (char_outside_routes) at "
    )


def test_annex_self_check_second_case_is_ok_with_a_vacuous_warning() -> None:
    body = "---\nwork_id: \"BV1:p0\"\nbvid: \"BV1\"\n---\n# t\n\n> legend\n\n"
    verdict = verify_candidate(body + "hello world\n", work_id="BV1:p0", bvid="BV1",
                               reference="BV1:p0", asr_text="hello world",
                               caption_text="hello world", hotwords=[])
    lines = verdict_line("BV1:p0", verdict).splitlines()

    assert lines[0].startswith("BV1:p0: ok (")
    assert lines[1].startswith("BV1:p0: warning (hotword_screen_vacuous) at ")


# --- the T2c contract: the sixteen cases the plan froze -----------------------
#
# Seven of them drive the command end to end through ``bili_asr.cli.main`` against
# a synthetic archive root: one stored part, its caption row in the store and its
# ASR sidecar below the root. The fixture is built through the repository APIs and
# the shipped writer's own path rule (``archive.bundle_paths``), never by writing
# raw SQL or by guessing a filename, so the two routes the command reads are the
# two routes the archive actually publishes.

#: The contract §E vocabulary, transcribed once. The module's own tuple is
#: compared against it rather than against itself: a re-derivation would let a
#: mistyped id pass both sides.
CONTRACT_RULE_IDS = (
    "accounting_invalid",
    "marker_parity",
    "evidence_missing",
    "char_outside_routes",
    "hotword_disagreement",
    "timestamp_in_body",
    "insertion_unexplained",
    "deletion_unclassified",
    "term_guard_tripped",
    "twin_not_retained",
    "seam_break",
    "concat_mismatch",
    "identity_mismatch",
    "part_missing",
    "route_absent_for_part",
    "hotword_screen_vacuous",
)

CLI_BVID = "BV1T2CCLI"
CLI_CID = 901_001
#: The shared stretch both fixture routes carry, and the drifted caption reading of
#: it. ``拉康`` occurs in the body of the CLI cases, so the hotword screen has a site;
#: the two readings differ by two characters, well under ``FLOOR``.
CLI_SHARED = "关于拉康的理论我们稍后再讲一遍"
CLI_SHARED_DRIFTED = "关于拉康的学说我们稍后再讲一遍"
#: The two routes the fixture publishes. Each carries the shared stretch, so a
#: candidate made of that stretch alone is contained; ``此在`` occurs in the ASR
#: route alone and ``装置`` in the caption route alone, which is what a candidate
#: line may legitimately be found in and nowhere else (R4).
CLI_ASR = "第一段：此在的分析。" + CLI_SHARED + "。第二段：到此为止。"
CLI_CAPTION = "第一段：装置的分析。" + CLI_SHARED + "。第二段：到此为止。"

CLI_CANDIDATE_NAME = f"{CLI_BVID}.p0.md"


def _exit_code(argv: list[str]) -> int:
    """The command's exit code, argparse's own ``SystemExit`` included."""
    try:
        return main(argv)
    except SystemExit as signal:
        return int(signal.code)


def _seed_part(root: str) -> None:
    """Create the store with exactly one stored part, through the repositories."""
    connection = open_database(root)
    try:
        metadata = MetadataRepository(connection)
        with metadata.transaction():
            metadata.upsert_user(make_user_record())
            metadata.upsert_video(make_video_record(CLI_BVID, aid=None, title="T2c"))
            metadata.upsert_part(make_part_record(CLI_BVID, page_index=0, cid=CLI_CID))
    finally:
        connection.close()


def _store_caption(root: str, text: str) -> None:
    """Store one ``subtitle-ai`` caption body — the caption route (D13)."""
    connection = open_database(root)
    try:
        part_id = int(
            connection.execute(
                "SELECT video_part_id FROM video_parts WHERE bvid = ? AND page_index = 0",
                (CLI_BVID,),
            ).fetchone()["video_part_id"]
        )
        repository = TranscriptRepository(connection)
        run_id = f"caption-{CLI_BVID}"
        repository.start_acquisition_run(
            AcquisitionRunRecord(
                run_id=run_id,
                kind="subtitle",
                selector_kind="pending",
                selector_target=None,
                requested_limit=None,
                credential_present=False,
                started_at=101,
            )
        )
        repository.record_acquired_transcript(
            run_id=run_id,
            video_part_id=part_id,
            source_kind="subtitle-ai",
            language="zh-CN",
            segments=(TranscriptSegmentRecord(0, 3_000, text),),
            started_at=200,
            finished_at=300,
            created_at=400,
        )
    finally:
        connection.close()


def _write_sidecar(root: str, text: str, hotwords: str) -> None:
    """Write the bundle's ASR sidecar — the ASR route (D13) — at its writer path."""
    entry = {
        "bvid": CLI_BVID,
        "work_id": f"{CLI_BVID}:p0",
        "page_index": 0,
        "cid": CLI_CID,
        "unresolved": False,
        "page_label": "",
    }
    sidecar = archive_module.bundle_paths(root, entry)["raw_path"]
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(
        json.dumps(
            {
                "segments": [{"start": 0.0, "end": 3.0, "text": text}],
                "source": "asr",
                "provenance": {"model": "t2c-fixture", "hotwords": hotwords},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _fixture_root(root: str, *, asr: str = CLI_ASR, caption: str = CLI_CAPTION,
                  hotwords: str = "拉康") -> str:
    """One archive root holding both routes for the single stored part."""
    os.makedirs(root, exist_ok=True)
    _seed_part(root)
    _store_caption(root, caption)
    _write_sidecar(root, asr, hotwords)
    return root


def _write_candidate(path: str, body: str, rows: str = "", *,
                     work_id: str | None = None, bvid: str | None = None) -> str:
    """Write one candidate document at ``path`` and return the path."""
    document = (
        "---\n"
        f'work_id: "{work_id or CLI_BVID + ":p0"}"\n'
        f'bvid: "{bvid or CLI_BVID}"\n'
        "---\n"
        + PROLOGUE
        + body
        + "\n"
        + RECORD_HEADING
        + HEADER_ROW
        + SEPARATOR_ROW
        + rows
    )
    Path(path).write_text(document, encoding="utf-8")
    return path


def _verify(candidate_path: str, root: str, bvid: str = CLI_BVID) -> int:
    """Run the command the way an operator does, and return its exit code."""
    return _exit_code(
        ["verify-proofread", "--candidate", candidate_path, "--bvid", bvid,
         "--archive-root", root]
    )


# --- 1-2. the clean run and the vocabulary ------------------------------------


def test_a_clean_candidate_verifies_ok_with_its_three_counts() -> None:
    """The ok line carries the three counts D11 fixed, and nothing else refuses."""
    body = CLI_SHARED + "\n"
    verdict = verify_candidate(candidate(body), work_id="BV1:p0", bvid="BV1",
                               reference="BV1:p0", asr_text=body, caption_text=body,
                               hotwords=["拉康"])

    assert verdict.ok is True
    assert verdict.violations == ()
    assert verdict_line("BV1:p0", verdict).splitlines() == [
        "BV1:p0: ok (body_chars=15 marks=0 record_rows=0)"
    ]


def test_an_unlisted_marker_glyph_is_refused_by_its_e_rule_and_location() -> None:
    """A glyph outside the one normalised vocabulary is ``marker_parity``.

    The rule is the contract's (``marker_parity`` covers "every body rejection mark
    is in the one normalised vocabulary"), and the location is the body line the
    unlisted token sits on. Both a *dragged* mark (``‹?〕``, whose two halves are
    not a pair) and a stray glyph (``‹mark``, closing glyph absent) are unlisted.
    """
    mixed = parse_candidate(candidate("他说了一个词 ‹?〕\n"))
    stray = parse_candidate(candidate("他说了一个词 ‹mark\n"))

    for facts in (mixed, stray):
        violations = check_marker_vocabulary(facts)
        assert [v.rule for v in violations] == ["marker_parity"]
        assert violations[0].location == "BV1:p0:1"
        assert violations[0].advisory is False


# --- 3-4. parity, in both directions ------------------------------------------


def test_a_body_marker_without_a_record_row_is_refused_by_parity() -> None:
    """A body mark with no *marked* record row pairing with it."""
    rows = record_row("原话", "字幕话", "定稿话", "依据")  # a row, but unmarked
    facts = parse_candidate(candidate("他说了一个词‹?›\n", rows))

    violations = check_marker_record_parity(facts)

    assert [v.rule for v in violations] == ["marker_parity"]
    assert violations[0].location == "BV1:p0:1 mark '‹?›' (body_marks=1, marked_rows=0)"


def test_a_record_row_without_a_body_marker_is_refused_by_parity() -> None:
    """The other direction: a marked row the body never carries a mark for."""
    rows = record_row("原话", "字幕话", "定稿话‹?›", "依据")
    facts = parse_candidate(candidate("这一行没有任何标记\n", rows))

    violations = check_marker_record_parity(facts)

    assert [v.rule for v in violations] == ["marker_parity"]
    assert violations[0].location == "BV1:p0:row 1 (body_marks=0, marked_rows=1)"


# --- 5. the recorded change and its evidence ----------------------------------


def test_a_recorded_change_without_its_evidence_is_refused() -> None:
    """A 定稿 differing from both route cells asserts a change, so it needs 依据."""
    rows = record_row("原话", "字幕话", "定稿话", "   ")
    facts = parse_candidate(candidate("无关正文\n", rows))

    violations = check_change_evidence(facts)

    assert [v.rule for v in violations] == ["evidence_missing"]
    assert violations[0].location == "BV1:p0:record row #1"
    assert violations[0].advisory is False


# --- 6-8. containment is per-character membership -----------------------------


def test_a_body_line_absent_from_both_routes_is_refused_as_out_of_containment() -> None:
    """A character in neither route is refused, naming itself and its excerpt."""
    facts = parse_candidate(candidate("泓\n"))

    violations = check_containment(facts, "aaaa", "bbbb")

    assert [v.rule for v in violations] == ["char_outside_routes"]
    assert violations[0].location == "BV1:p0:1 char '泓' (neither route) in '泓'"


def test_a_body_line_found_in_the_asr_route_alone_is_contained() -> None:
    """``此在`` is in the ASR route only: membership in *either* route suffices."""
    facts = parse_candidate(candidate("此在是个术语\n"))

    assert check_containment(facts, "此在是个术语", "完全不同的另一段字幕") == ()


def test_a_body_line_found_in_the_caption_route_alone_is_contained() -> None:
    """The mirror of the ASR case: ``装置`` is in the caption route only."""
    facts = parse_candidate(candidate("装置是个术语\n"))

    assert check_containment(facts, "完全不同的一段话", "装置是个术语") == ()


# --- 9-10. the hotword screen -------------------------------------------------


def test_a_hotword_token_where_the_two_routes_disagree_is_refused() -> None:
    """Below the floor the routes disagree, and the location names the token."""
    facts = parse_candidate(candidate(CLI_SHARED + "\n"))

    violations = check_hotword_screen(facts, CLI_SHARED, CLI_SHARED_DRIFTED, ["拉康"])

    assert [v.rule for v in violations] == ["hotword_disagreement"]
    assert violations[0].advisory is False
    assert violations[0].location.startswith(
        f"BV1:p0:1 token '拉康' at {CLI_SHARED.find('拉康')} asr["
    )
    assert "ratio=" in violations[0].location


def test_a_hotword_token_where_the_routes_agree_is_not_a_violation() -> None:
    """The same token, the same fixtures, one agreeing route: nothing to refuse."""
    facts = parse_candidate(candidate(CLI_SHARED + "\n"))

    assert check_hotword_screen(facts, CLI_SHARED, CLI_SHARED, ["拉康"]) == ()


# --- 11. an advisory is not a refusal -----------------------------------------


def test_an_advisory_rule_changes_neither_the_verdict_nor_the_exit(
    tmp_root: str, capsys
) -> None:
    """A sidecar recording no hotword makes the screen vacuous, and that is all.

    The screen could not bite, so the run says so — as a ``warning`` line, on
    stdout, beside the ``ok`` summary — and the exit stays ``0``. Refusing here
    would fake a defect; passing silently would hide that no screen ran.
    """
    root = _fixture_root(os.path.join(tmp_root, "clean"), asr=CLI_SHARED,
                         caption=CLI_SHARED, hotwords="")
    path = _write_candidate(os.path.join(tmp_root, CLI_CANDIDATE_NAME), CLI_SHARED + "\n")

    code = _verify(path, root)

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.splitlines() == [
        f"{CLI_BVID}:p0: ok (body_chars=15 marks=0 record_rows=0)",
        f"{CLI_BVID}:p0: warning (hotword_screen_vacuous) at {CLI_CANDIDATE_NAME}:hotwords=0",
        "verify-proofread: candidates=1 ok=1 refused=0",
    ]
    assert captured.err == ""


# --- 12. the vocabulary is the contract's, and only the contract's ------------


def test_every_emitted_rule_id_is_one_of_the_contracts_sixteen() -> None:
    """§E's sixteen ids, split 14/2 — and no rule id minted anywhere else.

    The second half scans the module's own source for its ``Violation("<id>", …)``
    call sites, so a check that started emitting an id §E does not name fails here
    even if no crafted case happens to reach it.
    """
    assert E_RULE_IDS == CONTRACT_RULE_IDS
    assert len(CONTRACT_RULE_IDS) == 16
    assert ERROR_RULE_IDS == CONTRACT_RULE_IDS[:14]
    assert ADVISORY_RULE_IDS == CONTRACT_RULE_IDS[14:]
    assert ERROR_RULE_IDS == tuple(
        rule for rule in E_RULE_IDS if rule not in ADVISORY_RULE_IDS
    )

    source = Path(verify_module.__file__).read_text(encoding="utf-8")
    emitted = set(re.findall(r'Violation\(\s*"([a-z_]+)"', source))
    assert emitted, "the scan must find the module's call sites at all"
    assert emitted <= set(CONTRACT_RULE_IDS)


# --- 13-16. the command's own promises ----------------------------------------


def test_a_candidate_whose_frontmatter_work_id_disagrees_with_the_selector_is_refused_as_identity_mismatch(
    tmp_root: str, capsys
) -> None:
    """The candidate's own ids must equal the selector, by name, both keys.

    The bare ``--bvid`` takes the only stored part (the candidate's own
    ``work_id`` names no stored part), so the refusal is the identity check's and
    not the selector's: one line per disagreeing frontmatter key, ``work_id``
    before ``bvid`` in the module's own declared key order.
    """
    root = _fixture_root(os.path.join(tmp_root, "archive"), asr=CLI_SHARED,
                         caption=CLI_SHARED)
    foreign = "BV1OTHER"
    path = _write_candidate(os.path.join(tmp_root, "elsewhere.md"), CLI_SHARED + "\n",
                            work_id=f"{foreign}:p0", bvid=foreign)

    code = _verify(path, root)

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out.splitlines() == [
        f"{CLI_BVID}:p0: refused (identity_mismatch) at elsewhere.md:2",
        f"{CLI_BVID}:p0: refused (identity_mismatch) at elsewhere.md:3",
        "verify-proofread: candidates=1 ok=0 refused=1",
    ]
    assert captured.err == ""


def test_refusal_locations_carry_the_basename_and_never_the_operators_parents(
    tmp_root: str, capsys
) -> None:
    """D11's location rule: ``<basename>:<line>``, never the operator's parents.

    The candidate sits three directories deep and its own frontmatter ``work_id``
    is what the pure module can prefix a site with, so the command has to rewrite
    that prefix to the basename. Nothing the operator sees may name a directory.
    """
    root = _fixture_root(os.path.join(tmp_root, "archive"), asr=CLI_ASR,
                         caption=CLI_CAPTION)
    nested = os.path.join(tmp_root, "operators", "private", "dir")
    os.makedirs(nested)
    path = _write_candidate(os.path.join(nested, CLI_CANDIDATE_NAME), "泓\n")

    code = _verify(path, root)

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out.splitlines() == [
        f"{CLI_BVID}:p0: refused (char_outside_routes) at "
        f"{CLI_CANDIDATE_NAME}:1 char '泓' (neither route) in '泓'",
        "verify-proofread: candidates=1 ok=0 refused=1",
    ]
    assert captured.err == ""
    for leaked in (tmp_root, nested, os.path.join(nested, CLI_CANDIDATE_NAME)):
        assert leaked not in captured.out
        assert leaked not in captured.err


@pytest.mark.parametrize("unreadable", ["absent", "directory", "nul"])
def test_an_unreadable_candidate_is_exit_1_naming_the_path_without_a_traceback(
    tmp_root: str, capsys, unreadable: str
) -> None:
    """An absent file, a directory and a NUL-carrying path are one answer, exit 1.

    The path is named as the operator passed it — the one site where the command
    echoes its own argument — and no traceback reaches stderr. The store is never
    reached, because the candidate is read before the connection is opened.
    """
    root = _fixture_root(os.path.join(tmp_root, "archive"))
    candidates = {
        "absent": os.path.join(tmp_root, "never-written.md"),
        "directory": tmp_root,
        "nul": os.path.join(tmp_root, "nul\x00in-name.md"),
    }
    value = candidates[unreadable]

    code = _verify(value, root)

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert captured.err == f"verify-proofread: {value}: unreadable\n"
    assert "Traceback" not in captured.err


def test_no_path_through_the_command_produces_exit_2(tmp_root: str, capsys) -> None:
    """D8: ``2`` stays unreachable, argparse's own usage exit included.

    Every shape below is a usage or configuration error — a missing flag, an
    unknown flag, an unstorable selector, a missing store, a selector naming no
    stored part, an unreadable candidate — plus the help path, which is not an
    error at all. ``_UsageErrorArgumentParser`` is what turns argparse's ``2``
    into ``1``; no handler may reintroduce it.

    The loop is vacuous unless the subparser really exists — an *unregistered*
    ``verify-proofread`` is an argparse usage error too, and every one of these
    assertions would hold while the command did nothing at all — so the last
    block drives the happy path and requires the three real line kinds.
    """
    root = _fixture_root(os.path.join(tmp_root, "archive"))
    path = _write_candidate(os.path.join(tmp_root, CLI_CANDIDATE_NAME), CLI_ASR + "\n")
    absent_root = os.path.join(tmp_root, "no-archive-here")
    absent_candidate = os.path.join(tmp_root, "never-written.md")

    invocations = [
        ["verify-proofread"],
        ["verify-proofread", "--bvid", CLI_BVID],
        ["verify-proofread", "--candidate", path],
        ["verify-proofread", "--candidate", path, "--bvid", CLI_BVID, "--unknown-flag"],
        ["verify-proofread", "--candidate", path, "--bvid", "", "--archive-root", root],
        ["verify-proofread", "--candidate", path, "--bvid", " \t ", "--archive-root", root],
        ["verify-proofread", "--candidate", path, "--bvid", f"{CLI_BVID}\x00",
         "--archive-root", root],
        ["verify-proofread", "--candidate", absent_candidate, "--bvid", CLI_BVID,
         "--archive-root", root],
        ["verify-proofread", "--candidate", path, "--bvid", CLI_BVID,
         "--archive-root", absent_root],
        ["verify-proofread", "--candidate", path, "--bvid", "BV1ABSENT",
         "--archive-root", root],
        ["verify-proofread", "--candidate", path, "--bvid", "BV1ABSENT:p7",
         "--archive-root", root],
        ["verify-proofread", "--help"],
    ]

    for argv in invocations:
        code = _exit_code(argv)
        captured = capsys.readouterr()
        assert code in (0, 1), (argv, code, captured.out, captured.err)

    # Non-vacuity: the command exists, the fixture reaches its handler, and the
    # ok summary really is printed — a registered subparser that silently answered
    # 0 would satisfy every assertion above.  The agreeing pair is used so the run
    # carries no screen warning to fold into the expected lines.
    agreed = _fixture_root(os.path.join(tmp_root, "agreed"), asr=CLI_SHARED,
                           caption=CLI_SHARED, hotwords="拉康")
    agreed_path = _write_candidate(os.path.join(tmp_root, "agreed.md"), CLI_SHARED + "\n")
    assert _verify(agreed_path, agreed) == 0
    assert capsys.readouterr().out.splitlines() == [
        f"{CLI_BVID}:p0: ok (body_chars=15 marks=0 record_rows=0)",
        "verify-proofread: candidates=1 ok=1 refused=0",
    ]


# --- the four route-unavailable lines -----------------------------------------
#
# A part whose two routes are not both reachable has nothing to verify the
# candidate against.  That is a configuration error, and the four ways to reach
# it are answered one spelling each: one message for several causes would send an
# operator to re-run an acquisition that cannot change the answer.


@pytest.mark.parametrize(
    "cause", ["caption_absent", "asr_unreadable", "asr_absent", "caption_unreadable"]
)
def test_a_part_whose_routes_are_not_both_reachable_is_named_by_cause(
    tmp_root: str, capsys, monkeypatch, cause: str
) -> None:
    """``caption_absent`` / ``asr_unreadable`` / ``asr_absent`` / ``caption_unreadable``.

    The first three are reachable from the fixture alone: no stored caption row, a
    sidecar that is not there, a sidecar that carries no text.  The fourth is the
    store listing the row and then failing to read the version back, which no
    outside action can produce — it is reached here by making the read return
    ``None``, the one shape ``read_transcript`` (``storage/database.py:1023``) has
    for "gone since the listing".

    All four: exit 1, the cause on stderr, nothing on stdout — the refusal lands
    before any verdict line is composed — and no traceback.
    """
    root = os.path.join(tmp_root, cause)
    os.makedirs(root, exist_ok=True)
    _seed_part(root)
    if cause != "caption_absent":
        _store_caption(root, CLI_CAPTION)
    if cause != "asr_unreadable":
        # The caption-less case still gets a readable sidecar, so the line it
        # prints is the caption check's answer and not a fallback for an empty
        # root: the four causes are told apart one from another, not from
        # "nothing is there".
        _write_sidecar(root, "" if cause == "asr_absent" else CLI_ASR, "拉康")
    if cause == "caption_unreadable":
        monkeypatch.setattr(
            TranscriptRepository, "read_transcript", lambda self, *args, **kwargs: None
        )
    path = _write_candidate(os.path.join(tmp_root, f"{cause}.md"), CLI_SHARED + "\n")

    code = _verify(path, root)

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert captured.err == (
        f"verify-proofread: {CLI_BVID}:p0: route unavailable ({cause})\n"
    )
    assert "Traceback" not in captured.err


# --- the real corpus, when this machine has it -------------------------------

CORPUS = "/mnt/123pan/bili-asr-e2e"
CANDIDATES = ("BV11p5qzAE6s", "BV1BdtazGEBE", "BV1Y7M4zNEfF",
              "BV1iddQYQE7D", "BV1vNTqzFEve", "BV1zz5zzFENq")
ROW_COUNTS = (96, 106, 89, 191, 194, 68)
OUT_OF_ROUTE = (2, 5, 1, 6, 12, 0)

corpus_present = pytest.mark.skipif(
    not os.path.isdir(os.path.join(CORPUS, "proofread-transcripts", "md")),
    reason="the /mnt/123pan measurement corpus is not mounted on this machine",
)


@corpus_present
@pytest.mark.parametrize(("bvid", "rows", "offenders"),
                         tuple(zip(CANDIDATES, ROW_COUNTS, OUT_OF_ROUTE)))
def test_real_candidate_parses_and_reports_the_measured_counts(
    bvid: str, rows: int, offenders: int,
) -> None:
    """The measurement that the amendment is backed by, pinned per candidate."""
    import json
    from pathlib import Path

    root = Path(CORPUS)
    text = (root / "proofread-transcripts" / "md" / f"{bvid}.p0.md").read_text(encoding="utf-8")
    facts = parse_candidate(text)
    hotwords = json.loads(
        (root / "asr-vs-subtitle" / "transcripts" / "raw" / f"{bvid}.p0.json").read_text(
            encoding="utf-8"
        )
    )["provenance"]["hotwords"]

    assert len(facts.record_rows) == rows
    assert facts.fail_closed is False
    assert facts.counts.get("corrections") == rows

    verdict = verify_candidate(
        text, work_id=f"{bvid}:p0", bvid=bvid, reference=f"{bvid}:p0",
        asr_text=(root / "asr-vs-subtitle" / "transcripts" / "txt" / f"{bvid}.p0.txt").read_text(
            encoding="utf-8"
        ),
        caption_text=(root / "subtitle-publish" / "transcripts" / "txt" / f"{bvid}.p0.txt").read_text(
            encoding="utf-8"
        ),
        hotwords=[token.strip() for token in hotwords.split(",") if token.strip()],
    )
    counts: dict[str, int] = {}
    for violation in verdict.violations:
        counts[violation.rule] = counts.get(violation.rule, 0) + 1

    assert counts.get("char_outside_routes", 0) == offenders
    assert counts.get("evidence_missing", 0) == 0
    assert counts.get("identity_mismatch", 0) == 0
    assert counts.get("route_absent_for_part", 0) == 0
