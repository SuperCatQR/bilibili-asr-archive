from __future__ import annotations

import json
from pathlib import Path

import pytest

from bili_asr.campaign import CampaignRunner
from bili_asr.coordinator import RowResult, RunSummary
from bili_asr.scheduler import SchedulerStore


def _rows(*ids: str):
    return [(item, {"work_id": item, "bvid": item, "status": "meta_ok"}) for item in ids]


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


def test_coordinator_arguments_propagate_and_live_is_not_forced_offline(tmp_path):
    seen = {}
    class Coordinator:
        def __init__(self, *args, **kwargs): seen.update(kwargs)
        def run_batch(self, rows): return RunSummary(results=[RowResult("a", "archived", ok=True)])
    pacing = lambda _: None
    CampaignRunner(tmp_path, client="fake", offline=False, max_audio_bytes=12, sleep=pacing, coordinator_factory=Coordinator, scope_rows=_selector(_rows("a"))).run("pending", 1)
    assert seen == {"client": "fake", "offline": False, "max_audio_bytes": 12, "sleep": pacing}
