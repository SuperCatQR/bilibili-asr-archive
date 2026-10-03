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


def _journal_path(root):
    return os.path.join(root, "manifest", "manifest.journal.jsonl")


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

    # Per-row upserts now land in the journal; the snapshot compacts later.
    ledger_lines = []
    for path in (_manifest_path(tmp_root), _journal_path(tmp_root)):
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                ledger_lines.extend(fh.read().splitlines())
    assert len(ledger_lines) == 2


def test_resume_dedupe_no_duplicate_bvids(store, tmp_root):
    # simulate resume: existing file, then upsert same + new
    store.upsert(_auto("BV1aa"))
    store2 = ManifestStore(root=tmp_root)
    store2.load()
    store2.upsert(_auto("BV1aa"))  # resume re-upsert same work_id
    store2.upsert(_auto("BV1cc", cid=3))

    ledger_lines = []
    for path in (_manifest_path(tmp_root), _journal_path(tmp_root)):
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                ledger_lines.extend(fh.read().splitlines())
    bvids = [json.loads(l)["bvid"] for l in ledger_lines]
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


def test_migrate_keeps_journaled_supersede_of_existing_page_row(store, tmp_root):
    # I-000195: the rewrite base must be the effective replay view. A journaled
    # row superseding a page-qualified snapshot row used to be dropped when the
    # migration rewrote the snapshot and unlinked the journal -- the only copy
    # of the newer transition.
    store.save({
        "BV1aa:p0": _entry("BV1aa", work_id="BV1aa:p0", page_index=0, cid=1),
        "BV9zz": _entry("BV9zz"),
    })
    store.upsert(
        _entry("BV1aa", work_id="BV1aa:p0", page_index=0, cid=1, status="archived")
    )
    assert os.path.exists(_journal_path(tmp_root))
    assert store.get("BV1aa:p0")["status"] == "archived"

    report = ManifestStore(root=tmp_root).migrate_legacy_rows(
        lambda bvid: [_page(bvid, 0, cid=1)]
    )
    # Report semantics unchanged: the bare legacy row is the only re-key.
    assert report.migrated == ["BV9zz:p0"]
    assert report.unresolved == []

    with open(_manifest_path(tmp_root), encoding="utf-8") as fh:
        snapshot = {
            row["work_id"]: row
            for row in (json.loads(line) for line in fh if line.strip())
        }
    assert snapshot["BV1aa:p0"]["status"] == "archived"
    # The journal was discarded together with the rewrite, so a fresh reader
    # sees the superseded value only if the base carried it.
    assert not os.path.exists(_journal_path(tmp_root))
    reloaded = ManifestStore(root=tmp_root).load()
    assert reloaded["BV1aa:p0"]["status"] == "archived"
    assert set(reloaded) == {"BV1aa:p0", "BV9zz:p0"}


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


def test_journal_crash_mid_batch_replays_last_full_record_per_key(store, tmp_root):
    # Seed a snapshot through save(); subsequent upserts append to the journal.
    store.save({"BV1aa:p0": _auto("BV1aa")})

    rows = [
        _auto("BV1aa", title="t1"),
        _auto("BV1bb"),
        _auto("BV1aa", title="t2"),
    ]
    for row in rows:
        store.upsert(row)
    assert os.path.exists(_journal_path(tmp_root))

    # Simulate a crash mid-journal: truncate inside the final "t2" append, so
    # that line tears while every earlier line stays fully intact.
    with open(_journal_path(tmp_root), "rb") as fh:
        journal = fh.read()
    t2_start = journal.rindex(b'"t2"')
    cut = t2_start - 5
    with open(_journal_path(tmp_root), "wb") as fh:
        fh.write(journal[:cut])

    recovered = ManifestStore(root=tmp_root)
    loaded = recovered.load()
    # Torn append is dropped: BV1aa falls back to its last fully-appended row.
    assert loaded["BV1aa:p0"]["title"] == "t1"
    # Rows appended before the tear are unaffected.
    assert loaded["BV1bb:p0"]["title"] == "some title"
    assert len(loaded) == 2


def test_snapshot_deterministic_after_compaction(store, tmp_root):
    store.upsert(_auto("BV1aa"))
    store.upsert(_auto("BV1bb", cid=2))
    store.upsert(_auto("BV1aa", title="second"))
    store.compact()
    # Compaction folded the journal in and reset it.
    assert not os.path.exists(_journal_path(tmp_root))

    first = open(_manifest_path(tmp_root), "rb").read()
    store.save()
    second = open(_manifest_path(tmp_root), "rb").read()
    assert first == second

    # Post-compaction upserts go to the journal and must not change the
    # snapshot until the next compaction; compacting reproduces the same bytes
    # only when no new rows landed, so assert byte-stability across save() and
    # a no-op compact() round-trip.
    store.compact()
    third = open(_manifest_path(tmp_root), "rb").read()
    assert second == third


def test_batch_cost_bounded_full_rereads(store, tmp_root, monkeypatch):
    # L-line pre-existing manifest: history replayed through save().
    seed = {f"BV{i:04x}:p0": _auto(f"BV{i:04x}") for i in range(64)}
    store.save(seed)

    store2 = ManifestStore(root=tmp_root)
    reads = 0
    original = ManifestStore._read_latest

    def counting(self):
        nonlocal reads
        reads += 1
        return original(self)

    monkeypatch.setattr(ManifestStore, "_read_latest", counting)

    k = 12
    for i in range(k):
        store2.upsert(_auto(f"BV{i:04x}", title=f"batch {i}"))

    # The batch takes the journal path: exactly one full snapshot re-read
    # (first upsert) instead of K.
    assert reads == 1

    # Journal replay still yields the latest rows for this process...
    assert store2.get("BV0000:p0")["title"] == "batch 0"
    # ...and for a fresh process reading from disk.
    reloaded = ManifestStore(root=tmp_root).load()
    assert reloaded["BV0000:p0"]["title"] == "batch 0"
    assert len(reloaded) == 64


def test_compact_with_only_torn_journal_keeps_journal(store, tmp_root):
    # The replayed effective state is empty (the journal's only row is a torn
    # append), so there is no snapshot to rewrite. compact() must leave the
    # journal in place rather than delete the sole on-disk history — mirror
    # migrate_legacy_rows, which removes the journal only on a real rewrite.
    journal_dir = os.path.join(tmp_root, "manifest")
    os.makedirs(journal_dir, exist_ok=True)
    with open(_journal_path(tmp_root), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(_auto("BV1aa"))[:20])  # torn line, no newline

    store.compact()

    assert os.path.exists(_journal_path(tmp_root))
    assert not os.path.exists(_manifest_path(tmp_root))
    # The torn row replays to nothing, so the store stays empty.
    assert store.load() == {}
def test_upsert_invalidates_cache_on_foreign_journal_append(store, tmp_root):
    # Process A holds a loaded store; a second writer (same fs, separate
    # process semantics) appends between two of A's upserts.  A's next
    # upsert must re-replay so save()/compact() cannot overwrite the
    # foreign row with the stale cached view.
    store.upsert(_auto("BVaaaa"))

    other = ManifestStore(root=tmp_root)
    other.upsert(_auto("BVbbbb"))

    # Foreign append changed the journal: the stale cache would hold only
    # BVaaaa.  The invalidation re-replays before applying this upsert.
    store.upsert(_auto("BVcccc", status="pending"))
    assert store.get("BVbbbb:p0") is not None

    # save() publishes the merged view, not the pre-invalidation cache.
    store.save()
    reloaded = ManifestStore(root=tmp_root).load()
    assert set(reloaded) == {"BVaaaa:p0", "BVbbbb:p0", "BVcccc:p0"}

    # Same guarantee through compact(): foreign row survives the fold.
    other2 = ManifestStore(root=tmp_root)
    other2.upsert(_auto("BVdddd"))
    store.upsert(_auto("BVeeee", status="pending"))
    store.compact()
    reloaded = ManifestStore(root=tmp_root).load()
    assert set(reloaded) == {
        "BVaaaa:p0", "BVbbbb:p0", "BVcccc:p0", "BVdddd:p0", "BVeeee:p0",
    }


def test_journal_row_with_u2028_does_not_truncate_the_replay(store, tmp_root):
    # A row whose text carries U+2028 (LINE SEPARATOR) is legal JSON and lands
    # on disk raw: the writer serializes with ensure_ascii=False. str.splitlines()
    # breaks on U+2028/U+2029/U+0085 as well as "\n", so it cut the row into
    # fragments; the first fragment failed validation and the torn-tail break
    # stopped the replay, hiding every later row. save() then republished that
    # truncated view -- deleting the later row from the snapshot for good.
    store.save({"BV0aa:p0": _auto("BV0aa")})  # a pre-existing snapshot row

    journal_dir = os.path.join(tmp_root, "manifest")
    os.makedirs(journal_dir, exist_ok=True)
    journal_rows = [
        _auto("BV1aa", title="before\u2028after"),
        _auto("BV1bb", cid=2, title="later row"),
    ]
    with open(_journal_path(tmp_root), "w", encoding="utf-8") as fh:
        for row in journal_rows:
            # Built at runtime, not pasted literally: this source file must not
            # itself carry the separator.
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    # Replay half: the separator-bearing row must not swallow the row after it.
    loaded = ManifestStore(root=tmp_root).load()
    assert set(loaded) == {"BV0aa:p0", "BV1aa:p0", "BV1bb:p0"}
    assert loaded["BV1aa:p0"]["title"] == "before\u2028after"

    # Durable half: the rewritten snapshot must still hold every replayed row.
    store.save()
    with open(_manifest_path(tmp_root), encoding="utf-8") as fh:
        snapshot_rows = [json.loads(line) for line in fh.read().split("\n") if line.strip()]
    assert {row["work_id"] for row in snapshot_rows} == {"BV0aa:p0", "BV1aa:p0", "BV1bb:p0"}


def _snapshot_stat(path):
    st = os.stat(path)
    return (st.st_size, st.st_mtime_ns)


def test_file_based_trigger_folds_journal_grown_by_another_handle(store, tmp_root):
    # An L-line snapshot seeded directly on disk (no ManifestStore involved),
    # then appends through one instance that never calls save()/compact(). Its
    # own append count stays far below the old per-instance threshold, so only
    # the on-disk sizes can fold this journal.
    row_bytes = 192
    os.makedirs(os.path.dirname(_manifest_path(tmp_root)), exist_ok=True)
    seed_rows = [
        _auto(f"BV{i:04x}", cid=i + 1, title="L" * (row_bytes - 120))
        for i in range(4)
    ]
    with open(_manifest_path(tmp_root), "w", encoding="utf-8") as fh:
        for row in seed_rows:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    snapshot_bytes = os.path.getsize(_manifest_path(tmp_root))

    for i in range(16):
        store.upsert(_auto(f"BV{i:04x}", cid=i + 1, title="M" * (row_bytes - 120)))

    journal_bytes = (
        os.path.getsize(_journal_path(tmp_root)) if os.path.exists(_journal_path(tmp_root)) else 0
    )
    # The file-based trigger folds once the journal reaches 2x the snapshot, so
    # the journal can never exceed that bound plus the row that crossed it. A
    # per-instance counter lets these 16 appends grow to 4x the snapshot
    # unfolded, which is the bound this asserts.
    assert journal_bytes <= max(2 * snapshot_bytes, 512) + row_bytes
    with open(_manifest_path(tmp_root), encoding="utf-8") as fh:
        snapshot_text = fh.read()
    # Folded rows are published into the snapshot, not stranded in the journal.
    assert '"M' in snapshot_text

    reloaded = ManifestStore(root=tmp_root).load()
    # Every seeded row plus every appended row survives the fold that the
    # per-instance counter could not reach.
    assert len(reloaded) == 16
    assert reloaded["BV0000:p0"]["title"] == "M" * (row_bytes - 120)
    assert reloaded["BV0003:p0"]["title"] == "M" * (row_bytes - 120)


def test_tiny_ledger_does_not_compact_per_row(store, tmp_root):
    seed = {f"BV{i:04x}:p0": _auto(f"BV{i:04x}", cid=i + 1) for i in range(64)}
    store.save(seed)
    snapshot_before = _snapshot_stat(_manifest_path(tmp_root))

    for i in range(8):
        store.upsert(_auto(f"BV{i:04x}", cid=i + 1, title=f"update {i}"))

    assert _snapshot_stat(_manifest_path(tmp_root)) == snapshot_before
    assert os.path.exists(_journal_path(tmp_root))


def test_save_failure_before_discard_keeps_journal_rows(store, tmp_root, monkeypatch):
    store.save({_auto("BVseed")["work_id"]: _auto("BVseed")})
    snapshot_before = open(_manifest_path(tmp_root), "rb").read()
    store.upsert(_auto("BV1aa"))
    store.upsert(_auto("BV1bb", cid=2))
    assert os.path.getsize(_journal_path(tmp_root)) > 0

    def boom(entries, *args, **kwargs):
        raise OSError(28, "no space left on device")

    monkeypatch.setattr(store, "_replace_snapshot", boom)
    with pytest.raises(OSError):
        store.save()

    # The journal was not discarded while the snapshot stayed stale.
    assert os.path.exists(_journal_path(tmp_root))
    assert open(_manifest_path(tmp_root), "rb").read() == snapshot_before
    reloaded = ManifestStore(root=tmp_root).load()
    assert set(reloaded) == {"BVseed:p0", "BV1aa:p0", "BV1bb:p0"}


def test_save_empty_current_touches_no_artifact(store, tmp_root):
    journal_dir = os.path.join(tmp_root, "manifest")
    os.makedirs(journal_dir, exist_ok=True)
    with open(_journal_path(tmp_root), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(_auto("BV1aa"))[:20])  # torn append: replays to nothing
    journal_before = _snapshot_stat(_journal_path(tmp_root))

    store.save()

    assert os.path.exists(_journal_path(tmp_root))
    assert _snapshot_stat(_journal_path(tmp_root)) == journal_before
    assert not os.path.exists(_manifest_path(tmp_root))
