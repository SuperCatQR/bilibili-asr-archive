"""Executable mixed-branch pilot: fake HTTP + stubbed ASR, no live network."""



def test_pilot_rejects_downloader_path_escape(tmp_path, monkeypatch):
    from bili_asr import cli
    from bili_asr import audio as audio_mod
    class Store:
        def get(self, _key): return None
        def upsert(self, _row): pass
    outside = tmp_path.parent / "escaped.m4a"
    outside.write_bytes(b"audio")
    monkeypatch.setattr(audio_mod, "download_audio", lambda *args, **kwargs: str(outside))
    from bili_asr.page_identity import page_identity
    target = page_identity("BVescape", 0, 1, "p0")
    with pytest.raises(ValueError):
        cli._pilot_archive_asr(Store(), object(), str(tmp_path), {"bvid": "BVescape", "status": "needs_audio"}, target)

import json
import os
import pytest

from bili_asr import asr as asr_mod
from bili_asr import bili_client as bc
from bili_asr.cli import main
from bili_asr.manifest import ManifestStore
from bili_asr.page_identity import artifact_stem, page_identity

from test_audio import (
    AUDIO_BYTES,
    SPI_OK,
    STREAM_HOST,
    RouterTransport,
    nav_response,
    playurl_ok,
)
from test_subtitles import SAMPLE_DOC, nav_ok, player_ok, sub_entry


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
    monkeypatch.setattr("bili_asr.cli.time.sleep", lambda _seconds: None)


def test_cli_pilot_mixed_meta_ok_archives_both_branches(tmp_root, monkeypatch, capsys):
    sub = page_identity("BVsub", 0, 111, "p0")
    aud = page_identity("BVaud", 0, 222, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(sub, duration_s=5, title="has-sub"))
    store.upsert(_row(aud, duration_s=8, title="needs-asr"))

    transcribe_calls: list[str] = []

    def fake_transcribe(audio_path, model_name=None):
        transcribe_calls.append(audio_path)
        return [{"start": 0.0, "end": 1.0, "text": "asr-text"}]

    monkeypatch.setattr(asr_mod, "transcribe", fake_transcribe)
    transport = RouterTransport(
        {
            "finger/spi": [SPI_OK],
            "nav": [nav_ok(), nav_response()],
            "player/wbi/v2": [player_ok([sub_entry()]), player_ok([])],
            "aisubtitle.hdslb.com": [(200, dict(SAMPLE_DOC))],
            "/x/player/wbi/playurl": [playurl_ok()],
        },
        stream_routes={f"{STREAM_HOST}/a30216.m4s": AUDIO_BYTES},
    )
    _patch_cli(monkeypatch, transport)

    rc = main(["pilot", "--n", "2", "--archive-root", tmp_root, "--sessdata", "SECRET-SESS"])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert "SECRET-SESS" not in captured.out
    assert "SECRET-SESS" not in captured.err
    assert "pilot batch branches: subtitle=1, audio-asr=1" in captured.out
    assert "pilot coverage branches: subtitle=1, audio-asr=1" in captured.out

    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[sub.work_id]["status"] == "archived"
    assert loaded[aud.work_id]["status"] == "archived"
    assert loaded[aud.work_id].get("audio_path")
    assert os.path.isfile(os.path.join(tmp_root, loaded[sub.work_id]["srt_path"]))
    assert os.path.isfile(os.path.join(tmp_root, loaded[aud.work_id]["srt_path"]))
    # post-archive audio reclaim: m4a removed once the row is archived
    assert not os.path.exists(os.path.join(tmp_root, loaded[aud.work_id]["audio_path"]))
    assert transcribe_calls == [
        os.path.join(tmp_root, "audio", f"{artifact_stem(aud)}.m4a")
    ]
    player = [c for c in transport.calls if "player/wbi/v2" in c["url"]]
    assert [c["params"]["cid"] for c in player] == [111, 222]
    sess_calls = [c for c in transport.calls if c["cookies"].get("SESSDATA") == "SECRET-SESS"]
    assert sess_calls
    with open(os.path.join(tmp_root, "manifest", "manifest.jsonl"), encoding="utf-8") as fh:
        ledger = fh.read()
    assert "SECRET-SESS" not in ledger
    assert "SECRET-SESS" not in json.dumps(loaded)


def test_cli_pilot_multipart_processes_every_page(tmp_root, monkeypatch, capsys):
    p0 = page_identity("BVmulti", 0, 111, "p0")
    p1 = page_identity("BVmulti", 1, 222, "p1")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(p0, duration_s=2, title="multi"))
    store.upsert(_row(p1, duration_s=50, title="multi"))

    monkeypatch.setattr(
        asr_mod,
        "transcribe",
        lambda audio_path, model_name=None: [
            {"start": 0.0, "end": 1.0, "text": "page-asr"}
        ],
    )
    transport = RouterTransport(
        {
            "finger/spi": [SPI_OK],
            "nav": [nav_ok(), nav_response()],
            "player/wbi/v2": [player_ok([sub_entry()]), player_ok([])],
            "aisubtitle.hdslb.com": [(200, dict(SAMPLE_DOC))],
            "/x/player/wbi/playurl": [playurl_ok()],
        },
        stream_routes={f"{STREAM_HOST}/a30216.m4s": AUDIO_BYTES},
    )
    _patch_cli(monkeypatch, transport)
    rc = main(["pilot", "--n", "1", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[p0.work_id]["status"] == "archived"
    assert loaded[p1.work_id]["status"] == "archived"
    player_cids = [
        c["params"]["cid"]
        for c in transport.calls
        if "player/wbi/v2" in c["url"]
    ]
    assert player_cids == [111, 222]


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

    monkeypatch.setattr(
        asr_mod,
        "transcribe",
        lambda path, model_name=None: [
            {"start": 0.0, "end": 1.0, "text": "asr-text"}
        ],
    )
    monkeypatch.setattr(
        audio_mod,
        "download_audio",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("audio_ok must not download again")
        ),
    )
    _patch_cli(monkeypatch, RouterTransport({}))

    rc = main(
        [
            "pilot",
            "--n",
            "1",
            "--max-audio-gb",
            "0.000001",
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
    monkeypatch.setattr(
        asr_mod,
        "transcribe",
        lambda audio_path, model_name=None: [
            {"start": 0.0, "end": 1.0, "text": "only-asr"}
        ],
    )
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


def test_cli_pilot_summary_separates_batch_and_prior_coverage(
    tmp_root, monkeypatch, capsys
):
    prior = page_identity("BVprior", 0, 100, "p0")
    sub = page_identity("BVsub", 0, 111, "p0")
    aud = page_identity("BVaud", 0, 222, "p0")
    store = ManifestStore(root=tmp_root)
    prior_row = _row(prior, duration_s=1, title="prior-asr")
    prior_row.update({"status": "archived", "audio_path": "audio/prior.m4a"})
    store.upsert(prior_row)
    store.upsert(_row(sub, duration_s=5, title="has-sub"))
    store.upsert(_row(aud, duration_s=8, title="needs-asr"))

    monkeypatch.setattr(
        asr_mod,
        "transcribe",
        lambda audio_path, model_name=None: [
            {"start": 0.0, "end": 1.0, "text": "asr-text"}
        ],
    )
    _patch_cli(monkeypatch, _mixed_transport())

    assert main(["pilot", "--n", "2", "--archive-root", tmp_root]) == 0
    captured = capsys.readouterr()
    assert "pilot batch branches: subtitle=1, audio-asr=1" in captured.out
    assert "pilot coverage branches: subtitle=1, audio-asr=2" in captured.out


def test_cli_pilot_completed_rerun_skips_archived(tmp_root, monkeypatch, capsys):
    sub = page_identity("BVsub", 0, 111, "p0")
    aud = page_identity("BVaud", 0, 222, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(sub, duration_s=5, title="has-sub"))
    store.upsert(_row(aud, duration_s=8, title="needs-asr"))
    transcribe_calls: list[str] = []

    def fake_transcribe(audio_path, model_name=None):
        transcribe_calls.append(audio_path)
        return [{"start": 0.0, "end": 1.0, "text": "asr-text"}]

    monkeypatch.setattr(asr_mod, "transcribe", fake_transcribe)
    _patch_cli(monkeypatch, _mixed_transport())
    assert main(["pilot", "--n", "2", "--archive-root", tmp_root]) == 0
    capsys.readouterr()

    manifest_path = os.path.join(tmp_root, "manifest", "manifest.jsonl")
    with open(manifest_path, encoding="utf-8") as fh:
        first_ledger = fh.read()
    first_files = []
    for dirpath, _dirs, files in os.walk(tmp_root):
        for name in files:
            first_files.append(os.path.join(dirpath, name))
    first_files.sort()
    first_calls = list(transcribe_calls)

    rc = main(["pilot", "--n", "2", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert "already archived" in captured.out or "already archived" in captured.err
    with open(manifest_path, encoding="utf-8") as fh:
        assert fh.read() == first_ledger
    rerun_files = []
    for dirpath, _dirs, files in os.walk(tmp_root):
        for name in files:
            rerun_files.append(os.path.join(dirpath, name))
    assert sorted(rerun_files) == first_files
    assert transcribe_calls == first_calls
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[sub.work_id]["status"] == "archived"
    assert loaded[aud.work_id]["status"] == "archived"


def test_cli_pilot_missing_asr_dependency_does_not_archive(tmp_root, monkeypatch, capsys):
    from bili_asr.asr import ASRDependencyError

    sub = page_identity("BVsub", 0, 111, "p0")
    aud = page_identity("BVaud", 0, 222, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(sub, duration_s=5, title="has-sub"))
    store.upsert(_row(aud, duration_s=8, title="needs-asr"))
    hint = 'pip install -e "bilibili-asr-archive/[asr]"'

    def missing_asr(audio_path, model_name=None):
        raise ASRDependencyError(
            f"SenseVoice support is not installed; run: {hint}"
        )

    monkeypatch.setattr(asr_mod, "transcribe", missing_asr)
    _patch_cli(monkeypatch, _mixed_transport())
    rc = main(["pilot", "--n", "2", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 1
    assert hint in captured.err
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[sub.work_id]["status"] == "archived"
    assert loaded[aud.work_id]["status"] != "archived"
    assert not loaded[aud.work_id].get("srt_path")


def test_cli_pilot_resume_after_partial_asr_counts_archived_subtitle(
    tmp_root, monkeypatch, capsys
):
    from bili_asr.asr import ASRDependencyError

    sub = page_identity("BVsub", 0, 111, "p0")
    aud = page_identity("BVaud", 0, 222, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(sub, duration_s=5, title="has-sub"))
    store.upsert(_row(aud, duration_s=8, title="needs-asr"))

    def missing_asr(audio_path, model_name=None):
        raise ASRDependencyError("SenseVoice support is not installed")

    monkeypatch.setattr(asr_mod, "transcribe", missing_asr)
    _patch_cli(monkeypatch, _mixed_transport())
    assert main(["pilot", "--n", "2", "--archive-root", tmp_root]) == 1
    capsys.readouterr()

    monkeypatch.setattr(
        asr_mod,
        "transcribe",
        lambda audio_path, model_name=None: [
            {"start": 0.0, "end": 1.0, "text": "asr-text"}
        ],
    )
    _patch_cli(monkeypatch, _mixed_transport())
    rc = main(["pilot", "--n", "2", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert "missing branch coverage" not in captured.err
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[sub.work_id]["status"] == "archived"
    assert loaded[aud.work_id]["status"] == "archived"


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


def test_cli_pilot_asr_model_error_names_exception(tmp_root, monkeypatch, capsys):
    from bili_asr.asr import ASRModelError

    sub = page_identity("BVsub", 0, 111, "p0")
    aud = page_identity("BVaud", 0, 222, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(sub, duration_s=5, title="has-sub"))
    store.upsert(_row(aud, duration_s=8, title="needs-asr"))

    def boom(audio_path, model_name=None):
        raise ASRModelError("model failed")

    monkeypatch.setattr(asr_mod, "transcribe", boom)
    _patch_cli(monkeypatch, _mixed_transport())
    rc = main(["pilot", "--n", "2", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 1
    assert "ASRModelError" in captured.err
    assert "unexpected error" not in captured.err
    assert "pilot batch branches:" in captured.out
    assert "pilot coverage branches:" in captured.out


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
    rc = main(["pilot", "--n", "2", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 2
    assert "risk-control ceiling" in captured.err
    assert "pilot batch branches:" in captured.out
    assert "pilot coverage branches:" in captured.out
