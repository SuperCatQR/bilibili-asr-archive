"""Evaluation replays actual stored bytes and never relaxes the validator."""
import json
from copy import deepcopy

import pytest

from bili_asr.editorial import EditorialConfig
from bili_asr.services.editorial_evaluation import load_sample, replay_sample
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
