"""Provider termination is finite, safe, and never expands a paid retry budget."""

import json

import pytest

from bili_asr.deepseek import DeepSeekError, parse_response
from bili_asr.services.workflow_retry import guarded_retry_failed
from bili_asr.services.workflow_status import explain_workflow_job
from bili_asr.workflow_errors import safe_job_details
from bili_asr.workflow_failure_policy import failure_policy
from tests import test_ai_editorial as fixtures
from tests.test_ai_editorial import FakeClient, runtime

database = fixtures.database


def response(reason):
    return {"usage": {"prompt_tokens": 100, "completion_tokens": 80,
                      "completion_tokens_details": {"reasoning_tokens": 75}},
            "choices": [{"finish_reason": reason, "message": {"content": "", "reasoning_content": "SECRET"}}]}


@pytest.mark.parametrize("reason,code,expected", [
    ("length", "deepseek_output_truncated", "length"),
    ("content_filter", "deepseek_content_filtered", "content_filter"),
    ("stop", "deepseek_empty_output", "stop"),
    ("tool_calls", "deepseek_unsupported_completion", "tool_calls"),
    ("function_call", "deepseek_unsupported_completion", "function_call"),
    ("SECRET " * 1000, "deepseek_output_interrupted", "unknown"),
    ({"SECRET": []}, "deepseek_output_interrupted", "unknown"),
    (None, "deepseek_output_interrupted", "missing"),
])
def test_finish_reasons_are_distinct_and_diagnostics_never_reflect_content(reason, code, expected):
    with pytest.raises(DeepSeekError) as caught:
        parse_response(response(reason))
    error = caught.value
    assert error.error_code == code
    assert error.safe_details["finish_reason"] == expected
    assert error.safe_details["length_exceeded"] is (reason == "length")
    assert error.safe_details["reasoning_tokens"] == 75
    assert error.safe_details["reasoning_chars"] == 6
    assert safe_job_details(error.safe_details) == error.safe_details
    assert "SECRET" not in str(error) + json.dumps(error.safe_details)
    policy = failure_policy(code)
    assert policy.automatic_retry is False
    assert policy.retry_policy == ("manual" if reason in ("length", "stop") else "blocked")


class FilteredClient(FakeClient):
    def complete(self, request, config):
        self.requests.append(request)
        return response("content_filter")


def test_saved_filter_blocks_automatic_and_direct_retry_without_paid_send(database, tmp_path):
    client = FilteredClient()
    workflow, editorial, _, executor = runtime(database, tmp_path, client)
    prepared = editorial.prepare(1, None, fixtures.EditorialConfig())
    proof, *_ = workflow.request_editorial(video_part_id=1, input_id=prepared["input_id"])
    assert executor.run().failed == 1 and len(client.requests) == 1
    saved = [tuple(row) for row in database.execute("SELECT * FROM editorial_model_calls")]
    attempt = database.execute("SELECT error_code,result_json FROM workflow_attempts WHERE job_id=?", (proof,)).fetchone()
    assert attempt["error_code"] == "deepseek_content_filtered"
    assert "SECRET" not in attempt["result_json"]
    assert editorial.recovery_status_for_job(proof) == {
        "eligible": False, "exhausted": False, "reason": "deepseek_content_filtered"}
    denied = guarded_retry_failed(workflow, job_ids=[proof], no_control_state=True, automatic=True)
    assert denied["requeued"] == 0
    # Simulate a legacy caller bypassing the modern retry facade. Even its
    # requeue cannot authorize a second request against the frozen filter result.
    with database:
        database.execute("UPDATE workflow_jobs SET last_error_code='DeepSeekError' WHERE job_id=?", (proof,))
        database.execute("UPDATE editorial_model_calls SET error_code='DeepSeekError'")
    historical = [tuple(row) for row in database.execute("SELECT * FROM editorial_model_calls")]
    report = explain_workflow_job(database, proof, no_control_state=True)
    assert report["error_code"] == "DeepSeekError"
    assert report["provider_termination"]["error_code"] == "deepseek_content_filtered"
    assert report["provider_termination"]["diagnostic_source"] == "stored_response_replay"
    assert report["recovery"]["next_action"] == "review_provider_filter"
    assert "SECRET" not in json.dumps(report)
    with database:
        database.execute("UPDATE workflow_jobs SET status='queued' WHERE job_id=?", (proof,))
    assert executor.run().failed == 1 and len(client.requests) == 1
    assert [tuple(row) for row in database.execute("SELECT * FROM editorial_model_calls")] == historical
    assert saved[0][0] == historical[0][0]
