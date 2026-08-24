"""Unit tests for audio download (Task 3): mocked transport, no network."""

from __future__ import annotations

import json
import os

import pytest

from bili_asr import audio
from bili_asr import bili_client as bc
from bili_asr.cli import main
from bili_asr.manifest import ManifestStore

SPI_OK = (200, {"code": 0, "data": {"b_3": "B3", "b_4": "B4"}})

IMG_KEY = "7cd084941338484aae1ad9425b84077c"
SUB_KEY = "4932caff0ff746eab6f01bf08b70ac45"

BVID = "BV1test00"

STREAM_HOST = "upos-sz-mirrorcoso.bilivideo.com"


class RouterTransport:
    """Routes by URL substring to scripted (status, body) queues.

    Also implements the binary stream seam used by Task 3: a
    `stream_bytes` route receives (url, headers) and returns bytes.
    """

    def __init__(self, routes: dict[str, list], stream_routes: dict[str, bytes] | None = None):
        self.routes = routes
        self.stream_routes = stream_routes or {}
        self.calls: list[dict] = []
        self.stream_calls: list[dict] = []

    def get_json(self, url, params=None, headers=None, cookies=None, timeout=None):
        self.calls.append({"url": url, "params": dict(params or {}),
                           "headers": dict(headers or {}),
                           "cookies": dict(cookies or {})})
        for frag, queue in self.routes.items():
            if frag in url:
                if not queue:
                    raise AssertionError(f"queue for {frag!r} exhausted")
                item = queue.pop(0)
                if isinstance(item, Exception):
                    raise item
                return item
        raise AssertionError(f"no route for {url}")

    def get_stream(self, url, headers=None, cookies=None, timeout=None) -> bytes:
        self.stream_calls.append({"url": url, "headers": dict(headers or {}),
                                  "cookies": dict(cookies or {})})
        for frag, payload in self.stream_routes.items():
            if frag in url:
                return payload
        raise AssertionError(f"no stream route for {url}")


class FastSleeper:
    def __init__(self):
        self.waits = []

    def __call__(self, seconds):
        self.waits.append(seconds)


def pagelist_ok(cid=111):
    return (200, {"code": 0, "data": [{"cid": cid, "page": 1}]})


def playurl_ok(streams=None, code=30216):
    """dash playurl with selectable audio codec ids (default DTS m4s)."""
    audio_list = streams if streams is not None else [
        {"id": 30216, "baseUrl": f"https://{STREAM_HOST}/a30216.m4s",
         "base_url": f"https://{STREAM_HOST}/a30216.m4s",
         "backupUrl": [], "bandwidth": 320000},
        {"id": 30280, "baseUrl": f"https://{STREAM_HOST}/a30280.m4s",
         "base_url": f"https://{STREAM_HOST}/a30280.m4s",
         "backupUrl": [], "bandwidth": 192000},
    ]
    return (200, {"code": 0, "data": {"dash": {"audio": audio_list}}})


def make_client(routes, stream_routes=None):
    routes.setdefault("finger/spi", [SPI_OK])
    return bc.BiliClient(
        transport=RouterTransport(routes, stream_routes),
        sleeper=FastSleeper(),
        jitter=lambda: 0.0,
    )


# ------------------------------------------------------------- stream choice

@pytest.mark.parametrize(
    "ids,expected",
    [
        ([30216, 30280], 30216),          # prefer DTS 30216
        ([30232, 30280], 30232),          # then Hi-Res flac 30232
        ([30232, 30216], 30216),          # 30216 beats 30232
        ([30280, 30250], 30250),          # fallback: highest quality id order
        ([30216], 30216),
    ],
)
def test_pick_audio_stream_preference(ids, expected):
    streams = [{"id": i, "baseUrl": f"https://h/{i}.m4s",
                "base_url": f"https://h/{i}.m4s"} for i in ids]
    assert audio.pick_audio_stream(streams)["id"] == expected


def test_pick_audio_stream_empty():
    assert audio.pick_audio_stream([]) is None


def test_pick_audio_stream_none():
    assert audio.pick_audio_stream(None) is None


# ------------------------------------------------------------------ download

AUDIO_BYTES = b"\x00\x00\x00\x18ftypM4A " + b"payload" * 100


def test_download_audio_prefers_30216_and_sends_referer_ua(tmp_root):
    client = make_client(
        {"pagelist": [pagelist_ok()], "playurl": [playurl_ok()]},
        stream_routes={f"{STREAM_HOST}/a30216.m4s": AUDIO_BYTES},
    )
    out = os.path.join(tmp_root, "audio", f"{BVID}.m4a")
    path = audio.download_audio(client, BVID, out)
    assert path == out
    with open(out, "rb") as fh:
        assert fh.read() == AUDIO_BYTES
    # playurl requested with cid + bvid (fnval=16 dash)
    play_call = [c for c in client.transport.calls if "playurl" in c["url"]][0]
    assert play_call["params"]["cid"] == 111
    assert play_call["params"]["bvid"] == BVID
    assert play_call["params"]["fnval"] == 16
    # stream GET must carry Referer + UA (spec hard requirement)
    assert len(client.transport.stream_calls) == 1
    sc = client.transport.stream_calls[0]
    assert sc["url"] == f"https://{STREAM_HOST}/a30216.m4s"
    assert sc["headers"].get("Referer") == "https://www.bilibili.com/"
    assert sc["headers"].get("User-Agent") == bc.UA


def test_download_audio_falls_back_when_preferred_missing(tmp_root):
    client = make_client(
        {"pagelist": [pagelist_ok()],
         "playurl": [playurl_ok(streams=[
             {"id": 30280, "baseUrl": f"https://{STREAM_HOST}/a30280.m4s",
              "base_url": f"https://{STREAM_HOST}/a30280.m4s"},
         ])]},
        stream_routes={f"{STREAM_HOST}/a30280.m4s": AUDIO_BYTES},
    )
    out = os.path.join(tmp_root, "audio", f"{BVID}.m4a")
    audio.download_audio(client, BVID, out)
    assert client.transport.stream_calls[0]["url"].endswith("a30280.m4s")


def test_download_audio_no_dash_audio_raises(tmp_root):
    client = make_client(
        {"pagelist": [pagelist_ok()],
         "playurl": [(200, {"code": 0, "data": {"dash": {"audio": []}}})]},
    )
    with pytest.raises(audio.NoAudioStreamError):
        audio.download_audio(client, BVID,
                             os.path.join(tmp_root, "audio", "x.m4a"))


def test_download_audio_atomic_no_partial_on_failure(tmp_root):
    client = make_client(
        {"pagelist": [pagelist_ok()], "playurl": [playurl_ok()]},
        stream_routes={},  # no route -> transport raises
    )
    out = os.path.join(tmp_root, "audio", f"{BVID}.m4a")
    with pytest.raises(Exception):
        audio.download_audio(client, BVID, out)
    assert not os.path.exists(out)


def test_download_audio_skips_existing(tmp_root):
    client = make_client(
        {"pagelist": [pagelist_ok()], "playurl": [playurl_ok()]},
        stream_routes={f"{STREAM_HOST}/a30216.m4s": AUDIO_BYTES},
    )
    out = os.path.join(tmp_root, "audio", f"{BVID}.m4a")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "wb") as fh:
        fh.write(b"already-there")
    audio.download_audio(client, BVID, out)
    assert client.transport.stream_calls == []  # no re-download
    with open(out, "rb") as fh:
        assert fh.read() == b"already-there"


def test_download_audio_remux_flac_to_m4a(tmp_root, monkeypatch):
    flac = b"fLaC" + b"data" * 10
    client = make_client(
        {"pagelist": [pagelist_ok()],
         "playurl": [playurl_ok(streams=[
             {"id": 30232, "baseUrl": f"https://{STREAM_HOST}/a30232.m4s",
              "base_url": f"https://{STREAM_HOST}/a30232.m4s"},
         ])]},
        stream_routes={f"{STREAM_HOST}/a30232.m4s": flac},
    )
    calls = []
    monkeypatch.setattr(audio, "_run_ffmpeg", lambda src, dst: calls.append((src, dst)))
    out = os.path.join(tmp_root, "audio", f"{BVID}.m4a")
    audio.download_audio(client, BVID, out)
    assert calls and calls[0][1] == out
    assert not os.path.exists(calls[0][0])  # temp removed
    assert not os.path.exists(os.path.join(tmp_root, "audio", f"{BVID}.flac"))
    # remuxed output is named .m4a
    assert os.path.basename(out).endswith(".m4a")


def test_download_audio_flac_without_ffmpeg_keeps_flac(tmp_root, monkeypatch):
    flac = b"fLaC" + b"data" * 10
    client = make_client(
        {"pagelist": [pagelist_ok()],
         "playurl": [playurl_ok(streams=[
             {"id": 30232, "baseUrl": f"https://{STREAM_HOST}/a30232.m4s",
              "base_url": f"https://{STREAM_HOST}/a30232.m4s"},
         ])]},
        stream_routes={f"{STREAM_HOST}/a30232.m4s": flac},
    )
    def boom(src, dst):
        raise audio.FFmpegUnavailable("no ffmpeg")
    monkeypatch.setattr(audio, "_run_ffmpeg", boom)
    flac_path = audio.download_audio(client, BVID,
                                     os.path.join(tmp_root, "audio", f"{BVID}.m4a"))
    assert flac_path.endswith(f"{BVID}.flac")
    with open(flac_path, "rb") as fh:
        assert fh.read() == flac


# ------------------------------------------------------------------ manifest

def test_download_audio_updates_manifest_audio_ok(tmp_root):
    store = ManifestStore(root=tmp_root)
    store.upsert({"bvid": BVID, "status": "needs_audio", "title": "t",
                  "duration_s": 1, "pubdate": 1})
    client = make_client(
        {"pagelist": [pagelist_ok()], "playurl": [playurl_ok()]},
        stream_routes={f"{STREAM_HOST}/a30216.m4s": AUDIO_BYTES},
    )
    audio.download_audio(client, BVID,
                         os.path.join(tmp_root, "audio", f"{BVID}.m4a"),
                         store=store)
    entry = store.get(BVID)
    assert entry["status"] == "audio_ok"
    assert entry["audio_path"] == os.path.join("audio", f"{BVID}.m4a")
    assert "hdslb" not in json.dumps(entry)
    assert "bilivideo" not in json.dumps(entry)  # no stream URL persisted


# ----------------------------------------------------------------------- CLI

def _cli_routes(monkeypatch, transport):
    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
    monkeypatch.setattr(bc, "default_sleeper", lambda: FastSleeper())


def manifest_needs_audio(tmp_root):
    store = ManifestStore(root=tmp_root)
    store.upsert({"bvid": BVID, "status": "needs_audio", "title": "t",
                  "duration_s": 1, "pubdate": 1})
    store.upsert({"bvid": "BV1done", "status": "subtitle_done", "title": "d",
                  "duration_s": 1, "pubdate": 1})
    return store


def test_cli_download_audio_missing_subs(tmp_root, monkeypatch, capsys):
    manifest_needs_audio(tmp_root)
    transport = RouterTransport(
        {"finger/spi": [SPI_OK],
         "pagelist": [pagelist_ok()],
         "playurl": [playurl_ok()]},
        stream_routes={f"{STREAM_HOST}/a30216.m4s": AUDIO_BYTES},
    )
    _cli_routes(monkeypatch, transport)
    rc = main(["download-audio", "--missing-subs", "--archive-root", tmp_root])
    assert rc == 0
    store = ManifestStore(root=tmp_root)
    assert store.get(BVID)["status"] == "audio_ok"
    assert store.get("BV1done")["status"] == "subtitle_done"
    assert os.path.exists(os.path.join(tmp_root, "audio", f"{BVID}.m4a"))
    assert "audio_ok" in capsys.readouterr().out
    # only the needs_audio video was streamed
    assert len(transport.stream_calls) == 1


def test_cli_download_audio_bvid(tmp_root, monkeypatch):
    manifest_needs_audio(tmp_root)
    transport = RouterTransport(
        {"finger/spi": [SPI_OK],
         "pagelist": [pagelist_ok()],
         "playurl": [playurl_ok()]},
        stream_routes={f"{STREAM_HOST}/a30216.m4s": AUDIO_BYTES},
    )
    _cli_routes(monkeypatch, transport)
    rc = main(["download-audio", "--bvid", "BV1fresh",
               "--archive-root", tmp_root])
    assert rc == 0
    store = ManifestStore(root=tmp_root)
    assert store.get("BV1fresh")["status"] == "audio_ok"


def test_cli_download_audio_requires_selection(tmp_root, monkeypatch, capsys):
    _cli_routes(monkeypatch, RouterTransport({"finger/spi": [SPI_OK]}))
    rc = main(["download-audio", "--archive-root", tmp_root])
    assert rc == 1


def test_cli_download_audio_budget_exhausted_exit_2(tmp_root, monkeypatch, capsys):
    manifest_needs_audio(tmp_root)
    transport = RouterTransport(
        {"finger/spi": [SPI_OK],
         "pagelist": [pagelist_ok()],
         "playurl": [(412, None)] * 5},
    )
    _cli_routes(monkeypatch, transport)
    rc = main(["download-audio", "--missing-subs", "--archive-root", tmp_root])
    assert rc == 2
    assert "risk-control" in capsys.readouterr().err
