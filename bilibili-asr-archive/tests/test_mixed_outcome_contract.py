"""Characterization tests for the mixed per-item outcome / exit contract.

Fake transport + stubbed ASR only. Assertions encode the locked taxonomy
(exit 0 fully processed / already terminal; exit 1 incomplete per-item work;
exit 2 risk interruption with durable successes). Pre-fix mismatches must
fail loudly rather than be weakened.
"""

from __future__ import annotations

import json
import os

from bili_asr import asr as asr_mod
from bili_asr import bili_client as bc
from bili_asr.cli import main
from bili_asr.coordinator import AttemptLedger, RowResult, RunSummary
from bili_asr.manifest import ManifestStore
from bili_asr.page_identity import artifact_stem, page_identity
from bili_asr.run_ledger import LEDGER_FILENAME, RunLedger

from test_audio import (
    AUDIO_BYTES,
    SPI_OK,
    STREAM_HOST,
    RouterTransport,
    nav_response,
    playurl_ok,
)
from test_subtitles import SAMPLE_DOC, nav_ok, player_ok, sub_entry

SECRET = "SECRET-SESS"
API_FAIL = (200, {"code": -400})
RISK = (412, {"code": -412, "message": "request too frequent"})


def _audio_target(path: str) -> str:
    try:
        return os.readlink(path)
    except OSError:
        return path


def _row(identity, *, status="meta_ok", duration_s=5, title="clip", **extra):
    row = {
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
    row.update(extra)
    return row


def _patch_cli(monkeypatch, transport):
    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
    monkeypatch.setattr(bc, "default_sleeper", lambda: (lambda _s: None))
    monkeypatch.setattr("bili_asr.cli.time.sleep", lambda _s: None)


def _stub_asr(monkeypatch, impl=None):
    def fake_transcribe(audio_path, model_name=None):
        if impl is not None:
            return impl(_audio_target(audio_path))
        return [{"start": 0.0, "end": 1.0, "text": "asr-text"}]

    monkeypatch.setattr(asr_mod, "transcribe", fake_transcribe)


# Redacted-scalar lock. Markers are fragments, not live credentials or
# full signed URLs / exception dumps. Exception *type names* (e.g.
# ASRModelError) are the documented scalar codes and are allowed.
# Archive markdown may include the public video URL (bilibili.com/video/...).
_NO_SECRET_MARKERS = (
    SECRET,
    "SESSDATA",
    "Traceback",
    "upos-sz-",
    "bilivideo.com",
    "deadline=",
    "model failed",
    "FunASR support is not installed",
)


def _assert_no_secrets(captured, root, extra_forbidden=()):
    forbidden = _NO_SECRET_MARKERS + tuple(extra_forbidden)
    blob = captured.out + captured.err
    for marker in forbidden:
        assert marker not in blob
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if not name.endswith((".jsonl", ".json", ".md", ".txt", ".srt")):
                continue
            text = open(os.path.join(dirpath, name), encoding="utf-8").read()
            for marker in forbidden:
                assert marker not in text


def _write_subtitle_raw(root, identity):
    path = os.path.join(root, "subtitles", "raw", f"{artifact_stem(identity)}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(SAMPLE_DOC, fh)


def _write_audio(root, identity):
    path = os.path.join(root, "audio", f"{artifact_stem(identity)}.m4a")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"\x00" * 16)
    return path


def _ledger_records(root):
    path = os.path.join(root, LEDGER_FILENAME)
    if not os.path.isfile(path):
        return []
    return RunLedger(root=root).load()


class CidRouterTransport(RouterTransport):
    """Route player/playurl by cid so mixed batches stay deterministic."""

    def __init__(self, player_by_cid, playurl_by_cid=None, routes=None,
                 stream_routes=None):
        routes = dict(routes or {})
        routes.pop("player/wbi/v2", None)
        routes.pop("playurl", None)
        super().__init__(routes, stream_routes)
        self.player_by_cid = dict(player_by_cid)
        self.playurl_by_cid = dict(playurl_by_cid or {})

    def get_json(self, url, params=None, headers=None, cookies=None, timeout=None):
        self.calls.append({
            "url": url,
            "params": dict(params or {}),
            "headers": dict(headers or {}),
            "cookies": dict(cookies or {}),
        })
        cid = dict(params or {}).get("cid")
        if "player/wbi/v2" in url:
            if cid not in self.player_by_cid:
                raise AssertionError(f"no player route for cid={cid}")
            return self.player_by_cid[cid]
        if "/x/player/wbi/playurl" in url:
            if cid not in self.playurl_by_cid:
                raise AssertionError(f"no playurl route for cid={cid}")
            return self.playurl_by_cid[cid]
        # Replay the parent matcher without double-recording the call.
        self.calls.pop()
        return super().get_json(url, params=params, headers=headers,
                                cookies=cookies, timeout=timeout)


def _base_routes():
    return {
        "finger/spi": [SPI_OK] * 16,
        "nav": [nav_ok(), nav_response()],
        "aisubtitle.hdslb.com": [(200, dict(SAMPLE_DOC))],
    }


# ------------------------------------------------------------ aggregation unit

def test_run_summary_locks_terminal_selectors_and_risk_precedence():
    ok = RowResult("ok:p0", "archived", ok=True)
    failed = RowResult("fail:p0", "audio_ok", failure_codes=[-400])
    skip_budget = RowResult(
        "skip:p0", "needs_audio", skipped=True, skip_reason="audio_budget",
    )
    skip_offline = RowResult(
        "off:p0", "meta_ok", skipped=True, skip_reason="offline",
    )
    skip_terminal = RowResult(
        "term:p0", "archived", skipped=True, skip_reason="already_terminal",
    )

    mixed_fail = RunSummary(results=[ok, failed])
    assert mixed_fail.ok_count == 1
    assert [r.work_id for r in mixed_fail.failed] == ["fail:p0"]
    assert mixed_fail.fully_processed is False

    mixed_skip = RunSummary(results=[ok, skip_budget])
    assert mixed_skip.fully_processed is False
    mixed_offline = RunSummary(results=[ok, skip_offline])
    assert mixed_offline.fully_processed is False

    terminal_only = RunSummary(results=[ok, skip_terminal])
    assert terminal_only.fully_processed is True
    assert RunSummary().fully_processed is True

    # Isolate risk: a successful-only batch is still incomplete when
    # risk_interrupted is set. Mixing in `failed` would already force False.
    risk_only = RunSummary(results=[ok], risk_interrupted=True)
    assert risk_only.ok_count == 1
    assert risk_only.failed == []
    assert risk_only.fully_processed is False
    risk_after_fail = RunSummary(results=[ok, failed], risk_interrupted=True)
    assert risk_after_fail.fully_processed is False


# ------------------------------------------------------------ download-audio

def test_download_audio_mixed_success_and_api_failure_is_retryable(
    tmp_root, monkeypatch, capsys,
):
    ok_id = page_identity("BVdOk", 0, 111, "p0")
    fail_id = page_identity("BVdFail", 0, 222, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(fail_id, status="needs_audio"))
    store.upsert(_row(ok_id, status="needs_audio"))
    transport = CidRouterTransport(
        {},
        playurl_by_cid={fail_id.cid: API_FAIL, ok_id.cid: playurl_ok()},
        routes=_base_routes(),
        stream_routes={f"{STREAM_HOST}/a30216.m4s": AUDIO_BYTES},
    )
    _patch_cli(monkeypatch, transport)

    rc = main([
        "download-audio", "--missing-subs", "--archive-root", tmp_root,
        "--sessdata", SECRET,
    ])
    captured = capsys.readouterr()
    assert rc == 1
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[ok_id.work_id]["status"] == "audio_ok"
    audio_abs = os.path.join(tmp_root, loaded[ok_id.work_id]["audio_path"])
    assert os.path.isfile(audio_abs)
    assert loaded[fail_id.work_id]["status"] == "needs_audio"
    assert loaded[fail_id.work_id]["last_api_error_code"] == -400
    assert _ledger_records(tmp_root) == []
    _assert_no_secrets(captured, tmp_root)

    rc = main(["download-audio", "--missing-subs", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 1
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[ok_id.work_id]["status"] == "audio_ok"
    assert loaded[fail_id.work_id]["status"] == "needs_audio"


def test_download_audio_success_then_risk_exit_2_keeps_success(
    tmp_root, monkeypatch, capsys,
):
    # download-audio walks ManifestStore insertion order (JSONL). work_id
    # names also keep success first if todo is later sorted by work_id.
    ok_id = page_identity("BVdAOk", 0, 111, "p0")
    risk_id = page_identity("BVdZRisk", 0, 222, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(ok_id, status="needs_audio"))
    store.upsert(_row(risk_id, status="needs_audio"))
    transport = CidRouterTransport(
        {},
        playurl_by_cid={ok_id.cid: playurl_ok(), risk_id.cid: RISK},
        routes=_base_routes(),
        stream_routes={f"{STREAM_HOST}/a30216.m4s": AUDIO_BYTES},
    )
    _patch_cli(monkeypatch, transport)

    rc = main(["download-audio", "--missing-subs", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 2
    assert "download-audio:" in captured.out
    assert "1 audio_ok" in captured.out
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[ok_id.work_id]["status"] == "audio_ok"
    assert loaded[risk_id.work_id]["status"] == "needs_audio"
    _assert_no_secrets(captured, tmp_root)


# ------------------------------------------------------------ asr

def test_asr_mixed_success_and_per_item_failure_exits_1(
    tmp_root, monkeypatch, capsys,
):
    ok_id = page_identity("BVaOk", 0, 111, "p0")
    fail_id = page_identity("BVaFail", 0, 222, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(ok_id, status="subtitle_done"))
    store.upsert(_row(
        fail_id, status="audio_ok",
        audio_path=f"audio/{artifact_stem(fail_id)}.m4a",
    ))
    _write_subtitle_raw(tmp_root, ok_id)
    _write_audio(tmp_root, fail_id)

    transcribe_calls: list[str] = []

    def flaky(audio_path):
        transcribe_calls.append(_audio_target(audio_path))
        raise asr_mod.ASRModelError("model failed")

    _stub_asr(monkeypatch, flaky)
    _patch_cli(monkeypatch, RouterTransport({}))

    rc = main(["asr", "--pending", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    # Incomplete requested work is exit 1 even when another row archived.
    assert rc == 1
    assert "1 archived" in captured.out
    assert "1 failed" in captured.out
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[ok_id.work_id]["status"] == "archived"
    assert os.path.isfile(os.path.join(tmp_root, loaded[ok_id.work_id]["srt_path"]))
    assert loaded[fail_id.work_id]["status"] == "audio_ok"
    assert _ledger_records(tmp_root) == []
    assert not os.path.exists(os.path.join(tmp_root, "coordinator", "attempts.jsonl"))
    assert len(transcribe_calls) == 1
    assert artifact_stem(fail_id) in transcribe_calls[0]
    _assert_no_secrets(captured, tmp_root)

    rc = main(["asr", "--pending", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 1
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[ok_id.work_id]["status"] == "archived"
    assert loaded[fail_id.work_id]["status"] == "audio_ok"
    assert len(transcribe_calls) == 2
    assert artifact_stem(fail_id) in transcribe_calls[-1]
    assert _ledger_records(tmp_root) == []
    assert not os.path.exists(os.path.join(tmp_root, "coordinator", "attempts.jsonl"))
    _assert_no_secrets(captured, tmp_root)


def test_asr_pending_ignores_already_terminal_rows(
    tmp_root, monkeypatch, capsys,
):
    archived = page_identity("BVaArch", 0, 111, "p0")
    gone = page_identity("BVaGone", 0, 222, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(archived, status="archived", srt_path="transcripts/srt/x.srt"))
    store.upsert(_row(gone, status="gone"))
    transcribe_calls: list[str] = []

    def unexpected(audio_path):
        transcribe_calls.append(_audio_target(audio_path))
        raise AssertionError("asr --pending must ignore archived/gone")

    _stub_asr(monkeypatch, unexpected)
    _patch_cli(monkeypatch, RouterTransport({}))
    manifest_path = os.path.join(tmp_root, "manifest", "manifest.jsonl")
    with open(manifest_path, encoding="utf-8") as fh:
        before = fh.read()

    rc = main(["asr", "--pending", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 0
    assert transcribe_calls == []
    with open(manifest_path, encoding="utf-8") as fh:
        assert fh.read() == before
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[archived.work_id]["status"] == "archived"
    assert loaded[gone.work_id]["status"] == "gone"
    assert _ledger_records(tmp_root) == []
    _assert_no_secrets(captured, tmp_root)


def test_asr_optional_dependency_after_success_exits_1(
    tmp_root, monkeypatch, capsys,
):
    # Insertion order = work_id order: subtitle success, audio missing-ASR,
    # later subtitle_done. Missing optional ASR must not starve later rows.
    ok_id = page_identity("BVaDepOk", 0, 111, "p0")
    miss_id = page_identity("BVbDepMiss", 0, 222, "p0")
    later_id = page_identity("BVzDepLater", 0, 333, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(ok_id, status="subtitle_done"))
    store.upsert(_row(
        miss_id, status="audio_ok",
        audio_path=f"audio/{artifact_stem(miss_id)}.m4a",
    ))
    store.upsert(_row(later_id, status="subtitle_done"))
    _write_subtitle_raw(tmp_root, ok_id)
    _write_audio(tmp_root, miss_id)
    _write_subtitle_raw(tmp_root, later_id)

    transcribe_calls: list[str] = []

    def missing(audio_path):
        transcribe_calls.append(_audio_target(audio_path))
        raise asr_mod.ASRDependencyError("FunASR support is not installed")

    _stub_asr(monkeypatch, missing)
    _patch_cli(monkeypatch, RouterTransport({}))

    rc = main(["asr", "--pending", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 1
    assert "ASR dependency unavailable" in captured.err
    assert "2 archived" in captured.out
    assert "1 failed" in captured.out
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[ok_id.work_id]["status"] == "archived"
    assert loaded[miss_id.work_id]["status"] == "audio_ok"
    assert loaded[later_id.work_id]["status"] == "archived"
    assert len(transcribe_calls) == 1
    assert artifact_stem(miss_id) in transcribe_calls[0]
    assert _ledger_records(tmp_root) == []
    _assert_no_secrets(captured, tmp_root)


def test_asr_subtitle_done_missing_raw_is_incomplete_skip(
    tmp_root, monkeypatch, capsys,
):
    miss_id = page_identity("BVaRawMiss", 0, 111, "p0")
    ok_id = page_identity("BVzRawOk", 0, 222, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(miss_id, status="subtitle_done"))
    store.upsert(_row(ok_id, status="subtitle_done"))
    _write_subtitle_raw(tmp_root, ok_id)

    transcribe_calls: list[str] = []

    def unexpected(audio_path):
        transcribe_calls.append(_audio_target(audio_path))
        raise AssertionError("subtitle_done without raw must not invoke ASR")

    _stub_asr(monkeypatch, unexpected)
    _patch_cli(monkeypatch, RouterTransport({}))

    rc = main(["asr", "--pending", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 1
    assert "missing_subtitle_raw" in captured.err
    assert "1 archived" in captured.out
    assert "1 failed" in captured.out
    assert transcribe_calls == []
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[miss_id.work_id]["status"] == "subtitle_done"
    assert loaded[ok_id.work_id]["status"] == "archived"
    assert _ledger_records(tmp_root) == []
    _assert_no_secrets(captured, tmp_root)


# ------------------------------------------------------------ pilot

def test_pilot_mixed_success_and_api_failure_records_ledger(
    tmp_root, monkeypatch, capsys,
):
    ok_id = page_identity("BVpOk", 0, 111, "p0")
    fail_id = page_identity("BVpFail", 0, 222, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(ok_id, duration_s=5, title="has-sub"))
    store.upsert(_row(fail_id, duration_s=8, title="api-fail"))
    _stub_asr(monkeypatch)
    transport = CidRouterTransport(
        {ok_id.cid: player_ok([sub_entry()]), fail_id.cid: API_FAIL},
        routes=_base_routes(),
    )
    _patch_cli(monkeypatch, transport)

    rc = main([
        "pilot", "--n", "2", "--archive-root", tmp_root, "--sessdata", SECRET,
    ])
    captured = capsys.readouterr()
    assert rc == 1
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[ok_id.work_id]["status"] == "archived"
    assert loaded[fail_id.work_id]["status"] == "meta_ok"
    assert loaded[fail_id.work_id]["last_api_error_code"] == -400
    recs = _ledger_records(tmp_root)
    assert len(recs) == 1
    assert recs[0]["command"] == "pilot"
    assert recs[0]["exit_code"] == 1
    _assert_no_secrets(captured, tmp_root)

    rc = main(["pilot", "--n", "2", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 1
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[ok_id.work_id]["status"] == "archived"
    assert loaded[fail_id.work_id]["status"] == "meta_ok"


def test_pilot_success_then_risk_exit_2_keeps_success(
    tmp_root, monkeypatch, capsys,
):
    # pilot walks the selected list in insertion/select order. work_id
    # names also keep success first if selection is later sorted by work_id.
    ok_id = page_identity("BVpAOk", 0, 111, "p0")
    risk_id = page_identity("BVpZRisk", 0, 222, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(ok_id, duration_s=5))
    store.upsert(_row(risk_id, duration_s=8))
    _stub_asr(monkeypatch)
    transport = CidRouterTransport(
        {ok_id.cid: player_ok([sub_entry()]), risk_id.cid: RISK},
        routes=_base_routes(),
    )
    _patch_cli(monkeypatch, transport)

    rc = main(["pilot", "--n", "2", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 2
    assert "pilot batch branches:" in captured.out
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[ok_id.work_id]["status"] == "archived"
    assert loaded[risk_id.work_id]["status"] == "meta_ok"
    recs = _ledger_records(tmp_root)
    assert recs[-1]["exit_code"] == 2
    _assert_no_secrets(captured, tmp_root)


def test_pilot_mixed_success_and_audio_budget_skip_exits_1(
    tmp_root, monkeypatch, capsys,
):
    ok_id = page_identity("BVpSub", 0, 111, "p0")
    skip_id = page_identity("BVpAud", 0, 222, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(ok_id, status="subtitle_done", duration_s=5))
    store.upsert(_row(skip_id, status="needs_audio", duration_s=600))
    _write_subtitle_raw(tmp_root, ok_id)
    audio_dir = os.path.join(tmp_root, "audio")
    os.makedirs(audio_dir)
    with open(os.path.join(audio_dir, "fill.m4a"), "wb") as fh:
        fh.write(b"x" * 600_000)
    _stub_asr(monkeypatch)
    _patch_cli(monkeypatch, RouterTransport(_base_routes()))

    rc = main([
        "pilot", "--n", "2", "--archive-root", tmp_root,
        "--max-audio-gb", "0.001",
    ])
    captured = capsys.readouterr()
    assert rc == 1
    assert "audio_budget" in captured.err
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[ok_id.work_id]["status"] == "archived"
    assert loaded[skip_id.work_id]["status"] == "needs_audio"


# ------------------------------------------------------------ run

def test_run_mixed_failure_keeps_success_and_failed_scope_retries(
    tmp_root, monkeypatch, capsys,
):
    ok_id = page_identity("BVrOk", 0, 111, "p0")
    fail_id = page_identity("BVrFail", 0, 222, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(ok_id, status="subtitle_done"))
    store.upsert(_row(
        fail_id, status="audio_ok",
        audio_path=f"audio/{artifact_stem(fail_id)}.m4a",
    ))
    _write_subtitle_raw(tmp_root, ok_id)
    _write_audio(tmp_root, fail_id)

    def flaky(audio_path, model_name=None):
        if artifact_stem(fail_id) in _audio_target(audio_path):
            raise asr_mod.ASRModelError("model failed")
        return [{"start": 0.0, "end": 1.0, "text": "ok"}]

    monkeypatch.setattr(asr_mod, "transcribe", flaky)
    _patch_cli(monkeypatch, RouterTransport(_base_routes()))

    rc = main(["run", "--scope", "pending", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 1
    assert "scope not fully processed" in captured.out
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[ok_id.work_id]["status"] == "archived"
    assert loaded[fail_id.work_id]["status"] == "audio_ok"
    recs = _ledger_records(tmp_root)
    assert recs[-1]["command"] == "run"
    assert recs[-1]["exit_code"] == 1
    attempts = AttemptLedger(tmp_root).load()
    assert any(
        r["work_id"] == fail_id.work_id and r["outcome"] == "failed"
        for r in attempts
    )
    _assert_no_secrets(captured, tmp_root)

    rc = main(["run", "--scope", "failed", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 1
    assert f"selected 1 row(s)" in captured.out
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[ok_id.work_id]["status"] == "archived"
    assert loaded[fail_id.work_id]["status"] == "audio_ok"


def test_run_explicit_terminal_selectors_exit_0_without_duplicating(
    tmp_root, monkeypatch, capsys,
):
    archived = page_identity("BVrArch", 0, 111, "p0")
    gone = page_identity("BVrGone", 0, 222, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(archived, status="archived", srt_path="transcripts/srt/x.srt"))
    store.upsert(_row(gone, status="gone"))
    _stub_asr(monkeypatch)
    transport = RouterTransport(_base_routes())
    _patch_cli(monkeypatch, transport)
    manifest_path = os.path.join(tmp_root, "manifest", "manifest.jsonl")
    with open(manifest_path, encoding="utf-8") as fh:
        before = fh.read()

    rc = main([
        "run", "--scope", f"{archived.work_id},{gone.work_id}",
        "--archive-root", tmp_root,
    ])
    captured = capsys.readouterr()
    assert rc == 0
    assert "already_terminal" in captured.out
    assert "scope not fully processed" not in captured.out
    with open(manifest_path, encoding="utf-8") as fh:
        assert fh.read() == before
    assert transport.calls == []
    recs = _ledger_records(tmp_root)
    assert recs[-1]["exit_code"] == 0


def test_run_risk_after_success_exit_2_precedes_per_item_failure(
    tmp_root, monkeypatch, capsys,
):
    # pending scope iterates sorted work_ids; names keep success first.
    ok_id = page_identity("BVaOk", 0, 111, "p0")
    risk_id = page_identity("BVzRisk", 0, 222, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(ok_id, status="subtitle_done"))
    store.upsert(_row(risk_id, status="meta_ok"))
    _write_subtitle_raw(tmp_root, ok_id)
    _stub_asr(monkeypatch)
    transport = CidRouterTransport(
        {risk_id.cid: RISK},
        routes=_base_routes(),
    )
    _patch_cli(monkeypatch, transport)

    rc = main(["run", "--scope", "pending", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 2
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[ok_id.work_id]["status"] == "archived"
    assert loaded[risk_id.work_id]["status"] == "meta_ok"
    recs = _ledger_records(tmp_root)
    assert recs[-1]["exit_code"] == 2
    assert recs[-1]["coverage_summary"].get("archived") == 1


def test_run_per_item_failure_then_risk_still_exits_2(
    tmp_root, monkeypatch, capsys,
):
    # pending scope iterates sorted work_ids: per-item failure first, then
    # risk. Risk still wins the process exit (2), not the per-item 1.
    fail_id = page_identity("BVaFail", 0, 111, "p0")
    ok_id = page_identity("BVbOk", 0, 222, "p0")
    risk_id = page_identity("BVzRisk", 0, 333, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(
        fail_id, status="audio_ok",
        audio_path=f"audio/{artifact_stem(fail_id)}.m4a",
    ))
    store.upsert(_row(ok_id, status="subtitle_done"))
    store.upsert(_row(risk_id, status="meta_ok"))
    _write_audio(tmp_root, fail_id)
    _write_subtitle_raw(tmp_root, ok_id)

    def flaky(audio_path, model_name=None):
        if artifact_stem(fail_id) in _audio_target(audio_path):
            raise asr_mod.ASRModelError("model failed")
        return [{"start": 0.0, "end": 1.0, "text": "ok"}]

    monkeypatch.setattr(asr_mod, "transcribe", flaky)
    transport = CidRouterTransport(
        {risk_id.cid: RISK},
        routes=_base_routes(),
    )
    _patch_cli(monkeypatch, transport)

    rc = main(["run", "--scope", "pending", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 2
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[fail_id.work_id]["status"] == "audio_ok"
    assert loaded[ok_id.work_id]["status"] == "archived"
    assert loaded[risk_id.work_id]["status"] == "meta_ok"
    recs = _ledger_records(tmp_root)
    assert recs[-1]["exit_code"] == 2
    _assert_no_secrets(captured, tmp_root)


def test_run_offline_skip_does_not_roll_back_success(
    tmp_root, monkeypatch, capsys,
):
    ok_id = page_identity("BVrOffOk", 0, 111, "p0")
    skip_id = page_identity("BVrOffSkip", 0, 222, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(ok_id, status="subtitle_done"))
    store.upsert(_row(skip_id, status="needs_audio"))
    _write_subtitle_raw(tmp_root, ok_id)
    _stub_asr(monkeypatch)
    transport = RouterTransport(_base_routes())
    _patch_cli(monkeypatch, transport)

    rc = main([
        "run", "--scope", "pending", "--offline", "--archive-root", tmp_root,
    ])
    captured = capsys.readouterr()
    assert rc == 1
    assert "skipped (missing_audio)" in captured.out
    assert transport.calls == []
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[ok_id.work_id]["status"] == "archived"
    assert loaded[skip_id.work_id]["status"] == "needs_audio"


# ------------------------------------------------------------ docs lock

def test_readme_documents_mixed_outcome_aggregation_rules():
    readme = os.path.join(os.path.dirname(__file__), "..", "README.md")
    text = open(readme, encoding="utf-8").read()
    assert "### Mixed batch outcomes" in text
    assert "Risk interruption takes precedence" in text
    assert "already terminal" in text
    assert "run --scope failed" in text
    assert "| 0 |" in text
    assert "Requested work processed" in text
    assert "| 1 |" in text
    assert "missing optional ASR" in text
    assert "per-item failure" in text
    assert "| 2 |" in text
    assert "Risk/API terminal interruption" in text
    assert "`archived` / `gone`" in text
