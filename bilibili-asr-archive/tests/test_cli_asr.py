"""Command-level frozen status transitions through harvest / download / asr."""

from __future__ import annotations

import json
import os

from bili_asr import asr as asr_mod
from bili_asr import bili_client as bc
from bili_asr.cli import main
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


def _row(identity, *, duration_s=5, title="clip", status="meta_ok", **extra):
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


def _patch_cli(monkeypatch, transport=None):
    if transport is not None:
        monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
    monkeypatch.setattr(bc, "default_sleeper", lambda: (lambda _seconds: None))


def _jsonl_lines(root):
    path = os.path.join(root, "manifest", "manifest.jsonl")
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _jsonl_work_ids(root):
    return [row.get("work_id") or row.get("bvid") for row in _jsonl_lines(root)]


def _audio_transport():
    return RouterTransport(
        {
            "finger/spi": [SPI_OK],
            "nav": [nav_ok(), nav_response()],
            "player/wbi/v2": [player_ok([])],
            "/x/player/wbi/playurl": [playurl_ok()],
        },
        stream_routes={f"{STREAM_HOST}/a30216.m4s": AUDIO_BYTES},
    )


def _subtitle_transport():
    return RouterTransport(
        {
            "finger/spi": [SPI_OK],
            "nav": [nav_ok()],
            "player/wbi/v2": [player_ok([sub_entry()])],
            "aisubtitle.hdslb.com": [(200, dict(SAMPLE_DOC))],
        }
    )


def test_download_audio_rejects_escaped_downloader_result(tmp_root, monkeypatch, capsys):
    from bili_asr import audio
    identity = page_identity("BVescape", 0, 333, "p0")
    ManifestStore(root=tmp_root).upsert(_row(identity, status="needs_audio"))
    outside = os.path.join(tmp_root, "..", "escaped.m4a")
    monkeypatch.setattr(audio, "download_audio", lambda *args, **kwargs: outside)
    _patch_cli(monkeypatch)
    rc = main(["download-audio", "--missing-subs", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 1
    assert "0 audio_ok" in captured.out
    assert ManifestStore(root=tmp_root).get(identity.work_id)["status"] == "needs_audio"
def test_cli_audio_branch_meta_ok_needs_audio_audio_ok_archived(
    tmp_root, monkeypatch, capsys
):
    identity = page_identity("BVaud", 0, 222, "p0")
    ManifestStore(root=tmp_root).upsert(_row(identity, title="needs-asr"))
    transcribe_calls: list[str] = []

    def fake_transcribe(audio_path, model_name=None):
        transcribe_calls.append(audio_path)
        return [{"start": 0.0, "end": 1.0, "text": "asr-text"}]

    monkeypatch.setattr(asr_mod, "transcribe", fake_transcribe)
    _patch_cli(monkeypatch)
    monkeypatch.setattr(bc, "build_default_transport", _audio_transport)

    rc = main(["harvest-subs", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    after_harvest = ManifestStore(root=tmp_root).get(identity.work_id)
    assert after_harvest["status"] == "needs_audio"

    rc = main(["download-audio", "--missing-subs", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    after_audio = ManifestStore(root=tmp_root).get(identity.work_id)
    assert after_audio["status"] == "audio_ok"
    assert after_audio.get("audio_path")
    audio_abs = os.path.join(tmp_root, after_audio["audio_path"])
    assert os.path.isfile(audio_abs)

    rc = main(["asr", "--pending", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    archived = ManifestStore(root=tmp_root).get(identity.work_id)
    assert archived["status"] == "archived"
    assert os.path.isfile(os.path.join(tmp_root, archived["srt_path"]))
    assert transcribe_calls == [audio_abs]


def test_cli_subtitle_branch_meta_ok_subtitle_done_archived_skips_asr(
    tmp_root, monkeypatch, capsys
):
    identity = page_identity("BVsub", 0, 111, "p0")
    ManifestStore(root=tmp_root).upsert(_row(identity, title="has-sub"))
    transcribe_calls: list[str] = []

    def fake_transcribe(audio_path, model_name=None):
        transcribe_calls.append(audio_path)
        return [{"start": 0.0, "end": 1.0, "text": "should-not-run"}]

    monkeypatch.setattr(asr_mod, "transcribe", fake_transcribe)
    _patch_cli(monkeypatch, _subtitle_transport())

    rc = main(["harvest-subs", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    after_harvest = ManifestStore(root=tmp_root).get(identity.work_id)
    assert after_harvest["status"] == "subtitle_done"
    assert os.path.isfile(os.path.join(tmp_root, after_harvest["srt_path"]))

    rc = main(["asr", "--pending", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    archived = ManifestStore(root=tmp_root).get(identity.work_id)
    assert archived["status"] == "archived"
    assert os.path.isfile(os.path.join(tmp_root, archived["srt_path"]))
    assert transcribe_calls == []


def test_cli_harvest_risk_exhaustion_preserves_last_stable_status(
    tmp_root, monkeypatch, capsys
):
    first = page_identity("BVok", 0, 111, "p0")
    second = page_identity("BVrisk", 0, 222, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(first, title="stable"))
    store.upsert(_row(second, title="risk"))

    risk = (412, {"code": -412, "message": "request too frequent"})
    transport = RouterTransport(
        {
            "finger/spi": [SPI_OK] * 8,
            "nav": [nav_ok()],
            "player/wbi/v2": [player_ok([sub_entry()])] + [risk] * 8,
            "aisubtitle.hdslb.com": [(200, dict(SAMPLE_DOC))],
        }
    )
    monkeypatch.setattr(asr_mod, "transcribe", lambda *a, **k: [])
    _patch_cli(monkeypatch, transport)

    rc = main(["harvest-subs", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 2
    assert "risk-control ceiling" in captured.err
    assert "re-run to resume" in captured.err
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[first.work_id]["status"] == "subtitle_done"
    assert loaded[second.work_id]["status"] == "meta_ok"


def test_cli_asr_missing_optional_asr_exits_1_non_archived(
    tmp_root, monkeypatch, capsys
):
    from bili_asr.asr import ASRDependencyError

    identity = page_identity("BVaud", 0, 222, "p0")
    ManifestStore(root=tmp_root).upsert(_row(identity, title="needs-asr"))
    hint = 'pip install -e "bilibili-asr-archive/[asr]"'

    def missing_asr(audio_path, model_name=None):
        raise ASRDependencyError(
            f"SenseVoice support is not installed; run: {hint}"
        )

    monkeypatch.setattr(asr_mod, "transcribe", missing_asr)
    _patch_cli(monkeypatch)
    monkeypatch.setattr(bc, "build_default_transport", _audio_transport)

    assert main(["harvest-subs", "--archive-root", tmp_root]) == 0
    capsys.readouterr()
    assert main(["download-audio", "--missing-subs", "--archive-root", tmp_root]) == 0
    capsys.readouterr()
    assert ManifestStore(root=tmp_root).get(identity.work_id)["status"] == "audio_ok"

    rc = main(["asr", "--pending", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 1
    assert "ASR dependency unavailable" in captured.err
    loaded = ManifestStore(root=tmp_root).get(identity.work_id)
    assert loaded["status"] == "audio_ok"
    assert loaded["status"] != "archived"
    assert not loaded.get("txt_path")


def test_cli_asr_rerun_idempotent_leaves_unrelated_rows(
    tmp_root, monkeypatch, capsys
):
    target = page_identity("BVsub", 0, 111, "p0")
    other = page_identity("BVother", 0, 999, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(target, title="has-sub"))
    store.upsert(
        _row(other, title="already-done", status="archived", srt_path="keep.srt")
    )
    other_snapshot = dict(store.get(other.work_id))

    monkeypatch.setattr(
        asr_mod,
        "transcribe",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("ASR must not run")),
    )
    _patch_cli(monkeypatch, _subtitle_transport())

    assert main(["harvest-subs", "--archive-root", tmp_root]) == 0
    capsys.readouterr()
    assert main(["asr", "--pending", "--archive-root", tmp_root]) == 0
    capsys.readouterr()

    first_lines = _jsonl_lines(tmp_root)
    first_ids = _jsonl_work_ids(tmp_root)
    assert len(first_ids) == len(set(first_ids))
    assert ManifestStore(root=tmp_root).get(target.work_id)["status"] == "archived"
    assert ManifestStore(root=tmp_root).get(other.work_id) == other_snapshot

    rc = main(["asr", "--pending", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    rerun_lines = _jsonl_lines(tmp_root)
    rerun_ids = _jsonl_work_ids(tmp_root)
    assert rerun_ids == first_ids
    assert len(rerun_ids) == len(set(rerun_ids))
    assert rerun_lines == first_lines
    assert ManifestStore(root=tmp_root).get(other.work_id) == other_snapshot
