"""Deterministic local lifecycle oracles for the optional ASR boundary."""

from __future__ import annotations

import builtins
import dataclasses
import json
import os
import pathlib
import sys
import types
from typing import Any

import pytest

from bili_asr import asr
from bili_asr import coordinator
from bili_asr.coordinator import RunCoordinator
from bili_asr.manifest import ManifestStore
from bili_asr.page_identity import artifact_stem, page_identity


def _audio_row(identity, *, status="audio_ok"):
    """One manifest row the offline coordinator routes straight to ASR."""
    return {
        "bvid": identity.bvid,
        "work_id": identity.work_id,
        "page_index": identity.page_index,
        "cid": identity.cid,
        "page_label": identity.page_label,
        "status": status,
        "title": "batch-clip",
        "duration_s": 5,
        "pubdate": 1,
        "pubdate_str": "2026-01-02",
    }


def _seed_audio_batch(root, count, *, prefix="BVbatch"):
    """`count` audio_ok rows with their audio on disk; returns (store, rows)."""
    store = ManifestStore(root=root)
    identities = [
        page_identity(f"{prefix}{index}", 0, 100 + index, "p0")
        for index in range(count)
    ]
    audio_dir = pathlib.Path(root) / "audio"
    audio_dir.mkdir(exist_ok=True)
    for identity in identities:
        store.upsert(_audio_row(identity))
        (audio_dir / f"{artifact_stem(identity)}.m4a").write_bytes(b"fixture")
    return store, [(i.work_id, store.get(i.work_id)) for i in identities]


@pytest.fixture
def counted_batch_seam(monkeypatch, fake_funasr):
    """The D2.5 seam: the counted factory sits on `_load_default_model`.

    Patching the module-level factory (not `ASRRunner`) keeps the real
    `_get_model` path under test, so the counter a batch reports is the
    counter the production construction site would have produced.
    """

    monkeypatch.setenv("BILI_ASR_DEVICE", "cpu")
    monkeypatch.setattr(asr, "_load_default_model", fake_funasr)
    return fake_funasr


class FakeAutoModel:
    construction_count = 0
    construction_records: list[dict[str, object]] = []
    generation_records: list[dict[str, object]] = []

    def __init__(self, **kwargs):
        type(self).construction_count += 1
        type(self).construction_records.append(dict(kwargs))

    def generate(self, **kwargs):
        type(self).generation_records.append(dict(kwargs))
        return [{"text": "deterministic output", "timestamps": [
            {"token": "deterministic", "start_time": 0.125, "end_time": 1.5, "score": 0.9},
            {"token": " output", "start_time": 3.0, "end_time": 4.25, "score": 0.8},
        ]}]


@pytest.fixture
def fake_funasr(monkeypatch):
    FakeAutoModel.construction_count = 0
    FakeAutoModel.construction_records = []
    FakeAutoModel.generation_records = []
    
    # Mock torch to report CUDA is available
    fake_torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(is_available=lambda: True)
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "funasr", types.SimpleNamespace(AutoModel=FakeAutoModel))
    return FakeAutoModel


def test_fake_model_result_normalization_timestamps_and_rich_tag_cleanup(fake_funasr):
    assert asr.transcribe("fixture-audio.wav", model_name="local-test-model") == [
        {"start": 0.125, "end": 1.5, "text": "deterministic", "confidence": 0.9},
        {"start": 3.0, "end": 4.25, "text": "output", "confidence": 0.8},
    ]
    assert fake_funasr.construction_records == [{
        "model": "local-test-model", "device": "cuda", "trust_remote_code": False,
        "vad_model": "fsmn-vad", "vad_kwargs": {"max_single_segment_time": 30_000},
    }]
    assert fake_funasr.generation_records == [{
        "input": "fixture-audio.wav", "cache": {}, "itn": True,
        "hotwords": list(asr.DEFAULT_HOTWORDS),
    }]


def test_empty_and_malformed_results_are_ignored():
    assert asr.normalize_result([]) == []
    assert asr.normalize_result([None, "bad", {}, {"text": ""}]) == []
    assert asr.normalize_result({"text": "plain", "timestamp": []}) == [
        {"start": 0.0, "end": 0.0, "text": "plain"}
    ]
    # only the pinned shape is read; a foreign one is ignored rather than guessed
    assert asr.normalize_result({"sentences": [{"start": 10, "end": 20, "text": "<|en|>ok"}]}) == []
    assert asr.normalize_result({"text": "<|en|>ok"}) == [{"start": 0.0, "end": 0.0, "text": "ok"}]


def test_fake_generation_snapshots_include_both_input_paths(fake_funasr, monkeypatch):
    monkeypatch.setenv("BILI_ASR_MODEL", "/fixture/local-model")
    first = asr.transcribe("one.wav")
    second = asr.transcribe("two.wav")
    assert first == second
    assert fake_funasr.construction_count == 2
    assert [record["input"] for record in fake_funasr.generation_records] == ["one.wav", "two.wav"]
    assert fake_funasr.construction_records == [{
        "model": "/fixture/local-model", "device": "cuda", "trust_remote_code": False,
        "vad_model": "fsmn-vad", "vad_kwargs": {"max_single_segment_time": 30_000},
    }] * 2


def test_error_serialization_redacts_forbidden_markers_and_preserves_class(monkeypatch):
    hostile_message = (
        "SESSDATA cookie token signed-url raw exception /tmp/private.wav "
        "model-bytes media-bytes"
    )

    class ExplodingModel:
        def __init__(self, **_kwargs):
            raise RuntimeError(hostile_message)

    fake_torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(is_available=lambda: True)
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(
        sys.modules, "funasr", types.SimpleNamespace(AutoModel=ExplodingModel)
    )
    with pytest.raises(asr.ASRModelError) as caught:
        asr.transcribe("/tmp/private.wav")
    assert isinstance(caught.value, asr.ASRModelError)
    assert isinstance(asr.ASRDependencyError("missing"), asr.ASRDependencyError)

    record = coordinator._validate_attempt(
        {
            "stage": "asr",
            "work_id": "BVfixture.p0",
            "attempt": 1,
            "outcome": "failed",
            "error_code": caught.value.__class__.__name__,
            "artifact_paths": [],
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T00:00:01Z",
        }
    )
    serialized = json.dumps(record)
    forbidden_markers = (
        "SESSDATA", "cookie", "token", "signed-url", "raw exception",
        "/tmp/private.wav", "model-bytes", "media-bytes",
    )
    assert all(marker.lower() not in serialized.lower() for marker in forbidden_markers)
    assert "ASRModelError" in serialized


def test_download_helpers_are_not_called_and_submodule_imports_are_blocked(monkeypatch, fake_funasr):
    calls: list[str] = []
    for helper_name in ("download_model", "download_audio"):
        monkeypatch.setattr(
            asr, helper_name, lambda name=helper_name: calls.append(name), raising=False
        )
    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "socket" or name.startswith(("socket.", "modelscope.", "requests.")):
            raise AssertionError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    assert asr.transcribe("fixture.wav")
    assert calls == []


def test_config_rejects_hostile_values_and_provenance_is_redacted():
    for field, value in (("model_name", ""), ("model_revision", ""), ("device", ""), ("local_source", "prefix token=secret"), ("local_source", "C:\\\\private")):
        values = {"model_name": "safe", "model_revision": None, "device": "cpu", "offline": True, "local_source": "configured-local"}
        values[field] = value
        with pytest.raises((ValueError, TypeError)):
            asr.ASRConfig(**values)


def test_factory_gets_exact_kwargs_and_typeerror_is_not_retried(monkeypatch):
    calls = []
    def factory(**kwargs):
        calls.append(kwargs)
        raise TypeError("hostile secret")
    
    fake_torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(is_available=lambda: True)
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    
    runner = asr.ASRRunner(asr.ASRConfig("model", model_revision="rev"), model_factory=factory)
    with pytest.raises(asr.ASRModelError) as caught:
        runner.transcribe("fixture.wav")
    assert len(calls) == 1
    assert set(calls[0]) == {
        "model", "device", "trust_remote_code", "model_revision",
        "vad_model", "vad_kwargs",
    }
    assert "hostile" not in str(caught.value)


def test_current_transcribe_constructs_once_per_call_characterization(fake_funasr):
    asr.transcribe("first.wav")
    asr.transcribe("second.wav")
    assert fake_funasr.construction_count == 2


def test_target_runner_reuse_oracle_is_target_facing(fake_funasr):
    """Target contract: one runner owns one model across all input paths."""
    runner = asr.ASRRunner(
        asr.ASRConfig(model_name="local-test-model"), model_factory=fake_funasr
    )
    outputs = [runner.transcribe(path) for path in ("first.wav", "second.wav")]
    assert outputs
    assert fake_funasr.construction_count == 1
    assert [record["input"] for record in fake_funasr.generation_records] == [
        "first.wav", "second.wav"
    ]


def test_runner_release_dereferences_owned_model(fake_funasr):
    runner = asr.ASRRunner(
        asr.ASRConfig(model_name="local-test-model"), model_factory=fake_funasr
    )
    runner.transcribe("fixture.wav")

    runner.release()

    assert runner._model is None


def test_provenance_has_stable_redacted_configuration_keys():
    config = asr.ASRConfig(
        model_name="local-model",
        model_revision="revision-1",
        device="cpu",
        language="中文",
        hotwords=("a", "b"),
        offline=True,
        local_source="configured-local",
    )
    provenance = asr.ASRRunner(config).provenance()
    assert list(provenance) == [
        "model_name", "model_revision", "device", "language", "vad_model",
        "vad_max_segment_s", "hotwords", "offline", "local_source",
    ]
    assert provenance == {
        "model_name": "local-model",
        "model_revision": "revision-1",
        "device": "cpu",
        "language": "中文",
        "vad_model": "fsmn-vad",
        "vad_max_segment_s": "30.0",
        "hotwords": "a,b",
        "offline": "True",
        "local_source": "configured-local",
    }
    assert all(isinstance(value, str) for value in provenance.values())


def test_provenance_is_deterministic_and_revision_sensitive():
    def make_provenance(revision: str | None) -> dict[str, str]:
        return asr.ASRRunner(
            asr.ASRConfig("fixture-model", model_revision=revision)
        ).provenance()

    assert make_provenance("rev-a") == make_provenance("rev-a")
    assert make_provenance("rev-a") != make_provenance("rev-b")
    assert make_provenance(None) != make_provenance("rev-a")


def test_provenance_preserves_safe_slash_qualified_model_identifier():
    provenance = asr.ASRRunner(asr.ASRConfig("FunAudioLLM/Fun-ASR-Nano-2512")).provenance()

    assert provenance["model_name"] == "FunAudioLLM/Fun-ASR-Nano-2512"


@pytest.mark.parametrize(
    "model_name",
    (
        "/opt/models/Fun-ASR-Nano-2512",
        "C:\\models\\Fun-ASR-Nano-2512",
        "https://models.example/Fun-ASR-Nano-2512",
        "token=private-model",
        # F-001: an underscore is a word character, so the old trailing ``\b``
        # marker let the credential word run into the next word and the value
        # was published verbatim.  Both separators now redact.
        "myorg/token_abc",
        "myorg/sessdata123",
        "myorg/secret_1",
        "token_abc",
    ),
)
def test_provenance_redacts_path_url_and_credential_like_model_values(model_name):
    provenance = asr.ASRRunner(asr.ASRConfig(model_name)).provenance()

    assert provenance["model_name"] == "[redacted]"
    assert model_name not in json.dumps(provenance)


def test_the_credential_scan_redacts_across_both_separators_without_over_redacting():
    """F-001: the separator-aware boundary, pinned on both sides.

    ``_`` is a word character, so the credential marker's trailing ``\\b``
    could not end the match after it: ``myorg/token_abc`` passed the scan and
    was published verbatim while ``myorg/token-abc`` was caught.  The scan now
    uses the separator-aware lookaround already applied to file names, so the
    two separators agree.  The negative half matters just as much: the fix must
    not start redacting ordinary identifiers that merely contain a marker.
    """

    from bili_asr import quality

    for marker in ("token", "sessdata", "cookie", "password", "secret", "credential"):
        for value in (f"myorg/{marker}_abc", f"myorg/{marker}-abc", f"myorg/{marker}"):
            assert asr._FORBIDDEN_PROVENANCE.search(value), value
            assert quality._NAME_CREDENTIAL.search(value), value

    # Not a credential: the marker runs into a following letter.
    for value in ("myorg/tokenizer", "myorg/SecretSanta", "myorg/cookies"):
        assert not asr._FORBIDDEN_PROVENANCE.search(value), value
        assert not quality._NAME_CREDENTIAL.search(value), value
        assert (
            asr.ASRRunner(asr.ASRConfig(value)).provenance()["model_name"] == value
        ), value


def test_the_local_source_twin_shares_the_hardened_credential_rule():
    """S-2: the two byte-identical literals are now one definition.

    ``_FORBIDDEN_LOCAL_SOURCE`` and ``_FORBIDDEN_PROVENANCE`` were separate but
    identical regexes, so the weak credential boundary had to be fixed twice and
    was in fact fixed nowhere.  They are one compiled pattern now, which is what
    makes the ``local_source`` guard (the field ``__post_init__`` validates with
    the *other* name) reject the underscore form too.
    """

    assert asr._FORBIDDEN_LOCAL_SOURCE is asr._FORBIDDEN_PROVENANCE
    # The production default still passes, and the shapes that always failed
    # still fail.
    asr.ASRConfig("local-test-model")  # local_source defaults to configured-local
    for hostile in ("prefix token=secret", "C:\\private", "prefix token_abc"):
        with pytest.raises(ValueError):
            asr.ASRConfig("local-test-model", local_source=hostile)


def test_environment_model_path_is_runtime_only_and_not_exposed_in_provenance(
    fake_funasr, monkeypatch
):
    local_model_path = "/fixture/private-model"
    observed_provenance = []
    original_provenance = asr.ASRRunner.provenance

    def capture_provenance(runner):
        provenance = original_provenance(runner)
        observed_provenance.append(provenance)
        return provenance

    original_transcribe = asr.ASRRunner.transcribe

    def inspect_then_transcribe(runner, audio_path):
        capture_provenance(runner)
        return original_transcribe(runner, audio_path)

    monkeypatch.setattr(asr.ASRRunner, "transcribe", inspect_then_transcribe)
    monkeypatch.setenv("BILI_ASR_MODEL", local_model_path)

    asr.transcribe("fixture.wav")

    assert fake_funasr.construction_records[0]["model"] == local_model_path
    assert observed_provenance[0]["model_name"] == "[redacted]"
    assert local_model_path not in json.dumps(observed_provenance)


def test_provenance_redacts_forbidden_values_without_serializing_payloads():
    config = asr.ASRConfig("fixture-model", model_revision="rev-a")
    runner = asr.ASRRunner(config)
    safe = runner.provenance()
    forbidden_markers = (
        "SESSDATA", "cookie", "token", "http://", "https://", "Traceback",
        "/tmp/", "model-bytes", "media-bytes", "transcript-payload",
    )
    serialized = json.dumps(safe)
    assert all(marker.lower() not in serialized.lower() for marker in forbidden_markers)


# ------------------------------------ Task 1: declared producer identity (D4.1-D4.5)


DECLARED_MODEL_ID = "FunAudioLLM/Fun-ASR-Nano-2512"


def test_the_declared_identity_is_the_last_config_field_and_reads_its_env_knob(
    monkeypatch,
):
    """D4.1: appended last, so existing positional construction does not shift."""

    assert asr.ASR_MODEL_ID_ENV_VAR == "BILI_ASR_MODEL_ID"
    assert [field.name for field in dataclasses.fields(asr.ASRConfig)][-1] == "model_id"
    assert asr.ASRConfig("model", model_revision="rev").model_id is None

    monkeypatch.delenv("BILI_ASR_MODEL_ID", raising=False)
    assert asr.default_config().model_id is None

    monkeypatch.setenv("BILI_ASR_MODEL_ID", DECLARED_MODEL_ID)
    assert asr.default_config().model_id == DECLARED_MODEL_ID

    # A blank declaration is "not declared", like every other blank knob: a
    # shell `BILI_ASR_MODEL_ID=` must not fail every run.
    monkeypatch.setenv("BILI_ASR_MODEL_ID", "   ")
    assert asr.default_config().model_id is None


def test_the_declared_identity_fills_the_model_name_slot_and_adds_no_key(
    monkeypatch,
):
    """D4.3/D4.4: declared id -> the existing slot; never a tenth key."""

    local_checkpoint = "/opt/models/Fun-ASR-Nano-2512"
    monkeypatch.setenv("BILI_ASR_MODEL_ID", DECLARED_MODEL_ID)
    monkeypatch.setenv("BILI_ASR_MODEL", local_checkpoint)
    monkeypatch.setenv("BILI_ASR_MODEL_REVISION", "rev-9")

    provenance = asr.ASRRunner(asr.default_config()).provenance()

    # The nine keys, in the order the contract pins (A4 carrier = model_name).
    assert list(provenance) == [
        "model_name", "model_revision", "device", "language", "vad_model",
        "vad_max_segment_s", "hotwords", "offline", "local_source",
    ]
    assert provenance["model_name"] == DECLARED_MODEL_ID
    assert provenance["model_revision"] == "rev-9"
    # The local path is still never serialized.
    assert local_checkpoint not in json.dumps(provenance)


def test_the_declared_identity_never_reaches_the_loader(monkeypatch):
    """D4.1: the declaration is provenance, not a load argument."""

    seen: list[dict[str, Any]] = []

    class RecordingModel:
        def __init__(self, **kwargs):
            seen.append(dict(kwargs))

        def generate(self, **_kwargs):
            return [{"text": "ok", "timestamp": []}]

    local_checkpoint = "/opt/models/Fun-ASR-Nano-2512"
    monkeypatch.setenv("BILI_ASR_MODEL", local_checkpoint)
    monkeypatch.setenv("BILI_ASR_MODEL_ID", DECLARED_MODEL_ID)
    monkeypatch.setenv("BILI_ASR_DEVICE", "cpu")

    runner = asr.ASRRunner(asr.default_config(), model_factory=RecordingModel)
    runner.transcribe("fixture.wav")

    # The loader still receives the local directory the operator configured...
    assert seen[0]["model"] == local_checkpoint
    # ...and the declaration is nowhere in its arguments.
    assert "model_id" not in seen[0]
    assert local_checkpoint not in json.dumps(runner.provenance())


def test_a_safe_configured_model_name_is_kept_without_a_declaration():
    """D4.3 step 2: no declaration, but the configured id is itself safe."""

    provenance = asr.ASRRunner(asr.ASRConfig(DECLARED_MODEL_ID)).provenance()

    assert provenance["model_name"] == DECLARED_MODEL_ID


def test_without_a_declaration_an_unsafe_configured_name_stays_redacted():
    """D4.3 step 3 / A4: no declaration and no safe id -> ``[redacted]``."""

    provenance = asr.ASRRunner(
        asr.ASRConfig("/opt/models/Fun-ASR-Nano-2512")
    ).provenance()

    assert provenance["model_name"] == "[redacted]"


def test_the_declared_identity_is_equal_to_a_matching_safe_model_name():
    """A declaration that agrees with the load value is not a contradiction."""

    config = asr.ASRConfig(DECLARED_MODEL_ID, model_id=DECLARED_MODEL_ID)

    assert asr.ASRRunner(config).provenance()["model_name"] == DECLARED_MODEL_ID


@pytest.mark.parametrize(
    "model_id",
    (
        "/opt/models/Fun-ASR-Nano-2512",
        "C:\\models\\Fun-ASR-Nano-2512",
        "https://models.example/Fun-ASR-Nano-2512",
        "token=private-model",
        "Fun-ASR-Nano-2512",  # a bare name is not a hub-level identifier
        # F-001: the underscore-adjacent shape is a credential too.
        "myorg/token_abc",
        "myorg/sessdata123",
        "myorg/secret_1",
        "",
        "   ",
    ),
)
def test_an_unsafe_declaration_is_a_loud_value_error(model_id):
    """D4.2: never a silent fall back to ``[redacted]``."""

    with pytest.raises(ValueError) as caught:
        asr.ASRConfig("model", model_id=model_id)

    assert asr.ASR_MODEL_ID_ENV_VAR in str(caught.value)
    assert "hub-level model identifier" in str(caught.value)


def test_a_declaration_contradicting_a_safe_model_name_is_a_value_error():
    """D4.3: two different safe identities would make the archive lie."""

    with pytest.raises(ValueError) as caught:
        asr.ASRConfig("OtherOrg/OtherModel", model_id=DECLARED_MODEL_ID)

    assert asr.ASR_MODEL_ID_ENV_VAR in str(caught.value)
    assert "contradicts" in str(caught.value)


def test_a_declaration_beside_a_relative_local_checkpoint_constructs(
    tmp_path, monkeypatch
):
    """F-002: the route is hub-level only, so the documented form is not refused.

    ``models/Fun-ASR-Nano-2512`` satisfies ``_MODEL_IDENTIFIER`` and contains a
    ``/``, so the shape-only predicate of D4.3's first draft fired on it and the
    *truthful* declaration ``FunAudioLLM/Fun-ASR-Nano-2512`` aborted the row —
    the loud failure landed on the truth-telling side.  The predicate is now
    hub-level: a value that resolves to a directory on this machine is a local
    checkpoint, whatever its spelling, and the declared identity is recorded.
    """

    monkeypatch.chdir(tmp_path)
    (tmp_path / "models" / "Fun-ASR-Nano-2512").mkdir(parents=True)
    monkeypatch.setenv("BILI_ASR_MODEL", "models/Fun-ASR-Nano-2512")
    monkeypatch.setenv("BILI_ASR_MODEL_ID", DECLARED_MODEL_ID)

    config = asr.default_config()
    provenance = asr.ASRRunner(config).provenance()

    assert config.model_name == "models/Fun-ASR-Nano-2512"  # the loader is unchanged
    assert config.model_id == DECLARED_MODEL_ID
    assert provenance["model_name"] == DECLARED_MODEL_ID
    assert "models/Fun-ASR-Nano-2512" not in json.dumps(provenance)


def test_two_different_hub_ids_still_contradict(tmp_path, monkeypatch):
    """F-002's other direction: the case D4.3 exists for still raises.

    Neither value resolves to a directory, so both really are hub ids and one
    of them would be a lie.  The refusal survives the amendment.
    """

    monkeypatch.chdir(tmp_path)
    for model in ("OtherOrg/OtherModel", "models/NotDownloaded"):
        monkeypatch.setenv("BILI_ASR_MODEL", model)
        monkeypatch.setenv("BILI_ASR_MODEL_ID", DECLARED_MODEL_ID)

        with pytest.raises(ValueError) as caught:
            asr.default_config()

        assert "contradicts" in str(caught.value)
        assert model in str(caught.value)


def test_the_declared_identity_is_redaction_scanned_like_any_other_value():
    """A declared id that is itself identifier-shaped but forbidden is refused."""

    with pytest.raises(ValueError):
        asr.ASRConfig("model", model_id="org/token")


def test_transcribe_refuses_a_model_name_override_under_a_declaration(
    fake_funasr, monkeypatch
):
    """F-003: the wrapper's override is composed with the declaration, loudly.

    ``transcribe(path, model_name=…)`` reaches the config through
    ``dataclasses.replace``, which re-runs ``__post_init__``.  Under a declared
    identity it therefore raises where the base returned segments — deliberately
    (the override would contradict the recorded producer), but previously
    undocumented and unpinned.  Both directions are pinned here, so the
    behaviour cannot drift silently either way.
    """

    monkeypatch.setenv("BILI_ASR_MODEL_ID", DECLARED_MODEL_ID)

    # A different hub id contradicts the declaration: refused, nothing loaded.
    with pytest.raises(ValueError) as caught:
        asr.transcribe("fixture-audio.wav", model_name="OtherOrg/OtherModel")

    assert "contradicts" in str(caught.value)
    assert fake_funasr.construction_records == []

    # An override that *agrees* with the declaration is not a contradiction.
    assert asr.transcribe("fixture-audio.wav", model_name=DECLARED_MODEL_ID)
    assert fake_funasr.construction_records[0]["model"] == DECLARED_MODEL_ID


def test_the_module_provenance_helper_records_the_declaration(monkeypatch):
    """The CLI's no-model provenance path sees the declaration too."""

    def explode(**_kwargs):
        raise AssertionError("provenance must not build a model")

    monkeypatch.setattr(asr, "_load_default_model", explode)
    monkeypatch.setenv("BILI_ASR_MODEL", "/opt/models/Fun-ASR-Nano-2512")
    monkeypatch.setenv("BILI_ASR_MODEL_ID", DECLARED_MODEL_ID)

    recorded = asr.provenance()

    assert recorded["model_name"] == DECLARED_MODEL_ID
    assert "/opt/models/Fun-ASR-Nano-2512" not in json.dumps(recorded)


def test_the_documented_target_scenario_is_a_local_dir_plus_a_declaration(monkeypatch):
    """A4's exact case: local checkpoint dir in, hub id recorded, path absent.

    This is the 2026-09-12 ten-video run's configuration, which recorded
    ``[redacted]`` because nothing declared the identity behind the path.
    """

    local_checkpoint = "/opt/models/Fun-ASR-Nano-2512"
    monkeypatch.setenv("BILI_ASR_MODEL", local_checkpoint)
    monkeypatch.setenv("BILI_ASR_MODEL_ID", DECLARED_MODEL_ID)
    monkeypatch.delenv("BILI_ASR_MODEL_REVISION", raising=False)

    config = asr.default_config()

    assert config.model_name == local_checkpoint  # the loader still gets the path
    assert config.model_id == DECLARED_MODEL_ID
    assert asr.ASRRunner(config).provenance()["model_name"] == DECLARED_MODEL_ID


def test_the_default_model_name_needs_a_matching_declaration(monkeypatch):
    """The unset-knob path is a safe id, so a different declaration contradicts it."""

    monkeypatch.delenv("BILI_ASR_MODEL", raising=False)
    monkeypatch.setenv("BILI_ASR_MODEL_ID", "OtherOrg/OtherModel")

    with pytest.raises(ValueError) as caught:
        asr.default_config()

    assert "contradicts" in str(caught.value)

    # Declaring the value the default already names is not a contradiction.
    monkeypatch.setenv("BILI_ASR_MODEL_ID", asr.DEFAULT_MODEL)
    assert asr.default_config().model_id == asr.DEFAULT_MODEL


def test_an_unsafe_declaration_fails_the_row_through_the_batch_path(
    tmp_root, monkeypatch, counted_batch_seam, capsys
):
    """D4.2: the loud error reaches the existing per-item failure path.

    The declaration is read at the same place the runner is built, inside
    ``process_row``, so a bad value fails that row (redacted code, no
    traceback leak) while the batch keeps going — and nothing is archived
    under a producer identity the operator did not validly declare.
    """

    store, rows = _seed_audio_batch(tmp_root, 2, prefix="BVbadid")
    monkeypatch.setenv("BILI_ASR_MODEL_ID", "/opt/models/Fun-ASR-Nano-2512")

    summary = RunCoordinator(tmp_root, store, offline=True).run_batch(rows)

    assert [result.ok for result in summary.results] == [False, False]
    assert [result.failure_codes for result in summary.results] == [
        ["ValueError"], ["ValueError"],
    ]
    # No model was built, so the run paid no construction for either row.
    assert counted_batch_seam.construction_count == 0
    assert summary.model_constructions == 0
    # The rejected value is not echoed anywhere, and no transcript exists.
    captured = capsys.readouterr()
    assert "/opt/models" not in captured.out + captured.err
    assert not (pathlib.Path(tmp_root) / "transcripts" / "md").exists()


def test_fixture_benchmark_reports_only_construction_and_shape(fake_funasr):
    runner = asr.ASRRunner(asr.ASRConfig("fixture-model"), model_factory=fake_funasr)
    outputs = [runner.transcribe(path) for path in ("first.wav", "second.wav")]
    report: dict[str, Any] = {
        "model_construction_count": fake_funasr.construction_count,
        "normalized_segment_count": sum(len(output) for output in outputs),
        "output_shape": sorted(outputs[0][0]),
    }
    assert report == {
        "model_construction_count": 1,
        "normalized_segment_count": 4,
        "output_shape": ["confidence", "end", "start", "text"],
    }
    assert set(report) == {
        "model_construction_count", "normalized_segment_count", "output_shape"
    }


def test_cuda_unavailable_raises_dependency_error_with_rocm_hint(monkeypatch):
    """The device hint points at the check and the recipe, never at a wheel index."""
    class FakeTorch:
        @staticmethod
        def cuda_is_available():
            return False
        
        class cuda:
            @staticmethod
            def is_available():
                return False
    
    monkeypatch.setitem(sys.modules, "torch", FakeTorch)
    monkeypatch.setitem(sys.modules, "funasr", types.SimpleNamespace(AutoModel=lambda **kw: None))
    
    runner = asr.ASRRunner(asr.ASRConfig("test-model", device="cuda"))
    with pytest.raises(asr.ASRDependencyError) as caught:
        runner.transcribe("fixture.wav")
    
    error_message = str(caught.value)
    assert "CUDA/ROCm is not available" in error_message
    # D1.6: exactly these stable pointer tokens, and no vendor index URL.  The
    # broken PyTorch.org ROCm wheel must not come back through this message; the
    # literal is assembled so this file does not itself carry the dead-end URL.
    assert "ROCm" in error_message
    assert "scripts/check_asr_env.py" in error_message
    assert "docs/wsl-rocm-gpu.md" in error_message
    assert "BILI_ASR_DEVICE=cpu" in error_message
    # N-1: the hint must publish the check the way the check's own fix text and
    # docs/wsl-rocm-gpu.md do — the venv interpreter that holds torch.  A bare
    # `python3.12` invocation probes the *system* interpreter and reports a false
    # `torch-present FAIL` on a host built exactly as the recipe says, so the
    # token is banned from this surface entirely, not merely discouraged.
    # N-2: the hint is a human-readable exception message, not a paste-into-bash
    # block, so it names the venv's interpreter in plain language and keeps only
    # the runnable command.  The `${VENV:?…}` shell-expansion form stays in the
    # code blocks of README.md / docs/wsl-rocm-gpu.md, where a shell expands it.
    assert '"$VENV/bin/python" scripts/check_asr_env.py' in error_message
    assert "${VENV:" not in error_message
    assert "venv's interpreter" in error_message
    assert "python3.12" not in error_message
    assert "python3.12 scripts/check_asr_env.py" not in error_message
    assert ("download.pytorch.org" + "/whl/rocm") not in error_message
    assert "http://" not in error_message and "https://" not in error_message
    # No machine-specific layout either: the hint must not name one host's paths.
    assert "/opt/rocm" not in error_message
    assert "/root/" not in error_message and "/home/" not in error_message


def test_device_hint_doc_path_resolves_in_the_checkout():
    """Drift guard: the doc the hint names must exist in this checkout.

    Only the documented path is asserted. `scripts/` is not part of the installed
    distribution and the verification baseline stages `docs/` without it, so a
    check on the script's own path would be a property of one tree layout.
    """
    package_root = pathlib.Path(__file__).resolve().parents[1]
    assert (package_root / "docs" / "wsl-rocm-gpu.md").is_file()


def test_torch_import_error_raises_dependency_error(monkeypatch):
    """Missing torch should raise ASRDependencyError when device is cuda."""
    def fail_torch_import(name, *args, **kwargs):
        if name == "torch":
            raise ImportError("No module named 'torch'")
        return builtins.__import__(name, *args, **kwargs)
    
    monkeypatch.setattr(builtins, "__import__", fail_torch_import)
    monkeypatch.setitem(sys.modules, "funasr", types.SimpleNamespace(AutoModel=lambda **kw: None))
    
    runner = asr.ASRRunner(asr.ASRConfig("test-model", device="cuda"))
    with pytest.raises(asr.ASRDependencyError) as caught:
        runner.transcribe("fixture.wav")
    
    error_message = str(caught.value)
    assert "PyTorch is required" in error_message or "torch" in error_message.lower()


def test_cpu_override_skips_gpu_check(fake_funasr):
    """CPU device should work without CUDA availability check."""
    runner = asr.ASRRunner(asr.ASRConfig("test-model", device="cpu"), model_factory=fake_funasr)
    result = runner.transcribe("fixture.wav")
    
    assert result == [
        {"start": 0.125, "end": 1.5, "text": "deterministic", "confidence": 0.9},
        {"start": 3.0, "end": 4.25, "text": "output", "confidence": 0.8},
    ]
    assert fake_funasr.construction_records[0]["device"] == "cpu"


def test_default_config_reads_the_documented_environment_knobs(monkeypatch):
    monkeypatch.setenv("BILI_ASR_MODEL", "/opt/checkpoints/nano")
    monkeypatch.setenv("BILI_ASR_MODEL_REVISION", "rev-9")
    monkeypatch.setenv("BILI_ASR_DEVICE", "cpu")
    monkeypatch.setenv("BILI_ASR_LANGUAGE", "中文")
    monkeypatch.setenv("BILI_ASR_VAD_MODEL", "fsmn-vad")

    config = asr.default_config()

    assert config.model_name == "/opt/checkpoints/nano"
    assert config.model_revision == "rev-9"
    assert config.device == "cpu"
    assert config.language == "中文"
    assert config.vad_model == "fsmn-vad"


def test_vad_is_the_default_and_a_blank_knob_disables_it(monkeypatch):
    """Long recordings need the VAD; an explicit blank turns that pipeline off."""

    monkeypatch.delenv("BILI_ASR_VAD_MODEL", raising=False)
    assert asr.default_config().vad_model == "fsmn-vad"

    monkeypatch.setenv("BILI_ASR_VAD_MODEL", "   ")
    assert asr.default_config().vad_model is None


def test_no_vad_configured_omits_the_component_from_the_construction(fake_funasr):
    asr.ASRRunner(
        asr.ASRConfig("test-model", device="cpu", vad_model=None), model_factory=fake_funasr
    ).transcribe("fixture.wav")

    assert fake_funasr.construction_records == [
        {"model": "test-model", "device": "cpu", "trust_remote_code": False}
    ]


@pytest.mark.skipif(not os.path.exists("/proc/self/fd"), reason="descriptor paths are POSIX")
def test_confined_descriptor_input_is_materialized_for_component_subprocesses(tmp_path):
    """The VAD component shells out to ffmpeg, which cannot open a cloexec fd."""

    payload = b"fake audio payload"
    real = tmp_path / "clip.m4a"
    real.write_bytes(payload)
    seen: list[bytes] = []

    class ReadingModel:
        def __init__(self, **_kwargs):
            pass

        def generate(self, **kwargs):
            with open(kwargs["input"], "rb") as handle:
                seen.append(handle.read())
            return [{"text": "ok", "timestamp": []}]

    descriptor = None
    fd = os.open(real, os.O_RDONLY)
    try:
        descriptor = f"/proc/self/fd/{fd}"
        segments = asr.ASRRunner(
            asr.ASRConfig("test-model", device="cpu"), model_factory=ReadingModel
        ).transcribe(descriptor)
    finally:
        os.close(fd)

    assert segments == [{"start": 0.0, "end": 0.0, "text": "ok"}]
    assert seen == [payload]
    assert descriptor is not None


def test_a_plain_path_is_never_copied(fake_funasr):
    asr.ASRRunner(
        asr.ASRConfig("test-model", device="cpu"), model_factory=fake_funasr
    ).transcribe("fixture.wav")

    assert fake_funasr.generation_records[0]["input"] == "fixture.wav"


def test_default_config_defaults_are_unchanged_without_the_knobs(monkeypatch):
    for name in ("BILI_ASR_MODEL", "BILI_ASR_MODEL_REVISION", "BILI_ASR_DEVICE", "BILI_ASR_LANGUAGE"):
        monkeypatch.delenv(name, raising=False)

    config = asr.default_config()

    assert config.model_name == asr.DEFAULT_MODEL
    assert config.model_revision is None
    assert config.device == "cuda"
    assert config.language is None


def test_configured_language_is_passed_and_absent_language_is_not(fake_funasr):
    """`language` is prompt text for Nano, so only a configured value is sent."""

    asr.ASRRunner(
        asr.ASRConfig("test-model", device="cpu", language="中文"), model_factory=fake_funasr
    ).transcribe("one.wav")
    asr.ASRRunner(
        asr.ASRConfig("test-model", device="cpu"), model_factory=fake_funasr
    ).transcribe("two.wav")

    assert fake_funasr.generation_records == [
        {"input": "one.wav", "cache": {}, "itn": True, "language": "中文"},
        {"input": "two.wav", "cache": {}, "itn": True},
    ]


def test_config_rejects_a_blank_language():
    with pytest.raises(ValueError):
        asr.ASRConfig("test-model", language="   ")
    with pytest.raises(ValueError):
        asr.ASRConfig("test-model", language=7)  # type: ignore[arg-type]


def test_hotwords_travel_to_the_model_and_are_recorded(monkeypatch, fake_funasr):
    """Configured terms bias decoding and are visible in provenance."""

    monkeypatch.setenv("BILI_ASR_HOTWORDS", "马恩牌, 未明子,劳动仲裁,劳动仲裁")
    config = asr.default_config()

    assert config.hotwords[: len(asr.DEFAULT_HOTWORDS)] == asr.DEFAULT_HOTWORDS
    assert config.hotwords[len(asr.DEFAULT_HOTWORDS):] == ("劳动仲裁",)

    asr.ASRRunner(config, model_factory=fake_funasr).transcribe("fixture.wav")

    assert fake_funasr.generation_records[0]["hotwords"] == list(config.hotwords)
    assert "马恩牌" in asr.ASRRunner(config).provenance()["hotwords"]


def test_no_hotwords_configured_omits_the_bias(fake_funasr):
    asr.ASRRunner(
        asr.ASRConfig("test-model", device="cpu", hotwords=()), model_factory=fake_funasr
    ).transcribe("fixture.wav")

    assert "hotwords" not in fake_funasr.generation_records[0]


def test_config_rejects_a_malformed_hotword_entry():
    with pytest.raises(ValueError):
        asr.ASRConfig("test-model", hotwords=("ok", "  "))
    with pytest.raises(ValueError):
        asr.ASRConfig("test-model", hotwords=["ok"])  # type: ignore[arg-type]


def test_module_provenance_helper_reads_no_model(monkeypatch):
    """The CLI records provenance without loading a checkpoint."""

    def explode(**_kwargs):
        raise AssertionError("provenance must not build a model")

    monkeypatch.setattr(asr, "_load_default_model", explode)
    monkeypatch.setenv("BILI_ASR_MODEL", "FunAudioLLM/Fun-ASR-Nano-2512")

    recorded = asr.provenance()

    assert recorded["model_name"] == "FunAudioLLM/Fun-ASR-Nano-2512"
    assert recorded["device"] == "cuda"


def test_provenance_renders_absent_values_as_empty_not_none(monkeypatch):
    """A missing revision or language must not read as the string "None"."""

    monkeypatch.delenv("BILI_ASR_LANGUAGE", raising=False)
    monkeypatch.delenv("BILI_ASR_MODEL_REVISION", raising=False)

    recorded = asr.ASRRunner(asr.ASRConfig("local-model", device="cpu")).provenance()

    assert recorded["model_revision"] == ""
    assert recorded["language"] == ""
    assert "None" not in recorded.values()


def test_vad_cap_is_configurable_and_validated(monkeypatch):
    """The measured-optimal cap is a knob, not a constant frozen in the code."""

    monkeypatch.delenv("BILI_ASR_VAD_MAX_SEGMENT_S", raising=False)
    assert asr.default_config().vad_max_segment_s == asr.DEFAULT_VAD_MAX_SEGMENT_S

    monkeypatch.setenv("BILI_ASR_VAD_MAX_SEGMENT_S", "30")
    assert asr.default_config().vad_max_segment_s == 30.0
    monkeypatch.setenv("BILI_ASR_VAD_MAX_SEGMENT_S", " 7.5s ")
    assert asr.default_config().vad_max_segment_s == 7.5
    monkeypatch.setenv("BILI_ASR_VAD_MAX_SEGMENT_S", "   ")
    assert asr.default_config().vad_max_segment_s == asr.DEFAULT_VAD_MAX_SEGMENT_S

    monkeypatch.setenv("BILI_ASR_VAD_MAX_SEGMENT_S", "soon")
    with pytest.raises(ValueError):
        asr.default_config()
    monkeypatch.setenv("BILI_ASR_VAD_MAX_SEGMENT_S", "-1")
    with pytest.raises(ValueError):
        asr.default_config()

    with pytest.raises(ValueError):
        asr.ASRConfig("m", vad_max_segment_s=0)
    with pytest.raises(ValueError):
        asr.ASRConfig("m", vad_max_segment_s=True)  # type: ignore[arg-type]


def test_the_configured_cap_reaches_the_vad_component(fake_funasr):
    asr.ASRRunner(
        asr.ASRConfig("test-model", device="cpu", vad_max_segment_s=10),
        model_factory=fake_funasr,
    ).transcribe("fixture.wav")

    assert fake_funasr.construction_records[0]["vad_kwargs"] == {"max_single_segment_time": 10_000}


# ------------------------------------------- Task 1: the construction counter


def test_runner_counter_is_zero_until_the_model_is_built(fake_funasr):
    """Asking for no transcript costs no construction; release never resets."""

    runner = asr.ASRRunner(
        asr.ASRConfig("local-test-model", device="cpu"), model_factory=fake_funasr
    )
    assert runner.model_constructions == 0

    runner.transcribe("first.wav")
    assert runner.model_constructions == 1
    # Reuse is not a second construction.
    runner.transcribe("second.wav")
    assert runner.model_constructions == 1

    runner.release()
    assert runner.model_constructions == 1
    runner.transcribe("third.wav")
    assert runner.model_constructions == 2


def test_a_failed_load_does_not_inflate_the_counter(monkeypatch):
    """A factory that raised built nothing, so the count stays 0."""

    def exploding_factory(**_kwargs):
        raise RuntimeError("no checkpoint")

    runner = asr.ASRRunner(
        asr.ASRConfig("local-test-model", device="cpu"),
        model_factory=exploding_factory,
    )
    with pytest.raises(asr.ASRModelError):
        runner.transcribe("fixture.wav")

    # Nothing was built, so nothing is claimed: no model, no count.
    assert runner._model is None
    assert runner.model_constructions == 0


def test_a_failed_load_is_retried_per_row_and_counted_as_an_attempt(monkeypatch):
    """R1 (inherited): attempts and constructions are two different numbers.

    A failed load leaves ``_model`` unset, so every later row retries the same
    factory call and pays no construction.  The attempt counter is what makes
    the difference observable *to a caller holding the runner*: without it
    ``model_constructions == 0`` cannot be told apart between a runner that
    never needed a model and one whose N loads were all rejected.  Nothing
    prints this number — ``test_cli_prints_no_reuse_line_when_every_load_fails``
    pins the operator-visible side.
    """

    attempts = []

    def exploding_factory(**kwargs):
        attempts.append(dict(kwargs))
        raise RuntimeError("no checkpoint")

    runner = asr.ASRRunner(
        asr.ASRConfig("local-test-model", device="cpu"),
        model_factory=exploding_factory,
    )
    assert runner.model_load_attempts == 0

    for path in ("first.wav", "second.wav", "third.wav"):
        with pytest.raises(asr.ASRModelError):
            runner.transcribe(path)

    # One retry per row: N attempts, zero constructions (the R1 defect), and
    # the two counters together state exactly that.
    assert len(attempts) == 3
    assert runner.model_load_attempts == 3
    assert runner.model_constructions == 0


def test_a_successful_load_counts_one_attempt_and_one_construction(fake_funasr):
    """The invariant: attempts equal constructions when every load succeeds."""

    runner = asr.ASRRunner(
        asr.ASRConfig("local-test-model", device="cpu"), model_factory=fake_funasr
    )

    runner.transcribe("first.wav")
    runner.transcribe("second.wav")  # reuse is neither a new attempt nor a build

    assert runner.model_load_attempts == 1
    assert runner.model_constructions == 1

    runner.release()
    runner.transcribe("third.wav")  # a released model is rebuilt: both counters move

    assert runner.model_load_attempts == 2
    assert runner.model_constructions == 2


def test_a_mixed_failure_then_success_states_both_counts(fake_funasr, monkeypatch):
    """A load that fails then succeeds: 2 attempts, 1 construction."""

    outcomes = [RuntimeError("first load failed")]

    class Flaky:
        def __init__(self, **_kwargs):
            if outcomes:
                raise outcomes.pop(0)

        def generate(self, **_kwargs):
            return [{"text": "ok", "timestamp": []}]

    runner = asr.ASRRunner(
        asr.ASRConfig("local-test-model", device="cpu"), model_factory=Flaky
    )

    with pytest.raises(asr.ASRModelError):
        runner.transcribe("fixture.wav")
    assert (runner.model_load_attempts, runner.model_constructions) == (1, 0)

    runner.transcribe("fixture.wav")
    assert (runner.model_load_attempts, runner.model_constructions) == (2, 1)


def test_three_item_batch_through_the_documented_path_constructs_once(
    tmp_root, counted_batch_seam
):
    """D2.5: one run scope, one runner, one construction — over 3 ASR rows."""

    store, rows = _seed_audio_batch(tmp_root, 3)
    coordinator_ = RunCoordinator(tmp_root, store, offline=True)

    summary = coordinator_.run_batch(rows)

    assert summary.asr_items == 3
    assert summary.model_constructions == 1
    assert counted_batch_seam.construction_count == 1
    # ...and all three rows really were transcribed by that one model.
    assert len(counted_batch_seam.generation_records) == 3
    assert [result.final_status for result in summary.results] == ["archived"] * 3
    # The coordinator owns and releases what it created.
    assert coordinator_.asr_runner is None


def test_batch_prints_the_reuse_line_once_with_the_exact_format(
    tmp_root, counted_batch_seam, capsys
):
    """A2: the run's own output states the construction count."""

    store, rows = _seed_audio_batch(tmp_root, 3)
    summary = RunCoordinator(tmp_root, store, offline=True).run_batch(rows)

    captured = capsys.readouterr()
    assert captured.err.splitlines() == [
        "run: model constructions=1 for 3 asr item(s)",
    ]
    assert summary.model_constructions == 1
    assert summary.asr_items == 3


def test_the_printed_line_is_the_shared_helper_string():
    """One source of the shipped string, so README can quote the exact literal."""

    assert coordinator.model_constructions_line("run", 1, 3) == (
        "run: model constructions=1 for 3 asr item(s)"
    )
    assert coordinator.model_constructions_line("asr", 3, 12) == (
        "asr: model constructions=3 for 12 asr item(s)"
    )


def test_the_batch_line_names_the_invoking_command(tmp_root, counted_batch_seam, capsys):
    """`run_batch` is shared, so the label is a constructor argument.

    `schedule` / `campaign` wrap the same batch entry; they pass their own
    name here instead of the line claiming to be `run`.
    """

    store, rows = _seed_audio_batch(tmp_root, 2, prefix="BVlabel")
    RunCoordinator(tmp_root, store, offline=True, command="schedule").run_batch(rows)

    assert capsys.readouterr().err.splitlines() == [
        "schedule: model constructions=1 for 2 asr item(s)",
    ]


def test_injected_runner_reports_the_per_batch_delta(tmp_root, counted_batch_seam):
    """D2.5: a caller-owned runner reused across batches reports this batch only."""

    store, rows = _seed_audio_batch(tmp_root, 3, prefix="BVdelta")
    runner = asr.ASRRunner(asr.default_config(), model_factory=counted_batch_seam)
    coordinator_ = RunCoordinator(tmp_root, store, offline=True, asr_runner=runner)

    first = coordinator_.run_batch(rows)
    assert first.model_constructions == 1
    assert first.asr_items == 3

    # Second batch over fresh rows reuses the same caller-owned model: the
    # runner's lifetime counter is 1, but the batch delta must be 0.
    store2, rows2 = _seed_audio_batch(tmp_root, 2, prefix="BVdelta2")
    second = coordinator_.run_batch(rows2)

    assert runner.model_constructions == 1
    assert second.model_constructions == 0
    assert second.asr_items == 2
    # The injected runner stays caller-owned.
    assert coordinator_.asr_runner is runner


def test_per_item_failure_continues_the_batch_with_one_construction(
    tmp_root, monkeypatch, fake_funasr, capsys
):
    """A shared runner changes the construction count only, not the outcome."""

    store, rows = _seed_audio_batch(tmp_root, 3, prefix="BVflaky")
    monkeypatch.setenv("BILI_ASR_DEVICE", "cpu")

    class FlakyModel:
        def __init__(self):
            self.calls = 0

        def generate(self, **_kwargs):
            self.calls += 1
            if self.calls == 2:  # the middle row pays for the failure
                raise asr.ASRModelError("boom")
            return [{"text": "ok", "timestamp": [[0, 1000]]}]

    def factory(**_kwargs):
        fake_funasr.construction_count += 1
        return FlakyModel()

    monkeypatch.setattr(asr, "_load_default_model", factory)

    summary = RunCoordinator(tmp_root, store, offline=True).run_batch(rows)

    captured = capsys.readouterr()
    assert [len(result.failure_codes) for result in summary.results] == [0, 1, 0]
    assert [result.ok for result in summary.results] == [True, False, True]
    # One construction still served the whole batch, and the denominator
    # counts only the rows that produced a transcript.
    assert fake_funasr.construction_count == 1
    assert captured.err.splitlines() == [
        "run: model constructions=1 for 2 asr item(s)",
    ]


def test_subtitle_only_batch_prints_no_reuse_line(tmp_root, counted_batch_seam, capsys):
    """D2.6: a zero-ASR batch prints the line on neither stream."""

    store = ManifestStore(root=tmp_root)
    identity = page_identity("BVsubonly", 0, 111, "p0")
    store.upsert({**_audio_row(identity, status="subtitle_done")})
    raw_dir = pathlib.Path(tmp_root) / "subtitles" / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / f"{artifact_stem(identity)}.json").write_text(
        json.dumps({"body": [{"from": 0.0, "to": 1.0, "content": "hi"}]}),
        encoding="utf-8",
    )

    summary = RunCoordinator(tmp_root, store, offline=True).run_batch(
        [(identity.work_id, store.get(identity.work_id))]
    )

    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == ""
    assert summary.asr_items == 0
    assert summary.model_constructions == 0
    assert counted_batch_seam.construction_count == 0


def test_the_batch_line_goes_to_stderr_and_never_to_stdout(
    tmp_root, counted_batch_seam, capsys
):
    """D2.6 as amended: the line is a diagnostic, so stdout keeps its contract.

    `campaign`'s stdout is one JSON document; `run`'s stdout is its row
    report. The batch label goes to stderr so neither is disturbed.
    """

    store, rows = _seed_audio_batch(tmp_root, 3, prefix="BVstreams")
    RunCoordinator(tmp_root, store, offline=True).run_batch(rows)

    captured = capsys.readouterr()
    assert "model constructions=" in captured.err
    assert "model constructions=" not in captured.out
    assert captured.out == ""



def test_batch_that_paid_a_construction_and_failed_every_row_still_states_it(
    tmp_root, monkeypatch, counted_batch_seam, capsys
):
    """D2.6 as amended at plan-QC: the guard is "nothing was paid".

    All three QC seats independently reproduced this: the model is built (the
    ~34 s/item cost the line exists to expose), every transcription then
    raises, and the old ``asr_items <= 0`` guard printed nothing — hiding
    precisely the first-decode failure (GPU / ROCm / checkpoint) an operator
    needs stated while the batch has already paid for it.
    """

    store, rows = _seed_audio_batch(tmp_root, 3, prefix="BVpaidfail")

    def exploding_generate(**_kwargs):
        raise asr.ASRModelError("first decode failed")

    monkeypatch.setattr(FakeAutoModel, "generate", exploding_generate)

    summary = RunCoordinator(tmp_root, store, offline=True).run_batch(rows)

    captured = capsys.readouterr()
    assert counted_batch_seam.construction_count == 1
    assert summary.model_constructions == 1
    assert summary.asr_items == 0
    assert captured.err.splitlines() == [
        "run: model constructions=1 for 0 asr item(s)",
    ]
    assert "model constructions=" not in captured.out


def test_subtitle_only_batch_prints_nothing_with_the_widened_guard(
    tmp_root, counted_batch_seam, capsys
):
    """The other half of the amendment: neither counter moved ⇒ silence.

    A subtitle-only batch pays no construction *and* transcribes nothing, so
    widening the guard must not start printing ``for 0 asr item(s)`` here.
    """

    store = ManifestStore(root=tmp_root)
    identity = page_identity("BVsubsilent", 0, 120, "p0")
    store.upsert({**_audio_row(identity, status="subtitle_done")})
    raw_dir = pathlib.Path(tmp_root) / "subtitles" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / f"{artifact_stem(identity)}.json").write_text(
        json.dumps({"body": [{"from": 0.0, "to": 1.0, "content": "hi"}]}),
        encoding="utf-8",
    )

    summary = RunCoordinator(tmp_root, store, offline=True).run_batch(
        [(identity.work_id, store.get(identity.work_id))]
    )

    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == ""
    assert summary.asr_items == 0
    assert summary.model_constructions == 0
    assert counted_batch_seam.construction_count == 0


def test_interrupted_batch_still_states_what_it_paid(
    tmp_root, monkeypatch, counted_batch_seam, capsys
):
    """Ctrl-C mid-batch: the count and the release both survive the unwind.

    The print used to sit *after* the ``try/finally``, so a KeyboardInterrupt
    (or any other exception) carried the line away while ``asr``/``pilot`` kept
    theirs; the on-call reading of a Ctrl-C'd run lost the count on the very
    action the plan names.  Assignments and print now live inside the
    ``finally``, and the original exception must still propagate.
    """

    store, rows = _seed_audio_batch(tmp_root, 3, prefix="BVinterrupt")
    coordinator_ = RunCoordinator(tmp_root, store, offline=True)

    original = coordinator_._run_batch_locked

    def interrupt_after_two(rows_arg):
        original(rows_arg[:2])
        raise KeyboardInterrupt("operator pressed Ctrl-C")

    monkeypatch.setattr(coordinator_, "_run_batch_locked", interrupt_after_two)

    with pytest.raises(KeyboardInterrupt):
        coordinator_.run_batch(rows)

    captured = capsys.readouterr()
    assert counted_batch_seam.construction_count == 1
    # The batch paid one construction and transcribed two rows before the
    # interrupt; both facts still reach stderr.
    assert captured.err.splitlines() == [
        "run: model constructions=1 for 2 asr item(s)",
    ]
    # The coordinator-owned runner is still handed back on the interrupt path.
    assert coordinator_.asr_runner is None


def test_the_reuse_line_is_dropped_when_stderr_is_closed(
    tmp_root, monkeypatch, counted_batch_seam, capsys
):
    """fd 2 closed: CPython sets ``sys.stderr = None`` and ``file=None`` is stdout.

    A closed stderr must never push the diagnostic into ``campaign``'s single
    JSON document, so both print sites refuse to print when the stream is gone.
    """

    store, rows = _seed_audio_batch(tmp_root, 3, prefix="BVnostderr")
    monkeypatch.setattr(sys, "stderr", None)

    summary = RunCoordinator(tmp_root, store, offline=True).run_batch(rows)

    captured = capsys.readouterr()
    assert "model constructions=" not in captured.out
    assert captured.out == ""
    assert summary.model_constructions == 1
    assert summary.asr_items == 3


def test_run_batch_refuses_to_nest_and_keeps_the_outer_denominator(
    tmp_root, counted_batch_seam, capsys
):
    """W2b: a nested ``run_batch`` would clobber the outer count silently.

    ``_batch_asr_items`` is per-coordinator, reset on entry and printed on
    exit, so an inner call would zero the outer denominator and print a second
    line for unfinished work.  No caller nests today; the tripwire makes that
    an error instead of a wrong number.
    """

    store, rows = _seed_audio_batch(tmp_root, 3, prefix="BVnest")
    coordinator_ = RunCoordinator(tmp_root, store, offline=True)
    seen: dict[str, object] = {}

    original = coordinator_._run_batch_locked

    def nest(rows_arg):
        try:
            coordinator_.run_batch(rows_arg[:1])
        except RuntimeError as exc:
            seen["error"] = str(exc)
        return original(rows_arg)

    coordinator_._run_batch_locked = nest
    summary = coordinator_.run_batch(rows)

    captured = capsys.readouterr()
    assert "re-entrant" in str(seen.get("error"))
    # The outer batch is intact: one line, its own denominator.
    assert summary.asr_items == 3
    assert captured.err.splitlines() == [
        "run: model constructions=1 for 3 asr item(s)",
    ]
    # And the tripwire does not leak: a later batch still runs.
    store2, rows2 = _seed_audio_batch(tmp_root, 1, prefix="BVnest2")
    later = coordinator_.run_batch(rows2)
    assert later.asr_items == 1


# ------------------------------------------------------------ docs lock

def test_readme_publishes_the_paid_or_transcribed_rule():
    """W3: the documented rule is the shipped rule, guarded like the others."""

    readme = os.path.join(os.path.dirname(__file__), "..", "README.md")
    text = open(readme, encoding="utf-8").read()
    # The shipped literal and the two labels README quotes.
    assert "model constructions=" in text
    assert "for <m> asr item(s)" in text
    assert "run: model constructions=1 for 3 asr item(s)" in text
    # The per-item loop README warns about (A2's greppable statement).
    assert "forfeits that reuse" in text
    assert "bili-asr asr --bvid <bvid>" in text
    # The amended guard: paid-but-empty states its cost, subtitle-only is silent.
    assert "failed every transcription" in text
    assert "subtitle-only" in text


def test_readme_publishes_the_declaration_surface_and_the_attempt_rule():
    """A4 is reproduced from README alone; R1's choice is stated there too."""

    readme = os.path.join(os.path.dirname(__file__), "..", "README.md")
    text = open(readme, encoding="utf-8").read()
    # The declaration surface (A4: "reproduce from README.md alone").
    assert "BILI_ASR_MODEL_ID" in text
    assert "BILI_ASR_MODEL_REVISION" in text
    assert "^asr_model_name:" in text
    assert "^asr_model_revision:" in text
    assert "[redacted]" in text
    # The measured facts (A5), documented with the greps spec 04 names, and the
    # failure line the CLI actually prints on stderr: `<work_id>: archive
    # failed` (cli.py L1737) — there is no `asr: ` prefix to quote.
    assert "^asr_vad_" in text
    assert "^asr_low_confidence_at:" in text
    assert "asr: <label>: archive" not in text
    # R1: the counter's scope and the per-row retry are documented, not implied.
    assert "model_load_attempts" in text
    assert "successful constructions" in text
    assert "retries the same load" in text


def test_a_batch_whose_every_load_fails_is_silent_and_pays_n_attempts(
    tmp_root, monkeypatch, capsys
):
    """F1: the shipped behaviour the README's attempt paragraph must describe.

    This is the review's scenario at the coordinator seam: three rows, a factory
    that raises on every call.  Every row pays one attempt, no construction is
    paid and nothing is transcribed, so the guard is silent on both streams.
    Asserted here as *behaviour* (counts and streams), not as a substring: the
    test the README's paragraph is checked against has to be able to fail when
    the paragraph (or the guard) drifts.
    """

    attempts: list[dict] = []

    def exploding_factory(**kwargs):
        attempts.append(dict(kwargs))
        raise RuntimeError("no checkpoint")

    monkeypatch.setenv("BILI_ASR_DEVICE", "cpu")
    monkeypatch.setattr(asr, "_load_default_model", exploding_factory)
    store, rows = _seed_audio_batch(tmp_root, 3, prefix="BVallloadfail")

    summary = RunCoordinator(tmp_root, store, offline=True).run_batch(rows)

    captured = capsys.readouterr()
    # N attempts were really paid...
    assert len(attempts) == 3
    assert summary.model_constructions == 0
    assert summary.asr_items == 0
    assert [result.ok for result in summary.results] == [False, False, False]
    # ...and the cost is stated nowhere: no reuse line on either stream.
    assert "model constructions=" not in captured.err
    assert "model constructions=" not in captured.out
    assert captured.err == ""
    assert captured.out == ""
    # The failures are reported per row instead — the only operator surface.
    assert len(summary.failed) == 3


def test_the_attempt_count_survives_on_the_runner_the_batch_no_longer_holds(
    tmp_root, monkeypatch, capsys
):
    """F1/F2: the count is recorded on an in-process surface, and nowhere else.

    The coordinator releases its runner at batch exit, so the N attempts a
    failed batch paid are unreachable from `RunSummary` — this pins that
    boundary deliberately: the README states the count is *recorded, not
    printed*, and this test is where either half may not silently change.  A
    caller that owns the runner (an injected one, or the in-process `asr` /
    `pilot` loops) is the only surface that can read it.
    """

    attempts: list[dict] = []

    def exploding_factory(**kwargs):
        attempts.append(dict(kwargs))
        raise RuntimeError("no checkpoint")

    monkeypatch.setenv("BILI_ASR_DEVICE", "cpu")
    runner = asr.ASRRunner(
        asr.ASRConfig("local-test-model", device="cpu"),
        model_factory=exploding_factory,
    )
    store, rows = _seed_audio_batch(tmp_root, 2, prefix="BVinjected")
    coordinator_ = RunCoordinator(tmp_root, store, offline=True, asr_runner=runner)

    summary = coordinator_.run_batch(rows)

    capsys.readouterr()
    # The batch paid one attempt per row while holding the caller's runner...
    assert runner.model_load_attempts == 2
    assert runner.model_constructions == 0
    # ...and the caller-owned runner is handed back, so the count stays
    # readable after the batch — the surface the README names.
    assert coordinator_.asr_runner is runner
    assert summary.model_constructions == 0
    assert not hasattr(summary, "model_load_attempts")


def test_readme_states_the_attempts_are_recorded_rather_than_printed():
    """F1's contract in words: the README may not promise a printed attempt line.

    The review's finding was a paragraph asserting a diagnostic the tool does
    not emit ("reports ``model constructions=0``", "still states its cost — as N
    attempts and 0 constructions").  The behavioural tests above pin what is
    shipped; these assertions pin what is *written*, so the paragraph cannot
    drift back into promising a line.  Together they agree by construction: the
    README is only allowed to claim the silence the tests measure.
    """

    readme = os.path.join(os.path.dirname(__file__), "..", "README.md")
    text = open(readme, encoding="utf-8").read()

    # The truthful rule, stated: silence, and where the number actually lives.
    assert "prints no reuse line" in text
    assert "recorded, not printed" in text
    assert "ASRRunner.model_load_attempts" in text
    assert "no command prints the attempt count" in text
    # ...and the two false promises are gone for good.
    assert "still states its cost" not in text
    assert "as N attempts and 0 constructions" not in text
    assert "reports `model constructions=0`" not in text


def test_readme_does_not_claim_relative_paths_are_rejected():
    """F3: the claim is narrowed to the rule the code implements (D4.2).

    A *relative* path-shaped declaration satisfies ``_MODEL_IDENTIFIER`` +
    ``"/"`` + no forbidden marker, and is recorded verbatim (verified through
    the real `ASRConfig`/`provenance()` path by the test below).  The README may
    therefore only claim rejection for absolute paths, URLs and
    credential-like values — the categories the scan actually catches.
    """

    readme = os.path.join(os.path.dirname(__file__), "..", "README.md")
    text = open(readme, encoding="utf-8").read()

    assert "absolute path" in text
    assert "relative" in text and "path-shaped" in text
    # The rule is named exactly: the same identifier scan, plus the slash rule.
    assert "same identifier rule" in text
    assert "slash-qualified" in text
    # The old, broader claim: "anything path-, URL-, or credential-like".
    assert "anything path-, URL-, or credential-like is rejected" not in text


def test_readme_states_the_plan_qc_fix_wave_claims():
    """The sentences this fix wave added are pinned where they are read.

    Each assertion here corresponds to a claim that would be *false* if the code
    moved back: the two gates of the measurement family (S-3), the inclusive
    threshold (S-4), the recompute recipe that makes A5 exact (S-5), the
    separator-aware credential rule (F-001), and the D4.5 probe's existence plus
    its overridable inputs (S-6).
    """

    readme = os.path.join(os.path.dirname(__file__), "..", "README.md")
    text = open(readme, encoding="utf-8").read()

    # S-3: only the capture keys are source-gated; the confidence pair is not.
    assert "source-gated" in text
    assert "**capture**" in text
    assert "score rule" in text
    # The old, unqualified sentence: one gate stated for both families.
    assert "records none\nof it, exactly as it records no other" not in text
    # S-4: the boundary is stated inclusively, not as "sub-second".
    assert "at or below the shaper's 1.0 s pause threshold" in text
    assert "sub-second-adjacent" not in text
    # S-5: the recompute is spelled out, including the zero-length skip.
    assert "zero-length cue describes no captured" in text
    # F-001: the credential rule is stated as separator-aware, and the old
    # "=" -only illustration is gone.
    assert "separator-aware, not word-bounded" in text
    assert "credential-like value (`token=...`)" not in text
    # S-6: the probe is findable and its defaults are labelled as an example.
    assert "scripts/probe_target_host_load.py" in text
    assert "BILI_ASR_PROBE_SOURCE" in text


def test_a_relative_path_shaped_declaration_is_accepted_and_recorded():
    """F3's code half: the documented rule and the implementation agree.

    D4.2's rule is shape-based, so this value passes it.  The test exists so the
    README's narrowed sentence is checked against behaviour: if the rule is ever
    tightened to reject relative paths, this test fails and the README sentence
    must be widened again in the same change.
    """

    relative_path = "srv/private/models/Fun-ASR-Nano-2512"
    config = asr.ASRConfig("/srv/models/Fun-ASR-Nano-2512", model_id=relative_path)

    assert asr.ASRRunner(config).provenance()["model_name"] == relative_path
    # The absolute form of the same path is refused, which is exactly the
    # distinction the README now draws.
    with pytest.raises(ValueError):
        asr.ASRConfig("/srv/models/Fun-ASR-Nano-2512", model_id=f"/{relative_path}")


def test_the_substituted_declaration_is_redaction_scanned_like_any_value():
    """F4 (mutation M6): the slot replacement still passes the scan.

    ``ASRConfig.__post_init__`` validates the declaration, so an unsafe value
    cannot arrive through normal construction — which is why dropping the
    re-scan in ``provenance()`` survived 78/78 tests.  This test constructs a
    subclass that bypasses validation and asserts the substituted value is
    redacted anyway, so the defence-in-depth layer is load-bearing under test.
    """

    class Unvalidated(asr.ASRConfig):
        def __post_init__(self) -> None:  # deliberately skips D4.2's validation
            pass

    for hostile in (
        "/etc/passwd",
        "C:\\models\\Fun-ASR-Nano-2512",
        "https://models.example/Fun-ASR-Nano-2512",
        "token=private-model",
        # F-001: the same shape through the bypassing route, where only the
        # render-side re-scan stands between it and the frontmatter.
        "myorg/token_abc",
        "myorg/sessdata123",
    ):
        config = Unvalidated("local-test-model", model_id=hostile)
        provenance = asr.ASRRunner(config).provenance()

        assert provenance["model_name"] == "[redacted]", hostile
        assert hostile not in json.dumps(provenance), hostile
        # The nine-key contract holds on this route too.
        assert list(provenance) == [
            "model_name", "model_revision", "device", "language", "vad_model",
            "vad_max_segment_s", "hotwords", "offline", "local_source",
        ]


def test_the_render_rescan_applies_the_validators_strength_to_the_slot():
    """S-2: rendering and validation now use the same rule, not merely one helper.

    ``__post_init__`` validates a declaration at hub level (``hub_level=True``)
    while the render-side re-scan used the default (``False``), so a subclass
    that bypasses validation could render a *bare* declared id the validator
    would have refused.  The re-scan is now hub-level for a declaration, and
    still permissive for a configured name — where a bare safe identifier such
    as ``local-model`` is the historical, legitimate output.
    """

    class Unvalidated(asr.ASRConfig):
        def __post_init__(self) -> None:  # deliberately skips D4.2's validation
            pass

    # A declaration is held to the validator's strength: a bare name is not a
    # hub-level identifier, so it never reaches the frontmatter.
    bare_declaration = asr.ASRRunner(
        Unvalidated("local-test-model", model_id="barename")
    ).provenance()
    assert bare_declaration["model_name"] == "[redacted]"
    assert "barename" not in json.dumps(bare_declaration)

    # With no declaration the slot holds the configured value under the
    # historical rule, which does allow a bare identifier.
    assert (
        asr.ASRRunner(Unvalidated("local-test-model")).provenance()["model_name"]
        == "local-test-model"
    )
