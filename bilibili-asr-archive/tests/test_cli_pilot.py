"""Executable mixed-branch pilot: fake HTTP + stubbed ASR, no live network."""

import bili_asr.asr.runner as _module_asr_runner
import bili_asr.cli.pilot as _module_cli_pilot




def test_pilot_rejects_downloader_path_escape(tmp_path, monkeypatch):
    from bili_asr import cli
    from bili_asr import audio as audio_mod
    class Store:
        def get(self, _key): return None
        def upsert(self, _row): pass
    outside = tmp_path.parent / "escaped.m4a"
    outside.write_bytes(b"audio")
    monkeypatch.setattr(audio_mod, "download_audio", lambda *args, **kwargs: str(outside))
    from bili_asr.artifact_root import ArtifactRoots
    from bili_asr.page_identity import page_identity
    target = page_identity("BVescape", 0, 1, "p0")
    with pytest.raises(ValueError):
        _module_cli_pilot._pilot_archive_asr(
            Store(), object(), ArtifactRoots.of(str(tmp_path)),
            {"bvid": "BVescape", "status": "needs_audio"}, target, keep=True,
        )

import json
import os
import pytest

from bili_asr import asr as asr_mod
from bili_asr import bili_client as bc
from bili_asr.cli.main import main
from bili_asr.manifest import ManifestStore
from bili_asr.page_identity import artifact_stem, page_identity

from tests.support.audio import (
    AUDIO_BYTES,
    SPI_OK,
    STREAM_HOST,
    RouterTransport,
    nav_response,
    playurl_ok,
)
from tests.support.subtitles import SAMPLE_DOC, nav_ok, player_ok, sub_entry
from tests.conftest import reuse_line

import tests.support.asr_fakes as asr_fakes
from tests.support.archive_database import _seed_archive_database




def _stub_runner_model(monkeypatch, reads=None, released=None):
    """D2.5 seam: patch the module-level factory, not ``asr.transcribe``.

    The real ``_get_model`` path stays under test, so the counter a command reports is the one the
    production construction site produces.  ``reads`` collects the path of every recording the
    boundary opened — the model is handed a chunk file, so a row is identified at the read, not at
    the model.
    """

    constructions: list[dict] = []
    asr_fakes.install(monkeypatch, constructions=constructions, reads=reads)

    if released is not None:
        real_release = _module_asr_runner.ASRRunner.release

        def recording_release(self):
            released.append(self)
            real_release(self)

        monkeypatch.setattr(_module_asr_runner.ASRRunner, "release", recording_release)

    return constructions


def _row(identity, *, duration_s, title="clip"):
    return {
        "bvid": identity.bvid,
        "work_id": identity.work_id,
        "page_index": identity.page_index,
        "cid": identity.cid,
        "page_label": identity.page_label,
        "status": "meta_ok",
        "title": title,
        "duration_s": duration_s,
        "pubdate": 1,
        "pubdate_str": "2026-01-02",
    }


def _patch_cli(monkeypatch, transport):
    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
    monkeypatch.setattr(bc, "default_sleeper", lambda: (lambda _seconds: None))
    monkeypatch.setattr('bili_asr.cli.pilot.time.sleep', lambda _seconds: None)






def test_cli_pilot_audio_ok_reuses_local_audio_when_budget_is_full(
    tmp_root, monkeypatch, capsys
):
    from bili_asr import audio as audio_mod

    aud = page_identity("BVlocal", 0, 222, "p0")
    store = ManifestStore(root=tmp_root)
    row = _row(aud, duration_s=600, title="local-audio")
    row.update({"status": "audio_ok", "audio_path": "audio/BVlocal.p0.m4a"})
    store.upsert(row)
    audio_dir = os.path.join(tmp_root, "audio")
    os.makedirs(audio_dir)
    local_audio = os.path.join(audio_dir, "BVlocal.p0.m4a")
    with open(local_audio, "wb") as fh:
        fh.write(b"audio" * 1000)

    asr_fakes.install(monkeypatch)
    monkeypatch.setattr(
        audio_mod,
        "download_audio",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("audio_ok must not download again")
        ),
    )
    _patch_cli(monkeypatch, RouterTransport({}))

    _seed_archive_database(tmp_root)
    rc = main(
        [
            "pilot",
            "--n",
            "1",
            "--max-audio-gb",
            "0.000001",
            # The post-archive removal this case asserts is the retention pair's
            # explicit opt-in now (contract D5); the default keeps the audio.
            "--no-keep-audio",
            "--archive-root",
            tmp_root,
        ]
    )
    captured = capsys.readouterr()
    assert rc == 1  # audio branch succeeded; required subtitle branch is absent.
    assert "audio_budget" not in captured.err
    assert ManifestStore(root=tmp_root).get(aud.work_id)["status"] == "archived"
    assert not os.path.exists(local_audio)


def test_cli_pilot_missing_subtitle_branch_exits_nonzero(tmp_root, monkeypatch, capsys):
    only = page_identity("BVonly", 0, 333, "p0")
    ManifestStore(root=tmp_root).upsert(_row(only, duration_s=4))
    asr_fakes.install(monkeypatch)
    transport = RouterTransport(
        {
            "finger/spi": [SPI_OK],
            "nav": [nav_ok(), nav_response()],
            "player/wbi/v2": [player_ok([])],
            "/x/player/wbi/playurl": [playurl_ok()],
        },
        stream_routes={f"{STREAM_HOST}/a30216.m4s": AUDIO_BYTES},
    )
    _patch_cli(monkeypatch, transport)
    _seed_archive_database(tmp_root)
    rc = main(["pilot", "--n", "1", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 1
    assert "missing branch coverage" in captured.err
    assert "subtitle" in captured.err
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[only.work_id]["status"] == "archived"


def _mixed_transport():
    return RouterTransport(
        {
            "finger/spi": [SPI_OK],
            "nav": [nav_ok(), nav_response()],
            "player/wbi/v2": [player_ok([sub_entry()]), player_ok([])],
            "aisubtitle.hdslb.com": [(200, dict(SAMPLE_DOC))],
            "/x/player/wbi/playurl": [playurl_ok()],
        },
        stream_routes={f"{STREAM_HOST}/a30216.m4s": AUDIO_BYTES},
    )










def test_cli_pilot_empty_n_with_processable_rows_does_not_skip(tmp_root, capsys):
    only = page_identity("BVonly", 0, 333, "p0")
    ManifestStore(root=tmp_root).upsert(_row(only, duration_s=4))
    rc = main(["pilot", "--n", "0", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 1
    assert "already archived" not in captured.out
    assert "already archived" not in captured.err


def test_cli_pilot_archived_plus_gone_does_not_skip(tmp_root, capsys):
    done = page_identity("BVdone", 0, 111, "p0")
    gone = page_identity("BVgone", 0, 222, "p0")
    store = ManifestStore(root=tmp_root)
    archived = _row(done, duration_s=5, title="done")
    archived["status"] = "archived"
    leftover = _row(gone, duration_s=3, title="gone")
    leftover["status"] = "gone"
    store.upsert(archived)
    store.upsert(leftover)
    rc = main(["pilot", "--n", "2", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 1
    assert "already archived" not in captured.out
    assert "already archived" not in captured.err




def test_cli_pilot_risk_budget_prints_branch_summary(tmp_root, monkeypatch, capsys):
    sub = page_identity("BVsub", 0, 111, "p0")
    aud = page_identity("BVaud", 0, 222, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(sub, duration_s=5, title="has-sub"))
    store.upsert(_row(aud, duration_s=8, title="needs-asr"))

    def raise_risk(*_args, **_kwargs):
        raise bc.RiskBudgetExhausted(-412)

    monkeypatch.setattr("bili_asr.subtitles.harvest_subtitle", raise_risk)
    _patch_cli(monkeypatch, _mixed_transport())
    # Harvest-route risk budget: pinned through the manifest rollback source
    # (the fixture seeds no archive.db, which the store source requires).
    rc = main([
        "pilot", "--n", "2", "--queue-source", "manifest",
        "--archive-root", tmp_root,
    ])
    captured = capsys.readouterr()
    assert rc == 2
    assert "risk-control ceiling" in captured.err
    assert "pilot batch branches:" in captured.out
    assert "pilot coverage branches:" in captured.out


# ------------------------------------------------------------ one runner per invocation


def test_cli_pilot_invocation_constructs_the_model_once_for_three_audio_rows(
    tmp_root, monkeypatch, capsys
):
    """D2.3: the pilot's own loop holds one runner for its whole selection.

    All three rows are ``audio_ok`` with audio already on disk, so they need
    no network at all; three rows (rather than one) prove the selection is
    wider than a single item.
    """

    identities = [
        page_identity(f"BVpilot{index}", 0, 400 + index, "p0") for index in range(3)
    ]
    store = ManifestStore(root=tmp_root)
    audio_dir = os.path.join(tmp_root, "audio")
    os.makedirs(audio_dir)
    for identity in identities:
        row = _row(identity, duration_s=5, title="pilot-reuse")
        row.update({
            "status": "audio_ok",
            "audio_path": f"audio/{artifact_stem(identity)}.m4a",
        })
        store.upsert(row)
        with open(os.path.join(audio_dir, f"{artifact_stem(identity)}.m4a"), "wb") as fh:
            fh.write(AUDIO_BYTES)

    released: list[object] = []
    constructions = _stub_runner_model(monkeypatch, released=released)
    _patch_cli(monkeypatch, RouterTransport({}))

    _seed_archive_database(tmp_root)
    rc = main(["pilot", "--n", "3", "--archive-root", tmp_root])
    captured = capsys.readouterr()

    # Exit 1 is the frozen pilot contract here: no subtitle branch was covered.
    assert rc == 1, captured.err
    loaded = ManifestStore(root=tmp_root).load()
    assert [loaded[i.work_id]["status"] for i in identities] == ["archived"] * 3
    assert len(constructions) == 1
    # The pilot's finally hands the invocation-scoped runner back exactly once.
    assert len(released) == 1
    assert "pilot: model constructions=1 for 3 asr item(s)" in captured.err
    assert "model constructions=" not in captured.out


def test_cli_pilot_releases_the_runner_when_the_loop_is_interrupted(
    tmp_root, monkeypatch, capsys
):
    """The pilot's `finally` releases even when the row raises past `except`.

    Every row-level ``except`` clause in ``_cmd_pilot`` catches ``Exception``,
    so a ``KeyboardInterrupt`` mid-selection is the path where only the
    `finally` can release the model — and that is exactly the interruption an
    operator sends to a long pilot batch.
    """

    identity = page_identity("BVpilotint", 0, 777, "p0")
    store = ManifestStore(root=tmp_root)
    row = _row(identity, duration_s=5, title="pilot-interrupt")
    row.update({
        "status": "audio_ok",
        "audio_path": f"audio/{artifact_stem(identity)}.m4a",
    })
    store.upsert(row)
    audio_dir = os.path.join(tmp_root, "audio")
    os.makedirs(audio_dir)
    with open(os.path.join(audio_dir, f"{artifact_stem(identity)}.m4a"), "wb") as fh:
        fh.write(AUDIO_BYTES)

    released: list[object] = []

    def interrupting(self, **_kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr(asr_fakes.Model, "generate", interrupting)
    asr_fakes.install(monkeypatch)

    real_release = _module_asr_runner.ASRRunner.release

    def recording_release(self):
        released.append(self)
        real_release(self)

    monkeypatch.setattr(_module_asr_runner.ASRRunner, "release", recording_release)
    _patch_cli(monkeypatch, RouterTransport({}))

    _seed_archive_database(tmp_root)
    assert main(["pilot", "--n", "1", "--archive-root", tmp_root]) == 130

    assert len(released) == 1
    assert ManifestStore(root=tmp_root).get(identity.work_id)["status"] == "audio_ok"
    from bili_asr.run_ledger import RunLedger

    record, = RunLedger(tmp_root).load()
    assert record["command"] == "pilot" and record["exit_code"] == 130
    assert record["work_ids"] == [identity.work_id]
    assert record["records_existing"] == 1
    assert record["coverage_summary"] == {"audio_ok": 1}


# ------------------------------------------------- the pilot's asr_items denominator


def _patch_bundle_incomplete_for(monkeypatch, failing):
    """Fail the archive step for ``failing`` only, on the pilot's path.

    The rows are seeded as ordinary ``audio_ok`` rows with their audio already
    on disk, so they all reach the real transcription boundary.  This patch
    then makes one of them fail *after* it produced its transcript: the real
    ``write_archive`` runs, the real ``ValueError("archive bundle
    incomplete")`` is raised, and the row keeps its ``audio_ok`` status.
    """
    from bili_asr import archive as archive_mod

    stem = artifact_stem(failing)
    real = archive_mod.archive_bundle_complete

    def patched(archive_root, paths):
        if any(stem in str(path) for path in paths.values()):
            return False
        return real(archive_root, paths)

    monkeypatch.setattr(archive_mod, "archive_bundle_complete", patched)


def test_cli_pilot_counts_the_row_that_fails_after_transcription(
    tmp_root, monkeypatch, capsys
):
    """D2.5 for the pilot: the denominator counts the ASR stage, not the archive.

    The pilot's increment used to sit in ``_cmd_pilot`` *after*
    ``_pilot_archive_asr`` returned, so a row that transcribed and then failed
    downstream dropped out of the line's denominator while ``run`` counted it
    at ``asr: ok``.  Row 2 of 3 fails exactly there, so the placement is only
    observable on this path: the wider selection must still read ``for 3``.
    """

    identities = [
        page_identity(f"BVpilotfail{index}", 0, 500 + index, "p0") for index in range(3)
    ]
    failing = identities[1]
    store = ManifestStore(root=tmp_root)
    audio_dir = os.path.join(tmp_root, "audio")
    os.makedirs(audio_dir)
    for identity in identities:
        row = _row(identity, duration_s=5, title="pilot-asr-count")
        row.update({
            "status": "audio_ok",
            "audio_path": f"audio/{artifact_stem(identity)}.m4a",
        })
        store.upsert(row)
        with open(os.path.join(audio_dir, f"{artifact_stem(identity)}.m4a"), "wb") as fh:
            fh.write(AUDIO_BYTES)

    constructions = _stub_runner_model(monkeypatch)
    _patch_bundle_incomplete_for(monkeypatch, failing)
    _patch_cli(monkeypatch, RouterTransport({}))

    _seed_archive_database(tmp_root)
    rc = main(["pilot", "--n", "3", "--archive-root", tmp_root])
    captured = capsys.readouterr()

    # Exit 1 is the frozen pilot contract here: no subtitle branch was covered.
    assert rc == 1, captured.err
    loaded = ManifestStore(root=tmp_root).load()
    # The failing row transcribed, then failed at the archive tail, so it is
    # neither archived nor lost: it keeps its pre-archive status.
    assert [loaded[i.work_id]["status"] for i in identities] == [
        "archived",
        "audio_ok",
        "archived",
    ]
    # One construction paid for three rows...
    assert len(constructions) == 1
    # ...and the line's denominator counts all three, the failed one included.
    assert reuse_line(captured, "pilot") == (
        "pilot: model constructions=1 for 3 asr item(s)"
    )
    assert "model constructions=" not in captured.out
