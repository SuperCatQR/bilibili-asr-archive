"""Characterization tests for the mixed per-item outcome / exit contract.

Fake transport + stubbed ASR only. Assertions encode the locked taxonomy
(exit 0 fully processed / already terminal; exit 1 incomplete per-item work;
exit 2 risk interruption with durable successes). Pre-fix mismatches must
fail loudly rather than be weakened.
"""

from __future__ import annotations

import bili_asr.asr.errors as _module_asr_errors


import json
import os
from pathlib import Path

from bili_asr import asr as asr_mod
from bili_asr import bili_client as bc
from bili_asr.cli.main import main
from bili_asr.pipeline.attempts import AttemptLedger
from bili_asr.pipeline.models import RowResult, RunSummary
from bili_asr.manifest import ManifestStore
from bili_asr.page_identity import artifact_stem, page_identity
from bili_asr.run_ledger import LEDGER_FILENAME, RunLedger

from tests.support.audio import (
    AUDIO_BYTES,
    SPI_OK,
    STREAM_HOST,
    RouterTransport,
    nav_response,
    playurl_ok,
)
from tests.support.subtitles import SAMPLE_DOC, nav_ok, player_ok, sub_entry

import tests.support.asr_fakes as asr_fakes
from tests.support.archive_database import _seed_archive_database

SECRET = "SECRET-SESS"
API_FAIL = (200, {"code": -400})
RISK = (412, {"code": -412, "message": "request too frequent"})


def _audio_target(path: str) -> str:
    """Name the audio the model read, from the fixture body that identifies it.

    The runner opens the row's confined audio through a guarded descriptor and
    the ASR boundary hands the model a short-lived *copy*, so the model's own
    path names no durable file.  Every audio fixture here writes its row id
    into the body, which does name it.
    """
    candidates = [path]
    try:
        candidates.append(os.readlink(path))
    except OSError:
        pass
    for candidate in candidates:
        try:
            with open(os.fspath(candidate), "rb") as fh:
                body = fh.read()
        except OSError:
            continue
        if body.startswith(AUDIO_BYTES):
            return body[len(AUDIO_BYTES):].decode("utf-8", "replace")
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


def _manifest_bytes(root: str) -> dict[str, bytes]:
    """Include journal-only manifests when checking for unwanted writes."""
    directory = Path(root) / "manifest"
    return {
        path.name: path.read_bytes()
        for path in directory.glob("*.jsonl")
    }


def _patch_cli(monkeypatch, transport):
    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
    monkeypatch.setattr(bc, "default_sleeper", lambda: (lambda _s: None))
    monkeypatch.setattr('bili_asr.cli.pilot.time.sleep', lambda _s: None)


def _stub_asr(monkeypatch, impl=None):
    """D2.5 seam: the model factory, not the one-shot ``asr.transcribe``.

    The commands characterized here now own one runner per invocation
    (Task 2), so per-item behaviour has to be injected where the runner
    actually builds its model.  ``impl`` keeps its old contract: it receives
    the audio the model would read and may return segments (ignored — the fake
    model returns its own) or raise.
    """
    constructions: list[dict] = []

    def probe(path: str) -> bool:
        """Hand ``impl`` the row's own audio; a raise from it is that row's failure."""

        if impl is not None:
            impl(path)
        return False

    asr_fakes.install(
        monkeypatch, text="asr-text", constructions=constructions, fail_when=probe
    )
    return constructions


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
        # The row id rides in the body so a test can name the audio a model
        # read even after the boundary copied it to a temp file.
        fh.write(AUDIO_BYTES + artifact_stem(identity).encode("utf-8"))
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
        "download-audio", "--missing-subs", "--queue-source", "manifest",
        "--archive-root", tmp_root,
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

    rc = main([
        "download-audio", "--missing-subs", "--queue-source", "manifest",
        "--archive-root", tmp_root,
    ])
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

    rc = main([
        "download-audio", "--missing-subs", "--queue-source", "manifest",
        "--archive-root", tmp_root,
    ])
    captured = capsys.readouterr()
    assert rc == 2
    assert "download-audio:" in captured.out
    assert "1 audio_ok" in captured.out
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[ok_id.work_id]["status"] == "audio_ok"
    assert loaded[risk_id.work_id]["status"] == "needs_audio"
    _assert_no_secrets(captured, tmp_root)


# ------------------------------------------------------------ asr



def test_asr_pending_ignores_already_terminal_rows(
    tmp_root, monkeypatch, capsys,
):
    archived = page_identity("BVaArch", 0, 111, "p0")
    gone = page_identity("BVaGone", 0, 222, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(archived, status="archived", srt_path="transcripts/x/bundle.srt"))
    store.upsert(_row(gone, status="gone"))
    transcribe_calls: list[str] = []

    def unexpected(audio_path):
        transcribe_calls.append(_audio_target(audio_path))
        raise AssertionError("asr --pending must ignore archived/gone")

    _stub_asr(monkeypatch, unexpected)
    _patch_cli(monkeypatch, RouterTransport({}))
    before = _manifest_bytes(tmp_root)
    assert before

    _seed_archive_database(tmp_root)
    rc = main(["asr", "--pending", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 0
    assert transcribe_calls == []
    assert _manifest_bytes(tmp_root) == before
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[archived.work_id]["status"] == "archived"
    assert loaded[gone.work_id]["status"] == "gone"
    assert _ledger_records(tmp_root) == []
    _assert_no_secrets(captured, tmp_root)






# ------------------------------------------------------------ pilot







# ------------------------------------------------------------ run



def test_run_explicit_terminal_selectors_exit_0_without_duplicating(
    tmp_root, monkeypatch, capsys,
):
    archived = page_identity("BVrArch", 0, 111, "p0")
    gone = page_identity("BVrGone", 0, 222, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(archived, status="archived", srt_path="transcripts/x/bundle.srt"))
    store.upsert(_row(gone, status="gone"))
    # Run publishes a final snapshot; start with one to pin its no-op bytes.
    store.save()
    _stub_asr(monkeypatch)
    transport = RouterTransport(_base_routes())
    _patch_cli(monkeypatch, transport)
    before = _manifest_bytes(tmp_root)
    assert before

    rc = main([
        "run", "--scope", f"{archived.work_id},{gone.work_id}",
        "--archive-root", tmp_root,
    ])
    captured = capsys.readouterr()
    assert rc == 0
    assert "already_terminal" in captured.out
    assert "scope not fully processed" not in captured.out
    assert _manifest_bytes(tmp_root) == before
    assert transport.calls == []
    recs = _ledger_records(tmp_root)
    assert recs[-1]["exit_code"] == 0






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

    _seed_archive_database(tmp_root)
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
