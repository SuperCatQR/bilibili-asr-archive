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

import os

import pytest

from bili_asr.services.editorial_verify import (
    CandidateFacts,
    Verdict,
    Violation,
    check_change_evidence,
    check_containment,
    check_hotword_screen,
    check_marker_record_parity,
    closing_line,
    parse_candidate,
    verdict_line,
    verify_candidate,
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
