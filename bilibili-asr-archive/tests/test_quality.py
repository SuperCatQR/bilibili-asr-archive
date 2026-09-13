from __future__ import annotations

import json
from pathlib import Path

import pytest

from bili_asr import archive, asr, quality
from bili_asr.archive import LOW_CONFIDENCE, write_archive
from bili_asr.page_identity import page_identity
from bili_asr.quality import (
    CONTENT_REASON_CODES,
    DEFECT_REASON_CODES,
    FRAGMENT_MAX_CHARS,
    FRAGMENT_MAX_SECONDS,
    OVERLONG_CHARS,
    REASON_CODES,
    REFERENCE_AGREEMENT_FLOOR,
    QualityAnalyzer,
    ReferenceUnavailable,
)


def row(**values: object) -> dict[str, object]:
    return {
        "bvid": "BV1demo",
        "work_id": "BV1demo:p0",
        "source": "subtitle",
        "sub_lan": "ai-zh",
        "status": "archived",
        "duration_s": 10,
        **values,
    }


def write_srt(root: Path, name: str, body: str) -> str:
    path = root / "transcripts" / "srt" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return "transcripts/srt/" + name


def test_valid_monotonic_srt_is_stable_and_read_only(tmp_path: Path) -> None:
    relative = write_srt(
        tmp_path, "BV1demo.p0.srt", "1\n00:00:00,000 --> 00:00:01,000\nhello\n"
    )
    path = tmp_path / relative
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    analyzer = QualityAnalyzer()
    first = analyzer.analyze(row(srt_path=relative), tmp_path)
    second = analyzer.analyze(row(srt_path=relative), tmp_path)
    assert first.to_dict() == second.to_dict()
    assert first.reasons == ()
    assert first.cue_count == 1
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert json.dumps(first.to_dict(), sort_keys=True) == json.dumps(
        second.to_dict(), sort_keys=True
    )


def test_canonical_page_identity_has_no_defect(tmp_path: Path) -> None:
    relative = write_srt(
        tmp_path, "BV1demo.p0.srt", "1\n00:00:00,000 --> 00:00:01,000\nhello\n"
    )
    result = QualityAnalyzer().analyze(
        row(work_id="BV1demo:p0", srt_path=relative), tmp_path
    )
    assert result.reasons == ()
    assert result.cue_count == 1


def test_anomaly_reason_codes(tmp_path: Path) -> None:
    cases = {
        "empty": "",
        "malformed": "1\nnot timing\ntext\n",
        "non_monotonic": (
            "1\n00:00:02,000 --> 00:00:03,000\na\n\n2\n00:00:01,000 -->"
            " 00:00:01,500\nb\n"
        ),
        "overlap": (
            "1\n00:00:00,000 --> 00:00:02,000\na\n\n2\n00:00:01,000 -->"
            " 00:00:03,000\nb\n"
        ),
        "out_of_range": "1\n00:00:09,000 --> 00:00:11,000\na\n",
    }
    for reason, content in cases.items():
        relative = write_srt(tmp_path / reason, "BV1demo.p0.srt", content)
        result = QualityAnalyzer().analyze(
            row(srt_path=relative), tmp_path / reason
        )
        assert reason in result.reasons


def test_json_and_standard_archive_paths_are_supported(tmp_path: Path) -> None:
    raw = tmp_path / "transcripts" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "BV1demo.p0.json").write_text(
        json.dumps({"body": [{"from": 0, "to": 1, "content": "x"}]}),
        encoding="utf-8",
    )
    result = QualityAnalyzer().analyze(row(), tmp_path)
    assert result.reasons == ()
    assert result.artifact_count == 1


def test_write_archive_canonical_outputs_pass_quality_analysis(
    tmp_path: Path,
) -> None:
    ident = page_identity("BV1demo", 0, 99)
    entry = {
        "bvid": ident.bvid,
        "work_id": ident.work_id,
        "page_index": 0,
        "cid": 99,
        "title": "demo",
        "pubdate_str": "2026-01-02",
        "duration_s": 12,
        "source": "asr",
        "status": "archived",
    }
    write_archive(
        tmp_path,
        entry,
        [{"start": 0.0, "end": 1.0, "text": "你好"}],
        source="asr",
    )
    result = QualityAnalyzer().analyze(entry, tmp_path)
    assert result.reasons == ()
    assert result.artifact_count == 4
    assert result.cue_count == 2


def test_json_timestamp_anomalies_and_non_finite_values(tmp_path: Path) -> None:
    raw_dir = tmp_path / "transcripts" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    # Non-finite NaN
    (raw_dir / "nan.json").write_text(
        '{"body": [{"from": "NaN", "to": 1.0, "content": "x"}]}',
        encoding="utf-8",
    )
    res_nan = QualityAnalyzer().analyze(
        row(raw_path="transcripts/raw/nan.json"), tmp_path
    )
    assert "malformed" in res_nan.reasons

    # Non-finite Infinity
    (raw_dir / "inf.json").write_text(
        '{"body": [{"from": 0.0, "to": "Infinity", "content": "x"}]}',
        encoding="utf-8",
    )
    res_inf = QualityAnalyzer().analyze(
        row(raw_path="transcripts/raw/inf.json"), tmp_path
    )
    assert "malformed" in res_inf.reasons

    # Negative from timestamp
    (raw_dir / "neg.json").write_text(
        json.dumps({"body": [{"from": -1.0, "to": 1.0, "content": "x"}]}),
        encoding="utf-8",
    )
    res_neg = QualityAnalyzer().analyze(
        row(raw_path="transcripts/raw/neg.json"), tmp_path
    )
    assert "out_of_range" in res_neg.reasons

    # Non-monotonic
    (raw_dir / "nonmono.json").write_text(
        json.dumps(
            {"body": [{"from": 2.0, "to": 3.0}, {"from": 1.0, "to": 1.5}]}
        ),
        encoding="utf-8",
    )
    res_nm = QualityAnalyzer().analyze(
        row(raw_path="transcripts/raw/nonmono.json"), tmp_path
    )
    assert "non_monotonic" in res_nm.reasons

    # Overlap
    (raw_dir / "overlap.json").write_text(
        json.dumps(
            {"body": [{"from": 0.0, "to": 2.0}, {"from": 1.0, "to": 3.0}]}
        ),
        encoding="utf-8",
    )
    res_ov = QualityAnalyzer().analyze(
        row(raw_path="transcripts/raw/overlap.json"), tmp_path
    )
    assert "overlap" in res_ov.reasons

    # Out of range (exceeds duration_s=10)
    (raw_dir / "oor.json").write_text(
        json.dumps({"body": [{"from": 9.0, "to": 12.0}]}),
        encoding="utf-8",
    )
    res_oor = QualityAnalyzer().analyze(
        row(raw_path="transcripts/raw/oor.json"), tmp_path
    )
    assert "out_of_range" in res_oor.reasons


def test_markdown_frontmatter_identity_checks(tmp_path: Path) -> None:
    md_dir = tmp_path / "transcripts" / "md"
    md_dir.mkdir(parents=True, exist_ok=True)

    # Matching frontmatter
    md_ok = md_dir / "2026-01-02_BV1demo.p0_title.md"
    md_ok.write_text(
        '---\nbvid: "BV1demo"\nwork_id: "BV1demo:p0"\n---\n\ncontent\n',
        encoding="utf-8",
    )
    res_ok = QualityAnalyzer().analyze(
        row(md_path=f"transcripts/md/{md_ok.name}"), tmp_path
    )
    assert res_ok.reasons == ()
    assert res_ok.artifact_count == 1

    # Mismatched work_id in frontmatter
    md_bad_work = md_dir / "2026-01-02_BV1demo.p0_badwork.md"
    md_bad_work.write_text(
        '---\nbvid: "BV1demo"\nwork_id: "BV1other:p0"\n---\n\ncontent\n',
        encoding="utf-8",
    )
    res_bad_work = QualityAnalyzer().analyze(
        row(md_path=f"transcripts/md/{md_bad_work.name}"), tmp_path
    )
    assert "identity_mismatch" in res_bad_work.reasons

    # Mismatched bvid in frontmatter
    md_bad_bvid = md_dir / "2026-01-02_BV1demo.p0_badbvid.md"
    md_bad_bvid.write_text(
        '---\nbvid: "BV1other"\nwork_id: "BV1demo:p0"\n---\n\ncontent\n',
        encoding="utf-8",
    )
    res_bad_bvid = QualityAnalyzer().analyze(
        row(md_path=f"transcripts/md/{md_bad_bvid.name}"), tmp_path
    )
    assert "identity_mismatch" in res_bad_bvid.reasons


def test_txt_and_md_single_artifacts_are_not_empty_when_populated(
    tmp_path: Path,
) -> None:
    txt_dir = tmp_path / "transcripts" / "txt"
    txt_dir.mkdir(parents=True, exist_ok=True)
    txt_file = txt_dir / "BV1demo.p0.txt"
    txt_file.write_text("Hello transcript text\nSecond line\n", encoding="utf-8")

    res = QualityAnalyzer().analyze(
        row(txt_path="transcripts/txt/BV1demo.p0.txt"), tmp_path
    )
    assert res.reasons == ()
    assert res.artifact_count == 1
    assert res.cue_count == 0

    # Empty txt file
    empty_txt = txt_dir / "BV1demo.p0_empty.txt"
    empty_txt.write_text("", encoding="utf-8")
    res_empty = QualityAnalyzer().analyze(
        row(txt_path="transcripts/txt/BV1demo.p0_empty.txt"), tmp_path
    )
    assert "empty" in res_empty.reasons


def test_missing_identity_and_traversal_are_redacted(tmp_path: Path) -> None:
    result = QualityAnalyzer().analyze(row(srt_path="../secret.srt"), tmp_path)
    payload = json.dumps(result.to_dict())
    assert result.reasons == ("artifact_missing",)
    assert "secret" not in payload
    assert "http" not in payload


def test_identity_mismatch_is_reported_without_leaking_path(
    tmp_path: Path,
) -> None:
    relative = write_srt(
        tmp_path, "BV1other.p0.srt", "1\n00:00:00,000 --> 00:00:01,000\nx\n"
    )
    result = QualityAnalyzer().analyze(row(srt_path=relative), tmp_path)
    assert result.reasons == ("identity_mismatch",)


def test_reclaimed_audio_does_not_count_as_defect(tmp_path: Path) -> None:
    relative = write_srt(
        tmp_path, "BV1demo.p0.srt", "1\n00:00:00,000 --> 00:00:01,000\nx\n"
    )
    result = QualityAnalyzer().analyze(
        row(srt_path=relative, audio_path="audio/BV1demo.p0.m4a"), tmp_path
    )
    assert result.reasons == ()
    assert result.status == "archived"


# --- content reasons: the second class, advisory by construction ---------------


def test_reason_vocabulary_splits_into_two_classes() -> None:
    assert DEFECT_REASON_CODES == (
        "empty",
        "malformed",
        "non_monotonic",
        "overlap",
        "out_of_range",
        "identity_mismatch",
        "artifact_missing",
    )
    assert CONTENT_REASON_CODES == (
        "low_confidence",
        "leading_mark",
        "fragment_cue",
        "overlong_cue",
        "duplicate_cue",
        "repeated_ngram",
        "reference_disagreement",
    )
    # the ordered union keeps the seven defect codes at their original indices
    assert REASON_CODES == DEFECT_REASON_CODES + CONTENT_REASON_CODES


def test_content_thresholds_track_the_cue_shaper() -> None:
    """A cue the shaper sized is reported only when it could not be merged."""

    assert OVERLONG_CHARS == asr._CUE_MAX_CHARS
    assert FRAGMENT_MAX_CHARS == asr._CUE_MIN_CHARS
    assert FRAGMENT_MAX_SECONDS == asr._CUE_MIN_SECONDS
    # Identity as well as value: the reason and the archived low-confidence
    # count must read the same object, so a local re-declaration in quality.py
    # cannot silently disagree with archive.py.
    assert quality.LOW_CONFIDENCE is archive.LOW_CONFIDENCE
    assert LOW_CONFIDENCE == 0.4


def write_raw(root: Path, name: str, segments: list[dict]) -> str:
    path = root / "transcripts" / "raw" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"segments": segments}), encoding="utf-8")
    return "transcripts/raw/" + name


def test_each_content_reason_fires_on_a_crafted_artefact(tmp_path: Path) -> None:
    """One crafted artefact per content code — and each stays free of defects."""

    overlong = (
        "今天的讨论围绕国际劳工仲裁这个主题展开，涉及多个国家的法律资源分配，"
        "以及普通劳动者在遇到纠纷时能够获得的支持方式与成本问题"
    )
    assert len(overlong) > OVERLONG_CHARS
    cases: dict[str, tuple[str, str]] = {
        "low_confidence": (
            "raw",
            json.dumps(
                {
                    "segments": [
                        {"start": 0.0, "end": 2.0, "text": "正常的一句话", "confidence": 0.25}
                    ]
                }
            ),
        ),
        "leading_mark": (
            "srt",
            "1\n00:00:00,000 --> 00:00:02,000\n，今天天气很好我们出去走走\n",
        ),
        "fragment_cue": ("srt", "1\n00:00:00,000 --> 00:00:00,500\n嗯\n"),
        "overlong_cue": ("srt", f"1\n00:00:00,000 --> 00:00:08,000\n{overlong}\n"),
        "duplicate_cue": (
            "srt",
            "1\n00:00:00,000 --> 00:00:02,000\n重复的一句话\n\n"
            "2\n00:00:02,000 --> 00:00:04,000\n重复的一句话\n",
        ),
        "repeated_ngram": (
            "srt",
            "1\n00:00:00,000 --> 00:00:08,000\n" + "一二三四五六七八" * 4 + "\n",
        ),
    }
    assert set(cases) <= set(CONTENT_REASON_CODES)
    for reason, (kind, body) in cases.items():
        case_root = tmp_path / reason
        if kind == "raw":
            relative = write_raw(case_root, "BV1demo.p0.json", json.loads(body)["segments"])
        else:
            relative = write_srt(case_root, "BV1demo.p0.srt", body)
        result = QualityAnalyzer().analyze(
            row(**{f"{kind}_path": relative}), case_root
        )
        assert reason in result.content_reasons, reason
        # advisory: a content reason never makes the item defective
        assert result.reasons == (), reason
        assert not set(result.content_reasons) & set(DEFECT_REASON_CODES), reason


def test_content_reasons_are_not_defects_and_do_not_leak_into_reasons(
    tmp_path: Path,
) -> None:
    """A healthy transcript with content observations stays a valid work item."""

    relative = write_srt(
        tmp_path,
        "BV1demo.p0.srt",
        "1\n00:00:00,000 --> 00:00:02,000\n，今天天气很好我们出去走走\n",
    )
    result = QualityAnalyzer().analyze(row(srt_path=relative), tmp_path)
    assert result.content_reasons == ("leading_mark",)
    assert result.reasons == ()
    assert "content_reasons" not in result.to_dict()


def test_clean_cue_scores_no_content_reason(tmp_path: Path) -> None:
    relative = write_srt(
        tmp_path, "BV1demo.p0.srt", "1\n00:00:00,000 --> 00:00:02,000\n今天天气很好我们出去走走\n"
    )
    result = QualityAnalyzer().analyze(row(srt_path=relative), tmp_path)
    assert result.content_reasons == ()
    assert result.reasons == ()


def test_srt_only_artefact_reports_no_low_confidence(tmp_path: Path) -> None:
    """No recorded score means not computed — never fabricated."""

    relative = write_srt(
        tmp_path, "BV1demo.p0.srt", "1\n00:00:00,000 --> 00:00:02,000\n今天天气很好我们出去走走\n"
    )
    result = QualityAnalyzer().analyze(row(srt_path=relative), tmp_path)
    assert "low_confidence" not in result.content_reasons


@pytest.fixture(scope="module")
def recorded_cues() -> list[dict]:
    """The recorded Fun-ASR-Nano result for one archived part, shaped as cues."""

    path = (
        Path(__file__).parent
        / "fixtures"
        / "asr-cues"
        / "BV1wLTP6NE9h.p0.tokens.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))[0]
    return asr._token_cues(payload["timestamps"])


def _recorded_entry() -> dict[str, object]:
    ident = page_identity("BV1wLTP6NE9h", 0, 12345)
    return {
        "bvid": ident.bvid,
        "work_id": ident.work_id,
        "page_index": 0,
        "cid": 12345,
        "title": "recorded probe",
        "pubdate_str": "2026-01-02",
        "duration_s": 448.0,
        "source": "asr",
        "status": "archived",
    }


def test_recorded_cue_fixture_yields_the_two_advisory_reasons(
    tmp_path: Path, recorded_cues: list[dict]
) -> None:
    """A3: on the recorded 95-cue transcript the new vocabulary fires exactly
    one under-confident cue and two over-long cues, and nothing else."""

    assert len(recorded_cues) == 95
    segments = [
        {
            "start": cue["start"],
            "end": cue["end"],
            "text": cue["text"],
            "confidence": cue["confidence"],
        }
        for cue in recorded_cues
    ]
    entry = _recorded_entry()
    write_archive(tmp_path, entry, segments, source="asr")

    result = QualityAnalyzer().analyze(entry, tmp_path)
    assert result.reasons == (), "no structural defect on a healthy transcript"
    assert result.content_reasons == ("low_confidence", "overlong_cue")
    # the 95-cue stream is counted once per cue-bearing artifact (srt + raw)
    assert result.artifact_count == 4
    assert result.cue_count == 2 * len(recorded_cues)
    assert sum(1 for cue in recorded_cues if cue["confidence"] <= LOW_CONFIDENCE) == 1
    assert sum(1 for cue in recorded_cues if len(cue["text"]) > OVERLONG_CHARS) == 2
    # the shape layer is untouched: the cue fixture keeps the shaper's invariants
    assert all(cue["text"][0] not in "，。！？、；：" for cue in recorded_cues)
    assert not any(
        len(cue["text"].strip("，。！？、；：")) < FRAGMENT_MAX_CHARS
        and (cue["end"] - cue["start"]) < FRAGMENT_MAX_SECONDS
        for cue in recorded_cues
    )


def test_recorded_cue_fixture_still_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], recorded_cues: list[dict]
) -> None:
    """A3: advisory content reasons must not flip a healthy archive to exit 1."""

    from bili_asr import cli
    from bili_asr.manifest import ManifestStore

    entry = _recorded_entry()
    segments = [
        {
            "start": cue["start"],
            "end": cue["end"],
            "text": cue["text"],
            "confidence": cue["confidence"],
        }
        for cue in recorded_cues
    ]
    write_archive(tmp_path, entry, segments, source="asr")
    ManifestStore(root=str(tmp_path)).upsert(dict(entry))

    exit_code = cli.main(
        ["coverage", "--archive-root", str(tmp_path), "--quality", "--format", "json"]
    )
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["valid_work_items"] == 1
    assert payload["summary"]["total_cues"] == 2 * len(recorded_cues)
    # The row's projected reason list now carries the two advisory content
    # reasons — asserted per class, so a defect leaking into the projection
    # (or a content reason going missing) fails here rather than passing on an
    # accidentally empty list.
    row_reasons = payload["rows"][0]["reasons"]
    assert [r for r in row_reasons if r in DEFECT_REASON_CODES] == []
    assert [r for r in row_reasons if r in CONTENT_REASON_CODES] == [
        "low_confidence",
        "overlong_cue",
    ]
    assert sorted(row_reasons) == ["low_confidence", "overlong_cue"]
    # The content counts are surfaced in the summary too, and the defect codes
    # stay at zero.
    assert payload["summary"]["low_confidence"] == 1
    assert payload["summary"]["overlong_cue"] == 1
    for code in DEFECT_REASON_CODES:
        assert payload["summary"][code] == 0


def _transcript(root: Path, text: str, name: str = "BV1demo.p0.srt") -> str:
    """An SRT named after the ``row()`` helper's canonical stem, so that the
    only reasons in play are the ones a test is about."""

    body = f"1\n00:00:00,000 --> 00:00:04,000\n{text}\n"
    return write_srt(root, name, body)


def test_reference_agreement_compares_flattened_text(tmp_path: Path) -> None:
    """Punctuation and spacing never read as disagreement; the floor holds."""

    relative = _transcript(tmp_path, "你好世界")
    reference = tmp_path / "second.txt"
    reference.write_text("你好，世界！\n", encoding="utf-8")

    result = QualityAnalyzer().analyze(
        row(srt_path=relative), tmp_path, reference
    )
    assert result.reference is not None
    assert result.reference.agreement == 1.0
    assert result.reference.floor == 0.95
    assert result.reference.compared_chars == (4, 4)
    assert "reference_disagreement" not in result.content_reasons


def test_reference_disagreement_is_advisory(tmp_path: Path) -> None:
    """A contested reference adds a content reason and no defect."""

    relative = _transcript(tmp_path, "今天的讨论围绕国际劳工仲裁展开")
    reference = tmp_path / "second.txt"
    reference.write_text("完全无关的另一段录音内容\n", encoding="utf-8")

    result = QualityAnalyzer().analyze(
        row(srt_path=relative), tmp_path, reference
    )
    assert result.reasons == (), "a contested reference is never a defect"
    assert result.content_reasons == ("reference_disagreement",)
    assert result.reference is not None
    assert result.reference.agreement < result.reference.floor
    assert result.reference.reference == "second.txt"


def test_reference_reports_basename_only(tmp_path: Path) -> None:
    """The block never carries the operator's directory layout."""

    relative = _transcript(tmp_path, "hello world")
    nested = tmp_path / "private" / "runs"
    nested.mkdir(parents=True)
    reference = nested / "second.txt"
    reference.write_text("hello world\n", encoding="utf-8")

    result = QualityAnalyzer().analyze(
        row(srt_path=relative), tmp_path, reference
    )
    assert result.reference is not None
    assert result.reference.reference == "second.txt"
    assert "private" not in repr(result.reference)


@pytest.mark.parametrize(
    "name",
    ["sessdata-backup.txt", "cookie-jar.txt", "token-file.txt", "my-secret.txt"],
)
def test_reference_credential_like_name_is_redacted(tmp_path: Path, name: str) -> None:
    """A name that is itself credential-shaped is replaced entirely."""

    relative = _transcript(tmp_path, "hello world")
    reference = tmp_path / name
    reference.write_text("hello world\n", encoding="utf-8")

    result = QualityAnalyzer().analyze(row(srt_path=relative), tmp_path, reference)
    assert result.reference is not None
    assert result.reference.reference == "[redacted]"


@pytest.mark.parametrize("name,body", [("empty.txt", ""), ("blank.txt", "   \n\n")])
def test_reference_without_comparable_text_is_refused(
    tmp_path: Path, name: str, body: str
) -> None:
    """A reference with nothing to compare is a diagnostic, not a silent pass."""

    relative = _transcript(tmp_path, "hello world")
    reference = tmp_path / name
    reference.write_text(body, encoding="utf-8")

    with pytest.raises(ReferenceUnavailable) as exc:
        QualityAnalyzer().analyze(row(srt_path=relative), tmp_path, reference)
    assert exc.value.reason == "reference has no comparable text"


def test_reference_unreadable_is_refused(tmp_path: Path) -> None:
    """A missing reference raises rather than reporting a fabricated ratio."""

    relative = _transcript(tmp_path, "hello world")
    with pytest.raises(ReferenceUnavailable) as exc:
        QualityAnalyzer().analyze(
            row(srt_path=relative), tmp_path, tmp_path / "absent.txt"
        )
    assert exc.value.reason == "reference unreadable"


def test_reference_oversized_is_refused(tmp_path: Path) -> None:
    """``_MAX_BYTES`` bounds the reference exactly as it bounds an artifact."""

    relative = _transcript(tmp_path, "hello world")
    reference = tmp_path / "huge.txt"
    reference.write_text("x" * (quality._MAX_BYTES + 1), encoding="utf-8")

    with pytest.raises(ReferenceUnavailable) as exc:
        QualityAnalyzer().analyze(row(srt_path=relative), tmp_path, reference)
    assert exc.value.reason == "reference too large"


def test_reference_is_ignored_when_the_row_has_no_transcript_text(tmp_path: Path) -> None:
    """A row with no comparable text keeps its own defect; no ratio is invented."""

    reference = tmp_path / "second.txt"
    reference.write_text("hello world\n", encoding="utf-8")

    result = QualityAnalyzer().analyze(
        row(srt_path="transcripts/srt/missing.p0.srt"), tmp_path, reference
    )
    assert result.reasons == ("artifact_missing",)
    assert result.reference is None
    assert result.content_reasons == ()


def test_reference_comparison_uses_the_transcript_not_the_md_bundle(
    tmp_path: Path,
) -> None:
    """The published ``.md`` bundle never stands in for the row's transcript.

    Its body is the transcript, but the bundle also carries the archive's own
    YAML frontmatter — title, bilibili URL, identity.  Comparing that metadata
    would fabricate a disagreeing reference against a transcript that matches.
    """

    relative = write_raw(
        tmp_path, "BV1demo.p0.json", [{"start": 0.0, "end": 4.0, "text": "你好世界"}]
    )
    # A bundle whose body is exactly the reference, frontmatter and all.
    md = tmp_path / "transcripts" / "md" / "2026-01-02_BV1demo.p0_demo.md"
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(
        '---\nbvid: "BV1demo"\ntitle: "demo"\n'
        'url: "https://www.bilibili.com/video/BV1demo"\n---\n\n你好世界\n',
        encoding="utf-8",
    )
    reference = tmp_path / "second.txt"
    reference.write_text("你好世界\n", encoding="utf-8")

    result = QualityAnalyzer().analyze(
        row(raw_path=relative, md_path="transcripts/md/" + md.name),
        tmp_path,
        reference,
    )
    assert result.reasons == ()
    assert result.reference is not None
    assert result.reference.agreement == 1.0
    assert result.reference.compared_chars == (4, 4)
    assert "reference_disagreement" not in result.content_reasons


def test_md_bundle_is_compared_by_its_body_when_it_is_the_only_source(
    tmp_path: Path,
) -> None:
    """The bundle stays usable as a transcript — without its frontmatter.

    With no SRT, TXT or cue sidecar in the row, the bundle is the last resort,
    so its comparison text must be the body it publishes and not its title,
    URL, or identity keys.
    """

    md = tmp_path / "transcripts" / "md" / "2026-01-02_BV1demo.p0_demo.md"
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(
        '---\nbvid: "BV1demo"\ntitle: "demo"\n'
        'url: "https://www.bilibili.com/video/BV1demo"\n---\n\n你好世界\n',
        encoding="utf-8",
    )
    reference = tmp_path / "second.txt"
    reference.write_text("你好世界\n", encoding="utf-8")

    result = QualityAnalyzer().analyze(
        row(md_path="transcripts/md/" + md.name), tmp_path, reference
    )
    assert result.reasons == ()
    assert result.reference is not None
    assert result.reference.agreement == 1.0
    assert "reference_disagreement" not in result.content_reasons


def test_md_bundle_never_marks_a_defect_free_row_as_disagreeing(
    tmp_path: Path,
) -> None:
    """A defect-free row whose SRT yields no text keeps its clean reason list.

    The row's SRT has one timed cue with empty text — a structural defect this
    module does not report — and the bundle beside it holds the reference text
    in its body.  Comparing the bundle's frontmatter would invent a
    ``reference_disagreement`` against a transcript the row does not contest.
    """

    relative = _transcript(tmp_path, "")
    md = tmp_path / "transcripts" / "md" / "2026-01-02_BV1demo.p0_demo.md"
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(
        '---\nbvid: "BV1demo"\ntitle: "demo"\n'
        'url: "https://www.bilibili.com/video/BV1demo"\n---\n\n你好世界\n',
        encoding="utf-8",
    )
    reference = tmp_path / "second.txt"
    reference.write_text("你好世界\n", encoding="utf-8")

    result = QualityAnalyzer().analyze(
        row(srt_path=relative, md_path="transcripts/md/" + md.name),
        tmp_path,
        reference,
    )
    assert result.reasons == ()
    assert result.reference is not None
    assert result.reference.agreement == 1.0
    assert result.content_reasons == ()


def test_frontmatter_free_plain_text_keeps_its_leading_line(tmp_path: Path) -> None:
    """Stripping frontmatter never eats transcript text that is not frontmatter.

    A leading ``---`` with no closing delimiter is text, not a metadata block.
    """

    txt_dir = tmp_path / "transcripts" / "txt"
    txt_dir.mkdir(parents=True, exist_ok=True)
    (txt_dir / "BV1demo.p0.txt").write_text(
        "---\n正文从这一行开始\n", encoding="utf-8"
    )
    reference = tmp_path / "second.txt"
    reference.write_text("---\n正文从这一行开始\n", encoding="utf-8")

    result = QualityAnalyzer().analyze(
        row(txt_path="transcripts/txt/BV1demo.p0.txt"), tmp_path, reference
    )
    assert result.reference is not None
    assert result.reference.agreement == 1.0


@pytest.mark.parametrize(
    "name,body",
    [
        ("bad.json", '{"segments": ['),
        ("empty_segments.json", '{"segments": []}'),
        ("bare_list.json", "[]"),
        ("blank.json", ""),
    ],
)
def test_reference_json_that_carries_no_transcript_is_refused(
    tmp_path: Path, name: str, body: str
) -> None:
    """A cue sidecar that does not parse, or has no segment, is unreadable.

    Comparing it as its own source text would report a fabricated near-zero
    ratio for a reference that never held a transcript.
    """

    relative = _transcript(tmp_path, "你好世界")
    reference = tmp_path / name
    reference.write_text(body, encoding="utf-8")

    with pytest.raises(ReferenceUnavailable) as exc:
        QualityAnalyzer().analyze(row(srt_path=relative), tmp_path, reference)
    assert exc.value.reason == "reference unreadable"


def test_reference_json_with_segments_still_compares(tmp_path: Path) -> None:
    """Refusing unreadable sidecars does not narrow the JSON arm."""

    relative = _transcript(tmp_path, "你好世界")
    reference = tmp_path / "second.json"
    reference.write_text(
        json.dumps({"segments": [{"start": 0.0, "end": 4.0, "text": "你好世界"}]}),
        encoding="utf-8",
    )

    result = QualityAnalyzer().analyze(row(srt_path=relative), tmp_path, reference)
    assert result.reference is not None
    assert result.reference.agreement == 1.0


def test_reference_agreement_exactly_at_the_floor_is_not_a_disagreement(
    tmp_path: Path,
) -> None:
    """D3.7: the reason fires *below* the floor, so equality does not fire it.

    The ratio is exact rather than approximate: 19 of 20 flattened characters
    shared, which ``SequenceMatcher`` reports as exactly ``0.95``.
    """

    relative = _transcript(tmp_path, "abcdefghijklmnopqrst")
    reference = tmp_path / "second.txt"
    reference.write_text("abcdefghijklmnopqrsX\n", encoding="utf-8")

    result = QualityAnalyzer().analyze(row(srt_path=relative), tmp_path, reference)
    assert result.reference is not None
    assert result.reference.agreement == REFERENCE_AGREEMENT_FLOOR == 0.95
    assert "reference_disagreement" not in result.content_reasons


def test_reference_agreement_floor_is_the_retired_scripts_figure() -> None:
    """The threshold is the retired script's ``~0.95``, declared in one place."""

    assert quality.REFERENCE_AGREEMENT_FLOOR == 0.95
