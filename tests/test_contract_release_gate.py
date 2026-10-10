"""Release support cannot be inferred from ignored tests or regenerated history."""
import json
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from bili_asr.contracts.registry import catalog
from bili_asr.contracts.release_gate import validate_release_collection
from scripts import pytest_shard

ROOT = Path(__file__).resolve().parents[1]


def _nodes(value):
    return [node for row in value["release_acceptance"]["upgrades"] for node in row["test_nodes"]] + list(
        value["release_acceptance"]["required_tests"])


def _transition(value):
    edge = value["upgrades"][0]
    return {"contract": "bilibili-v1", "kind": "reader-retirement", "source": edge["source"],
            "target": edge["target"], "path": [edge["identity"]], "acceptance": [edge["identity"]],
            "reason": "Explicit old archive conversion is validated before dropping runtime access"}


def _shrink(value):
    entry = next(item for item in value["contracts"] if item["identity"] == "bilibili-v1")
    entry["capabilities"] = ["snapshot"]


def test_actual_full_pytest_collection_covers_every_registered_upgrade(monkeypatch):
    monkeypatch.chdir(ROOT)
    report = validate_release_collection(ROOT, pytest_shard._node_ids())
    assert report["registered_edges"] == 9
    assert report["frozen_files"] == 3
    assert all(report["collected_acceptance"].values())


def test_frozen_evidence_checkout_is_byte_identical_with_autocrlf_enabled(tmp_path):
    """A Windows-style checkout must retain the same historical bytes as Git archive."""
    def git(*arguments):
        return subprocess.run(["git", "-C", str(tmp_path), *arguments], check=True,
                              capture_output=True, text=True)

    git("init", "-q")
    git("config", "core.autocrlf", "true")
    shutil.copyfile(ROOT / ".gitattributes", tmp_path / ".gitattributes")
    expected = {}
    for entry in catalog()["release_acceptance"]["frozen_files"]:
        relative = entry["path"]
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        expected[relative] = (ROOT / relative).read_bytes()
        destination.write_bytes(expected[relative])
    git("add", ".gitattributes", *expected)
    for relative in expected:
        (tmp_path / relative).unlink()
    git("checkout-index", "--all")
    for relative, original in expected.items():
        assert (tmp_path / relative).read_bytes() == original, relative


def test_collect_ignore_cannot_supply_release_acceptance(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_archive_upgrade.py").write_text("def test_ignored(): pass\n")
    (tests / "test_other.py").write_text("def test_collected(): pass\n")
    (tests / "conftest.py").write_text("collect_ignore = ['test_archive_upgrade.py']\n")
    result = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q"],
                            cwd=tmp_path, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    nodes = [line.strip() for line in result.stdout.splitlines() if "::" in line]
    assert nodes == ["tests/test_other.py::test_collected"]
    with pytest.raises(ValueError, match="was not collected"):
        validate_release_collection(ROOT, nodes)


def test_removing_completed_work_reuse_test_blocks_release_even_with_all_upgrade_edges():
    value = catalog()
    removed = "tests/test_upgrade_result_reuse.py::test_formal_upgrade_reuses_completed_ai_jobs_and_preserves_pending_work"
    nodes = [node for node in _nodes(value) if node != removed]
    with pytest.raises(ValueError, match="required release test was not collected: " + removed):
        validate_release_collection(ROOT, nodes, candidate=value)


@pytest.mark.parametrize("damage", ["missing-case", "similar-name", "missing-matrix", "extra-matrix", "installed-test"])
def test_missing_cases_and_unregistered_matrix_rows_fail(damage):
    value = deepcopy(catalog())
    nodes = _nodes(value)
    if damage == "missing-case":
        target = value["release_acceptance"]["upgrades"][0]["test_nodes"][0]
        nodes = [node for node in nodes if node != target]
    elif damage == "similar-name":
        target = value["release_acceptance"]["upgrades"][0]["test_nodes"][1]
        nodes = [node + "_unrelated" if node == target else node for node in nodes]
    elif damage == "installed-test":
        nodes.remove(value["release_acceptance"]["required_tests"][1])
    elif damage == "missing-matrix":
        value["release_acceptance"]["upgrades"].pop()
    else:
        row = deepcopy(value["release_acceptance"]["upgrades"][0])
        row["edge"] = "unregistered/v1"
        value["release_acceptance"]["upgrades"].append(row)
    with pytest.raises(ValueError, match="collected|exactly one"):
        validate_release_collection(ROOT, nodes, candidate=value)


@pytest.mark.parametrize("filename", ["bilibili-v1-frozen.zip", "bilibili-v1-frozen.json"])
def test_fixed_zip_and_expected_digest_reject_rewritten_history(tmp_path, filename):
    value = catalog()
    for evidence in value["release_acceptance"]["frozen_files"]:
        path = tmp_path / evidence["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / evidence["path"], path)
    changed = tmp_path / "tests/fixtures/data" / filename
    changed.write_bytes(changed.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="frozen release evidence changed"):
        validate_release_collection(tmp_path, _nodes(value), candidate=value)


def test_pr_baseline_prevents_rebinding_a_frozen_sample_to_new_expected_bytes():
    previous = catalog()
    value = deepcopy(previous)
    value["release_acceptance"]["frozen_files"][0]["sha256"] = "a" * 64
    with pytest.raises(ValueError, match="cannot be removed or rebound"):
        validate_release_collection(ROOT, _nodes(value), candidate=value, previous_catalog=previous)


@pytest.mark.parametrize("loss", ["identity", "capability", "consumer"])
def test_support_reduction_without_conversion_is_blocked(loss):
    value = deepcopy(catalog())
    entry = next(item for item in value["contracts"] if item["identity"] == "bilibili-v1")
    if loss == "identity":
        value["contracts"].remove(entry)
    elif loss == "capability":
        _shrink(value)
    else:
        entry["consumers"] = ["storage.snapshots"]
    with pytest.raises(ValueError, match="support shrank"):
        validate_release_collection(ROOT, _nodes(value), candidate=value)


def test_registered_path_and_collected_evidence_allow_explicit_reader_retirement():
    value = deepcopy(catalog())
    _shrink(value)
    value["release_acceptance"]["transitions"] = [_transition(value)]
    assert validate_release_collection(ROOT, _nodes(value), candidate=value)["registered_edges"] == 9


@pytest.mark.parametrize("damage", ["unregistered-path", "evidence", "target", "self-replacement"])
def test_transition_declaration_alone_does_not_waive_evidence(damage):
    value = deepcopy(catalog())
    _shrink(value)
    declaration = _transition(value)
    if damage == "unregistered-path":
        declaration["path"] = ["invented/v1"]
    elif damage == "evidence":
        declaration["acceptance"] = []
    elif damage == "target":
        declaration["target"] = ["artifact-storage-v1"]
    else:
        declaration["kind"] = "replacement"
        declaration["target"] = ["bilibili-v1", "universal-v2"]
    value["release_acceptance"]["transitions"] = [declaration]
    with pytest.raises(ValueError, match="transition|replacement"):
        validate_release_collection(ROOT, _nodes(value), candidate=value)


def test_new_independent_contract_needs_no_invented_migration_but_pr_baseline_is_enforced():
    value = deepcopy(catalog())
    additional = {"identity": "new-independent/v1", "capabilities": ["read"], "consumers": ["reader"]}
    value["contracts"].append(additional)
    assert validate_release_collection(ROOT, _nodes(value), candidate=value)
    previous = deepcopy(value)
    value["contracts"].pop()
    with pytest.raises(ValueError, match="new-independent/v1"):
        validate_release_collection(ROOT, _nodes(value), candidate=value, previous_catalog=previous)


def test_shard_gate_blocks_before_any_test_execution(monkeypatch, capsys):
    monkeypatch.chdir(ROOT)
    monkeypatch.delenv("BILI_ASR_CONTRACT_BASELINE_REF", raising=False)
    monkeypatch.setattr(pytest_shard, "_node_ids", lambda: ["tests/test_other.py::test_ok"])
    monkeypatch.setattr(pytest_shard.subprocess, "run", lambda *a, **kw: pytest.fail("must stop before shard execution"))
    assert pytest_shard.main(["--shard-index", "0", "--shard-count", "4"]) == 1
    assert "was not collected" in capsys.readouterr().err


def test_git_baseline_is_exact_readonly_and_required(monkeypatch):
    from types import SimpleNamespace
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout=json.dumps(catalog()))
    monkeypatch.setattr(pytest_shard.subprocess, "run", run)
    assert pytest_shard._previous_catalog("a" * 40)["contracts"]
    assert calls == [["git", "show", "a" * 40 + ":docs/contracts/registry.json"]]
    with pytest.raises(ValueError, match="full Git commit"):
        pytest_shard._previous_catalog("HEAD~1")
    monkeypatch.setattr(pytest_shard.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=1))
    with pytest.raises(ValueError, match="cannot read"):
        pytest_shard._previous_catalog("a" * 40)
