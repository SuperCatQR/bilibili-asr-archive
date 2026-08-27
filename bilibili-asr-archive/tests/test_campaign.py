from __future__ import annotations

import json
from pathlib import Path

from bili_asr.campaign import CampaignRunner
from bili_asr.coordinator import RowResult, RunSummary


def test_summary_dict_has_stable_redacted_shape(tmp_path):
    runner = CampaignRunner(tmp_path, scope_rows=lambda *_: ([], None))
    runner.coordinator_factory = lambda *_args, **_kwargs: type("C", (), {"run_batch": lambda self, rows: RunSummary()})()
    result = runner.run("pending", 2)
    assert list(result.to_dict()) == ["selected", "processed", "skipped", "failed", "checkpoint_state", "reason_codes", "exit_code"]
    assert json.loads((Path(tmp_path) / "campaign.json").read_text())["state"] == "complete"


def test_bounded_run_marks_limited_and_only_settled_rows(tmp_path):
    rows = [("a", {"bvid": "BV1", "work_id": "a", "status": "meta_ok"}), ("b", {"bvid": "BV2", "work_id": "b", "status": "meta_ok"})]
    class Coordinator:
        def __init__(self, *_args, **_kwargs): pass
        def run_batch(self, selected): return RunSummary(results=[RowResult("a", "archived", ok=True)])
    result = CampaignRunner(tmp_path, coordinator_factory=Coordinator, scope_rows=lambda *_: (rows, None)).run("pending", 1)
    assert result.checkpoint_state == "limited"
    assert result.processed == ["a"]
    assert result.exit_code == 0
