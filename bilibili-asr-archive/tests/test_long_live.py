"""Opt-in long-live campaign proof for `bili-asr schedule`.

Fake transport + stubbed ASR only. No live HTTP, model, or media.
Locks: explicit --allow-long-live, default short-video selection,
configured audio cap, conservative pre-download estimate, measured
audio/ peak, post-archive reclaim, and retryable failure state.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from bili_asr import asr as asr_mod
from bili_asr import bili_client as bc
from bili_asr.audio_budget import estimate_audio_bytes, max_duration_exceeded
from bili_asr.cli import _pilot_select, build_parser, main
from bili_asr.coordinator import AttemptLedger
from bili_asr.long_live import (
    DEFAULT_SHORT_MAX_DURATION_MIN,
    apply_long_live_policy,
    campaign_plan,
    is_long_live,
)
from bili_asr.manifest import ManifestStore
from bili_asr.meta_cursor import utc_now_iso
from bili_asr.page_identity import artifact_stem, page_identity
from bili_asr.scheduler import SchedulerStore

from test_audio import AUDIO_BYTES, SPI_OK, STREAM_HOST, RouterTransport, playurl_ok
from test_scheduler import (
    CidRouterTransport,
    _assert_no_secrets,
    _base_routes,
    _patch_cli,
    _row,
    _scheduler,
    _stub_asr,
    _write_subtitle_raw,
)
from test_subtitles import SAMPLE_DOC, player_ok

import _asr_fakes as asr_fakes
from _archive_database import _seed_archive_database

THREE_HOURS_S = 3 * 60 * 60
ESTIMATED_THREE_HOURS = THREE_HOURS_S * 8_000  # 64 kbps ceiling
DOCS_DIR = Path(__file__).resolve().parents[1] / "docs"


def _long_identity():
    return page_identity("BVlive", 0, 999, "p0")


def _short_identity():
    return page_identity("BVshort", 0, 111, "p0")


def _audio_path(root, identity):
    return os.path.join(root, "audio", f"{artifact_stem(identity)}.m4a")


def _download_transport(identity):
    routes = _base_routes()
    return CidRouterTransport(
        player_by_cid={identity.cid: player_ok([])},
        playurl_by_cid={identity.cid: playurl_ok()},
        routes=routes,
        stream_routes={f"{STREAM_HOST}/a30216.m4s": AUDIO_BYTES},
    )


# ------------------------------------------------------------ helpers / policy


def test_three_hour_row_is_long_live_and_pilot_default_excludes_it():
    long_row = {"work_id": "BVlive:p0", "duration_s": THREE_HOURS_S, "status": "needs_audio"}
    short_row = {"work_id": "BVshort:p0", "duration_s": 5, "status": "needs_audio"}
    assert DEFAULT_SHORT_MAX_DURATION_MIN == 45
    assert is_long_live(long_row) is True
    assert is_long_live(short_row) is False
    assert max_duration_exceeded(long_row, 45) is True
    selected = _pilot_select(
        {"BVlive:p0": long_row, "BVshort:p0": short_row},
        5,
        max_duration_min=DEFAULT_SHORT_MAX_DURATION_MIN,
    )
    keys = [str(e.get("work_id")) for e in selected]
    assert "BVshort:p0" in keys
    assert "BVlive:p0" not in keys


def test_pilot_and_schedule_parser_defaults_keep_short_video_and_audio_cap():
    parser = build_parser()
    pilot = parser.parse_args(["pilot"])
    assert pilot.max_duration_min == 45
    assert pilot.max_audio_gb == 10.0
    schedule = parser.parse_args(["schedule", "--scope", "pending", "--limit", "1"])
    assert schedule.max_audio_gb == 10.0
    assert schedule.allow_long_live is False
    assert schedule.queue_source == "store"
    manifest_schedule = parser.parse_args(
        ["schedule", "--scope", "pending", "--limit", "1", "--queue-source", "manifest"]
    )
    assert manifest_schedule.queue_source == "manifest"


def test_apply_long_live_policy_holds_pending_and_refuses_explicit():
    long_id = _long_identity()
    short_id = _short_identity()
    rows = [
        (short_id.work_id, _row(short_id, status="needs_audio", duration_s=5)),
        (long_id.work_id, _row(long_id, status="needs_audio", duration_s=THREE_HOURS_S)),
    ]
    filtered, held, error = apply_long_live_policy(
        rows, allow_long_live=False, explicit_scope=False,
    )
    assert error is None
    assert held == 1
    assert [key for key, _ in filtered] == [short_id.work_id]

    _kept, _held, explicit_error = apply_long_live_policy(
        rows[-1:], allow_long_live=False, explicit_scope=True,
    )
    assert explicit_error is not None
    assert "--allow-long-live" in explicit_error

    kept_all, held_all, error_all = apply_long_live_policy(
        rows, allow_long_live=True, explicit_scope=False,
    )
    assert error_all is None
    assert held_all == 0
    assert [key for key, _ in kept_all] == [short_id.work_id, long_id.work_id]


def test_unknown_duration_is_long_live_under_default_short_policy():
    assert is_long_live({"duration_s": 0}) is True
    assert is_long_live({}) is True
    assert is_long_live({"duration_s": "nope"}) is True
    assert is_long_live({"duration_s": 5}) is False


def test_campaign_plan_unknown_duration_fail_closes_against_cap(tmp_root):
    identity = _long_identity()
    entry = _row(identity, status="needs_audio", duration_s=0)
    plan = campaign_plan(tmp_root, entry, 1_000_000)
    assert plan["duration_s"] == "unknown"
    assert plan["would_exceed"] is True
    assert plan["estimated_bytes"] == 1_000_001


def test_campaign_plan_walks_audio_dir_once(tmp_root, monkeypatch):
    identity = _long_identity()
    entry = _row(identity, status="needs_audio", duration_s=THREE_HOURS_S)
    audio = os.path.join(tmp_root, "audio")
    os.makedirs(audio, exist_ok=True)
    with open(os.path.join(audio, "fill.m4a"), "wb") as fh:
        fh.write(b"x" * 16)
    walks = {"n": 0}
    real_walk = os.walk

    def counting_walk(*args, **kwargs):
        walks["n"] += 1
        return real_walk(*args, **kwargs)

    monkeypatch.setattr("os.walk", counting_walk)
    campaign_plan(tmp_root, entry, 10 * 1024 ** 3)
    assert walks["n"] == 1


def test_campaign_plan_conservative_estimate_and_budget_gate(tmp_root):
    identity = _long_identity()
    entry = _row(identity, status="needs_audio", duration_s=THREE_HOURS_S)
    cap = 10 * 1024 ** 3
    plan = campaign_plan(tmp_root, entry, cap)
    assert plan["duration_s"] == THREE_HOURS_S
    assert plan["estimated_bytes"] == ESTIMATED_THREE_HOURS
    assert plan["estimated_bytes"] == estimate_audio_bytes(THREE_HOURS_S)
    assert plan["audio_usage_bytes"] == 0
    assert plan["projected_peak_bytes"] == ESTIMATED_THREE_HOURS
    assert plan["would_exceed"] is False
    tiny = campaign_plan(tmp_root, entry, 1_000_000)
    assert tiny["would_exceed"] is True


# ------------------------------------------------------------ CLI: opt-in + defaults


def test_schedule_pending_holds_long_live_without_flag(
    tmp_root, monkeypatch, capsys,
):
    long_id = _long_identity()
    short_id = _short_identity()
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(short_id, status="subtitle_done", duration_s=5))
    store.upsert(_row(long_id, status="needs_audio", duration_s=THREE_HOURS_S))
    raw = os.path.join(tmp_root, "subtitles", "raw", f"{artifact_stem(short_id)}.json")
    os.makedirs(os.path.dirname(raw), exist_ok=True)
    with open(raw, "w", encoding="utf-8") as fh:
        json.dump(SAMPLE_DOC, fh)
    _stub_asr(monkeypatch)
    transport = _download_transport(long_id)
    _patch_cli(monkeypatch, transport)

    _seed_archive_database(tmp_root)
    rc = main([
        "schedule", "--scope", "pending", "--limit", "5",
        "--archive-root", tmp_root,
    ])
    captured = capsys.readouterr()
    assert rc == 0
    assert "--allow-long-live" in captured.out
    assert "batch=limited" in captured.out
    assert "batch=complete" not in captured.out
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[short_id.work_id]["status"] == "archived"
    assert loaded[long_id.work_id]["status"] == "needs_audio"
    assert "needs_audio: 1" in captured.out
    sidecar = _scheduler(tmp_root)
    assert sidecar["state"] == "limited"
    assert transport.stream_calls == []
    _assert_no_secrets(captured, tmp_root)


def test_schedule_pending_only_long_live_is_limited_not_complete(
    tmp_root, monkeypatch, capsys,
):
    identity = _long_identity()
    ManifestStore(root=tmp_root).upsert(
        _row(identity, status="needs_audio", duration_s=THREE_HOURS_S)
    )
    _stub_asr(monkeypatch)
    transport = _download_transport(identity)
    _patch_cli(monkeypatch, transport)

    _seed_archive_database(tmp_root)
    rc = main([
        "schedule", "--scope", "pending", "--limit", "5",
        "--archive-root", tmp_root,
    ])
    captured = capsys.readouterr()
    assert rc == 0
    assert "long-duration row(s) held" in captured.out
    assert "batch=limited" in captured.out
    assert "batch=complete" not in captured.out
    assert ManifestStore(root=tmp_root).load()[identity.work_id]["status"] == (
        "needs_audio"
    )
    assert "needs_audio: 1" in captured.out
    sidecar = _scheduler(tmp_root)
    assert sidecar["state"] == "limited"
    assert sidecar["processed_work_ids"] == []
    assert transport.stream_calls == []
    _assert_no_secrets(captured, tmp_root)


def test_schedule_explicit_long_live_requires_opt_in(
    tmp_root, monkeypatch, capsys,
):
    identity = _long_identity()
    ManifestStore(root=tmp_root).upsert(
        _row(identity, status="needs_audio", duration_s=THREE_HOURS_S)
    )
    _stub_asr(monkeypatch)
    transport = _download_transport(identity)
    _patch_cli(monkeypatch, transport)

    rc = main([
        "schedule", "--scope", identity.work_id, "--limit", "1",
        "--archive-root", tmp_root,
    ])
    captured = capsys.readouterr()
    assert rc == 1
    assert "--allow-long-live" in captured.err
    assert ManifestStore(root=tmp_root).load()[identity.work_id]["status"] == "needs_audio"
    assert transport.stream_calls == []
    assert not os.path.isfile(_audio_path(tmp_root, identity))


def test_allow_long_live_tiny_positive_cap_is_nonzero_not_unlimited(
    tmp_root, monkeypatch, capsys,
):
    identity = _long_identity()
    ManifestStore(root=tmp_root).upsert(
        _row(identity, status="needs_audio", duration_s=THREE_HOURS_S)
    )
    _stub_asr(monkeypatch)
    transport = _download_transport(identity)
    _patch_cli(monkeypatch, transport)

    rc = main([
        "schedule", "--scope", identity.work_id, "--limit", "1",
        "--allow-long-live", "--max-audio-gb", "1e-12",
        "--archive-root", tmp_root,
    ])
    captured = capsys.readouterr()
    assert rc == 1
    assert "cap_bytes=1" in captured.out
    assert "would_exceed=true" in captured.out
    assert "audio_budget" in captured.out
    assert ManifestStore(root=tmp_root).load()[identity.work_id]["status"] == (
        "needs_audio"
    )
    assert transport.stream_calls == []
    assert not os.path.isfile(_audio_path(tmp_root, identity))
    _assert_no_secrets(captured, tmp_root)


def test_allow_long_live_refuses_disabled_audio_cap(
    tmp_root, monkeypatch, capsys,
):
    identity = _long_identity()
    ManifestStore(root=tmp_root).upsert(
        _row(identity, status="needs_audio", duration_s=THREE_HOURS_S)
    )
    _stub_asr(monkeypatch)
    _patch_cli(monkeypatch, _download_transport(identity))

    rc = main([
        "schedule", "--scope", identity.work_id, "--limit", "1",
        "--allow-long-live", "--max-audio-gb", "0",
        "--archive-root", tmp_root,
    ])
    captured = capsys.readouterr()
    assert rc == 1
    assert "cannot disable the audio cap" in captured.err
    assert ManifestStore(root=tmp_root).load()[identity.work_id]["status"] == "needs_audio"


def test_schedule_help_lists_allow_long_live(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["schedule", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--allow-long-live" in out
    assert "--max-audio-gb" in out


# ------------------------------------------------------------ budget / archive / reclaim / retry


def test_allow_long_live_skips_when_conservative_estimate_exceeds_cap(
    tmp_root, monkeypatch, capsys,
):
    identity = _long_identity()
    ManifestStore(root=tmp_root).upsert(
        _row(identity, status="needs_audio", duration_s=THREE_HOURS_S)
    )
    _stub_asr(monkeypatch)
    transport = _download_transport(identity)
    _patch_cli(monkeypatch, transport)

    rc = main([
        "schedule", "--scope", identity.work_id, "--limit", "1",
        "--allow-long-live", "--max-audio-gb", "0.01",
        "--archive-root", tmp_root,
    ])
    captured = capsys.readouterr()
    assert rc == 1
    assert f"duration_s={THREE_HOURS_S}" in captured.out
    assert f"estimated_bytes={ESTIMATED_THREE_HOURS}" in captured.out
    assert "would_exceed=true" in captured.out
    assert "audio_budget" in captured.out
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[identity.work_id]["status"] == "needs_audio"
    assert transport.stream_calls == []
    assert not os.path.isfile(_audio_path(tmp_root, identity))
    skips = [
        rec for rec in AttemptLedger(tmp_root).load()
        if rec["stage"] == "download" and rec["outcome"] == "skipped"
    ]
    assert skips and skips[-1]["error_code"] == "audio_budget"
    _assert_no_secrets(captured, tmp_root)


def test_allow_long_live_archives_and_reclaims_with_measured_peak(
    tmp_root, monkeypatch, capsys,
):
    identity = _long_identity()
    ManifestStore(root=tmp_root).upsert(
        _row(identity, status="needs_audio", duration_s=THREE_HOURS_S)
    )
    filler_dir = os.path.join(tmp_root, "audio")
    os.makedirs(filler_dir, exist_ok=True)
    filler = os.path.join(filler_dir, "other.m4a")
    with open(filler, "wb") as fh:
        fh.write(b"x" * 4096)
    _stub_asr(monkeypatch)
    transport = _download_transport(identity)
    _patch_cli(monkeypatch, transport)

    rc = main([
        "schedule", "--scope", identity.work_id, "--limit", "1",
        "--allow-long-live", "--max-audio-gb", "10",
        # The reclaim this case measures is the retention pair's explicit opt-in
        # (contract D5, plan T4): the default flipped to retain.
        "--no-keep-audio",
        "--archive-root", tmp_root, "--sessdata", "SECRET-SESS",
    ])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert f"duration_s={THREE_HOURS_S}" in captured.out
    assert f"estimated_bytes={ESTIMATED_THREE_HOURS}" in captured.out
    assert "would_exceed=false" in captured.out
    assert "peak audio/" in captured.out
    assert "audio/ after" in captured.out
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[identity.work_id]["status"] == "archived"
    assert not os.path.isfile(_audio_path(tmp_root, identity))
    assert os.path.isfile(filler)
    peak_line = [
        line for line in captured.out.splitlines() if "peak audio/" in line
    ][-1]
    after_line = [
        line for line in captured.out.splitlines() if "audio/ after" in line
    ][-1]
    peak = int(peak_line.rsplit("=", 1)[-1])
    after = int(after_line.rsplit("=", 1)[-1])
    assert peak >= 4096 + len(AUDIO_BYTES)
    assert after == 4096
    assert after < peak
    assert transport.stream_calls  # fake download only
    _assert_no_secrets(captured, tmp_root)


def test_allow_long_live_failed_download_samples_partial_peak(
    tmp_root, monkeypatch, capsys,
):
    identity = _long_identity()
    ManifestStore(root=tmp_root).upsert(
        _row(identity, status="needs_audio", duration_s=THREE_HOURS_S)
    )
    leftover = b"partial-audio" * 128

    def boom(_client, _identity, out_path, store=None):
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "wb") as fh:
            fh.write(leftover)
        raise bc.StreamDownloadError("CDN stream request failed")

    monkeypatch.setattr("bili_asr.audio.download_audio", boom)
    _stub_asr(monkeypatch)
    transport = _download_transport(identity)
    _patch_cli(monkeypatch, transport)

    rc = main([
        "schedule", "--scope", identity.work_id, "--limit", "1",
        "--allow-long-live", "--archive-root", tmp_root,
    ])
    captured = capsys.readouterr()
    assert rc == 1
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[identity.work_id]["status"] == "needs_audio"
    audio_path = _audio_path(tmp_root, identity)
    assert os.path.isfile(audio_path)
    assert os.path.getsize(audio_path) == len(leftover)
    peak_line = [
        line for line in captured.out.splitlines() if "peak audio/" in line
    ][-1]
    after_line = [
        line for line in captured.out.splitlines() if "audio/ after" in line
    ][-1]
    peak = int(peak_line.rsplit("=", 1)[-1])
    after = int(after_line.rsplit("=", 1)[-1])
    assert peak >= len(leftover)
    assert after == len(leftover)
    assert peak >= after
    _assert_no_secrets(captured, tmp_root)


def test_schedule_pending_allow_long_live_processes_long_row(
    tmp_root, monkeypatch, capsys,
):
    long_id = _long_identity()
    short_id = _short_identity()
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(short_id, status="subtitle_done", duration_s=5))
    store.upsert(_row(long_id, status="needs_audio", duration_s=THREE_HOURS_S))
    raw = os.path.join(tmp_root, "subtitles", "raw", f"{artifact_stem(short_id)}.json")
    os.makedirs(os.path.dirname(raw), exist_ok=True)
    with open(raw, "w", encoding="utf-8") as fh:
        json.dump(SAMPLE_DOC, fh)
    _stub_asr(monkeypatch)
    transport = _download_transport(long_id)
    _patch_cli(monkeypatch, transport)

    _seed_archive_database(tmp_root)
    rc = main([
        "schedule", "--scope", "pending", "--limit", "5",
        "--allow-long-live", "--max-audio-gb", "10",
        # Reclaim is explicit now (contract D5, plan T4); this row asserted it before.
        "--no-keep-audio",
        "--archive-root", tmp_root,
    ])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert f"duration_s={THREE_HOURS_S}" in captured.out
    assert "batch=complete" in captured.out
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[short_id.work_id]["status"] == "archived"
    assert loaded[long_id.work_id]["status"] == "archived"
    assert not os.path.isfile(_audio_path(tmp_root, long_id))
    assert transport.stream_calls
    sidecar = _scheduler(tmp_root)
    assert sidecar["state"] == "complete"
    _assert_no_secrets(captured, tmp_root)


def test_allow_long_live_asr_failure_keeps_retryable_audio(
    tmp_root, monkeypatch, capsys,
):
    identity = _long_identity()
    ManifestStore(root=tmp_root).upsert(
        _row(identity, status="needs_audio", duration_s=THREE_HOURS_S)
    )

    # D2.5 seam: `schedule` runs the shared coordinator, which builds its runner's model through
    # this factory.
    asr_fakes.raising(monkeypatch, RuntimeError("asr"))
    transport = _download_transport(identity)
    _patch_cli(monkeypatch, transport)

    rc = main([
        "schedule", "--scope", identity.work_id, "--limit", "1",
        "--allow-long-live", "--archive-root", tmp_root,
    ])
    captured = capsys.readouterr()
    assert rc == 1
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[identity.work_id]["status"] == "audio_ok"
    assert os.path.isfile(_audio_path(tmp_root, identity))
    _assert_no_secrets(captured, tmp_root)


def test_schedule_unknown_duration_held_without_allow_long_live(
    tmp_root, monkeypatch, capsys,
):
    identity = _short_identity()
    ManifestStore(root=tmp_root).upsert(
        _row(identity, status="needs_audio", duration_s=0)
    )
    transport = _download_transport(identity)
    _patch_cli(monkeypatch, transport)
    _stub_asr(monkeypatch)

    _seed_archive_database(tmp_root)
    rc = main([
        "schedule", "--scope", "pending", "--limit", "5",
        "--archive-root", tmp_root,
    ])
    captured = capsys.readouterr()
    assert rc == 0
    assert "long-duration row(s) held" in captured.out
    assert "batch=limited" in captured.out
    assert ManifestStore(root=tmp_root).load()[identity.work_id]["status"] == (
        "needs_audio"
    )
    assert transport.stream_calls == []
    _assert_no_secrets(captured, tmp_root)


def test_schedule_resume_long_live_without_flag_keeps_risk_token(
    tmp_root, monkeypatch, capsys,
):
    identity = _long_identity()
    ManifestStore(root=tmp_root).upsert(
        _row(identity, status="needs_audio", duration_s=THREE_HOURS_S)
    )
    SchedulerStore(root=tmp_root).replace_atomic(
        {
            "scope": "pending",
            "limit": 1,
            "state": "risk_interrupted",
            "processed_work_ids": [],
            "last_api_error_code": -412,
            "allow_long_live": True,
            "updated_at": utc_now_iso(),
        }
    )
    transport = _download_transport(identity)
    _patch_cli(monkeypatch, transport)
    _stub_asr(monkeypatch)

    _seed_archive_database(tmp_root)
    rc = main([
        "schedule", "--scope", "pending", "--limit", "1", "--resume",
        "--archive-root", tmp_root,
    ])
    captured = capsys.readouterr()
    assert rc == 1
    assert "--resume refused" in captured.err
    assert "long-live policy mismatch" in captured.err
    sidecar = _scheduler(tmp_root)
    assert sidecar["state"] == "risk_interrupted"
    assert sidecar["allow_long_live"] is True
    assert ManifestStore(root=tmp_root).load()[identity.work_id]["status"] == (
        "needs_audio"
    )
    assert transport.stream_calls == []
    _assert_no_secrets(captured, tmp_root)


@pytest.mark.parametrize("duration_s", [THREE_HOURS_S, 0])
def test_schedule_resume_risk_stopped_long_row_without_flag_refuses(
    tmp_root, monkeypatch, capsys, duration_s,
):
    identity = _long_identity()
    ManifestStore(root=tmp_root).upsert(
        _row(identity, status="needs_audio", duration_s=duration_s)
    )
    SchedulerStore(root=tmp_root).replace_atomic(
        {
            "scope": "pending",
            "limit": 1,
            "state": "risk_interrupted",
            "processed_work_ids": [],
            "last_api_error_code": -412,
            "allow_long_live": False,
            "updated_at": utc_now_iso(),
        }
    )
    transport = _download_transport(identity)
    _patch_cli(monkeypatch, transport)
    _stub_asr(monkeypatch)

    _seed_archive_database(tmp_root)
    rc = main([
        "schedule", "--scope", "pending", "--limit", "1", "--resume",
        "--archive-root", tmp_root,
    ])
    captured = capsys.readouterr()
    assert rc == 1
    assert "--resume refused" in captured.err
    assert "risk-stopped long-duration" in captured.err
    sidecar = _scheduler(tmp_root)
    assert sidecar["state"] == "risk_interrupted"
    assert ManifestStore(root=tmp_root).load()[identity.work_id]["status"] == (
        "needs_audio"
    )
    assert transport.stream_calls == []
    _assert_no_secrets(captured, tmp_root)


def test_schedule_resume_mixed_held_long_then_short_risk_continues(
    tmp_root, monkeypatch, capsys,
):
    """A held long/unknown row that sorts first is not the risk-stopped row."""
    long_id = page_identity("BVaLong", 0, 999, "p0")
    short_id = page_identity("BVzShort", 0, 111, "p0")
    assert long_id.work_id < short_id.work_id
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(long_id, status="needs_audio", duration_s=THREE_HOURS_S))
    store.upsert(_row(short_id, status="subtitle_done", duration_s=5))
    _write_subtitle_raw(tmp_root, short_id)
    SchedulerStore(root=tmp_root).replace_atomic(
        {
            "scope": "pending",
            "limit": 5,
            "state": "risk_interrupted",
            "processed_work_ids": [],
            "last_api_error_code": -412,
            "allow_long_live": False,
            "updated_at": utc_now_iso(),
        }
    )
    _stub_asr(monkeypatch)
    _patch_cli(monkeypatch, RouterTransport(_base_routes()))

    _seed_archive_database(tmp_root)
    rc = main([
        "schedule", "--scope", "pending", "--limit", "5", "--resume",
        "--archive-root", tmp_root,
    ])
    captured = capsys.readouterr()
    assert rc == 0
    assert "--resume refused" not in captured.err
    assert "risk-stopped long-duration" not in captured.err
    assert "long-duration row(s) held" in captured.out
    assert "batch=limited" in captured.out
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[long_id.work_id]["status"] == "needs_audio"
    assert loaded[short_id.work_id]["status"] == "archived"
    sidecar = _scheduler(tmp_root)
    assert sidecar["state"] == "limited"
    assert sidecar["allow_long_live"] is False
    assert short_id.work_id in sidecar["processed_work_ids"]
    _assert_no_secrets(captured, tmp_root)


# ------------------------------------------------------------ operator docs


def test_operator_guide_and_evidence_template_cover_wsl_boundaries():
    guide = (DOCS_DIR / "wsl-long-live.md").read_text(encoding="utf-8")
    evidence = (DOCS_DIR / "wsl-long-live-evidence.md").read_text(encoding="utf-8")
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(
        encoding="utf-8"
    )
    blob = "\n".join((guide, evidence))
    assert "Windows" in guide and "WSL" in guide
    assert "du -sb" in guide
    assert "BILI_SESSDATA" in guide
    assert "--allow-long-live" in guide
    assert "--max-audio-gb" in guide
    assert "archive-root" in guide or "--archive-root" in guide
    assert "cookie" in guide.lower()
    assert "redact" in evidence.lower() or "redacted" in evidence.lower()
    assert "du -sb" in evidence
    assert "allow-long-live" in readme
    scanned = blob.replace("BILI_SESSDATA", "BILI_COOKIE")
    assert "SESSDATA=" not in scanned
    assert "SECRET" not in blob
    assert "http://" not in blob
    assert "bilivideo.com" not in blob
    assert "Traceback" not in blob
