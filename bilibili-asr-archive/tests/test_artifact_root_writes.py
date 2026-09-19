"""Cross-module cases for the configured artifact root (plan Task 2, spec §4–§8).

One configured root, two ordered read bases: ``{artifact}`` carries the products
(audio, transcript bundles, harvested subtitle documents) and ``{archive}`` keeps
the state (``manifest/``, ``coordinator/``).  The cases here drive the shipped
entry points — ``audio.download_audio``, ``RunCoordinator``, ``subtitles.harvest_subtitle``,
``audio_reclaim.reclaim_audio``, ``ManifestStore.migrate_legacy_rows`` — against two
distinct directories and assert three things the feature exists to guarantee:

* every write lands under the configured root (spec §4);
* every **recorded** path stays the shipped root-relative string (D7, spec §2.1) —
  a ``..``-bearing value is the silent failure of spec §15 correction 7;
* omitting ``artifact_roots`` reproduces today's layout byte for byte (spec §11).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from bili_asr import asr as asr_module
from bili_asr import audio as audio_module
from bili_asr.artifact_root import ArtifactRoots
from bili_asr.audio_reclaim import reclaim_audio
from bili_asr.coordinator import RunCoordinator
from bili_asr.manifest import ManifestStore
from bili_asr.page_identity import artifact_stem, page_identity
from bili_asr.subtitles import harvest_subtitle

BVID = "BV1artifact"
SAMPLE_DOC = {
    "body": [
        {"from": 0.0, "to": 1.5, "content": "hi"},
        {"from": 1.5, "to": 3.0, "content": "there"},
    ]
}


def _roots(tmp_path: Path, *, nested: bool = False) -> tuple[Path, Path, ArtifactRoots]:
    """An archive root and a distinct, existing artifact root (spec §3.3).

    ``nested=True`` places the artifact root *inside* the archive root — the
    second accepted layout (§3.3) — as a sibling directory otherwise.
    """
    archive = tmp_path / "state"
    archive.mkdir(parents=True, exist_ok=True)
    artifact = (archive / "artifacts") if nested else (tmp_path / "artifacts")
    artifact.mkdir(parents=True, exist_ok=True)
    return archive, artifact, ArtifactRoots.of(archive, artifact)


class FakeClient:
    """The four client seams the product code calls. No transport, no network."""

    def __init__(self, *, audio: bytes = b"audio-bytes") -> None:
        self.audio = audio
        self.audio_calls: list[tuple[str, int | None]] = []
        self.subtitle_calls: list[str] = []

    def fetch_playurl_audio(self, bvid: str, cid: int | None = None):
        self.audio_calls.append((bvid, cid))
        return [
            {
                "id": 30216,
                "baseUrl": "https://cdn.example/a30216.m4s",
                "mimeType": "audio/mp4",
            }
        ]

    def download_audio_stream(self, url: str, dest_path: str) -> None:
        with open(dest_path, "wb") as handle:
            handle.write(self.audio)

    def probe_subs(self, bvid: str, cid: int | None = None):
        return [
            {
                "lan": "ai-zh",
                "lan_doc": "中文（自动生成）",
                "subtitle_url": "https://sub.example/short-lived.json",
            }
        ]

    def download_subtitle(self, url: str):
        self.subtitle_calls.append(url)
        return dict(SAMPLE_DOC)


class BoomClient:
    """Every attribute is a failure: proves a path never touches the network."""

    def __getattr__(self, name):  # pragma: no cover - only reached on a bug
        raise AssertionError(f"no network call expected (touched {name!r})")


def _stub_asr(monkeypatch) -> None:
    class FakeModel:
        def generate(self, **_kwargs):
            return [{"text": "hi", "timestamp": [[0, 1000]]}]

    monkeypatch.setattr(
        asr_module, "_load_default_model", lambda **_kwargs: FakeModel()
    )


def _page(bvid: str, page_index: int, cid: int):
    return page_identity(bvid, page_index, cid, f"p{page_index}")


# ---------------------------------------------------------------- audio writes


def test_download_audio_publishes_into_the_artifact_root_and_records_a_root_relative_path(
    tmp_path,
):
    """The file lands at {artifact}/audio; the row records `audio/{stem}.m4a`."""
    archive, artifact, roots = _roots(tmp_path)
    ident = page_identity(BVID, 0, 7, "p0")
    stem = artifact_stem(ident)
    store = ManifestStore(root=archive)
    store.load()

    result = audio_module.download_audio(
        FakeClient(),
        ident,
        os.path.join(str(artifact), "audio", f"{stem}.m4a"),
        store=store,
        artifact_roots=roots,
    )

    assert Path(result) == artifact / "audio" / f"{stem}.m4a"
    assert (artifact / "audio" / f"{stem}.m4a").is_file()
    # The silent failure of spec §15 correction 7: a `..`-bearing value is
    # refused by every audio reader, so the row would never reach audio_ok.
    row = store.get(ident.work_id)
    assert row["audio_path"] == f"audio/{stem}.m4a"
    assert row["status"] == "audio_ok"
    assert not (archive / "audio").exists()


def test_an_existing_legacy_copy_at_the_archive_root_is_honoured_and_not_duplicated(
    tmp_path,
):
    """A pre-existing file at the archive root is reused, not re-downloaded."""
    archive, artifact, roots = _roots(tmp_path)
    ident = page_identity(BVID, 0, 7, "p0")
    stem = artifact_stem(ident)
    (archive / "audio").mkdir()
    (archive / "audio" / f"{stem}.m4a").write_bytes(b"legacy-bytes")
    store = ManifestStore(root=archive)
    store.load()

    result = audio_module.download_audio(
        BoomClient(),
        ident,
        os.path.join(str(artifact), "audio", f"{stem}.m4a"),
        store=store,
        artifact_roots=roots,
    )

    assert Path(result) == archive / "audio" / f"{stem}.m4a"
    assert not (artifact / "audio" / f"{stem}.m4a").exists()
    row = store.get(ident.work_id)
    assert row["audio_path"] == f"audio/{stem}.m4a"
    assert row["status"] == "audio_ok"


# ------------------------------------------------------------- coordinator run


def _audio_ok_row(store: ManifestStore, ident, *, audio_path: str) -> None:
    store.upsert(
        {
            "work_id": ident.work_id,
            "bvid": ident.bvid,
            "page_index": ident.page_index,
            "cid": ident.cid,
            "status": "audio_ok",
            "title": "clip",
            "duration_s": 5,
            "pubdate": 1,
            "pubdate_str": "2026-01-02",
            "audio_path": audio_path,
        }
    )


def _run_offline_archive(
    archive: Path, *, stem: str, artifact_roots, keep_audio: bool
):
    """Archive one ``audio_ok`` row whose audio sits under the write base."""
    base = archive if artifact_roots is None else artifact_roots.write_base
    (base / "audio").mkdir(parents=True, exist_ok=True)
    (base / "audio" / f"{stem}.m4a").write_bytes(b"audio-bytes")
    store = ManifestStore(root=archive)
    ident = page_identity(BVID, 0, 7, "p0")
    _audio_ok_row(store, ident, audio_path=f"audio/{stem}.m4a")
    kwargs: dict = {"keep_audio": keep_audio}
    if artifact_roots is not None:
        kwargs["artifact_roots"] = artifact_roots
    coordinator = RunCoordinator(str(archive), store, offline=True, **kwargs)
    coordinator.run_batch([(ident.work_id, store.load()[ident.work_id])])
    return store.load()[ident.work_id]


def test_the_coordinator_archives_with_bundles_at_the_artifact_root(
    tmp_path, monkeypatch
):
    """Bundles and their recorded paths follow the artifact root; state does not."""
    archive, artifact, roots = _roots(tmp_path)
    _stub_asr(monkeypatch)
    ident = page_identity(BVID, 0, 7, "p0")
    stem = artifact_stem(ident)

    row = _run_offline_archive(
        archive, stem=stem, artifact_roots=roots, keep_audio=True
    )

    assert row["status"] == "archived"
    assert row["srt_path"] == f"transcripts/srt/{stem}.srt"
    assert row["txt_path"] == f"transcripts/txt/{stem}.txt"
    assert row["raw_path"] == f"transcripts/raw/{stem}.json"
    for key in ("srt_path", "txt_path", "md_path", "raw_path"):
        recorded = row[key]
        assert not os.path.isabs(recorded)
        assert ".." not in Path(recorded).parts
        assert (artifact / recorded).is_file()
        assert not (archive / recorded).exists()
    for name in ("srt", "txt", "md", "raw"):
        assert (artifact / "transcripts" / name).is_dir()
    # State stays at the archive root (D13), and a configured root adds nothing
    # there but the audio the legacy probe may still read.
    assert (archive / "manifest" / "manifest.jsonl").is_file()
    assert (archive / "coordinator").is_dir()
    assert not (archive / "transcripts").exists()
    assert not (artifact / "manifest").exists()
    assert not (artifact / "coordinator").exists()


def test_retention_leaves_the_audio_in_place_by_default(tmp_path, monkeypatch):
    """The default policy retains: the row is archived and the audio stays."""
    archive, artifact, roots = _roots(tmp_path, nested=True)
    _stub_asr(monkeypatch)
    ident = page_identity(BVID, 0, 7, "p0")
    stem = artifact_stem(ident)

    row = _run_offline_archive(
        archive, stem=stem, artifact_roots=roots, keep_audio=True
    )

    assert row["status"] == "archived"
    assert (artifact / "audio" / f"{stem}.m4a").is_file()


def test_reclaim_removes_the_audio_when_it_is_asked_for(tmp_path):
    """``keep=False`` removes the copy under *both* bases and nothing else."""
    archive, artifact, roots = _roots(tmp_path)
    ident = page_identity(BVID, 0, 7, "p0")
    stem = artifact_stem(ident)
    for base in (archive, artifact):
        (base / "audio").mkdir()
        (base / "audio" / f"{stem}.m4a").write_bytes(b"audio-bytes")
    victim = tmp_path / "victim.m4a"
    victim.write_bytes(b"victim")

    removed = reclaim_audio(
        str(archive),
        {
            "work_id": ident.work_id,
            "bvid": ident.bvid,
            "status": "archived",
            "audio_path": f"audio/{stem}.m4a",
        },
        artifact_roots=roots,
        keep=False,
    )

    assert removed is True
    assert not (archive / "audio" / f"{stem}.m4a").exists()
    assert not (artifact / "audio" / f"{stem}.m4a").exists()
    assert victim.read_bytes() == b"victim"

    # Day-one shape (D6): the freshly configured root has no `audio/` at all and
    # the row's only copy is the legacy one at the archive root — the scan has to
    # reach the second base rather than stop at the first.
    day_archive, day_artifact, day_roots = _roots(tmp_path / "day-one")
    (day_archive / "audio").mkdir()
    legacy = day_archive / "audio" / f"{stem}.m4a"
    legacy.write_bytes(b"legacy-bytes")

    assert reclaim_audio(
        str(day_archive),
        {
            "work_id": ident.work_id,
            "bvid": ident.bvid,
            "status": "archived",
            "audio_path": f"audio/{stem}.m4a",
        },
        artifact_roots=day_roots,
        keep=False,
    ) is True
    assert not legacy.exists()
    assert not (day_artifact / "audio").exists()


def test_a_symlink_at_the_configured_base_does_not_abandon_the_other_copy(tmp_path):
    """§7 in its inverse direction: the refusal is per **base**, not per row.

    ``unlink_confined_audio`` refuses a symlinked entry at the base it is validating
    (``path_policy.py:167-169``), and the configured root is base 1 — so an explicit
    "do not keep this row's audio" met that refusal there and abandoned the scan,
    leaving the row's real copy at the archive root on disk.  Each base is judged
    independently, exactly as the ordered *read* rule already is (D8/§5): the scan
    moves on and reclaims the copy that is really there.
    """
    archive, artifact, roots = _roots(tmp_path)
    ident = page_identity(BVID, 0, 7, "p0")
    stem = artifact_stem(ident)
    for base in (archive, artifact):
        (base / "audio").mkdir()
    real = archive / "audio" / f"{stem}.m4a"
    real.write_bytes(b"audio-bytes")
    link = artifact / "audio" / f"{stem}.m4a"
    link.symlink_to(real)

    removed = reclaim_audio(
        str(archive),
        {
            "work_id": ident.work_id,
            "bvid": ident.bvid,
            "status": "archived",
            "audio_path": f"audio/{stem}.m4a",
        },
        artifact_roots=roots,
        keep=False,
    )

    assert removed is True
    assert not real.exists()
    # The refused entry at base 1 is left as it was: never followed, never deleted.
    assert link.is_symlink()


# ------------------------------------------------------------- subtitle writes


def test_harvest_subtitle_writes_raw_and_srt_into_the_artifact_root(tmp_path):
    """Both harvested products land under the artifact root; `srt_path` is relative."""
    archive, artifact, roots = _roots(tmp_path)
    ident = page_identity(BVID, 0, 7, "p0")
    stem = artifact_stem(ident)
    store = ManifestStore(root=archive)
    store.load()

    status = harvest_subtitle(
        FakeClient(), ident, store, str(archive), artifact_roots=roots
    )

    assert status == "subtitle_done"
    assert (artifact / "subtitles" / "raw" / f"{stem}.json").is_file()
    assert (artifact / "transcripts" / "srt" / f"{stem}.srt").is_file()
    assert not (archive / "subtitles").exists()
    assert not (archive / "transcripts").exists()
    assert store.get(ident.work_id)["srt_path"] == f"transcripts/srt/{stem}.srt"


# ----------------------------------------------------------- legacy migration


def _seed_bare_row(store: ManifestStore, bvid: str) -> None:
    store.load()
    store.save(
        {
            bvid: {
                "bvid": bvid,
                "aid": 1,
                "title": "legacy",
                "duration_s": 10,
                "pubdate": 1,
                "status": "meta_ok",
            }
        }
    )


def test_a_foreign_page_stem_under_the_artifact_root_freezes_a_legacy_bare_row(tmp_path):
    """A `pN` stem in *either* base freezes the bare row (spec §10, D13)."""
    archive, artifact, roots = _roots(tmp_path)
    srt_dir = artifact / "transcripts" / "srt"
    srt_dir.mkdir(parents=True)
    (srt_dir / f"{BVID}.p1.srt").write_text("x", encoding="utf-8")
    store = ManifestStore(root=archive)
    _seed_bare_row(store, BVID)

    report = store.migrate_legacy_rows(lambda bvid: [_page(bvid, 0, 1)], roots)

    assert report.migrated == []
    assert report.unresolved == [BVID]

    # Negative control: with no foreign stem in either base the same row
    # migrates, so the freeze above is caused by the stem, not the root.
    control_archive, control_artifact, control_roots = _roots(tmp_path / "control")
    control_store = ManifestStore(root=control_archive)
    _seed_bare_row(control_store, BVID)

    control_report = control_store.migrate_legacy_rows(
        lambda bvid: [_page(bvid, 0, 1)], control_roots
    )

    assert control_report.unresolved == []
    assert control_report.migrated == [f"{BVID}:p0"]
    assert control_artifact.is_dir()


# ----------------------------------------------------------- the identity case


def test_the_identity_default_reproduces_todays_paths(tmp_path, monkeypatch):
    """With no artifact root every product lands under the archive root."""
    archive, artifact, _roots_value = _roots(tmp_path)
    _stub_asr(monkeypatch)
    ident = page_identity(BVID, 0, 7, "p0")
    stem = artifact_stem(ident)
    store = ManifestStore(root=archive)
    store.load()

    downloaded = audio_module.download_audio(
        FakeClient(),
        ident,
        os.path.join(str(archive), "audio", f"{stem}.m4a"),
        store=store,
    )
    row = _run_offline_archive(
        archive, stem=stem, artifact_roots=None, keep_audio=True
    )

    assert Path(downloaded) == archive / "audio" / f"{stem}.m4a"
    assert (archive / "audio" / f"{stem}.m4a").is_file()
    assert store.get(ident.work_id)["audio_path"] == f"audio/{stem}.m4a"
    assert row["srt_path"] == f"transcripts/srt/{stem}.srt"
    assert (archive / "transcripts" / "srt" / f"{stem}.srt").is_file()
    # Nothing at all was written to the unused directory.
    assert list(artifact.iterdir()) == []
