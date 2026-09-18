"""RunCoordinator + `bili-asr run` (Task 1): fake transport + stubbed ASR.

No live HTTP: RouterTransport scripts every response; transcribe is
monkeypatched to a deterministic stub.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from bili_asr import asr as asr_mod
from bili_asr import coordinator
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
    class FakeModel:
        def generate(self, **kwargs):
            if calls is not None:
                calls.append(kwargs["input"])
            return [{"text": "asr-text", "timestamp": [[0, 1000]]}]

    monkeypatch.setattr(asr_mod, "_load_default_model", lambda **_kwargs: FakeModel())


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




def test_recover_defect_code_expansion_fails_before_audit_write(tmp_root):
    from bili_asr.integrity import IntegrityVerifier, RETRYABLE_INCOMPLETE, RECOVERY_TARGET_LIMIT_EXCEEDED
    store = ManifestStore(root=tmp_root)
    for index in range(101):
        ident = page_identity(f"BV{index}", 0, index + 1, "p0")
        store.upsert(_row(ident, status="pending"))
    AttemptLedger(tmp_root).append({"stage": "harvest", "work_id": "BV0:p0", "attempt": 1,
        "outcome": "ok", "error_code": None, "artifact_paths": [],
        "started_at": "2026-08-28T00:00:00Z", "finished_at": "2026-08-28T00:00:01Z"})
    result = IntegrityVerifier.recover(tmp_root, defect_codes=[RETRYABLE_INCOMPLETE])
    assert result == {"ok": False, "code": RECOVERY_TARGET_LIMIT_EXCEEDED, "selected": []}
    assert not (Path(tmp_root) / "coordinator" / "recovery-audit.jsonl").exists()


def test_recover_rejects_invalid_limit_without_writing(tmp_root):
    from bili_asr.integrity import IntegrityVerifier, RECOVERY_TARGET_LIMIT_EXCEEDED
    ident = page_identity("BVlimit", 0, 1, "p0")
    ManifestStore(root=tmp_root).upsert(_row(ident, status="pending"))
    AttemptLedger(tmp_root).append({"stage": "harvest", "work_id": ident.work_id, "attempt": 1,
        "outcome": "ok", "error_code": None, "artifact_paths": [],
        "started_at": "2026-08-28T00:00:00Z", "finished_at": "2026-08-28T00:00:01Z"})
    result = IntegrityVerifier.recover(tmp_root, work_ids=[ident.work_id], limit=0)
    assert result["ok"] is False and result["code"] == RECOVERY_TARGET_LIMIT_EXCEEDED
    assert not (Path(tmp_root) / "coordinator" / "recovery-audit.jsonl").exists()


def test_recover_fails_closed_on_malformed_or_oversize_audit(tmp_root):
    from bili_asr.integrity import IntegrityVerifier, RECOVERY_MALFORMED_SIDECAR, _AUDIT_REL_PATH, _AUDIT_MAX_BYTES
    ident = page_identity("BVsidecar", 0, 1, "p0")
    ManifestStore(root=tmp_root).upsert(_row(ident, status="pending"))
    AttemptLedger(tmp_root).append({"stage": "harvest", "work_id": ident.work_id, "attempt": 1,
        "outcome": "ok", "error_code": None, "artifact_paths": [],
        "started_at": "2026-08-28T00:00:00Z", "finished_at": "2026-08-28T00:00:01Z"})
    audit_path = Path(tmp_root) / _AUDIT_REL_PATH
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text("{bad}\n", encoding="utf-8")
    before = audit_path.read_bytes()
    result = IntegrityVerifier.recover(tmp_root, work_ids=[ident.work_id])
    assert result["ok"] is False and result["code"] == RECOVERY_MALFORMED_SIDECAR
    assert audit_path.read_bytes() == before
    audit_path.write_bytes(b"x" * (_AUDIT_MAX_BYTES + 1))
    result = IntegrityVerifier.recover(tmp_root, work_ids=[ident.work_id])
    assert result["ok"] is False and result["code"] == RECOVERY_MALFORMED_SIDECAR


def test_recover_rejects_unterminated_audit_at_exact_byte_boundary(tmp_root, monkeypatch):
    from bili_asr.integrity import IntegrityVerifier, RECOVERY_MALFORMED_SIDECAR, _AUDIT_REL_PATH

    ident = page_identity("BVboundary", 0, 1, "p0")
    ManifestStore(root=tmp_root).upsert(_row(ident, status="pending"))
    AttemptLedger(tmp_root).append({"stage": "harvest", "work_id": ident.work_id, "attempt": 1,
        "outcome": "ok", "error_code": None, "artifact_paths": [],
        "started_at": "2026-08-28T00:00:00Z", "finished_at": "2026-08-28T00:00:01Z"})
    audit_path = Path(tmp_root) / _AUDIT_REL_PATH
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    existing_record = {"action": "audit", "work_ids": ["prior"],
                       "defect_codes": ["retryable_incomplete"]}
    existing = json.dumps(existing_record, sort_keys=True).encode("utf-8")
    new_record = {"action": "audit", "work_ids": [ident.work_id],
                  "defect_codes": ["retryable_incomplete"]}
    line_bytes = (json.dumps(new_record, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    audit_path.write_bytes(existing)
    monkeypatch.setattr("bili_asr.integrity._AUDIT_MAX_BYTES", len(existing) + len(line_bytes))
    before = audit_path.read_bytes()

    result = IntegrityVerifier.recover(tmp_root, work_ids=[ident.work_id])

    assert result["ok"] is False and result["code"] == RECOVERY_MALFORMED_SIDECAR
    assert audit_path.read_bytes() == before
    assert not audit_path.with_name(audit_path.name + ".tmp").exists()
    assert not audit_path.with_name(audit_path.name + ".rollback").exists()


def test_recover_rolls_back_when_directory_fsync_fails(tmp_root, monkeypatch):
    from bili_asr.integrity import IntegrityVerifier, RECOVERY_MALFORMED_SIDECAR, _AUDIT_REL_PATH

    ident = page_identity("BVfsync", 0, 1, "p0")
    ManifestStore(root=tmp_root).upsert(_row(ident, status="pending"))
    AttemptLedger(tmp_root).append({"stage": "harvest", "work_id": ident.work_id, "attempt": 1,
        "outcome": "ok", "error_code": None, "artifact_paths": [],
        "started_at": "2026-08-28T00:00:00Z", "finished_at": "2026-08-28T00:00:01Z"})
    audit_path = Path(tmp_root) / _AUDIT_REL_PATH
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    before = b'{"action":"requeue","defect_codes":["retryable_incomplete"],"work_ids":["prior"]}\n'
    audit_path.write_bytes(before)
    monkeypatch.setattr("bili_asr.integrity._fsync_directory", lambda _directory: (_ for _ in ()).throw(OSError("injected")))

    result = IntegrityVerifier.recover(tmp_root, work_ids=[ident.work_id])

    assert result["ok"] is False and result["code"] == RECOVERY_MALFORMED_SIDECAR
    assert audit_path.read_bytes() == before
    assert not audit_path.with_name(audit_path.name + ".tmp").exists()
    assert not audit_path.with_name(audit_path.name + ".rollback").exists()


def test_recover_rejects_oversized_existing_audit_record(tmp_root):
    from bili_asr.integrity import IntegrityVerifier, RECOVERY_MALFORMED_SIDECAR, _AUDIT_REL_PATH
    ident = page_identity("BVlogical", 0, 1, "p0")
    ManifestStore(root=tmp_root).upsert(_row(ident, status="pending"))
    AttemptLedger(tmp_root).append({"stage": "harvest", "work_id": ident.work_id, "attempt": 1,
        "outcome": "ok", "error_code": None, "artifact_paths": [],
        "started_at": "2026-08-28T00:00:00Z", "finished_at": "2026-08-28T00:00:01Z"})
    audit_path = Path(tmp_root) / _AUDIT_REL_PATH
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    oversized = {"action": "audit", "work_ids": [f"work-{index}" for index in range(101)],
                 "defect_codes": ["retryable_incomplete"]}
    audit_path.write_text(json.dumps(oversized) + "\n", encoding="utf-8")
    before = audit_path.read_bytes()
    result = IntegrityVerifier.recover(tmp_root, work_ids=[ident.work_id])
    assert result["ok"] is False and result["code"] == RECOVERY_MALFORMED_SIDECAR
    assert audit_path.read_bytes() == before


def test_recover_audits_named_defect_without_manifest_or_transcript_mutation(tmp_root, capsys):
    from bili_asr.integrity import IntegrityVerifier, MISSING_TRANSCRIPT, _AUDIT_LOCK_REL_PATH
    ident = page_identity("BVrecover", 0, 111, "p0")
    store = ManifestStore(root=tmp_root)
    row = _row(ident, status="archived")
    stem = artifact_stem(ident)
    row.update({"srt_path": f"transcripts/srt/{stem}.srt", "txt_path": f"transcripts/txt/{stem}.txt",
                "md_path": f"transcripts/md/2026-01-02_{stem}_clip.md"})
    store.upsert(row)
    AttemptLedger(tmp_root).append({
        "stage": "archive",
        "work_id": ident.work_id,
        "attempt": 1,
        "outcome": "ok",
        "error_code": None,
        "artifact_paths": [],
        "started_at": "2026-08-28T00:00:00Z",
        "finished_at": "2026-08-28T00:00:01Z",
    })
    for directory, filename, content in (("srt", f"{stem}.srt", "1\n00:00:00,000 --> 00:00:01,000\nok"),
                                          ("txt", f"{stem}.txt", "ok"),):
        path = os.path.join(tmp_root, "transcripts", directory)
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, filename), "w", encoding="utf-8") as handle:
            handle.write(content)
    result = IntegrityVerifier().verify(tmp_root)
    assert any(defect.work_id == ident.work_id and defect.code == MISSING_TRANSCRIPT
               for defect in result.defects)
    manifest_path = os.path.join(tmp_root, "manifest", "manifest.jsonl")
    before = open(manifest_path, encoding="utf-8").read()
    result = IntegrityVerifier.recover(tmp_root, work_ids=[ident.work_id])
    assert result["ok"] is True
    assert result["selected"] == [ident.work_id]
    assert open(manifest_path, encoding="utf-8").read() == before
    audit = open(os.path.join(tmp_root, "coordinator", "recovery-audit.jsonl"), encoding="utf-8").read()
    audit_record = json.loads(audit)
    assert set(audit_record) == {"action", "defect_codes", "work_ids"}
    assert audit_record["action"] == "audit"
    assert audit_record["defect_codes"] == [MISSING_TRANSCRIPT]
    assert audit_record["work_ids"] == [ident.work_id]
    assert (Path(tmp_root) / _AUDIT_LOCK_REL_PATH).is_file()
    assert "https://" not in audit and "SESSDATA" not in audit

def test_recover_rejects_invalid_existing_audit_fields_without_replacement(tmp_root):
    from bili_asr.integrity import (
        IntegrityVerifier,
        RECOVERY_MALFORMED_SIDECAR,
        _AUDIT_REL_PATH,
        _AUDIT_MAX_FIELD_CHARS,
    )

    ident = page_identity("BVinvalid", 0, 1, "p0")
    ManifestStore(root=tmp_root).upsert(_row(ident, status="pending"))
    AttemptLedger(tmp_root).append({"stage": "harvest", "work_id": ident.work_id, "attempt": 1,
        "outcome": "ok", "error_code": None, "artifact_paths": [],
        "started_at": "2026-08-28T00:00:00Z", "finished_at": "2026-08-28T00:00:01Z"})
    audit_path = Path(tmp_root) / _AUDIT_REL_PATH
    audit_path.parent.mkdir(parents=True, exist_ok=True)

    invalid_records = [
        {"action": "audit", "work_ids": [ident.work_id],
         "defect_codes": ["retryable_incomplete"], "extra": "rejected"},
        {"action": "audit", "work_ids": ["Cookie: secret"],
         "defect_codes": ["retryable_incomplete"]},
        {"action": "audit", "work_ids": ["x" * (_AUDIT_MAX_FIELD_CHARS + 1)],
         "defect_codes": ["retryable_incomplete"]},
    ]
    for record in invalid_records:
        audit_path.write_text(json.dumps(record) + "\n", encoding="utf-8")
        before = audit_path.read_bytes()
        result = IntegrityVerifier.recover(tmp_root, work_ids=[ident.work_id])
        assert result["ok"] is False and result["code"] == RECOVERY_MALFORMED_SIDECAR
        assert audit_path.read_bytes() == before
        assert not audit_path.with_name(audit_path.name + ".tmp").exists()


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


# ------------------------------------------------------------ ASR runner binding

def test_run_batch_default_runner_is_lazy_reused_and_batch_scoped(tmp_root, monkeypatch):
    identities = [page_identity(f"BVbind{index}", 0, index + 1, "p0") for index in range(2)]
    store = ManifestStore(root=tmp_root)
    for ident in identities:
        store.upsert(_row(ident, status="audio_ok"))
        audio_dir = Path(tmp_root) / "audio"
        audio_dir.mkdir(exist_ok=True)
        (audio_dir / f"{artifact_stem(ident)}.m4a").write_bytes(b"fixture")
    model_constructions = []
    constructed_models = []
    class FakeModel:
        def generate(self, **_kwargs):
            return [{"text": "ok", "timestamp": [[0, 1000]]}]
    def fake_factory(**kwargs):
        model_constructions.append(dict(kwargs))
        model = FakeModel()
        constructed_models.append(model)
        return model
    monkeypatch.setattr(coordinator.asr_module, "_load_default_model", fake_factory)
    runner = RunCoordinator(tmp_root, store, offline=True)
    runner.run_batch([(i.work_id, store.get(i.work_id)) for i in identities])
    assert len(model_constructions) == 1
    assert runner.asr_runner is None
    assert len(constructed_models) == 1
    runner.run_batch([(identities[0].work_id, store.get(identities[0].work_id))])
    assert len(model_constructions) == 1


def test_run_batch_releases_coordinator_owned_runner_after_exception(tmp_root, monkeypatch):
    runner = RunCoordinator(tmp_root, ManifestStore(root=tmp_root), offline=True)

    class OwnedRunner:
        def __init__(self, *args, **kwargs):
            self.release_calls = 0

        def release(self):
            self.release_calls += 1

    owned_runner = OwnedRunner()
    monkeypatch.setattr(coordinator.asr_module, "ASRRunner", lambda *args, **kwargs: owned_runner)

    def fail_after_creating_runner(_rows):
        runner.asr_runner = coordinator.asr_module.ASRRunner()
        raise RuntimeError("batch failed")

    monkeypatch.setattr(runner, "_run_batch_locked", fail_after_creating_runner)

    import pytest

    with pytest.raises(RuntimeError, match="batch failed"):
        runner.run_batch([])

    assert owned_runner.release_calls == 1
    assert runner.asr_runner is None


def test_run_batch_keeps_injected_runner_caller_owned(tmp_root, monkeypatch):
    class InjectedRunner:
        def __init__(self):
            self.release_calls = 0

        def release(self):
            self.release_calls += 1

    injected_runner = InjectedRunner()
    runner = RunCoordinator(
        tmp_root,
        ManifestStore(root=tmp_root),
        offline=True,
        asr_runner=injected_runner,
    )
    monkeypatch.setattr(runner, "_run_batch_locked", lambda _rows: coordinator.RunSummary())

    runner.run_batch([])

    assert injected_runner.release_calls == 0
    assert runner.asr_runner is injected_runner


def test_run_batch_subtitle_first_does_not_construct_runner(tmp_root, monkeypatch):
    ident = page_identity("BVsubtitle", 0, 1, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(ident, status="subtitle_done"))
    monkeypatch.setattr(coordinator.asr_module, "ASRRunner", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("constructed")))
    RunCoordinator(tmp_root, store, offline=True).run_batch([(ident.work_id, store.get(ident.work_id))])


def test_run_batch_needs_audio_lazily_constructs_one_runner(tmp_root, monkeypatch):
    ident = page_identity("BVlazy", 0, 1, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(ident, status="audio_ok"))
    audio_dir = Path(tmp_root) / "audio"
    audio_dir.mkdir(exist_ok=True)
    (audio_dir / f"{artifact_stem(ident)}.m4a").write_bytes(b"fixture")
    constructions = []
    releases = []

    class FakeRunner:
        def __init__(self, *args, **kwargs):
            constructions.append((args, kwargs))

        def transcribe(self, _audio_path):
            return [{"start": 0.0, "end": 1.0, "text": "ok"}]

        def release(self):
            releases.append("released")

    monkeypatch.setattr(coordinator.asr_module, "ASRRunner", FakeRunner)
    runner = RunCoordinator(tmp_root, store, offline=True)
    runner.run_batch([(ident.work_id, store.get(ident.work_id))])
    assert len(constructions) == 1
    assert releases == ["released"]
    assert runner.asr_runner is None


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

    class FlakyModel:
        def generate(self, **kwargs):
            audio_path = kwargs["input"]
            probe = os.readlink(audio_path) if audio_path.startswith("/proc/self/fd/") else audio_path
            if artifact_stem(a) in probe:
                raise ASRModelError("model failed")
            return [{"text": "ok-text", "timestamp": [[0, 1000]]}]

    # These rows are told apart through the CLI's confined descriptor path, so the
    # boundary's descriptor materialization is switched off here; it has its own
    # unit test in tests/test_asr_reproducibility.py.
    monkeypatch.setattr(asr_mod, "_materialize_input", lambda path: (path, None))
    monkeypatch.setattr(asr_mod, "_load_default_model", lambda **_kwargs: FlakyModel())
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


# ------------------------------------------------- signals mid-run (Task 2, R5)

# The child is the real CLI over a real archive root, so the fixture must be
# provably still in flight when the signal lands *and* must not reach the
# network: `needs_audio` rows under a tiny `--max-audio-gb` are skipped locally
# (download/audio_budget) and a live batch sleeps 3s between rows, so a
# two-row fixture cannot finish before the signal.
_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_SRC_DIR = _PACKAGE_ROOT / "src"
_CHILD_TIMEOUT_S = 60.0


def _run_argv(archive_root: str, *extra: str) -> list[str]:
    """The CLI invocation under test (`-u`: the banner must reach the pipe)."""
    return [sys.executable, "-u", "-m", "bili_asr", "run", "--scope", "pending",
            "--max-audio-gb", "0.000001", *extra, "--archive-root", archive_root]


def _child_stderr(child: subprocess.Popen) -> str:
    """The child's stderr, read only once it cannot write any more."""
    if child.poll() is None:
        child.kill()
        child.wait(timeout=_CHILD_TIMEOUT_S)
    return child.stderr.read()


def _await_banner(child: subprocess.Popen) -> str:
    """The child's `run: scope=` banner line, read under a real deadline.

    `child.stdout.readline()` blocks until a newline or EOF, so a deadline
    consulted between reads cannot bound a wedged child: it would hang the
    suite instead of failing it.  The reads happen on a daemon thread that must
    finish inside the deadline, and the failure message carries the child's
    stderr -- a child that died at startup ends the stream, and an empty banner
    diagnoses nothing on its own.
    """
    found: list[str] = []

    def _read_until_banner() -> None:
        while True:
            line = child.stdout.readline()
            if not line or line.startswith("run: scope="):
                found.append(line)
                return

    reader = threading.Thread(target=_read_until_banner, daemon=True)
    reader.start()
    reader.join(_CHILD_TIMEOUT_S)
    if reader.is_alive():
        raise AssertionError(
            f"the child printed no banner within {_CHILD_TIMEOUT_S:.0f}s; "
            f"stderr={_child_stderr(child)!r}")
    return found[0]


def _await_file(child: subprocess.Popen, path: Path, what: str) -> None:
    """Block until the child creates `path`, bounded, failing with its stderr."""
    deadline = time.monotonic() + _CHILD_TIMEOUT_S
    while time.monotonic() < deadline:
        if path.exists():
            return
        if child.poll() is not None:
            break
        time.sleep(0.01)
    raise AssertionError(
        f"{what}; rc={child.poll()}, stderr={_child_stderr(child)!r}")


def _await_first_attempt(child: subprocess.Popen, root: str, work_id: str) -> None:
    """Block until the child durably recorded its first attempt, bounded.

    The banner alone does not prove the child reached the batch (the handler is
    installed just after it) or that the interrupted row has anything to
    report: this is that sync point.  Row two's attempt is 3s away, so the
    batch is still running when the caller signals.
    """
    deadline = time.monotonic() + _CHILD_TIMEOUT_S
    while time.monotonic() < deadline:
        if any(a["work_id"] == work_id for a in AttemptLedger(root).load()):
            return
        if child.poll() is not None:
            break
        time.sleep(0.01)
    raise AssertionError(
        f"the child never recorded an attempt for {work_id}; "
        f"rc={child.poll()}, stderr={_child_stderr(child)!r}")


def _interrupted_run_case(tmp_root, signum: int, expected_rc: int) -> None:
    """Signal a live `bili-asr run` and grade the one record it leaves."""
    from bili_asr.run_ledger import RunLedger

    first = page_identity("BVlater", 0, 111, "p0")
    second = page_identity("BVsigterm", 0, 222, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(first, status="needs_audio"))
    store.upsert(_row(second, status="needs_audio"))

    child = subprocess.Popen(
        _run_argv(tmp_root), cwd=str(_PACKAGE_ROOT),
        env=dict(os.environ, PYTHONPATH=str(_SRC_DIR)),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        banner = _await_banner(child)
        assert banner.startswith("run: scope=pending selected 2 row(s)"), (
            banner, _child_stderr(child))
        _await_first_attempt(child, tmp_root, first.work_id)
        child.send_signal(signum)
        assert child.wait(timeout=_CHILD_TIMEOUT_S) == expected_rc, _child_stderr(child)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()

    run_records = [r for r in RunLedger(root=tmp_root).load() if r.get("command") == "run"]
    assert len(run_records) == 1
    record = run_records[0]
    assert record["exit_code"] == expected_rc
    assert record["work_ids"] == [first.work_id]
    # The partial counts the run had already persisted, plus the pre-run
    # manifest count the run body loaded above the batch.
    assert record["records_existing"] == 2
    assert record["coverage_summary"] == {"needs_audio": 2}

    # The archive root the interrupted child left behind is re-enterable: the
    # next run takes the writer lock and appends its own record.
    resumed = subprocess.run(
        _run_argv(tmp_root, "--limit", "1"), cwd=str(_PACKAGE_ROOT),
        env=dict(os.environ, PYTHONPATH=str(_SRC_DIR)),
        capture_output=True, text=True, timeout=_CHILD_TIMEOUT_S,
    )
    assert "archive_busy" not in resumed.stderr, resumed.stderr
    assert resumed.returncode in (0, 1), resumed.stderr
    assert len([r for r in RunLedger(root=tmp_root).load()
                if r.get("command") == "run"]) == 2


def test_cli_run_sigterm_leaves_one_interrupted_record_and_root_reusable(tmp_root):
    _interrupted_run_case(tmp_root, signal.SIGTERM, 143)


def test_cli_run_sigint_leaves_one_interrupted_record_and_root_reusable(tmp_root):
    _interrupted_run_case(tmp_root, signal.SIGINT, 130)


# `sitecustomize` on the child's `PYTHONPATH` parks the run inside the guarded
# unwind without touching the shipped `python -m bili_asr` argv: the wrapper's
# `finally` runs inside `_interruptible_run()` and before the run-ledger write,
# so the child holds still in exactly the span a repeated signal must not be
# able to kill it in.  Racing that span instead would be a coin flip -- it is
# microseconds wide, and a second send is usually coalesced with the still
# pending first one.
_UNWIND_HOOK = '''"""Test hook: announce and hold the guarded unwind open.

Written into a scratch dir and imported by CPython's `site` machinery; the
marker/release paths arrive through the environment.
"""
import os
import time
from pathlib import Path

from bili_asr.coordinator import RunCoordinator

_MARKER = Path(os.environ["BILI_TEST_UNWIND_MARKER"])
_RELEASE = Path(os.environ["BILI_TEST_UNWIND_RELEASE"])
_ORIGINAL = RunCoordinator.run_batch


def _parking_run_batch(self, rows):
    try:
        return _ORIGINAL(self, rows)
    finally:
        _MARKER.write_text("unwinding", encoding="utf-8")
        deadline = time.monotonic() + 60
        while not _RELEASE.exists() and time.monotonic() < deadline:
            time.sleep(0.01)


RunCoordinator.run_batch = _parking_run_batch
'''


def test_cli_run_repeated_sigterm_during_the_unwind_still_writes_the_record(tmp_root):
    """A second SIGTERM in the unwind must not cost the run its record.

    The child is parked between the signal's delivery and the record write, so
    the repeated signal is delivered there for certain rather than in a
    microsecond-wide race.  Before the disposition fix the second SIGTERM lands
    at the restored default and terminates the child: no record, and no
    message.  A queued signal is taken before the child's next user-mode
    instruction, so releasing it after the send cannot let it slip past.
    """
    from bili_asr.run_ledger import RunLedger

    first = page_identity("BVlater", 0, 111, "p0")
    second = page_identity("BVparked", 0, 222, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(first, status="needs_audio"))
    store.upsert(_row(second, status="needs_audio"))

    hook_dir = Path(tmp_root).parent / f"{Path(tmp_root).name}-hook"
    hook_dir.mkdir()
    (hook_dir / "sitecustomize.py").write_text(_UNWIND_HOOK, encoding="utf-8")
    marker = hook_dir / "unwinding"
    release = hook_dir / "release"

    child = subprocess.Popen(
        _run_argv(tmp_root), cwd=str(_PACKAGE_ROOT),
        env=dict(os.environ, PYTHONPATH=f"{hook_dir}{os.pathsep}{_SRC_DIR}",
                 BILI_TEST_UNWIND_MARKER=str(marker),
                 BILI_TEST_UNWIND_RELEASE=str(release)),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        banner = _await_banner(child)
        assert banner.startswith("run: scope=pending selected 2 row(s)"), (
            banner, _child_stderr(child))
        _await_first_attempt(child, tmp_root, first.work_id)
        child.send_signal(signal.SIGTERM)
        _await_file(child, marker, "the child never parked in its unwind")
        child.send_signal(signal.SIGTERM)
        release.write_text("go", encoding="utf-8")
        rc = child.wait(timeout=_CHILD_TIMEOUT_S)
        assert rc == 143, (rc, _child_stderr(child))
    finally:
        release.write_text("go", encoding="utf-8")
        if child.poll() is None:
            child.kill()
            child.wait()
        shutil.rmtree(hook_dir, ignore_errors=True)

    run_records = [r for r in RunLedger(root=tmp_root).load() if r.get("command") == "run"]
    assert len(run_records) == 1
    record = run_records[0]
    assert record["exit_code"] == 143
    assert record["work_ids"] == [first.work_id]
    assert record["records_existing"] == 2
    assert record["coverage_summary"] == {"needs_audio": 2}


def test_sigterm_delivery_ignores_both_signals_across_the_unwind():
    """A repeated SIGTERM must not kill the process before the record write.

    The span between delivery and `_signals_ignored()` is the whole coordinator
    unwind -- runner release, batch-evidence stderr write -- and not a few
    statements, so delivery must leave both signals ignored: at the captured
    default a repeated SIGTERM terminates the process in that span with no
    record at all.  The installed handler is called directly, which is exactly
    what delivery runs, so a regression is asserted instead of killing the test
    process.
    """
    from bili_asr.cli import _RunInterrupted, _interruptible_run

    original = signal.getsignal(signal.SIGTERM)
    try:
        with _interruptible_run():
            handler = signal.getsignal(signal.SIGTERM)
            assert handler is not signal.SIG_DFL
            with pytest.raises(_RunInterrupted):
                handler(signal.SIGTERM, None)
            assert signal.getsignal(signal.SIGTERM) is signal.SIG_IGN
            assert signal.getsignal(signal.SIGINT) is signal.SIG_IGN
        # One-shot: the true previous disposition is back once the body is done.
        assert signal.getsignal(signal.SIGTERM) is original
    finally:
        signal.signal(signal.SIGTERM, original)


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

    class FlakyModel:
        def generate(self, **kwargs):
            audio_path = kwargs["input"]
            probe = os.readlink(audio_path) if audio_path.startswith("/proc/self/fd/") else audio_path
            if artifact_stem(a) in probe:
                raise ASRModelError("boom")
            return [{"text": "ok", "timestamp": [[0, 1000]]}]

    # These rows are told apart through the CLI's confined descriptor path, so the
    # boundary's descriptor materialization is switched off here; it has its own
    # unit test in tests/test_asr_reproducibility.py.
    monkeypatch.setattr(asr_mod, "_materialize_input", lambda path: (path, None))
    monkeypatch.setattr(asr_mod, "_load_default_model", lambda **_kwargs: FlakyModel())
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


def test_complete_bundle_retries_after_manifest_transition_failure(
    tmp_root, monkeypatch, capsys
):
    from pathlib import Path
    from bili_asr import archive as archive_mod

    sub = page_identity("BVretry", 0, 111, "p0")
    store = ManifestStore(root=tmp_root)
    store.upsert(_row(sub, status="subtitle_done", title="retryable"))
    stem = artifact_stem(sub)
    raw_dir = Path(tmp_root) / "subtitles" / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / f"{stem}.json").write_text(
        json.dumps(SAMPLE_DOC), encoding="utf-8"
    )
    _patch_cli(monkeypatch, _mixed_transport())

    original_upsert = ManifestStore.upsert
    failed_once = False

    def fail_first_archived(self, entry):
        nonlocal failed_once
        if entry.get("status") == "archived" and not failed_once:
            failed_once = True
            raise OSError("injected manifest transition detail")
        return original_upsert(self, entry)

    monkeypatch.setattr(ManifestStore, "upsert", fail_first_archived)
    assert main([
        "run", "--scope", "pending", "--offline",
        "--archive-root", tmp_root,
    ]) == 1
    first_output = capsys.readouterr()
    assert "injected manifest transition detail" not in first_output.err
    assert "Traceback" not in first_output.err
    assert ManifestStore(tmp_root).load()[sub.work_id]["status"] == "subtitle_done"

    marker = next((Path(tmp_root) / "transcripts" / "srt").glob("*.bundle-ready"))
    marker_doc = json.loads(marker.read_text(encoding="ascii"))
    published_paths = {
        key: value["path"]
        for key, value in marker_doc["artifacts"].items()
    }
    assert archive_mod.archive_bundle_complete(tmp_root, published_paths)

    assert main([
        "run", "--scope", "pending", "--offline",
        "--archive-root", tmp_root,
    ]) == 0
    capsys.readouterr()
    archived = ManifestStore(tmp_root).load()[sub.work_id]
    assert archived["status"] == "archived"
    archived_paths = {
        key: archived[key]
        for key in ("srt_path", "txt_path", "md_path", "raw_path")
    }
    assert archive_mod.archive_bundle_complete(tmp_root, archived_paths)


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
