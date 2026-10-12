"""Paid invocation budgets and request policy upgrades use only offline fakes."""

import json
from contextlib import closing
from copy import deepcopy

import pytest
import requests

from bili_asr import cli
from bili_asr.deepseek import DeepSeekClient, DeepSeekError, DeepSeekTransportError, request_body
from bili_asr.editorial import EditorialConfig, digest
from bili_asr.storage import open_database
from tests import test_ai_editorial as editorial_fixtures
from tests.test_ai_editorial import envelope, no_changes, runtime


@pytest.fixture
def database(tmp_path):
    yield from editorial_fixtures.database.__wrapped__(tmp_path)


class ReferenceClient:
    def __init__(self, failures=1, on_call=None):
        self.requests = []
        self.failures = failures
        self.on_call = on_call

    def complete(self, request, config):
        self.requests.append(deepcopy(request))
        if self.on_call:
            self.on_call()
        chunk = json.loads(request["messages"][1]["content"])
        value = no_changes(chunk)
        if len(self.requests) <= self.failures:
            value["paragraphs"][0]["issues"] = [{"note": "核对", "candidate": "",
                "evidence_refs": [chunk["editable_segments"][1]["segment_id"]]}]
        return envelope(value)


def queued(connection, root, client, config=None):
    workflow, repository, handlers, executor = runtime(connection, root, client)
    prepared = repository.prepare(1, None, config or EditorialConfig())
    job_id, _, _, _ = workflow.request_editorial(video_part_id=1, input_id=prepared["input_id"])
    return workflow, repository, handlers, executor, prepared, job_id


@pytest.mark.parametrize("endpoint", ["https://api.deepseek.com", "https://opencode.ai/zen/go/v1"])
def test_versioned_request_modes_have_only_effective_parameters(endpoint):
    config = EditorialConfig(base_url=endpoint)
    body = request_body({}, config)
    assert body["thinking"] == {"type": "enabled"}
    assert body["reasoning_effort"] == "high"
    assert body["top_p"] == .95 and "temperature" not in body
    disabled = request_body({}, EditorialConfig(base_url=endpoint, thinking_mode="disabled", temperature=.2))
    assert disabled["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in disabled and disabled["top_p"] == 1
    assert disabled["temperature"] == .2
    legacy = request_body({}, EditorialConfig.from_snapshot({"base_url": endpoint}))
    assert legacy["thinking"] == {"type": "enabled", "reasoning_effort": "high"}
    assert "reasoning_effort" not in legacy and legacy["top_p"] == .95


@pytest.mark.parametrize("value", [-1, 2.1, True, float("nan"), float("inf")])
def test_invalid_temperature_rejected_before_request(value):
    with pytest.raises(ValueError):
        EditorialConfig(thinking_mode="disabled", temperature=value)
    with pytest.raises(ValueError):
        EditorialConfig(temperature=.2)


def test_transport_failure_has_distinct_safe_error_code():
    class Session:
        def post(self, *args, **kwargs):
            raise requests.ReadTimeout("private request details")
    with pytest.raises(DeepSeekTransportError, match="DeepSeek transport failed"):
        DeepSeekClient("offline-key", session=Session()).complete({}, EditorialConfig())


@pytest.mark.parametrize("error", [DeepSeekError("DeepSeek HTTP 402"), ValueError("invalid")])
def test_generic_provider_or_unknown_failure_is_not_maintenance_eligible(database, tmp_path, error):
    class FailedClient:
        def complete(self, request, config):
            raise error
    _, repository, _, executor, _, job_id = queued(database, tmp_path, FailedClient())
    assert executor.run().failed == 1
    assert repository.recovery_status_for_job(job_id)["eligible"] is False


def test_regeneration_persists_feedback_and_preserves_original_input(database, tmp_path):
    client = ReferenceClient()
    _, repository, _, executor, prepared, job_id = queued(database, tmp_path, client)
    frozen = deepcopy(prepared)
    assert executor.run().succeeded == 2
    assert len(client.requests) == 2
    assert client.requests[0]["messages"] == client.requests[1]["messages"][:2]
    feedback = json.loads(client.requests[1]["messages"][2]["content"])
    assert feedback["validation_diagnostic"]["reason"] == "cross_paragraph_reference"
    assert feedback["regeneration"] == 1
    assert repository.load_input(prepared["input_id"]) == frozen
    calls = repository.physical_calls(prepared["input_id"], prepared["chunks"][0]["chunk_id"])
    assert calls[0]["error_code"] == "RevisionValidationError"
    assert calls[1]["stored_request"]["recovery"]["previous_call_id"] == calls[0]["call_id"]
    assert repository.revision_for_job(job_id)


def test_repeated_bad_references_exhaust_once_and_remain_exhausted_after_restart(database, tmp_path):
    client = ReferenceClient(failures=10)
    workflow, repository, _, executor, prepared, job_id = queued(database, tmp_path, client)
    assert executor.run().failed == 1 and len(client.requests) == 3
    state = repository.recovery_status_for_job(job_id)
    assert state["exhausted"] and not state["eligible"]
    result = database.execute("SELECT result_json FROM workflow_attempts WHERE job_id=?", (job_id,)).fetchone()[0]
    assert json.loads(result)["diagnostic"]["physical_calls"] == 3
    assert workflow.explain_job(job_id)["error_code"] == "EditorialRecoveryExhausted"
    with closing(open_database(tmp_path)) as connection:
        new_client = ReferenceClient(failures=10)
        new_workflow, new_repository, _, new_executor = runtime(connection, tmp_path, new_client)
        new_workflow.requeue_failed(job_ids=[job_id])
        assert new_executor.run().failed == 1 and not new_client.requests
        assert len(new_repository.physical_calls(prepared["input_id"], prepared["chunks"][0]["chunk_id"])) == 3


def test_unknown_references_fail_once_without_regeneration(database, tmp_path):
    class UnknownClient(ReferenceClient):
        def complete(self, request, config):
            response = super().complete(request, config)
            value = json.loads(response["choices"][0]["message"]["content"])
            value["paragraphs"][0]["issues"][0]["evidence_refs"] = ["unknown-id"]
            return envelope(value)
    client = UnknownClient()
    _, repository, _, executor, _, job_id = queued(database, tmp_path, client)
    assert executor.run().failed == 1 and len(client.requests) == 1
    assert repository.recovery_status_for_job(job_id)["reason"] == "no_allowlisted_failure"


def test_cancel_during_provider_call_prevents_regeneration_and_checkpoint(database, tmp_path):
    client = ReferenceClient()
    workflow, _, _, executor, _, job_id = queued(database, tmp_path, client)
    client.on_call = lambda: workflow.cancel(job_ids=[job_id])
    executor.run()
    assert len(client.requests) == 1
    assert database.execute("SELECT COUNT(*) FROM editorial_chunk_results").fetchone()[0] == 0
    assert database.execute("SELECT COUNT(*) FROM editorial_revisions").fetchone()[0] == 0


def test_unknown_inflight_reservation_consumes_budget_without_call(database, tmp_path):
    client = ReferenceClient(failures=0)
    workflow, repository, _, executor, prepared, job_id = queued(database, tmp_path, client,
                                                               EditorialConfig(max_chunk_regenerations=0))
    job = workflow.claim("crashed-worker")
    chunk = prepared["chunks"][0]
    repository.begin_call(job, prepared["input_id"], chunk["chunk_id"], request_body(chunk, EditorialConfig()),
                          recovery={"policy": "paragraph-reference-v1", "max_physical_calls": 1, "regeneration": 0})
    workflow.fail(job_id, worker_id="crashed-worker", error_code="DeepSeekError")
    workflow.requeue_failed(job_ids=[job_id])
    assert executor.run().failed == 1 and not client.requests
    assert repository.recovery_status_for_job(job_id)["exhausted"]


def test_last_completed_envelope_replay_does_not_consume_budget(database, tmp_path):
    client = ReferenceClient(failures=0)
    workflow, repository, _, executor, prepared, job_id = queued(database, tmp_path, client,
                                                               EditorialConfig(max_chunk_regenerations=0))
    job = workflow.claim("crashed-worker")
    chunk = prepared["chunks"][0]
    request = request_body(chunk, EditorialConfig())
    call_id = repository.begin_call(job, prepared["input_id"], chunk["chunk_id"], request,
                                   recovery={"policy": "paragraph-reference-v1", "max_physical_calls": 1, "regeneration": 0})
    repository.finish_call(call_id, envelope(no_changes(chunk)))
    workflow.fail(job_id, worker_id="crashed-worker", error_code="crash")
    workflow.requeue_failed(job_ids=[job_id])
    assert executor.run().succeeded == 2 and not client.requests
    assert len(repository.physical_calls(prepared["input_id"], chunk["chunk_id"])) == 1
    row = database.execute("SELECT request_json FROM editorial_model_calls ORDER BY rowid DESC LIMIT 1").fetchone()
    assert json.loads(row[0])["invocation_kind"] == "response_replay"


def test_bad_cached_response_is_reclassified_then_regenerated_once(database, tmp_path):
    client = ReferenceClient(failures=0)
    workflow, repository, _, executor, prepared, job_id = queued(database, tmp_path, client)
    job = workflow.claim("crashed-worker")
    chunk = prepared["chunks"][0]
    request = request_body(chunk, EditorialConfig())
    call_id = repository.begin_call(job, prepared["input_id"], chunk["chunk_id"], request,
                                   recovery={"policy": "paragraph-reference-v1", "max_physical_calls": 3, "regeneration": 0})
    invalid = no_changes(chunk)
    invalid["paragraphs"][0]["issues"] = [{"note": "核对", "candidate": "", "evidence_refs": ["t1:s1"]}]
    repository.finish_call(call_id, envelope(invalid))
    with database:
        database.execute("UPDATE editorial_model_calls SET finished_at=123 WHERE call_id=?", (call_id,))
    workflow.fail(job_id, worker_id="crashed-worker", error_code="crash")
    workflow.requeue_failed(job_ids=[job_id])
    assert executor.run().succeeded == 2 and len(client.requests) == 1
    row = database.execute("SELECT finished_at,error_code FROM editorial_model_calls WHERE call_id=?", (call_id,)).fetchone()
    assert row["finished_at"] == 123 and row["error_code"] == "RevisionValidationError"
    assert len(repository.physical_calls(prepared["input_id"], chunk["chunk_id"])) == 2


def test_legacy_raw_call_is_classified_read_only_without_enabling_regeneration(database, tmp_path):
    client = ReferenceClient(failures=5)
    workflow, repository, _, executor, prepared, job_id = queued(database, tmp_path, client,
        EditorialConfig.from_snapshot({}))
    assert executor.run().failed == 1 and len(client.requests) == 1
    row = database.execute("SELECT call_id,request_json FROM editorial_model_calls").fetchone()
    raw = json.loads(row["request_json"])["request"]
    with database:
        database.execute("UPDATE editorial_model_calls SET request_json=? WHERE call_id=?", (json.dumps(raw), row["call_id"]))
    before = [tuple(r) for r in database.execute("SELECT * FROM editorial_model_calls")]
    assert repository.recovery_status_for_job(job_id) == {
        "eligible": True, "exhausted": False, "reason": "cross_paragraph_reference"}
    assert [tuple(r) for r in database.execute("SELECT * FROM editorial_model_calls")] == before
    workflow.requeue_failed(job_ids=[job_id])
    assert executor.run().failed == 1 and len(client.requests) == 2
    assert client.requests[0] == client.requests[1]
    assert repository.load_input(prepared["input_id"]) == prepared


def test_default_replan_reuses_legacy_but_explicit_new_limit_creates_new_identity(database, tmp_path):
    _, repository, _, _, prepared, _ = queued(database, tmp_path, ReferenceClient(),
        EditorialConfig.from_snapshot({}))
    # Remove fields that were absent in archives, recomputing fixture identity.
    legacy = deepcopy(prepared)
    for field in ("request_policy", "temperature", "max_chunk_regenerations"):
        del legacy["snapshot"]["config"][field]
    legacy["input_id"] = digest(legacy["snapshot"])
    repository.store_input(legacy)
    assert repository.build_input(1, None, EditorialConfig(), reuse_existing=True) == legacy
    fresh = repository.build_input(1, None, EditorialConfig(max_chunk_regenerations=1), reuse_existing=True)
    assert fresh["input_id"] != legacy["input_id"]
    assert repository.build_input(1, None, EditorialConfig(), reuse_existing=False)["input_id"] != legacy["input_id"]


def test_cli_freezes_temperature_and_rejects_ignored_enabled_temperature(database, tmp_path, capsys):
    args = ["workflow", "proofread", "--archive-root", str(tmp_path), "--part-id", "1", "--temperature", ".2"]
    assert cli.main(args) == 1
    assert "temperature requires disabled thinking" in capsys.readouterr().err
    assert cli.main(args + ["--thinking-mode", "disabled"]) == 0
    config = json.loads(database.execute("SELECT prepared_json FROM editorial_inputs").fetchone()[0])["snapshot"]["config"]
    assert config["temperature"] == .2 and config["request_policy"] == "deepseek-v2"
