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


def _auto(bvid, page_index=0, cid=1, **kw):
    work_id = kw.pop("work_id", f"{bvid}:p{page_index}")
    return _entry(
        bvid, work_id=work_id, page_index=page_index, cid=cid, **kw
    )


def seed_legacy(store, *entries):
    store.load()
    data = dict(store._entries)
    for entry in entries:
        data[entry.get("work_id") or entry["bvid"]] = entry
    store.save(data)


def _manifest_path(root):
    return os.path.join(root, "manifest", "manifest.jsonl")


def test_load_empty_missing_file(store):
    assert store.load() == {}


def test_manifest_symlink_is_not_read_or_replaced_by_any_write_path(store, tmp_root):
    path = __import__("pathlib").Path(_manifest_path(tmp_root))
    path.parent.mkdir()
    outside = path.parent.parent / "outside.jsonl"
    original = json.dumps(_auto("BVoutside")) + "\n"
    outside.write_text(original, encoding="utf-8")
    path.symlink_to(outside)

    with pytest.raises(OSError):
        store.save({_auto("BVsave")["work_id"]: _auto("BVsave")})
    with pytest.raises(OSError):
        store.compact()
    with pytest.raises(OSError):
        store.migrate_legacy_rows(lambda _bvid: [])

    assert path.is_symlink()
    assert outside.read_text(encoding="utf-8") == original


def test_upsert_then_reload(store, tmp_root):
    store.upsert(_auto("BV1aa"))
    store.upsert(_auto("BV1bb", cid=2, status="pending"))

    loaded = ManifestStore(root=tmp_root).load()
    assert set(loaded) == {"BV1aa:p0", "BV1bb:p0"}
    assert loaded["BV1aa:p0"]["status"] == "meta_ok"
    assert loaded["BV1bb:p0"]["status"] == "pending"


def test_upsert_rejects_nonserializable_extra_fields(store):
    with pytest.raises(ValueError, match="not serializable"):
        store.upsert(_auto("BVbad", unsupported={"value"}))


def test_manifest_parent_symlink_does_not_create_external_lock(store, tmp_root):
    root = __import__("pathlib").Path(tmp_root)
    outside = root / "outside"
    outside.mkdir()
    (root / "manifest").symlink_to(outside, target_is_directory=True)

    with pytest.raises(OSError):
        store.upsert(_auto("BVescape"))

    assert not (outside / "manifest.jsonl.lock").exists()


def test_upsert_dedupe_same_bvid(store, tmp_root):
    store.upsert(_auto("BV1aa", status="pending"))
    store.upsert(_auto("BV1aa", status="meta_ok", title="new"))

    loaded = ManifestStore(root=tmp_root).load()
    assert len(loaded) == 1
    assert loaded["BV1aa:p0"]["status"] == "meta_ok"
    assert loaded["BV1aa:p0"]["title"] == "new"

    with open(_manifest_path(tmp_root), encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    assert len(lines) == 2


def test_resume_dedupe_no_duplicate_bvids(store, tmp_root):
    # simulate resume: existing file, then upsert same + new
    store.upsert(_auto("BV1aa"))
    store2 = ManifestStore(root=tmp_root)
    store2.load()
    store2.upsert(_auto("BV1aa"))  # resume re-upsert same work_id
    store2.upsert(_auto("BV1cc", cid=3))

    with open(_manifest_path(tmp_root), encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    bvids = [json.loads(l)["bvid"] for l in lines]
    assert len(bvids) == 3
    assert len({bvids[0], bvids[1], bvids[2]}) == 2




def test_non_object_manifest_row_is_rejected(store, tmp_root):
    path = _manifest_path(tmp_root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("[]\n")
    with pytest.raises(ValueError, match="object"):
        store.load()


def test_save_roundtrip_preserves_fields(store, tmp_root):
    e = _auto("BV1aa", title="chinese title", duration_s=3105)
    store.upsert(e)
    loaded = ManifestStore(root=tmp_root).load()["BV1aa:p0"]
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
        store.upsert(_auto("BV1aa", status="bogus"))


def test_upsert_rejects_new_bare_processable_row(store):
    with pytest.raises(ValueError, match="work_id"):
        store.upsert(_entry("BV1aa"))


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
    seed_legacy(store, _entry("BV1aa"))
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
    seed_legacy(store, _entry("BV1mm", title="keep-me", duration_s=9))
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
    seed_legacy(store, _entry("BV1aa"))
    # Shape A: the foreign stem is the directory name.
    srt_dir = os.path.join(tmp_root, "transcripts", "BV1aa.p1")
    os.makedirs(srt_dir)
    open(os.path.join(srt_dir, "bundle.srt"), "w").write("x")
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

    seed_legacy(store, _entry("BV1aa"))
    store.upsert(_entry("BV1aa", work_id="BV1aa:p0", page_index=0, cid=7))
    with pytest.raises(ManifestMigrationCollision):
        store.migrate_legacy_rows(lambda bvid: [_page(bvid, 0, cid=1)])


def test_migrate_coalesces_matching_page_created_by_successful_fetch(store, tmp_root):
    seed_legacy(store, _entry("BV1aa", legacy_only="keep"))
    store.upsert(
        _entry(
            "BV1aa",
            work_id="BV1aa:p0",
            page_index=0,
            cid=1,
            title="fresh title",
        )
    )

    report = store.migrate_legacy_rows(
        lambda bvid: [_page(bvid, 0, cid=1)],
        coalesce_existing_page=True,
    )

    assert report.migrated == ["BV1aa:p0"]
    loaded = store.load()
    assert set(loaded) == {"BV1aa:p0"}
    assert loaded["BV1aa:p0"]["title"] == "fresh title"
    assert loaded["BV1aa:p0"]["legacy_only"] == "keep"


def test_migrate_collision_on_existing_p0_artifact(store, tmp_root):
    seed_legacy(store, _entry("BV1aa"))
    # Shape A: a foreign page's stem is a directory under transcripts/.
    srt_dir = os.path.join(tmp_root, "transcripts", "BV1aa.p0")
    os.makedirs(srt_dir)
    open(os.path.join(srt_dir, "bundle.srt"), "w").write("x")
    report = store.migrate_legacy_rows(
        lambda bvid: [_page(bvid, 0, cid=1)]
    )
    assert report.migrated == []
    assert report.unresolved == ["BV1aa"]
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded["BV1aa"]["unresolved"] is True


def test_migrate_collision_on_foreign_stem_under_configured_artifact_root(
    store, tmp_root
):
    """The collision probe scans both bases, so the configured root freezes too."""
    from bili_asr.artifact_root import ArtifactRoots

    artifact_root = os.path.join(tmp_root, "artifacts")
    # Shape A: the foreign stem is the directory name.
    srt_dir = os.path.join(artifact_root, "transcripts", "BV1aa.p1")
    os.makedirs(srt_dir)
    open(os.path.join(srt_dir, "bundle.srt"), "w").write("x")
    seed_legacy(store, _entry("BV1aa"))
    roots = ArtifactRoots.of(tmp_root, artifact_root)

    report = store.migrate_legacy_rows(
        lambda bvid: [_page(bvid, 0, cid=1)], roots
    )

    assert report.migrated == []
    assert report.unresolved == ["BV1aa"]
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded["BV1aa"]["unresolved"] is True
    # Nothing colliding sits at the archive root: the freeze came from the
    # configured base, which the probe reaches only because it scans both.
    assert not os.path.exists(os.path.join(tmp_root, "transcripts", "BV1aa.p1"))
