"""Fault injection and published-transcript accounting regressions."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bili_asr import archive, quality
from bili_asr.cli.main import main
from bili_asr.manifest import ManifestStore
from bili_asr.page_identity import page_identity
from bili_asr.services.manifest_derivation import derive_rows
from bili_asr.storage import MediaQueueRepository, open_database

from tests.support.coordinator import _row
from tests.support.manifest_derivation import _part, PUBDATE


@pytest.mark.parametrize("failure", ["snapshot", "journal-discard"])
def test_explicit_save_replays_requested_state_after_crash(tmp_root, monkeypatch, failure):
    identity = page_identity("BVcrash", 0, 1)
    store = ManifestStore(root=tmp_root)
    initial = _row(identity, status="meta_ok")
    store.save({identity.work_id: initial})
    store.upsert({**initial, "status": "audio_ok"})
    requested = {**initial, "status": "archived"}

    def crash(*args, **kwargs):
        raise OSError("simulated crash")

    target = "_replace_snapshot" if failure == "snapshot" else "_remove_journal"
    monkeypatch.setattr(store, target, crash)
    with pytest.raises(OSError, match="simulated crash"):
        store.save({identity.work_id: requested})
    fresh = ManifestStore(root=tmp_root)
    assert fresh.load()[identity.work_id]["status"] == "archived"
    fresh.save()
    assert ManifestStore(root=tmp_root).get(identity.work_id)["status"] == "archived"


def test_corrupt_utf8_cannot_be_rewritten_as_a_substituted_identity(tmp_root):
    journal = Path(tmp_root, "manifest", "manifest.journal.jsonl")
    journal.parent.mkdir(parents=True, exist_ok=True)
    payload = b'{"bvid":"BVbad","work_id":"BVbad\xff:p0","status":"audio_ok"}\n'
    journal.write_bytes(payload)
    store = ManifestStore(root=tmp_root)
    with pytest.raises(UnicodeDecodeError):
        store.load()
    with pytest.raises(UnicodeDecodeError):
        store.save()
    assert journal.read_bytes() == payload
    assert not Path(store.path).exists()


def test_published_quality_counts_each_stored_segment_once(tmp_root):
    identity = page_identity("BVcount", 0, 1)
    row = _row(identity, status="archived")
    row["source"] = "asr"
    segments = [{"start": i, "end": i + 0.8, "text": "计数测试"} for i in range(3)]
    row.update(archive.write_archive(tmp_root, row, segments, source="asr"))
    result = quality.QualityAnalyzer().analyze(row, Path(tmp_root))
    assert result.artifact_count == 4
    assert result.cue_count == len(segments)
    raw = json.loads(Path(tmp_root, row["raw_path"]).read_text())
    assert result.cue_count == len(raw["segments"])


def test_character_sidecar_is_compact_and_preserves_exact_timings(tmp_root):
    identity = page_identity("BVcompact", 0, 1)
    row = _row(identity, status="archived")
    text = "甲" * 1000
    segments = [{"start": 0, "end": 2, "text": text}]
    characters = {"text": text, "starts": [i / 1000 for i in range(1000)], "ends": [(i + 1) / 1000 for i in range(1000)]}
    paths = archive.write_archive(tmp_root, row, segments, source="asr", characters=characters)
    encoded = Path(tmp_root, paths["raw_path"]).read_text()
    raw = json.loads(encoded)
    assert raw["characters"] == characters
    pretty = json.dumps(raw, ensure_ascii=False, indent=2) + "\n"
    assert len(encoded.encode()) < len(pretty.encode()) * 0.65


@pytest.mark.parametrize("option", ["--asr-root", "--caption-root"])
@pytest.mark.parametrize("value", ["", "   "])
def test_proofread_cli_refuses_empty_input_roots(tmp_root, capsys, option, value):
    assert main(["proofread", "--bvid", "BVempty:p0", "--archive-root", tmp_root, option, value]) == 1
    assert "must name a non-empty directory" in capsys.readouterr().err
    assert not Path(tmp_root, ".tmp", "proofread-work").exists()


def test_legacy_archive_ownership_prevents_derived_redownload():
    part = _part()
    legacy = {part["bvid"]: {"bvid": part["bvid"], "status": "archived"}}
    result = derive_rows([part], {part["bvid"]: PUBDATE}, legacy)
    assert result.appended == ()
    assert result.chain_owned == (part["work_id"],)


def test_invalid_transcript_write_is_validated_before_part_lookup(tmp_root):
    connection = open_database(tmp_root)
    try:
        repository = MediaQueueRepository(connection)
        with pytest.raises(TypeError, match="transcript_id"):
            repository.mark_transcript_stored(
                bvid="BVabsent", page_index=0, transcript_id=True,
                run_id="absent", started_at=0, finished_at=1,
            )
    finally:
        connection.close()


@pytest.mark.parametrize("document", [[], {"source": "subtitle", "segments": [{"start": 0, "end": 1, "text": "另一条路线"}]}])
def test_asr_quality_rejects_unattributed_or_caption_sidecar(tmp_path, document):
    raw = tmp_path / "bundle.raw.json"
    raw.write_text(json.dumps(document), encoding="utf-8")
    result = quality.QualityAnalyzer().analyze(
        {"bvid": "BVshape", "status": "archived", "source": "asr", "raw_path": raw.name}, tmp_path,
    )
    assert "malformed" in result.reasons
    assert "source_mismatch" in result.diagnostics


def test_long_reference_samples_endpoints_and_reports_its_scope(tmp_path):
    text = "abcdef" * 4000
    reference = tmp_path / "reference.txt"
    reference.write_text(text)
    result = quality._compare_reference(reference, text)
    assert result.agreement == 1.0
    assert result.method == "windowed"
    assert result.total_chars == (len(text), len(text))
    assert result.compared_chars == (20000, 20000)
    assert result.windows[0][:2] == (0, 2000)
    assert result.windows[-1][1] == len(text)
    reference.write_text("z" * len(text))
    assert quality._compare_reference(reference, text).agreement == 0.0


def test_retryable_quality_diagnostics_follow_the_backlog_exit_policy(tmp_root, monkeypatch, capsys):
    identity = page_identity("BVbacklog", 0, 1)
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(identity, status="needs_audio"))
    store.compact()
    result = quality.QualityResult(
        source=None, language=None, status="needs_audio", cue_count=0,
        artifact_count=0, reasons=("artifact_missing",), diagnostics=("retryable_attempt",),
    )
    monkeypatch.setattr(quality.QualityAnalyzer, "analyze", lambda *args, **kwargs: result)
    argv = ["coverage", "--quality", "--archive-root", tmp_root, "--format", "json"]
    assert main(argv) == 0
    assert main(argv + ["--strict"]) == 1
