"""Queue-source cutover: archive.db is the sole queue input.

``--queue-source store`` (the default) selects work for ``download-audio``,
``asr`` and ``pilot`` from the ``MediaQueueRepository`` gap views
(``v_missing_audio`` / ``v_missing_transcript``), never from the manifest.
``--queue-source manifest`` keeps the pre-cutover manifest behaviour as the
rollback path and prints one deprecation line to stderr.

The fixture store is built through the repositories' own writers; the only raw
SQL is the positive audio evidence (``audio_objects`` / ``part_audio_objects``),
which the storage contract tests own.
"""

from __future__ import annotations

import hashlib
import os

import pytest

from bili_asr import bili_client as bc
from bili_asr.cli.main import main
from bili_asr.manifest import ManifestStore
from bili_asr.page_identity import page_identity
from bili_asr.storage import (
    AcquisitionRunRecord,
    MediaQueueRepository,
    MetadataRepository,
    TranscriptRepository,
    TranscriptSegmentRecord,
    UserRecord,
    VideoPartRecord,
    VideoRecord,
    open_database,
)

from tests.support.audio import AUDIO_BYTES, RouterTransport
from tests.support.cli_asr import _audio_transport, _patch_cli, _stub_runner_model
from tests.support.cli_queue_source import _MID, _seed_store, _write_audio_file


_DEPRECATION = "queue-source manifest is deprecated; archive.db is the sole queue"






# --------------------------------------------------------------------------
# store source: download-audio selects from the gap view, not the manifest
# --------------------------------------------------------------------------


def test_download_audio_store_source_ignores_manifest_queue_rows(
    tmp_root, monkeypatch, capsys
):
    """A stale manifest needs_audio row must not pull work the store drained.

    The part holds a stored transcript, so ``v_missing_audio`` excludes it;
    only a manifest read could resurrect it — the cutover removes that read.
    """
    from bili_asr.storage import MediaQueueRepository

    audio_id, transcript_id = _seed_store(tmp_root)
    # Give the captionless part a transcript too, so the whole audio queue is
    # drained and only a stale manifest row could resurrect work.
    connection = open_database(tmp_root)
    try:
        repo = TranscriptRepository(connection)
        for run_seq, identity in ((20, audio_id), (30, transcript_id)):
            repo.start_acquisition_run(
                AcquisitionRunRecord(
                    run_id=f"run-sub-{identity.bvid}",
                    kind="subtitle",
                    selector_kind="pending",
                    selector_target=None,
                    requested_limit=None,
                    credential_present=False,
                    started_at=run_seq,
                )
            )
            repo.record_acquired_transcript(
                run_id=f"run-sub-{identity.bvid}",
                video_part_id=connection.execute(
                    "SELECT video_part_id FROM video_parts WHERE bvid=? AND page_index=0",
                    (identity.bvid,),
                ).fetchone()[0],
                source_kind="subtitle-ai",
                language="zh-CN",
                segments=(
                    TranscriptSegmentRecord(start_ms=0, end_ms=1_000, text="字幕"),
                ),
                started_at=run_seq + 1,
                finished_at=run_seq + 2,
                created_at=run_seq + 3,
            )
        # The store drained both parts from every audio queue.
        assert MediaQueueRepository(connection).list_queue_gaps(
            gap="missing_audio"
        ) == []
        assert MediaQueueRepository(connection).list_queue_gaps(
            gap="missing_transcript"
        ) == []
    finally:
        connection.close()

    stale = {
        "bvid": transcript_id.bvid,
        "work_id": transcript_id.work_id,
        "page_index": 0,
        "cid": transcript_id.cid,
        "status": "needs_audio",
        "title": "stale",
        "duration_s": 5,
        "pubdate": 1,
        "pubdate_str": "2026-01-02",
    }
    ManifestStore(root=tmp_root).upsert(stale)

    _patch_cli(monkeypatch)
    rc = main(["download-audio", "--missing-subs", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    # The store drained the queue: the run reports empty and the manifest's
    # stale needs_audio row was never consulted (a manifest-driven run would
    # have selected and "downloaded" it).
    assert rc == 0, captured.err
    assert "queue empty (no parts need audio)" in captured.out
    assert "audio downloaded" not in captured.out


def test_download_audio_store_source_acquires_and_marks(tmp_root, monkeypatch, capsys):
    """A captionless store part is selected, downloaded, and marked acquired.

    The manifest holds no queue row at all — the store alone drives selection —
    and the successful acquisition records audio evidence back into the store
    (contract §4c/§4d: the part leaves ``v_missing_audio``).
    """
    from bili_asr.storage import MediaQueueRepository

    audio_id, _ = _seed_store(tmp_root)
    assert ManifestStore(root=tmp_root).load() == {}

    monkeypatch.setattr(bc, "build_default_transport", _audio_transport)
    _patch_cli(monkeypatch)
    rc = main(["download-audio", "--missing-subs", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert "1 audio_ok" in captured.out
    assert f"{audio_id.work_id}: audio downloaded" in captured.out

    connection = open_database(tmp_root)
    try:
        # The acquisition is store evidence now: the part left the audio queue.
        assert MediaQueueRepository(connection).list_queue_gaps(
            gap="missing_audio"
        ) == []
    finally:
        connection.close()


# --------------------------------------------------------------------------
# store source: asr selects from the transcript gap view
# --------------------------------------------------------------------------


def test_asr_store_source_selects_transcript_gap_part(
    tmp_root, monkeypatch, capsys
):
    """``asr --pending`` selects from ``v_missing_transcript``, not the manifest.

    The fake ASR model is skipped on hosts without the ``[asr]`` extra, so
    the assertion pins selection itself — the audio-backed part is chosen and
    transcription is attempted — and the store-side write-back is verified
    separately by ``test_storage_queue_writes.py``.
    """
    from bili_asr.storage import MediaQueueRepository

    _, transcript_id = _seed_store(tmp_root)
    _write_audio_file(tmp_root, transcript_id)

    transcribe_calls: list[str] = []
    _stub_runner_model(monkeypatch, transcribe_calls)
    _patch_cli(monkeypatch)

    rc = main(["asr", "--pending", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    if rc == 0:
        # The transcript gap part was transcribed and archived.
        assert f"{transcript_id.work_id}: archived (asr)" in captured.out
        connection = open_database(tmp_root)
        try:
            assert MediaQueueRepository(connection).list_queue_gaps(
                gap="missing_transcript"
            ) == []
        finally:
            connection.close()
    else:
        # numpy/soundfile absent on this host: the runner failed to decode,
        # but the row must still have been *selected* for ASR (the read is
        # attempted before the decode).  A manifest-driven run would select
        # nothing and report 0 failed with no read attempt at all.
        assert transcribe_calls, (
            "asr --pending must select the v_missing_transcript part even "
            "when decoding is unavailable"
        )
        assert f"{transcript_id.work_id}: archive failed" in captured.err


def test_asr_store_limit_is_applied_once(tmp_root, monkeypatch, capsys):
    """``asr --limit N`` reads exactly N rows on the store route (single application).

    The store-side ``LIMIT ?`` is the sole owner of the bound; the CLI must not
    re-slice the store's rows.  The per-row read hook identifies each selected
    row, so an exact count pins the single-application contract: a future
    over-fetching store read (per-bvid cap etc.) cannot silently reintroduce
    the second slice this plan removed.
    """
    _, first_id = _seed_store(tmp_root)
    connection = open_database(tmp_root)
    try:
        metadata = MetadataRepository(connection)
        transcripts = TranscriptRepository(connection)
        with metadata.transaction():
            for index, identity in enumerate(
                (page_identity("BVlimitB", 0, 9003, "p0"),
                 page_identity("BVlimitC", 0, 9004, "p0"))
            ):
                metadata.upsert_video(
                    VideoRecord(
                        bvid=identity.bvid,
                        aid=None,
                        mid=_MID,
                        title=f"limited-{index}",
                        pubdate=1_000,
                        created_at=2,
                        updated_at=2,
                    )
                )
                metadata.upsert_part(
                    VideoPartRecord(
                        bvid=identity.bvid,
                        page_index=identity.page_index,
                        cid=identity.cid,
                        title=f"{identity.bvid} 段",
                        duration_ms=5_000,
                        processing_status="discovered",
                        created_at=3,
                        updated_at=3,
                    )
                )
        # Reuse the fixture's audio object (audio_id 1, sha256 UNIQUE): each
        # extra part just links it as its own audio evidence.
        for bvid in ("BVlimitB", "BVlimitC"):
            connection.execute(
                "INSERT INTO part_audio_objects("
                "  video_part_id, audio_id, acquired_at, acquisition_source"
                ") VALUES ("
                "  (SELECT video_part_id FROM video_parts WHERE bvid=?"
                "   AND page_index=0), 1, 4, 'download')",
                (bvid,),
            )
        # The third part's subtitle route is exhausted so it joins the queue.
        transcripts.start_acquisition_run(
            AcquisitionRunRecord(
                run_id="run-sub-limitc",
                kind="subtitle",
                selector_kind="pending",
                selector_target=None,
                requested_limit=None,
                credential_present=False,
                started_at=20,
            )
        )
        # Two independent empty observations: one look is not exhaustion.
        transcripts.record_subtitle_attempt(
            run_id="run-sub-limitc",
            video_part_id=connection.execute(
                "SELECT video_part_id FROM video_parts WHERE bvid=? AND page_index=0",
                ("BVlimitC",),
            ).fetchone()[0],
            outcome="no-subtitle",
            error_code=None,
            started_at=21,
            finished_at=22,
        )
        transcripts.start_acquisition_run(
            AcquisitionRunRecord(
                run_id="run-sub-limitc-2",
                kind="subtitle",
                selector_kind="pending",
                selector_target=None,
                requested_limit=None,
                credential_present=False,
                started_at=23,
            )
        )
        transcripts.record_subtitle_attempt(
            run_id="run-sub-limitc-2",
            video_part_id=connection.execute(
                "SELECT video_part_id FROM video_parts WHERE bvid=? AND page_index=0",
                ("BVlimitC",),
            ).fetchone()[0],
            outcome="no-subtitle",
            error_code=None,
            started_at=24,
            finished_at=25,
        )
        connection.commit()
    finally:
        connection.close()

    for bvid in ("BVlimitB", "BVlimitC"):
        _write_audio_file(tmp_root, page_identity(bvid, 0, 0, "p0"))

    transcribe_calls: list[str] = []
    _stub_runner_model(monkeypatch, transcribe_calls)
    _patch_cli(monkeypatch)

    rc = main(["asr", "--pending", "--limit", "2", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    # Exactly N rows were read and transcribed — the store-side bound is the
    # single authority; a CLI re-slice on top of an over-fetching store read
    # would show up here as a count below the store's candidate set.
    assert len(transcribe_calls) == 2, captured.out + captured.err
    assert rc == 0, captured.err
    assert "asr: 2 archived" in captured.out
    # Exactly the two limited rows archived; the third candidate was never
    # read (its audio file was never opened) — the bound came from the store
    # read, not from dropping rows after the fact.  The store gap view still
    # lists all three candidates: this route's write-back is the manifest
    # (store transcript write-back is owned by test_storage_queue_writes.py),
    # so queue membership is not the assertion here.
    archived = {os.path.basename(call) for call in transcribe_calls}
    assert archived == {"BVlimitB.p0.m4a", "BVlimitC.p0.m4a"}, transcribe_calls


def test_asr_store_source_skips_part_with_subtitles(tmp_root, monkeypatch, capsys):
    """A part holding AI subtitles never reaches the audio→ASR branch.

    This is the exact inversion of the pre-cutover root cause: the manifest
    used to route a subtitle-holding part to audio download; the store view
    treats it as satisfied in every queue.
    """
    from bili_asr.storage import MediaQueueRepository

    audio_id, _ = _seed_store(tmp_root)
    connection = open_database(tmp_root)
    try:
        repo = TranscriptRepository(connection)
        repo.start_acquisition_run(
            AcquisitionRunRecord(
                run_id="run-sub-inv",
                kind="subtitle",
                selector_kind="pending",
                selector_target=None,
                requested_limit=None,
                credential_present=False,
                started_at=30,
            )
        )
        repo.record_acquired_transcript(
            run_id="run-sub-inv",
            video_part_id=connection.execute(
                "SELECT video_part_id FROM video_parts WHERE bvid=? AND page_index=0",
                (audio_id.bvid,),
            ).fetchone()[0],
            source_kind="subtitle-ai",
            language="zh-CN",
            segments=(TranscriptSegmentRecord(start_ms=0, end_ms=1_000, text="字幕"),),
            started_at=31,
            finished_at=32,
            created_at=33,
        )
        queue = MediaQueueRepository(connection)
        # The subtitle-holding part is in no audio or transcript queue.  (The
        # other fixture part, BVqueueT, legitimately sits in missing_transcript:
        # it has audio evidence and no transcript — it is not the part under
        # test and download-audio does not read that queue.)
        for gap in ("missing_audio", "missing_transcript"):
            assert all(
                item.bvid != audio_id.bvid
                for item in queue.list_queue_gaps(gap=gap)
            )
    finally:
        connection.close()

    # The downloader must never see the subtitle-holding part even when asked
    # for all missing-subs work — the store says it needs nothing.
    monkeypatch.setattr(bc, "build_default_transport", _audio_transport)
    _patch_cli(monkeypatch)
    rc = main(["download-audio", "--missing-subs", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert f"{audio_id.work_id}: audio downloaded" not in captured.out


# --------------------------------------------------------------------------
# manifest source: rollback preserves pre-cutover behaviour
# --------------------------------------------------------------------------


def test_download_audio_manifest_source_preserves_legacy_selection(
    tmp_root, monkeypatch, capsys
):
    """``--queue-source manifest`` still reads needs_audio rows and warns once."""
    identity = page_identity("BVlegacy", 0, 777, "p0")
    ManifestStore(root=tmp_root).upsert(
        {
            "bvid": identity.bvid,
            "work_id": identity.work_id,
            "page_index": 0,
            "cid": identity.cid,
            "status": "needs_audio",
            "title": "legacy",
            "duration_s": 5,
            "pubdate": 1,
            "pubdate_str": "2026-01-02",
        }
    )

    monkeypatch.setattr(bc, "build_default_transport", _audio_transport)
    _patch_cli(monkeypatch)
    rc = main(
        [
            "download-audio",
            "--missing-subs",
            "--queue-source",
            "manifest",
            "--archive-root",
            tmp_root,
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert "1 audio_ok" in captured.out
    assert captured.err.count(_DEPRECATION) == 1


def test_download_audio_store_source_prints_no_deprecation(
    tmp_root, monkeypatch, capsys
):
    """The default store path is silent about the manifest: no warning line."""
    _seed_store(tmp_root)
    monkeypatch.setattr(bc, "build_default_transport", _audio_transport)
    _patch_cli(monkeypatch)
    rc = main(["download-audio", "--missing-subs", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert _DEPRECATION not in captured.err
    assert "deprecated" not in captured.err


# --------------------------------------------------------------------------
# pilot store selection
# --------------------------------------------------------------------------


def test_pilot_store_source_uses_gap_views(tmp_root, monkeypatch, capsys):
    """``pilot`` selects work from the store queue, not the manifest."""
    from bili_asr.storage import MediaQueueRepository

    audio_id, transcript_id = _seed_store(tmp_root)
    _write_audio_file(tmp_root, transcript_id)

    monkeypatch.setattr(bc, "build_default_transport", _audio_transport)
    _patch_cli(monkeypatch)
    _stub_runner_model(monkeypatch)

    rc = main(
        [
            "pilot",
            "--n",
            "5",
            "--archive-root",
            tmp_root,
            "--sessdata",
            "SECRET-SESS",
        ]
    )
    captured = capsys.readouterr()
    # Both queued parts were selected from the store and driven through the
    # audio branch (the captionless one downloads, the backed one reuses).
    # On hosts without the [asr] extra the decode fails per row; selection is
    # still proven by the parts appearing in the batch lines.
    assert f"{audio_id.work_id}: archived (asr)" in captured.out or (
        f"{audio_id.work_id}: archive failed" in captured.err
    )
    assert f"{transcript_id.work_id}: archived (asr)" in captured.out or (
        f"{transcript_id.work_id}: archive failed" in captured.err
    )
    connection = open_database(tmp_root)
    try:
        queue = MediaQueueRepository(connection)
        # If decoding was available both parts drained; otherwise the audio
        # evidence still took the captionless part out of the audio queue.
        audio_gap = queue.list_queue_gaps(gap="missing_audio")
        if rc == 0:
            assert audio_gap == []
            assert queue.list_queue_gaps(gap="missing_transcript") == []
        else:
            assert all(item.bvid != audio_id.bvid for item in audio_gap)
    finally:
        connection.close()


# --------------------------------------------------------------------------
# Task 2: the batch chain's pending scope reads the store gap views
# --------------------------------------------------------------------------




def test_schedule_pending_scope_requires_store(tmp_root, capsys):
    """``schedule --scope pending`` cut to the store outright (no switch)."""
    rc = main([
        "schedule", "--scope", "pending", "--limit", "1",
        "--archive-root", tmp_root,
    ])
    captured = capsys.readouterr()
    # No archive.db: the documented configuration error, and the manifest's
    # needs_audio rows are never read to decide work.
    assert rc == 1
    assert "no archive database" in captured.err
