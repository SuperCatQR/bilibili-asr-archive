import json
import os

import pytest

from bili_asr.manifest import ManifestStore


@pytest.fixture
def store(tmp_root):
    return ManifestStore(root=tmp_root)


def _entry(bvid, **kw):
    base = {
        "bvid": bvid,
        "aid": 1,
        "title": "some title",
        "duration_s": 100,
        "pubdate": 1785701056,
        "status": "meta_ok",
    }
    base.update(kw)
    return base


def _manifest_path(root):
    return os.path.join(root, "manifest", "manifest.jsonl")


def test_load_empty_missing_file(store):
    assert store.load() == {}


def test_upsert_then_reload(store, tmp_root):
    store.upsert(_entry("BV1aa"))
    store.upsert(_entry("BV1bb", status="pending"))

    loaded = ManifestStore(root=tmp_root).load()
    assert set(loaded) == {"BV1aa", "BV1bb"}
    assert loaded["BV1aa"]["status"] == "meta_ok"
    assert loaded["BV1bb"]["status"] == "pending"


def test_upsert_dedupe_same_bvid(store, tmp_root):
    store.upsert(_entry("BV1aa", status="pending"))
    store.upsert(_entry("BV1aa", status="meta_ok", title="new"))

    loaded = ManifestStore(root=tmp_root).load()
    assert len(loaded) == 1
    assert loaded["BV1aa"]["status"] == "meta_ok"
    assert loaded["BV1aa"]["title"] == "new"

    with open(_manifest_path(tmp_root), encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    assert len(lines) == 1


def test_resume_dedupe_no_duplicate_bvids(store, tmp_root):
    # simulate resume: existing file, then upsert same + new
    store.upsert(_entry("BV1aa"))
    store2 = ManifestStore(root=tmp_root)
    store2.load()
    store2.upsert(_entry("BV1aa"))  # resume re-upsert same bvid
    store2.upsert(_entry("BV1cc"))

    with open(_manifest_path(tmp_root), encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    bvids = [json.loads(l)["bvid"] for l in lines]
    assert len(bvids) == len(set(bvids)) == 2


def test_get_missing_returns_none(store):
    assert store.get("BV1zz") is None


def test_save_roundtrip_preserves_fields(store, tmp_root):
    e = _entry("BV1aa", title="chinese title", duration_s=3105)
    store.upsert(e)
    loaded = ManifestStore(root=tmp_root).load()["BV1aa"]
    assert loaded["title"] == "chinese title"
    assert loaded["duration_s"] == 3105
    assert loaded["pubdate"] == 1785701056


def test_status_ssot_names(store):
    from bili_asr.manifest import VALID_STATUSES

    expected = {
        "pending", "meta_ok", "sub_checked", "subtitle_done",
        "needs_audio", "audio_ok", "asr_done", "archived", "gone",
    }
    assert expected == set(VALID_STATUSES)


def test_upsert_rejects_unknown_status(store):
    with pytest.raises(ValueError):
        store.upsert(_entry("BV1aa", status="bogus"))


def test_save_no_entries_writes_nothing(store, tmp_root):
    store.save({})
    assert not os.path.exists(_manifest_path(tmp_root))
