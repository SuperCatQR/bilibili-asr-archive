"""A manifest-era bundle can converge store queues without decoding its audio."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys

import pytest

from bili_asr import archive, cli
from bili_asr.manifest import ManifestStore
from bili_asr.services.queue_source import QueueSource
from bili_asr.services.transcript_adoption import AdoptionRefused, read_archived_transcript
from bili_asr.storage import MetadataRepository, MediaQueueRepository, TranscriptRepository, open_database
from fixtures.metadata_records import make_part_record, make_user_record, make_video_record


def _seed(root, *, page=0, cid=3001):
    connection = open_database(root)
    metadata = MetadataRepository(connection)
    with metadata.transaction():
        metadata.upsert_user(make_user_record())
        metadata.upsert_video(make_video_record("BV1ADOPT", aid=None))
        metadata.upsert_part(replace(make_part_record("BV1ADOPT", page_index=page, cid=cid), duration_ms=8000))
    MediaQueueRepository(connection).mark_audio_acquired(
        bvid="BV1ADOPT", page_index=page, audio_path=f"audio/BV1ADOPT.p{page}.m4a",
        sha256="a" * 64, byte_size=4096, format="m4a", duration_ms=8000,
        acquisition_source="download", acquired_at=500,
    )
    return connection


def _bundle(root, *, page=0, cid=3001, source="asr", segments=None, provenance=None, title="Already archived"):
    row = {
        "work_id": f"BV1ADOPT:p{page}", "bvid": "BV1ADOPT", "page_index": page,
        "cid": cid, "title": title, "duration_s": 8, "status": "archived",
        "source": source, "language": "Chinese",
    }
    segments = segments or [{"start": 0.001, "end": 4.567, "text": "A saved transcript"}]
    paths = archive.write_archive(
        root, row, segments, source=source,
        asr_provenance=provenance or {"model_name": "Qwen/Qwen3-ASR-0.6B", "model_revision": "rev123", "language": "Chinese"},
    )
    row.update(paths)
    ManifestStore(root=root).upsert(row)
    return row


def _part(connection):
    return dict(connection.execute("SELECT work_id, video_part_id, cid FROM v_video_parts").fetchone())


def _rehash(root, row):
    marker_path = Path(root) / Path(row["srt_path"]).parent / ".bundle-ready"
    marker = json.loads(marker_path.read_text(encoding="ascii"))
    for key, item in marker["artifacts"].items():
        item["sha256"] = hashlib.sha256((Path(root) / row[key]).read_bytes()).hexdigest()
    marker_path.write_text(json.dumps(marker), encoding="ascii")


def test_adopt_converges_store_queue_and_is_idempotent_without_asr(tmp_root, monkeypatch, capsys):
    connection = _seed(tmp_root)
    row = _bundle(tmp_root)
    before = (Path(tmp_root) / row["raw_path"]).read_bytes()
    monkeypatch.setattr("bili_asr.asr.ASRRunner", lambda *a, **kw: pytest.fail("adoption ran ASR"))
    try:
        assert QueueSource(connection).select_transcript_queue().entries
        assert cli.main(["adopt-transcripts", "--archive-root", tmp_root]) == 0
        assert not QueueSource(connection).select_transcript_queue().entries
        record = TranscriptRepository(connection).read_transcript(_part(connection)["video_part_id"], "asr-local", "Chinese")
        assert record.segments[0].start_ms == 1
        assert record.segments[0].end_ms == 4567
        assert record.segments[0].text == "A saved transcript"
        assert tuple(connection.execute("SELECT model_name, revision FROM asr_models").fetchone()) == ("Qwen/Qwen3-ASR-0.6B", "rev123")
        assert cli.main(["adopt-transcripts", "--archive-root", tmp_root]) == 0
        assert connection.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM acquisition_runs").fetchone()[0] == 1
        assert connection.execute("SELECT outcome FROM acquisition_runs").fetchone()[0] == "complete"
        assert (Path(tmp_root) / row["raw_path"]).read_bytes() == before
        assert "adopted=1" in capsys.readouterr().out
    finally:
        connection.close()


def test_repeated_limited_adoption_advances_past_previously_stored_parts(tmp_root, capsys):
    connection = _seed(tmp_root)
    try:
        _seed(tmp_root, page=1, cid=3002).close()
        _bundle(tmp_root)
        _bundle(tmp_root, page=1, cid=3002)
        arguments = ["adopt-transcripts", "--archive-root", tmp_root, "--limit-parts", "1"]

        assert cli.main(arguments) == 0
        assert connection.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0] == 1
        assert "adopted=1 already_stored=0 refused=0" in capsys.readouterr().out

        assert cli.main(arguments) == 0
        assert connection.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0] == 2
        assert "adopted=1 already_stored=1 refused=0" in capsys.readouterr().out
        assert not QueueSource(connection).select_transcript_queue().entries

        assert cli.main(arguments) == 0
        assert "adopted=0 already_stored=2 refused=0" in capsys.readouterr().out
        assert connection.execute("SELECT COUNT(*) FROM acquisition_runs").fetchone()[0] == 2
    finally:
        connection.close()


@pytest.mark.parametrize("key,value", [("cid", 9999), ("page_index", 1), ("bvid", "BVOTHER"), ("unresolved", True)])
def test_manifest_identity_never_attributes_to_another_part(tmp_root, key, value):
    connection = _seed(tmp_root)
    try:
        row = _bundle(tmp_root)
        row[key] = value
        with pytest.raises(AdoptionRefused, match="manifest_identity"):
            read_archived_transcript(row, _part(connection), tmp_root)
        assert connection.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0] == 0
    finally:
        connection.close()


@pytest.mark.parametrize("defect,reason", [
    ("hash", "bundle_digest_mismatch"), ("marker", "bundle_unreadable"),
    ("metadata_identity", "bundle_identity_mismatch"), ("text", "bundle_content_mismatch"),
    ("source", "bundle_source_mismatch"), ("raw_type", "raw_invalid"),
    ("raw_nesting", "raw_invalid|bundle_invalid"), ("provenance", "bundle_provenance_mismatch"),
])
def test_bundle_refusals_preserve_the_store_gap(tmp_root, defect, reason):
    connection = _seed(tmp_root)
    try:
        row = _bundle(tmp_root)
        raw_path = Path(tmp_root) / row["raw_path"]
        if defect == "hash":
            raw_path.write_text("{}", encoding="utf-8")
        elif defect == "marker":
            (Path(tmp_root) / Path(row["srt_path"]).parent / ".bundle-ready").unlink()
        elif defect == "metadata_identity":
            path = Path(tmp_root) / row["md_path"]
            path.write_text(path.read_text(encoding="utf-8").replace("cid: 3001", "cid: 9999"), encoding="utf-8")
            _rehash(tmp_root, row)
        elif defect == "text":
            (Path(tmp_root) / row["txt_path"]).write_text("Different saved transcript\n", encoding="utf-8")
            _rehash(tmp_root, row)
        elif defect == "raw_nesting":
            depth = sys.getrecursionlimit() + 100
            raw_path.write_text("[" * depth + "0" + "]" * depth, encoding="utf-8")
            _rehash(tmp_root, row)
        else:
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            if defect == "source":
                raw["source"] = "subtitle"
            elif defect == "provenance":
                raw["provenance"]["model_name"] = "another-model"
            else:
                raw["segments"][0]["start"] = True
            raw_path.write_text(json.dumps(raw), encoding="utf-8")
            _rehash(tmp_root, row)
        with pytest.raises(AdoptionRefused, match=reason):
            read_archived_transcript(row, _part(connection), tmp_root)
        assert cli.main(["adopt-transcripts", "--archive-root", tmp_root]) == 1
        assert QueueSource(connection).select_transcript_queue().entries
        assert connection.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0] == 0
    finally:
        connection.close()


def test_adopt_reads_configured_artifact_base_and_legacy_archive_fallback(tmp_root, tmp_path):
    connection = _seed(tmp_root)
    try:
        row = _bundle(tmp_root)
        # A configured base that lacks this complete bundle must not hide the
        # already-published one at the former base.
        assert cli.main(["adopt-transcripts", "--archive-root", tmp_root, "--artifact-root", str(tmp_path)]) == 0
        assert not QueueSource(connection).select_transcript_queue().entries
        assert (Path(tmp_root) / row["raw_path"]).exists()
    finally:
        connection.close()


def test_adopt_caption_uses_track_kind_and_language(tmp_root):
    connection = _seed(tmp_root)
    try:
        row = _bundle(tmp_root, source="subtitle")
        row["sub_lan"] = "ai-zh"
        ManifestStore(root=tmp_root).upsert(row)
        assert cli.main(["adopt-transcripts", "--archive-root", tmp_root]) == 0
        record = TranscriptRepository(connection).read_transcript(_part(connection)["video_part_id"], "subtitle-ai", "ai-zh")
        assert record is not None
        assert connection.execute("SELECT kind FROM acquisition_runs").fetchone()[0] == "subtitle"
    finally:
        connection.close()


def test_adoption_preserves_valid_unicode_line_separator_in_metadata(tmp_root):
    connection = _seed(tmp_root)
    try:
        _bundle(tmp_root, title="One\u2028Two")
        assert cli.main(["adopt-transcripts", "--archive-root", tmp_root]) == 0
        assert not QueueSource(connection).select_transcript_queue().entries
    finally:
        connection.close()


def test_adopt_prior_four_directory_bundle_without_republishing(tmp_root):
    connection = _seed(tmp_root)
    try:
        row = _bundle(tmp_root)
        old_paths = {
            "srt_path": "transcripts/srt/BV1ADOPT.p0.srt",
            "txt_path": "transcripts/txt/BV1ADOPT.p0.txt",
            "md_path": "transcripts/md/2026-09-01_BV1ADOPT.p0_saved.md",
            "raw_path": "transcripts/raw/BV1ADOPT.p0.json",
        }
        for key, relative in old_paths.items():
            target = Path(tmp_root) / relative
            target.parent.mkdir(exist_ok=True)
            target.write_bytes((Path(tmp_root) / row[key]).read_bytes())
        marker = {
            "schema": "archive-bundle-v1",
            "artifacts": {
                key: {"path": relative, "sha256": hashlib.sha256((Path(tmp_root) / relative).read_bytes()).hexdigest()}
                for key, relative in old_paths.items()
            },
        }
        (Path(tmp_root) / (old_paths["srt_path"] + ".bundle-ready")).write_text(json.dumps(marker), encoding="ascii")
        row.update(old_paths)
        ManifestStore(root=tmp_root).upsert(row)
        assert cli.main(["adopt-transcripts", "--archive-root", tmp_root]) == 0
        assert not QueueSource(connection).select_transcript_queue().entries
    finally:
        connection.close()


def test_adopt_does_not_truncate_a_long_transcript_at_reader_report_cap(tmp_root):
    connection = _seed(tmp_root)
    try:
        row = _bundle(tmp_root, segments=[{"start": i * 2, "end": i * 2 + 1, "text": f"cue {i}"} for i in range(10001)])
        adopted = read_archived_transcript(row, _part(connection), tmp_root)
        assert len(adopted.segments) == 10001
        assert adopted.segments[-1].text == "cue 10000"
    finally:
        connection.close()


@pytest.mark.parametrize("flag,value", [("--limit-parts", "0"), ("--bvid", "BVUNKNOWN")])
def test_adopt_usage_errors_do_not_write_transcript_evidence(tmp_root, flag, value):
    connection = _seed(tmp_root)
    try:
        _bundle(tmp_root)
        assert cli.main(["adopt-transcripts", "--archive-root", tmp_root, flag, value]) == 1
        assert connection.execute("SELECT COUNT(*) FROM acquisition_runs").fetchone()[0] == 0
    finally:
        connection.close()


def test_store_failure_can_retry_the_complete_archive_without_asr(tmp_root, monkeypatch):
    connection = _seed(tmp_root)
    try:
        _bundle(tmp_root)
        with monkeypatch.context() as patches:
            patches.setattr(TranscriptRepository, "record_local_transcript", lambda *a, **kw: (_ for _ in ()).throw(ValueError("injected store failure")))
            assert cli.main(["adopt-transcripts", "--archive-root", tmp_root]) == 1
        assert connection.execute("SELECT outcome FROM acquisition_runs").fetchone()[0] == "failed"
        assert QueueSource(connection).select_transcript_queue().entries
        assert cli.main(["adopt-transcripts", "--archive-root", tmp_root]) == 0
        assert not QueueSource(connection).select_transcript_queue().entries
    finally:
        connection.close()


def test_interrupted_adoption_closes_its_running_process_record(tmp_root, monkeypatch):
    connection = _seed(tmp_root)
    try:
        _bundle(tmp_root)
        def interrupt(*args, **kwargs):
            raise KeyboardInterrupt
        monkeypatch.setattr(TranscriptRepository, "record_local_transcript", interrupt)
        with pytest.raises(KeyboardInterrupt):
            cli.main(["adopt-transcripts", "--archive-root", tmp_root])
        assert connection.execute("SELECT outcome FROM acquisition_runs").fetchone()[0] == "failed"
        assert QueueSource(connection).select_transcript_queue().entries
    finally:
        connection.close()


def test_adoption_preserves_run_coverage_evidence(tmp_root):
    connection = _seed(tmp_root)
    try:
        row = _bundle(tmp_root)
        raw_path = Path(tmp_root) / row["raw_path"]
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        raw["coverage"] = {"decoded_s": 8.0, "produced_s": 4.0, "coverage": 0.5, "coverage_min": 0.9, "coverage_short": True}
        raw_path.write_text(json.dumps(raw), encoding="utf-8")
        _rehash(tmp_root, row)
        assert cli.main(["adopt-transcripts", "--archive-root", tmp_root]) == 0
        run_id = connection.execute("SELECT run_id FROM acquisition_runs").fetchone()[0]
        evidence = TranscriptRepository(connection).read_transcript_coverage(run_id, _part(connection)["video_part_id"])
        assert evidence["coverage"] == 0.5
        assert evidence["coverage_short"] == 1
    finally:
        connection.close()


def test_adoption_refuses_oversized_artifact_instead_of_truncating(tmp_root, monkeypatch):
    connection = _seed(tmp_root)
    try:
        row = _bundle(tmp_root)
        # Lower the bound to make the same file-size refusal inexpensive to test.
        from bili_asr.services import transcript_adoption as service
        original = service._read_confined
        monkeypatch.setattr(service, "_read_confined", lambda root, relative, limit=64: original(root, relative, limit))
        with pytest.raises(AdoptionRefused, match="bundle_oversized"):
            read_archived_transcript(row, _part(connection), tmp_root)
    finally:
        connection.close()


def test_adoption_refuses_symlinked_raw_artifact(tmp_root, tmp_path):
    connection = _seed(tmp_root)
    try:
        row = _bundle(tmp_root)
        target = Path(tmp_root) / row["raw_path"]
        original = target.read_bytes()
        outside = tmp_path / "external.json"
        outside.write_bytes(original)
        target.unlink()
        try:
            target.symlink_to(outside)
        except OSError:
            pytest.skip("symlink creation is not available")
        with pytest.raises(AdoptionRefused, match="bundle_unreadable|unsafe_bundle_path"):
            read_archived_transcript(row, _part(connection), tmp_root)
        assert outside.read_bytes() == original
    finally:
        connection.close()
