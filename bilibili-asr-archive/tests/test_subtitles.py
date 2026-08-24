"""Unit tests for subtitle probe/harvest: mocked transport only, no network."""

from __future__ import annotations

import json
import os

import pytest

from bili_asr import bili_client as bc
from bili_asr import subtitles
from bili_asr.cli import main
from bili_asr.manifest import ManifestStore

API = "https://api.bilibili.com"
SPI_OK = (200, {"code": 0, "data": {"b_3": "B3", "b_4": "B4"}})

IMG_KEY = "7cd084941338484aae1ad9425b84077c"
SUB_KEY = "4932caff0ff746eab6f01bf08b70ac45"

SUBTITLE_URL = "//aisubtitle.hdslb.com/bfs/ai_subtitle/prod/SHORTLIVED.json"


class RouterTransport:
    """Routes by URL substring to scripted (status, body) queues."""

    def __init__(self, routes: dict[str, list]):
        self.routes = routes
        self.calls: list[dict] = []

    def get_json(self, url, params=None, headers=None, cookies=None, timeout=None):
        self.calls.append(
            {
                "url": url,
                "params": dict(params or {}),
                "headers": dict(headers or {}),
                "cookies": dict(cookies or {}),
            }
        )
        for frag, queue in self.routes.items():
            if frag in url:
                if not queue:
                    raise AssertionError(f"queue for {frag!r} exhausted")
                item = queue.pop(0)
                if isinstance(item, Exception):
                    raise item
                return item
        raise AssertionError(f"no route for {url}")


class FastSleeper:
    def __init__(self):
        self.waits = []

    def __call__(self, seconds):
        self.waits.append(seconds)


def nav_ok():
    return (
        200,
        {
            "code": -101,  # spike: wbi_img populated even when not logged in
            "data": {
                "wbi_img": {
                    "img_url": f"https://i0.hdslb.com/bfs/wbi/{IMG_KEY}.png",
                    "sub_url": f"https://i0.hdslb.com/bfs/wbi/{SUB_KEY}.png",
                }
            },
        },
    )


def pagelist_ok(cid=111):
    return (200, {"code": 0, "data": [{"cid": cid, "page": 1}]})


def player_ok(subtitles_list, extra_data=None):
    data = {
        "subtitle": {"subtitles": subtitles_list, "allow_submit": False},
        "need_login_subtitle": not subtitles_list,
    }
    if extra_data:
        data.update(extra_data)
    return (200, {"code": 0, "data": data})


def sub_entry(lan="ai-zh", lan_doc="中文（自动生成）", url=SUBTITLE_URL):
    return {"lan": lan, "lan_doc": lan_doc, "subtitle_url": url,
            "ai_type": 1, "ai_status": 2}


def make_client(routes, sessdata=None):
    routes.setdefault("finger/spi", [SPI_OK])
    return bc.BiliClient(
        transport=RouterTransport(routes),
        sleeper=FastSleeper(),
        jitter=lambda: 0.0,
        sessdata=sessdata,
    )


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

SAMPLE_DOC = {
    "body": [
        {"from": 1.0, "to": 2.5, "content": "你好"},
        {"from": 2.5, "to": 4.0, "content": "世界"},
        {"from": 61.25, "to": 62.0, "content": "第三句"},
    ]
}


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
    srt_path = os.path.join(tmp_root, "transcripts", "srt", "BV1test00.p0.srt")
    assert json.load(open(raw_path, encoding="utf-8")) == doc
    assert "你好" in open(srt_path, encoding="utf-8").read()
    # short-lived URL never persisted
    manifest_text = open(store.path, encoding="utf-8").read()
    assert "hdslb" not in manifest_text
    assert "subtitle_url" not in manifest_text


# ---------------------------------------------------------------- CLI

def _cli_routes(monkeypatch, transport):
    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
    monkeypatch.setattr(bc, "default_sleeper", lambda: FastSleeper())


def test_cli_probe_subs_empty(tmp_root, monkeypatch, capsys):
    transport = RouterTransport({
        "finger/spi": [SPI_OK],
        "nav": [nav_ok()],
        "pagelist": [pagelist_ok()],
        "player/wbi/v2": [player_ok([])],
    })
    _cli_routes(monkeypatch, transport)
    rc = main(["probe-subs", "--bvid", "BV1mk8W6dEyx",
               "--archive-root", tmp_root])
    assert rc == 0
    out = capsys.readouterr().out
    assert "no subtitles" in out
    assert "needs_audio" in out


def test_cli_probe_subs_unknown_bvid_api_error_does_not_create_row(
    tmp_root, monkeypatch, capsys
):
    sentinel_cookie = "PROBE-SESSDATA-SECRET"
    monkeypatch.setenv("BILI_SESSDATA", sentinel_cookie)
    transport = RouterTransport({
        "finger/spi": [SPI_OK],
        "pagelist": [(200, {"code": -99999})],
    })
    _cli_routes(monkeypatch, transport)

    rc = main([
        "probe-subs", "--bvid", "BV1unknown",
        "--archive-root", tmp_root,
    ])

    assert rc == 1
    assert ManifestStore(root=tmp_root).get("BV1unknown") is None
    assert not os.path.exists(ManifestStore(root=tmp_root).path)
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert sentinel_cookie not in output
    assert "http" not in output.lower()


def test_cli_probe_subs_transport_error_redacts_exception_message(
    tmp_root, monkeypatch, capsys
):
    sentinel = "SESSDATA=PROBE-SECRET https://cdn.example/sub.json?token=SIGNED"
    transport = RouterTransport({
        "finger/spi": [SPI_OK],
        "pagelist": [RuntimeError(sentinel)] * 5,
    })
    _cli_routes(monkeypatch, transport)

    rc = main([
        "probe-subs", "--bvid", "BV1transport",
        "--archive-root", tmp_root,
    ])

    assert rc == 2
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "RuntimeError" in output
    assert "PROBE-SECRET" not in output
    assert "SIGNED" not in output
    assert not os.path.exists(ManifestStore(root=tmp_root).path)


def test_cli_probe_subs_lists_entries(tmp_root, monkeypatch, capsys):
    transport = RouterTransport({
        "finger/spi": [SPI_OK],
        "nav": [nav_ok()],
        "pagelist": [pagelist_ok()],
        "player/wbi/v2": [player_ok([sub_entry()])],
    })
    _cli_routes(monkeypatch, transport)
    rc = main(["probe-subs", "--bvid", "BV1mk8W6dEyx",
               "--archive-root", tmp_root])
    assert rc == 0
    out = capsys.readouterr().out
    assert "ai-zh" in out


def test_cli_harvest_subs_marks_needs_audio(tmp_root, monkeypatch, capsys):
    manifest_with(tmp_root)
    transport = RouterTransport({
        "finger/spi": [SPI_OK],
        "nav": [nav_ok()],
        "pagelist": [pagelist_ok()],
        "player/wbi/v2": [player_ok([])],
    })
    _cli_routes(monkeypatch, transport)
    rc = main(["harvest-subs", "--archive-root", tmp_root])
    assert rc == 0
    store = ManifestStore(root=tmp_root)
    assert store.get("BV1test00:p0")["status"] == "needs_audio"
    out = capsys.readouterr().out
    assert "needs_audio" in out


def test_cli_harvest_subs_downloads_and_marks_done(tmp_root, monkeypatch):
    manifest_with(tmp_root)
    transport = RouterTransport({
        "finger/spi": [SPI_OK],
        "nav": [nav_ok()],
        "pagelist": [pagelist_ok()],
        "player/wbi/v2": [player_ok([sub_entry()])],
        "aisubtitle.hdslb.com": [(200, dict(SAMPLE_DOC))],
    })
    _cli_routes(monkeypatch, transport)
    rc = main(["harvest-subs", "--archive-root", tmp_root])
    assert rc == 0
    store = ManifestStore(root=tmp_root)
    assert store.get("BV1test00:p0")["status"] == "subtitle_done"
    assert os.path.exists(
        os.path.join(tmp_root, "transcripts", "srt", "BV1test00.p0.srt"))


def test_cli_harvest_sessdata_env_not_echoed(tmp_root, monkeypatch, capsys):
    """BILI_SESSDATA is used but never echoed in output, errors, or files."""
    manifest_with(tmp_root)
    monkeypatch.setenv("BILI_SESSDATA", "TOPSECRET123")
    transport = RouterTransport({
        "finger/spi": [SPI_OK],
        "nav": [nav_ok()],
        "pagelist": [pagelist_ok()],
        "player/wbi/v2": [player_ok([sub_entry()])],
        "aisubtitle.hdslb.com": [(200, dict(SAMPLE_DOC))],
    })
    _cli_routes(monkeypatch, transport)
    rc = main(["harvest-subs", "--archive-root", tmp_root])
    assert rc == 0
    captured = capsys.readouterr()
    assert "TOPSECRET123" not in captured.out + captured.err
    text = open(ManifestStore(root=tmp_root).path, encoding="utf-8").read()
    assert "TOPSECRET123" not in text
    # ...but it was actually sent to the API
    player_call = [c for c in transport.calls
                   if "player/wbi/v2" in c["url"]][0]
    assert player_call["cookies"].get("SESSDATA") == "TOPSECRET123"


def test_cli_harvest_api_error_preserves_status_and_mixed_batch_fails(
    tmp_root, monkeypatch, capsys
):
    store = manifest_with(tmp_root, statuses=("meta_ok", "meta_ok"))
    transport = RouterTransport({
        "finger/spi": [SPI_OK],
        "nav": [nav_ok()],
        "pagelist": [
            (200, {"code": -400}),
            pagelist_ok(),
        ],
        "player/wbi/v2": [player_ok([])],
    })
    _cli_routes(monkeypatch, transport)
    monkeypatch.setattr("bili_asr.cli.time.sleep", lambda _seconds: None)
    rc = main(["harvest-subs", "--archive-root", tmp_root])
    assert rc == 1
    entries = ManifestStore(root=tmp_root).load()
    failed = entries.get("BV1test00") or entries["BV1test00:p0"]
    assert failed["status"] == "meta_ok"
    assert failed["last_api_error_code"] == -400
    assert entries["BV1test01:p0"]["status"] == "needs_audio"
    assert all(entry.get("status") != "gone" for entry in entries.values())
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "SECRET" not in output
    assert "http" not in output.lower()


def test_cli_harvest_budget_exhausted_exit_2(tmp_root, monkeypatch, capsys):
    manifest_with(tmp_root)
    transport = RouterTransport({
        "finger/spi": [SPI_OK],
        "nav": [nav_ok()],
        "pagelist": [pagelist_ok()],
        "player/wbi/v2": [(412, None)] * 5,
    })
    _cli_routes(monkeypatch, transport)
    rc = main(["harvest-subs", "--archive-root", tmp_root])
    assert rc == 2
    assert "risk-control" in capsys.readouterr().err


def test_cli_harvest_skips_done_and_needs_audio(tmp_root, monkeypatch):
    store = ManifestStore(root=tmp_root)
    seed_legacy(
        store,
        {"bvid": "BV1done", "status": "subtitle_done", "title": "d",
         "duration_s": 1, "pubdate": 1},
        {"bvid": "BV1audio", "status": "needs_audio", "title": "a",
         "duration_s": 1, "pubdate": 1},
        {"bvid": "BV1todo", "status": "meta_ok", "title": "t",
         "duration_s": 1, "pubdate": 1},
    )
    transport = RouterTransport({
        "finger/spi": [SPI_OK],
        "nav": [nav_ok()],
        "pagelist": [pagelist_ok()],
        "player/wbi/v2": [player_ok([sub_entry()])],
        "aisubtitle.hdslb.com": [(200, dict(SAMPLE_DOC))],
    })
    _cli_routes(monkeypatch, transport)
    rc = main(["harvest-subs", "--archive-root", tmp_root])
    assert rc == 0
    player_calls = [c for c in transport.calls if "player/wbi/v2" in c["url"]]
    assert len(player_calls) == 1  # only BV1todo probed
    assert store.get("BV1done")["status"] == "subtitle_done"


def test_cli_harvest_bvid_filter(tmp_root, monkeypatch):
    manifest_with(tmp_root, statuses=("meta_ok", "meta_ok"))
    transport = RouterTransport({
        "finger/spi": [SPI_OK],
        "nav": [nav_ok()],
        "pagelist": [pagelist_ok()],
        "player/wbi/v2": [player_ok([])],
    })
    _cli_routes(monkeypatch, transport)
    rc = main(["harvest-subs", "--bvid", "BV1test01",
               "--archive-root", tmp_root])
    assert rc == 0
    store = ManifestStore(root=tmp_root)
    assert store.get("BV1test00")["status"] == "meta_ok"  # untouched
    assert store.get("BV1test01:p0")["status"] == "needs_audio"
