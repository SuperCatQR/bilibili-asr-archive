"""Unit tests for bili_client transport: mocked transport only, no live network.

The fetch-meta CLI contract lives in tests/test_metadata_cli.py (SQLite
metadata path).  This module keeps covering the bili_client transport
layer that the future subtitle/audio/ASR modules still drive.
"""

from __future__ import annotations

import pytest

from bili_asr import bili_client as bc
from bili_asr.cli.parser import build_parser
from tests.support.fetch_meta import FakeTransport, FastSleeper, SPI_NEW, SPI_OK, arc, ok_page

API = "https://api.bilibili.com"











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


def test_buvid_bootstrap_uses_browser_headers_and_optional_sessdata():
    transport = FakeTransport(
        [(200, ok_page([arc("BV1A")]))],
        spi=[(200, {"code": 0, "data": {"b_3": "BV3XXX", "b_4": "BV4YYY"}})],
    )
    client = bc.BiliClient(
        transport=transport,
        sessdata="test-sessdata-value",
        sleeper=FastSleeper(),
    )

    client.fetch_pages(23191782, max_pages=1)

    spi_call = transport.calls[0]
    assert spi_call["headers"] == bc.BASE_HEADERS
    assert set(spi_call["cookies"]) == {"SESSDATA"}
    assert spi_call["cookies"]["SESSDATA"] == "test-sessdata-value"


def test_archive_enumeration_sends_optional_sessdata():
    transport = FakeTransport(
        [(200, ok_page([arc("BV1A")]))],
        spi=[(200, {"code": 0, "data": {"b_3": "B3", "b_4": "B4"}})],
    )
    client = bc.BiliClient(
        transport=transport,
        sessdata="test-sessdata-value",
        sleeper=FastSleeper(),
    )

    client.fetch_pages(23191782, max_pages=1)

    page_call = next(c for c in transport.calls if "recArchives" in c["url"])
    assert page_call["cookies"]["SESSDATA"] == "test-sessdata-value"
    assert page_call["cookies"]["buvid3"] == "B3"
    assert page_call["cookies"]["buvid4"] == "B4"


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
            (200, ok_page([arc("BV1A")], total=60)),
            (200, ok_page([arc("BV1B")], total=60)),
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
            (200, ok_page([arc("BV1A")], total=60)),
            (200, ok_page([arc("BV1B")], total=60)),
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


# ------------------------------------------------- fix wave 1 (QC1/2/3) tests
# (the fetch-meta CLI contract moved to tests/test_metadata_cli.py — SQLite
# metadata path; these tests keep covering the bili_client transport layer
# that the future subtitle/audio/ASR modules still drive)


# ------------------------------------------------- fix wave 1 (QC1/2/3) tests

import urllib.error

from bili_asr.cli.parser import build_parser


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
