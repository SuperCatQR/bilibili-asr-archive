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
import sys

import pytest

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
from conftest import reuse_line

import _asr_fakes as asr_fakes


def _stub_runner_model(monkeypatch, calls=None, released=None):
    """D2.5 seam: patch the module-level factory, not ``asr.transcribe``.

    The real ``_get_model`` path stays under test, so the counter a command reports is the one the
    production construction site produces.  Returns the list of construction kwargs, one entry per
    model set built.  ``calls`` collects the path of every recording the boundary opened — the model
    is handed a chunk file, so a row is identified at the read, not at the model.  ``released``
    records each ``ASRRunner.release()`` call, so a test can assert the invocation-scoped runner is
    handed back on every exit path.
    """

    constructions: list[dict] = []
    asr_fakes.install(monkeypatch, text="asr-text", constructions=constructions, reads=calls)

    if released is not None:
        real_release = asr_mod.ASRRunner.release

        def recording_release(self):
            released.append(self)
            real_release(self)

        monkeypatch.setattr(asr_mod.ASRRunner, "release", recording_release)

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
    assert len(transcribe_calls) == 1, "one row, one recording opened"
    assert artifact_stem(identity) in transcribe_calls[0], "the boundary read this row's audio"


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

    asr_fakes.raising(
        monkeypatch, ASRDependencyError(f"Qwen3-ASR support is not installed; run: {hint}")
    )
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

    asr_fakes.forbidden(monkeypatch)
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
    released: list[object] = []
    constructions = _stub_runner_model(monkeypatch, released=released)
    _patch_cli(monkeypatch)

    rc = main(["asr", "--pending", "--limit", "3", "--archive-root", tmp_root])
    captured = capsys.readouterr()

    assert rc == 0, captured.err
    loaded = ManifestStore(root=tmp_root).load()
    assert [loaded[i.work_id]["status"] for i in identities] == ["archived"] * 3
    # One construction served all three rows...
    assert len(constructions) == 1
    assert constructions[0]["device"] == "cpu"
    # ...the invocation-scoped runner is handed back exactly once...
    assert len(released) == 1
    # ...and the invocation's own output states it, on stderr only.
    assert "asr: model constructions=1 for 3 asr item(s)" in captured.err
    assert "model constructions=" not in captured.out


def test_cli_asr_releases_the_runner_when_transcription_is_interrupted(
    tmp_root, monkeypatch, capsys
):
    """The `finally` must release on a path no `except` clause catches.

    ``_cmd_asr`` catches ``Exception`` per row, so the release only has a
    chance to run for a ``BaseException`` that escapes the loop — a Ctrl-C
    mid-transcription is the realistic one.  Without the `finally` the runner
    (and the model it holds) would leak for the rest of the process.
    """

    identity = page_identity("BVinterrupt", 0, 555, "p0")
    _seed_audio_ok(tmp_root, [identity])
    released: list[object] = []

    def interrupting(self, **_kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr(asr_fakes.Model, "generate", interrupting)
    asr_fakes.install(monkeypatch, text="asr-text")

    real_release = asr_mod.ASRRunner.release

    def recording_release(self):
        released.append(self)
        real_release(self)

    monkeypatch.setattr(asr_mod.ASRRunner, "release", recording_release)
    _patch_cli(monkeypatch)

    with pytest.raises(KeyboardInterrupt):
        main(["asr", "--pending", "--archive-root", tmp_root])

    assert len(released) == 1
    # The row must not be archived: the interrupt aborted the transcription.
    assert ManifestStore(root=tmp_root).get(identity.work_id)["status"] == "audio_ok"


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


def test_cli_asr_prints_the_line_when_every_transcription_fails(
    tmp_root, monkeypatch, capsys
):
    """The guard is "nothing was paid", not "no ASR items" (D2.6 as amended).

    Three rows reach the model, the model is built once (the ~34 s/item cost
    this plan exists to expose), and then every ``generate`` raises.  The old
    ``asr_items <= 0`` guard swallowed the line exactly here, hiding the
    first-decode failure the operator needs stated while the process had
    already paid for it.
    """

    identities = [
        page_identity(f"BVallfail{index}", 0, 850 + index, "p0") for index in range(3)
    ]
    _seed_audio_ok(tmp_root, identities)
    constructions = _stub_runner_model(monkeypatch)
    monkeypatch.setattr(asr_fakes.Model, "generate", lambda self, **kwargs: _raise_asr_error())
    _patch_cli(monkeypatch, RouterTransport({}))

    rc = main(["asr", "--pending", "--limit", "3", "--archive-root", tmp_root])
    captured = capsys.readouterr()

    assert rc == 1, captured.err
    # Paid exactly once, transcribed nothing, and said so.
    assert len(constructions) == 1
    assert reuse_line(captured, "asr") == "asr: model constructions=1 for 0 asr item(s)"
    assert "model constructions=" not in captured.out
    assert [
        ManifestStore(root=tmp_root).get(i.work_id)["status"] for i in identities
    ] == ["audio_ok"] * 3


def _raise_asr_error():
    raise asr_mod.ASRModelError("first decode failed")


def test_cli_asr_reuse_line_is_dropped_when_stderr_is_closed(
    tmp_root, monkeypatch, capsys
):
    """F-02 (CLI half): a closed fd 2 must not relocate the line to stdout.

    With fd 2 closed CPython sets ``sys.stderr`` to ``None``, and
    ``print(..., file=None)`` writes to **stdout** — the stream ``_cmd_asr``
    owns for its per-row ``archived`` lines and its summary.  A missing stream
    means the diagnostic has nowhere to go, so the shared helper drops it
    rather than falling back into stdout; the coordinator applies the same rule
    to keep ``campaign``'s single JSON document intact.
    """

    identities = [
        page_identity(f"BVnostderr{index}", 0, 950 + index, "p0") for index in range(3)
    ]
    _seed_audio_ok(tmp_root, identities)
    constructions = _stub_runner_model(monkeypatch)
    _patch_cli(monkeypatch, RouterTransport({}))
    monkeypatch.setattr(sys, "stderr", None)

    rc = main(["asr", "--pending", "--limit", "3", "--archive-root", tmp_root])
    captured = capsys.readouterr()

    # The line reaches neither stream: not stderr (closed), and above all not
    # stdout, where a `file=None` fallback would have put it.
    assert "model constructions=" not in captured.out
    assert "model constructions=" not in captured.err
    # ...while the invocation it describes still did the work.
    assert len(constructions) == 1
    assert rc == 0, captured.err
    assert [
        ManifestStore(root=tmp_root).get(i.work_id)["status"] for i in identities
    ] == ["archived"] * 3


def test_cli_asr_counts_only_the_row_whose_transcribe_returned(
    tmp_root, monkeypatch, capsys
):
    """The denominator's exact event: a *successful* ``runner.transcribe``.

    D2.5 counts rows whose ASR stage produced a transcript, and the `run` path
    counts at its ``asr: ok`` attempt — i.e. after ``transcribe`` returns.
    Row 1 of 3 raises there, so a counter moved one line earlier (before the
    call) counts it anyway and the two paths disagree on identical input;
    this test pins that boundary by comparing both paths word for word.
    """

    identities = [
        page_identity(f"BVraisefirst{index}", 0, 860 + index, "p0")
        for index in range(3)
    ]
    raising = identities[0]
    asr_root = os.path.join(tmp_root, "asr-path")
    run_root = os.path.join(tmp_root, "run-path")
    os.makedirs(asr_root)
    os.makedirs(run_root)
    _seed_audio_ok(asr_root, identities)
    _seed_audio_ok(run_root, identities)
    constructions = _stub_runner_model(monkeypatch)
    real_transcribe = asr_mod.ASRRunner.transcribe
    raising_stem = artifact_stem(raising)

    def fail_for_row_one(self, audio_path):
        # `asr` hands the runner a /proc/self/fd descriptor while `run` hands it
        # the real audio path; realpath resolves both to the same file.
        if raising_stem in os.path.realpath(os.fspath(audio_path)):
            raise asr_mod.ASRModelError("row 1 decode failed")
        return real_transcribe(self, audio_path)

    monkeypatch.setattr(asr_mod.ASRRunner, "transcribe", fail_for_row_one)
    _patch_cli(monkeypatch, RouterTransport({}))

    rc = main(["asr", "--pending", "--limit", "3", "--archive-root", asr_root])
    asr_captured = capsys.readouterr()
    assert rc == 1, asr_captured.err

    rc = main(["run", "--scope", "pending", "--limit", "3", "--archive-root", run_root])
    run_captured = capsys.readouterr()
    assert rc == 1, run_captured.err

    # One construction paid per invocation (the model is built before row 1 is
    # handed to it), two of the three rows produced a transcript.
    assert len(constructions) == 2
    asr_line = reuse_line(asr_captured, "asr")
    run_line = reuse_line(run_captured, "run")
    assert asr_line == "asr: model constructions=1 for 2 asr item(s)"
    assert run_line == "run: model constructions=1 for 2 asr item(s)"
    assert asr_line.split(": ", 1)[1] == run_line.split(": ", 1)[1]


def _patch_bundle_incomplete_for(monkeypatch, failing):
    """Fail the archive step for ``failing`` only, on both command paths.

    The rows are seeded as ordinary ``audio_ok`` rows (``_seed_audio_ok``), so
    they all reach the real transcription boundary.  This patch then makes one
    of them fail *after* it produced its transcript: the real ``write_archive``
    runs, the real ``ValueError("archive bundle incomplete")`` is raised, and
    the row keeps its ``audio_ok`` status.  Both the in-process loop and the
    coordinator are driven from a root seeded this way, so the injected
    failure is identical on both paths.
    """
    from bili_asr import archive as archive_mod

    stem = artifact_stem(failing)
    real = archive_mod.archive_bundle_complete

    def patched(archive_root, paths):
        if any(stem in str(path) for path in paths.values()):
            return False
        return real(archive_root, paths)

    monkeypatch.setattr(archive_mod, "archive_bundle_complete", patched)


def test_cli_asr_and_run_state_the_same_asr_items_after_a_downstream_failure(
    tmp_root, monkeypatch, capsys
):
    """D2.5: the in-process loop and the coordinator share one denominator.

    Minor 1 of the Task 2 review: `asr` counted the row after the whole
    archive step while `run` counts it at `asr: ok` (a row that produced a
    transcript), so a row that failed *after* transcription appeared in one
    line and not the other.  The same three-row input is driven through both
    paths here; their lines must agree word for word but for the label.
    """

    identities = [
        page_identity(f"BVagree{index}", 0, 700 + index, "p0") for index in range(3)
    ]
    failing = identities[1]
    asr_root = os.path.join(tmp_root, "asr-path")
    run_root = os.path.join(tmp_root, "run-path")
    os.makedirs(asr_root)
    os.makedirs(run_root)
    _seed_audio_ok(asr_root, identities)
    _seed_audio_ok(run_root, identities)
    constructions = _stub_runner_model(monkeypatch)
    _patch_bundle_incomplete_for(monkeypatch, failing)
    _patch_cli(monkeypatch, RouterTransport({}))

    rc = main(["asr", "--pending", "--limit", "3", "--archive-root", asr_root])
    asr_captured = capsys.readouterr()
    assert rc == 1, asr_captured.err
    asr_loaded = ManifestStore(root=asr_root).load()
    assert asr_loaded[failing.work_id]["status"] == "audio_ok"
    assert [asr_loaded[i.work_id]["status"] for i in identities].count("archived") == 2

    rc = main(["run", "--scope", "pending", "--limit", "3", "--archive-root", run_root])
    run_captured = capsys.readouterr()
    assert rc == 1, run_captured.err
    run_loaded = ManifestStore(root=run_root).load()
    assert run_loaded[failing.work_id]["status"] == "audio_ok"
    assert [run_loaded[i.work_id]["status"] for i in identities].count("archived") == 2

    # One construction paid per invocation...
    assert len(constructions) == 2
    # ...and the same denominator, because the same three rows transcribed.
    asr_line = reuse_line(asr_captured, "asr")
    run_line = reuse_line(run_captured, "run")
    assert asr_line == "asr: model constructions=1 for 3 asr item(s)"
    assert run_line == "run: model constructions=1 for 3 asr item(s)"
    assert asr_line.split(": ", 1)[1] == run_line.split(": ", 1)[1]


def test_cli_asr_downstream_failure_of_the_only_asr_row_still_prints_the_line(
    tmp_root, monkeypatch, capsys
):
    """D2.6's `asr_items > 0` guard must not swallow a paid construction.

    The review's sharpest form of Minor 1: when the *only* transcribing row
    failed after transcription, the old post-archive increment left the count
    at zero and the line vanished — an invocation that built a model reported
    nothing, while `run` reported it for the same work.
    """

    identity = page_identity("BVonlyfail", 0, 900, "p0")
    asr_root = os.path.join(tmp_root, "asr-path")
    run_root = os.path.join(tmp_root, "run-path")
    os.makedirs(asr_root)
    os.makedirs(run_root)
    _seed_audio_ok(asr_root, [identity])
    _seed_audio_ok(run_root, [identity])
    _stub_runner_model(monkeypatch)
    _patch_bundle_incomplete_for(monkeypatch, identity)
    _patch_cli(monkeypatch, RouterTransport({}))

    rc = main(["asr", "--pending", "--archive-root", asr_root])
    asr_captured = capsys.readouterr()
    assert rc == 1, asr_captured.err
    assert ManifestStore(root=asr_root).get(identity.work_id)["status"] == "audio_ok"

    rc = main(["run", "--scope", "pending", "--archive-root", run_root])
    run_captured = capsys.readouterr()
    assert rc == 1, run_captured.err

    assert reuse_line(asr_captured, "asr") == (
        "asr: model constructions=1 for 1 asr item(s)"
    )
    assert reuse_line(run_captured, "run") == (
        "run: model constructions=1 for 1 asr item(s)"
    )


def _stub_failing_loads(monkeypatch):
    """A factory that raises on every call, counting its invocations (F1).

    The device gate precedes the factory, so a CPU device plus a raising
    factory is the exact shape of the review's scenario: every row pays one
    load attempt and no row ever gets a model.
    """
    attempts: list[dict] = []

    asr_fakes.install(monkeypatch, text="asr-text", constructions=attempts,
                      raises=RuntimeError("no checkpoint"))
    return attempts


def test_cli_prints_no_reuse_line_when_every_load_fails(
    tmp_root, monkeypatch, capsys
):
    """F1: the attempts are recorded, not printed — pinned on the real CLI.

    The review found the README asserting that this batch "reports
    ``model constructions=0``" and "still states its cost — as N attempts and 0
    constructions".  Neither is shipped: no surface prints the attempt count, and
    the reuse line's guard (``asr_items <= 0 and model_constructions <= 0``) is
    silent exactly here, because a failed load increments neither counter's
    printed side.  This test pins the *behaviour* the README now documents: N
    attempts really are paid, and the line appears on neither stream.  It fails
    if a future change starts printing a line this paragraph does not promise.
    """

    identities = [
        page_identity(f"BVnoload{index}", 0, 960 + index, "p0") for index in range(3)
    ]
    asr_root = os.path.join(tmp_root, "asr-path")
    run_root = os.path.join(tmp_root, "run-path")
    os.makedirs(asr_root)
    os.makedirs(run_root)
    _seed_audio_ok(asr_root, identities)
    _seed_audio_ok(run_root, identities)
    attempts = _stub_failing_loads(monkeypatch)
    _patch_cli(monkeypatch, RouterTransport({}))

    rc = main(["asr", "--pending", "--limit", "3", "--archive-root", asr_root])
    asr_captured = capsys.readouterr()
    run_attempts = len(attempts)
    rc_run = main(["run", "--scope", "pending", "--limit", "3", "--archive-root", run_root])
    run_captured = capsys.readouterr()

    # Every row paid its own load attempt: N attempts, zero constructions.
    assert rc == 1, asr_captured.err
    assert rc_run == 1, run_captured.err
    assert run_attempts == 3
    assert len(attempts) == 6
    # ...and neither invocation printed the reuse line, on either stream.
    for captured in (asr_captured, run_captured):
        assert "model constructions=" not in captured.out
        assert "model constructions=" not in captured.err
    # The rows' failures are what the operator sees instead, per row.
    assert "failed (ASRModelError)" in run_captured.err
    assert "BVnoload0:p0: archive failed (ASRModelError)" in asr_captured.err
    assert "run: 0 completed, 0 skipped, 3 failed" in run_captured.out
    assert "asr: 0 archived, 3 failed" in asr_captured.out


def test_the_asr_path_names_the_exception_class_beside_the_row(
    tmp_root, monkeypatch, capsys
):
    """QC3-F1: the `asr` path used to print fixed text with no reason at all.

    The `run` path states the code (`failed (ValueError)`); this one printed
    ``<work_id>: archive failed`` and nothing else, so a row that failed
    downstream of transcription was indistinguishable from any other.  The code
    is attached now, and the row stays unarchived exactly as before.
    """

    identity = page_identity("BVcode0", 0, 970, "p0")
    _seed_audio_ok(tmp_root, [identity])
    _stub_runner_model(monkeypatch)

    def explode(_root, _entry, _segments, **_kwargs):
        raise KeyError("downstream")

    _patch_cli(monkeypatch, RouterTransport({}))
    monkeypatch.setattr(asr_mod.ASRRunner, "transcribe", lambda self, _path: [
        {"start": 0.0, "end": 1.0, "text": "句子。"}
    ])
    # Patch the one archive seam this row reaches, after transcription.
    from bili_asr import archive as archive_mod

    monkeypatch.setattr(archive_mod, "write_archive", explode)

    rc = main(["asr", "--pending", "--archive-root", tmp_root])
    captured = capsys.readouterr()

    assert rc == 1, captured.err
    assert "BVcode0:p0: archive failed (KeyError)" in captured.err
    # The code is the class name, never the exception's message or payload.
    assert "downstream" not in captured.err
    assert "downstream" not in captured.out
    assert "BVcode0:p0: archive failed\n" not in captured.err
    assert ManifestStore(root=tmp_root).get(identity.work_id)["status"] == "audio_ok"


def test_a_malformed_declaration_is_refused_before_the_first_row(
    tmp_root, monkeypatch, capsys
):
    """QC3-F1: one message at entry, exit 1, and no row pays a load attempt.

    Before this, the same misconfiguration printed one identical
    ``archive failed`` line per row — the reason reaching no stream and no
    sidecar.  The declaration is now read once at command entry, so the
    operator gets the variable's name and nothing is attempted.
    """

    identities = [
        page_identity(f"BVdecl{index}", 0, 980 + index, "p0") for index in range(3)
    ]
    _seed_audio_ok(tmp_root, identities)
    attempts = _stub_failing_loads(monkeypatch)
    monkeypatch.setenv("BILI_ASR_MODEL_ID", "/opt/models/Fun-ASR-Nano-2512")
    _patch_cli(monkeypatch, RouterTransport({}))

    rc = main(["asr", "--pending", "--limit", "3", "--archive-root", tmp_root])
    captured = capsys.readouterr()

    assert rc == 1
    assert (
        "asr: BILI_ASR_MODEL_ID must be a hub-level model identifier"
        in captured.err
    )
    # Stated once, not once per row, and no row was even reached.
    assert captured.err.count("BILI_ASR_MODEL_ID") == 1
    assert "archive failed" not in captured.err
    assert attempts == []
    assert [
        ManifestStore(root=tmp_root).get(i.work_id)["status"] for i in identities
    ] == ["audio_ok"] * 3


def test_a_malformed_declaration_does_not_block_a_subtitle_only_selection(
    tmp_root, monkeypatch, capsys
):
    """The entry check is scoped to the ASR path, not to the command.

    A subtitle-sourced row never reads the ASR knobs, so a malformed
    declaration must not refuse a selection that would not have loaded a model
    anyway — the same "no ASR row, no cost" rule D2.6 states for the reuse line.
    """

    sub = page_identity("BVdeclsub", 0, 990, "p0")
    ManifestStore(root=tmp_root).upsert(_row(sub, title="has-sub"))
    constructions = _stub_runner_model(monkeypatch)
    monkeypatch.setenv("BILI_ASR_MODEL_ID", "/opt/models/Fun-ASR-Nano-2512")
    _patch_cli(monkeypatch, _subtitle_transport())

    assert (
        _legacy_subtitle_state(tmp_root, sub, _subtitle_transport())
        == "subtitle_done"
    )
    capsys.readouterr()

    rc = main(["asr", "--pending", "--archive-root", tmp_root])
    captured = capsys.readouterr()

    assert rc == 0, captured.err
    assert "BILI_ASR_MODEL_ID" not in captured.err
    assert constructions == []
    assert (
        ManifestStore(root=tmp_root).get(sub.work_id)["status"] == "archived"
    )


def test_the_asr_entry_failure_message_never_carries_a_path(
    tmp_root, monkeypatch, capsys
):
    """QC3-F1's redaction pre-condition, both branches, on the real command.

    Printing a ``ValueError``'s own message is only safe if neither branch can
    carry an operator path.  The unsafe-declaration branch names the variable
    and nothing else; the contradiction branch can only fire once **both**
    values have passed the identifier scan, so it echoes two identifiers.  Each
    branch is driven through ``main()`` and both streams are scanned.
    """

    identity = page_identity("BVdeclpath", 0, 995, "p0")
    local_path = "/opt/models/Fun-ASR-Nano-2512"
    _seed_audio_ok(tmp_root, [identity])
    _stub_failing_loads(monkeypatch)
    _patch_cli(monkeypatch, RouterTransport({}))

    # Branch 1: an absolute path as the *declaration* — refused, path absent.
    monkeypatch.setenv("BILI_ASR_MODEL_ID", local_path)
    assert main(["asr", "--pending", "--archive-root", tmp_root]) == 1
    branch_one = capsys.readouterr()
    for stream in (branch_one.out, branch_one.err):
        assert local_path not in stream
        assert "/opt/" not in stream

    # Branch 2: a declaration contradicting a safe hub-level load value.  The
    # contradiction branch fires only because both values are identifiers.
    monkeypatch.setenv("BILI_ASR_MODEL", "OtherOrg/OtherModel")
    monkeypatch.setenv("BILI_ASR_MODEL_ID", "FunAudioLLM/Fun-ASR-Nano-2512")
    assert main(["asr", "--pending", "--archive-root", tmp_root]) == 1
    branch_two = capsys.readouterr()
    assert "contradicts" in branch_two.err
    assert "OtherOrg/OtherModel" in branch_two.err
    assert "FunAudioLLM/Fun-ASR-Nano-2512" in branch_two.err
    for stream in (branch_two.out, branch_two.err):
        assert "/opt/" not in stream
        assert "archive failed" not in stream
