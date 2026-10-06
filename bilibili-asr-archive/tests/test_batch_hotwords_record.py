"""Per-row guard verdicts survive runner reuse, cleanup and interruption."""

from pathlib import Path
import json
import signal

import pytest

from bili_asr import cli
from bili_asr.bili_client import RiskBudgetExhausted
from bili_asr.campaign import CampaignRunner
from bili_asr.coordinator import RunCoordinator
from bili_asr.manifest import ManifestStore
from bili_asr.page_identity import artifact_stem, page_identity
from bili_asr.run_ledger import RunLedger, build_run_record, collect_hotwords_dropped


COMMANDS = ("run", "schedule", "campaign", "pilot")
EXPECTED = ["扬弃", "此在", "总体性", "甲,乙", "[redacted]"]


class VerdictRunner:
    """The guard result changes each row and is cleared when resources close."""

    def __init__(self, interrupt=None):
        self.interrupt = interrupt
        self.calls = 0
        self.released = 0
        self.hotwords_dropped = ()

    def set_hotword_evidence(self, **kwargs):
        pass

    def rebuild_hotwords_from_first_pass(self, transcript_text):
        return []

    def transcribe(self, path, **kwargs):
        self.calls += 1
        if self.calls == 3 and self.interrupt is not None:
            signal.getsignal(self.interrupt)(self.interrupt, None)
        self.hotwords_dropped = (
            ("扬弃", "此在", "扬弃") if self.calls == 1 else (
                "此在", "总体性", "甲,乙", "cookie=SECRET",
                "SESSDATA=private", "https://signed.example/?token=SECRET",
                "password=private", "C:/private/model", "Traceback private",
            )
        )
        return [{"start": 0, "end": 1, "text": "记录"}]

    def provenance(self):
        return {"model_name": "test-model", "language": "zh"}

    def release(self):
        self.released += 1
        self.hotwords_dropped = ("released-only",)


def _seed_audio(root, count):
    store = ManifestStore(root)
    rows = []
    for index in range(count):
        identity = page_identity("BVhotword", index, 7 + index, f"p{index}")
        declared = f"audio/{artifact_stem(identity)}.m4a"
        audio = Path(root) / declared
        audio.parent.mkdir(parents=True, exist_ok=True)
        audio.write_bytes(b"audio")
        row = {
            "work_id": identity.work_id, "bvid": identity.bvid,
            "page_index": index, "cid": identity.cid, "page_label": identity.page_label,
            "title": "record", "date": "2026-10-05", "duration_s": 1,
            "status": "audio_ok", "audio_path": declared,
        }
        store.upsert(row)
        rows.append((identity.work_id, row))
    return store, rows


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("interruption", (None, signal.SIGINT, signal.SIGTERM))
def test_command_records_each_completed_row_verdict_before_runner_is_reused_or_released(
    tmp_root, monkeypatch, capsys, command, interruption,
):
    count = 2 if interruption is None else 3
    store, rows = _seed_audio(tmp_root, count)
    runner = VerdictRunner(interruption)
    monkeypatch.setattr("bili_asr.asr.ASRRunner", lambda config: runner)
    monkeypatch.setattr("bili_asr.bili_client.BiliClient", lambda **kwargs: object())
    monkeypatch.setattr("bili_asr.cli.time.sleep", lambda seconds: None)
    argv = [command, "--archive-root", tmp_root]
    if command == "pilot":
        argv += ["--n", str(count), "--queue-source", "manifest"]
    else:
        argv += ["--scope", ",".join(key for key, row in rows), "--limit", str(count)]
    if command == "campaign":
        argv.append("--offline")

    # Pilot intentionally requires both routes; this ASR-only batch succeeds
    # per row and records the product-level missing-subtitle-branch status.
    expected_exit = (1 if command == "pilot" else 0) if interruption is None else 128 + interruption
    assert cli.main(argv) == expected_exit
    record, = RunLedger(tmp_root).load()
    assert record["command"] == command
    assert record["exit_code"] == expected_exit
    assert record["hotwords_dropped"] == EXPECTED
    assert runner.calls == count
    assert runner.released == 1
    assert store.load()[rows[0][0]]["status"] == "archived"
    assert store.load()[rows[1][0]]["status"] == "archived"
    if interruption is not None:
        assert store.load()[rows[2][0]]["status"] == "audio_ok"
    output = capsys.readouterr()
    ledger_bytes = (Path(tmp_root) / "run-ledger.jsonl").read_text(encoding="utf-8")
    for sensitive in ("SECRET", "SESSDATA", "cookie=", "https://", "password=", "private", "released-only"):
        assert sensitive not in ledger_bytes + output.out + output.err


def test_coordinator_summary_is_a_per_batch_snapshot_with_a_reused_injected_runner(tmp_root):
    store, rows = _seed_audio(tmp_root, 2)
    runner = VerdictRunner()
    coordinator = RunCoordinator(tmp_root, store, offline=True, asr_runner=runner)
    first = coordinator.run_batch(rows)
    assert first.hotwords_dropped == EXPECTED
    assert coordinator.hotwords_dropped == EXPECTED
    second = coordinator.run_batch([])
    assert second.hotwords_dropped == []
    assert coordinator.hotwords_dropped == []
    assert first.hotwords_dropped == EXPECTED
    assert runner.released == 0


def test_run_ledger_preserves_hotwords_and_reads_legacy_records(tmp_root):
    ledger = RunLedger(tmp_root)
    record = build_run_record(command="run", started_at="2026-10-05T00:00:00Z", exit_code=0,
                              hotwords_dropped=["扬弃", "此在", "扬弃"])
    stored = ledger.append(record)
    assert stored["hotwords_dropped"] == ["扬弃", "此在"]
    assert ledger.load() == [stored]
    assert ledger.latest() == stored
    legacy = {key: value for key, value in record.items() if key != "hotwords_dropped"}
    with Path(ledger.path).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(legacy) + "\n")
    assert ledger.latest()["hotwords_dropped"] == []


@pytest.mark.parametrize("bad", [None, "扬弃", [1], [None], [""], [" "],
                                  ["cookie=private"], ["password=private"], ["https://signed.example/"]])
def test_run_ledger_rejects_malformed_or_unredacted_hotwords_without_writing(tmp_root, bad):
    record = build_run_record(command="run", started_at="2026-10-05T00:00:00Z", exit_code=0)
    record["hotwords_dropped"] = bad
    ledger = RunLedger(tmp_root)
    with pytest.raises(ValueError, match="hotwords_dropped"):
        ledger.append(record)
    assert not Path(ledger.path).exists()


@pytest.mark.parametrize("runner", [object(), type("BadShape", (), {"hotwords_dropped": "扬弃"})()])
def test_older_or_malformed_runner_metadata_is_optional(runner):
    collected = ["已有"]
    collect_hotwords_dropped(collected, runner)
    assert collected == ["已有"]


@pytest.mark.parametrize("separator", [" ", ", \t"])
def test_campaign_multiple_selectors_archive_before_preserving_exact_scope(
    tmp_root, monkeypatch, capsys, separator,
):
    store, rows = _seed_audio(tmp_root, 2)
    runner = VerdictRunner()
    monkeypatch.setattr("bili_asr.asr.ASRRunner", lambda config: runner)
    monkeypatch.setattr("bili_asr.cli.time.sleep", lambda seconds: None)
    scope = separator.join(key for key, row in rows)
    assert cli.main(["campaign", "--archive-root", tmp_root, "--offline",
                     "--scope", scope, "--limit", "2"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["checkpoint_state"] == "complete"
    assert summary["processed"] == [key for key, row in rows]
    checkpoint = json.loads((Path(tmp_root) / "campaign.json").read_text(encoding="utf-8"))
    assert checkpoint["scope"] == scope
    assert checkpoint["selected_work_ids"] == [key for key, row in rows]
    assert [row["status"] for row in store.load().values()] == ["archived"] * 2
    assert runner.calls == 2


@pytest.mark.parametrize("scope", ["", ",", " ", "BVgood/SECRET", "BVgood,cookie=SECRET",
                                   "BVgood,https://signed.example/?token=SECRET", "BVgood Traceback",
                                   "BVhotword:p0,BVhotword:p0"])
def test_campaign_rejects_unsafe_or_empty_scope_before_model_construction(
    tmp_root, monkeypatch, capsys, scope,
):
    store, rows = _seed_audio(tmp_root, 2)
    constructions = []
    monkeypatch.setattr("bili_asr.asr.ASRRunner", lambda config: constructions.append(config))
    assert cli.main(["campaign", "--archive-root", tmp_root, "--offline",
                     "--scope", scope, "--limit", "2"]) == 1
    assert constructions == []
    assert [row["status"] for row in store.load().values()] == ["audio_ok"] * 2
    assert not (Path(tmp_root) / "campaign.json").exists()
    output = capsys.readouterr()
    assert output.err == "campaign: invalid configuration or execution failure\n"
    ledger = (Path(tmp_root) / "run-ledger.jsonl").read_text(encoding="utf-8")
    assert "SECRET" not in output.out + output.err + ledger
    assert "signed.example" not in output.out + output.err + ledger


class RiskOnceRunner(VerdictRunner):
    def __init__(self):
        super().__init__()
        self.risk_seen = False

    def transcribe(self, path, **kwargs):
        if self.calls == 1 and not self.risk_seen:
            self.risk_seen = True
            self.calls += 1
            raise RiskBudgetExhausted(-412)
        return super().transcribe(path, **kwargs)


@pytest.mark.parametrize("count", [2, 3])
def test_campaign_resume_retains_the_original_bounded_selection(
    tmp_root, monkeypatch, capsys, count,
):
    store, rows = _seed_audio(tmp_root, count)
    runner = RiskOnceRunner()
    monkeypatch.setattr("bili_asr.asr.ASRRunner", lambda config: runner)
    monkeypatch.setattr("bili_asr.cli.time.sleep", lambda seconds: None)
    scope = ",".join(key for key, row in rows)
    argv = ["campaign", "--archive-root", tmp_root, "--offline", "--scope", scope, "--limit", "2"]
    assert cli.main(argv) == 2
    assert store.load()[rows[0][0]]["status"] == "archived"
    interrupted = json.loads((Path(tmp_root) / "campaign.json").read_text(encoding="utf-8"))
    assert interrupted["selected_work_ids"] == [key for key, row in rows[:2]]
    assert interrupted["processed_work_ids"] == [rows[0][0]]
    capsys.readouterr()

    assert cli.main(argv + ["--resume"]) == (0 if count == 2 else 1)
    summary = json.loads(capsys.readouterr().out)
    assert summary["selected"] == [key for key, row in rows[:2]]
    assert summary["processed"] == [key for key, row in rows[:2]]
    checkpoint = json.loads((Path(tmp_root) / "campaign.json").read_text(encoding="utf-8"))
    assert checkpoint["state"] == ("complete" if count == 2 else "limited")
    assert checkpoint["selected_work_ids"] == [key for key, row in rows[:2]]
    assert checkpoint["processed_work_ids"] == [key for key, row in rows[:2]]
    assert runner.calls == 3
    assert runner.released == 2
    assert [store.load()[key]["status"] for key, row in rows[:2]] == ["archived"] * 2
    if count > 2:
        assert store.load()[rows[2][0]]["status"] == "audio_ok"


def test_campaign_resume_accepts_completed_rows_that_leave_the_pending_queue(tmp_root, monkeypatch):
    store, rows = _seed_audio(tmp_root, 2)
    runner = RiskOnceRunner()
    monkeypatch.setattr("bili_asr.asr.ASRRunner", lambda config: runner)

    def pending_selector(current_store, entries, scope):
        return [(key, row) for key, row in sorted(entries.items()) if row["status"] != "archived"], None

    campaign = CampaignRunner(tmp_root, offline=True, sleep=lambda seconds: None,
                              scope_rows=pending_selector)
    assert campaign.run("pending", 2).exit_code == 2
    result = campaign.run("pending", 2, resume=True)
    assert result.exit_code == 0
    assert result.selected == [key for key, row in rows]
    assert result.processed == [key for key, row in rows]
    assert runner.calls == 3


def test_campaign_resume_refuses_unprocessed_members_that_leave_the_scope(tmp_root, monkeypatch):
    store, rows = _seed_audio(tmp_root, 3)
    runner = RiskOnceRunner()
    monkeypatch.setattr("bili_asr.asr.ASRRunner", lambda config: runner)
    excluded = set()

    def pending_selector(current_store, entries, scope):
        return [(key, row) for key, row in sorted(entries.items())
                if row["status"] != "archived" and key not in excluded], None

    campaign = CampaignRunner(tmp_root, offline=True, sleep=lambda seconds: None,
                              scope_rows=pending_selector)
    assert campaign.run("pending", 2).exit_code == 2
    prior = (Path(tmp_root) / "campaign.json").read_bytes()
    excluded.add(rows[1][0])
    with pytest.raises(ValueError, match="corrupt/mismatch"):
        campaign.run("pending", 2, resume=True)
    assert runner.calls == 2
    assert (Path(tmp_root) / "campaign.json").read_bytes() == prior


def test_campaign_resume_keeps_exact_scope_matching_for_equivalent_grammars(tmp_root, monkeypatch, capsys):
    store, rows = _seed_audio(tmp_root, 2)
    runner = RiskOnceRunner()
    monkeypatch.setattr("bili_asr.asr.ASRRunner", lambda config: runner)
    monkeypatch.setattr("bili_asr.cli.time.sleep", lambda seconds: None)
    argv = ["campaign", "--archive-root", tmp_root, "--offline", "--limit", "2"]
    assert cli.main(argv + ["--scope", ",".join(key for key, row in rows)]) == 2
    prior = (Path(tmp_root) / "campaign.json").read_bytes()
    capsys.readouterr()
    assert cli.main(argv + ["--scope", " ".join(key for key, row in rows), "--resume"]) == 1
    assert runner.calls == 2
    assert (Path(tmp_root) / "campaign.json").read_bytes() == prior
    assert capsys.readouterr().err == "campaign: invalid configuration or execution failure\n"
