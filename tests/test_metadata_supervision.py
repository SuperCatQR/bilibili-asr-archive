"""Persistent admission, bounded no-progress escalation, and process recovery."""
from __future__ import annotations

import asyncio
import json
import multiprocessing
from dataclasses import replace

import pytest

from bili_asr.cli.main import main
from bili_asr.services.metadata_ingest import IngestionRunResult, MetadataIngestor
from bili_asr.services.metadata_supervision import MetadataSupervisionPolicy, MetadataSupervisor
from bili_asr.services.retry_maintenance_io import MaintenanceBusyError, maintenance_lock
from bili_asr.sources.models import GatewayAuthenticationError, GatewayRateLimited, UserVideoPage
from bili_asr.storage import MetadataRepository, open_database
from tests.fixtures.fake_bilibili_gateway import MID, FakeGateway, fake_gateway_seam  # noqa: F401
from tests.test_metadata_page_retries import _first_page


def policy(**changes):
    return replace(MetadataSupervisionPolicy(), initial_backoff_seconds=10, maximum_backoff_seconds=40,
        maximum_consecutive_no_progress=3, maximum_no_progress_seconds=1000,
        maximum_wait_seconds=1000, maximum_pages_per_cycle=2, **changes)


@pytest.fixture
def supervision(tmp_path):
    root = tmp_path / "archive"
    connection = open_database(root)
    repository = MetadataRepository(connection)
    clock = [100.0]
    gateway = FakeGateway()
    gateway.script_page(1, GatewayRateLimited(detail="private upstream response"))
    supervisor = MetadataSupervisor(repository, archive_root=root, state_path=root / "supervision.json",
        policy=policy(), clock=lambda: clock[0])
    yield root, repository, clock, gateway, supervisor
    connection.close()


@pytest.mark.parametrize("version", [2, True, 1.0])
def test_policy_rejects_unknown_or_noninteger_versions(version):
    with pytest.raises(ValueError, match="unsupported metadata supervision policy version"):
        MetadataSupervisionPolicy(version=version)


@pytest.mark.parametrize("field,value", [
    ("maximum_consecutive_no_progress", 0),
    ("maximum_no_progress_seconds", -1),
    ("maximum_wait_seconds", True),
    ("initial_backoff_seconds", 1.5),
    ("maximum_backoff_seconds", "3600"),
    ("maximum_pages_per_cycle", 0),
])
def test_policy_rejects_invalid_budget_values(field, value):
    with pytest.raises(ValueError, match="positive integers: " + field):
        MetadataSupervisionPolicy(**{field: value})


def test_policy_rejects_inverted_backoff_bounds():
    with pytest.raises(ValueError, match="backoff bounds are inverted"):
        MetadataSupervisionPolicy(initial_backoff_seconds=11, maximum_backoff_seconds=10)


@pytest.mark.parametrize("field", ["maximum_pages_per_cycle", "maximum_consecutive_no_progress"])
def test_policy_caps_request_and_retry_counts(field):
    with pytest.raises(ValueError, match="bound exceeds 100"):
        MetadataSupervisionPolicy(**{field: 101})


def test_policy_file_preserves_explicit_bounds_and_supplies_defaults(tmp_path):
    path = tmp_path / "supervision-policy.json"
    path.write_text(json.dumps({"maximum_pages_per_cycle": 100, "maximum_consecutive_no_progress": 100,
        "initial_backoff_seconds": 10, "maximum_backoff_seconds": 10}), encoding="utf-8")
    assert MetadataSupervisionPolicy.from_file(str(path)) == MetadataSupervisionPolicy(
        maximum_pages_per_cycle=100, maximum_consecutive_no_progress=100,
        initial_backoff_seconds=10, maximum_backoff_seconds=10)


def test_policy_file_rejects_unknown_fields_instead_of_silently_ignoring_them(tmp_path):
    path = tmp_path / "supervision-policy.json"
    path.write_text('{"maximum_page_per_cycle": 1}', encoding="utf-8")
    with pytest.raises(ValueError, match="unknown metadata supervision policy field"):
        MetadataSupervisionPolicy.from_file(path)


@pytest.mark.parametrize("mid", [0, -1, True, str(MID)])
def test_invalid_creator_is_rejected_before_state_or_collection(supervision, mid):
    _, repo, _, gateway, supervisor = supervision
    with pytest.raises(ValueError, match="mid must be positive"):
        supervisor.collect(MetadataIngestor(gateway, repo), mid=mid)
    assert not supervisor.state_path.exists()
    assert gateway.page_calls == []
    assert repo.connection.execute("SELECT COUNT(*) FROM ingestion_runs").fetchone()[0] == 0


@pytest.mark.parametrize("damage,message", [
    ("missing_field", "unsupported metadata supervision state"),
    ("unknown_field", "unsupported metadata supervision state"),
    ("format", "unsupported metadata supervision state"),
    ("state", "invalid metadata supervision state"),
    ("policy_hash", "policy changed"),
])
def test_damaged_state_is_preserved_and_stops_collection(supervision, damage, message):
    _, repo, _, gateway, supervisor = supervision
    state = supervisor.inspect(MID)
    if damage == "missing_field":
        del state["last_run_id"]
    elif damage == "unknown_field":
        state["unexpected_field"] = 1
    elif damage == "format":
        state["format"] = "metadata-supervision/v2"
    elif damage == "state":
        state["state"] = "completed"
    else:
        state["policy_sha256"] = "0" * 64
    supervisor.state_path.write_text(json.dumps(state), encoding="utf-8")
    before = supervisor.state_path.read_bytes()
    with pytest.raises(ValueError, match=message):
        supervisor.collect(MetadataIngestor(gateway, repo), mid=MID)
    assert supervisor.state_path.read_bytes() == before
    assert gateway.page_calls == []
    assert repo.connection.execute("SELECT COUNT(*) FROM ingestion_runs").fetchone()[0] == 0


@pytest.mark.parametrize("field,value", [
    ("monitoring_started_at", -1),
    ("updated_at", True),
    ("next_action_at", float("inf")),
    ("accumulated_wait_seconds", float("nan")),
    ("no_progress_wait_seconds", "0"),
    ("last_progress_at", -1),
    ("last_progress_at", True),
    ("wait_accounted_at", float("inf")),
    ("wait_accounted_at", "0"),
])
def test_invalid_durable_clocks_preserve_evidence_and_stop_collection(supervision, field, value):
    _, repo, _, gateway, supervisor = supervision
    state = supervisor.inspect(MID)
    state[field] = value
    supervisor.state_path.write_text(json.dumps(state), encoding="utf-8")
    before = supervisor.state_path.read_bytes()
    with pytest.raises(ValueError, match="invalid metadata supervision clock: " + field):
        supervisor.collect(MetadataIngestor(gateway, repo), mid=MID)
    assert supervisor.state_path.read_bytes() == before
    assert gateway.page_calls == []


def test_clock_rollback_does_not_rewrite_cooldown_or_admit_a_request(supervision):
    _, repo, clock, gateway, supervisor = supervision
    first = supervisor.collect(MetadataIngestor(gateway, repo), mid=MID)
    assert first.supervision["next_action_at"] == 110
    before = supervisor.state_path.read_bytes()
    clock[0] = 99
    with pytest.raises(ValueError, match="clock moved backwards"):
        supervisor.collect(MetadataIngestor(gateway, repo), mid=MID)
    assert supervisor.state_path.read_bytes() == before
    assert len(gateway.page_calls) == 1


@pytest.mark.parametrize("page_limit", [0, -1, True, 1.5, "1"])
def test_invalid_page_limits_are_rejected_before_state_or_collection(supervision, page_limit):
    _, repo, _, gateway, supervisor = supervision
    with pytest.raises(ValueError, match="invalid supervised page limit"):
        supervisor.collect(MetadataIngestor(gateway, repo), mid=MID, page_limit=page_limit)
    assert not supervisor.state_path.exists()
    assert gateway.page_calls == []


@pytest.mark.parametrize("exception_type", [RuntimeError, KeyboardInterrupt])
def test_collection_exception_is_persisted_and_rethrown_before_restart(supervision, monkeypatch, exception_type):
    root, repo, clock, gateway, supervisor = supervision
    ingestor = MetadataIngestor(gateway, repo)
    failure = exception_type("private interruption detail")

    def interrupted(**_options):
        clock[0] = 105
        raise failure

    monkeypatch.setattr(ingestor, "collect_user_pages", interrupted)
    with pytest.raises(exception_type) as raised:
        supervisor.collect(ingestor, mid=MID)
    assert raised.value is failure
    persisted = json.loads(supervisor.state_path.read_text(encoding="utf-8"))
    assert persisted["state"] == "needs_attention"
    assert persisted["error_code"] == "supervision_interrupted"
    assert persisted["consecutive_no_progress"] == 1
    assert persisted["active_attempt"] is None and persisted["updated_at"] == 105
    assert persisted["last_progress_at"] is None and persisted["accumulated_wait_seconds"] == 0
    assert "private interruption detail" not in supervisor.state_path.read_text(encoding="utf-8")
    restarted = MetadataSupervisor(repo, archive_root=root, state_path=supervisor.state_path,
        policy=policy(), clock=lambda: 110)
    blocked = restarted.collect(MetadataIngestor(gateway, repo), mid=MID)
    assert blocked.result is None and blocked.supervision["consecutive_no_progress"] == 1
    assert gateway.page_calls == []


def test_wrong_creator_result_is_rejected_and_incomplete_attempt_reconciles_on_restart(supervision, monkeypatch):
    root, repo, _, gateway, supervisor = supervision
    ingestor = MetadataIngestor(gateway, repo)
    wrong_result = IngestionRunResult(run_id="wrong-creator", mid=MID + 1, outcome="limited",
        next_cursor=None, page_count=0, video_count=0, part_count=0, error_code=None, collected_page_count=0)
    monkeypatch.setattr(ingestor, "collect_user_pages", lambda **_options: wrong_result)
    with pytest.raises(ValueError, match="result scope mismatch"):
        supervisor.collect(ingestor, mid=MID)
    persisted = json.loads(supervisor.state_path.read_text(encoding="utf-8"))
    assert persisted["state"] == "running" and persisted["mid"] == MID
    assert persisted["last_run_id"] is None and persisted["last_progress_at"] is None
    restarted = MetadataSupervisor(repo, archive_root=root, state_path=supervisor.state_path,
        policy=policy(), clock=lambda: 105)
    state = restarted.inspect(MID)
    assert state["state"] == "needs_attention" and state["reason"] == "previous_process_interrupted"
    assert state["error_code"] == "supervision_interrupted" and state["active_attempt"] is None
    assert state["last_run_id"] is None and state["consecutive_no_progress"] == 1
    assert restarted.collect(MetadataIngestor(gateway, repo), mid=MID).result is None
    assert gateway.page_calls == []
    assert repo.connection.execute("SELECT COUNT(*) FROM ingestion_runs").fetchone()[0] == 0


def test_persisted_backoff_and_streak_survive_service_reconstruction(supervision):
    root, repo, clock, gateway, supervisor = supervision
    first = supervisor.collect(MetadataIngestor(gateway, repo), mid=MID)
    assert first.supervision["state"] == "backoff"
    assert first.supervision["consecutive_no_progress"] == 1
    assert first.supervision["next_action_at"] == 110
    assert "private upstream response" not in supervisor.state_path.read_text()
    clock[0] = 105
    restarted = MetadataSupervisor(repo, archive_root=root, state_path=supervisor.state_path,
        policy=policy(), clock=lambda: clock[0])
    blocked = restarted.collect(MetadataIngestor(gateway, repo), mid=MID)
    assert blocked.result is None and len(gateway.page_calls) == 1
    assert blocked.supervision["accumulated_wait_seconds"] == 5
    clock[0] = 110
    second = restarted.collect(MetadataIngestor(gateway, repo), mid=MID)
    assert second.supervision["consecutive_no_progress"] == 2
    assert second.supervision["next_action_at"] == 130
    assert second.supervision["accumulated_wait_seconds"] == 10
    clock[0] = 130
    stopped = restarted.collect(MetadataIngestor(gateway, repo), mid=MID)
    assert stopped.supervision["state"] == "needs_attention"
    assert stopped.supervision["reason"] == "consecutive_no_progress_budget"
    clock[0] = 200
    assert restarted.collect(MetadataIngestor(gateway, repo), mid=MID).result is None
    assert len(gateway.page_calls) == 3


@pytest.mark.parametrize("field,value,at,reason", [
    ("maximum_wait_seconds", 10, 110, "no_progress_wait_budget"),
    ("maximum_no_progress_seconds", 7, 107, "no_progress_time_budget"),
])
def test_wait_and_elapsed_budgets_stop_before_another_request(supervision, field, value, at, reason):
    root, repo, clock, gateway, _ = supervision
    supervisor = MetadataSupervisor(repo, archive_root=root, state_path=root / "bounded.json",
        policy=replace(policy(), **{field: value}), clock=lambda: clock[0])
    supervisor.collect(MetadataIngestor(gateway, repo), mid=MID)
    clock[0] = at
    state = supervisor.collect(MetadataIngestor(gateway, repo), mid=MID).supervision
    assert state["state"] == "needs_attention" and state["reason"] == reason
    assert len(gateway.page_calls) == 1


def test_new_committed_progress_resets_streak_but_not_lifetime_wait(supervision, monkeypatch):
    _, repo, clock, gateway, supervisor = supervision
    supervisor.collect(MetadataIngestor(gateway, repo), mid=MID)
    clock[0] = 110
    _first_page(gateway)
    gateway.script_page(2, GatewayRateLimited())
    async def no_wait(_delay):
        return None
    monkeypatch.setattr("bili_asr.services.metadata_ingest.asyncio.sleep", no_wait)
    result = supervisor.collect(MetadataIngestor(gateway, repo), mid=MID)
    state = result.supervision
    assert state["state"] == "backoff" and state["consecutive_no_progress"] == 0
    assert state["last_progress_at"] == 110
    assert state["last_progress"]["videos"] == 1 and state["last_progress"]["parts"] == 1
    assert state["last_progress"]["next_page"] == 2
    assert state["last_progress"]["boundary_page"] == 1
    assert state["accumulated_wait_seconds"] == 10 and state["no_progress_wait_seconds"] == 0
    clock[0] = 120
    again = supervisor.collect(MetadataIngestor(gateway, repo), mid=MID)
    assert again.supervision["consecutive_no_progress"] == 1  # Prefix replay is not new progress.
    assert again.supervision["last_progress_at"] == 110


def test_limited_is_resumable_not_complete_and_pages_are_bounded(supervision, monkeypatch):
    _, repo, _, gateway, supervisor = supervision
    _first_page(gateway)
    async def no_wait(_delay):
        return None
    monkeypatch.setattr("bili_asr.services.metadata_ingest.asyncio.sleep", no_wait)
    limited = supervisor.collect(MetadataIngestor(gateway, repo), mid=MID, page_limit=1)
    assert limited.result.outcome == "limited"
    assert limited.supervision["state"] == "ready"
    gateway.script_page(2, UserVideoPage(mid=MID, page_number=2, videos=(), observed_total=1))
    complete = supervisor.collect(MetadataIngestor(gateway, repo), mid=MID, page_limit=999)
    assert complete.supervision["state"] == "complete"
    limit = repo.connection.execute("SELECT requested_page_limit FROM ingestion_runs ORDER BY rowid DESC LIMIT 1").fetchone()[0]
    assert limit == 2
    calls = len(gateway.page_calls)
    assert supervisor.collect(MetadataIngestor(gateway, repo), mid=MID).result is None
    assert len(gateway.page_calls) == calls


def test_authentication_and_explicit_rewinds_require_attention(supervision):
    _, repo, _, gateway, supervisor = supervision
    for options in ({"start_page": 1}, {"incremental": True}, {"skip_failed_page": True}):
        with pytest.raises(ValueError, match="cannot rewind or skip"):
            supervisor.collect(MetadataIngestor(gateway, repo), mid=MID, **options)
    assert not supervisor.state_path.exists()
    gateway.script_page(1, GatewayAuthenticationError())
    result = supervisor.collect(MetadataIngestor(gateway, repo), mid=MID)
    assert result.supervision["state"] == "needs_attention" and result.supervision["reason"] == "auth_error"


def test_policy_scope_corruption_and_concurrent_lock_fail_closed(supervision):
    root, repo, _, gateway, supervisor = supervision
    supervisor.collect(MetadataIngestor(gateway, repo), mid=MID)
    with maintenance_lock(supervisor.state_path.with_suffix(".json.lock")):
        with pytest.raises(MaintenanceBusyError):
            supervisor.inspect(MID)
    changed = MetadataSupervisor(repo, archive_root=root, state_path=supervisor.state_path,
        policy=replace(policy(), maximum_wait_seconds=900), clock=lambda: 105)
    with pytest.raises(ValueError, match="policy changed"):
        changed.inspect(MID)
    with pytest.raises(ValueError, match="another archive or creator"):
        supervisor.inspect(MID + 1)
    state = json.loads(supervisor.state_path.read_text())
    state["consecutive_no_progress"] = -1
    supervisor.state_path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(ValueError, match="counter"):
        supervisor.collect(MetadataIngestor(gateway, repo), mid=MID)
    assert len(gateway.page_calls) == 1


def _run_in_new_process(root, state_path, now, output):
    connection = open_database(root)
    try:
        repo = MetadataRepository(connection)
        gateway = FakeGateway()
        gateway.script_page(1, GatewayRateLimited())
        supervisor = MetadataSupervisor(repo, archive_root=root, state_path=state_path, policy=policy(), clock=lambda: now)
        outcome = supervisor.collect(MetadataIngestor(gateway, repo), mid=MID)
        output.put({"state": outcome.supervision, "calls": len(gateway.page_calls)})
    finally:
        connection.close()


def test_separate_process_restart_preserves_budget_deadline_and_accumulated_wait(tmp_path):
    root, path = tmp_path / "archive", tmp_path / "state.json"
    context = multiprocessing.get_context("spawn")
    evidence = []
    for now in (100, 105, 110):
        output = context.Queue()
        process = context.Process(target=_run_in_new_process, args=(root, path, now, output))
        process.start()
        try:
            evidence.append(output.get(timeout=20))
            process.join(20)
            assert process.exitcode == 0
        finally:
            if process.is_alive():
                process.kill()
                process.join(10)
            output.close()
    assert [item["calls"] for item in evidence] == [1, 0, 1]
    assert [item["state"]["consecutive_no_progress"] for item in evidence] == [1, 1, 2]
    assert [item["state"]["next_action_at"] for item in evidence] == [110, 110, 130]
    assert [item["state"]["accumulated_wait_seconds"] for item in evidence] == [0, 5, 10]
    (tmp_path / "restart-evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")


def _killed_collection(root, state_path, entered):
    class WaitingGateway(FakeGateway):
        async def get_user_video_page(self, mid, page_number, page_size=30):
            entered.set()
            await asyncio.sleep(60)
    connection = open_database(root)
    repo = MetadataRepository(connection)
    supervisor = MetadataSupervisor(repo, archive_root=root, state_path=state_path, policy=policy(), clock=lambda: 100)
    supervisor.collect(MetadataIngestor(WaitingGateway(), repo), mid=MID)


def test_killed_process_is_reconciled_and_never_resets_to_fresh_retry(tmp_path):
    root, path = tmp_path / "archive", tmp_path / "state.json"
    context = multiprocessing.get_context("spawn")
    entered = context.Event()
    process = context.Process(target=_killed_collection, args=(root, path, entered))
    process.start()
    try:
        assert entered.wait(20)
    finally:
        process.kill()
        process.join(10)
    connection = open_database(root)
    try:
        supervisor = MetadataSupervisor(MetadataRepository(connection), archive_root=root,
            state_path=path, policy=policy(), clock=lambda: 105)
        state = supervisor.inspect(MID)
        assert state["state"] == "needs_attention" and state["consecutive_no_progress"] == 1
        assert state["reason"] == "previous_process_interrupted"
        assert state["last_run_id"] is not None and state["last_progress_at"] is None
        assert state["accumulated_wait_seconds"] == 0  # Runtime is not invented wait evidence.
    finally:
        connection.close()


def test_recovered_committed_progress_uses_its_evidence_time_not_restart_time(supervision, monkeypatch):
    _, repo, clock, gateway, supervisor = supervision
    baseline = supervisor.inspect(MID)
    baseline.update(state="running", active_attempt={"started_at": 100, "previous_run_rowid": 0})
    supervisor.state_path.write_text(json.dumps(baseline), encoding="utf-8")
    _first_page(gateway)
    async def no_wait(_delay):
        return None
    monkeypatch.setattr("bili_asr.services.metadata_ingest.asyncio.sleep", no_wait)
    MetadataIngestor(gateway, repo).collect_user_pages(mid=MID, page_limit=1)
    with repo.connection:
        repo.connection.execute("UPDATE ingestion_pages SET started_at=100,finished_at=101")
    clock[0] = 1200
    state = supervisor.inspect(MID)
    assert state["last_progress_at"] == 101
    assert state["last_progress"]["next_page"] == 2
    assert state["state"] == "needs_attention" and state["reason"] == "no_progress_time_budget"
    assert state["accumulated_wait_seconds"] == 0


def test_cli_single_cycle_and_status_do_not_request_during_durable_cooldown(tmp_root, fake_gateway_seam, capsys):
    gateway = fake_gateway_seam
    gateway.script_page(1, GatewayRateLimited())
    arguments = ["fetch-meta", "--archive-root", tmp_root, "--supervised"]
    assert main(arguments) == 2
    assert main(arguments) == 3
    assert len(gateway.page_calls) == 1
    assert main(arguments + ["--supervision-status"]) == 0
    assert len(gateway.page_calls) == 1
    assert '"state": "backoff"' in capsys.readouterr().out
