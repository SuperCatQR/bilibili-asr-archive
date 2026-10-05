"""Owned batches share a measured audio budget and account for their mutations."""

from __future__ import annotations

from pathlib import Path

import pytest

from bili_asr import audio, audio_budget, bili_client, cli, long_live
from bili_asr.coordinator import RunCoordinator
from bili_asr.manifest import ManifestStore


def _row(bvid, *, duration_s=1):
    return {
        "work_id": f"{bvid}:p0", "bvid": bvid, "page_index": 0,
        "cid": 1001 if bvid == "BVtrackA" else 1002, "title": "Budget test",
        "status": "needs_audio", "duration_s": duration_s,
    }


def _count_scans(monkeypatch):
    calls = []
    original = audio_budget._audio_file_sizes

    def counted(root):
        calls.append(str(root))
        return original(root)

    monkeypatch.setattr(audio_budget, "_audio_file_sizes", counted)
    return calls


def _coordinator(root, rows, *, cap=16000, keep=True):
    store = ManifestStore(root=str(root))
    for row in rows:
        store.upsert(row)
    coord = RunCoordinator(
        str(root), store, client=object(), max_audio_bytes=cap,
        keep_audio=keep, sleep=lambda seconds: None,
    )
    return coord, [(row["work_id"], row) for row in rows]


def _archive_without_model(self, key, entry, result):
    # Isolate the model/publication stage while exercising the coordinator's
    # real reclaim and budget paths against actual downloaded files.
    current = dict(self.store.load()[key])
    current["status"] = "archived"
    self.store.upsert(current)
    self._reclaim_audio(current)
    result.ok = True
    result.final_status = "archived"


def _download_two_candidates(downloaded):
    def download(client, identity, out_path, *, store, **kwargs):
        downloaded.append(identity.work_id)
        target = Path(out_path)
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(b"a" * 4000)
        target.with_suffix(".flac").write_bytes(b"b" * 7000)
        current = dict(store.load()[identity.work_id])
        current.update(status="audio_ok", audio_path=f"audio/{target.name}")
        store.upsert(current)
        return str(target)

    return download


def test_tracker_refreshes_both_candidates_without_double_counting(tmp_path, monkeypatch):
    directory = tmp_path / "audio"
    directory.mkdir()
    m4a, flac = directory / "BVtrackA.p0.m4a", directory / "BVtrackA.p0.flac"
    m4a.write_bytes(b"a" * 10)
    flac.write_bytes(b"b" * 20)
    (directory / "unrelated.m4a").write_bytes(b"c" * 7)
    scans = _count_scans(monkeypatch)
    tracker = audio_budget.AudioUsageTracker(tmp_path)
    entry = {**_row("BVtrackA"), "audio_path": "audio/BVtrackA.p0.m4a"}
    assert tracker.usage_bytes == 37

    m4a.write_bytes(b"a" * 12)
    flac.write_bytes(b"b" * 35)
    tracker.refresh_entry(entry)
    tracker.refresh_entry(entry)
    assert tracker.usage_bytes == 54

    m4a.unlink()
    flac.unlink()
    tracker.refresh_entry(entry)
    assert tracker.usage_bytes == 7
    assert len(scans) == 1


@pytest.mark.parametrize("keep", [True, False])
def test_download_and_reclaim_change_the_next_rows_budget(tmp_path, monkeypatch, keep):
    rows = [_row("BVtrackA"), _row("BVtrackB")]
    coord, selected = _coordinator(tmp_path, rows, keep=keep)
    scans = _count_scans(monkeypatch)
    downloaded = []
    monkeypatch.setattr(audio, "download_audio", _download_two_candidates(downloaded))
    monkeypatch.setattr(RunCoordinator, "_stage_asr_archive", _archive_without_model)

    summary = coord.run_batch(selected)

    assert len(scans) == 1
    assert coord.audio_peak_bytes == 11000
    if keep:
        assert downloaded == ["BVtrackA:p0"]
        assert summary.skipped_rows[0].work_id == "BVtrackB:p0"
        assert summary.skipped_rows[0].skip_reason == "audio_budget"
        assert coord.audio_usage_bytes() == 11000
        assert len(list((tmp_path / "audio").iterdir())) == 2
    else:
        assert downloaded == ["BVtrackA:p0", "BVtrackB:p0"]
        assert summary.ok_count == 2
        assert not summary.skipped_rows
        assert coord.audio_usage_bytes() == 0
        assert not list((tmp_path / "audio").iterdir())


def test_failed_download_rescans_unknown_partial_before_next_row(tmp_path, monkeypatch):
    coord, selected = _coordinator(
        tmp_path, [_row("BVtrackA"), _row("BVtrackB")], cap=12000,
    )
    scans = _count_scans(monkeypatch)
    downloaded = []

    def failed_download(client, identity, out_path, **kwargs):
        downloaded.append(identity.work_id)
        directory = Path(out_path).parent
        directory.mkdir(exist_ok=True)
        (directory / "transport-unknown.partial").write_bytes(b"x" * 9000)
        raise OSError("injected transport failure")

    monkeypatch.setattr(audio, "download_audio", failed_download)
    summary = coord.run_batch(selected)

    assert downloaded == ["BVtrackA:p0"]
    assert len(scans) == 2  # Initial measurement plus the failed transfer's rescan.
    assert summary.failed[0].work_id == "BVtrackA:p0"
    assert summary.skipped_rows[0].work_id == "BVtrackB:p0"
    assert summary.skipped_rows[0].skip_reason == "audio_budget"
    assert coord.audio_usage_bytes() == 9000
    assert coord.audio_peak_bytes == 9000
    assert (tmp_path / "audio" / "transport-unknown.partial").stat().st_size == 9000


def test_unmeasurable_usage_refuses_downloads_with_a_finite_cap(tmp_path, monkeypatch):
    coord, selected = _coordinator(tmp_path, [_row("BVtrackA"), _row("BVtrackB")])
    scans = []

    def unavailable(root):
        scans.append(str(root))
        raise audio_budget.AudioUsageError("injected measurement failure")

    monkeypatch.setattr(audio_budget, "_audio_file_sizes", unavailable)
    monkeypatch.setattr(audio, "download_audio", lambda *a, **kw: pytest.fail("unmeasured download"))

    summary = coord.run_batch(selected)

    assert len(summary.failed) == 2
    assert all(not result.ok for result in summary.results)
    assert not (tmp_path / "audio").exists()
    assert coord.audio_peak_bytes is None
    assert len(scans) == 1


def test_measurement_failure_preserves_archive_and_refuses_later_download(tmp_path, monkeypatch):
    coord, selected = _coordinator(tmp_path, [_row("BVtrackA"), _row("BVtrackB")])
    downloaded = []
    monkeypatch.setattr(audio, "download_audio", _download_two_candidates(downloaded))
    monkeypatch.setattr(RunCoordinator, "_stage_asr_archive", _archive_without_model)

    def unavailable(self, entry):
        raise audio_budget.AudioUsageError("injected refresh failure")

    monkeypatch.setattr(audio_budget.AudioUsageTracker, "refresh_entry", unavailable)
    summary = coord.run_batch(selected)

    assert downloaded == ["BVtrackA:p0"]
    assert summary.results[0].ok
    assert summary.failed[0].work_id == "BVtrackB:p0"
    assert coord.store.load()["BVtrackA:p0"]["status"] == "archived"
    assert coord.audio_peak_bytes is None


def test_reused_coordinator_measures_external_changes_in_next_batch(tmp_path, monkeypatch):
    coord, selected = _coordinator(tmp_path, [_row("BVtrackA"), _row("BVtrackB")], cap=20000)
    scans = _count_scans(monkeypatch)
    downloaded = []
    monkeypatch.setattr(audio, "download_audio", _download_two_candidates(downloaded))
    monkeypatch.setattr(RunCoordinator, "_stage_asr_archive", _archive_without_model)
    assert coord.run_batch(selected[:1]).ok_count == 1
    assert coord.audio_usage_bytes() == 11000

    (tmp_path / "audio" / "other-batch.m4a").write_bytes(b"x" * 3000)
    summary = coord.run_batch(selected[1:])

    assert len(scans) == 2
    assert downloaded == ["BVtrackA:p0"]
    assert summary.skipped_rows[0].skip_reason == "audio_budget"
    assert coord.audio_usage_bytes() == 14000
    assert coord.audio_peak_bytes == 14000


def test_schedule_plan_and_download_gate_share_one_owned_snapshot(tmp_path, monkeypatch, capsys):
    row = _row("BVtrackA", duration_s=3600)
    ManifestStore(root=str(tmp_path)).upsert(row)
    directory = tmp_path / "audio"
    directory.mkdir()
    (directory / "existing.m4a").write_bytes(b"x" * 17)
    scans = _count_scans(monkeypatch)
    plan_usage, gate_usage = [], []
    original_plan, original_gate = long_live.campaign_plan, audio_budget.would_exceed_budget

    def plan(root, entry, cap, **kwargs):
        plan_usage.append(kwargs["usage_bytes"])
        return original_plan(root, entry, cap, **kwargs)

    def gate(root, entry, cap, **kwargs):
        gate_usage.append(kwargs["usage_bytes"])
        return original_gate(root, entry, cap, **kwargs)

    monkeypatch.setattr(long_live, "campaign_plan", plan)
    monkeypatch.setattr(audio_budget, "would_exceed_budget", gate)
    monkeypatch.setattr(bili_client, "BiliClient", lambda **kwargs: object())
    monkeypatch.setattr(audio, "download_audio", lambda *a, **kw: pytest.fail("over-budget download"))

    assert cli.main([
        "schedule", "--archive-root", str(tmp_path), "--scope", row["work_id"],
        "--limit", "1", "--queue-source", "manifest", "--allow-long-live",
        "--max-audio-gb", "0.001",
    ]) == 1

    assert len(scans) == 1
    assert plan_usage == [17]
    assert gate_usage == [17]
    output = capsys.readouterr().out
    assert "audio_usage_bytes=17" in output
    assert "would_exceed=true" in output
    assert "audio/ after bytes=17" in output
