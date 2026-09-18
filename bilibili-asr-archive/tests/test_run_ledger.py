"""Unit tests for RunLedger + fetch-meta / pilot run records (no live network)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from bili_asr import asr as asr_mod
from bili_asr import bili_client as bc
from bili_asr.cli import _partial_run_state, main
from bili_asr.manifest import ManifestStore
from bili_asr.meta_cursor import MetaCursorStore, utc_now_iso
from bili_asr.page_identity import page_identity
from bili_asr.run_ledger import (
    LEDGER_FILENAME,
    RunLedger,
    build_run_record,
    compute_coverage_summary,
    format_coverage_summary,
    format_cursor_summary,
    format_run_summary,
    generate_run_id,
)

from test_audio import (
    AUDIO_BYTES,
    SPI_OK,
    STREAM_HOST,
    RouterTransport,
    nav_response,
    playurl_ok,
)
from test_fetch_meta import FastSleeper
from test_subtitles import SAMPLE_DOC, nav_ok, player_ok, sub_entry


@pytest.fixture
def fast_sleep():
    return FastSleeper()


def _patch_client(monkeypatch, transport, sleeper=None):
    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
    if sleeper is not None:
        monkeypatch.setattr(bc, "default_sleeper", lambda: sleeper)
    else:
        monkeypatch.setattr(bc, "default_sleeper", lambda: (lambda _seconds: None))
    monkeypatch.setattr("bili_asr.cli.time.sleep", lambda _seconds: None)


# ---------------------------------------------------------------- RunLedger core


def test_ledger_initial_empty(tmp_root):
    ledger = RunLedger(root=tmp_root)
    assert ledger.load() == []
    assert ledger.latest() is None
    assert os.path.basename(ledger.path) == LEDGER_FILENAME
    assert os.path.dirname(ledger.path) == tmp_root


def test_ledger_schema_roundtrip(tmp_root):
    ledger = RunLedger(root=tmp_root)
    cursor_snap = {
        "mid": 23191782,
        "next_page": 2,
        "total": 50,
        "state": "complete",
        "last_api_error_code": None,
        "updated_at": utc_now_iso(),
    }
    rec = build_run_record(
        command="fetch-meta",
        started_at="2026-08-25T10:00:00Z",
        finished_at="2026-08-25T10:01:00Z",
        exit_code=0,
        run_id="run-test-01",
        mid=23191782,
        work_ids=None,
        pages_fetched=2,
        records_fetched=40,
        records_existing=0,
        last_api_error_code=None,
        coverage_summary={"meta_ok": 40},
        cursor_snapshot=cursor_snap,
    )
    stored = ledger.append(rec)
    assert stored["run_id"] == "run-test-01"
    assert stored["command"] == "fetch-meta"
    assert stored["exit_code"] == 0
    assert stored["coverage_summary"] == {"meta_ok": 40}
    assert stored["cursor_snapshot"] == cursor_snap

    loaded = ledger.load()
    assert len(loaded) == 1
    assert loaded[0] == stored
    assert ledger.latest() == stored


def test_ledger_multiple_appends_chronological(tmp_root):
    ledger = RunLedger(root=tmp_root)
    r1 = ledger.append(
        build_run_record(
            command="fetch-meta",
            started_at="2026-08-25T10:00:00Z",
            finished_at="2026-08-25T10:01:00Z",
            exit_code=0,
            run_id="run-1",
            mid=123,
        )
    )
    r2 = ledger.append(
        build_run_record(
            command="pilot",
            started_at="2026-08-25T10:02:00Z",
            finished_at="2026-08-25T10:03:00Z",
            exit_code=0,
            run_id="run-2",
            work_ids=["BV1xx:p0"],
        )
    )
    loaded = ledger.load()
    assert len(loaded) == 2
    assert loaded[0]["run_id"] == "run-1"
    assert loaded[1]["run_id"] == "run-2"
    assert ledger.latest()["run_id"] == "run-2"
    assert not os.path.exists(ledger.path + ".tmp")


def test_latest_streams_large_history_without_calling_load(tmp_root, monkeypatch):
    ledger = RunLedger(root=tmp_root)
    base = build_run_record(
        command="pilot",
        started_at="2026-08-25T10:00:00Z",
        finished_at="2026-08-25T10:01:00Z",
        exit_code=0,
        run_id="run-0",
        work_ids=["BV1xx:p0"],
    )
    with open(ledger.path, "w", encoding="utf-8") as handle:
        for index in range(10001):
            handle.write(json.dumps({**base, "run_id": f"run-{index}"}) + "\n")

    monkeypatch.setattr(
        ledger, "load", lambda: (_ for _ in ()).throw(AssertionError("load called"))
    )
    assert ledger.latest()["run_id"] == "run-10000"


def test_ledger_validation_required_fields(tmp_root):
    ledger = RunLedger(root=tmp_root)
    with pytest.raises(ValueError, match="required field"):
        ledger.append({"command": "pilot", "started_at": "2026-08-25T00:00:00Z"})


def test_ledger_validation_types(tmp_root):
    ledger = RunLedger(root=tmp_root)
    base = {
        "run_id": "r1",
        "command": "pilot",
        "started_at": "2026-08-25T00:00:00Z",
        "finished_at": "2026-08-25T00:01:00Z",
        "exit_code": 0,
    }

    # exit_code cannot be bool
    with pytest.raises(ValueError, match="exit_code"):
        ledger.append({**base, "exit_code": True})

    # mid cannot be str
    with pytest.raises(ValueError, match="mid"):
        ledger.append({**base, "mid": "23191782"})

    # work_ids must be list of str
    with pytest.raises(ValueError, match="work_ids"):
        ledger.append({**base, "work_ids": [123]})


def test_ledger_validation_coverage_summary(tmp_root):
    ledger = RunLedger(root=tmp_root)
    base = {
        "run_id": "r1",
        "command": "pilot",
        "started_at": "2026-08-25T00:00:00Z",
        "finished_at": "2026-08-25T00:01:00Z",
        "exit_code": 0,
    }

    # unknown status key
    with pytest.raises(ValueError, match="invalid status key"):
        ledger.append({**base, "coverage_summary": {"unknown_status": 5}})

    # negative count
    with pytest.raises(ValueError, match="int >= 0"):
        ledger.append({**base, "coverage_summary": {"archived": -1}})

    # bool count
    with pytest.raises(ValueError, match="int >= 0"):
        ledger.append({**base, "coverage_summary": {"archived": True}})


def test_ledger_validation_cursor_snapshot(tmp_root):
    ledger = RunLedger(root=tmp_root)
    base = {
        "run_id": "r1",
        "command": "fetch-meta",
        "started_at": "2026-08-25T00:00:00Z",
        "finished_at": "2026-08-25T00:01:00Z",
        "exit_code": 0,
    }

    # missing cursor field
    with pytest.raises(ValueError, match="cursor_snapshot missing fields"):
        ledger.append({**base, "cursor_snapshot": {"mid": 1}})

    # running cursor snapshot is not allowed
    with pytest.raises(ValueError, match="state=running"):
        ledger.append(
            {
                **base,
                "cursor_snapshot": {
                    "mid": 1,
                    "next_page": 1,
                    "total": 10,
                    "state": "running",
                    "last_api_error_code": None,
                    "updated_at": utc_now_iso(),
                },
            }
        )


def test_ledger_forbidden_markers_redaction(tmp_root):
    ledger = RunLedger(root=tmp_root)
    base = {
        "run_id": "r1",
        "command": "pilot",
        "started_at": "2026-08-25T00:00:00Z",
        "finished_at": "2026-08-25T00:01:00Z",
        "exit_code": 0,
    }

    for forbidden in ["SESSDATA=xyz", "cookie=abc", "http://bad.url", "https://bad.url", "Traceback (most recent):"]:
        with pytest.raises(ValueError, match="forbidden marker"):
            ledger.append({**base, "last_api_error_code": forbidden})


def test_ledger_error_code_max_len(tmp_root):
    ledger = RunLedger(root=tmp_root)
    base = {
        "run_id": "r1",
        "command": "pilot",
        "started_at": "2026-08-25T00:00:00Z",
        "finished_at": "2026-08-25T00:01:00Z",
        "exit_code": 0,
    }
    with pytest.raises(ValueError, match="not a redacted code"):
        ledger.append({**base, "last_api_error_code": "E" * 65})


def test_compute_coverage_summary(tmp_root):
    store = ManifestStore(root=tmp_root)
    assert compute_coverage_summary(store) == {}
    store.upsert({"bvid": "BV1", "work_id": "BV1:p0", "status": "meta_ok"})
    store.upsert({"bvid": "BV2", "work_id": "BV2:p0", "status": "archived"})
    store.upsert({"bvid": "BV3", "work_id": "BV3:p0", "status": "archived"})
    summary = compute_coverage_summary(store)
    assert summary == {"archived": 2, "meta_ok": 1}


def test_corrupt_lines_ignored(tmp_root, capsys):
    ledger = RunLedger(root=tmp_root)
    ledger.append(
        build_run_record(
            command="fetch-meta",
            started_at="2026-08-25T10:00:00Z",
            finished_at="2026-08-25T10:01:00Z",
            exit_code=0,
            run_id="run-valid-1",
        )
    )
    # Manually append corrupt line, non-dict JSON lines, and another valid line
    with open(ledger.path, "a", encoding="utf-8") as fh:
        fh.write("{corrupt json\n")
        fh.write('{"run_id":"bad","command":"x"}\n')  # missing required fields
        fh.write("[1, 2, 3]\n")  # valid JSON, non-dict
        fh.write('"standalone string"\n')  # valid JSON, non-dict

    ledger.append(
        build_run_record(
            command="pilot",
            started_at="2026-08-25T10:02:00Z",
            finished_at="2026-08-25T10:03:00Z",
            exit_code=0,
            run_id="run-valid-2",
        )
    )
    loaded = ledger.load()
    assert len(loaded) == 2
    assert loaded[0]["run_id"] == "run-valid-1"
    assert loaded[1]["run_id"] == "run-valid-2"
    captured = capsys.readouterr()
    assert captured.err.count("run-ledger: ignoring corrupt line") == 4


def test_bili_client_does_not_import_run_ledger():
    import bili_asr.bili_client as mod

    assert "bili_asr.run_ledger" not in getattr(mod, "__dict__", {})
    src = open(mod.__file__, encoding="utf-8").read()
    assert "run_ledger" not in src


# ------------------------------------------------- interrupted run inputs (R5)


def test_partial_counts_come_from_the_attempts_this_run_persisted(tmp_path: Path) -> None:
    """A killed run still says what it managed to do."""
    from bili_asr.coordinator import AttemptLedger

    started_at = "2026-09-18T00:00:00Z"
    ledger = AttemptLedger(tmp_path)
    ledger.append({"stage": "download", "work_id": "BVold:p0", "attempt": 1,
                   "outcome": "ok", "error_code": None, "artifact_paths": [],
                   "started_at": "2026-09-17T23:00:00Z",
                   "finished_at": "2026-09-17T23:00:01Z"})          # before this run
    for stage in ("download", "asr"):
        ledger.append({"stage": stage, "work_id": "BV1x:p0", "attempt": 1,
                       "outcome": "ok", "error_code": None, "artifact_paths": [],
                       "started_at": started_at, "finished_at": started_at})

    work_ids, records_existing, coverage = _partial_run_state(tmp_path, started_at)
    record = build_run_record(command="run", started_at=started_at, exit_code=143,
                              work_ids=work_ids, records_existing=records_existing,
                              coverage_summary=coverage)
    assert record["command"] == "run"
    assert record["work_ids"] == ["BV1x:p0"]      # BVold:p0 belongs to an earlier run
    assert record["exit_code"] == 143
    # The manifest's row count, exactly as the normal path passes len(entries) --
    # this root has no manifest rows yet, while the attempts ledger has three.
    assert record["records_existing"] == 0


# ---------------------------------------------------------------- CLI pilot wiring
# (fetch-meta no longer appends JSONL ledger records: the SQLite metadata
# path writes normalized runs; see tests/test_metadata_cli.py)


def _pilot_row(identity, *, duration_s, title="clip"):
    return {
        "bvid": identity.bvid,
        "work_id": identity.work_id,
        "page_index": identity.page_index,
        "cid": identity.cid,
        "page_label": identity.page_label,
        "status": "meta_ok",
        "title": title,
        "duration_s": duration_s,
        "pubdate": 1,
        "pubdate_str": "2026-01-02",
    }


def _mixed_transport():
    return RouterTransport(
        {
            "finger/spi": [SPI_OK],
            "nav": [nav_ok(), nav_response()],
            "player/wbi/v2": [player_ok([sub_entry()]), player_ok([])],
            "aisubtitle.hdslb.com": [(200, dict(SAMPLE_DOC))],
            "/x/player/wbi/playurl": [playurl_ok()],
        },
        stream_routes={f"{STREAM_HOST}/a30216.m4s": AUDIO_BYTES},
    )


def test_cli_pilot_exit_0_appends_ledger(tmp_root, monkeypatch, capsys):
    sub = page_identity("BVsub", 0, 111, "p0")
    aud = page_identity("BVaud", 0, 222, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_pilot_row(sub, duration_s=5, title="has-sub"))
    store.upsert(_pilot_row(aud, duration_s=8, title="needs-asr"))

    # D2.5 seam: `pilot` owns one runner for the whole invocation now, so the
    # stub sits on the factory the runner builds its model through.
    class FakeModel:
        def generate(self, **_kwargs):
            return [{"start": 0.0, "end": 1.0, "text": "asr-text"}]

    monkeypatch.setenv("BILI_ASR_DEVICE", "cpu")
    monkeypatch.setattr(asr_mod, "_load_default_model", lambda **_kw: FakeModel())
    _patch_client(monkeypatch, _mixed_transport())

    rc = main(["pilot", "--n", "2", "--archive-root", tmp_root, "--sessdata", "SECRET-SESSDATA-12345"])
    assert rc == 0

    ledger = RunLedger(root=tmp_root)
    records = ledger.load()
    assert len(records) == 1
    rec = records[0]
    assert rec["command"] == "pilot"
    assert rec["exit_code"] == 0
    assert rec["coverage_summary"] == {"archived": 2}
    assert sorted(rec["work_ids"]) == sorted([sub.work_id, aud.work_id])

    # Ensure no credentials leaked into the ledger file
    with open(ledger.path, "r", encoding="utf-8") as fh:
        raw_ledger = fh.read()
    assert "SECRET-SESSDATA-12345" not in raw_ledger


def test_cli_pilot_exit_1_empty_manifest_appends_ledger(tmp_root, capsys):
    rc = main(["pilot", "--archive-root", tmp_root])
    assert rc == 1

    ledger = RunLedger(root=tmp_root)
    records = ledger.load()
    assert len(records) == 1
    rec = records[0]
    assert rec["command"] == "pilot"
    assert rec["exit_code"] == 1
    assert rec["work_ids"] is None
    assert rec["coverage_summary"] == {}


def test_cli_pilot_exit_2_risk_appends_ledger(tmp_root, monkeypatch, capsys):
    sub = page_identity("BVrisk", 0, 333, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_pilot_row(sub, duration_s=5, title="hit-risk"))

    def raise_risk(*_args, **_kwargs):
        raise bc.RiskBudgetExhausted(-412)

    monkeypatch.setattr("bili_asr.subtitles.harvest_subtitle", raise_risk)
    _patch_client(monkeypatch, _mixed_transport())

    rc = main(["pilot", "--n", "1", "--archive-root", tmp_root])
    assert rc == 2

    ledger = RunLedger(root=tmp_root)
    records = ledger.load()
    assert len(records) == 1
    rec = records[0]
    assert rec["command"] == "pilot"
    assert rec["exit_code"] == 2
    assert rec["last_api_error_code"] == -412


# ---------------------------------------------------------------- Formatters & CLI status / runs


def test_format_cursor_summary():
    assert format_cursor_summary(None) == "none"
    assert format_cursor_summary({}) == "none"
    assert format_cursor_summary({"state": "complete", "total": 100}) == "complete (total 100)"
    assert format_cursor_summary({"state": "complete", "total": None}) == "complete"
    assert (
        format_cursor_summary({"state": "limited", "next_page": 3, "total": 50})
        == "limited (next_page 3, observed_total 50)"
    )
    assert (
        format_cursor_summary({"state": "limited", "next_page": 3, "total": None})
        == "limited (next_page 3)"
    )
    assert (
        format_cursor_summary({"state": "risk_interrupted", "next_page": 2, "last_api_error_code": -412})
        == "risk_interrupted (next_page 2, code -412)"
    )
    assert (
        format_cursor_summary({"state": "risk_interrupted", "next_page": 2, "last_api_error_code": None})
        == "risk_interrupted (next_page 2)"
    )


def test_format_coverage_summary():
    assert format_coverage_summary(None) == "none"
    assert format_coverage_summary({}) == "none"
    assert (
        format_coverage_summary({"meta_ok": 10, "archived": 2, "unknown": 5})
        == "archived: 2, meta_ok: 10"
    )


def test_format_run_summary():
    rec = {
        "run_id": "run-20260825-test1",
        "command": "fetch-meta",
        "exit_code": 0,
        "finished_at": "2026-08-25T10:00:00Z",
        "cursor_snapshot": {"state": "complete", "total": 40},
        "coverage_summary": {"meta_ok": 40},
    }
    line = format_run_summary(rec)
    assert "run-20260825-test1" in line
    assert "command: fetch-meta" in line
    assert "exit: 0" in line
    assert "cursor: complete (total 40)" in line
    assert "coverage: [meta_ok: 40]" in line
    assert "(2026-08-25T10:00:00Z)" in line


# (the CLI status/runs tests moved to the SQLite metadata path:
# tests/test_metadata_cli.py)

