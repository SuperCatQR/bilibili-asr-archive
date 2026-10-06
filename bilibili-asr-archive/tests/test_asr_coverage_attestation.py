"""The coverage attestation: a partial model span cannot read as an unqualified success.

Offline by construction — no GPU, no network, no Bilibili credential.  The model seam is
``tests/_asr_fakes.py`` (the same four-object double every ASR suite drives) and the write path is
the real CLI, so what these tests read back is the row the archive actually recorded.

**Carrier (D11).**  The coverage fact rides the part's manifest row beside the existing outcome
vocabulary: ``decoded_s`` / ``produced_s`` / ``coverage`` / ``coverage_min``, plus the boolean
marker ``coverage_short``.  No new ``outcome`` and no new ``error_code`` — the existing CHECK
constraint and the Python guards refuse new values on every existing database, and no DDL is
available (``CREATE TABLE IF NOT EXISTS``, no in-place migration).

**Basis.**  The measured ``I-000188`` part: ``decoded_s = 73.561`` (3 244 032 samples @ 44.1 kHz,
re-sampled to 16 kHz) and ``produced_s = 59.0`` (cues 0.0–59.0 s) ⇒ ``coverage = 0.80204…``.
``COVERAGE_MIN = 0.97`` sits strictly between that and a correct run.
"""

from __future__ import annotations

import json
import os

import pytest

from bili_asr import asr
from bili_asr.cli import main
from bili_asr.manifest import ManifestStore
from bili_asr.page_identity import artifact_stem, page_identity

import _asr_fakes as asr_fakes

#: The measured basis (I-000188): 73.561 s decoded / 0.0–59.0 s produced.
DEFECT_DECODED_S = 73.561

#: The defect fixture: one 100-character utterance whose per-character step makes the aligner's
#: last unit end at 100 × 0.5905 − 0.05 = 59.0 s — the recorded span, not a rounded stand-in.
DEFECT_TEXT = "甲" * 100
DEFECT_STEP = 0.5905

#: The negative control: the same utterance shape covering 59.1 of 60.0 s decoded (0.985).
FULL_TEXT = "乙" * 100
FULL_STEP = 0.5915
FULL_DECODED_S = 60.0


def _seed_audio_ok_row(root, identity):
    """One ``audio_ok`` manifest row whose bytes are on disk — the state ``asr`` routes to ASR.

    The manifest source is pinned (``--queue-source manifest``) for the same reason
    ``tests/test_cli_asr.py`` pins it: this fixture drives the manifest-state route, and the
    evidence write-back is shared with the store route below the selection.
    """

    store = ManifestStore(root=root)
    row = {
        "bvid": identity.bvid,
        "work_id": identity.work_id,
        "page_index": identity.page_index,
        "cid": identity.cid,
        "page_label": identity.page_label,
        "status": "audio_ok",
        "title": "clip",
        "duration_s": 74,
        "pubdate": 1,
        "pubdate_str": "2026-01-02",
        "audio_path": f"audio/{artifact_stem(identity)}.m4a",
    }
    store.upsert(row)
    audio_dir = os.path.join(root, "audio")
    os.makedirs(audio_dir, exist_ok=True)
    with open(os.path.join(audio_dir, f"{artifact_stem(identity)}.m4a"), "wb") as fh:
        fh.write(b"\x00" * 16)


def _recorded_row(root, work_id: str) -> dict:
    """The row as the archive persists it — read from the manifest JSONL, not from memory.

    AC1's hard condition (a): the evidence must be readable from the archive itself, so this
    helper deliberately bypasses ``ManifestStore`` and parses the written file.
    """

    path = os.path.join(root, "manifest", "manifest.jsonl")
    with open(path, encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    matching = [row for row in rows if (row.get("work_id") or row.get("bvid")) == work_id]
    assert matching, f"no manifest row for {work_id!r} in {path}"
    return matching[-1]


def _cover(monkeypatch, *, text: str, step: float, seconds: float) -> None:
    """Install the fake seam with a span the test chose, not one the default step happens to give."""

    fakes = asr_fakes.install(monkeypatch, text=text, seconds=seconds)
    fakes.aligner_processor.units = asr_fakes.units_for(text, step=step)


def test_a_partial_model_span_is_flagged_short_on_the_recorded_row(
    tmp_root, monkeypatch, capsys
):
    """The defect case at the measured basis: full decode, model covers 0.802 of it.

    ``I-000188`` archived a part this way with ``outcome=stored``, a complete bundle and no
    warning.  The row must now carry the comparison that says otherwise.
    """

    identity = page_identity("BVshort", 0, 41, "p0")
    _seed_audio_ok_row(tmp_root, identity)
    _cover(monkeypatch, text=DEFECT_TEXT, step=DEFECT_STEP, seconds=DEFECT_DECODED_S)

    rc = main(["asr", "--pending", "--queue-source", "manifest", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 0, captured.err

    row = _recorded_row(tmp_root, identity.work_id)
    assert row["status"] == "archived"
    decoded = row.get("decoded_s")
    produced = row.get("produced_s")
    coverage = row.get("coverage")
    assert isinstance(decoded, float), f"decoded_s missing from the row: {sorted(row)}"
    assert isinstance(produced, float), f"produced_s missing from the row: {sorted(row)}"
    assert isinstance(coverage, float), f"coverage missing from the row: {sorted(row)}"
    assert decoded == pytest.approx(DEFECT_DECODED_S), "the measured decode length is the denominator"
    assert produced == pytest.approx(59.0, abs=1e-6), "the measured span is the numerator"
    assert coverage == pytest.approx(0.80206, abs=1e-4), (
        "coverage must report the measured basis (73.561 s decoded / 59.0 s produced)"
    )
    assert coverage == pytest.approx(produced / decoded), "coverage is compared unrounded"
    assert row.get("coverage_min") == asr.COVERAGE_MIN
    assert row.get("coverage_short") is True, "a 0.802 span must not read as an unqualified success"
    # The existing outcome vocabulary is untouched: no new outcome, no new error_code.
    assert row.get("error_code") is None
    assert row["status"] == "archived"


def test_a_fully_covering_run_is_not_flagged(tmp_root, monkeypatch, capsys):
    """The anti-"always alarm" control: a run covering 0.985 of its decode stays clean."""

    identity = page_identity("BVfull", 0, 42, "p0")
    _seed_audio_ok_row(tmp_root, identity)
    _cover(monkeypatch, text=FULL_TEXT, step=FULL_STEP, seconds=FULL_DECODED_S)

    rc = main(["asr", "--pending", "--queue-source", "manifest", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 0, captured.err

    row = _recorded_row(tmp_root, identity.work_id)
    assert row["status"] == "archived"
    coverage = row.get("coverage")
    assert isinstance(coverage, float), f"coverage missing from the row: {sorted(row)}"
    assert coverage == pytest.approx(0.985, abs=1e-4)
    assert row.get("coverage_short") is False
    assert row.get("error_code") is None


def test_the_coordinator_route_carries_the_same_evidence(tmp_root, monkeypatch, capsys):
    """The ``run`` path is a second writer of the same row; it must carry the same evidence."""

    identity = page_identity("BVcoord", 0, 43, "p0")
    _seed_audio_ok_row(tmp_root, identity)
    _cover(monkeypatch, text=DEFECT_TEXT, step=DEFECT_STEP, seconds=DEFECT_DECODED_S)

    rc = main([
        "run", "--scope", "pending", "--queue-source", "manifest", "--offline",
        "--archive-root", tmp_root,
    ])
    captured = capsys.readouterr()
    assert rc == 0, captured.err

    row = _recorded_row(tmp_root, identity.work_id)
    assert row["status"] == "archived"
    assert row.get("coverage") == pytest.approx(0.80206, abs=1e-4), sorted(row)
    assert row.get("coverage_short") is True


def test_an_untranscribed_chunk_still_counts_in_the_denominator(
    tmp_root, monkeypatch, capsys
):
    """The plan's named silent point: ``if not text: continue`` drops a chunk with no record.

    Two chunks, one second each; the model returns text for the first only.  The decoded duration
    is still the whole 2 s — the dropped chunk is *in* the denominator, which is what makes the
    drop visible at all — and the resulting coverage is 0.5.
    """

    identity = page_identity("BVdrop", 0, 44, "p0")
    _seed_audio_ok_row(tmp_root, identity)
    # A 1 s cap makes the 2 s recording two chunks, so the drop branch is reachable at all.
    monkeypatch.setenv("BILI_ASR_CHUNK_SECONDS", "1.0")
    fakes = asr_fakes.install(monkeypatch, text="丙" * 6, seconds=2.0)
    # The kept chunk's units: six characters at a 0.16 s step, so its span ends at 0.91 s of the
    # 1 s it was given.  The second chunk returns no text at all.
    fakes.aligner_processor.units = asr_fakes.units_for("丙" * 6, step=0.16)
    calls: list[int] = []
    real = fakes.processor.apply_transcription_request

    def first_chunk_only(*args, **kwargs):
        calls.append(1)
        fakes.processor.text = "丙" * 6 if len(calls) == 1 else ""
        return real(*args, **kwargs)

    monkeypatch.setattr(fakes.processor, "apply_transcription_request", first_chunk_only)

    rc = main([
        "asr", "--pending", "--queue-source", "manifest", "--archive-root", tmp_root,
    ])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert len(calls) == 2, "the recording must split into two chunks for this witness"

    row = _recorded_row(tmp_root, identity.work_id)
    assert row["decoded_s"] == pytest.approx(2.0), "the dropped chunk is inside the denominator"
    assert row["produced_s"] == pytest.approx(0.91)
    assert row["coverage"] == pytest.approx(0.455)
    assert row["coverage_short"] is True


def test_a_short_decode_is_out_of_scope_and_says_so_as_much(
    tmp_root, monkeypatch, capsys
):
    """The documented limitation, asserted **separately** so it is not conflated with this fix.

    ``asr.py``'s ``AudioDecodeError`` docstring records that a download truncated in the middle
    decodes **silently short**: nothing compares the decoded duration with the row's
    ``duration_s``, so 30 % of the bytes decode to 30 % of the seconds and the row still archives.
    This witness does *not* claim to catch that: a truncated decode tiles exactly and the model
    covers all of it, so ``coverage`` is 1.0 and the row is clean.  What is left is a row whose
    ``decoded_s`` contradicts the ``duration_s`` the archive already held — the two numbers are
    both on the record, so the contradiction is *readable*, but nothing acts on it and this fix
    deliberately does not start: download truncation is a different defect with a different
    owner.
    """

    identity = page_identity("BVtrunc", 0, 45, "p0")
    _seed_audio_ok_row(tmp_root, identity)  # the row declares duration_s = 74
    # 100 units ending at 9.95 s: the model covers every second the truncated decode offered.
    _cover(monkeypatch, text="丁" * 100, step=0.1, seconds=10.0)

    rc = main([
        "asr", "--pending", "--queue-source", "manifest", "--archive-root", tmp_root,
    ])
    captured = capsys.readouterr()
    assert rc == 0, captured.err

    row = _recorded_row(tmp_root, identity.work_id)
    assert row["decoded_s"] == pytest.approx(10.0), "the truncated decode is what was measured"
    assert row["coverage"] == pytest.approx(0.995, abs=1e-3)
    assert row["coverage_short"] is False, (
        "model coverage is complete; the loss is in the decode, which this fix does not claim"
    )
    assert row["duration_s"] == 74, "the container/row duration is untouched and still disagrees"


def test_missing_evidence_is_not_read_as_no_gap():
    """AC1's condition (c): a record without the field is *not evaluable*, never clean.

    This is the read-only half of the rule: stock rows written before the measurement existed
    carry no ``coverage``, and a reader that treats the absent boolean as ``False`` would call
    every one of them fine — the exact illusion this plan removes.
    """

    legacy = {"work_id": "BVlegacy:p0", "bvid": "BVlegacy", "status": "archived"}
    assert asr.coverage_verdict(legacy) == "not-evaluable"
    assert asr.coverage_verdict(dict(legacy, coverage=0.985)) == "covered"
    assert asr.coverage_verdict(dict(legacy, coverage=0.80204)) == "short"


def test_the_threshold_boundary_is_strict_and_compared_unrounded():
    """``coverage < COVERAGE_MIN`` strictly: the boundary itself is covered."""

    at = asr._coverage_record(100.0, [{"start": 0.0, "end": 97.0}])
    assert at["coverage"] == asr.COVERAGE_MIN
    assert at["coverage_short"] is False

    below = asr._coverage_record(100.0, [{"start": 0.0, "end": 96.99}])
    assert below["coverage_short"] is True


def test_alignment_span_overrun_is_bounded_to_decoded_audio():
    """An aligner overrun cannot make the coverage record invalid."""

    record = asr._coverage_record(3.0, [{"start": 0.0, "end": 4.0}])

    assert record["decoded_s"] == 3.0
    assert record["produced_s"] == 3.0
    assert record["coverage"] == 1.0
    assert record["coverage_short"] is False


def test_a_rerun_recomputes_and_a_no_decode_run_claims_nothing(tmp_root, monkeypatch, capsys):
    """Rules 5/6: a re-run never copies a prior ``coverage``; no decode makes no claim.

    Both branches of :func:`asr.apply_coverage_evidence` are pinned here, because both writers
    (``asr``/``pilot``, and the coordinator) go through it.
    """

    stale = {
        "work_id": "BVrelay:p0", "bvid": "BVrelay", "status": "archived",
        "decoded_s": 1.0, "produced_s": 1.0, "coverage": 0.99, "coverage_min": 0.97,
        "coverage_short": False,
    }

    # A run that decoded nothing makes no coverage claim at all — and must not leave the prior
    # row's numbers standing as if they described this run.
    empty = asr_fakes.install(monkeypatch, seconds=0.0)
    runner = asr.ASRRunner(asr.default_config())
    assert runner.transcribe("/nonexistent/empty.wav") == []
    assert runner.transcribed_coverage() is None
    entry = dict(stale)
    asr.apply_coverage_evidence(entry, runner)
    assert not set(asr.COVERAGE_KEYS) & set(entry), sorted(entry)

    # A re-run recomputes from its own decode: the stale success is replaced by the fresh
    # measurement, which here is a shortfall.
    _cover(monkeypatch, text=DEFECT_TEXT, step=DEFECT_STEP, seconds=DEFECT_DECODED_S)
    runner = asr.ASRRunner(asr.default_config())
    runner.transcribe("/nonexistent/again.wav")
    entry = dict(stale)
    asr.apply_coverage_evidence(entry, runner)
    assert entry["coverage"] == pytest.approx(0.80206, abs=1e-4)
    assert entry["coverage_short"] is True


def test_the_published_bundle_carries_the_same_attestation(tmp_root, monkeypatch, capsys):
    """AC1's other named surface: the signal is visible *in the bundle*, not only in the store.

    The acceptance reads "visible in the store and in the bundle", so a reader holding only the
    published artefact must be able to see the shortfall without opening the store.  The span the
    model produced against the span it decoded rides the ``.md`` frontmatter as ``coverage_*`` and
    the raw sidecar as a ``coverage`` object.
    """

    identity = page_identity("BVbundle", 0, 42, "p0")
    _seed_audio_ok_row(tmp_root, identity)
    _cover(monkeypatch, text=DEFECT_TEXT, step=DEFECT_STEP, seconds=DEFECT_DECODED_S)

    rc = main(["asr", "--pending", "--queue-source", "manifest", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 0, captured.err

    row = _recorded_row(tmp_root, identity.work_id)
    md_path = os.path.join(tmp_root, row["md_path"])
    raw_path = os.path.join(tmp_root, row["raw_path"])

    with open(md_path, encoding="utf-8") as fh:
        body = fh.read()
    frontmatter = body.split("---", 2)[1]
    # The attestation is present and self-describing in the published text.  Keys are prefixed
    # with `coverage_` over the record's own names, so the ratio is `coverage_coverage`.
    assert "coverage_coverage_short: true" in frontmatter, (
        "the bundle must itself say the run fell short:\n" + frontmatter
    )
    assert f"coverage_coverage_min: {asr.COVERAGE_MIN}" in frontmatter, frontmatter
    assert "coverage_coverage: 0.802" in frontmatter, (
        "the bundle carries the measured ratio, not a rounded stand-in:\n" + frontmatter
    )
    assert "coverage_decoded_s: 73.561" in frontmatter, frontmatter

    with open(raw_path, encoding="utf-8") as fh:
        raw = json.load(fh)
    measured = raw["coverage"]
    assert measured["decoded_s"] == pytest.approx(DEFECT_DECODED_S)
    assert measured["produced_s"] == pytest.approx(59.0, abs=1e-6)
    assert measured["coverage"] == pytest.approx(0.80206, abs=1e-4)
    assert measured["coverage_short"] is True

    # The published frontmatter and the sidecar carry the same measurement.  The `asr_*`
    # provenance and the VAD capture summary beside them are untouched by this change, which the
    # existing asr/archive suites pin; this test owns only the coverage surface.
    assert measured["coverage_min"] == asr.COVERAGE_MIN


def test_a_path_with_no_measurement_publishes_no_coverage_keys(tmp_root, monkeypatch, capsys):
    """The subtitle route has no decode to compare, so it claims nothing.

    A bundle that invented a ``coverage`` for a caption-derived transcript would be asserting a
    measurement nobody made — the same class of error as reading an absent record as "covered".
    """

    from bili_asr import archive as archive_module

    entry = {"bvid": "BVsub", "title": "t", "duration_s": 10, "pubdate_str": "2026-01-02"}
    segments = [{"start": 0.0, "end": 1.0, "text": "hello"}]
    paths = archive_module.write_archive(tmp_root, entry, segments, source="subtitle")
    with open(os.path.join(tmp_root, paths["md_path"]), encoding="utf-8") as fh:
        frontmatter = fh.read().split("---", 2)[1]
    assert "coverage" not in frontmatter, frontmatter
    with open(os.path.join(tmp_root, paths["raw_path"]), encoding="utf-8") as fh:
        assert "coverage" not in json.load(fh)
