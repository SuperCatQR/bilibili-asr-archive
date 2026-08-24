"""Executable mixed-branch pilot: fake HTTP + stubbed ASR, no live network."""

from __future__ import annotations

import json
import os

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
    assert "subtitle=1" in captured.out
    assert "audio-asr=1" in captured.out

    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[sub.work_id]["status"] == "archived"
    assert loaded[aud.work_id]["status"] == "archived"
    assert loaded[aud.work_id].get("audio_path")
    assert os.path.isfile(os.path.join(tmp_root, loaded[sub.work_id]["srt_path"]))
    assert os.path.isfile(os.path.join(tmp_root, loaded[aud.work_id]["srt_path"]))
    assert os.path.isfile(os.path.join(tmp_root, loaded[aud.work_id]["audio_path"]))
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
