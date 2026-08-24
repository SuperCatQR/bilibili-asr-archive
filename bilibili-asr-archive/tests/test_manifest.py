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


def _page(bvid, page_index, cid, label=""):
    from bili_asr.page_identity import page_identity
    return page_identity(bvid, page_index, cid, label)


def test_upsert_keys_by_work_id(store, tmp_root):
    store.upsert(_entry("BV1aa", work_id="BV1aa:p0", page_index=0, cid=11))
    loaded = ManifestStore(root=tmp_root).load()
    assert set(loaded) == {"BV1aa:p0"}
    assert loaded["BV1aa:p0"]["bvid"] == "BV1aa"


def test_get_compatible_single_page_row(store):
    store.upsert(_entry("BV1aa", work_id="BV1aa:p0", page_index=0, cid=1))
    got = store.get_compatible("BV1aa")
    assert got is not None
    assert got["work_id"] == "BV1aa:p0"


def test_get_compatible_does_not_guess_among_pages(store):
    store.upsert(_entry("BV1aa", work_id="BV1aa:p0", page_index=0, cid=1, title="p0"))
    store.upsert(_entry("BV1aa", work_id="BV1aa:p1", page_index=1, cid=2, title="p1"))
    assert store.get_compatible("BV1aa") is None
    assert store.get("BV1aa:p0")["title"] == "p0"
    assert store.get("BV1aa:p1")["title"] == "p1"


def test_migrate_single_page_bare_row(store, tmp_root):
    store.upsert(_entry("BV1aa"))
    report = store.migrate_legacy_rows(
        lambda bvid: [_page(bvid, 0, cid=42, label="only")]
    )
    assert report.migrated == ["BV1aa:p0"]
    assert report.unresolved == []
    loaded = ManifestStore(root=tmp_root).load()
    assert set(loaded) == {"BV1aa:p0"}
    row = loaded["BV1aa:p0"]
    assert row["bvid"] == "BV1aa"
    assert row["page_index"] == 0
    assert row["cid"] == 42
    assert row["page_label"] == "only"
    assert row["status"] == "meta_ok"


def test_freeze_multipart_bare_row_byte_stable(store, tmp_root):
    store.upsert(_entry("BV1mm", title="keep-me", duration_s=9))
    before = open(_manifest_path(tmp_root), encoding="utf-8").read()
    original_obj = json.loads(before.splitlines()[0])

    report = store.migrate_legacy_rows(
        lambda bvid: [
            _page(bvid, 0, cid=1, label="a"),
            _page(bvid, 1, cid=2, label="b"),
        ]
    )
    assert report.migrated == []
    assert report.unresolved == ["BV1mm"]

    after_lines = open(_manifest_path(tmp_root), encoding="utf-8").read().splitlines()
    assert len(after_lines) == 1
    after_obj = json.loads(after_lines[0])
    for key, value in original_obj.items():
        assert after_obj[key] == value
    assert after_obj["unresolved"] is True
    assert after_obj["unresolved_reason"] == "ambiguous_bare_bvid"
    assert after_obj["excluded_from_page_processing"] is True
    assert "work_id" not in after_obj
    assert "page_index" not in after_obj
    assert "cid" not in after_obj
    assert store.get_compatible("BV1mm")["unresolved"] is True


def test_migrate_stops_on_pN_artifact_collision(store, tmp_root):
    store.upsert(_entry("BV1aa"))
    srt_dir = os.path.join(tmp_root, "transcripts", "srt")
    os.makedirs(srt_dir)
    open(os.path.join(srt_dir, "BV1aa.p1.srt"), "w").write("x")
    report = store.migrate_legacy_rows(
        lambda bvid: [_page(bvid, 0, cid=1)]
    )
    assert report.migrated == []
    assert report.unresolved == ["BV1aa"]
    loaded = ManifestStore(root=tmp_root).load()
    assert "BV1aa" in loaded
    assert loaded["BV1aa"]["unresolved"] is True


def test_migrate_collision_existing_work_id_row(store, tmp_root):
    from bili_asr.manifest import ManifestMigrationCollision

    store.upsert(_entry("BV1aa"))
    store.upsert(_entry("BV1aa", work_id="BV1aa:p0", page_index=0, cid=7))
    with pytest.raises(ManifestMigrationCollision):
        store.migrate_legacy_rows(lambda bvid: [_page(bvid, 0, cid=1)])
