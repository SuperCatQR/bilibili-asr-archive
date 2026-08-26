"""Two-page fixtures for list_pages, cid threading, and independent status."""

from __future__ import annotations

import os

import pytest

from bili_asr import audio
from bili_asr import bili_client as bc
from bili_asr import subtitles
from bili_asr.cli import main
from bili_asr.manifest import ManifestStore
from bili_asr.page_identity import artifact_stem, page_identity

from test_audio import (
    AUDIO_BYTES,
    SPI_OK,
    STREAM_HOST,
    RouterTransport as AudioRouter,
    make_client as make_audio_client,
    nav_response,
    playurl_ok,
)
from test_subtitles import RouterTransport as SubRouter
from test_subtitles import (
    SAMPLE_DOC,
    make_client as make_sub_client,
    nav_ok,
    player_ok,
    sub_entry,
)

BVID = "BV1multi"


def pagelist_two(cid0=111, cid1=222):
    return (
        200,
        {
            "code": 0,
            "data": [
                {"cid": cid0, "page": 1, "part": "p0"},
                {"cid": cid1, "page": 2, "part": "p1"},
            ],
        },
    )


def test_list_pages_zero_based_indices():
    client = make_sub_client({
        "nav": [nav_ok()],
        "pagelist": [pagelist_two(11, 22)],
    })
    pages = client.list_pages(BVID)
    assert [p.page_index for p in pages] == [0, 1]
    assert [p.cid for p in pages] == [11, 22]
    assert [p.work_id for p in pages] == [f"{BVID}:p0", f"{BVID}:p1"]
    assert pages[0].page_label == "p0"


def test_list_pages_missing_cid_is_stop():
    client = make_sub_client({
        "pagelist": [(200, {"code": 0, "data": [{"page": 1, "part": "x"}]})],
    })
    with pytest.raises(ValueError, match="missing cid"):
        client.list_pages(BVID)


def test_probe_subs_none_cid_on_two_page_raises():
    client = make_sub_client({"pagelist": [pagelist_two()]})
    with pytest.raises(bc.AmbiguousPageError):
        client.probe_subs(BVID)
    player = [c for c in client.transport.calls if "player/wbi/v2" in c["url"]]
    assert player == []


def test_probe_subs_uses_explicit_cid_not_pages0():
    client = make_sub_client({
        "nav": [nav_ok()],
        "pagelist": [pagelist_two(111, 222)],
        "player/wbi/v2": [player_ok([sub_entry()])],
    })
    client.probe_subs(BVID, cid=222)
    player = [c for c in client.transport.calls if "player/wbi/v2" in c["url"]][0]
    assert player["params"]["cid"] == 222
    pagelist_calls = [c for c in client.transport.calls if "pagelist" in c["url"]]
    assert pagelist_calls == []


def test_fetch_playurl_audio_none_cid_on_two_page_raises():
    client = make_audio_client({"pagelist": [pagelist_two()]})
    with pytest.raises(bc.AmbiguousPageError):
        client.fetch_playurl_audio(BVID)


def test_fetch_playurl_audio_uses_explicit_cid():
    client = make_audio_client({
        "pagelist": [pagelist_two(111, 222)],
        "/x/player/wbi/playurl": [playurl_ok()],
    })
    client.fetch_playurl_audio(BVID, cid=222)
    play = [c for c in client.transport.calls if "playurl" in c["url"]][0]
    assert play["params"]["cid"] == 222


def test_harvest_pages_independent_status(tmp_root):
    store = ManifestStore(root=tmp_root)
    p0 = page_identity(BVID, 0, 111, "p0")
    p1 = page_identity(BVID, 1, 222, "p1")
    store.upsert({
        "bvid": BVID, "work_id": p0.work_id, "page_index": 0, "cid": 111,
        "status": "meta_ok", "title": "multi", "duration_s": 1, "pubdate": 1,
    })
    store.upsert({
        "bvid": BVID, "work_id": p1.work_id, "page_index": 1, "cid": 222,
        "status": "meta_ok", "title": "multi", "duration_s": 1, "pubdate": 1,
    })
    client = make_sub_client({
        "nav": [nav_ok()],
        "player/wbi/v2": [
            player_ok([sub_entry()]),
            player_ok([]),
        ],
        "aisubtitle.hdslb.com": [(200, dict(SAMPLE_DOC))],
    })
    assert subtitles.harvest_subtitle(client, p0, store, tmp_root) == "subtitle_done"
    assert subtitles.harvest_subtitle(client, p1, store, tmp_root) == "needs_audio"
    assert store.get(p0.work_id)["status"] == "subtitle_done"
    assert store.get(p1.work_id)["status"] == "needs_audio"
    stem0 = artifact_stem(p0)
    assert os.path.exists(os.path.join(tmp_root, "transcripts", "srt", f"{stem0}.srt"))
    player_cids = [
        c["params"]["cid"]
        for c in client.transport.calls
        if "player/wbi/v2" in c["url"]
    ]
    assert player_cids == [111, 222]


def test_download_pages_independent_status(tmp_root):
    store = ManifestStore(root=tmp_root)
    p0 = page_identity(BVID, 0, 111)
    p1 = page_identity(BVID, 1, 222)
    for page in (p0, p1):
        store.upsert({
            "bvid": BVID, "work_id": page.work_id, "page_index": page.page_index,
            "cid": page.cid, "status": "needs_audio", "title": "multi",
            "duration_s": 1, "pubdate": 1,
        })
    client = make_audio_client(
        {
            "nav": [nav_response()],
            "/x/player/wbi/playurl": [playurl_ok(), playurl_ok()],
        },
        stream_routes={f"{STREAM_HOST}/a30216.m4s": AUDIO_BYTES},
    )
    out0 = os.path.join(tmp_root, "audio", f"{artifact_stem(p0)}.m4a")
    out1 = os.path.join(tmp_root, "audio", f"{artifact_stem(p1)}.m4a")
    audio.download_audio(client, p0, out0, store=store)
    # p0 complete must not suppress p1
    audio.download_audio(client, p1, out1, store=store)
    assert store.get(p0.work_id)["status"] == "audio_ok"
    assert store.get(p1.work_id)["status"] == "audio_ok"
    assert os.path.exists(out0) and os.path.exists(out1)
    play_cids = [
        c["params"]["cid"]
        for c in client.transport.calls
        if "playurl" in c["url"]
    ]
    assert play_cids == [111, 222]


def test_cli_harvest_skips_unresolved_and_processes_other_page(
    tmp_root, monkeypatch
):
    store = ManifestStore(root=tmp_root)
    store.upsert({
        "bvid": BVID, "status": "meta_ok", "title": "legacy",
        "duration_s": 1, "pubdate": 1, "unresolved": True,
        "unresolved_reason": "ambiguous_bare_bvid",
        "excluded_from_page_processing": True,
    })
    ok = page_identity("BV1ok", 0, 333)
    store.upsert({
        "bvid": "BV1ok", "work_id": ok.work_id, "page_index": 0, "cid": 333,
        "status": "meta_ok", "title": "ok", "duration_s": 1, "pubdate": 1,
    })
    transport = SubRouter({
        "finger/spi": [SPI_OK],
        "nav": [nav_ok()],
        "player/wbi/v2": [player_ok([])],
    })
    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
    monkeypatch.setattr(bc, "default_sleeper", lambda _s=None: None)
    monkeypatch.setattr("bili_asr.cli.time.sleep", lambda _seconds: None)
    rc = main(["harvest-subs", "--archive-root", tmp_root])
    assert rc == 0
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[BVID]["unresolved"] is True
    assert loaded[BVID]["status"] == "meta_ok"
    assert "work_id" not in loaded[BVID]
    assert loaded[ok.work_id]["status"] == "needs_audio"
    player = [c for c in transport.calls if "player/wbi/v2" in c["url"]]
    assert len(player) == 1
    assert player[0]["params"]["cid"] == 333


def test_cli_download_skips_unresolved_and_processes_other_page(
    tmp_root, monkeypatch
):
    store = ManifestStore(root=tmp_root)
    store.upsert({
        "bvid": BVID, "status": "needs_audio", "title": "legacy",
        "duration_s": 1, "pubdate": 1, "unresolved": True,
        "unresolved_reason": "ambiguous_bare_bvid",
        "excluded_from_page_processing": True,
    })
    ok = page_identity("BV1ok", 1, 444)
    store.upsert({
        "bvid": "BV1ok", "work_id": ok.work_id, "page_index": 1, "cid": 444,
        "status": "needs_audio", "title": "ok", "duration_s": 1, "pubdate": 1,
    })
    transport = AudioRouter(
        {
            "finger/spi": [SPI_OK],
            "nav": [nav_response()],
            "/x/player/wbi/playurl": [playurl_ok()],
        },
        stream_routes={f"{STREAM_HOST}/a30216.m4s": AUDIO_BYTES},
    )
    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
    monkeypatch.setattr(bc, "default_sleeper", lambda _s=None: None)
    monkeypatch.setattr("bili_asr.cli.time.sleep", lambda _seconds: None)
    rc = main(["download-audio", "--missing-subs", "--archive-root", tmp_root])
    assert rc == 0
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[BVID]["status"] == "needs_audio"
    assert loaded[BVID]["unresolved"] is True
    assert loaded[ok.work_id]["status"] == "audio_ok"
    play = [c for c in transport.calls if "playurl" in c["url"]]
    assert len(play) == 1
    assert play[0]["params"]["cid"] == 444
    assert not os.path.exists(os.path.join(tmp_root, "audio", f"{BVID}.m4a"))


def test_cli_download_audio_bvid_unresolved_stops(tmp_root, monkeypatch, capsys):
    store = ManifestStore(root=tmp_root)
    store.upsert({
        "bvid": BVID, "status": "needs_audio", "title": "legacy",
        "duration_s": 1, "pubdate": 1, "unresolved": True,
        "unresolved_reason": "ambiguous_bare_bvid",
        "excluded_from_page_processing": True,
    })
    monkeypatch.setattr(bc, "build_default_transport", lambda: AudioRouter({}))
    monkeypatch.setattr(bc, "default_sleeper", lambda _s=None: None)
    rc = main(["download-audio", "--bvid", BVID, "--archive-root", tmp_root])
    assert rc == 1
    err = capsys.readouterr().err
    assert "unresolved" in err
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[BVID]["unresolved"] is True
    assert "work_id" not in loaded[BVID]
    assert not os.path.exists(os.path.join(tmp_root, "audio", f"{BVID}.m4a"))
    assert not os.path.exists(os.path.join(tmp_root, "audio", f"{BVID}.p0.m4a"))


def test_cli_harvest_subs_bvid_unresolved_stops(tmp_root, monkeypatch, capsys):
    store = ManifestStore(root=tmp_root)
    store.upsert({
        "bvid": BVID, "status": "meta_ok", "title": "legacy",
        "duration_s": 1, "pubdate": 1, "unresolved": True,
        "unresolved_reason": "ambiguous_bare_bvid",
        "excluded_from_page_processing": True,
    })
    monkeypatch.setattr(bc, "build_default_transport", lambda: SubRouter({}))
    monkeypatch.setattr(bc, "default_sleeper", lambda _s=None: None)
    rc = main(["harvest-subs", "--bvid", BVID, "--archive-root", tmp_root])
    assert rc == 1
    err = capsys.readouterr().err
    assert "unresolved" in err
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[BVID]["unresolved"] is True
    assert "work_id" not in loaded[BVID]


def test_harvest_subtitle_str_skips_unresolved(tmp_root):
    store = ManifestStore(root=tmp_root)
    store.upsert({
        "bvid": BVID, "status": "meta_ok", "unresolved": True,
        "excluded_from_page_processing": True,
    })
    client = make_sub_client({"pagelist": [pagelist_two()]})
    with pytest.raises(ValueError, match="unresolved"):
        subtitles.harvest_subtitle(client, BVID, store, tmp_root)
    pagelist = [c for c in client.transport.calls if "pagelist" in c["url"]]
    assert pagelist == []


def test_asr_pending_p0_failure_does_not_suppress_p1(tmp_root, monkeypatch):
    from bili_asr import asr as asr_mod
    from bili_asr.archive import write_archive

    store = ManifestStore(root=tmp_root)
    p0 = page_identity(BVID, 0, 111)
    p1 = page_identity(BVID, 1, 222)
    for page, status in ((p0, "audio_ok"), (p1, "audio_ok")):
        store.upsert({
            "bvid": BVID, "work_id": page.work_id, "page_index": page.page_index,
            "cid": page.cid, "status": status, "title": "multi",
            "duration_s": 1, "pubdate": 1, "pubdate_str": "2026-01-02",
            "audio_path": f"audio/{artifact_stem(page)}.m4a",
        })
    os.makedirs(os.path.join(tmp_root, "audio"), exist_ok=True)
    for page in (p0, p1):
        open(os.path.join(tmp_root, "audio", f"{artifact_stem(page)}.m4a"), "wb").close()

    def fake_transcribe(path):
        if artifact_stem(p0) in path:
            raise RuntimeError("p0 failed")
        return [{"start": 0, "end": 1, "text": "p1"}]

    monkeypatch.setattr(asr_mod, "transcribe", fake_transcribe)
    rc = main(["asr", "--pending", "--archive-root", tmp_root])
    assert rc == 1
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[p0.work_id]["status"] == "audio_ok"
    assert loaded[p1.work_id]["status"] == "archived"
    assert loaded[p1.work_id]["srt_path"] != loaded[p0.work_id].get("srt_path")
    paths = write_archive(
        tmp_root,
        loaded[p1.work_id],
        [{"start": 0, "end": 1, "text": "p1"}],
        source="asr",
    )
    assert os.path.exists(os.path.join(tmp_root, paths["srt_path"]))
