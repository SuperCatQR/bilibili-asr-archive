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


def nav_response(img_key=IMG_KEY, sub_key=SUB_KEY):
    return (
        200,
        {"code": -101, "data": {"wbi_img": {
            "img_url": f"https://i0.hdslb.com/bfs/wbi/{img_key}.png",
            "sub_url": f"https://i0.hdslb.com/bfs/wbi/{sub_key}.png",
        }}},
    )


def make_client(routes, stream_routes=None):
    routes.setdefault("finger/spi", [SPI_OK])
    routes.setdefault("nav", [nav_response()])
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
        ([30232, 30280], 30232),          # then 132K 30232
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


def test_fetch_playurl_audio_uses_signed_wbi_endpoint_and_cookie():
    transport = RouterTransport({
        "finger/spi": [SPI_OK],
        "pagelist": [pagelist_ok(cid=111)],
        "nav": [(
            200,
            {"code": -101, "data": {"wbi_img": {
                "img_url": f"https://i0.hdslb.com/bfs/wbi/{IMG_KEY}.png",
                "sub_url": f"https://i0.hdslb.com/bfs/wbi/{SUB_KEY}.png",
            }}},
        )],
        "/x/player/wbi/playurl": [playurl_ok()],
    })
    client = bc.BiliClient(
        transport=transport,
        sleeper=FastSleeper(),
        jitter=lambda: 0.0,
        sessdata="SECRET-SESSDATA",
    )

    assert client.fetch_playurl_audio(BVID)
    call = [c for c in transport.calls if "/x/player/wbi/playurl" in c["url"]][0]
    assert call["url"] == bc.API_BASE + "/x/player/wbi/playurl"
    assert call["params"]["bvid"] == BVID
    assert call["params"]["cid"] == 111
    assert call["params"]["fnval"] == 16
    assert call["params"]["qn"] == 0
    assert isinstance(call["params"]["wts"], int)
    assert len(call["params"]["w_rid"]) == 32
    assert call["cookies"]["SESSDATA"] == "SECRET-SESSDATA"
    assert "SECRET-SESSDATA" not in json.dumps(call["params"])


def test_fetch_playurl_audio_retries_once_with_rotated_wbi_keys(monkeypatch):
    fresh_img = "0123456789abcdef0123456789abcdef"
    fresh_sub = "fedcba9876543210fedcba9876543210"
    transport = RouterTransport({
        "finger/spi": [SPI_OK],
        "pagelist": [pagelist_ok(cid=111)],
        "nav": [
            nav_response(),
            nav_response(fresh_img, fresh_sub),
        ],
        "/x/player/wbi/playurl": [
            (200, {"code": -403}),
            playurl_ok(),
        ],
    })
    timestamps = iter([1700000000, 1700000001])
    monkeypatch.setattr(bc.time, "time", lambda: next(timestamps))
    client = bc.BiliClient(
        transport=transport,
        sleeper=FastSleeper(),
        jitter=lambda: 0.0,
    )

    assert client.fetch_playurl_audio(BVID)

    nav_calls = [
        c for c in transport.calls if "/x/web-interface/nav" in c["url"]
    ]
    play_calls = [
        c for c in transport.calls if "/x/player/wbi/playurl" in c["url"]
    ]
    assert len(nav_calls) == 2
    assert len(play_calls) == 2
    assert play_calls[0]["params"]["wts"] != play_calls[1]["params"]["wts"]
    assert play_calls[0]["params"]["w_rid"] != play_calls[1]["params"]["w_rid"]


def test_fetch_playurl_audio_second_minus_403_is_not_retried():
    transport = RouterTransport({
        "finger/spi": [SPI_OK],
        "pagelist": [pagelist_ok(cid=111)],
        "nav": [nav_response(), nav_response()],
        "/x/player/wbi/playurl": [
            (200, {"code": -403}),
            (200, {"code": -403}),
        ],
    })
    client = bc.BiliClient(
        transport=transport,
        sleeper=FastSleeper(),
        jitter=lambda: 0.0,
    )

    with pytest.raises(bc.APIResponseError) as exc:
        client.fetch_playurl_audio(BVID)

    assert exc.value.code == -403
    play_calls = [
        c for c in transport.calls if "/x/player/wbi/playurl" in c["url"]
    ]
    assert len(play_calls) == 2


def test_download_audio_prefers_30216_and_sends_referer_ua(tmp_root):
    client = make_client(
        {"pagelist": [pagelist_ok()],
         "/x/player/wbi/playurl": [playurl_ok()]},
        stream_routes={f"{STREAM_HOST}/a30216.m4s": AUDIO_BYTES},
    )
    client._sessdata = "SECRET-SESSDATA"
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
    assert play_call["cookies"]["SESSDATA"] == "SECRET-SESSDATA"
    # stream GET must carry Referer + UA (spec hard requirement)
    assert len(client.transport.stream_calls) == 1
    sc = client.transport.stream_calls[0]
    assert sc["url"] == f"https://{STREAM_HOST}/a30216.m4s"
    assert sc["headers"].get("Referer") == "https://www.bilibili.com/"
    assert sc["headers"].get("User-Agent") == bc.UA
    assert sc["cookies"] == {}


def test_download_audio_falls_back_when_preferred_missing(tmp_root):
    client = make_client(
        {"pagelist": [pagelist_ok()],
         "/x/player/wbi/playurl": [playurl_ok(streams=[
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
         "/x/player/wbi/playurl": [(200, {"code": 0, "data": {"dash": {"audio": []}}})]},
    )
    with pytest.raises(audio.NoAudioStreamError):
        audio.download_audio(client, BVID,
                             os.path.join(tmp_root, "audio", "x.m4a"))


def test_download_audio_atomic_no_partial_on_failure(tmp_root):
    client = make_client(
        {"pagelist": [pagelist_ok()], "/x/player/wbi/playurl": [playurl_ok()]},
        stream_routes={},  # no route -> transport raises
    )
    out = os.path.join(tmp_root, "audio", f"{BVID}.m4a")
    with pytest.raises(Exception):
        audio.download_audio(client, BVID, out)
    assert not os.path.exists(out)


def test_download_audio_skips_existing_page_identity_without_network(tmp_root):
    from bili_asr.page_identity import page_identity

    identity = page_identity(BVID, 0, 111)
    client = make_client({})
    out = os.path.join(tmp_root, "audio", f"{BVID}.p0.m4a")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "wb") as fh:
        fh.write(b"already-there")
    audio.download_audio(client, identity, out)
    assert client.transport.calls == []
    assert client.transport.stream_calls == []


def test_download_audio_skips_existing(tmp_root):
    client = make_client(
        {"pagelist": [pagelist_ok()], "/x/player/wbi/playurl": [playurl_ok()]},
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


def test_download_audio_30232_m4s_does_not_remux(tmp_root, monkeypatch):
    client = make_client(
        {"pagelist": [pagelist_ok()],
         "/x/player/wbi/playurl": [playurl_ok(streams=[
             {"id": 30232, "baseUrl": f"https://{STREAM_HOST}/a30232.m4s",
              "base_url": f"https://{STREAM_HOST}/a30232.m4s"},
         ])]},
        stream_routes={f"{STREAM_HOST}/a30232.m4s": AUDIO_BYTES},
    )
    calls = []
    monkeypatch.setattr(
        audio, "_run_ffmpeg", lambda src, dst: calls.append((src, dst))
    )
    out = os.path.join(tmp_root, "audio", f"{BVID}.m4a")
    audio.download_audio(client, BVID, out)
    assert calls == []
    assert os.path.exists(out)


def test_download_audio_explicit_flac_url_remuxes(tmp_root, monkeypatch):
    flac = b"fLaC" + b"data" * 10
    client = make_client(
        {"pagelist": [pagelist_ok()],
         "/x/player/wbi/playurl": [playurl_ok(streams=[
             {"id": 30232, "baseUrl": f"https://{STREAM_HOST}/a30232.flac",
              "base_url": f"https://{STREAM_HOST}/a30232.flac"},
         ])]},
        stream_routes={f"{STREAM_HOST}/a30232.flac": flac},
    )
    calls = []
    monkeypatch.setattr(
        audio, "_run_ffmpeg", lambda src, dst: calls.append((src, dst))
    )
    out = os.path.join(tmp_root, "audio", f"{BVID}.m4a")
    audio.download_audio(client, BVID, out)
    assert calls and calls[0][1] == out
    assert not os.path.exists(calls[0][0])
    assert os.path.basename(out).endswith(".m4a")


def test_download_audio_mime_only_flac_remuxes(tmp_root, monkeypatch):
    flac = b"fLaC" + b"data" * 10
    client = make_client(
        {"pagelist": [pagelist_ok()],
         "/x/player/wbi/playurl": [playurl_ok(streams=[
             {"id": 30232, "baseUrl": f"https://{STREAM_HOST}/a30232.m4s",
              "base_url": f"https://{STREAM_HOST}/a30232.m4s",
              "mimeType": "audio/flac"},
         ])]},
        stream_routes={f"{STREAM_HOST}/a30232.m4s": flac},
    )
    calls = []
    monkeypatch.setattr(
        audio, "_run_ffmpeg", lambda src, dst: calls.append((src, dst))
    )
    out = os.path.join(tmp_root, "audio", f"{BVID}.m4a")
    audio.download_audio(client, BVID, out)
    assert calls and calls[0][1] == out


def test_download_audio_flac_without_ffmpeg_keeps_flac(tmp_root, monkeypatch):
    flac = b"fLaC" + b"data" * 10
    client = make_client(
        {"pagelist": [pagelist_ok()],
         "/x/player/wbi/playurl": [playurl_ok(streams=[
             {"id": 30232, "baseUrl": f"https://{STREAM_HOST}/a30232.flac",
              "base_url": f"https://{STREAM_HOST}/a30232.flac"},
         ])]},
        stream_routes={f"{STREAM_HOST}/a30232.flac": flac},
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

def seed_legacy(store, *entries):
    store.load()
    data = dict(store._entries)
    for entry in entries:
        data[entry.get("work_id") or entry["bvid"]] = entry
    store.save(data)


def test_download_audio_updates_manifest_audio_ok(tmp_root):
    store = ManifestStore(root=tmp_root)
    seed_legacy(store, {"bvid": BVID, "status": "needs_audio", "title": "t",
                        "duration_s": 1, "pubdate": 1,
                        "last_api_error_code": -403})
    client = make_client(
        {"pagelist": [pagelist_ok()], "/x/player/wbi/playurl": [playurl_ok()]},
        stream_routes={f"{STREAM_HOST}/a30216.m4s": AUDIO_BYTES},
    )
    audio.download_audio(client, BVID,
                         os.path.join(tmp_root, "audio", f"{BVID}.m4a"),
                         store=store)
    entry = store.get(f"{BVID}:p0")
    assert entry["status"] == "audio_ok"
    assert entry["audio_path"] == os.path.join("audio", f"{BVID}.m4a")
    assert "last_api_error_code" not in entry
    assert "hdslb" not in json.dumps(entry)
    assert "bilivideo" not in json.dumps(entry)  # no stream URL persisted


# ----------------------------------------------------------------------- CLI

def _cli_routes(monkeypatch, transport):
    transport.routes.setdefault("nav", [(
        200,
        {"code": -101, "data": {"wbi_img": {
            "img_url": f"https://i0.hdslb.com/bfs/wbi/{IMG_KEY}.png",
            "sub_url": f"https://i0.hdslb.com/bfs/wbi/{SUB_KEY}.png",
        }}},
    )])
    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
    monkeypatch.setattr(bc, "default_sleeper", lambda: FastSleeper())


def manifest_needs_audio(tmp_root):
    store = ManifestStore(root=tmp_root)
    seed_legacy(
        store,
        {"bvid": BVID, "status": "needs_audio", "title": "t",
         "duration_s": 1, "pubdate": 1},
        {"bvid": "BV1done", "status": "subtitle_done", "title": "d",
         "duration_s": 1, "pubdate": 1},
    )
    return store


def test_cli_download_audio_missing_subs(tmp_root, monkeypatch, capsys):
    manifest_needs_audio(tmp_root)
    transport = RouterTransport(
        {"finger/spi": [SPI_OK],
         "pagelist": [pagelist_ok()],
         "/x/player/wbi/playurl": [playurl_ok()]},
        stream_routes={f"{STREAM_HOST}/a30216.m4s": AUDIO_BYTES},
    )
    _cli_routes(monkeypatch, transport)
    rc = main(["download-audio", "--missing-subs", "--archive-root", tmp_root])
    assert rc == 0
    store = ManifestStore(root=tmp_root)
    assert store.get(f"{BVID}:p0")["status"] == "audio_ok"
    assert store.get("BV1done")["status"] == "subtitle_done"
    assert os.path.exists(os.path.join(tmp_root, "audio", f"{BVID}.p0.m4a"))
    assert "audio_ok" in capsys.readouterr().out
    # only the needs_audio video was streamed
    assert len(transport.stream_calls) == 1


def test_cli_download_audio_bvid(tmp_root, monkeypatch):
    manifest_needs_audio(tmp_root)
    transport = RouterTransport(
        {"finger/spi": [SPI_OK],
         "pagelist": [pagelist_ok()],
         "/x/player/wbi/playurl": [playurl_ok()]},
        stream_routes={f"{STREAM_HOST}/a30216.m4s": AUDIO_BYTES},
    )
    _cli_routes(monkeypatch, transport)
    rc = main(["download-audio", "--bvid", BVID,
               "--archive-root", tmp_root])
    assert rc == 0
    store = ManifestStore(root=tmp_root)
    assert store.get(f"{BVID}:p0")["status"] == "audio_ok"


def test_cli_download_audio_requires_selection(tmp_root, monkeypatch, capsys):
    _cli_routes(monkeypatch, RouterTransport({"finger/spi": [SPI_OK]}))
    rc = main(["download-audio", "--archive-root", tmp_root])
    assert rc == 1


def test_cli_download_audio_unknown_bvid_stops_without_row(
    tmp_root, monkeypatch, capsys
):
    monkeypatch.setenv("BILI_SESSDATA", "SECRET-SESSDATA")
    transport = RouterTransport({
        "finger/spi": [SPI_OK],
        "pagelist": [(200, {"code": -403})],
    })
    _cli_routes(monkeypatch, transport)

    rc = main([
        "download-audio", "--bvid", "BV1unknown",
        "--archive-root", tmp_root,
    ])

    assert rc == 1
    assert ManifestStore(root=tmp_root).get("BV1unknown") is None
    assert not os.path.exists(ManifestStore(root=tmp_root).path)
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "unresolved" in output
    assert "SECRET-SESSDATA" not in output
    assert "http" not in output.lower()


def test_cli_download_audio_api_error_preserves_status_and_mixed_batch_fails(
    tmp_root, monkeypatch, capsys
):
    store = ManifestStore(root=tmp_root)
    seed_legacy(
        store,
        {"bvid": "BV1error", "status": "needs_audio", "title": "e"},
        {"bvid": "BV1success", "status": "needs_audio", "title": "s"},
    )
    transport = RouterTransport(
        {
            "finger/spi": [SPI_OK],
            "pagelist": [
                (200, {"code": -101}),
                pagelist_ok(),
            ],
            "/x/player/wbi/playurl": [playurl_ok()],
        },
        stream_routes={f"{STREAM_HOST}/a30216.m4s": AUDIO_BYTES},
    )
    _cli_routes(monkeypatch, transport)
    monkeypatch.setattr("bili_asr.cli.time.sleep", lambda _seconds: None)
    rc = main(["download-audio", "--missing-subs", "--archive-root", tmp_root])
    assert rc == 1
    entries = ManifestStore(root=tmp_root).load()
    failed = entries.get("BV1error") or entries["BV1error:p0"]
    assert failed["status"] == "needs_audio"
    assert failed["last_api_error_code"] == -101
    assert entries["BV1success:p0"]["status"] == "audio_ok"
    assert all(entry.get("status") != "gone" for entry in entries.values())
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "http" not in output.lower()


def test_cli_download_audio_transport_error_redacts_exception_message(
    tmp_root, monkeypatch, capsys
):
    sentinel = "SESSDATA=AUDIO-SECRET https://cdn.example/a.m4s?token=SIGNED"
    seed_legacy(
        ManifestStore(root=tmp_root),
        {"bvid": "BV1transport", "status": "needs_audio", "title": "t",
         "duration_s": 1, "pubdate": 1},
    )
    transport = RouterTransport({
        "finger/spi": [SPI_OK],
        "pagelist": [RuntimeError(sentinel)] * 5,
    })
    _cli_routes(monkeypatch, transport)

    rc = main([
        "download-audio", "--bvid", "BV1transport",
        "--archive-root", tmp_root,
    ])

    assert rc == 2
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "RuntimeError" in output
    assert "AUDIO-SECRET" not in output
    assert "SIGNED" not in output
    leftover = ManifestStore(root=tmp_root).get("BV1transport")
    assert leftover is not None
    assert leftover.get("status") == "needs_audio"
    assert "work_id" not in leftover


def test_cli_download_audio_budget_exhausted_exit_2(tmp_root, monkeypatch, capsys):
    manifest_needs_audio(tmp_root)
    transport = RouterTransport(
        {"finger/spi": [SPI_OK],
         "pagelist": [pagelist_ok()],
         "/x/player/wbi/playurl": [(412, None)] * 5},
    )
    _cli_routes(monkeypatch, transport)
    rc = main(["download-audio", "--missing-subs", "--archive-root", tmp_root])
    assert rc == 2
    assert "risk-control" in capsys.readouterr().err
