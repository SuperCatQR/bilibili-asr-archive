import hashlib
import json
import sys
from pathlib import Path

import pytest

from scripts.verify_baseline import (
    FIXTURE_SCHEMA,
    SNAPSHOT_SCHEMA,
    PrerequisiteError,
    advisory_applies,
    audit,
    load_snapshot,
    main,
    redact,
    safe_env,
    validate_fixture,
)


def write_fixture(path: Path, *, required_distributions: list[str] | None = None) -> Path:
    path.mkdir()
    wheel = path / "demo-1.0-py3-none-any.whl"
    wheel.write_bytes(b"not a real wheel")
    manifest = {
        "schema": FIXTURE_SCHEMA,
        "project": "bili-asr",
        "required_distributions": required_distributions or ["demo"],
        "artifacts": [{"filename": wheel.name, "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest()}],
    }
    (path / "fixture-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return path


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


def test_duplicate_advisory_ids_are_rejected(tmp_path: Path):
    path = tmp_path / "advisories.json"
    path.write_text(
        json.dumps(
            {
                "schema": SNAPSHOT_SCHEMA,
                "advisories": [
                    {"id": "TEST-1", "name": "demo", "specifier": ">=1"},
                    {"id": "TEST-1", "name": "other", "specifier": ">=1"},
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(PrerequisiteError, match="duplicate advisory id TEST-1"):
        load_snapshot(path)


def test_advisory_in_range_version_matches():
    assert advisory_applies({"id": "TEST-1", "name": "demo", "specifier": ">=1,<2"}, "1.5")


def test_advisory_out_of_range_version_does_not_match():
    assert not advisory_applies({"id": "TEST-1", "name": "demo", "specifier": ">=1,<2"}, "2.0")


def test_unsupported_advisory_specifier_is_named_prerequisite():
    with pytest.raises(PrerequisiteError, match="unsupported specifier for TEST-1"):
        advisory_applies({"id": "TEST-1", "name": "demo", "specifier": "not a specifier"}, "1.0")


def test_audit_fails_for_in_range_advisory(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("scripts.verify_baseline.installed_packages", lambda _python: {"demo": "1.5"})
    result: dict[str, object] = {"commands": []}
    snapshot = {"schema": SNAPSHOT_SCHEMA, "advisories": [{"id": "TEST-1", "name": "demo", "specifier": ">=1,<2"}]}
    with pytest.raises(RuntimeError, match="findings"):
        audit(Path(sys.executable), snapshot, "digest", result)
    assert result["audit"]["finding_ids"] == ["TEST-1"]


def test_audit_passes_for_out_of_range_advisory(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("scripts.verify_baseline.installed_packages", lambda _python: {"demo": "2.0"})
    result: dict[str, object] = {"commands": []}
    snapshot = {"schema": SNAPSHOT_SCHEMA, "advisories": [{"id": "TEST-1", "name": "demo", "specifier": ">=1,<2"}]}
    audit(Path(sys.executable), snapshot, "digest", result)
    assert result["audit"]["status"] == "passed"


def test_fixture_manifest_rejects_modified_artifact(tmp_path: Path):
    fixture = write_fixture(tmp_path / "fixture")
    (fixture / "demo-1.0-py3-none-any.whl").write_bytes(b"modified")
    with pytest.raises(PrerequisiteError, match="artifact content"):
        validate_fixture(fixture)


def test_fixture_manifest_rejects_duplicate_required_distributions(tmp_path: Path):
    fixture = write_fixture(tmp_path / "fixture", required_distributions=["Demo", "demo"])
    with pytest.raises(PrerequisiteError, match="required_distributions contains duplicates"):
        validate_fixture(fixture)


def test_safe_env_removes_session_and_proxy_variables(monkeypatch: pytest.MonkeyPatch):
    for key in ("PYTHONPATH", "BILI_SESSDATA", "SESSDATA", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.setenv(key, "secret")
    env = safe_env()
    assert not {"PYTHONPATH", "BILI_SESSDATA", "SESSDATA", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"} & env.keys()
    assert env["PIP_NO_INDEX"] == "1"


def test_redact_removes_bearer_json_header_and_url_secrets():
    diagnostic = 'Authorization: Bearer abc.def\n{"access_token":"secret"}\nhttps://example.test/?signature=secret'
    redacted = redact(diagnostic)
    assert "abc.def" not in redacted
    assert '"secret"' not in redacted
    assert "example.test" not in redacted
    assert "[redacted]" in redacted
    assert "[redacted-url]" in redacted


def test_invalid_arguments_write_named_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("scripts.verify_baseline.DEFAULT_RESULT", tmp_path / "verification-results" / "baseline.json")
    assert main(["--pip-audit", "unused"]) == 2
    payload = json.loads((tmp_path / "verification-results" / "baseline.json").read_text(encoding="utf-8"))
    assert payload["status"] == "prerequisite_failed"
    assert payload["error"] == "invalid_arguments: use --help for supported options"
