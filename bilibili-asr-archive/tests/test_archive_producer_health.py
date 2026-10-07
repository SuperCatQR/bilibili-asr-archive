"""Actual archive producers distinguish optional and missing campaign evidence."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from functools import partial
from bili_asr.cli.main import _main

# Exercise the publication worker in-process so fault injection and captured
# output remain local; supervisor process/deadline tests cover the public entry.
main = partial(_main, _publication_worker=True)
from bili_asr.coordinator import RunCoordinator
from bili_asr.integrity import MISSING_ATTEMPTS
from bili_asr.manifest import ManifestStore
from bili_asr.page_identity import artifact_stem, page_identity
from bili_asr.sidecar_projection import is_plain_cli_archive
from bili_asr.storage import AcquisitionRunRecord, TranscriptRepository, open_database

from test_cli_asr import _patch_cli, _stub_runner_model
from test_cli_publish_transcripts import CAPTION_SEGMENTS, FRESH_BVID, PARTS, _seed_archive
from test_cli_queue_source import _seed_store, _write_audio_file
from test_coordinator import SAMPLE_DOC, _row, _seed_part
from test_coverage_report import cursor, ledger, scheduler


pytestmark = pytest.mark.skipif(
    os.name == "nt", reason="descriptor-confined health readers require POSIX",
)


def _caption_input(root: str, *, producer: str = "coordinator"):
    identity = page_identity("BVproducer", 0, 401, "p0")
    store = ManifestStore(root=root)
    row = _row(identity, status="subtitle_done", title="caption")
    row.update(sub_lan="ai-zh", archive_producer=producer)
    store.upsert(row)
    raw = Path(root, "subtitles", "raw", artifact_stem(identity) + ".json")
    raw.parent.mkdir(parents=True)
    raw.write_text(json.dumps(SAMPLE_DOC), encoding="utf-8")
    return identity, store, row


def _health(root: str, command: str, capsys):
    capsys.readouterr()
    result = main([
        command, "--strict", "--archive-root", root, "--format", "json",
    ])
    return result, json.loads(capsys.readouterr().out)


@pytest.mark.parametrize("command", ["coverage", "verify"])
@pytest.mark.parametrize("route", ["asr", "subtitle"])
def test_actual_standalone_asr_command_needs_no_campaign_sidecars(
    tmp_root, monkeypatch, capsys, command, route,
):
    if route == "asr":
        _, identity = _seed_store(tmp_root)
        _write_audio_file(tmp_root, identity)
        _stub_runner_model(monkeypatch, [])
        _patch_cli(monkeypatch)
        selection = []
    else:
        identity, _, _ = _caption_input(tmp_root)
        selection = ["--queue-source", "manifest"]
    assert main(["asr", "--pending", *selection, "--archive-root", tmp_root]) == 0
    row = ManifestStore(root=tmp_root).get(identity.work_id)
    assert row["status"] == "archived"
    assert row["source"] == route
    assert row["archive_producer"] == "stage-cli"
    assert not Path(tmp_root, "coordinator", "attempts.jsonl").exists()
    result, payload = _health(tmp_root, command, capsys)
    assert result == 0
    assert payload["diagnostics"] == []


@pytest.mark.parametrize("command", ["coverage", "verify"])
@pytest.mark.parametrize("source", ["subtitle-ai", "subtitle-cc", "asr-local"])
def test_actual_publish_transcripts_is_a_standalone_producer(
    tmp_root, capsys, command, source,
):
    _seed_archive(tmp_root, parts=(PARTS[0],))
    connection = open_database(tmp_root)
    try:
        repository = TranscriptRepository(connection)
        repository.start_acquisition_run(AcquisitionRunRecord(
            run_id="publication-input", kind="asr" if source == "asr-local" else "subtitle",
            selector_kind="pending", selector_target=None, requested_limit=None,
            credential_present=False, started_at=100,
        ))
        part_id = connection.execute("SELECT video_part_id FROM video_parts").fetchone()[0]
        arguments = dict(
            run_id="publication-input", video_part_id=part_id, language="zh-CN",
            segments=CAPTION_SEGMENTS, started_at=200, finished_at=300, created_at=400,
        )
        if source == "asr-local":
            repository.record_local_transcript(
                **arguments, model_name="offline-model", model_revision=None,
            )
        else:
            repository.record_acquired_transcript(**arguments, source_kind=source)
    finally:
        connection.close()
    assert main(["publish-transcripts", "--archive-root", tmp_root]) == 0
    row = ManifestStore(root=tmp_root).get(FRESH_BVID + ":p0")
    assert row["source"] == source
    assert row["archive_producer"] == "stage-cli"
    result, payload = _health(tmp_root, command, capsys)
    assert result == 0
    assert payload["diagnostics"] == []


@pytest.mark.parametrize("command", ["coverage", "verify"])
@pytest.mark.parametrize("damage", ["missing", "malformed"])
def test_actual_coordinator_archive_still_owes_its_attempts(
    tmp_root, capsys, command, damage,
):
    identity, store, row = _caption_input(tmp_root, producer="stage-cli")
    _seed_part(tmp_root, identity.bvid, identity.page_index, identity.cid)
    result = RunCoordinator(tmp_root, store, offline=True).run_batch([(identity.work_id, row)])
    assert result.fully_processed
    store.save()
    archived = ManifestStore(root=tmp_root).get(identity.work_id)
    assert archived["source"] == "subtitle"
    assert archived["archive_producer"] == "coordinator"
    assert not is_plain_cli_archive({identity.work_id: archived})
    # Other evidence is available, so only the changed attempts can move health.
    root = Path(tmp_root)
    (root / "meta-cursor.json").write_text(json.dumps(cursor()), encoding="utf-8")
    (root / "scheduler.json").write_text(json.dumps(scheduler(ids=[identity.work_id])), encoding="utf-8")
    (root / "run-ledger.jsonl").write_text(json.dumps(ledger([identity.work_id])) + "\n", encoding="utf-8")
    assert _health(tmp_root, command, capsys)[0] == 0
    attempts = root / "coordinator" / "attempts.jsonl"
    if damage == "missing":
        attempts.unlink()
    else:
        attempts.write_text("{broken\n", encoding="utf-8")
    result, payload = _health(tmp_root, command, capsys)
    assert result == 1
    assert payload["diagnostics"]
    if damage == "missing":
        if command == "coverage":
            assert "evidence_missing" in json.dumps(payload["diagnostics"])
        else:
            assert MISSING_ATTEMPTS in payload["diagnostics"]


@pytest.mark.parametrize("command", ["coverage", "verify"])
@pytest.mark.parametrize("producer", [None, "coordinator", "unknown"])
def test_historical_or_unknown_producer_cannot_waive_missing_evidence(
    tmp_root, capsys, command, producer,
):
    identity, store, _ = _caption_input(tmp_root)
    assert main(["asr", "--pending", "--queue-source", "manifest", "--archive-root", tmp_root]) == 0
    archived = ManifestStore(root=tmp_root).get(identity.work_id)
    if producer is None:
        archived.pop("archive_producer")
    else:
        archived["archive_producer"] = producer
    store.upsert(archived)
    store.save()
    result, payload = _health(tmp_root, command, capsys)
    assert result == 1
    assert payload["diagnostics"]
    # Read-only health must neither guess nor backfill producer provenance.
    assert ManifestStore(root=tmp_root).get(identity.work_id).get("archive_producer") == producer


@pytest.mark.parametrize("command", ["coverage", "verify"])
def test_standalone_provenance_does_not_hide_malformed_present_sidecars(
    tmp_root, capsys, command,
):
    _caption_input(tmp_root)
    assert main(["asr", "--pending", "--queue-source", "manifest", "--archive-root", tmp_root]) == 0
    attempts = Path(tmp_root, "coordinator", "attempts.jsonl")
    attempts.parent.mkdir(exist_ok=True)
    attempts.write_text("{broken\n", encoding="utf-8")
    result, payload = _health(tmp_root, command, capsys)
    assert result == 1
    assert payload["diagnostics"]


def test_mixed_producers_never_waive_campaign_evidence():
    assert not is_plain_cli_archive({
        "BVcli:p0": {"status": "archived", "source": "asr", "archive_producer": "stage-cli"},
        "BVcampaign:p0": {"status": "archived", "source": "subtitle", "archive_producer": "coordinator"},
    })
    assert not is_plain_cli_archive({})
