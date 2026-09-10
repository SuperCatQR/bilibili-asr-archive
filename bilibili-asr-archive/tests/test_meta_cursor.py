"""MetaCursorStore sidecar contract (no live HTTP).

The fetch-meta CLI resume/limited/complete behavior moved to the SQLite
metadata path (tests/test_metadata_cli.py and tests/test_metadata_e2e.py);
this module keeps covering the MetaCursorStore sidecar that scheduler and
coordinator flows still use.
"""

from __future__ import annotations

import os

import pytest

from bili_asr import bili_client as bc
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
    pages = client.fetch_pages(23191782, max_pages=1, start_page=2)
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


# (fetch-meta CLI resume/limited/complete behavior moved to the SQLite
# metadata path: tests/test_metadata_cli.py and tests/test_metadata_e2e.py)


def test_fetch_pages_stops_at_last_catalog_page(fast_sleep):
    """R4: complete when pn reaches ceil(total/ps), no empty-page pair."""
    transport = FakeTransport(
        [
            (200, ok_page([arc("BV1A")], total=2)),
        ],
    )
    client = bc.BiliClient(transport=transport, sleeper=fast_sleep, jitter=lambda: 0.0)
    pages = client.fetch_pages(23191782, start_page=1)
    assert len(pages) == 1
    assert client.enumeration_complete is True
    leftover = [c for c in transport.calls if "recArchivesByKeywords" in c["url"]]
    assert len(leftover) == 1


def test_fetch_pages_stops_when_nonempty_adds_no_new(fast_sleep):
    transport = FakeTransport(
        [
            (200, ok_page([arc("BV1A")], total=90)),
        ],
    )
    client = bc.BiliClient(transport=transport, sleeper=fast_sleep, jitter=lambda: 0.0)
    pages = client.fetch_pages(23191782, start_page=2, known_bvids={"BV1A"})
    assert len(pages) == 1
    assert client.enumeration_complete is True


def test_load_corrupt_cursor_notes_stderr(tmp_root, capsys):
    path = _cursor(tmp_root).path
    os.makedirs(tmp_root, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{not json")
    assert _cursor(tmp_root).load() is None
    assert "corrupt sidecar" in capsys.readouterr().err


def test_cursor_strips_extra_keys_and_rejects_secrets(tmp_root):
    store = _cursor(tmp_root)
    stored = store.replace_atomic(
        {
            "mid": 1,
            "next_page": 2,
            "total": 9,
            "state": "risk_interrupted",
            "last_api_error_code": 412,
            "updated_at": utc_now_iso(),
            "cookie": "SESSDATA=leak",
            "signed_url": "https://example.com/playurl?sign=abc",
            "exception": "Traceback (most recent call last): boom",
        }
    )
    assert set(stored) == {
        "mid", "next_page", "total", "state",
        "last_api_error_code", "updated_at",
    }
    text = open(store.path, encoding="utf-8").read()
    assert "SESSDATA" not in text
    assert "cookie" not in text.lower()
    assert "https://" not in text
    assert "Traceback" not in text
    assert "playurl" not in text
    with pytest.raises(ValueError, match="redacted|credentials"):
        store.replace_atomic(
            {
                "mid": 1,
                "next_page": 2,
                "total": 9,
                "state": "risk_interrupted",
                "last_api_error_code": "SESSDATA=abc",
                "updated_at": utc_now_iso(),
            }
        )


def test_readme_documents_resume_and_exit_2():
    root = os.path.join(os.path.dirname(__file__), "..")
    text = open(os.path.join(root, "README.md"), encoding="utf-8").read()
    assert "--resume" in text
    assert "exit 2" in text.lower() or "Exit 2" in text or "| 2 |" in text
    assert "meta-cursor.json" in text
    assert "risk_interrupted" in text
    assert "SESSDATA" in text
    assert "only" in text.lower() or "auto-continues" in text.lower()
