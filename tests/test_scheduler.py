"""Bounded sequential scheduler (`bili-asr schedule`).

Fake transport + stubbed ASR only. No live HTTP or model downloads.
Locks explicit scope/limit, terminal-row handling, resume/risk sidecar
semantics, and mixed-outcome exit codes.
"""

from __future__ import annotations

import json
import os

import pytest

from bili_asr import asr as asr_mod
from bili_asr import bili_client as bc
from bili_asr.cli.main import main
from bili_asr.pipeline.attempts import AttemptLedger
from bili_asr.pipeline.models import RowResult
from bili_asr.manifest import ManifestStore
from bili_asr.meta_cursor import MetaCursorStore, utc_now_iso
from bili_asr.page_identity import artifact_stem, page_identity
from bili_asr.run_ledger import LEDGER_FILENAME, RunLedger
from bili_asr.scheduler import (
    SCHEDULER_FILENAME,
    SchedulerStore,
    classify_batch_state,
    settled_processed_ids,
    terminal_resume_ids,
)

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
from tests.support.scheduler import CidRouterTransport, SECRET, _NO_SECRET_MARKERS, _assert_no_secrets, _base_routes, _patch_cli, _row, _scheduler, _stub_asr, _write_subtitle_raw

RISK = (412, {"code": -412, "message": "request too frequent"})



def _audio_target(path: str) -> str:
    """Name the audio the model read, from the fixture body that identifies it.

    The runner hands the model a guarded descriptor, and the ASR boundary
    copies it to a short-lived temp file, so the model's path names no durable
    file.  ``_write_audio`` writes the row id into the body, which does.
    """
    candidates = [path]
    try:
        candidates.append(os.readlink(path))
    except OSError:
        pass
    for candidate in candidates:
        try:
            with open(candidate, "rb") as fh:
                body = fh.read()
        except OSError:
            continue
        if body.startswith(AUDIO_BYTES):
            return body[len(AUDIO_BYTES):].decode("utf-8", "replace")
    return path












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








def _seed_limited_cursor(root, mid=23191782):
    MetaCursorStore(root=root).replace_atomic(
        {
            "mid": mid,
            "next_page": 3,
            "total": 90,
            "state": "limited",
            "last_api_error_code": None,
            "updated_at": utc_now_iso(),
        }
    )


# ------------------------------------------------------------ sidecar unit


def test_scheduler_store_roundtrip_and_rejects_running(tmp_root):
    store = SchedulerStore(root=tmp_root)
    stored = store.replace_atomic(
        {
            "scope": "pending",
            "limit": 2,
            "state": "limited",
            "processed_work_ids": ["BV1:p0"],
            "last_api_error_code": None,
            "updated_at": utc_now_iso(),
        }
    )
    assert store.load() == stored
    assert stored["allow_long_live"] is False
    assert os.path.basename(store.path) == SCHEDULER_FILENAME
    with pytest.raises(ValueError, match="running"):
        store.replace_atomic(
            {
                "scope": "pending",
                "limit": 2,
                "state": "running",
                "processed_work_ids": [],
                "last_api_error_code": None,
                "updated_at": utc_now_iso(),
            }
        )
    assert store.load()["state"] == "limited"


def test_scheduler_resume_only_matching_risk_scope(tmp_root):
    store = SchedulerStore(root=tmp_root)
    store.replace_atomic(
        {
            "scope": "pending",
            "limit": 2,
            "state": "risk_interrupted",
            "processed_work_ids": ["BVa:p0"],
            "last_api_error_code": -412,
            "updated_at": utc_now_iso(),
        }
    )
    assert store.resume_processed_ids("pending", allow_long_live=False) == [
        "BVa:p0"
    ]
    assert store.resume_processed_ids("failed", allow_long_live=False) is None
    store.replace_atomic(
        {
            "scope": "pending",
            "limit": 2,
            "state": "limited",
            "processed_work_ids": ["BVa:p0"],
            "last_api_error_code": None,
            "updated_at": utc_now_iso(),
        }
    )
    assert store.resume_processed_ids("pending", allow_long_live=False) is None


def test_resume_processed_ids_sees_long_live_policy_mismatch(tmp_root):
    store = SchedulerStore(root=tmp_root)
    store.replace_atomic(
        {
            "scope": "pending",
            "limit": 1,
            "state": "risk_interrupted",
            "processed_work_ids": ["BVa:p0"],
            "last_api_error_code": -412,
            "allow_long_live": True,
            "updated_at": utc_now_iso(),
        }
    )
    assert store.resume_processed_ids("pending", allow_long_live=False) is None
    assert store.resume_processed_ids("pending", allow_long_live=True) == [
        "BVa:p0"
    ]


def test_inspect_resume_corrupt_sidecar_logs_once(tmp_root, capsys):
    store = SchedulerStore(root=tmp_root)
    with open(store.path, "w", encoding="utf-8") as fh:
        fh.write("{not json\n")
    lookup = store.inspect_resume("pending", allow_long_live=False)
    captured = capsys.readouterr()
    assert lookup.processed_ids is None
    assert lookup.refuse is False
    assert lookup.diagnostic == "sidecar corrupt"
    assert captured.err == ""
    assert store.load() is None
    assert "scheduler: ignoring corrupt sidecar" in capsys.readouterr().err


def test_scheduler_store_rejects_forbidden_markers(tmp_root):
    store = SchedulerStore(root=tmp_root)
    stored = store.replace_atomic(
        {
            "scope": "pending",
            "limit": 2,
            "state": "risk_interrupted",
            "processed_work_ids": ["BVa:p0"],
            "last_api_error_code": 412,
            "allow_long_live": False,
            "updated_at": utc_now_iso(),
            "cookie": "SESSDATA=leak",
            "signed_url": "https://example.com/playurl?sign=abc",
            "exception": "Traceback (most recent call last): boom",
        }
    )
    assert "cookie" not in stored
    text = open(store.path, encoding="utf-8").read()
    assert "SESSDATA" not in text
    assert "cookie" not in text.lower()
    assert "https://" not in text
    assert "Traceback" not in text
    with pytest.raises(ValueError, match="redacted|credentials"):
        store.replace_atomic(
            {
                "scope": "pending",
                "limit": 2,
                "state": "risk_interrupted",
                "processed_work_ids": ["BVa:p0"],
                "last_api_error_code": "SESSDATA=abc",
                "updated_at": utc_now_iso(),
            }
        )


def test_settled_processed_ids_keep_only_ok_and_already_terminal():
    results = [
        RowResult("A", "archived", ok=True),
        RowResult("B", "needs_audio", skipped=True, skip_reason="audio_budget"),
        RowResult("C", "meta_ok", skipped=True, skip_reason="offline"),
        RowResult("D", "subtitle_done", skipped=True, skip_reason="missing_subtitle_raw"),
        RowResult("E", "archived", skipped=True, skip_reason="already_terminal"),
        RowResult("F", "needs_audio", failure_codes=[-412]),
    ]
    assert settled_processed_ids(results, risk_interrupted=True) == ["A", "E"]
    assert settled_processed_ids(results, risk_interrupted=False) == ["A", "E"]
    entries = {
        "A": {"status": "archived"},
        "B": {"status": "needs_audio"},
        "E": {"status": "gone"},
    }
    assert terminal_resume_ids(["A", "B", "E", "missing"], entries) == ["A", "E"]


def test_classify_batch_state_never_promotes_truncated_to_complete():
    assert classify_batch_state(risk_interrupted=True, truncated=True) == (
        "risk_interrupted"
    )
    assert classify_batch_state(risk_interrupted=False, truncated=True) == "limited"
    assert classify_batch_state(risk_interrupted=False, truncated=False) == (
        "complete"
    )


# ------------------------------------------------------------ CLI usage


def test_schedule_requires_positive_limit(tmp_root, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["schedule", "--scope", "pending", "--archive-root", tmp_root])
    assert exc.value.code == 1

    rc = main([
        "schedule", "--scope", "pending", "--limit", "0",
        "--archive-root", tmp_root,
    ])
    captured = capsys.readouterr()
    assert rc == 1
    assert "limit must be a positive integer" in captured.err


def test_schedule_help_lists_scope_limit_resume(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["schedule", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--scope" in out
    assert "--limit" in out
    assert "--resume" in out
    assert "--max-audio-gb" in out


# ------------------------------------------------------------ bounded batch / no false complete


def test_schedule_limit_marks_limited_and_does_not_claim_corpus_complete(
    tmp_root, monkeypatch, capsys,
):
    a = page_identity("BVa", 0, 111, "p0")
    b = page_identity("BVb", 0, 222, "p0")
    c = page_identity("BVc", 0, 333, "p0")
    store = ManifestStore(root=tmp_root)
    # A part holding a stored caption is in no store queue (SSOT §4d), so the
    # bounded batch is built from harvest-needed rows: the limit truncates
    # the selection, the processed rows run harvest (scripted empty) →
    # download → ASR → archive, the untouched one stays harvest-needed.
    for identity in (a, b, c):
        store.upsert(_row(identity, status="meta_ok"))
    _seed_limited_cursor(tmp_root)
    _stub_asr(monkeypatch)
    transport = CidRouterTransport(
        {a.cid: player_ok([]), b.cid: player_ok([]), c.cid: player_ok([])},
        playurl_by_cid={
            a.cid: playurl_ok(),
            b.cid: playurl_ok(),
            c.cid: playurl_ok(),
        },
        routes=_base_routes(),
        stream_routes={f"{STREAM_HOST}/a30216.m4s": AUDIO_BYTES},
    )
    _patch_cli(monkeypatch, transport)

    _seed_archive_database(tmp_root)
    rc = main([
        "schedule", "--scope", "pending", "--limit", "2",
        "--archive-root", tmp_root, "--sessdata", SECRET,
    ])
    captured = capsys.readouterr()
    assert rc == 0
    assert "scope=pending" in captured.out
    assert "limit=2" in captured.out
    assert "selected 2" in captured.out
    assert "batch=limited" in captured.out
    assert "batch=complete" not in captured.out
    assert "enumeration: complete" not in captured.out
    assert "enumeration: limited" in captured.out
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[a.work_id]["status"] == "archived"
    assert loaded[b.work_id]["status"] == "archived"
    # The limit also bounded the store-side selection, so the untouched row
    # was never selected and stays harvest-needed.
    assert loaded[c.work_id]["status"] == "meta_ok"
    sidecar = _scheduler(tmp_root)
    assert sidecar["state"] == "limited"
    assert sidecar["scope"] == "pending"
    assert sidecar["limit"] == 2
    recs = _ledger_records(tmp_root)
    assert recs[-1]["command"] == "schedule"
    assert recs[-1]["exit_code"] == 0
    assert recs[-1]["cursor_snapshot"]["state"] == "limited"
    _assert_no_secrets(captured, tmp_root)


def test_schedule_second_batch_completes_requested_scope_not_corpus(
    tmp_root, monkeypatch, capsys,
):
    a = page_identity("BVa", 0, 111, "p0")
    b = page_identity("BVb", 0, 222, "p0")
    store = ManifestStore(root=tmp_root)
    for identity in (a, b):
        store.upsert(_row(identity, status="meta_ok"))
    _seed_limited_cursor(tmp_root)
    _stub_asr(monkeypatch)
    transport = CidRouterTransport(
        {a.cid: player_ok([]), b.cid: player_ok([])},
        playurl_by_cid={a.cid: playurl_ok(), b.cid: playurl_ok()},
        routes=_base_routes(),
        stream_routes={f"{STREAM_HOST}/a30216.m4s": AUDIO_BYTES},
    )
    _patch_cli(monkeypatch, transport)

    _seed_archive_database(tmp_root)
    assert main([
        "schedule", "--scope", "pending", "--limit", "1",
        "--archive-root", tmp_root,
    ]) == 0
    capsys.readouterr()
    rc = main([
        "schedule", "--scope", "pending", "--limit", "1",
        "--archive-root", tmp_root,
    ])
    captured = capsys.readouterr()
    assert rc == 0
    # The second batch finishes every currently known pending row. The
    # separate enumeration cursor still reports that more pages may exist.
    assert "batch=complete" in captured.out
    assert "enumeration: limited" in captured.out
    assert "enumeration: complete" not in captured.out
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[a.work_id]["status"] == "archived"
    assert loaded[b.work_id]["status"] == "archived"
    sidecar = _scheduler(tmp_root)
    assert sidecar["state"] == "complete"
    recs = _ledger_records(tmp_root)
    assert recs[-1]["command"] == "schedule"
    assert recs[-1]["cursor_snapshot"]["state"] == "limited"


# ------------------------------------------------------------ terminal / missing / mixed


def test_schedule_terminal_selectors_are_idempotent_exit_0(
    tmp_root, monkeypatch, capsys,
):
    archived = page_identity("BVsArch", 0, 111, "p0")
    gone = page_identity("BVsGone", 0, 222, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(archived, status="archived", srt_path="transcripts/x/bundle.srt"))
    store.upsert(_row(gone, status="gone"))
    # Materialize the snapshot: the byte-identity assertion below reads
    # ``manifest.jsonl`` directly, and journal-only upserts never write it.
    store.save()
    _stub_asr(monkeypatch)
    transport = RouterTransport(_base_routes())
    _patch_cli(monkeypatch, transport)
    manifest_path = os.path.join(tmp_root, "manifest", "manifest.jsonl")
    with open(manifest_path, encoding="utf-8") as fh:
        before = fh.read()

    rc = main([
        "schedule", "--scope", f"{archived.work_id},{gone.work_id}",
        "--limit", "5", "--archive-root", tmp_root,
    ])
    captured = capsys.readouterr()
    assert rc == 0
    assert "already_terminal" in captured.out
    assert "batch=complete" in captured.out
    assert "scope not fully processed" not in captured.out
    with open(manifest_path, encoding="utf-8") as fh:
        assert fh.read() == before
    assert transport.calls == []
    sidecar = _scheduler(tmp_root)
    assert sidecar["state"] == "complete"


def test_schedule_missing_artifact_exits_1_and_keeps_success(
    tmp_root, monkeypatch, capsys,
):
    ok_id = page_identity("BVsOk", 0, 111, "p0")
    fail_id = page_identity("AVsFail", 0, 222, "p0")
    store = ManifestStore(root=tmp_root)
    # Both parts hold a stored caption and declare audio, so the store seeds
    # both as the audio queue's rows; the bytes exist only for ``ok_id``.
    # The locked queue order puts the missing-audio row first: its scripted
    # empty playurl fails the download terminally (one failed row), then
    # ``ok_id`` archives — one success, one failure, exit 1.
    for identity in (ok_id, fail_id):
        store.upsert(_row(identity, status="audio_ok",
                          audio_path=f"audio/{artifact_stem(identity)}.m4a"))
    _write_audio(tmp_root, ok_id)
    _stub_asr(monkeypatch)
    transport = CidRouterTransport(
        {},
        playurl_by_cid={
            fail_id.cid: playurl_ok(streams=[]),
            ok_id.cid: playurl_ok(),
        },
        routes=_base_routes(),
        stream_routes={f"{STREAM_HOST}/a30216.m4s": AUDIO_BYTES},
    )
    _patch_cli(monkeypatch, transport)

    _seed_archive_database(tmp_root)
    rc = main([
        "schedule", "--scope", "pending", "--limit", "5",
        "--archive-root", tmp_root,
    ])
    captured = capsys.readouterr()
    assert rc == 1
    assert "scope not fully processed" in captured.out
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[ok_id.work_id]["status"] == "archived"
    assert loaded[fail_id.work_id]["status"] == "audio_ok"
    sidecar = _scheduler(tmp_root)
    assert sidecar["state"] == "complete"
    recs = _ledger_records(tmp_root)
    assert recs[-1]["exit_code"] == 1
    _assert_no_secrets(captured, tmp_root)


def test_schedule_mixed_failure_exits_1_failed_scope_retries(
    tmp_root, monkeypatch, capsys,
):
    ok_id = page_identity("BVsOk", 0, 111, "p0")
    fail_id = page_identity("BVsFail", 0, 222, "p0")
    store = ManifestStore(root=tmp_root)
    # Both parts hold a stored caption and declare audio, so the store seeds
    # both as the audio queue's ``audio_ok`` rows; the bytes are on disk for
    # both.  The failure seam fires only on ``fail_id``'s confined audio, so
    # ``ok_id`` transcribes and archives while ``fail_id`` fails — one
    # success, one failure, exit 1, and a ``failed``-scope retry that fails
    # again.
    store.upsert(_row(ok_id, status="audio_ok",
                      audio_path=f"audio/{artifact_stem(ok_id)}.m4a"))
    store.upsert(_row(
        fail_id, status="audio_ok",
        audio_path=f"audio/{artifact_stem(fail_id)}.m4a",
    ))
    _write_audio(tmp_root, ok_id)
    _write_audio(tmp_root, fail_id)

    # D2.5 seam: `schedule` runs the shared coordinator.  The per-row failure sits on the
    # boundary's read of that row's confined audio, which is where a row is still identifiable.
    asr_fakes.install(
        monkeypatch, text="ok", fail_when=lambda path: artifact_stem(fail_id) in path
    )
    _patch_cli(monkeypatch, RouterTransport(_base_routes()))

    _seed_archive_database(tmp_root)
    rc = main([
        "schedule", "--scope", "pending", "--limit", "5",
        "--archive-root", tmp_root,
    ])
    captured = capsys.readouterr()
    assert rc == 1
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[ok_id.work_id]["status"] == "archived"
    assert loaded[fail_id.work_id]["status"] == "audio_ok"
    attempts = AttemptLedger(tmp_root).load()
    assert any(
        r["work_id"] == fail_id.work_id and r["outcome"] == "failed"
        for r in attempts
    )
    _assert_no_secrets(captured, tmp_root)

    rc = main([
        "schedule", "--scope", "failed", "--limit", "5",
        "--archive-root", tmp_root,
    ])
    captured = capsys.readouterr()
    # The failed row is selected and fails again (the ASR failure seam is
    # still armed), so the failed-scope retry is exit 1 as well.
    assert rc == 1
    assert "selected 1" in captured.out
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[ok_id.work_id]["status"] == "archived"
    assert loaded[fail_id.work_id]["status"] == "audio_ok"








def test_schedule_persist_failure_does_not_advise_resume(
    tmp_root, monkeypatch, capsys,
):
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

    def boom(self, cursor):
        raise OSError("disk full: /secret/SESSDATA=leak")

    monkeypatch.setattr(SchedulerStore, "replace_atomic", boom)
    _seed_archive_database(tmp_root)
    rc = main([
        "schedule", "--scope", "pending", "--limit", "5",
        "--archive-root", tmp_root, "--sessdata", SECRET,
    ])
    captured = capsys.readouterr()
    assert rc == 2
    assert "failed to persist scheduler.json (OSError)" in captured.err
    assert "not persisted" in captured.out
    assert "re-run with --resume" not in captured.err
    assert "disk full" not in captured.err
    assert "SESSDATA" not in captured.err
    assert not os.path.isfile(os.path.join(tmp_root, SCHEDULER_FILENAME))
    _assert_no_secrets(captured, tmp_root)


def test_schedule_resume_scope_mismatch_does_not_clobber_risk_token(
    tmp_root, monkeypatch, capsys,
):
    SchedulerStore(root=tmp_root).replace_atomic(
        {
            "scope": "pending",
            "limit": 2,
            "state": "risk_interrupted",
            "processed_work_ids": ["BVa:p0"],
            "last_api_error_code": -412,
            "allow_long_live": False,
            "updated_at": utc_now_iso(),
        }
    )
    identity = page_identity("BVf", 0, 111, "p0")
    ManifestStore(root=tmp_root).upsert(_row(identity, status="subtitle_done"))
    _write_subtitle_raw(tmp_root, identity)
    _stub_asr(monkeypatch)
    _patch_cli(monkeypatch, RouterTransport(_base_routes()))

    rc = main([
        "schedule", "--scope", "failed", "--limit", "1", "--resume",
        "--archive-root", tmp_root,
    ])
    captured = capsys.readouterr()
    assert rc == 1
    assert "--resume refused" in captured.err
    assert "scope mismatch" in captured.err
    sidecar = _scheduler(tmp_root)
    assert sidecar["state"] == "risk_interrupted"
    assert sidecar["processed_work_ids"] == ["BVa:p0"]
    assert ManifestStore(root=tmp_root).load()[identity.work_id]["status"] == (
        "subtitle_done"
    )
    _assert_no_secrets(captured, tmp_root)




# ------------------------------------------------------------ reuse line label


def test_schedule_reuse_line_names_schedule_not_run(tmp_root, monkeypatch, capsys):
    """D2.6: `schedule` wraps the shared `run_batch`, so it must relabel it.

    Three audio_ok rows with audio already on disk; the coordinator path builds
    one model for the batch and the line says which command paid it.
    """

    identities = [
        page_identity(f"BVsch{index}", 0, 600 + index, "p0") for index in range(3)
    ]
    store = ManifestStore(root=tmp_root)
    for identity in identities:
        store.upsert(_row(
            identity, status="audio_ok",
            audio_path=f"audio/{artifact_stem(identity)}.m4a",
        ))
        _write_audio(tmp_root, identity)
    _patch_cli(monkeypatch, RouterTransport(_base_routes()))

    constructed: list[dict] = []

    asr_fakes.install(monkeypatch, text="schedule-asr", constructions=constructed)

    _seed_archive_database(tmp_root)
    rc = main([
        "schedule", "--scope", "pending", "--limit", "3",
        "--archive-root", tmp_root,
    ])
    captured = capsys.readouterr()

    assert rc == 0, captured.err
    assert len(constructed) == 1
    assert "schedule: model constructions=1 for 3 asr item(s)" in captured.err
    assert "run: model constructions=" not in captured.err
    assert "model constructions=" not in captured.out
    loaded = ManifestStore(root=tmp_root).load()
    assert [loaded[i.work_id]["status"] for i in identities] == ["archived"] * 3
