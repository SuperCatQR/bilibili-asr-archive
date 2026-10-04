"""Audio pipeline regressions, using real codecs and offline model doubles."""

import io
import os
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from bili_asr import archive, asr, audio, bili_client
from bili_asr.cli import main
from bili_asr.coordinator import RunCoordinator
from bili_asr.manifest import ManifestStore
from bili_asr.page_identity import page_identity
from bili_asr.services.queue_source import QueueSource
from bili_asr.storage import open_database

from _asr_fakes import ModelSet, install
from test_audio import AUDIO_BYTES, STREAM_HOST, make_client, playurl_ok
from test_cli_asr import _audio_transport, _patch_cli, _stub_runner_model
from test_cli_queue_source import _seed_store, _write_audio_file
from test_coordinator import _row


@pytest.mark.parametrize("subtype", ["PCM_16", "PCM_24"])
def test_flac_download_converts_losslessly_and_reaches_asr(tmp_root, subtype):
    samples = np.sin(np.arange(32_000) * 0.1).astype(np.float32) * 0.2
    encoded = io.BytesIO()
    sf.write(encoded, samples, 16_000, format="FLAC", subtype=subtype)
    encoded.seek(0)
    expected, rate = sf.read(encoded, dtype="float32")
    url = f"https://{STREAM_HOST}/lossless.flac"
    client = make_client(
        {"playurl": [playurl_ok([{"id": 30232, "baseUrl": url}])]},
        stream_routes={url: encoded.getvalue()},
    )
    identity = page_identity("BVlossless", 0, 11, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(identity, status="needs_audio"))
    output = os.path.join(tmp_root, "audio", "BVlossless.p0.m4a")

    assert audio.download_audio(client, identity, output, store=store) == output
    decoded, decoded_rate = asr._read_audio(output)
    assert decoded_rate == rate
    np.testing.assert_array_equal(decoded, expected)
    models = ModelSet()
    runner = asr.ASRRunner(asr.ASRConfig(model_name=asr.DEFAULT_MODEL, device="cpu"), model_factory=lambda **kwargs: models)
    assert runner.transcribe(output)
    assert runner.transcribed_coverage()["decoded_s"] == 2.0
    assert store.get(identity.work_id)["status"] == "audio_ok"
    assert list(Path(tmp_root, "audio").iterdir()) == [Path(output)]


@pytest.mark.parametrize("failure", ["partial", "empty"])
def test_download_tries_backup_without_reusing_failed_prefix(tmp_root, failure):
    primary = f"https://{STREAM_HOST}/primary.m4s"
    backup = f"https://{STREAM_HOST}/backup.m4s"
    client = make_client({"playurl": [playurl_ok([{
        "id": 30216, "baseUrl": primary,
        "backupUrl": [primary, None, backup], "backup_url": [backup],
    }])]})
    calls = []

    def download(url, destination):
        calls.append(url)
        with open(destination, "wb") as handle:
            if url == primary:
                if failure == "partial":
                    handle.write(b"broken-prefix" * 100)
                    raise bili_client.StreamDownloadError("private signed URL")
            else:
                handle.write(AUDIO_BYTES)

    client.download_audio_stream = download
    identity = page_identity("BVbackup", 0, 11, "p0")
    output = os.path.join(tmp_root, "audio", "BVbackup.p0.m4a")
    audio.download_audio(client, identity, output)
    assert calls == [primary, backup]
    assert Path(output).read_bytes() == AUDIO_BYTES
    assert list(Path(tmp_root, "audio").iterdir()) == [Path(output)]


def test_empty_download_is_retryable_and_never_marks_audio_ok(tmp_root):
    url = f"https://{STREAM_HOST}/empty.m4s"
    client = make_client(
        {"playurl": [playurl_ok([{"id": 30216, "baseUrl": url}])]},
        stream_routes={url: b""},
    )
    identity = page_identity("BVempty", 0, 11, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(identity, status="needs_audio"))
    with pytest.raises(bili_client.StreamDownloadError, match="all audio CDN addresses failed"):
        audio.download_audio(client, identity, Path(tmp_root, "audio", "BVempty.p0.m4a"), store)
    assert store.get(identity.work_id)["status"] == "needs_audio"
    assert list(Path(tmp_root, "audio").iterdir()) == []


@pytest.mark.parametrize("selector", ["pending", "bvid"])
def test_asr_run_records_scope_limit_detected_language_and_completion(
    tmp_root, monkeypatch, selector,
):
    _, identity = _seed_store(tmp_root)
    _write_audio_file(tmp_root, identity)
    _stub_runner_model(monkeypatch, [])
    _patch_cli(monkeypatch)
    target = ["--pending"] if selector == "pending" else ["--bvid", identity.work_id]
    assert main(["asr", *target, "--limit", "1", "--archive-root", tmp_root]) == 0
    connection = open_database(tmp_root)
    try:
        run = connection.execute("SELECT * FROM acquisition_runs WHERE kind='asr'").fetchone()
        assert run["selector_kind"] == selector
        assert run["selector_target"] == (None if selector == "pending" else identity.work_id)
        assert run["requested_limit"] == 1
        assert run["outcome"] == "complete"
        assert run["finished_at"] >= run["started_at"]
        transcript = connection.execute("SELECT language FROM transcripts WHERE source_kind='asr-local'").fetchone()
        assert transcript["language"] == "Chinese"
    finally:
        connection.close()


@pytest.mark.parametrize("error", [ValueError, RuntimeError])
def test_store_writeback_failure_preserves_published_asr(tmp_root, monkeypatch, capsys, error):
    _, identity = _seed_store(tmp_root)
    _write_audio_file(tmp_root, identity)
    _stub_runner_model(monkeypatch, [])
    _patch_cli(monkeypatch)

    def fail(*args, **kwargs):
        raise error("private store path")

    boundary = (
        "bili_asr.cli.asr._asr_transcript_segments"
        if error is ValueError
        else "bili_asr.services.queue_source.record_local_transcript"
    )
    monkeypatch.setattr(boundary, fail)
    assert main(["asr", "--pending", "--archive-root", tmp_root]) == 0
    captured = capsys.readouterr()
    assert "archive failed" not in captured.err
    assert "private store path" not in captured.err
    assert "write-back failed" in captured.err
    row = ManifestStore(root=tmp_root).get(identity.work_id)
    assert row["status"] == "archived"
    paths = {key: row[key] for key in ("srt_path", "txt_path", "md_path", "raw_path")}
    assert archive.archive_bundle_complete(tmp_root, paths)


@pytest.mark.parametrize("interrupted", [False, True])
def test_failed_or_interrupted_asr_finishes_its_run(tmp_root, monkeypatch, interrupted):
    _, identity = _seed_store(tmp_root)
    _write_audio_file(tmp_root, identity)
    _patch_cli(monkeypatch)

    def fail(*args, **kwargs):
        raise KeyboardInterrupt() if interrupted else asr.AudioDecodeError("bad audio")

    monkeypatch.setattr(asr.ASRRunner, "transcribe", fail)
    command = ["asr", "--pending", "--archive-root", tmp_root]
    if interrupted:
        with pytest.raises(KeyboardInterrupt):
            main(command)
    else:
        assert main(command) == 1
    connection = open_database(tmp_root)
    try:
        run = connection.execute("SELECT outcome, finished_at FROM acquisition_runs WHERE kind='asr'").fetchone()
        assert run["outcome"] == "failed"
        assert run["finished_at"] is not None
    finally:
        connection.close()


def test_reused_audio_bypasses_download_budget_and_network(tmp_root, monkeypatch):
    identity = page_identity("BVreuse", 0, 12, "p0")
    entry = _row(identity, status="needs_audio")
    store = ManifestStore(root=tmp_root)
    store.upsert(entry)
    _write_audio_file(tmp_root, identity)
    install(monkeypatch)
    coordinator = RunCoordinator(tmp_root, store, client=object(), max_audio_bytes=1)
    summary = coordinator.run_batch([(identity.work_id, entry)])
    assert summary.ok_count == 1
    assert store.get(identity.work_id)["status"] == "archived"


def test_missing_audio_ok_file_is_downloaded_again(tmp_root, monkeypatch):
    identity = page_identity("BVlost", 0, 12, "p0")
    entry = _row(identity, status="audio_ok")
    store = ManifestStore(root=tmp_root)
    store.upsert(entry)
    install(monkeypatch)
    client = make_client(
        {"playurl": [playurl_ok()]},
        stream_routes={f"{STREAM_HOST}/a30216.m4s": AUDIO_BYTES},
    )
    summary = RunCoordinator(tmp_root, store, client=client).run_batch([(identity.work_id, entry)])
    assert summary.ok_count == 1
    assert len(client.transport.stream_calls) == 1
    assert store.get(identity.work_id)["status"] == "archived"


def test_finishing_a_source_twice_preserves_its_terminal_record(tmp_root):
    connection = open_database(tmp_root)
    try:
        source = QueueSource(connection)
        run_id = source.ensure_asr_run("asr")
        source.finish_asr_run(outcome="failed")
        source.finish_asr_run(outcome="complete")
        assert connection.execute("SELECT outcome FROM acquisition_runs WHERE run_id=?", (run_id,)).fetchone()[0] == "failed"
    finally:
        connection.close()


def test_detected_language_is_cleared_after_an_unrelated_failure(monkeypatch):
    models = install(monkeypatch)
    runner = asr.ASRRunner(asr.ASRConfig(model_name=asr.DEFAULT_MODEL, device="cpu"), model_factory=lambda **kwargs: models)
    assert runner.provenance()["language"] == ""
    runner.transcribe("first.wav")
    assert runner.provenance()["language"] == "Chinese"

    def fail(path):
        raise asr.AudioDecodeError("unreadable")

    monkeypatch.setattr(asr, "_read_audio", fail)
    with pytest.raises(asr.AudioDecodeError):
        runner.transcribe("second.wav")
    assert runner.provenance()["language"] == ""


def test_multiple_detected_languages_are_marked_as_multilingual(monkeypatch):
    models = install(monkeypatch, seconds=2)
    runner = asr.ASRRunner(
        asr.ASRConfig(model_name=asr.DEFAULT_MODEL, device="cpu", chunk_seconds=1),
        model_factory=lambda **kwargs: models,
    )
    languages = iter(["Chinese", "English"])
    monkeypatch.setattr(runner, "_transcribe_chunk", lambda *args, **kwargs: ("文字。", next(languages)))
    runner.transcribe("mixed.wav")
    assert runner.provenance()["language"] == "mul"


def test_coordinator_finishes_its_writeback_run(tmp_root, monkeypatch):
    _, identity = _seed_store(tmp_root)
    _write_audio_file(tmp_root, identity)
    install(monkeypatch)
    entry = _row(identity, status="audio_ok")
    store = ManifestStore(root=tmp_root)
    store.upsert(entry)
    summary = RunCoordinator(tmp_root, store, offline=True).run_batch([(identity.work_id, entry)])
    assert summary.ok_count == 1
    connection = open_database(tmp_root)
    try:
        run = connection.execute("SELECT outcome, finished_at FROM acquisition_runs WHERE kind='asr'").fetchone()
        assert run["outcome"] == "complete"
        assert run["finished_at"] is not None
    finally:
        connection.close()


def test_pilot_finishes_its_writeback_run(tmp_root, monkeypatch):
    _seed_store(tmp_root)
    _write_audio_file(tmp_root, page_identity("BVqueueT", 0, 9002, "p0"))
    _stub_runner_model(monkeypatch, [])
    _patch_cli(monkeypatch, _audio_transport())
    monkeypatch.setattr("bili_asr.cli.pilot.time.sleep", lambda seconds: None)
    # The pilot demands both branches, so this audio-only scope exits 1;
    # its successful ASR work still has a completed acquisition run.
    main(["pilot", "--n", "5", "--archive-root", tmp_root])
    connection = open_database(tmp_root)
    try:
        run = connection.execute("SELECT outcome, finished_at, requested_limit FROM acquisition_runs WHERE kind='asr'").fetchone()
        assert run is not None
        assert run["outcome"] == "complete"
        assert run["finished_at"] is not None
        assert run["requested_limit"] == 5
    finally:
        connection.close()


def test_conversion_failure_never_publishes_or_leaves_staging_files(tmp_root):
    url = f"https://{STREAM_HOST}/broken.flac"
    client = make_client(
        {"playurl": [playurl_ok([{"id": 30232, "baseUrl": url}])]},
        stream_routes={url: b"fLaCbroken"},
    )
    identity = page_identity("BVbroken", 0, 11, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(identity, status="needs_audio"))
    with pytest.raises(audio.AudioConversionError, match="ffmpeg audio conversion failed"):
        audio.download_audio(client, identity, Path(tmp_root, "audio", "BVbroken.p0.m4a"), store)
    assert list(Path(tmp_root, "audio").iterdir()) == []
    assert store.get(identity.work_id)["status"] == "needs_audio"
