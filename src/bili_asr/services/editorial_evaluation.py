"""Read-only replay of exact saved editorial calls; never repairs provider text."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from typing import Any

from bili_asr.deepseek import (
    DeepSeekError,
    normalize_usage,
    parse_response,
    request_body,
)
from bili_asr.editorial import (
    EditorialConfig,
    RevisionValidationError,
    digest,
    validate_revision,
)
from bili_asr.editorial_recovery import diagnostic_for_error, recovery_request
from bili_asr.storage.editorial import EditorialRepository


def load_sample(database: Path, call_id: str) -> dict[str, Any]:
    """Load immutable evidence without opening a writable archive connection."""
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT m.call_id,m.input_id,m.chunk_id,m.request_json,m.response_json,i.prepared_json "
            "FROM editorial_model_calls m JOIN editorial_inputs i USING(input_id) WHERE m.call_id=?",
            (call_id,),
        ).fetchone()
    if row is None or row["response_json"] is None:
        raise ValueError("saved call with a response is required")
    prepared = json.loads(row["prepared_json"])
    if prepared["input_id"] != row["input_id"] or digest(prepared["snapshot"]) != row["input_id"]:
        raise ValueError("saved input identity mismatch")
    chunk = next((item for item in prepared["chunks"] if item["chunk_id"] == row["chunk_id"]), None)
    if chunk is None:
        raise ValueError("saved call chunk is absent from frozen input")
    stored = json.loads(row["request_json"])
    kind = stored.get("invocation_kind", "provider")
    if kind != "provider" or stored.get("replay_of_call_id") is not None:
        raise ValueError("select an original physical provider call")
    request = stored.get("request", stored)
    response = json.loads(row["response_json"])
    if response.get("id") == "local-precheck":
        raise ValueError("select an original physical provider call")
    fingerprint = stored.get("request_fingerprint")
    if fingerprint is not None and fingerprint != EditorialRepository.request_fingerprint(
            row["input_id"], row["chunk_id"], request):
        raise ValueError("stored request fingerprint mismatch")
    if json.loads(request["messages"][1]["content"]) != chunk:
        raise ValueError("saved request does not match the frozen chunk")
    if request["messages"][0]["content"] != prepared["snapshot"]["system_prompt"]:
        raise ValueError("saved system prompt does not match frozen input")
    config = EditorialConfig.from_snapshot(prepared["snapshot"]["config"])
    original = request_body(chunk, config, system_prompt=prepared["snapshot"]["system_prompt"])
    # Recovery calls legitimately add feedback messages, but cannot silently
    # change the frozen provider controls or original two-message prefix.
    controls = dict(request, messages=request["messages"][:2])
    if controls != original:
        raise ValueError("saved request controls do not match frozen config")
    return {"call_id": row["call_id"], "prepared": prepared, "chunk": chunk,
            "request": request, "response": response,
            "request_fingerprint_evidence": "verified" if fingerprint is not None else "unavailable_legacy"}


def validation_result(chunk: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    try:
        blocks = validate_revision(chunk, parse_response(response))
    except (DeepSeekError, RevisionValidationError) as error:
        # Provider messages and transcript prose never enter the public report.
        result = {"accepted": False, "error_type": type(error).__name__}
        diagnostic = diagnostic_for_error(error)
        if diagnostic is not None:
            result["diagnostic"] = diagnostic
        return result
    return {"accepted": True, "paragraphs": len(blocks)}


def replay_sample(sample: dict[str, Any]) -> dict[str, Any]:
    prepared, chunk = sample["prepared"], sample["chunk"]
    validation = validation_result(chunk, sample["response"])
    historic = EditorialConfig.from_snapshot(prepared["snapshot"]["config"])
    report = {"source_call_id": sample["call_id"], "source_input_id": prepared["input_id"],
              "source_chunk_id": chunk["chunk_id"], "source_request_sha256": digest(sample["request"]),
              "source_response_sha256": digest(sample["response"]),
              "source_request_policy": historic.request_policy,
              "request_fingerprint_evidence": sample["request_fingerprint_evidence"],
              "editable_segments": len(chunk["editable_segments"]),
              "validation": validation, "usage": normalize_usage(sample["response"]),
              "physical_calls": 0, "semantic_quality": "not_reviewed"}
    if validation.get("diagnostic"):
        # This is an explicitly identified new request preview, never a rewrite
        # of the historic input, prompt or provider response.
        config = replace(historic, request_policy="deepseek-v2", max_chunk_regenerations=1)
        original = request_body(chunk, config, system_prompt=prepared["snapshot"]["system_prompt"])
        request, recovery = recovery_request(original, {"call_id": sample["call_id"],
            "stored_request": {"request": sample["request"],
                               "validation_diagnostic": validation["diagnostic"]}}, config)
        report["feedback_preview"] = {"request_sha256": digest(request),
            "config_sha256": digest(config.to_dict()), "policy": recovery["policy"],
            "regeneration": recovery["regeneration"], "provider_called": False}
    return report
