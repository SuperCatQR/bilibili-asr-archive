"""MetaCursorStore + fetch-meta resume/limited/complete (no live HTTP)."""

from __future__ import annotations

import json
import os

import pytest

from bili_asr import bili_client as bc
from bili_asr.cli import main
from bili_asr.manifest import ManifestStore
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


def test_cli_resume_persists_after_each_page(tmp_root, fast_sleep, monkeypatch):
    """R1: --resume still merges JSONL and advances next_page per page."""
    ManifestStore(root=tmp_root).save(
        {
            "BV1A:p0": {
                "work_id": "BV1A:p0", "bvid": "BV1A", "page_index": 0,
                "cid": 1, "status": "meta_ok",
            },
        }
    )
    _seed_risk(tmp_root, next_page=2, total=90)
    transport = FakeTransport(
        [
            (200, ok_page([arc("BV1B")], total=90)),
            (412, None), (412, None), (412, None), (412, None), (412, None),
        ],
        spi=[SPI_OK, SPI_NEW],
    )
    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
    monkeypatch.setattr(bc, "default_sleeper", lambda: fast_sleep)
    rc = main([
        "fetch-meta", "--mid", "23191782", "--resume",
        "--archive-root", tmp_root,
    ])
    assert rc == 2
    entries = ManifestStore(root=tmp_root).load()
    assert "BV1A:p0" in entries
    assert "BV1B:p0" in entries
    cursor = _cursor(tmp_root).load()
    assert cursor["state"] == "risk_interrupted"
    assert cursor["next_page"] == 3


def test_cli_no_resume_merges_prior_jsonl_not_prefix(
    tmp_root, fast_sleep, monkeypatch,
):
    """R2: without --resume, page-1 must not clobber a complete JSONL."""
    ManifestStore(root=tmp_root).save(
        {
            "BVOLD:p0": {
                "work_id": "BVOLD:p0", "bvid": "BVOLD", "page_index": 0,
                "cid": 9, "status": "meta_ok",
            },
        }
    )
    _seed_risk(tmp_root, next_page=5, total=99)
    transport = FakeTransport(
        [(200, ok_page([arc("BV1A")], total=1))],
    )
    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
    monkeypatch.setattr(bc, "default_sleeper", lambda: fast_sleep)
    rc = main(["fetch-meta", "--mid", "23191782", "--archive-root", tmp_root])
    assert rc == 0
    entries = ManifestStore(root=tmp_root).load()
    assert set(entries) >= {"BVOLD:p0", "BV1A:p0"}
    cursor = _cursor(tmp_root).load()
    assert cursor["state"] == "complete"
    assert _cursor(tmp_root).resume_start_page(23191782) is None


def test_cli_limit_pages_counts_this_call(tmp_root, fast_sleep, monkeypatch):
    """R3: --resume from next_page=5 plus --limit-pages 2 fetches two pages."""
    _seed_risk(tmp_root, next_page=5, total=300)
    transport = FakeTransport(
        [
            (200, ok_page([arc("BV1E")], total=300)),
            (200, ok_page([arc("BV1F")], total=300)),
        ],
    )
    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
    monkeypatch.setattr(bc, "default_sleeper", lambda: fast_sleep)
    rc = main([
        "fetch-meta", "--mid", "23191782", "--resume", "--limit-pages", "2",
        "--archive-root", tmp_root,
    ])
    assert rc == 0
    page_calls = [c for c in transport.calls if "recArchivesByKeywords" in c["url"]]
    assert [c["params"]["pn"] for c in page_calls] == [5, 6]
    cursor = _cursor(tmp_root).load()
    assert cursor["state"] == "limited"
    assert cursor["next_page"] == 7


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


def test_cli_page2_stop_resume_is_idempotent(tmp_root, fast_sleep, monkeypatch):
    """Risk stop on page 2 → next_page=2; --resume starts there with no dup rows."""
    transport = FakeTransport(
        [
            (200, ok_page([arc("BV1A"), arc("BV1B")], total=33)),
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
    store = ManifestStore(root=tmp_root)
    first = store.load()
    assert set(first) == {"BV1A:p0", "BV1B:p0"}
    assert cursor["state"] != "complete"

    transport2 = FakeTransport(
        [
            (200, ok_page([arc("BV1C")], total=33)),
            (200, ok_page([], total=33)),
            (200, ok_page([], total=33)),
        ],
    )
    monkeypatch.setattr(bc, "build_default_transport", lambda: transport2)
    rc2 = main([
        "fetch-meta", "--mid", "23191782", "--resume",
        "--archive-root", tmp_root,
    ])
    assert rc2 == 0
    page_calls = [c for c in transport2.calls if "recArchivesByKeywords" in c["url"]]
    assert page_calls[0]["params"]["pn"] == 2
    entries = store.load()
    assert set(entries) == {"BV1A:p0", "BV1B:p0", "BV1C:p0"}
    lines = open(store.path, encoding="utf-8").read().strip().splitlines()
    work_ids = [json.loads(line)["work_id"] for line in lines]
    assert len(work_ids) == len(set(work_ids))
    assert _cursor(tmp_root).load()["state"] == "complete"


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
