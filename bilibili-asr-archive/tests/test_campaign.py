from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from bili_asr import asr as asr_mod
from bili_asr.campaign import CampaignRunner
from bili_asr.coordinator import RowResult, RunSummary, archive_writer
from bili_asr.manifest import ManifestStore
from bili_asr.page_identity import artifact_stem, page_identity
from bili_asr.scheduler import SchedulerStore

_AUDIO_BYTES = b"\x00\x00\x00\x18ftypM4A " + b"payload" * 100


def _rows(*ids: str):
    return [(item, {"work_id": item, "bvid": item, "status": "archived"}) for item in ids]


def _selector(rows):
    return lambda *_: (rows, None)


def _runner(tmp_path, summary, rows=None):
    class Coordinator:
        def __init__(self, *_args, **_kwargs): pass
        def run_batch(self, selected): return summary
    return CampaignRunner(tmp_path, scope_rows=_selector(rows if rows is not None else _rows("a")), coordinator_factory=Coordinator)


def test_projection_is_safe_and_policy_is_hash(tmp_path):
    result = _runner(tmp_path, RunSummary(), _rows("a")).run("pending", 2)
    checkpoint = json.loads((Path(tmp_path) / "campaign.json").read_text())
    assert result.exit_code == 1
    assert len(checkpoint["policy_fingerprint"]) == 64
    assert all(marker.lower() not in json.dumps(checkpoint).lower() for marker in ("sessdata", "https://", "traceback"))


def test_limit_is_not_success(tmp_path):
    result = _runner(tmp_path, RunSummary(results=[RowResult("a", "archived", ok=True)]), _rows("a", "b")).run("pending", 1)
    assert result.checkpoint_state == "limited"
    assert result.exit_code == 1


def test_empty_selection_is_not_complete(tmp_path):
    result = _runner(tmp_path, RunSummary(), []).run("pending", 1)
    assert result.exit_code == 1
    assert result.checkpoint_state == "limited"


def test_failed_and_nonterminal_skips_are_not_success(tmp_path):
    summary = RunSummary(results=[RowResult("a", "meta_ok", skipped=True, skip_reason="offline")])
    assert _runner(tmp_path, summary).run("pending", 1).exit_code == 1


def test_resume_requires_matching_risk_scheduler_state(tmp_path):
    SchedulerStore(tmp_path).replace_atomic({"scope": "other", "limit": 1, "state": "risk_interrupted", "processed_work_ids": [], "last_api_error_code": 412, "allow_long_live": False, "updated_at": "now"})
    with pytest.raises(ValueError, match="scope mismatch"):
        _runner(tmp_path, RunSummary(), _rows("a")).run("pending", 1, resume=True)


def test_nonterminal_missing_result_is_not_success(tmp_path):
    summary = RunSummary(results=[RowResult("a", "meta_ok", ok=True)])
    result = _runner(tmp_path, summary).run("pending", 1)
    assert result.exit_code == 1


def test_matching_resume_filters_terminal_processed_ids(tmp_path):
    SchedulerStore(tmp_path).replace_atomic({"scope": "pending", "limit": 1, "state": "risk_interrupted", "processed_work_ids": ["a"], "last_api_error_code": 412, "allow_long_live": False, "updated_at": "now"})
    (Path(tmp_path) / "campaign.json").write_text(json.dumps({"schema_version": 1, "scope": "pending", "batch_limit": 1, "state": "risk_interrupted", "policy_fingerprint": __import__("hashlib").sha256(b"default").hexdigest(), "selected_work_ids": ["a"], "processed_work_ids": ["a"], "skipped_work_ids": [], "failed_work_ids": [], "reason_codes": []}))
    result = _runner(tmp_path, RunSummary(), _rows("a")).run("pending", 1, resume=True)
    assert result.selected == ["a"]
    assert result.exit_code == 1


def test_resume_refuses_limit_and_policy_mismatch(tmp_path):
    SchedulerStore(tmp_path).replace_atomic({"scope": "pending", "limit": 2, "state": "risk_interrupted", "processed_work_ids": [], "last_api_error_code": 412, "allow_long_live": False, "updated_at": "now"})
    with pytest.raises(ValueError, match="limit mismatch"):
        _runner(tmp_path, RunSummary(), _rows("a")).run("pending", 1, resume=True)
    SchedulerStore(tmp_path).replace_atomic({"scope": "pending", "limit": 1, "state": "risk_interrupted", "processed_work_ids": [], "last_api_error_code": 412, "allow_long_live": False, "updated_at": "now"})
    (Path(tmp_path) / "campaign.json").write_text(json.dumps({"schema_version": 1, "policy_fingerprint": "wrong", "scope": "pending", "batch_limit": 1, "state": "risk_interrupted", "selected_work_ids": [], "processed_work_ids": [], "skipped_work_ids": [], "failed_work_ids": [], "reason_codes": []}))
    with pytest.raises(ValueError, match="policy mismatch"):
        _runner(tmp_path, RunSummary(), _rows("a")).run("pending", 1, resume=True)

    (Path(tmp_path) / "campaign.json").unlink()

    seen = {}
    class Coordinator:
        def __init__(self, *args, **kwargs): seen.update(kwargs)
        def run_batch(self, rows): return RunSummary(results=[RowResult("a", "archived", ok=True)])
    pacing = lambda _: None
    CampaignRunner(tmp_path, client="fake", offline=False, max_audio_bytes=12, sleep=pacing, coordinator_factory=Coordinator, scope_rows=_selector(_rows("a"))).run("pending", 1)


def test_resume_rejects_scalar_projection(tmp_path):
    SchedulerStore(tmp_path).replace_atomic({"scope": "pending", "limit": 1, "state": "risk_interrupted", "processed_work_ids": [], "last_api_error_code": 412, "allow_long_live": False, "updated_at": "now"})
    (Path(tmp_path) / "campaign.json").write_text("[]")
    with pytest.raises(ValueError, match="corrupt/mismatch"):
        _runner(tmp_path, RunSummary(), _rows("a")).run("pending", 1, resume=True)


def test_atomic_failure_preserves_prior_projection(tmp_path, monkeypatch):
    runner = _runner(tmp_path, RunSummary(), _rows("a"))
    runner.run("pending", 1)
    prior = (Path(tmp_path) / "campaign.json").read_bytes()
    original = __import__("os").replace
    def fail_replace(src, dst):
        if str(dst).endswith("campaign.json"):
            raise OSError("injected")
        return original(src, dst)
    monkeypatch.setattr("bili_asr.campaign.os.replace", fail_replace)
    with pytest.raises(OSError):
        runner.run("pending", 1)
    assert (Path(tmp_path) / "campaign.json").read_bytes() == prior


def test_cli_campaign_preserves_summary_exit_codes(monkeypatch, tmp_path):
    from bili_asr import cli
    class FakeRunner:
        def __init__(self, *args, **kwargs): pass
        def run(self, *args, **kwargs): return type("S", (), {"exit_code": 2, "to_dict": lambda self: {"exit_code": 2}})()
    monkeypatch.setattr("bili_asr.campaign.CampaignRunner", FakeRunner)
    args = type("A", (), {"offline": True, "archive_root": str(tmp_path), "scope": "pending", "limit": 1, "resume": False, "max_audio_gb": 0})()
    assert cli._cmd_campaign(args) == 2


def test_cli_campaign_safely_catches_unexpected_exception(monkeypatch, tmp_path, capsys):
    from bili_asr import cli
    class FakeRunner:
        def __init__(self, *args, **kwargs): raise RuntimeError("secret")
    monkeypatch.setattr("bili_asr.campaign.CampaignRunner", FakeRunner)
    args = type("A", (), {"offline": True, "archive_root": str(tmp_path), "scope": "pending", "limit": 1, "resume": False, "max_audio_gb": 0})()
    assert cli._cmd_campaign(args) == 1
    captured = capsys.readouterr()
    assert captured.err == "campaign: invalid configuration or execution failure\n"
    assert "secret" not in captured.err


def test_two_call_risk_projection_requires_resume_and_avoids_terminal_ids(tmp_path):
    calls = []
    class Coordinator:
        def __init__(self, *_args, **_kwargs): pass
        def run_batch(self, selected):
            calls.append([key for key, _ in selected])
            if len(calls) == 1:
                return RunSummary(results=[RowResult("a", "archived", ok=True), RowResult("b", "meta_ok", ok=False)], risk_interrupted=True)
            return RunSummary(results=[RowResult("b", "archived", ok=True)])
    runner = CampaignRunner(tmp_path, scope_rows=_selector([(k, {**e, "status": "archived" if k == "a" else "meta_ok"}) for k, e in _rows("a", "b")]), coordinator_factory=Coordinator)
    assert runner.run("pending", 2).exit_code == 2
    with pytest.raises(ValueError, match="requires --resume"):
        runner.run("pending", 2)
    assert calls == [["a", "b"]]
    result = runner.run("pending", 2, resume=True)
    assert result.exit_code == 1
    assert calls == [["a", "b"], ["a", "b"]]


def test_atomic_directory_fsync_failure_restores_bytes_and_cleans_temp(tmp_path, monkeypatch):
    runner = _runner(tmp_path, RunSummary(), _rows("a"))
    runner.run("pending", 1)
    prior = (Path(tmp_path) / "campaign.json").read_bytes()
    real_fsync = __import__("os").fsync
    count = 0
    def fail_directory_fsync(fd):
        nonlocal count
        count += 1
        if count == 2:
            raise OSError("directory fsync injected")
        return real_fsync(fd)
    monkeypatch.setattr("bili_asr.campaign.os.fsync", fail_directory_fsync)
    with archive_writer(tmp_path):
        with pytest.raises(OSError, match="directory fsync injected"):
            runner.run("pending", 1)
    assert (Path(tmp_path) / "campaign.json").read_bytes() == prior
    assert not list(Path(tmp_path).glob(".campaign.json.*"))

def test_cli_campaign_summary_exit_code_two(monkeypatch, tmp_path, capsys):
    from bili_asr import cli
    class FakeRunner:
        def __init__(self, *args, **kwargs): pass
        def run(self, *args, **kwargs): return type("S", (), {"exit_code": 2, "to_dict": lambda self: {"exit_code": 2}})()
    monkeypatch.setattr("bili_asr.campaign.CampaignRunner", FakeRunner)
    args = type("A", (), {"offline": True, "archive_root": str(tmp_path), "scope": "pending", "limit": 1, "resume": False, "max_audio_gb": 0})()
    assert cli._cmd_campaign(args) == 2
    assert json.loads(capsys.readouterr().out)["exit_code"] == 2


def test_cli_campaign_summary_exit_code_one(monkeypatch, tmp_path):
    from bili_asr import cli
    class FakeRunner:
        def __init__(self, *args, **kwargs): pass
        def run(self, *args, **kwargs): return type("S", (), {"exit_code": 1, "to_dict": lambda self: {"exit_code": 1}})()
    monkeypatch.setattr("bili_asr.campaign.CampaignRunner", FakeRunner)
    args = type("A", (), {"offline": True, "archive_root": str(tmp_path), "scope": "pending", "limit": 1, "resume": False, "max_audio_gb": 0})()
    assert cli._cmd_campaign(args) == 1


def test_cli_campaign_invalid_resume_is_generic(monkeypatch, tmp_path, capsys):
    from bili_asr import cli
    class FakeRunner:
        def __init__(self, *args, **kwargs): pass
        def run(self, *args, **kwargs): raise ValueError("resume refused: drift")
    monkeypatch.setattr("bili_asr.campaign.CampaignRunner", FakeRunner)
    args = type("A", (), {"offline": True, "archive_root": str(tmp_path), "scope": "pending", "limit": 1, "resume": True, "max_audio_gb": 0})()
    assert cli._cmd_campaign(args) == 1
    assert capsys.readouterr().err == "campaign: invalid configuration or execution failure\n"


# ---------------------------------------------- real coordinator, real stdout contract


def _seed_campaign_audio_rows(root, count):
    """`count` audio_ok rows with audio on disk (no network, no fake runner)."""
    store = ManifestStore(root=root)
    audio_dir = os.path.join(root, "audio")
    os.makedirs(audio_dir, exist_ok=True)
    identities = [
        page_identity(f"BVcamp{index}", 0, 500 + index, "p0") for index in range(count)
    ]
    for identity in identities:
        store.upsert({
            "bvid": identity.bvid, "work_id": identity.work_id, "page_index": 0,
            "cid": identity.cid, "page_label": "p0", "status": "audio_ok",
            "title": "campaign-clip", "duration_s": 5, "pubdate": 1,
            "pubdate_str": "2026-01-02",
            "audio_path": f"audio/{artifact_stem(identity)}.m4a",
        })
        with open(os.path.join(audio_dir, f"{artifact_stem(identity)}.m4a"), "wb") as fh:
            fh.write(_AUDIO_BYTES)
    return identities


def _stub_campaign_model(monkeypatch):
    """D2.5 seam for the real coordinator: count constructions at the factory."""
    constructions: list[dict] = []

    class FakeModel:
        def generate(self, **_kwargs):
            return [{"text": "campaign-asr", "timestamp": [[0, 1000]]}]

    def factory(**kwargs):
        constructions.append(dict(kwargs))
        return FakeModel()

    monkeypatch.setenv("BILI_ASR_DEVICE", "cpu")
    monkeypatch.setattr(asr_mod, "_load_default_model", factory)
    return constructions


def test_cli_campaign_stdout_is_json_and_the_reuse_line_is_stderr(
    tmp_path, monkeypatch, capsys
):
    """D2.6 regression: the constructions line must not break campaign's JSON.

    Task 1 measured this against the real coordinator — the existing campaign
    CLI tests inject a fake coordinator, so they never exercised the real
    stdout.  This test drives `_cmd_campaign` through `CampaignRunner` and the
    real `RunCoordinator` over three on-disk audio rows.
    """

    from bili_asr import cli

    identities = _seed_campaign_audio_rows(str(tmp_path), 3)
    constructions = _stub_campaign_model(monkeypatch)
    args = type("A", (), {
        "offline": True, "archive_root": str(tmp_path), "scope": "pending",
        "limit": 3, "resume": False, "max_audio_gb": 0,
    })()

    assert cli._cmd_campaign(args) == 0
    captured = capsys.readouterr()

    # stdout is exactly one JSON document — nothing else, on one line.
    assert len(captured.out.splitlines()) == 1
    summary = json.loads(captured.out)
    assert summary["checkpoint_state"] == "complete"
    assert sorted(summary["processed"]) == sorted(i.work_id for i in identities)
    # The reuse line names `campaign`, not `run`, and lives on stderr.
    assert "campaign: model constructions=1 for 3 asr item(s)" in captured.err
    assert "model constructions=" not in captured.out
    assert len(constructions) == 1
    loaded = ManifestStore(root=str(tmp_path)).load()
    assert [loaded[i.work_id]["status"] for i in identities] == ["archived"] * 3



def test_cli_campaign_stdout_stays_one_json_document_with_fd_2_closed(
    tmp_path, monkeypatch, capsys
):
    """F-02: a closed stderr must not push the reuse line into campaign's JSON.

    With fd 2 closed CPython sets ``sys.stderr`` to ``None``, and
    ``print(..., file=None)`` writes to **stdout** — the exact stream this
    contract reserves for one JSON document.  The batch must therefore drop
    the diagnostic rather than relocate it.
    """

    import sys

    from bili_asr import cli

    identities = _seed_campaign_audio_rows(str(tmp_path), 3)
    _stub_campaign_model(monkeypatch)
    monkeypatch.setattr(sys, "stderr", None)
    args = type("A", (), {
        "offline": True, "archive_root": str(tmp_path), "scope": "pending",
        "limit": 3, "resume": False, "max_audio_gb": 0,
    })()

    assert cli._cmd_campaign(args) == 0

    captured = capsys.readouterr()
    assert len(captured.out.splitlines()) == 1, captured.out
    summary = json.loads(captured.out)
    assert summary["checkpoint_state"] == "complete"
    assert sorted(summary["processed"]) == sorted(i.work_id for i in identities)
    assert "model constructions=" not in captured.out
