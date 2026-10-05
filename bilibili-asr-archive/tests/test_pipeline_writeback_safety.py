"""Pipeline attribution, queue eligibility and diagnostic failure boundaries."""

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from bili_asr import archive, audio, manifest
from bili_asr.cli.run import _run_scope_rows
from bili_asr.coordinator import RunCoordinator, _caption_language_from_entry
from bili_asr.manifest import ManifestStore
from bili_asr.page_identity import page_identity, writeback_identity
from bili_asr.services import _common, queue_source as qs
from bili_asr.storage import TranscriptRepository, TranscriptSegmentRecord, open_database

from _asr_fakes import install
from test_cli_queue_source import _seed_store, _write_audio_file
from test_coordinator import _row
from test_storage_queue_gaps import _open_run, _seed


@pytest.mark.parametrize("credentials", [(False, False), (False, True), (True, True)])
def test_only_authenticated_empty_observations_corroborate_exhaustion(tmp_root, credentials):
    connection = open_database(tmp_root)
    try:
        parts, repository = _seed(connection)
        part = parts[("BV1AAA", 0)]
        transcripts = TranscriptRepository(connection)
        for number, credential in enumerate(credentials):
            run_id = f"credential-probe-{number}"
            _open_run(transcripts, run_id, "subtitle", credential_present=credential)
            transcripts.record_subtitle_attempt(
                run_id=run_id, video_part_id=part, outcome="no-subtitle",
                error_code=None, started_at=1000 + number, finished_at=1000 + number,
                credential_verified=credential,
            )
        queued = {item.work_id for item in repository.list_queue_gaps(gap="missing_audio")}
        assert ("BV1AAA:p0" in queued) == all(credentials)
        state = connection.execute(
            "SELECT pipeline_state FROM v_part_pipeline WHERE video_part_id=?", (part,),
        ).fetchone()[0]
        assert state == ("audio_pending" if all(credentials) else "no_subtitle")
    finally:
        connection.close()
    # Reopen the archive: existing roots receive the changed view contract too.
    connection = open_database(tmp_root)
    try:
        count = connection.execute(
            "SELECT COUNT(*) FROM v_missing_audio WHERE video_part_id=?", (part,),
        ).fetchone()[0]
        assert count == int(all(credentials))
    finally:
        connection.close()


def test_connection_contract_failure_preserves_archive_across_batches(tmp_root, monkeypatch, capsys):
    _, identity = _seed_store(tmp_root)
    _write_audio_file(tmp_root, identity)
    install(monkeypatch)
    store = ManifestStore(root=tmp_root)
    coordinator = RunCoordinator(tmp_root, store, offline=True, keep_audio=True)

    def source_with_lost_contract(root):
        source = qs.QueueSource(open_database(root))
        source.connection.row_factory = None
        return source

    monkeypatch.setattr(qs, "open_queue_source", source_with_lost_contract)
    for _ in range(2):
        entry = _row(identity, status="audio_ok")
        store.upsert(entry)
        result = coordinator.run_batch([(identity.work_id, entry)])
        assert result.ok_count == 1
        assert store.get(identity.work_id)["status"] == "archived"
    attempts = coordinator.ledger.load()
    assert not any(a["stage"] == "archive" and a["outcome"] == "failed" for a in attempts)
    captured = capsys.readouterr()
    assert captured.err.count("acquisition run refused") == 1
    assert "TypeError" in captured.err


@pytest.mark.parametrize("site", ["queue", "coordinator", "load-failure", "asr-cli"])
def test_closed_stderr_diagnostics_preserve_process_exit_status(site):
    script = '''
import os
from types import SimpleNamespace
from bili_asr.services.queue_source import QueueSource
from bili_asr.coordinator import RunCoordinator, RunSummary
from bili_asr.cli.asr import _print_in_process_constructions
source = object.__new__(QueueSource)
source._asr_run_refusal_reported = False
coordinator = object.__new__(RunCoordinator)
coordinator.command = "run"
os.close(2)
if SITE == "queue":
    source._report_refused_asr_run("asr", ValueError())
elif SITE == "coordinator":
    coordinator._print_model_constructions(RunSummary(model_constructions=1, asr_items=1))
elif SITE == "load-failure":
    coordinator._print_model_constructions(RunSummary(model_load_attempts=1))
else:
    _print_in_process_constructions("asr", SimpleNamespace(model_constructions=1), 1)
'''
    result = subprocess.run(
        [sys.executable, "-c", "SITE=" + repr(site) + "\n" + script],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_queue_writebacks_share_one_injectable_clock(tmp_root, monkeypatch):
    identity, _ = _seed_store(tmp_root)
    _write_audio_file(tmp_root, identity)
    monkeypatch.setattr(_common, "_now", lambda: 2_000_000_000)
    connection = open_database(tmp_root)
    try:
        source = qs.QueueSource(connection)
        run_id = source.ensure_asr_run("asr")
        qs.mark_audio_acquired(
            source, bvid=identity.bvid, page_index=identity.page_index,
            audio_path=os.path.join(tmp_root, "audio", identity.bvid + ".p0.m4a"),
            declared_relative="audio/clock.m4a",
        )
        qs.record_local_transcript(
            source, run_id=run_id, bvid=identity.bvid, page_index=identity.page_index,
            language="Chinese", segments=(TranscriptSegmentRecord(0, 1000, "时钟"),),
            model_name="test", model_revision=None,
        )
        source.finish_asr_run()
        run = connection.execute("SELECT started_at,finished_at FROM acquisition_runs WHERE run_id=?", (run_id,)).fetchone()
        assert tuple(run) == (2_000_000_000, 2_000_000_000)
        attempt = connection.execute("SELECT started_at,finished_at FROM acquisition_attempts WHERE run_id=?", (run_id,)).fetchone()
        assert tuple(attempt) == (2_000_000_000, 2_000_000_000)
        acquired = connection.execute("SELECT acquired_at FROM part_audio_objects WHERE video_part_id=(SELECT video_part_id FROM video_parts WHERE bvid=?)", (identity.bvid,)).fetchone()[0]
        assert acquired == 2_000_000_000
    finally:
        connection.close()


def test_audio_run_and_failure_attempt_share_one_injectable_clock(tmp_root, monkeypatch):
    """Audio lifecycle timestamps stay on the service clock, including failures."""
    identity, _ = _seed_store(tmp_root)
    monkeypatch.setattr(_common, "_now", lambda: 2_100_000_000)
    connection = open_database(tmp_root)
    try:
        source = qs.QueueSource(connection)
        run_id = source.ensure_audio_run("download-audio", selector_target=identity.bvid)
        assert run_id is not None
        source.record_audio_failed(
            bvid=identity.bvid,
            page_index=identity.page_index,
            error_code="stream-http",
        )
        source.finish_audio_run(outcome="failed")
        run = connection.execute(
            "SELECT started_at, finished_at, outcome FROM acquisition_runs "
            "WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        assert tuple(run) == (2_100_000_000, 2_100_000_000, "failed")
        attempt = connection.execute(
            "SELECT started_at, finished_at, outcome, error_code "
            "FROM acquisition_attempts WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        assert tuple(attempt) == (
            2_100_000_000,
            2_100_000_000,
            "failed",
            "stream-http",
        )
    finally:
        connection.close()


def test_scope_filters_honor_an_added_terminal_status(tmp_root, monkeypatch):
    monkeypatch.setattr(manifest, "TERMINAL_STATUSES", manifest.TERMINAL_STATUSES | {"retired"})
    monkeypatch.setattr(manifest, "VALID_STATUSES", manifest.VALID_STATUSES | {"retired"})
    monkeypatch.setattr(RunCoordinator, "failed_work_ids", lambda self: {"BVlive", "BVretired"})
    entries = {"BVlive": {"bvid": "BVlive", "status": "needs_audio"}, "BVretired": {"bvid": "BVretired", "status": "retired"}}
    for scope in ("pending", "failed"):
        rows, error = _run_scope_rows(SimpleNamespace(root=tmp_root), entries, scope)
        assert error is None
        assert [key for key, _ in rows] == ["BVlive"]


def test_failed_scope_reselects_archived_transcript_writeback_failure(
    tmp_root, monkeypatch
):
    monkeypatch.setattr(RunCoordinator, "failed_work_ids", lambda self: set())
    entries = {
        "BVretry": {
            "bvid": "BVretry",
            "status": "archived",
            "transcript_writeback_error": "OperationalError",
        },
        "BVdone": {"bvid": "BVdone", "status": "archived"},
    }
    rows, error = _run_scope_rows(SimpleNamespace(root=tmp_root), entries, "failed")
    assert error is None
    assert [key for key, _ in rows] == ["BVretry"]


def test_unconfined_audio_cannot_silently_skip_manifest_write(tmp_root, tmp_path):
    store = ManifestStore(root=tmp_root)
    identity = page_identity("BVoutside", 0, 1)
    store.upsert(_row(identity, status="needs_audio"))
    external = tmp_path / "outside.m4a"
    external.write_bytes(b"audio")
    with pytest.raises(OSError, match="audio path outside archive"):
        audio._mark_audio_ok(store, identity, os.fspath(external))
    assert store.get(identity.work_id)["status"] == "needs_audio"


def test_writeback_uses_work_id_and_never_attributes_legacy_row_to_p0(tmp_root, monkeypatch):
    _, identity = _seed_store(tmp_root)
    store = ManifestStore(root=tmp_root)
    coordinator = RunCoordinator(tmp_root, store)
    legacy = {"bvid": identity.bvid, "sub_lan": "ai-zh"}
    coordinator._record_asr_transcript(legacy, [{"start": 0, "end": 1, "text": "旧记录"}])
    coordinator._record_subtitle_transcript(entry=legacy, raw={}, segments=[])
    assert coordinator._writeback_source is None
    source = qs.QueueSource(open_database(tmp_root))
    coordinator._writeback_source = source
    captured = []
    monkeypatch.setattr(qs, "record_local_transcript", lambda *args, **kwargs: captured.append(kwargs))
    coordinator._record_asr_transcript({"bvid": identity.bvid, "work_id": identity.bvid + ":p2", "page_index": 0}, [])
    coordinator._close_writeback_source()
    assert captured[0]["page_index"] == 2
    assert writeback_identity({"bvid": "wrong", "work_id": identity.work_id}) is None


def test_caption_language_uses_documented_fallback():
    assert _caption_language_from_entry({"sub_lan_doc": "  zh-CN  "}) == "zh-CN"
    assert _caption_language_from_entry({"sub_lan": "ai-zh", "sub_lan_doc": "中文"}) == "ai-zh"


def test_asr_archive_manifest_carries_branch_and_language(tmp_root, monkeypatch):
    _, identity = _seed_store(tmp_root)
    _write_audio_file(tmp_root, identity)
    install(monkeypatch)
    store = ManifestStore(root=tmp_root)
    entry = _row(identity, status="audio_ok")
    store.upsert(entry)
    assert RunCoordinator(tmp_root, store, offline=True).run_batch([(identity.work_id, entry)]).ok_count == 1
    row = store.get(identity.work_id)
    assert (row["source"], row["language"]) == ("asr", "Chinese")
    assert archive.archive_bundle_complete(tmp_root, {key: row[key] for key in ("srt_path", "txt_path", "md_path", "raw_path")})
    from bili_asr.export import export_rows
    from bili_asr.integrity import IntegrityVerifier
    from bili_asr.search_index import SearchQuery, search

    exported = export_rows(store)
    assert exported[0]["source"] == "asr"
    assert exported[0]["language"] == "Chinese"
    hits = search(tmp_root, SearchQuery(query="", source="asr"))
    assert hits and hits[0]["source"] == "asr"
    assert IntegrityVerifier().verify(Path(tmp_root)).authoritative
