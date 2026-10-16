"""A disk install and a running interpreter must attest the same complete build."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from bili_asr import release_identity as identity
from bili_asr.services import worker_health
from scripts import build_release, production


@pytest.fixture
def attested_package(tmp_path, monkeypatch):
    root = tmp_path / "package"
    root.mkdir()
    (root / "__init__.py").write_text("original = True\n", encoding="utf-8")
    manifest = identity.create_manifest(root, "a" * 40, "b" * 64)
    (root / identity.MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(identity, "PACKAGE_ROOT", root)
    monkeypatch.setattr(identity, "_STARTUP_MANIFEST", manifest)
    monkeypatch.setattr(identity, "_STARTUP_ERROR", None)
    monkeypatch.delenv("BILI_ASR_EXPECTED_BUILD_ID", raising=False)
    return root, manifest


@pytest.mark.parametrize("change", ["modified", "added", "removed", "new_manifest"])
def test_startup_build_remains_frozen_and_detects_disk_drift(attested_package, change):
    root, original = attested_package
    assert identity.require_expected_build(original["build_id"])["state"] == "verified"
    if change == "modified":
        (root / "__init__.py").write_text("modified = True\n")
    elif change == "added":
        (root / "extra.py").write_text("injected = True\n")
    elif change == "removed":
        (root / "__init__.py").unlink()
    else:
        value = identity.create_manifest(root, "c" * 40, "b" * 64)
        (root / identity.MANIFEST_NAME).write_text(json.dumps(value))
    status = identity.build_status()
    assert status["build_id"] == original["build_id"]
    assert status["source_commit"] == original["source_commit"]
    assert status["state"] == "disk_drift"
    with pytest.raises(identity.ReleaseIdentityError):
        identity.require_expected_build()


def test_guard_rejects_wrong_expected_release(attested_package):
    with pytest.raises(identity.ReleaseIdentityError, match="unexpected_build"):
        identity.require_expected_build("f" * 64)


@pytest.mark.parametrize("field,value", [
    ("schema_version", 2), ("source_commit", "not-a-commit"),
    ("lock_sha256", None), ("build_id", "invalid"),
    ("files", {}), ("files", []), ("files", {"extra.txt": "a" * 64}),
    ("build_id", "f" * 64),
])
def test_invalid_manifest_never_attests_a_release(attested_package, field, value):
    _, manifest = attested_package
    with pytest.raises(identity.ReleaseIdentityError):
        identity.validate_manifest({**manifest, field: value})


@pytest.mark.parametrize("value", [None, {}, {"unexpected": True}])
def test_manifest_requires_exact_schema(value):
    with pytest.raises(identity.ReleaseIdentityError, match="invalid build manifest"):
        identity.validate_manifest(value)


def test_invalid_source_identity_is_rejected_before_hashing(tmp_path):
    with pytest.raises(identity.ReleaseIdentityError, match="invalid release identity"):
        identity.create_manifest(tmp_path, "not-a-commit", "b" * 64)


def test_inventory_ignores_bytecode_but_rejects_nonfiles(tmp_path):
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "injected.py").write_text("ignored")
    assert identity.package_files(tmp_path) == {}
    (tmp_path / "invalid.py").mkdir()
    with pytest.raises(identity.ReleaseIdentityError, match="unsupported file"):
        identity.package_files(tmp_path)


@pytest.mark.parametrize("contents", ["not json", " " * (2 * 1024 * 1024 + 1)],
                         ids=["malformed-json", "oversized-manifest"])
def test_invalid_disk_manifest_is_reported_without_loading_it(attested_package, contents):
    root, _ = attested_package
    (root / identity.MANIFEST_NAME).write_text(contents, encoding="utf-8")
    assert identity._capture() == (None, "invalid_manifest")
    assert identity.build_status()["state"] == "disk_drift"


def test_unreadable_package_fails_closed(attested_package, monkeypatch):
    def unreadable(_root):
        raise OSError("private filesystem details")
    monkeypatch.setattr(identity, "package_files", unreadable)
    assert identity.build_status()["state"] == "disk_unreadable"
    with pytest.raises(identity.ReleaseIdentityError, match="disk_unreadable"):
        identity.require_expected_build()


@pytest.mark.parametrize("name", ["../secret.py", "/secret.py", "a\\secret.py", "a//b.py"])
def test_manifest_rejects_unsafe_file_inventory(attested_package, name):
    _, manifest = attested_package
    manifest = {**manifest, "files": {name: "a" * 64}}
    with pytest.raises(identity.ReleaseIdentityError):
        identity.validate_manifest(manifest)


def test_drift_drains_worker_and_stopped_record_is_not_ready(attested_package, tmp_path):
    root, manifest = attested_package
    stop = threading.Event()
    with worker_health.WorkerHealth(tmp_path / "archive", role="asr", stop=stop, interval=.01) as health:
        with health.attempt():
            health.profile("d" * 64)
            first = json.loads(health.path.read_text())
            assert first["phase"] == "running"
            assert first["build"]["build_id"] == manifest["build_id"]
        (root / "__init__.py").write_text("changed = True\n")
        assert stop.wait(2)
        assert identity.build_status()["state"] == "disk_drift"
    record = worker_health.inspect_workers(health.directory)[0]
    assert record["observed_state"] == "stopped"
    assert record["reason"] == "disk_drift"
    assert record["profile_digests"] == ["d" * 64]
    assert record["gpu_acceptance"] == "not_recorded"
    assert record["build"]["production_acceptance"] == "pending"


def test_stale_or_invalid_health_does_not_claim_ready(attested_package, tmp_path):
    with worker_health.WorkerHealth(tmp_path / "archive", role="cpu", stop=threading.Event()) as health:
        value = json.loads(health.path.read_text())
    value.update(phase="running", heartbeat_at="2000-01-01T00:00:00+00:00")
    health.path.write_text(json.dumps(value))
    (health.directory / "invalid.json").write_text("broken")
    assert {r["observed_state"] for r in worker_health.inspect_workers(health.directory)} == {"stale", "invalid_record"}


@pytest.mark.parametrize("build_state, expected, observed", [
    ("verified", "f" * 64, "unexpected_build"),
    ("unexpected_build", None, "unexpected_build"),
    ("unattested", None, "unattested"),
    ("invented", None, "invalid_record"),
])
def test_fresh_heartbeat_does_not_attest_wrong_build(attested_package, tmp_path, build_state, expected, observed):
    with worker_health.WorkerHealth(tmp_path / "archive", role="cpu", stop=threading.Event()) as health:
        value = json.loads(health.path.read_text())
    value["phase"] = "ready"
    value["build"]["state"] = build_state
    health.path.write_text(json.dumps(value))
    assert worker_health.inspect_workers(health.directory, expected_build_id=expected)[0]["observed_state"] == observed


@pytest.mark.parametrize("business_fails", [False, True])
def test_observation_failure_preserves_attempt_outcome(attested_package, tmp_path, monkeypatch, business_fails):
    from bili_asr.storage import open_database, WorkflowRepository
    from bili_asr.workflow import WorkflowExecutor
    from bili_asr.workflow_models import AsrPolicy, AsrProfile, JobKind
    from tests.test_workflow_control_plane import _seed_part
    connection = open_database(tmp_path / "archive")
    _seed_part(connection)
    repository = WorkflowRepository(connection)
    profile = repository.register_profile(AsrProfile("health", "offline", device="cpu"))
    repository.plan(part_ids=[1], policy=AsrPolicy.ALL, profile_id=profile)
    stop = threading.Event()
    original = worker_health.atomic_replace_file
    def fail(*args, **kwargs):
        raise OSError("private health write error")
    def handler(_job):
        monkeypatch.setattr(worker_health, "atomic_replace_file", fail)
        if business_fails:
            raise ValueError("private business failure")
        return {"successful_result": True}
    try:
        with worker_health.WorkerHealth(tmp_path / "archive", role="cpu", stop=stop) as health:
            result = WorkflowExecutor(repository, worker_id="health-test", kinds=(JobKind.SUBTITLE,),
                handlers={JobKind.SUBTITLE: handler}, attempt_scope=health.attempt, drain_requested=stop.is_set).run(limit=1)
            assert stop.is_set()
            assert result.failed == int(business_fails) and result.succeeded == int(not business_fails)
            row = connection.execute("SELECT outcome,error_code,result_json FROM workflow_attempts").fetchone()
            assert row["error_code"] == ("ValueError" if business_fails else None)
            if not business_fails:
                assert json.loads(row["result_json"]) == {"successful_result": True}
            monkeypatch.setattr(worker_health, "atomic_replace_file", original)
    finally:
        connection.close()


def test_health_write_failure_requests_drain(attested_package, tmp_path, monkeypatch):
    stop = threading.Event()
    with worker_health.WorkerHealth(tmp_path / "archive", role="cpu", stop=stop, interval=.01) as health:
        original = worker_health.atomic_replace_file
        def fail(*args, **kwargs):
            raise OSError("private filesystem error")
        monkeypatch.setattr(worker_health, "atomic_replace_file", fail)
        assert stop.wait(2)
        monkeypatch.setattr(worker_health, "atomic_replace_file", original)
    assert json.loads(health.path.read_text())["reason"] == "health_write_failed"


def test_startup_checks_wheel_and_installed_build(tmp_path, monkeypatch, capsys):
    env_file = tmp_path / ".env"
    env_file.write_text("BILI_SESSDATA=private-startup-secret\n")
    env_file.chmod(0o600)
    wheel = tmp_path / "app.whl"
    wheel.write_bytes(b"wheel")
    manifest = tmp_path / "release.json"
    manifest.write_text(json.dumps({"wheel": wheel.name, "build_id": "a" * 64,
                                   "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest()}))
    monkeypatch.setattr(sys, "argv", ["production", "--env-file", str(env_file),
                                     "--release-manifest", str(manifest), "--", "workflow", "status"])
    launched = []
    monkeypatch.setattr(production.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1))
    monkeypatch.setattr(production.subprocess, "call", lambda *a, **k: launched.append(k) or 0)
    assert production.main() == 2
    assert not launched
    monkeypatch.setattr(production.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0))
    assert production.main() == 0
    assert launched[0]["env"]["BILI_ASR_EXPECTED_BUILD_ID"] == "a" * 64
    wheel.write_bytes(b"changed")
    assert production.main() == 2
    assert len(launched) == 1
    assert "private-startup-secret" not in capsys.readouterr().err


def test_complete_release_installs_and_guards_real_entrypoint(tmp_path):
    """Real git archive -> wheel -> isolated target -> installed CLI, no network."""
    import shutil
    repository = tmp_path / "repository"
    repository.mkdir()
    project = Path(__file__).resolve().parents[1]
    for name in ("pyproject.toml", "uv.lock", "LICENSE", "README.md"):
        shutil.copyfile(project / name, repository / name)
    shutil.copytree(project / "src" / "bili_asr", repository / "src" / "bili_asr",
                    ignore=shutil.ignore_patterns("__pycache__", identity.MANIFEST_NAME))
    for args in (["init", "-q"], ["add", "."],
                 ["-c", "user.name=Release Test", "-c", "user.email=test@example.invalid",
                  "commit", "-qm", "release fixture"]):
        subprocess.run(["git", *args], cwd=repository, check=True, capture_output=True)
    output = tmp_path / "release"
    release = build_release.build(repository, output)
    with pytest.raises(ValueError, match="new directory"):
        build_release.build(repository, output)
    installed = tmp_path / "installed"
    subprocess.run([sys.executable, "-m", "pip", "install", "--no-index", "--no-deps",
                    "--disable-pip-version-check", "--target", str(installed), str(output / release["wheel"])],
                   check=True, capture_output=True, timeout=120)
    probe = ("import sys,json,os; sys.path.insert(0,sys.argv[1]); "
             "os.environ['BILI_ASR_EXPECTED_BUILD_ID']=sys.argv[2]; "
             "from bili_asr.release_identity import require_expected_build; "
             "print(json.dumps(require_expected_build())); "
             "from bili_asr.cli.main import _main; assert _main(['--version']) == 0")
    # argparse exits normally for --version; the status precedes it.
    result = subprocess.run([sys.executable, "-I", "-c", probe, str(installed), release["build_id"]],
                            text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.splitlines()[0])
    assert report["state"] == "verified" and report["build_id"] == release["build_id"]
    (installed / "bili_asr" / "workflow.py").write_text("raise RuntimeError('unexpected disk drift')\n")
    result = subprocess.run([sys.executable, "-I", "-c", probe, str(installed), release["build_id"]],
                            text=True, capture_output=True)
    assert result.returncode != 0 and "disk_drift" in result.stderr
