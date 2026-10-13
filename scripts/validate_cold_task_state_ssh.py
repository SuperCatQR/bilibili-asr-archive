"""Exercise cold task-state references over real, isolated Linux OpenSSH.

Run with the project installed (including its remote extra), or PYTHONPATH=src.
Only a newly created TemporaryDirectory is used for archives, targets, server
configuration, authorized keys and host/client keys. No existing SSH credentials
or server configuration are read. Exit codes: 0 passed, 1 failed, 2 unsupported.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import traceback
import zipfile
from contextlib import closing, contextmanager
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch


class UnsupportedEnvironment(RuntimeError):
    """The host cannot start the dedicated server without changing system state."""


def require(condition: bool, explanation: str) -> None:
    if not condition:
        raise AssertionError(explanation)


def command(arguments: list[str]) -> None:
    completed = subprocess.run(arguments, capture_output=True, text=True, timeout=15, check=False)
    if completed.returncode:
        raise UnsupportedEnvironment(completed.stderr.strip()[-2000:] or "SSH setup command failed")


@contextmanager
def isolated_sshd(directory: Path):
    """Start only our process group, with only our keys and loopback listener."""
    import pwd

    executable = shutil.which("sshd")
    if executable is None and Path("/usr/sbin/sshd").is_file():
        executable = "/usr/sbin/sshd"
    keygen = shutil.which("ssh-keygen")
    if not executable or not keygen:
        raise UnsupportedEnvironment("OpenSSH sshd and ssh-keygen are required")
    username = pwd.getpwuid(os.geteuid()).pw_name
    if any(character.isspace() for character in username):
        raise UnsupportedEnvironment("current account name cannot be used in isolated sshd configuration")
    directory.mkdir(mode=0o700)
    host_key, client_key = directory / "host-key", directory / "client-key"
    for key in (host_key, client_key):
        command([keygen, "-q", "-t", "ed25519", "-N", "", "-f", str(key)])
        key.chmod(0o600)
    authorized_keys = directory / "authorized_keys"
    authorized_keys.write_bytes(client_key.with_suffix(".pub").read_bytes())
    authorized_keys.chmod(0o600)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    configuration = directory / "sshd_config"
    configuration.write_text("\n".join([
        f"Port {port}", "ListenAddress 127.0.0.1", "AddressFamily inet",
        f'HostKey "{host_key}"', f'PidFile "{directory / "sshd.pid"}"',
        f'AuthorizedKeysFile "{authorized_keys}"', f"AllowUsers {username}",
        "StrictModes yes", "PubkeyAuthentication yes", "PasswordAuthentication no",
        "KbdInteractiveAuthentication no", "UsePAM no", "PermitRootLogin prohibit-password",
        "PermitEmptyPasswords no", "AllowTcpForwarding no", "AllowAgentForwarding no",
        "X11Forwarding no", "PermitTunnel no", "PermitUserEnvironment no", "PermitUserRC no", "PrintMotd no",
        "LogLevel ERROR", "",
    ]), encoding="utf-8")
    command([executable, "-t", "-f", str(configuration)])
    host_kind, host_public, *_ = host_key.with_suffix(".pub").read_text().split()
    known_hosts = directory / "known_hosts"
    known_hosts.write_text(f"[127.0.0.1]:{port} {host_kind} {host_public}\n", encoding="ascii")
    with (directory / "sshd.log").open("wb") as log:
        process = subprocess.Popen([executable, "-D", "-e", "-f", str(configuration)],
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                   close_fds=True, start_new_session=True)
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise UnsupportedEnvironment((directory / "sshd.log").read_text()[-2000:])
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        break
                except OSError:
                    time.sleep(0.05)
            else:
                raise UnsupportedEnvironment("isolated loopback sshd did not become ready")
            yield username, port, client_key, known_hosts
        finally:
            # The group was created by this Popen, never found by a process-name scan.
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)


@contextmanager
def isolated_client_authentication(binding):
    """Keep the actual Paramiko transport while disabling ambient discovery."""
    import paramiko

    original_connect = paramiko.SSHClient.connect

    def connect(client, hostname, **options):
        require(hostname == "127.0.0.1" and options.get("port") == binding.port,
                "acceptance connection escaped its dedicated loopback endpoint")
        require(options.get("key_filename") == binding.key_filename and options.get("password") is None,
                "acceptance connection attempted another credential")
        options.update(allow_agent=False, look_for_keys=False)
        return original_connect(client, hostname, **options)

    with patch.object(paramiko.SSHClient, "load_system_host_keys", lambda _client: None), \
            patch.object(paramiko.SSHClient, "connect", connect):
        yield


def create_archive(parent: Path) -> tuple[Path, Path, bytes, str]:
    from bili_asr.artifact_root import ArtifactRoots
    from bili_asr.storage.artifact_catalog import ArtifactCatalog
    from bili_asr.storage.artifact_online import install_online_in_staged_copy
    from bili_asr.storage.database import initialize_schema
    from bili_asr.storage.schema_contract import schema_resource
    from bili_asr.storage_targets import bind_directory_target

    root, target = parent / "archive", parent / "local-cold"
    root.mkdir()
    target.mkdir()
    audio = b"retained sound"
    digest = hashlib.sha256(audio).hexdigest()
    with closing(sqlite3.connect(root / "archive.db")) as connection:
        connection.row_factory = sqlite3.Row
        initialize_schema(connection)
        with connection:
            connection.execute("INSERT INTO bilibili_users VALUES (1,'creator',1,1)")
            connection.execute("INSERT INTO videos VALUES ('BVTEST',1,1,'video',1,1,1)")
            connection.execute("INSERT INTO video_parts VALUES (1,'BVTEST',0,1,'part',1000,'discovered',1,1)")
            connection.execute("INSERT INTO audio_objects VALUES (1,?,?,'m4a',1000,'audio/input.m4a',1)",
                               (digest, len(audio)))
            connection.execute("INSERT INTO part_audio_objects VALUES (1,1,1,'acceptance')")
        connection.executescript(schema_resource("schema-artifact-storage.sql"))
        install_online_in_staged_copy(connection)
        with connection:
            catalog = ArtifactCatalog(connection)
            catalog.register_object(digest, len(audio))
            catalog.bind_audio(1, digest)
    (root / "audio").mkdir()
    (root / "audio/input.m4a").write_bytes(audio)
    bind_directory_target(target, "cold", roots=ArtifactRoots.of(root))
    return root, target, audio, digest


def offload_audio(root: Path, target: Path, audio: bytes) -> dict:
    from bili_asr.archive_session import ArchiveAccessMode, ArchiveSession
    from bili_asr.artifact_root import ArtifactRoots
    from bili_asr.services.artifact_policy import configure_policy, run_policy_once
    from bili_asr.services.audio_retention_policy import default_audio_retention_policy

    configuration = default_audio_retention_policy()
    configuration.update(mode="offload", target_id="cold", minimum_age_seconds=0,
                         local_retention_seconds=0, trigger_free_bytes=0, stop_free_bytes=1,
                         minimum_free_bytes=0, bytes_per_second=0, allow_delete=True)
    with ArchiveSession(root, mode=ArchiveAccessMode.WRITE) as session:
        configure_policy(session.connection, "audio", configuration)
    result = run_policy_once(ArtifactRoots.of(root), policy_id="audio", target_root=target, external_holds={})
    require(result["state"] == "complete" and result["released_bytes"] == len(audio),
            "explicit, verified audio offload did not release the original bytes")
    require(result["delete_authorized"] and not (root / "audio/input.m4a").exists(),
            "offload did not preserve explicit deletion authorization")
    return result


def seed_failed_evidence(root: Path, parent: Path, digest: str) -> tuple[dict, bytes]:
    with closing(sqlite3.connect(root / "archive.db")) as connection, connection:
        connection.execute("INSERT INTO workflow_asr_profiles VALUES (1,'acceptance','model','revision',"
                           "'aligner','cpu',NULL,?,1)", ("1" * 64,))
        for identity, status in (("failed-asr", "failed"), ("queued-asr", "queued")):
            connection.execute("INSERT INTO workflow_jobs(job_id,kind,video_part_id,profile_id,dedupe_key,"
                               "payload_json,status,available_at,created_at,updated_at) "
                               "VALUES (?,'asr',1,1,?,'{}',?,1,1,1)", (identity, identity, status))
        connection.execute("INSERT INTO workflow_attempts VALUES ('failed-attempt','failed-asr','worker',"
                           "1,2,'failed',NULL,?)",
                           (json.dumps({"storage_key": "audio/input.m4a", "sha256": digest}),))
    controls = parent / "controls"
    controls.mkdir()
    control = controls / "retry.json"
    raw = (json.dumps({"format": "retry-control/v1", "schema_version": 1,
           "retry_holds": {"failed-asr": {"reason": "keep failed audio investigation"}},
           "retry_ledger": {"failed-asr": {"retries": 3, "max_retries": 3, "last_retry_at": 100,
             "next_retry_at": 200, "last_error_code": "timeout", "dispatch_outcome": "reserved"}}},
           ensure_ascii=False, indent=3) + "\n").encode("utf-8")
    control.write_bytes(raw)
    return {"kind": "retry-control/v1", "path": str(control), "lock_path": str(controls / "retry.lock")}, raw


def capture_over_ssh(parent: Path, binding, progress: dict) -> tuple[Path, dict, list, bytes]:
    from bili_asr.artifact_root import ArtifactRoots
    from bili_asr.remote_storage import SSHDirectoryBackend
    from bili_asr.services import maintenance_backup as backup
    from bili_asr.services import maintenance_task_state as state
    from bili_asr.services.remote_artifacts import push_remote_package
    from bili_asr.storage.maintenance_selection import table_ledger

    progress["stage"] = "create-isolated-archive"
    root, local_target, audio, digest = create_archive(parent)
    progress["stage"] = "explicit-local-audio-offload"
    offload = offload_audio(root, local_target, audio)
    package = next(local_target.glob("packages/*.zip"))
    # The production prepare contract writes a marker into an existing root;
    # it deliberately cannot create a missing mount or target directory.
    progress["stage"] = "create-isolated-remote-root"
    remote_root = Path(binding.root)
    require(remote_root == parent / "remote-cold", "remote fixture root escaped its private parent")
    remote_root.mkdir(mode=0o700)
    progress["stage"] = "ssh-connect-for-prepare"
    with SSHDirectoryBackend(binding) as preparer:
        progress["stage"] = "ssh-prepare-existing-root"
        prepared = preparer.prepare()
    bound = replace(binding, instance_id=prepared["instance_id"])
    progress["stage"] = "ssh-connect-bound-instance"
    with SSHDirectoryBackend(bound) as backend:
        progress["stage"] = "ssh-package-upload-and-client-readback"
        upload = push_remote_package(ArtifactRoots.of(root), package, backend)
        progress["stage"] = "ssh-probe-bound-instance"
        probe = backend.probe()
        require(probe["instance_id"] == bound.instance_id, "SSH target instance did not match preparation")
        # Only the real SSH copy can satisfy capture after this removal.
        progress["stage"] = "remove-local-cold-copy-and-seed-failed-evidence"
        shutil.rmtree(local_target)
        component, raw_control = seed_failed_evidence(root, parent, digest)
        ledger = table_ledger(root / "archive.db")
        document = backup.policy(root, parent / "repository", mode="full", profile="task-state",
                                 media_policy="verified-references", external_components=[component])
        progress["stage"] = "automatic-task-state-v2-ssh-capture"
        result = backup.run_backup(document, trigger="time", remote_backends={bound.target_id: backend})
        require(result.get("valid") is True, f"automatic SSH state capture failed: {result.get('error')}")
        snapshot = Path(document["repository"]) / result["snapshot"]
        progress["stage"] = "verify-captured-reference-and-uncompressed-ledger"
        manifest = state.verify_task_state(snapshot)["manifest"]
        require(manifest["format"] == state.REFERENCE_FORMAT, "capture did not use explicit task-state v2")
        require(len(manifest["media_dependencies"]) == 1, "unexpected media dependency set")
        reference = manifest["media_dependencies"][0]
        require((reference["path"], reference["sha256"], reference["size"], reference["available"])
                == ("audio/input.m4a", digest, len(audio), False), "original cold identity changed")
        replica = reference["replicas"][0]
        require((replica["backend"], replica["target_id"], replica["instance_id"], replica["generation"])
                == ("ssh-directory/v1", bound.target_id, bound.instance_id, 1), "SSH reference binding changed")
        require(replica["package_id"] == upload["package_id"], "reference selected another package")
        with zipfile.ZipFile(snapshot) as bundle:
            require(all(member.compress_type == zipfile.ZIP_STORED for member in bundle.infolist()),
                    "task ledger was compressed")
            require(not any(member.filename.startswith("audio/") for member in bundle.infolist()),
                    "state capture embedded or restored cold audio")
            require(bundle.read("control-state/component-0.json") == raw_control, "retry control bytes changed")
        # Corruption is read through real SSH; failure must publish no partial state.
        progress["stage"] = "corrupt-isolated-ssh-package"
        remote_package = Path(bound.root) / replica["relative_key"]
        with remote_package.open("r+b") as stream:
            stream.write(b"BAD!")
        rejected = parent / "corrupt-state.zip"
        progress["stage"] = "reject-corrupt-package-over-real-ssh"
        try:
            state.save_task_state(root, rejected, no_external_control_state=True,
                                  media_policy="verified-references", remote_backends={bound.target_id: backend})
        except ValueError as error:
            require("currently verified replica" in str(error), "corruption failed for an unrelated reason")
        else:
            raise AssertionError("corrupted real SSH replica was accepted")
        require(not rejected.exists(), "failed SSH verification left a published snapshot")
        require(table_ledger(root / "archive.db") == ledger, "capture changed original task/catalog ledger")
        require(not (root / "audio/input.m4a").exists(), "capture silently restored cold audio")
    facts = {"transport": "real-paramiko-openssh-loopback", "backend": "ssh-directory/v1",
             "source_release_bytes": offload["released_bytes"], "original_sha256": digest,
             "instance_id": bound.instance_id, "package_id": replica["package_id"],
             "package_sha256": replica["package_sha256"], "replica_generation": replica["generation"],
             "content_id": manifest["content_id"], "corrupt_remote_replica_rejected": True,
             "task_ledger_uncompressed": True, "ambient_credentials_disabled": True,
             "remote_root_precreated": True, "remote_agent_requires_project_pythonpath": False}
    return snapshot, facts, ledger, raw_control


def offline_read(parent: Path, snapshot: Path, ledger: list, raw_control: bytes, progress: dict) -> dict:
    from bili_asr.remote_storage import SSHDirectoryBackend
    from bili_asr.services import maintenance_task_state as state
    from bili_asr.services.maintenance_state_reader import (
        read_task_records,
        read_task_state,
    )
    from bili_asr.storage.maintenance_selection import table_ledger

    progress["stage"] = "remove-isolated-source-and-remote-target"
    shutil.rmtree(parent / "archive")
    shutil.rmtree(parent / "remote-cold")
    with patch.object(SSHDirectoryBackend, "__enter__", side_effect=AssertionError("offline read attempted SSH")):
        progress["stage"] = "offline-task-state-check"
        verified = state.verify_task_state(snapshot)
        progress["stage"] = "offline-task-and-attempt-read"
        report = read_task_state(snapshot)
        attempts = read_task_records(snapshot, "workflow_attempts")
        stage = parent / "detached-evidence"
        stage.mkdir()
        progress["stage"] = "offline-detached-evidence-extract"
        state.extract_task_state(snapshot, stage)
    progress["stage"] = "compare-offline-status-controls-and-all-table-ledgers"
    require(verified["valid"] and report["valid"], "offline state verification failed")
    require({row["values"]["job_id"]: row["values"]["status"] for row in report["jobs"]}
            == {"failed-asr": "failed", "queued-asr": "queued"}, "offline reader changed job state")
    require(attempts["records"][0]["values"]["outcome"] == "failed", "failed attempt was lost")
    require(any(base64.b64decode(record["base64"]) == raw_control for record in report["control_records"]),
            "hold or exhausted retry budget changed")
    require(table_ledger(stage / "archive.db") == ledger, "detached task ledger differs from capture")
    require(not (stage / "audio").exists(), "offline extraction restored original media")
    require(report["external_audio_references"] == 1 and report["media_restored"] is False
            and report["media_restore_required"] is True and report["external_media_verified_now"] is False,
            "offline report claimed current media verification or restoration")
    return {"source_and_cold_target_removed": True, "sshd_stopped_before_offline_reads": True,
            "offline_state_read": True, "offline_detached_extract": True, "failed_attempt_preserved": True,
            "retry_hold_and_budget_bytes_preserved": True, "all_table_ledgers_preserved": True,
            "media_restored": False, "media_restore_required": True, "external_audio_references": 1,
            "external_media_verified_now": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-directory", type=Path, help="existing temporary validation parent")
    options = parser.parse_args()
    started = time.monotonic()
    progress = {"stage": "environment-check"}
    try:
        if not sys.platform.startswith("linux"):
            raise UnsupportedEnvironment("the actual SSH storage backend requires a Linux OpenSSH server")
        try:
            import paramiko  # noqa: F401
        except ImportError:
            raise UnsupportedEnvironment("install the project's remote extra (Paramiko)") from None
        from bili_asr.remote_storage import SSHBinding

        if options.work_directory is not None:
            require(options.work_directory.is_absolute() and options.work_directory.is_dir()
                    and not options.work_directory.is_symlink(), "work-directory must be an existing absolute directory")
        with tempfile.TemporaryDirectory(prefix="bili-cold-state-ssh-", dir=options.work_directory) as temporary:
            parent = Path(temporary).resolve()
            progress["stage"] = "start-isolated-loopback-sshd"
            with isolated_sshd(parent / "ssh") as (username, port, key, known_hosts):
                binding = SSHBinding(target_id="ssh-cold-acceptance", instance_id=None, host="127.0.0.1",
                                     root=str(parent / "remote-cold"), username=username, port=port,
                                     key_filename=str(key), known_hosts=str(known_hosts),
                                     python_executable=sys.executable, timeout=15)
                with isolated_client_authentication(binding):
                    snapshot, facts, ledger, raw_control = capture_over_ssh(parent, binding, progress)
                progress["stage"] = "stop-isolated-sshd"
            facts.update(offline_read(parent, snapshot, ledger, raw_control, progress))
            progress["stage"] = "remove-isolated-directories-and-keys"
        result, exit_code = {"status": "passed", "valid": True, "checks": facts,
                             "temporary_server_keys_and_directories_removed": True}, 0
    except UnsupportedEnvironment as error:
        result, exit_code = {"status": "unsupported", "valid": False, "reason": str(error),
                             "failure_stage": progress["stage"]}, 2
    except Exception as error:  # noqa: BLE001 - emit a machine-readable standalone failure
        result, exit_code = {"status": "failed", "valid": False,
                             "error_type": type(error).__name__, "reason": str(error),
                             "failure_stage": progress["stage"],
                             # Frame source and exception text only; no locals,
                             # binding values, configuration or private keys.
                             "traceback": "".join(traceback.format_exception(error, limit=20))}, 1
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
