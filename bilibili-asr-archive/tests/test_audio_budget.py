"""Tests for the bounded audio budget gate and duration skip."""

from __future__ import annotations

from bili_asr.audio_budget import (
    SKIP_REASON,
    audio_cap_bytes,
    audio_dir_usage_bytes,
    estimate_audio_bytes,
    max_duration_exceeded,
    parse_duration_s,
    would_exceed_budget,
)


def test_usage_empty_when_no_audio_dir(tmp_path):
    assert audio_dir_usage_bytes(tmp_path) == 0


def test_usage_sums_files(tmp_path):
    audio = tmp_path / "audio"
    audio.mkdir()
    (audio / "a.m4a").write_bytes(b"x" * 100)
    (audio / "b.m4a").write_bytes(b"x" * 50)
    assert audio_dir_usage_bytes(tmp_path) == 150


def test_estimate_uses_64kbps_ceiling():
    assert estimate_audio_bytes(60) == 60 * 8000
    assert estimate_audio_bytes(None) == 0
    assert estimate_audio_bytes("garbage") == 0


def test_would_exceed_budget_true_then_false_after_reclaim(tmp_path):
    audio = tmp_path / "audio"
    audio.mkdir()
    cap = 1 * 1024 * 1024
    (audio / "existing.m4a").write_bytes(b"x" * (cap - 400_000))
    entry = {"duration_s": 60}  # 60s = 480 000 B
    assert would_exceed_budget(tmp_path, entry, cap) is True
    (audio / "existing.m4a").unlink()
    assert would_exceed_budget(tmp_path, entry, cap) is False


def test_zero_max_is_unlimited(tmp_path):
    audio = tmp_path / "audio"
    audio.mkdir()
    (audio / "big.m4a").write_bytes(b"x" * 1000)
    assert would_exceed_budget(tmp_path, {"duration_s": 99999}, 0) is False


def test_audio_cap_bytes_positive_never_truncates_to_unlimited(tmp_path):
    assert audio_cap_bytes(0) == 0
    assert audio_cap_bytes(-1) == 0
    tiny = 1e-12
    assert int(tiny * 1024 ** 3) == 0
    assert audio_cap_bytes(tiny) == 1
    assert audio_cap_bytes(10) == 10 * 1024 ** 3
    assert would_exceed_budget(
        tmp_path, {"duration_s": 1}, audio_cap_bytes(tiny)
    ) is True


def test_max_duration_exceeded():
    assert max_duration_exceeded({"duration_s": 46 * 60}, 45) is True
    assert max_duration_exceeded({"duration_s": 44 * 60}, 45) is False
    assert max_duration_exceeded({"duration_s": 99999}, 0) is False  # off
    assert max_duration_exceeded({"duration_s": 5}, 45) is False


def test_unknown_zero_unparseable_duration_fail_closed(tmp_path):
    assert parse_duration_s(None) is None
    assert parse_duration_s(0) is None
    assert parse_duration_s("garbage") is None
    assert parse_duration_s(12) == 12
    assert max_duration_exceeded({}, 45) is True
    assert max_duration_exceeded({"duration_s": 0}, 45) is True
    assert max_duration_exceeded({"duration_s": "nope"}, 45) is True
    assert max_duration_exceeded({}, 0) is False  # cap off
    assert would_exceed_budget(tmp_path, {}, 1) is True
    assert would_exceed_budget(tmp_path, {"duration_s": 0}, 1) is True
    assert would_exceed_budget(tmp_path, {"duration_s": "nope"}, 1) is True
    assert would_exceed_budget(tmp_path, {}, 0) is False  # unlimited
    assert estimate_audio_bytes(None) == 0
    assert estimate_audio_bytes(0) == 0


def test_skip_reason_is_stable_scalar():
    assert SKIP_REASON == "audio_budget"


# --- CLI wiring: pilot honors budget + duration flags ---


def _budget_row(bvid, cid, duration_s, status="meta_ok", audio_path=None):
    row = {
        "work_id": f"{bvid}:p0", "bvid": bvid, "cid": cid, "page_index": 0,
        "status": status, "duration_s": duration_s, "title": "t",
    }
    if audio_path:
        row["audio_path"] = audio_path
    return row


def test_pilot_budget_skip_via_cli(tmp_path, monkeypatch, capsys):
    """Audio row skipped with named reason when cap would be breached."""
    import sys
    sys.path.insert(0, "tests")
    from test_cli_pilot import RouterTransport, SPI_OK, nav_ok, nav_response, player_ok  # noqa
    from bili_asr import bili_client as bc
    from bili_asr import asr as asr_mod
    from bili_asr.cli import main
    from bili_asr.manifest import ManifestStore

    store = ManifestStore(root=str(tmp_path))
    store.upsert(_budget_row("BVaud", 222, 600, status="needs_audio"))
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    # Small equivalent of a 1 GiB cap: 600s*8000B/s exceeds this cap.
    (audio_dir / "fill.m4a").write_bytes(b"x" * 600_000)
    monkeypatch.setattr(bc, "build_default_transport", lambda: RouterTransport({}))
    monkeypatch.setattr(bc, "default_sleeper", lambda: (lambda _s: None))
    called = []
    # D2.5 seam: patch the factory the runner builds through (the one-shot
    # `asr.transcribe` wrapper is no longer on the pilot's path).
    class FakeModel:
        def generate(self, **_kwargs):
            called.append(True)
            return [{"start": 0.0, "end": 1.0, "text": "x"}]

    monkeypatch.setenv("BILI_ASR_DEVICE", "cpu")
    monkeypatch.setattr(asr_mod, "_load_default_model", lambda **_kw: FakeModel())
    rc = main(["pilot", "--n", "2", "--archive-root", str(tmp_path),
               "--max-audio-gb", "0.001"])
    captured = capsys.readouterr()
    assert "audio_budget" in captured.err
    assert not called
    assert rc == 1  # required audio-ASR branch had zero eligible rows


def test_pilot_duration_excluded_from_selection(tmp_path, monkeypatch, capsys):
    from bili_asr.cli import _pilot_select

    rows = {
        "BVlong:p0": _budget_row("BVlong", 1, 3600),
        "BVshort:p0": _budget_row("BVshort", 2, 600),
    }
    selected = _pilot_select(rows, 5, max_duration_min=45)
    keys = [str(e.get("work_id")) for e in selected]
    assert "BVshort:p0" in keys
    assert "BVlong:p0" not in keys


def test_run_coordinator_download_budget_skip(tmp_path):
    """run download stage skips (does not download) when cap would be breached."""
    from bili_asr.coordinator import RunCoordinator
    from bili_asr.manifest import ManifestStore

    store = ManifestStore(root=str(tmp_path))
    store.upsert(_budget_row("BVaud", 222, 600, status="needs_audio"))
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    (audio_dir / "fill.m4a").write_bytes(b"x" * 600_000)

    class _BoomClient:
        def __getattr__(self, name):
            raise AssertionError("budget skip must not touch HTTP")

    coord = RunCoordinator(
        str(tmp_path), store, client=_BoomClient(),
        max_audio_bytes=1_000_000, sleep=lambda _s: None,
    )
    coord.run_batch([("BVaud:p0", store.load()["BVaud:p0"])])
    row = store.load()["BVaud:p0"]
    assert row["status"] == "needs_audio"  # untouched
    attempts = coord.ledger.load()
    skips = [r for r in attempts
             if r["stage"] == "download" and r["outcome"] == "skipped"]
    assert skips and skips[-1]["error_code"] == "audio_budget"
    assert not list(audio_dir.glob("BVaud*"))
