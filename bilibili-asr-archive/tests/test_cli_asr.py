"""Command-level frozen status transitions through download / asr.

The legacy manifest states these commands start from (``needs_audio``,
``subtitle_done``) are produced by the legacy subtitle producer
(``subtitles.harvest_subtitle``) directly: ``harvest-subs`` moved to the SQLite
transcript path and no longer writes the manifest, so these tests drive the
ASR/audio path from the state a pre-cutover archive already holds.
"""

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


def _model_input_bytes(path: str) -> bytes:
    """The audio the model was handed, read while the path still resolves.

    The runner passes a ``/proc/self/fd/N`` descriptor and the ASR boundary
    copies it to a temp file the model actually opens, so reading it here is
    the only way to see the bytes the model received.
    """
    try:
        with open(os.fspath(path), "rb") as fh:
            return fh.read()
    except OSError:
        return b""


class _FakeModel:
    """Stands in for the FunASR AutoModel the runner builds lazily."""

    def __init__(self, calls=None):
        self._calls = calls

    def generate(self, **kwargs):
        if self._calls is not None:
            self._calls.append(
                (kwargs["input"], _model_input_bytes(kwargs["input"]))
            )
        return [{"start": 0.0, "end": 1.0, "text": "asr-text"}]


def _stub_runner_model(monkeypatch, calls=None):
    """D2.5 seam: patch the module-level factory, not ``asr.transcribe``.

    The real ``_get_model`` path stays under test, so the counter a command
    reports is the one the production construction site produces.  Returns the
    list of construction kwargs, one entry per model built.
    """
    constructions: list[dict] = []

    def factory(**kwargs):
        constructions.append(dict(kwargs))
        return _FakeModel(calls)

    monkeypatch.setenv("BILI_ASR_DEVICE", "cpu")
    monkeypatch.setattr(asr_mod, "_load_default_model", factory)
    return constructions


def _seed_audio_ok(root, identities):
    """Rows the ``asr`` command routes straight to transcription."""
    store = ManifestStore(root=root)
    audio_dir = os.path.join(root, "audio")
    os.makedirs(audio_dir, exist_ok=True)
    for identity in identities:
        row = _row(identity, status="audio_ok")
        row["audio_path"] = f"audio/{artifact_stem(identity)}.m4a"
        store.upsert(row)
        with open(os.path.join(audio_dir, f"{artifact_stem(identity)}.m4a"), "wb") as fh:
            fh.write(AUDIO_BYTES)


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


def _legacy_subtitle_state(root, identity, transport) -> str:
    """Produce the legacy manifest state the ASR/audio path still reads.

    ``harvest-subs`` no longer writes the manifest — it stores normalized
    transcripts in ``archive.db`` — so the legacy producer the pilot and
    coordinator paths still call is driven directly here: the resulting row and
    its raw/srt artifacts are exactly what a pre-cutover archive holds.
    """
    from bili_asr import subtitles

    store = ManifestStore(root=root)
    client = bc.BiliClient(
        transport=transport,
        sleeper=lambda _seconds: None,
        jitter=lambda: 0.0,
        sessdata=None,
    )
    return subtitles.harvest_subtitle(client, identity, store, root)


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
def test_cli_audio_branch_needs_audio_audio_ok_archived(
    tmp_root, monkeypatch, capsys
):
    identity = page_identity("BVaud", 0, 222, "p0")
    ManifestStore(root=tmp_root).upsert(_row(identity, title="needs-asr"))
    transcribe_calls: list[str] = []

    _stub_runner_model(monkeypatch, transcribe_calls)
    _patch_cli(monkeypatch)
    monkeypatch.setattr(bc, "build_default_transport", _audio_transport)

    assert _legacy_subtitle_state(tmp_root, identity, _audio_transport()) == "needs_audio"
    captured = capsys.readouterr()
    assert ManifestStore(root=tmp_root).get(identity.work_id)["status"] == "needs_audio"

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
    # The model read this row's confined audio, not a stale or foreign file.
    assert [body for _path, body in transcribe_calls] == [AUDIO_BYTES]


def test_cli_subtitle_branch_subtitle_done_archived_skips_asr(
    tmp_root, monkeypatch, capsys
):
    identity = page_identity("BVsub", 0, 111, "p0")
    ManifestStore(root=tmp_root).upsert(_row(identity, title="has-sub"))
    transcribe_calls: list[str] = []

    # The seam records the model's generation inputs: this row must never
    # reach a model (the subtitle branch wins before ASR).
    _stub_runner_model(monkeypatch, transcribe_calls)
    _patch_cli(monkeypatch, _subtitle_transport())

    assert (
        _legacy_subtitle_state(tmp_root, identity, _subtitle_transport())
        == "subtitle_done"
    )
    capsys.readouterr()
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


def test_cli_asr_missing_optional_asr_exits_1_non_archived(
    tmp_root, monkeypatch, capsys
):
    from bili_asr.asr import ASRDependencyError

    identity = page_identity("BVaud", 0, 222, "p0")
    ManifestStore(root=tmp_root).upsert(_row(identity, title="needs-asr"))
    hint = 'pip install -e "bilibili-asr-archive/[asr]"'

    def missing_asr(**_kwargs):
        raise ASRDependencyError(
            f"FunASR support is not installed; run: {hint}"
        )

    monkeypatch.setenv("BILI_ASR_DEVICE", "cpu")
    monkeypatch.setattr(asr_mod, "_load_default_model", missing_asr)
    _patch_cli(monkeypatch)
    monkeypatch.setattr(bc, "build_default_transport", _audio_transport)

    assert _legacy_subtitle_state(tmp_root, identity, _audio_transport()) == "needs_audio"
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
        "_load_default_model",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("ASR must not run")),
    )
    monkeypatch.setenv("BILI_ASR_DEVICE", "cpu")
    _patch_cli(monkeypatch, _subtitle_transport())

    assert (
        _legacy_subtitle_state(tmp_root, target, _subtitle_transport())
        == "subtitle_done"
    )
    capsys.readouterr()
    assert main(["asr", "--pending", "--archive-root", tmp_root]) == 0
    capsys.readouterr()

    first_lines = _jsonl_lines(tmp_root)
    first_ids = _jsonl_work_ids(tmp_root)
    assert set(first_ids) == {target.work_id, other.work_id}
    assert ManifestStore(root=tmp_root).get(target.work_id)["status"] == "archived"
    assert ManifestStore(root=tmp_root).get(other.work_id) == other_snapshot

    rc = main(["asr", "--pending", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    rerun_lines = _jsonl_lines(tmp_root)
    rerun_ids = _jsonl_work_ids(tmp_root)
    assert rerun_ids == first_ids
    assert rerun_lines == first_lines
    assert ManifestStore(root=tmp_root).get(other.work_id) == other_snapshot


# ------------------------------------------------------------ one runner per invocation


def test_cli_asr_invocation_constructs_the_model_once_for_three_items(
    tmp_root, monkeypatch, capsys
):
    """D2.2/D2.5: one `asr --pending --limit 3` process pays one construction."""

    identities = [
        page_identity(f"BVreuse{index}", 0, 300 + index, "p0") for index in range(3)
    ]
    _seed_audio_ok(tmp_root, identities)
    constructions = _stub_runner_model(monkeypatch)
    _patch_cli(monkeypatch)

    rc = main(["asr", "--pending", "--limit", "3", "--archive-root", tmp_root])
    captured = capsys.readouterr()

    assert rc == 0, captured.err
    loaded = ManifestStore(root=tmp_root).load()
    assert [loaded[i.work_id]["status"] for i in identities] == ["archived"] * 3
    # One construction served all three rows...
    assert len(constructions) == 1
    assert constructions[0]["device"] == "cpu"
    # ...and the invocation's own output states it, on stderr only.
    assert "asr: model constructions=1 for 3 asr item(s)" in captured.err
    assert "model constructions=" not in captured.out


def test_cli_asr_subtitle_only_selection_constructs_no_model(
    tmp_root, monkeypatch, capsys
):
    """A selection with no ASR row prints no line (D2.6) and builds nothing."""

    sub = page_identity("BVsubonly", 0, 111, "p0")
    ManifestStore(root=tmp_root).upsert(_row(sub, title="has-sub"))
    constructions = _stub_runner_model(monkeypatch)
    _patch_cli(monkeypatch, _subtitle_transport())

    assert (
        _legacy_subtitle_state(tmp_root, sub, _subtitle_transport())
        == "subtitle_done"
    )
    capsys.readouterr()

    rc = main(["asr", "--pending", "--archive-root", tmp_root])
    captured = capsys.readouterr()

    assert rc == 0, captured.err
    assert ManifestStore(root=tmp_root).get(sub.work_id)["status"] == "archived"
    assert constructions == []
    assert "model constructions=" not in captured.out
    assert "model constructions=" not in captured.err
