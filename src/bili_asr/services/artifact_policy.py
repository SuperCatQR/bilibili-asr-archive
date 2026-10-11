"""Explicit, bounded online policy runs using the shared inventory and executor."""
from __future__ import annotations

import json
import shutil
import sqlite3
import time
import uuid
from contextlib import ExitStack, contextmanager
from dataclasses import asdict

from bili_asr.archive_maintenance import ArchiveBusyError
from bili_asr.archive_session import ArchiveAccessMode, ArchiveSession
from bili_asr.canonical_json import digest
from bili_asr.services.artifact_coordination import (
    reconcile_consumer_pins,
    reserve_local_space,
    resource_fence,
)
from bili_asr.services.artifact_inventory_service import (
    ArtifactSelection,
    inventory_artifacts,
    plan_artifact_offload,
)
from bili_asr.services.artifact_io import artifact_io_budget
from bili_asr.services.artifact_transfer import transfer_artifacts
from bili_asr.storage.artifact_catalog import ArtifactCatalog
from bili_asr.storage.artifact_online import require_artifact_online

DEFAULT_POLICY = {
    "version": 1, "mode": "off", "target_id": None,
    "selection": asdict(ArtifactSelection()), "minimum_age_seconds": 86400,
    "trigger_free_bytes": 10 * 1024**3, "stop_free_bytes": 20 * 1024**3,
    "minimum_free_bytes": 1024**3, "batch_bytes": 1024**3, "batch_objects": 100,
    "max_concurrency": 1, "bytes_per_second": 16 * 1024**2,
    "scan_interval_seconds": 60, "backoff_seconds": 300,
    "priority": "oldest", "download_bytes_per_second": 256000,
    "download_workspace_multiplier": 3,
}


def validate_policy(value):
    from bili_asr.contracts.json_schema import validate_json
    try:
        value = json.loads(json.dumps(value))
    except (TypeError, ValueError) as error:
        raise ValueError("artifact policy must be a JSON value") from error
    validate_json("artifact-policy-v1", value)
    if (value["backoff_seconds"] < value["scan_interval_seconds"]
            or value["trigger_free_bytes"] >= value["stop_free_bytes"]
            or value["minimum_free_bytes"] > value["trigger_free_bytes"]):
        raise ValueError("invalid artifact policy bounds or watermarks")
    if value["mode"] != "off" and value["target_id"] is None:
        raise ValueError("enabled artifact policy requires a target identity")
    return value



def configure_policy(connection, policy_id: str, configuration: dict):
    require_artifact_online(connection, required=True)
    config = validate_policy(configuration)
    catalog = ArtifactCatalog(connection)
    if not isinstance(policy_id, str) or not policy_id or len(policy_id) > 128:
        raise ValueError("policy identity must be bounded nonempty text")
    with connection:
        if config["target_id"] is not None:
            catalog.register_target(config["target_id"])
        connection.execute("INSERT INTO artifact_policies VALUES (?,?,?,?,?) ON CONFLICT(policy_id) DO UPDATE SET mode=excluded.mode,target_id=excluded.target_id,config_json=excluded.config_json,updated_at=excluded.updated_at",
                           (policy_id, config["mode"], config["target_id"], json.dumps(config, sort_keys=True), int(time.time())))
    return {"policy_id": policy_id, "policy_sha256": digest(config), "configuration": config}


def read_policy(connection, policy_id="default"):
    require_artifact_online(connection, required=True)
    row = connection.execute("SELECT config_json FROM artifact_policies WHERE policy_id=?", (policy_id,)).fetchone()
    return validate_policy(json.loads(row[0]) if row else DEFAULT_POLICY)


def minimum_free_space(connection):
    return max((validate_policy(json.loads(row[0]))["minimum_free_bytes"] for row in connection.execute(
        "SELECT config_json FROM artifact_policies WHERE mode!='off'")), default=0)


@contextmanager
def download_reservation(connection, roots, part_id, *, owner):
    policies = [validate_policy(json.loads(row[0])) for row in connection.execute("SELECT config_json FROM artifact_policies WHERE mode!='off'")]
    if not policies:
        yield
        return
    duration = connection.execute("SELECT duration_ms FROM video_parts WHERE video_part_id=?", (part_id,)).fetchone()
    if duration is None or duration[0] <= 0:
        raise ValueError("artifact_download_backpressure: unknown input duration")
    floor = max(policy["minimum_free_bytes"] for policy in policies)
    if any(shutil.disk_usage(roots.write_base).free < policy["trigger_free_bytes"] for policy in policies):
        raise ValueError("artifact_download_backpressure: storage pressure requires verified release first")
    needed = max((duration[0] * policy["download_bytes_per_second"] + 999) // 1000 * policy["download_workspace_multiplier"] for policy in policies)
    with reserve_local_space(connection, roots, needed, owner="download:" + owner, minimum_free_bytes=floor):
        yield


def _bounded_plan(inventory, config):
    # Freeze complete connected groups; sharing one object joins their members.
    candidates = {copy["copy_id"]: copy for copy in inventory["copies"] if copy["candidate"]}
    membership = {}
    for obj in inventory["objects"]:
        groups = {ref["group_id"] for ref in obj["references"]}
        for copy_id in obj["copies"]:
            if copy_id in candidates:
                membership.setdefault(copy_id, set()).update(groups)
    components = []
    remaining = set(candidates)
    while remaining:
        current = {remaining.pop()}
        groups = set(membership.get(next(iter(current)), ()))
        while True:
            adjacent = {key for key in remaining if membership.get(key, set()) & groups}
            if not adjacent:
                break
            current.update(adjacent)
            remaining.difference_update(adjacent)
            for key in adjacent:
                groups.update(membership.get(key, ()))
        copies = [candidates[key] for key in current]
        if any(copy["fingerprint"][3] / 1e9 > time.time() - config["minimum_age_seconds"] for copy in copies):
            continue
        components.append(copies)
    components.sort(key=lambda copies: (-sum(copy["size"] for copy in copies) if config["priority"] == "largest"
                                      else min(copy["fingerprint"][3] for copy in copies)))
    selected, total, objects = set(), 0, set()
    for copies in components:
        incoming = {copy["sha256"]: copy["size"] for copy in copies}
        added = sum(size for identity, size in incoming.items() if identity not in objects)
        if total + added > config["batch_bytes"] or len(objects | incoming.keys()) > config["batch_objects"]:
            continue
        selected.update(copy["copy_id"] for copy in copies)
        total += added
        objects.update(incoming)
    filtered = {**inventory, "copies": [{**copy, "selected": copy["copy_id"] in selected} for copy in inventory["copies"]]}
    physical = {copy["physical_id"]: copy["size"] for copy in candidates.values() if copy["copy_id"] in selected}
    filtered["summary"] = {**inventory["summary"], "reclaimable_content_bytes": sum(physical.values()),
        "target_payload_bytes": total, "restore_workspace_bytes": max((copy["size"] for copy in candidates.values() if copy["copy_id"] in selected), default=0)}
    return plan_artifact_offload(filtered, target_id=config["target_id"])


def run_policy_once(roots, *, policy_id="default", target_root=None, external_holds=None):
    """Run at most one frozen batch; callers may poll using the returned deadline."""
    with ArchiveSession(roots.archive_root, mode=ArchiveAccessMode.WRITE, artifact_roots=roots) as session:
        connection = session.connection
        require_artifact_online(connection, required=True)
        config = read_policy(connection, policy_id)
        if config["mode"] == "off":
            return {"state": "off", "policy_id": policy_id, "released_bytes": 0}
        with ExitStack() as resources:
            for lane in range(config["max_concurrency"]):
                try:
                    resources.enter_context(resource_fence(roots, f"policy:{policy_id}:{lane}", exclusive=True))
                    break
                except ArchiveBusyError:
                    continue
            else:
                return {"state": "busy", "policy_id": policy_id, "released_bytes": 0}
            now = int(time.time())
            prior = connection.execute("SELECT * FROM artifact_policy_runs WHERE policy_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1", (policy_id,)).fetchone()
            if prior is not None and prior["policy_sha256"] == digest(config) and prior["retry_after"] > now:
                return {"state": "backoff", "policy_id": policy_id, "retry_after": prior["retry_after"], "released_bytes": 0}
            resume = (prior is not None and prior["policy_sha256"] == digest(config)
                      and prior["state"] in {"running", "failed"} and prior["plan_json"] is not None
                      and bool(json.loads(prior["plan_json"])["items"]))
            free = shutil.disk_usage(roots.write_base).free
            pressure = free < config["trigger_free_bytes"] or (prior is not None and prior["result_json"] is not None
                and json.loads(prior["result_json"]).get("pressure_active", False) and free < config["stop_free_bytes"])
            if config["mode"] == "offload" and not pressure and not resume:
                return {"state": "watermark_satisfied", "policy_id": policy_id, "free_bytes": free, "released_bytes": 0}
            frozen_hash, run_id = digest(config), uuid.uuid4().hex
            with connection:
                connection.execute("INSERT INTO artifact_policy_runs VALUES (?,?,?,?,NULL,NULL,'running',?,?,?)",
                    (run_id, policy_id, frozen_hash, json.dumps(config, sort_keys=True), now + config["scan_interval_seconds"], now, now))
            def guard():
                current = connection.execute("SELECT config_json FROM artifact_policies WHERE policy_id=?", (policy_id,)).fetchone()
                if current is None or digest(validate_policy(json.loads(current[0]))) != frozen_hash:
                    raise ValueError("artifact_policy_changed: frozen execution stopped at a safe boundary")
            report = {"policy_id": policy_id, "run_id": run_id, "policy_sha256": frozen_hash, "pressure_active": bool(pressure), "released_bytes": 0}
            try:
                reconcile_consumer_pins(connection, roots)
                measured = {"bytes_read": 0}
                def progress(event):
                    measured["bytes_read"] += event["bytes_read"] - measured.get(event["path"], 0)
                    measured[event["path"]] = event["bytes_read"]
                started = time.monotonic()
                inventory = inventory_artifacts(session.database_path, roots, deep=True,
                    selection=ArtifactSelection(**{key: tuple(values) for key, values in config["selection"].items()}),
                    external_holds=external_holds() if callable(external_holds) else external_holds,
                    progress=progress, max_bytes_per_second=config["bytes_per_second"] or None)
                plan = _bounded_plan(inventory, config)
                if resume:
                    plan = json.loads(prior["plan_json"])  # Resume the exact journaled operation.
                report["scan"] = {"bytes_read": measured["bytes_read"], "elapsed_seconds": time.monotonic() - started}
                with connection:
                    connection.execute("UPDATE artifact_policy_runs SET plan_json=? WHERE run_id=?", (json.dumps(plan, sort_keys=True), run_id))
                if not plan["items"]:
                    report.update(state="blocked", reason="no_eligible_complete_group")
                else:
                    guard()
                    if target_root is None:
                        raise ValueError("artifact_target_unbound")
                    with artifact_io_budget(config["bytes_per_second"]) as meter:
                        result = transfer_artifacts(roots, plan, target_root=target_root, mode=config["mode"], external_holds=external_holds,
                            max_bytes=config["batch_bytes"], max_objects=config["batch_objects"], _online=True, _policy_guard=guard)
                    report.update(state="complete" if result["operation"]["state"] == "complete" else "blocked",
                                  transfer=result, io=meter.report(), released_bytes=result["released_bytes_this_run"])
                    if report["state"] == "blocked":
                        report["reason"] = "release_retention_guard"
                    report["pressure_active"] = pressure and shutil.disk_usage(roots.write_base).free < config["stop_free_bytes"]
            except (ValueError, OSError, sqlite3.Error) as error:
                report.update(state="failed", reason=str(error)[:512])
            retry_after = int(time.time()) + config["scan_interval_seconds" if report["state"] == "complete" else "backoff_seconds"]
            report["retry_after"] = retry_after
            with connection:
                connection.execute("UPDATE artifact_policy_runs SET state=?,result_json=?,retry_after=?,updated_at=? WHERE run_id=?",
                    (report["state"], json.dumps(report, sort_keys=True), retry_after, int(time.time()), run_id))
            return report
