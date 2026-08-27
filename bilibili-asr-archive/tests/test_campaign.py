from __future__ import annotations

import json
from pathlib import Path

import pytest

from bili_asr.campaign import CampaignRunner
from bili_asr.coordinator import RowResult, RunSummary
from bili_asr.manifest import ManifestStore
from bili_asr.scheduler import SchedulerStore


def _rows(*ids: str):
    return [(item, {"work_id": item, "bvid": item, "status": "meta_ok"}) for item in ids]


def _selector(rows):
    return lambda *_: (rows, None)


def test_summary_checkpoint_is_redacted_and_atomic(tmp_path):
    result = CampaignRunner(
        tmp_path, scope_rows=_selector(_rows("a")),
        coordinator_factory=lambda *args, **kwargs: type("C", (), {"run_batch": lambda self, rows: RunSummary()})(),
    ).run("pending", 2)
    checkpoint = json.loads((Path(tmp_path) / "campaign.json").read_text())
    assert result.exit_code == 0
    assert set(checkpoint) == {"scope", "policy_fingerprint", "selected_work_ids", "processed_work_ids", "state", "reason_codes"}
    assert all(marker not in json.dumps(checkpoint) for marker in ("SESSDATA", "https://", "Traceback"))


def test_limit_is_distinct_from_complete(tmp_path):
    class Coordinator:
        def __init__(self, *_args, **_kwargs): pass
        def run_batch(self, selected):
            return RunSummary(results=[RowResult(selected[0][0], "archived", ok=True)])
    result = CampaignRunner(tmp_path, coordinator_factory=Coordinator, scope_rows=_selector(_rows("a", "b"))).run("pending", 1)
    assert result.checkpoint_state == "limited"
    assert result.processed == ["a"]
    assert result.exit_code == 0


def test_resume_requires_matching_risk_scheduler_state(tmp_path):
    ManifestStore(tmp_path).upsert({"work_id": "BV1abc:p0", "bvid": "BV1abc", "status": "archived"})
    SchedulerStore(tmp_path).replace_atomic({"scope": "other", "limit": 1, "state": "risk_interrupted", "processed_work_ids": [], "last_api_error_code": 412, "allow_long_live": False, "updated_at": "now"})
    with pytest.raises(ValueError, match="scope mismatch"):
        CampaignRunner(tmp_path, scope_rows=_selector(_rows("a"))).run("pending", 1, resume=True)


def test_coordinator_arguments_propagate_and_live_is_not_forced_offline(tmp_path):
    seen = {}
    class Coordinator:
        def __init__(self, *args, **kwargs): seen.update(kwargs)
        def run_batch(self, rows): return RunSummary()
    pacing = lambda _: None
    CampaignRunner(tmp_path, client="fake", offline=False, max_audio_bytes=12, sleep=pacing, coordinator_factory=Coordinator, scope_rows=_selector(_rows("a"))).run("pending", 1)
    assert seen == {"client": "fake", "offline": False, "max_audio_bytes": 12, "sleep": pacing}
