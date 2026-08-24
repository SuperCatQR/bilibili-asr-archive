"""MetaCursorStore + fetch-meta resume/limited/complete (no live HTTP)."""

from __future__ import annotations

import json
import os

import pytest

from bili_asr import bili_client as bc
from bili_asr.cli import main
from bili_asr.meta_cursor import MetaCursorStore, utc_now_iso

from test_fetch_meta import FakeTransport, FastSleeper, SPI_NEW, SPI_OK, arc, ok_page


@pytest.fixture
def fast_sleep():
    return FastSleeper()


def _cursor(tmp_root):
    return MetaCursorStore(root=tmp_root)


def _seed_risk(tmp_root, mid=23191782, next_page=2, total=99, code=412):
    return _cursor(tmp_root).replace_atomic(
        {
            "mid": mid,
            "next_page": next_page,
            "total": total,
            "state": "risk_interrupted",
            "last_api_error_code": code,
            "updated_at": utc_now_iso(),
        }
    )


def test_schema_roundtrip(tmp_root):
    store = _cursor(tmp_root)
    stored = store.replace_atomic(
        {
            "mid": 23191782,
            "next_page": 3,
            "total": 90,
            "state": "limited",
            "last_api_error_code": None,
            "updated_at": utc_now_iso(),
        }
    )
    loaded = store.load()
    assert loaded == stored
    assert loaded["mid"] == 23191782
    assert loaded["next_page"] == 3
    assert loaded["state"] == "limited"
    assert os.path.basename(store.path) == "meta-cursor.json"
    assert os.path.dirname(store.path) == tmp_root


def test_running_is_not_persisted(tmp_root):
    store = _cursor(tmp_root)
    with pytest.raises(ValueError, match="running"):
        store.replace_atomic(
            {
                "mid": 1,
                "next_page": 1,
                "total": None,
                "state": "running",
                "last_api_error_code": None,
                "updated_at": utc_now_iso(),
            }
        )
    assert store.load() is None


def test_atomic_replace_no_partial(tmp_root):
    store = _cursor(tmp_root)
    store.replace_atomic(
        {
            "mid": 1,
            "next_page": 1,
            "total": None,
            "state": "complete",
            "last_api_error_code": None,
            "updated_at": utc_now_iso(),
        }
    )
    store.replace_atomic(
        {
            "mid": 1,
            "next_page": 4,
            "total": 10,
            "state": "limited",
            "last_api_error_code": None,
            "updated_at": utc_now_iso(),
        }
    )
    assert not os.path.exists(store.path + ".tmp")
    assert store.load()["state"] == "limited"
    assert store.load()["next_page"] == 4


def test_resume_start_page_only_matching_risk(tmp_root):
    store = _cursor(tmp_root)
    _seed_risk(tmp_root, mid=23191782, next_page=2)
    assert store.resume_start_page(23191782) == 2
    assert store.resume_start_page(999) is None
    store.replace_atomic(
        {
            "mid": 23191782,
            "next_page": 2,
            "total": 99,
            "state": "limited",
            "last_api_error_code": None,
            "updated_at": utc_now_iso(),
        }
    )
    assert store.resume_start_page(23191782) is None


def test_fetch_pages_start_page(fast_sleep):
    transport = FakeTransport(
        [
            (200, ok_page([arc("BV1B")], total=2)),
        ],
    )
    client = bc.BiliClient(transport=transport, sleeper=fast_sleep, jitter=lambda: 0.0)
    pages = client.fetch_pages(23191782, max_pages=2, start_page=2)
    assert len(pages) == 1
    assert pages[0][0]["bvid"] == "BV1B"
    page_calls = [c for c in transport.calls if "recArchivesByKeywords" in c["url"]]
    assert page_calls[0]["params"]["pn"] == 2
    assert client.last_completed_page == 2


def test_bili_client_does_not_import_meta_cursor():
    import bili_asr.bili_client as mod

    assert "bili_asr.meta_cursor" not in getattr(mod, "__dict__", {})
    src = open(mod.__file__, encoding="utf-8").read()
    assert "meta_cursor" not in src


def test_cli_risk_writes_cursor_exit_2(tmp_root, fast_sleep, monkeypatch, capsys):
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
    cursor = _cursor(tmp_root).load()
    assert cursor["state"] == "risk_interrupted"
    assert cursor["next_page"] == 2
    assert cursor["mid"] == 23191782
    assert cursor["last_api_error_code"] is not None
    err = capsys.readouterr().err
    assert "page 2" in err


def test_cli_resume_consumes_risk_cursor(tmp_root, fast_sleep, monkeypatch):
    _seed_risk(tmp_root, next_page=2, total=2)
    transport = FakeTransport(
        [
            (200, ok_page([arc("BV1B")], total=2)),
            (200, ok_page([], total=2)),
            (200, ok_page([], total=2)),
        ],
    )
    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
    monkeypatch.setattr(bc, "default_sleeper", lambda: fast_sleep)
    rc = main([
        "fetch-meta", "--mid", "23191782", "--resume",
        "--archive-root", tmp_root,
    ])
    assert rc == 0
    page_calls = [c for c in transport.calls if "recArchivesByKeywords" in c["url"]]
    assert page_calls[0]["params"]["pn"] == 2
    cursor = _cursor(tmp_root).load()
    assert cursor["state"] == "complete"


def test_cli_without_resume_starts_at_page_one(tmp_root, fast_sleep, monkeypatch):
    _seed_risk(tmp_root, next_page=5, total=99)
    transport = FakeTransport(
        [
            (200, ok_page([arc("BV1A")], total=1)),
        ],
    )
    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
    monkeypatch.setattr(bc, "default_sleeper", lambda: fast_sleep)
    rc = main(["fetch-meta", "--mid", "23191782", "--archive-root", tmp_root])
    assert rc == 0
    page_calls = [c for c in transport.calls if "recArchivesByKeywords" in c["url"]]
    assert page_calls[0]["params"]["pn"] == 1
    cursor = _cursor(tmp_root).load()
    assert cursor["state"] == "complete"
    assert cursor["next_page"] == 2


def test_cli_limit_pages_is_limited_not_complete(
    tmp_root, fast_sleep, monkeypatch, capsys
):
    transport = FakeTransport(
        [(200, ok_page([arc("BV1A")], total=99))],
    )
    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
    monkeypatch.setattr(bc, "default_sleeper", lambda: fast_sleep)
    rc = main([
        "fetch-meta", "--mid", "23191782", "--limit-pages", "1",
        "--archive-root", tmp_root,
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "complete" not in out
    assert "limited" in out
    cursor = _cursor(tmp_root).load()
    assert cursor["state"] == "limited"
    assert cursor["next_page"] == 2
    assert _cursor(tmp_root).resume_start_page(23191782) is None


def test_cli_full_run_marks_complete(tmp_root, fast_sleep, monkeypatch, capsys):
    transport = FakeTransport(
        [
            (200, ok_page([arc("BV1A"), arc("BV1B")], total=2)),
        ],
    )
    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
    monkeypatch.setattr(bc, "default_sleeper", lambda: fast_sleep)
    rc = main(["fetch-meta", "--mid", "23191782", "--archive-root", tmp_root])
    assert rc == 0
    out = capsys.readouterr().out
    assert "enumeration: complete" in out
    cursor = _cursor(tmp_root).load()
    assert cursor["state"] == "complete"
    text = open(_cursor(tmp_root).path, encoding="utf-8").read()
    assert "SESSDATA" not in text
    assert "cookie" not in text.lower()
