"""RunCoordinator + `bili-asr run` (Task 1): fake transport + stubbed ASR.

No live HTTP: RouterTransport scripts every response; transcribe is
monkeypatched to a deterministic stub.
"""

from __future__ import annotations

import json
import os

from bili_asr import asr as asr_mod
from bili_asr import bili_client as bc
from bili_asr.cli import main
from bili_asr.coordinator import AttemptLedger, RunCoordinator
from bili_asr.manifest import ManifestStore
from bili_asr.page_identity import artifact_stem, page_identity

from test_audio import (
    AUDIO_BYTES,
    SPI_OK,
    STREAM_HOST,
    RouterTransport,
    nav_response,
    playurl_ok,
)
from test_subtitles import SAMPLE_DOC, nav_ok, player_ok, sub_entry


def _row(identity, *, status="meta_ok", duration_s=5, title="clip"):
    return {
        "bvid": identity.bvid,
        "work_id": identity.work_id,
        "page_index": identity.page_index,
        "cid": identity.cid,
        "page_label": identity.page_label,
        "status": status,
        "title": title,
        "duration_s": duration_s,
        "pubdate": 1,
        "pubdate_str": "2026-01-02",
    }


def _patch_cli(monkeypatch, transport):
    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
    monkeypatch.setattr(bc, "default_sleeper", lambda: (lambda _s: None))
    monkeypatch.setattr("bili_asr.cli.time.sleep", lambda _s: None)


def _stub_asr(monkeypatch, calls=None):
    def fake_transcribe(audio_path, model_name=None):
        if calls is not None:
            calls.append(audio_path)
        return [{"start": 0.0, "end": 1.0, "text": "asr-text"}]

    monkeypatch.setattr(asr_mod, "transcribe", fake_transcribe)


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


def _cid_transport(sub_cids):
    return CidRouterTransport(
        sub_cids,
        routes={
            "finger/spi": [SPI_OK],
            "nav": [nav_ok(), nav_response()],
            "aisubtitle.hdslb.com": [(200, dict(SAMPLE_DOC))],
            "playurl": [playurl_ok()],
        },
        stream_routes={f"{STREAM_HOST}/a30216.m4s": AUDIO_BYTES},
    )


class CidRouterTransport(RouterTransport):
    """Routes player/wbi/v2 by the cid param so scripting is per-page.

    Rows run in sorted(work_id) order which need not match queue order
    for arbitrary bvid names; routing by cid keeps the subtitle-hit /
    no-subtitle assignment explicit per test.
    """

    def __init__(self, sub_cids, routes=None, stream_routes=None):
        routes = dict(routes or {})
        routes.pop("player/wbi/v2", None)
        self._playurl_queue = routes.pop("playurl", None)
        super().__init__(routes, stream_routes)
        self.sub_cids = set(sub_cids)

    def get_json(self, url, params=None, headers=None, cookies=None, timeout=None):
        if "player/wbi/v2" in url:
            cid = dict(params or {}).get("cid")
            if cid in self.sub_cids:
                return player_ok([sub_entry()])
            return player_ok([])
        if "/x/player/wbi/playurl" in url:
            # RouterTransport routes by substring; player/wbi/v2 would also
            # match this URL, so serve playurl from an explicit queue.
            queue = self._playurl_queue or [playurl_ok()]
            if not queue:
                raise AssertionError("queue for playurl exhausted")
            return queue.pop(0)
        return super().get_json(url, params=params, headers=headers,
                                cookies=cookies, timeout=timeout)


# ------------------------------------------------------------ ledger atomicity

def test_attempt_ledger_append_is_atomic_no_partial_lines(tmp_root):
    ledger = AttemptLedger(tmp_root)
    rec = {
        "stage": "asr",
        "work_id": "BV1x:p0",
        "attempt": 1,
        "outcome": "ok",
        "error_code": None,
        "artifact_paths": ["audio/a.m4a"],
        "started_at": "2026-08-25T00:00:00Z",
        "finished_at": "2026-08-25T00:00:01Z",
    }
    stored = ledger.append(rec)
    assert stored["stage"] == "asr"
    with open(ledger.path, "rb") as fh:
        content = fh.read()
    assert content.endswith(b"\n")
    lines = [l for l in content.decode().split("\n") if l]
    assert len(lines) == 1
    json.loads(lines[0])  # complete, valid JSON line


def test_attempt_ledger_rejects_non_redacted_payload(tmp_root):
    ledger = AttemptLedger(tmp_root)
    bad = {
        "stage": "harvest",
        "work_id": "BV1x:p0",
        "attempt": 1,
        "outcome": "ok",
        "error_code": None,
        "artifact_paths": ["https://signed.example.com/x"],
        "started_at": "2026-08-25T00:00:00Z",
        "finished_at": "2026-08-25T00:00:01Z",
    }
    import pytest

    with pytest.raises(ValueError):
        ledger.append(bad)
    assert not os.path.exists(ledger.path)


def test_attempt_counter_increments_across_instantiations(tmp_root):
    store = ManifestStore(root=tmp_root)
    sub = page_identity("BVcnt", 0, 111, "p0")
    store.upsert(_row(sub))
    coord = RunCoordinator(tmp_root, store)
    coord._record("harvest", sub.work_id, "ok")
    coord2 = RunCoordinator(tmp_root, store)
    coord2._record("harvest", sub.work_id, "ok")
    records = AttemptLedger(tmp_root).load()
    assert [r["attempt"] for r in records] == [1, 2]


# ------------------------------------------------------------ run: live path

def test_cli_run_pending_executes_stages_and_records_attempts(
    tmp_root, monkeypatch, capsys
):
    sub = page_identity("BVsub", 0, 111, "p0")
    aud = page_identity("BVaud", 0, 222, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(sub, title="has-sub"))
    store.upsert(_row(aud, title="needs-asr"))
    _stub_asr(monkeypatch)
    _patch_cli(monkeypatch, _cid_transport({sub.cid}))

    rc = main(["run", "--scope", "pending", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 0, captured.err

    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[sub.work_id]["status"] == "archived"
    assert loaded[aud.work_id]["status"] == "archived"

    attempts = AttemptLedger(tmp_root).load()
    stages_by_work = {}
    for rec in attempts:
        stages_by_work.setdefault(rec["work_id"], []).append(rec["stage"])
    assert stages_by_work[sub.work_id] == ["harvest", "archive"]
    assert stages_by_work[aud.work_id] == ["harvest", "download", "asr", "archive"]
    assert all(rec["outcome"] == "ok" for rec in attempts)
    # artifact paths are relative to archive root
    for rec in attempts:
        for p in rec["artifact_paths"]:
            assert not os.path.isabs(p)


def test_cli_run_rerun_skips_terminal_rows(tmp_root, monkeypatch, capsys):
    sub = page_identity("BVsub", 0, 111, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(sub, title="has-sub"))
    transcribe_calls: list[str] = []
    _stub_asr(monkeypatch, transcribe_calls)
    transport = _mixed_transport()
    _patch_cli(monkeypatch, transport)

    assert main(["run", "--scope", "pending", "--archive-root", tmp_root]) == 0
    capsys.readouterr()
    manifest_path = os.path.join(tmp_root, "manifest", "manifest.jsonl")
    with open(manifest_path, encoding="utf-8") as fh:
        first_manifest = fh.read()
    attempts_path = os.path.join(tmp_root, "coordinator", "attempts.jsonl")
    with open(attempts_path, encoding="utf-8") as fh:
        first_attempts = fh.read()
    first_probe_calls = [c for c in transport.calls if "player/wbi/v2" in c["url"]]

    rc = main(["run", "--scope", "pending", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert "selected 0 row(s)" in captured.out
    with open(manifest_path, encoding="utf-8") as fh:
        assert fh.read() == first_manifest
    with open(attempts_path, encoding="utf-8") as fh:
        assert fh.read() == first_attempts
    probes_now = [c for c in transport.calls if "player/wbi/v2" in c["url"]]
    assert probes_now == first_probe_calls
    assert transcribe_calls == []  # no new work


def test_cli_run_limit_bounds_batch(tmp_root, monkeypatch, capsys):
    a = page_identity("BVA", 0, 111, "p0")
    b = page_identity("BVB", 0, 222, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(a, title="a"))
    store.upsert(_row(b, title="b"))
    _stub_asr(monkeypatch)
    transport = _mixed_transport()
    _patch_cli(monkeypatch, transport)

    rc = main(["run", "--scope", "pending", "--limit", "1",
               "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert "selected 1 row(s)" in captured.out
    probes = [c for c in transport.calls if "player/wbi/v2" in c["url"]]
    assert len(probes) == 1


def test_cli_run_per_item_failure_batch_continues(tmp_root, monkeypatch, capsys):
    from bili_asr.asr import ASRModelError

    a = page_identity("BVAud", 0, 111, "p0")
    b = page_identity("BVBud", 0, 222, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(a, title="a"))
    store.upsert(_row(b, title="b"))

    broken = {artifact_stem(a)}

    def flaky(audio_path, model_name=None):
        if artifact_stem(a) in audio_path:
            raise ASRModelError("model failed")
        return [{"start": 0.0, "end": 1.0, "text": "ok-text"}]

    monkeypatch.setattr(asr_mod, "transcribe", flaky)
    _patch_cli(monkeypatch, _cid_transport(set()))  # no subtitles anywhere

    rc = main(["run", "--scope", "pending", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 1
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[a.work_id]["status"] != "archived"
    assert loaded[b.work_id]["status"] == "archived"

    attempts = AttemptLedger(tmp_root).load()
    outcomes = {(r["work_id"], r["stage"]): r for r in attempts}
    failed_asr = [r for r in attempts
                  if r["stage"] == "asr" and r["outcome"] == "failed"]
    assert len(failed_asr) == 1
    assert failed_asr[0]["work_id"] == a.work_id
    assert failed_asr[0]["error_code"] == "ASRModelError"
    # no raw exception text persisted
    with open(os.path.join(tmp_root, "coordinator", "attempts.jsonl"),
              encoding="utf-8") as fh:
        assert "model failed" not in fh.read()
    del broken, outcomes


def test_cli_run_specific_work_id_scope(tmp_root, monkeypatch, capsys):
    sub = page_identity("BVone", 0, 111, "p0")
    other = page_identity("BVtwo", 0, 222, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(sub, title="one"))
    store.upsert(_row(other, title="two"))
    _stub_asr(monkeypatch)
    transport = _mixed_transport()
    _patch_cli(monkeypatch, transport)

    rc = main(["run", "--scope", sub.work_id, "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[sub.work_id]["status"] == "archived"
    assert loaded[other.work_id]["status"] == "meta_ok"


def test_cli_run_gone_marks_terminal_and_continues(tmp_root, monkeypatch, capsys):
    a = page_identity("BVGone", 0, 111, "p0")
    b = page_identity("BVokX", 0, 222, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(a, title="a"))
    store.upsert(_row(b, title="b"))
    _stub_asr(monkeypatch)

    class GoneForCid(CidRouterTransport):
        """Returns a terminal gone API body for one cid (risk-classified)."""

        def __init__(self, gone_cid, sub_cids, **kwargs):
            super().__init__(sub_cids, **kwargs)
            self.gone_cid = gone_cid

        def get_json(self, url, params=None, **kwargs):
            if "player/wbi/v2" in url:
                cid = dict(params or {}).get("cid")
                if cid == self.gone_cid:
                    return (200, {"code": -404, "data": {}})
            return super().get_json(url, params=params, **kwargs)

    transport = GoneForCid(
        a.cid, {b.cid},
        routes={
            "finger/spi": [SPI_OK],
            "nav": [nav_ok(), nav_response()],
            "aisubtitle.hdslb.com": [(200, dict(SAMPLE_DOC))],
            "playurl": [playurl_ok()],
        },
        stream_routes={f"{STREAM_HOST}/a30216.m4s": AUDIO_BYTES},
    )
    _patch_cli(monkeypatch, transport)

    rc = main(["run", "--scope", "pending", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 1
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[a.work_id]["status"] == "gone"
    assert loaded[b.work_id]["status"] == "archived"


def test_cli_run_offline_flag_skips_http_stages(tmp_root, monkeypatch, capsys):
    # offline semantics are Task 2; Task 1 only guarantees harvest/download
    # are never called (no HTTP at all in this run).
    sub = page_identity("BVsub", 0, 111, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(sub, title="has-sub"))
    _stub_asr(monkeypatch)
    transport = _mixed_transport()
    _patch_cli(monkeypatch, transport)

    rc = main(["run", "--scope", "pending", "--offline",
               "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert transport.calls == []  # no HTTP issued
    attempts = AttemptLedger(tmp_root).load()
    assert [(r["stage"], r["outcome"], r["error_code"]) for r in attempts] == [
        ("harvest", "skipped", "offline"),
    ]


def test_cli_run_appends_run_ledger_record(tmp_root, monkeypatch, capsys):
    from bili_asr.run_ledger import RunLedger

    sub = page_identity("BVsub", 0, 111, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(sub, title="has-sub"))
    _stub_asr(monkeypatch)
    _patch_cli(monkeypatch, _mixed_transport())

    rc = main(["run", "--scope", "pending", "--archive-root", tmp_root])
    assert rc == 0
    records = RunLedger(root=tmp_root).load()
    run_records = [r for r in records if r.get("command") == "run"]
    assert len(run_records) == 1
    assert run_records[0]["exit_code"] == 0
    assert sub.work_id in (run_records[0].get("work_ids") or [])
