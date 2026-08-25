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
    failed_asr = [r for r in attempts
                  if r["stage"] == "asr" and r["outcome"] == "failed"]
    assert len(failed_asr) == 1
    assert failed_asr[0]["work_id"] == a.work_id
    assert failed_asr[0]["error_code"] == "ASRModelError"
    # no raw exception text persisted
    with open(os.path.join(tmp_root, "coordinator", "attempts.jsonl"),
              encoding="utf-8") as fh:
        assert "model failed" not in fh.read()
    # per-run failure summary names the failed row and its redacted code (M1:
    # the code appears once, not duplicated)
    assert f"{a.work_id}: failed (ASRModelError)" in captured.err


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
    # offline with nothing on disk: no HTTP at all, row skipped with reason
    sub = page_identity("BVsub", 0, 111, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(sub, title="has-sub"))
    _stub_asr(monkeypatch)
    transport = _mixed_transport()
    _patch_cli(monkeypatch, transport)

    rc = main(["run", "--scope", "pending", "--offline",
               "--archive-root", tmp_root])
    captured = capsys.readouterr()
    # missing on-disk input -> scope not fully processed -> exit 1
    assert rc == 1
    assert transport.calls == []  # no HTTP issued
    attempts = AttemptLedger(tmp_root).load()
    assert [(r["stage"], r["outcome"], r["error_code"]) for r in attempts] == [
        ("harvest", "skipped", "offline"),
    ]
    assert f"{sub.work_id}: skipped (offline)" in captured.out


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


# ------------------------------------------------------------ offline (Task 2)


def test_run_offline_reprocesses_subtitle_raw_on_disk(
    tmp_root, monkeypatch, capsys
):
    sub = page_identity("BVoffSub", 0, 111, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(sub, status="subtitle_done", title="on-disk-raw"))
    stem = artifact_stem(sub)
    raw_dir = os.path.join(tmp_root, "subtitles", "raw")
    os.makedirs(raw_dir)
    with open(os.path.join(raw_dir, f"{stem}.json"), "w",
              encoding="utf-8") as fh:
        json.dump(SAMPLE_DOC, fh)
    transport = _mixed_transport()
    _patch_cli(monkeypatch, transport)

    rc = main(["run", "--scope", "pending", "--offline",
               "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert transport.calls == []  # proven network-free
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[sub.work_id]["status"] == "archived"
    attempts = AttemptLedger(tmp_root).load()
    assert [(r["stage"], r["outcome"]) for r in attempts] == [
        ("archive", "ok"),
    ]


def test_run_offline_reprocesses_audio_on_disk(tmp_root, monkeypatch, capsys):
    aud = page_identity("BVoffAud", 0, 222, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(aud, status="audio_ok", title="on-disk-audio"))
    audio_dir = os.path.join(tmp_root, "audio")
    os.makedirs(audio_dir)
    with open(os.path.join(audio_dir, f"{artifact_stem(aud)}.m4a"),
              "wb") as fh:
        fh.write(b"\x00" * 16)
    transcribe_calls: list[str] = []
    _stub_asr(monkeypatch, transcribe_calls)
    transport = _mixed_transport()
    _patch_cli(monkeypatch, transport)

    rc = main(["run", "--scope", "pending", "--offline",
               "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert transport.calls == []  # proven network-free
    assert len(transcribe_calls) == 1
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[aud.work_id]["status"] == "archived"
    attempts = AttemptLedger(tmp_root).load()
    assert [(r["stage"], r["outcome"]) for r in attempts] == [
        ("asr", "ok"), ("archive", "ok"),
    ]


def test_run_offline_missing_input_skipped_with_reason_zero_http(
    tmp_root, monkeypatch, capsys
):
    # subtitle_done row whose raw JSON vanished + audio_ok row whose audio
    # vanished: both skipped with reason, no HTTP, nonzero exit (scope not
    # fully processed).
    sub = page_identity("BVmissSub", 0, 111, "p0")
    aud = page_identity("BVmissAud", 0, 222, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(sub, status="subtitle_done", title="no-raw"))
    store.upsert(_row(aud, status="audio_ok", title="no-audio"))
    transcribe_calls: list[str] = []
    _stub_asr(monkeypatch, transcribe_calls)
    transport = _mixed_transport()
    _patch_cli(monkeypatch, transport)

    rc = main(["run", "--scope", "pending", "--offline",
               "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 1
    assert transport.calls == []
    assert transcribe_calls == []
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[sub.work_id]["status"] == "subtitle_done"
    assert loaded[aud.work_id]["status"] == "audio_ok"
    attempts = AttemptLedger(tmp_root).load()
    skipped = {(r["work_id"], r["error_code"]) for r in attempts}
    assert (sub.work_id, "missing_subtitle_raw") in skipped
    assert (aud.work_id, "missing_audio") in skipped
    # operator surfaces the skip reasons
    assert "skipped (missing_subtitle_raw)" in captured.out
    assert "skipped (missing_audio)" in captured.out
    assert "scope not fully processed" in captured.out


def test_run_failure_summary_and_exit_when_scope_not_processed(
    tmp_root, monkeypatch, capsys
):
    from bili_asr.asr import ASRModelError

    a = page_identity("BVsumFail", 0, 111, "p0")
    b = page_identity("BVmissOk", 0, 222, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(a, status="audio_ok", title="fails"))
    store.upsert(_row(b, status="audio_ok", title="ok"))
    audio_dir = os.path.join(tmp_root, "audio")
    os.makedirs(audio_dir)
    for ident in (a, b):
        with open(os.path.join(audio_dir, f"{artifact_stem(ident)}.m4a"),
                  "wb") as fh:
            fh.write(b"\x00" * 16)

    def flaky(audio_path, model_name=None):
        if artifact_stem(a) in audio_path:
            raise ASRModelError("boom")
        return [{"start": 0.0, "end": 1.0, "text": "ok"}]

    monkeypatch.setattr(asr_mod, "transcribe", flaky)
    transport = _mixed_transport()
    _patch_cli(monkeypatch, transport)

    rc = main(["run", "--scope", "pending", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    # live mode (no --offline): no HTTP routes hit because audio exists,
    # batch continues past the per-item failure
    assert rc == 1
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[a.work_id]["status"] != "archived"
    assert loaded[b.work_id]["status"] == "archived"
    # failure summary surface: failed row named once with redacted code
    assert captured.err.count(f"{a.work_id}: failed (ASRModelError)") == 1
    assert "1 completed" in captured.out and "1 failed" in captured.out
    assert "scope not fully processed" in captured.out


def test_run_scope_resolution_error_exits_1_before_batch(
    tmp_root, monkeypatch, capsys
):
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(page_identity("BVreal", 0, 111, "p0"), title="r"))
    _stub_asr(monkeypatch)
    transport = _mixed_transport()
    _patch_cli(monkeypatch, transport)

    rc = main(["run", "--scope", "BVnope", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 1
    assert "BVnope" in captured.err
    assert transport.calls == []  # nothing executed
    assert "selected" not in captured.out  # no batch output at all


# ------------------------------------------------------------ QC fix round


def test_run_download_failure_recorded_and_reselected_by_failed_scope(
    tmp_root, monkeypatch, capsys
):
    # W1/F-001: a download-stage failure must leave a ("download",
    # "failed") attempt record and the row must be re-selectable via
    # `--scope failed`.
    aud = page_identity("BVdlFail", 0, 222, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(aud, status="needs_audio", title="dl-fails"))
    _stub_asr(monkeypatch)

    def boom(client, identity, out_path, store=None):
        raise bc.StreamDownloadError("cdn exploded")

    monkeypatch.setattr("bili_asr.audio.download_audio", boom)
    transport = _mixed_transport()
    _patch_cli(monkeypatch, transport)

    rc = main(["run", "--scope", "pending", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 1
    attempts = AttemptLedger(tmp_root).load()
    assert [(r["stage"], r["outcome"]) for r in attempts] == [
        ("download", "failed"),
    ]
    assert attempts[0]["error_code"] == "StreamDownloadError"
    with open(os.path.join(tmp_root, "coordinator", "attempts.jsonl"),
              encoding="utf-8") as fh:
        assert "cdn exploded" not in fh.read()
    assert f"{aud.work_id}: failed (StreamDownloadError)" in captured.err

    # the failed row is re-selected by --scope failed
    rc2 = main(["run", "--scope", "failed", "--archive-root", tmp_root])
    captured2 = capsys.readouterr()
    assert rc2 == 1
    assert "selected 1 row(s)" in captured2.out
    assert f"{aud.work_id}: needs_audio" in captured2.out


def test_run_offline_archive_write_failure_recorded(
    tmp_root, monkeypatch, capsys
):
    # W1/F-001: archive-stage write failure leaves an ("archive",
    # "failed") record (subtitle path).
    from bili_asr import archive as archive_mod

    sub = page_identity("BVarchF", 0, 111, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(sub, status="subtitle_done", title="raw-exists"))
    stem = artifact_stem(sub)
    raw_dir = os.path.join(tmp_root, "subtitles", "raw")
    os.makedirs(raw_dir)
    with open(os.path.join(raw_dir, f"{stem}.json"), "w",
              encoding="utf-8") as fh:
        json.dump(SAMPLE_DOC, fh)

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(archive_mod, "write_archive", boom)
    transport = _mixed_transport()
    _patch_cli(monkeypatch, transport)

    rc = main(["run", "--scope", "pending", "--offline",
               "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 1
    attempts = AttemptLedger(tmp_root).load()
    assert [(r["stage"], r["outcome"]) for r in attempts] == [
        ("archive", "failed"),
    ]
    assert attempts[0]["error_code"] == "OSError"
    assert f"{sub.work_id}: failed (OSError)" in captured.err


def test_run_offline_asr_path_archive_write_failure_recorded(
    tmp_root, monkeypatch, capsys
):
    # W1/F-001: archive-stage write failure on the asr path (audio on
    # disk, transcribe ok, write_archive raises).
    from bili_asr import archive as archive_mod

    aud = page_identity("BVarchA", 0, 222, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(aud, status="audio_ok", title="audio-exists"))
    audio_dir = os.path.join(tmp_root, "audio")
    os.makedirs(audio_dir)
    with open(os.path.join(audio_dir, f"{artifact_stem(aud)}.m4a"),
              "wb") as fh:
        fh.write(b"\x00" * 16)
    _stub_asr(monkeypatch)

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(archive_mod, "write_archive", boom)
    transport = _mixed_transport()
    _patch_cli(monkeypatch, transport)

    rc = main(["run", "--scope", "pending", "--offline",
               "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 1
    attempts = AttemptLedger(tmp_root).load()
    assert [(r["stage"], r["outcome"]) for r in attempts] == [
        ("asr", "ok"), ("archive", "failed"),
    ]
    assert f"{aud.work_id}: failed (OSError)" in captured.err


def test_run_explicit_scope_rerun_of_terminal_row_is_idempotent_zero(
    tmp_root, monkeypatch, capsys
):
    # F-002: rerunning an already-archived row by explicit work_id exits
    # 0 and leaves manifest/attempts byte-identical.
    sub = page_identity("BVterm", 0, 111, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(sub, status="subtitle_done", title="raw"))
    stem = artifact_stem(sub)
    raw_dir = os.path.join(tmp_root, "subtitles", "raw")
    os.makedirs(raw_dir)
    with open(os.path.join(raw_dir, f"{stem}.json"), "w",
              encoding="utf-8") as fh:
        json.dump(SAMPLE_DOC, fh)
    transport = _mixed_transport()
    _patch_cli(monkeypatch, transport)

    assert main(["run", "--scope", "pending", "--offline",
                 "--archive-root", tmp_root]) == 0
    capsys.readouterr()
    manifest_path = os.path.join(tmp_root, "manifest", "manifest.jsonl")
    attempts_path = os.path.join(tmp_root, "coordinator", "attempts.jsonl")
    with open(manifest_path, encoding="utf-8") as fh:
        first_manifest = fh.read()
    with open(attempts_path, encoding="utf-8") as fh:
        first_attempts = fh.read()

    rc = main(["run", "--scope", sub.work_id, "--offline",
               "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert "selected 1 row(s)" in captured.out
    assert f"{sub.work_id}: skipped (already_terminal)" in captured.out
    assert "scope not fully processed" not in captured.out
    with open(manifest_path, encoding="utf-8") as fh:
        assert fh.read() == first_manifest
    with open(attempts_path, encoding="utf-8") as fh:
        assert fh.read() == first_attempts


def test_run_non_positive_limit_is_usage_error(
    tmp_root, monkeypatch, capsys
):
    # qc1-S3 / qc3-S3: --limit 0 must not silently select zero rows.
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(page_identity("BVlim", 0, 111, "p0"), title="l"))
    _stub_asr(monkeypatch)
    transport = _mixed_transport()
    _patch_cli(monkeypatch, transport)

    rc = main(["run", "--scope", "pending", "--limit", "0",
               "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 1
    assert "--limit must be a positive integer" in captured.err
    assert transport.calls == []
    assert "selected" not in captured.out


def test_safe_error_code_sanitizes_forbidden_markers(tmp_root):
    # qc3-S2: a hostile .code string carrying forbidden markers must be
    # sanitized so _record never throws and never masks the stage error.
    from bili_asr.coordinator import _safe_error_code

    class HostileCode(Exception):
        code = "https://evil.example/SESSDATA=abc"

    sanitized = _safe_error_code(HostileCode("boom"))
    assert sanitized == "evil.example/=abc"
    assert "http" not in sanitized and "SESSDATA" not in sanitized

    store = ManifestStore(root=tmp_root)
    store.upsert(_row(page_identity("BVsane", 0, 111, "p0")))
    coord = RunCoordinator(tmp_root, store)
    stored = coord._record("harvest", "BVsane:p0", "failed",
                           error_code=sanitized)
    assert stored["error_code"] == "evil.example/=abc"
