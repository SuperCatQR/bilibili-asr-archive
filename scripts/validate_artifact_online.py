"""Bounded isolated POSIX soak; no network, real media, or production roots.

Run from a development checkout with PYTHONPATH=src:. and pytest installed.
Every archive is created in a TemporaryDirectory. There is deliberately no
archive-root or target-root option. JSON is printed to stdout.
"""

import argparse
import hashlib
import json
import multiprocessing as mp
import os
import resource
import subprocess
import tempfile
import time
from collections import Counter
from pathlib import Path

from bili_asr.archive_maintenance import ArchiveBusyError
from bili_asr.archive_session import ArchiveAccessMode, ArchiveSession
from bili_asr.artifact_root import ArtifactRoots
from bili_asr.services.artifact_consumer import ensure_local
from bili_asr.services.artifact_coordination import consumer_pin
from bili_asr.services.artifact_inventory_service import (
    ArtifactSelection,
    inventory_artifacts,
    plan_artifact_offload,
)
from bili_asr.services.artifact_io import artifact_io_budget
from bili_asr.services.artifact_policy import run_policy_once
from bili_asr.services.artifact_transfer import transfer_artifacts
from bili_asr.services.workflow_audio_access import retained_audio
from bili_asr.storage.artifact_catalog import ArtifactCatalog
from bili_asr.storage.artifact_online import install_online_in_staged_copy
from tests.support.artifact_online import configure
from tests.test_artifact_transfer import archive as audio_fixture
from tests.test_artifact_transfer import domain_facts

MIB = 1024**2
RATE = 32 * MIB


def fixture(parent, size):
    parent.mkdir()
    archive = audio_fixture.__wrapped__(parent)
    archive.data = bytes(range(256)) * (size // 256)
    archive.digest = hashlib.sha256(archive.data).hexdigest()
    (archive.root / "audio/input.m4a").write_bytes(archive.data)
    with ArchiveSession(archive.root, mode=ArchiveAccessMode.WRITE) as session:
        with session.connection:
            session.connection.execute(
                "UPDATE audio_objects SET sha256=?,byte_size=? WHERE audio_id=1",
                (archive.digest, len(archive.data)),
            )
        install_online_in_staged_copy(session.connection)
        with session.connection:
            catalog = ArtifactCatalog(session.connection)
            catalog.register_object(archive.digest, len(archive.data))
            catalog.bind_audio(1, archive.digest)
    return archive


def check(path, expected):
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    assert digest == expected, (digest, expected)


def plan(roots, metrics):
    progress = {}
    started = time.monotonic()
    inventory = inventory_artifacts(
        roots.archive_root / "archive.db",
        roots,
        deep=True,
        selection=ArtifactSelection(kinds=("audio",)),
        external_holds={},
        progress=lambda event: progress.update({event["path"]: event["bytes_read"]}),
        max_bytes_per_second=RATE,
    )
    metrics["scan_bytes"] += sum(progress.values())
    metrics["scan_seconds"] += time.monotonic() - started
    return plan_artifact_offload(inventory, target_id="cold")


def reader(root, target, identity, size, start, queue, index):
    metrics = {
        "role": "reader",
        "index": index,
        "reads": 0,
        "busy": 0,
        "corrupt_reads": 0,
        "read_bytes": 0,
    }
    roots = ArtifactRoots.of(root)
    try:
        start.wait(20)
        with ArchiveSession(root, mode=ArchiveAccessMode.WRITE) as session:
            for _ in range(160):
                try:
                    with consumer_pin(
                        session.connection,
                        roots,
                        identity,
                        owner=f"soak-reader-{index}",
                    ):
                        path = ensure_local(
                            session.connection,
                            roots,
                            retained_audio(session.connection, 1),
                            storage_targets={"cold": target},
                        )
                        check(path, identity)
                        metrics["reads"] += 1
                        metrics["read_bytes"] += size
                        time.sleep(0.005)
                except ArchiveBusyError:
                    metrics["busy"] += 1
                time.sleep(0.025)
    except Exception as error:  # noqa: BLE001 - parent asserts every child result has no error.
        metrics["error"] = type(error).__name__ + ":" + str(error)
    metrics["peak_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    queue.put(metrics)


def migrator(root, target, identity, start, queue, index):
    roots = ArtifactRoots.of(root)
    metrics = {
        "role": "migrator",
        "index": index,
        "cycles": 0,
        "busy": 0,
        "released_bytes": 0,
        "scan_bytes": 0,
        "scan_seconds": 0.0,
        "io_bytes": 0,
        "io_seconds": 0.0,
    }
    reasons = Counter()
    try:
        start.wait(20)
        deadline = time.monotonic() + 75
        while metrics["cycles"] < 6 and time.monotonic() < deadline:
            try:
                frozen = plan(roots, metrics)
                if not frozen["items"]:
                    reasons["no_candidate_or_live_pin"] += 1
                    time.sleep(0.02)
                    continue
                with artifact_io_budget(RATE) as meter:
                    result = transfer_artifacts(
                        roots,
                        frozen,
                        target_root=target,
                        mode="offload",
                        external_holds={},
                        _online=True,
                    )
                metrics["io_bytes"] += meter.bytes_read
                metrics["io_seconds"] += meter.report()["elapsed_seconds"]
                metrics["released_bytes"] += result["released_bytes_this_run"]
                if result["released_bytes_this_run"]:
                    metrics["cycles"] += 1
            except ArchiveBusyError:
                metrics["busy"] += 1
            except ValueError as error:
                # A plan observed before the competing reader/restorer is stale.
                if not str(error).startswith(
                    (
                        "plan source changed or acquired a retention guard:",
                        "selected audio is pinned",
                        "release acquired a retention guard after isolation",
                    )
                ):
                    raise
                reasons[str(error)[:180]] += 1
            while time.monotonic() < deadline:
                try:
                    with (
                        ArchiveSession(root, mode=ArchiveAccessMode.WRITE) as session,
                        consumer_pin(
                            session.connection,
                            roots,
                            identity,
                            owner=f"soak-restore-{index}",
                        ),
                    ):
                        path = ensure_local(
                            session.connection,
                            roots,
                            retained_audio(session.connection, 1),
                            storage_targets={"cold": target},
                        )
                        check(path, identity)
                    break
                except ArchiveBusyError:
                    metrics["busy"] += 1
                    time.sleep(0.02)
        assert metrics["cycles"] == 6, metrics
    except Exception as error:  # noqa: BLE001 - parent asserts every child result has no error.
        metrics["error"] = type(error).__name__ + ":" + str(error)
    metrics["observations"] = dict(reasons)
    metrics["peak_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    queue.put(metrics)


def rss_kib(pids):
    result = 0
    for pid in pids:
        try:
            for line in Path(f"/proc/{pid}/status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    result += int(line.split()[1])
        except FileNotFoundError:
            pass
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-revision",
        help="Verified source revision when Git is unavailable (for example a Windows worktree in WSL).",
    )
    options = parser.parse_args()
    source_head = (
        options.source_revision
        or subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            text=True,
            capture_output=True,
            cwd=Path(__file__).resolve().parents[1],
        ).stdout.strip()
    )
    start_time = time.monotonic()
    context = mp.get_context("spawn")
    processes = []
    with tempfile.TemporaryDirectory(
        prefix="artifact-online-soak-extended-"
    ) as temporary:
        base = Path(temporary)
        archive = fixture(base / "concurrent", 4 * MIB)
        before = domain_facts(archive)
        initial = {"scan_bytes": 0, "scan_seconds": 0.0}
        transfer_artifacts(
            archive.roots,
            plan(archive.roots, initial),
            target_root=archive.target,
            mode="copy",
            external_holds={},
        )
        queue = context.Queue()
        start = context.Event()
        try:
            for index in range(2):
                processes.append(
                    context.Process(
                        target=reader,
                        args=(
                            archive.root,
                            archive.target,
                            archive.digest,
                            len(archive.data),
                            start,
                            queue,
                            index,
                        ),
                    )
                )
                processes.append(
                    context.Process(
                        target=migrator,
                        args=(
                            archive.root,
                            archive.target,
                            archive.digest,
                            start,
                            queue,
                            index,
                        ),
                    )
                )
            for process in processes:
                process.start()
            start.set()
            peak = 0
            deadline = time.monotonic() + 90
            while (
                any(process.is_alive() for process in processes)
                and time.monotonic() < deadline
            ):
                peak = max(
                    peak,
                    rss_kib([os.getpid()] + [process.pid for process in processes]),
                )
                time.sleep(0.02)
            for process in processes:
                process.join(1)
                assert not process.is_alive() and process.exitcode == 0
            results = [queue.get(timeout=5) for _ in processes]
            assert all("error" not in result for result in results), results
            assert all(
                result["reads"] > 0 for result in results if result["role"] == "reader"
            ), results
            assert domain_facts(archive) == before
            check(archive.root / "audio/input.m4a", archive.digest)
            concurrency_seconds = time.monotonic() - start_time
            # Separate real rate measurement avoids inferring throughput from tiny fixtures.
            measured = fixture(base / "measured", 16 * MIB)
            measured_before = domain_facts(measured)
            configure(measured, mode="copy", bytes_per_second=RATE)
            copied = run_policy_once(
                measured.roots, target_root=measured.target, external_holds={}
            )
            assert copied["state"] == "complete" and copied["released_bytes"] == 0, (
                copied
            )
            configure(measured, mode="offload", bytes_per_second=RATE)
            offloaded = run_policy_once(
                measured.roots, target_root=measured.target, external_holds={}
            )
            assert (
                offloaded["state"] == "complete"
                and offloaded["released_bytes"] == 16 * MIB
            ), offloaded
            assert domain_facts(measured) == measured_before
            for result in (copied, offloaded):
                assert (
                    result["io"]["elapsed_seconds"]
                    >= result["io"]["bytes_read"] / RATE * 0.98
                )
            report = {
                "schema": "isolated-artifact-online-soak/v1",
                "source_head": source_head,
                "platform": "WSL Linux POSIX flock; temporary local filesystem",
                "fixture_object_bytes": 4 * MIB,
                "rate_bytes_per_second_per_process": RATE,
                "concurrent_processes": 4,
                "workers": results,
                "concurrency_seconds": concurrency_seconds,
                "total_seconds": time.monotonic() - start_time,
                "aggregate_peak_sampled_rss_kib": peak,
                "aggregate_rss_sample_interval_seconds": 0.02,
                "authority_unchanged": True,
                "source_sha256_exact": True,
                "policy_measurements": {
                    mode: {
                        key: result.get(key)
                        for key in ("state", "scan", "io", "released_bytes")
                    }
                    for mode, result in [("copy", copied), ("offload", offloaded)]
                },
                "limitations": [
                    "Bounded 12-cycle soak, not a production-duration or large-catalog benchmark.",
                    "RSS is sampled aggregate; each worker also records ru_maxrss.",
                    "Transfer meter measures repeated payload reads, not device writes or wall-clock free-space gain.",
                    "Windows native online release semantics were not executed.",
                ],
            }
            print(json.dumps(report, indent=2))
        finally:
            for process in processes:
                if process.is_alive():
                    process.kill()
                    process.join(5)
