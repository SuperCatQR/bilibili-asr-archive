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

from tests.support.fetch_meta import FakeTransport, FastSleeper, SPI_NEW, SPI_OK, arc, ok_page


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


def test_fetch_pages_ignores_total_and_walks_to_the_empty_page(fast_sleep):
    """R4 (re-scoped 2026-09-30): completion rests on row evidence, not `total`.

    R4 originally asked for a stop at ``ceil(total/ps)`` to cap a walk that
    could otherwise loop when upstream repeats its last page. That loop is
    already caught by the row-based stop below it -- a repeated page is
    non-empty and adds no new bvids -- while a `total`-derived page bound can
    truncate the walk: ``page.total`` and the ``archives`` rows are different
    quantities upstream (measured 2026-09-30: total 1739 vs 1730 rows served,
    and ``爱情`` 13 vs 12). So the page bound is gone and this test pins the
    replacement: a page whose ``total`` is already satisfied does not end the
    walk; the empty page does.
    """
    transport = FakeTransport(
        [
            (200, ok_page([arc("BV1A")], total=1)),
            (200, ok_page([], total=1)),
            (200, ok_page([], total=1)),
        ],
    )
    client = bc.BiliClient(transport=transport, sleeper=fast_sleep, jitter=lambda: 0.0)
    pages = client.fetch_pages(23191782, start_page=1)
    assert len(pages) == 1
    assert client.enumeration_complete is True
    page_calls = [c for c in transport.calls if "recArchivesByKeywords" in c["url"]]
    assert [c["params"]["pn"] for c in page_calls] == [1, 2, 3]
    assert client.last_observed_total == 1


def test_fetch_pages_does_not_truncate_when_total_undercounts(fast_sleep):
    """The defect this guards: a `total` below the true row count must not cut the walk.

    ``total=1`` with two real rows on two pages is the shape that a
    ``total``-derived bound turns into a silent truncation -- the walk would
    stop after one page and lose BV1B entirely.
    """
    transport = FakeTransport(
        [
            (200, ok_page([arc("BV1A")], total=1)),
            (200, ok_page([arc("BV1B")], total=1)),
            (200, ok_page([], total=1)),
            (200, ok_page([], total=1)),
        ],
    )
    client = bc.BiliClient(transport=transport, sleeper=fast_sleep, jitter=lambda: 0.0)
    pages = client.fetch_pages(23191782, start_page=1)
    served = {a["bvid"] for page in pages for a in page}
    assert served == {"BV1A", "BV1B"}, "a low `total` must not drop a whole page"
    assert client.enumeration_complete is True


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
