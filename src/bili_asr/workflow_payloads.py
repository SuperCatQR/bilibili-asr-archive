"""Validate durable job descriptions before a worker begins side effects.

Unversioned rows are the existing v1 contract. Validation does not rewrite
their JSON, dedupe keys or frozen profile/input hashes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from bili_asr.workflow_models import JobKind, WorkflowJob


@dataclass(frozen=True)
class ValidatedPayload:
    kind: JobKind
    schema_version: int
    values: Mapping[str, Any]


def _positive_id(value: Any, name: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"workflow payload: {name} must be a positive integer")
    return value


def validate_payload(kind: JobKind, payload: Mapping[str, Any], *,
                     part_id: int | None, profile_id: int | None = None) -> ValidatedPayload:
    if not isinstance(payload, Mapping):
        raise ValueError("workflow payload must be a JSON object")
    version = payload.get("schema_version", 1)
    if type(version) is not int or version != 1:
        raise ValueError("unsupported workflow payload schema version")
    if kind in {JobKind.SUBTITLE, JobKind.AUDIO, JobKind.ASR, JobKind.PUBLISH}:
        if _positive_id(payload.get("video_part_id"), "video_part_id") != part_id:
            raise ValueError("workflow payload belongs to another video part")
    if kind is JobKind.ASR:
        if _positive_id(payload.get("profile_id"), "profile_id") != profile_id:
            raise ValueError("workflow payload belongs to another ASR profile")
        reference = payload.get("reference_transcript_id")
        if reference is not None:
            _positive_id(reference, "reference_transcript_id")
    elif kind is JobKind.PUBLISH:
        _positive_id(payload.get("transcript_id"), "transcript_id")
    elif kind is JobKind.PROOFREAD:
        _one_reference(payload, "input_id", "asr_job_id")
        if "repair_of_job_id" in payload:
            _text(payload["repair_of_job_id"], "repair_of_job_id")
            if "input_id" not in payload:
                raise ValueError("workflow repair requires an explicit frozen input")
        if "asr_job_id" in payload and not isinstance(payload.get("editorial_config"), Mapping):
            raise ValueError("workflow payload: automatic proofreading requires editorial_config")
    elif kind is JobKind.RENDER_DOCUMENT:
        _one_reference(payload, "revision_id", "proofread_job_id")
        _text(payload.get("template_version"), "template_version")
    return ValidatedPayload(kind, version, MappingProxyType(dict(payload)))


def _text(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"workflow payload: {name} must be non-empty text")


def _one_reference(payload: Mapping[str, Any], first: str, second: str) -> None:
    if (first in payload) == (second in payload):
        raise ValueError(f"workflow payload requires exactly one of {first} and {second}")
    name = first if first in payload else second
    _text(payload[name], name)


def decode_job_payload(job: WorkflowJob) -> ValidatedPayload:
    return validate_payload(job.kind, job.payload, part_id=job.video_part_id, profile_id=job.profile_id)
