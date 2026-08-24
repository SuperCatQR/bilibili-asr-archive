"""Two-page fixtures for list_pages, cid threading, and independent status."""

from __future__ import annotations

import os

import pytest

from bili_asr import audio
from bili_asr import bili_client as bc
from bili_asr import subtitles
from bili_asr.manifest import ManifestStore
from bili_asr.page_identity import artifact_stem, page_identity

from test_audio import (
    AUDIO_BYTES,
    STREAM_HOST,
    make_client as make_audio_client,
    nav_response,
    playurl_ok,
)
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
        "nav": [nav_ok(), nav_ok()],
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
            "nav": [nav_response(), nav_response()],
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


def test_harvest_skips_unresolved_row(tmp_root):
    store = ManifestStore(root=tmp_root)
    store.upsert({
        "bvid": BVID, "status": "meta_ok", "title": "legacy",
        "duration_s": 1, "pubdate": 1, "unresolved": True,
        "unresolved_reason": "ambiguous_bare_bvid",
        "excluded_from_page_processing": True,
    })
    from bili_asr.cli import _is_excluded
    assert _is_excluded(store.get(BVID))
    todo = [
        (k, e) for k, e in store.load().items()
        if e.get("status") == "meta_ok" and not _is_excluded(e)
    ]
    assert todo == []
