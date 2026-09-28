"""The operator surface of the configured artifact root (plan Task 4, spec §3, §7, §9).

Tasks 1–3 moved the products, the readers and the retention policy into the library;
this file drives the **CLI** they are reached through.  Every command of spec §9's table
is invoked as an operator invokes it — ``cli.main([...])`` with a real archive root on
disk — so the three things the surface owes are pinned here rather than inferred:

* the flag exists exactly where it is honoured, and the environment fallback loses to
  it (D18, D9);
* a configured root that cannot be used is a **refusal** with exit 1 and a named line,
  rendered before the writer lock, so a doomed invocation leaves no
  ``{archive_root}/coordinator/`` behind (D17, §9);
* retention is the resolved policy the boundary hands down, not a library environment
  read (D15, §7) — and with nothing configured the layout is today's, byte for byte
  (D6, §3.3).

Nothing here reaches the network or a live Bilibili endpoint: the shipped fixtures of
``test_audio`` / ``test_subtitles`` script every transport, and the ASR seam is the
module-level model factory the other CLI suites already stub (``_load_qwen_models``).
"""

from __future__ import annotations

import json
import os

import pytest

from bili_asr import asr as asr_mod
from bili_asr import bili_client as bc
from bili_asr.archive import write_archive
from bili_asr.cli import build_parser, main
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
from test_subtitles import SAMPLE_DOC, nav_ok, player_ok

import _asr_fakes as asr_fakes

#: The word the fixture transcript carries.  The row's title does not contain it, so a
#: hit proves the transcript file was really read from the base the row was written to.
MARKER_TEXT = "artefactmarker"

ARTIFACT_ROOT_ENV = "BILI_ARTIFACT_ROOT"
KEEP_AUDIO_ENV = "BILI_KEEP_AUDIO"

#: The twelve commands that carry the flag: spec §9's eleven in the order the table
#: lists them, then `publish-transcripts`, the iteration's product-writing command.
FLAG_COMMANDS = (
    "asr",
    "pilot",
    "download-audio",
    "run",
    "schedule",
    "campaign",
    "coverage",
    "verify",
    "recover",
    "export",
    "search",
    "publish-transcripts",
)

#: The six commands the flag is deliberately **not** on (D18): none resolves an
#: artifact path, and an accepted-but-ignored flag would be a false statement.
NO_FLAG_COMMANDS = (
    "fetch-meta",
    "status",
    "runs",
    "probe-subs",
    "harvest-subs",
    "derive-manifest",
)

#: The five commands that archive rows and therefore reclaim (spec §7).
RETENTION_COMMANDS = ("asr", "pilot", "run", "schedule", "campaign")


# --------------------------------------------------------------------------- fixtures


def _two_roots(tmp_root: str) -> tuple[str, str]:
    """An archive root (state) and a distinct, existing artifact root (products)."""
    archive = os.path.join(tmp_root, "state")
    artifact = os.path.join(tmp_root, "artifacts")
    os.makedirs(archive)
    os.makedirs(artifact)
    return archive, artifact


def _identity(bvid: str, cid: int = 111):
    return page_identity(bvid, 0, cid, "p0")


def _row(identity, *, status: str = "meta_ok", **extra) -> dict:
    return {
        "bvid": identity.bvid,
        "work_id": identity.work_id,
        "page_index": identity.page_index,
        "page_label": identity.page_label,
        "cid": identity.cid,
        "title": "Fixture",
        "status": status,
        "duration_s": 5,
        "pubdate": 1,
        "pubdate_str": "2026-01-02",
        **extra,
    }


def _publish_bundle(root: str, identity, *, status: str = "archived") -> dict:
    """Publish one complete transcript bundle under ``root`` and return its row fields.

    The recorded strings are the shipped root-relative ones (``transcripts/<stem>/bundle.srt``,
    D7), which is why the same row shape works at either base and only the base list
    decides where it is found.
    """
    row = _row(identity, status=status)
    paths = write_archive(
        root,
        {**row, "status": "archived"},
        [{"start": 0.0, "end": 1.0, "text": MARKER_TEXT}],
        source="cc",
    )
    return {"status": "archived", **paths}


def _publish_audio(root: str, identity) -> dict:
    """Place one row's audio under ``root`` and return the recorded relative string."""
    stem = artifact_stem(identity)
    directory = os.path.join(root, "audio")
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, f"{stem}.m4a"), "wb") as handle:
        handle.write(AUDIO_BYTES)
    return {"audio_path": f"audio/{stem}.m4a"}


def _publish_caption(root: str, identity) -> dict:
    """Place one row's harvested caption document under ``root`` (§2.1's second product)."""
    stem = artifact_stem(identity)
    directory = os.path.join(root, "subtitles", "raw")
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, f"{stem}.json"), "w", encoding="utf-8") as handle:
        json.dump(SAMPLE_DOC, handle)
    return {}


def _write_manifest(archive: str, rows: list[dict]) -> None:
    """Write the manifest — state, and therefore always at the archive root (D13)."""
    store = ManifestStore(root=archive)
    for row in rows:
        store.upsert(row)


def _write_sidecars(archive: str, work_ids: list[str], *, now: str = "2026-01-02T00:00:00Z") -> None:
    """The four operational sidecars `coverage` needs before it reports complete evidence.

    Modeled on ``tests/test_coverage_report.py``'s fixture: a manifest that looks complete
    without operational evidence is not proof of a completed campaign, so a case that
    asserts ``coverage``'s exit status has to write them.  All four are state (D13).
    """
    cursor = {"mid": 23191782, "next_page": 1, "total": len(work_ids), "state": "complete",
              "last_api_error_code": None, "updated_at": now}
    scheduler = {"scope": "all", "limit": len(work_ids), "state": "complete",
                 "processed_work_ids": list(work_ids), "last_api_error_code": None,
                 "allow_long_live": False, "updated_at": now}
    ledger = {"run_id": "run-1", "command": "schedule", "started_at": now,
              "finished_at": now, "exit_code": 0, "mid": 23191782,
              "work_ids": list(work_ids), "pages_fetched": 1,
              "records_fetched": len(work_ids), "records_existing": 0,
              "last_api_error_code": None, "coverage_summary": {"archived": len(work_ids)},
              "cursor_snapshot": cursor}
    attempts = [
        {"stage": "archive", "work_id": work_id, "attempt": 1, "outcome": "ok",
         "error_code": None, "artifact_paths": [], "started_at": now, "finished_at": now}
        for work_id in work_ids
    ]
    with open(os.path.join(archive, "meta-cursor.json"), "w", encoding="utf-8") as handle:
        json.dump(cursor, handle)
    with open(os.path.join(archive, "scheduler.json"), "w", encoding="utf-8") as handle:
        json.dump(scheduler, handle)
    with open(os.path.join(archive, "run-ledger.jsonl"), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(ledger) + "\n")
    os.makedirs(os.path.join(archive, "coordinator"), exist_ok=True)
    with open(os.path.join(archive, "coordinator", "attempts.jsonl"), "w", encoding="utf-8") as handle:
        handle.write("".join(json.dumps(item) + "\n" for item in attempts))


class _FakeModel:
    """Stands in for the FunASR AutoModel the runner builds lazily."""

    def generate(self, **_kwargs):
        return [{"start": 0.0, "end": 1.0, "text": MARKER_TEXT}]


def _stub_asr(monkeypatch) -> None:
    """The D2.5 seam: patch the module-level factory the production site uses."""
    asr_fakes.install(monkeypatch, text=MARKER_TEXT)


def _offline_client(monkeypatch, transport=None) -> None:
    """No live call: every command builds its ``BiliClient`` eagerly, so fake the transport."""
    monkeypatch.setattr(
        bc, "build_default_transport", lambda: transport or RouterTransport({})
    )
    monkeypatch.setattr(bc, "default_sleeper", lambda: (lambda _seconds: None))
    monkeypatch.setattr("bili_asr.cli.time.sleep", lambda _seconds: None)


def _audio_transport() -> RouterTransport:
    """The scripted download path `download-audio` needs (test_cli_asr's fixture)."""
    return RouterTransport(
        {
            "finger/spi": [SPI_OK],
            "nav": [nav_ok(), nav_response()],
            "player/wbi/v2": [player_ok([])],
            "/x/player/wbi/playurl": [playurl_ok()],
        },
        stream_routes={f"{STREAM_HOST}/a30216.m4s": AUDIO_BYTES},
    )


def _archived_json(captured) -> dict:
    return json.loads(captured.out)


def _present(payload: dict, work_id: str):
    return [row["artifact_present"] for row in payload["rows"] if row["work_id"] == work_id][0]


# ------------------------------------------------------- one case per flag-carrying command


def _drive_download_audio(archive, artifact, monkeypatch, capsys):
    identity = _identity("BVdl")
    _write_manifest(archive, [_row(identity, status="needs_audio")])
    _offline_client(monkeypatch, _audio_transport())

    # Manifest-only fixture: pin the rollback source (no archive.db seeded).
    rc = main(["download-audio", "--missing-subs", "--queue-source", "manifest",
               "--archive-root", archive, "--artifact-root", artifact])
    captured = capsys.readouterr()
    stem = artifact_stem(identity)

    assert rc == 0, captured.err
    assert os.path.isfile(os.path.join(artifact, "audio", f"{stem}.m4a"))
    # Negative control: the product did not also land at the archive root.
    assert not os.path.exists(os.path.join(archive, "audio"))


def _drive_asr(archive, artifact, monkeypatch, capsys):
    identity = _identity("BVasr")
    _write_manifest(archive, [{**_row(identity, status="audio_ok"),
                               **_publish_audio(artifact, identity)}])
    _stub_asr(monkeypatch)
    _offline_client(monkeypatch)

    rc = main(["asr", "--pending", "--archive-root", archive, "--artifact-root", artifact])
    captured = capsys.readouterr()

    assert rc == 0, captured.err
    archived = ManifestStore(root=archive).get(identity.work_id)
    assert archived["status"] == "archived"
    assert os.path.isfile(os.path.join(artifact, archived["srt_path"]))
    assert not os.path.exists(os.path.join(archive, "transcripts"))


def _drive_pilot(archive, artifact, monkeypatch, capsys):
    sub = _identity("BVpilotsub")
    aud = _identity("BVpilotaud")
    _write_manifest(archive, [
        {**_row(sub, status="subtitle_done"), **_publish_caption(artifact, sub)},
        {**_row(aud, status="audio_ok"), **_publish_audio(artifact, aud)},
    ])
    _stub_asr(monkeypatch)
    _offline_client(monkeypatch)

    rc = main(["pilot", "--n", "2", "--archive-root", archive, "--artifact-root", artifact])
    captured = capsys.readouterr()

    assert rc == 0, captured.err
    for identity in (sub, aud):
        archived = ManifestStore(root=archive).get(identity.work_id)
        assert archived["status"] == "archived", captured.err
        assert os.path.isfile(os.path.join(artifact, archived["srt_path"]))
    assert not os.path.exists(os.path.join(archive, "transcripts"))


def _drive_run(archive, artifact, monkeypatch, capsys):
    identity = _identity("BVrun")
    _write_manifest(archive, [{**_row(identity, status="audio_ok"),
                               **_publish_audio(artifact, identity)}])
    _stub_asr(monkeypatch)
    _offline_client(monkeypatch)

    rc = main(["run", "--scope", identity.work_id, "--limit", "1",
               "--archive-root", archive, "--artifact-root", artifact])
    captured = capsys.readouterr()

    assert rc == 0, captured.err
    archived = ManifestStore(root=archive).get(identity.work_id)
    assert archived["status"] == "archived"
    assert os.path.isfile(os.path.join(artifact, archived["srt_path"]))
    assert not os.path.exists(os.path.join(archive, "transcripts"))


def _drive_schedule(archive, artifact, monkeypatch, capsys):
    identity = _identity("BVsched")
    _write_manifest(archive, [{**_row(identity, status="audio_ok"),
                               **_publish_audio(artifact, identity)}])
    _stub_asr(monkeypatch)
    _offline_client(monkeypatch)

    rc = main(["schedule", "--scope", identity.work_id, "--limit", "1",
               "--archive-root", archive, "--artifact-root", artifact])
    captured = capsys.readouterr()

    assert rc == 0, captured.err
    archived = ManifestStore(root=archive).get(identity.work_id)
    assert archived["status"] == "archived"
    assert os.path.isfile(os.path.join(artifact, archived["srt_path"]))
    assert not os.path.exists(os.path.join(archive, "transcripts"))
    # The scheduler sidecar is state: it stays at the archive root (D13).
    assert os.path.isfile(os.path.join(archive, "scheduler.json"))


def _drive_campaign(archive, artifact, monkeypatch, capsys):
    identity = _identity("BVcamp")
    _write_manifest(archive, [{**_row(identity, status="audio_ok"),
                               **_publish_audio(artifact, identity)}])
    _stub_asr(monkeypatch)
    _offline_client(monkeypatch)

    rc = main(["campaign", "--scope", identity.work_id, "--limit", "1",
               "--archive-root", archive, "--artifact-root", artifact])
    captured = capsys.readouterr()

    assert rc == 0, captured.err
    archived = ManifestStore(root=archive).get(identity.work_id)
    assert archived["status"] == "archived"
    assert os.path.isfile(os.path.join(artifact, archived["srt_path"]))
    assert not os.path.exists(os.path.join(archive, "transcripts"))
    # The campaign checkpoint is state: it stays at the archive root (D13).
    assert os.path.isfile(os.path.join(archive, "campaign.json"))


def _drive_coverage(archive, artifact, monkeypatch, capsys):
    identity = _identity("BVcov")
    _write_manifest(archive, [{**_row(identity, status="archived"),
                               **_publish_bundle(artifact, identity),
                               **_publish_audio(artifact, identity)}])
    _write_sidecars(archive, [identity.work_id])
    _offline_client(monkeypatch)

    rc = main(["coverage", "--format", "json", "--archive-root", archive,
               "--artifact-root", artifact])
    configured = _archived_json(capsys.readouterr())
    assert rc == 0, configured
    assert _present(configured, identity.work_id) is True

    # Negative control: without the flag the same archive reports the row the way the
    # single-base reader does — the bundle is not at the archive root — and says so.
    rc = main(["coverage", "--format", "json", "--archive-root", archive])
    identity_only = _archived_json(capsys.readouterr())
    assert rc == 1, identity_only
    assert _present(identity_only, identity.work_id) is False
    assert any(
        entry["code"] == "terminal_missing_artifact"
        for entry in identity_only["diagnostics"]
    )


def _drive_verify(archive, artifact, monkeypatch, capsys):
    identity = _identity("BVver")
    _write_manifest(archive, [{**_row(identity, status="archived"),
                               **_publish_bundle(artifact, identity),
                               **_publish_audio(artifact, identity)}])
    _write_sidecars(archive, [identity.work_id])
    _offline_client(monkeypatch)

    rc = main(["verify", "--archive-root", archive, "--artifact-root", artifact])
    configured = _archived_json(capsys.readouterr())
    assert rc == 0, configured
    assert configured["defect_count"] == 0

    rc = main(["verify", "--archive-root", archive])
    identity_only = _archived_json(capsys.readouterr())
    assert rc == 1, identity_only
    assert [defect["work_id"] for defect in identity_only["defects"]] == [identity.work_id]


def _drive_recover(archive, artifact, monkeypatch, capsys):
    identity = _identity("BVrec")
    _write_manifest(archive, [{**_row(identity, status="archived"),
                               **_publish_bundle(artifact, identity),
                               **_publish_audio(artifact, identity)}])
    _write_sidecars(archive, [identity.work_id])
    _offline_client(monkeypatch)

    # `recover` selects the defects `verify` reports, so the flag decides the selection:
    # with it the row is clean and there is nothing to audit...
    rc = main(["recover", "--work-id", identity.work_id, "--archive-root", archive,
               "--artifact-root", artifact])
    configured = _archived_json(capsys.readouterr())
    assert rc == 1
    assert configured["code"] == "recovery_target_not_found"

    # ...without it the same row carries the defect the configured root answers for.
    rc = main(["recover", "--work-id", identity.work_id, "--archive-root", archive])
    identity_only = _archived_json(capsys.readouterr())
    assert rc == 0
    assert identity_only["ok"] is True
    assert identity_only["selected"] == [identity.work_id]


def _drive_export(archive, artifact, monkeypatch, capsys):
    identity = _identity("BVexp")
    _write_manifest(archive, [{**_row(identity, status="archived"),
                               **_publish_bundle(artifact, identity),
                               **_publish_audio(artifact, identity)}])
    _offline_client(monkeypatch)

    main(["export", "--format", "json", "--with-text", "--archive-root", archive,
          "--artifact-root", artifact])
    row = json.loads(capsys.readouterr().out)[0]
    assert row["srt_path"] and row["raw_path"]
    assert MARKER_TEXT in row["transcript_text"]

    # Without the flag the transcript is not under the archive root, so `--with-text`
    # reads nothing: the path columns stay the same relative strings (D7), and the one
    # observable that has to follow the base is the text read.
    main(["export", "--format", "json", "--with-text", "--archive-root", archive])
    assert json.loads(capsys.readouterr().out)[0]["transcript_text"] == ""


def _drive_search(archive, artifact, monkeypatch, capsys):
    identity = _identity("BVsea")
    _write_manifest(archive, [{**_row(identity, status="archived"),
                               **_publish_bundle(artifact, identity),
                               **_publish_audio(artifact, identity)}])
    _offline_client(monkeypatch)

    # The legacy manifest filter (`--status`) drives the manifest-backed index, so
    # `--rebuild` on both runs: `search.db` is a cache, and the point here is which
    # transcripts the index can read, not what an earlier run left in it.  The
    # store-backed default has nothing to index (no store rows in this fixture)
    # and answers exit 0 with an explicit "no hits" line — the exit-contract
    # change pinned in `test_search.py`.
    rc = main(["search", MARKER_TEXT, "--status", "archived", "--rebuild",
               "--archive-root", archive, "--artifact-root", artifact])
    assert rc == 0, capsys.readouterr().err

    rc = main(["search", MARKER_TEXT, "--status", "archived", "--rebuild",
               "--archive-root", archive])
    captured = capsys.readouterr()
    assert rc == 0
    assert "no hits" in captured.out

    # The store-backed default path refuses to read transcripts outside the
    # archive root's store: with only a manifest present it reports the missing
    # index, never the artifact text.
    rc = main(["search", MARKER_TEXT, "--archive-root", archive,
               "--artifact-root", artifact])
    captured = capsys.readouterr()
    assert rc == 0
    assert "index missing" in captured.out


_COMMAND_CASES = {
    "download-audio": _drive_download_audio,
    "asr": _drive_asr,
    "pilot": _drive_pilot,
    "run": _drive_run,
    "schedule": _drive_schedule,
    "campaign": _drive_campaign,
    "coverage": _drive_coverage,
    "verify": _drive_verify,
    "recover": _drive_recover,
    "export": _drive_export,
    "search": _drive_search,
}


@pytest.mark.parametrize("command", list(_COMMAND_CASES))
def test_every_flag_carrying_command_uses_the_configured_artifact_root(
    command, tmp_root, monkeypatch, capsys
):
    """Spec §9's table, one case per command, each with its own negative control.

    The fixture puts every product under the configured root and nothing at the archive
    root, so a command that ignored the flag cannot observe what the case asserts: the
    write would land at the archive root, and the read would find nothing.
    """
    archive, artifact = _two_roots(tmp_root)
    _COMMAND_CASES[command](archive, artifact, monkeypatch, capsys)


# ------------------------------------------------------------------------- the refusals


def _missing_argv(command: str, archive: str, root: str) -> list[str]:
    argv = {
        "download-audio": ["download-audio", "--missing-subs", "--archive-root", archive],
        "coverage": ["coverage", "--archive-root", archive],
    }[command]
    return [*argv, "--artifact-root", root]


@pytest.mark.parametrize("command", ["download-audio", "coverage"])
def test_a_missing_configured_root_is_refused_with_the_pinned_line_and_exit_one(
    command, tmp_root, monkeypatch, capsys
):
    """§9 pins the line; the writer case also pins *when* resolution happens.

    `download-audio` is an ``_ARCHIVE_WRITER_COMMANDS`` member, so its dispatch would
    create ``{archive_root}/coordinator/`` — the lock's documented side effect.  A
    refused invocation must not leave it behind, which is why the resolution sits
    between ``parse_args`` and the lock block rather than inside a handler.
    """
    archive, _artifact = _two_roots(tmp_root)
    missing = os.path.join(tmp_root, "not-mounted")
    _offline_client(monkeypatch)

    rc = main(_missing_argv(command, archive, missing))
    captured = capsys.readouterr()

    assert rc == 1
    assert captured.err == f"{command}: artifact root does not exist ({missing})\n"
    assert not os.path.exists(missing)
    assert not os.path.exists(os.path.join(archive, "coordinator"))


def test_a_file_as_the_artifact_root_is_refused(tmp_root, monkeypatch, capsys):
    """§3.3: nothing can be written below a non-directory, so it is refused as such."""
    archive, _artifact = _two_roots(tmp_root)
    path = os.path.join(tmp_root, "mount.txt")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("not a directory\n")
    _offline_client(monkeypatch)

    rc = main(["coverage", "--archive-root", archive, "--artifact-root", path])
    captured = capsys.readouterr()

    assert rc == 1
    assert captured.err == f"coverage: artifact root is not a directory ({path})\n"


def test_a_symlinked_configured_root_is_refused_with_its_own_tail(tmp_root, monkeypatch, capsys):
    """§3.2/§6: the lexical path is kept, so a symlinked root is refused, never followed."""
    archive, artifact = _two_roots(tmp_root)
    link = os.path.join(tmp_root, "mounted-link")
    os.symlink(artifact, link)
    _offline_client(monkeypatch)

    rc = main(["verify", "--archive-root", archive, "--artifact-root", link])
    captured = capsys.readouterr()

    assert rc == 1
    assert captured.err == f"verify: artifact root is a symlink ({link})\n"


def test_an_existing_but_unopenable_configured_root_is_refused(tmp_root, monkeypatch, capsys):
    """R4 under D17: an existing directory this process cannot open is unusable.

    ``is_dir()`` is a stat, so a root the process may not open passes the type checks and
    then fails every write and every read — the read silently, because a reader drops a
    base it cannot open and answers from the archive root instead.  That is exactly the
    "unusable root masquerading as a usable one" D17 refuses, so the boundary probes the
    operation the writers and readers perform.

    The denial is injected at the probe's syscall: a permission-denied directory is
    indistinguishable from an erroring mount here, and the environment this suite runs in
    is root, for which a mode-000 directory is still openable — so chmod would prove
    nothing on this host.
    """
    archive, artifact = _two_roots(tmp_root)
    real_open = os.open

    def denying_open(path, *args, **kwargs):
        if os.fspath(path) == os.fspath(artifact):
            raise PermissionError(13, "Permission denied")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", denying_open)
    _offline_client(monkeypatch)

    rc = main(["coverage", "--archive-root", archive, "--artifact-root", artifact])
    captured = capsys.readouterr()

    assert rc == 1
    assert captured.err == f"coverage: artifact root cannot be opened ({artifact})\n"


@pytest.mark.parametrize(
    "error",
    [PermissionError(13, "Permission denied"), OSError(5, "Input/output error")],
    ids=["EACCES", "EIO"],
)
def test_a_configured_root_whose_stat_fails_is_refused_with_the_same_tail(
    error, tmp_root, monkeypatch, capsys
):
    """W-1: a root whose *stat* fails is the same input as one this process cannot open.

    ``is_dir()``/``exists()`` are stats, and ``pathlib`` re-raises every ``OSError``
    outside its ignored errnos (ENOENT/ENOTDIR/EBADF/ELOOP): an ``EACCES`` from an
    unsearchable ancestor, or an ``ENOTCONN``/``EIO`` from a dropped FUSE mount, escapes
    the classification and reaches ``main()`` as a bare traceback with **no** refusal
    line — while the fourth line is the one that names exactly that input (§9/D17).

    The failure is injected at the stat seam; the sibling case above injects it at
    ``os.open``, where the stat still succeeds — the two together cover both halves of
    "cannot be opened".  A denied ancestor and a dropped mount are indistinguishable to
    this process, and this suite runs as root, for which a mode-000 directory is still
    statable — so chmod would prove nothing on this host.
    """
    from pathlib import Path

    archive, artifact = _two_roots(tmp_root)
    real_is_dir = Path.is_dir

    def denying_is_dir(self):
        if os.fspath(self) == os.fspath(artifact):
            raise error
        return real_is_dir(self)

    monkeypatch.setattr(Path, "is_dir", denying_is_dir)
    _offline_client(monkeypatch)

    rc = main(["coverage", "--archive-root", archive, "--artifact-root", artifact])
    captured = capsys.readouterr()

    assert rc == 1
    assert captured.err == f"coverage: artifact root cannot be opened ({artifact})\n"


# --------------------------------------------------- precedence, the identity case, unset


def test_the_flag_wins_over_the_environment_variable(tmp_root, monkeypatch, capsys):
    """D9: flag, then environment, then the archive root."""
    archive, flag_root = _two_roots(tmp_root)
    env_root = os.path.join(tmp_root, "env-root")
    os.makedirs(env_root)
    identity = _identity("BVprec")
    _write_manifest(archive, [{**_row(identity, status="archived"),
                               **_publish_bundle(flag_root, identity)}])
    monkeypatch.setenv(ARTIFACT_ROOT_ENV, env_root)
    _offline_client(monkeypatch)

    main(["coverage", "--format", "json", "--archive-root", archive,
          "--artifact-root", flag_root])
    assert _present(_archived_json(capsys.readouterr()), identity.work_id) is True


def test_the_environment_variable_alone_is_enough(tmp_root, monkeypatch, capsys):
    """D9: with no flag the variable decides, and the flag is not required to exist."""
    archive, artifact = _two_roots(tmp_root)
    identity = _identity("BVenv")
    _write_manifest(archive, [{**_row(identity, status="archived"),
                               **_publish_bundle(artifact, identity)}])
    monkeypatch.setenv(ARTIFACT_ROOT_ENV, artifact)
    _offline_client(monkeypatch)

    main(["coverage", "--format", "json", "--archive-root", archive])
    assert _present(_archived_json(capsys.readouterr()), identity.work_id) is True


def test_a_blank_environment_value_falls_through_to_the_archive_root(tmp_root, monkeypatch, capsys):
    """§3.2's blank rule: ``export BILI_ARTIFACT_ROOT=`` must not shadow the real layout.

    A whitespace-only value counts as *unset*, so the run is the identity one.  Treating
    it as a path instead would resolve to a directory that does not exist and refuse.
    """
    archive, _artifact = _two_roots(tmp_root)
    identity = _identity("BVblank")
    _write_manifest(archive, [{**_row(identity, status="archived"),
                               **_publish_bundle(archive, identity)}])
    monkeypatch.setenv(ARTIFACT_ROOT_ENV, "   ")
    _offline_client(monkeypatch)

    rc = main(["coverage", "--format", "json", "--archive-root", archive])
    captured = capsys.readouterr()

    # The row resolves and no refusal was rendered: had the blank been taken as a path,
    # it would have resolved to a directory that does not exist and refused with exit 1.
    assert "artifact root" not in captured.err, captured.err
    assert _present(_archived_json(captured), identity.work_id) is True


def test_unset_reproduces_todays_layout_byte_for_byte(tmp_root, monkeypatch, capsys):
    """Compass §4: with nothing configured, every artifact and every manifest line is today's.

    The two archives hold the same row and differ in exactly one thing — whether the
    redundant ``--artifact-root <archive-root>`` flag was passed — so identical manifest
    bytes are what "an explicit no-op is a no-op" (§3.3) means observably.
    """
    monkeypatch.delenv(ARTIFACT_ROOT_ENV, raising=False)
    identity = _identity("BVlayout")
    stem = artifact_stem(identity)
    layouts = []
    for label, extra in (("unset", False), ("identity", True)):
        archive = os.path.join(tmp_root, label)
        os.makedirs(archive)
        _write_manifest(archive, [_row(identity, status="needs_audio")])
        _offline_client(monkeypatch, _audio_transport())

        argv = ["download-audio", "--missing-subs", "--queue-source", "manifest",
                "--archive-root", archive]
        if extra:
            argv += ["--artifact-root", archive]
        assert main(argv) == 0, capsys.readouterr().err

        assert os.path.isfile(os.path.join(archive, "audio", f"{stem}.m4a"))
        with open(os.path.join(archive, "manifest", "manifest.jsonl"), "rb") as handle:
            layouts.append(handle.read())

    assert layouts[0] == layouts[1]
    assert b"audio/" in layouts[0]


def test_an_explicit_flag_equal_to_the_archive_root_is_not_refused(tmp_root, monkeypatch, capsys):
    """§3.3's identity row: a value equal to the archive root is accepted, not validated.

    A *missing* archive root is therefore not an artifact-root refusal either — the flag
    named the archive root, so there is no second root to refuse.
    """
    archive, _artifact = _two_roots(tmp_root)
    identity = _identity("BVidentity")
    _write_manifest(archive, [{**_row(identity, status="archived"),
                               **_publish_bundle(archive, identity)}])
    _offline_client(monkeypatch)

    main(["coverage", "--format", "json", "--archive-root", archive, "--artifact-root", archive])
    configured = _archived_json(capsys.readouterr())
    main(["coverage", "--format", "json", "--archive-root", archive])
    unset = _archived_json(capsys.readouterr())

    assert configured == unset

    missing = os.path.join(tmp_root, "absent-archive")
    rc = main(["verify", "--archive-root", missing, "--artifact-root", missing])
    captured = capsys.readouterr()
    assert rc == 1
    assert "artifact root" not in captured.err


# --------------------------------------------------------------------- retention (§7, D15)


def _retention_case(archive: str, artifact: str, monkeypatch, argv: list[str]) -> bool:
    """Archive one ``audio_ok`` row under the configured root; report whether audio stayed."""
    identity = _identity("BVkeep")
    _write_manifest(archive, [{**_row(identity, status="audio_ok"),
                               **_publish_audio(artifact, identity)}])
    _stub_asr(monkeypatch)
    _offline_client(monkeypatch)

    assert main([*argv, "--archive-root", archive, "--artifact-root", artifact]) == 0
    archived = ManifestStore(root=archive).get(identity.work_id)
    assert archived["status"] == "archived"
    return os.path.isfile(os.path.join(artifact, archived["audio_path"]))


def test_keep_audio_defaults_to_retain_and_no_keep_audio_reclaims(
    tmp_root, monkeypatch, capsys
):
    """D5/D15: the default flipped to retain, and reclaim is the opt-in it now is."""
    monkeypatch.delenv(KEEP_AUDIO_ENV, raising=False)
    assert _retention_case(*_two_roots(tmp_root), monkeypatch, ["asr", "--pending"]) is True

    other = os.path.join(tmp_root, "opt-in")
    os.makedirs(other)
    assert (
        _retention_case(*_two_roots(other), monkeypatch, ["asr", "--pending", "--no-keep-audio"])
        is False
    )


@pytest.mark.parametrize(
    "flag,env,retained",
    [
        ([], None, True),      # default: retain (the user-locked flip)
        ([], "1", True),       # the documented keep value
        ([], "0", False),      # the documented reclaim value
        ([], "", True),        # blank is not "1" or "0" -> default
        ([], " 1 ", True),     # §7's second changed case: not a literal "1" -> default
        ([], "yes", True),     # anything else -> default
        (["--keep-audio"], "0", True),     # the flag wins over a reclaim value
        (["--no-keep-audio"], "1", False),  # the flag wins over a keep value
    ],
)
def test_keep_audio_env_precedence_table(flag, env, retained, tmp_root, monkeypatch, capsys):
    """§7's precedence: the flag, else ``1``/``0``, else the default."""
    if env is None:
        monkeypatch.delenv(KEEP_AUDIO_ENV, raising=False)
    else:
        monkeypatch.setenv(KEEP_AUDIO_ENV, env)
    archive, artifact = _two_roots(tmp_root)

    assert _retention_case(archive, artifact, monkeypatch, ["asr", "--pending", *flag]) is retained


@pytest.mark.parametrize("command", RETENTION_COMMANDS)
def test_the_retention_pair_reaches_reclaim_on_every_command_that_reclaims(
    command, tmp_root, monkeypatch, capsys
):
    """§7 + R1: the pair is honoured wherever ``reclaim_audio`` is reached, `campaign` included.

    ``campaign`` is the case the plan had to rule on: its retention flag is honoured only
    through ``CampaignRunner``, the sole path to the coordinator's own reclaim — a runner
    that dropped the value would leave the documented flag silently inert while the other
    four commands still reclaimed correctly.
    """
    monkeypatch.delenv(KEEP_AUDIO_ENV, raising=False)
    archive, artifact = _two_roots(tmp_root)
    aud = _identity("BVreclaim")
    rows = [{**_row(aud, status="audio_ok"), **_publish_audio(artifact, aud)}]
    if command == "pilot":
        # The pilot states its own branch coverage, so both branches have to exist.
        sub = _identity("BVreclaimsub")
        rows.append({**_row(sub, status="subtitle_done"), **_publish_caption(artifact, sub)})
    _write_manifest(archive, rows)
    _stub_asr(monkeypatch)
    _offline_client(monkeypatch)

    argv = {
        "asr": ["asr", "--pending"],
        "pilot": ["pilot", "--n", "2"],
        "run": ["run", "--scope", aud.work_id, "--limit", "1"],
        "schedule": ["schedule", "--scope", aud.work_id, "--limit", "1"],
        "campaign": ["campaign", "--scope", aud.work_id, "--limit", "1"],
    }[command]
    rc = main([*argv, "--no-keep-audio", "--archive-root", archive,
               "--artifact-root", artifact])
    captured = capsys.readouterr()

    assert rc == 0, captured.err
    archived = ManifestStore(root=archive).get(aud.work_id)
    assert archived["status"] == "archived"
    assert archived["audio_path"]
    assert not os.path.exists(os.path.join(artifact, archived["audio_path"]))


# ------------------------------------------------- the resolution step's own guards (M1)


@pytest.mark.parametrize(
    "env,expected",
    [(None, True), ("0", False)],  # unset -> the default (retain); "0" -> reclaim
)
def test_retention_resolves_without_the_artifact_root_flag(
    env, expected, tmp_root, monkeypatch
):
    """The retention resolution must not be nested under the artifact-root guard.

    A command that carried the pair without ``--artifact-root`` would leave
    ``args.keep_audio`` as ``None`` — falsy at ``reclaim_audio``'s ``if keep:`` — so it
    would reclaim while the row's default is retain.  No shipped command has that shape
    (the five retention commands all carry both flags), which is why the shape is
    synthesized at the parser seam: the namespace carries ``keep_audio`` and no
    ``artifact_root``, so this case fails if the resolution stops having its own guard.
    """
    if env is None:
        monkeypatch.delenv(KEEP_AUDIO_ENV, raising=False)
    else:
        monkeypatch.setenv(KEEP_AUDIO_ENV, env)
    namespace = build_parser().parse_args(["status", "--archive-root", tmp_root])
    namespace.keep_audio = None
    assert not hasattr(namespace, "artifact_root")

    class _KeepOnlyParser:
        def parse_args(self, _argv):
            return namespace

    monkeypatch.setattr("bili_asr.cli.build_parser", lambda: _KeepOnlyParser())
    monkeypatch.setattr("bili_asr.cli._dispatch_command", lambda _args: 0)

    assert main([]) == 0
    assert namespace.keep_audio is expected


# --------------------------------------------------------- the budget skip line (Q1)


def test_the_run_budget_skip_line_names_the_flag_that_lifts_it(
    tmp_root, monkeypatch, capsys
):
    """Q1: the run path carries the same ``--max-audio-gb 0`` clause as the pilot's line.

    ``run`` prints one skip line for every reason, so the clause rides on the budget
    reason alone.  The transport is unrouted on purpose: the skip has to happen before
    any request, so a download attempt would fail this case rather than pass it.
    """
    archive, artifact = _two_roots(tmp_root)
    identity = _identity("BVbudget")
    _write_manifest(archive, [_row(identity, status="needs_audio", duration_s=600)])
    _offline_client(monkeypatch, RouterTransport({}))

    rc = main(["run", "--scope", identity.work_id, "--limit", "1",
               "--archive-root", archive, "--artifact-root", artifact,
               "--max-audio-gb", "1e-9"])
    captured = capsys.readouterr()

    assert rc == 1
    assert f"run: {identity.work_id}: skipped (audio_budget)" in captured.out
    assert "--max-audio-gb 0 = unlimited" in captured.out
    assert not os.path.exists(os.path.join(artifact, "audio"))


# --------------------------------------------------------------- the excluded commands


@pytest.mark.parametrize("command", NO_FLAG_COMMANDS)
def test_the_flag_is_absent_from_the_commands_that_do_not_touch_artifacts(command, capsys):
    """D18: the flag exists only where it is honoured — the six excluded commands refuse it."""
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args([command, "--help"])
    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    assert "--artifact-root" not in help_text
    assert "--keep-audio" not in help_text

    with pytest.raises(SystemExit) as exc:
        main([command, "--archive-root", "archive", "--artifact-root", "elsewhere"])
    assert exc.value.code == 1
    assert "unrecognized arguments" in capsys.readouterr().err


@pytest.mark.parametrize(
    "command", [name for name in FLAG_COMMANDS if name not in RETENTION_COMMANDS]
)
def test_the_retention_pair_is_absent_from_the_commands_that_never_reclaim(command, capsys):
    """Spec §7: only the five commands that archive rows carry the retention pair."""
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args([command, "--help"])
    assert exc.value.code == 0
    assert "--keep-audio" not in capsys.readouterr().out


# ------------------------------------------------------------- the readers agree (§10)


def test_coverage_reports_the_same_inventory_with_and_without_the_root(
    tmp_root, monkeypatch, capsys
):
    """§10: an archive whose artifacts are already where they belong reports identically.

    This is the legacy half of the reader promise — the rows were written under the
    archive root before any root was configured — and it is the case an operator with an
    existing archive meets on day one.  Both runs exit 0, so the comparison is between two
    successful reports rather than between a report and a diagnostic.
    """
    archive, artifact = _two_roots(tmp_root)
    identities = [_identity("BVagree1", 111), _identity("BVagree2", 222)]
    rows = []
    for identity in identities:
        rows.append({
            **_row(identity, status="archived"),
            **_publish_bundle(archive, identity),
            **_publish_audio(archive, identity),
        })
    _write_manifest(archive, rows)
    _write_sidecars(archive, [identity.work_id for identity in identities])
    _offline_client(monkeypatch)

    rc = main(["coverage", "--format", "json", "--archive-root", archive])
    without_root = _archived_json(capsys.readouterr())
    rc_configured = main(["coverage", "--format", "json", "--archive-root", archive,
                          "--artifact-root", artifact])
    with_root = _archived_json(capsys.readouterr())

    assert rc == 0 and rc_configured == 0
    assert with_root == without_root
    assert {row["work_id"]: row["artifact_present"] for row in with_root["rows"]} == {
        identity.work_id: True for identity in identities
    }
    assert with_root["diagnostics"] == []


def test_pilot_archives_a_row_whose_audio_is_still_at_the_archive_root(
    tmp_root, monkeypatch, capsys
):
    """D6/§10 inside the pilot's ASR stage: the recorded copy may predate the root.

    The row records the shipped root-relative ``audio/<stem>.m4a``, and it was written
    before the root was configured — so the file is at the **archive root** while the
    publish goes to the configured one.  The stage reads the value through both bases
    (D8) and must then re-confine it against the base that actually holds it: deriving
    the recorded form from ``write_base`` alone yields a ``..``-bearing string, the
    audio guard refuses it, and the row fails instead of archiving.

    The negative control is the artifact-root copy (``_drive_pilot``, the shipped
    case): the same recorded string with the bytes under the configured root, which
    pins that the fix does not simply resolve the pair the other way round.

    A second, subtitle-branch row rides along because ``pilot`` states its own branch
    coverage and exits 1 on an audio-only selection — the row under test is still the
    legacy one, and its verdict is what this case asserts.
    """
    archive, artifact = _two_roots(tmp_root)
    identity = _identity("BVlegacy")
    sub = _identity("BVlegacysub")
    recorded = _publish_audio(archive, identity)
    _write_manifest(archive, [
        {**_row(identity, status="audio_ok"), **recorded},
        {**_row(sub, status="subtitle_done"), **_publish_caption(artifact, sub)},
    ])
    _stub_asr(monkeypatch)
    _offline_client(monkeypatch)

    rc = main(["pilot", "--n", "2", "--archive-root", archive,
               "--artifact-root", artifact])
    captured = capsys.readouterr()

    assert rc == 0, captured.err
    archived = ManifestStore(root=archive).get(identity.work_id)
    assert archived["status"] == "archived"
    # The recorded value keeps the shipped spelling, whichever base held the bytes.
    assert archived["audio_path"] == recorded["audio_path"]
    # The transcript is a product, so it lands under the configured root (D7/§4).
    assert os.path.isfile(os.path.join(artifact, archived["srt_path"]))
    # Nothing is moved or copied: the legacy copy stays where the row recorded it (D12).
    assert os.path.isfile(os.path.join(archive, recorded["audio_path"]))


def _drive_pilot_download_branch(tmp_root, monkeypatch, capsys, *, bvid, at_archive):
    """Drive one ``needs_audio`` row through the pilot's **download** branch.

    The row records no ``audio_path``, so the stage takes the download branch and the
    downloader's resumability fast path hands it the copy already on disk.  ``at_archive``
    puts that copy at the archive root — the legacy shape (D6), which the downloader finds
    over ``read_bases()`` while the write base does not hold it — and the case without it is
    the shipped shape, where the write base holds the bytes.

    A second, subtitle-branch row rides along because ``pilot`` states its own branch
    coverage and exits 1 on an audio-only selection — the row under test is still the
    audio one, and its verdict is what the two cases assert.
    """
    archive, artifact = _two_roots(
        os.path.join(tmp_root, "legacy" if at_archive else "configured")
    )
    identity = _identity(bvid)
    sub = _identity(bvid + "sub")
    recorded = _publish_audio(archive if at_archive else artifact, identity)
    _write_manifest(archive, [
        # No `audio_path`: the status alone decides the branch (`existing_rel` is None).
        _row(identity, status="needs_audio"),
        {**_row(sub, status="subtitle_done"), **_publish_caption(artifact, sub)},
    ])
    _stub_asr(monkeypatch)
    # No transport route at all: only the on-disk fast path may serve this row.
    _offline_client(monkeypatch)

    rc = main(["pilot", "--n", "2", "--archive-root", archive,
               "--artifact-root", artifact])
    return archive, artifact, identity, recorded, rc, capsys.readouterr()


def test_pilot_archives_a_needs_audio_row_whose_audio_is_at_the_archive_root(
    tmp_root, monkeypatch, capsys
):
    """D6/§10 on the pilot's **download** branch: the base that *holds* the return wins.

    ``audio._existing_audio`` walks ``roots.read_bases()`` and ``download_audio`` returns
    that hit verbatim (its resumability fast path), so with a configured root the stage is
    handed an **archive-root** file for a row whose status is not ``audio_ok``.  Measuring
    that return against ``write_base`` alone refuses a product that exists: the first pass
    reports ``failed=1`` plus a false ``missing branch coverage: audio-asr`` line and
    publishes no bundle, and the row archives only on a re-run, once ``_mark_audio_ok`` has
    recorded ``audio_ok``.  ``write_base`` still decides where a *write* goes.

    The negative control is the configured-root case below — the same branch with the bytes
    under the configured root — which pins that the base is chosen, not inverted.
    """
    archive, artifact, identity, recorded, rc, captured = _drive_pilot_download_branch(
        tmp_root, monkeypatch, capsys, bvid="BVdlload", at_archive=True
    )

    assert rc == 0, captured.err
    assert "missing branch coverage" not in captured.err
    # `failed` is appended only when non-zero, so this exact line is a clean first pass.
    assert "pilot batch branches: subtitle=1, audio-asr=1" in captured.out, captured.out
    archived = ManifestStore(root=archive).get(identity.work_id)
    assert archived["status"] == "archived"
    # The recorded value keeps the shipped spelling, whichever base held the bytes (D7).
    assert archived["audio_path"] == recorded["audio_path"]
    # The transcript is a product, so it lands under the configured root (D7/§4).
    assert os.path.isfile(os.path.join(artifact, archived["srt_path"]))
    # Nothing is moved or copied: the legacy copy stays where it was found (D12).
    assert os.path.isfile(os.path.join(archive, recorded["audio_path"]))


def test_pilot_archives_a_needs_audio_row_whose_audio_is_at_the_configured_root(
    tmp_root, monkeypatch, capsys
):
    """The negative control for the download branch's base: the shipped shape still holds.

    Same row, same recorded spelling, same branch — only the base holding the bytes moves to
    the configured root, so ``write_base`` is the base that holds the return, exactly what
    the branch measured before the fix.  A case that pinned only the legacy direction would
    also pass for a fix that resolved the pair backwards.
    """
    archive, artifact, identity, recorded, rc, captured = _drive_pilot_download_branch(
        tmp_root, monkeypatch, capsys, bvid="BVdlconf", at_archive=False
    )

    assert rc == 0, captured.err
    assert "pilot batch branches: subtitle=1, audio-asr=1" in captured.out, captured.out
    archived = ManifestStore(root=archive).get(identity.work_id)
    assert archived["status"] == "archived"
    assert archived["audio_path"] == recorded["audio_path"]
    assert os.path.isfile(os.path.join(artifact, archived["srt_path"]))
    # Reading the configured root does not create the legacy location as a side effect.
    assert not os.path.exists(os.path.join(archive, "audio"))
