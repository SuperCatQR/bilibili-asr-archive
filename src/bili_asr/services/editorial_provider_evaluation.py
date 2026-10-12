"""Explicitly opted-in experiments with durable, bounded physical reservations."""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from typing import Any

from bili_asr.deepseek import (
    DeepSeekClient,
    DeepSeekError,
    normalize_usage,
    request_body,
)
from bili_asr.editorial import EditorialConfig, canonical, digest
from bili_asr.editorial_recovery import recovery_request
from bili_asr.services.editorial_evaluation import validation_result

MAX_CALLS = 4
MAX_OUTPUT_TOKENS = 8192
VARIANT_NAMES = ("disabled-temperature-0.2", "enabled-low")
LEDGER_TABLES = {
    "manifest": "CREATE TABLE manifest(identity TEXT PRIMARY KEY, body TEXT NOT NULL)",
    "calls": "CREATE TABLE calls(ordinal INTEGER PRIMARY KEY, variant TEXT NOT NULL, "
             "request TEXT NOT NULL, response TEXT, outcome TEXT, latency_ms INTEGER)",
}


def _validate_schema(connection):
    for name, expected in LEDGER_TABLES.items():
        row = connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
        if row is None or " ".join(row[0].upper().split()) != " ".join(expected.upper().split()):
            raise ValueError("experiment ledger schema changed")
    if connection.execute("SELECT 1 FROM sqlite_master WHERE type IN ('trigger','view')").fetchone():
        raise ValueError("experiment ledger schema changed")


def _validate_calls(connection, variant_names):
    rows = connection.execute("SELECT ordinal,variant FROM calls ORDER BY ordinal").fetchall()
    if len(rows) > MAX_CALLS or [row["ordinal"] for row in rows] != list(range(1, len(rows) + 1)):
        raise ValueError("experiment ledger ordinals or budget changed")
    counts = {name: 0 for name in variant_names}
    for row in rows:
        if row["variant"] not in counts:
            raise ValueError("experiment ledger has unknown variant")
        counts[row["variant"]] += 1
    if any(count > 2 for count in counts.values()):
        raise ValueError("experiment ledger variant budget changed")


def variants(sample: dict[str, Any], endpoint: str, model: str) -> list[tuple[str, EditorialConfig]]:
    historic = EditorialConfig.from_snapshot(sample["prepared"]["snapshot"]["config"])
    common = replace(historic, base_url=endpoint, model=model, request_policy="deepseek-v2",
                     max_chunk_regenerations=1, max_output_tokens=MAX_OUTPUT_TOKENS,
                     timeout_seconds=180, temperature=None)
    return [(VARIANT_NAMES[0], replace(common, thinking_mode="disabled", temperature=.2)),
            (VARIANT_NAMES[1], replace(common, thinking_mode="enabled", reasoning_effort="low"))]


def evaluate_provider(sample: dict[str, Any], ledger: Path, *, endpoint: str, model: str,
                      allow_paid_calls: bool, client: DeepSeekClient | None = None) -> dict[str, Any]:
    if not allow_paid_calls:
        raise ValueError("provider experiments require --allow-paid-calls")
    configs = variants(sample, endpoint, model)
    manifest = {"schema": "editorial-provider-evaluation-v1", "source_call": sample["call_id"],
                "source_request_sha256": digest(sample["request"]), "source_response_sha256": digest(sample["response"]),
                "source_chunk_sha256": digest(sample["chunk"]), "max_physical_calls": MAX_CALLS,
                "variants": {name: config.to_dict() for name, config in configs}}
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(ledger)) as connection:
        connection.row_factory = sqlite3.Row
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if tables and tables != {"manifest", "calls"}:
            raise ValueError("ledger is not a dedicated provider experiment database")
        for statement in LEDGER_TABLES.values():
            connection.execute(statement.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1))
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            _validate_schema(connection)
            _validate_calls(connection, VARIANT_NAMES)
            existing = connection.execute("SELECT identity,body FROM manifest").fetchall()
            if existing and (len(existing) != 1 or existing[0][0] != digest(manifest)
                             or existing[0][1] != canonical(manifest)):
                raise ValueError("experiment identity or budget changed; existing ledger cannot be reset")
            if not existing and connection.execute("SELECT 1 FROM calls LIMIT 1").fetchone():
                raise ValueError("experiment ledger calls have no manifest")
            connection.execute("INSERT OR IGNORE INTO manifest VALUES (?,?)", (digest(manifest), canonical(manifest)))
        owned = client is None
        client = client or DeepSeekClient()
        try:
            for name, config in configs:
                _evaluate_variant(connection, sample, name, config, client)
        finally:
            if owned:
                client.close()
        reports = []
        for row in connection.execute("SELECT * FROM calls ORDER BY ordinal"):
            response = None if row["response"] is None else json.loads(row["response"])
            entry = {"ordinal": row["ordinal"], "variant": row["variant"],
                     "request_sha256": digest(json.loads(row["request"])),
                     "outcome": row["outcome"] or "unknown_send_consumed", "latency_ms": row["latency_ms"],
                     "http_response_accepted": response is not None}
            if response is not None:
                entry.update(response_sha256=digest(response), validation=validation_result(sample["chunk"], response),
                             usage=normalize_usage(response))
            reports.append(entry)
    return {"schema": manifest["schema"], "experiment_id": digest(manifest), "source_call_id": sample["call_id"],
            "endpoint": endpoint, "model": model, "max_physical_calls": MAX_CALLS,
            "max_output_tokens_per_call": MAX_OUTPUT_TOKENS, "physical_calls": len(reports),
            "calls": reports, "provider_parameter_enforcement": "not_verified", "semantic_quality": "not_reviewed"}


def _evaluate_variant(connection, sample, name, config, client):
    original = request_body(sample["chunk"], config, system_prompt=sample["prepared"]["snapshot"]["system_prompt"])
    previous = None
    # Two persisted reservations per variant, four across the experiment. A
    # crash after reservation leaves an unknown send; it is never sent again.
    for generation in range(2):
        request, _ = recovery_request(original, previous, config)
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            _validate_schema(connection)
            _validate_calls(connection, VARIANT_NAMES)
            rows = connection.execute("SELECT * FROM calls WHERE variant=? ORDER BY ordinal", (name,)).fetchall()
            if len(rows) > generation:
                row = rows[generation]
                if row["response"] is None:
                    return
                response = json.loads(row["response"])
                ordinal = row["ordinal"]
                if json.loads(row["request"]) != request:
                    raise ValueError("persisted experiment request changed")
                reserved = False
            else:
                consumed = connection.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
                if consumed >= MAX_CALLS:
                    return
                ordinal = consumed + 1
                connection.execute("INSERT INTO calls(ordinal,variant,request) VALUES (?,?,?)",
                                   (ordinal, name, canonical(request)))
                response = None
                reserved = True
        if reserved:
            started = time.monotonic()
            try:
                response = client.complete(request, config)
            except DeepSeekError as error:
                # Preserve safe type only, no server body or credential-bearing
                # exception text. Reservation remains consumed on every error.
                with connection:
                    connection.execute("UPDATE calls SET outcome=?,latency_ms=? WHERE ordinal=?",
                        (type(error).__name__, int((time.monotonic() - started) * 1000), ordinal))
                return
            with connection:
                connection.execute("UPDATE calls SET response=?,outcome=?,latency_ms=? WHERE ordinal=?",
                    (canonical(response), "response_saved", int((time.monotonic() - started) * 1000), ordinal))
        validation = validation_result(sample["chunk"], response)
        if validation["accepted"] or not validation.get("diagnostic"):
            return
        previous = {"call_id": f"experiment:{ordinal}", "stored_request": {"request": request,
                    "recovery": {"regeneration": generation}, "validation_diagnostic": validation["diagnostic"]}}
