"""Public evaluation boundaries preserve evidence and never make paid calls."""
import json
import sqlite3
from copy import deepcopy

import pytest

from bili_asr.editorial import digest
from bili_asr.services import editorial_evaluation as replay
from bili_asr.services import editorial_provider_evaluation as provider
from bili_asr.storage.editorial import EditorialRepository
from tests.test_editorial_evaluation import database, saved_failure
from tests.test_editorial_regeneration import ReferenceClient


@pytest.fixture
def sample(database, tmp_path):
    return replay.load_sample(tmp_path / "archive.db", saved_failure(database, tmp_path))


def campaign(sample, path, client=None):
    return provider.evaluate_campaign([sample], path, endpoint="https://api.deepseek.com",
        model="deepseek-flash", allow_paid_calls=True, client=client or ReferenceClient(failures=0))


@pytest.mark.parametrize("mutation,match", [
    ("unknown", "unknown frozen"), ("empty", "empty frozen"), ("source_id", "source identity"),
    ("precheck", "precheck"), ("budget", "estimate"), ("boundary", "boundary identity"),
])
def test_frozen_chunk_rejects_mutable_cache_corruption(sample, mutation, match):
    changed = deepcopy(sample["chunk"])
    if mutation == "unknown":
        changed["unexpected"] = True
    elif mutation == "empty":
        changed["editable_segments"] = []
    elif mutation == "source_id":
        changed["editable_segments"][0]["segment_id"] = "fabricated"
    elif mutation == "precheck":
        changed["local_precheck"] = [{"fabricated": True}]
    elif mutation == "budget":
        changed["budget_estimate"] = {}
    else:
        changed["chunk_id"] = "not-a-boundary"
        changed.pop("budget_estimate", None)
    with pytest.raises(ValueError, match=match):
        replay._validate_frozen_chunk(sample["prepared"], changed)


def test_frozen_v2_identity_is_verified_without_rewriting_chunk(sample):
    prepared, chunk = deepcopy(sample["prepared"]), deepcopy(sample["chunk"])
    chunk.pop("budget_estimate", None)
    chunk.pop("local_precheck", None)
    body = {k: v for k, v in chunk.items() if k != "chunk_id"}
    chunk["chunk_id"] = digest({"input_id": prepared["input_id"], "start": 0,
                                "end": len(chunk["editable_segments"]), "chunk": body})
    original = deepcopy(chunk)
    replay._validate_frozen_chunk(prepared, chunk)
    assert chunk == original


@pytest.mark.parametrize("args", [([], 2), (["duplicate", "duplicate"], 2), (["any"], 3)])
def test_historical_cohort_rejects_invalid_selection_before_database_open(tmp_path, args):
    ids, maximum = args
    with pytest.raises(ValueError, match="distinct real failures"):
        replay.historical_recovery_report(tmp_path / "missing.db", ids, maximum_additional_calls=maximum)
    assert not (tmp_path / "missing.db").exists()


def add_followup(database, sample, name, *, stored=None, response=None, unknown=False):
    source = database.execute("SELECT * FROM editorial_model_calls WHERE call_id=?", (sample["call_id"],)).fetchone()
    ordinal = database.execute("SELECT COUNT(*) FROM editorial_model_calls").fetchone()[0]
    with database:
        database.execute("INSERT INTO editorial_model_calls(call_id,attempt_id,input_id,chunk_id,request_json,response_json,started_at,finished_at) VALUES (?,?,?,?,?,?,?,?)",
            (name, source["attempt_id"], source["input_id"], source["chunk_id"],
             json.dumps(stored) if stored is not None else source["request_json"],
             None if unknown else json.dumps(response or sample["response"]),
             source["started_at"] + ordinal, None if unknown else source["finished_at"] + ordinal))


def test_natural_retry_excludes_replays_and_changed_controls_and_stops_at_two(database, sample, tmp_path):
    cached = {"request": sample["request"], "invocation_kind": "response_replay"}
    add_followup(database, sample, "cached", stored=cached)
    changed = deepcopy(sample["request"])
    changed["max_tokens"] += 1
    add_followup(database, sample, "changed", stored=changed)
    add_followup(database, sample, "unknown", unknown=True)
    add_followup(database, sample, "failed")
    add_followup(database, sample, "beyond-window")
    result = replay.historical_recovery_report(tmp_path / "archive.db", [sample["call_id"]])
    row = result["samples"][0]
    assert row["excluded_nonphysical_or_changed_controls"] == 2
    assert row["additional_physical_calls"] == 2 and row["observation"] == "budget_exhausted"
    assert [c["call_id"] for c in row["calls"]] == ["unknown", "failed"]
    assert result["additional_usage"]["prompt_tokens"]["missing_call_counters"] >= 1
    assert result["recoveries"] == 0


def test_historical_followup_corrupt_fingerprint_is_rejected(database, sample, tmp_path):
    add_followup(database, sample, "corrupt", stored={"request": sample["request"], "request_fingerprint": "changed"}, unknown=True)
    with pytest.raises(ValueError, match="follow-up request fingerprint"):
        replay.historical_recovery_report(tmp_path / "archive.db", [sample["call_id"]])


def test_historical_accepted_source_is_not_a_recovery_cohort(database, sample, tmp_path):
    response = ReferenceClient(failures=0).complete(sample["request"], provider.variants(sample, "https://api.deepseek.com", "deepseek-flash")[0][1])
    with database:
        database.execute("UPDATE editorial_model_calls SET response_json=?", (json.dumps(response),))
    with pytest.raises(ValueError, match="recoverable original failures"):
        replay.historical_recovery_report(tmp_path / "archive.db", [sample["call_id"]])


@pytest.mark.parametrize("selection", [[], "six", "duplicate"])
def test_campaign_rejects_bad_selection_without_creating_ledger(sample, tmp_path, selection):
    samples = [] if selection == [] else ([dict(sample, call_id=str(i)) for i in range(6)] if selection == "six" else [sample, sample])
    with pytest.raises(ValueError, match="distinct historical samples"):
        provider.evaluate_campaign(samples, tmp_path / "absent.db", endpoint="https://api.deepseek.com",
            model="deepseek-flash", allow_paid_calls=True)
    assert not (tmp_path / "absent.db").exists()


def test_campaign_requires_paid_authorization_before_any_side_effect(sample, tmp_path):
    with pytest.raises(ValueError, match="allow-paid-calls"):
        provider.evaluate_campaign([sample], tmp_path / "absent.db", endpoint="https://api.deepseek.com",
            model="deepseek-flash", allow_paid_calls=False)
    assert not (tmp_path / "absent.db").exists()


def test_owned_clients_close_and_finished_review_packet_is_read_only(sample, tmp_path, monkeypatch):
    clients = []
    class OwnedClient(ReferenceClient):
        def __init__(self):
            super().__init__(failures=0)
            self.closed = False
            clients.append(self)
        def close(self):
            self.closed = True
    monkeypatch.setattr(provider, "DeepSeekClient", OwnedClient)
    ledger = tmp_path / "campaign.db"
    provider.evaluate_campaign([sample], ledger, endpoint="https://api.deepseek.com", model="deepseek-flash", allow_paid_calls=True)
    provider.evaluate_provider(sample, tmp_path / "single.db", endpoint="https://api.deepseek.com", model="deepseek-flash", allow_paid_calls=True)
    assert len(clients) == 2 and all(c.closed for c in clients)
    before = ledger.read_bytes()
    output = tmp_path / "private" / "review.json"
    provider.write_review_packet([sample], ledger, output)
    assert ledger.read_bytes() == before
    report = json.loads(output.read_text())
    assert report["semantic_quality"] == "not_reviewed" and report["reviewer_kind"] is None
    assert len(report["samples"][0]["outputs"]) == 2
    assert report["samples"][0]["source_chunk"] == sample["chunk"]


def test_private_review_excludes_unknown_and_invalid_response_and_refuses_tamper(sample, tmp_path):
    class Mixed:
        def complete(self, request, config):
            return {"choices": [{"finish_reason": "length", "message": {"content": ""}}], "usage": {"completion_tokens": 8192}}
    ledger = tmp_path / "campaign.db"
    campaign(sample, ledger, Mixed())
    with sqlite3.connect(ledger) as connection:
        connection.execute("UPDATE calls SET response=NULL,outcome=NULL WHERE ordinal=2")
    output = tmp_path / "review.json"
    provider.write_review_packet([sample], ledger, output)
    assert json.loads(output.read_text())["samples"][0]["outputs"] == []
    with sqlite3.connect(ledger) as connection:
        connection.execute("UPDATE calls SET response='{}' WHERE ordinal=1")
    with pytest.raises(ValueError, match="response changed"):
        provider.write_review_packet([sample], ledger, output)


@pytest.mark.parametrize("mutation", ["no_manifest", "unknown_outcome", "after_unknown"])
def test_campaign_refuses_incomplete_or_forged_history_before_network(sample, tmp_path, mutation):
    from bili_asr.deepseek import DeepSeekError
    class Failed:
        def complete(self, request, config):
            raise DeepSeekError("private error")
    ledger = tmp_path / "campaign.db"
    campaign(sample, ledger, Failed())
    with sqlite3.connect(ledger) as connection:
        if mutation == "no_manifest":
            connection.execute("DELETE FROM manifest")
        elif mutation == "unknown_outcome":
            connection.execute("UPDATE calls SET outcome='invented' WHERE ordinal=1")
        else:
            connection.execute("INSERT INTO calls SELECT 3,variant,request,response,outcome,latency_ms FROM calls WHERE ordinal=1")
    client = ReferenceClient(failures=0)
    with pytest.raises(ValueError, match="manifest|outcome|unknown"):
        campaign(sample, ledger, client)
    assert client.requests == []


def test_campaign_valid_historical_sample_requires_no_feedback_and_reports_parse_failure(sample, tmp_path):
    sample = deepcopy(sample)
    sample["response"] = ReferenceClient(failures=0).complete(sample["request"],
        provider.variants(sample, "https://api.deepseek.com", "deepseek-flash")[0][1])
    class MissingFinalJSON:
        requests = []
        def complete(self, request, config):
            self.requests.append(request)
            return {"choices": [], "usage": {"completion_tokens": 0}}
    client = MissingFinalJSON()
    report = campaign(sample, tmp_path / "campaign.db", client)
    assert not report["samples"][0]["historical_feedback_seeded"]
    assert len(client.requests) == 2 and all(len(r["messages"]) == 2 for r in client.requests)
    assert all(not c["validation"]["accepted"] for c in report["samples"][0]["calls"])
    assert report["variant_summaries"]["enabled-low"]["historical_feedback_recovery_rate"] is None


def test_load_sample_missing_and_mismatched_source_evidence_is_not_synthesized(database, sample, tmp_path):
    source = tmp_path / "archive.db"
    with pytest.raises(ValueError, match="saved call with a response"):
        replay.load_sample(source, "nonexistent")
    prepared = deepcopy(sample["prepared"])
    prepared["chunks"] = []
    with database:
        database.execute("UPDATE editorial_inputs SET prepared_json=?", (json.dumps(prepared),))
    with pytest.raises(ValueError, match="absent from frozen input"):
        replay.load_sample(source, sample["call_id"])


def test_provider_refuses_ledger_without_manifest_and_changed_saved_request(sample, tmp_path):
    ledger = tmp_path / "single.db"
    args = dict(endpoint="https://api.deepseek.com", model="deepseek-flash", allow_paid_calls=True)
    client = ReferenceClient(failures=0)
    provider.evaluate_provider(sample, ledger, client=client, **args)
    with sqlite3.connect(ledger) as connection:
        connection.execute("DELETE FROM manifest")
    with pytest.raises(ValueError, match="no manifest"):
        provider.evaluate_provider(sample, ledger, client=client, **args)
    assert len(client.requests) == 2
    second = tmp_path / "single2.db"
    provider.evaluate_provider(sample, second, client=client, **args)
    with sqlite3.connect(second) as connection:
        connection.execute("UPDATE calls SET request='{}' WHERE ordinal=1")
    with pytest.raises(ValueError, match="request changed"):
        provider.evaluate_provider(sample, second, client=client, **args)
    assert len(client.requests) == 4


def test_successive_simulated_unknown_sends_exhaust_observation_not_generate_free_retries(database, sample, tmp_path):
    for name in ("unknown-a", "unknown-b", "outside-budget"):
        add_followup(database, sample, name, unknown=True)
    report = replay.historical_recovery_report(tmp_path / "archive.db", [sample["call_id"]])
    assert report["samples"][0]["additional_physical_calls"] == 2
    assert report["samples"][0]["observation"] == "budget_exhausted"
    assert report["additional_usage"]["completion_tokens"]["known_total"] == 0
    assert report["additional_usage"]["completion_tokens"]["missing_call_counters"] == 2
