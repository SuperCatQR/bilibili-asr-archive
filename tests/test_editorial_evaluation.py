"""Evaluation replays actual stored bytes and never relaxes the validator."""
import json
from copy import deepcopy

import pytest

from bili_asr.editorial import EditorialConfig
from bili_asr.services.editorial_evaluation import load_sample, replay_sample
from bili_asr.services.editorial_provider_evaluation import evaluate_provider
from tests import test_ai_editorial as fixtures
from tests.test_editorial_regeneration import ReferenceClient, queued


@pytest.fixture
def database(tmp_path):
    yield from fixtures.database.__wrapped__(tmp_path)


def saved_failure(database, tmp_path):
    _, _, _, executor, _, _ = queued(database, tmp_path, ReferenceClient(failures=10),
                                    EditorialConfig(max_chunk_regenerations=0))
    assert executor.run().failed == 1
    return database.execute("SELECT call_id FROM editorial_model_calls").fetchone()[0]


def test_replay_is_read_only_and_feedback_is_only_a_preview(database, tmp_path):
    call_id = saved_failure(database, tmp_path)
    before = (tmp_path / "archive.db").read_bytes()
    sample = load_sample(tmp_path / "archive.db", call_id)
    original = deepcopy(sample)
    report = replay_sample(sample)
    assert report["validation"]["diagnostic"]["reason"] == "cross_paragraph_reference"
    assert report["feedback_preview"]["provider_called"] is False
    assert report["physical_calls"] == 0
    assert report["semantic_quality"] == "not_reviewed"
    assert sample == original
    assert (tmp_path / "archive.db").read_bytes() == before
    assert "messages" not in json.dumps(report) and "paragraphs\": [" not in json.dumps(report)


def test_replay_rejects_changed_request_instead_of_fabricating_match(database, tmp_path):
    call_id = saved_failure(database, tmp_path)
    row = database.execute("SELECT request_json FROM editorial_model_calls").fetchone()
    request = json.loads(row[0])
    request["request"]["messages"][1]["content"] = "{}"
    with database:
        database.execute("UPDATE editorial_model_calls SET request_json=?", (json.dumps(request),))
    with pytest.raises(ValueError, match="fingerprint|frozen chunk"):
        load_sample(tmp_path / "archive.db", call_id)


def test_replay_rejects_changed_frozen_identity(database, tmp_path):
    call_id = saved_failure(database, tmp_path)
    prepared = json.loads(database.execute("SELECT prepared_json FROM editorial_inputs").fetchone()[0])
    prepared["snapshot"]["config"]["top_p"] = 1
    with database:
        database.execute("UPDATE editorial_inputs SET prepared_json=?", (json.dumps(prepared),))
    with pytest.raises(ValueError, match="identity"):
        load_sample(tmp_path / "archive.db", call_id)


@pytest.mark.parametrize("kind", ["response_replay", "local_precheck", "unknown"])
def test_replay_refuses_nonphysical_evidence(database, tmp_path, kind):
    call_id = saved_failure(database, tmp_path)
    request = json.loads(database.execute("SELECT request_json FROM editorial_model_calls").fetchone()[0])
    request["invocation_kind"] = kind
    with database:
        database.execute("UPDATE editorial_model_calls SET request_json=?", (json.dumps(request),))
    with pytest.raises(ValueError, match="original physical"):
        load_sample(tmp_path / "archive.db", call_id)


@pytest.mark.parametrize("fingerprint_present", [True, False])
def test_replay_refuses_changed_sampling_controls(database, tmp_path, fingerprint_present):
    call_id = saved_failure(database, tmp_path)
    request = json.loads(database.execute("SELECT request_json FROM editorial_model_calls").fetchone()[0])
    request["request"]["top_p"] = 1
    if not fingerprint_present:
        del request["request_fingerprint"]
    with database:
        database.execute("UPDATE editorial_model_calls SET request_json=?", (json.dumps(request),))
    with pytest.raises(ValueError, match="fingerprint|controls"):
        load_sample(tmp_path / "archive.db", call_id)


def test_legacy_raw_request_marks_absent_fingerprint(database, tmp_path):
    call_id = saved_failure(database, tmp_path)
    stored = json.loads(database.execute("SELECT request_json FROM editorial_model_calls").fetchone()[0])
    with database:
        database.execute("UPDATE editorial_model_calls SET request_json=?", (json.dumps(stored["request"]),))
    assert replay_sample(load_sample(tmp_path / "archive.db", call_id))[
        "request_fingerprint_evidence"] == "unavailable_legacy"


def test_provider_budget_survives_restart_and_refuses_changed_identity(database, tmp_path):
    call_id = saved_failure(database, tmp_path)
    sample = load_sample(tmp_path / "archive.db", call_id)
    ledger = tmp_path / "private-experiment.db"
    client = ReferenceClient(failures=10)
    args = {"endpoint": "https://api.deepseek.com", "model": "deepseek-flash",
            "allow_paid_calls": True, "client": client}
    report = evaluate_provider(sample, ledger, **args)
    assert len(client.requests) == report["physical_calls"] == 4
    assert all(r["max_tokens"] == 8192 for r in client.requests)
    assert client.requests[0]["temperature"] == .2
    assert client.requests[2]["reasoning_effort"] == "low" and "temperature" not in client.requests[2]
    assert all(not r["validation"]["accepted"] for r in report["calls"])
    assert evaluate_provider(sample, ledger, **args)["physical_calls"] == 4
    assert len(client.requests) == 4
    args["model"] = "different-model"
    with pytest.raises(ValueError, match="identity or budget changed"):
        evaluate_provider(sample, ledger, **args)


def test_unknown_send_is_consumed_before_http_and_never_reissued(database, tmp_path):
    import sqlite3
    call_id = saved_failure(database, tmp_path)
    sample = load_sample(tmp_path / "archive.db", call_id)
    ledger = tmp_path / "private-experiment.db"
    class CrashClient:
        def complete(self, request, config):
            with sqlite3.connect(ledger) as other:
                assert other.execute("SELECT COUNT(*) FROM calls").fetchone()[0] == 1
            raise SystemExit("simulated process crash")
    args = {"endpoint": "https://api.deepseek.com", "model": "deepseek-flash", "allow_paid_calls": True}
    with pytest.raises(SystemExit):
        evaluate_provider(sample, ledger, client=CrashClient(), **args)
    client = ReferenceClient(failures=0)
    report = evaluate_provider(sample, ledger, client=client, **args)
    assert report["physical_calls"] == 2 and len(client.requests) == 1
    assert report["calls"][0]["outcome"] == "unknown_send_consumed"


def test_provider_requires_explicit_opt_in_before_creating_ledger(database, tmp_path):
    call_id = saved_failure(database, tmp_path)
    ledger = tmp_path / "private-experiment.db"
    with pytest.raises(ValueError, match="allow-paid-calls"):
        evaluate_provider(load_sample(tmp_path / "archive.db", call_id), ledger,
            endpoint="https://api.deepseek.com", model="deepseek-flash", allow_paid_calls=False)
    assert not ledger.exists()


def test_provider_refuses_existing_archive_as_ledger_without_source_writes(database, tmp_path):
    call_id = saved_failure(database, tmp_path)
    source = tmp_path / "archive.db"
    sample = load_sample(source, call_id)
    before = source.read_bytes()
    with pytest.raises(ValueError, match="dedicated provider experiment"):
        evaluate_provider(sample, source, endpoint="https://api.deepseek.com", model="deepseek-flash",
                          allow_paid_calls=True, client=ReferenceClient(failures=0))
    assert source.read_bytes() == before


def test_provider_errors_consume_reservations_without_leaking_error_text(database, tmp_path):
    from bili_asr.deepseek import DeepSeekError
    call_id = saved_failure(database, tmp_path)
    sample = load_sample(tmp_path / "archive.db", call_id)
    class FailedClient:
        requests = 0
        def complete(self, request, config):
            self.requests += 1
            raise DeepSeekError("private-provider-body-secret")
    client = FailedClient()
    args = {"endpoint": "https://api.deepseek.com", "model": "deepseek-flash",
            "allow_paid_calls": True, "client": client}
    ledger = tmp_path / "experiment.db"
    report = evaluate_provider(sample, ledger, **args)
    assert report["physical_calls"] == client.requests == 2
    assert "private-provider-body-secret" not in json.dumps(report)
    assert all(not call["http_response_accepted"] for call in report["calls"])
    evaluate_provider(sample, ledger, **args)
    assert client.requests == 2


@pytest.mark.parametrize("tamper", ["manifest", "gap", "over_budget", "unknown_variant", "variant_budget", "schema"])
def test_provider_refuses_corrupt_ledger_before_http(database, tmp_path, tamper):
    import sqlite3
    sample = load_sample(tmp_path / "archive.db", saved_failure(database, tmp_path))
    ledger = tmp_path / "experiment.db"
    client = ReferenceClient(failures=0)
    args = {"endpoint": "https://api.deepseek.com", "model": "deepseek-flash",
            "allow_paid_calls": True, "client": client}
    evaluate_provider(sample, ledger, **args)
    assert len(client.requests) == 2
    with sqlite3.connect(ledger) as connection:
        if tamper == "manifest":
            connection.execute("UPDATE manifest SET body='{}'")
        elif tamper == "gap":
            connection.execute("DELETE FROM calls WHERE ordinal=1")
        elif tamper in {"over_budget", "variant_budget"}:
            stop = 6 if tamper == "over_budget" else 5
            for ordinal in range(3, stop):
                connection.execute("INSERT INTO calls SELECT ?,variant,request,response,outcome,latency_ms "
                                   "FROM calls WHERE ordinal=1", (ordinal,))
        elif tamper == "unknown_variant":
            connection.execute("UPDATE calls SET variant='invented' WHERE ordinal=1")
        else:
            connection.execute("ALTER TABLE calls ADD COLUMN changed TEXT")
    before = ledger.read_bytes()
    with pytest.raises(ValueError, match="identity|ledger"):
        evaluate_provider(sample, ledger, **args)
    assert len(client.requests) == 2
    assert ledger.read_bytes() == before
