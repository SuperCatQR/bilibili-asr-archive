"""Unit tests for fetch-meta: mocked transport only, no live network."""

from __future__ import annotations

import json
import os

import pytest

from bili_asr import bili_client as bc
from bili_asr.cli import main
from bili_asr.manifest import ManifestStore

API = "https://api.bilibili.com"

SPI_OK = (200, {"code": 0, "data": {"b_3": "B3", "b_4": "B4"}})
SPI_NEW = (200, {"code": 0, "data": {"b_3": "B3NEW", "b_4": "B4NEW"}})


class FakeTransport:
    """Scripted injectable transport; records calls, never opens sockets."""

    def __init__(self, script, spi=None):
        # script: (status, body) responses for endpoint GETs (in order)
        # spi: finger/spi responses; refreshes draw from the same queue
        self.script = list(script)
        self.spi = list(spi or [SPI_OK])
        self.calls = []

    def get_json(self, url, params=None, headers=None, cookies=None, timeout=None):
        self.calls.append(
            {"url": url, "params": dict(params or {}), "cookies": dict(cookies or {})}
        )
        if "pagelist" in url:
            cid = abs(hash((params or {}).get("bvid") or "x")) % 10_000 + 1
            return 200, {
                "code": 0,
                "data": [{"cid": cid, "page": 1, "part": ""}],
            }
        queue = self.spi if "finger/spi" in url else self.script
        if not queue:
            raise AssertionError("FakeTransport ran out of scripted responses")
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        status, body = item
        return status, body


def ok_page(archives, total=None):
    return {
        "code": 0,
        "message": "0",
        "data": {
            "page": {"total": total if total is not None else len(archives)},
            "archives": archives,
        },
    }


def arc(bvid, duration=100, pubdate=1700000000, title=None):
    return {
        "bvid": bvid,
        "aid": 1,
        "title": title if title is not None else "t " + bvid,
        "duration": duration,
        "pubdate": pubdate,
        "stat": {"view": 10},
        "state": 0,
    }


class FastSleeper:
    def __init__(self):
        self.waits = []

    def __call__(self, seconds):
        self.waits.append(seconds)


@pytest.fixture
def fast_sleep():
    return FastSleeper()


# ---------------------------------------------------------------- WBI golden


def test_wbi_signing_golden_vector():
    # Reference vector from bilibili-API-collect docs/misc/sign/wbi.md
    # (Rust unit test in the doc: MIXIN_KEY_ENC_TAB reorder + "!'()*"
    # filter + sorted urlencode + MD5, wts pinned)
    img_key = "7cd084941338484aae1ad9425b84077c"
    sub_key = "4932caff0ff746eab6f01bf08b70ac45"
    params = {"foo": "114", "bar": "514", "zab": 1919810}
    signed = bc.sign_wbi(params, img_key, sub_key, wts=1702204169)
    assert signed["wts"] == 1702204169
    assert signed["w_rid"] == "8f6f2b5b3d485fe1886cec6a0be8c5d4"


def test_mixin_key_derivation():
    key = bc.get_mixin_key(
        "7cd084941338484aae1ad9425b84077c", "4932caff0ff746eab6f01bf08b70ac45"
    )
    assert key == "ea1db124af3c7062474693fa704f4ff8"


# ---------------------------------------------------- risk-code classification


@pytest.mark.parametrize(
    "status,body,expected",
    [
        (412, None, bc.RISK_RETRYABLE),
        (200, {"code": -412}, bc.RISK_RETRYABLE),
        (200, {"code": -352}, bc.RISK_RETRYABLE),
        (200, {"code": -799}, bc.RISK_RETRYABLE),
        (500, None, bc.RISK_RETRYABLE),
        (200, {"code": -403}, bc.RISK_API_ERROR),
        (200, {"code": -101}, bc.RISK_API_ERROR),
        (200, {"code": -400}, bc.RISK_API_ERROR),
        (200, {"code": -99999}, bc.RISK_API_ERROR),
        (404, None, bc.RISK_GONE),
        (200, {"code": -404}, bc.RISK_GONE),
        (200, {"code": -62002}, bc.RISK_GONE),
        (200, {"code": 0}, bc.RISK_OK),
        # H3: HTTP 200 with unparseable (None) body is the 412-adjacent
        # risk-control challenge-page signal -> retryable, never RISK_OK
        (200, None, bc.RISK_RETRYABLE),
    ],
)
def test_classify_risk(status, body, expected):
    assert bc.classify_risk(status, body) == expected


# ------------------------------------------------------------------- buvid


def test_buvid_bootstrap_via_finger_spi():
    transport = FakeTransport(
        [(200, ok_page([arc("BV1A")]))],
        spi=[(200, {"code": 0, "data": {"b_3": "BV3XXX", "b_4": "BV4YYY"}})],
    )
    client = bc.BiliClient(transport=transport, sleeper=FastSleeper())
    pages = client.fetch_pages(23191782, max_pages=1)
    assert len(pages[0]) == 1
    spi_call, page_call = transport.calls
    assert spi_call["url"] == API + "/x/frontend/finger/spi"
    assert page_call["cookies"]["buvid3"] == "BV3XXX"
    assert page_call["cookies"]["buvid4"] == "BV4YYY"
    assert page_call["url"] == API + "/x/series/recArchivesByKeywords"


def test_buvid_cached_per_process():
    transport = FakeTransport(
        [(200, ok_page([arc("BV1A")])), (200, ok_page([arc("BV1B")]))],
    )
    client = bc.BiliClient(transport=transport, sleeper=FastSleeper())
    client.fetch_pages(23191782, max_pages=1)
    client.fetch_pages(23191782, max_pages=1)
    spi_calls = [c for c in transport.calls if "finger/spi" in c["url"]]
    assert len(spi_calls) == 1  # one bootstrap per process/client


# ------------------------------------------------------------ 412 backoff/retry


def test_412_retry_then_success(fast_sleep):
    transport = FakeTransport(
        [(412, None), (412, None), (200, ok_page([arc("BV1A"), arc("BV1B")]))],
        spi=[SPI_OK, SPI_NEW],  # initial bootstrap + one mid-sequence refresh
    )
    client = bc.BiliClient(transport=transport, sleeper=fast_sleep,
                           jitter=lambda: 0.0)
    pages = client.fetch_pages(23191782, max_pages=1)
    assert len(pages[0]) == 2
    assert fast_sleep.waits[0] == pytest.approx(2.0)
    assert fast_sleep.waits[1] == pytest.approx(4.0)


@pytest.mark.parametrize("code", [-101, -400, -99999])
def test_request_raises_api_response_error_for_non_gone_code(code):
    transport = FakeTransport([(200, {"code": code})])
    client = bc.BiliClient(transport=transport, sleeper=FastSleeper())
    with pytest.raises(bc.APIResponseError) as exc:
        client.fetch_pages(23191782, max_pages=1)
    assert exc.value.code == code


def test_request_with_cookies_raises_api_response_error_for_non_gone_code():
    transport = FakeTransport([(200, {"code": -400})])
    client = bc.BiliClient(transport=transport, sleeper=FastSleeper())
    with pytest.raises(bc.APIResponseError) as exc:
        client._request_with_cookies(API + "/test", {})
    assert exc.value.code == -400


def test_minus_403_directly_raises_api_response_error(fast_sleep):
    transport = FakeTransport([(200, {"code": -403})])
    client = bc.BiliClient(
        transport=transport, sleeper=fast_sleep, jitter=lambda: 0.0
    )
    with pytest.raises(bc.APIResponseError) as exc:
        client.fetch_pages(23191782, max_pages=1)
    assert exc.value.code == -403
    assert len(transport.calls) == 2  # bootstrap plus one API request
    assert fast_sleep.waits == []


def test_budget_exhausted_raises_after_max_attempts(fast_sleep):
    transport = FakeTransport([(412, None)] * 5, spi=[SPI_OK, SPI_NEW])
    client = bc.BiliClient(transport=transport, sleeper=fast_sleep,
                           jitter=lambda: 0.0)
    with pytest.raises(bc.RiskBudgetExhausted) as exc:
        client.fetch_pages(23191782, max_pages=1)
    assert exc.value.last_code == 412
    assert len(fast_sleep.waits) == 4  # 5 attempts -> 4 sleeps


def test_backoff_growth(fast_sleep):
    transport = FakeTransport([(200, {"code": -352})] * 5, spi=[SPI_OK, SPI_NEW])
    client = bc.BiliClient(transport=transport, sleeper=fast_sleep,
                           jitter=lambda: 0.0)
    with pytest.raises(bc.RiskBudgetExhausted):
        client.fetch_pages(23191782, max_pages=1)
    assert fast_sleep.waits == [2.0, 4.0, 8.0, 16.0]  # base 2, exponential


def test_backoff_cap_60s():
    # 60s cap formula check without driving 30+ attempts over HTTP mocks
    client = bc.BiliClient(jitter=lambda: 0.0)
    waits = []
    client._sleeper = waits.append
    for attempt in range(1, 11):  # attempt 10 would naively be 1024s
        client._sleep_backoff(attempt)
    assert waits[-1] == 60.0
    assert waits == [2.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0, 60.0, 60.0, 60.0]


def test_buvid_refresh_once_mid_sequence(fast_sleep):
    transport = FakeTransport(
        [(200, {"code": -412}), (200, {"code": -412}), (200, ok_page([arc("BV1A")]))],
        spi=[SPI_OK, SPI_NEW],
    )
    client = bc.BiliClient(transport=transport, sleeper=fast_sleep,
                           jitter=lambda: 0.0)
    pages = client.fetch_pages(23191782, max_pages=1)
    assert len(pages[0]) == 1
    spi_calls = [c for c in transport.calls if "finger/spi" in c["url"]]
    assert len(spi_calls) == 2  # initial + exactly one mid-sequence refresh
    page_calls = [c for c in transport.calls if "recArchives" in c["url"]]
    assert page_calls[-1]["cookies"]["buvid3"] == "B3NEW"


# ---------------------------------------------------------------- page merge


def test_inter_page_pacing_is_real_delay(fast_sleep):
    # Regression: fetch_pages must pace pages with a real randomized delay
    # (0.8-1.6s like the retired script), not sleep(0).
    transport = FakeTransport(
        [
            (200, ok_page([arc("BV1A")], total=2)),
            (200, ok_page([arc("BV1B")], total=2)),
        ],
    )
    client = bc.BiliClient(transport=transport, sleeper=fast_sleep,
                           jitter=lambda: 0.0)
    pages = client.fetch_pages(23191782, max_pages=2)
    assert len(pages) == 2
    assert len(fast_sleep.waits) == 1  # one inter-page sleep
    assert fast_sleep.waits[0] >= 0.8
    assert fast_sleep.waits[0] <= 1.6


def test_inter_page_pacing_jitter_adds(fast_sleep):
    transport = FakeTransport(
        [
            (200, ok_page([arc("BV1A")], total=2)),
            (200, ok_page([arc("BV1B")], total=2)),
        ],
    )
    client = bc.BiliClient(transport=transport, sleeper=fast_sleep,
                           jitter=lambda: 0.5)
    client.fetch_pages(23191782, max_pages=2)
    assert fast_sleep.waits[0] == pytest.approx(0.8 + 0.5 * 0.8)


def test_merge_pages_dedupes_across_pages():
    pages = [
        [arc("BV1A"), arc("BV1B")],
        [arc("BV1C"), arc("BV1A")],  # BV1A repeated on page 2
    ]
    records = bc.BiliClient().merge_pages(pages)
    assert set(records) == {"BV1A", "BV1B", "BV1C"}
    assert records["BV1A"]["duration_s"] == 100
    assert records["BV1A"]["title"] == "t BV1A"


# ---------------------------------------------------------------- CLI


def test_cli_fetch_meta_writes_manifest(tmp_root, fast_sleep, monkeypatch):
    transport = FakeTransport(
        [
            (200, ok_page([arc("BV1A", duration=3600), arc("BV1B", duration=1800)],
                          total=2)),
            (200, ok_page([], total=2)),  # next page empty -> stop
        ],
    )
    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
    monkeypatch.setattr(bc, "default_sleeper", lambda: fast_sleep)
    rc = main(["fetch-meta", "--mid", "23191782", "--archive-root", tmp_root])
    assert rc == 0
    entries = ManifestStore(root=tmp_root).load()
    assert set(entries) == {"BV1A:p0", "BV1B:p0"}
    for e in entries.values():
        assert e["status"] == "meta_ok"
        assert e["work_id"].endswith(":p0")
    assert entries["BV1A:p0"]["duration_s"] == 3600
    assert entries["BV1A:p0"]["pubdate"] == 1700000000


def test_cli_resume_does_not_duplicate(tmp_root, fast_sleep, monkeypatch):
    store = ManifestStore(root=tmp_root)
    store.upsert(
        {"bvid": "BV1A", "status": "meta_ok", "title": "t BV1A",
         "duration_s": 100, "pubdate": 1}
    )
    transport = FakeTransport(
        [
            (200, ok_page([arc("BV1A"), arc("BV1B")], total=2)),
            (200, ok_page([], total=2)),
        ],
    )
    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
    monkeypatch.setattr(bc, "default_sleeper", lambda: fast_sleep)
    rc = main(["fetch-meta", "--mid", "23191782", "--resume",
               "--archive-root", tmp_root])
    assert rc == 0
    entries = store.load()
    assert set(entries) == {"BV1A:p0", "BV1B:p0"}
    lines = open(store.path, encoding="utf-8").read().strip().splitlines()
    bvids = [json.loads(l)["bvid"] for l in lines]
    assert sorted(bvids) == ["BV1A", "BV1B"]  # no dup lines


def test_cli_budget_exhausted_exit_2(tmp_root, fast_sleep, monkeypatch, capsys):
    transport = FakeTransport([(412, None)] * 5, spi=[SPI_OK, SPI_NEW])
    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
    monkeypatch.setattr(bc, "default_sleeper", lambda: fast_sleep)
    rc = main(["fetch-meta", "--mid", "23191782", "--archive-root", tmp_root])
    assert rc == 2
    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert "risk-control ceiling" in out
    assert "page 1" in out  # un-enumerated page count documented


def test_cli_pages_limit(tmp_root, fast_sleep, monkeypatch):
    transport = FakeTransport(
        [(200, ok_page([arc("BV1A")], total=99))],
    )
    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
    monkeypatch.setattr(bc, "default_sleeper", lambda: fast_sleep)
    rc = main(["fetch-meta", "--mid", "23191782", "--limit-pages", "1",
               "--archive-root", tmp_root])
    assert rc == 0
    entries = ManifestStore(root=tmp_root).load()
    assert set(entries) == {"BV1A:p0"}


# ------------------------------------------------- fix wave 1 (QC1/2/3) tests

import urllib.error

from bili_asr.cli import build_parser


class _FakeRequestsError(Exception):
    """Stand-in for requests.RequestException (tests don't import requests)."""


# H3: 200 + non-JSON body (None) is retryable risk, not AttributeError


def test_200_non_json_body_retryable_then_ok(fast_sleep):
    transport = FakeTransport(
        [(200, None), (200, ok_page([arc("BV1A")]))],
        spi=[SPI_OK, SPI_NEW],
    )
    client = bc.BiliClient(transport=transport, sleeper=fast_sleep,
                           jitter=lambda: 0.0)
    pages = client.fetch_pages(23191782, max_pages=1)
    assert len(pages[0]) == 1


def test_200_non_json_body_exhausts_budget(fast_sleep):
    transport = FakeTransport([(200, None)] * 5, spi=[SPI_OK, SPI_NEW])
    client = bc.BiliClient(transport=transport, sleeper=fast_sleep,
                           jitter=lambda: 0.0)
    with pytest.raises(bc.RiskBudgetExhausted) as exc:
        client.fetch_pages(23191782, max_pages=1)
    assert exc.value.last_code == "200-non-json"


def test_classify_risk_200_none_is_retryable():
    assert bc.classify_risk(200, None) == bc.RISK_RETRYABLE


# H1: transport exceptions are retried, then become RiskBudgetExhausted(2)


def test_transport_exception_retried_then_success(fast_sleep):
    transport = FakeTransport(
        [_FakeRequestsError("conn reset"),
         (200, ok_page([arc("BV1A")]))],
    )
    client = bc.BiliClient(transport=transport, sleeper=fast_sleep,
                           jitter=lambda: 0.0)
    pages = client.fetch_pages(23191782, max_pages=1)
    assert len(pages[0]) == 1


def test_transport_exception_exhausts_budget_exit_2(fast_sleep):
    transport = FakeTransport([_FakeRequestsError("dns")] * 5,
                              spi=[SPI_OK, SPI_NEW])
    client = bc.BiliClient(transport=transport, sleeper=fast_sleep,
                           jitter=lambda: 0.0)
    with pytest.raises(bc.RiskBudgetExhausted) as exc:
        client.fetch_pages(23191782, max_pages=1)
    assert exc.value.last_code == "_FakeRequestsError"


def test_spi_transport_error_wrapped_as_budget_exhausted(fast_sleep):
    transport = FakeTransport([(200, ok_page([arc("BV1A")]))],
                              spi=[_FakeRequestsError("timeout")])
    client = bc.BiliClient(transport=transport, sleeper=fast_sleep,
                           jitter=lambda: 0.0)
    with pytest.raises(bc.RiskBudgetExhausted):
        client.fetch_pages(23191782, max_pages=1)


# H2: partial pages persisted on RiskBudgetExhausted / GoneResponse mid-run


def test_cli_budget_exhausted_midrun_persists_partial(tmp_root, fast_sleep,
                                                      monkeypatch, capsys):
    transport = FakeTransport(
        [
            (200, ok_page([arc("BV1A"), arc("BV1B")], total=99)),
            (412, None), (412, None), (412, None), (412, None), (412, None),
        ],
        spi=[SPI_OK, SPI_NEW],
    )
    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
    monkeypatch.setattr(bc, "default_sleeper", lambda: fast_sleep)
    rc = main(["fetch-meta", "--mid", "23191782", "--archive-root", tmp_root])
    assert rc == 2
    entries = ManifestStore(root=tmp_root).load()
    assert set(entries) == {"BV1A:p0", "BV1B:p0"}  # partial run persisted
    err = capsys.readouterr().err
    assert "page 2" in err
    assert "2" in err and "persisted" in err


def test_cli_budget_exhausted_page1_persists_nothing(tmp_root, fast_sleep,
                                                     monkeypatch):
    transport = FakeTransport([(412, None)] * 5, spi=[SPI_OK, SPI_NEW])
    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
    monkeypatch.setattr(bc, "default_sleeper", lambda: fast_sleep)
    rc = main(["fetch-meta", "--mid", "23191782", "--archive-root", tmp_root])
    assert rc == 2
    assert not os.path.exists(ManifestStore(root=tmp_root).path)


# APIResponseError/GoneResponse: persist partial, honest message


def test_cli_api_error_midrun_persists_partial(tmp_root, fast_sleep,
                                               monkeypatch, capsys):
    store = ManifestStore(root=tmp_root)
    store.upsert({"bvid": "BVexisting", "status": "subtitle_done"})
    transport = FakeTransport(
        [
            (200, ok_page([arc("BV1A")], total=99)),
            (200, {"code": -400}),
        ],
    )
    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
    monkeypatch.setattr(bc, "default_sleeper", lambda: fast_sleep)
    rc = main([
        "fetch-meta", "--mid", "23191782", "--resume",
        "--archive-root", tmp_root,
    ])
    assert rc == 2
    entries = store.load()
    assert entries["BVexisting"]["status"] == "subtitle_done"
    assert entries["BV1A:p0"]["status"] == "meta_ok"
    assert all(entry.get("status") != "gone" for entry in entries.values())
    err = capsys.readouterr().err
    assert "API response error (code -400)" in err
    assert "Traceback" not in err


def test_cli_gone_midrun_persists_partial(tmp_root, fast_sleep, monkeypatch,
                                          capsys):
    transport = FakeTransport(
        [
            (200, ok_page([arc("BV1A")], total=99)),
            (200, ok_page([arc("BV1B")], total=99)),
            (404, None),
        ],
    )
    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
    monkeypatch.setattr(bc, "default_sleeper", lambda: fast_sleep)
    rc = main(["fetch-meta", "--mid", "23191782", "--archive-root", tmp_root])
    assert rc == 2
    entries = ManifestStore(root=tmp_root).load()
    assert set(entries) == {"BV1A:p0", "BV1B:p0"}
    err = capsys.readouterr().err
    assert "2 page(s)" in err
    assert "no pages enumerated" not in err


def test_cli_gone_on_first_page_reports_no_pages(tmp_root, fast_sleep,
                                                 monkeypatch, capsys):
    transport = FakeTransport([(200, {"code": -62002})])
    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
    monkeypatch.setattr(bc, "default_sleeper", lambda: fast_sleep)
    rc = main(["fetch-meta", "--mid", "23191782", "--archive-root", tmp_root])
    assert rc == 2
    err = capsys.readouterr().err
    assert "no pages" in err


# QC2-2: argparse usage errors exit 1, not 2


def test_argparse_usage_error_exits_1():
    parser = build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--mid", "abc"])
    assert exc.value.code == 1


def test_argparse_invalid_choice_exits_1():
    parser = build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["frobnicate"])
    assert exc.value.code == 1


def test_argparse_help_exits_0():
    parser = build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--help"])
    assert exc.value.code == 0


# H1 CLI-level: RiskBudgetExhausted carries no traceback (exit 2, summary)


def test_cli_unexpected_error_exit_1_no_traceback(tmp_root, monkeypatch,
                                                  capsys):
    sentinel = "SESSDATA=FETCH-SECRET https://cdn.example/audio.m4s?token=SIGNED"

    def boom(self, *a, **k):
        raise RuntimeError(sentinel)

    monkeypatch.setattr(bc.BiliClient, "fetch_pages", boom)
    rc = main(["fetch-meta", "--mid", "1", "--archive-root", tmp_root])
    assert rc == 1
    err = capsys.readouterr().err
    assert "fetch-meta: unexpected error" in err
    assert "Traceback" not in err
    assert "FETCH-SECRET" not in err
    assert "SIGNED" not in err


def test_cli_transport_error_redacts_exception_message(
    tmp_root, fast_sleep, monkeypatch, capsys
):
    sentinel = "SESSDATA=TRANSPORT-SECRET https://cdn.example/a.m4s?token=SIGNED"
    transport = FakeTransport(
        [_FakeRequestsError(sentinel)] * 5,
        spi=[SPI_OK, SPI_NEW],
    )
    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
    monkeypatch.setattr(bc, "default_sleeper", lambda: fast_sleep)

    rc = main(["fetch-meta", "--mid", "1", "--archive-root", tmp_root])

    assert rc == 2
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "_FakeRequestsError" in output
    assert "TRANSPORT-SECRET" not in output
    assert "SIGNED" not in output
    assert not os.path.exists(ManifestStore(root=tmp_root).path)
