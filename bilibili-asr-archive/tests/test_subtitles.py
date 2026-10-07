"""Unit tests for subtitle probe/harvest: mocked transport only, no network.

The ``probe-subs`` / ``harvest-subs`` command surface moved to the SQLite
transcript path and is covered by ``tests/test_subtitle_cli.py``; what stays
here is the legacy client and harvest-helper layer that the untouched ASR,
pilot, run, and coordinator paths still call.
"""

from __future__ import annotations

import json
import os

from bili_asr import bili_client as bc
from bili_asr import subtitles
from bili_asr.manifest import ManifestStore
from tests.support.subtitles import FastSleeper, IMG_KEY, RouterTransport, SAMPLE_DOC, SPI_OK, SUBTITLE_URL, SUB_KEY, make_client, nav_ok, player_ok, sub_entry

API = "https://api.bilibili.com"










def pagelist_ok(cid=111):
    return (200, {"code": 0, "data": [{"cid": cid, "page": 1}]})








# --------------------------------------------------------- probe (Path A/B)

def test_probe_subs_empty_without_cookie():
    client = make_client({
        "nav": [nav_ok()],
        "pagelist": [pagelist_ok(cid=111)],
        "player/wbi/v2": [player_ok([])],
    })
    subs = client.probe_subs("BV1mk8W6dEyx")
    assert subs == []


def test_probe_subs_signed_request_and_entries():
    client = make_client({
        "nav": [nav_ok()],
        "pagelist": [pagelist_ok(cid=111)],
        "player/wbi/v2": [player_ok([sub_entry()])],
    })
    subs = client.probe_subs("BV1mk8W6dEyx")
    assert [s["lan"] for s in subs] == ["ai-zh"]
    player_call = [c for c in client.transport.calls
                   if "player/wbi/v2" in c["url"]][0]
    assert player_call["params"]["cid"] == 111
    assert player_call["params"]["bvid"] == "BV1mk8W6dEyx"
    assert "w_rid" in player_call["params"] and "wts" in player_call["params"]
    assert "SESSDATA" not in player_call["cookies"]


def test_probe_subs_sessdata_sent_as_cookie_never_in_params():
    client = make_client({
        "nav": [nav_ok()],
        "pagelist": [pagelist_ok(cid=111)],
        "player/wbi/v2": [player_ok([sub_entry()])],
    }, sessdata="SECRET-SESS")
    client.probe_subs("BV1mk8W6dEyx")
    player_call = [c for c in client.transport.calls
                   if "player/wbi/v2" in c["url"]][0]
    assert player_call["cookies"].get("SESSDATA") == "SECRET-SESS"
    assert "SECRET-SESS" not in json.dumps(player_call["params"])


# ------------------------------------------------------------- SRT conversion



def test_json_to_srt():
    srt = subtitles.json_to_srt(SAMPLE_DOC)
    assert srt == (
        "1\n"
        "00:00:01,000 --> 00:00:02,500\n"
        "你好\n"
        "\n"
        "2\n"
        "00:00:02,500 --> 00:00:04,000\n"
        "世界\n"
        "\n"
        "3\n"
        "00:01:01,250 --> 00:01:02,000\n"
        "第三句\n"
    )


def test_json_to_srt_empty():
    assert subtitles.json_to_srt({"body": []}) == ""


def test_pick_subtitle_prefers_ai_zh():
    entries = [
        sub_entry(lan="en"),
        sub_entry(lan="ai-zh", lan_doc="中文（自动生成）"),
        sub_entry(lan="zh-CN", lan_doc="中文（人做）"),
    ]
    assert subtitles.pick_subtitle(entries)["lan"] == "ai-zh"


# ---------------------------------------------------------------- harvest

def seed_legacy(store, *entries):
    store.load()
    data = dict(store._entries)
    for entry in entries:
        data[entry.get("work_id") or entry["bvid"]] = entry
    store.save(data)


def manifest_with(tmp_root, statuses=("meta_ok",)):
    store = ManifestStore(root=tmp_root)
    rows = []
    for i, st in enumerate(statuses):
        bvid = f"BV1test{i:02d}"
        rows.append({"bvid": bvid, "status": st, "title": f"t {bvid}",
                     "duration_s": 100, "pubdate": 1})
    seed_legacy(store, *rows)
    return store


def test_harvest_empty_marks_needs_audio(tmp_root):
    store = manifest_with(tmp_root)
    store.upsert({
        **store.get("BV1test00"),
        "last_api_error_code": -400,
    })
    client = make_client({
        "nav": [nav_ok()],
        "pagelist": [pagelist_ok()],
        "player/wbi/v2": [player_ok([])],
    })
    status = subtitles.harvest_subtitle(client, "BV1test00", store, tmp_root)
    assert status == "needs_audio"
    entry = store.get("BV1test00:p0")
    assert entry["status"] == "needs_audio"
    assert "last_api_error_code" not in entry


def test_harvest_downloads_shortlived_url_same_run(tmp_root):
    """Subtitle JSON must be fetched in the same run as the probe, using
    exactly the URL the probe returned (short-lived signed URL), and the
    URL must not be persisted into the manifest."""
    store = manifest_with(tmp_root)
    store.upsert({
        **store.get("BV1test00"),
        "last_api_error_code": -403,
    })
    doc = dict(SAMPLE_DOC)
    client = make_client({
        "nav": [nav_ok()],
        "pagelist": [pagelist_ok()],
        "player/wbi/v2": [player_ok([sub_entry()])],
        "aisubtitle.hdslb.com": [(200, doc)],
    })
    status = subtitles.harvest_subtitle(client, "BV1test00", store, tmp_root)
    assert status == "subtitle_done"
    entry = store.get("BV1test00:p0")
    assert entry["status"] == "subtitle_done"
    assert "last_api_error_code" not in entry
    # downloaded URL = the probe-provided URL, normalized to https
    dl = [c for c in client.transport.calls if "aisubtitle" in c["url"]]
    assert len(dl) == 1
    assert dl[0]["url"] == "https:" + SUBTITLE_URL
    # download immediately followed the probe (same run, same client)
    player_idx = [i for i, c in enumerate(client.transport.calls)
                  if "player/wbi/v2" in c["url"]][0]
    assert dl[0] is client.transport.calls[player_idx + 1]
    # raw + srt artifacts written
    raw_path = os.path.join(tmp_root, "subtitles", "raw", "BV1test00.p0.json")
    srt_path = os.path.join(tmp_root, "transcripts", "BV1test00.p0", "bundle.srt")
    assert json.load(open(raw_path, encoding="utf-8")) == doc
    assert "你好" in open(srt_path, encoding="utf-8").read()
    # short-lived URL never persisted
    manifest_text = open(store.path, encoding="utf-8").read()
    assert "hdslb" not in manifest_text
    assert "subtitle_url" not in manifest_text
