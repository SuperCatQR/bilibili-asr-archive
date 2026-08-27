import json
import sys
from pathlib import Path

import pytest

from scripts.verify_baseline import (
    SNAPSHOT_SCHEMA,
    PrerequisiteError,
    advisory_applies,
    audit,
    load_snapshot,
    main,
)


def test_snapshot_schema_and_digest_are_validated(tmp_path: Path):
    path = tmp_path / "advisories.json"
    path.write_text(json.dumps({"schema": SNAPSHOT_SCHEMA, "advisories": []}), encoding="utf-8")
    data, digest = load_snapshot(path)
    assert data["schema"] == SNAPSHOT_SCHEMA
    assert len(digest) == 16


def test_arbitrary_snapshot_is_rejected(tmp_path: Path):
    path = tmp_path / "not-a-snapshot.json"
    path.write_text(json.dumps({"name": "anything"}), encoding="utf-8")
    with pytest.raises(PrerequisiteError, match="schema"):
        load_snapshot(path)


def test_advisory_in_range_version_matches():
    assert advisory_applies({"id": "TEST-1", "name": "demo", "specifier": ">=1,<2"}, "1.5")


def test_advisory_out_of_range_version_does_not_match():
    assert not advisory_applies({"id": "TEST-1", "name": "demo", "specifier": ">=1,<2"}, "2.0")


def test_unsupported_advisory_specifier_is_named_prerequisite():
    with pytest.raises(PrerequisiteError, match="unsupported advisory specifier for TEST-1"):
        advisory_applies({"id": "TEST-1", "name": "demo", "specifier": "not a specifier"}, "1.0")


def test_audit_fails_for_in_range_advisory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    snapshot = tmp_path / "advisories.json"
    snapshot.write_text(json.dumps({"schema": SNAPSHOT_SCHEMA, "advisories": [{"id": "TEST-1", "name": "demo", "specifier": ">=1,<2"}]}), encoding="utf-8")
    monkeypatch.setattr("scripts.verify_baseline.venv_site_packages", lambda _python: ["C:/venv/Lib/site-packages"])
    monkeypatch.setattr("scripts.verify_baseline.installed_packages", lambda _python: {"demo": "1.5"})
    result: dict[str, object] = {"commands": []}
    with pytest.raises(RuntimeError, match="findings"):
        audit(Path(sys.executable), snapshot, result)
    assert result["audit"]["finding_ids"] == ["TEST-1"]


def test_audit_passes_for_out_of_range_advisory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    snapshot = tmp_path / "advisories.json"
    snapshot.write_text(json.dumps({"schema": SNAPSHOT_SCHEMA, "advisories": [{"id": "TEST-1", "name": "demo", "specifier": ">=1,<2"}]}), encoding="utf-8")
    monkeypatch.setattr("scripts.verify_baseline.venv_site_packages", lambda _python: ["C:/venv/Lib/site-packages"])
    monkeypatch.setattr("scripts.verify_baseline.installed_packages", lambda _python: {"demo": "2.0"})
    result: dict[str, object] = {"commands": []}
    audit(Path(sys.executable), snapshot, result)
    assert result["audit"]["status"] == "passed"


def test_invalid_arguments_write_named_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("scripts.verify_baseline.ROOT", tmp_path)
    assert main(["--pip-audit", "unused"]) == 2
    payload = json.loads((tmp_path / "verification-results" / "baseline.json").read_text(encoding="utf-8"))
    assert payload["status"] == "prerequisite_failed"
    assert payload["error"] == "invalid arguments; use --help for supported options"
